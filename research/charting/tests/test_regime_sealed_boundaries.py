"""Sealed 2023-01-01..2024-07-31 out-of-sample boundary tests, on the REAL NIFTY 500
index history (`research/index_history/data/NIFTY_500.csv`) -- the exact real-data
boundary dates the task asked for: the last pre-sealed date (2022-12-30), the first
post-sealed date (2024-08-01), and the first date whose 200-bar SMA lookback window is
ENTIRELY post-sealed (2025-05-22 -- computed once from the real file's own row
positions, see comment below; 2025-05-21 -- one trading day earlier -- is the last date
still UNAVAILABLE). Also the literal task example (2024-09-02) and the RS/regime/breadth
equivalents of the same boundary.

Position arithmetic behind 2025-05-22 (real NIFTY_500.csv, verified against the actual
file): row 870 is 2024-08-01 (the first post-sealed row). A 200-bar SMA window ending at
row 870+199=1069 starts at row 870 -- i.e. it is the first window whose start row is
ALSO post-sealed. Row 1069's date is 2025-05-22; row 1068 (2025-05-21) is the last date
whose window still starts at row 869 = 2022-12-30 (pre-sealed), so its window overlaps
the gap.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from research.charting import context, regime

_REAL_DATA_DIR = Path(context.DEFAULT_INDEX_HISTORY_DIR)
_real_data_present = (_REAL_DATA_DIR / "NIFTY_500.csv").is_file()
requires_real_data = pytest.mark.skipif(not _real_data_present, reason="real NIFTY_500.csv not present")

_BREADTH_PATH = Path(regime.DEFAULT_BREADTH_UNIVERSE_PATH)
requires_real_breadth = pytest.mark.skipif(not _BREADTH_PATH.is_file(), reason="BREADTH_UNIVERSE.csv not present")


@pytest.fixture(scope="module")
def nifty500():
    return context.load_index_history("NIFTY 500")


# ── SMA200 boundary (trend_context, on the benchmark series itself) ─────────


@requires_real_data
def test_sma200_ok_on_last_pre_sealed_date(nifty500):
    tc = regime.trend_context(nifty500, "2022-12-30", sma_periods=(200,), ema_periods=())
    assert tc["sma_200"].status == "OK"


@requires_real_data
def test_sma200_unavailable_on_first_post_sealed_date(nifty500):
    tc = regime.trend_context(nifty500, "2024-08-01", sma_periods=(200,), ema_periods=())
    assert tc["sma_200"].status == "UNAVAILABLE"
    assert tc["sma_200"].reason == "SEALED_GAP"


@requires_real_data
def test_sma200_unavailable_on_the_tasks_own_literal_example_date(nifty500):
    """docs/charting.md section 35.2 / task instructions' own worked example: "SMA200 of
    NIFTY 500 on 2024-09-02 is UNAVAILABLE"."""
    tc = regime.trend_context(nifty500, "2024-09-02", sma_periods=(200,), ema_periods=())
    assert tc["sma_200"].status == "UNAVAILABLE"
    assert tc["sma_200"].reason == "SEALED_GAP"


@requires_real_data
def test_sma200_window_just_clears_the_gap(nifty500):
    """2025-05-22: the first date whose 200-bar SMA window is entirely post-sealed ->
    OK. 2025-05-21, one trading day earlier -> still UNAVAILABLE (its window's first bar
    is 2022-12-30, pre-sealed) -- proving this is a real boundary, not a loose margin."""
    ok = regime.trend_context(nifty500, "2025-05-22", sma_periods=(200,), ema_periods=())
    assert ok["sma_200"].status == "OK"

    still_gap = regime.trend_context(nifty500, "2025-05-21", sma_periods=(200,), ema_periods=())
    assert still_gap["sma_200"].status == "UNAVAILABLE"
    assert still_gap["sma_200"].reason == "SEALED_GAP"


@requires_real_data
def test_sma200_never_silently_skips_the_gap_value_check(nifty500):
    """Belt-and-braces: the value a naive positional rolling SMA WOULD have computed at
    the first post-sealed row (by construction, skipping straight over the missing
    rows) is a real, finite number -- proving the UNAVAILABLE status above is a
    deliberate guard, not an accidental NaN from pandas' own rolling/min_periods
    machinery."""
    from research.charting import series

    naive = series.sma(nifty500, 200)
    row = nifty500.index[nifty500["date"] == __import__("pandas").Timestamp("2024-08-01")][0]
    assert not __import__("pandas").isna(naive.iloc[row])  # naive positional SMA succeeds...
    # ...but the guarded feature refuses it anyway:
    tc = regime.trend_context(nifty500, "2024-08-01", sma_periods=(200,), ema_periods=())
    assert tc["sma_200"].status == "UNAVAILABLE"


# ── Relative strength across the gap ─────────────────────────────────────


@requires_real_data
def test_relative_strength_unavailable_when_window_spans_the_gap(nifty500):
    from research.charting import bars

    sym_bars = bars.load_symbol("RELIANCE")
    rs = regime.relative_strength(sym_bars, nifty500, "2024-08-05", windows=(20,))
    assert rs["rs_20"].status == "UNAVAILABLE"
    assert rs["rs_20"].reason == "SEALED_GAP"


@requires_real_data
def test_relative_strength_ok_entirely_pre_sealed(nifty500):
    from research.charting import bars

    sym_bars = bars.load_symbol("RELIANCE")
    rs = regime.relative_strength(sym_bars, nifty500, "2022-12-30", windows=(20,))
    assert rs["rs_20"].status == "OK"


# ── Market regime across the gap ──────────────────────────────────────────


@requires_real_data
def test_market_regime_unavailable_in_sealed_gap(nifty500):
    mr = regime.market_regime(nifty500, "2024-09-02")
    assert mr["regime"].status == "UNAVAILABLE"
    assert mr["regime"].reason == "SEALED_GAP"


@requires_real_data
def test_market_regime_ok_on_last_pre_sealed_date(nifty500):
    mr = regime.market_regime(nifty500, "2022-12-30")
    assert mr["regime"].status == "OK"
    assert mr["regime"].value in ("BULL", "BEAR", "SIDEWAYS")


# ── Breadth across the gap ─────────────────────────────────────────────────


@requires_real_breadth
def test_breadth_on_first_post_sealed_date_real_zero_vs_blank_in_source():
    """2024-08-01's real CSV row (verified directly against the file):
    `0,0,0,,,,,,0` -- advancers/decliners/unchanged/names_contributing are REAL zeros
    (breadth.py restarts each symbol's rolling state after the gap, so literally nobody
    has a prior POST-sealed close yet on day 1 -- the same "no prior day" shape as the
    file's very first-ever row, 2021-01-01), while advance_decline_ratio and the
    window-based fields are genuinely blank (BLANK_IN_SOURCE, not SEALED_GAP -- the
    date itself is a valid, non-sealed date; the blank is breadth.py's own
    full-window-only rule, already baked into the CSV, not this module's sealed-gap
    guard). A date genuinely INSIDE the sealed block (no row at all) is covered
    separately in test_regime_market.py's test_breadth_unavailable_in_sealed_gap."""
    df = regime.load_breadth_universe()
    result = regime.breadth_at("2024-08-01", df)
    for name in ("advancers", "decliners", "unchanged", "names_contributing"):
        assert result[name].status == "OK", name
        assert result[name].value == 0, name
    for name in ("advance_decline_ratio", "pct_above_sma50", "pct_above_sma200", "new_52w_highs", "new_52w_lows"):
        assert result[name].status == "UNAVAILABLE", name
        assert result[name].reason == "BLANK_IN_SOURCE", name


# ── feature_config_hash / FEATURE_VERSION determinism (section 35.2 "feature versions") ──


def test_feature_config_hash_is_deterministic():
    assert regime.feature_config_hash() == regime.feature_config_hash()
    assert regime.feature_config_hash(dict(regime.FEATURE_CONFIG)) == regime.feature_config_hash()


def test_feature_config_hash_changes_when_a_parameter_changes():
    baseline = regime.feature_config_hash()
    mutated = dict(regime.FEATURE_CONFIG)
    mutated["trend_slope_lookback_bars"] = 25
    assert regime.feature_config_hash(mutated) != baseline


def test_needs_owner_confirmation_parameters_are_present_and_hashed():
    """The two genuinely-unstated N-section-12/N-section-10 parameters must live in
    FEATURE_CONFIG (so they are covered by feature_config_hash()), not as bare module
    constants."""
    assert "trend_slope_lookback_bars" in regime.FEATURE_CONFIG
    assert "regime_slope_lookback_bars" in regime.FEATURE_CONFIG
    assert regime.FEATURE_CONFIG["regime_sideways_band"] is None  # not invented; see docstring
