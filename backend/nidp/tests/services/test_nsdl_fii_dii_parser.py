"""Golden-fixture tests for the NSDL FPI/DII fallback parsers.

Fixtures are the real pages fetched on 2026-08-18 for report date
2026-08-17, saved verbatim under tests/fixtures/nsdl/. Every expected
number below was read off the rendered NSDL grid.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nidp.services.fii_dii.nsdl_parser import (
    _num,
    parse_nsdl_dii,
    parse_nsdl_fpi,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "nsdl"
FPI = (FIXTURES / "fpi_latest_20260817.html").read_bytes()
DII = (FIXTURES / "dii_latest_20260817.html").read_bytes()


def _by(rows, **kw):
    for r in rows:
        if all(r.get(k) == v for k, v in kw.items()):
            return r
    raise AssertionError(f"no row matching {kw} in {[ (r['category'], r['segment']) for r in rows ]}")


# ── number parsing ───────────────────────────────────────────────────
@pytest.mark.parametrize("raw,expected", [
    ("13756.70", 13756.70),
    ("(618.83)", -618.83),          # NSDL writes negatives in parentheses
    ("0.00", 0.0),
    ("1,234.56", 1234.56),
    ("", None),
    ("-", None),
])
def test_num_parsing(raw, expected):
    assert _num(raw) == expected


# ── FPI leg ──────────────────────────────────────────────────────────
def test_fpi_equity_cash_matches_published_grid():
    row = _by(parse_nsdl_fpi(FPI), category="FII", segment="EQUITY_CASH")
    assert row["as_of_date"] == "2026-08-17"
    assert row["buy_value_cr"] == 13756.70
    assert row["sell_value_cr"] == 12926.71
    assert row["net_value_cr"] == 829.99


def test_fpi_inherits_asset_class_across_rowspan():
    """'Primary market & others' carries no asset label — it inherits Equity."""
    row = _by(parse_nsdl_fpi(FPI), category="FII", segment="EQUITY_PRIMARY")
    assert row["buy_value_cr"] == 3282.00
    assert row["net_value_cr"] == 3282.00


def test_fpi_parenthesised_value_is_negative():
    row = _by(parse_nsdl_fpi(FPI), segment="DEBT_GENERAL_LIMIT")
    assert row["net_value_cr"] == -618.83


def test_fpi_skips_nsdl_own_subtotals_and_total():
    """Sub-total / Total rows must never be stored as segments."""
    segs = {r["segment"] for r in parse_nsdl_fpi(FPI)}
    assert not {s for s in segs if "TOTAL" in s.upper()}, segs


def test_fpi_net_is_consistent_with_buy_minus_sell():
    for r in parse_nsdl_fpi(FPI):
        assert r["net_value_cr"] == pytest.approx(
            r["buy_value_cr"] - r["sell_value_cr"], abs=0.02), r


# ── DII leg ──────────────────────────────────────────────────────────
def test_dii_splits_by_investor_type():
    rows = parse_nsdl_dii(DII)
    got = {r["category"]: r["net_value_cr"] for r in rows}
    assert got["DII_BANK"] == 387.43
    assert got["DII_INSURANCE"] == -145.32
    assert got["DII_MF"] == -113.97
    assert got["DII_AIF"] == -331.08
    assert got["DII_OTHERS"] == 419.12


def test_dii_derived_total_equals_sum_of_types():
    rows = parse_nsdl_dii(DII)
    total = _by(rows, category="DII")
    parts = [r for r in rows if r["category"].startswith("DII_")]
    assert len(parts) == 5
    assert total["net_value_cr"] == pytest.approx(
        sum(p["net_value_cr"] for p in parts), abs=0.01)
    assert total["buy_value_cr"] == pytest.approx(
        sum(p["buy_value_cr"] for p in parts), abs=0.01)


def test_dii_skips_nsdl_star_total_rows():
    """'Bank-total' etc. run across instruments and are NOT summable."""
    cats = {r["category"] for r in parse_nsdl_dii(DII)}
    assert "DII_BANK_TOTAL" not in cats
    # Bank-total net is (580.05); it must not leak in as a Bank figure.
    assert _by(parse_nsdl_dii(DII), category="DII_BANK")["net_value_cr"] == 387.43


def test_dii_only_equity_stock_exchange_leg_is_kept():
    """Corporate Debt / Government Debt / Bullion legs are not equity flows."""
    rows = parse_nsdl_dii(DII)
    assert {r["segment"] for r in rows} == {"EQUITY_CASH"}
    # Bank's Corporate Debt net is (395.95) — must not appear anywhere.
    assert all(r["net_value_cr"] != -395.95 for r in rows)


def test_dii_validator_contract_both_categories_present():
    """fii_dii.cash_rows_present requires FII *and* DII for EQUITY_CASH."""
    cats = {r["category"] for r in parse_nsdl_fpi(FPI) + parse_nsdl_dii(DII)}
    assert {"FII", "DII"} <= cats


def test_empty_body_yields_no_rows_rather_than_raising():
    assert parse_nsdl_fpi(b"<html></html>", "2026-08-17") == []
    assert parse_nsdl_dii(b"<html></html>", "2026-08-17") == []
