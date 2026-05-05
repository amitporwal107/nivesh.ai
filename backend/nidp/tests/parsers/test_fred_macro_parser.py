"""Unit tests for FRED CSV parser."""
from __future__ import annotations

import pytest

from nidp.services.fred_macro.parser import (
    SERIES_CATALOG, parse_fred_csv,
)


def test_parse_dgs10_canonical():
    body = (
        b"DATE,DGS10\n"
        b"2024-01-02,3.95\n"
        b"2024-01-03,4.01\n"
        b"2024-01-04,.\n"               # FRED's missing-value sentinel
        b"2024-01-05,4.05\n"
    )
    rows = parse_fred_csv(body, series_id="DGS10")
    assert len(rows) == 4
    by_date = {r["as_of_date"]: r for r in rows}
    assert by_date["2024-01-02"]["value"] == pytest.approx(3.95)
    assert by_date["2024-01-04"]["value"] is None    # '.' → None
    assert rows[0]["series_id"] == "DGS10"
    assert rows[0]["series_name"] == "US 10-year Treasury yield"
    assert rows[0]["units"] == "Percent"
    assert rows[0]["frequency"] == "Daily"


def test_parse_unknown_series_uses_id_as_name():
    body = b"DATE,FOOBAR\n2024-01-02,1.5\n"
    rows = parse_fred_csv(body, series_id="FOOBAR")
    assert len(rows) == 1
    assert rows[0]["series_name"] == "FOOBAR"   # falls back to series_id
    assert rows[0]["units"] is None
    assert rows[0]["frequency"] is None


def test_empty_csv_returns_no_rows():
    assert parse_fred_csv(b"", series_id="DGS10") == []
    assert parse_fred_csv(b"DATE,DGS10\n", series_id="DGS10") == []


def test_skips_malformed_rows():
    body = (
        b"DATE,DGS10\n"
        b"2024-01-02,3.95\n"
        b"BAD-DATE,1.0\n"               # invalid date row dropped
        b"2024-01-03,4.01\n"
    )
    rows = parse_fred_csv(body, series_id="DGS10")
    assert len(rows) == 2
    assert {r["as_of_date"] for r in rows} == {"2024-01-02", "2024-01-03"}


def test_series_catalog_completeness():
    """All curated series have name + units + frequency."""
    expected_keys = {"DGS10", "DGS2", "DTWEXBGS", "DCOILBRENTEU",
                     "DCOILWTICO", "VIXCLS", "GOLDAMGBD228NLBM", "FEDFUNDS"}
    assert set(SERIES_CATALOG.keys()) == expected_keys
    for sid, (name, units, freq) in SERIES_CATALOG.items():
        assert name and units and freq, f"{sid} has incomplete catalog entry"
