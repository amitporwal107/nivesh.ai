"""The Strategy Builder's rule constants (PRD §16.4, §16.9, §17.5). One dict, versioned, returned with every plan.

Change a constant here and bump STRATEGY_RULES_VERSION: a saved plan carries the version it was built with.
"""
from __future__ import annotations

STRATEGY_RULES_VERSION = "strategy-rules.v1.2 (2026-10-20)"
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
        "include_combinations": True,
    },
    # Liquidity gate: the scanner's own (services/positional_engine/setup_rules.py LIQUIDITY).
    "liquidity_min_traded_value_cr": 10.0,
    # End-of-day price older than this many calendar days before today is stale (a weekend plus one holiday).
    "stale_after_calendar_days": 4,
    # A trend/return reading inside this band is "flat".
    "flat_band_pct": 0.5,
    "rsi": {"stretched_above": 70.0, "weak_below": 30.0},
    # Sector strength: the sector indices that LIST the stock (nidp.index_constituents; a stock can be in several), each ranked by
    # its 1-month return among all the desk sector indices that have one. Rank 1 is the strongest. With n ranked sectors,
    # band_n = ceil(n x band_fraction): ranks 1..band_n are "top" (up), the last band_n ranks are "bottom" (down), the rest are
    # "middle" (flat). Several matching indices: the view's supporting indices against its conflicting ones, the larger count
    # wins, a tie is neutral.
    "sector_strength": {"metric": "ret_1m_pct", "band_fraction": 1 / 3, "top": "top third supports a bullish view",
                        "bottom": "bottom third conflicts with a bullish view", "middle": "neutral",
                        "several": "majority of the matching indices (supports vs conflicts); a tie is neutral"},
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
    # Combination strategies (cash legs together with F&O legs, all defined risk; the shares leg is lots x lot size shares, the F&O legs
    # are whole lots). Each family says WHEN it qualifies; a family that does not qualify is listed with the reason, never hidden.
    "combinations": {
        # Views each family can serve. Scanner ideas are long ideas, so "bullish" is the view the ideas route sends.
        "views": {"covered_call": ["bullish", "neutral"], "collar": ["bullish", "neutral"], "protective_put": ["bullish"],
                  "futures_protective_put": ["bullish"]},
        # Insurance has a reason or it is a cost drag: these families qualify only with event risk (results inside the horizon)
        # or high gap risk (the scanner's risk class "high": ATR(14) above setup_rules.RISK_BANDS high_above_pct of the close).
        "needs_hedge_reason": ["protective_put", "collar", "futures_protective_put"],
        # A long put makes the downside defined, so results inside the horizon do not block these families the way they block an
        # unhedged position (rules.defaults.avoid_events); the event is shown as a warning with the defined max loss.
        "event_hedged": ["protective_put", "collar", "futures_protective_put"],
        "short_call_strike": "the call wall (largest call open interest) when it lies above the at-the-money strike, else the first listed "
                             "strike at or beyond spot + one expected move",
        "long_put_strike": "the listed out-of-the-money put strike nearest the stop (the scanner's stop, else the chart engine's ATR stop)",
        "future": "the futures contract that expires on the options expiry (a synthetic call needs matching expiries)",
        "shares": "lots x lot size shares, at the last close; if the stock is already held, the shares leg is that position priced at the last close",
        "reward_risk": "reward = P&L at the gate scenario level, risk = loss if the price reaches the stop (both from the payoff calculation); "
                       "a long put or a short call changes that loss, so the ratio is not comparable with an unhedged cash idea: read max loss "
                       "and capital at risk beside it. When the premium received covers the loss at the stop, the ratio is undefined and the gate is not applied.",
        "sizing": "lots = floor(risk budget / loss per lot at the stop (the cash stop distance x lot size when the premium covers it)), "
                  "capped by the allocation cap on the deployed value per lot (shares or futures notional plus the net premium)",
    },
    "sizing": {"formula": "units = floor(risk budget / risk per unit), capped by floor(capital x max allocation % / "
                          "entry value per unit), rounded down to whole lots"},
    "model_estimate": "withheld: no calibrated probability model exists for these setups (a scanner score is not a probability)",
}
