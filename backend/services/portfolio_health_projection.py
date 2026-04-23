"""Portfolio Health Projection — What-If if action plan is fully implemented.

Given an action plan and current holdings, shadow-mutates a copy of the
holdings to reflect each PENDING action's effect, then re-runs the Health
engine. Returns:

  {
    "current": {health_score, grade, components},
    "projected": {health_score, grade, components},
    "delta": {total, per_component},
    "completed_count": int,   # already-done actions
    "pending_count": int,     # actions yet to do
    "message": str,           # human-readable summary
    "per_action_preview": [   # light per-action impact hint
      {"action_id", "type", "estimated_delta": float}
    ]
  }

Mutation rules (simplified, deterministic):
  - EXIT: remove the holding matching `asset_name`
  - TRIM: scale `quantity` by (1 - amount / current_value)
  - SWITCH (Regular → Direct): rename holding, reduce expense ratio
  - ADD (debt/hybrid gap fill): append a synthetic debt holding of `amount`

This is a projection, not a commitment — no DB writes.
"""
from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional

from services import portfolio_health as ph

logger = logging.getLogger(__name__)


# ── Mutation primitives ────────────────────────────────────────────────
def _match_holding(holdings: List[Dict[str, Any]], asset_name: str) -> Optional[int]:
    """Fuzzy match on scheme name (case/space-insensitive). Returns index."""
    if not asset_name:
        return None
    key = "".join(asset_name.lower().split())
    for i, h in enumerate(holdings):
        name = "".join((h.get("name") or "").lower().split())
        if key in name or name in key:
            return i
    return None


def _apply_exit(holdings: List[Dict[str, Any]], action: Dict[str, Any]) -> bool:
    idx = _match_holding(holdings, action.get("asset_name", ""))
    if idx is None:
        return False
    holdings.pop(idx)
    return True


def _apply_trim(holdings: List[Dict[str, Any]], action: Dict[str, Any]) -> bool:
    idx = _match_holding(holdings, action.get("asset_name", ""))
    if idx is None:
        return False
    h = holdings[idx]
    cur_val = float(h.get("quantity") or 0) * float(h.get("current_price") or 0)
    trim_amt = float(action.get("amount") or 0)
    if cur_val <= 0 or trim_amt <= 0:
        return False
    ratio = max(0.0, 1.0 - trim_amt / cur_val)
    h["quantity"] = float(h.get("quantity") or 0) * ratio
    return True


def _apply_switch_to_direct(holdings: List[Dict[str, Any]], action: Dict[str, Any]) -> bool:
    idx = _match_holding(holdings, action.get("asset_name", ""))
    if idx is None:
        return False
    h = holdings[idx]
    name = h.get("name") or ""
    if "regular" in name.lower():
        h["name"] = name.replace("Regular", "Direct").replace("regular", "direct")
    # Impact on expense modelled via name-based heuristic in compute_cost
    return True


def _apply_add_debt(holdings: List[Dict[str, Any]], action: Dict[str, Any]) -> bool:
    amt = float(action.get("amount") or 0)
    if amt <= 0:
        return False
    holdings.append({
        "holding_id": f"synthetic_{action.get('action_id', 'x')}",
        "user_id": "projection",
        "name": f"[Projected] {action.get('asset_name') or 'Debt Fund'}",
        "asset_type": "mutual_fund",
        "quantity": 1.0,
        "buy_price": amt,
        "current_price": amt,
        "sector": "Debt",
    })
    return True


def _mutate_for_action(holdings: List[Dict[str, Any]], action: Dict[str, Any]) -> bool:
    """Apply a single PENDING action to the shadow holdings list.
    Returns True if mutation succeeded."""
    atype = (action.get("type") or "").upper()
    codes = action.get("reason_codes") or []
    if atype == "EXIT":
        return _apply_exit(holdings, action)
    if atype == "TRIM":
        return _apply_trim(holdings, action)
    if atype == "SWITCH" or "REG_TO_DIRECT" in codes or "COST_LEAK" in codes:
        return _apply_switch_to_direct(holdings, action)
    if atype == "ADD" or "DEBT_GAP" in codes or "ALLOCATION_GAP" in codes:
        return _apply_add_debt(holdings, action)
    # Unknown type → no-op (don't count)
    return False


# ── Public API ─────────────────────────────────────────────────────────
async def project_health(user_id: str) -> Optional[Dict[str, Any]]:
    """Compute current + projected Health for `user_id`. Returns None if the
    user has no active plan OR no holdings."""
    from deps import db
    from services import action_plan_manager as _apm  # noqa: WPS433

    plan = await _apm.ActionPlanManager().get_active_plan(user_id)
    if not plan or not plan.get("actions"):
        return None

    # Current Health (live)
    current_hr = await ph.build_portfolio_health(user_id)
    current_payload = current_hr.to_dict()

    # Build shadow holdings (from Mongo)
    shadow = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(1000)
    shadow = copy.deepcopy(shadow)

    actions = plan.get("actions", [])
    completed = [a for a in actions if (a.get("status") or "").upper() == "COMPLETED"]
    pending = [a for a in actions if (a.get("status") or "").upper() in ("PENDING", "IN_PROGRESS")]

    # Shadow-apply every PENDING action. Completed actions already reflected
    # in the live holdings so we skip them here.
    mutated = 0
    for act in pending:
        try:
            if _mutate_for_action(shadow, act):
                mutated += 1
        except Exception as e:  # noqa: BLE001
            logger.warning(f"projection mutate failed for {act.get('action_id')}: {e}")

    # Compute projected Health against shadow holdings
    projected_payload = None
    if mutated > 0:
        try:
            projected_hr = await _build_health_from_holdings(user_id, shadow)
            projected_payload = projected_hr.to_dict()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"projection build_from_holdings failed: {e}")

    # Delta (per-component)
    delta_total = None
    delta_by_comp: Dict[str, float] = {}
    if projected_payload:
        delta_total = round(projected_payload["health_score"] - current_payload["health_score"], 2)
        for k in ("diversification", "risk", "cost", "performance"):
            c = (current_payload.get("components") or {}).get(k) or {}
            p = (projected_payload.get("components") or {}).get(k) or {}
            if c.get("score") is not None and p.get("score") is not None:
                delta_by_comp[k] = round(p["score"] - c["score"], 2)

    # Human-readable message
    if projected_payload and delta_total is not None:
        if delta_total >= 3:
            msg = (
                f"Completing the remaining {len(pending)} action(s) would lift your "
                f"Portfolio Health from {round(current_payload['health_score'])}/100 to "
                f"{round(projected_payload['health_score'])}/100 ({'+' if delta_total>=0 else ''}{delta_total})."
            )
        elif delta_total <= -3:
            msg = (
                f"Pending actions would DROP your Portfolio Health by {abs(delta_total)} points — "
                f"review before executing."
            )
        else:
            msg = (
                f"{len(completed)} action(s) done, {len(pending)} pending. "
                f"Projected Health change is marginal ({'+' if delta_total>=0 else ''}{delta_total})."
            )
    else:
        msg = (
            f"{len(completed)} action(s) already completed · {len(pending)} pending. "
            f"Projection unavailable for this plan."
        )

    return {
        "current": current_payload,
        "projected": projected_payload,
        "delta_total": delta_total,
        "delta_by_component": delta_by_comp,
        "completed_count": len(completed),
        "pending_count": len(pending),
        "mutated_action_count": mutated,
        "message": msg,
        "plan_id": plan.get("plan_id"),
    }


async def _build_health_from_holdings(
    user_id: str, shadow: List[Dict[str, Any]],
) -> ph.HealthResult:
    """Compute Health against a custom holdings list (shadow projection).
    Replicates the core of `build_portfolio_health` but skips DB fetch of
    holdings — everything else (V3 enrichment, overlap, risk profile) still
    comes from user state."""
    from deps import db as _db
    from services import portfolio_intelligence as _pintel
    from services import v3_integration as _v3i
    from services import stock_enricher as _enricher

    all_holdings = shadow
    mf_holdings = [h for h in all_holdings if (h.get("asset_type") or "").lower() in ("mutual_fund", "etf")]
    equity_holdings = [h for h in all_holdings if (h.get("asset_type") or "").lower() in ("equity", "stock")]

    if not all_holdings:
        return ph.HealthResult(
            health_score=0.0, grade="N/A", components={}, risk_drivers=[],
            low_confidence=True, summary="No holdings in projection.",
        )

    # Asset allocation
    alloc_actual: Dict[str, float] = {}
    total_val = 0.0
    for h in all_holdings:
        val = float(h.get("quantity") or 0) * float(h.get("current_price") or 0)
        if val <= 0:
            continue
        total_val += val
        bucket = ph._classify_asset(h)
        key = "hybrid" if bucket == "gold" else bucket if bucket in ("equity", "debt", "hybrid") else "other"
        alloc_actual[key] = alloc_actual.get(key, 0.0) + val
    if total_val > 0:
        alloc_actual = {k: (v / total_val) * 100.0 for k, v in alloc_actual.items()}

    user_doc = await _db.users.find_one({"user_id": user_id}, {"_id": 0}) or {}
    raw_rp = user_doc.get("risk_profile") or (user_doc.get("profile") or {}).get("risk_profile")
    ideal_alloc = ph._ideal_allocation(ph._normalise_risk(raw_rp), horizon_years=10.0)

    try:
        stock_funda = await _enricher.enrich_stocks_for_user(user_id)
    except Exception:  # noqa: BLE001
        stock_funda = {}

    mf_investments = [
        {
            "scheme_name": h.get("name"),
            "instrument_id": h.get("instrument_id"),
            "value": float(h.get("quantity") or 0) * float(h.get("current_price") or 0),
        }
        for h in mf_holdings
        if (float(h.get("quantity") or 0) * float(h.get("current_price") or 0)) > 0
    ]
    v3_by_id: Dict[str, Any] = {}
    if mf_investments:
        try:
            v3_map = await _v3i.enrich_candidates_with_v3(
                mf_investments=mf_investments, exit_candidates=[],
                mf_holdings=mf_holdings, portfolio_intelligence={},
            )
            for m in mf_investments:
                iid = m.get("instrument_id")
                v3 = _v3i.lookup_v3(iid, m.get("scheme_name", ""), v3_map)
                if iid and v3:
                    v3_by_id[iid] = v3
        except Exception:  # noqa: BLE001
            pass

    # Overlap (still use user's live portfolio_intelligence — cheap approximation)
    try:
        pi = await _pintel.compute_portfolio_intelligence(user_id)
    except Exception:  # noqa: BLE001
        pi = {}
    avg_overlap_pct: Optional[float] = None
    if pi and pi.get("pairwise_overlap") and pi.get("mf_investments"):
        val_by_iid = {m["instrument_id"]: m.get("amount_rs", 0)
                      for m in pi["mf_investments"] if m.get("instrument_id")}
        total_pair_w = 0.0
        weighted_ov = 0.0
        for pair in pi["pairwise_overlap"]:
            w = min(val_by_iid.get(pair["a"], 0.0), val_by_iid.get(pair["b"], 0.0))
            if w > 0:
                weighted_ov += float(pair.get("overlap_pct") or 0) * w
                total_pair_w += w
        if total_pair_w > 0:
            avg_overlap_pct = weighted_ov / total_pair_w

    mf_top_stocks = pi.get("top_stocks", []) if pi else []
    stock_weights = ph._stock_weights_for_concentration(equity_holdings, mf_top_stocks)

    divers = ph.compute_diversification(
        stock_weights=stock_weights,
        asset_allocation_actual=alloc_actual,
        asset_allocation_ideal=ideal_alloc,
        portfolio_overlap_pct=avg_overlap_pct,
    )

    instruments: List[Dict[str, Any]] = []
    if total_val > 0:
        for h in equity_holdings:
            val = float(h.get("quantity") or 0) * float(h.get("current_price") or 0)
            if val <= 0:
                continue
            sym = (h.get("nse_symbol") or "").upper()
            ent = stock_funda.get(sym, {})
            instruments.append({
                "weight_pct": (val / total_val) * 100.0,
                "vol_annual_pct": ent.get("vol_annual_pct"),
                "fallback_vol_annual_pct": _enricher.CAP_HEURISTICS["unknown"]["vol_annual_pct"],
            })
        for h in mf_holdings:
            val = float(h.get("quantity") or 0) * float(h.get("current_price") or 0)
            if val <= 0:
                continue
            bucket = ph._classify_asset(h)
            mf_vol = {"equity": 20.0, "debt": 3.0, "hybrid": 10.0}.get(bucket, 18.0)
            instruments.append({
                "weight_pct": (val / total_val) * 100.0,
                "vol_annual_pct": mf_vol, "fallback_vol_annual_pct": mf_vol,
            })
    dd_sum = 0.0; dd_w = 0.0
    for m in mf_investments:
        iid = m.get("instrument_id")
        v3 = v3_by_id.get(iid) if iid else None
        if not v3:
            continue
        prim = v3.get("v3_primitives") or {}
        dd = prim.get("max_drawdown_pct")
        if dd is not None:
            dd_sum += abs(float(dd)) * float(m.get("value", 0))
            dd_w += float(m.get("value", 0))
    portfolio_dd = (dd_sum / dd_w) if dd_w > 0 else None

    risk = ph.compute_risk(
        instruments=instruments, portfolio_drawdown_pct=portfolio_dd, correlation=0.5,
    )

    equity_value_rs = sum(
        float(h.get("quantity") or 0) * float(h.get("current_price") or 0)
        for h in equity_holdings
    )
    cost_bundle = ph._weighted_mf_expense(
        mf_investments, v3_by_id, equity_value_rs=equity_value_rs,
    )
    cost = ph.compute_cost(
        weighted_expense_ratio_pct=cost_bundle["expense_pct"],
        tax_drag_pct=None,
        regular_plan_weight_pct=cost_bundle["regular_plan_weight_pct"],
    )

    mf_avg = ph._portfolio_avg_health_from_v3(mf_investments, v3_by_id)
    total_inv = sum(float(h.get("quantity") or 0) * float(h.get("buy_price") or 0) for h in all_holdings)
    total_cur = sum(float(h.get("quantity") or 0) * float(h.get("current_price") or 0) for h in all_holdings)
    port_return_1y = ((total_cur - total_inv) / total_inv * 100.0) if total_inv > 0 else None
    benchmark_1y = 12.0 if port_return_1y is not None else None
    perf = ph.compute_performance(
        portfolio_return_1y_pct=port_return_1y,
        benchmark_return_1y_pct=benchmark_1y,
        sharpe=None, consistency_score=mf_avg.get("avg_consistency"),
    )

    return ph.compute_portfolio_health(
        diversification=divers, risk=risk, cost=cost, performance=perf,
    )
