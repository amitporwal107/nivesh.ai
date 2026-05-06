"""Unit tests for FRED observations (JSON) parser."""
from __future__ import annotations

import json

import pytest

from nidp.services.fred_macro.parser import (
    SERIES_CATALOG, parse_fred_observations,
)


def _obs(date: str, value: str) -> dict:
    return {
        "realtime_start": "2026-01-01", "realtime_end": "2026-01-01",
        "date": date, "value": value,
    }


def _envelope(observations: list[dict]) -> bytes:
    return json.dumps({
        "realtime_start": "2026-01-01", "realtime_end": "2026-01-01",
        "observation_start": "1962-01-02", "observation_end": "9999-12-31",
        "units": "lin", "output_type": 1, "file_type": "json",
        "order_by": "observation_date", "sort_order": "asc",
        "count": len(observations), "offset": 0, "limit": 100000,
        "observations": observations,
    }).encode()


def test_parse_dgs10_canonical():
    body = _envelope([
        _obs("2024-01-02", "3.95"),
        _obs("2024-01-03", "4.01"),
        _obs("2024-01-04", "."),                # FRED's missing-value sentinel
        _obs("2024-01-05", "4.05"),
    ])
    rows = parse_fred_observations(body, series_id="DGS10")
    assert len(rows) == 4
    by_date = {r["as_of_date"]: r for r in rows}
    assert by_date["2024-01-02"]["value"] == pytest.approx(3.95)
    assert by_date["2024-01-04"]["value"] is None    # '.' → None
    assert rows[0]["series_id"] == "DGS10"
    assert rows[0]["series_name"] == "US 10-year Treasury yield"
    assert rows[0]["units"] == "Percent"
    assert rows[0]["frequency"] == "Daily"


def test_parse_unknown_series_uses_id_as_name():
    body = _envelope([_obs("2024-01-02", "1.5")])
    rows = parse_fred_observations(body, series_id="FOOBAR")
    assert len(rows) == 1
    assert rows[0]["series_name"] == "FOOBAR"   # falls back to series_id
    assert rows[0]["units"] is None
    assert rows[0]["frequency"] is None


def test_empty_observations_returns_no_rows():
    assert parse_fred_observations(_envelope([]), series_id="DGS10") == []


def test_invalid_json_raises():
    with pytest.raises(ValueError, match="invalid JSON"):
        parse_fred_observations(b"not json", series_id="DGS10")


def test_api_error_payload_raises():
    """FRED returns 200 with an error_code body on bad keys / unknown ids —
    surface that as a ValueError so service.py records the run as failed
    with a real message, not "all N failed"."""
    body = json.dumps({
        "error_code": 400,
        "error_message": "Bad Request. Variable api_key is not registered.",
    }).encode()
    with pytest.raises(ValueError, match="API error 400"):
        parse_fred_observations(body, series_id="DGS10")


def test_skips_malformed_rows():
    body = _envelope([
        _obs("2024-01-02", "3.95"),
        _obs("BAD-DATE", "1.0"),                # invalid date row dropped
        _obs("2024-01-03", "4.01"),
    ])
    rows = parse_fred_observations(body, series_id="DGS10")
    assert len(rows) == 2
    assert {r["as_of_date"] for r in rows} == {"2024-01-02", "2024-01-03"}


def test_series_catalog_completeness():
    """All curated series have name + units + frequency."""
    expected_keys = {"DGS10", "DGS2", "DTWEXBGS", "DCOILBRENTEU",
                     "DCOILWTICO", "VIXCLS", "GOLDAMGBD228NLBM", "FEDFUNDS"}
    assert set(SERIES_CATALOG.keys()) == expected_keys
    for sid, (name, units, freq) in SERIES_CATALOG.items():
        assert name and units and freq, f"{sid} has incomplete catalog entry"
