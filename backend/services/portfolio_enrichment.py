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


def derive_action_badge(
    scores: Optional[Dict[str, Any]],
    recommendation: Optional[str],
    *,
    is_regular_plan: bool = False,
    high_overlap: bool = False,
) -> Dict[str, Any]:
    """Badge per user-approved logic. Returns {action, tone, emoji, reason}."""
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
        return {**SWITCH, "reason": " · ".join(parts) or "Switch candidate."}
    if a >= 70 and q >= 65:
        return {**ADD,
                "reason": f"Add {a:.0f} · Quality {q:.0f} — fits portfolio gap."}
    return {**HOLD,
            "reason": f"Quality {q:.0f} · Health {h:.0f} — maintain position."}


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
) -> List[Dict[str, Any]]:
    """Build a 0-N list of actionable top-of-page alerts."""
    alerts: List[Dict[str, Any]] = []
    # Allocation drift
    for bucket, ideal_pct in ideal.items():
        actual = alloc.get(bucket, 0.0)
        drift = actual - ideal_pct
        if drift >= 15:
            alerts.append({
                "severity": "warning",
                "title": f"Overexposed to {bucket.capitalize()}",
                "detail": f"{actual:.0f}% in {bucket} vs recommended {ideal_pct:.0f}%.",
                "component": "allocation",
            })
        elif drift <= -15:
            alerts.append({
                "severity": "warning",
                "title": f"Underweight {bucket.capitalize()}",
                "detail": f"{actual:.0f}% vs recommended {ideal_pct:.0f}% — consider rebalancing.",
                "component": "allocation",
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
    for rd in (health_payload or {}).get("risk_drivers", [])[:3]:
        alerts.append({
            "severity": "info",
            "title": rd.get("label") or "Risk driver",
            "detail": rd.get("detail") or "",
            "component": rd.get("component") or "health",
        })
    # Unscored fundamentals
    if unscored_equity_count > 0 and total_equity_count > 0:
        alerts.append({
            "severity": "info",
            "title": f"{unscored_equity_count} stocks not yet scored",
            "detail": (
                f"{unscored_equity_count}/{total_equity_count} equity holdings lack "
                "fundamentals — click to trigger refresh."
            ),
            "component": "data_coverage",
            "action_hint": "refresh_stock_fundamentals",
        })
    return alerts


# ── Main orchestrator: enriched holdings for UI ────────────────────────
async def build_enriched_portfolio(user_id: str) -> Dict[str, Any]:
    """Build the full `actionable portfolio` payload for the new UI.

    Returns:
      {
        holdings: [ {core + scores + action + xirr + switch_hint} ],
        alerts: [...],
        totals: {count, value_rs, invested_rs, pnl_rs, pnl_pct, xirr_pct},
        coverage_pct: % of equity holdings with scores,
        health: portfolio_health payload,
      }
    """
    from deps import db
    from services import portfolio_health as ph
    from services import pg_client

    holdings = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(2000)
    if not holdings:
        return {"holdings": [], "alerts": [], "totals": {}, "coverage_pct": 0,
                "health": None}

    # Load stock scores in bulk
    stock_scores_by_sym: Dict[str, Dict[str, Any]] = {}
    try:
        pool = await pg_client.get_pool()
        if pool is not None:
            symbols = [
                (h.get("nse_symbol") or "").upper()
                for h in holdings if (h.get("asset_type") or "").lower() == "equity"
            ]
            symbols = [s for s in symbols if s]
            if symbols:
                async with pool.acquire() as conn:
                    rows = await conn.fetch(
                        """SELECT ss.nse_symbol, sm.sector, sm.cap_bucket,
                                  ss.quality_score, ss.health_score,
                                  ss.exit_score, ss.add_score,
                                  ss.recommendation, ss.recommendation_reason,
                                  ss.low_confidence
                           FROM stock_scores ss
                           JOIN stock_master sm ON sm.nse_symbol = ss.nse_symbol
                           WHERE ss.nse_symbol = ANY($1::text[])""",
                        symbols,
                    )
                for r in rows:
                    stock_scores_by_sym[r["nse_symbol"]] = {
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
                    }
    except Exception as e:  # noqa: BLE001
        logger.warning(f"enriched_portfolio: stock score join failed: {e}")

    # Load MF V3 scores via the existing v3_portfolio endpoint's logic
    mf_scores_by_name: Dict[str, Dict[str, Any]] = {}
    mf_candidates: List[Dict[str, Any]] = []
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
                    mf_scores_by_name[key] = {
                        "scores": {
                            "quality": v3.get("quality_score"),
                            "health":  v3.get("health_score"),
                            "exit":    v3.get("exit_score"),
                            "add":     v3.get("add_score"),
                        },
                        "category": v3.get("category"),
                        "expense_ratio": (v3.get("v3_primitives") or {}).get("expense_ratio_direct"),
                    }
    except Exception as e:  # noqa: BLE001
        logger.warning(f"enriched_portfolio: MF V3 join failed: {e}")

    # Portfolio Health (for risk drivers + totals)
    try:
        hr = await ph.build_portfolio_health(user_id)
        health_payload = hr.to_dict()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"enriched_portfolio: health failed: {e}")
        health_payload = None

    # Build per-holding rows
    enriched: List[Dict[str, Any]] = []
    total_val = 0.0
    total_inv = 0.0
    alloc: Dict[str, float] = {}
    scored_equities = 0
    total_equities = 0
    for h in holdings:
        at = (h.get("asset_type") or "").lower()
        qty = float(h.get("quantity") or 0)
        bp = float(h.get("buy_price") or 0)
        cp = float(h.get("current_price") or 0)
        val = qty * cp
        inv = qty * bp
        total_val += val
        total_inv += inv
        name_l = (h.get("name") or "").lower()

        # Lookup scores
        score_bundle: Optional[Dict[str, Any]] = None
        rec: Optional[str] = None
        rec_reason: Optional[str] = None
        category: Optional[str] = h.get("category")
        expense_ratio: Optional[float] = None
        is_regular = "regular" in name_l and "direct" not in name_l

        if at == "equity":
            total_equities += 1
            sym = (h.get("nse_symbol") or "").upper()
            s = stock_scores_by_sym.get(sym)
            if s:
                scored_equities += 1
                score_bundle = s["scores"]
                rec = s["recommendation"]
                rec_reason = s["recommendation_reason"]
        elif at in ("mutual_fund", "etf"):
            m = mf_scores_by_name.get(name_l)
            if m:
                score_bundle = m["scores"]
                category = category or m.get("category")
                expense_ratio = m.get("expense_ratio")

        composite = composite_score(score_bundle)
        badge = derive_action_badge(score_bundle, rec,
                                     is_regular_plan=is_regular, high_overlap=False)
        xirr_pct = _holding_xirr(h.get("buy_date"), bp, cp, qty)

        enriched.append({
            "holding_id": h.get("holding_id"),
            "name": h.get("name"), "isin": h.get("ticker"),
            "nse_symbol": h.get("nse_symbol"),
            "asset_type": at, "sector": h.get("sector"),
            "category": category,
            "quantity": qty, "buy_price": bp, "current_price": cp,
            "buy_date": h.get("buy_date"),
            "value_rs": round(val, 2), "invested_rs": round(inv, 2),
            "pnl_rs": round(val - inv, 2),
            "pnl_pct": round((val - inv) / inv * 100, 2) if inv > 0 else 0,
            "xirr_pct": round(xirr_pct, 2) if xirr_pct is not None else None,
            "is_regular_plan": is_regular,
            "scores": score_bundle,
            "composite_score": composite,
            "recommendation": rec,
            "recommendation_reason": rec_reason,
            "action_badge": badge,
            "expense_ratio": expense_ratio,
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

    if total_val > 0:
        alloc = {k: round((v / total_val) * 100, 1) for k, v in alloc.items()}

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

    # Portfolio XIRR from all flows
    flows = []
    for h in holdings:
        qty = float(h.get("quantity") or 0); bp = float(h.get("buy_price") or 0)
        cp = float(h.get("current_price") or 0)
        if h.get("buy_date") and qty > 0 and bp > 0:
            try:
                bd = datetime.strptime(h["buy_date"][:10], "%Y-%m-%d").date()
                flows.append((bd, -bp * qty))
            except (ValueError, TypeError):
                pass
    if flows:
        flows.append((datetime.now(timezone.utc).date(), total_val))
        port_xirr = xirr(flows)
        port_xirr_pct = round(port_xirr * 100, 2) if port_xirr is not None else None
    else:
        port_xirr_pct = None

    alerts = derive_portfolio_alerts(
        health_payload=health_payload,
        alloc=alloc, ideal=ideal_alloc,
        risk_profile_user=risk_user, risk_profile_portfolio=risk_port,
        unscored_equity_count=(total_equities - scored_equities),
        total_equity_count=total_equities,
    )

    coverage_pct = round((scored_equities / total_equities) * 100, 1) if total_equities else 100.0

    return {
        "holdings": enriched,
        "alerts": alerts,
        "totals": {
            "count": len(enriched),
            "value_rs": round(total_val, 2),
            "invested_rs": round(total_inv, 2),
            "pnl_rs": round(total_val - total_inv, 2),
            "pnl_pct": round((total_val - total_inv) / total_inv * 100, 2) if total_inv else 0,
            "xirr_pct": port_xirr_pct,
        },
        "coverage_pct": coverage_pct,
        "allocation_actual": alloc,
        "allocation_ideal": ideal_alloc,
        "health": health_payload,
    }
