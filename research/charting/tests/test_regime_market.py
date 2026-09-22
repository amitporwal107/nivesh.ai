"""N-section-12 Market Regime Engine + India VIX / universe breadth context-field tests.

`market_regime()` reuses the same closed-form linear-ramp technique as
test_regime_trend.py's trend_state tests (SMA of an arithmetic sequence has a known
midpoint), applied to the BENCHMARK series directly -- BULL/BEAR are provable by
construction; SIDEWAYS uses a flat (zero-slope) series, also provable by construction
(a constant series has SMA == close everywhere and slope == 0 everywhere, so neither
the BULL nor BEAR condition can ever hold).

`india_vix_at`/`breadth_at` are tested against the REAL committed data files (this repo
already ships real `research/index_history/data/INDIA_VIX.csv` and
`research/index_history/data/BREADTH_UNIVERSE.csv` -- no network call, no mock), plus a
small synthetic breadth frame for the blank-not-zero contract specifically.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from research.charting import context, regime
from research.charting.tests import synth

_SAFE_START = "2019-01-02"

_REAL_DATA_DIR = Path(context.DEFAULT_INDEX_HISTORY_DIR)
_real_data_present = (_REAL_DATA_DIR / "NIFTY_500.csv").is_file() and (_REAL_DATA_DIR / "INDIA_VIX.csv").is_file()
requires_real_data = pytest.mark.skipif(not _real_data_present, reason="real index_history CSVs not present")

_BREADTH_PATH = Path(regime.DEFAULT_BREADTH_UNIVERSE_PATH)
requires_real_breadth = pytest.mark.skipif(not _BREADTH_PATH.is_file(), reason="BREADTH_UNIVERSE.csv not present")


# ── Hand-computed / by-construction regime on synthetic benchmark series ────


def test_market_regime_bull_by_construction_linear_ramp():
    """close[i] = 100 + 0.5*i, i=0..259 -- same closed-form as trend_state's bullish
    test: SMA200(259)=179.75 < close(259)=229.5, and SMA200's slope is a positive
    constant by construction -> BULL."""
    closes = [100 + 0.5 * i for i in range(260)]
    bench = synth.bars_from_closes(closes, start_date=_SAFE_START, wick=0.1)
    t = bench["date"].iloc[-1]

    mr = regime.market_regime(bench, t)
    assert mr["close"].value == pytest.approx(229.5)
    assert mr["sma_200"].value == pytest.approx(179.75)
    assert mr["sma_200_slope"].value > 0
    assert mr["regime"].status == "OK"
    assert mr["regime"].value == "BULL"


def test_market_regime_bear_by_construction_linear_ramp():
    closes = [500 - 0.5 * i for i in range(260)]
    bench = synth.bars_from_closes(closes, start_date=_SAFE_START, wick=0.1)
    t = bench["date"].iloc[-1]

    mr = regime.market_regime(bench, t)
    assert mr["close"].value == pytest.approx(370.5)
    assert mr["sma_200"].value == pytest.approx(420.25)
    assert mr["sma_200_slope"].value < 0
    assert mr["regime"].status == "OK"
    assert mr["regime"].value == "BEAR"


def test_market_regime_sideways_by_construction_flat_series():
    """A perfectly flat close series: SMA200 == close == 100.0 everywhere, slope == 0
    everywhere -> neither BULL (`slope > 0`) nor BEAR (`slope < 0`) can hold -> SIDEWAYS,
    N-section-12's own "neither" wording, exactly the logical complement with no numeric
    band involved (see regime.py module docstring)."""
    closes = [100.0] * 260
    bench = synth.bars_from_closes(closes, start_date=_SAFE_START, wick=0.1)
    t = bench["date"].iloc[-1]

    mr = regime.market_regime(bench, t)
    assert mr["sma_200"].value == pytest.approx(100.0)
    assert mr["sma_200_slope"].value == pytest.approx(0.0)
    assert mr["regime"].status == "OK"
    assert mr["regime"].value == "SIDEWAYS"


def test_market_regime_unavailable_when_sma200_unavailable():
    closes = [100.0 + i for i in range(50)]
    bench = synth.bars_from_closes(closes, start_date=_SAFE_START, wick=0.1)
    t = bench["date"].iloc[-1]
    mr = regime.market_regime(bench, t)
    assert mr["sma_200"].status == "UNAVAILABLE"
    assert mr["regime"].status == "UNAVAILABLE"


# ── India VIX -- real data ────────────────────────────────────────────────


@requires_real_data
def test_india_vix_real_value_on_a_known_date():
    vix_df = context.load_index_history("INDIA VIX")
    fv = regime.india_vix_at("2022-12-30", vix_df)
    assert fv.status == "OK"
    assert fv.value == pytest.approx(14.87)  # verified against the raw CSV row directly


@requires_real_data
def test_india_vix_unavailable_in_sealed_gap():
    vix_df = context.load_index_history("INDIA VIX")
    fv = regime.india_vix_at("2023-06-15", vix_df)
    assert fv.status == "UNAVAILABLE"
    assert fv.reason == "SEALED_GAP"


def test_india_vix_defaults_to_loading_real_file_when_omitted():
    fv = regime.india_vix_at("2022-12-30")
    if _real_data_present:
        assert fv.status == "OK"


# ── Universe breadth -- blank-not-zero contract ──────────────────────────


def test_breadth_blank_in_source_is_not_coerced_to_zero():
    """A synthetic breadth frame with an explicit blank (NaN) `pct_above_sma200` cell
    must surface as UNAVAILABLE/BLANK_IN_SOURCE with value None -- never 0.0."""
    df = pd.DataFrame({
        "date": pd.to_datetime(["2020-01-01", "2020-01-02"]),
        "advancers": [900, 950],
        "decliners": [500, 450],
        "unchanged": [10, 12],
        "advance_decline_ratio": [1.8, float("nan")],
        "pct_above_sma50": [55.0, 56.0],
        "pct_above_sma200": [float("nan"), float("nan")],
        "new_52w_highs": [12.0, float("nan")],
        "new_52w_lows": [3.0, float("nan")],
        "names_contributing": [1410, 1412],
    })
    result = regime.breadth_at("2020-01-02", df)
    assert result["pct_above_sma200"].status == "UNAVAILABLE"
    assert result["pct_above_sma200"].reason == "BLANK_IN_SOURCE"
    assert result["pct_above_sma200"].value is None
    assert result["advance_decline_ratio"].status == "UNAVAILABLE"
    assert result["advance_decline_ratio"].reason == "BLANK_IN_SOURCE"
    # A genuinely-present zero (advancers/decliners/etc.) must stay a real 0, not blank:
    assert result["pct_above_sma50"].status == "OK"
    assert result["pct_above_sma50"].value == 56.0


def test_breadth_zero_advancers_on_the_very_first_real_row_is_a_real_zero_not_blank():
    """BREADTH_UNIVERSE.csv's own first row (2021-01-01) has advancers=decliners=0 as a
    REAL computed value (no prior-day close exists yet for anyone), not a blank cell --
    contrasted directly against the same row's genuinely-blank pct_above_sma50/200."""
    df = pd.DataFrame({
        "date": pd.to_datetime(["2021-01-01"]),
        "advancers": [0],
        "decliners": [0],
        "unchanged": [0],
        "advance_decline_ratio": [float("nan")],
        "pct_above_sma50": [float("nan")],
        "pct_above_sma200": [float("nan")],
        "new_52w_highs": [float("nan")],
        "new_52w_lows": [float("nan")],
        "names_contributing": [0],
    })
    result = regime.breadth_at("2021-01-01", df)
    assert result["advancers"].status == "OK"
    assert result["advancers"].value == 0
    assert result["pct_above_sma50"].status == "UNAVAILABLE"
    assert result["pct_above_sma50"].reason == "BLANK_IN_SOURCE"


@requires_real_breadth
def test_breadth_real_file_first_row_matches_expectations():
    df = regime.load_breadth_universe()
    result = regime.breadth_at("2021-01-01", df)
    assert result["advancers"].value == 0
    assert result["decliners"].value == 0
    assert result["pct_above_sma200"].status == "UNAVAILABLE"
    assert result["pct_above_sma200"].reason == "BLANK_IN_SOURCE"


@requires_real_breadth
def test_breadth_unavailable_in_sealed_gap():
    df = regime.load_breadth_universe()
    result = regime.breadth_at("2023-06-15", df)
    for fv in result.values():
        assert fv.status == "UNAVAILABLE"
        assert fv.reason == "SEALED_GAP"


# ── features_at() integration ────────────────────────────────────────────


@requires_real_data
@requires_real_breadth
def test_features_at_flattens_every_family_with_versioning_fields():
    from research.charting import bars

    sym_bars = bars.load_symbol("RELIANCE")
    flat = regime.features_at(sym_bars, "2022-12-30", symbol="RELIANCE")

    assert flat["symbol"] == "RELIANCE"
    assert flat["feature_version"] == regime.FEATURE_VERSION
    assert flat["feature_config_hash"] == regime.feature_config_hash()
    for key in ("rs_5", "rs_20", "rs_50", "rs_100"):
        assert key in flat
        assert f"{key}_status" in flat
    for key in ("trend_close", "trend_sma_20", "trend_trend_state", "trend_adx_14"):
        assert key in flat
    for key in ("regime_regime", "regime_sma_200"):
        assert key in flat
    assert "india_vix_close" in flat
    assert "breadth_advancers" in flat
    assert "breadth_pct_above_sma200" in flat
