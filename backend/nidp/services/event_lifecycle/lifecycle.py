"""Corporate-transaction lifecycle: family, stage and transaction grouping.

Pure functions, no I/O — the same contract as bhavcopy/parser.py, so every rule
here is golden-file testable.

One filing is not one transaction. A buyback runs board proposal -> board
approval -> public announcement -> record date -> letter of offer -> post-offer
announcement -> extinguishment, and each step is filed on BOTH exchanges. PRD
v1.1 sec 3/5.1 calls for a persistent transaction_id spanning that; nidp has no
such concept today (repo-wide grep for transaction_id / event_group /
parent_event / deal_id returns nothing).

Every rule below is derived from the real subject vocabulary in
nidp.corporate_announcements over 2026-01-19..2026-09-25, not from a
specification. The exclusions matter as much as the matches — see EXCLUDE_*.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Iterable, Optional

# ── families ─────────────────────────────────────────────────────────
BUYBACK = "BUYBACK"
QIP_PREF = "QIP_PREF"

# A share buyback. NOT a debt buyback: "Buyback Of Commercial Papers" appears
# in the real data and is a money-market operation with no equity effect.
_BUYBACK = re.compile(r"buy[\s-]?back", re.I)
_BUYBACK_NOT_EQUITY = re.compile(
    r"buy[\s-]?back\s+of\s+(commercial\s+paper|ncd|debenture|bond|"
    r"non[\s-]?convertible)", re.I)

_QIP = re.compile(r"qualified\s+institution(al)?\s+(placement|buyer)", re.I)
_PREF = re.compile(r"preferential\s+(issue|allotment|basis)", re.I)

# Filed for YEARS after a raise, every quarter, under Reg 32. Not lifecycle.
_EXCLUDE_DEVIATION = re.compile(
    r"statement\s+of\s+(nil\s+)?deviation|variation\s+in\s+utilisation|"
    r"utilisation\s+of\s+(the\s+)?(issue\s+)?proceeds", re.I)
# Warrants issued preferentially convert over 18 months. Each conversion is its
# own event, not a late stage of the original issue.
_EXCLUDE_WARRANT_CONV = re.compile(
    r"conversion\s+of\s+(share\s+)?warrants|upon\s+conversion\s+of\s+warrants", re.I)


def classify_family(text: str) -> Optional[str]:
    """Which Phase-1 family a filing belongs to, or None.

    None is the right answer for post-issue compliance and warrant conversions:
    they mention the family but are not part of its lifecycle.
    """
    if not text:
        return None
    if _EXCLUDE_DEVIATION.search(text) or _EXCLUDE_WARRANT_CONV.search(text):
        return None
    if _BUYBACK.search(text) and not _BUYBACK_NOT_EQUITY.search(text):
        return BUYBACK
    if _QIP.search(text) or _PREF.search(text):
        return QIP_PREF
    return None


# ── lifecycle stages ─────────────────────────────────────────────────
# Ordered most-specific first; the first match wins, because a subject often
# contains several of these words ("Board Meeting Outcome ... Public
# Announcement"). Order is the whole design here.
_STAGE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("WITHDRAWN",    re.compile(r"withdraw|cancell?ation of (the )?(buy|issue|offer)", re.I)),
    ("COMPLETED",    re.compile(r"extinguishment|certificate of extinguish|"
                                r"completion of (the )?buy|allotment of .*equity shares", re.I)),
    ("OFFER_CLOSED", re.compile(r"post[\s-]?buy[\s-]?back|closure of (the )?(offer|buyback)|"
                                r"offer clos", re.I)),
    ("OFFER_OPEN",   re.compile(r"letter of offer|despatch|dispatch|opening of (the )?(offer|buyback)", re.I)),
    ("RECORD_DATE",  re.compile(r"record date", re.I)),
    ("ANNOUNCED",    re.compile(r"public announcement|corrigendum", re.I)),
    ("APPROVED",     re.compile(r"board meeting outcome|outcome of (the )?(board|meeting)|"
                                r"resolution passed|board resolution|in[\s-]?principle approval|"
                                r"shareholders.{0,20}approv", re.I)),
    ("PROPOSED",     re.compile(r"board meeting intimation|advance intimation|"
                                r"prior intimation|proposal (for|of)", re.I)),
)


def classify_stage(text: str) -> str:
    """Lifecycle stage of one filing. UPDATE when it is clearly in-family but
    carries no stage marker (e.g. NSE's bare subject 'Buyback')."""
    if not text:
        return "UNKNOWN"
    for stage, rx in _STAGE_RULES:
        if rx.search(text):
            return stage
    return "UPDATE"


# Results season bundles announcements: "Consideration And Approval Of The
# Audited Financial Results ... And Proposal For Buyback". PRD sec 7.5 excludes
# these from cohort statistics, so they must be flagged at parse time.
_RESULTS = re.compile(r"financial results|audited results|unaudited results|"
                      r"quarterly results", re.I)


def is_confounded(text: str) -> bool:
    """True when one filing announces the family event AND results together."""
    return bool(text) and bool(_RESULTS.search(text)) and classify_family(text) is not None


# ── transaction grouping ─────────────────────────────────────────────
# Measured gap between consecutive buyback filings for one company over
# 2026-01-19..2026-09-25: 110 gaps of 0-28 days, 7 of 30-49, and a single gap of
# 92 days that separates two distinct buybacks. JSW Energy ran two separate
# preferential/QIP transactions in 2026, Jan 20-21 and May 20-25. So a company
# can and does repeat a family within a year, and a generous-but-finite gap is
# what separates them.
DEFAULT_MAX_GAP_DAYS = 60


def group_transactions(rows: Iterable[dict[str, Any]],
                       max_gap_days: int = DEFAULT_MAX_GAP_DAYS
                       ) -> list[dict[str, Any]]:
    """Assign a per-(symbol, family) transaction ordinal to each filing.

    `rows` need `nse_symbol`, `family` and `filed_on` (a date). A gap longer
    than max_gap_days from the previous filing of the same (symbol, family)
    starts a new transaction. Returns the same dicts with `txn_ordinal` added,
    sorted by (symbol, family, filed_on).

    Deliberately NOT a clustering model: the rule has to be explainable when a
    linking error shows up in a cohort, and it has to be reproducible from the
    filing dates alone.
    """
    out = sorted(rows, key=lambda r: (r["nse_symbol"] or "", r["family"] or "",
                                      r["filed_on"]))
    prev_key: Optional[tuple[str, str]] = None
    prev_date: Optional[date] = None
    ordinal = 0
    for r in out:
        key = (r["nse_symbol"] or "", r["family"] or "")
        if key != prev_key:
            ordinal = 1
        elif prev_date is not None and (r["filed_on"] - prev_date).days > max_gap_days:
            ordinal += 1
        r["txn_ordinal"] = ordinal
        prev_key, prev_date = key, r["filed_on"]
    return out
