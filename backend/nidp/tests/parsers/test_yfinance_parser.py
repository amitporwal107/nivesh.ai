"""Unit tests for yfinance v8 chart-API parser. No network."""
from __future__ import annotations

import json

import pytest

from nidp.services.yfinance_backfill.parser import (
    epoch_range_for, parse_yf_chart,
)


def _yf_response(opens, highs, lows, closes, volumes, timestamps, symbol="RELIANCE.NS"):
    return {
        "chart": {
            "result": [{
                "meta": {"symbol": symbol},
                "timestamp": timestamps,
                "indicators": {
                    "quote": [{
                        "open": opens, "high": highs, "low": lows,
                        "close": closes, "volume": volumes,
                    }],
                    "adjclose": [{"adjclose": closes}],
                }
            }]
        }
    }


def test_parse_typical_two_day_response():
    body = json.dumps(_yf_response(
        opens=[1296.0, 1300.5],
        highs=[1310.0, 1315.0],
        lows=[1290.0, 1296.0],
        closes=[1305.5, 1311.0],
        volumes=[2_500_000, 2_700_000],
        timestamps=[1735603200, 1735689600],
    )).encode()
    rows = parse_yf_chart(body, symbol="RELIANCE")
    assert len(rows) == 2
    assert rows[0]["symbol"] == "RELIANCE"
    assert rows[0]["close_price"] == pytest.approx(1305.5)
    assert rows[0]["volume"] == 2_500_000
    assert rows[0]["prev_close"] is None  # first row has no prior close
    assert rows[1]["prev_close"] == pytest.approx(1305.5)


def test_parse_handles_null_close_skipped():
    """YF returns null for non-trading days. Parser must skip those."""
    body = json.dumps(_yf_response(
        opens=[1296.0, None, 1300.0],
        highs=[1310.0, None, 1315.0],
        lows=[1290.0, None, 1296.0],
        closes=[1305.5, None, 1311.0],
        volumes=[2_500_000, None, 2_700_000],
        timestamps=[1735603200, 1735689600, 1735776000],
    )).encode()
    rows = parse_yf_chart(body, symbol="RELIANCE")
    assert len(rows) == 2  # null-close row dropped
    assert rows[0]["close_price"] == pytest.approx(1305.5)
    assert rows[1]["close_price"] == pytest.approx(1311.0)


def test_yf_error_response_raises():
    """Bad ticker → YF returns {chart: {result: null, error: {...}}}."""
    body = json.dumps({
        "chart": {
            "result": None,
            "error": {"code": "Not Found",
                      "description": "No data found, symbol may be delisted"}
        }
    }).encode()
    with pytest.raises(ValueError, match="yf chart error"):
        parse_yf_chart(body, symbol="BADSYM")


def test_empty_result_returns_no_rows():
    body = json.dumps({"chart": {"result": []}}).encode()
    assert parse_yf_chart(body, symbol="X") == []


def test_invalid_json_raises():
    with pytest.raises(ValueError, match="invalid JSON"):
        parse_yf_chart(b"not-json", symbol="X")


def test_epoch_range_known_dates():
    # 2010-01-01 UTC = 1262304000
    p1, p2 = epoch_range_for("2010-01-01", "2024-12-31")
    assert p1 == 1262304000
    assert p2 == 1735603200


def test_series_field_default_eq():
    body = json.dumps(_yf_response(
        opens=[100.0], highs=[101.0], lows=[99.0], closes=[100.5],
        volumes=[1000], timestamps=[1735603200],
    )).encode()
    rows = parse_yf_chart(body, symbol="WIPRO")
    assert rows[0]["series"] == "EQ"


def test_series_can_be_overridden():
    body = json.dumps(_yf_response(
        opens=[100.0], highs=[101.0], lows=[99.0], closes=[100.5],
        volumes=[1000], timestamps=[1735603200],
    )).encode()
    rows = parse_yf_chart(body, symbol="WIPRO", series="BE")
    assert rows[0]["series"] == "BE"
