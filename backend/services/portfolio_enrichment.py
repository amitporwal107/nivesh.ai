"""Portfolio Enrichment Service — joins holdings with V3 scores + action
badges + portfolio alerts. Used by the new Actionable Portfolio page.

Returns a per-holding row with:
  - core (name, qty, cmp, value, pnl, pnl_pct, sector, isin)
  - scores (quality, health, exit, add, composite)
  - action (EXIT/SWITCH/ADD/HOLD/REVIEW) with rationale
  - replacement suggestion for SWITCH actions
  - switch_score breakdown

Action badge mapping (user-approved Feb 2026):
  🔴 EXIT   : exit_score ≥ 70 OR recommendation == "EXIT"
  🔁 SWITCH : Regular-plan MF OR pairwise overlap > 40% OR rec == "SWITCH"
  🟢 ADD    : add_score ≥ 70 AND quality_score ≥ 65
  🟡 HOLD   : default
  ⚠️ REVIEW : insufficient data / low confidence
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── XIRR (Newton-Raphson) ──────────────────────────────────────────────
def _xnpv(rate: float, flows: List[Tuple[date, float]]) -> float:
    if not flows:
        return 0.0
    t0 = flows[0][0]
    return sum(cf / ((1 + rate) ** ((d - t0).days / 365.0)) for d, cf in flows)


def xirr(flows: List[Tuple[date, float]], guess: float = 0.1) -> Optional[float]:
    """Return annualised IRR (decimal). Requires at least one negative and
    one positive cash flow. Returns None if solver fails to converge."""
    if len(flows) < 2:
        return None
    if not any(cf < 0 for _, cf in flows) or not any(cf > 0 for _, cf in flows):
        return None
    rate = guess
    for _ in range(60):
        try:
            npv = _xnpv(rate, flows)
            # Numerical derivative
            d_rate = 1e-4
            npv_d = _xnpv(rate + d_rate, flows)
            slope = (npv_d - npv) / d_rate
            if abs(slope) < 1e-12:
                return None
            rate_next = rate - npv / slope
            if abs(rate_next - rate) < 1e-6:
                return rate_next
            rate = rate_next
            if rate < -0.9999:
                rate = -0.9999
        except (ValueError, ZeroDivisionError, OverflowError):
            return None
    return None


# ── True money-weighted portfolio XIRR (from the dated transaction ledger) ──
_LEDGER_BUY_TYPES = ("PURCHASE", "SIP_PURCHASE", "BUY")
_LEDGER_SELL_KEYS = ("REDEMPTION", "REDEEM", "SELL", "SWITCH OUT", "SWITCH-OUT", "SWITCHOUT")
_LEDGER_SKIP_KEYS = ("REVERSAL", "PLEDGE", "STT", "STAMP", "TAX")  # fees / non-cashflow


async def portfolio_xirr_from_ledger(
    user_id: str,
    current_value: float,
    cost_basis: Optional[float] = None,
) -> Dict[str, Any]:
    """Money-weighted portfolio XIRR from the dated `cas_transactions` ledger.

    Pools EVERY transaction into a single cashflow series — purchases negative,
    redemptions/sells positive, on their actual dates — plus today's total
    market value as the final positive flow, then solves ONE IRR. This is the
    textbook money-weighted return; unlike averaging per-holding *annualised*
    rates (which explodes for short-horizon holdings), it stays sane because a
    small recent buy contributes a small cashflow, not an outsized rate.

    Returns {xirr_pct, xirr_raw_pct, reliable, coverage_pct, n_txn, source}.
    `xirr_pct` is None (reliable=False) when the ledger can't be trusted —
    too few transactions, or the buys cover well under the current cost basis
    (i.e. positions predate the statement / lack opening balances). The caller
    should then fall back to the absolute return rather than show a number we
    know is incomplete.
    """
    try:
        from deps import db
    except Exception:  # noqa: BLE001
        return {"xirr_pct": None, "reliable": False, "coverage_pct": None, "n_txn": 0, "source": "no_db"}

    flows: List[Tuple[date, float]] = []
    buy_total = 0.0
    sell_total = 0.0
    n_txn = 0
    try:
        cursor = db.cas_transactions.find(
            {"user_id": user_id},
            {"_id": 0, "date": 1, "type": 1, "transaction_type": 1,
             "description": 1, "raw_description": 1, "amount": 1, "amount_inr": 1},
        )
        async for t in cursor:
            amt = 0.0
            try:
                amt = float(t.get("amount") or t.get("amount_inr") or 0)
            except (TypeError, ValueError):
                continue
            if amt <= 0:
                continue
            d = (t.get("date") or "")[:10]
            if not d:
                continue
            try:
                dt = datetime.strptime(d, "%Y-%m-%d").date()
            except ValueError:
                continue
            ttype = (t.get("type") or t.get("transaction_type") or "").upper()
            desc = (t.get("description") or t.get("raw_description") or "").upper()
            blob = f"{ttype} {desc}"
            if any(k in blob for k in _LEDGER_SKIP_KEYS):
                continue
            if any(k in blob for k in _LEDGER_SELL_KEYS):
                flows.append((dt, amt)); sell_total += amt; n_txn += 1
            elif ttype in _LEDGER_BUY_TYPES or any(k in blob for k in ("PURCHASE", "SIP", "BUY", "ALLOTMENT")):
                flows.append((dt, -amt)); buy_total += amt; n_txn += 1
            # unknown types are ignored
    except Exception as exc:  # noqa: BLE001
        logger.warning("portfolio_xirr_from_ledger: ledger read failed for %s: %s", user_id, exc)
        return {"xirr_pct": None, "reliable": False, "coverage_pct": None, "n_txn": 0, "source": "ledger_error"}

    if n_txn < 2 or buy_total <= 0 or current_value <= 0:
        return {"xirr_pct": None, "reliable": False, "coverage_pct": None,
                "n_txn": n_txn, "source": "insufficient_ledger"}

    flows.append((datetime.now(timezone.utc).date(), float(current_value)))
    r = xirr(flows)
    xirr_pct = round(r * 100.0, 2) if r is not None else None

    # Reliability: the ledger's net invested should explain most of the current
    # cost basis. If it covers well under it, the statement is missing opening
    # balances → the IRR overstates and we shouldn't report it.
    net_invested = buy_total - sell_total
    coverage = (net_invested / cost_basis) if (cost_basis and cost_basis > 0) else None
    reliable = (
        xirr_pct is not None
        and -60.0 <= xirr_pct <= 120.0
        and (coverage is None or coverage >= 0.6)
    )
    return {
        "xirr_pct": xirr_pct if reliable else None,
        "xirr_raw_pct": xirr_pct,
        "reliable": reliable,
        "coverage_pct": round(coverage * 100.0, 1) if coverage is not None else None,
        "n_txn": n_txn,
        "source": "ledger",
    }


def _holding_xirr(buy_date: Optional[str], buy_price: float,
                   current_price: float, qty: float) -> Optional[float]:
    if not buy_date or buy_price <= 0 or qty <= 0:
        return None
    try:
        bd = datetime.fromisoformat(buy_date.replace("Z", "+00:00")).date() \
            if "T" in buy_date else datetime.strptime(buy_date[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    today = datetime.now(timezone.utc).date()
    if bd >= today:
        return None
    flows = [(bd, -buy_price * qty), (today, current_price * qty)]
    r = xirr(flows)
    return r * 100.0 if r is not None else None


# ── Action badge derivation ────────────────────────────────────────────
REVIEW = {"action": "REVIEW", "tone": "slate",   "emoji": "⚠️"}
EXIT   = {"action": "EXIT",   "tone": "rose",    "emoji": "🔴"}
SWITCH = {"action": "SWITCH", "tone": "amber",   "emoji": "🔁"}
ADD    = {"action": "ADD",    "tone": "emerald", "emoji": "🟢"}
HOLD   = {"action": "HOLD",   "tone": "slate",   "emoji": "🟡"}


def _hold_sub_action(
    q: float, h: float, weight_pct: Optional[float] = None,
) -> Dict[str, str]:
    """Intelligent HOLD sub-label so the UI isn't a sea of grey 'HOLD' pills.
    Returns {sub_action, sub_reason}."""
    # Oversized single position → nudge to rebalance
    if weight_pct is not None and weight_pct >= 10:
        return {
            "sub_action": "Rebalance",
            "sub_reason": f"Single position is {weight_pct:.0f}% of portfolio — trim to <10%.",
        }
    if q >= 65 and h >= 60:
        return {
            "sub_action": "Keep",
            "sub_reason": f"Solid Quality {q:.0f} · Health {h:.0f} — no action needed.",
        }
    if q >= 50:
        return {
            "sub_action": "Watch",
            "sub_reason": f"Quality {q:.0f} · Health {h:.0f} — monitor next quarter.",
        }
    return {
        "sub_action": "Review",
        "sub_reason": f"Quality {q:.0f} · Health {h:.0f} — weak fundamentals; revisit.",
    }


def derive_action_badge(
    scores: Optional[Dict[str, Any]],
    recommendation: Optional[str],
    *,
    is_regular_plan: bool = False,
    high_overlap: bool = False,
    weight_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """Badge per user-approved logic. Returns {action, tone, emoji, reason,
    sub_action?, sub_reason?}."""
    if not scores or scores.get("quality") is None:
        return {**REVIEW, "reason": "Fundamentals not yet scored — refresh to enrich."}

    q = scores.get("quality") or 0
    h = scores.get("health") or 0
    e = scores.get("exit") or 0
    a = scores.get("add") or 0
    rec = (recommendation or "").upper()

    if e >= 70 or rec == "EXIT":
        return {**EXIT,
                "reason": f"Exit score {e:.0f} — overvaluation / earnings stress."}
    if rec == "SWITCH" or is_regular_plan or high_overlap:
        parts = []
        if is_regular_plan:
            parts.append("Regular plan (high expense)")
        if high_overlap:
            parts.append("High portfolio overlap")
        if rec == "SWITCH":
            parts.append("Engine flagged switch")
        # Differentiate the THREE switch flavours so the UI doesn't render
        # them all as the same scary "SWITCH" pill:
        #   • "To Direct" — Regular plan with healthy scores; pure cost
        #     optimisation, fund itself is fine. Teal/positive tone.
        #   • "Reduce" — diversification fix (high overlap); amber.
        #   • "To Peer" — engine recommends a different fund; amber/red.
        is_healthy = q >= 60 and h >= 60 and e < 60
        if is_regular_plan and is_healthy and not high_overlap and rec != "SWITCH":
            sub = "To Direct"
        elif rec == "SWITCH" and not is_regular_plan:
            sub = "To Peer"
        elif high_overlap:
            sub = "Reduce"
        else:
            # Regular + (overlap or unhealthy) — main concern is the fund itself
            sub = "To Peer" if (rec == "SWITCH" or not is_healthy) else "To Direct"
        return {
            **SWITCH,
            "reason": " · ".join(parts) or "Switch candidate.",
            "sub_action": sub,
            "sub_reason": " · ".join(parts) or "Switch candidate.",
        }
    if a >= 70 and q >= 65:
        return {**ADD,
                "reason": f"Add {a:.0f} · Quality {q:.0f} — fits portfolio gap."}
    sub = _hold_sub_action(q, h, weight_pct)
    return {**HOLD,
            "reason": sub["sub_reason"],
            "sub_action": sub["sub_action"],
            "sub_reason": sub["sub_reason"]}


def composite_score(scores: Optional[Dict[str, Any]]) -> Optional[float]:
    """Weighted composite: 40% Quality + 30% Health + 20% (100-Exit) + 10% Add.
    Returns 0-100 or None when data missing."""
    if not scores or scores.get("quality") is None:
        return None
    q = scores.get("quality") or 0
    h = scores.get("health") or 50
    e = 100 - (scores.get("exit") or 50)
    a = scores.get("add") or 50
    return round(0.4 * q + 0.3 * h + 0.2 * e + 0.1 * a, 1)


# ── Switch replacement suggester ────────────────────────────────────────
def suggest_replacement(
    holding_name: str, category: Optional[str], v3_funds: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Pick the top same-category fund with the highest ADD score that isn't
    the same fund. Returns top-3 sorted by add_score desc."""
    if not v3_funds:
        return None
    same_cat = [
        f for f in v3_funds
        if (f.get("category") == category if category else True)
        and (f.get("name") or "").strip().lower() != (holding_name or "").strip().lower()
    ]
    ranked = sorted(
        same_cat,
        key=lambda f: (f.get("scores") or {}).get("add") or 0,
        reverse=True,
    )[:3]
    if not ranked:
        return None
    return {"candidates": ranked, "category": category}


def compute_switch_score(
    old: Dict[str, Any], new: Dict[str, Any],
    *, exit_load_pct: float = 1.0,
) -> Dict[str, Any]:
    """Compute the 5-component Switch Score per user spec:
      +30%  ΔQuality
      +20%  Cost efficiency gain (expense ratio Δ)
      -25%  Tax impact (STCG/LTCG)
      -15%  Exit load impact
      +10%  Portfolio fit (placeholder = delta add score)"""
    old_s = old.get("scores") or {}
    new_s = new.get("scores") or {}
    delta_quality = (new_s.get("quality") or 0) - (old_s.get("quality") or 0)
    delta_add = (new_s.get("add") or 0) - (old_s.get("add") or 0)
    old_er = (old.get("expense_ratio") or 1.0)
    new_er = (new.get("expense_ratio") or 0.5)
    cost_gain = max(0, old_er - new_er) / max(0.01, old_er) * 100.0
    tax_impact_score = 100 - min(100, (old.get("tax_impact_pct") or 0) * 5)
    exit_load_score = 100 - min(100, exit_load_pct * 30)
    portfolio_fit = 50 + delta_add  # rough
    score = (
        0.30 * delta_quality + 0.20 * cost_gain
        + 0.25 * tax_impact_score + 0.15 * exit_load_score
        + 0.10 * portfolio_fit
    )
    return {
        "switch_score": round(max(0, min(100, score)), 1),
        "delta_quality": round(delta_quality, 1),
        "cost_gain_pct": round(cost_gain, 1),
        "expense_ratio_old": old_er,
        "expense_ratio_new": new_er,
        "tax_impact_pct": old.get("tax_impact_pct"),
        "exit_load_pct": exit_load_pct,
    }


# ── Portfolio-level alerts ─────────────────────────────────────────────
def derive_portfolio_alerts(
    health_payload: Optional[Dict[str, Any]],
    alloc: Dict[str, float],
    ideal: Dict[str, float],
    risk_profile_user: str,
    risk_profile_portfolio: str,
    unscored_equity_count: int = 0,
    total_equity_count: int = 0,
    unscored_equity_holdings: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Build a 0-N list of actionable top-of-page alerts."""
    alerts: List[Dict[str, Any]] = []
    # Allocation drift
    # `bucket` and `direction` are surfaced to the frontend so CTAs can route
    # to the right action (suggest funds for the missing bucket, or filter the
    # table to the overexposed bucket) instead of the prior generic "Show
    # biggest positions" which sorted the whole table by value.
    for bucket, ideal_pct in ideal.items():
        actual = alloc.get(bucket, 0.0)
        drift = actual - ideal_pct
        if drift >= 15:
            alerts.append({
                "severity": "warning",
                "title": f"Overexposed to {bucket.capitalize()}",
                "detail": f"{actual:.0f}% in {bucket} vs recommended {ideal_pct:.0f}%.",
                "component": "allocation",
                "bucket": bucket,
                "direction": "overweight",
                "actual_pct": round(actual, 1),
                "recommended_pct": round(ideal_pct, 1),
            })
        elif drift <= -15:
            alerts.append({
                "severity": "warning",
                "title": f"Underweight {bucket.capitalize()}",
                "detail": f"{actual:.0f}% vs recommended {ideal_pct:.0f}% — consider rebalancing.",
                "component": "allocation",
                "bucket": bucket,
                "direction": "underweight",
                "actual_pct": round(actual, 1),
                "recommended_pct": round(ideal_pct, 1),
            })
    # Risk misalignment
    order = {"conservative": 1, "moderate": 2, "aggressive": 3}
    if (risk_profile_user in order and risk_profile_portfolio in order
            and order[risk_profile_portfolio] - order[risk_profile_user] >= 1):
        alerts.append({
            "severity": "danger",
            "title": "Risk profile mismatch",
            "detail": f"Profile: {risk_profile_user.capitalize()} · Portfolio behaving: {risk_profile_portfolio.capitalize()}.",
            "component": "risk_alignment",
        })
    # Top risk drivers from Portfolio Health
    # Forward action_hint so per-driver CTAs (e.g. allocation drift → Plan Board)
    # don't get collapsed to the generic component-based CTA on the frontend.
    for rd in (health_payload or {}).get("risk_drivers", [])[:3]:
        alert = {
            "severity": "info",
            "title": rd.get("label") or "Risk driver",
            "detail": rd.get("detail") or "",
            "component": rd.get("component") or "health",
        }
        if rd.get("action_hint"):
            alert["action_hint"] = rd["action_hint"]
        alerts.append(alert)
    # Unscored fundamentals
    if unscored_equity_count > 0 and total_equity_count > 0:
        alert = {
            "severity": "info",
            "title": f"{unscored_equity_count} stocks not yet scored",
            "detail": (
                f"{unscored_equity_count}/{total_equity_count} equity holdings lack "
                "fundamentals — click to trigger refresh."
            ),
            "component": "data_coverage",
            "action_hint": "refresh_stock_fundamentals",
        }
        # Surface the actual symbols so the UI can render them inline (capped
        # at 20 to keep payloads bounded; user with hundreds of unscored stocks
        # would hit pathological renders otherwise).
        if unscored_equity_holdings:
            alert["unscored_symbols"] = unscored_equity_holdings[:20]
        alerts.append(alert)
    return alerts


# ── Main orchestrator: enriched holdings for UI ────────────────────────
async def build_enriched_portfolio(
    user_id: str, *, use_cache: bool = True,
) -> Dict[str, Any]:
    """Build the full `actionable portfolio` payload for the new UI.
    Results are cached for 5 minutes in Redis (per user) — pass use_cache=False
    to force recompute after a refresh.
    """
    from deps import db
    from services import portfolio_health as ph
    from services import pg_client
    from services import redis_client as _rc

    cache_key = f"enriched_portfolio:{user_id}"
    if use_cache:
        cached = await _rc.cache_get(cache_key)
        if cached is not None:
            cached["_cache_hit"] = True
            return cached

    holdings = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(2000)
    if not holdings:
        # Self-heal: when `db.holdings` is empty but the user has at least
        # one parsed CAS snapshot in `db.portfolio_snapshots`, the live
        # holdings table got nuked or was never populated (write_holdings_table
        # didn't fire after the parse, or a delete_many ran). Load the
        # latest snapshot into holdings so the UI doesn't falsely tell the
        # user / advisor to "Upload a CAS to begin" when the CAS was already
        # ingested. Snapshots are preserved in `portfolio_snapshots`; this
        # only rewrites the live mirror.
        try:
            # Pick the latest snapshot that ACTUALLY carries a `holdings`
            # array. The eod_cron writes lightweight trend snapshots
            # (`top_holdings` + aggregates only, no `holdings` field).
            # If we self-heal from one of those, `write_holdings_table`
            # wipes the live table to zero rows on every page-load — the
            # exact failure mode this self-heal was designed to fix.
            latest_snap = await db.portfolio_snapshots.find_one(
                {"user_id": user_id,
                 "holdings": {"$exists": True, "$not": {"$size": 0}}},
                {"_id": 0, "snapshot_date": 1},
                sort=[("snapshot_date", -1)],
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("snapshot self-heal probe failed for %s: %s", user_id, e)
            latest_snap = None
        if latest_snap and latest_snap.get("snapshot_date"):
            try:
                from services import cas_snapshot_engine as cse
                logger.info(
                    "holdings self-heal: rehydrating %s from snapshot %s",
                    user_id, latest_snap["snapshot_date"],
                )
                await cse.load_snapshot_into_holdings(
                    user_id, latest_snap["snapshot_date"],
                )
                holdings = await db.holdings.find(
                    {"user_id": user_id}, {"_id": 0},
                ).to_list(2000)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "holdings self-heal failed for %s (snapshot %s): %s",
                    user_id, latest_snap["snapshot_date"], e,
                )
        if not holdings:
            return {"holdings": [], "alerts": [], "totals": {}, "coverage_pct": 0,
                    "health": None}

    # Load stock scores in bulk
    stock_scores_by_sym: Dict[str, Dict[str, Any]] = {}
    # Symbol backfills derived from ISIN — written back to db.holdings at the
    # end so subsequent renders are fully enriched without a full reparse.
    isin_to_symbol_backfill: Dict[str, str] = {}
    try:
        pool = await pg_client.get_pool()
        if pool is not None:
            equity_holdings = [
                h for h in holdings
                if (h.get("asset_type") or "").lower() == "equity"
            ]
            symbols = [
                (h.get("nse_symbol") or "").upper()
                for h in equity_holdings
            ]
            symbols = [s for s in symbols if s]
            # Resolve missing nse_symbols via ISIN so freshly-parsed CAS rows
            # (which carry ISIN but not the NSE ticker) still match V3 scores.
            missing_isins = [
                (h.get("ticker") or "").strip()
                for h in equity_holdings
                if not (h.get("nse_symbol") or "").strip()
            ]
            missing_isins = [i for i in missing_isins if i]
            if missing_isins:
                try:
                    async with pool.acquire() as conn:
                        iso_rows = await conn.fetch(
                            "SELECT nse_symbol, isin FROM stock_master "
                            "WHERE isin = ANY($1::text[])",
                            missing_isins,
                        )
                    for r in iso_rows:
                        if r["isin"] and r["nse_symbol"]:
                            isin_to_symbol_backfill[r["isin"]] = r["nse_symbol"]
                            symbols.append(r["nse_symbol"])
                except Exception as e:  # noqa: BLE001
                    logger.debug("isin→symbol backfill skipped: %s", e)
            if symbols:
                # Fetch 1Y returns for each symbol from NIDP DaaS first
                # (POST /v1/stocks/v3-primitives/bulk). Direct PG read is the
                # fallback for environments where DaaS isn't configured or
                # migration 055 hasn't been applied. The Nivesh scoring tables
                # (stock_scores, stock_master) still live in the Nivesh PG
                # and are joined locally below — the cutover here is about
                # the *primitive* data source, not the Nivesh-side scores.
                nidp_returns: Dict[str, Optional[float]] = {}
                try:
                    import feature_flags as _ff
                    from services.copilot_tools import daas_client as _daas
                    if _ff.mode_enabled("v3_data_source_daas") and _daas.is_configured():
                        primitives = await _daas.get_v3_stock_primitives_bulk(symbols)
                        for sym, row in primitives.items():
                            nidp_returns[sym] = row.get("return_252d_pct")
                except Exception as e:  # noqa: BLE001
                    logger.warning("DaaS stock primitives bulk fetch failed: %s", e)

                async with pool.acquire() as conn:
                    if nidp_returns:
                        # DaaS already supplied returns; skip the lateral join.
                        rows = await conn.fetch(
                            """SELECT ss.nse_symbol, sm.sector, sm.cap_bucket,
                                      ss.quality_score, ss.health_score,
                                      ss.exit_score, ss.add_score,
                                      ss.recommendation, ss.recommendation_reason,
                                      ss.low_confidence, ss.morningstar_rating
                               FROM stock_scores ss
                               JOIN stock_master sm ON sm.nse_symbol = ss.nse_symbol
                               WHERE ss.nse_symbol = ANY($1::text[])""",
                            symbols,
                        )
                    else:
                        # DaaS unavailable — fall back to PG-direct lateral join
                        # against the NIDP view (or legacy stock_primitives).
                        nidp_view_present = await conn.fetchval(
                            """
                            SELECT EXISTS (
                                SELECT 1 FROM information_schema.views
                                 WHERE table_schema = 'nidp'
                                   AND table_name   = 'v_v3_stock_primitives'
                            )
                            """
                        )
                        if nidp_view_present:
                            sql_returns_join = """
                               LEFT JOIN LATERAL (
                                 SELECT return_252d_pct AS return_1y_pct
                                   FROM nidp.v_v3_stock_primitives
                                  WHERE symbol = ss.nse_symbol
                                  ORDER BY as_of_date DESC LIMIT 1
                               ) sp ON TRUE
                            """
                        else:
                            sql_returns_join = """
                               LEFT JOIN LATERAL (
                                 SELECT return_1y_pct FROM stock_primitives
                                  WHERE nse_symbol = ss.nse_symbol
                                  ORDER BY as_of_date DESC LIMIT 1
                               ) sp ON TRUE
                            """
                        rows = await conn.fetch(
                            f"""SELECT ss.nse_symbol, sm.sector, sm.cap_bucket,
                                      ss.quality_score, ss.health_score,
                                      ss.exit_score, ss.add_score,
                                      ss.recommendation, ss.recommendation_reason,
                                      ss.low_confidence, ss.morningstar_rating,
                                      sp.return_1y_pct
                               FROM stock_scores ss
                               JOIN stock_master sm ON sm.nse_symbol = ss.nse_symbol
                               {sql_returns_join}
                               WHERE ss.nse_symbol = ANY($1::text[])""",
                            symbols,
                        )
                for r in rows:
                    sym = r["nse_symbol"]
                    ret_1y = nidp_returns.get(sym) if nidp_returns else r.get("return_1y_pct")
                    stock_scores_by_sym[sym] = {
                        "scores": {
                            "quality": float(r["quality_score"]) if r["quality_score"] else None,
                            "health":  float(r["health_score"])  if r["health_score"]  else None,
                            "exit":    float(r["exit_score"])    if r["exit_score"]    else None,
                            "add":     float(r["add_score"])     if r["add_score"]     else None,
                        },
                        "recommendation": r["recommendation"],
                        "recommendation_reason": r["recommendation_reason"],
                        "sector": r["sector"],
                        "cap_bucket": r["cap_bucket"],
                        "low_confidence": bool(r["low_confidence"]) if r["low_confidence"] is not None else False,
                        "return_1y_pct": float(ret_1y) if ret_1y is not None else None,
                        "morningstar_rating": int(r["morningstar_rating"]) if r["morningstar_rating"] is not None else None,
                    }
    except Exception as e:  # noqa: BLE001
        logger.warning("enriched_portfolio: stock score join failed: %s", e)

    # Load MF V3 scores via the existing v3_portfolio endpoint's logic
    mf_scores_by_name: Dict[str, Dict[str, Any]] = {}
    try:
        from services import v3_integration
        mf_holdings = [h for h in holdings
                       if (h.get("asset_type") or "").lower() in ("mutual_fund", "etf")]
        if mf_holdings:
            mf_inv = [
                {
                    "scheme_name": h.get("name"),
                    "instrument_id": h.get("instrument_id"),
                    "value": float(h.get("quantity") or 0) * float(h.get("current_price") or 0),
                }
                for h in mf_holdings
            ]
            v3_map = await v3_integration.enrich_candidates_with_v3(
                mf_investments=mf_inv, exit_candidates=[],
                mf_holdings=mf_holdings, portfolio_intelligence={},
            )
            for m in mf_inv:
                v3 = v3_integration.lookup_v3(
                    m.get("instrument_id"), m.get("scheme_name", ""), v3_map,
                )
                if v3:
                    key = (m["scheme_name"] or "").lower().strip()
                    prim = v3.get("v3_primitives") or {}
                    mf_scores_by_name[key] = {
                        "instrument_id": v3.get("instrument_id"),
                        "scores": {
                            "quality": v3.get("quality_score"),
                            "health":  v3.get("health_score"),
                            "exit":    v3.get("exit_score"),
                            "add":     v3.get("add_score"),
                        },
                        "category": v3.get("category"),
                        "sub_category": v3.get("sub_category"),
                        "expense_ratio": prim.get("expense_ratio_direct"),
                        "ret_1y": prim.get("ret_1y"),
                        "ret_3y": prim.get("ret_3y"),
                        "ret_5y": prim.get("ret_5y"),
                        "morningstar_rating": prim.get("morningstar_rating"),
                    }
    except Exception as e:  # noqa: BLE001
        logger.warning("enriched_portfolio: MF V3 join failed: %s", e)

    # Category rank: for each sub_category represented in the user's portfolio,
    # fetch all funds in that category and rank them by quality_score.
    # Scoped to active categories only — no full-table scan.
    category_rank_by_iid: Dict[str, Dict[str, Any]] = {}
    try:
        pool = await pg_client.get_pool()
        if pool:
            # Collect the sub_categories present in this portfolio
            user_cats = {
                r.get("sub_category") or r.get("category")
                for r in v3_map.values()
                if r.get("sub_category") or r.get("category")
            }
            if user_cats:
                async with pool.acquire() as conn:
                    cat_rows = await conn.fetch(
                        """
                        SELECT im.instrument_id,
                               mfm.sub_category,
                               mfm.category,
                               mfm.quality_score
                          FROM mutual_fund_metadata mfm
                          JOIN instrument_master im ON im.instrument_id = mfm.instrument_id
                         WHERE im.is_active = TRUE
                           AND mfm.quality_score IS NOT NULL
                           AND (mfm.sub_category = ANY($1::text[])
                                OR mfm.category  = ANY($1::text[]))
                         ORDER BY mfm.quality_score DESC NULLS LAST
                        """,
                        list(user_cats),
                    )
                by_cat: Dict[str, List[Dict]] = {}
                for r in cat_rows:
                    sub = r["sub_category"] or r["category"]
                    if sub:
                        by_cat.setdefault(sub, []).append(dict(r))
                for sub, funds in by_cat.items():
                    total = len(funds)
                    for i, f in enumerate(funds, start=1):
                        iid = str(f["instrument_id"])
                        category_rank_by_iid[iid] = {
                            "rank": i, "total": total, "sub_category": sub,
                        }
    except Exception as e:  # noqa: BLE001
        logger.warning("enriched_portfolio: category rank build failed: %s", e)

    # Portfolio Health (for risk drivers + totals)
    try:
        hr = await ph.build_portfolio_health(user_id)
        health_payload = hr.to_dict()
    except Exception as e:  # noqa: BLE001
        logger.warning("enriched_portfolio: health failed: %s", e)
        health_payload = None

    # Build per-holding rows
    enriched: List[Dict[str, Any]] = []
    # Pre-compute total value so weight_pct can be passed into badge logic.
    grand_total_val = sum(
        float(h.get("quantity") or 0) * float(h.get("current_price") or 0)
        for h in holdings
    )
    total_val = 0.0
    total_inv = 0.0
    total_val_known = 0.0
    alloc: Dict[str, float] = {}
    scored_equities = 0
    total_equities = 0
    scored_mfs = 0
    total_mfs = 0
    # Collected so the data_coverage alert can show *which* stocks are unscored,
    # not just the count. Each entry: {symbol, name, value_rs}.
    unscored_equity_holdings: List[Dict[str, Any]] = []
    for h in holdings:
        at = (h.get("asset_type") or "").lower()
        qty = float(h.get("quantity") or 0)
        bp = float(h.get("buy_price") or 0)
        cp = float(h.get("current_price") or 0)
        val = qty * cp
        inv = qty * bp
        # Cost-basis-unknown rows must NOT poison portfolio totals — they
        # have buy_price=0 (CAS doesn't carry cost basis for direct
        # equities and we couldn't reconstruct it from snapshot history).
        # If we counted these, total_invested would understate and the
        # portfolio-level return % would balloon. Track value but skip
        # invested AND skip the matching value when computing pnl_rs.
        cost_basis_known = bp > 0
        total_val += val
        if cost_basis_known:
            total_inv += inv
            total_val_known += val
        name_l = (h.get("name") or "").lower()

        # Lookup scores
        score_bundle: Optional[Dict[str, Any]] = None
        rec: Optional[str] = None
        rec_reason: Optional[str] = None
        category: Optional[str] = h.get("category")
        expense_ratio: Optional[float] = None
        is_regular = "regular" in name_l and "direct" not in name_l
        ret_1y_ext: Optional[float] = None   # external CAGR (Groww/MC)
        ret_3y_ext: Optional[float] = None
        ret_5y_ext: Optional[float] = None

        if at == "equity":
            total_equities += 1
            sym = (h.get("nse_symbol") or "").upper()
            if not sym:
                # Fall back to ISIN-resolved symbol from stock_master.
                resolved = isin_to_symbol_backfill.get(
                    (h.get("ticker") or "").strip(),
                )
                if resolved:
                    sym = resolved.upper()
                    h["nse_symbol"] = sym
            s = stock_scores_by_sym.get(sym)
            if s:
                scored_equities += 1
                score_bundle = s["scores"]
                rec = s["recommendation"]
                rec_reason = s["recommendation_reason"]
                ret_1y_ext = s.get("return_1y_pct")
            else:
                # Surface to the data_coverage alert so the user can see *which*
                # stocks lack fundamentals instead of just a count.
                unscored_equity_holdings.append({
                    "symbol": sym or (h.get("ticker") or ""),
                    "name": h.get("name", ""),
                    "value_rs": round(val, 2),
                })
            morningstar_rating = s.get("morningstar_rating") if s else None
            category_rank = None
            category_rank_total = None
        elif at in ("mutual_fund", "etf"):
            total_mfs += 1
            m = mf_scores_by_name.get(name_l)
            if m:
                scored_mfs += 1
                score_bundle = m["scores"]
                # Prefer sub_category (e.g. Flexi Cap) over broad category (equity)
                category = m.get("sub_category") or m.get("category") or category
                expense_ratio = m.get("expense_ratio")
                ret_1y_ext = m.get("ret_1y")
                ret_3y_ext = m.get("ret_3y")
                ret_5y_ext = m.get("ret_5y")
                morningstar_rating = m.get("morningstar_rating")
            else:
                morningstar_rating = None
            # Category rank: use instrument_id from the matched v3 bundle.
            iid = (m or {}).get("instrument_id") if m else None
            cr = category_rank_by_iid.get(iid) if iid else None
            category_rank = cr["rank"] if cr else None
            category_rank_total = cr["total"] if cr else None
            if cr:
                # Always override with the sub_category used for ranking so the
                # tooltip reads a meaningful bucket name (e.g. "Flexi Cap").
                category = cr.get("sub_category") or category
        else:
            morningstar_rating = None
            category_rank = None
            category_rank_total = None

        composite = composite_score(score_bundle)
        weight_pct = (val / grand_total_val * 100) if grand_total_val > 0 else None
        badge = derive_action_badge(
            score_bundle, rec,
            is_regular_plan=is_regular, high_overlap=False,
            weight_pct=weight_pct,
        )

        # Personal XIRR from avg-cost lump-sum proxy
        raw_xirr = _holding_xirr(h.get("buy_date"), bp, cp, qty)
        xirr_pct = None
        xirr_source = None
        if raw_xirr is not None:
            # CAS gives avg cost + earliest buy_date; true XIRR needs full SIP
            # cashflows. Clamp to realistic band to suppress avg-cost inflation
            # artefacts (e.g. avg cost ₹10 for a ₹2000 stock over 5 yrs → 366% IRR).
            if -80.0 <= raw_xirr <= 150.0:
                xirr_pct = round(raw_xirr, 2)
                xirr_source = "personal"

        # Fallback to 3y > 1y > 5y scraped CAGR when personal XIRR unavailable
        # or was capped as an artifact.
        cagr_pct = ret_3y_ext if ret_3y_ext is not None else (
            ret_1y_ext if ret_1y_ext is not None else ret_5y_ext
        )
        if xirr_pct is None and cagr_pct is not None:
            xirr_pct = round(float(cagr_pct), 2)
            xirr_source = (
                "cagr_3y" if ret_3y_ext is not None
                else ("cagr_1y" if ret_1y_ext is not None else "cagr_5y")
            )

        # ── Decision engine + Cost-of-Switch (PRD framework) ──────────
        # Two-tier strategy:
        # 1. Always compute the cheap switch-cost breakdown (tax + exit +
        #    slippage). No peer lookup needed.
        # 2. When sub_category + peers are available, also run the full
        #    decision engine to surface to_fund / to_allocation_pct + a
        #    real benchmark-based alpha. Falls back gracefully when peer
        #    data is missing.
        switch_cost_block = None
        to_fund: Optional[str] = None
        to_allocation_pct: Optional[int] = None
        is_equity_fund = True
        if at in ("mutual_fund", "etf") and val > 0:
            try:
                from services import switch_decision_engine as sde
                holding_age_days = None
                if h.get("buy_date"):
                    try:
                        bd = h["buy_date"]
                        if isinstance(bd, str):
                            bd = datetime.fromisoformat(bd.replace("Z", "+00:00")).date()
                        elif isinstance(bd, datetime):
                            bd = bd.date()
                        holding_age_days = (date.today() - bd).days
                    except (TypeError, ValueError):
                        pass
                # Equity-fund tax treatment unless name OR category suggests debt.
                cat_l = (category or "").lower()
                is_equity_fund = not any(
                    k in name_l or k in cat_l
                    for k in ("liquid", "debt", "bond", "gilt",
                              "corporate", "short term", "ultra short",
                              "money market", "low duration")
                )

                # Cheap path — always runs. Provides the % chips even when
                # the heavy decision engine path can't run (no peers).
                cost_inp = sde.DecisionInputs(
                    invested_amount=inv, current_value=val,
                    holding_period_days=holding_age_days,
                    is_equity=is_equity_fund,
                    exit_load_pct=float(h.get("exit_load_pct") or 0),
                )
                c = sde.compute_switch_costs(cost_inp)
                fallback_alpha_pct = 0.8 if is_regular else 0.0
                switch_cost_block = {
                    "tax_cost": c["tax_cost"],
                    "exit_cost": c["exit_cost"],
                    "slippage_cost": c["slippage_cost"],
                    "total_cost": c["total_cost"],
                    "switch_cost_pct": round(c["switch_cost_pct"] * 100, 3),
                    "tax_impact_pct": round(c["tax_impact_pct"] * 100, 3),
                    "exit_load_pct": round(c["exit_load_pct"] * 100, 3),
                    "slippage_pct": round(c["slippage_pct"] * 100, 3),
                    "alpha_pct_annual": fallback_alpha_pct,
                    "cost_saving": round(val * (fallback_alpha_pct / 100.0) * 5, 0) if fallback_alpha_pct > 0 else 0,
                    "alpha_gain": 0,
                    "net_benefit": round(val * (fallback_alpha_pct / 100.0) * 5 - c["total_cost"], 0) if fallback_alpha_pct > 0 else 0,
                }

                # Heavy path — full decision engine with peers. Skipped if
                # no instrument_id resolved (e.g., CAS-only holding) since
                # without it we can't fetch the peer universe reliably.
                lookup_iid = (m or {}).get("instrument_id")
                if lookup_iid:
                    try:
                        from services import candidate_fund_hydrator as cfh
                        ctx = await cfh.fetch_current_fund_context(
                            db, instrument_id=lookup_iid, scheme_name=h.get("name"),
                        ) or {}
                        sub_cat = ctx.get("sub_category") or category
                        peers = []
                        if sub_cat:
                            peers = await cfh.fetch_candidates_for_category(
                                db, sub_cat, prefer_direct=True,
                                exclude_instrument_id=lookup_iid,
                            )
                        if peers:
                            sub_lower = (sub_cat or "").lower()
                            is_thematic = any(
                                kw in sub_lower
                                for kw in ("sector", "thematic", "energy", "infra",
                                           "pharma", "fmcg", "tech", "banking",
                                           "psu", "consumption", "manufactur")
                            )
                            full_inp = sde.DecisionInputs(
                                quality=(score_bundle or {}).get("quality"),
                                health=(score_bundle or {}).get("health"),
                                exit_s=(score_bundle or {}).get("exit"),
                                add=(score_bundle or {}).get("add"),
                                invested_amount=inv, current_value=val,
                                holding_period_days=holding_age_days,
                                is_equity=is_equity_fund,
                                exit_load_pct=float(h.get("exit_load_pct") or 0),
                                expense_current=ctx.get("expense_current"),
                                expense_direct=ctx.get("expense_direct"),
                                current_return_5y=ctx.get("current_return_5y"),
                                current_drawdown=ctx.get("current_drawdown"),
                                current_consistency=ctx.get("current_consistency"),
                                current_category=sub_cat,
                                current_fund_name=h.get("name"),
                                direct_plan_available=bool(
                                    ctx.get("expense_current") is not None
                                    and ctx.get("expense_direct") is not None
                                    and ctx["expense_current"] > ctx["expense_direct"]
                                ),
                                portfolio_weight_pct=weight_pct,
                                is_sector_or_thematic=is_thematic,
                                candidate_funds=peers,
                            )
                            decision = sde.decide(
                                full_inp,
                                plan_type="regular" if is_regular else "direct",
                            )
                            d = sde.result_to_dict(decision)
                            to_fund = d.get("to_fund")
                            to_allocation_pct = d.get("allocation_pct")
                            # Replace the fallback impact block with the
                            # engine's real numbers (proper alpha, net_benefit).
                            # NB: the engine's `impact` dict already stores
                            # switch_cost_pct / tax_impact_pct / exit_load_pct /
                            # slippage_pct / alpha_pct_annual in display-percent
                            # form (×100 applied inside decide()'s breakdown).
                            # Do NOT multiply again — the cheap fallback above
                            # uses raw decimals from compute_switch_costs and
                            # converts there, but result_to_dict pulls from the
                            # already-converted breakdown.
                            switch_cost_block = {
                                **switch_cost_block,
                                **d.get("impact", {}),
                            }
                    except Exception as e:  # noqa: BLE001
                        logger.debug("decision engine skipped for %s: %s", h.get('name'), e)
            except Exception as e:  # noqa: BLE001
                logger.debug("switch_cost compute failed for %s: %s", h.get('name'), e)

        enriched.append({
            "holding_id": h.get("holding_id"),
            "name": h.get("name"), "isin": h.get("ticker"),
            "nse_symbol": h.get("nse_symbol"),
            "asset_type": at, "sector": h.get("sector"),
            "category": category,
            "quantity": qty, "buy_price": bp, "current_price": cp,
            "buy_date": h.get("buy_date"),
            "value_rs": round(val, 2),
            "invested_rs": round(inv, 2) if cost_basis_known else None,
            "pnl_rs": round(val - inv, 2) if cost_basis_known else None,
            "pnl_pct": (
                round((val - inv) / inv * 100, 2)
                if cost_basis_known and inv > 0 else None
            ),
            "cost_basis_source": h.get("cost_basis_source"),
            "xirr_pct": xirr_pct,
            "xirr_source": xirr_source,
            "cagr_1y_pct": round(float(ret_1y_ext), 2) if ret_1y_ext is not None else None,
            "cagr_3y_pct": round(float(ret_3y_ext), 2) if ret_3y_ext is not None else None,
            "cagr_5y_pct": round(float(ret_5y_ext), 2) if ret_5y_ext is not None else None,
            "is_regular_plan": is_regular,
            "scores": score_bundle,
            "composite_score": composite,
            "morningstar_rating": morningstar_rating,
            "category_rank": category_rank,
            "category_rank_total": category_rank_total,
            "recommendation": rec,
            "recommendation_reason": rec_reason,
            "action_badge": badge,
            "expense_ratio": expense_ratio,
            "switch_cost": switch_cost_block,
            "to_fund": to_fund,
            "to_allocation_pct": to_allocation_pct,
            "is_equity_fund": is_equity_fund if at in ("mutual_fund", "etf") else None,
            "weight_pct": (round(weight_pct, 2)
                           if weight_pct is not None else None),
            "low_confidence": (
                score_bundle is None
                or (stock_scores_by_sym.get((h.get("nse_symbol") or "").upper()) or {}).get("low_confidence", False)
            ),
        })

        # Rough allocation bucket
        if at in ("equity", "stock"):
            alloc["equity"] = alloc.get("equity", 0) + val
        elif at == "etf" or ("hybrid" in name_l or "balanced" in name_l):
            alloc["hybrid"] = alloc.get("hybrid", 0) + val
        elif at in ("mutual_fund",):
            if any(k in name_l for k in ["liquid", "debt", "bond", "gilt", "corporate", "short term"]):
                alloc["debt"] = alloc.get("debt", 0) + val
            else:
                alloc["equity"] = alloc.get("equity", 0) + val
        elif at in ("gold",):
            alloc["hybrid"] = alloc.get("hybrid", 0) + val

        # Per-holding target bucket — keyed to target_allocator's
        # {equity, debt, gold, cash} taxonomy. Used below for the
        # allocation gap shown in the ADD verdict reasoning.
        is_liquid = any(k in name_l for k in ["liquid", "money market", "ultra short"])
        is_debt = any(k in name_l for k in ["debt", "bond", "gilt", "corporate", "short term", "low duration"])
        if at in ("gold",):
            target_bucket = "gold"
        elif at in ("equity", "stock"):
            target_bucket = "equity"
        elif at == "etf":
            target_bucket = "equity"
        elif at in ("mutual_fund",):
            if is_liquid:
                target_bucket = "cash"
            elif is_debt:
                target_bucket = "debt"
            else:
                target_bucket = "equity"
        else:
            target_bucket = "equity"
        enriched[-1]["_target_bucket"] = target_bucket

    if total_val > 0:
        alloc = {k: round((v / total_val) * 100, 1) for k, v in alloc.items()}

    # ── Per-holding target_weight_pct ─────────────────────────────────
    # Naive split: bucket target % is divided evenly across holdings in
    # that bucket. Crude (doesn't reflect category leadership or fund
    # size), but unblocks the ADD verdict's allocation-gap reasoning.
    # When target_allocator is unavailable (no risk profile yet),
    # target_weight_pct stays None and the verdict falls back gracefully.
    try:
        from services.target_allocator import compute_target_allocation
        ta = await compute_target_allocation(user_id)
        bucket_target_pct = ta.allocation or {}
        bucket_holdings: Dict[str, List[int]] = {}
        for i, row in enumerate(enriched):
            b = row.pop("_target_bucket", None)
            if b:
                bucket_holdings.setdefault(b, []).append(i)
        for bucket, idxs in bucket_holdings.items():
            target_pct = float(bucket_target_pct.get(bucket) or 0)
            if target_pct <= 0 or not idxs:
                continue
            per_fund = round(target_pct / len(idxs), 2)
            for i in idxs:
                enriched[i]["target_weight_pct"] = per_fund
                enriched[i]["target_bucket"] = bucket

        # ── Reconcile ADD badge with allocation gap ──────────────────
        # `derive_action_badge` flags ADD purely from scores (Add≥70 +
        # Quality≥65) — it has no allocation context at the time it runs.
        # When the fund is already at or over its target weight, ADD is
        # the wrong CTA: the DecisionCard correctly downgrades to HOLD,
        # so do the same on the badge to keep the row pill consistent
        # with the expanded card.
        ALLOC_OVER_THRESHOLD_PP = 0.5  # >0.5pp over target → block ADD
        for row in enriched:
            badge = row.get("action_badge") or {}
            if badge.get("action") != "ADD":
                continue
            cur = row.get("weight_pct")
            tgt = row.get("target_weight_pct")
            if cur is None or tgt is None:
                continue
            if (cur - tgt) >= ALLOC_OVER_THRESHOLD_PP:
                row["action_badge"] = {
                    **HOLD,
                    "reason": (
                        f"Already at target ({cur:.1f}% vs {tgt:.1f}%) — "
                        "fresh capital better deployed elsewhere."
                    ),
                    "sub_action": "At target",
                    "sub_reason": (
                        f"Allocation {cur:.1f}% is over target {tgt:.1f}% "
                        f"by {(cur - tgt):.1f}pp."
                    ),
                }
    except Exception as e:  # noqa: BLE001
        logger.debug("target_weight_pct hydration skipped: %s", e)
        # Strip the temp key so it doesn't leak into the response
        for row in enriched:
            row.pop("_target_bucket", None)

    # Hydrate benchmark CAGR per row — one Postgres read per distinct
    # benchmark, then attach to all rows that map there. The Decision
    # Verdict UI computes alpha = fund_cagr - benchmark_cagr.
    try:
        from services import benchmark_index as _bm
        wanted: Dict[str, List[int]] = {}
        for i, row in enumerate(enriched):
            cat = (row.get("category") or row.get("scores", {}).get("category"))
            if not cat:
                # Best-effort: heuristic category from name
                from services.action_plan_manager import ActionPlanManager as _APM
                try:
                    cat = _APM()._infer_category_from_name(row.get("name") or "")
                except Exception:  # noqa: BLE001
                    cat = None
            if not cat:
                continue
            bench = await _bm.get_benchmark_for_category(cat)
            if not bench:
                continue
            wanted.setdefault(bench, []).append(i)
            row["benchmark_label"] = bench.replace("_", " ").title()
            row["benchmark_name"] = bench
        # One latest-snapshot read per distinct benchmark
        for bench, idxs in wanted.items():
            snap = await _bm.get_latest_index(bench)
            if not snap:
                continue
            cagr_3y = (snap.get("metrics") or {}).get("return_3y")
            cagr_1y = (snap.get("metrics") or {}).get("return_1y")
            for i in idxs:
                if cagr_3y is not None:
                    enriched[i]["benchmark_cagr_3y_pct"] = round(float(cagr_3y) * 100, 2)
                if cagr_1y is not None:
                    enriched[i]["benchmark_cagr_1y_pct"] = round(float(cagr_1y) * 100, 2)
                # Forward expected alpha = max(historical alpha, 0).
                # Conservative — never assume forward gain just because of past alpha.
                fund_3y = enriched[i].get("cagr_3y_pct")
                if fund_3y is not None and cagr_3y is not None:
                    enriched[i]["expected_alpha_annual_pct"] = round(
                        max(0.0, float(fund_3y) - float(cagr_3y) * 100), 2,
                    )
    except Exception as e:  # noqa: BLE001
        logger.debug("benchmark hydration skipped: %s", e)

    # Ideal alloc + risk profile from Portfolio Health
    ideal_alloc = {"equity": 60, "debt": 30, "hybrid": 10}
    risk_user = "moderate"
    risk_port = "moderate"
    if health_payload:
        try:
            # Heuristic: if equity > 70% → aggressive behaviour
            if alloc.get("equity", 0) >= 75:
                risk_port = "aggressive"
            elif alloc.get("equity", 0) <= 40:
                risk_port = "conservative"
        except Exception:  # noqa: BLE001
            pass

    # Portfolio XIRR — value-weighted average of per-holding XIRRs.
    # (Flow-based XIRR explodes when avg-cost + single buy_date is used as a
    # lump-sum proxy for SIPs, so we use the weighted-average approach which
    # is also what Groww / Kuvera show.)
    weighted_num = 0.0
    weighted_den = 0.0
    for row in enriched:
        r = row.get("xirr_pct")
        v = float(row.get("value_rs") or 0)
        if r is not None and v > 0:
            weighted_num += r * v
            weighted_den += v
    port_xirr_pct = round(weighted_num / weighted_den, 2) if weighted_den > 0 else None

    # Sort unscored by largest value first so the UI surfaces the highest-impact
    # holdings at the top of the expandable list.
    unscored_equity_holdings.sort(key=lambda x: x.get("value_rs") or 0, reverse=True)
    alerts = derive_portfolio_alerts(
        health_payload=health_payload,
        alloc=alloc, ideal=ideal_alloc,
        risk_profile_user=risk_user, risk_profile_portfolio=risk_port,
        unscored_equity_count=(total_equities - scored_equities),
        total_equity_count=total_equities,
        unscored_equity_holdings=unscored_equity_holdings,
    )

    # Coverage: scored (equities + MFs) / (equities + MFs). ETFs count towards MFs.
    total_scorable = total_equities + total_mfs
    scored_total = scored_equities + scored_mfs
    coverage_pct = round((scored_total / total_scorable) * 100, 1) if total_scorable else 100.0

    # ── Portfolio Impact (completing all pending actions) ─────────────
    # Cost savings: for each Regular-plan SWITCH row, annual saving is
    #   value × (regular_er − direct_er) / 100. We approximate the Δ as
    #   the MF's expense_ratio primitive vs. category baseline 0.75%.
    impact_cost_savings_rs = 0.0
    impact_value_freed_rs = 0.0
    impact_counts = {"EXIT": 0, "SWITCH": 0, "ADD": 0}
    for row in enriched:
        act = (row.get("action_badge") or {}).get("action")
        if act == "EXIT":
            impact_value_freed_rs += float(row.get("value_rs") or 0)
            impact_counts["EXIT"] += 1
        elif act == "SWITCH":
            impact_counts["SWITCH"] += 1
            if row.get("is_regular_plan"):
                # Baseline 0.75% Direct-plan expense; current ER from primitives or 1.25% default.
                old_er = float(row.get("expense_ratio") or 1.25)
                saving_rs = float(row.get("value_rs") or 0) * max(0, old_er - 0.75) / 100.0
                impact_cost_savings_rs += saving_rs
        elif act == "ADD":
            impact_counts["ADD"] += 1

    # Health projection delta (best-effort — swallow errors)
    health_current = None
    health_projected = None
    health_delta = None
    try:
        if health_payload:
            health_current = round(float(health_payload.get("health_score") or 0), 1) or None
        from services import portfolio_health_projection as phj
        proj = await phj.project_health(user_id)
        if proj:
            health_projected = round(float(proj.get("projected") or 0), 1) or None
            health_delta = round(float(proj.get("delta_total") or 0), 2) or None
    except Exception as e:  # noqa: BLE001
        logger.info("enriched_portfolio: projection skipped: %s", e)

    portfolio_impact = {
        "pending_actions": sum(impact_counts.values()),
        "by_action": impact_counts,
        "estimated_cost_savings_rs_per_yr": round(impact_cost_savings_rs, 0),
        "estimated_value_freed_rs": round(impact_value_freed_rs, 0),
        "health_current": health_current,
        "health_projected": health_projected,
        "health_delta": health_delta,
    }

    result = {
        "holdings": enriched,
        "alerts": alerts,
        "totals": {
            "count": len(enriched),
            "value_rs": round(total_val, 2),
            "invested_rs": round(total_inv, 2),
            # P&L is computed only over holdings whose cost basis is
            # known — pairing total_val (which includes unknown-basis
            # rows) with total_inv would produce an inflated profit.
            "pnl_rs": round(total_val_known - total_inv, 2),
            "pnl_pct": (
                round((total_val_known - total_inv) / total_inv * 100, 2)
                if total_inv else 0
            ),
            "xirr_pct": port_xirr_pct,
        },
        "coverage_pct": coverage_pct,
        "allocation_actual": alloc,
        "allocation_ideal": ideal_alloc,
        "health": health_payload,
        "portfolio_impact": portfolio_impact,
        "_cache_hit": False,
    }
    # Persist any ISIN→nse_symbol backfills we resolved so future renders
    # don't repeat the lookup. Best-effort — never fail enrichment for this.
    if isin_to_symbol_backfill:
        try:
            for isin, sym in isin_to_symbol_backfill.items():
                await db.holdings.update_many(
                    {"user_id": user_id, "ticker": isin,
                     "asset_type": "equity",
                     "$or": [{"nse_symbol": None}, {"nse_symbol": ""}]},
                    {"$set": {"nse_symbol": sym}},
                )
        except Exception as e:  # noqa: BLE001
            logger.debug("nse_symbol backfill persist skipped: %s", e)

    # B-4: one-time backfill of mutual_fund_metadata.asset_class for NULL rows.
    # Guard with a fast COUNT so the UPDATE only runs when there is actually work to do.
    try:
        from services import pg_client as _pg
        _pool = await _pg.get_pool()
        if _pool:
            async with _pool.acquire() as _conn:
                null_count = await _conn.fetchval(
                    "SELECT COUNT(*) FROM mutual_fund_metadata WHERE asset_class IS NULL LIMIT 1"
                )
            if null_count:
                await _backfill_mfm_asset_class(_pool)
    except Exception as e:  # noqa: BLE001
        logger.debug("asset_class backfill skipped: %s", e)

    # Cache for 5 minutes — refresh-fundamentals and refresh-prices evict this key.
    try:
        await _rc.cache_set(cache_key, result, ttl_s=300)
    except Exception:  # noqa: BLE001
        pass
    return result


async def _backfill_mfm_asset_class(pool) -> None:
    """Populate mutual_fund_metadata.asset_class for rows where it is NULL.

    Uses a single UPDATE … CASE so all rows are fixed in one round-trip.
    The CASE logic mirrors _asset_class_for() in routes/portfolio_composition.py.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE mutual_fund_metadata
               SET asset_class = CASE
                   WHEN category ILIKE ANY(ARRAY['%liquid%','%debt%','%bond%','%gilt%',
                                                  '%corporate%','%short term%',
                                                  '%low duration%','%overnight%',
                                                  '%money market%'])
                        THEN 'Debt'
                   WHEN category ILIKE ANY(ARRAY['%hybrid%','%balanced%',
                                                  '%multi asset%','%arbitrage%'])
                        THEN 'Hybrid'
                   WHEN category ILIKE '%gold%' OR category ILIKE '%commodity%'
                        THEN 'Gold'
                   WHEN category ILIKE ANY(ARRAY['%international%','%global%',
                                                  '%overseas%','%us equity%',
                                                  '%nasdaq%'])
                        THEN 'International'
                   ELSE 'Equity'
               END
             WHERE asset_class IS NULL
            """
        )
