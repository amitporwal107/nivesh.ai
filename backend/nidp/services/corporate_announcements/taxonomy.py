"""BSE announcement category / subcategory taxonomy.

Adopted from the BSE Announcements API suite (docs/bse-announcements-suite) and
then CORRECTED against the live API (bseindia AnnSubCategoryGetData/w), verified
2026-07-15 from the NIDP VM.

Key correction vs the suite: the suite placed "Presentation" and "Earnings Call
Transcript" under the "Result" category — but live BSE files them under
"Company Update" as SUBCATNAME "Investor Presentation" (50 rows/30d) and
"Earnings Call Transcript" (27 rows/30d). Rather than keep guessing subcategory
filter strings (the README's caveat 1), we now sweep each CATEGORY with an EMPTY
subcategory: that returns ALL of the category's filings with SUBCATNAME populated,
so we read the real subcategory off each row. The strCat value must be a real
category name — strCat=-1 returns {} on this endpoint (verified).
"""
from __future__ import annotations

# strCat value for "All" (works on AnnGetData/w, NOT on AnnSubCategoryGetData/w).
ALL_CATEGORIES = "-1"

# Category -> observed subcategories. Reference/priority only — the sweep fetches
# each category with an empty subcategory and reads SUBCATNAME off each row, so
# these lists don't need to be exhaustive. Strings marked "live" are verified.
CATEGORIES: dict[str, list[str]] = {
    "AGM/EGM": ["AGM", "Book Closure / AGM", "Court Convened Meeting", "EGM", "Postal Ballot"],
    "Board Meeting": ["Board Meeting", "Outcome of Board Meeting", "Change in Board Meeting Date"],
    "Company Update": [
        "Acquisition",
        "Amalgamation / Merger",
        "Award of Order / Receipt of Order",   # live (47 rows/5d)
        "Investor Presentation",               # live (50 rows/30d) — RAG corpus
        "Earnings Call Transcript",            # live (27 rows/30d) — RAG corpus
        "Analyst / Investor Meet",             # live (50 rows/30d)
        "Credit Rating",                       # live
        "Press Release / Media Release",       # live
        "Change in Management",                # live
        "Buy Back", "Delisting", "Joint Venture", "New Product",
        "Expansion / Diversification", "Clarification", "Debt Securities",
        "Scheme of Arrangement", "Change in Directors / KMP / Auditor",
        "Disruption of Operations",
    ],
    "Corp. Action": ["Dividend", "Bonus", "Stock Split", "Rights Issue", "Record Date", "Book Closure"],
    "Insider Trading / SAST": ["Insider Trading", "SAST", "Pledge / Revoke"],
    "New Listing": [],
    "Result": ["Financial Results"],           # live (only Financial Results under Result)
    "Integrated Filing": [],
    "Others": [],
}

# Sweep order — most RAG/event-valuable categories first, so the highest-value
# filings (transcripts, presentations, order-wins, results) land first even if a
# later category is throttled.
CATEGORY_ORDER = [
    "Company Update",            # Investor Presentation, Earnings Call Transcript, Award of Order, M&A
    "Result",                    # Financial Results
    "Board Meeting",
    "Corp. Action",
    "AGM/EGM",
    "Insider Trading / SAST",
    "New Listing",
    "Integrated Filing",
    "Others",
]

# High-value subcategories our copilot feed prioritises (SUBCATNAME values, live-checked).
HIGH_PRIORITY_SUBCATEGORIES = {
    "Award of Order / Receipt of Order",
    "Acquisition",
    "Amalgamation / Merger",
    "Joint Venture",
    "Financial Results",
    "Earnings Call Transcript",
    "Investor Presentation",
    "Analyst / Investor Meet",
    "Credit Rating",
    "Buy Back",
    "Bonus",
}

# OUR mapping: filing SUBCATNAME -> corpus doc_type for the document_parser.
# Anything not listed defaults to "announcement_attachment". These two strings
# are the live BSE SUBCATNAME values (verified) — this is what makes transcripts
# and presentations first-class RAG documents.
SUBCATEGORY_DOC_TYPE: dict[str, str] = {
    "Earnings Call Transcript": "concall_transcript",
    "Investor Presentation": "investor_presentation",
}


def validate_category(category: str) -> None:
    if category != ALL_CATEGORIES and category not in CATEGORIES:
        raise ValueError(
            f"Unknown category {category!r}. Known: {list(CATEGORIES)} or '-1' for all."
        )


def iter_slices(priority_first: bool = True):
    """Yield (category, subcategory) pairs for the sweep.

    Design: one pass per CATEGORY with an EMPTY subcategory. BSE returns every
    filing in that category with SUBCATNAME populated, so the parser reads the
    real subcategory off each row — no guessing filter strings. Ordered by
    CATEGORY_ORDER when priority_first.
    """
    cats = list(CATEGORIES.keys())
    if priority_first:
        cats.sort(key=lambda c: CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else 99)
    return [(c, "") for c in cats]


def doc_type_for_subcategory(subcategory: str | None) -> str:
    """Corpus doc_type for a filing's BSE subcategory (default: attachment)."""
    return SUBCATEGORY_DOC_TYPE.get((subcategory or "").strip(), "announcement_attachment")
