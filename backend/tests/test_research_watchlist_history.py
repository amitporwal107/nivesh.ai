"""Research Watchlist — dated lists (the page's historical view).

Covers TC-5..TC-9 of test_reports/research_watchlist_history_*.md plus the
route's date handling, against an in-memory stand-in for the Mongo collection
(the store only uses find / find_one / update_one / update_many / distinct).
"""
from __future__ import annotations

import asyncio
import itertools
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException

from routes import research_watchlist as route
from services import research_watchlist_store as store


def _matches(doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
    for key, cond in query.items():
        if isinstance(cond, dict) and "$exists" in cond:
            if (key in doc) != cond["$exists"]:
                return False
        elif doc.get(key) != cond:
            return False
    return True


class _Cursor:
    def __init__(self, docs: List[Dict[str, Any]], projection):
        self._docs, self._projection = docs, projection or {}

    def sort(self, key: str, direction: int) -> "_Cursor":
        self._docs = sorted(self._docs, key=lambda d: d.get(key), reverse=direction < 0)
        return self

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for d in self._docs:
            yield {k: v for k, v in d.items() if not (k == "_id" and self._projection.get("_id") == 0)}


class _Result:
    def __init__(self, modified_count: int):
        self.modified_count = modified_count


class FakeCollection:
    def __init__(self):
        self.docs: List[Dict[str, Any]] = []
        self._ids = itertools.count(1)

    def find(self, query, projection=None):
        return _Cursor([d for d in self.docs if _matches(d, query)], projection)

    async def find_one(self, query, projection=None):
        return next((dict(d) for d in self.docs if _matches(d, query)), None)

    async def update_one(self, query, update, upsert=False):
        for d in self.docs:
            if _matches(d, query):
                d.update(update["$set"])
                return _Result(1)
        if upsert:
            self.docs.append({"_id": next(self._ids), **query, **update["$set"]})
        return _Result(0)

    async def update_many(self, query, update):
        hit = [d for d in self.docs if _matches(d, query)]
        for d in hit:
            d.update(update["$set"])
        return _Result(len(hit))

    async def distinct(self, key):
        return list({d[key] for d in self.docs if key in d})


@pytest.fixture
def col(monkeypatch):
    fake = FakeCollection()
    monkeypatch.setattr(store, "db", {store.COL: fake})
    return fake


def _research(symbol: str, rank: int, thesis: str) -> Dict[str, Any]:
    return {"symbol": symbol, "company_name": f"{symbol} Ltd", "tier": "high", "rank": rank, "thesis": thesis}


def run(coro):
    return asyncio.run(coro)


async def _seed_two_lists():
    await store.seed_pick(_research("AAA", 1, "old thesis"), list_date="2026-10-06", published_price=100.0, published_date="2026-10-06")
    await store.seed_pick(_research("BBB", 2, "old only"), list_date="2026-10-06", published_price=50.0, published_date="2026-10-06")
    await store.seed_pick(_research("AAA", 2, "new thesis"), list_date="2026-10-12", published_price=120.0, published_date="2026-10-12")
    await store.seed_pick(_research("CCC", 1, "new only"), list_date="2026-10-12", published_price=10.0, published_date="2026-10-12")


# TC-5 — a symbol in two lists is two documents; a new list leaves the old one alone.
def test_lists_are_separate_snapshots(col):
    run(_seed_two_lists())
    assert run(store.list_dates()) == [{"list_date": "2026-10-12", "count": 2}, {"list_date": "2026-10-06", "count": 2}]
    old = run(store.list_picks("2026-10-06"))
    new = run(store.list_picks("2026-10-12"))
    assert [(p["symbol"], p["thesis"], p["published_price"]) for p in old] == [("AAA", "old thesis", 100.0), ("BBB", "old only", 50.0)]
    assert [(p["symbol"], p["thesis"], p["published_price"]) for p in new] == [("CCC", "new only", 10.0), ("AAA", "new thesis", 120.0)]
    assert all("_id" not in p for p in old + new)


# TC-6 — re-seeding fixes the text but never resets the price baseline.
def test_reseed_keeps_baseline(col):
    run(_seed_two_lists())
    run(store.seed_pick(_research("AAA", 1, "typo fixed"), list_date="2026-10-06", published_price=999.0, published_date="2026-12-31"))
    pick = run(store.get_pick("2026-10-06", "AAA"))
    assert (pick["thesis"], pick["published_price"], pick["published_date"]) == ("typo fixed", 100.0, "2026-10-06")
    assert run(store.get_pick("2026-10-12", "AAA"))["thesis"] == "new thesis"
    assert len(col.docs) == 4


# TC-7 — only undated (pre-history) documents are stamped, and only once.
def test_backfill_list_date_is_idempotent(col):
    col.docs.extend([{"_id": 901, "symbol": "OLD1", "rank": 1}, {"_id": 902, "symbol": "OLD2", "rank": 2}])
    run(store.seed_pick(_research("NEW", 1, "t"), list_date="2026-10-12", published_price=1.0, published_date="2026-10-12"))
    assert run(store.backfill_list_date("2026-10-06")) == 2
    assert run(store.backfill_list_date("2026-10-06")) == 0
    assert run(store.list_dates()) == [{"list_date": "2026-10-12", "count": 1}, {"list_date": "2026-10-06", "count": 2}]


# TC-8 — the daily refresh reaches every list, each against its own baseline.
def test_price_refresh_updates_every_list(col):
    run(_seed_two_lists())
    run(store.update_current_price("AAA", current_price=132.0, current_price_date="2026-10-13"))
    old, new = run(store.get_pick("2026-10-06", "AAA")), run(store.get_pick("2026-10-12", "AAA"))
    assert (old["current_price"], old["change_since_published_pct"]) == (132.0, 32.0)
    assert (new["current_price"], new["change_since_published_pct"]) == (132.0, 10.0)
    assert (old["published_price"], new["published_price"]) == (100.0, 120.0)
    assert run(store.get_pick("2026-10-06", "BBB"))["current_price"] == 50.0
    run(store.update_current_price("NOPE", current_price=1.0, current_price_date="2026-10-13"))  # unknown: no-op
    assert len(col.docs) == 4


@pytest.fixture
def quotes(monkeypatch):
    asked: List[List[str]] = []

    async def fake_quotes(symbols):
        asked.append(list(symbols))
        return {s: {"price": 200.0, "day_change": 1.0, "day_change_pct": 0.5} for s in symbols}

    monkeypatch.setattr(route.live, "get_live_quotes", fake_quotes)
    return asked


# TC-1 / TC-2 / TC-9 — newest by default, an older list on request, quotes for all lists' symbols.
def test_route_serves_newest_then_requested_list(col, quotes):
    from datetime import date

    run(_seed_two_lists())
    latest = run(route.get_research_watchlist(list_date=None))
    assert latest["meta"]["list_date"] == "2026-10-12"
    assert latest["meta"]["available_dates"] == [{"list_date": "2026-10-12", "count": 2}, {"list_date": "2026-10-06", "count": 2}]
    assert [p["symbol"] for p in latest["items"]] == ["CCC", "AAA"]
    assert {p["list_date"] for p in latest["items"]} == {"2026-10-12"}

    older = run(route.get_research_watchlist(list_date=date(2026, 10, 6)))
    assert older["meta"]["list_date"] == "2026-10-06" and older["meta"]["count"] == 2
    assert [p["symbol"] for p in older["items"]] == ["AAA", "BBB"]
    assert all(p["is_live"] for p in older["items"])
    assert older["items"][0]["change_since_published_pct"] == 100.0  # 200 vs its own 100 baseline
    assert quotes == [["AAA", "BBB", "CCC"], ["AAA", "BBB", "CCC"]]


# TC-3 — an unknown date is a 404, not an empty list.
def test_route_unknown_date_is_404(col, quotes):
    from datetime import date

    run(_seed_two_lists())
    with pytest.raises(HTTPException) as exc:
        run(route.get_research_watchlist(list_date=date(2020, 1, 1)))
    assert exc.value.status_code == 404 and "2020-01-01" in exc.value.detail


def test_route_empty_collection(col, quotes):
    out = run(route.get_research_watchlist(list_date=None))
    assert out["items"] == [] and out["meta"]["list_date"] is None and out["meta"]["available_dates"] == []
    assert quotes == []
