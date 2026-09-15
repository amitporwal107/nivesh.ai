"""v3 technical extensions (PRD §6-12): volume ratios and acceleration, ATR ratios (compression), MACD, ADX,
Donchian position, 100/200-DMA distance, range contraction. All from the symbol's own bars up to T."""
import numpy as np
import pandas as pd
import pytest

from nidp.tests.services.tpd_model.conftest import make_panel, weekday_sessions


def _window(n=300, seed=3):
    p = make_panel(["ACME"], weekday_sessions("2025-01-01", n), seed=seed)
    return p.sort_values("as_of_date").reset_index(drop=True)


def test_feature_names_are_declared_and_all_returned():
    from nidp.services.tpd_model.technical_ext import TECHNICAL_EXT_FEATURES, extended_technical

    f = extended_technical(_window())
    assert set(f) == set(TECHNICAL_EXT_FEATURES) and len(TECHNICAL_EXT_FEATURES) >= 12
    assert all(isinstance(v, float) for v in f.values())


def test_volume_ratios_exclude_today_from_the_baseline():
    from nidp.services.tpd_model.technical_ext import extended_technical

    w = _window()
    w["volume"] = 1000
    w.loc[w.index[-1], "volume"] = 3000
    f = extended_technical(w)
    assert f["vol_ratio_5"] == pytest.approx(3.0) and f["vol_ratio_20"] == pytest.approx(3.0)
    assert f["vol_ratio_250"] == pytest.approx(3.0)


def test_volume_acceleration_is_a_ratio_of_trailing_means():
    from nidp.services.tpd_model.technical_ext import extended_technical

    w = _window()
    w["volume"] = 1000
    w.loc[w.index[-5:], "volume"] = 2000        # last 5 sessions doubled
    f = extended_technical(w)
    assert f["vol_accel_5_20"] == pytest.approx(2000 / ((15 * 1000 + 5 * 2000) / 20))


def test_atr_ratios_are_one_on_a_constant_range_series():
    from nidp.services.tpd_model.technical_ext import extended_technical

    w = _window()
    w["close"] = 100.0
    w["open"] = 100.0
    w["high"], w["low"] = 101.0, 99.0
    f = extended_technical(w)
    assert f["atr5_atr20"] == pytest.approx(1.0) and f["atr20_atr100"] == pytest.approx(1.0)


def test_compression_shows_in_atr_ratios():
    from nidp.services.tpd_model.technical_ext import extended_technical

    w = _window()
    w["close"], w["open"] = 100.0, 100.0
    w["high"], w["low"] = 105.0, 95.0
    w.loc[w.index[-10:], ["high", "low"]] = [[101.0, 99.0]] * 10   # range shrinks in the last 10 sessions
    f = extended_technical(w)
    assert f["atr5_atr20"] < 1.0


def test_donchian_position_and_range_contraction():
    from nidp.services.tpd_model.technical_ext import extended_technical

    w = _window()
    w["high"], w["low"], w["close"] = 110.0, 90.0, 100.0
    w.loc[w.index[-1], ["high", "low", "close"]] = [110.0, 90.0, 110.0]
    f = extended_technical(w)
    assert f["donchian20_pos"] == pytest.approx(1.0)
    assert 0.0 <= f["adx14"] <= 100.0
    assert f["range20_vs_100"] == pytest.approx(1.0)


def test_long_averages_need_enough_bars():
    from nidp.services.tpd_model.technical_ext import extended_technical

    f = extended_technical(_window(n=150))
    assert np.isnan(f["dist_sma200"]) and not np.isnan(f["dist_sma100"])


def test_only_bars_in_the_window_matter():
    from nidp.services.tpd_model.technical_ext import extended_technical

    w = _window()
    a = extended_technical(w)
    b = extended_technical(w.iloc[-260:])
    for k in ("vol_ratio_20", "atr5_atr20", "macd_hist_pct", "dist_sma100", "donchian20_pos"):
        assert a[k] == pytest.approx(b[k], rel=1e-9), k
