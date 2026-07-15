"""BSE announcement category / subcategory taxonomy.

Adopted from the BSE Announcements API suite (docs/bse-announcements-suite). These
strings are passed verbatim to the BSE ``AnnSubCategoryGetData/w`` API's ``strCat``
and ``subcategory`` params and mirror the dropdowns on
https://www.bseindia.com/corporates/ann.html

IMPORTANT (from the suite's README, caveat 1): these strings and field names are
from observation of the live site + community libraries and were NOT verifiable
from the build environment. If a (category, subcategory) slice returns zero rows
unexpectedly, open ann.html, apply the filter, and copy the exact strCat /
subcategory values from the browser's Network tab. Only this file needs editing.

The ``SUBCATEGORY_DOC_TYPE`` map is OURS (not BSE's): it lets the document_parser
tag an attachment's ``doc_type`` from the filing's subcategory, so concall
transcripts and investor presentations become first-class corpus documents
instead of a generic ``announcement_attachment``.
"""
from __future__ import annotations

# strCat value for "All"
ALL_CATEGORIES = "-1"

# Category -> known subcategories (empty list = fetch the category without a
# subcategory filter, i.e. a single "-1" pass).
CATEGORIES: dict[str, list[str]] = {
    "AGM/EGM": [
        "AGM",
        "Book Closure / AGM",
        "Court Convened Meeting",
        "EGM",
        "Postal Ballot",
    ],
    "Board Meeting": [
        "Board Meeting",
        "Outcome of Board Meeting",
        "Change in Board Meeting Date",
    ],
    "Company Update": [
        "Acquisition",
        "Amalgamation / Merger",
        "Award of Order / Receipt of Order",
        "Buy Back",
        "Delisting",
        "Joint Venture",
        "New Product",
        "Expansion / Diversification",
        "Press Release / Media Release",
        "Analyst / Investor Meet",
        "Credit Rating",
        "Clarification",
        "Debt Securities",
        "Scheme of Arrangement",
        "Change in Directors / KMP / Auditor",
        "Disruption of Operations",
    ],
    "Corp. Action": [
        "Dividend",
        "Bonus",
        "Stock Split",
        "Rights Issue",
        "Record Date",
        "Book Closure",
    ],
    "Insider Trading / SAST": [
        "Insider Trading",
        "SAST",
        "Pledge / Revoke",
    ],
    "New Listing": [],
    "Result": [
        "Financial Results",
        "Results Press Release",
        "Presentation",
        "Earnings Call Transcript",
    ],
    "Integrated Filing": [],
    "Others": [],
}

# High-value subcategories our copilot feed prioritises (order wins, M&A, results,
# transcripts, presentations, credit-rating, buyback, bonus). Used to run the
# priority slices first / more often. This is our layer, not BSE's.
HIGH_PRIORITY_SUBCATEGORIES = {
    "Award of Order / Receipt of Order",
    "Acquisition",
    "Amalgamation / Merger",
    "Joint Venture",
    "Financial Results",
    "Earnings Call Transcript",
    "Presentation",
    "Credit Rating",
    "Buy Back",
    "Bonus",
}

# OUR mapping: filing subcategory -> corpus doc_type for the document_parser.
# Anything not listed defaults to "announcement_attachment" (the parser's status
# quo). This is what makes transcripts/presentations first-class RAG documents.
SUBCATEGORY_DOC_TYPE: dict[str, str] = {
    "Earnings Call Transcript": "concall_transcript",
    "Presentation": "investor_presentation",
    # "Results Press Release" / "Financial Results" attachments stay generic —
    # the structured numbers come from the XBRL (nse_financials) feed, and the
    # PDF is just a results deck; keep it searchable as an attachment.
}


def validate_category(category: str) -> None:
    if category != ALL_CATEGORIES and category not in CATEGORIES:
        raise ValueError(
            f"Unknown category {category!r}. Known: {list(CATEGORIES)} or '-1' for all."
        )


def iter_slices(priority_first: bool = True):
    """Yield (category, subcategory) pairs for a full taxonomy sweep.

    Categories with no known subcategories yield a single (category, "-1") pass.
    When priority_first, high-priority subcategories are emitted before the rest
    so the most valuable filings land first even if a later slice is throttled.
    """
    pairs: list[tuple[str, str]] = []
    for category, subcats in CATEGORIES.items():
        if not subcats:
            pairs.append((category, "-1"))
            continue
        for sub in subcats:
            pairs.append((category, sub))
    if priority_first:
        pairs.sort(key=lambda p: p[1] not in HIGH_PRIORITY_SUBCATEGORIES)
    return pairs


def doc_type_for_subcategory(subcategory: str | None) -> str:
    """Corpus doc_type for a filing's BSE subcategory (default: attachment)."""
    return SUBCATEGORY_DOC_TYPE.get((subcategory or "").strip(), "announcement_attachment")
