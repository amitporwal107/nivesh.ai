"""Settings for the F&O build-up candidates (v2, after docs/NIVESH_FO_SMART_MONEY_INTELLIGENCE_PRD.md section 7 and the user's
decisions of 2026-10-23).

EVERY number here is a research setting that has NOT been validated: no experiment has tested it out of sample. They are returned
to the caller as `rules` with the research status beside them, so the screen can say so. Nothing here is a probability."""
from __future__ import annotations

RULES_VERSION = "fno-candidates-v2"

# The four labels the research and the UI use for what a setting's evidence is.
RESEARCH_STATUSES = ("research_setting_not_validated", "research_result", "validated", "insufficient_evidence")

CATEGORIES = ("long_buildup", "short_buildup", "short_covering", "long_unwinding")

# The direction the plan engine is asked about for a category. Short covering and long unwinding are weaker readings than a
# fresh build-up (positions closing, not opening), which the card says in words.
DIRECTION = {"long_buildup": "bullish", "short_covering": "bullish", "short_buildup": "bearish", "long_unwinding": "bearish"}

CATEGORY_TEXT = {
    "long_buildup": "Price up and OI up: new long positions are being opened.",
    "short_buildup": "Price down and OI up: new short positions are being opened.",
    "short_covering": "Price up and OI down: shorts are closing. A weaker reading than a fresh build-up.",
    "long_unwinding": "Price down and OI down: longs are closing. A weaker reading than a fresh build-up.",
}

PER_DEFAULT = 5
PER_MAX = 10

RULES = {
    "version": RULES_VERSION,
    "research_status": "research_setting_not_validated",
    # Which stocks are considered at all, per category (the scan's own order is largest |OI change| first).
    "pool_per_category": 12,
    "min_futures_turnover_cr": 50.0,      # futures traded value that day, ₹ crore: below this the build-up is too thin to read
    "min_abs_price_chg_pct": 0.5,
    "min_abs_oi_chg_pct": 3.0,

    # Signal Strength: the PRD's stock weights, in points out of 100. A missing input is NEVER redistributed: the score keeps the
    # 100-point denominator, `coverage` is the share of the 100 that was available, and the score is marked incomplete.
    "signal_weights": {"oi_signal": 30, "price_behavior": 20, "volume": 15, "options_confirmation": 15, "cash_delivery": 10, "technical": 10},
    "signal_labels": {
        "oi_signal": "Futures OI signal", "price_behavior": "Futures price behaviour", "volume": "Volume / relative volume",
        "options_confirmation": "Options-chain confirmation", "cash_delivery": "Cash-market and delivery context", "technical": "Technical structure",
    },
    # Tradeability: its own score. The weights are this build's research setting (the PRD gives none).
    "tradeability_weights": {"liquidity": 50, "expiry_distance": 25, "spread_depth": 25},
    "tradeability_labels": {"liquidity": "Futures liquidity", "expiry_distance": "Distance to expiry", "spread_depth": "Spread and depth"},
    # A candidate is ranked (and published) only when each score's coverage reaches its minimum. Configurable.
    "min_coverage": {"signal_strength": 0.80, "tradeability": 0.50},

    # Scaling of the inputs to 0-100.
    "saturation": {"oi_chg_pct": 15.0, "price_chg_pct": 3.0},           # a 15% OI change / a 3% price move score full marks
    "oi_weaker_reading_factor": {"long_buildup": 1.0, "short_buildup": 1.0, "short_covering": 0.8, "long_unwinding": 0.8},
    "rvol": {"zero_score_at": 1.0, "full_score_at": 2.0},               # cash volume over its 20-day average
    "liquidity_full_multiple": 10.0,                                    # full marks at this multiple of the turnover floor
    "expiry_distance_days": {"zero_score_at": 1, "full_score_at": 7},
    # Entry is "extended" when the stock has already moved this many normal daily ranges (ATR % of price) in the trade's direction over five sessions.
    "extended_atr_multiple": 3.0,
    # PRD 10.5: a signal is never "confirmed" from one price-and-OI move.
    "state": {"unavailable_below_known": 3, "confirmed_min_other_checks": 2},

    # Six checks. A missing input is "unknown": never a pass and never a fail. They feed the cash/delivery and technical inputs of the
    # signal score and the entry / state fields; none of them is a score on its own.
    "checks": {
        "cash_confirms": "The cash market moved the same way as the futures that day.",
        "volume_elevated": "Relative volume (vol_z20) is at least 1.0 standard deviation above its 20-session history.",
        "delivery_rising": "The share of delivered volume has been rising over 10 sessions (deliv_trend10 above 0).",
        "trend_aligned": "The cash close is on the trade's side of both its 20-day and 50-day average.",
        "momentum_aligned": "RSI 14 and the MACD histogram agree with the direction and RSI is not already stretched.",
        "entry_not_extended": "The stock has not already moved more than 3 normal daily ranges in the trade's direction over 5 sessions, so an entry is still viable.",
    },
    "groups": {"cash_delivery": ["cash_confirms", "delivery_rising"], "technical": ["trend_aligned", "momentum_aligned"]},
    "vol_z_min": 1.0,
    "rsi_bullish_band": [50.0, 75.0],
    "rsi_bearish_band": [25.0, 50.0],

    # Fundamental Quality / Risk Context: a separate panel, NOT an input of any score. Six facts, each pass / fail / unknown.
    "fundamentals": {
        "roe_pct_min": 15.0, "roce_pct_min": 15.0, "debt_to_equity_max": 1.0, "pat_growth_yoy_pct_min": 0.0,
        "eps_growth_3y_cagr_pct_min": 10.0, "promoter_pledged_pct_max": 10.0,
        "min_known": 3, "strong_share": 0.7, "weak_share": 0.35,
    },
    "ranking": "Signal Strength points among candidates whose coverage meets the minimum, then the larger absolute OI change. Tradeability is shown beside it, never blended in.",
}


RESEARCH_EXPERIMENTS = (
    {"id": "fo-bt-95f4e5df42dc", "stage": "Stage A ranking backtest", "date": "2026-10-23", "data_window": {"from": "2025-12-29", "to": "2026-10-22"},
     "finding": "No ranking skill beyond picking at random from the same pool; no frozen setting was positive in both validation and test.",
     "doc": "docs/FO_RANKING_BACKTEST_FINDINGS_20261023.md"},
    {"id": "fo-b2-c4295fca6fbf", "stage": "Stage B2 expiry-curve study", "date": "2026-10-23", "data_window": {"from": "2025-10-01", "to": "2026-10-22"},
     "finding": "No hypothesis supported for near, next or far expiry, nor for cross-expiry agreement or state transitions; near-month short build-up is inconclusive (permutation p 0.06).",
     "doc": "docs/FO_STAGE_B2_FINDINGS_20261023.md"},
)


def research_block() -> dict:
    """The research status that travels with every response. The two completed experiments are listed with their findings; neither validated
    anything, so the status stays `research_setting_not_validated` and nothing here is `research_result` or `validated`."""
    lead = RESEARCH_EXPERIMENTS[0]
    return {
        "status": RULES["research_status"], "threshold_version": RULES_VERSION, "experiment_id": lead["id"], "data_window": dict(lead["data_window"]),
        "last_updated": max(e["date"] for e in RESEARCH_EXPERIMENTS), "experiments": [dict(e) for e in RESEARCH_EXPERIMENTS],
        "statuses": list(RESEARCH_STATUSES),
        "note": "Every threshold and weight on this screen is a research setting, not a validated one. The ranking orders candidates for review; it is not a proven selection method, "
                "and back-tests found no skill beyond a random pick from the same pool.",
    }


DISCLOSURE = (
    "These are heuristic readings of two figures (futures price and open interest), not proof of what traders intended. "
    "Rollovers, expiry and changes in who trades a contract distort them. Signal Strength, Tradeability and Strategy Quality are kept "
    "as separate scores and never blended; a missing input leaves its points unearned and is shown, it is not redistributed. All weights "
    "and thresholds are research settings that no out-of-sample test has validated. Fundamental quality is a separate context panel and "
    "is not part of any score. Research and hypothetical scenarios only: nothing here is advice and nothing is sent to a broker."
)
