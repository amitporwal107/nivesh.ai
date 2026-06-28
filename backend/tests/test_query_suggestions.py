"""Tests for the chat composer's suggested-query typeahead.

`services.query_suggestions` is pure (loads the bundled question bank and ranks
it with no FastAPI/DB/LLM), so it's tested directly at the unit level. A
regression here — broken ranking, lost placeholder flag, non-deterministic
order — would otherwise surface only as bad suggestions in the live composer.
"""
from __future__ import annotations

from services.query_suggestions import suggest_queries


def _queries(rows):
    return [r["query"] for r in rows]


def test_short_term_returns_curated_defaults():
    rows = suggest_queries("", limit=5)
    assert len(rows) == 5
    # Defaults lead with the portfolio overview starter.
    assert rows[0]["query"] == "How is my portfolio doing today?"
    # Single char is still "too short to rank" → defaults.
    assert suggest_queries("p", limit=5)[0]["query"] == "How is my portfolio doing today?"


def test_pe_matches_valuation_queries():
    rows = suggest_queries("pe ratio", limit=5)
    qs = _queries(rows)
    # The exact "P/E ratio" template should surface and rank first (the typed
    # phrase "pe ratio" is a whole-phrase hit once the slash is normalised away).
    assert "{stock} P/E ratio" in qs
    assert qs[0] == "{stock} P/E ratio"


def test_sip_growth_query_surfaces():
    qs = _queries(suggest_queries("sip", limit=5))
    assert any("SIP" in q for q in qs)


def test_placeholder_tokens_are_searchable():
    # "{fund}" must be findable by typing "fund" (braces normalised to spaces).
    qs = _queries(suggest_queries("fund nav", limit=5))
    assert "{fund} latest NAV" in qs


def test_has_placeholder_flag():
    rows = suggest_queries("latest nav", limit=5)
    nav = next(r for r in rows if r["query"] == "{fund} latest NAV")
    assert nav["has_placeholder"] is True
    rows2 = suggest_queries("concentrated", limit=5)
    conc = next(r for r in rows2 if "concentrated" in r["query"].lower())
    assert conc["has_placeholder"] is False


def test_limit_is_honoured_and_clamped():
    assert len(suggest_queries("fund", limit=3)) <= 3
    # Out-of-range limits are clamped to [1, 10].
    assert len(suggest_queries("fund", limit=999)) <= 10
    assert len(suggest_queries("fund", limit=0)) >= 1


def test_results_carry_section_metadata():
    rows = suggest_queries("dividend yield", limit=5)
    assert rows, "expected at least one match for 'dividend yield'"
    top = rows[0]
    assert set(("query", "section", "category", "subcategory", "has_placeholder")) <= set(top)
    assert top["section"]  # non-empty for a real bank row


def test_deterministic_ordering():
    a = suggest_queries("returns vs benchmark", limit=5)
    b = suggest_queries("returns vs benchmark", limit=5)
    assert a == b


def test_no_match_returns_empty():
    # A term with no bank overlap ranks nothing (we don't pad ranked results).
    assert suggest_queries("zzqqxx", limit=5) == []
