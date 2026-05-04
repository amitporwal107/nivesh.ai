"""Golden-file tests for corporate_actions parser.

The classifier is regex-based and the most likely future regression
site as NSE shifts purpose-string formatting. Every supported
action_type has a row here; an unsupported row falls through to OTHER
(never silently dropped).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nidp.services.corporate_actions.parser import parse_corporate_actions

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_classify_all_action_types():
    body = (FIXTURES / "corporate_actions_sample.csv").read_bytes()
    rows = parse_corporate_actions(body)
    assert len(rows) == 7
    by_sym = {r["symbol"]: r for r in rows}

    assert by_sym["RELIANCE"]["action_type"] == "DIVIDEND"
    assert by_sym["RELIANCE"]["dividend_amount"] == pytest.approx(5.0)
    assert by_sym["RELIANCE"]["ex_date"] == "2026-05-15"
    assert by_sym["RELIANCE"]["record_date"] == "2026-05-16"

    assert by_sym["TCS"]["action_type"] == "DIVIDEND"
    assert by_sym["TCS"]["action_subtype"] == "INTERIM"
    assert by_sym["TCS"]["dividend_amount"] == pytest.approx(12.0)

    assert by_sym["INFY"]["action_type"] == "BONUS"
    assert by_sym["INFY"]["ratio"] == "1:1"

    assert by_sym["HDFCBANK"]["action_type"] == "SPLIT"
    assert by_sym["HDFCBANK"]["face_value_pre"] == pytest.approx(10.0)
    assert by_sym["HDFCBANK"]["face_value_post"] == pytest.approx(2.0)

    assert by_sym["WIPRO"]["action_type"] == "RIGHTS"
    assert by_sym["WIPRO"]["ratio"] == "1:5"

    assert by_sym["ITC"]["action_type"] == "BUYBACK"

    # Unrecognised purpose lands as OTHER, raw purpose preserved
    other = by_sym["NEWCO"]
    assert other["action_type"] == "OTHER"
    assert "RECOGNISE" in (other["purpose"] or "")


def test_missing_required_columns_raises():
    body = b"SYMBOL,SERIES\nFOO,EQ\n"
    with pytest.raises(ValueError, match="missing required columns"):
        parse_corporate_actions(body)


def test_empty_body():
    assert parse_corporate_actions(b"") == []
