"""Volume / delivery metrics must ignore bars they cannot compare.

prices_eod is now multi-source: days NSE's edge blocked us are filled
from BSE. Prices track across the two exchanges, but volume and delivery
measure one order book — BSE turnover runs roughly an order of magnitude
below NSE's. Left unmasked, a BSE bar reads as a volume collapse and
fires a false distribution signal.

Separately, a *missing* delivery figure used to be coerced to 0.0 (both
by `COALESCE(deliv_pct, 0.0)` in SQL and `float(r["deliv_pct"] or 0)` in
_to_arrays), which dragged deliv_pct_avg_20 toward zero and mis-scored
the accumulation pillar.
"""
from __future__ import annotations

import numpy as np
import pytest

from nidp.services.technical_indicator_engine.calculator import (
    delivery_stats,
    volume_stats,
)
from nidp.services.technical_indicator_engine.service import _to_arrays


def _rec(close=100.0, volume=1_000_000, deliv=50.0, source="NSE_BHAVCOPY"):
    return {"close_price": close, "open_price": close, "high_price": close * 1.01,
            "low_price": close * 0.99, "volume": volume, "deliv_pct": deliv,
            "source": source, "symbol": "X", "as_of_date": None}


# ── masking ──────────────────────────────────────────────────────────
def test_bse_bar_volume_is_masked_to_nan():
    _, _, _, _, vols, _ = _to_arrays([_rec(source="BSE_BHAVCOPY")])
    assert np.isnan(vols[0])


def test_bse_bar_delivery_is_masked_to_nan():
    *_, deliv = _to_arrays([_rec(source="BSE_BHAVCOPY")])
    assert np.isnan(deliv[0])


def test_nse_bar_volume_is_kept():
    _, _, _, _, vols, _ = _to_arrays([_rec(volume=1234, source="NSE_BHAVCOPY")])
    assert vols[0] == 1234


def test_missing_delivery_is_nan_not_zero():
    """The old code turned a missing figure into a real 0%."""
    *_, deliv = _to_arrays([_rec(deliv=None)])
    assert np.isnan(deliv[0])


def test_prices_from_a_bse_bar_are_still_used():
    """Only volume/delivery are untrusted — price continuity is the point."""
    closes, opens, highs, lows, _, _ = _to_arrays([_rec(close=250.0, source="BSE_BHAVCOPY")])
    assert closes[0] == 250.0 and highs[0] > 0 and lows[0] > 0 and opens[0] == 250.0


# ── volume_stats ─────────────────────────────────────────────────────
def test_masked_bars_do_not_deflate_the_baseline():
    """A BSE day inside the window must not drag avg_volume_20 down."""
    clean = np.array([1_000_000.0] * 21)
    withnan = clean.copy()
    withnan[5] = np.nan                      # a BSE day mid-window
    avg_clean, z_clean = volume_stats(clean)
    avg_nan, z_nan = volume_stats(withnan)
    assert avg_clean == pytest.approx(avg_nan)
    assert z_clean == pytest.approx(z_nan)


def test_zero_coercion_would_have_broken_it():
    """Pin the bug being fixed: zeros DO corrupt the baseline."""
    zeroed = np.array([1_000_000.0] * 21)
    zeroed[5] = 0.0
    avg_zero, _ = volume_stats(zeroed)
    avg_clean, _ = volume_stats(np.array([1_000_000.0] * 21))
    assert avg_zero < avg_clean


def test_nan_today_yields_no_score():
    v = np.array([1_000_000.0] * 21)
    v[-1] = np.nan
    assert volume_stats(v) == (None, None)


def test_too_few_comparable_bars_yields_no_score():
    v = np.array([1_000_000.0] * 21)
    v[:18] = np.nan                          # only 2 usable baseline bars
    assert volume_stats(v) == (None, None)


def test_real_volume_spike_still_scores():
    """With a masked bar in the window, a genuine spike must still score.

    Baseline needs real variance — a perfectly flat window has std 0 and
    volume_stats returns z=0.0 by design (the z-score is undefined).
    """
    rng = np.random.default_rng(7)
    v = np.append(rng.normal(1_000_000, 50_000, 20), 5_000_000.0)
    v[3] = np.nan                            # a BSE day inside the window
    avg, z = volume_stats(v)
    assert avg == pytest.approx(1_000_000, rel=0.1)
    assert z is not None and z > 3


# ── delivery_stats ───────────────────────────────────────────────────
def test_delivery_avg_ignores_nan():
    d = np.array([60.0] * 20)
    d[4] = np.nan
    avg, _ = delivery_stats(d)
    assert avg == pytest.approx(60.0)


def test_delivery_avg_would_be_wrong_with_zeros():
    d = np.array([60.0] * 20)
    d[4] = 0.0
    avg_zero, _ = delivery_stats(d)
    assert avg_zero < 60.0
