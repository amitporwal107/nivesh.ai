"""Resolve a mutual-fund NAME in free text to an AMFI scheme_code.

The copilot's intent node only extracts a literal 6-digit AMFI code; the MF card
prompts ("Show the holdings of HDFC Balanced Advantage Fund") carry the fund by
name. This module is the MF analogue of `symbol_resolver` for stocks:

  extract_scheme_query(text) -> str        pure phrase extractor (testable)
  resolve_scheme(text)       -> SchemeMatch | None   (async; calls DaaS search)

Resolution rules:
  * A 6-digit code in the text always wins (no network needed).
  * Otherwise the fund-name phrase is extracted and matched via DaaS
    GET /mf/schemes?q=<phrase>; among the hits we prefer the canonical
    Regular-Growth plan over Direct / IDCW / dividend variants.
  * Returns None when nothing resolves — callers must NOT invent a scheme.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from . import daas_client as _daas

logger = logging.getLogger(__name__)

_SIX_DIGIT = re.compile(r"\b(\d{6})\b")

# Leading command clauses to strip ("show the holdings of …", "compare …").
_LEAD = re.compile(
    r"^\s*(?:please\s+)?(?:tell\s+me\s+about|tell\s+me|tell|show|give|get|display|"
    r"pull\s+up|open|view|research|comparison\s+of|compare|about|"
    r"help\s+me\s+(?:start\s+a\s+sip\s+in|with)|start\s+(?:a\s+)?sip\s+in|"
    r"should\s+i\s+(?:pick|invest\s+in)|"
    r"the\s+full\s+(?:overview|analysis)\s+of|full\s+(?:overview|analysis)\s+of|"
    r"what'?s|what\s+is|how\s+is|is)\b",
    re.IGNORECASE,
)
# View / qualifier nouns that bracket the fund name in our templated prompts.
_VIEW_NOUN = re.compile(
    r"\b(?:the\s+)?(?:overview|returns?|holdings?|ratios?|peers?|performance|"
    r"summary|details?|allocation|portfolio|full\s+analysis|analysis|nav|"
    r"direct\s+or\s+regular\s+plan|direct\s+vs\s+regular)\b",
    re.IGNORECASE,
)
# Connectors after which the fund name ends.
_TAIL = re.compile(
    r"\s+(?:with\b|across\b|over\b|and\s+(?:its|what)\b|vs\b|versus\b|"
    r"compared\b|for\s+a\b|in\s+detail\b|across\s+periods\b).*$",
    re.IGNORECASE,
)
# A view/metric clause TRAILING the fund name ("{fund} top holdings", "{fund}
# latest NAV", "{fund} expense ratio"). Anchored to the END and the view noun
# must sit at the tail, so the leading "holdings of {fund}" order (handled below)
# and real names ending in "Fund"/"Index"/"Top 100" are never touched.
_TRAIL_VIEW = re.compile(
    r"\s+(?:(?:top|latest|current|recent|best|worst)\s+|\d+[\s-]?(?:year|yr|y)s?\s+)?"
    r"(?:overview|returns?|holdings?|ratios?|peers?|performance|summary|"
    r"allocation|sector\s+allocation|cap\s+split|portfolio\s+turnover|"
    r"\bnav\b|expense\s+ratio|\baum\b|rating|riskometer|sharpe|sortino|"
    r"\bcagr\b|exit\s+load|top\s+holdings?)"
    r"(?:\s+(?:today|now|please|breakdown|ratio|details?))?\s*$",
    re.IGNORECASE,
)
# Plan/option suffixes that aren't part of the searchable canonical name.
_PLAN_SUFFIX = re.compile(
    r"\s+(?:-\s+)?(?:growth|regular|direct|idcw|dividend|payout|reinvest\w*|"
    r"plan|option)\b.*$",
    re.IGNORECASE,
)
_OF = re.compile(r"\bof\b", re.IGNORECASE)
_STOP_TAIL = re.compile(r"[.?!,:;].*$")
# Generic filler that can sit in front of the fund name once the command verb
# is gone ("the mutual fund HDFC …", "the fund HDFC …", "scheme HDFC …").
# Leading-anchored so the trailing "Fund" in the real name is never stripped.
_FILLER_LEAD = re.compile(
    r"^\s*(?:the\s+|a\s+|an\s+)?(?:mutual\s+funds?|funds?|schemes?|mf)\b\s*",
    re.IGNORECASE,
)

# Common short forms → a searchable substring of the canonical scheme name.
_ALIASES = {
    "hdfc baf": "HDFC Balanced Advantage",
    "icici baf": "ICICI Prudential Balanced Advantage",
    "sbi baf": "SBI Balanced Advantage",
    "ppfas": "Parag Parikh Flexi Cap",
    "pp flexi": "Parag Parikh Flexi Cap",
    "nifty 50 index fund": "Nifty 50 Index",
}


@dataclass
class SchemeMatch:
    scheme_code: str
    scheme_name: str
    isin: Optional[str] = None
    confidence: float = 0.0


def extract_scheme_query(text: str) -> str:
    """Pull the fund-name phrase out of a free-text prompt. Pure / no network.

    "Show the holdings of HDFC Balanced Advantage Fund."        -> "HDFC Balanced Advantage Fund"
    "Compare HDFC Balanced Advantage Fund with its peers."      -> "HDFC Balanced Advantage Fund"
    "Show the overview of HDFC Balanced Advantage Fund Growth." -> "HDFC Balanced Advantage Fund"
    """
    s = (text or "").strip()
    if not s:
        return ""
    low = s.lower()
    for alias, full in _ALIASES.items():
        if alias in low:
            return full

    s = _STOP_TAIL.sub("", s)          # drop trailing punctuation clause
    s = _TAIL.sub("", s)               # drop "with its peers", "across periods", …
    s = _LEAD.sub("", s).strip()       # drop the leading command verb

    # Drop generic "(the) mutual fund / fund / scheme" filler left in front of
    # the real name ("tell me about the mutual fund HDFC Balanced Advantage
    # Fund" -> "HDFC Balanced Advantage Fund"). Leading-anchored and looped so
    # the trailing "Fund" in the actual name is never touched.
    prev = None
    while prev != s:
        prev = s
        s = _FILLER_LEAD.sub("", s).strip()

    # Drop a TRAILING view/metric clause ("{fund} top holdings", "{fund} latest
    # NAV") that the leading-oriented logic below would otherwise miss — the MF
    # node resolves on the whole message, so these intent words ride along.
    s = _TRAIL_VIEW.sub("", s).strip()

    # If a view noun remains (e.g. "the returns of HDFC …"), keep what follows
    # the last "of"; else strip a leading view noun.
    if _VIEW_NOUN.search(s):
        m = list(_OF.finditer(s))
        if m:
            s = s[m[-1].end():].strip()
        else:
            s = _VIEW_NOUN.sub("", s, count=1).strip()

    s = _PLAN_SUFFIX.sub("", s).strip()    # drop "Growth / Direct / Plan" suffix
    s = re.sub(r"\s{2,}", " ", s).strip(" -")
    return s


def _rank(name: str) -> float:
    """Higher = more canonical (Regular Growth) plan."""
    n = name.lower()
    score = 0.0
    if "growth" in n:
        score += 3
    if any(w in n for w in ("idcw", "dividend", "payout", "reinvest", "bonus")):
        score -= 4
    if "direct" in n:
        score -= 2            # prefer the regular plan (mockup figures are regular)
    score -= len(name) / 200  # mild preference for the shorter canonical name
    return score


async def resolve_scheme(text: str) -> Optional[SchemeMatch]:
    """Resolve a fund name (or 6-digit code) in `text` to a SchemeMatch, or None."""
    s = (text or "").strip()
    if not s:
        return None

    m = _SIX_DIGIT.search(s)
    if m:
        return SchemeMatch(scheme_code=m.group(1), scheme_name="", confidence=1.0)

    query = extract_scheme_query(s)
    if len(query) < 4:
        return None

    try:
        rows: List[dict] = await _daas.search_mf_schemes(query, limit=10)
    except Exception as exc:  # noqa: BLE001 — never let resolution break the turn
        logger.debug("resolve_scheme(%r): %s", query[:40], exc)
        return None
    if not rows:
        return None

    best = max(rows, key=lambda r: _rank(str(r.get("scheme_name") or "")))
    code = best.get("scheme_code")
    if not code:
        return None
    return SchemeMatch(
        scheme_code=str(code),
        scheme_name=str(best.get("scheme_name") or ""),
        isin=best.get("isin_growth") or best.get("isin"),
        confidence=0.85,
    )
