"""Regression tests for two mf_holdings parser fixes (2026-06-24):

Bug 1 — weight-unit inconsistency: _normalise_weights normalised to a 0–1 fraction,
but the DB column, the DQ per-scheme weight-sum check and the v3 primitives view
(top10_concentration_pct = SUM(weight_pct)) all read weight_pct as a percent. 5 of 6
AMC parsers therefore stored fractions (per-scheme sum ≈1.0), failing the sum-≈100
check for 1,497 schemes and understating concentration ~100×. Now normalises to %.

Bug 2a — ISIN write-guard: a misaligned SBI column landed a date in security_isin
('2026-05-26 00:00:00') for 3,160 rows. _clean_isin rejects anything that isn't a
well-formed ISIN.
"""
from nidp.services.mf_holdings.sbi_parser import (
    _clean_isin,
    _normalise_weights,
    _parse_sheet,
)


# ── Bug 1: weight units ───────────────────────────────────────────────
def test_fraction_weights_scaled_to_percent():
    rows = [{"weight_pct": 0.0421}, {"weight_pct": 0.0276}, {"weight_pct": 0.02}]
    out = _normalise_weights([dict(r) for r in rows])
    assert round(sum(r["weight_pct"] for r in out), 4) == 8.97


def test_percent_weights_left_unchanged():
    rows = [{"weight_pct": 8.91}, {"weight_pct": 7.71}, {"weight_pct": 6.10}]
    out = _normalise_weights([dict(r) for r in rows])
    assert round(sum(r["weight_pct"] for r in out), 2) == 22.72


def test_normalise_weights_handles_empty_and_none():
    assert _normalise_weights([]) == []
    assert _normalise_weights([{"weight_pct": None}]) == [{"weight_pct": None}]


# ── Bug 2a: ISIN write-guard ──────────────────────────────────────────
def test_clean_isin_rejects_date_and_garbage():
    assert _clean_isin("2026-05-26 00:00:00") is None
    assert _clean_isin("-") is None
    assert _clean_isin("N.A.") is None
    assert _clean_isin(None) is None
    assert _clean_isin("") is None


def test_clean_isin_keeps_and_uppercases_valid():
    assert _clean_isin("INE002A01018") == "INE002A01018"
    assert _clean_isin("  ine002a01018 ") == "INE002A01018"


def test_parse_sheet_nulls_date_in_isin_column_keeps_security():
    rows = [
        ("SBI Bluechip Fund", "", "", "", ""),                                  # scheme name
        ("Name of Instrument", "ISIN", "Quantity", "Market Value", "% to NAV"),  # header
        # ISIN column holds a date (the SBI misalignment) — security must survive, ISIN nulled
        ("ABB India Ltd.", "2026-05-26 00:00:00", "1000", "5000.00", "4.21"),
        ("Reliance Industries Ltd", "INE002A01018", "2000", "8000.00", "3.50"),  # well-formed
    ]
    out = _parse_sheet(rows, "2026-04-01", "http://x", "s1", "SBI_MF_PORTFOLIO_XLSX")
    by_name = {r["security_name"]: r for r in out}
    assert "ABB India Ltd." in by_name                      # row kept
    assert by_name["ABB India Ltd."]["security_isin"] is None      # date rejected
    assert by_name["Reliance Industries Ltd"]["security_isin"] == "INE002A01018"
