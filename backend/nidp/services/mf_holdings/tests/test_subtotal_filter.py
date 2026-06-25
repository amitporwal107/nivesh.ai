"""SD-06: the generic portfolio parser must drop subtotal / grand-total / section-label
rows. Before this, NIPPON schemes summed to ~224% because every section's Sub Total plus
the Grand Total were ingested alongside the real holdings."""
from nidp.services.mf_holdings.sbi_parser import _parse_sheet


def test_subtotal_and_section_rows_dropped():
    rows = [
        ("100375", "Nippon India Large Cap Fund", "", "", ""),                      # scheme name
        ("Name of the Instrument", "ISIN", "Quantity", "Market Value", "% to NAV"),  # header
        ("(a) Listed / awaiting listing on Stock Exchanges", "", "", "", ""),       # section label (no value)
        ("BSE Limited",             "INE118H01025", "5300000", "14222.55", "38.0"),  # real
        ("Reliance Industries Ltd", "INE002A01018", "1000000", "12000.00", "35.0"),  # real
        ("HDFC Bank Ltd",           "INE040A01034", "500000",  "8000.00",  "24.0"),  # real
        ("Sub Total",               "",             "",        "34222.55", "97.0"),  # SUBTOTAL -> drop
        ("(b) Unlisted",            "",             "",        "500.00",   "5.0"),   # section label w/ value -> drop
        ("TREPS / Reverse Repo",    "",             "",        "1000.00",  "3.0"),   # legit cash -> KEEP
        ("Grand Total",             "",             "",        "35222.55", "100.0"), # GRAND TOTAL -> drop
        ("Total Energies SE",       "INE999Z01011", "100",     "50.00",    "0.0"),   # real ('Total' but valid ISIN) -> KEEP
    ]
    out = _parse_sheet(rows, "2026-03-01", "http://x", "sheet1", "NIPPON_MF_PORTFOLIO_XLSX")
    names = {r["security_name"] for r in out}
    total_wt = sum(r["weight_pct"] or 0 for r in out)

    assert {"Sub Total", "(b) Unlisted", "Grand Total"} & names == set()
    assert {"BSE Limited", "Reliance Industries Ltd", "HDFC Bank Ltd",
            "TREPS / Reverse Repo", "Total Energies SE"} <= names
    assert 99.0 <= total_wt <= 101.0
