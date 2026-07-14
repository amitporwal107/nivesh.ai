"""Unit tests for CAS statement-period label derivation.

Locks down period_label_from_date() — the fallback that lets the "Last CAS"
dashboard banner show a month for custom-extractor CAS layouts (NSDL / CAMS /
KFin), which provide a statement DATE but no casparser meta period, so
extract_statement_period() alone returns None for them.
"""
from services.cas_api_client import period_label_from_date


def test_dd_mmm_yyyy_to_period():
    # CAMS/KFin + NSDL custom extractors emit "DD-MMM-YYYY".
    assert period_label_from_date("31-Mar-2025") == "Mar/2025"
    assert period_label_from_date("01-Apr-2026") == "Apr/2026"


def test_iso_date_to_period():
    assert period_label_from_date("2025-03-31") == "Mar/2025"


def test_slash_ddmmyyyy_to_period():
    assert period_label_from_date("31/03/2025") == "Mar/2025"


def test_already_a_period_label_is_passed_through():
    # Idempotent: a value already in "MMM/YYYY" is returned unchanged.
    assert period_label_from_date("Mar/2025") == "Mar/2025"


def test_unparseable_or_missing_returns_none():
    assert period_label_from_date("not a date") is None
    assert period_label_from_date("") is None
    assert period_label_from_date(None) is None
    assert period_label_from_date(12345) is None  # non-str input


def test_full_month_name_variant():
    assert period_label_from_date("31-March-2025") == "Mar/2025"
