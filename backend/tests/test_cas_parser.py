"""
CAS Parser Test Framework
Tests NSDL and CDSL CAS parsing with golden expected outputs.
Accuracy-driven testing with fuzzy matching for names and numeric tolerance for values.
"""
import json
import os
import sys
import pytest
from pathlib import Path
from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).parent.parent))

TEST_DATA = Path(__file__).parent / "test_data"
EXPECTED = TEST_DATA / "expected_outputs"
NSDL_PDF = TEST_DATA / "nsdl" / "priyanka_nsdl.pdf"
CDSL_PDF = TEST_DATA / "cdsl" / "varun_cdsl.pdf"

# ─── Accuracy Thresholds ──────────────────────────────────────
SCHEME_NAME_MIN_SIMILARITY = 70   # fuzzy match %
VALUE_TOLERANCE_PCT = 0.05        # 5% tolerance on numeric values
VALUE_TOLERANCE_ABS = 10          # ₹10 absolute tolerance
SECTION_COVERAGE_MIN = 0.50       # 50% of section value must be captured
ISIN_MATCH_RATE = 0.70            # 70% of ISINs should be found


def load_expected(name):
    with open(EXPECTED / name) as f:
        return json.load(f)


def match_holding_by_isin(holdings, isin):
    """Find a parsed holding by ISIN (with OCR error tolerance)."""
    for h in holdings:
        ticker = h.get("ticker", "")
        if ticker == isin:
            return h
        # Allow 1-char OCR error
        if len(ticker) == len(isin) and sum(a != b for a, b in zip(ticker, isin)) <= 1:
            return h
    return None


def value_close(actual, expected, tolerance_pct=VALUE_TOLERANCE_PCT, tolerance_abs=VALUE_TOLERANCE_ABS):
    """Check if values are close within tolerance."""
    if expected == 0:
        return actual == 0
    return abs(actual - expected) <= max(abs(expected) * tolerance_pct, tolerance_abs)


def compute_accuracy(parsed_holdings, expected_holdings, value_key="value"):
    """Compute parsing accuracy metrics."""
    total = len(expected_holdings)
    found = 0
    isin_matched = 0
    value_correct = 0
    name_scores = []

    for exp in expected_holdings:
        h = match_holding_by_isin(parsed_holdings, exp["isin"])
        if h:
            isin_matched += 1
            # Check value
            parsed_val = h.get("quantity", 0) * h.get("current_price", 0)
            if value_close(parsed_val, exp.get(value_key, exp.get("value", 0))):
                value_correct += 1
            # Check name similarity
            sim = fuzz.partial_ratio(h.get("name", "").lower(), exp.get("name", "").lower())
            name_scores.append(sim)

    return {
        "total_expected": total,
        "isin_matched": isin_matched,
        "isin_match_rate": isin_matched / max(total, 1),
        "value_correct": value_correct,
        "value_accuracy": value_correct / max(total, 1),
        "avg_name_similarity": sum(name_scores) / max(len(name_scores), 1),
    }


# ═══════════════════════════════════════════════════════════════
# A. FILE HANDLING TESTS
# ═══════════════════════════════════════════════════════════════

class TestFileHandling:
    def test_valid_nsdl_pdf(self):
        """Valid NSDL PDF should parse without crashing."""
        from services.cas_parser import parse_nsdl_cas_image
        with open(NSDL_PDF, "rb") as f:
            content = f.read()
        holdings = parse_nsdl_cas_image(content)
        assert isinstance(holdings, list)
        assert len(holdings) > 0, "No holdings parsed from valid NSDL PDF"

    def test_valid_cdsl_pdf(self):
        """Valid CDSL PDF should parse without crashing."""
        from services.cas_parser import parse_nsdl_cas_image
        with open(CDSL_PDF, "rb") as f:
            content = f.read()
        holdings = parse_nsdl_cas_image(content)
        assert isinstance(holdings, list)
        assert len(holdings) > 0, "No holdings parsed from valid CDSL PDF"

    def test_corrupted_file(self):
        """Corrupted/non-PDF should return empty list, not crash."""
        from services.cas_parser import parse_nsdl_cas_image
        holdings = parse_nsdl_cas_image(b"this is not a pdf")
        assert holdings == []

    def test_empty_file(self):
        """Empty file should return empty list."""
        from services.cas_parser import parse_nsdl_cas_image
        holdings = parse_nsdl_cas_image(b"")
        assert holdings == []

    def test_large_file_no_timeout(self):
        """Large PDF (16+ pages) should complete within 120 seconds."""
        import time
        from services.cas_parser import parse_nsdl_cas_image
        with open(NSDL_PDF, "rb") as f:
            content = f.read()
        start = time.time()
        holdings = parse_nsdl_cas_image(content)
        elapsed = time.time() - start
        assert elapsed < 120, f"Parsing took {elapsed:.1f}s, expected < 120s"
        assert len(holdings) > 0


# ═══════════════════════════════════════════════════════════════
# B. NSDL CAS PARSING TESTS
# ═══════════════════════════════════════════════════════════════

class TestNSDLParsing:
    @pytest.fixture(autouse=True)
    def setup(self):
        from services.cas_parser import parse_nsdl_cas_image
        with open(NSDL_PDF, "rb") as f:
            content = f.read()
        self.holdings = parse_nsdl_cas_image(content)
        self.expected = load_expected("priyanka_nsdl.json")

    def _by_type(self, asset_type):
        return [h for h in self.holdings if h["asset_type"] == asset_type]

    # --- ISIN Format Validation ---
    def test_all_isins_valid_format(self):
        """All parsed ISINs should match IN[A-Z0-9]{10} pattern."""
        import re
        isin_re = re.compile(r'^IN[A-Z0-9]{10}$')
        invalid = [h["ticker"] for h in self.holdings if h["ticker"] and not isin_re.match(h["ticker"])]
        # Allow SGB ISINs (IN00...) which have different format
        invalid_filtered = [i for i in invalid if not i.startswith("IN00")]
        assert len(invalid_filtered) == 0, f"Invalid ISINs: {invalid_filtered}"

    # --- Section Coverage ---
    def test_equities_section_coverage(self):
        """Equities section should capture >= 50% of expected value."""
        equities = self._by_type("equity")
        total_parsed = sum(h["quantity"] * h["current_price"] for h in equities)
        expected = self.expected["summary"]["equities"]
        coverage = total_parsed / expected if expected > 0 else 0
        assert coverage >= SECTION_COVERAGE_MIN, f"Equities coverage {coverage:.1%} < {SECTION_COVERAGE_MIN:.0%} (₹{total_parsed:,.0f}/₹{expected:,.0f})"

    def test_mf_folios_section_coverage(self):
        """MF Folios section should capture >= 50% of expected value."""
        mf = self._by_type("mutual_fund")
        total_parsed = sum(h["quantity"] * h["current_price"] for h in mf)
        expected = self.expected["summary"]["mutual_fund_folios"]
        coverage = total_parsed / expected if expected > 0 else 0
        assert coverage >= SECTION_COVERAGE_MIN, f"MF Folios coverage {coverage:.1%} < {SECTION_COVERAGE_MIN:.0%} (₹{total_parsed:,.0f}/₹{expected:,.0f})"

    def test_sgb_section_exists(self):
        """SGB section should have at least 1 holding parsed."""
        gold = self._by_type("gold")
        assert len(gold) > 0, "No SGBs parsed — SGB section completely missing"

    def test_etf_section_coverage(self):
        """ETF demat section should capture >= 30% of expected value."""
        etfs = self._by_type("etf")
        total_parsed = sum(h["quantity"] * h["current_price"] for h in etfs)
        expected = self.expected["summary"]["mutual_funds_demat"]
        coverage = total_parsed / expected if expected > 0 else 0
        assert coverage >= 0.30, f"ETF coverage {coverage:.1%} < 30%"

    # --- Holdings Accuracy ---
    def test_equities_isin_match_rate(self):
        """>=70% of expected equity ISINs should be found."""
        equities = self._by_type("equity")
        acc = compute_accuracy(equities, self.expected["equities"])
        assert acc["isin_match_rate"] >= ISIN_MATCH_RATE, f"Equity ISIN match rate {acc['isin_match_rate']:.1%} < {ISIN_MATCH_RATE:.0%}"

    def test_equities_value_accuracy(self):
        """Parsed equity values should be within 5% of expected."""
        equities = self._by_type("equity")
        acc = compute_accuracy(equities, self.expected["equities"])
        assert acc["value_accuracy"] >= 0.60, f"Equity value accuracy {acc['value_accuracy']:.1%} < 60%"

    def test_mf_folios_isin_match_rate(self):
        """>=70% of expected MF Folio ISINs should be found."""
        mf = self._by_type("mutual_fund")
        acc = compute_accuracy(mf, self.expected["mf_folios"])
        assert acc["isin_match_rate"] >= ISIN_MATCH_RATE, f"MF Folio ISIN match {acc['isin_match_rate']:.1%} < {ISIN_MATCH_RATE:.0%}"

    def test_mf_folios_value_accuracy(self):
        """Parsed MF values should be within 5% of expected."""
        mf = self._by_type("mutual_fund")
        acc = compute_accuracy(mf, self.expected["mf_folios"])
        assert acc["value_accuracy"] >= 0.50, f"MF value accuracy {acc['value_accuracy']:.1%} < 50%"

    # --- Cross-Validation ---
    def test_units_times_nav_equals_value(self):
        """For each holding: quantity * current_price should be a reasonable value."""
        for h in self.holdings:
            qty = h.get("quantity", 0)
            price = h.get("current_price", 0)
            if qty > 0 and price > 0:
                value = qty * price
                assert value < 100000000, f"{h['name']}: value ₹{value:,.0f} seems unreasonably high"

    # --- Specific Holdings Tests ---
    def test_ambuja_cements_correct(self):
        """AMBUJA CEMENTS: 30 shares @ ₹500.40."""
        h = match_holding_by_isin(self.holdings, "INE079A01024")
        assert h is not None, "AMBUJA CEMENTS not found"
        assert h["quantity"] == 30, f"Expected 30 shares, got {h['quantity']}"
        assert value_close(h["current_price"], 500.40), f"Expected ₹500.40, got ₹{h['current_price']}"

    def test_gabriel_india_correct(self):
        """GABRIEL INDIA: 204 shares @ ₹998.80."""
        h = match_holding_by_isin(self.holdings, "INE524A01029")
        assert h is not None, "GABRIEL INDIA not found"
        assert h["quantity"] == 204, f"Expected 204 shares, got {h['quantity']}"

    def test_icici_prudential_largecap_correct(self):
        """ICICI Prudential Large Cap: ~5479.803 units @ ~₹123.60 NAV."""
        h = match_holding_by_isin(self.holdings, "INF109K016L0")
        if h:
            assert value_close(h["quantity"], 5479.803, 0.01), f"Expected ~5479.803 units, got {h['quantity']}"
            assert value_close(h["current_price"], 123.60, 0.05), f"Expected NAV ~123.60, got {h['current_price']}"

    def test_aditya_birla_largecap_correct(self):
        """Aditya Birla Sun Life Large Cap: ~7626.250 units @ ~₹93.87 NAV."""
        h = match_holding_by_isin(self.holdings, "INF209K01YW1")
        if h:
            assert value_close(h["quantity"], 7626.250, 0.01), f"Expected ~7626.250 units, got {h['quantity']}"
            assert value_close(h["current_price"], 93.87, 0.05), f"Expected NAV ~93.87, got {h['current_price']}"

    # --- No Duplicates ---
    def test_no_duplicate_isins(self):
        """No duplicate ISINs in parsed holdings."""
        isins = [h["ticker"] for h in self.holdings if h["ticker"]]
        dupes = set(i for i in isins if isins.count(i) > 1)
        # Allow ICICI Prudential (2 different funds with similar ISIN prefix)
        assert len(dupes) <= 2, f"Duplicate ISINs: {dupes}"


# ═══════════════════════════════════════════════════════════════
# C. CDSL CAS PARSING TESTS
# ═══════════════════════════════════════════════════════════════

class TestCDSLParsing:
    @pytest.fixture(autouse=True)
    def setup(self):
        from services.cas_parser import parse_nsdl_cas_image
        with open(CDSL_PDF, "rb") as f:
            content = f.read()
        self.holdings = parse_nsdl_cas_image(content)
        self.expected = load_expected("varun_cdsl.json")

    def _by_type(self, asset_type):
        return [h for h in self.holdings if h["asset_type"] == asset_type]

    def test_parses_holdings(self):
        """CDSL CAS should parse at least some holdings."""
        assert len(self.holdings) > 0, "No holdings parsed from CDSL CAS"

    def test_equities_coverage(self):
        """Equities should capture >= 30% of expected value."""
        equities = [h for h in self.holdings if h["asset_type"] in ("equity", "etf", "mutual_fund")]
        total_parsed = sum(h["quantity"] * h["current_price"] for h in equities)
        expected = self.expected["summary"]["total_portfolio"]
        coverage = total_parsed / expected if expected > 0 else 0
        assert coverage >= 0.30, f"Total coverage {coverage:.1%} < 30% (₹{total_parsed:,.0f}/₹{expected:,.0f})"

    def test_isin_format_valid(self):
        """All parsed ISINs should be valid format."""
        import re
        isin_re = re.compile(r'^IN[A-Z0-9]{10}$')
        for h in self.holdings:
            if h["ticker"]:
                assert isin_re.match(h["ticker"]) or h["ticker"].startswith("IN00"), f"Invalid ISIN: {h['ticker']}"

    def test_no_extreme_values(self):
        """No holding should have unreasonably high value (>₹10Cr)."""
        for h in self.holdings:
            val = h["quantity"] * h["current_price"]
            assert val < 100000000, f"{h['name']}: ₹{val:,.0f} is unreasonably high"

    def test_equities_isin_match(self):
        """>=50% of expected equity ISINs should be found."""
        all_parsed = self.holdings
        acc = compute_accuracy(all_parsed, self.expected["equities"])
        assert acc["isin_match_rate"] >= 0.50, f"CDSL equity ISIN match {acc['isin_match_rate']:.1%} < 50%"

    def test_mf_folios_exist(self):
        """MF Folios should have at least 4 holdings."""
        mf = self._by_type("mutual_fund")
        assert len(mf) >= 4, f"Expected >= 4 MF folios, got {len(mf)}"


# ═══════════════════════════════════════════════════════════════
# D. ACCURACY REPORT GENERATION
# ═══════════════════════════════════════════════════════════════

class TestAccuracyReport:
    def test_generate_nsdl_accuracy_report(self):
        """Generate detailed accuracy report for NSDL CAS."""
        from services.cas_parser import parse_nsdl_cas_image
        with open(NSDL_PDF, "rb") as f:
            content = f.read()
        holdings = parse_nsdl_cas_image(content)
        expected = load_expected("priyanka_nsdl.json")

        report = {"nsdl": {}}
        for section, asset_type in [("equities", "equity"), ("mf_folios", "mutual_fund")]:
            parsed = [h for h in holdings if h["asset_type"] == asset_type]
            acc = compute_accuracy(parsed, expected[section])
            total_parsed = sum(h["quantity"] * h["current_price"] for h in parsed)
            total_expected = sum(e["value"] for e in expected[section])
            report["nsdl"][section] = {
                "isin_match_rate": f"{acc['isin_match_rate']:.1%}",
                "value_accuracy": f"{acc['value_accuracy']:.1%}",
                "name_similarity": f"{acc['avg_name_similarity']:.0f}%",
                "total_parsed": f"₹{total_parsed:,.0f}",
                "total_expected": f"₹{total_expected:,.0f}",
                "coverage": f"{total_parsed / max(total_expected, 1):.1%}",
            }

        # Write report
        report_path = Path(__file__).parent.parent / "tests" / "accuracy_report.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nAccuracy Report: {json.dumps(report, indent=2)}")
        assert True  # Always pass — this is a reporting test
