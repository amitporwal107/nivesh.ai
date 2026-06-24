"""Bug 2b regression: parse_sbi_multisheet_xlsx must drop section subtotal / "Total" /
"GRAND TOTAL (AUM)" rows. Verified on a real SBI file (SBI Bluchip Feb-2021) where the
sheet lists holdings + per-section "Total" rows + a "GRAND TOTAL (AUM)", which the
multisheet path counted as holdings → per-scheme weight summed to ~300% instead of 100%.
(_parse_sheet already filtered these; the SBI multisheet path did not.)
"""
import io
from datetime import date

import openpyxl

from nidp.services.mf_holdings.sbi_parser import parse_sbi_multisheet_xlsx


def _build_sbi_workbook() -> bytes:
    wb = openpyxl.Workbook()
    # Index sheet: shortcode -> scheme name (rows[2:] are read)
    idx = wb.active
    idx.title = "Index"
    idx.append(["", "", ""])
    idx.append(["", "", ""])
    idx.append(["", "SCH1", "Test Bluechip Fund"])

    sh = wb.create_sheet("SCH1")
    sh.append([None] * 8)
    sh.append([None, None, "SBI MUTUAL FUND", "103"])
    sh.append([None, None, "SCHEME NAME :", "Test Bluechip Fund"])
    sh.append([None, None, "PORTFOLIO STATEMENT AS ON :", "2021-02-28"])
    sh.append([None] * 8)
    # header row (col indices mirror the real sheet: name@2, isin@3, ind@4, qty@5, mv@6, %@7)
    sh.append([None, None, "Name of the Instrument", "ISIN", "Rating / Industry^",
               "Quantity", "Market Value (Rs. in Lakhs)", "% to AUM"])
    sh.append([None] * 8)
    sh.append([None, None, "EQUITY & EQUITY RELATED", None, None, None, None, None])
    sh.append([None, None, "HDFC Bank Ltd.", "INE040A01034", "Banks", 100, 600.0, 60.0])
    sh.append([None, None, "ICICI Bank Ltd.", "INE090A01021", "Banks", 100, 350.0, 35.0])
    sh.append([None, None, "Total", None, None, None, 950.0, 95.0])              # subtotal -> drop
    sh.append([None, None, "TREPS / Reverse Repo", None, "CBLO", None, 50.0, 5.0])  # cash -> keep
    sh.append([None, None, "GRAND TOTAL (AUM)", None, None, None, 1000.0, 100.0])  # grand total -> STOP
    # Below GRAND TOTAL: the DERIVATIVES / hedging-exposure detail table. Same header
    # row above, but column [3] now holds the futures EXPIRY DATE (not an ISIN) and
    # column [7] holds NOTIONAL values (not %). These must NOT be ingested as holdings.
    sh.append([None, None, "DERIVATIVES", None, None, None, None, None])
    sh.append([None, None, "Alkem Laboratories Ltd.", "2026-06-30 00:00:00", None, 100, None, 3441.13])
    sh.append([None, None, "Wipro Ltd.", "2026-06-30 00:00:00", None, 200, None, 2560.75])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_multisheet_drops_subtotal_and_grand_total():
    rows = parse_sbi_multisheet_xlsx(_build_sbi_workbook(), date(2021, 2, 1),
                                     source_url="x", source_tag="SBI_MF_PORTFOLIO_XLSX")
    names = {r["security_name"] for r in rows}
    assert "Total" not in names and "GRAND TOTAL (AUM)" not in names   # aggregations dropped
    assert {"HDFC Bank Ltd.", "ICICI Bank Ltd.", "TREPS / Reverse Repo"} <= names  # holdings kept
    total = sum((r["weight_pct"] or 0) for r in rows)
    assert 99.0 <= total <= 101.0                                       # reconciles to ~100, not ~300


def test_multisheet_stops_at_grand_total_excludes_derivatives_table():
    rows = parse_sbi_multisheet_xlsx(_build_sbi_workbook(), date(2021, 2, 1),
                                     source_url="x", source_tag="SBI_MF_PORTFOLIO_XLSX")
    names = {r["security_name"] for r in rows}
    # The post-GRAND-TOTAL derivatives detail rows (date-in-ISIN, notional weights)
    # must be excluded entirely — they were the production date-in-ISIN + >1000% source.
    assert "Alkem Laboratories Ltd." not in names
    assert "Wipro Ltd." not in names
    # And no row carries a date or notional in place of a real ISIN / weight.
    assert all(r["security_isin"] is None or r["security_isin"].startswith("INE") for r in rows)
    assert all((r["weight_pct"] or 0) <= 100 for r in rows)
