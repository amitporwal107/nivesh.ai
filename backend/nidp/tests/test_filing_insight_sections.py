"""filing_insights — section cleaning + citation grounding.

The product claim these tests defend: a citation shown to the user points at a
page that really exists in the filing. A model that invents "pp. 12-14" for an
8-page PDF must lose the citation, not have it rendered.
"""
from __future__ import annotations

import pytest

from nidp.services.filing_insights.generator import (
    _AR_TABS, _GENERIC_TABS, _clean_sections, tabs_for,
)


def _sec(**kw):
    base = {"tab": "Quick Summary", "h": "What the filing says",
            "items": ["Revenue grew 14% YoY."],
            "cite_page_start": None, "cite_page_end": None}
    base.update(kw)
    return base


class TestTabsFor:
    def test_annual_report_gets_the_ar_tab_set(self):
        assert tabs_for("annual_report") == _AR_TABS

    @pytest.mark.parametrize("dt", ["concall_transcript", "financial_results",
                                    "investor_presentation", "press_release", None, ""])
    def test_everything_else_gets_the_generic_set(self, dt):
        assert tabs_for(dt) == _GENERIC_TABS


class TestCitationGrounding:
    def test_in_range_citation_survives(self):
        out = _clean_sections([_sec(cite_page_start=6, cite_page_end=8)],
                              tabs=_GENERIC_TABS, max_page=20)
        assert (out[0]["cite_page_start"], out[0]["cite_page_end"]) == (6, 8)

    def test_citation_past_end_of_document_is_dropped_but_section_kept(self):
        """The bullets were still grounded in the text; only the page pointer is
        unverifiable, so we keep the facts and drop the citation."""
        out = _clean_sections([_sec(cite_page_start=12, cite_page_end=14)],
                              tabs=_GENERIC_TABS, max_page=8)
        assert len(out) == 1
        assert out[0]["items"] == ["Revenue grew 14% YoY."]
        assert out[0]["cite_page_start"] is None
        assert out[0]["cite_page_end"] is None

    def test_page_zero_or_negative_is_dropped(self):
        out = _clean_sections([_sec(cite_page_start=0, cite_page_end=3)],
                              tabs=_GENERIC_TABS, max_page=10)
        assert out[0]["cite_page_start"] is None

    def test_reversed_page_range_is_normalised(self):
        out = _clean_sections([_sec(cite_page_start=9, cite_page_end=4)],
                              tabs=_GENERIC_TABS, max_page=10)
        assert (out[0]["cite_page_start"], out[0]["cite_page_end"]) == (4, 9)

    def test_unknown_max_page_keeps_a_plausible_citation(self):
        """max_page is None when chunks carry no page metadata — we can't refute
        the citation, so we don't silently delete it."""
        out = _clean_sections([_sec(cite_page_start=5, cite_page_end=6)],
                              tabs=_GENERIC_TABS, max_page=None)
        assert out[0]["cite_page_start"] == 5

    def test_non_numeric_citation_is_dropped_not_crashed(self):
        out = _clean_sections([_sec(cite_page_start="six", cite_page_end="eight")],
                              tabs=_GENERIC_TABS, max_page=20)
        assert out[0]["cite_page_start"] is None


class TestSectionValidity:
    def test_unknown_tab_is_discarded(self):
        """A generic-tab section must not leak into an annual-report panel."""
        out = _clean_sections([_sec(tab="Potential Risks")],
                              tabs=_AR_TABS, max_page=10)
        assert out == []

    def test_tab_matching_is_case_insensitive_and_canonicalised(self):
        out = _clean_sections([_sec(tab="quick summary")],
                              tabs=_GENERIC_TABS, max_page=10)
        assert out[0]["tab"] == "Quick Summary"

    def test_section_with_no_items_is_discarded(self):
        assert _clean_sections([_sec(items=[])], tabs=_GENERIC_TABS, max_page=10) == []

    def test_section_with_only_blank_items_is_discarded(self):
        assert _clean_sections([_sec(items=["", "   "])],
                               tabs=_GENERIC_TABS, max_page=10) == []

    def test_section_with_no_heading_is_discarded(self):
        assert _clean_sections([_sec(h="  ")], tabs=_GENERIC_TABS, max_page=10) == []

    def test_items_are_capped_at_four(self):
        out = _clean_sections([_sec(items=[f"fact {i}" for i in range(9)])],
                              tabs=_GENERIC_TABS, max_page=10)
        assert len(out[0]["items"]) == 4

    @pytest.mark.parametrize("raw", [None, [], "not a list", [None], ["str"], [123]])
    def test_malformed_payloads_yield_no_sections(self, raw):
        assert _clean_sections(raw, tabs=_GENERIC_TABS, max_page=10) == []
