"""CDSL coverage for nivesh_cas_normalizer.

These are deterministic unit tests of `normalize()` driven by synthesised
Document AI `{text, tables}` inputs — they don't call Google Document AI
and don't need network. They lock in:

  1. Depository detection (CDSL vs NSDL)
  2. CDSL table classification (cdsl_equity, cdsl_mf_folio)
  3. CDSL row extractors → unified holdings schema buckets
  4. CDSL statement / investor extraction (BO ID, DD-MM-YYYY period)
  5. NSDL flow remains intact

The chosen ISIN/quantity/price values mirror the
`tests/test_data/expected_outputs/varun_cdsl.json` fixture so future Doc AI
integration tests can reuse the assertions.
"""
import sys

sys.path.insert(0, "/app/backend")

from services.nivesh_cas_normalizer import (  # noqa: E402
    _classify_table,
    _cdsl_equity_row_to_record,
    _cdsl_mf_folio_row_to_record,
    _detect_depository,
    _extract_investor_info,
    _extract_statement_info,
    normalize,
)


# ── Depository detection ──────────────────────────────────────────────
def test_detect_depository_nsdl_default():
    assert _detect_depository("") == "NSDL"
    assert _detect_depository("National Securities Depository Limited\nNSDL ID: 12345") == "NSDL"


def test_detect_depository_cdsl_marker():
    text = "Central Depository Services Limited\nBO ID: 1234 5678 9012 3456\nVARUN AGARWAL"
    assert _detect_depository(text) == "CDSL"


def test_detect_depository_consolidated_prefers_nsdl():
    """Consolidated CASes name both NSDL and CDSL on the cover page; an
    explicit `NSDL ID:` is the dominant signal so we keep treating the
    file as NSDL (the existing pipeline)."""
    text = "Welcome to your CDSL & NSDL CAS\nNSDL ID: 109876543\nBO ID: 1234567890123456"
    assert _detect_depository(text) == "NSDL"


# ── Statement / investor extraction ───────────────────────────────────
def test_extract_statement_info_cdsl_period_and_id():
    text = (
        "Central Depository Services Limited\n"
        "BO ID: 1234 5678 9012 3456\n"
        "Period: 01-02-2026 to 28-02-2026\n"
    )
    si = _extract_statement_info(text)
    assert si["depository"] == "CDSL"
    assert si["id"] == "1234567890123456"
    assert si["period"] == "01-02-2026 to 28-02-2026"


def test_extract_investor_info_cdsl_bo_name():
    text = (
        "Central Depository Services Limited\n"
        "BO ID: 1234567890123456\n"
        "BO Name: VARUN AGARWAL\n"
        "PAN: ABCDE1234F\n"
    )
    inv = _extract_investor_info(text, depository="CDSL")
    assert inv["name"] == "VARUN AGARWAL"
    assert inv["pan"] == "ABCDE1234F"


def test_extract_statement_info_nsdl_unchanged():
    text = (
        "NSDL ID: 109876543\n"
        "Statement period from 01-Apr-2025 to 31-Mar-2026\n"
    )
    si = _extract_statement_info(text)
    assert si["depository"] == "NSDL"
    assert si["id"] == "109876543"
    assert si["period"] == "01-Apr-2025 to 31-Mar-2026"


# ── Table classifier ──────────────────────────────────────────────────
def test_classify_cdsl_equity_table():
    table = [
        ["ISIN", "Security", "Current Bal", "Frozen", "Pledge", "Free Bal", "Price", "Value"],
        ["INE040A01034", "HDFC BANK LIMITED\nEQUITY SHARES OF RS.1 EACH", "90", "0", "0", "90", "887.40", "79866.00"],
    ]
    assert _classify_table(table) == "cdsl_equity"


def test_classify_cdsl_mf_folio_table():
    table = [
        ["ISIN", "Scheme Name", "Folio No", "Units", "NAV", "Invested", "Valuation", "PnL", "PnL%"],
        ["INF179K01CR2", "HDFC Mid Cap Fund - Growth", "12345678", "1995.624", "202.575", "300000.00", "404263.53", "104263.53", "34.75"],
    ]
    assert _classify_table(table) == "cdsl_mf_folio"


def test_classify_does_not_misroute_nsdl_equity():
    """NSDL equity table — Company Name + Face Value header, 6 cols. Must
    stay classified as 'equity' (not 'cdsl_equity')."""
    table = [
        ["ISIN/Symbol", "Company Name", "Face Value", "Shares", "Market Price", "Value"],
        ["INE009A01021\nINFY.NSE", "INFOSYS LIMITED", "5", "35", "1299.95", "45498.25"],
    ]
    assert _classify_table(table) == "equity"


# ── CDSL row extractors ───────────────────────────────────────────────
def test_cdsl_equity_row_basic():
    row = [
        "INE040A01034",
        "HDFC BANK LIMITED\nEQUITY SHARES OF RS.1 EACH",
        "90",  # current qty
        "0", "0", "0", "90",  # frozen / pledge / setup / free
        "887.40",  # price
        "79866.00",  # value
    ]
    rec = _cdsl_equity_row_to_record(row)
    assert rec is not None
    assert rec["isin"] == "INE040A01034"
    assert rec["company_name"] == "HDFC BANK LIMITED"
    assert rec["num_shares"] == 90
    assert abs(rec["market_price_inr"] - 887.40) < 1e-6
    assert abs(rec["value_inr"] - 79866.00) < 1e-6


def test_cdsl_equity_row_minimal_two_numbers():
    """Doc AI sometimes loses the qty cell; fall back to value/price."""
    row = ["INE002A01018", "RELIANCE INDUSTRIES LIMITED", "1394.30", "41829.00"]
    rec = _cdsl_equity_row_to_record(row)
    assert rec is not None
    assert rec["isin"] == "INE002A01018"
    assert rec["num_shares"] == 30  # round(41829 / 1394.30)


def test_cdsl_equity_row_skips_no_isin():
    assert _cdsl_equity_row_to_record(["", "PLACEHOLDER", "100", "10"]) is None


def test_cdsl_mf_folio_row_basic():
    row = [
        "INF179K01CR2",
        "HDFC Mid Cap Fund - Growth",
        "12345678",  # folio
        "1995.624",  # units
        "202.575",  # nav
        "300000.00",  # invested
        "404263.53",  # valuation
        "104263.53",  # pnl
        "34.75",  # pnl%
    ]
    rec = _cdsl_mf_folio_row_to_record(row)
    assert rec is not None
    assert rec["isin"] == "INF179K01CR2"
    assert rec["fund_name"].startswith("HDFC Mid Cap Fund")
    assert rec["folio_number"] == "12345678"
    assert abs(rec["num_units"] - 1995.624) < 1e-3
    assert abs(rec["current_nav_inr"] - 202.575) < 1e-3
    assert abs(rec["current_value_inr"] - 404263.53) < 1e-2
    assert abs(rec["total_cost_inr"] - 300000.00) < 1e-2
    # avg_cost_per_unit ≈ 300000 / 1995.624 ≈ 150.33
    assert abs(rec["avg_cost_per_unit_inr"] - (300000.00 / 1995.624)) < 1e-2


def test_cdsl_mf_folio_row_two_numbers_only():
    row = ["INF879001019", "Parag Parikh Flexi Cap Fund", "84.0452", "63130.13"]
    rec = _cdsl_mf_folio_row_to_record(row)
    assert rec is not None
    # units = 63130.13 / 84.0452 ≈ 751.149
    assert abs(rec["num_units"] - 751.149) < 0.1
    assert abs(rec["current_nav_inr"] - 84.0452) < 1e-4
    assert abs(rec["current_value_inr"] - 63130.13) < 1e-2


# ── End-to-end normalize() with synthesised CDSL Doc AI input ─────────
def _cdsl_docai_fixture():
    """Mimics what Document AI returns for a CDSL-only CAS PDF: a text
    blob with cover-page metadata + two tables (equities, MF folios).
    """
    text = (
        "Central Depository Services (India) Limited\n"
        "Consolidated Account Statement\n"
        "BO ID: 1234 5678 9012 3456\n"
        "BO Name: VARUN AGARWAL\n"
        "PAN: ABCDE1234F\n"
        "Period: 01-02-2026 to 28-02-2026\n"
        "Address: 12, MG Road, Mumbai 400001\n"
    )
    tables = [
        # Equities
        [
            ["ISIN", "Security", "Current Bal", "Frozen", "Pledge", "Free Bal", "Price", "Value"],
            ["INE040A01034", "HDFC BANK LIMITED\nEQUITY SHARES OF RS.1 EACH",
             "90", "0", "0", "90", "887.40", "79866.00"],
            ["INE002A01018", "RELIANCE INDUSTRIES LIMITED\nEQUITY SHARES OF RS.10 EACH",
             "30", "0", "0", "30", "1394.30", "41829.00"],
            # ETF row inside the same table — has INF ISIN. Should be
            # routed to mutual_funds_demat.
            ["INF204KB1715", "NIPPON INDIA ETF GOLD BeES",
             "100", "0", "0", "100", "131.64", "13164.00"],
        ],
        # MF folios
        [
            ["ISIN", "Scheme Name", "Folio No", "Units", "NAV", "Invested", "Valuation", "PnL", "PnL%"],
            ["INF179K01CR2", "HDFC Mid Cap Fund - Growth", "12345678",
             "1995.624", "202.575", "300000.00", "404263.53", "104263.53", "34.75"],
            ["INF879001019", "Parag Parikh Flexi Cap Fund", "87654321",
             "751.145", "84.0452", "60000.00", "63130.13", "3130.13", "5.22"],
        ],
    ]
    return {"text": text, "tables": tables}


def test_normalize_end_to_end_cdsl():
    out = normalize(_cdsl_docai_fixture())

    # Statement / investor metadata
    assert out["statement_info"]["depository"] == "CDSL"
    assert out["statement_info"]["id"] == "1234567890123456"
    assert out["statement_info"]["period"] == "01-02-2026 to 28-02-2026"
    assert out["investor_info"]["name"] == "VARUN AGARWAL"
    assert out["investor_info"]["pan"] == "ABCDE1234F"

    # Holdings buckets
    eq = out["holdings"]["equities"]
    assert len(eq) == 2
    isins_eq = {h["isin"] for h in eq}
    assert isins_eq == {"INE040A01034", "INE002A01018"}

    mfd = out["holdings"]["mutual_funds_demat"]
    assert len(mfd) == 1
    assert mfd[0]["isin"] == "INF204KB1715"

    folios = out["holdings"]["mutual_fund_folios"]
    assert len(folios) == 2
    isins_f = {h["isin"] for h in folios}
    assert isins_f == {"INF179K01CR2", "INF879001019"}


def test_normalize_cdsl_holdings_pass_mapper():
    """The downstream `claude_cas_mapper.map_to_internal()` is depository-
    agnostic — verifies CDSL holdings flow through the same pipeline as
    NSDL without changes.
    """
    from services import claude_cas_mapper as mapper

    out = normalize(_cdsl_docai_fixture())
    result = mapper.map_to_internal(out)
    holdings = result[0] if isinstance(result, tuple) else (
        result.get("holdings") if isinstance(result, dict) else result
    )
    assert isinstance(holdings, list)
    # 2 equities + 1 ETF (in mf_demat bucket) + 2 folios = 5 internal rows
    assert len(holdings) == 5
    isins = {h.get("ticker") for h in holdings}
    assert {"INE040A01034", "INE002A01018", "INF204KB1715",
            "INF179K01CR2", "INF879001019"}.issubset(isins)
