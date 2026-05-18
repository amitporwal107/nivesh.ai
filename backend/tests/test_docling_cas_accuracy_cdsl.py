"""
Accuracy test for services/docling_cas_parser.py against varun_cdsl.pdf (CDSL CAS).

Ground truth is hardcoded below (derived from varun_cdsl.json, hand-verified).
Mirrors the structure of test_docling_cas_accuracy.py (NSDL) so the two
suites stay symmetrical and easy to maintain.

Three levels of assertion per asset class:
  1. Count  — right number of holdings
  2. Total  — sum of (qty × price) matches expected within tolerance
  3. Per-holding — ISIN exact, name fuzzy ≥70, qty exact, price ±5%, value ±5%

CDSL-specific shape:
  • No SGB section (gold count must be 0)
  • HDFC BANK appears twice with two different ISINs (two demats) — both must parse
  • METROPOLITAN STOCK EXCHANGE quoted at ₹1.00 — covered by ±₹50 absolute floor

Run (unit-only, no docling):   pytest tests/test_docling_cas_accuracy_cdsl.py -v -k "not Integration"
Run (full, needs docling):     pytest tests/test_docling_cas_accuracy_cdsl.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.docling_cas_parser import is_available

# ── paths ───────────────────────────────────────────────────────────────────
CDSL_PDF = Path(__file__).parent / "test_data" / "cdsl" / "varun_cdsl.pdf"

# ── tolerances (same as NSDL test) ──────────────────────────────────────────
VALUE_TOL_PCT   = 0.05   # ±5 % on any monetary figure
VALUE_TOL_ABS   = 50.0   # ±₹50 floor
QTY_TOL         = 0.01   # ±0.01 units (rounding)
NAME_SIM_MIN    = 70     # rapidfuzz partial_ratio threshold

docling_required = pytest.mark.skipif(
    not is_available(),
    reason="docling / PyMuPDF not installed — pip install 'docling>=2.5.0' pymupdf",
)
pdf_required = pytest.mark.skipif(
    not CDSL_PDF.exists(),
    reason="varun_cdsl.pdf missing from tests/test_data/cdsl/",
)


# ════════════════════════════════════════════════════════════════════════════
# HARDCODED GROUND TRUTH  (source: varun_cdsl.json, hand-verified)
# ════════════════════════════════════════════════════════════════════════════

EXPECTED_SUMMARY = {
    "investor":             "VARUN AGARWAL",
    "source":               "CDSL",
    "total_portfolio":      2_844_998.46,    # from JSON (informational; tests use per-row sums)
    "cdsl_demat":           1_459_999.04,    # from JSON (informational)
    "mutual_fund_folios":   1_384_999.42,
}

# 33 CDSL equities — all non-zero balance.
# Two HDFC BANK entries (INE102D01028, INE040A01034) — different demats, both must appear.
EXPECTED_EQUITIES = [
    {"isin": "INE14LE01019", "name": "ADITYA BIRLA LIFESTYLE BRANDS LIMITED",   "qty":   173, "price":  102.10, "value":    17_663.30},
    {"isin": "INE901L01018", "name": "ALEMBIC PHARMACEUTICALS LIMITED",         "qty":    27, "price":  711.55, "value":    19_211.85},
    {"isin": "INE397D01024", "name": "BHARTI AIRTEL LIMITED",                   "qty":    20, "price": 1879.75, "value":    37_595.00},
    {"isin": "INE836A01035", "name": "BIRLASOFT LIMITED",                       "qty":   150, "price":  390.10, "value":    58_515.00},
    {"isin": "INE491A01021", "name": "CITY UNION BANK LIMITED",                 "qty":   158, "price":  283.30, "value":    44_761.40},
    {"isin": "INE299U01018", "name": "CROMPTON GREAVES CONSUMER ELECTRICALS",   "qty":    83, "price":  257.55, "value":    21_376.65},
    {"isin": "INE171A01029", "name": "THE FEDERAL BANK LIMITED",                "qty":   147, "price":  299.95, "value":    44_092.65},
    {"isin": "INE364U01010", "name": "GODREJ CONSUMER PRODUCTS LIMITED",        "qty":    25, "price":  948.20, "value":    23_705.00},
    {"isin": "INE102D01028", "name": "HDFC BANK LIMITED",                       "qty":    45, "price": 1217.60, "value":    54_792.00},
    {"isin": "INE040A01034", "name": "HDFC BANK LIMITED",                       "qty":    90, "price":  887.40, "value":    79_866.00},
    {"isin": "INE531E01026", "name": "HINDUSTAN COPPER LIMITED",                "qty":   100, "price":  567.55, "value":    56_755.00},
    {"isin": "INE090A01021", "name": "ICICI BANK LIMITED",                      "qty":    41, "price": 1379.00, "value":    56_539.00},
    {"isin": "INE346A01027", "name": "ICICI PRUDENTIAL AMC LIMITED",            "qty":     6, "price": 3104.35, "value":    18_626.10},
    {"isin": "INE022Q01020", "name": "INDIAN ENERGY EXCHANGE LIMITED",          "qty":    30, "price":  125.15, "value":     3_754.50},
    {"isin": "INE202E01016", "name": "IREDA LIMITED",                           "qty":   292, "price":  122.30, "value":    35_711.60},
    {"isin": "INE009A01021", "name": "INFOSYS LIMITED",                         "qty":    35, "price": 1299.95, "value":    45_498.25},
    {"isin": "INE018A01030", "name": "LARSEN AND TOUBRO LIMITED",               "qty":    10, "price": 4280.55, "value":    42_805.50},
    {"isin": "INE774D01024", "name": "L&T FINANCE LIMITED",                     "qty":   105, "price":  374.95, "value":    39_369.75},
    {"isin": "INE312K01010", "name": "METROPOLITAN STOCK EXCHANGE LIMITED",     "qty": 20000, "price":    1.00, "value":    20_000.00},
    {"isin": "INE663F01032", "name": "POWER GRID CORPORATION",                  "qty":    31, "price": 1031.70, "value":    31_982.70},
    {"isin": "INE237A01036", "name": "STAR HEALTH INSURANCE",                   "qty":    87, "price":  415.30, "value":    36_131.10},
    {"isin": "INE982J01020", "name": "RBL BANK LIMITED",                        "qty":    52, "price": 1096.15, "value":    56_999.80},
    {"isin": "INE020B01018", "name": "REC LIMITED",                             "qty":   154, "price":  350.10, "value":    53_915.40},
    {"isin": "INE002A01018", "name": "RELIANCE INDUSTRIES LIMITED",             "qty":    30, "price": 1394.30, "value":    41_829.00},
    {"isin": "INE665A01038", "name": "SWAN CORP LIMITED",                       "qty":    36, "price":  382.80, "value":    13_780.80},
    {"isin": "INE00H001014", "name": "SWIGGY LIMITED",                          "qty":   101, "price":  302.10, "value":    30_512.10},
    {"isin": "INE398R01022", "name": "SYNGENE INTERNATIONAL LIMITED",           "qty":    35, "price":  422.35, "value":    14_782.25},
    {"isin": "INE669C01036", "name": "TECH MAHINDRA LIMITED",                   "qty":    43, "price": 1357.25, "value":    58_361.75},
    {"isin": "INE854D01024", "name": "UNITED SPIRITS LIMITED",                  "qty":    31, "price": 1383.20, "value":    42_879.20},
    {"isin": "INE665L01035", "name": "VARROC ENGINEERING LIMITED",              "qty":    60, "price":  541.10, "value":    32_466.00},
    {"isin": "INE377N01017", "name": "WAAREE ENERGIES LIMITED",                 "qty":     9, "price": 2709.60, "value":    24_386.40},
    {"isin": "INE716O01013", "name": "WHIRLPOOL OF INDIA LIMITED",              "qty":    26, "price":  922.15, "value":    23_975.90},
    {"isin": "INE572E01012", "name": "PNB HOUSING FINANCE LIMITED",             "qty":    29, "price":  828.80, "value":    24_035.20},
]

EXPECTED_ETFS = [
    {"isin": "INF204KB1715", "name": "NIPPON INDIA ETF GOLD BeES",                  "qty":   100,   "price":  131.64, "value":     13_164.00},
    {"isin": "INF732E01037", "name": "NIPPON INDIA ETF NIFTY 1D RATE LIQUID BeES",  "qty":   0.613, "price":  999.99, "value":        612.99},
    {"isin": "INF204KC1402", "name": "NIPPON INDIA SILVER ETF",                     "qty":   600,   "price":  252.81, "value":    151_686.00},
    {"isin": "INF078F01034", "name": "ZERODHA NIFTY 1D RATE LIQUID ETF",            "qty":   588,   "price":  112.95, "value":     66_414.60},
]

EXPECTED_MF_FOLIOS = [
    {"isin": "INF209K01BR9", "name": "Aditya Birla Sun Life Large Cap Fund", "units":   41.576, "nav":  525.9800, "value":    21_868.14},
    {"isin": "INF179K01CR2", "name": "HDFC Mid Cap Fund",                    "units": 1995.624, "nav":  202.5750, "value":   404_263.53},
    {"isin": "INF179K01CT8", "name": "HDFC Mid Cap Fund",                    "units": 3519.313, "nav":   50.8240, "value":   178_865.56},
    {"isin": "INF109K01AF8", "name": "ICICI Prudential Value Fund",          "units":  900.619, "nav":  484.3500, "value":   436_214.81},
    {"isin": "INF174K01187", "name": "Kotak Large & Midcap Fund",            "units":  162.485, "nav":  355.6990, "value":    57_795.75},
    {"isin": "INF769K01EY2", "name": "Mirae Asset Midcap Fund",              "units": 2864.292, "nav":   37.0490, "value":   106_119.15},
    {"isin": "INF204K01HY3", "name": "NIPPON INDIA SMALL CAP FUND",          "units":  719.911, "nav":  162.1622, "value":   116_742.35},
    {"isin": "INF879001019", "name": "Parag Parikh Flexi Cap Fund",          "units":  751.145, "nav":   84.0452, "value":    63_130.13},
]

# Expected counts visible to the parser
EXPECTED_COUNTS = {
    "equity":       33,
    "etf":           4,
    "gold":          0,    # CDSL CAS has no SGB section
    "mutual_fund":   8,
}

# Expected section totals (sum of qty × price per asset class, per-row)
EXPECTED_SECTION_TOTALS = {
    "equity":       sum(e["value"] for e in EXPECTED_EQUITIES),        # 1_206_676.15
    "etf":          sum(e["value"] for e in EXPECTED_ETFS),            #   231_877.59
    "gold":         0.0,
    "mutual_fund":  sum(m["value"] for m in EXPECTED_MF_FOLIOS),       # 1_384_999.42
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
    if not CDSL_PDF.exists():
        pytest.skip("varun_cdsl.pdf missing from tests/test_data/cdsl/")
    from services.docling_cas_parser import parse_with_docling
    holdings, _ = parse_with_docling(CDSL_PDF.read_bytes(), password="")
    return holdings


# ════════════════════════════════════════════════════════════════════════════
# 1. COUNT CHECKS
# ════════════════════════════════════════════════════════════════════════════

@docling_required
@pdf_required
class TestCDSLCountAccuracy:
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

    def test_gold_sgb_count_is_zero(self, parsed):
        """CDSL CAS for this investor has no SGBs — parser must not invent any."""
        got = [h for h in parsed if h["asset_type"] == "gold"]
        assert len(got) == 0, (
            f"CDSL fixture has no SGB holdings, but parser returned {len(got)}: "
            f"{[h['ticker'] for h in got]}"
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

    def test_no_duplicate_isins(self, parsed):
        isins = [h["ticker"] for h in parsed if h.get("ticker")]
        dupes = [t for t in set(isins) if isins.count(t) > 1]
        assert not dupes, f"Duplicate ISINs in output: {dupes}"

    def test_two_hdfc_bank_demats_present(self, parsed):
        """CDSL fixture has HDFC BANK held in two different demats — both ISINs
        (INE102D01028 and INE040A01034) must appear as separate rows."""
        a = _find(parsed, "INE102D01028")
        b = _find(parsed, "INE040A01034")
        assert a is not None, "First HDFC BANK demat (INE102D01028) missing"
        assert b is not None, "Second HDFC BANK demat (INE040A01034) missing"
        assert a is not b, "Both HDFC BANK ISINs collapsed to a single row"


# ════════════════════════════════════════════════════════════════════════════
# 2. SECTION TOTAL VALUE CHECKS
# ════════════════════════════════════════════════════════════════════════════

@docling_required
@pdf_required
class TestCDSLSectionTotals:
    """Sum of (qty × price) per asset class must be within 5% of ground truth."""

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
    # Two HDFC BANK rows share the same name — ID by ISIN keeps pytest IDs unique
    return e["isin"]


@docling_required
@pdf_required
class TestCDSLEquityHoldings:
    """One-to-one check for each of the 33 equity holdings."""

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
class TestCDSLETFHoldings:
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
# 5. PER-HOLDING: MUTUAL FUND FOLIOS
# ════════════════════════════════════════════════════════════════════════════

def _mf_id(m):
    return m["isin"]


@docling_required
@pdf_required
class TestCDSLMFHoldings:
    """One-to-one check for each of the 8 MF folio holdings (via casparser)."""

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
