"""The Strategy Builder's rule constants (PRD §16.4, §16.9, §17.5). One dict, versioned, returned with every plan.

Change a constant here and bump STRATEGY_RULES_VERSION: a saved plan carries the version it was built with.
"""
from __future__ import annotations

STRATEGY_RULES_VERSION = "strategy-rules.v1.6 (2026-10-27)"
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
    # Cash-flow quality (nidp.stock_features_daily.cfo_pat_ratio = the latest financial year's cash from operations / trailing-twelve-month
    # profit after tax). A documented heuristic, not a validated threshold. At or above `strong_at_or_above` the profit is backed by cash
    # ("up"); below `weak_below` it is not ("down"); in between "flat". Against the view: up supports bullish, down supports bearish.
    "cash_flow": {"measure": "cfo_pat_ratio (annual CFO / TTM PAT)", "strong_at_or_above": 1.0, "weak_below": 0.7},
    # Ownership changes (nidp.shareholding_pattern, DaaS /v1/shareholding/{symbol}; bulk and block deals, DaaS /v1/flows/*-deals).
    # A figure's change is the newest quarter that has it minus the previous quarter that has it (so a quarter with only a pledge row
    # does not hide the holding split). A change inside +/- min_change_pp is "flat". Promoter, FII, DII and mutual-fund holdings rising
    # are "up" (bullish); the promoter pledge rising is "down". Deals: net bought minus sold quantity over the last `deal_window_days`
    # days as a percent of the company's shares; inside +/- deal_min_net_pct_of_shares it is "flat".
    "ownership": {"min_change_pp": 0.25, "deal_window_days": 30, "deal_min_net_pct_of_shares": 0.1, "stale_after_days": 200,
                  "deal_coverage_tolerance_days": 3},
    # Live broker quotes (read-only, the user's own connected broker session). A quote whose last trade is at most this old is live,
    # older is delayed. A spread wider than wide_spread_pct of the mid price is flagged.
    "quotes": {"live_max_age_seconds": 120, "wide_spread_pct": 10.0, "read_timeout_seconds": 10.0},
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
    "sizing": {"formula": "units = floor((risk budget - fixed costs) / (risk per unit + estimated round-trip costs per unit at "
                          "the stop)), capped by floor(capital x max allocation % / entry value per unit), rounded down to whole "
                          "lots; for an option structure the risk per unit is already its worst net loss"},
    # The user's Chartink dashboard as a second source of opportunities (services/chartink_desk). A Chartink scan is the user's own screen: a rule
    # match, not validated, not a probability. Chartink-only stocks (hits that the AI scanner does not list) follow the scanner's ideas, ranked by the
    # number of enabled bullish scans that listed them, then by 20-session traded value, and pass the same eligibility gates as scanner stocks.
    "chartink": {
        "include_default": True,
        "limit_default": 4, "limit_max": 8,
        "stale_after_calendar_days": 4,
        "eod_after_ist": "15:40",
        "ranking": "Chartink-only ideas follow the AI scanner's ideas; they are ranked by the number of enabled bullish Chartink scans that listed the stock, "
                   "then by 20-session traded value. That is a count of the user's own scans, not a probability and not a score.",
        "gates": "the same eligibility gates as scanner stocks (the scan snapshot: price, 20-session traded value, reference data, series EQ or BE, not an ETF, "
                 "price band, not at its band limit, traded value of at least the liquidity gate); a stock that is not in the snapshot cannot be tested and is excluded",
        "evidence": "technical.chartink_scans: a bullish-tagged scan hit supports a bullish view and conflicts with a bearish one, a bearish-tagged hit the reverse; "
                    "hits of both tags are neutral; no hit is neutral; no dashboard, a stale or failed refresh is unavailable",
        "cash_family": "chartink_screen_signal",
        "cash_rule": "A stock the scanner lists in no bucket, with at least one enabled bullish Chartink hit, gets a cash candidate whose stop, targets and sizing "
                     "come from the chart engine's ATR rule (ATR_2X_STOP); the same reward : risk, liquidity and event gates as every other candidate apply",
        "levels_label": "rule-based levels; the scan is the user's Chartink scan, not validated",
    },
    # Best picks from the user's Chartink scans (services/strategy_plan/picks.py): a deterministic, explainable evidence score, 0 to 100, over REAL
    # figures only. Each factor earns `weight x credit`; credit is 1 for a supporting reading, `neutral_credit` for a neutral one, 0 for a conflicting
    # or an UNAVAILABLE one (a missing figure is never neutral and never positive). The score is 100 x points earned / weight of the factors that apply to
    # the stock (the OI build-up factor applies to F&O stocks only). It is a rank of evidence, not a probability and not a forecast.
    "chartink_picks": {
        "label": "evidence score — not a probability",
        "limit_default": 5, "limit_max": 10, "evaluate_max": 12, "concurrency": 4,
        "weights": {"scan_confluence": 25, "trend": 12, "momentum": 10, "relative_volume": 8, "liquidity": 8, "oi_buildup": 10, "fundamentals": 10,
                    "event_risk": 8, "range_position": 5, "atr_risk": 4},
        "neutral_credit": 0.5,
        # Scan confluence: credit = (aligned scans - opposed_scan_penalty x opposed scans) / full_at_aligned_scans, clamped to 0..1. Aligned = enabled scans tagged
        # with the pick's direction (bullish for a long, bearish for a short); opposed = tagged the other way. Neutral-tagged scans count for nothing.
        "scan_confluence": {"full_at_aligned_scans": 3, "opposed_scan_penalty": 1.0},
        # Liquidity: 20-session traded value (Rs crore a day). Below setup_rules.LIQUIDITY min is excluded before scoring; from the gate to full_at_cr is neutral.
        "liquidity": {"full_at_cr": 50.0},
        # Relative volume: at or above rules.rvol_confirm supports, from 1.0 up to it is neutral, below 1.0 conflicts.
        "rvol": {"neutral_from": 1.0},
        # An RSI past the stretched/weak band in the pick's direction halves the momentum credit.
        "rsi_haircut": 0.5,
        # Fundamentals quality, from the feature row: ROE at or above roe_min_pct, debt-to-equity at or below debt_to_equity_max and cash conversion
        # (cfo_pat_ratio) at or above rules.cash_flow.strong_at_or_above are three tests. At least min_tests must be readable; all readable tests passed is
        # quality (supports a long, conflicts with a short), none passed is weak (the reverse), otherwise neutral.
        "fundamentals": {"roe_min_pct": 15.0, "debt_to_equity_max": 1.0, "min_tests": 2},
        # Distance from the 52-week extremes (feature row dist_52w_high_pct <= 0 and dist_52w_low_pct >= 0). A long is supported within near_pct of the
        # high and conflicted when more than far_pct below it; a short is supported within near_pct of the low and conflicted within near_pct of the high.
        "range_position": {"near_pct": 10.0, "far_pct": 40.0},
        "outcome": {
            "min_score": 55.0,
            # at least this share of the applicable weight must be readable, else the evidence is thin: Wait
            "min_available_weight_pct": 60.0,
            # this many conflicting factors, at least as many as supporting ones: No trade (mirrors rules.conflict)
            "min_conflicts": 3,
        },
        "rule": "Each Chartink stock that passes the scan-snapshot eligibility gates is scored on scan confluence, trend (EMA), momentum (MACD, 20-day change, RSI), "
                "relative volume, liquidity, F&O open-interest build-up (F&O stocks), fundamentals quality, event risk (results inside the horizon), distance from "
                "its 52-week extremes and ATR risk. A figure that could not be read earns nothing and is listed as unavailable. Thin or conflicting evidence, a score "
                "under the minimum, or a strategy plan that says wait or no trade, is Wait / No trade and the stock is not a pick. Strategies come from the Strategy "
                "Builder's plan; options are defined risk only and nothing is sent to a broker.",
    },
    "model_estimate": "withheld: no calibrated probability model exists for these setups (a scanner score is not a probability)",
}
