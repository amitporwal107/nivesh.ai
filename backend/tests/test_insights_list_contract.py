"""GET /api/insights contract (audit of 30 Oct: Home's insight cards were dead).

The route answers a BARE LIST of the saved insights (routes/insights.py get_insights); the legacy app reads it as a list
(frontend/src/v3/adapters/insights.js), and the v5 adapter now reads that list as `insights`
(frontend-v5/src/services/adapters/insights.adapter.ts). Before, the v5 contract wanted `{insights: [...]}` and threw.

The body is built by the REAL routes: POST /api/insights/generate (the deterministic rules) saves the insights, then
GET /api/insights reads them back, on an in-memory Mongo. It is compared with the shared fixture
frontend-v5/e2e/fixtures/contract-insights-list.json, which copilot-app.spec.ts TC-CP4 renders on Home.

Writing the fixture: CONTRACT_FIXTURES_OUT=<dir> python -m pytest tests/test_insights_list_contract.py -q

MOCK — not real data: the holdings are invented; no network.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from routes import insights as route
from services import rules_config

FIXTURE = Path(__file__).resolve().parents[2] / "frontend-v5" / "e2e" / "fixtures" / "contract-insights-list.json"
STAMP = "2026-10-30T12:00:00+00:00"
HOLDINGS = [   # MOCK: one AMC, regular plans, no debt — enough for the rules to fire
    {"user_id": "u1", "name": "HDFC Flexi Cap Fund - Regular Plan - Growth", "asset_type": "mutual_fund",
     "quantity": 1000, "current_price": 900.0, "buy_price": 700.0, "sector": None},
    {"user_id": "u1", "name": "HDFC Mid-Cap Opportunities Fund - Regular Plan - Growth", "asset_type": "mutual_fund",
     "quantity": 2000, "current_price": 150.0, "buy_price": 120.0, "sector": None},
    {"user_id": "u1", "name": "HDFC Small Cap Fund - Regular Plan - Growth", "asset_type": "mutual_fund",
     "quantity": 1500, "current_price": 120.0, "buy_price": 100.0, "sector": None},
]


class _Cursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def sort(self, key, direction):
        self.docs.sort(key=lambda d: d.get(key) or "", reverse=direction < 0)
        return self

    async def to_list(self, n):
        return [dict(d) for d in self.docs[:n]]

    def __aiter__(self):
        async def gen():
            for d in self.docs:
                yield dict(d)
        return gen()


class _Coll:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find(self, query=None, projection=None):
        q = query or {}
        return _Cursor(d for d in self.docs if all(d.get(k) == v for k, v in q.items()))

    async def find_one(self, *_a, **_k):
        return None

    async def insert_one(self, doc):
        self.docs.append(dict(doc))

    async def delete_many(self, query):
        self.docs = [d for d in self.docs if not all(d.get(k) == v for k, v in query.items())]


class _Db:
    def __init__(self):
        self.holdings = _Coll(HOLDINGS)
        self.ai_insights, self.insight_completions = _Coll(), _Coll()
        self.portfolio_analysis_deep, self.allocation_analysis_cache, self.portfolio_analysis = _Coll(), _Coll(), _Coll()


class _Req:
    pass


def build_body(monkeypatch) -> list:
    db = _Db()
    monkeypatch.setattr(route, "db", db)

    async def user(_request):
        return {"user_id": "u1"}

    async def config(refresh=False):
        return rules_config.DEFAULTS

    async def no_intelligence(_uid):
        raise RuntimeError("MOCK: portfolio intelligence not used in this contract")
    monkeypatch.setattr(route, "get_current_user", user)
    monkeypatch.setattr(rules_config, "get_config", config)
    import services.portfolio_intelligence as pi
    monkeypatch.setattr(pi, "compute_portfolio_intelligence", no_intelligence)

    asyncio.run(route.generate_insights(_Req()))
    for d in db.ai_insights.docs:
        d["created_at"] = STAMP
    return asyncio.run(route.get_insights(_Req()))


@pytest.mark.skipif(not os.environ.get("CONTRACT_FIXTURES_OUT"), reason="writes the fixture only when asked")
def test_write_the_fixture(monkeypatch):
    out = Path(os.environ["CONTRACT_FIXTURES_OUT"]) / FIXTURE.name
    out.write_text(json.dumps(build_body(monkeypatch), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def test_get_insights_answers_a_bare_list_of_saved_insights(monkeypatch):
    body = build_body(monkeypatch)
    assert isinstance(body, list) and len(body) >= 2                 # the legacy app and the v5 adapter read a list
    for item in body:                                                 # what the v5 item contract (InsightItemC) needs
        assert isinstance(item["insight_id"], str) and item["insight_id"]
        assert isinstance(item["title"], str) and item["title"]
        assert isinstance(item["category"], str) and isinstance(item["severity"], str)
        assert isinstance(item.get("description", ""), str)


def test_the_shared_fixture_is_what_the_routes_return(monkeypatch):
    assert FIXTURE.exists(), f"{FIXTURE} is the shared browser/route contract fixture and must be present"
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == json.loads(json.dumps(build_body(monkeypatch)))
