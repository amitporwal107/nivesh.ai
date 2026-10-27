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
from tests import mongo_ops
from tests.test_paper_account import mongo_expr  # noqa: F401  (re-exported for older importers)

TRADES_URL = "/api/desk/paper-trades"
ALERTS_URL = "/api/desk/alerts"
A = {"X-Test-User": "user_a"}
B = {"X-Test-User": "user_b"}
NOW = datetime(2026, 10, 12, 5, 0, tzinfo=timezone.utc)          # Monday 10:30 IST


# ── an in-memory Mongo collection ────────────────────────────────────────────
def _matches(doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
    """Mongo's filter semantics for the operators the desk and the risk reservation use (tests/mongo_ops.py)."""
    return mongo_ops.match(doc, query)


class _Cursor:
    def __init__(self, docs: List[Dict[str, Any]]):
        self._docs = docs

    def sort(self, key: str, direction: int) -> "_Cursor":
        def k(d):                      # numbers sort as numbers (a plan's version 10 after 9), anything else as text
            v = d.get(key)
            return (1, v, "") if isinstance(v, (int, float)) and not isinstance(v, bool) else (0, 0, str(v or ""))
        self._docs = sorted(self._docs, key=k, reverse=direction < 0)
        return self

    def limit(self, n: int) -> "_Cursor":
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length: Optional[int]) -> List[Dict[str, Any]]:
        return self._docs if length is None else self._docs[:length]


class _Result:
    def __init__(self, matched: int = 0, deleted: int = 0):
        self.matched_count = self.modified_count = matched
        self.deleted_count = deleted


def _in_partial(doc: Dict[str, Any], partial: Optional[Dict[str, Any]]) -> bool:
    """A partialFilterExpression the desk uses (services/desk_trading.ensure_indexes): {field: {"$type": "string"}}
    and plain equality {field: value}."""
    for key, cond in (partial or {}).items():
        if isinstance(cond, dict):
            assert cond == {"$type": "string"}, f"the fake collection does not know the partial filter {cond}"
            if not isinstance(doc.get(key), str):
                return False
        elif doc.get(key) != cond:
            return False
    return True


class FakeCollection:
    def __init__(self):
        self.docs: List[Dict[str, Any]] = []
        self.indexes: List[Any] = []
        self.unique: List[Any] = []          # (keys, partialFilterExpression) of the unique indexes asked for
        self.writes = 0

    async def create_index(self, keys, **kw):
        self.indexes.append(keys)
        if kw.get("unique"):
            # Modelled because the desk's duplicate and idempotency rules lean on Mongo refusing the second insert
            # when two requests race past the checks; a fake that accepted it would hide that path.
            self.unique.append((keys, kw.get("partialFilterExpression")))

    def find(self, query):
        return _Cursor([copy.deepcopy(d) for d in self.docs if _matches(d, query)])

    async def find_one(self, query):
        return next((copy.deepcopy(d) for d in self.docs if _matches(d, query)), None)

    async def count_documents(self, query):
        return sum(1 for d in self.docs if _matches(d, query))

    async def insert_one(self, doc):
        # A paper-account ledger row has no `_id` (Mongo assigns one); only a given `_id` can collide.
        if "_id" in doc and any(d.get("_id") == doc["_id"] for d in self.docs):
            raise DuplicateKeyError("E11000 duplicate key: _id")
        for keys, partial in self.unique:
            fields = [k for k, _ in keys]
            if _in_partial(doc, partial) and any(
                    _in_partial(d, partial) and all(d.get(f) == doc.get(f) for f in fields) for d in self.docs):
                raise DuplicateKeyError(f"E11000 duplicate key: {fields}")
        self.writes += 1
        self.docs.append(copy.deepcopy(doc))

    async def update_one(self, query, update, upsert=False):
        # $inc / $setOnInsert / upsert / $push ($each too: services/trade_lifecycle writes events so) / $pull / $max on
        # dotted paths are modelled (tests/mongo_ops.py) because the paper account keeps its cash, blocked funds and risk
        # reservation that way (services/paper_account). A fixture that cannot express them would fail every trade
        # create, which is a gap in the fixture, not the code.
        for d in self.docs:
            if _matches(d, query):
                self.writes += 1
                mongo_ops.apply(d, update)
                return _Result(matched=1)
        if upsert:
            doc: Dict[str, Any] = {k: v for k, v in query.items() if not k.startswith("$") and not isinstance(v, dict)}
            mongo_ops.apply(doc, update, inserting=True)
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
                     _acct.ACCOUNTS: FakeCollection(), _acct.LEDGER: FakeCollection(),
                     # the evening script's lease and heartbeat (services/job_runs)
                     "job_runs": FakeCollection(), "job_locks": FakeCollection(),
                     # the universal risk service: the profile, its audit and the journal the risk book reads
                     "risk_profiles": FakeCollection(), "risk_profile_audit": FakeCollection(),
                     "trade_journal": FakeCollection(), "live_authorizations": FakeCollection(),
                     # canonical TradePlans (services/strategy_plan/trade_plan.py) a paper trade may cite
                     "trade_plans": FakeCollection()}

    def __getitem__(self, name: str) -> FakeCollection:
        assert name in self.cols, f"the desk touched db[{name!r}]"
        return self.cols[name]

    @property
    def trades(self) -> FakeCollection:
        return self.cols[svc.TRADES]

    @property
    def alerts(self) -> FakeCollection:
        return self.cols[svc.ALERTS]


def bar(day: str, high: Optional[float], low: Optional[float], close: Optional[float], series: str = "EQ",
        volume: float = 1_000_000) -> Dict[str, Any]:
    """One row the way GET /v1/prices/eod/{symbol} sends it (row_to_dict of nidp.prices_eod). MOCK volume 10 lakh
    shares (was 1,000): the risk service's liquidity rule caps a position at 5% of the average traded value."""
    return {"as_of_date": day, "symbol": None, "series": series, "isin": None, "prev_close": None,
            "open_price": None, "high_price": high, "low_price": low, "close_price": close,
            "volume": volume, "turnover": None, "trades": None, "deliv_qty": None, "deliv_pct": None}


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
    # MOCK: the mechanics suites run under the loosest allowed risk profile (tests/risk_helpers.py)
    from tests.risk_helpers import loose_profile_doc
    w.db.cols["risk_profiles"].docs.extend(loose_profile_doc(u) for u in ("user_a", "user_b"))
    return w


@pytest.fixture
def api(world) -> TestClient:
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app)


def trade_body(**over) -> Dict[str, Any]:
    # MOCK. On Rs 1,000 of notional the Rs 20-a-side brokerage makes reward:risk after costs 0.49: the owner's default
    # profile refuses it, which is why this mechanics suite runs under tests/risk_helpers.loose_profile_doc.
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
    world.add("M&M", bar("2026-10-09", 103, 97, 101))           # MOCK: the session the at-once entry is checked against
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
    # No mark is made up on create. The bars are read once, only to check that an at-once entry is a price the last
    # completed session traded (the fill model, paper_fills_pnl TESTCASES FM-1); before that check, nothing was read.
    assert t["last_close"] is None and t["unrealized_pnl_rs"] is None and t["realized_pnl_rs"] is None
    assert body["price_basis"] == "end of day" and "nidp.prices_eod" in body["source"]
    # Read twice: the at-once range check, and the risk service's own server-side read of the last close (Phase 1).
    assert [c["symbol"] for c in world.calls] == ["M&M", "M&M"]
    [stored] = world.db.trades.docs
    assert stored["_id"] == t["id"] and stored["user_id"] == "user_a" and len(t["id"]) == 36
    # The two unique partial indexes behind the duplicate and idempotency rules (TESTCASES I-13).
    assert world.db.trades.indexes == [[("user_id", 1), ("status", 1)], [("status", 1), ("symbol", 1)],
                                       [("user_id", 1), ("idempotency_key", 1)], [("user_id", 1), ("open_key", 1)]]
    assert world.db.trades.unique == [([("user_id", 1), ("idempotency_key", 1)], {"idempotency_key": {"$type": "string"}}),
                                      ([("user_id", 1), ("open_key", 1)], {"open_key": {"$type": "string"}, "status": "open"})]
    assert world.db.alerts.indexes == [[("user_id", 1), ("status", 1)], [("status", 1), ("symbol", 1)]]
    assert stored["open_key"] == "cash:M&M" and "idempotency_key" not in stored        # no key was sent


def test_a_trade_without_a_target_is_refused_by_the_risk_policy(api, world):
    """Phase 1 behaviour change: the validator still accepts a null target, but the universal risk service needs one to
    check reward against risk (min_reward_risk), so the entry is refused with target_required and nothing is written."""
    r = api.post(TRADES_URL, json=trade_body(target_price=None), headers=A)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "risk_blocked"
    assert "target_required" in [x["code"] for x in r.json()["detail"]["reasons"]]
    body = trade_body(symbol="FIXB", entry_price=500.0, stop_price=480.0)
    del body["target_price"]
    assert api.post(TRADES_URL, json=body, headers=A).status_code == 409
    assert world.db.trades.docs == []


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


def test_the_open_position_limit_now_comes_first_and_is_per_user(api, world):
    """Phase 1: every account is held to the governor's 10 open positions on every path (services/risk_gate/service.py),
    so the 100-trade cap below is a backstop the route no longer reaches. 10 positions on record (different symbols)
    make the 11th a refusal with MAX_POSITIONS; another user is unaffected; a closed one frees a slot."""
    for i in range(10):
        world.db.trades.docs.append({**svc.new_trade("user_a", trade_body(symbol=f"FX{i}"), NOW), "_id": f"t{i}"})
        world.rows[f"FX{i}"] = copy.deepcopy(HISTORY["FIXA"])          # MOCK marks, so equity is known
    r = api.post(TRADES_URL, json=trade_body(), headers=A)
    assert r.status_code == 409 and "MAX_POSITIONS" in [x["code"] for x in r.json()["detail"]["reasons"]]
    assert len(world.db.trades.docs) == 10
    assert api.post(TRADES_URL, json=trade_body(), headers=B).status_code == 201       # per user
    world.db.trades.docs[0]["status"] = "closed"                                        # closed ones do not count
    assert api.post(TRADES_URL, json=trade_body(), headers=A).status_code == 201


def test_the_open_trade_backstop_gives_the_reservation_back(api, world, monkeypatch):
    """The 100-trade cap (here 1) still answers 409 open_trade_limit, and the reservation the risk service took for the
    refused trade is given back: no funds and no risk stay reserved."""
    monkeypatch.setattr(svc, "MAX_OPEN_TRADES", 1)
    world.db.trades.docs.append({**svc.new_trade("user_a", trade_body(symbol="FX0"), NOW), "_id": "t0"})
    world.rows["FX0"] = copy.deepcopy(HISTORY["FIXA"])                  # MOCK marks, so equity is known
    r = api.post(TRADES_URL, json=trade_body(), headers=A)
    assert (r.status_code, r.json()["detail"]) == (409, "open_trade_limit")
    (acct_doc,) = world.db.cols["paper_accounts"].docs
    assert acct_doc["blocked_rs"] == 0 and acct_doc.get("open_risk_rs", 0) == 0 and acct_doc["reservations"] == []
    assert len(world.db.trades.docs) == 1


# ── GET /paper-trades: marks and the exit rule ───────────────────────────────
def test_list_marks_open_trades_at_the_last_end_of_day_close(api, world):
    t = open_trade(api)
    world.calls.clear()                  # the create's own read (the at-once entry check); this test counts the list's
    body = trades(api)
    [row] = body["trades"]
    assert row["id"] == t["id"] and row["status"] == "open"
    assert row["last_close"] == 101.0 and row["last_close_date"] == "2026-10-12"
    assert row["unrealized_pnl_rs"] == 10.0 and row["realized_pnl_rs"] is None
    assert row["checked_through"] is None            # opened on 2026-10-12 (IST): no session after it yet
    assert row["mark_error"] is None
    assert body["as_of"] == "2026-10-12" and body["checked_through"] == "2026-10-12"
    assert body["marks_error"] is None and body["price_basis"] == "end of day"
    # Under the desk cost card (desk-cost-v2) by hand: buy 100 x 10 = 20 + 1.00 STT + 0.03 exch + 0.15 stamp + 3.61 GST
    # + 0.50 slippage = 25.29; sell 101 x 10 = 20 + 1.01 + 0.03 + 3.61 + 0.51 = 25.16; 50.45 (41.00 flat, before).
    costs = 50.45
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
    # A trade with no target can only be on record from before Phase 1 (the risk policy now needs one), so it is seeded.
    world.db.trades.docs.append(svc.new_trade("user_a", trade_body(target_price=None), world.now))
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
    # 1210 (was 1200): an at-once entry must be inside the last completed session's range, 7 Oct 1203.50–1220.80.
    open_trade(api, symbol="RELIANCE", entry_price=1210.0, stop_price=1150.0, target_price=1250.0)
    [row] = trades(api)["trades"]
    assert row["status"] == "open" and row["checked_through"] == "2026-10-13"
    assert row["last_close"] == 1166.7 and row["last_close_date"] == "2026-10-13"
    assert row["unrealized_pnl_rs"] == round((1166.7 - 1210.0) * 10, 2)
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
    # The route now refuses a second open trade in one symbol; two can still be on record (written before that rule,
    # like staging's ICICIBANK x2, or by the AI trader), and the list must read them once.
    world.db.trades.docs.append(svc.new_trade("user_a", trade_body(quantity=5), world.now))
    world.now = datetime(2026, 10, 20, 6, 0, tzinfo=timezone.utc)
    # MOCK: the sessions up to the 19th, so the risk service's last close is fresh on the 20th (else last_close_stale).
    world.add("FIXA", bar("2026-10-19", 102, 99, 101))
    world.add("FIXB", bar("2026-10-19", 506, 498, 502))
    open_trade(api, symbol="FIXB", entry_price=500.0, stop_price=480.0, target_price=560.0)
    world.calls.clear()
    body = trades(api)
    assert sorted((c["symbol"], c["start"]) for c in world.calls) == [("FIXA", "2026-09-28"), ("FIXB", "2026-10-06")]
    assert [t["symbol"] for t in body["trades"]] == ["FIXB", "FIXA", "FIXA"]          # newest first
    assert body["summary"]["unrealized_pnl_rs"] == 10.0 + 5.0 + 20.0


def test_every_page_is_read_so_an_early_stop_is_not_missed(api, world, monkeypatch):
    monkeypatch.setattr(svc, "PAGE_LIMIT", 2)
    open_trade(api)
    world.calls.clear()                  # the create's own read (the at-once entry check)
    world.add("FIXA", bar("2026-10-13", 103, 94, 97), bar("2026-10-14", 99, 96, 98), bar("2026-10-15", 99, 96, 98))
    [row] = trades(api)["trades"]
    assert (row["status"], row["exit_session"]) == ("closed", "2026-10-13")
    # Pages of 2 rows, newest first; a full last page is followed by one empty read, as the real envelope says.
    assert [c["offset"] for c in world.calls] == [0, 2, 4, 6]


def test_when_the_data_platform_fails_the_list_still_answers_with_null_marks(api, world):
    open_trade(api)
    open_trade(api, symbol="FIXB", entry_price=500.0, stop_price=480.0, target_price=560.0)
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
    world.calls.clear()                  # the create's own read (the at-once entry check)
    world.configured = False
    body = trades(api)
    assert body["marks_error"] == "prices_unavailable" and body["trades"][0]["unrealized_pnl_rs"] is None
    assert world.calls == []


def test_a_symbol_the_platform_has_no_prices_for_says_so(api, world):
    # Stored directly: the route now refuses an at-once entry it cannot check (entry_unverifiable); a trade recorded
    # before that check, or whose symbol's bars later vanish, must still list honestly.
    world.db.trades.docs.append(svc.new_trade("user_a", trade_body(symbol="FIXNONE"), world.now))
    body = trades(api)
    assert body["trades"][0]["mark_error"] == "no_prices_for_symbol" and body["trades"][0]["last_close"] is None
    assert body["marks_error"] is None and body["as_of"] is None


def test_the_status_filter_lists_one_kind_but_the_summary_covers_all(api, world):
    open_trade(api)
    t2 = open_trade(api, symbol="FIXB", entry_price=500.0, stop_price=480.0, target_price=560.0)
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
    t = svc.new_trade("user_a", trade_body(symbol="FIXNONE"), world.now)       # stored directly, as in the test above
    world.db.trades.docs.append(t)
    t["id"] = t["_id"]
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
    tc = open_trade(api, B, quantity=3, stop_price=90.0, target_price=130.0)
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
