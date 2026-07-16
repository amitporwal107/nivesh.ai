"""
Content-based document-type classifier for exchange-filing attachments.

Types a filing from what the document actually SAYS, not from BSE's self-reported
subcategory (companies tag inconsistently, and the subcategory sweep is not even
scheduled). Signals, in descending trust order:
  1. first-page(s) text of the PDF   — strongest; companies title their documents
  2. announcement headline / subject
  3. BSE subcategory (SUBCATNAME)     — a low-weight HINT only; never types alone

Emits the doc_type vocabulary stored in nidp.documents.doc_type:
  concall_transcript | investor_presentation | annual_report |
  financial_results  | press_release        | announcement_attachment (fallback)

Pure functions, no I/O. Wired into document_parser at parse time (service.py,
which already extracts page text with pypdf) and reused by the backfill script.

Adapted from the user-supplied doc-type fix pack. NIDP additions: the
intimation negative-guard (a NOTICE of an upcoming call is not a transcript) and
the SUBCATNAME hint strings, both verified live against BSE 2026-07.
"""
from __future__ import annotations

import re

# (doc_type, pattern, weight). classify() multiplies first-page hits by 2 (the
# strongest signal) and headline/filename hits by 1.
_P = [
    # transcripts — strong, distinctive phrases
    ("concall_transcript", r"\btranscript\b", 5),
    ("concall_transcript", r"earnings\s+(conference\s+)?call", 4),
    ("concall_transcript", r"\bcon[\s-]?call\b", 4),
    ("concall_transcript", r"analysts?\s*/?\s*investors?\s+(conference\s+)?call", 3),
    ("concall_transcript", r"\bmoderator\s*:", 5),                 # transcript body tell
    ("concall_transcript", r"ladies\s+and\s+gentlemen.{0,40}welcome", 4),

    # investor presentations
    ("investor_presentation", r"investor\s+presentation", 5),
    ("investor_presentation", r"earnings\s+presentation", 5),
    ("investor_presentation", r"corporate\s+presentation", 4),
    ("investor_presentation", r"(results?|performance)\s+(update\s+)?presentation", 4),
    ("investor_presentation", r"analyst\s+(day|meet)\s+presentation", 4),

    # annual reports
    ("annual_report", r"annual\s+report\s+(20\d{2}|for\s+the)", 5),
    ("annual_report", r"\bintegrated\s+annual\s+report\b", 5),
    ("annual_report", r"notice\s+of\s+.{0,20}annual\s+general\s+meeting", 2),
    ("annual_report", r"business\s+responsibility\s+and\s+sustainability\s+report", 2),

    # financial results
    ("financial_results", r"(unaudited|audited)\s+(standalone|consolidated)?\s*financial\s+results", 5),
    ("financial_results", r"statement\s+of\s+.{0,30}results\s+for\s+the\s+(quarter|year)", 4),
    ("financial_results", r"regulation\s+33", 3),
    ("financial_results", r"limited\s+review\s+report", 3),

    # press releases
    ("press_release", r"press\s+release", 4),
    ("press_release", r"media\s+release", 4),
]
PATTERNS = [(t, re.compile(rx, re.IGNORECASE), w) for t, rx, w in _P]

# Live-verified BSE SUBCATNAME values (AnnSubCategoryGetData/w, 2026-07) -> hint.
# Weights are deliberately < THRESHOLD so a subcategory NEVER types a doc alone;
# it only tips a doc the content already leans toward.
SUBCATEGORY_HINTS = {
    "earnings call transcript": ("concall_transcript", 3),
    "investor presentation": ("investor_presentation", 3),
    "analyst / investor meet": ("concall_transcript", 1),
    "financial results": ("financial_results", 3),
    "reg. 34 (1) annual report": ("annual_report", 3),
    "press release / media release": ("press_release", 3),
}

# A NOTICE about an upcoming call/meet is not the transcript of one. Without this
# guard, "the company will host an earnings conference call" mistypes as a
# transcript. Suppress concall_transcript when an intimation phrase is present
# AND no hard "this IS a transcript" tell (transcript / moderator) appears.
_INTIMATION_RX = re.compile(
    r"\b(prior\s+)?intimation\b|notice\s+is\s+hereby\s+given|"
    r"\bwill\s+(be\s+)?(hold|held|host|conduct|organi[sz]e)\b|"
    r"\bto\s+be\s+held\b|\bis\s+scheduled\b|\bschedule\s+of\b",
    re.IGNORECASE,
)
_TRANSCRIPT_HARD_RX = re.compile(
    r"\btranscript\b|\bmoderator\s*:|ladies\s+and\s+gentlemen", re.IGNORECASE,
)

THRESHOLD = 4                          # min score to leave the fallback type
FALLBACK = "announcement_attachment"


def classify(
    headline: str = "",
    first_page_text: str = "",
    filename: str = "",
    subcategory: str = "",
) -> tuple[str, int, dict[str, int]]:
    """Classify a filing -> (doc_type, confidence_score, all_scores).

    ``first_page_text`` should be the extracted text of page 1 (ideally page 2
    too — a transcript's page 1 is often a cover letter). Every arg is optional;
    the more signals present, the higher the confidence.
    """
    scores: dict[str, int] = {}
    for source_text, mult in ((first_page_text, 2), (headline, 1), (filename, 1)):
        if not source_text:
            continue
        for doc_type, rx, weight in PATTERNS:
            if rx.search(source_text):
                scores[doc_type] = scores.get(doc_type, 0) + weight * mult

    hint = SUBCATEGORY_HINTS.get(subcategory.strip().lower())
    if hint:
        doc_type, weight = hint
        scores[doc_type] = scores.get(doc_type, 0) + weight

    # Negative guard: notice-of-upcoming-call is not a transcript.
    blob = f"{first_page_text}\n{headline}"
    if ("concall_transcript" in scores
            and _INTIMATION_RX.search(blob)
            and not _TRANSCRIPT_HARD_RX.search(blob)):
        del scores["concall_transcript"]

    if not scores:
        return (FALLBACK, 0, scores)
    best_type, best_score = max(scores.items(), key=lambda kv: kv[1])
    if best_score < THRESHOLD:
        return (FALLBACK, best_score, scores)
    return (best_type, best_score, scores)
