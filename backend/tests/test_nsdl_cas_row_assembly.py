"""Row assembly in services/nsdl_cas_extractor.py.

An NSDL eCAS holding is one table row, but pdfplumber's text layer delivers it
as one to five lines depending on how the cells are stacked. These cases mirror
the layouts seen in a real August-2026 statement; every ISIN, name and figure
below is made up.
"""
import pytest

from services.nsdl_cas_extractor import (
    _assemble_row,
    _clean_line,
    _parse_holding_line,
)


def _row(raw_lines, isin_index, klass):
    lines = [_clean_line(ln) for ln in raw_lines]
    return _parse_holding_line(_assemble_row(lines, isin_index, klass), klass)


def test_equity_row_already_on_one_line_is_unchanged():
    raw = ["INE000A01011 ALPHA LIMITED 2.00 100 50.00 5,000.00"]
    lines = [_clean_line(ln) for ln in raw]
    assert _assemble_row(lines, 0, "E") == lines[0]
    h = _row(raw, 0, "E")
    assert (h.quantity, h.current_price, h.value) == (100, 50.0, 5000.0)


def test_equity_isin_alone_columns_on_next_line():
    h = _row([
        "INE000A01011",
        "ALPHA RENEWABLES LIMITED 1.00 100 502.60 50,260.00",
        "ALPHAREN.NSE",
    ], 0, "E")
    assert h.isin == "INE000A01011"
    assert h.name == "ALPHA RENEWABLES LIMITED"
    assert (h.quantity, h.current_price, h.value) == (100, 502.60, 50260.0)


def test_equity_quantity_on_isin_line_with_pledge_subline():
    h = _row([
        "INE000B01019 BETA LIFESTYLE BRANDS LIMITED 187",
        "10.00 86.71 16,214.77",
        "BETALB.NSE of which Pledged / Unconfirmed Pledge 141",
    ], 0, "E")
    assert h.name == "BETA LIFESTYLE BRANDS LIMITED"
    # 187 is the holding; 141 is the pledged part and must not be read as quantity
    assert (h.quantity, h.current_price, h.value) == (187, 86.71, 16214.77)


def test_equity_name_wrapped_around_isin_line():
    h = _row([
        "PREVIOUS.NSE 164",
        "GAMMA GREAVES CONSUMER ELECTRICALS",
        "INE000C01017 63",
        "LIMITED 2.00 235.90 14,861.70",
        "GAMMA.NSE 63",
        "of which Pledged / Unconfirmed Pledge",
    ], 2, "E")
    assert h.name == "GAMMA GREAVES CONSUMER ELECTRICALS LIMITED"
    assert (h.quantity, h.current_price, h.value) == (63, 235.90, 14861.70)


def test_equity_figures_printed_on_the_pledge_label_line():
    h = _row([
        "DELTA PRIME INFRA LIMITED",
        "IN0000D01013 21",
        "of which Pledged / Unconfirmed Pledge 2.00 40.52 850.92",
        "ISIN SUSPENDED 20",
    ], 1, "E")
    assert h.name == "DELTA PRIME INFRA LIMITED"
    assert (h.quantity, h.current_price, h.value) == (21, 40.52, 850.92)


def test_preference_row_issuer_above_isin():
    h = _row([
        "EPSILON MOTOR COMPANY LIMITED",
        "INE000E04019",
        "6% Non Convertible Redeemable Preference Shares 10.00 24 10.55 253.20",
        "Suspended",
    ], 1, "P")
    assert h.name.startswith("EPSILON MOTOR COMPANY LIMITED")
    assert (h.quantity, h.current_price, h.value) == (24, 10.55, 253.20)


def test_demat_mf_row_on_one_line():
    h = _row(["INF000F01037 ZETA ETF LIQUID 0.726 1,000.00 726.00"], 0, "M")
    assert (h.quantity, h.current_price, h.value) == (0.726, 1000.0, 726.0)


def test_demat_mf_name_and_units_above_isin():
    h = _row([
        "ETA PRUDENTIAL NIFTY 100 LOW VOLATILITY 30 ETF-- 453",
        "INF000G01034 22.34 10,119.02",
        "of which Pledged / Unconfirmed Pledge 113",
    ], 1, "M")
    # 100 and 30 belong to the fund name; 453 is the units, 113 the pledged part
    assert (h.quantity, h.current_price, h.value) == (453, 22.34, 10119.02)


def test_folio_row_figures_below_isin_and_name_continued_after_ucc():
    h = _row([
        "INF000H01QE4 Theta Arbitrage Fund - Regular Monthly",
        "910140445463 100.000 10.0000 1,000.00 11.0000 1,100.00 100.00",
        "MFTHETA0100 IDCW",
    ], 0, "F")
    assert h.name == "Theta Arbitrage Fund - Regular Monthly IDCW"
    assert (h.quantity, h.current_price, h.value) == (100.0, 11.0, 1100.0)
    assert h.cost_basis == 1000.0


def test_folio_row_isin_alone_name_wrapped_around_it():
    h = _row([
        "Iota India Flexi Cap Fund - Direct Plan",
        "INF000I01FK3",
        "- Growth (erstwhile Iota India Equity 34332289 20.000 1,000.0000 20,000.00 1,100.0000 22,000.00 2,000.00",
        "IOTAGPD",
        "Fund - Direct)",
    ], 1, "F")
    assert h.name.startswith("Iota India Flexi Cap Fund - Direct Plan - Growth")
    assert (h.quantity, h.current_price, h.value) == (20.0, 1100.0, 22000.0)
    assert h.cost_basis == 20000.0


@pytest.mark.parametrize("neighbour", [
    "Sub Total 85,511.00",
    "INE000J01011 KAPPA LIMITED 2.00 10 5.00 50.00",
    "Mutual Funds (M)",
])
def test_incomplete_row_does_not_borrow_from_a_total_another_row_or_a_section(neighbour):
    lines = [_clean_line(ln) for ln in ["INE000K01010", neighbour]]
    assert _assemble_row(lines, 0, "E") == "INE000K01010"
