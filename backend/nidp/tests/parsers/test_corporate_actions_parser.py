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


def test_classify_real_nse_strings_that_previously_landed_as_other():
    """Regression: 9 rows tripped other_ratio_not_dominant on 2026-05-06.

    Each string below was observed in nidp.corporate_actions with
    action_type='OTHER'. Pinning them here so future regex regressions
    fail loudly.
    """
    from nidp.services.corporate_actions.parser import _classify

    # "Re" (singular) currency token — _DIV_RE didn't accept it before.
    t, sub, fields = _classify("Interim Dividend - Re 0.50 Per Share")
    assert t == "DIVIDEND"
    assert sub == "INTERIM"
    assert fields["dividend_amount"] == pytest.approx(0.50)

    t, sub, fields = _classify("Interim Dividend - Re 1 Per Share")
    assert t == "DIVIDEND"
    assert fields["dividend_amount"] == pytest.approx(1.0)

    # Govt-securities coupon — new INTEREST_PAYMENT bucket.
    t, _, _ = _classify("Interest Payment")
    assert t == "INTEREST_PAYMENT"

    # InvIT/REIT distribution — new DISTRIBUTION bucket, headline amount captured.
    t, _, fields = _classify(
        "Distribution - Rs 3.50 Per Unit Consisting Of Re 1.01 Per Unit "
        "As Interest/ Rs 2.49 Per Unit As Return Of Capital"
    )
    assert t == "DISTRIBUTION"
    assert fields["dividend_amount"] == pytest.approx(3.50)

    # Face-value split with "/-" formatting — _SPLIT_RE used to bail on the
    # "/- Per Share To Re" gap between pre and post values.
    t, _, fields = _classify(
        "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share"
    )
    assert t == "SPLIT"
    assert fields["face_value_pre"] == pytest.approx(10.0)
    assert fields["face_value_post"] == pytest.approx(1.0)


def test_missing_required_columns_raises():
    body = b"SYMBOL,SERIES\nFOO,EQ\n"
    with pytest.raises(ValueError, match="missing required columns"):
        parse_corporate_actions(body)


def test_empty_body():
    assert parse_corporate_actions(b"") == []
