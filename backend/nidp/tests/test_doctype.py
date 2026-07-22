"""Unit tests for the content-based filing doc_type classifier.

Pure functions, no network/DB — these lock in the behaviour that makes concall
transcripts / investor presentations / annual reports first-class corpus docs
instead of generic 'announcement_attachment'.

The negative cases matter as much as the positive ones: an *intimation* of an
upcoming earnings call is NOT a transcript, and a subcategory hint must never be
strong enough to type a document on its own.
"""
from __future__ import annotations

import pytest

from nidp.services.corporate_announcements.doctype import (
    FALLBACK,
    THRESHOLD,
    SUBCATEGORY_HINTS,
    classify,
)


@pytest.mark.parametrize(
    "name, kwargs, expected",
    [
        (
            "transcript with an explicit title",
            dict(first_page_text="Earnings Call Transcript\nTCS Q1 FY27",
                 headline="Transcript of earnings call"),
            "concall_transcript",
        ),
        (
            # Real-world shape: the headline is a generic Reg-30 intimation and the
            # transcript itself only reveals itself in the body.
            "generic Reg-30 headline but page 1 is the transcript body",
            dict(headline="Intimation under Regulation 30 of SEBI LODR",
                 first_page_text="Moderator: Ladies and gentlemen, good day and welcome to "
                                 "the Q1 FY27 earnings conference call of the company."),
            "concall_transcript",
        ),
        (
            "investor presentation",
            dict(first_page_text="Investor Presentation Q1 FY27",
                 headline="Investor Presentation", subcategory="Investor Presentation"),
            "investor_presentation",
        ),
        (
            "earnings deck with no subcategory",
            dict(first_page_text="Earnings Presentation\nQuarterly performance highlights"),
            "investor_presentation",
        ),
        (
            "annual report cover",
            dict(first_page_text="Integrated Annual Report 2025-26",
                 headline="Annual Report for the year 2025-26",
                 subcategory="Reg. 34 (1) Annual Report"),
            "annual_report",
        ),
        (
            "Reg-33 financial results statement",
            dict(first_page_text="Unaudited Standalone Financial Results for the quarter "
                                 "ended 30 June 2026\nLimited Review Report",
                 headline="Financial Results", subcategory="Financial Results"),
            "financial_results",
        ),
        (
            "press release",
            dict(first_page_text="Press Release\nCompany wins large order",
                 headline="Press Release / Media Release",
                 subcategory="Press Release / Media Release"),
            "press_release",
        ),
    ],
)
def test_positive_classification(name, kwargs, expected):
    doc_type, score, _ = classify(**kwargs)
    assert doc_type == expected, f"{name}: got {doc_type} (score {score})"
    assert score >= THRESHOLD


@pytest.mark.parametrize(
    "name, kwargs",
    [
        (
            # A notice ABOUT a meet is not a transcript of one.
            "analyst-meet intimation is a notice, not a transcript",
            dict(headline="Intimation of Analyst / Investor Meet under Reg 30",
                 first_page_text="This is to inform that the company will hold an analyst "
                                 "and investor meet on 20 July 2026 at 3 PM.",
                 subcategory="Analyst / Investor Meet"),
        ),
        (
            # Regression guard: 'earnings conference call' appears in BOTH a real
            # transcript and a pre-intimation about one. Only the transcript has a
            # hard tell (moderator/transcript), so the intimation must stay untyped.
            "pre-intimation of an upcoming concall stays untyped",
            dict(headline="Intimation of Earnings Conference Call",
                 first_page_text="Notice is hereby given that the company will host an "
                                 "earnings conference call on 25 July 2026."),
        ),
        (
            "order-win PDF stays untyped",
            dict(headline="Award of Order / Receipt of Order",
                 first_page_text="The company has received an order worth Rs 500 crore.",
                 subcategory="Award of Order / Receipt of Order"),
        ),
        (
            "trading-window closure stays untyped",
            dict(headline="Closure of Trading Window",
                 first_page_text="Notice of closure of trading window for the quarter."),
        ),
        (
            "no signal at all",
            dict(),
        ),
    ],
)
def test_negative_classification(name, kwargs):
    doc_type, _, _ = classify(**kwargs)
    assert doc_type == FALLBACK, f"{name}: got {doc_type}"


@pytest.mark.parametrize("subcategory", sorted(SUBCATEGORY_HINTS))
def test_subcategory_hint_alone_never_types_a_document(subcategory):
    """Design invariant: BSE subcategories are self-reported and inconsistent, so a
    hint may only tip a decision the content already supports — never decide it."""
    doc_type, score, _ = classify(subcategory=subcategory)
    assert doc_type == FALLBACK
    assert score < THRESHOLD


def test_first_page_outweighs_a_conflicting_headline():
    """Content is the strongest signal: a deck filed under a vague headline is still
    a deck (first-page hits are weighted 2x headline)."""
    doc_type, _, _ = classify(headline="Submission under Regulation 30",
                              first_page_text="Investor Presentation Q1 FY27")
    assert doc_type == "investor_presentation"
