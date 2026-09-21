"""Tests for research.charting.bars — synthetic gzip CSV fixtures only.

The one integration test at the bottom touches the real Kite daily-bars directory and is
skipped (not failed) when that directory is absent from the environment.
"""
from __future__ import annotations

import gzip
import hashlib
from pathlib import Path

import pandas as pd
import pytest

from research.charting import bars
from research.charting.config import BARS_COLUMNS

_HEADER = "symbol,instrument_token,date,open,high,low,close,volume,source_version"


def _write_part(directory: Path, filename: str, rows: list[str]) -> Path:
    """Write one gzip CSV part. `rows` are raw data lines (no header)."""
    path = directory / filename
    with gzip.open(path, "wt", newline="") as f:
        f.write(_HEADER + "\n")
        for row in rows:
            f.write(row + "\n")
    return path


# ---------------------------------------------------------------------------
# load_symbol
# ---------------------------------------------------------------------------

def test_load_symbol_returns_exactly_bars_columns(tmp_path):
    _write_part(tmp_path, "part-1.csv.gz", [
        "ABC,111,2021-01-01,10,11,9,10.5,1000,kite-connect-v3",
        "ABC,111,2021-01-04,10.5,12,10,11.5,1200,kite-connect-v3",
        "XYZ,222,2021-01-01,50,51,49,50.5,500,kite-connect-v3",
    ])
    df = bars.load_symbol("ABC", directory=tmp_path)
    assert list(df.columns) == list(BARS_COLUMNS)
    assert len(df) == 2
    assert df["date"].tolist() == [pd.Timestamp("2021-01-01"), pd.Timestamp("2021-01-04")]
    assert df["close"].tolist() == [10.5, 11.5]


def test_load_symbol_missing_symbol_returns_empty_typed_frame(tmp_path):
    _write_part(tmp_path, "part-1.csv.gz", [
        "ABC,111,2021-01-01,10,11,9,10.5,1000,kite-connect-v3",
    ])
    df = bars.load_symbol("NOPE", directory=tmp_path)
    assert list(df.columns) == list(BARS_COLUMNS)
    assert len(df) == 0


def test_header_only_part_files_do_not_break_loading(tmp_path):
    _write_part(tmp_path, "part-1.csv.gz", [
        "ABC,111,2021-01-01,10,11,9,10.5,1000,kite-connect-v3",
    ])
    _write_part(tmp_path, "part-2.csv.gz", [])  # header-only, as real parts sometimes are
    df = bars.load_symbol("ABC", directory=tmp_path)
    assert len(df) == 1


def test_load_symbol_preserves_duplicate_and_out_of_order_rows_verbatim(tmp_path):
    # Mirrors a real case in the data: symbol CLEDUCATE has two rows for the same date
    # (2023-11-01..2023-11-06 each appear twice). bars.py must not deduplicate or re-sort
    # — that is validate.py's DUPLICATE_TIMESTAMP / OUT_OF_ORDER job, not this module's.
    _write_part(tmp_path, "part-1.csv.gz", [
        "DUP,1,2021-01-04,10,11,9,10.5,100,kite-connect-v3",  # appears before an earlier date
        "DUP,1,2021-01-01,10,11,9,10.0,100,kite-connect-v3",
        "DUP,1,2021-01-01,10,11,9,10.2,100,kite-connect-v3",  # duplicate date
    ])
    df = bars.load_symbol("DUP", directory=tmp_path)
    assert len(df) == 3
    assert df["date"].tolist() == [
        pd.Timestamp("2021-01-04"), pd.Timestamp("2021-01-01"), pd.Timestamp("2021-01-01"),
    ]
    assert df["close"].tolist() == [10.5, 10.0, 10.2]


def test_load_symbol_preserves_bad_rows_verbatim(tmp_path):
    # Nonpositive open, and a high<low + negative volume row: bars.py must not drop or
    # clip these. Flagging is validate.py's job.
    _write_part(tmp_path, "part-1.csv.gz", [
        "BAD,1,2021-01-01,-5,10,9,10.5,1000,kite-connect-v3",
        "BAD,1,2021-01-04,10,9,11,10.5,-50,kite-connect-v3",
    ])
    df = bars.load_symbol("BAD", directory=tmp_path)
    assert len(df) == 2
    assert df.loc[0, "open"] == -5
    assert df.loc[1, "high"] == 9
    assert df.loc[1, "low"] == 11
    assert df.loc[1, "volume"] == -50


def test_load_symbol_concatenates_rows_split_across_part_files(tmp_path):
    _write_part(tmp_path, "part-1.csv.gz", [
        "SPLIT,1,2021-01-01,10,11,9,10.5,100,kite-connect-v3",
    ])
    _write_part(tmp_path, "part-2.csv.gz", [
        "SPLIT,1,2021-01-04,11,12,10,11.5,120,kite-connect-v3",
    ])
    df = bars.load_symbol("SPLIT", directory=tmp_path)
    assert len(df) == 2
    assert df["date"].tolist() == [pd.Timestamp("2021-01-01"), pd.Timestamp("2021-01-04")]


# ---------------------------------------------------------------------------
# load_all
# ---------------------------------------------------------------------------

def test_load_all_yields_every_symbol_typed_correctly(tmp_path):
    _write_part(tmp_path, "part-1.csv.gz", [
        "ABC,111,2021-01-01,10,11,9,10.5,1000,kite-connect-v3",
        "XYZ,222,2021-01-01,50,51,49,50.5,500,kite-connect-v3",
    ])
    _write_part(tmp_path, "part-2.csv.gz", [])
    result = dict(bars.load_all(directory=tmp_path))
    assert set(result.keys()) == {"ABC", "XYZ"}
    for df in result.values():
        assert list(df.columns) == list(BARS_COLUMNS)


def test_load_all_is_an_iterator(tmp_path):
    _write_part(tmp_path, "part-1.csv.gz", [
        "ABC,111,2021-01-01,10,11,9,10.5,1000,kite-connect-v3",
    ])
    result = bars.load_all(directory=tmp_path)
    assert iter(result) is result  # generator protocol: allowed by the spec as "an iterator"


def test_load_all_on_empty_directory_yields_nothing(tmp_path):
    _write_part(tmp_path, "part-1.csv.gz", [])
    assert list(bars.load_all(directory=tmp_path)) == []


# ---------------------------------------------------------------------------
# source_dir / env override
# ---------------------------------------------------------------------------

def test_source_dir_honors_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv(bars.ENV_VAR, str(tmp_path))
    assert bars.source_dir() == tmp_path


def test_source_dir_default_when_env_unset(monkeypatch):
    monkeypatch.delenv(bars.ENV_VAR, raising=False)
    assert bars.source_dir() == Path(bars.DEFAULT_KITE_DAILY_DIR)


# ---------------------------------------------------------------------------
# provenance (PRD §32.10)
# ---------------------------------------------------------------------------

def test_provenance_reports_files_hashes_row_counts_and_versions(tmp_path):
    p1 = _write_part(tmp_path, "part-1.csv.gz", [
        "ABC,111,2021-01-01,10,11,9,10.5,1000,kite-connect-v3",
        "XYZ,222,2021-01-01,50,51,49,50.5,500,kite-connect-v3",
    ])
    p2 = _write_part(tmp_path, "part-2.csv.gz", [])  # header only

    prov = bars.provenance(directory=tmp_path)
    assert prov.source_dir == str(tmp_path)
    assert prov.total_row_count == 2
    assert prov.symbol_count == 2
    assert prov.source_versions == ("kite-connect-v3",)
    assert len(prov.files) == 2

    by_path = {f.path: f for f in prov.files}
    assert by_path[str(p1)].sha256 == hashlib.sha256(p1.read_bytes()).hexdigest()
    assert by_path[str(p1)].row_count == 2
    assert by_path[str(p2)].sha256 == hashlib.sha256(p2.read_bytes()).hexdigest()
    assert by_path[str(p2)].row_count == 0
    assert by_path[str(p2)].source_versions == ()


# ---------------------------------------------------------------------------
# Real-data integration test — skipped, not failed, if the directory is absent.
# ---------------------------------------------------------------------------

_REAL_DIR = Path(bars.DEFAULT_KITE_DAILY_DIR)


@pytest.mark.skipif(not _REAL_DIR.is_dir(), reason="real Kite daily-bars directory not present in this environment")
def test_real_data_has_2926_symbols():
    # Independently verified (data-availability.md and this task's own re-derivation via
    # status.csv's OK count and a direct scan of the part files): 2,926 symbols.
    prov = bars.provenance()
    assert prov.symbol_count == 2926
    assert len(dict(bars.load_all())) == 2926
