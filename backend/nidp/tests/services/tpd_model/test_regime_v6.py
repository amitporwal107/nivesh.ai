"""v6 regime classifiers and cross-sectional strength (PRD Ten-Percent Days v6 §5.7, §5.8, §6, Phase 2)."""
import numpy as np
import pandas as pd
import pytest

from nidp.services.tpd_model.regime_v6 import (MARKET_TRENDS, REGIME_VERSION, TECHNICAL_REGIMES, breadth_and_dispersion,
                                               cross_sectional_strength, market_regime, technical_regime)


def _session(rows):
    return pd.DataFrame(rows)


def test_sector_relative_strength_is_measured_against_that_session_only():
    s = _session([{"symbol": "A", "ret20": 0.20, "sector": "IT"}, {"symbol": "B", "ret20": 0.10, "sector": "IT"},
                  {"symbol": "C", "ret20": 0.00, "sector": "IT"}, {"symbol": "D", "ret20": -0.10, "sector": "Pharma"}])
    out = cross_sectional_strength(s).set_index("symbol")
    assert out.loc["A", "sector_relative_strength"] == pytest.approx(0.20 - 0.10)   # IT median is B's 0.10
    assert out.loc["C", "sector_relative_strength"] == pytest.approx(-0.10)
    assert out.loc["A", "relative_strength_rank_universe"] == pytest.approx(1.0)
    assert out.loc["D", "relative_strength_rank_universe"] == pytest.approx(0.25)


def test_a_sector_too_small_to_have_a_median_gets_no_sector_figure():
    """Two stocks are not a sector: a median of them says nothing, so it stays missing rather than inventing one."""
    s = _session([{"symbol": "A", "ret20": 0.20, "sector": "Tiny"}, {"symbol": "B", "ret20": 0.10, "sector": "Tiny"},
                  {"symbol": "C", "ret20": 0.05, "sector": "Big"}, {"symbol": "D", "ret20": 0.04, "sector": "Big"},
                  {"symbol": "E", "ret20": 0.03, "sector": "Big"}])
    out = cross_sectional_strength(s).set_index("symbol")
    assert np.isnan(out.loc["A", "sector_relative_strength"])
    assert np.isnan(out.loc["A", "relative_strength_rank_sector"])
    assert out.loc["C", "sector_relative_strength"] == pytest.approx(0.01)          # Big's median is 0.04
    assert np.isnan(cross_sectional_strength(_session([{"symbol": "X", "ret20": 0.1, "sector": None}]))
                    .set_index("symbol").loc["X", "sector_relative_strength"])


def test_breadth_is_the_share_of_the_universe_that_rose():
    s = _session([{"symbol": s_, "ret1": r, "sector": "IT"} for s_, r in
                  [("A", 0.01), ("B", 0.02), ("C", -0.01), ("D", -0.02)]])
    assert breadth_and_dispersion(s)["breadth_up_share"] == pytest.approx(0.5)


def _index(n=200, drift=0.001, start=20000.0):
    return start * np.cumprod(np.full(n, 1 + drift))


def test_market_trend_reads_the_sma_stack():
    up = market_regime(_index(drift=0.002))
    assert up["market_trend"] == "BULL_TREND" and up["index_vs_sma20"] > 0
    down = market_regime(_index(drift=-0.002))
    assert down["market_trend"] == "BEAR_TREND"
    flat = market_regime(_index(drift=0.0))
    assert flat["market_trend"] == "RANGE_BOUND"
    assert all(r["market_trend"] in MARKET_TRENDS for r in (up, down, flat))


def test_a_hard_fall_with_no_participation_is_a_sell_off_not_just_a_downtrend():
    c = _index(drift=0.001)
    c[-5:] = c[-6] * np.array([0.99, 0.98, 0.97, 0.96, 0.95])         # −5% over the last five sessions
    assert market_regime(c, breadth_up_share=0.10)["market_trend"] == "BROAD_MARKET_SELL_OFF"
    # the same fall with half the market still rising is not a broad sell-off
    assert market_regime(c, breadth_up_share=0.50)["market_trend"] != "BROAD_MARKET_SELL_OFF"


def test_volatility_is_scored_against_the_index_its_own_history():
    """The yardstick is the index's own last 120 readings, so it answers "violent for this market", not an absolute."""
    n = 200
    c = _index(n=n, drift=0.0005)
    h, l = c * 1.02, c * 0.98                                         # a wide-ranging market for most of the window
    settled_h, settled_l = h.copy(), l.copy()
    settled_h[-25:] = c[-25:] * 1.002; settled_l[-25:] = c[-25:] * 0.998   # then it goes quiet
    calm = market_regime(c, settled_h, settled_l)
    assert calm["market_volatility"] == "LOW_VOLATILITY" and calm["index_atr_percentile_120d"] <= 0.20
    loud_h, loud_l = h.copy(), l.copy()
    loud_h[-20:] = c[-20:] * 1.08; loud_l[-20:] = c[-20:] * 0.92      # or the last month turns violent
    loud = market_regime(c, loud_h, loud_l)
    assert loud["market_volatility"] == "HIGH_VOLATILITY" and loud["index_atr_percentile_120d"] >= 0.80
    # a market whose volatility never changes is neither high nor low today
    steady = market_regime(c, h, l)
    assert steady["market_volatility"] == "NORMAL_VOLATILITY"


def test_a_short_index_history_refuses_to_call_a_regime():
    out = market_regime(_index(n=30))
    assert out["market_trend"] is None and out["market_volatility"] is None
    assert out["regime_version"] == REGIME_VERSION


def test_sector_rotation_needs_sectors_apart_and_an_index_going_nowhere():
    c = _index(drift=0.0)                                             # flat index
    hist = np.full(40, 0.002)                                         # dispersion has been low for weeks
    hot = market_regime(c, sector_dispersion=0.02, dispersion_history=hist)
    assert hot["sector_rotation"] is True
    calm = market_regime(c, sector_dispersion=0.001, dispersion_history=hist)
    assert calm["sector_rotation"] is False
    trending = _index(drift=0.004)                                    # index moving: not rotation, just a rally
    assert market_regime(trending, sector_dispersion=0.02, dispersion_history=hist)["sector_rotation"] is False


BASE = {"close": 100.0, "high": 101.0, "sma20": 95.0, "ret1": 0.005, "ret3": 0.01, "ret5": 0.02,
        "relative_volume_20d": 1.0, "true_range_zscore": 0.5, "close_location_value": 0.5,
        "prior_high_20": 105.0, "ema20": 98.0, "ema50": 94.0, "ema50_slope_20d": 0.03, "relative_return_20d": 0.04}


def test_the_prd_worked_example_classifies_as_trend_up():
    """§6: EMA20 > EMA50 AND EMA50 slope positive AND 20-day relative strength positive."""
    assert technical_regime(BASE) == "TREND_UP"


def test_the_most_specific_state_wins_when_several_rules_could_match():
    # a capitulation bar also satisfies DISTRIBUTION and HIGH_VOLATILITY_EVENT; the order decides
    cap = {**BASE, "ret1": -0.08, "relative_volume_20d": 3.0, "close_location_value": 0.1,
           "true_range_zscore": 5.0, "ret5": -0.10}
    assert technical_regime(cap) == "CAPITULATION"
    # without the heavy volume it is no longer capitulation but is still an outsized range
    assert technical_regime({**cap, "relative_volume_20d": 1.0}) == "HIGH_VOLATILITY_EVENT"
    # heavy volume, weak close, falling week, but an ordinary range: distribution
    assert technical_regime({**cap, "ret1": -0.01, "true_range_zscore": 0.5, "close_location_value": 0.2}) == "DISTRIBUTION"


def test_breakout_confirmed_needs_the_close_to_hold_above_the_prior_high():
    held = {**BASE, "close": 108.0, "high": 109.0, "prior_high_20": 105.0, "close_location_value": 0.8}
    assert technical_regime(held) == "BREAKOUT_CONFIRMED"
    failed = {**BASE, "close": 104.0, "high": 109.0, "prior_high_20": 105.0, "close_location_value": 0.2,
              "relative_volume_20d": 1.0, "ret5": 0.02}
    assert technical_regime(failed) == "BREAKOUT_ATTEMPT"


def test_a_dip_above_the_20day_average_is_a_mean_reversion_candidate_and_a_deeper_one_a_pullback():
    dip = {**BASE, "ret3": -0.05, "close": 100.0, "sma20": 95.0}
    assert technical_regime(dip) == "MEAN_REVERSION_CANDIDATE"
    pullback = {**BASE, "ret3": -0.02, "close": 97.0, "sma20": 99.0, "ema20": 98.0}
    assert technical_regime(pullback) == "PULLBACK_IN_UPTREND"


def test_an_unknown_state_returns_none_rather_than_defaulting_to_range_bound():
    assert technical_regime({**BASE, "ema20": float("nan"), "ema50": float("nan"), "relative_return_20d": float("nan")}) is None
    assert technical_regime({"close": float("nan")}) is None
    assert technical_regime({**BASE, "relative_return_20d": 0.0, "ema20": 98.0, "ema50": 94.0,
                             "ema50_slope_20d": 0.03}) == "RANGE_BOUND"


def test_every_label_returned_is_one_of_the_declared_regimes():
    for row in (BASE, {**BASE, "ret1": -0.08, "relative_volume_20d": 3.0, "close_location_value": 0.1},
                {**BASE, "close": 108.0, "close_location_value": 0.9}, {**BASE, "ret3": -0.05},
                {**BASE, "ema20": 94.0, "ema50": 98.0, "ema50_slope_20d": -0.02, "relative_return_20d": -0.05}):
        label = technical_regime(row)
        assert label is None or label in TECHNICAL_REGIMES, label
