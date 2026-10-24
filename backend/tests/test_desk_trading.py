"""Smart trading desk — the user's own paper trades and price alerts.

Covers routes/desk_trading.py, services/desk_trading.py and scripts/check_desk_alerts.py.

No network and no real database. What is replaced, and by what:

  * `route.db` / the script's `deps.db`   an in-memory stand-in for the two Mongo collections
                                          (FakeCollection: only the operators these modules use)
  * `route.get_current_user`              reads the test's `X-Test-User` header
  * the data platform                     `daas_client._get` / `is_configured`, serving
                                          GET /v1/prices/eod/{symbol} the way the real router does
                                          (newest first, `start` filter, limit/offset pages)
  * the clock                             `svc.utcnow`, fixed at 2026-10-12 05:00 UTC (10:30 IST)

Everything the modules do runs for real: validation, ownership, limits, the series choice, the
exit / firing rules, the idempotent writes and the response shapes.

MOCK — not real data: the FIX* symbols and their bars are made up. The RELIANCE rows in
`STAGING_RELIANCE_ROWS` are copied from the staging warehouse (nidp.prices_eod, read 2026-10-14).
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

from routes import desk_trading as route
from services import desk_trading as svc
from services import paper_account as _acct
from services import risk_controls as _rc
from tests.test_paper_account import mongo_expr

TRADES_URL = "/api/desk/paper-trades"
ALERTS_URL = "/api/desk/alerts"
A = {"X-Test-User": "user_a"}
B = {"X-Test-User": "user_b"}
NOW = datetime(2026, 10, 12, 5, 0, tzinfo=timezone.utc)          # Monday 10:30 IST


# ── an in-memory Mongo collection ────────────────────────────────────────────
def _matches(doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
    for key, cond in query.items():
        if key == "$expr":          # the paper account's conditional reserve (services/paper_account.reserve)
            if not mongo_expr(doc, cond):
                return False
            continue
        assert not isinstance(cond, dict), f"the fake collection does not know {cond}"
        if doc.get(key) != cond:
            return False
    return True


class _Cursor:
    def __init__(self, docs: List[Dict[str, Any]]):
        self._docs = docs

    def sort(self, key: str, direction: int) -> "_Cursor":
        self._docs = sorted(self._docs, key=lambda d: str(d.get(key) or ""), reverse=direction < 0)
        return self

    async def to_list(self, length: Optional[int]) -> List[Dict[str, Any]]:
        return self._docs if length is None else self._docs[:length]


class _Result:
    def __init__(self, matched: int = 0, deleted: int = 0):
        self.matched_count = self.modified_count = matched
        self.deleted_count = deleted


class FakeCollection:
    def __init__(self):
        self.docs: List[Dict[str, Any]] = []
        self.indexes: List[Any] = []
        self.writes = 0

    async def create_index(self, keys, **_):
        self.indexes.append(keys)

    def find(self, query):
        return _Cursor([copy.deepcopy(d) for d in self.docs if _matches(d, query)])

    async def find_one(self, query):
        return next((copy.deepcopy(d) for d in self.docs if _matches(d, query)), None)

    async def count_documents(self, query):
        return sum(1 for d in self.docs if _matches(d, query))

    async def insert_one(self, doc):
        if any(d["_id"] == doc["_id"] for d in self.docs):
            raise DuplicateKeyError("E11000 duplicate key: _id")
        self.writes += 1
        self.docs.append(copy.deepcopy(doc))

    async def update_one(self, query, update, upsert=False):
        # $inc / $setOnInsert / upsert are modelled because the paper account keeps its cash and
        # blocked figures that way (services/paper_account). A fixture that cannot express them would
        # fail every trade create, which is a gap in the fixture, not in the account.
        known = {"$set", "$inc", "$setOnInsert", "$push"}
        assert set(update) <= known, f"the fake collection does not know {set(update) - known}"
        for d in self.docs:
            if _matches(d, query):
                self.writes += 1
                d.update(copy.deepcopy(update.get("$set") or {}))
                for key, delta in (update.get("$inc") or {}).items():
                    d[key] = (d.get(key) or 0) + delta
                for key, value in (update.get("$push") or {}).items():
                    d.setdefault(key, []).append(copy.deepcopy(value))
                return _Result(matched=1)
        if upsert:
            doc = copy.deepcopy(update.get("$setOnInsert") or {})
            doc.update(copy.deepcopy(update.get("$set") or {}))
            for key, delta in (update.get("$inc") or {}).items():
                doc[key] = (doc.get(key) or 0) + delta
            self.writes += 1
            self.docs.append(doc)
            return _Result(matched=0)
        return _Result()

    async def delete_one(self, query):
        for i, d in enumerate(self.docs):
            if _matches(d, query):
                self.writes += 1
                del self.docs[i]
                return _Result(deleted=1)
        return _Result()


class FakeDb:
    def __init__(self):
        # The paper-trade route now asks the kill switch before it writes (services/risk_controls);
        # an unreadable store fails CLOSED, so a fake DB that does not model these collections
        # would block every create. Modelling them keeps the fail-closed behaviour under test
        # instead of weakening it.
        self.cols = {svc.TRADES: FakeCollection(), svc.ALERTS: FakeCollection(),
                     _rc.CONTROLS: FakeCollection(), _rc.AUDIT: FakeCollection(),
                     _rc.DECISIONS: FakeCollection(),
                     _acct.ACCOUNTS: FakeCollection(), _acct.LEDGER: FakeCollection()}

    def __getitem__(self, name: str) -> FakeCollection:
        assert name in self.cols, f"the desk touched db[{name!r}]"
        return self.cols[name]

    @property
    def trades(self) -> FakeCollection:
        return self.cols[svc.TRADES]

    @property
    def alerts(self) -> FakeCollection:
        return self.cols[svc.ALERTS]


def bar(day: str, high: Optional[float], low: Optional[float], close: Optional[float], series: str = "EQ") -> Dict[str, Any]:
    """One row the way GET /v1/prices/eod/{symbol} sends it (row_to_dict of nidp.prices_eod)."""
    return {"as_of_date": day, "symbol": None, "series": series, "isin": None, "prev_close": None,
            "open_price": None, "high_price": high, "low_price": low, "close_price": close,
            "volume": 1000, "turnover": None, "trades": None, "deliv_qty": None, "deliv_pct": None}


# MOCK — not real data: FIXA trades around ₹100, FIXB around ₹500.
HISTORY = {
    "FIXA": [bar("2026-10-08", 101, 97, 99), bar("2026-10-09", 102, 98, 100), bar("2026-10-12", 104, 94, 101)],
    "FIXB": [bar("2026-10-09", 505, 495, 500), bar("2026-10-12", 510, 490, 502)],
}

# Copied from the staging warehouse 2026-10-14 (nidp.prices_eod, symbol RELIANCE): the 2026-10-08 session has
# a block-deal-window row (BL) beside the normal-market row (EQ).
STAGING_RELIANCE_ROWS = [
    bar("2026-10-13", 1168.30, 1152.20, 1166.70), bar("2026-10-12", 1185.50, 1153.20, 1158.90),
    bar("2026-10-09", 1179.00, 1160.20, 1170.30), bar("2026-10-08", 1176.00, 1176.00, 1176.00, "BL"),
    bar("2026-10-08", 1208.00, 1173.00, 1178.00), bar("2026-10-07", 1220.80, 1203.50, 1207.70),
]


class World:
    def __init__(self):
        self.db = FakeDb()
        self.rows: Dict[str, List[Dict[str, Any]]] = copy.deepcopy(HISTORY)
        self.fail: Dict[str, Exception] = {}          # symbol → error the platform raises
        self.configured = True
        self.calls: List[Dict[str, Any]] = []
        self.now = NOW

    def add(self, symbol: str, *rows: Dict[str, Any]) -> None:
        self.rows.setdefault(symbol, []).extend(rows)


@pytest.fixture
def world(monkeypatch) -> World:
    w = World()
    monkeypatch.setattr(route, "db", w.db)
    monkeypatch.setattr(svc, "_indexes_ready", False)
    monkeypatch.setattr(svc, "utcnow", lambda: w.now)

    async def fake_user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": uid}

    monkeypatch.setattr(route, "get_current_user", fake_user)

    async def fake_get(path: str, params=None, timeout: float = 10.0, *, creds=None):
        assert path.startswith("/prices/eod/"), f"the desk read {path}"
        symbol = unquote(path[len("/prices/eod/"):])
        w.calls.append({"symbol": symbol, **(params or {})})
        if symbol in w.fail:
            raise w.fail[symbol]
        start = (params or {}).get("start")
        rows = [r for r in w.rows.get(symbol, []) if start is None or r["as_of_date"] >= start]
        rows = sorted(rows, key=lambda r: r["as_of_date"], reverse=True)          # ORDER BY as_of_date DESC
        limit, offset = params["limit"], params["offset"]
        page = [dict(r, symbol=symbol) for r in rows[offset:offset + limit]]
        return {"data": page, "count": len(page),
                "pagination": {"limit": limit, "offset": offset, "total": None,
                               "next_offset": offset + limit if len(page) == limit else None},
                "as_of": "2026-10-14T09:00:00Z", "symbol": symbol}

    monkeypatch.setattr(svc.daas_client, "_get", fake_get)
    monkeypatch.setattr(svc.daas_client, "is_configured", lambda: w.configured)
    return w


@pytest.fixture
def api(world) -> TestClient:
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app)


def trade_body(**over) -> Dict[str, Any]:
    body = {"symbol": "FIXA", "quantity": 10, "entry_price": 100.0, "stop_price": 95.0, "target_price": 110.0}
    body.update(over)
    return body


def open_trade(api: TestClient, who=A, **over) -> Dict[str, Any]:
    r = api.post(TRADES_URL, json=trade_body(**over), headers=who)
    assert r.status_code == 201, r.text
    return r.json()["trade"]


def make_alert(api: TestClient, who=A, **over) -> Dict[str, Any]:
    body = {"symbol": "FIXA", "condition": "above", "level": 105.0}
    body.update(over)
    r = api.post(ALERTS_URL, json=body, headers=who)
    assert r.status_code == 201, r.text
    return r.json()["alert"]


def trades(api: TestClient, who=A, status: str = "all") -> Dict[str, Any]:
    r = api.get(TRADES_URL, params={"status": status}, headers=who)
    assert r.status_code == 200, r.text
    return r.json()


def alerts(api: TestClient, who=A, status: str = "all") -> Dict[str, Any]:
    r = api.get(ALERTS_URL, params={"status": status}, headers=who)
    assert r.status_code == 200, r.text
    return r.json()


# ── sign-in and ownership ────────────────────────────────────────────────────
def test_every_route_needs_a_signed_in_user(api, world):
    calls = [("post", TRADES_URL, trade_body()), ("get", TRADES_URL, None), ("post", f"{TRADES_URL}/x/close", {}),
             ("post", ALERTS_URL, {"symbol": "FIXA", "condition": "above", "level": 1}), ("get", ALERTS_URL, None),
             ("delete", f"{ALERTS_URL}/x", None)]
    for method, url, body in calls:
        r = api.request(method, url, json=body) if body is not None else api.request(method, url)
        assert r.status_code == 401, f"{method} {url} → {r.status_code}"
    assert world.db.trades.docs == [] and world.db.alerts.docs == []


def test_another_users_trades_and_alerts_are_invisible_and_answer_404(api, world):
    t = open_trade(api, A)
    a = make_alert(api, A)
    assert trades(api, B)["trades"] == [] and alerts(api, B)["alerts"] == []
    assert trades(api, B)["summary"]["open"] == 0
    r = api.post(f"{TRADES_URL}/{t['id']}/close", json={"exit_price": 120}, headers=B)
    assert (r.status_code, r.json()["detail"]) == (404, "trade_not_found")
    r = api.delete(f"{ALERTS_URL}/{a['id']}", headers=B)
    assert (r.status_code, r.json()["detail"]) == (404, "alert_not_found")
    assert world.db.trades.docs[0]["status"] == "open" and len(world.db.alerts.docs) == 1
    assert [x["id"] for x in trades(api, A)["trades"]] == [t["id"]]


def test_writes_go_through_the_csrf_middleware_like_any_other_write(world):
    from middleware import CsrfProtectMiddleware

    app = FastAPI()
    app.add_middleware(CsrfProtectMiddleware)
    app.include_router(route.router)
    client = TestClient(app)
    client.cookies.set("session_token", "cookie-session")
    r = client.post(TRADES_URL, json=trade_body(), headers={**A, "Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"] == "CSRF_BLOCKED"
    r = client.delete(f"{ALERTS_URL}/x", headers={**A, "Origin": "https://evil.example"})
    assert r.status_code == 403
    assert world.db.trades.docs == []
    r = client.post(TRADES_URL, json=trade_body(), headers={**A, "Origin": "https://staging.niveshcopilot.com"})
    assert r.status_code == 201, r.text


# ── POST /paper-trades ───────────────────────────────────────────────────────
def test_open_a_paper_trade_stores_it_for_the_user_and_returns_201(api, world):
    r = api.post(TRADES_URL, headers=A, json=trade_body(
        symbol=" m&m ", note="  breakout retest  ", source={"kind": "scanner", "bucket": "breakout", "signal_date": "2026-10-09"}))
    assert r.status_code == 201, r.text
    body = r.json()
    t = body["trade"]
    assert t["symbol"] == "M&M" and t["quantity"] == 10 and t["entry_price"] == 100.0
    assert t["stop_price"] == 95.0 and t["target_price"] == 110.0 and t["note"] == "breakout retest"
    assert t["source"] == {"kind": "scanner", "bucket": "breakout", "signal_date": "2026-10-09"}
    assert t["status"] == "open" and t["opened_at"] == "2026-10-12T05:00:00+00:00"
    assert t["closed_at"] is None and t["exit_price"] is None and t["exit_reason"] is None
    # No mark is made up on create: nothing was read from the data platform.
    assert t["last_close"] is None and t["unrealized_pnl_rs"] is None and t["realized_pnl_rs"] is None
    assert body["price_basis"] == "end of day" and "nidp.prices_eod" in body["source"]
    assert world.calls == []
    [stored] = world.db.trades.docs
    assert stored["_id"] == t["id"] and stored["user_id"] == "user_a" and len(t["id"]) == 36
    assert world.db.trades.indexes == [[("user_id", 1), ("status", 1)], [("status", 1), ("symbol", 1)]]
    assert world.db.alerts.indexes == [[("user_id", 1), ("status", 1)], [("status", 1), ("symbol", 1)]]


def test_target_may_be_null_or_left_out(api):
    assert open_trade(api, target_price=None)["target_price"] is None
    body = trade_body()
    del body["target_price"]
    assert api.post(TRADES_URL, json=body, headers=A).json()["trade"]["target_price"] is None


@pytest.mark.parametrize("over, code", [
    ({"symbol": "RELIANCE!"}, "invalid_symbol"),
    ({"symbol": ""}, "invalid_symbol"),
    ({"symbol": "A" * 21}, "invalid_symbol"),
    ({"symbol": 7}, "invalid_symbol"),
    ({"quantity": 0}, "invalid_quantity"),
    ({"quantity": 1.5}, "invalid_quantity"),
    ({"quantity": "10"}, "invalid_quantity"),
    ({"quantity": True}, "invalid_quantity"),
    ({"quantity": 1_000_001}, "invalid_quantity"),
    ({"entry_price": 0}, "invalid_entry_price"),
    ({"entry_price": -5}, "invalid_entry_price"),
    ({"entry_price": "100"}, "invalid_entry_price"),
    ({"entry_price": None}, "invalid_entry_price"),
    ({"stop_price": None}, "invalid_stop_price"),
    ({"stop_price": 100.0}, "stop_not_below_entry"),
    ({"stop_price": 101.0}, "stop_not_below_entry"),
    ({"target_price": 100.0}, "target_not_above_entry"),
    ({"target_price": 0}, "invalid_target_price"),
    ({"note": "x" * 501}, "invalid_note"),
    ({"note": 5}, "invalid_note"),
    ({"source": {"bucket": "x"}}, "invalid_source"),
    ({"source": {"kind": "scanner", "extra": 1}}, "invalid_source"),
    ({"source": {"kind": "scanner", "signal_date": "13-10-2026"}}, "invalid_source"),
    ({"source": "scanner"}, "invalid_source"),
    ({"side": "short"}, "unknown_field"),
])
def test_open_refuses_a_bad_body_with_a_code_and_stores_nothing(api, world, over, code):
    r = api.post(TRADES_URL, json=trade_body(**over), headers=A)
    assert (r.status_code, r.json()["detail"]) == (422, code)
    assert world.db.trades.docs == []


def test_open_refuses_a_body_that_is_not_a_json_object(api, world):
    for content in (b"", b"not json", b"[1,2]", b'{"symbol": "FIXA", "quantity": 1, "entry_price": NaN, "stop_price": 1}'):
        r = api.post(TRADES_URL, content=content, headers={**A, "Content-Type": "application/json"})
        assert r.status_code == 422, content
        assert r.json()["detail"] in ("invalid_body", "invalid_entry_price")
    assert world.db.trades.docs == []


def test_a_user_may_hold_100_open_trades_and_the_101st_is_409(api, world):
    for i in range(100):
        world.db.trades.docs.append({**svc.new_trade("user_a", trade_body(), NOW), "_id": f"t{i}"})
    r = api.post(TRADES_URL, json=trade_body(), headers=A)
    assert (r.status_code, r.json()["detail"]) == (409, "open_trade_limit")
    assert len(world.db.trades.docs) == 100
    assert api.post(TRADES_URL, json=trade_body(), headers=B).status_code == 201       # per user
    world.db.trades.docs[0]["status"] = "closed"                                        # closed ones do not count
    assert api.post(TRADES_URL, json=trade_body(), headers=A).status_code == 201


def test_two_opens_that_race_past_the_count_do_not_exceed_the_limit(api, world, monkeypatch):
    for i in range(100):
        world.db.trades.docs.append({**svc.new_trade("user_a", trade_body(), NOW), "_id": f"t{i}"})
    real = world.db.trades.count_documents
    seen = []

    async def first_count_is_stale(query):
        seen.append(query)
        n = await real(query)
        return 99 if len(seen) == 1 else n                 # the pre-check read before the other insert landed

    monkeypatch.setattr(world.db.trades, "count_documents", first_count_is_stale)
    r = api.post(TRADES_URL, json=trade_body(), headers=A)
    assert (r.status_code, r.json()["detail"]) == (409, "open_trade_limit")
    assert len(world.db.trades.docs) == 100


# ── GET /paper-trades: marks and the exit rule ───────────────────────────────
def test_list_marks_open_trades_at_the_last_end_of_day_close(api, world):
    t = open_trade(api)
    body = trades(api)
    [row] = body["trades"]
    assert row["id"] == t["id"] and row["status"] == "open"
    assert row["last_close"] == 101.0 and row["last_close_date"] == "2026-10-12"
    assert row["unrealized_pnl_rs"] == 10.0 and row["realized_pnl_rs"] is None
    assert row["checked_through"] is None            # opened on 2026-10-12 (IST): no session after it yet
    assert row["mark_error"] is None
    assert body["as_of"] == "2026-10-12" and body["checked_through"] == "2026-10-12"
    assert body["marks_error"] is None and body["price_basis"] == "end of day"
    # Net of the strategy_engine cost model: 100 × 10 × 0.05% + ₹20 and 101 × 10 × 0.05% + ₹20 → ₹41.00; 10 − 41 = −31.
    costs = round((100 * 10 * 0.0005 + 20.0) + (101 * 10 * 0.0005 + 20.0), 2)
    assert body["summary"] == {"open": 1, "closed": 0, "wins": 0, "losses": 0, "realized_pnl_rs": None,
                               "unrealized_pnl_rs": 10.0, "unmarked_open": 0, "partial": False,
                               "net_realized_pnl_rs": None, "costs_realized_rs": None,
                               "net_unrealized_pnl_rs": round(10.0 - costs, 2), "entry_pending": 0, "not_entered": 0}
    # The 2026-10-12 bar's low (94) is below the stop, but the trade was opened that day: not an exit.
    assert world.db.trades.docs[0]["status"] == "open"
    # One read for the symbol, from 14 days before the open date.
    assert world.calls == [{"symbol": "FIXA", "start": "2026-09-28", "limit": 5000, "offset": 0}]


def test_a_low_at_or_below_the_stop_closes_the_trade_at_the_stop_once(api, world):
    t = open_trade(api)
    world.add("FIXA", bar("2026-10-13", 103, 96, 97), bar("2026-10-14", 99, 95.0, 96))
    body = trades(api)
    [row] = body["trades"]
    assert row["status"] == "closed" and row["exit_reason"] == "stop" and row["exit_price"] == 95.0
    assert row["exit_session"] == "2026-10-14" and row["exit_note"] is None
    assert row["realized_pnl_rs"] == -50.0 and row["unrealized_pnl_rs"] is None and row["last_close"] is None
    assert row["closed_at"] == "2026-10-12T05:00:00+00:00"
    assert body["summary"]["losses"] == 1 and body["summary"]["realized_pnl_rs"] == -50.0
    stored = world.db.trades.docs[0]
    assert stored["status"] == "closed" and stored["exit_reason"] == "stop" and stored["_id"] == t["id"]
    # A second read finds it closed and writes nothing.
    writes = world.db.trades.writes
    world.now = datetime(2026, 10, 15, 5, 0, tzinfo=timezone.utc)
    again = trades(api)
    assert world.db.trades.writes == writes and again["trades"][0]["closed_at"] == "2026-10-12T05:00:00+00:00"


def test_a_high_at_or_above_the_target_closes_it_at_the_target(api, world):
    open_trade(api)
    world.add("FIXA", bar("2026-10-13", 110.0, 99, 108))
    [row] = trades(api)["trades"]
    assert (row["exit_reason"], row["exit_price"], row["exit_session"]) == ("target", 110.0, "2026-10-13")
    assert row["realized_pnl_rs"] == 100.0
    assert trades(api)["summary"]["wins"] == 1


def test_a_session_that_touches_both_counts_as_the_stop_and_says_so(api, world):
    open_trade(api)
    world.add("FIXA", bar("2026-10-13", 112, 94, 100))
    [row] = trades(api)["trades"]
    assert (row["exit_reason"], row["exit_price"]) == ("stop", 95.0)
    assert row["exit_note"] == svc.BOTH_IN_RANGE_NOTE
    assert "conservative" in trades(api)["exit_rule"]


def test_without_a_target_only_the_stop_can_close_it(api, world):
    open_trade(api, target_price=None)
    world.add("FIXA", bar("2026-10-13", 500, 99, 400))
    [row] = trades(api)["trades"]
    assert row["status"] == "open" and row["unrealized_pnl_rs"] == 3000.0 and row["checked_through"] == "2026-10-13"


def test_the_first_session_counted_is_the_one_after_the_ist_open_date(api, world):
    # 20:00 UTC on 12 Oct is 01:30 IST on 13 Oct: the 13 Oct session is the open date, not after it.
    world.now = datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc)
    open_trade(api)
    world.add("FIXA", bar("2026-10-13", 103, 90, 97))
    assert trades(api)["trades"][0]["status"] == "open"
    world.add("FIXA", bar("2026-10-14", 103, 94, 97))
    [row] = trades(api)["trades"]
    assert (row["status"], row["exit_session"]) == ("closed", "2026-10-14")


def test_block_deal_window_rows_never_move_a_trade(api, world):
    """Real staging rows: on 2026-10-08 RELIANCE has a BL row (1176) and an EQ row (low 1173)."""
    world.rows["RELIANCE"] = copy.deepcopy(STAGING_RELIANCE_ROWS)
    world.now = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    open_trade(api, symbol="RELIANCE", entry_price=1200.0, stop_price=1150.0, target_price=1250.0)
    [row] = trades(api)["trades"]
    assert row["status"] == "open" and row["checked_through"] == "2026-10-13"
    assert row["last_close"] == 1166.7 and row["last_close_date"] == "2026-10-13"
    assert row["unrealized_pnl_rs"] == round((1166.7 - 1200.0) * 10, 2)
    bars = svc.session_bars(STAGING_RELIANCE_ROWS)
    assert [(b["date"].isoformat(), b["series"], b["close"]) for b in bars if b["date"].day == 8] == [("2026-10-08", "EQ", 1178.0)]
    # A BL-only print below the stop is ignored too.
    world.add("RELIANCE", bar("2026-10-14", 1140, 1140, 1140, "BL"))
    assert trades(api)["trades"][0]["status"] == "open"


def test_a_session_without_a_high_or_low_stops_the_scan_rather_than_skipping_it(api, world):
    open_trade(api)
    world.add("FIXA", bar("2026-10-13", None, None, 100), bar("2026-10-14", 99, 90, 92))
    [row] = trades(api)["trades"]
    assert row["status"] == "open" and row["checked_through"] is None
    assert row["last_close"] == 92.0


def test_two_trades_in_one_symbol_share_one_read_from_the_earliest_open(api, world):
    open_trade(api)
    world.now = datetime(2026, 10, 20, 5, 0, tzinfo=timezone.utc)
    open_trade(api, quantity=5)
    world.now = datetime(2026, 10, 20, 6, 0, tzinfo=timezone.utc)
    open_trade(api, symbol="FIXB", entry_price=500.0, stop_price=480.0, target_price=None)
    world.calls.clear()
    body = trades(api)
    assert sorted((c["symbol"], c["start"]) for c in world.calls) == [("FIXA", "2026-09-28"), ("FIXB", "2026-10-06")]
    assert [t["symbol"] for t in body["trades"]] == ["FIXB", "FIXA", "FIXA"]          # newest first
    assert body["summary"]["unrealized_pnl_rs"] == 10.0 + 5.0 + 20.0


def test_every_page_is_read_so_an_early_stop_is_not_missed(api, world, monkeypatch):
    monkeypatch.setattr(svc, "PAGE_LIMIT", 2)
    open_trade(api)
    world.add("FIXA", bar("2026-10-13", 103, 94, 97), bar("2026-10-14", 99, 96, 98), bar("2026-10-15", 99, 96, 98))
    [row] = trades(api)["trades"]
    assert (row["status"], row["exit_session"]) == ("closed", "2026-10-13")
    # Pages of 2 rows, newest first; a full last page is followed by one empty read, as the real envelope says.
    assert [c["offset"] for c in world.calls] == [0, 2, 4, 6]


def test_when_the_data_platform_fails_the_list_still_answers_with_null_marks(api, world):
    open_trade(api)
    open_trade(api, symbol="FIXB", entry_price=500.0, stop_price=480.0, target_price=None)
    world.fail["FIXA"] = svc.daas_client.DaasError("DAAS /prices/eod/FIXA returned HTTP 502", status_code=502)
    body = trades(api)
    by = {t["symbol"]: t for t in body["trades"]}
    assert by["FIXA"]["last_close"] is None and by["FIXA"]["unrealized_pnl_rs"] is None
    assert by["FIXA"]["mark_error"] == "prices_unavailable"
    assert by["FIXB"]["last_close"] == 502.0 and by["FIXB"]["mark_error"] is None
    assert body["marks_error"] == "prices_partially_unavailable"
    assert body["summary"]["unrealized_pnl_rs"] is None and body["summary"]["unmarked_open"] == 1
    world.fail["FIXB"] = svc.daas_client.DaasError("timed out")
    body = trades(api)
    assert body["marks_error"] == "prices_unavailable" and body["as_of"] is None and body["checked_through"] is None
    assert len(body["trades"]) == 2 and all(t["last_close"] is None for t in body["trades"])


def test_an_unconfigured_data_platform_reads_as_unavailable_not_as_zero(api, world):
    open_trade(api)
    world.configured = False
    body = trades(api)
    assert body["marks_error"] == "prices_unavailable" and body["trades"][0]["unrealized_pnl_rs"] is None
    assert world.calls == []


def test_a_symbol_the_platform_has_no_prices_for_says_so(api, world):
    open_trade(api, symbol="FIXNONE")
    body = trades(api)
    assert body["trades"][0]["mark_error"] == "no_prices_for_symbol" and body["trades"][0]["last_close"] is None
    assert body["marks_error"] is None and body["as_of"] is None


def test_the_status_filter_lists_one_kind_but_the_summary_covers_all(api, world):
    open_trade(api)
    t2 = open_trade(api, symbol="FIXB", entry_price=500.0, stop_price=480.0, target_price=None)
    assert api.post(f"{TRADES_URL}/{t2['id']}/close", json={"exit_price": 520.0}, headers=A).status_code == 200
    assert [t["symbol"] for t in trades(api, status="open")["trades"]] == ["FIXA"]
    closed = trades(api, status="closed")
    assert [t["symbol"] for t in closed["trades"]] == ["FIXB"]
    assert closed["summary"]["open"] == 1 and closed["summary"]["closed"] == 1
    assert closed["summary"]["realized_pnl_rs"] == 200.0 and closed["summary"]["wins"] == 1
    r = api.get(TRADES_URL, params={"status": "OPEN"}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (422, "invalid_status")


# ── POST /paper-trades/{id}/close ────────────────────────────────────────────
def test_close_at_a_given_price(api, world):
    t = open_trade(api)
    r = api.post(f"{TRADES_URL}/{t['id']}/close", json={"exit_price": 104.5}, headers=A)
    assert r.status_code == 200, r.text
    row = r.json()["trade"]
    assert (row["status"], row["exit_reason"], row["exit_price"]) == ("closed", "manual", 104.5)
    assert row["realized_pnl_rs"] == 45.0 and row["exit_session"] is None
    r = api.post(f"{TRADES_URL}/{t['id']}/close", json={"exit_price": 104.5}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (409, "trade_already_closed")


def test_close_without_a_price_uses_the_last_end_of_day_close(api, world):
    t = open_trade(api)
    r = api.post(f"{TRADES_URL}/{t['id']}/close", headers=A)          # no body at all
    assert r.status_code == 200, r.text
    row = r.json()["trade"]
    assert (row["exit_price"], row["exit_session"], row["exit_reason"]) == (101.0, "2026-10-12", "manual")
    assert row["exit_note"] == "Closed at the last end-of-day close (2026-10-12)."
    assert row["realized_pnl_rs"] == 10.0


def test_close_finds_an_earlier_stop_first_and_answers_409(api, world):
    t = open_trade(api)
    world.add("FIXA", bar("2026-10-13", 103, 94, 97))
    r = api.post(f"{TRADES_URL}/{t['id']}/close", json={"exit_price": 120.0}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (409, "trade_already_closed")
    stored = world.db.trades.docs[0]
    assert (stored["exit_reason"], stored["exit_price"], stored["exit_session"]) == ("stop", 95.0, "2026-10-13")


def test_close_when_prices_cannot_be_read(api, world):
    t = open_trade(api)
    world.fail["FIXA"] = svc.daas_client.DaasError("unreachable")
    r = api.post(f"{TRADES_URL}/{t['id']}/close", json={}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (503, "prices_unavailable")
    assert world.db.trades.docs[0]["status"] == "open"
    r = api.post(f"{TRADES_URL}/{t['id']}/close", json={"exit_price": 99.0}, headers=A)   # the user's own price
    assert r.status_code == 200 and r.json()["trade"]["exit_price"] == 99.0


def test_close_without_a_price_when_there_is_no_close_is_409(api, world):
    t = open_trade(api, symbol="FIXNONE")
    r = api.post(f"{TRADES_URL}/{t['id']}/close", json={"exit_price": None}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (409, "no_close_available")
    assert world.db.trades.docs[0]["status"] == "open"


@pytest.mark.parametrize("body, code", [
    ({"exit_price": 0}, "invalid_exit_price"), ({"exit_price": "100"}, "invalid_exit_price"),
    ({"price": 100}, "unknown_field"), ([100], "invalid_body"),
])
def test_close_refuses_a_bad_body(api, world, body, code):
    t = open_trade(api)
    r = api.post(f"{TRADES_URL}/{t['id']}/close", json=body, headers=A)
    assert (r.status_code, r.json()["detail"]) == (422, code)
    assert world.db.trades.docs[0]["status"] == "open"


def test_close_of_an_unknown_id_is_404(api):
    r = api.post(f"{TRADES_URL}/no-such-id/close", json={"exit_price": 1}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (404, "trade_not_found")


def test_an_exit_never_overwrites_a_close_written_in_between(world):
    """The evaluator holds a stale 'open' copy; the user closed it meanwhile. The status filter keeps the manual close."""
    doc = svc.new_trade("user_a", trade_body(), NOW)
    asyncio.run(world.db.trades.insert_one(doc))
    asyncio.run(svc.close_trade(world.db, doc, exit_reason="manual", exit_price=102.0, exit_session=None))
    bars = {"FIXA": svc.session_bars(HISTORY["FIXA"] + [bar("2026-10-13", 103, 90, 91)])}
    out, counts = asyncio.run(svc.apply_trade_exits(world.db, [doc], bars))
    assert counts["stop"] == 0 and counts["already_closed"] == 1
    assert out[0]["exit_reason"] == "manual" and world.db.trades.docs[0]["exit_price"] == 102.0


# ── alerts ───────────────────────────────────────────────────────────────────
def test_set_an_alert_returns_201_and_stores_it_for_the_user(api, world):
    r = api.post(ALERTS_URL, json={"symbol": "fixa", "condition": "below", "level": 96, "note": " dip "}, headers=A)
    assert r.status_code == 201, r.text
    a = r.json()["alert"]
    assert (a["symbol"], a["condition"], a["level"], a["note"], a["status"]) == ("FIXA", "below", 96.0, "dip", "active")
    assert a["created_at"] == "2026-10-12T05:00:00+00:00"
    assert a["fired_at"] is None and a["fired_session"] is None and a["fired_price"] is None
    assert world.db.alerts.docs[0]["user_id"] == "user_a" and world.db.alerts.docs[0]["_id"] == a["id"]


@pytest.mark.parametrize("body, code", [
    ({"symbol": "FIXA", "condition": "cross", "level": 1}, "invalid_condition"),
    ({"symbol": "FIXA", "condition": "above", "level": 0}, "invalid_level"),
    ({"symbol": "FIXA", "condition": "above", "level": "1"}, "invalid_level"),
    ({"symbol": "FIX A", "condition": "above", "level": 1}, "invalid_symbol"),
    ({"symbol": "FIXA", "condition": "above", "level": 1, "repeat": True}, "unknown_field"),
    ("FIXA", "invalid_body"),
])
def test_set_alert_refuses_a_bad_body(api, world, body, code):
    r = api.post(ALERTS_URL, json=body, headers=A)
    assert (r.status_code, r.json()["detail"]) == (422, code)
    assert world.db.alerts.docs == []


def test_a_user_may_keep_50_active_alerts_and_the_51st_is_409(api, world):
    for i in range(50):
        world.db.alerts.docs.append({**svc.new_alert("user_a", {"symbol": "FIXA", "condition": "above", "level": 200}, NOW), "_id": f"a{i}"})
    r = api.post(ALERTS_URL, json={"symbol": "FIXA", "condition": "above", "level": 1}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (409, "active_alert_limit")
    world.db.alerts.docs[0]["status"] = "fired"
    assert api.post(ALERTS_URL, json={"symbol": "FIXA", "condition": "above", "level": 1}, headers=A).status_code == 201


def test_an_alert_fires_on_the_first_session_after_it_was_made(api, world):
    above = make_alert(api, level=105.0)
    below = make_alert(api, condition="below", level=96.0)
    body = alerts(api)
    assert {a["status"] for a in body["alerts"]} == {"active"}        # 12 Oct is the day they were made
    assert body["alerts"][0]["last_close"] == 101.0 and body["checked_through"] == "2026-10-12"
    world.add("FIXA", bar("2026-10-13", 104, 97, 100), bar("2026-10-14", 106, 98, 105), bar("2026-10-15", 103, 95, 96))
    body = alerts(api)
    by = {a["id"]: a for a in body["alerts"]}
    assert (by[above["id"]]["status"], by[above["id"]]["fired_session"], by[above["id"]]["fired_price"]) == ("fired", "2026-10-14", 105.0)
    assert (by[below["id"]]["status"], by[below["id"]]["fired_session"], by[below["id"]]["fired_price"]) == ("fired", "2026-10-15", 96.0)
    assert by[above["id"]]["fired_at"] == "2026-10-12T05:00:00+00:00"
    assert body["counts"] == {"active": 0, "fired": 2} and body["as_of"] == "2026-10-15"
    assert {d["status"] for d in world.db.alerts.docs} == {"fired"}
    writes = world.db.alerts.writes
    alerts(api)
    assert world.db.alerts.writes == writes                            # firing is recorded once


def test_alert_status_filter_and_null_marks_on_failure(api, world):
    a1 = make_alert(api, level=150.0)
    make_alert(api, symbol="FIXB", condition="below", level=499.0)
    world.add("FIXB", bar("2026-10-13", 503, 498, 500))
    assert [a["symbol"] for a in alerts(api, status="fired")["alerts"]] == ["FIXB"]
    assert [a["id"] for a in alerts(api, status="active")["alerts"]] == [a1["id"]]
    r = api.get(ALERTS_URL, params={"status": "done"}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (422, "invalid_status")
    world.fail["FIXA"] = svc.daas_client.DaasError("unreachable")
    body = alerts(api)
    assert body["marks_error"] == "prices_unavailable" and body["checked_through"] is None
    active = [a for a in body["alerts"] if a["status"] == "active"][0]
    assert active["last_close"] is None and active["mark_error"] == "prices_unavailable"
    assert [a["status"] for a in body["alerts"]] == ["active", "fired"]   # stored alerts are still listed


def test_delete_an_alert_is_204_then_404(api, world):
    a = make_alert(api)
    r = api.delete(f"{ALERTS_URL}/{a['id']}", headers=A)
    assert r.status_code == 204 and r.content == b""
    assert world.db.alerts.docs == []
    r = api.delete(f"{ALERTS_URL}/{a['id']}", headers=A)
    assert (r.status_code, r.json()["detail"]) == (404, "alert_not_found")


# ── the evening script ───────────────────────────────────────────────────────
def _seed_two_users(api, world):
    ta = open_trade(api, A)
    tb = open_trade(api, B, symbol="FIXB", entry_price=500.0, stop_price=480.0, target_price=508.0)
    tc = open_trade(api, B, quantity=3, stop_price=90.0, target_price=None)
    aa = make_alert(api, A, symbol="FIXB", level=507.0)
    ab = make_alert(api, B, condition="below", level=80.0)
    world.add("FIXA", bar("2026-10-13", 103, 94.5, 97))
    world.add("FIXB", bar("2026-10-13", 509, 499, 507))
    return ta, tb, tc, aa, ab


def test_the_script_checks_every_user_once_and_a_rerun_changes_nothing(api, world):
    from scripts import check_desk_alerts as script

    ta, tb, tc, aa, ab = _seed_two_users(api, world)
    world.calls.clear()
    out = asyncio.run(script.run(world.db))
    assert out["ok"] is True and out["users"] == 2 and out["open_trades"] == 3 and out["active_alerts"] == 2
    assert (out["exits_stop"], out["exits_target"], out["alerts_fired"]) == (1, 1, 1)
    assert out["latest_session"] == "2026-10-13" and out["symbols_failed"] == []
    assert sorted(c["symbol"] for c in world.calls) == ["FIXA", "FIXB"]       # one read per symbol, all users
    docs = {d["_id"]: d for d in world.db.trades.docs}
    assert (docs[ta["id"]]["exit_reason"], docs[ta["id"]]["user_id"]) == ("stop", "user_a")
    assert (docs[tb["id"]]["exit_reason"], docs[tb["id"]]["exit_price"]) == ("target", 508.0)
    assert docs[tc["id"]]["status"] == "open"
    fired = {d["_id"]: d["status"] for d in world.db.alerts.docs}
    assert fired == {aa["id"]: "fired", ab["id"]: "active"}

    writes = world.db.trades.writes + world.db.alerts.writes
    again = asyncio.run(script.run(world.db))
    assert (again["exits_stop"], again["exits_target"], again["alerts_fired"]) == (0, 0, 0)
    assert world.db.trades.writes + world.db.alerts.writes == writes
    # What the script recorded is what the user then reads.
    row = [t for t in trades(api, A)["trades"] if t["id"] == ta["id"]][0]
    assert (row["status"], row["exit_session"]) == ("closed", "2026-10-13")


def test_the_script_dry_run_writes_nothing(api, world):
    from scripts import check_desk_alerts as script

    _seed_two_users(api, world)
    writes = world.db.trades.writes + world.db.alerts.writes
    out = asyncio.run(script.run(world.db, dry_run=True))
    assert (out["exits_stop"], out["exits_target"], out["alerts_fired"]) == (1, 1, 1)
    assert world.db.trades.writes + world.db.alerts.writes == writes
    assert {d["status"] for d in world.db.trades.docs} == {"open"}


def test_the_script_exit_codes(api, world, monkeypatch, caplog):
    import deps
    from scripts import check_desk_alerts as script

    caplog.set_level(logging.INFO)
    _seed_two_users(api, world)
    monkeypatch.setattr(deps, "db", world.db)
    monkeypatch.setattr("sys.argv", ["check_desk_alerts", "--dry-run"])
    assert script.main() == 0
    assert "exits stop=1 target=1" in caplog.text and "alerts fired=1" in caplog.text

    world.fail.update({s: svc.daas_client.DaasError("unreachable") for s in ("FIXA", "FIXB")})
    assert script.main() == 1                                  # nothing could be checked

    world.fail.clear()

    async def db_down(*_a, **_k):
        raise RuntimeError("mongo is down")

    monkeypatch.setattr(world.db.trades, "find", lambda q: type("C", (), {"to_list": db_down})())
    assert script.main() == 1


def test_the_script_with_nothing_to_check_is_ok(world):
    from scripts import check_desk_alerts as script

    out = asyncio.run(script.run(world.db))
    assert out["ok"] is True and out["symbols"] == 0 and world.calls == []


def test_responses_serialise_to_json(api, world):
    open_trade(api)
    make_alert(api)
    for body in (trades(api), alerts(api)):
        assert json.loads(json.dumps(body)) == body
