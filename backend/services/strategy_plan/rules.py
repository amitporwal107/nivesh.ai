"""The Strategy Builder's rule constants (PRD §16.4, §16.9, §17.5). One dict, versioned, returned with every plan.

Change a constant here and bump STRATEGY_RULES_VERSION: a saved plan carries the version it was built with.
"""
from __future__ import annotations

STRATEGY_RULES_VERSION = "strategy-rules.v1 (2026-10-20)"
PLAN_SCHEMA = "strategy-plan.v1"

RULES = {
    "version": STRATEGY_RULES_VERSION,
    # Defaults the user can change; every default that was used is listed in plan.inputs.defaults_applied.
    "defaults": {
        "horizon_days": {"intraday": 1, "positional": 10, "longer_term": 60},
        "min_reward_risk": 1.5,
        "max_allocation_pct": 25.0,
        "avoid_events": True,
        "allow_multi_leg": True,
    },
    # Liquidity gate: the scanner's own (services/positional_engine/setup_rules.py LIQUIDITY).
    "liquidity_min_traded_value_cr": 10.0,
    # End-of-day price older than this many calendar days before today is stale (a weekend plus one holiday).
    "stale_after_calendar_days": 4,
    # A trend/return reading inside this band is "flat".
    "flat_band_pct": 0.5,
    "rsi": {"stretched_above": 70.0, "weak_below": 30.0},
    "rvol_confirm": 1.5,
    "rs_flat_band_pct": 1.0,
    # Conflicting evidence: this many conflicting items, and at least as many as supporting ones, in the directional
    # groups (market context, technical, derivatives) is No Trade.
    "conflict": {"min_conflicts": 3, "groups": ["market_context", "technical", "derivatives"]},
    # Targets (underlying price levels, scenarios not forecasts). R = the stop distance. The reward : risk gate reads the conservative level when a real resistance caps the move, else the base level.
    "targets": {"conservative": "the nearest 20-session resistance (support for a short) at least min_resistance_atr x ATR beyond the entry, else 1 x ATR(14)",
                "conservative_atr_multiple": 1.0, "min_resistance_atr": 0.5, "base_reward_multiple": 2.0, "optimistic_reward_multiple": 3.0,
                "stop_atr_multiple": 2.0, "min_stop_atr": 0.5},
    "valuation_peers": {"min_peers": 5, "max_peers_read": 20},
    "catalysts": {"filings_days": 30},
    "futures": {"min_days_to_expiry": 3},
    "options": {
        "min_days_to_expiry": 5,
        "max_days_to_expiry": 60,
        # Relative liquidity flags: a leg whose OI (volume) is below this percent of the median of the strikes
        # sent in the chain window is flagged. Zero OI or zero volume on the day blocks the leg.
        "low_oi_pct_of_median": 25.0,
        "low_volume_pct_of_median": 25.0,
        # Abnormal IV: a leg's IV outside the Tukey fences (Q1 - k x IQR, Q3 + k x IQR) of the chain window's own IVs.
        "iv_fence_k": 1.5,
        "iv_min_sample": 8,
        "condor_wall_min_expected_moves": 1.0,
    },
    "sizing": {"formula": "units = floor(risk budget / risk per unit), capped by floor(capital x max allocation % / "
                          "entry value per unit), rounded down to whole lots"},
    "model_estimate": "withheld: no calibrated probability model exists for these setups (a scanner score is not a probability)",
}
