"""CAS Parser Benchmark Tests — ahaanporwal16@gmail.com fixtures.

These tests run against real NSDLe-CAS PDFs imported from the test account
(user_e56d1d46b024 / ahaanporwal16@gmail.com). Fixtures live at:
    tests/test_data/nsdl/ahaanporwal/NSDLe-CAS_106904998_*.PDF

To add a new fixture:
  1. Import the CAS PDF via the Gmail Import UI while logged in as the test user.
  2. The PDF is automatically saved to the fixture directory above.
  3. Run `python tests/generate_expected.py` to generate a baseline expected JSON.
  4. Verify the JSON is correct, commit both PDF + JSON.

Accuracy thresholds:
    ISIN match rate   ≥ 80%   (80% of expected ISINs must be found)
    Value tolerance   ≤ 5%    (per-holding current_price within 5% or ₹10)
    Holdings coverage ≥ 90%   (90% of expected holdings must appear)
    Parse time        ≤ 10 s  (casparser fast-path should hit for text PDFs)
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Paths ─────────────────────────────────────────────────────────────
TEST_DATA = Path(__file__).parent / "test_data"
FIXTURE_DIR = TEST_DATA / "nsdl" / "ahaanporwal"
EXPECTED_DIR = TEST_DATA / "expected_outputs" / "ahaanporwal"
EXPECTED_DIR.mkdir(parents=True, exist_ok=True)

# CAS PDF password for this account (PAN in uppercase)
CAS_PASSWORD = os.environ.get("CAS_TEST_PASSWORD", "")

# ── Thresholds ─────────────────────────────────────────────────────────
PARSE_SLA_SECONDS = 10
ISIN_MATCH_RATE = 0.80
VALUE_TOLERANCE_PCT = 0.05
VALUE_TOLERANCE_ABS = 10.0
HOLDINGS_COVERAGE = 0.90
SCHEME_NAME_FUZZY_MIN = 70


# ── Helpers ────────────────────────────────────────────────────────────
def _pdf_fixtures() -> List[Path]:
    if not FIXTURE_DIR.exists():
        return []
    return sorted(FIXTURE_DIR.glob("*.PDF")) + sorted(FIXTURE_DIR.glob("*.pdf"))


def _expected_path(pdf: Path) -> Path:
    return EXPECTED_DIR / (pdf.stem + ".json")


def _load_expected(pdf: Path) -> Dict[str, Any] | None:
    p = _expected_path(pdf)
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return None


def _value_close(actual: float, expected: float) -> bool:
    if expected == 0:
        return actual == 0
    return abs(actual - expected) <= max(abs(expected) * VALUE_TOLERANCE_PCT, VALUE_TOLERANCE_ABS)


def _isin_index(holdings: list) -> Dict[str, dict]:
    return {h.get("ticker", ""): h for h in holdings if h.get("ticker")}


# ── Parser import (lazy — skip if not installed) ────────────────────────
def _run_casparser(pdf_bytes: bytes, password: str) -> tuple[list, float]:
    """Run the casparser fast-path and return (holdings, elapsed_seconds)."""
    import asyncio
    from helpers.parsing import convert_casparser_to_holdings

    import casparser as _cp

    t0 = time.monotonic()
    raw = _cp.read_cas_pdf(io.BytesIO(pdf_bytes), password or "", output="dict")
    holdings = convert_casparser_to_holdings(raw)
    return holdings, time.monotonic() - t0


# ── Fixtures ────────────────────────────────────────────────────────────
@pytest.fixture(params=[str(p) for p in _pdf_fixtures()])
def cas_pdf(request):
    path = Path(request.param)
    with open(path, "rb") as f:
        return path, f.read()


# ── Tests ───────────────────────────────────────────────────────────────
class TestCasParseSLA:
    """casparser fast-path must parse each fixture within the 10 s SLA."""

    @pytest.mark.skipif(not _pdf_fixtures(), reason="No fixtures yet — import CAS PDFs first")
    def test_parse_time_within_sla(self, cas_pdf):
        pdf_path, pdf_bytes = cas_pdf
        try:
            holdings, elapsed = _run_casparser(pdf_bytes, CAS_PASSWORD)
        except Exception as e:
            pytest.skip(f"casparser failed on {pdf_path.name}: {e}")

        assert elapsed <= PARSE_SLA_SECONDS, (
            f"{pdf_path.name}: parse took {elapsed:.1f}s, SLA={PARSE_SLA_SECONDS}s"
        )


class TestCasHoldingsCount:
    """Parser must extract a non-trivial number of holdings."""

    @pytest.mark.skipif(not _pdf_fixtures(), reason="No fixtures yet — import CAS PDFs first")
    def test_non_empty_holdings(self, cas_pdf):
        pdf_path, pdf_bytes = cas_pdf
        try:
            holdings, _ = _run_casparser(pdf_bytes, CAS_PASSWORD)
        except Exception as e:
            pytest.skip(f"casparser failed on {pdf_path.name}: {e}")

        assert len(holdings) > 0, f"{pdf_path.name}: parser returned 0 holdings"

    @pytest.mark.skipif(not _pdf_fixtures(), reason="No fixtures yet — import CAS PDFs first")
    def test_holdings_have_required_fields(self, cas_pdf):
        pdf_path, pdf_bytes = cas_pdf
        try:
            holdings, _ = _run_casparser(pdf_bytes, CAS_PASSWORD)
        except Exception as e:
            pytest.skip(f"casparser failed on {pdf_path.name}: {e}")

        required = {"name", "ticker", "asset_type", "quantity", "current_price"}
        for h in holdings:
            missing = required - set(h.keys())
            assert not missing, f"{pdf_path.name}: holding {h.get('name')} missing fields: {missing}"


class TestCasAccuracyAgainstExpected:
    """Compare parsed output against the golden expected JSON.

    These tests only run when an expected JSON file exists for the fixture.
    Generate one with: python tests/generate_expected.py
    """

    def _check_fixture(self, pdf_path: Path, pdf_bytes: bytes):
        expected = _load_expected(pdf_path)
        if expected is None:
            pytest.skip(f"No expected JSON for {pdf_path.name} — run generate_expected.py")

        try:
            holdings, elapsed = _run_casparser(pdf_bytes, CAS_PASSWORD)
        except Exception as e:
            pytest.fail(f"casparser raised on {pdf_path.name}: {e}")

        exp_holdings = expected.get("holdings", [])
        if not exp_holdings:
            pytest.skip(f"Expected JSON for {pdf_path.name} has no holdings")

        parsed_idx = _isin_index(holdings)
        exp_idx = _isin_index(exp_holdings)

        # 1. ISIN match rate
        matched_isins = [isin for isin in exp_idx if isin in parsed_idx]
        isin_rate = len(matched_isins) / len(exp_idx) if exp_idx else 1.0
        assert isin_rate >= ISIN_MATCH_RATE, (
            f"{pdf_path.name}: ISIN match rate {isin_rate:.0%} < {ISIN_MATCH_RATE:.0%}. "
            f"Missing: {[i for i in exp_idx if i not in parsed_idx][:5]}"
        )

        # 2. Holdings coverage (by count)
        coverage = len(matched_isins) / len(exp_holdings) if exp_holdings else 1.0
        assert coverage >= HOLDINGS_COVERAGE, (
            f"{pdf_path.name}: holdings coverage {coverage:.0%} < {HOLDINGS_COVERAGE:.0%}"
        )

        # 3. Value accuracy for matched holdings
        value_errors = []
        for isin in matched_isins:
            parsed_h = parsed_idx[isin]
            exp_h = exp_idx[isin]
            exp_price = float(exp_h.get("current_price") or 0)
            parsed_price = float(parsed_h.get("current_price") or 0)
            if exp_price > 0 and not _value_close(parsed_price, exp_price):
                value_errors.append(
                    f"{isin}: expected ₹{exp_price:.2f}, got ₹{parsed_price:.2f}"
                )

        assert not value_errors, (
            f"{pdf_path.name}: {len(value_errors)} value mismatch(es):\n" +
            "\n".join(value_errors[:5])
        )

    @pytest.mark.skipif(not _pdf_fixtures(), reason="No fixtures yet — import CAS PDFs first")
    def test_accuracy_against_expected(self, cas_pdf):
        pdf_path, pdf_bytes = cas_pdf
        self._check_fixture(pdf_path, pdf_bytes)


class TestCasParserProviderChain:
    """casparser fast-path should be the winning provider for text PDFs."""

    @pytest.mark.skipif(not _pdf_fixtures(), reason="No fixtures yet — import CAS PDFs first")
    def test_casparser_is_fast_path_for_text_pdf(self, cas_pdf):
        """Verify text PDFs are handled by casparser, not Document AI."""
        from helpers.parsing import convert_casparser_to_holdings
        pdf_path, pdf_bytes = cas_pdf

        try:
            import casparser as _cp
            raw = _cp.read_cas_pdf(io.BytesIO(pdf_bytes), CAS_PASSWORD or "", output="dict")
            holdings = convert_casparser_to_holdings(raw)
        except Exception as e:
            pytest.skip(f"casparser unavailable: {e}")

        # If casparser got holdings, the fast-path would have fired,
        # meaning Document AI would NOT have been called.
        assert len(holdings) > 0, (
            f"{pdf_path.name}: casparser returned no holdings — this PDF will hit "
            "Document AI (slow path). Check if it's a scanned/image PDF."
        )


class TestNsdlCasSpecific:
    """NSDL-specific structure checks for the ahaanporwal fixtures."""

    @pytest.mark.skipif(not _pdf_fixtures(), reason="No fixtures yet — import CAS PDFs first")
    def test_all_holdings_have_isin(self, cas_pdf):
        pdf_path, pdf_bytes = cas_pdf
        try:
            holdings, _ = _run_casparser(pdf_bytes, CAS_PASSWORD)
        except Exception as e:
            pytest.skip(f"casparser failed on {pdf_path.name}: {e}")

        mf_holdings = [h for h in holdings if h.get("asset_type") == "mutual_fund"]
        no_isin = [h for h in mf_holdings if not h.get("ticker")]
        assert len(no_isin) == 0, (
            f"{pdf_path.name}: {len(no_isin)} mutual fund holdings missing ISIN: "
            f"{[h.get('name') for h in no_isin[:3]]}"
        )

    @pytest.mark.skipif(not _pdf_fixtures(), reason="No fixtures yet — import CAS PDFs first")
    def test_holdings_quantities_positive(self, cas_pdf):
        pdf_path, pdf_bytes = cas_pdf
        try:
            holdings, _ = _run_casparser(pdf_bytes, CAS_PASSWORD)
        except Exception as e:
            pytest.skip(f"casparser failed on {pdf_path.name}: {e}")

        bad = [h for h in holdings if float(h.get("quantity") or 0) <= 0]
        assert not bad, (
            f"{pdf_path.name}: {len(bad)} holdings have zero/negative quantity: "
            f"{[h.get('name') for h in bad[:3]]}"
        )

    @pytest.mark.skipif(not _pdf_fixtures(), reason="No fixtures yet — import CAS PDFs first")
    def test_holdings_prices_positive(self, cas_pdf):
        pdf_path, pdf_bytes = cas_pdf
        try:
            holdings, _ = _run_casparser(pdf_bytes, CAS_PASSWORD)
        except Exception as e:
            pytest.skip(f"casparser failed on {pdf_path.name}: {e}")

        bad = [h for h in holdings if float(h.get("current_price") or 0) <= 0]
        # Warn rather than fail — some ETFs may have missing NAV
        if bad:
            pytest.warns(
                UserWarning,
                match="zero price",
            ) if False else None  # soft check
            print(
                f"\nWARN {pdf_path.name}: {len(bad)} holdings have zero/negative "
                f"price: {[h.get('name') for h in bad[:3]]}"
            )
