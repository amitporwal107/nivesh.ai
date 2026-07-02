"""Pure response-shapers mapping goal-engine output onto the frontend API
contract (frontend-v5 goal.contract.ts — MonteCarloRes / WhatIfRes).

Kept dependency-free so it is unit-testable and reusable. This is the canonical
fix for the FE↔BE contract-drift bug class (WORK-0076 / epic 0.7): the engine's
raw field names (on_track_pct, monte_carlo{prob_success_pct, p5/p50/p95}) were
leaking to the API and never matched what the adapter's zod contract expected
(success_probability_pct, on_track, corpus_projections{p10/p50/p90}, verdict,
persisted). We now emit a SUPERSET: the raw engine dict PLUS the contract fields,
so both the frontend adapter and the existing backend tests are satisfied.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

ON_TRACK_THRESHOLD_PCT = 70.0


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _corpus_projections(mc: Dict[str, Any]) -> Dict[str, float]:
    """FE contract wants p10/p50/p90; engine emits p10/p90 (added) and p5/p95
    as a fallback for older payloads."""
    return {
        "p10_rs": _num(mc.get("p10_corpus_rs", mc.get("p5_corpus_rs"))),
        "p50_rs": _num(mc.get("median_corpus_rs")),
        "p90_rs": _num(mc.get("p90_corpus_rs", mc.get("p95_corpus_rs"))),
    }


def monte_carlo_response(goal_id: str, ev_dict: Dict[str, Any], goal: Dict[str, Any]) -> Dict[str, Any]:
    """Shape a /simulate response to MonteCarloRes (superset of the engine dict)."""
    mc = ev_dict.get("monte_carlo") or {}
    return {
        **ev_dict,
        "goal_id": goal_id,
        "goal_name": goal.get("goal_name") or goal.get("name"),
        "target_amount_rs": goal.get("target_amount_rs"),
        "horizon_years": goal.get("horizon_years"),
        "monthly_sip_rs": goal.get("monthly_sip_rs") or 0,
        "current_corpus_rs": goal.get("current_corpus_rs") or 0,
        "success_probability_pct": _num(mc.get("prob_success_pct")),
        "on_track": bool(_num(ev_dict.get("on_track_pct")) >= ON_TRACK_THRESHOLD_PCT),
        "corpus_projections": _corpus_projections(mc),
        "simulation_runs": mc.get("n_runs"),
    }


def whatif_response(goal_id: str, ev_dict: Dict[str, Any], goal: Dict[str, Any],
                    params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Shape a /what-if response to WhatIfRes (superset of the engine dict)."""
    mc = ev_dict.get("monte_carlo") or {}
    current = _num(goal.get("on_track_pct"))
    what_if = _num(ev_dict.get("on_track_pct"))
    delta = round(what_if - current, 1)
    if delta >= 1:
        verdict = f"On-track improves by {delta:.1f} pp with this change."
    elif delta <= -1:
        verdict = f"On-track drops by {abs(delta):.1f} pp with this change."
    else:
        verdict = "Roughly no change to your on-track probability."
    return {
        **ev_dict,
        "goal_id": goal_id,
        "preview": True,
        "persisted": False,
        "what_if_params": dict(params or {}),
        "current_on_track_pct": current,
        "what_if_on_track_pct": what_if,
        "delta_on_track_pct": delta,
        "corpus_projections": _corpus_projections(mc),
        "verdict": verdict,
    }
