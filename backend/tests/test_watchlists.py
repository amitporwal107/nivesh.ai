"""Personal watchlists — /api/watchlists (backend/routes/watchlists.py).

No network and no real database. What is replaced, and by what:

  * `route.db`                 an in-memory stand-in for the two Mongo collections
                               (FakeCollection below: the operators the route uses,
                               with the semantics checked against a real mongod)
  * `route.get_current_user`   reads the test's `X-Test-User` header
  * the symbol master          `daas_client.search_symbols`
  * stored end-of-day prices   `daas_client.get_stock_price_latest`
  * the live-quote service     `live.get_live_quotes`
  * the research watchlist     `research_store.list_dates / list_picks / all_symbols / get_pick`

Everything the route itself does runs for real: validation, ownership, limits,
the starter list and its never-again marker, and how a quote is chosen.

MOCK — not real data: every company, symbol and price here is made up.
"""
from __future__ import annotations

import copy
import itertools
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

from routes import watchlists as route

URL = "/api/watchlists"


# ── an in-memory Mongo collection ────────────────────────────────────────────
def _values_at(doc: Any, path: List[str]) -> List[Any]:
    """Every value a dotted path reaches, the way Mongo walks it: a number picks
    an array element, any other key fans out over an array's elements."""
    if not path:
        return [doc]
    head, rest = path[0], path[1:]
    if isinstance(doc, list):
        if head.isdigit():
            return _values_at(doc[int(head)], rest) if int(head) < len(doc) else []
        return [v for item in doc for v in _values_at(item, path)]
    if isinstance(doc, dict) and head in doc:
        return _values_at(doc[head], rest)
    return []


def _matches(doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
    for key, cond in query.items():
        found = _values_at(doc, key.split("."))
        if isinstance(cond, dict) and "$ne" in cond:
            if any(v == cond["$ne"] for v in found):
                return False
        elif isinstance(cond, dict) and "$nin" in cond:
            if any(v in cond["$nin"] for v in found):
                return False
        elif isinstance(cond, dict) and "$exists" in cond:
            if bool(found) != cond["$exists"]:
                return False
        elif isinstance(cond, dict):
            raise AssertionError(f"the fake collection does not know {cond}")
        elif not any(v == cond for v in found):
            return False
    return True


def _project(doc: Dict[str, Any], projection: Optional[Dict[str, int]]) -> Dict[str, Any]:
    out = copy.deepcopy(doc)
    if projection and projection.get("_id") == 0:
        out.pop("_id", None)
    return out


class _Cursor:
    def __init__(self, docs: List[Dict[str, Any]]):
        self._docs = docs

    def sort(self, key: str, direction: int) -> "_Cursor":
        self._docs = sorted(self._docs, key=lambda d: d.get(key), reverse=direction < 0)
        return self

    async def to_list(self, length: int) -> List[Dict[str, Any]]:
        return self._docs[:length]


class _Update:
    def __init__(self, matched: int, modified: int, upserted_id: Any = None):
        self.matched_count, self.modified_count, self.upserted_id = matched, modified, upserted_id


class _Delete:
    def __init__(self, deleted: int):
        self.deleted_count = deleted


class FakeCollection:
    def __init__(self):
        self.docs: List[Dict[str, Any]] = []
        self.unique: List[List[str]] = [["_id"]]
        self._ids = itertools.count(1)
        self.fail_inserts = False
        self.index_requests = 0

    async def create_index(self, keys, unique: bool = False):
        self.index_requests += 1
        fields = [keys] if isinstance(keys, str) else [k for k, _ in keys]
        if unique and fields not in self.unique:
            self.unique.append(fields)

    def _check_unique(self, candidate: Dict[str, Any], skip: Optional[Dict[str, Any]] = None) -> None:
        for fields in self.unique:
            for other in self.docs:
                if other is not skip and all(f in candidate and other.get(f) == candidate[f] for f in fields):
                    raise DuplicateKeyError(f"E11000 duplicate key: {fields}")

    def find(self, query, projection=None):
        return _Cursor([_project(d, projection) for d in self.docs if _matches(d, query)])

    async def find_one(self, query, projection=None):
        return next((_project(d, projection) for d in self.docs if _matches(d, query)), None)

    async def count_documents(self, query):
        return sum(1 for d in self.docs if _matches(d, query))

    async def insert_one(self, doc):
        if self.fail_inserts:
            raise RuntimeError("the database refused the write")
        doc.setdefault("_id", f"oid{next(self._ids)}")     # motor adds _id to the caller's dict too
        self._check_unique(doc)
        self.docs.append(copy.deepcopy(doc))

    async def update_one(self, query, update, upsert: bool = False):
        unknown = set(update) - {"$set", "$push", "$pull", "$setOnInsert"}
        assert not unknown, f"the fake collection does not know {unknown}"
        for d in self.docs:
            if not _matches(d, query):
                continue
            after = copy.deepcopy(d)
            after.update(copy.deepcopy(update.get("$set", {})))
            for field, value in update.get("$push", {}).items():
                if isinstance(value, dict) and "$each" in value:
                    after.setdefault(field, []).extend(copy.deepcopy(value["$each"]))
                else:
                    after.setdefault(field, []).append(copy.deepcopy(value))
            for field, cond in update.get("$pull", {}).items():
                after[field] = [item for item in after.get(field, []) if not _matches(item, cond)]
            self._check_unique(after, skip=d)
            changed = after != d
            d.clear()
            d.update(after)
            return _Update(1, int(changed))
        if upsert:
            new = {k: v for k, v in query.items() if not isinstance(v, dict)}
            new.update(copy.deepcopy(update.get("$setOnInsert", {})))
            new.update(copy.deepcopy(update.get("$set", {})))
            new.setdefault("_id", f"oid{next(self._ids)}")
            self._check_unique(new)
            self.docs.append(new)
            return _Update(0, 0, new["_id"])
        return _Update(0, 0)

    async def delete_one(self, query):
        for i, d in enumerate(self.docs):
            if _matches(d, query):
                del self.docs[i]
                return _Delete(1)
        return _Delete(0)


class FakeDb:
    def __init__(self):
        self.user_watchlists = FakeCollection()
        self.user_watchlist_state = FakeCollection()

    def __getattr__(self, name: str):
        raise AssertionError(f"the watchlist routes touched db.{name}")


# ── the outside world, as fixtures ───────────────────────────────────────────
# The symbol master: GET /v1/symbols/search rows (nidp.sector_master).
MASTER = {
    "FIXALPHA": "Fixture Alpha Industries Limited",
    "FIXBRAVO": "Fixture Bravo Pharma Limited",
    "FIXCHARLIE": "Fixture Charlie Power Limited",
    "FIX&CO": "Fixture & Company Limited",
    "FIXNONAME": "",
}

# Two published research lists; the newer one is what the starter list copies.
RESEARCH = {
    "2026-10-12": [
        {"symbol": "FIXBRAVO", "company_name": "Fixture Bravo Pharma Ltd", "rank": 2},
        {"symbol": "FIXALPHA", "company_name": "Fixture Alpha Industries Ltd", "rank": 1},
        {"symbol": "FIXRESEARCH", "company_name": "Fixture Research Only Ltd", "rank": 3},
    ],
    "2026-10-05": [{"symbol": "FIXOLD", "company_name": "Fixture Earlier Pick Ltd", "rank": 1}],
}


class World:
    """What the route can reach, and a record of what it asked for."""

    def __init__(self):
        self.db = FakeDb()
        self.master: Optional[Dict[str, str]] = dict(MASTER)      # None = the master does not answer
        self.research: Dict[str, List[Dict[str, Any]]] = copy.deepcopy(RESEARCH)
        self.live: Dict[str, Dict[str, Any]] = {}
        self.live_raises: Optional[Exception] = None
        self.eod: Dict[str, Any] = {}                             # symbol → row, or an Exception to raise
        self.master_calls: List[str] = []
        self.live_calls: List[List[str]] = []
        self.eod_calls: List[str] = []


@pytest.fixture
def world(monkeypatch) -> World:
    w = World()
    monkeypatch.setattr(route, "db", w.db)
    monkeypatch.setattr(route, "_indexes_ready", False)
    monkeypatch.setattr(route, "_STORED", {})

    async def fake_user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(status_code=401, detail="Not authenticated")
        # X-Test-Client stands in for an advisor who has a client open.
        return {"user_id": uid, "_session_user_id": uid, "_active_profile_id": request.headers.get("X-Test-Client")}

    monkeypatch.setattr(route, "get_current_user", fake_user)

    async def search_symbols(q: str, limit: int = 8):
        w.master_calls.append(q)
        if w.master is None:
            return None
        hits = sorted((s for s in w.master if q.upper() in s), key=lambda s: (s != q.upper(), s))
        return {"data": [{"symbol": s, "company_name": w.master[s] or None, "sector": None} for s in hits[:limit]]}

    async def get_stock_price_latest(symbol: str):
        w.eod_calls.append(symbol)
        row = w.eod.get(symbol)
        if isinstance(row, Exception):
            raise row
        return copy.deepcopy(row)

    monkeypatch.setattr(route.daas_client, "search_symbols", search_symbols)
    monkeypatch.setattr(route.daas_client, "get_stock_price_latest", get_stock_price_latest)

    async def get_live_quotes(symbols: List[str]):
        w.live_calls.append(list(symbols))
        if w.live_raises is not None:
            raise w.live_raises
        return copy.deepcopy(w.live)

    monkeypatch.setattr(route.live, "get_live_quotes", get_live_quotes)
    # The moment the live-quote service last filled its batch (its cache's own stamp).
    monkeypatch.setattr(route.live, "_CACHE", {"ts": 1791885000.0, "data": {}})     # 2026-10-13T09:50:00Z

    async def list_dates():
        return [{"list_date": d, "count": len(w.research[d])} for d in sorted(w.research, reverse=True)]

    async def list_picks(list_date: str):
        return sorted(copy.deepcopy(w.research.get(list_date, [])), key=lambda p: p["rank"])

    async def all_symbols():
        return sorted({p["symbol"] for picks in w.research.values() for p in picks})

    async def get_pick(list_date: str, symbol: str):
        return next((copy.deepcopy(p) for p in w.research.get(list_date, []) if p["symbol"] == symbol), None)

    monkeypatch.setattr(route.research_store, "list_dates", list_dates)
    monkeypatch.setattr(route.research_store, "list_picks", list_picks)
    monkeypatch.setattr(route.research_store, "all_symbols", all_symbols)
    monkeypatch.setattr(route.research_store, "get_pick", get_pick)
    return w


@pytest.fixture
def api(world) -> TestClient:
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app)


A = {"X-Test-User": "user_a"}
B = {"X-Test-User": "user_b"}


def _make(api: TestClient, name: str, who: Dict[str, str] = A) -> Dict[str, Any]:
    r = api.post(URL, json={"name": name}, headers=who)
    assert r.status_code == 200, r.text
    return r.json()


def _add(api: TestClient, list_id: str, symbol: str, who: Dict[str, str] = A):
    return api.post(f"{URL}/{list_id}/symbols", json={"symbol": symbol}, headers=who)


def _symbols(api: TestClient, list_id: str, who: Dict[str, str] = A) -> List[str]:
    r = api.get(f"{URL}/{list_id}", headers=who)
    assert r.status_code == 200, r.text
    return [s["symbol"] for s in r.json()["stocks"]]


# ── B1: the list of lists ────────────────────────────────────────────────────
def test_a_new_user_has_no_lists_and_the_starter_is_pending(api, world):
    r = api.get(URL, headers=A)
    assert r.status_code == 200, r.text
    assert r.json() == {"lists": [], "limits": {"max_lists": 20, "max_symbols": 100}, "starter_pending": True}
    assert world.db.user_watchlists.docs == [] and world.db.user_watchlist_state.docs == []   # reading writes nothing


def test_every_route_needs_a_signed_in_user(api):
    calls = [
        ("get", URL, None), ("post", URL, {"name": "x"}), ("post", f"{URL}/starter", None),
        ("get", f"{URL}/wl_x", None), ("patch", f"{URL}/wl_x", {"name": "x"}), ("delete", f"{URL}/wl_x", None),
        ("post", f"{URL}/wl_x/symbols", {"symbol": "FIXALPHA"}), ("delete", f"{URL}/wl_x/symbols/FIXALPHA", None),
    ]
    for method, url, body in calls:
        r = api.request(method, url, json=body) if body is not None else api.request(method, url)
        assert r.status_code == 401, f"{method} {url} → {r.status_code}"


# ── B2–B5: create ────────────────────────────────────────────────────────────
def test_create_trims_the_name_and_lists_it_oldest_first(api, world):
    made = _make(api, "  Banks   to  watch \n")
    assert made["name"] == "Banks to watch"
    assert made["watchlist_id"].startswith("wl_") and made["symbol_count"] == 0
    assert made["is_starter"] is False and made["seeded_from"] is None
    assert made["created_at"] == made["updated_at"] and made["created_at"].endswith("+00:00")
    second = _make(api, "Pharma")
    body = api.get(URL, headers=A).json()
    assert [l["watchlist_id"] for l in body["lists"]] == [made["watchlist_id"], second["watchlist_id"]]
    assert set(body["lists"][0]) == {"watchlist_id", "name", "symbol_count", "is_starter", "seeded_from", "created_at", "updated_at"}
    # Making a list by hand is "having had a list": the example list is no longer offered.
    assert body["starter_pending"] is False
    assert world.db.user_watchlist_state.docs[0]["first_list_via"] == "own_list"


@pytest.mark.parametrize("name", ["", "   ", "\n\t", "x" * 61])
def test_create_refuses_a_name_that_is_empty_or_too_long(api, world, name):
    r = api.post(URL, json={"name": name}, headers=A)
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "A list name needs 1 to 60 characters."
    assert world.db.user_watchlists.docs == []


def test_create_accepts_a_60_character_name_and_refuses_a_missing_one(api):
    assert _make(api, "x" * 60)["name"] == "x" * 60
    assert api.post(URL, json={}, headers=A).status_code == 422
    assert api.post(URL, json={"name": 7}, headers=A).status_code == 422


def test_a_name_is_unique_per_user_whatever_its_case(api, world):
    _make(api, "Energy Picks")
    r = api.post(URL, json={"name": " energy   PICKS "}, headers=A)
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "You already have a list called “Energy Picks”."
    assert len(world.db.user_watchlists.docs) == 1
    assert _make(api, "Energy Picks", B)["name"] == "Energy Picks"      # another user may use the name


def test_two_creates_that_race_on_a_name_end_as_one_list(api, world, monkeypatch):
    """The look-up passes for both; the unique index refuses the second insert."""
    _make(api, "Energy")
    real = world.db.user_watchlists.find_one

    async def sees_nothing(query, projection=None):
        return None if "name_key" in query else await real(query, projection)

    monkeypatch.setattr(world.db.user_watchlists, "find_one", sees_nothing)
    r = api.post(URL, json={"name": "energy"}, headers=A)
    assert r.status_code == 409, r.text
    assert len(world.db.user_watchlists.docs) == 1


def test_at_most_20_lists_per_user(api, world):
    for i in range(20):
        _make(api, f"List {i}")
    r = api.post(URL, json={"name": "One more"}, headers=A)
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "You can keep up to 20 lists. Delete one to make another."
    assert len(world.db.user_watchlists.docs) == 20
    assert _make(api, "One more", B)["name"] == "One more"              # the limit is per user


# ── B6: ownership ────────────────────────────────────────────────────────────
def test_another_users_list_is_not_found_and_is_left_alone(api, world):
    mine = _make(api, "Mine")
    assert _add(api, mine["watchlist_id"], "FIXALPHA").status_code == 200
    before = copy.deepcopy(world.db.user_watchlists.docs)
    wid = mine["watchlist_id"]
    attempts = [
        api.get(f"{URL}/{wid}", headers=B),
        api.patch(f"{URL}/{wid}", json={"name": "Taken"}, headers=B),
        api.delete(f"{URL}/{wid}", headers=B),
        _add(api, wid, "FIXBRAVO", B),
        api.delete(f"{URL}/{wid}/symbols/FIXALPHA", headers=B),
    ]
    for r in attempts:
        assert r.status_code == 404, r.text
        assert r.json()["detail"] == "List not found"
    assert world.db.user_watchlists.docs == before
    assert api.get(URL, headers=B).json()["lists"] == []


def test_a_list_that_does_not_exist_is_not_found(api):
    for r in (api.get(f"{URL}/wl_nope", headers=A), api.patch(f"{URL}/wl_nope", json={"name": "x"}, headers=A),
              api.delete(f"{URL}/wl_nope", headers=A), _add(api, "wl_nope", "FIXALPHA"),
              api.delete(f"{URL}/wl_nope/symbols/FIXALPHA", headers=A)):
        assert r.status_code == 404, r.text


# ── B7–B8: rename, delete ────────────────────────────────────────────────────
def test_rename(api, world):
    one, two = _make(api, "One"), _make(api, "Two")
    r = api.patch(f"{URL}/{one['watchlist_id']}", json={"name": "  First  list "}, headers=A)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "First list" and r.json()["watchlist_id"] == one["watchlist_id"]
    assert r.json()["updated_at"] >= one["updated_at"] and r.json()["created_at"] == one["created_at"]
    # Changing only the case of its own name is allowed; taking another list's name is not.
    assert api.patch(f"{URL}/{one['watchlist_id']}", json={"name": "FIRST LIST"}, headers=A).json()["name"] == "FIRST LIST"
    taken = api.patch(f"{URL}/{one['watchlist_id']}", json={"name": "two"}, headers=A)
    assert taken.status_code == 409 and taken.json()["detail"] == "You already have a list called “Two”."
    bad = api.patch(f"{URL}/{one['watchlist_id']}", json={"name": "   "}, headers=A)
    assert bad.status_code == 422 and bad.json()["detail"] == "A list name needs 1 to 60 characters."
    assert [l["name"] for l in api.get(URL, headers=A).json()["lists"]] == ["FIRST LIST", "Two"]
    assert two["name"] == "Two"


def test_delete_removes_the_list_once(api, world):
    one = _make(api, "One")
    r = api.delete(f"{URL}/{one['watchlist_id']}", headers=A)
    assert r.status_code == 200 and r.json() == {"status": "deleted", "watchlist_id": one["watchlist_id"]}
    assert api.get(URL, headers=A).json()["lists"] == []
    assert api.delete(f"{URL}/{one['watchlist_id']}", headers=A).status_code == 404
    assert _make(api, "One")["name"] == "One"                           # the name is free again


# ── B9–B14: stocks in a list ─────────────────────────────────────────────────
def test_add_checks_the_symbol_master_and_keeps_its_company_name(api, world):
    wid = _make(api, "Mine")["watchlist_id"]
    r = _add(api, wid, "  fixalpha ")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["added"] is True and body["reason"] is None
    assert body["stock"]["symbol"] == "FIXALPHA" and body["stock"]["company_name"] == "Fixture Alpha Industries Limited"
    assert body["watchlist"]["symbol_count"] == 1 and body["watchlist"]["watchlist_id"] == wid
    assert world.master_calls == ["FIXALPHA"]
    assert _add(api, wid, "FIX&CO").json()["stock"]["company_name"] == "Fixture & Company Limited"
    # A master row with no company name: the name is left empty, not invented.
    assert _add(api, wid, "FIXNONAME").json()["stock"]["company_name"] is None
    assert _symbols(api, wid) == ["FIXALPHA", "FIX&CO", "FIXNONAME"]     # in the order they were added


def test_adding_a_stock_twice_is_a_no_op_answer_not_an_error(api, world):
    wid = _make(api, "Mine")["watchlist_id"]
    first = _add(api, wid, "FIXALPHA").json()
    world.master_calls.clear()
    r = _add(api, wid, "fixalpha")
    assert r.status_code == 200, r.text
    assert r.json() == {"added": False, "reason": "already_in_list", "stock": first["stock"], "watchlist": first["watchlist"]}
    assert world.master_calls == []                                      # nothing to check: it is already there
    assert _symbols(api, wid) == ["FIXALPHA"]


def test_a_symbol_the_master_does_not_have_is_refused(api, world):
    wid = _make(api, "Mine")["watchlist_id"]
    r = _add(api, wid, "FIXNOPE")
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "“FIXNOPE” is not a stock in the instrument list."
    # A near match is not a match: FIXALPH is a prefix of a real symbol.
    assert _add(api, wid, "FIXALPH").status_code == 422
    assert _symbols(api, wid) == []


@pytest.mark.parametrize("symbol", ["", "   ", "FIX ALPHA", "FIX/ALPHA", "FIX%", "FIX_A", "$FIX", "A" * 25])
def test_a_malformed_symbol_is_refused_without_asking_the_master(api, world, symbol):
    wid = _make(api, "Mine")["watchlist_id"]
    r = _add(api, wid, symbol)
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "That is not a stock symbol."
    assert world.master_calls == []


def test_when_the_master_does_not_answer_nothing_is_added_unless_research_publishes_the_symbol(api, world):
    wid = _make(api, "Mine")["watchlist_id"]
    world.master = None
    r = _add(api, wid, "FIXALPHX")
    assert r.status_code == 503, r.text
    assert r.json()["detail"] == "The instrument list could not be checked just now, so nothing was added. Please try again."
    assert _symbols(api, wid) == []
    # A stock in a published research list is known to the app without the master.
    ok = _add(api, wid, "FIXOLD")
    assert ok.status_code == 200 and ok.json()["stock"]["company_name"] == "Fixture Earlier Pick Ltd"
    assert _symbols(api, wid) == ["FIXOLD"]


def test_a_research_symbol_the_master_lacks_is_still_accepted(api, world):
    wid = _make(api, "Mine")["watchlist_id"]
    assert "FIXRESEARCH" not in world.master
    r = _add(api, wid, "FIXRESEARCH")
    assert r.status_code == 200 and r.json()["stock"]["company_name"] == "Fixture Research Only Ltd"


def test_at_most_100_stocks_in_a_list(api, world):
    wid = _make(api, "Mine")["watchlist_id"]
    world.master = {f"FIX{i:03d}": f"Fixture {i} Limited" for i in range(101)}
    for i in range(100):
        assert _add(api, wid, f"FIX{i:03d}").status_code == 200
    world.master_calls.clear()
    r = _add(api, wid, "FIX100")
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "A list holds up to 100 stocks. Remove one to add another."
    assert world.master_calls == []
    assert len(_symbols(api, wid)) == 100
    # One already in the full list is still the no-op answer.
    assert _add(api, wid, "FIX007").json()["reason"] == "already_in_list"


def test_two_adds_that_race_cannot_duplicate_a_stock_or_pass_the_limit(api, world, monkeypatch):
    """Both requests read the list before either writes; the write itself is guarded."""
    wid = _make(api, "Mine")["watchlist_id"]
    assert _add(api, wid, "FIXALPHA").status_code == 200
    stale = copy.deepcopy(world.db.user_watchlists.docs[0])
    stale["symbols"] = []
    real = world.db.user_watchlists.find_one
    reads = {"n": 0}

    async def first_read_is_stale(query, projection=None):
        reads["n"] += 1
        return _project(stale, projection) if reads["n"] == 1 else await real(query, projection)

    monkeypatch.setattr(world.db.user_watchlists, "find_one", first_read_is_stale)
    r = _add(api, wid, "FIXALPHA")
    assert r.status_code == 200 and r.json()["added"] is False and r.json()["reason"] == "already_in_list"
    assert [s["symbol"] for s in world.db.user_watchlists.docs[0]["symbols"]] == ["FIXALPHA"]

    world.db.user_watchlists.docs[0]["symbols"] = [{"symbol": f"FIX{i:03d}", "company_name": None, "added_at": "t"} for i in range(100)]
    reads["n"] = 0
    full = _add(api, wid, "FIXBRAVO")
    assert full.status_code == 409 and len(world.db.user_watchlists.docs[0]["symbols"]) == 100


def test_remove_takes_a_stock_out_and_is_a_no_op_when_it_is_not_there(api, world):
    wid = _make(api, "Mine")["watchlist_id"]
    for s in ("FIXALPHA", "FIX&CO", "FIXBRAVO"):
        assert _add(api, wid, s).status_code == 200
    r = api.delete(f"{URL}/{wid}/symbols/FIX%26CO", headers=A)            # "&" travels percent-encoded
    assert r.status_code == 200, r.text
    assert r.json()["removed"] is True and r.json()["symbol"] == "FIX&CO" and r.json()["watchlist"]["symbol_count"] == 2
    assert _symbols(api, wid) == ["FIXALPHA", "FIXBRAVO"]
    again = api.delete(f"{URL}/{wid}/symbols/fix%26co", headers=A)
    assert again.status_code == 200 and again.json()["removed"] is False and again.json()["watchlist"]["symbol_count"] == 2
    assert api.delete(f"{URL}/{wid}/symbols/FIX%20X", headers=A).status_code == 422
    assert _symbols(api, wid) == ["FIXALPHA", "FIXBRAVO"]


# ── B15: quotes ──────────────────────────────────────────────────────────────
def _stocks(api: TestClient, wid: str) -> Dict[str, Any]:
    r = api.get(f"{URL}/{wid}", headers=A)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_quote_is_live_or_stored_or_absent_and_never_zero(api, world):
    wid = _make(api, "Mine")["watchlist_id"]
    for s in ("FIXALPHA", "FIXBRAVO", "FIXCHARLIE", "FIX&CO", "FIXNONAME"):
        assert _add(api, wid, s).status_code == 200
    # Alpha: in the live batch. Bravo: in the batch with no price. Charlie, FIX&CO: stored
    # end-of-day rows (the second without a previous close). FIXNONAME: nothing anywhere.
    world.live = {
        "FIXALPHA": {"price": 213.0, "prev_close": 210.5, "day_change": 2.5, "day_change_pct": 1.19},
        "FIXBRAVO": {"price": None, "prev_close": None, "day_change": None, "day_change_pct": None},
    }
    world.eod = {
        "FIXBRAVO": {"as_of_date": "2026-10-12", "symbol": "FIXBRAVO", "close_price": 480.0, "prev_close": 486.0},
        "FIXCHARLIE": {"as_of_date": "2026-10-10", "symbol": "FIXCHARLIE", "close_price": "75.40", "prev_close": "74.90"},
        "FIX&CO": {"as_of_date": "2026-10-12", "symbol": "FIX&CO", "close_price": 12.5, "prev_close": None},
        "FIXNONAME": None,
    }
    body = _stocks(api, wid)
    quotes = {s["symbol"]: s["quote"] for s in body["stocks"]}
    assert quotes["FIXALPHA"] == {"price": 213.0, "day_change": 2.5, "day_change_pct": 1.19, "as_of": "2026-10-13T09:50:00+00:00", "is_live": True}
    assert quotes["FIXBRAVO"] == {"price": 480.0, "day_change": -6.0, "day_change_pct": -1.23, "as_of": "2026-10-12", "is_live": False}
    assert quotes["FIXCHARLIE"] == {"price": 75.4, "day_change": 0.5, "day_change_pct": 0.67, "as_of": "2026-10-10", "is_live": False}
    assert quotes["FIX&CO"] == {"price": 12.5, "day_change": None, "day_change_pct": None, "as_of": "2026-10-12", "is_live": False}
    assert quotes["FIXNONAME"] is None
    assert body["quotes"] == {"live": 1, "stored": 3, "none": 1, "live_source": "yahoo_finance", "stored_source": "nidp.prices_eod"}
    assert body["symbol_count"] == 5 and body["name"] == "Mine"
    assert [s["company_name"] for s in body["stocks"]][:2] == ["Fixture Alpha Industries Limited", "Fixture Bravo Pharma Limited"]
    # Stored prices are looked up only for the stocks the live batch did not price.
    assert sorted(world.eod_calls) == ["FIX&CO", "FIXBRAVO", "FIXCHARLIE", "FIXNONAME"]


def test_the_live_service_is_asked_for_the_research_symbols_never_for_one_users_list(api, world):
    """Its cache holds one batch for every caller: asking for a user's own symbols
    would replace the batch the research watchlist page reads."""
    wid = _make(api, "Mine")["watchlist_id"]
    assert _add(api, wid, "FIXCHARLIE").status_code == 200
    _stocks(api, wid)
    assert world.live_calls == [["FIXALPHA", "FIXBRAVO", "FIXOLD", "FIXRESEARCH"]]


@pytest.mark.parametrize("bad_close", [0, 0.0, "0", -4.0, None, "", "n/a", float("nan")])
def test_a_stored_row_without_a_real_close_is_no_quote(api, world, bad_close):
    wid = _make(api, "Mine")["watchlist_id"]
    assert _add(api, wid, "FIXALPHA").status_code == 200
    row = {"as_of_date": "2026-10-12", "close_price": bad_close, "prev_close": 10.0}
    if isinstance(bad_close, float) and bad_close != bad_close:
        row["close_price"] = "nan"                                       # JSON has no NaN; the feed would send text
    world.eod = {"FIXALPHA": row}
    assert _stocks(api, wid)["stocks"][0]["quote"] is None


def test_a_live_quote_of_zero_is_not_a_price(api, world):
    wid = _make(api, "Mine")["watchlist_id"]
    assert _add(api, wid, "FIXALPHA").status_code == 200
    world.live = {"FIXALPHA": {"price": 0.0, "day_change": 0.0, "day_change_pct": 0.0}}
    body = _stocks(api, wid)
    assert body["stocks"][0]["quote"] is None and body["quotes"]["none"] == 1


def test_the_list_still_loads_when_the_quote_sources_fail(api, world):
    wid = _make(api, "Mine")["watchlist_id"]
    for s in ("FIXALPHA", "FIXBRAVO"):
        assert _add(api, wid, s).status_code == 200
    world.live_raises = RuntimeError("the quote service is down")
    world.eod = {"FIXALPHA": RuntimeError("the data platform is down"), "FIXBRAVO": {"as_of_date": "2026-10-12", "close_price": 480.0, "prev_close": 486.0}}
    body = _stocks(api, wid)
    assert [s["symbol"] for s in body["stocks"]] == ["FIXALPHA", "FIXBRAVO"]
    assert body["stocks"][0]["quote"] is None
    assert body["stocks"][1]["quote"]["is_live"] is False
    # A failed look-up is asked again next time; an answer is kept for a while.
    world.eod["FIXALPHA"] = {"as_of_date": "2026-10-12", "close_price": 99.0, "prev_close": 98.0}
    world.eod_calls.clear()
    assert _stocks(api, wid)["stocks"][0]["quote"]["price"] == 99.0
    assert world.eod_calls == ["FIXALPHA"]


def test_a_slow_live_service_does_not_hold_the_list_up(api, world, monkeypatch):
    import asyncio

    wid = _make(api, "Mine")["watchlist_id"]
    assert _add(api, wid, "FIXALPHA").status_code == 200
    world.eod = {"FIXALPHA": {"as_of_date": "2026-10-12", "close_price": 210.5, "prev_close": 209.0}}

    async def slow(symbols: List[str]):
        await asyncio.sleep(5)
        return {"FIXALPHA": {"price": 213.0, "day_change": 2.5, "day_change_pct": 1.19}}

    monkeypatch.setattr(route.live, "get_live_quotes", slow)
    monkeypatch.setattr(route, "_LIVE_WAIT_S", 0.05)
    quote = _stocks(api, wid)["stocks"][0]["quote"]
    assert quote == {"price": 210.5, "day_change": 1.5, "day_change_pct": 0.72, "as_of": "2026-10-12", "is_live": False}


def test_an_empty_list_asks_no_quote_source(api, world):
    wid = _make(api, "Mine")["watchlist_id"]
    body = _stocks(api, wid)
    assert body["stocks"] == [] and body["quotes"]["live"] == 0
    assert world.live_calls == [] and world.eod_calls == []


# ── B16–B24: the starter list ────────────────────────────────────────────────
def test_the_starter_copies_the_latest_research_list_and_is_labelled(api, world):
    r = api.post(f"{URL}/starter", headers=A)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] is True and body["reason"] is None
    made = body["watchlist"]
    assert made["name"] == "Multibagger" and made["is_starter"] is True and made["seeded_from"] == "2026-10-12"
    assert made["symbol_count"] == 3
    detail = _stocks(api, made["watchlist_id"])
    # The newest list only, in its own order (rank), with the research list's company names.
    assert [(s["symbol"], s["company_name"]) for s in detail["stocks"]] == [
        ("FIXALPHA", "Fixture Alpha Industries Ltd"), ("FIXBRAVO", "Fixture Bravo Pharma Ltd"), ("FIXRESEARCH", "Fixture Research Only Ltd"),
    ]
    assert detail["is_starter"] is True and detail["seeded_from"] == "2026-10-12"
    assert world.master_calls == []                                      # research symbols are not re-checked
    listing = api.get(URL, headers=A).json()
    assert [l["name"] for l in listing["lists"]] == ["Multibagger"] and listing["starter_pending"] is False
    marker = world.db.user_watchlist_state.docs[0]
    assert (marker["_id"], marker["first_list_via"], marker["starter_seeded_from"]) == ("user_a", "starter", "2026-10-12")


def test_the_starter_is_idempotent(api, world):
    first = api.post(f"{URL}/starter", headers=A).json()
    for _ in range(3):
        r = api.post(f"{URL}/starter", headers=A)
        assert r.status_code == 200 and r.json() == {"created": False, "reason": "already_had_a_list", "watchlist": None}
    assert [d["watchlist_id"] for d in world.db.user_watchlists.docs] == [first["watchlist"]["watchlist_id"]]
    assert api.post(f"{URL}/starter", headers=B).json()["created"] is True     # each user gets their own
    assert len(world.db.user_watchlists.docs) == 2


def test_deleting_the_starter_does_not_bring_it_back(api, world):
    made = api.post(f"{URL}/starter", headers=A).json()["watchlist"]
    assert api.delete(f"{URL}/{made['watchlist_id']}", headers=A).status_code == 200
    listing = api.get(URL, headers=A).json()
    assert listing["lists"] == [] and listing["starter_pending"] is False
    r = api.post(f"{URL}/starter", headers=A)
    assert r.json() == {"created": False, "reason": "already_had_a_list", "watchlist": None}
    assert world.db.user_watchlists.docs == []
    assert len(world.db.user_watchlist_state.docs) == 1                  # the marker outlives the list


def test_a_user_who_made_and_deleted_their_own_list_is_not_given_the_starter(api, world):
    own = _make(api, "Mine")
    assert api.post(f"{URL}/starter", headers=A).json()["created"] is False
    assert api.delete(f"{URL}/{own['watchlist_id']}", headers=A).status_code == 200
    assert api.post(f"{URL}/starter", headers=A).json() == {"created": False, "reason": "already_had_a_list", "watchlist": None}
    assert world.db.user_watchlists.docs == []


def test_a_list_without_a_marker_still_counts_as_having_had_one(api, world):
    """Should the marker write ever be lost, the lists themselves are the evidence."""
    _make(api, "Mine")
    world.db.user_watchlist_state.docs.clear()
    assert api.get(URL, headers=A).json()["starter_pending"] is False
    assert api.post(f"{URL}/starter", headers=A).json()["reason"] == "already_had_a_list"
    assert len(world.db.user_watchlists.docs) == 1


def test_with_no_research_list_published_nothing_is_made_and_the_offer_stays_open(api, world):
    world.research = {}
    r = api.post(f"{URL}/starter", headers=A)
    assert r.status_code == 200 and r.json() == {"created": False, "reason": "no_research_list", "watchlist": None}
    assert world.db.user_watchlists.docs == [] and world.db.user_watchlist_state.docs == []
    assert api.get(URL, headers=A).json()["starter_pending"] is True
    # A dated list with no usable symbol is the same as none.
    world.research = {"2026-10-12": [{"symbol": "  ", "company_name": "Blank", "rank": 1}]}
    assert api.post(f"{URL}/starter", headers=A).json()["reason"] == "no_research_list"
    # Once a list is published, the next visit gets the example.
    world.research = copy.deepcopy(RESEARCH)
    assert api.post(f"{URL}/starter", headers=A).json()["created"] is True


def test_the_starter_is_not_made_while_an_advisor_has_a_client_open(api, world):
    """An automatic write into someone else's account is not the viewer's to make."""
    viewing = {"X-Test-User": "client_c", "X-Test-Client": "profile_9"}
    assert api.get(URL, headers=viewing).json()["starter_pending"] is False
    r = api.post(f"{URL}/starter", headers=viewing)
    assert r.status_code == 200 and r.json() == {"created": False, "reason": "viewing_a_client", "watchlist": None}
    assert world.db.user_watchlists.docs == [] and world.db.user_watchlist_state.docs == []
    # The client, signed in themselves, is still offered it.
    assert api.get(URL, headers={"X-Test-User": "client_c"}).json()["starter_pending"] is True
    assert api.post(f"{URL}/starter", headers={"X-Test-User": "client_c"}).json()["created"] is True


def test_the_starter_holds_at_most_100_stocks_and_skips_repeats(api, world):
    picks = [{"symbol": f"FIX{i:03d}", "company_name": f"Fixture {i} Ltd", "rank": i} for i in range(130)]
    picks.insert(1, {"symbol": "fix000", "company_name": "Repeat", "rank": 0.5})
    world.research = {"2026-10-12": picks}
    made = api.post(f"{URL}/starter", headers=A).json()["watchlist"]
    assert made["symbol_count"] == 100
    symbols = _symbols(api, made["watchlist_id"])
    assert symbols == [f"FIX{i:03d}" for i in range(100)]


def test_two_starter_calls_that_race_make_one_list(api, world, monkeypatch):
    """Both pass the "never had a list" check; only the one that records the marker goes on."""
    async def no_marker_yet(user_id: str) -> bool:
        return False

    monkeypatch.setattr(route, "_has_had_a_list", no_marker_yet)
    real_count = world.db.user_watchlists.count_documents

    async def no_lists_yet(query):
        return 0

    monkeypatch.setattr(world.db.user_watchlists, "count_documents", no_lists_yet)
    first = api.post(f"{URL}/starter", headers=A).json()
    second = api.post(f"{URL}/starter", headers=A).json()
    assert first["created"] is True
    assert second == {"created": False, "reason": "already_had_a_list", "watchlist": None}
    monkeypatch.setattr(world.db.user_watchlists, "count_documents", real_count)
    assert len(world.db.user_watchlists.docs) == 1


def test_if_the_starter_cannot_be_stored_the_marker_is_taken_back(api, world):
    world.db.user_watchlists.fail_inserts = True
    with pytest.raises(RuntimeError):
        api.post(f"{URL}/starter", headers=A)
    assert world.db.user_watchlists.docs == [] and world.db.user_watchlist_state.docs == []
    world.db.user_watchlists.fail_inserts = False
    assert api.get(URL, headers=A).json()["starter_pending"] is True
    assert api.post(f"{URL}/starter", headers=A).json()["created"] is True


def test_the_starter_can_be_edited_like_any_list(api, world):
    made = api.post(f"{URL}/starter", headers=A).json()["watchlist"]
    wid = made["watchlist_id"]
    assert _add(api, wid, "FIXCHARLIE").json()["added"] is True
    assert api.delete(f"{URL}/{wid}/symbols/FIXALPHA", headers=A).json()["removed"] is True
    renamed = api.patch(f"{URL}/{wid}", json={"name": "My picks"}, headers=A).json()
    # It stays marked as the list that began as a copy, with the date it was copied from.
    assert (renamed["name"], renamed["is_starter"], renamed["seeded_from"]) == ("My picks", True, "2026-10-12")
    assert _symbols(api, wid) == ["FIXBRAVO", "FIXRESEARCH", "FIXCHARLIE"]
    assert _make(api, "Multibagger")["is_starter"] is False              # the name is free for an ordinary list


def test_the_indexes_are_asked_for_once(api, world):
    one = _make(api, "One")
    _make(api, "Two")
    api.patch(f"{URL}/{one['watchlist_id']}", json={"name": "Uno"}, headers=A)
    assert world.db.user_watchlists.unique == [["_id"], ["watchlist_id"], ["user_id", "name_key"]]
    assert world.db.user_watchlists.index_requests == 2                  # two indexes, each asked for once


def test_a_symbol_look_up_that_raises_is_the_master_not_answering(api, world, monkeypatch):
    wid = _make(api, "Mine")["watchlist_id"]

    async def broken(q: str, limit: int = 8):
        raise ValueError("not JSON")

    monkeypatch.setattr(route.daas_client, "search_symbols", broken)
    assert _add(api, wid, "FIXALPHX").status_code == 503
    assert _symbols(api, wid) == []


# ── W2 (2026-11-01): add many stocks at once, and no list writes while an advisor views a client ─────────────────
# docs/plans_20261031/SCREENER_WATCHLIST_PLAN.md slice W2. MOCK — not real data: every symbol below is made up.
BULK = "symbols/bulk"


def _bulk(api: TestClient, list_id: str, symbols: List[str], who: Dict[str, str] = A):
    return api.post(f"{URL}/{list_id}/{BULK}", json={"symbols": symbols}, headers=who)


def _many(world, n: int, prefix: str = "BLK") -> List[str]:
    """n made-up stocks, all known to the instrument list."""
    names = [f"{prefix}{i:03d}" for i in range(n)]
    for name in names:
        world.master[name] = f"{name} Limited"
    return names


def test_bulk_adds_a_hundred_in_one_write_and_a_repeat_adds_none(api, world, monkeypatch):
    wid = _make(api, "Screen")["watchlist_id"]
    names = _many(world, 100)
    writes: List[Dict[str, Any]] = []
    real = world.db.user_watchlists.update_one

    async def counting(query, update, upsert=False):
        writes.append(update)
        return await real(query, update, upsert)

    monkeypatch.setattr(world.db.user_watchlists, "update_one", counting)
    r = _bulk(api, wid, names)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [a["symbol"] for a in body["added"]] == names                  # input order kept
    assert body["already"] == [] and body["refused"] == []
    assert body["watchlist"]["symbol_count"] == 100
    assert len(writes) == 1 and "$each" in writes[0]["$push"]["symbols"]   # ONE guarded write, not 100
    assert body["added"][0] == {"symbol": "BLK000", "company_name": "BLK000 Limited"}
    # The same call again changes nothing.
    again = _bulk(api, wid, names).json()
    assert again["added"] == [] and again["already"] == names and again["refused"] == []
    assert _symbols(api, wid) == names


def test_bulk_refuses_what_does_not_fit_by_name_and_never_exceeds_the_limit(api, world):
    wid = _make(api, "Full")["watchlist_id"]
    names = _many(world, 101)
    # 101 in one request is over the request's own cap
    assert _bulk(api, wid, names).status_code == 422
    # 99 first, then two more: one fits, one is refused as list_full
    assert len(_bulk(api, wid, names[:99]).json()["added"]) == 99
    body = _bulk(api, wid, names[99:101]).json()
    assert [a["symbol"] for a in body["added"]] == ["BLK099"]
    assert body["refused"] == [{"symbol": "BLK100", "code": "list_full", "detail": "A list holds up to 100 stocks."}]
    assert body["watchlist"]["symbol_count"] == 100
    assert len(_symbols(api, wid)) == 100
    # a full list takes none, and says list_full for each
    full = _bulk(api, wid, ["FIXALPHA"]).json()
    assert full["added"] == [] and [r["code"] for r in full["refused"]] == ["list_full"]


def test_bulk_sorts_the_request_into_added_already_and_refused(api, world):
    wid = _make(api, "Mix")["watchlist_id"]
    assert _add(api, wid, "FIXALPHA").json()["added"] is True
    body = _bulk(api, wid, ["fixalpha", " FIXBRAVO ", "FIXBRAVO", "NOSUCH", "bad symbol!", "FIX&CO", "FIXNONAME"]).json()
    assert [a["symbol"] for a in body["added"]] == ["FIXBRAVO", "FIX&CO", "FIXNONAME"]     # trimmed, upper-cased, de-duplicated
    assert body["added"][2]["company_name"] is None                                      # a master row with no name is still a stock
    assert body["already"] == ["FIXALPHA"]
    assert {(r["symbol"], r["code"]) for r in body["refused"]} == {("bad symbol!", "invalid_symbol"), ("NOSUCH", "not_in_instrument_list")}
    assert _symbols(api, wid) == ["FIXALPHA", "FIXBRAVO", "FIX&CO", "FIXNONAME"]


def test_bulk_is_bounded_and_needs_something_to_add(api, world):
    wid = _make(api, "Edge")["watchlist_id"]
    assert _bulk(api, wid, []).status_code == 422
    assert api.post(f"{URL}/{wid}/{BULK}", json={}, headers=A).status_code == 422
    nothing = _bulk(api, wid, ["???"]).json()
    assert nothing["added"] == [] and nothing["refused"][0]["code"] == "invalid_symbol"
    assert world.master_calls == []                                                      # a malformed symbol is never looked up


def test_bulk_into_a_list_that_is_not_yours_is_a_404_and_writes_nothing(api, world):
    theirs = _make(api, "Theirs", B)["watchlist_id"]
    r = _bulk(api, theirs, ["FIXALPHA"])                                                 # A writes into B's list
    assert r.status_code == 404
    assert _symbols(api, theirs, B) == []
    assert _bulk(api, "wl_missing", ["FIXALPHA"]).status_code == 404


def test_bulk_when_the_instrument_list_cannot_be_checked_adds_nothing(api, world):
    wid = _make(api, "Down")["watchlist_id"]
    world.master = None                                                                  # the master does not answer
    world.research = {}                                                                  # and no research list vouches for a symbol
    r = _bulk(api, wid, ["FIXALPHA", "FIXBRAVO"])
    assert r.status_code == 503 and "nothing was added" in r.json()["detail"]
    assert _symbols(api, wid) == []


def test_bulk_looks_symbols_up_a_few_at_a_time(api, world, monkeypatch):
    import asyncio
    wid = _make(api, "Gate")["watchlist_id"]
    names = _many(world, 40)
    running = {"now": 0, "peak": 0}

    async def slow_master(q: str, limit: int = 8):
        running["now"] += 1
        running["peak"] = max(running["peak"], running["now"])
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        running["now"] -= 1
        return {"data": [{"symbol": q.upper(), "company_name": f"{q.upper()} Limited", "sector": None}]}

    monkeypatch.setattr(route.daas_client, "search_symbols", slow_master)
    assert len(_bulk(api, wid, names).json()["added"]) == 40
    assert 1 < running["peak"] <= route._STORED_CONCURRENCY                              # concurrent, but never above the module's limit


def test_bulk_only_looks_up_stocks_that_are_not_already_there(api, world):
    wid = _make(api, "Skip")["watchlist_id"]
    _add(api, wid, "FIXALPHA")
    world.master_calls.clear()
    _bulk(api, wid, ["FIXALPHA", "FIXBRAVO"])
    assert world.master_calls == ["FIXBRAVO"]


def test_bulk_that_loses_a_race_reads_again_and_still_respects_the_rules(api, world, monkeypatch):
    wid = _make(api, "Race")["watchlist_id"]
    real = world.db.user_watchlists.update_one
    state = {"raced": False}

    async def racing(query, update, upsert=False):
        if not state["raced"] and "$push" in update and "$each" in update["$push"]["symbols"]:
            state["raced"] = True
            # another request adds FIXBRAVO between our read and our write
            await real({"watchlist_id": wid}, {"$push": {"symbols": {"symbol": "FIXBRAVO", "company_name": "x", "added_at": "t"}}})
        return await real(query, update, upsert)

    monkeypatch.setattr(world.db.user_watchlists, "update_one", racing)
    body = _bulk(api, wid, ["FIXALPHA", "FIXBRAVO", "FIXCHARLIE"]).json()
    assert state["raced"] is True
    assert [a["symbol"] for a in body["added"]] == ["FIXALPHA", "FIXCHARLIE"]
    assert body["already"] == ["FIXBRAVO"]
    assert sorted(_symbols(api, wid)) == ["FIXALPHA", "FIXBRAVO", "FIXCHARLIE"]          # no symbol twice


def test_bulk_needs_a_signed_in_user(api):
    assert api.post(f"{URL}/wl_x/{BULK}", json={"symbols": ["FIXALPHA"]}).status_code == 401


# ── an advisor looking at a client cannot change that client's lists ──
CLIENT = {"X-Test-User": "client_c", "X-Test-Client": "profile_9"}


def test_every_list_write_is_refused_while_an_advisor_views_a_client(api, world):
    own = _make(api, "Client list", {"X-Test-User": "client_c"})["watchlist_id"]       # the client's own list, made by the client
    _add(api, own, "FIXALPHA", {"X-Test-User": "client_c"})
    before = copy.deepcopy(world.db.user_watchlists.docs)
    writes = [
        ("post", URL, {"name": "Advisor's idea"}),
        ("patch", f"{URL}/{own}", {"name": "Renamed"}),
        ("delete", f"{URL}/{own}", None),
        ("post", f"{URL}/{own}/symbols", {"symbol": "FIXBRAVO"}),
        ("post", f"{URL}/{own}/{BULK}", {"symbols": ["FIXBRAVO"]}),
        ("delete", f"{URL}/{own}/symbols/FIXALPHA", None),
    ]
    for method, url, body in writes:
        r = api.request(method, url, json=body, headers=CLIENT) if body is not None else api.request(method, url, headers=CLIENT)
        assert r.status_code == 403, f"{method} {url} → {r.status_code} {r.text}"
        assert "viewing a client" in r.json()["detail"]
    assert world.db.user_watchlists.docs == before                                       # nothing changed
    # reading is still allowed
    assert api.get(URL, headers=CLIENT).status_code == 200
    assert api.get(f"{URL}/{own}", headers=CLIENT).status_code == 200
