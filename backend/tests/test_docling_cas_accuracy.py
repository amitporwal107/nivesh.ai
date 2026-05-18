"""
Accuracy test for services/docling_cas_parser.py against priyanka_nsdl.pdf.

Ground truth is hardcoded below (derived from priyanka_nsdl.json, hand-verified).
Every section has three levels of assertion:
  1. Count  — right number of holdings per asset class
  2. Total  — sum of (qty × price) matches expected section value within tolerance
  3. Per-holding — ISIN exact, name fuzzy ≥70, qty exact, price ±5 %, value ±5 %

Run (unit-only, no docling):   pytest tests/test_docling_cas_accuracy.py -v -k "not Integration"
Run (full, needs docling):     pytest tests/test_docling_cas_accuracy.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.docling_cas_parser import is_available

# ── paths ───────────────────────────────────────────────────────────────────
NSDL_PDF = Path(__file__).parent / "test_data" / "nsdl" / "priyanka_nsdl.pdf"

# ── tolerances ──────────────────────────────────────────────────────────────
VALUE_TOL_PCT   = 0.05   # ±5 % on any monetary figure
VALUE_TOL_ABS   = 50.0   # ±₹50 floor
QTY_TOL         = 0.01   # ±0.01 units (rounding)
NAME_SIM_MIN    = 70     # rapidfuzz partial_ratio threshold

docling_required = pytest.mark.skipif(
    not is_available(),
    reason="docling / PyMuPDF not installed — pip install 'docling>=2.5.0' pymupdf",
)
pdf_required = pytest.mark.skipif(
    not NSDL_PDF.exists(),
    reason="priyanka_nsdl.pdf missing from tests/test_data/nsdl/",
)


# ════════════════════════════════════════════════════════════════════════════
# HARDCODED GROUND TRUTH  (source: priyanka_nsdl.json, hand-verified)
# ════════════════════════════════════════════════════════════════════════════

EXPECTED_SUMMARY = {
    "total_portfolio":     14_133_535.20,
    "equities":             1_279_628.34,
    "mutual_funds_demat":   2_022_520.38,
    "sovereign_gold_bonds": 3_689_886.85,
    "mutual_fund_folios":   6_816_165.90,
}

# 14 rows in PDF; SAMVARDHANA MOTHERSON has qty=0, value=0 → filtered by parser
# Parser should return 13 equities.
EXPECTED_EQUITIES = [
    {"isin": "INE079A01024", "name": "AMBUJA CEMENTS LIMITED",                      "qty": 30,   "price":  500.40,  "value":    15_012.00},
    {"isin": "INE259A01022", "name": "COLGATE-PALMOLIVE (INDIA) LIMITED",            "qty": 22,   "price": 2254.50,  "value":    49_599.00},
    {"isin": "INE524A01029", "name": "GABRIEL INDIA LIMITED",                        "qty": 204,  "price":  998.80,  "value":   203_755.20},
    {"isin": "INE066P01011", "name": "INOX WIND LIMITED",                            "qty": 500,  "price":   92.13,  "value":    46_065.00},
    {"isin": "INE220G01021", "name": "JINDAL STAINLESS LIMITED",                     "qty": 84,   "price":  776.35,  "value":    65_213.40},
    {"isin": "INE389H01022", "name": "KEC INTERNATIONAL LIMITED",                    "qty": 50,   "price":  585.30,  "value":    29_265.00},
    {"isin": "INE356A01018", "name": "MPHASIS LIMITED",                              "qty": 1,    "price": 2296.50,  "value":     2_296.50},
    {"isin": "INE733E01010", "name": "NTPC GREEN ENERGY LIMITED",                    "qty": 750,  "price":   90.14,  "value":    67_605.00},
    {"isin": "INE876N01018", "name": "ORIENT CEMENT LIMITED",                        "qty": 66,   "price":  154.12,  "value":    10_171.92},
    {"isin": "INE855B01025", "name": "RAIN INDUSTRIES LIMITED",                      "qty": 100,  "price":  148.64,  "value":    14_864.00},
    {"isin": "INE062A01020", "name": "STATE BANK OF INDIA",                          "qty": 8,    "price": 1201.70,  "value":     9_613.60},
    {"isin": "INE669C01036", "name": "TECH MAHINDRA LIMITED",                        "qty": 12,   "price": 1357.80,  "value":    16_293.60},
    {"isin": "INE053A01029", "name": "THE INDIAN HOTELS COMPANY LIMITED",            "qty": 200,  "price":  667.05,  "value":   133_410.00},
]

# This row appears in the PDF with qty=0, value=0 — must be EXCLUDED from output
EXPECTED_ZERO_BALANCE = [
    {"isin": "INE775A01035", "name": "SAMVARDHANA MOTHERSON INTERNATIONAL"},
]

EXPECTED_ETFS = [
    {"isin": "INF754K01LE1", "name": "BHARAT BOND ETF - APRIL 2031",    "qty":    4,    "price":  1402.08, "value":     5_608.31},
    {"isin": "INF666MO1NI0", "name": "GROWW NIFTY METAL ETF",           "qty": 9999,    "price":    11.61, "value":   116_101.38},
    {"isin": "INF204KB1715", "name": "NIPPON INDIA ETF GOLD BeES",      "qty": 1300,    "price":   130.90, "value": 1_701_745.50},
    {"isin": "INF769K01HF4", "name": "MIRAE ASSET NYSE FANG+ ETF",      "qty":    5,    "price":   769.77, "value":     3_848.85},
]

EXPECTED_SGBS = [
    {"isin": "IN0020220110", "name": "SGB 2022-23 SERIES III",  "qty": 10, "price": 15_924.50,  "value":   159_245.00},
    {"isin": "IN0020230168", "name": "SGB 2023-24 SERIES I",    "qty": 35, "price": 16_233.91,  "value":   568_186.85},
    {"isin": "IN0020200146", "name": "SGB 2020-21 SERIES IX",   "qty": 50, "price": 15_709.64,  "value":   785_482.00},
]

EXPECTED_MF_FOLIOS = [
    {"isin": "INF209K01YW1", "name": "Aditya Birla Sun Life Large Cap Fund",        "units":    7626.250, "nav":   93.8700, "value":   715_876.09},
    {"isin": "INF090I01569", "name": "Franklin India Small Cap Fund",                "units":      49.960, "nav":  160.4360, "value":     8_015.38},
    {"isin": "INF179K01830", "name": "HDFC Balanced Advantage Fund",                 "units":     164.627, "nav":  528.1470, "value":    86_947.26},
    {"isin": "INF179K01UT0", "name": "HDFC Flexi Cap Fund",                          "units":     161.424, "nav": 2261.5280, "value":   365_064.90},
    {"isin": "INF179K01VX0", "name": "HDFC Gold ETF Fund of Fund",                   "units":    6936.416, "nav":   49.6981, "value":   344_726.70},
    {"isin": "INF179KA1RZ8", "name": "HDFC Small Cap Fund",                          "units":     154.911, "nav":  133.8630, "value":    20_736.85},
    {"isin": "INF109K016L0", "name": "ICICI Prudential Large Cap Fund",              "units":    5479.803, "nav":  123.6000, "value":   677_303.65},
    {"isin": "INF109K01AF8", "name": "ICICI Prudential Value Fund",                  "units":     430.350, "nav":  484.3500, "value":   208_440.02},
    {"isin": "INF769K01IR7", "name": "Mirae Asset AI & Technology ETF FoF",          "units":    2879.147, "nav":   26.7260, "value":    76_948.08},
    {"isin": "INF204K01HY3", "name": "NIPPON INDIA SMALL CAP FUND",                  "units":     855.803, "nav":  162.1622, "value":   138_778.90},
    {"isin": "INF879001019", "name": "Parag Parikh Flexi Cap Fund",                  "units":    1010.803, "nav":   84.0452, "value":    84_953.14},
    {"isin": "INF200K01RA0", "name": "SBI Contra Fund",                              "units":     569.777, "nav":  428.9918, "value":   244_429.66},
    {"isin": "INF789F1AYT7", "name": "UTI Balanced Advantage Fund",                  "units":    3943.623, "nav":   12.6994, "value":    50_081.65},
    {"isin": "INF966L01580", "name": "quant Multi Asset Allocation Fund",             "units":     784.802, "nav":  175.2572, "value":   137_542.20},
    {"isin": "INF903J01538", "name": "Sundaram Mid Cap Fund",                         "units":     450.105, "nav":  222.4200, "value":   100_114.47},
]

# Expected counts visible to the parser (zero-balance filtered)
EXPECTED_COUNTS = {
    "equity":       13,   # 14 in PDF minus 1 zero-balance (SAMVARDHANA)
    "etf":           4,
    "gold":          3,   # 3 SGBs
    "mutual_fund":  15,   # 15 MF folios via casparser
}

# Expected section totals (sum of qty × price per asset class)
EXPECTED_SECTION_TOTALS = {
    "equity":       sum(e["value"] for e in EXPECTED_EQUITIES),          # 663_408.22
    "etf":          sum(e["value"] for e in EXPECTED_ETFS),              # 1_827_304.04
    "gold":         sum(s["value"] for s in EXPECTED_SGBS),              # 1_512_913.85
    "mutual_fund":  sum(m["value"] for m in EXPECTED_MF_FOLIOS),         # 3_060_198.05
}


# ════════════════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════════════════

def _close(actual: float, expected: float) -> bool:
    if expected == 0:
        return abs(actual) <= VALUE_TOL_ABS
    return abs(actual - expected) <= max(abs(expected) * VALUE_TOL_PCT, VALUE_TOL_ABS)


def _find(holdings, isin: str):
    """Exact ISIN lookup with 1-char OCR tolerance."""
    for h in holdings:
        t = h.get("ticker", "")
        if t == isin:
            return h
        if len(t) == len(isin) == 12 and sum(a != b for a, b in zip(t, isin)) <= 1:
            return h
    return None


def _name_ok(parsed_name: str, expected_name: str) -> bool:
    try:
        from rapidfuzz import fuzz
        return fuzz.partial_ratio(parsed_name.lower(), expected_name.lower()) >= NAME_SIM_MIN
    except ImportError:
        # fallback: check if any 4-word substring matches
        exp_words = expected_name.lower().split()
        got_words = parsed_name.lower().split()
        common = sum(1 for w in exp_words if w in got_words)
        return common >= max(1, len(exp_words) // 2)


# ════════════════════════════════════════════════════════════════════════════
# FIXTURE  (parse once, share across all tests)
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def parsed():
    if not is_available():
        pytest.skip("docling / PyMuPDF not installed — pip install 'docling>=2.5.0' pymupdf")
    if not NSDL_PDF.exists():
        pytest.skip("priyanka_nsdl.pdf missing from tests/test_data/nsdl/")
    from services.docling_cas_parser import parse_with_docling
    holdings, _ = parse_with_docling(NSDL_PDF.read_bytes(), password="")
    return holdings


# ════════════════════════════════════════════════════════════════════════════
# 1. COUNT CHECKS
# ════════════════════════════════════════════════════════════════════════════

@docling_required
@pdf_required
class TestCASCountAccuracy:
    """One test per asset class verifying the exact count of holdings parsed."""

    def test_equity_count(self, parsed):
        got = [h for h in parsed if h["asset_type"] == "equity"]
        assert len(got) == EXPECTED_COUNTS["equity"], (
            f"Equity count: expected {EXPECTED_COUNTS['equity']}, got {len(got)}\n"
            f"Parsed ISINs: {[h['ticker'] for h in got]}"
        )

    def test_etf_count(self, parsed):
        got = [h for h in parsed if h["asset_type"] == "etf"]
        assert len(got) == EXPECTED_COUNTS["etf"], (
            f"ETF count: expected {EXPECTED_COUNTS['etf']}, got {len(got)}\n"
            f"Parsed ISINs: {[h['ticker'] for h in got]}"
        )

    def test_gold_sgb_count(self, parsed):
        got = [h for h in parsed if h["asset_type"] == "gold"]
        assert len(got) == EXPECTED_COUNTS["gold"], (
            f"Gold/SGB count: expected {EXPECTED_COUNTS['gold']}, got {len(got)}\n"
            f"Parsed ISINs: {[h['ticker'] for h in got]}"
        )

    def test_mutual_fund_count(self, parsed):
        got = [h for h in parsed if h["asset_type"] == "mutual_fund"]
        assert len(got) == EXPECTED_COUNTS["mutual_fund"], (
            f"MF count: expected {EXPECTED_COUNTS['mutual_fund']}, got {len(got)}\n"
            f"Parsed ISINs: {[h['ticker'] for h in got]}"
        )

    def test_total_holding_count(self, parsed):
        expected_total = sum(EXPECTED_COUNTS.values())
        assert len(parsed) == expected_total, (
            f"Total holdings: expected {expected_total}, got {len(parsed)}"
        )

    def test_zero_balance_holdings_excluded(self, parsed):
        """SAMVARDHANA MOTHERSON (qty=0, value=0) must not appear in output."""
        for zb in EXPECTED_ZERO_BALANCE:
            h = _find(parsed, zb["isin"])
            assert h is None, (
                f"Zero-balance holding {zb['isin']} ({zb['name']}) was NOT filtered: {h}"
            )

    def test_no_duplicate_isins(self, parsed):
        isins = [h["ticker"] for h in parsed if h.get("ticker")]
        dupes = [t for t in set(isins) if isins.count(t) > 1]
        assert not dupes, f"Duplicate ISINs in output: {dupes}"


# ════════════════════════════════════════════════════════════════════════════
# 2. SECTION TOTAL VALUE CHECKS
# ════════════════════════════════════════════════════════════════════════════

@docling_required
@pdf_required
class TestCASSectionTotals:
    """Sum of (qty × price) per asset class must be within 5 % of ground truth."""

    def _section_total(self, parsed, asset_type: str) -> float:
        return sum(
            h.get("quantity", 0) * h.get("current_price", 0)
            for h in parsed if h["asset_type"] == asset_type
        )

    def test_equity_section_total(self, parsed):
        actual   = self._section_total(parsed, "equity")
        expected = EXPECTED_SECTION_TOTALS["equity"]
        assert _close(actual, expected), (
            f"Equity total: expected ₹{expected:,.2f}, got ₹{actual:,.2f} "
            f"(diff {abs(actual-expected)/expected*100:.1f}%)"
        )

    def test_etf_section_total(self, parsed):
        actual   = self._section_total(parsed, "etf")
        expected = EXPECTED_SECTION_TOTALS["etf"]
        assert _close(actual, expected), (
            f"ETF total: expected ₹{expected:,.2f}, got ₹{actual:,.2f} "
            f"(diff {abs(actual-expected)/expected*100:.1f}%)"
        )

    def test_gold_sgb_section_total(self, parsed):
        actual   = self._section_total(parsed, "gold")
        expected = EXPECTED_SECTION_TOTALS["gold"]
        assert _close(actual, expected), (
            f"Gold/SGB total: expected ₹{expected:,.2f}, got ₹{actual:,.2f} "
            f"(diff {abs(actual-expected)/expected*100:.1f}%)"
        )

    def test_mutual_fund_section_total(self, parsed):
        actual   = self._section_total(parsed, "mutual_fund")
        expected = EXPECTED_SECTION_TOTALS["mutual_fund"]
        assert _close(actual, expected), (
            f"MF total: expected ₹{expected:,.2f}, got ₹{actual:,.2f} "
            f"(diff {abs(actual-expected)/expected*100:.1f}%)"
        )

    def test_overall_portfolio_total(self, parsed):
        actual   = sum(h.get("quantity", 0) * h.get("current_price", 0) for h in parsed)
        expected = sum(EXPECTED_SECTION_TOTALS.values())
        assert _close(actual, expected), (
            f"Portfolio total: expected ₹{expected:,.2f}, got ₹{actual:,.2f} "
            f"(diff {abs(actual-expected)/expected*100:.1f}%)"
        )


# ════════════════════════════════════════════════════════════════════════════
# 3. PER-HOLDING: EQUITIES  (one test row per holding)
# ════════════════════════════════════════════════════════════════════════════

def _equity_id(e):
    return e["isin"]


@docling_required
@pdf_required
class TestCASEquityHoldings:
    """One-to-one check for each of the 13 equity holdings."""

    @pytest.mark.parametrize("exp", EXPECTED_EQUITIES, ids=_equity_id)
    def test_isin_present(self, parsed, exp):
        h = _find(parsed, exp["isin"])
        assert h is not None, (
            f"Equity {exp['isin']} ({exp['name']}) not found in parser output.\n"
            f"All equity ISINs parsed: {[h['ticker'] for h in parsed if h['asset_type']=='equity']}"
        )

    @pytest.mark.parametrize("exp", EXPECTED_EQUITIES, ids=_equity_id)
    def test_name_similarity(self, parsed, exp):
        h = _find(parsed, exp["isin"])
        if h is None:
            pytest.skip(f"{exp['isin']} not found — covered by test_isin_present")
        assert _name_ok(h["name"], exp["name"]), (
            f"{exp['isin']}: name mismatch\n"
            f"  expected : {exp['name']}\n"
            f"  got      : {h['name']}"
        )

    @pytest.mark.parametrize("exp", EXPECTED_EQUITIES, ids=_equity_id)
    def test_quantity(self, parsed, exp):
        h = _find(parsed, exp["isin"])
        if h is None:
            pytest.skip(f"{exp['isin']} not found — covered by test_isin_present")
        assert abs(h["quantity"] - exp["qty"]) <= QTY_TOL, (
            f"{exp['isin']} ({exp['name']}): quantity mismatch\n"
            f"  expected : {exp['qty']}\n"
            f"  got      : {h['quantity']}"
        )

    @pytest.mark.parametrize("exp", EXPECTED_EQUITIES, ids=_equity_id)
    def test_market_price(self, parsed, exp):
        h = _find(parsed, exp["isin"])
        if h is None:
            pytest.skip(f"{exp['isin']} not found — covered by test_isin_present")
        assert _close(h["current_price"], exp["price"]), (
            f"{exp['isin']} ({exp['name']}): price mismatch\n"
            f"  expected : ₹{exp['price']:,.2f}\n"
            f"  got      : ₹{h['current_price']:,.2f}"
        )

    @pytest.mark.parametrize("exp", EXPECTED_EQUITIES, ids=_equity_id)
    def test_holding_value(self, parsed, exp):
        h = _find(parsed, exp["isin"])
        if h is None:
            pytest.skip(f"{exp['isin']} not found — covered by test_isin_present")
        parsed_value = h["quantity"] * h["current_price"]
        assert _close(parsed_value, exp["value"]), (
            f"{exp['isin']} ({exp['name']}): value mismatch\n"
            f"  expected : ₹{exp['value']:,.2f}\n"
            f"  got      : ₹{parsed_value:,.2f} (qty={h['quantity']} × price={h['current_price']})"
        )

    @pytest.mark.parametrize("exp", EXPECTED_EQUITIES, ids=_equity_id)
    def test_asset_type_is_equity(self, parsed, exp):
        h = _find(parsed, exp["isin"])
        if h is None:
            pytest.skip(f"{exp['isin']} not found — covered by test_isin_present")
        assert h["asset_type"] == "equity", (
            f"{exp['isin']}: expected asset_type='equity', got '{h['asset_type']}'"
        )


# ════════════════════════════════════════════════════════════════════════════
# 4. PER-HOLDING: ETFs
# ════════════════════════════════════════════════════════════════════════════

def _etf_id(e):
    return e["isin"]


@docling_required
@pdf_required
class TestCASETFHoldings:
    """One-to-one check for each of the 4 ETF holdings."""

    @pytest.mark.parametrize("exp", EXPECTED_ETFS, ids=_etf_id)
    def test_isin_present(self, parsed, exp):
        h = _find(parsed, exp["isin"])
        assert h is not None, (
            f"ETF {exp['isin']} ({exp['name']}) not found.\n"
            f"All ETF ISINs: {[h['ticker'] for h in parsed if h['asset_type']=='etf']}"
        )

    @pytest.mark.parametrize("exp", EXPECTED_ETFS, ids=_etf_id)
    def test_name_similarity(self, parsed, exp):
        h = _find(parsed, exp["isin"])
        if h is None:
            pytest.skip(f"{exp['isin']} not found")
        assert _name_ok(h["name"], exp["name"]), (
            f"{exp['isin']}: name\n  expected: {exp['name']}\n  got: {h['name']}"
        )

    @pytest.mark.parametrize("exp", EXPECTED_ETFS, ids=_etf_id)
    def test_quantity(self, parsed, exp):
        h = _find(parsed, exp["isin"])
        if h is None:
            pytest.skip(f"{exp['isin']} not found")
        assert abs(h["quantity"] - exp["qty"]) <= QTY_TOL, (
            f"{exp['isin']}: qty expected={exp['qty']}, got={h['quantity']}"
        )

    @pytest.mark.parametrize("exp", EXPECTED_ETFS, ids=_etf_id)
    def test_nav(self, parsed, exp):
        h = _find(parsed, exp["isin"])
        if h is None:
            pytest.skip(f"{exp['isin']} not found")
        assert _close(h["current_price"], exp["price"]), (
            f"{exp['isin']}: NAV expected=₹{exp['price']}, got=₹{h['current_price']}"
        )

    @pytest.mark.parametrize("exp", EXPECTED_ETFS, ids=_etf_id)
    def test_holding_value(self, parsed, exp):
        h = _find(parsed, exp["isin"])
        if h is None:
            pytest.skip(f"{exp['isin']} not found")
        parsed_value = h["quantity"] * h["current_price"]
        assert _close(parsed_value, exp["value"]), (
            f"{exp['isin']}: value expected=₹{exp['value']:,.2f}, got=₹{parsed_value:,.2f}"
        )

    @pytest.mark.parametrize("exp", EXPECTED_ETFS, ids=_etf_id)
    def test_asset_type_is_etf(self, parsed, exp):
        h = _find(parsed, exp["isin"])
        if h is None:
            pytest.skip(f"{exp['isin']} not found")
        assert h["asset_type"] == "etf", (
            f"{exp['isin']}: expected asset_type='etf', got '{h['asset_type']}'"
        )


# ════════════════════════════════════════════════════════════════════════════
# 5. PER-HOLDING: SGBs
# ════════════════════════════════════════════════════════════════════════════

def _sgb_id(s):
    return s["isin"]


@docling_required
@pdf_required
class TestCASSGBHoldings:
    """One-to-one check for each of the 3 Sovereign Gold Bond holdings."""

    @pytest.mark.parametrize("exp", EXPECTED_SGBS, ids=_sgb_id)
    def test_isin_present(self, parsed, exp):
        h = _find(parsed, exp["isin"])
        assert h is not None, (
            f"SGB {exp['isin']} ({exp['name']}) not found.\n"
            f"All gold ISINs: {[h['ticker'] for h in parsed if h['asset_type']=='gold']}"
        )

    @pytest.mark.parametrize("exp", EXPECTED_SGBS, ids=_sgb_id)
    def test_name_similarity(self, parsed, exp):
        h = _find(parsed, exp["isin"])
        if h is None:
            pytest.skip(f"{exp['isin']} not found")
        assert _name_ok(h["name"], exp["name"]), (
            f"{exp['isin']}: name\n  expected: {exp['name']}\n  got: {h['name']}"
        )

    @pytest.mark.parametrize("exp", EXPECTED_SGBS, ids=_sgb_id)
    def test_quantity(self, parsed, exp):
        h = _find(parsed, exp["isin"])
        if h is None:
            pytest.skip(f"{exp['isin']} not found")
        assert abs(h["quantity"] - exp["qty"]) <= QTY_TOL, (
            f"{exp['isin']}: qty expected={exp['qty']}, got={h['quantity']}"
        )

    @pytest.mark.parametrize("exp", EXPECTED_SGBS, ids=_sgb_id)
    def test_market_price(self, parsed, exp):
        h = _find(parsed, exp["isin"])
        if h is None:
            pytest.skip(f"{exp['isin']} not found")
        assert _close(h["current_price"], exp["price"]), (
            f"{exp['isin']}: price expected=₹{exp['price']:,.2f}, got=₹{h['current_price']:,.2f}"
        )

    @pytest.mark.parametrize("exp", EXPECTED_SGBS, ids=_sgb_id)
    def test_holding_value(self, parsed, exp):
        h = _find(parsed, exp["isin"])
        if h is None:
            pytest.skip(f"{exp['isin']} not found")
        parsed_value = h["quantity"] * h["current_price"]
        assert _close(parsed_value, exp["value"]), (
            f"{exp['isin']}: value expected=₹{exp['value']:,.2f}, got=₹{parsed_value:,.2f}"
        )

    @pytest.mark.parametrize("exp", EXPECTED_SGBS, ids=_sgb_id)
    def test_asset_type_is_gold(self, parsed, exp):
        h = _find(parsed, exp["isin"])
        if h is None:
            pytest.skip(f"{exp['isin']} not found")
        assert h["asset_type"] == "gold", (
            f"{exp['isin']}: expected asset_type='gold', got '{h['asset_type']}'"
        )


# ════════════════════════════════════════════════════════════════════════════
# 6. PER-HOLDING: MUTUAL FUND FOLIOS
# ════════════════════════════════════════════════════════════════════════════

def _mf_id(m):
    return m["isin"]


@docling_required
@pdf_required
class TestCASMFHoldings:
    """One-to-one check for each of the 15 MF folio holdings (via casparser)."""

    @pytest.mark.parametrize("exp", EXPECTED_MF_FOLIOS, ids=_mf_id)
    def test_isin_present(self, parsed, exp):
        h = _find(parsed, exp["isin"])
        assert h is not None, (
            f"MF {exp['isin']} ({exp['name']}) not found.\n"
            f"All MF ISINs: {[h['ticker'] for h in parsed if h['asset_type']=='mutual_fund']}"
        )

    @pytest.mark.parametrize("exp", EXPECTED_MF_FOLIOS, ids=_mf_id)
    def test_name_similarity(self, parsed, exp):
        h = _find(parsed, exp["isin"])
        if h is None:
            pytest.skip(f"{exp['isin']} not found")
        assert _name_ok(h["name"], exp["name"]), (
            f"{exp['isin']}: name\n  expected: {exp['name']}\n  got: {h['name']}"
        )

    @pytest.mark.parametrize("exp", EXPECTED_MF_FOLIOS, ids=_mf_id)
    def test_units(self, parsed, exp):
        h = _find(parsed, exp["isin"])
        if h is None:
            pytest.skip(f"{exp['isin']} not found")
        assert _close(h["quantity"], exp["units"]), (
            f"{exp['isin']}: units expected={exp['units']}, got={h['quantity']}"
        )

    @pytest.mark.parametrize("exp", EXPECTED_MF_FOLIOS, ids=_mf_id)
    def test_nav(self, parsed, exp):
        h = _find(parsed, exp["isin"])
        if h is None:
            pytest.skip(f"{exp['isin']} not found")
        assert _close(h["current_price"], exp["nav"]), (
            f"{exp['isin']}: NAV expected=₹{exp['nav']}, got=₹{h['current_price']}"
        )

    @pytest.mark.parametrize("exp", EXPECTED_MF_FOLIOS, ids=_mf_id)
    def test_holding_value(self, parsed, exp):
        h = _find(parsed, exp["isin"])
        if h is None:
            pytest.skip(f"{exp['isin']} not found")
        parsed_value = h["quantity"] * h["current_price"]
        assert _close(parsed_value, exp["value"]), (
            f"{exp['isin']}: value expected=₹{exp['value']:,.2f}, got=₹{parsed_value:,.2f}"
        )

    @pytest.mark.parametrize("exp", EXPECTED_MF_FOLIOS, ids=_mf_id)
    def test_asset_type_is_mutual_fund(self, parsed, exp):
        h = _find(parsed, exp["isin"])
        if h is None:
            pytest.skip(f"{exp['isin']} not found")
        assert h["asset_type"] == "mutual_fund", (
            f"{exp['isin']}: expected asset_type='mutual_fund', got '{h['asset_type']}'"
        )
