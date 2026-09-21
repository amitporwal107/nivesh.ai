"""Tests for research.charting.context — CHART-S29/S30/T09 market & sector context.

Covers: correct values inside each real source file's actual range, explicit
UNAVAILABLE for the sealed 2023-01..2024-07 block (market AND sector), UNAVAILABLE /
PIT_UNVERIFIED behavior at edges, equal-weight sector index construction (synthetic
bars + the REAL sector_master.csv mapping), and at least one real end-to-end date
lookup against the actual CSV files via the public `get_context()` interface.

Sector-index tests deliberately use synthetic per-symbol bars rather than real Kite
daily bars: `build_sector_index()` takes a caller-supplied `{symbol: bars}` mapping by
design (this module has no bars.py/universe.py dependency — see context.py's module
docstring), so synthetic frames exercise the equal-weight math precisely. This also
means these tests never touch real Kite price history for any symbol, so they cannot
collide with the known TMPV 2025-10-14 unadjusted-price demerger-gap artifact (open
defect T13, owned by bars.py/patterns.py) — that artifact is a real-data caveat for
whoever loads real Kite bars, not something this file's synthetic fixtures can trip
over.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from research.charting import context
from research.charting.lifecycle import DataQualityStatus

# ---------------------------------------------------------------------------
# Real source files this task specified — used directly, not copied/mocked.
# ---------------------------------------------------------------------------

_REAL_MARKET_OHLC = Path(context.DEFAULT_MARKET_OHLC_PATH)
_REAL_MARKET_CLOSE = Path(context.DEFAULT_MARKET_CLOSE_PATH)
_REAL_SECTOR_MASTER = Path(context.DEFAULT_SECTOR_MASTER_PATH)

_real_files_present = (
    _REAL_MARKET_OHLC.is_file() and _REAL_MARKET_CLOSE.is_file() and _REAL_SECTOR_MASTER.is_file()
)

requires_real_data = pytest.mark.skipif(
    not _real_files_present,
    reason="real market-index / sector-master CSVs not present in this environment",
)


def _synth_bars(dates: list[str], closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"date": pd.to_datetime(dates), "close": closes})


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def test_market_ohlc_path_default():
    assert context.market_ohlc_path() == Path(context.DEFAULT_MARKET_OHLC_PATH)


def test_market_close_path_env_override(monkeypatch, tmp_path):
    p = tmp_path / "close.csv"
    monkeypatch.setenv(context.ENV_MARKET_CLOSE_PATH, str(p))
    assert context.market_close_path() == p


def test_sector_master_path_explicit_arg_wins_over_env(monkeypatch, tmp_path):
    env_p = tmp_path / "env.csv"
    arg_p = tmp_path / "arg.csv"
    monkeypatch.setenv(context.ENV_SECTOR_MASTER_PATH, str(env_p))
    assert context.sector_master_path(arg_p) == arg_p


# ---------------------------------------------------------------------------
# Sealed out-of-sample gap — fixed calendar rule
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("date", ["2023-01-01", "2023-06-15", "2024-07-31"])
def test_is_sealed_gap_true_inside_window(date):
    assert context.is_sealed_gap(date) is True


@pytest.mark.parametrize("date", ["2022-12-31", "2024-08-01"])
def test_is_sealed_gap_false_just_outside_window(date):
    assert context.is_sealed_gap(date) is False


# ---------------------------------------------------------------------------
# Real CSV inspection — pinning down the actual shapes this module depends on
# ---------------------------------------------------------------------------

@requires_real_data
def test_real_market_ohlc_file_contains_three_stacked_indices():
    # index_p4.csv is NOT a single-index file: it stacks NIFTY 500, NIFTY 50 and
    # INDIA VIX under one `index` column. Verify the filter this module relies on
    # actually narrows to just the market index, not the whole file.
    raw = pd.read_csv(_REAL_MARKET_OHLC)
    assert set(raw["index"].unique()) >= {"NIFTY 500", "NIFTY 50", "INDIA VIX"}
    filtered = context.load_market_index_ohlc()
    assert len(filtered) < len(raw)


@requires_real_data
def test_real_market_ohlc_date_range_matches_expected():
    df = context.load_market_index_ohlc()
    assert df["date"].min() == pd.Timestamp("2019-07-01")
    assert df["date"].max() == pd.Timestamp("2022-12-30")
    assert len(df) == 870


@requires_real_data
def test_real_market_close_date_range_matches_expected():
    df = context.load_market_index_close()
    assert df["date"].min() == pd.Timestamp("2024-08-01")
    assert df["date"].max() == pd.Timestamp("2026-09-18")
    assert len(df) == 530


@requires_real_data
def test_real_market_close_file_has_no_ohlc_columns_fabricated():
    df = context.load_market_index_close()
    assert df["open"].isna().all()
    assert df["high"].isna().all()
    assert df["low"].isna().all()
    assert df["close"].notna().all()


@requires_real_data
def test_real_sector_master_has_large_blank_sector_gap():
    # Real data-quality finding: the majority of sector_master.csv rows have an empty
    # `sector` field. Documented in context.py's load_sector_map docstring; pinned
    # here so a silent change in the source file surfaces as a test failure.
    stats = context.sector_master_stats()
    assert stats.total_rows > 2000
    assert stats.blank_sector > stats.mapped
    assert stats.mapped + stats.blank_sector == stats.total_rows


@requires_real_data
def test_real_sector_master_known_mapping():
    sector_map = context.load_sector_map()
    assert sector_map["CSBBANK"] == "Finance"
    assert sector_map["DATAMATICS"] == "Information Technology"


@requires_real_data
def test_real_sector_master_blank_rows_excluded_from_map():
    sector_map = context.load_sector_map()
    # SGIL is a real row in sector_master.csv with an empty sector field.
    assert "SGIL" not in sector_map
    assert context.sector_of("SGIL", sector_map) is None


# ---------------------------------------------------------------------------
# load_market_index — merge behavior
# ---------------------------------------------------------------------------

def test_load_market_index_merges_two_disjoint_synthetic_sources(tmp_path):
    ohlc_path = tmp_path / "ohlc.csv"
    close_path = tmp_path / "close.csv"
    pd.DataFrame({
        "date": ["2020-01-01", "2020-01-02"],
        "open": [100.0, 101.0], "high": [102.0, 103.0], "low": [99.0, 100.0], "close": [101.0, 102.0],
        "index": ["NIFTY 500", "NIFTY 500"],
    }).to_csv(ohlc_path, index=False)
    pd.DataFrame({"date": ["2021-06-01", "2021-06-02"], "close": [200.0, 201.0]}).to_csv(close_path, index=False)

    merged = context.load_market_index(ohlc_path, close_path)
    assert list(merged["date"]) == [pd.Timestamp(d) for d in ["2020-01-01", "2020-01-02", "2021-06-01", "2021-06-02"]]
    assert list(merged["source"]) == [
        context.SOURCE_OHLC_FULL, context.SOURCE_OHLC_FULL, context.SOURCE_CLOSE_ONLY, context.SOURCE_CLOSE_ONLY,
    ]
    assert merged.loc[merged["date"] == pd.Timestamp("2021-06-01"), "open"].isna().all()


def test_load_market_index_filters_other_indices_from_ohlc_source(tmp_path):
    ohlc_path = tmp_path / "ohlc.csv"
    close_path = tmp_path / "close.csv"
    pd.DataFrame({
        "date": ["2020-01-01", "2020-01-01"],
        "open": [100.0, 20.0], "high": [102.0, 21.0], "low": [99.0, 19.0], "close": [101.0, 20.5],
        "index": ["NIFTY 500", "INDIA VIX"],
    }).to_csv(ohlc_path, index=False)
    pd.DataFrame({"date": [], "close": []}).to_csv(close_path, index=False)

    merged = context.load_market_index(ohlc_path, close_path)
    assert len(merged) == 1
    assert merged.iloc[0]["close"] == 101.0


def test_load_market_index_raises_on_overlapping_dates(tmp_path):
    ohlc_path = tmp_path / "ohlc.csv"
    close_path = tmp_path / "close.csv"
    pd.DataFrame({
        "date": ["2020-01-01"], "open": [100.0], "high": [101.0], "low": [99.0], "close": [100.5],
        "index": ["NIFTY 500"],
    }).to_csv(ohlc_path, index=False)
    pd.DataFrame({"date": ["2020-01-01"], "close": [999.0]}).to_csv(close_path, index=False)

    with pytest.raises(ValueError, match="overlap"):
        context.load_market_index(ohlc_path, close_path)


def test_load_market_index_ohlc_raises_on_duplicate_dates(tmp_path):
    p = tmp_path / "ohlc.csv"
    pd.DataFrame({
        "date": ["2020-01-01", "2020-01-01"],
        "open": [100.0, 100.0], "high": [101.0, 101.0], "low": [99.0, 99.0], "close": [100.5, 100.5],
        "index": ["NIFTY 500", "NIFTY 500"],
    }).to_csv(p, index=False)
    with pytest.raises(ValueError, match="duplicate"):
        context.load_market_index_ohlc(p)


# ---------------------------------------------------------------------------
# market_value_at — synthetic, deterministic coverage of every status/reason
# ---------------------------------------------------------------------------

@pytest.fixture
def synth_market_df() -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-06", "2025-08-01", "2025-08-04"]),
        "open": [1, 1, 1, 1, 1], "high": [1, 1, 1, 1, 1], "low": [1, 1, 1, 1, 1],
        "close": [100.0, 101.0, 102.0, 200.0, 201.0],
        "source": ["OHLC_FULL", "OHLC_FULL", "OHLC_FULL", "CLOSE_ONLY", "CLOSE_ONLY"],
    })


def test_market_value_at_ok_inside_first_source_range(synth_market_df):
    r = context.market_value_at("2020-01-02", synth_market_df)
    assert r.status == context.STATUS_OK
    assert r.close == 101.0
    assert r.source == context.SOURCE_OHLC_FULL
    assert r.reason is None


def test_market_value_at_ok_inside_second_source_range(synth_market_df):
    r = context.market_value_at("2025-08-04", synth_market_df)
    assert r.status == context.STATUS_OK
    assert r.close == 201.0
    assert r.source == context.SOURCE_CLOSE_ONLY


def test_market_value_at_sealed_gap(synth_market_df):
    # Inside the sealed window even though it also falls "between" the two synthetic
    # ranges — sealed-gap status must win regardless of what data happens to exist.
    r = context.market_value_at("2023-03-15", synth_market_df)
    assert r.status == context.STATUS_UNAVAILABLE
    assert r.reason == context.REASON_SEALED_GAP
    assert r.close is None


def test_market_value_at_before_coverage(synth_market_df):
    r = context.market_value_at("2019-12-31", synth_market_df)
    assert r.status == context.STATUS_UNAVAILABLE
    assert r.reason == context.REASON_BEFORE_COVERAGE


def test_market_value_at_after_coverage(synth_market_df):
    r = context.market_value_at("2025-08-05", synth_market_df)
    assert r.status == context.STATUS_UNAVAILABLE
    assert r.reason == context.REASON_AFTER_COVERAGE


def test_market_value_at_no_data_for_date_inside_span(synth_market_df):
    # 2020-01-04 (a Saturday) is inside [2020-01-01, 2020-01-06] but has no row —
    # must not be forward-filled from 2020-01-02.
    r = context.market_value_at("2020-01-04", synth_market_df)
    assert r.status == context.STATUS_UNAVAILABLE
    assert r.reason == context.REASON_NO_DATA_FOR_DATE


def test_market_value_at_empty_frame():
    r = context.market_value_at("2020-01-01", pd.DataFrame(columns=["date", "close", "source"]))
    assert r.status == context.STATUS_UNAVAILABLE
    assert r.reason == context.REASON_NO_DATA_FOR_DATE


def test_market_value_at_sealed_gap_checked_before_loading_default(monkeypatch):
    # A sealed-gap date must short-circuit before load_market_index() is even called
    # (defense in depth: never touch/derive from real files for a sealed date).
    def _boom(*a, **k):
        raise AssertionError("load_market_index() must not be called for a sealed-gap date")

    monkeypatch.setattr(context, "load_market_index", _boom)
    r = context.market_value_at("2023-06-01")
    assert r.status == context.STATUS_UNAVAILABLE
    assert r.reason == context.REASON_SEALED_GAP


# ---------------------------------------------------------------------------
# Sector map
# ---------------------------------------------------------------------------

def test_load_sector_map_excludes_blank_sector_rows(tmp_path):
    p = tmp_path / "sector_master.csv"
    pd.DataFrame({
        "symbol": ["AAA", "BBB", "CCC"],
        "company_name": ["A Ltd", "B Ltd", "C Ltd"],
        "sector": ["Finance", "", "  "],
        "industry": ["Financial Services", "", ""],
    }).to_csv(p, index=False)

    sector_map = context.load_sector_map(p)
    assert sector_map == {"AAA": "Finance"}
    assert context.sector_of("BBB", sector_map) is None
    assert context.sector_of("ZZZ", sector_map) is None


def test_sector_master_stats_synthetic(tmp_path):
    p = tmp_path / "sector_master.csv"
    pd.DataFrame({
        "symbol": ["AAA", "BBB", "CCC"],
        "company_name": ["A", "B", "C"],
        "sector": ["Finance", "", "IT"],
        "industry": ["x", "", "y"],
    }).to_csv(p, index=False)

    stats = context.sector_master_stats(p)
    assert stats == context.SectorMasterStats(total_rows=3, mapped=2, blank_sector=1)


# ---------------------------------------------------------------------------
# build_sector_index — equal-weight construction + PIT_UNVERIFIED
# ---------------------------------------------------------------------------

def test_build_sector_index_equal_weight_two_members_same_dates():
    symbol_bars = {
        "AAA": _synth_bars(["2020-01-01", "2020-01-02", "2020-01-03"], [100.0, 110.0, 121.0]),
        "BBB": _synth_bars(["2020-01-01", "2020-01-02", "2020-01-03"], [50.0, 45.0, 40.0]),
    }
    sector_map = {"AAA": "Finance", "BBB": "Finance"}

    result = context.build_sector_index(symbol_bars, sector_map, base_value=100.0)
    assert set(result.keys()) == {"Finance"}
    frame = result["Finance"]

    # AAA normalized: 100, 110, 121 (already base 100 at t0). BBB normalized:
    # 100, 90, 80 (50 -> 100 base, 45 -> 90, 40 -> 80). Equal-weight mean:
    expected = [(100 + 100) / 2, (110 + 90) / 2, (121 + 80) / 2]
    assert list(frame["value"]) == pytest.approx(expected)
    assert list(frame["n_constituents"]) == [2, 2, 2]
    assert (frame["pit_status"] == DataQualityStatus.PIT_UNVERIFIED.value).all()


def test_build_sector_index_partial_overlap_uses_available_constituents_only():
    symbol_bars = {
        "AAA": _synth_bars(["2020-01-01", "2020-01-02"], [100.0, 110.0]),
        "BBB": _synth_bars(["2020-01-02", "2020-01-03"], [200.0, 220.0]),
    }
    sector_map = {"AAA": "IT", "BBB": "IT"}

    result = context.build_sector_index(symbol_bars, sector_map, base_value=100.0)
    frame = result["IT"].set_index("date")

    # 2020-01-01: only AAA (normalized 100.0) contributes.
    assert frame.loc[pd.Timestamp("2020-01-01"), "value"] == pytest.approx(100.0)
    assert frame.loc[pd.Timestamp("2020-01-01"), "n_constituents"] == 1
    # 2020-01-02: AAA normalized 110, BBB normalized 100 (its own base) -> mean 105.
    assert frame.loc[pd.Timestamp("2020-01-02"), "value"] == pytest.approx(105.0)
    assert frame.loc[pd.Timestamp("2020-01-02"), "n_constituents"] == 2
    # 2020-01-03: only BBB (normalized 110.0) contributes.
    assert frame.loc[pd.Timestamp("2020-01-03"), "value"] == pytest.approx(110.0)
    assert frame.loc[pd.Timestamp("2020-01-03"), "n_constituents"] == 1


def test_build_sector_index_separates_sectors():
    symbol_bars = {
        "AAA": _synth_bars(["2020-01-01"], [100.0]),
        "BBB": _synth_bars(["2020-01-01"], [50.0]),
    }
    sector_map = {"AAA": "Finance", "BBB": "IT"}
    result = context.build_sector_index(symbol_bars, sector_map)
    assert set(result.keys()) == {"Finance", "IT"}
    assert result["Finance"]["n_constituents"].iloc[0] == 1
    assert result["IT"]["n_constituents"].iloc[0] == 1


def test_build_sector_index_skips_symbols_without_a_sector():
    symbol_bars = {
        "AAA": _synth_bars(["2020-01-01"], [100.0]),
        "UNMAPPED": _synth_bars(["2020-01-01"], [999.0]),
    }
    sector_map = {"AAA": "Finance"}
    result = context.build_sector_index(symbol_bars, sector_map)
    assert result["Finance"]["n_constituents"].iloc[0] == 1  # UNMAPPED never contributed


def test_build_sector_index_skips_empty_bars_frame():
    symbol_bars = {
        "AAA": _synth_bars(["2020-01-01"], [100.0]),
        "EMPTY": pd.DataFrame(columns=["date", "close"]),
    }
    sector_map = {"AAA": "Finance", "EMPTY": "Finance"}
    result = context.build_sector_index(symbol_bars, sector_map)
    assert result["Finance"]["n_constituents"].iloc[0] == 1


def test_build_sector_index_dedupes_duplicate_dates_keeping_last():
    # bars.py preserves duplicate dates verbatim; build_sector_index must not crash or
    # silently misalign on them.
    df = pd.DataFrame({"date": pd.to_datetime(["2020-01-01", "2020-01-01", "2020-01-02"]), "close": [100.0, 105.0, 110.0]})
    symbol_bars = {"AAA": df}
    sector_map = {"AAA": "Finance"}
    result = context.build_sector_index(symbol_bars, sector_map, base_value=100.0)
    frame = result["Finance"]
    assert len(frame) == 2
    # first_close is the de-duplicated (keep last) 2020-01-01 value, 105.0 -> base 100.
    assert frame.iloc[0]["value"] == pytest.approx(100.0)
    assert frame.iloc[1]["value"] == pytest.approx(110.0 / 105.0 * 100.0)


def test_build_sector_index_raises_on_missing_close_column():
    symbol_bars = {"AAA": pd.DataFrame({"date": pd.to_datetime(["2020-01-01"]), "price": [100.0]})}
    with pytest.raises(ValueError, match="close"):
        context.build_sector_index(symbol_bars, {"AAA": "Finance"})


# ---------------------------------------------------------------------------
# sector_value_at
# ---------------------------------------------------------------------------

@pytest.fixture
def synth_sector_indices() -> dict[str, pd.DataFrame]:
    return {
        "Finance": pd.DataFrame({
            "date": pd.to_datetime(["2020-01-01", "2020-01-02"]),
            "value": [100.0, 102.0],
            "n_constituents": [3, 3],
            "pit_status": [DataQualityStatus.PIT_UNVERIFIED.value] * 2,
        }),
    }


def test_sector_value_at_ok_carries_pit_unverified(synth_sector_indices):
    r = context.sector_value_at("2020-01-02", "Finance", synth_sector_indices)
    assert r.status == context.STATUS_OK
    assert r.value == 102.0
    assert r.n_constituents == 3
    assert r.pit_status == DataQualityStatus.PIT_UNVERIFIED.value


def test_sector_value_at_unknown_sector(synth_sector_indices):
    r = context.sector_value_at("2020-01-02", "Nonexistent", synth_sector_indices)
    assert r.status == context.STATUS_UNAVAILABLE
    assert r.reason == context.REASON_UNKNOWN_SECTOR


def test_sector_value_at_no_data_for_date(synth_sector_indices):
    r = context.sector_value_at("2020-01-05", "Finance", synth_sector_indices)
    assert r.status == context.STATUS_UNAVAILABLE
    assert r.reason == context.REASON_NO_DATA_FOR_DATE


def test_sector_value_at_sealed_gap_even_if_sector_frame_has_a_row(synth_sector_indices):
    # Simulate a sector index built from bars that DO span the sealed window (e.g.
    # real Kite daily bars run continuously from 2021) — the sealed rule must still
    # block it, per context.py's module docstring rule 2.
    frames = dict(synth_sector_indices)
    frames["Finance"] = pd.concat([
        frames["Finance"],
        pd.DataFrame({
            "date": [pd.Timestamp("2023-06-01")], "value": [999.0], "n_constituents": [3],
            "pit_status": [DataQualityStatus.PIT_UNVERIFIED.value],
        }),
    ], ignore_index=True)

    r = context.sector_value_at("2023-06-01", "Finance", frames)
    assert r.status == context.STATUS_UNAVAILABLE
    assert r.reason == context.REASON_SEALED_GAP
    assert r.value is None


# ---------------------------------------------------------------------------
# get_context — the combined public query interface
# ---------------------------------------------------------------------------

def test_get_context_market_ok_sector_unresolvable_without_symbol_or_sector(synth_market_df):
    r = context.get_context("2020-01-02", market_df=synth_market_df)
    assert r.market.status == context.STATUS_OK
    assert r.sector.status == context.STATUS_UNAVAILABLE
    assert r.sector.reason == context.REASON_NO_SECTOR_RESOLVABLE


def test_get_context_explicit_sector_but_no_sector_indices_is_unavailable(synth_market_df):
    r = context.get_context("2020-01-02", market_df=synth_market_df, sector="Finance")
    assert r.sector.status == context.STATUS_UNAVAILABLE
    assert r.sector.reason == context.REASON_UNKNOWN_SECTOR
    assert r.sector.sector == "Finance"


def test_get_context_resolves_sector_from_symbol(synth_market_df, synth_sector_indices):
    sector_map = {"XYZ": "Finance"}
    r = context.get_context(
        "2020-01-02", market_df=synth_market_df, symbol="XYZ",
        sector_indices=synth_sector_indices, sector_map=sector_map,
    )
    assert r.market.status == context.STATUS_OK
    assert r.sector.status == context.STATUS_OK
    assert r.sector.value == 102.0
    assert r.sector.pit_status == DataQualityStatus.PIT_UNVERIFIED.value


def test_get_context_explicit_sector_overrides_symbol_lookup(synth_market_df, synth_sector_indices):
    # symbol maps to "IT" but explicit sector= "Finance" must win.
    sector_map = {"XYZ": "IT"}
    r = context.get_context(
        "2020-01-02", market_df=synth_market_df, symbol="XYZ", sector="Finance",
        sector_indices=synth_sector_indices, sector_map=sector_map,
    )
    assert r.sector.sector == "Finance"
    assert r.sector.status == context.STATUS_OK


def test_get_context_sealed_gap_blocks_both_market_and_sector(synth_sector_indices):
    frames = dict(synth_sector_indices)
    frames["Finance"] = pd.concat([
        frames["Finance"],
        pd.DataFrame({
            "date": [pd.Timestamp("2023-06-01")], "value": [999.0], "n_constituents": [3],
            "pit_status": [DataQualityStatus.PIT_UNVERIFIED.value],
        }),
    ], ignore_index=True)

    r = context.get_context("2023-06-01", sector="Finance", sector_indices=frames)
    assert r.market.status == context.STATUS_UNAVAILABLE
    assert r.market.reason == context.REASON_SEALED_GAP
    assert r.sector.status == context.STATUS_UNAVAILABLE
    assert r.sector.reason == context.REASON_SEALED_GAP


def test_get_context_independent_failures_market_ok_sector_fails(synth_market_df):
    r = context.get_context("2020-01-01", market_df=synth_market_df, sector="Nonexistent", sector_indices={})
    assert r.market.status == context.STATUS_OK
    assert r.sector.status == context.STATUS_UNAVAILABLE


# ---------------------------------------------------------------------------
# Real end-to-end lookups — actual CSV data, through the public interface,
# with zero mocking of paths or data.
# ---------------------------------------------------------------------------

@requires_real_data
def test_real_end_to_end_get_context_first_day_of_ohlc_source():
    r = context.get_context("2019-07-01")
    assert r.market.status == context.STATUS_OK
    assert r.market.close == pytest.approx(9713.0)
    assert r.market.source == context.SOURCE_OHLC_FULL


@requires_real_data
def test_real_end_to_end_get_context_last_day_of_close_source():
    r = context.get_context("2026-09-18")
    assert r.market.status == context.STATUS_OK
    assert r.market.close == pytest.approx(22840.55)
    assert r.market.source == context.SOURCE_CLOSE_ONLY


@requires_real_data
def test_real_end_to_end_get_context_sealed_gap_date_returns_unavailable():
    r = context.get_context("2023-11-01")
    assert r.market.status == context.STATUS_UNAVAILABLE
    assert r.market.reason == context.REASON_SEALED_GAP


@requires_real_data
def test_real_end_to_end_get_context_symbol_resolves_real_sector(monkeypatch):
    # Real sector_master.csv mapping (CSBBANK -> Finance) combined with a small
    # synthetic equal-weight sector index built the normal way — exercises the full
    # symbol -> sector -> sector index chain against the real mapping file.
    symbol_bars = {
        "CSBBANK": _synth_bars(["2019-07-01", "2019-07-02"], [280.0, 285.0]),
        "DCBBANK": _synth_bars(["2019-07-01", "2019-07-02"], [180.0, 183.0]),
    }
    sector_map = context.load_sector_map()
    sector_indices = context.build_sector_index(symbol_bars, sector_map)

    r = context.get_context(
        "2019-07-01", symbol="CSBBANK", sector_map=sector_map, sector_indices=sector_indices,
    )
    assert r.market.status == context.STATUS_OK
    assert r.sector.status == context.STATUS_OK
    assert r.sector.sector == "Finance"
    assert r.sector.pit_status == DataQualityStatus.PIT_UNVERIFIED.value
