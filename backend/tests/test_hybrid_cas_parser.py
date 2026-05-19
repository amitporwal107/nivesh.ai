"""Tests for the hybrid CAS parser pipeline.

A. Unit tests (always run): section detection, schema coercion,
   reconciliation logic — no external API calls.
B. Integration test (skipped unless OPENAI_API_KEY set): full pipeline
   on the NSDL fixture, with latency + holdings-count assertions.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from services import cas_sections                  # noqa: E402
from services.cas_reconciler import reconcile, ROW_TOLERANCE_PCT  # noqa: E402
from services.cas_schema import CASExtraction, EquityHolding      # noqa: E402


# ── A. Pure-function unit tests ───────────────────────────────────────
class TestSchema:
    def test_coerce_numeric_strings(self):
        e = EquityHolding.model_validate({
            "isin": "INE002A01018",
            "company_name": "RIL",
            "num_shares": "1,234.56",
            "market_price_inr": "₹2,500.75",
            "value_inr": "3,088,425.84",
        })
        assert e.num_shares == 1234.56
        assert e.market_price_inr == 2500.75
        assert e.value_inr == pytest.approx(3088425.84)

    def test_empty_strings_become_none(self):
        e = EquityHolding.model_validate({
            "isin": "INE002A01018",
            "company_name": "RIL",
            "num_shares": "",
            "market_price_inr": None,
        })
        assert e.num_shares is None
        assert e.market_price_inr is None

    def test_total_holding_value_sums_all_sections(self):
        cas = CASExtraction.model_validate({
            "holdings": {
                "equities": [
                    {"company_name": "A", "num_shares": 10,
                     "market_price_inr": 100, "value_inr": 1000},
                ],
                "mutual_fund_folios": [
                    {"fund_name": "F", "num_units": 5,
                     "current_nav_inr": 200, "current_value_inr": 1000},
                ],
            },
        })
        assert cas.total_holding_value() == 2000.0
        assert cas.holding_count() == 2


class TestSectionDetection:
    def _make_page(self, num: int, text: str) -> cas_sections.PageInfo:
        p = cas_sections.PageInfo(
            page_num=num, text=text, width=595, height=842,
        )
        # mimic extract_pages classification pass
        for name, pattern in cas_sections._ANCHORS:
            if pattern.search(text):
                p.sections.append(name)
        p.isin_count = len(cas_sections._ISIN_RE.findall(text))
        p.decimal_count = len(cas_sections._DECIMAL_RE.findall(text))
        p.is_table_dense = (p.isin_count >= 3 or p.decimal_count >= 8)
        return p

    def test_equity_anchor_matches_nsdl_heading(self):
        p = self._make_page(1, "Equities (E)\nINE002A01018  RIL  10  2,500.00  25,000.00")
        assert cas_sections.SECTION_EQUITY in p.sections

    def test_mf_folio_anchor_matches_cams_heading(self):
        p = self._make_page(2, "Folio No: 12345\nScheme Name  NAV  Units")
        assert cas_sections.SECTION_MF_FOLIO in p.sections

    def test_sgb_anchor(self):
        p = self._make_page(3, "Sovereign Gold Bond Holdings\nIN0020220110  SGB 2022-23 III")
        assert cas_sections.SECTION_SGB in p.sections

    def test_group_sections_continues_table_across_pages(self):
        p1 = self._make_page(
            1,
            "Equities (E)\n"
            "INE001A01036  AAA LTD  10  100.00  1,000.00\n"
            "INE002A01018  BBB LTD  20  200.00  4,000.00\n"
            "INE003A01024  CCC LTD  5  150.00  750.00",
        )
        # Page 2 has no anchor but is table-dense — should join page 1's section
        p2 = self._make_page(
            2,
            "INE004A01038  DDD LTD  3  500.00  1,500.00\n"
            "INE005A01030  EEE LTD  7  100.00  700.00\n"
            "INE006A01049  FFF LTD  9  250.00  2,250.00\n"
            "INE007A01015  GGG LTD  2  120.00  240.00",
        )
        secs = cas_sections.group_sections([p1, p2])
        assert len(secs) == 1
        assert secs[0].name == cas_sections.SECTION_EQUITY
        assert secs[0].pages == [1, 2]


class TestReconciler:
    def test_row_within_tolerance_passes(self):
        cas = CASExtraction.model_validate({
            "holdings": {"equities": [
                {"company_name": "X", "num_shares": 10,
                 "market_price_inr": 100, "value_inr": 1000.01},
            ]},
        })
        res = reconcile(cas)
        assert res.ok
        assert res.dirty_sections == []

    def test_row_outside_tolerance_marks_section_dirty(self):
        cas = CASExtraction.model_validate({
            "holdings": {"equities": [
                {"company_name": "X", "num_shares": 10,
                 "market_price_inr": 100, "value_inr": 2000},  # ~100% off
            ]},
        })
        res = reconcile(cas)
        assert not res.ok
        assert "equities" in res.dirty_sections
        assert any("X" in w for w in res.row_warnings)

    def test_missing_fields_skip_check(self):
        cas = CASExtraction.model_validate({
            "holdings": {"equities": [
                {"company_name": "X", "num_shares": None,
                 "market_price_inr": 100, "value_inr": 2000},
            ]},
        })
        res = reconcile(cas)
        # no qty → skipped, not dirty
        assert res.ok

    def test_grand_total_drift_marks_folios_dirty_when_no_row_warnings(self):
        cas = CASExtraction.model_validate({
            "portfolio_summary": {"total_value_inr": 100000},
            "holdings": {"equities": [
                {"company_name": "X", "num_shares": 10,
                 "market_price_inr": 100, "value_inr": 1000},
            ]},
        })
        res = reconcile(cas)
        assert not res.ok
        assert "mutual_fund_folios" in res.dirty_sections


# ── B. Integration test (skipped without API key) ─────────────────────
NSDL_PDF = BACKEND / "tests" / "test_data" / "nsdl" / "priyanka_nsdl.pdf"

_KEY = os.environ.get("OPENAI_API_KEY", "")


@pytest.mark.skipif(
    not (_KEY and _KEY.startswith("sk-") and NSDL_PDF.exists()),
    reason="needs OPENAI_API_KEY and NSDL fixture",
)
def test_hybrid_parses_nsdl_fixture():
    """End-to-end: hybrid parser on the real NSDL fixture should return
    holdings within a reasonable time. Uses asyncio.run so the test stays
    sync for pytest."""
    from services.hybrid_cas_parser import parse_cas_hybrid

    pdf = NSDL_PDF.read_bytes()
    t0 = time.monotonic()
    result = asyncio.run(parse_cas_hybrid(pdf, password=""))
    elapsed = time.monotonic() - t0

    assert result is not None, "hybrid declined the NSDL fixture"
    raw, source = result
    assert source in ("hybrid", "hybrid_blind", "hybrid_cached")
    holdings = raw.get("holdings") or {}
    n = sum(len(v or []) for v in holdings.values())
    # Ground truth has ~35 rows; allow significant slack for OCR drift
    assert n >= 20, f"expected >=20 holdings in NSDL fixture, got {n}"
    # Blind mode (image-only 16-page PDF) needs ~120s cold; per-section
    # mode on text PDFs is much faster. Cache hit (next run) is sub-second.
    cap = 30 if source == "hybrid_cached" else 180
    assert elapsed < cap, f"hybrid ({source}) took {elapsed:.1f}s — too slow"


@pytest.mark.skipif(
    not (_KEY and _KEY.startswith("sk-") and NSDL_PDF.exists()),
    reason="needs OPENAI_API_KEY and NSDL fixture",
)
def test_hybrid_cache_hit_is_fast():
    """Re-running parse on the same PDF should hit the SHA-256 cache
    and return in <2s (Redis lookup only)."""
    from services.hybrid_cas_parser import parse_cas_hybrid

    pdf = NSDL_PDF.read_bytes()
    # Prime the cache
    asyncio.run(parse_cas_hybrid(pdf, password=""))
    # Second call should be fast
    t0 = time.monotonic()
    result = asyncio.run(parse_cas_hybrid(pdf, password=""))
    elapsed = time.monotonic() - t0
    if result is None:
        pytest.skip("first parse declined — nothing to cache")
    raw, source = result
    if source != "hybrid_cached":
        pytest.skip("cache miss — Redis not configured")
    assert elapsed < 2.0, f"cache hit took {elapsed:.2f}s"
