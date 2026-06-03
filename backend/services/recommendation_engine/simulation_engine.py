"""
SimulationEngine — PRD IS-1, IS-2.

IS-1: Build before/after portfolio snapshots for each plan.
  - before: current holdings
  - after:  holdings minus EXIT/SWITCH targets + ADD targets as synthetic holdings
  - Computes projected_10y_value delta, weighted_er delta, mf_count delta

IS-2: Suppress actions where 10Y wealth improvement < threshold (default 0 = off).
  Tagged status="SUPPRESSED_MARGINAL" — kept in plan for audit, not shown in UI.

Output: plan["simulation"] dict  +  filtered action list.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from services.recommendation_engine.context import RecommendationContext

logger = logging.getLogger(__name__)


def _build_after_holdings(
    holdings: List[Dict[str, Any]],
    actions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Construct the 'after' holdings list:
      - Remove holdings targeted by EXIT/SWITCH actions
      - Add synthetic holdings for ADD actions
    """
    exit_names: set = set()
    exit_ids: set = set()
    add_synthetics: List[Dict[str, Any]] = []

    for a in actions:
        if a.get("status") in ("SUPPRESSED", "SUPPRESSED_MARGINAL"):
            continue
        if a.get("type") in ("EXIT", "SWITCH"):
            name = (a.get("asset_name") or "").lower().strip()
            if name:
                exit_names.add(name)
            iid = a.get("instrument_id")
            if iid:
                exit_ids.add(iid)
        elif a.get("type") == "ADD":
            fund_details = a.get("fund_details") or {}
            fund_name = a.get("asset_name") or fund_details.get("fund_name") or ""
            amount = float(a.get("amount") or 0)
            if fund_name and amount > 0:
                add_synthetics.append({
                    "asset_type": "mutual_fund",
                    "name": fund_name,
                    "quantity": 1,
                    "current_price": amount,
                    "buy_price": amount,
                    "instrument_id": None,
                })

    after: List[Dict[str, Any]] = []
    for h in holdings:
        iid = h.get("instrument_id")
        name = (h.get("name") or "").lower().strip()
        if iid and iid in exit_ids:
            continue
        if name and name in exit_names:
            continue
        after.append(dict(h))

    after.extend(add_synthetics)
    return after


class SimulationEngine:
    """IS-1: Before/after 10Y projection. IS-2: Marginal suppression (off by default)."""

    def __init__(self) -> None:
        self._last_simulation: Optional[Dict[str, Any]] = None

    def run(
        self,
        actions: List[Dict[str, Any]],
        ctx: RecommendationContext,
    ) -> tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """
        Returns (filtered_actions, simulation_dict).

        simulation_dict is stored in plan["simulation"].
        Marginal actions are tagged status="SUPPRESSED_MARGINAL" but kept in the list.
        """
        try:
            from services.switch_simulator import _portfolio_snapshot
        except ImportError:
            logger.warning("[SimulationEngine] switch_simulator unavailable — skipping simulation")
            return actions, None

        ep_cfg = (ctx.rules_cfg.get("engine_pipeline") or {})
        sim_cfg = ep_cfg.get("simulation") or {}
        threshold_rs = float(sim_cfg.get("marginal_improvement_threshold_rs", 0))

        # IS-1: before snapshot
        try:
            before = _portfolio_snapshot(ctx.holdings, "Before")
        except Exception as exc:
            logger.warning("[SimulationEngine] before snapshot failed: %s", exc)
            return actions, None

        # IS-1: after snapshot
        after_holdings = _build_after_holdings(ctx.holdings, actions)
        try:
            after = _portfolio_snapshot(after_holdings, "After")
        except Exception as exc:
            logger.warning("[SimulationEngine] after snapshot failed: %s", exc)
            return actions, None

        delta_10y = after["projected_10y_value_rs"] - before["projected_10y_value_rs"]
        delta_er = after["weighted_expense_ratio_pct"] - before["weighted_expense_ratio_pct"]
        delta_mf_count = after["mf_count"] - before["mf_count"]

        suppressed_marginal = 0

        # IS-2: suppress actions with no significant 10Y improvement
        if threshold_rs > 0:
            for a in actions:
                if a.get("status") in ("SUPPRESSED", "SUPPRESSED_MARGINAL"):
                    continue
                a_type = a.get("type")
                if a_type not in ("EXIT", "SWITCH"):
                    continue
                # Skip if action has a goal reason code
                rcodes = a.get("reason_codes") or []
                if "GOAL_ALIGNMENT" in rcodes:
                    continue
                if delta_10y < threshold_rs:
                    a["status"] = "SUPPRESSED_MARGINAL"
                    a["suppression_reason"] = (
                        f"10Y wealth improvement (₹{delta_10y:,.0f}) < "
                        f"threshold (₹{threshold_rs:,.0f})"
                    )
                    suppressed_marginal += 1

        simulation = {
            "before": before,
            "after": after,
            "delta": {
                "projected_10y_value_rs": round(delta_10y, 2),
                "weighted_expense_ratio_pct": round(delta_er, 2),
                "mf_count": delta_mf_count,
            },
            "suppressed_marginal_count": suppressed_marginal,
        }
        self._last_simulation = simulation

        logger.info(
            "[SimulationEngine] 10Y delta=₹%+,.0f ER delta=%+.2f%% mf_count delta=%+d suppressed=%d",
            delta_10y, delta_er, delta_mf_count, suppressed_marginal,
        )

        return actions, simulation
