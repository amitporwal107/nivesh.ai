"""v6 technical feature engine (PRD Ten-Percent Days v6 §5/§16, Phase 2). Values are checked against hand-computed
arithmetic on synthetic series, not against the implementation restated."""
import numpy as np
import pandas as pd
import pytest

from nidp.services.tpd_model.technical_v6 import (FEATURE_VERSION, FEATURES_V6, compute, momentum_features,
                                                  price_action_features, relative_features, structure_features,
                                                  trend_features, volatility_features, volume_features)


def _bars(n=260, start=100.0, step=0.004, seed=3, symbol="X"):
    """A gently rising series with a fixed wiggle: deterministic, so every expected value below is arithmetic."""
    rng = np.random.default_rng(seed)
    c = start * np.cumprod(1 + step + rng.normal(0, 0.004, n))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * 1.006
    l = np.minimum(o, c) * 0.994
    v = rng.integers(500_000, 1_500_000, n).astype(float)
    return pd.DataFrame({"symbol": symbol, "as_of_date": pd.bdate_range("2025-01-01", periods=n),
                         "open": o, "high": h, "low": l, "close": c, "volume": v,
                         "deliverable_pct": rng.uniform(30, 70, n)})


def test_every_declared_feature_is_returned_and_the_version_is_pinned():
    out = compute(_bars())
    assert set(out) == set(FEATURES_V6) and len(FEATURES_V6) == 31
    assert FEATURE_VERSION == "v6.0"


def test_no_feature_reads_a_bar_after_t():
    """PRD acceptance criterion 1: no look-ahead. What happens after T must not touch T's values, so wrecking the later
    bars of the same series and then cutting at T has to leave every feature identical."""
    full = _bars(n=280)
    clean = compute(full.iloc[:260])
    wrecked = full.copy()
    wrecked.loc[wrecked.index[260:], ["open", "high", "low", "close"]] *= 7.0      # a violent, impossible future
    wrecked.loc[wrecked.index[260:], "volume"] *= 50
    assert not wrecked.iloc[260:]["close"].equals(full.iloc[260:]["close"])        # the future really did change
    after = compute(wrecked.iloc[:260])
    for k in FEATURES_V6:
        a, b = clean[k], after[k]
        assert (np.isnan(a) and np.isnan(b)) or a == pytest.approx(b), k


def test_short_history_leaves_features_missing_rather_than_guessing():
    """PRD acceptance criterion 13: missing data stays missing."""
    out = compute(_bars(n=30))
    for k in ("trend_alignment_score", "volatility_percentile_60d", "bollinger_width_percentile",
              "distance_to_resistance_atr", "distance_to_support_atr"):
        assert np.isnan(out[k]), k
    assert not np.isnan(out["close_location_value"])          # geometry of today's bar needs no long window


def test_trend_efficiency_is_one_on_a_straight_line_and_low_on_churn():
    straight = np.arange(100, 130, dtype="float64")           # every step in the same direction
    t = trend_features(straight, straight * 1.01, straight * 0.99)
    assert t["trend_efficiency_20d"] == pytest.approx(1.0)
    assert t["higher_high_count_20d"] == 20.0                 # each of the last 20 highs above the one before
    churn = np.array([100 + (2 if i % 2 else 0) for i in range(30)], dtype="float64")
    assert volatility_features(churn, churn + 1, churn - 1) is not None
    assert trend_features(churn, churn + 1, churn - 1)["trend_efficiency_20d"] == pytest.approx(0.0, abs=0.06)


def test_ema_slope_and_alignment_follow_the_trend_direction():
    up = _bars(n=260, step=0.004)
    down = _bars(n=260, step=-0.004)
    tu, td = compute(up), compute(down)
    assert tu["ema20_slope_10d"] > 0 and td["ema20_slope_10d"] < 0
    assert tu["trend_alignment_score"] == 1.0                 # price > EMA20 > EMA50 > EMA100 > EMA200
    assert td["trend_alignment_score"] == 0.0


def test_momentum_acceleration_compares_the_last_five_days_with_the_five_before():
    c = np.r_[np.full(11, 100.0), 100.0]                      # flat
    flat = momentum_features(np.r_[np.full(20, 100.0)])
    assert flat["momentum_acceleration"] == pytest.approx(0.0)
    assert flat["positive_return_day_ratio_10d"] == 0.0
    speeding = np.r_[np.full(10, 100.0), np.linspace(100, 110, 6)]   # quiet, then a sharp run
    assert momentum_features(speeding)["momentum_acceleration"] > 0


def test_price_action_geometry_matches_hand_arithmetic():
    o = np.array([100.0]); h = np.array([110.0]); l = np.array([90.0]); c = np.array([105.0])
    p = price_action_features(np.r_[np.full(20, 100.0), o], np.r_[np.full(20, 101.0), h],
                              np.r_[np.full(20, 99.0), l], np.r_[np.full(20, 100.0), c])
    assert p["close_location_value"] == pytest.approx((105 - 90) / 20)      # 0.75
    assert p["body_pct_of_range"] == pytest.approx(5 / 20)                  # |105-100| / 20
    assert p["upper_wick_pct"] == pytest.approx((110 - 105) / 20)           # 0.25
    assert p["lower_wick_pct"] == pytest.approx((100 - 90) / 20)            # 0.50


def test_a_locked_bar_has_no_geometry_and_reports_nan_rather_than_zero():
    flat = np.full(20, 50.0)
    p = price_action_features(flat, flat, flat, flat)
    assert np.isnan(p["close_location_value"]) and np.isnan(p["body_pct_of_range"])


def test_up_down_volume_and_cmf_read_the_direction_of_the_money():
    n = 25
    c = np.array([100 + i for i in range(n)], dtype="float64")            # every day up
    h, l = c * 1.01, c * 0.99
    v = np.full(n, 1_000_000.0)
    up = volume_features(c, h, l, v)
    assert np.isnan(up["up_volume_down_volume_ratio_10d"]) or up["up_volume_down_volume_ratio_10d"] == np.inf or up["up_volume_down_volume_ratio_10d"] > 100
    assert up["obv_slope_10d"] > 0
    down = volume_features(c[::-1].copy(), h[::-1].copy(), l[::-1].copy(), v)
    assert down["obv_slope_10d"] < 0


def test_cmf_is_positive_when_closes_sit_at_the_top_of_their_range():
    n = 25
    base = np.full(n, 100.0)
    h, l = base + 2, base - 2
    at_top, at_bottom = base + 1.8, base - 1.8
    assert volume_features(at_top, h, l, np.full(n, 1e6))["cmf20"] > 0.7
    assert volume_features(at_bottom, h, l, np.full(n, 1e6))["cmf20"] < -0.7


def test_delivery_zscore_flags_an_unusual_delivery_day():
    n = 25
    c = np.full(n, 100.0); h, l, v = c + 1, c - 1, np.full(n, 1e6)
    deliv = np.r_[np.full(n - 1, 40.0), 80.0]                 # steady 40%, then a spike
    assert volume_features(c, h, l, v, deliv)["delivery_zscore_20d"] > 3
    assert np.isnan(volume_features(c, h, l, v, None)["delivery_zscore_20d"])


def test_structure_measures_room_above_and_marks_a_breakout_at_zero_distance():
    n = 80
    c = np.r_[np.full(n - 1, 100.0), 100.0]
    h, l = c + 1, c - 1
    below = structure_features(h, l, c)
    assert below["distance_to_resistance_atr"] > 0            # a 60-day high of 101 sits above today's 100
    at_high = c.copy(); at_high[-1] = 120.0
    hh = h.copy(); hh[-1] = 121.0
    broken = structure_features(hh, l, at_high)
    assert broken["distance_to_resistance_atr"] == 0.0        # nothing overhead left in the window
    assert broken["distance_to_support_atr"] > 0


def test_failed_breakouts_count_only_intraday_breaks_that_did_not_hold():
    n = 70
    c = np.full(n, 100.0); h = c + 1.0; l = c - 1.0
    h[-1] = 120.0                                             # poked well above the prior 20-day high
    c[-1] = 99.0                                              # and closed back below it
    s = structure_features(h, l, c)
    assert s["failed_breakout_count_60d"] >= 1
    held = np.full(n, 100.0); hh = held + 1.0; hh[-1] = 120.0; held[-1] = 119.0
    assert structure_features(hh, l, held)["failed_breakout_count_60d"] == 0
    assert structure_features(hh, l, held)["breakout_age_days"] == 0.0     # it broke out today


def test_consolidation_counts_only_the_run_that_stays_inside_ten_percent():
    quiet = np.full(40, 100.0)
    h, l = quiet + 0.5, quiet - 0.5
    assert structure_features(h, l, quiet)["consolidation_days"] == 40.0
    wide = quiet.copy(); wl = l.copy(); wl[-5] = 50.0                      # one violent session breaks the run
    assert structure_features(h, wl, wide)["consolidation_days"] == 4.0


def test_relative_return_is_the_stock_minus_the_index_and_needs_an_aligned_series():
    c = np.array([100.0] * 20 + [110.0])                      # stock +10% on the last day
    idx = np.array([200.0] * 20 + [206.0])                    # index +3%
    r = relative_features(c, idx)
    assert r["relative_return_5d"] == pytest.approx(0.10 - 0.03)
    assert np.isnan(relative_features(c, None)["relative_return_5d"])
    assert np.isnan(relative_features(c, idx[:5])["relative_return_5d"])   # misaligned length is refused, not truncated


def test_volatility_percentile_places_today_against_the_stocks_own_history():
    n = 120
    rng = np.random.default_rng(1)
    c = 100 + np.cumsum(rng.normal(0, 0.5, n))
    h, l = c + 0.5, c - 0.5
    calm = volatility_features(c, h, l)
    assert 0.0 <= calm["volatility_percentile_60d"] <= 1.0
    h2, l2 = h.copy(), l.copy()
    h2[-1] += 12; l2[-1] -= 12                                # one very wide session
    loud = volatility_features(c, h2, l2)
    assert loud["true_range_zscore"] > 3 and loud["range_expansion_ratio"] > calm["range_expansion_ratio"]
