"""Deterministic retrieval functions — the SQL/Mongo layer of the RAG.

Each function:
  • Takes user_id + query parameters.
  • Runs a tight, narrow query (no kitchen-sink dumps).
  • Returns a small structured payload (`Retrieval` dataclass).
  • Computes everything itself — the LLM never re-derives numbers.

If a retriever can't answer (no holdings / postgres down / etc.), it
returns a `Retrieval` with `ok=False` and a `reason`. The orchestrator
turns that into an honest "I don't have X" reply rather than letting
the LLM confabulate.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from deps import db

logger = logging.getLogger(__name__)


@dataclass
class Retrieval:
    """Tight structured payload for the LLM + frontend."""
    ok: bool
    reason: str = ""                 # populated when ok=False
    summary: str = ""                # one-sentence machine-readable summary
    rows: List[Dict[str, Any]] = field(default_factory=list)
    chart_spec: Optional[Dict[str, Any]] = None  # set by chart_specs.py
    extras: Dict[str, Any] = field(default_factory=dict)


# ── Holdings primitives ────────────────────────────────────────────────

async def _enriched_holdings(user_id: str) -> List[Dict[str, Any]]:
    """Fetch raw holdings + compute invested/profit/return per row,
    flagging cost-basis-known vs placeholder. Reused by ranking,
    concentration, and most other retrievers."""
    rows = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(500)
    out = []
    for h in rows:
        qty = float(h.get("quantity") or 0)
        bp = float(h.get("buy_price") or 0)
        cp = float(h.get("current_price") or 0)
        inv = qty * bp
        cur = qty * cp
        profit = cur - inv
        ret = (profit / inv * 100) if inv > 0 else 0.0
        prices_match = abs(bp - cp) < 0.005
        cost_basis_known = (bp > 0) and not (prices_match and not h.get("buy_date"))
        out.append({
            "name": h.get("name") or "Unknown",
            "type": (h.get("asset_type") or "").lower(),
            "sector": h.get("sector") or "Other",
            "qty": qty,
            "invested": inv,
            "current": cur,
            "profit": profit,
            "ret_pct": ret,
            "cost_basis_known": cost_basis_known,
        })
    return out


# ── Intent: ranking ────────────────────────────────────────────────────

async def top_n_by_metric(
    user_id: str,
    metric: str,           # "return" | "profit" | "loss" | "value"
    n: int = 5,
    asset_type: Optional[str] = None,  # "mutual_fund" | "equity" | None=both
) -> Retrieval:
    """Top N holdings ranked by a metric. Excludes placeholder cost-basis
    rows from anything return/profit/loss-based."""
    rows = await _enriched_holdings(user_id)
    if not rows:
        return Retrieval(ok=False, reason="no_holdings",
                         summary="user has no holdings recorded")
    if asset_type:
        rows = [r for r in rows if r["type"] == asset_type]
        if not rows:
            return Retrieval(ok=False, reason=f"no_{asset_type}_holdings",
                             summary=f"user holds no {asset_type}")

    # value rankings work on any holding — placeholder cost basis fine.
    if metric == "value":
        ranked = sorted(rows, key=lambda r: r["current"], reverse=True)[:n]
    else:
        ranked = [r for r in rows if r["cost_basis_known"]]
        if not ranked:
            return Retrieval(ok=False, reason="all_placeholder_cost_basis",
                             summary="all holdings have placeholder cost basis; profit/return not computable")
        if metric == "loss":
            ranked = sorted(ranked, key=lambda r: r["profit"])[:n]
            ranked = [r for r in ranked if r["profit"] < 0]  # only actual losers
        elif metric == "profit":
            ranked = sorted(ranked, key=lambda r: r["profit"], reverse=True)[:n]
        elif metric == "return":
            ranked = sorted(ranked, key=lambda r: r["ret_pct"], reverse=True)[:n]
        else:
            return Retrieval(ok=False, reason="bad_metric",
                             summary=f"unknown metric {metric!r}")

    if not ranked:
        return Retrieval(ok=False, reason="no_matching_rows",
                         summary=f"no holdings match metric={metric}")

    return Retrieval(
        ok=True,
        summary=f"top {len(ranked)} holdings by {metric}",
        rows=[{
            "rank": i + 1,
            "name": r["name"],
            "asset_type": r["type"],
            "sector": r["sector"],
            "current_value_rs": round(r["current"], 0),
            "profit_rs": round(r["profit"], 0),
            "return_pct": round(r["ret_pct"], 2),
        } for i, r in enumerate(ranked)],
        extras={"metric": metric, "n_requested": n, "asset_type_filter": asset_type},
    )


# ── Intent: concentration ──────────────────────────────────────────────

async def amc_concentration(user_id: str) -> Retrieval:
    """% of MF AUM by extracted AMC name. Highlights any AMC ≥15%."""
    from routes.chat import _extract_amc  # reuse the tested extractor
    rows = await _enriched_holdings(user_id)
    mf_rows = [r for r in rows if r["type"] in ("mutual_fund", "mf")]
    if not mf_rows:
        return Retrieval(ok=False, reason="no_mfs",
                         summary="user has no mutual funds")
    totals: Dict[str, float] = {}
    grand = 0.0
    for r in mf_rows:
        amc = _extract_amc(r["name"])
        if not amc:
            continue
        totals[amc] = totals.get(amc, 0.0) + r["current"]
        grand += r["current"]
    if grand <= 0:
        return Retrieval(ok=False, reason="zero_aum",
                         summary="MF AUM is zero")
    ranked = sorted(
        [{"label": amc, "value": round(v / grand * 100, 2),
          "amount_rs": round(v, 0)}
         for amc, v in totals.items()],
        key=lambda d: d["value"], reverse=True,
    )[:8]
    return Retrieval(
        ok=True,
        summary=f"{len(ranked)} AMCs across ₹{grand:,.0f} MF AUM",
        rows=ranked,
        extras={"total_aum_rs": round(grand, 0),
                "highlight_threshold_pct": 15.0},
    )


async def sector_concentration(user_id: str) -> Retrieval:
    """TRUE sector mix (IT, Pharma, Banking, Energy, FMCG…) using
    look-through data from `portfolio_intelligence.sector_exposure` —
    which decomposes every MF into its underlying stocks and aggregates
    by real sector. The naive bucket-by-holding.sector approach was
    showing fund categories (Mid Cap, Flexi Cap) instead of sectors;
    that's what users actually mean by 'sector' is IT vs Pharma vs
    Banking, not Mid Cap vs Small Cap.
    """
    try:
        from services import portfolio_intelligence as _pi
        m = await _pi.compute_portfolio_intelligence(user_id)
    except Exception as e:  # noqa: BLE001
        return Retrieval(ok=False, reason="intelligence_unavailable",
                         summary=f"sector look-through requires intelligence service: {e}")
    sector_exp = (m or {}).get("sector_exposure") or []
    if not sector_exp:
        return Retrieval(ok=False, reason="no_sector_data",
                         summary="no look-through sector data (Postgres / MF holdings catalog may be empty for this portfolio)")
    ranked = sorted(
        [{"label": s.get("sector") or "Other",
          "value": round(float(s.get("pct") or 0), 2),
          "amount_rs": round(float(s.get("rs") or 0), 0)}
         for s in sector_exp],
        key=lambda d: d["value"], reverse=True,
    )[:8]
    grand = sum(d["amount_rs"] for d in ranked)
    return Retrieval(
        ok=True,
        summary=f"{len(ranked)} sectors via stock-level look-through (₹{grand:,.0f})",
        rows=ranked,
        extras={"total_value_rs": grand, "source": "look_through"},
    )


async def category_mix(user_id: str) -> Retrieval:
    """% of MF AUM bucketed by SEBI/AMC fund category (Mid Cap, Small
    Cap, Flexi Cap, Value, Index, Balanced, etc.). This is what the
    `holding.sector` field actually stores for mutual funds — separate
    intent from real sector mix."""
    rows = await _enriched_holdings(user_id)
    mfs = [r for r in rows if r["type"] in ("mutual_fund", "mf", "etf")]
    if not mfs:
        return Retrieval(ok=False, reason="no_funds",
                         summary="user has no mutual funds or ETFs to bucket by category")
    totals: Dict[str, float] = {}
    grand = 0.0
    for r in mfs:
        cat = r["sector"] or "Uncategorised"
        totals[cat] = totals.get(cat, 0.0) + r["current"]
        grand += r["current"]
    if grand <= 0:
        return Retrieval(ok=False, reason="zero_value", summary="MF AUM is zero")
    ranked = sorted(
        [{"label": k, "value": round(v / grand * 100, 2),
          "amount_rs": round(v, 0)}
         for k, v in totals.items()],
        key=lambda d: d["value"], reverse=True,
    )[:8]
    return Retrieval(
        ok=True,
        summary=f"{len(ranked)} fund categories across ₹{grand:,.0f} MF/ETF AUM",
        rows=ranked,
        extras={"total_aum_rs": round(grand, 0)},
    )


async def company_concentration(user_id: str, n: int = 8) -> Retrieval:
    """Top N companies by ₹ exposure, look-through across every MF +
    direct equity. Pulls `top_stocks` from portfolio_intelligence which
    already does the heavy lifting (decomposes each MF into its
    underlying stocks, aggregates by company, ranks by ₹ exposure).
    Each row also carries the sector tag and how many funds the user
    is exposed to that company through.
    """
    try:
        from services import portfolio_intelligence as _pi
        m = await _pi.compute_portfolio_intelligence(user_id)
    except Exception as e:  # noqa: BLE001
        return Retrieval(ok=False, reason="intelligence_unavailable",
                         summary=f"company exposure requires intelligence service: {e}")
    top_stocks = (m or {}).get("top_stocks") or []
    if not top_stocks:
        return Retrieval(ok=False, reason="no_company_data",
                         summary=("no look-through company data — Postgres / "
                                  "MF holdings catalog may be empty for this portfolio"))
    ranked: List[Dict[str, Any]] = []
    for s in top_stocks[:n]:
        ranked.append({
            "label": s.get("name") or "Unknown",
            "value": round(float(s.get("exposure_pct") or 0), 2),
            "amount_rs": round(float(s.get("exposure_rs") or 0), 0),
            "sector": s.get("sector") or "Other",
            "fund_count": int(s.get("fund_count") or 0),
        })
    grand = sum(r["amount_rs"] for r in ranked)
    return Retrieval(
        ok=True,
        summary=f"top {len(ranked)} companies by ₹ exposure (look-through, ₹{grand:,.0f} aggregated)",
        rows=ranked,
        extras={
            "total_top_n_rs": grand,
            "source": "look_through",
            "highlight_threshold_pct": 5.0,  # any single-company > 5% is notable
        },
    )


async def invest_fresh_money(user_id: str, amount_rs: Optional[float] = None) -> Retrieval:
    """Where should the user deploy fresh money to improve diversification?

    Decision Engine driven — the answer is whichever bucket is most
    UNDERWEIGHT vs target. Rejects the naive "fewest holdings" heuristic
    that fooled the LLM into recommending more gold to a user already
    gold-overweight by 17pp.

    If `amount_rs` is provided, rows include a per-bucket allocation
    (proportional to underweight gap). Otherwise just the priority
    ranking + scaled-pct suggestion.
    """
    try:
        from services.deviation_engine import compute_deviation
        dev = await compute_deviation(user_id)
    except Exception as e:  # noqa: BLE001
        return Retrieval(ok=False, reason="deviation_engine_failed",
                         summary=f"deviation engine error: {e}")
    if not dev.rows:
        return Retrieval(ok=False, reason="no_holdings_for_drift",
                         summary="no holdings — cannot recommend a deployment bucket")

    # Underweight buckets only — those are eligible for fresh capital.
    underweights = [r for r in dev.rows
                    if r.direction == "underweight" and r.deviation_pp < 0]
    if not underweights:
        return Retrieval(
            ok=True,  # not a failure — portfolio is already balanced
            reason="balanced",
            summary=("portfolio is balanced or overweight everywhere — "
                     "no bucket is underweight enough to recommend fresh capital."),
            rows=[],
            extras={"target": dev.extras.get("target"),
                    "current": dev.extras.get("current")},
        )

    # Sort by absolute deviation (most underweight first). Cash is
    # untracked — exclude unless it's the only underweight bucket.
    underweights.sort(key=lambda r: r.deviation_pp)  # most negative = most underweight
    tracked = [r for r in underweights if r.direction != "untracked"]
    if tracked:
        underweights = tracked

    # Per-bucket fresh-money allocation. Proportional to the underweight
    # gap so the most-off bucket gets the largest slice.
    total_gap = sum(abs(r.deviation_pp) for r in underweights)
    rows: List[Dict[str, Any]] = []
    for r in underweights:
        share = abs(r.deviation_pp) / total_gap if total_gap > 0 else 1.0 / len(underweights)
        suggested_rs = round(float(amount_rs) * share, 0) if amount_rs else None
        # Friendly fund-class hint per bucket — same placeholders the
        # action generator uses, so chat + plan board stay consistent.
        suggestion = {
            "equity": "Diversified large/flexi-cap fund",
            "debt": "Investment-grade corporate bond fund",
            "gold": "Sovereign Gold Bond / Gold ETF",
        }.get(r.asset.lower(), f"{r.asset} allocation top-up")
        rows.append({
            "bucket": r.asset,
            "current_pct": r.current_pct,
            "target_pct": r.target_pct,
            "deviation_pp": r.deviation_pp,
            "share_of_fresh_pct": round(share * 100, 1),
            "suggested_amount_rs": suggested_rs,
            "fund_class": suggestion,
        })

    headline = rows[0]
    summary = (
        f"most underweight: {headline['bucket']} at {headline['current_pct']:.0f}% "
        f"vs target {headline['target_pct']:.0f}% ({headline['deviation_pp']:+.1f}pp)"
    )
    return Retrieval(
        ok=True,
        summary=summary,
        rows=rows,
        extras={
            "amount_rs": amount_rs,
            "target": dev.extras.get("target"),
            "current": dev.extras.get("current"),
            "risk_category": dev.risk_category,
        },
    )


async def rebalance_suggestions(user_id: str, n: int = 8) -> Retrieval:
    """Decision-Engine generated rebalance actions — synthesised from
    asset-class drift (Rule 6) + sector cap (Rule 7) + category cap
    (Rule 8). Distinct from `active_plan_actions` which reads existing
    saved plans; this one proposes fresh suggestions on demand."""
    try:
        from services.decision_engine_actions import generate_actions
        actions = await generate_actions(user_id)
    except Exception as e:  # noqa: BLE001
        return Retrieval(ok=False, reason="action_generator_failed",
                         summary=f"action generator error: {e}")
    if not actions:
        return Retrieval(ok=False, reason="no_drift_or_caps_breached",
                         summary="portfolio is within target / cap thresholds — no rebalance needed")
    return Retrieval(
        ok=True,
        summary=f"{len(actions)} rebalance suggestions across drift / sector / category rules",
        rows=[{
            "rank": i + 1,
            **a.to_dict(),
        } for i, a in enumerate(actions[:n])],
        extras={"rules_fired": sorted({a.rule for a in actions if a.rule})},
    )


async def allocation_drift(user_id: str) -> Retrieval:
    """Current vs target asset-class allocation, with per-bucket
    deviation and trigger flag. Powers the "are my allocations on
    target?" / "rebalance suggestions" chat intents."""
    try:
        from services.deviation_engine import compute_deviation
        result = await compute_deviation(user_id)
    except Exception as e:  # noqa: BLE001
        return Retrieval(ok=False, reason="deviation_engine_failed",
                         summary=f"deviation engine error: {e}")
    if not result.rows:
        return Retrieval(ok=False, reason=result.summary.replace(" ", "_") or "no_data",
                         summary=result.summary)
    return Retrieval(
        ok=True,
        summary=(
            f"target ({result.risk_category}, conf {result.target_confidence:.0f}/100): "
            + " · ".join(f"{r.asset} cur {r.current_pct:.0f}% / tgt {r.target_pct:.0f}% ({r.deviation_pp:+.1f}pp {r.trigger})"
                         for r in result.rows)
        ),
        rows=[{
            "asset": r.asset.title(),
            "current_pct": r.current_pct,
            "target_pct": r.target_pct,
            "deviation_pp": r.deviation_pp,
            "direction": r.direction,
            "trigger": r.trigger,
            "note": r.note,
        } for r in result.rows],
        extras={
            "needs_rebalance": result.needs_rebalance,
            "risk_category": result.risk_category,
            "target_confidence": result.target_confidence,
            "total_value_rs": result.extras.get("total_value_rs"),
            "thresholds_pp": result.extras.get("thresholds_pp"),
        },
    )


async def asset_class_breakdown(user_id: str) -> Retrieval:
    """% of TOTAL portfolio value by asset class — Equity, Mutual Fund,
    ETF, Gold, etc. Answers 'how am I split across asset classes?'."""
    rows = await _enriched_holdings(user_id)
    if not rows:
        return Retrieval(ok=False, reason="no_holdings",
                         summary="user has no holdings recorded")
    totals: Dict[str, float] = {}
    grand = 0.0
    type_label = {
        "equity": "Equity (direct stocks)",
        "mutual_fund": "Mutual Funds",
        "mf": "Mutual Funds",
        "etf": "ETFs",
        "gold": "Gold (incl. SGB)",
        "debt": "Debt",
        "bond": "Debt",
    }
    for r in rows:
        label = type_label.get(r["type"], (r["type"] or "Other").title())
        totals[label] = totals.get(label, 0.0) + r["current"]
        grand += r["current"]
    if grand <= 0:
        return Retrieval(ok=False, reason="zero_value", summary="portfolio value is zero")
    ranked = sorted(
        [{"label": k, "value": round(v / grand * 100, 2),
          "amount_rs": round(v, 0)}
         for k, v in totals.items()],
        key=lambda d: d["value"], reverse=True,
    )
    return Retrieval(
        ok=True,
        summary=f"{len(ranked)} asset classes across ₹{grand:,.0f}",
        rows=ranked,
        extras={"total_value_rs": round(grand, 0)},
    )


# ── Intent: overlap (uses portfolio_intelligence cache) ────────────────

async def top_overlap_pairs(user_id: str, n: int = 5) -> Retrieval:
    try:
        from services import portfolio_intelligence as _pi
        m = await _pi.compute_portfolio_intelligence(user_id)
    except Exception as e:  # noqa: BLE001
        return Retrieval(ok=False, reason="intelligence_unavailable",
                         summary=f"intelligence service down: {e}")
    pairs = (m or {}).get("pairwise_overlap") or []
    if not pairs:
        return Retrieval(ok=False, reason="no_overlap_data",
                         summary="no overlap pairs computed (postgres / catalog may be stale)")
    return Retrieval(
        ok=True,
        summary=f"top {min(n, len(pairs))} overlapping pairs",
        rows=[{
            "rank": i + 1,
            "fund_a": p.get("a_name"),
            "fund_b": p.get("b_name"),
            "overlap_pct": round(float(p.get("overlap_pct") or 0), 1),
            "shared_count": int(p.get("shared_count") or 0),
            "top_shared": [
                (s.get("key") or "").replace("-", " ").title()
                for s in (p.get("top_shared") or [])[:3]
            ],
        } for i, p in enumerate(pairs[:n])],
    )


# ── Intent: goals (PG-backed) ──────────────────────────────────────────

async def goals_status(user_id: str) -> Retrieval:
    try:
        from services import pg_client as _pg
        pool = await _pg.get_pool()
        if pool is None:
            return Retrieval(ok=False, reason="pg_unavailable",
                             summary="goals require Postgres which is unavailable")
        import uuid as _uuid
        try:
            uid = _uuid.UUID(user_id) if isinstance(user_id, str) else user_id
        except Exception:  # noqa: BLE001
            uid = _uuid.uuid5(_uuid.NAMESPACE_DNS, f"nivesh:user:{user_id}")
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT goal_id, goal_type, goal_name, target_amount_rs, "
                "horizon_years, current_corpus_rs, monthly_sip_rs, "
                "on_track_pct, priority, status "
                "FROM user_goals WHERE user_id = $1 "
                "AND COALESCE(status,'') <> 'archived' "
                "ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END",
                uid,
            )
    except Exception as e:  # noqa: BLE001
        return Retrieval(ok=False, reason="goals_query_failed",
                         summary=f"goals query failed: {e}")
    if not rows:
        return Retrieval(ok=False, reason="no_goals",
                         summary="user has no goals recorded")
    return Retrieval(
        ok=True,
        summary=f"{len(rows)} active goals",
        rows=[{
            "name": r["goal_name"],
            "type": r["goal_type"],
            "priority": r["priority"],
            "target_rs": round(float(r["target_amount_rs"] or 0), 0),
            "horizon_years": float(r["horizon_years"] or 0),
            "corpus_rs": round(float(r["current_corpus_rs"] or 0), 0),
            "plan_sip_rs": round(float(r["monthly_sip_rs"] or 0), 0),
            "on_track_pct": round(float(r["on_track_pct"] or 0), 1),
        } for r in rows],
    )


# ── Intent: health ─────────────────────────────────────────────────────

async def health_scorecard(user_id: str) -> Retrieval:
    try:
        from services import portfolio_health as _ph
        hr = await _ph.build_portfolio_health(user_id)
    except Exception as e:  # noqa: BLE001
        return Retrieval(ok=False, reason="health_unavailable",
                         summary=f"health service failed: {e}")
    if not hr or hr.health_score is None:
        return Retrieval(ok=False, reason="no_health",
                         summary="no health score (no portfolio yet)")
    summary_text = (hr.summary or "").lower()
    if hr.health_score == 0 and "no holdings" in summary_text:
        return Retrieval(ok=False, reason="empty_portfolio",
                         summary="portfolio is empty — health not meaningful")
    return Retrieval(
        ok=True,
        summary=f"health {hr.health_score:.0f}/100 (grade {hr.grade})",
        rows=[{
            "component": c.name,
            "score": round(c.score, 1),
            "weight": round(c.weight, 2),
            "low_confidence": c.low_confidence,
        } for c in (hr.components or {}).values()],
        extras={
            "health_score": round(hr.health_score, 1),
            "grade": hr.grade,
            "low_confidence": hr.low_confidence,
            "summary_text": hr.summary or "",
            "top_drivers": [
                {"label": d.get("label") or d.get("title", ""),
                 "detail": (d.get("detail") or d.get("note") or "")[:200]}
                for d in (hr.risk_drivers or [])[:3]
            ],
        },
    )


# ── Intent: active plan ────────────────────────────────────────────────

async def active_plan_actions(user_id: str, n: int = 5) -> Retrieval:
    plan = await db.action_plans.find_one(
        {"user_id": user_id, "status": {"$ne": "archived"}},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    if not plan or not plan.get("actions"):
        return Retrieval(ok=False, reason="no_active_plan",
                         summary="no active action plan")
    actions = [a for a in plan["actions"]
               if (a.get("status") or "").upper() not in ("COMPLETED", "SKIPPED")]
    if not actions:
        return Retrieval(ok=False, reason="all_actions_done",
                         summary="all plan actions are completed/skipped")
    tti = plan.get("total_tax_impact") or plan.get("tax_impact") or {}
    metrics_before = plan.get("metrics_before") or plan.get("before_metrics") or {}
    metrics_after = plan.get("metrics_after") or plan.get("after_metrics") or {}

    # Build a compact "before → after" string for the headline metrics
    # the dashboard surfaces: overlap, AMC concentration, debt allocation.
    def _metric_pair(mb: Dict, ma: Dict, key: str, fmt: str = "{:.0f}%") -> Optional[str]:
        b = mb.get(key); a = ma.get(key)
        if b is None and a is None:
            return None
        try:
            return f"{key}: {fmt.format(float(b)) if b is not None else '?'} → {fmt.format(float(a)) if a is not None else '?'}"
        except Exception:  # noqa: BLE001
            return None

    metric_lines = []
    for k in ("overlap_pct", "top_amc_pct", "debt_pct"):
        line = _metric_pair(metrics_before, metrics_after, k)
        if line:
            metric_lines.append(line)

    return Retrieval(
        ok=True,
        summary=(
            f"{len(actions)} pending actions in active plan"
            + (" · " + " · ".join(metric_lines) if metric_lines else "")
        ),
        rows=[{
            "action_type": a.get("type") or a.get("action_type"),
            "asset_name": a.get("asset_name"),
            "amount_rs": round(float(a.get("amount") or 0), 0),
            "reason_codes": a.get("reason_codes") or [],
            "reason_text": (a.get("reason_text") or "")[:240],
            "tax_impact_rs": round(float(
                (a.get("tax_impact") or {}).get("total_tax")
                or (a.get("tax_impact") or {}).get("total_tax_liability") or 0
            ), 0),
        } for a in actions[:n]],
        extras={
            "plan_id": plan.get("plan_id"),
            "plan_status": plan.get("status"),
            "total_tax_liability_rs": round(float(
                tti.get("total_tax_liability") or tti.get("total_tax") or 0
            ), 0),
            "metrics_before": {k: metrics_before.get(k) for k in
                               ("overlap_pct", "top_amc_pct", "debt_pct")
                               if metrics_before.get(k) is not None},
            "metrics_after": {k: metrics_after.get(k) for k in
                              ("overlap_pct", "top_amc_pct", "debt_pct")
                              if metrics_after.get(k) is not None},
        },
    )


# ── Intent: lightweight portfolio summary (for `generic` intent) ───────

async def portfolio_summary(user_id: str) -> Retrieval:
    rows = await _enriched_holdings(user_id)
    if not rows:
        return Retrieval(ok=False, reason="no_holdings",
                         summary="user has no holdings recorded")
    known = [r for r in rows if r["cost_basis_known"]]
    total_inv = sum(r["invested"] for r in known)
    total_cur = sum(r["current"] for r in known)
    total_profit = total_cur - total_inv
    total_ret = (total_profit / total_inv * 100) if total_inv > 0 else 0.0
    by_type: Dict[str, Dict[str, float]] = {}
    for r in rows:
        b = by_type.setdefault(r["type"] or "other", {"count": 0, "value": 0.0})
        b["count"] += 1
        b["value"] += r["current"]
    return Retrieval(
        ok=True,
        summary=f"{len(rows)} holdings · ₹{total_cur:,.0f} current · {total_ret:+.1f}% return",
        rows=[{"type": k, "count": int(v["count"]),
               "current_value_rs": round(v["value"], 0)}
              for k, v in by_type.items()],
        extras={
            "total_holdings": len(rows),
            "with_known_cost_basis": len(known),
            "total_invested_rs": round(total_inv, 0),
            "total_current_rs": round(total_cur, 0),
            "total_profit_rs": round(total_profit, 0),
            "total_return_pct": round(total_ret, 2),
        },
    )
