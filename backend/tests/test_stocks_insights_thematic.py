"""Thematic (cross-company) filings for the /research copilot.

Root cause of "the order filings in my data are headline-only, with no company name, value or
customer": the thematic path searched the filings feed with the WHOLE question as a text match,
found nothing, fell back to the events search, and handed the model lines carrying only the
exchange's subject ("Awarding of order(s)/contract(s)") and a date.

These tests cover the fix: a question about a kind of event is fetched by that event category and
its time window, every line names the company, and the corporate-event AI insight (what happened,
the amount, the counterparty) is attached when one exists. Pure functions and stubs, no network.
"""
from __future__ import annotations

import asyncio

import pytest

from services.copilot_tools import stocks_insights as si

ASK = "Rank the order wins in the last 14 days by value, sector and counterparty (govt/PSU/private)"


# ── what the question is about ──────────────────────────────────────────────
@pytest.mark.parametrize("text,expected", [
    (ASK, "orders"),
    ("Which companies won their largest-ever order this year?", "orders"),
    ("Biggest order wins this fortnight — by value, sector, and counterparty (govt/PSU/private)", "orders"),
    ("Which smallcaps entered new export markets or won first international orders?", "orders"),
    ("Companies whose order book grew fastest per their own concall disclosures", "orders"),
    ("In what order should I read these filings?", None),
    ("Which companies announced acquisitions or mergers this month?", "mna"),
    ("Who raised money via QIP or preferential issue recently?", "qip"),
    ("Any share buybacks announced this week?", "buyback"),
    ("Major capacity expansions or new-plant announcements this quarter", "capex"),
    ("Which companies got a credit rating upgrade?", "rating"),
    ("CFO resignations in the last fortnight", "management"),
    ("Companies that declared a dividend this week", "dividend"),
    ("Which companies flagged margin pressure in their concalls?", None),
])
def test_theme_category(text, expected):
    """TC-T1: a question about a kind of event maps to the filings table's category; a question
    about commentary (not an event) maps to none and keeps the old path."""
    assert si._theme_category(text) == expected


@pytest.mark.parametrize("text,expected", [
    (ASK, 14), ("order wins in the past 3 weeks", 21), ("in the last fortnight", 14),
    ("this week", 7), ("today", 1), ("last 90 days", 30), ("last 2 months", 30), ("order wins", 30),
])
def test_window_days(text, expected):
    """TC-T2: the window comes from the question and never exceeds the feed's 30-day maximum."""
    assert si._window_days(text) == expected


# ── what the model is shown ─────────────────────────────────────────────────
def _row(**kw):
    r = {"id": "a1", "title": "Bagging/Receiving of orders/contracts", "company": "Ircon International Limited",
         "symbol": "IRCON", "category": "Orders", "impact": "high", "when": "2026-10-12T10:00:00+00:00",
         "summary": "Ircon International Limited has informed the Exchange about Bagging/Receiving of orders/contracts"}
    r.update(kw)
    return r


def test_event_keeps_the_company():
    """TC-T3: the company name survives shaping (it used to be dropped)."""
    assert si._shape_event(_row())["company"] == "Ircon International Limited"


def test_context_line_names_the_company_and_prefers_the_insight():
    """TC-T4: each filing line carries company, ticker and impact; the AI insight and its headline
    figure replace the exchange's boilerplate summary when present."""
    ev = si._shape_event(_row())
    plain = si.StocksInsightsResult(ok=True, summary="s", mode="thematic", events=[dict(ev)]).as_llm_context()
    assert "Ircon International Limited (IRCON)" in plain and "impact high" in plain
    assert "has informed the Exchange" in plain
    ev.update(insight="Ircon received a Letter of Acceptance from East Central Railway worth about Rs 862.46 crore.",
              metric="Order value: 862.46 ₹ cr")
    rich = si.StocksInsightsResult(ok=True, summary="s", mode="thematic", events=[ev]).as_llm_context()
    assert "East Central Railway" in rich and "Order value: 862.46 ₹ cr" in rich
    assert "has informed the Exchange" not in rich


# ── how the filings are fetched ─────────────────────────────────────────────
class _Daas:
    def __init__(self, articles=None):
        self.calls, self.articles = [], articles if articles is not None else [_row()]

    async def get_market_pulse_articles(self, **kw):
        self.calls.append(("articles", kw))
        return {"articles": self.articles}

    async def _get(self, path, params=None):
        self.calls.append((path, params))
        return {}


def test_event_question_is_fetched_by_category_and_window(monkeypatch):
    """TC-T5: an event question asks the feed for that category, in the stated window, most
    material first — not for filings whose text contains the whole question."""
    d = _Daas()
    monkeypatch.setattr(si, "daas_client", d)
    events = asyncio.run(si._fetch_filings(ASK, 8, ticker=False))
    name, kw = d.calls[0]
    assert name == "articles" and kw["category"] == "orders" and kw["days"] == 14 and kw["sort"] == "material"
    assert "q" not in kw and kw["limit"] >= 15
    assert events and events[0]["company"] == "Ircon International Limited"


def test_commentary_question_keeps_the_text_search(monkeypatch):
    """TC-T6: a question that names no event category still searches by text, as before."""
    d = _Daas()
    monkeypatch.setattr(si, "daas_client", d)
    asyncio.run(si._fetch_filings("who flagged margin pressure", 8, ticker=False))
    assert d.calls[0][1].get("q") == "who flagged margin pressure" and "category" not in d.calls[0][1]


def test_empty_category_result_falls_back_to_text_search(monkeypatch):
    """TC-T7: no filings in that category and window is not the end — the text search still runs."""
    d = _Daas(articles=[])
    monkeypatch.setattr(si, "daas_client", d)
    asyncio.run(si._fetch_filings(ASK, 8, ticker=False))
    assert [c[1].get("category") for c in d.calls if c[0] == "articles"] == ["orders", None]


# ── insights ────────────────────────────────────────────────────────────────
def test_insights_are_attached_and_a_lookup_failure_is_harmless():
    """TC-T8: a filing with a stored AI insight gets its one-liner and headline figure; a filing
    without one is untouched; a failing lookup leaves every filing as it was."""
    events = [si._shape_event(_row()), si._shape_event(_row(id="b2", company="Other Ltd"))]

    async def found(ids):
        assert ids == ["a1", "b2"]
        return {"a1": {"one": "LoA worth Rs 862.46 crore from East Central Railway.",
                       "metric": {"label": "Order value", "value": "862.46", "unit": "₹ cr"}}}

    out = asyncio.run(si._attach_insights([dict(e) for e in events], lookup=found))
    assert out[0]["insight"].startswith("LoA worth") and out[0]["metric"] == "Order value: 862.46 ₹ cr"
    assert "insight" not in out[1]

    async def broken(ids):
        raise RuntimeError("mongo down")

    assert asyncio.run(si._attach_insights([dict(e) for e in events], lookup=broken)) == events
