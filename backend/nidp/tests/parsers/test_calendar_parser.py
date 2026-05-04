"""Golden-file tests for NSE holiday-master parser."""
from __future__ import annotations

from pathlib import Path

from nidp.services.nse_calendar.parser import parse_calendar

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_parse_calendar_canonical():
    body = (FIXTURES / "nse_calendar_sample.json").read_bytes()
    rows = parse_calendar(body)

    # 3 CM + 2 FO = 5 rows
    assert len(rows) == 5

    cm_rows = [r for r in rows if r["segment"] == "CM"]
    assert len(cm_rows) == 3
    holi = next(r for r in cm_rows if r["description"] == "Holi")
    assert holi["holiday_date"] == "2026-03-04"

    fo_rows = [r for r in rows if r["segment"] == "FO"]
    assert len(fo_rows) == 2


def test_parse_calendar_data_wrapper():
    body = b'{"data": {"CM": [{"tradingDate":"04-Mar-2026","description":"Holi"}]}}'
    rows = parse_calendar(body)
    assert len(rows) == 1
    assert rows[0]["holiday_date"] == "2026-03-04"
    assert rows[0]["segment"] == "CM"


def test_parse_calendar_invalid_json_raises():
    import pytest
    with pytest.raises(ValueError):
        parse_calendar(b"<html>not json</html>")
