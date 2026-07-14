"""Suggested-query typeahead for the copilot chat composer.

As the user types, this ranks example queries from the curated Nivesh question
bank (``data/nivesh_question_bank.json``) and returns the top matches so the
composer can offer ready-made question templates to pick and complete. Many
templates carry placeholders ({stock}, {amount}, …) the user fills in after
selecting.

Pure and deterministic — no LLM, no network. The bank is loaded once and cached
(``lru_cache``); ranking is a plain token/substring score so the same input
always yields the same suggestions. Mirrors the ``/chat/instrument-search``
typeahead pattern in routes/chat.py.
"""
from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "nivesh_question_bank.json")

# Shown when the user hasn't typed enough to rank (< 2 chars) — the broadly
# useful starters across sections. Sourced from the bank so the returned shape
# (section/category, has_placeholder) stays consistent.
_DEFAULT_QUERIES = [
    "How is my portfolio doing today?",
    "Is my portfolio too concentrated?",
    "{stock} P/E ratio",
    "{fund} latest NAV",
    "How's Nifty / Sensex doing today?",
    "What did FIIs and DIIs do today?",
    "How much will ₹{amount}/month SIP grow in {n} years?",
    "Best {category} funds right now",
]

_WORD = re.compile(r"[a-z0-9]+")


def _norm(text: str) -> str:
    """Lowercase; turn placeholder braces into spaces so "{stock}" is searchable
    as the token "stock"; drop "/" so "P/E" matches a typed "pe" and "buy/sell"
    collapses to one searchable token. Applied to both the bank text and the
    typed term so they align."""
    return (text or "").replace("{", " ").replace("}", " ").replace("/", "").lower()


@lru_cache(maxsize=1)
def _bank() -> List[Dict[str, str]]:
    """Load + index the question bank once. Dedupes on the example query text.
    Returns [] (degrade gracefully) if the data file is missing or malformed."""
    try:
        with open(_DATA_PATH, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError) as exc:  # noqa: BLE001
        logger.warning("query_suggestions: could not load bank: %s", exc)
        return []
    out: List[Dict[str, str]] = []
    seen: set[str] = set()
    for q in raw.get("questions", []):
        query = (q.get("example_query") or "").strip()
        if not query or query in seen:
            continue
        seen.add(query)
        out.append({
            "query": query,
            "section": q.get("section") or "",
            "category": q.get("category") or "",
            "subcategory": q.get("subcategory") or "",
            # Precomputed search fields.
            "_hay": _norm(query),
            "_meta": _norm(" ".join((
                q.get("section") or "", q.get("category") or "", q.get("subcategory") or "",
            ))),
        })
    return out


def _public(rec: Dict[str, str]) -> Dict[str, Any]:
    """The client-facing shape (drops the private _hay/_meta search fields)."""
    return {
        "query": rec["query"],
        "section": rec["section"],
        "category": rec["category"],
        "subcategory": rec["subcategory"],
        "has_placeholder": "{" in rec["query"],
    }


def _score(rec: Dict[str, str], term_l: str, tokens: List[str]) -> int:
    """Deterministic relevance score for one record against the typed term.

    Whole-term substring of the query phrase dominates (a prefix match more so);
    individual tokens add smaller weights, and a token in the section/category
    metadata counts less than one in the query text itself.
    """
    hay = rec["_hay"]
    meta = rec["_meta"]
    score = 0
    if term_l and term_l in hay:
        score += 100
        if hay.startswith(term_l):
            score += 50
    for tok in tokens:
        if tok in hay:
            score += 10
        elif tok in meta:
            score += 4
    return score


def suggest_queries(q: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Top-N question-bank templates matching ``q``, ranked deterministically.

    For terms shorter than 2 chars (or an empty bank) returns the curated
    starters. Ties break toward the shorter query (more lookup-like) and then the
    original bank order, so results are stable.
    """
    limit = max(1, min(int(limit or 5), 10))
    term = (q or "").strip()
    bank = _bank()

    if len(term) < 2 or not bank:
        by_query = {r["query"]: r for r in bank}
        out: List[Dict[str, Any]] = []
        for dq in _DEFAULT_QUERIES:
            rec = by_query.get(dq)
            out.append(_public(rec) if rec else {
                "query": dq, "section": "", "category": "", "subcategory": "",
                "has_placeholder": "{" in dq,
            })
            if len(out) >= limit:
                break
        return out

    term_l = _norm(term)
    tokens = [t for t in _WORD.findall(term_l) if len(t) >= 2]
    scored = []
    for idx, rec in enumerate(bank):
        s = _score(rec, term_l, tokens)
        if s > 0:
            # Sort key: score ↓, then shorter query ↑, then earlier bank order ↑.
            scored.append((s, -len(rec["query"]), -idx, rec))
    scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    return [_public(rec) for _, _, _, rec in scored[:limit]]
