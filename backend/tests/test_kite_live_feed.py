"""Kite live quote feed: lease, cadence clamp, token states, ws -> rest fallback, REST batching, final snapshot,
read-only guarantee, no token in logs, staleness, and the /api/live routes.

No network, no Mongo, no Kite: the Kite client, the ticker, Mongo and the clock are fakes (MOCK -- not real data).
The fake quote shapes follow what kite.quote() returned in a read-only smoke test on 2026-10-21. What these tests
cannot show is Kite's real WebSocket behaviour; that is UNVERIFIED here (see test_reports/OVERRIDE_kite_live_feed.md).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

from routes import live_quotes
from services.kite_live_feed import config as cfg
from services.kite_live_feed import feed as feed_mod
from services.kite_live_feed import gateway as gw
from services.kite_live_feed import universe as uni
from services.kite_live_feed.feed import LiveFeed, make_quote

IST = cfg.IST
OPEN_NOW = datetime(2026, 10, 20, 14, 32, 5, tzinfo=IST)     # a Tuesday, mid-session
AFTER_CLOSE = datetime(2026, 10, 20, 15, 45, 0, tzinfo=IST)
TOKEN = "tok-SECRET-1234567890"
TOKEN2 = "tok-SECRET-ABCDEFGHIJ"


# ── fakes ────────────────────────────────────────────────────────────────────

def _match(doc, flt):
    for k, v in flt.items():
        if k == "$or":
            if not any(_match(doc, f) for f in v):
                return False
        elif isinstance(v, dict) and any(o.startswith("$") for o in v):
            x = doc.get(k)
            for op, y in v.items():
                if op == "$ne":
                    if x == y:
                        return False
                    continue
                if x is None or not {"$gt": x > y, "$gte": x >= y, "$lt": x < y, "$lte": x <= y}[op]:
                    return False
        elif doc.get(k) != v:
            return False
    return True


class Res:
    def __init__(self, matched=0, upserted=None):
        self.matched_count, self.upserted_id = matched, upserted


class Coll:
    def __init__(self):
        self.docs: Dict[Any, dict] = {}
        self.indexes: List[tuple] = []

    def find(self, flt=None, proj=None):
        rows = [d for d in self.docs.values() if _match(d, flt or {})]

        class Cur:
            async def to_list(self, length=None):
                return [dict(r) for r in rows]
        return Cur()

    async def find_one(self, flt, proj=None):
        for d in self.docs.values():
            if _match(d, flt):
                out = dict(d)
                if proj and proj.get("_id") == 0:
                    out.pop("_id", None)
                return out
        return None

    async def update_one(self, flt, upd, upsert=False):
        for d in self.docs.values():
            if _match(d, flt):
                d.update(upd.get("$set", {}))
                for k, n in upd.get("$inc", {}).items():
                    d[k] = d.get(k, 0) + n
                return Res(matched=1)
        if not upsert:
            return Res()
        _id = flt.get("_id")
        if _id in self.docs:
            raise DuplicateKeyError("E11000 duplicate key")
        self.docs[_id] = {"_id": _id, **upd.get("$set", {})}
        return Res(upserted=_id)

    async def insert_one(self, doc):
        if doc["_id"] in self.docs:
            raise DuplicateKeyError("E11000 duplicate key")
        self.docs[doc["_id"]] = dict(doc)

    async def replace_one(self, flt, doc, upsert=False):
        self.docs[flt["_id"]] = dict(doc)
        return Res(matched=1)

    async def create_index(self, *a, **k):
        self.indexes.append((a, k))


class FakeDB:
    def __init__(self):
        self.cols: Dict[str, Coll] = {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, Coll())

    def __getattr__(self, name):
        if name.startswith("_") or name == "cols":
            raise AttributeError(name)
        return self[name]


class TokenException(Exception):       # same class name kiteconnect uses -> classify() = AUTH_EXPIRED
    pass


class Clock:
    def __init__(self, now=OPEN_NOW):
        self.now = now

    def __call__(self):
        return self.now

    async def sleep(self, s):
        self.slept.append(s)
        self.now += timedelta(seconds=s)

    slept: List[float] = []


NSE = ([{"segment": "INDICES", "tradingsymbol": "NIFTY 50", "instrument_token": 256265, "instrument_type": "EQ"},
        {"segment": "INDICES", "tradingsymbol": "NIFTY BANK", "instrument_token": 260105, "instrument_type": "EQ"},
        {"segment": "INDICES", "tradingsymbol": "NIFTY50 PR 2X LEV", "instrument_token": 9, "instrument_type": "EQ"}]
       + [{"segment": "NSE", "tradingsymbol": s, "instrument_token": 1000 + i, "instrument_type": "EQ"}
          for i, s in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE"])])
NFO = [{"name": "AAA", "instrument_type": "FUT"}, {"name": "EEE", "instrument_type": "FUT"}, {"name": "AAA", "instrument_type": "CE"}]


class FakeKite:
    def __init__(self, token="", fail=None, rows=NSE, price=100.0):
        self.token, self.fail, self.rows, self.price = token, fail, rows, price
        self.quote_calls: List[List[str]] = []

    def instruments(self, ex):
        if self.fail:
            raise self.fail
        return self.rows if ex == "NSE" else NFO

    def quote(self, keys):
        if self.fail:
            raise self.fail
        self.quote_calls.append(list(keys))
        return {k: {"last_price": self.price, "ohlc": {"open": 99.0, "high": 101.0, "low": 98.0, "close": 98.0},
                    "volume": 1234, "oi": 0, "timestamp": datetime(2026, 10, 20, 14, 32, 4)} for k in keys}


class FakeTicker:
    """Stands in for TickerSource's KiteTicker. Calling connect() does nothing: tests drive the callbacks."""
    instances: List["FakeTicker"] = []

    def __init__(self, key, token):
        self.args = (key, token)
        self.subscribed: List[int] = []
        FakeTicker.instances.append(self)

    def connect(self, threaded=False): pass
    def subscribe(self, t): self.subscribed += list(t)
    def unsubscribe(self, t): pass
    def set_mode(self, m, t): pass
    def close(self): pass


def make_feed(db=None, *, token=TOKEN, kite=None, clock=None, ticker=FakeTicker, holder="h1", cadence=5, force_rest=True, **kw):
    clock = clock or Clock()
    clock.slept = []
    holder_kite = kite or FakeKite()
    state = {"token": token}

    async def n500():
        return ["AAA", "BBB", "CCC", "ZZZ-UNKNOWN"]

    async def hol(day):
        return set()

    f = LiveFeed(db or FakeDB(), holder=holder, clock=clock, sleep=clock.sleep, cadence=cadence,
                 token_getter=lambda: state["token"], key_getter=lambda: "api-key-PUBLIC",
                 kite_factory=lambda k, t: holder_kite, ticker_factory=lambda k, t: ticker(k, t),
                 load_holidays=hol, load_nifty500=n500, force_rest=force_rest, **kw)
    f._state, f._kite_obj, f._clock = state, holder_kite, clock
    return f


def run(coro):
    return asyncio.run(coro)


# ── config ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,want", [(None, 30), ("5", 5), ("1", 2), ("0", 2), ("1000", 120), ("12", 12), ("abc", 30), ("2.9", 2)])
def test_cadence_is_clamped_to_2_120_default_30(raw, want):
    env = {} if raw is None else {cfg.CADENCE_ENV: raw}
    assert cfg.cadence_seconds(env) == want


def test_enabled_switch():
    assert cfg.enabled({}) is True
    for off in ("0", "false", "OFF", "no"):
        assert cfg.enabled({cfg.ENABLED_ENV: off}) is False


def test_api_key_file_reads_line_one_only(tmp_path, monkeypatch):
    p = tmp_path / "k"
    p.write_text("PUBLIC-KEY-LINE\nTHE-SECRET-LINE\n")
    monkeypatch.delenv("KITE_API_KEY", raising=False)
    monkeypatch.setenv("KITE_API_KEY_FILE", str(p))
    assert cfg.get_api_key() == "PUBLIC-KEY-LINE"


def test_default_token_reads_file_named_by_env(tmp_path, monkeypatch):
    p = tmp_path / "t"
    p.write_text(" file-token \n")
    monkeypatch.setenv("KITE_ACCESS_TOKEN_FILE", str(p))
    from helpers import secrets
    monkeypatch.setattr(secrets, "get", lambda k: "")
    from services.providers.kite_adapter import default_token
    assert default_token() == "file-token"


def test_session_clock():
    assert cfg.session_of(OPEN_NOW, set())[0] == "open"
    assert cfg.session_of(AFTER_CLOSE, set()) == ("closed", "after_hours")
    assert cfg.session_of(OPEN_NOW, {OPEN_NOW.date()}) == ("closed", "holiday")
    assert cfg.session_of(datetime(2026, 10, 24, 11, 0, tzinfo=IST), set()) == ("closed", "weekend")


# ── quotes ───────────────────────────────────────────────────────────────────

def test_make_quote_null_never_zero():
    assert make_quote("A", 0, {}, 1, 0, None, OPEN_NOW) is None
    assert make_quote("A", None, {}, 1, 0, None, OPEN_NOW) is None
    q = make_quote("A", 110.0, {"close": 100.0, "open": 99}, 5, 0, datetime(2026, 10, 20, 14, 0), OPEN_NOW)
    assert q["change"] == 10.0 and q["change_pct"] == 10.0 and q["oi"] is None and q["ts"].endswith("+05:30")
    no_close = make_quote("A", 110.0, {"close": 0}, 5, 0, None, OPEN_NOW)
    assert no_close["change"] is None and no_close["change_pct"] is None


# ── lease ────────────────────────────────────────────────────────────────────

def test_only_one_leader_and_takeover_after_expiry():
    db, clock = FakeDB(), Clock()
    a = make_feed(db, holder="A", clock=clock)
    b = make_feed(db, holder="B", clock=clock)
    assert run(a.tick())["leader"] is True
    assert run(b.tick())["leader"] is False
    assert b._kite_obj.quote_calls == []                       # a follower never reads Kite
    clock.now += timedelta(seconds=feed_mod.LEASE_TTL_SECONDS + 1)
    assert run(b.tick())["leader"] is True                     # A stopped renewing
    assert run(a.tick())["leader"] is False


# ── token states ─────────────────────────────────────────────────────────────

def test_missing_token_is_a_state_not_a_crash_then_recovers():
    f = make_feed(token="")
    out = run(f.tick())
    assert out["leader"] and f.state == "not_connected"
    assert f._kite_obj.quote_calls == []
    f._clock.now += timedelta(seconds=31)
    f._state["token"] = TOKEN
    run(f.tick())
    assert f.state == "live" and f.snapshot["count"] > 0


def test_expired_token_backs_off_and_rereads_token():
    kite = FakeKite(fail=TokenException("Incorrect `api_key` or `access_token`."))
    f = make_feed(kite=kite)
    run(f.tick())
    assert f.state == "expired"
    calls_before = len(kite.quote_calls)
    f._clock.now += timedelta(seconds=5)
    run(f.tick())                                              # inside the backoff: no new Kite call
    assert f.state == "expired"
    f._clock.now += timedelta(seconds=31)
    run(f.tick())                                              # same token still expired: no call, still expired
    assert f.state == "expired" and len(kite.quote_calls) == calls_before
    kite.fail = None                                           # the human renews the token
    f._state["token"] = TOKEN2
    run(f.tick())
    assert f.state == "live" and f._fp == cfg.fingerprint(TOKEN2)


def test_rate_limit_backs_off_exponentially_and_snapshot_survives():
    kite = FakeKite()
    f = make_feed(kite=kite)
    run(f.tick())
    good = f.snapshot
    kite.fail = RuntimeError("Too many requests")
    f._clock.now += timedelta(seconds=6)
    run(f.tick())
    assert f.state == "error" and f.snapshot is good
    first = (f._next_try - f._clock.now).total_seconds()
    kite.fail = None
    f._clock.now = f._next_try + timedelta(seconds=1)
    run(f.tick())
    assert f.state == "live" and first >= 10


# ── ws -> rest fallback ──────────────────────────────────────────────────────

def test_rest_is_used_when_ws_forced_off():
    f = make_feed(force_rest=True)
    run(f.tick())
    assert f.source == "rest" and f._kite_obj.quote_calls


def test_websocket_that_cannot_start_falls_back_to_rest():
    class Boom(FakeTicker):
        def connect(self, threaded=False):
            raise OSError("no route")
    f = make_feed(force_rest=False, ticker=Boom)
    run(f.tick())
    assert f.source == "rest" and f.state == "live" and f._ticker is None
    assert f.snapshot["source"] == "rest"


def test_silent_websocket_is_not_trusted_and_ticks_make_it_the_source():
    FakeTicker.instances.clear()
    f = make_feed(force_rest=False)
    run(f.tick())
    assert f.source == "rest" and f._ticker is not None        # connecting: REST carries the feed
    t = f._ticker
    t._connect(None)                                           # the socket connects ...
    assert f._ticker.healthy()
    tick = {"instrument_token": 1000, "last_price": 123.5, "ohlc": {"open": 1, "high": 2, "low": 1, "close": 120.0},
            "volume_traded": 77, "exchange_timestamp": datetime(2026, 10, 20, 14, 32, 6)}
    t._ticks(None, [tick, {"instrument_token": 424242, "last_price": 1.0}])    # unknown token is ignored
    f._clock.now += timedelta(seconds=5)
    n_rest = len(f._kite_obj.quote_calls)
    run(f.tick())
    assert f.source == "ws" and len(f._kite_obj.quote_calls) == n_rest
    q = {x["symbol"]: x for x in f.snapshot["quotes"]}["AAA"]
    assert q["ltp"] == 123.5 and q["change"] == 3.5 and q["volume"] == 77
    assert 1000 in FakeTicker.instances[0].subscribed and 256265 in FakeTicker.instances[0].subscribed
    t.last_tick = t.last_event = t.last_tick - 100             # ... then goes silent
    f._ticker.last_tick = f._ticker.last_event = 0.0
    f._clock.now += timedelta(seconds=5)
    run(f.tick())
    assert f.source == "rest"


def test_ticker_token_refusal_marks_expired():
    f = make_feed(force_rest=False)
    run(f.tick())
    f._ticker._error(None, 403, "Forbidden: invalid token")
    f._clock.now += timedelta(seconds=5)
    run(f.tick())
    assert f.state == "expired" and f._ticker is None


# ── REST batching ────────────────────────────────────────────────────────────

def test_rest_batches_are_at_most_500_and_spaced():
    rows = [{"segment": "INDICES", "tradingsymbol": "NIFTY 50", "instrument_token": 1, "instrument_type": "EQ"}]
    syms = [f"S{i}" for i in range(1700)]
    rows += [{"segment": "NSE", "tradingsymbol": s, "instrument_token": 10 + i, "instrument_type": "EQ"} for i, s in enumerate(syms)]
    kite = FakeKite(rows=rows)
    f = make_feed(kite=kite, cadence=30)

    async def n500():
        return syms
    f.load_nifty500 = n500
    run(f.tick())
    assert all(len(c) <= cfg.REST_BATCH for c in kite.quote_calls)
    assert len(kite.quote_calls) == 4 and f._clock.slept.count(1.1) == 3 or all(s >= 1.1 for s in f._clock.slept)
    assert all(s >= cfg.REST_SPACING_SECONDS for s in f._clock.slept)
    assert f.snapshot["count"] == 1701


def test_five_second_cadence_rotates_through_a_large_universe():
    rows = [{"segment": "NSE", "tradingsymbol": f"S{i}", "instrument_token": 10 + i, "instrument_type": "EQ"} for i in range(2500)]
    kite = FakeKite(rows=rows)
    f = make_feed(kite=kite, cadence=5)

    async def n500():
        return [f"S{i}" for i in range(2500)]
    f.load_nifty500 = n500
    run(f.tick())
    first = {k for c in kite.quote_calls for k in c}
    assert len(kite.quote_calls) == 4 and len(first) == 2000   # 4 batches fit in 5 s at 1.1 s spacing
    f._clock.now += timedelta(seconds=5)
    run(f.tick())
    assert f.snapshot["count"] == 2500                         # the rotation covered the rest on the next pass


# ── wanted symbols ───────────────────────────────────────────────────────────

def test_requested_symbols_join_the_universe_with_priority():
    db = FakeDB()
    f = make_feed(db)
    run(f.request_symbols(["nse:eee", "NOPE"]))
    run(f.tick())
    assert "EEE" in f.sets["wanted"] and "NOPE" in f.unresolved
    assert "EEE" in {q["symbol"] for q in f.snapshot["quotes"]}
    assert "NIFTY50 PR 2X LEV" not in f.sets["indices"]


# ── after the close ──────────────────────────────────────────────────────────

def test_one_final_snapshot_after_close_then_idle():
    clock = Clock(AFTER_CLOSE)
    f = make_feed(clock=clock)
    run(f.tick())
    assert f.snapshot["final"] is True and f.state == "market_closed"
    n = len(f._kite_obj.quote_calls)
    clock.now += timedelta(seconds=15)
    run(f.tick())
    run(f.tick())
    assert len(f._kite_obj.quote_calls) == n                   # nothing more is read until the next open


def test_closing_snapshot_uses_kites_own_close_and_is_served_as_the_final_market_close():
    clock = Clock(AFTER_CLOSE)
    f = make_feed(clock=clock)
    run(f.tick())
    snap = f.snapshot
    q = {x["symbol"]: x for x in snap["quotes"]}["AAA"]
    assert snap["final"] is True and snap["session"] == "closed"
    assert q["close"] == 98.0 and q["change"] == 2.0 and q["change_pct"] == pytest.approx(2.0408, abs=1e-3)   # vs Kite's own previous close, not the warehouse's
    now = AFTER_CLOSE.astimezone(timezone.utc) + timedelta(hours=2)
    body = live_quotes.build_payload(snap, {"state": "market_closed", "session": "closed", "cadence_seconds": 30}, ["AAA"], now)
    assert body["mode"] == "closed" and body["final"] is True and body["stale"] is False        # hours old is fine once the market is closed
    assert body["quotes"]["AAA"]["ts"].startswith("2026-10-20T14:32")                          # the quote's own exchange stamp is carried
    assert body["data_at"] == snap["data_at"] and body["missing"] == []


def test_no_read_inside_the_first_minute_after_close_and_none_stops_the_ticker():
    clock = Clock(datetime(2026, 10, 20, 15, 30, 20, tzinfo=IST))
    f = make_feed(clock=clock)
    run(f.tick())
    assert f._kite_obj.quote_calls == []


# ── read-only and secrets ────────────────────────────────────────────────────

def test_gateway_exposes_no_order_surface():
    names = {n for n in dir(gw.ReadOnlyKite) if not n.startswith("_")}
    assert names == {"instruments", "quote", "profile", "historical_data"}


def test_no_order_method_is_referenced_in_the_package_or_routes():
    bad = re.compile(r"place_order|modify_order|cancel_order|place_gtt|modify_gtt|delete_gtt|convert_position|exit_order|"
                     r"\.orders\(|\.trades\(|\.positions\(|\.holdings\(|\.margins\(|order_margins|invalidate_access_token")
    root = Path(feed_mod.__file__).parent
    for p in list(root.glob("*.py")) + [Path(live_quotes.__file__)]:
        assert not bad.search(p.read_text()), p.name
        # generate_session is the daily login's request_token exchange (no order power); it lives in platform_token.py only
        assert ("generate_session" in p.read_text()) == (p.name == "platform_token.py"), p.name


def test_token_and_key_never_reach_the_logs(caplog):
    caplog.set_level(logging.DEBUG)
    kite = FakeKite(fail=TokenException(f"bad {TOKEN}"))
    f = make_feed(kite=kite, force_rest=False)
    run(f.tick())
    kite.fail = RuntimeError("boom")
    f._clock.now += timedelta(seconds=40)
    f._expired_fp = ""
    f._next_try = None
    run(f.tick())
    f._state["token"] = ""
    f._clock.now += timedelta(seconds=400)
    run(f.tick())
    text = "\n".join(r.getMessage() + str(r.exc_info) for r in caplog.records)
    assert TOKEN not in text and "api-key-PUBLIC" not in text
    doc = json.dumps(f._status_doc(f._clock.now), default=str)
    assert TOKEN not in doc and "api-key-PUBLIC" not in doc


# ── payload staleness ────────────────────────────────────────────────────────

def _snap(data_at, quotes=None):
    return {"as_of": data_at.isoformat(), "data_at": data_at.isoformat(), "session": "open", "source": "rest", "final": False,
            "quotes": quotes if quotes is not None else [make_quote("AAA", 10.0, {"close": 9.0}, 1, 0, None, data_at)]}


def test_payload_fresh_stale_closed_and_missing():
    now = OPEN_NOW.astimezone(timezone.utc)
    st = {"state": "live", "session": "open", "cadence_seconds": 5}
    fresh = live_quotes.build_payload(_snap(now - timedelta(seconds=4)), st, ["AAA", "NOPE"], now)
    assert fresh["mode"] == "live" and fresh["stale"] is False and fresh["age_seconds"] == 4.0
    assert fresh["missing"] == ["NOPE"] and "NOPE" not in fresh["quotes"] and fresh["quotes"]["AAA"]["ltp"] == 10.0
    old = live_quotes.build_payload(_snap(now - timedelta(seconds=40)), st, None, now)
    assert old["mode"] == "delayed" and old["stale"] is True and old["stale_after_seconds"] == 12.5      # 2.5 x 5 s
    st30 = {"state": "live", "session": "open", "cadence_seconds": 30}
    mid = live_quotes.build_payload(_snap(now - timedelta(seconds=70)), st30, None, now)
    assert mid["mode"] == "live" and mid["stale"] is False and mid["stale_after_seconds"] == 75 and mid["cadence_seconds"] == 30
    assert live_quotes.build_payload(_snap(now - timedelta(seconds=80)), st30, None, now)["mode"] == "delayed"
    closed = live_quotes.build_payload(_snap(now - timedelta(hours=3)), {"state": "market_closed", "session": "closed"}, None, now)
    assert closed["mode"] == "closed" and closed["stale"] is False
    assert live_quotes.build_payload(None, None, None, now)["mode"] in ("not_connected", "disabled")
    assert live_quotes.build_payload(None, {"state": "expired", "session": "open"}, None, now)["mode"] == "expired"


# ── routes ───────────────────────────────────────────────────────────────────

@pytest.fixture
def api(monkeypatch):
    f = make_feed(cadence=2)
    run(f.tick())
    f.clock = lambda: datetime.now(timezone.utc)
    f.snapshot["data_at"] = datetime.now(timezone.utc).isoformat()    # make "now" fresh for the route's age
    monkeypatch.setattr(live_quotes, "get_feed", lambda: f)

    async def fake_user(request: Request):
        return {"user_id": "u1"}
    monkeypatch.setattr(live_quotes, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(live_quotes.router)
    return TestClient(app), f


def test_routes_quotes_snapshot_status(api):
    c, f = api
    f.session = "open"
    r = c.get("/api/live/quotes", params={"symbols": "aaa,NSE:Nifty 50,NOPE"})
    assert r.status_code == 200
    b = r.json()
    assert set(b["quotes"]) == {"AAA", "NIFTY 50"} and b["missing"] == ["NOPE"] and b["read_only"] is True
    assert b["quotes"]["AAA"]["ltp"] == 100.0 and b["quotes"]["AAA"]["change_pct"] == pytest.approx(2.0408, abs=1e-3)
    assert c.get("/api/live/quotes", params={"symbols": ""}).status_code == 400
    assert c.get("/api/live/quotes", params={"symbols": ",".join(f"S{i}" for i in range(601))}).status_code == 400
    s = c.get("/api/live/snapshot", params={"universe": "indices"}).json()
    assert set(s["quotes"]) == {"NIFTY 50", "NIFTY BANK"}
    assert c.get("/api/live/snapshot", params={"universe": "bogus"}).status_code == 400
    assert len(c.get("/api/live/snapshot", params={"universe": "all"}).json()["quotes"]) == f.snapshot["count"]
    st = c.get("/api/live/status").json()
    assert st["state"] == "live" and st["source"] == "rest" and st["instrument_count"] == len(f.ordered) and "holder" not in st


def test_routes_require_sign_in(monkeypatch):
    from fastapi import HTTPException

    async def deny(request: Request):
        raise HTTPException(status_code=401, detail="no")
    monkeypatch.setattr(live_quotes, "get_current_user", deny)
    app = FastAPI()
    app.include_router(live_quotes.router)
    c = TestClient(app)
    for path in ("/api/live/status", "/api/live/quotes?symbols=A", "/api/live/snapshot", "/api/live/stream"):
        assert c.get(path).status_code == 401


def test_sse_stream_emits_snapshot_events(api, monkeypatch):
    c, f = api
    f.cadence = 0.01
    monkeypatch.setattr(live_quotes, "STREAM_MAX_SECONDS", 0.05)
    with c.stream("GET", "/api/live/stream", params={"symbols": "AAA"}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    events = [e for e in body.split("\n\n") if e.startswith("event: snapshot")]
    assert events
    data = json.loads(events[0].split("data: ", 1)[1])
    assert data["quotes"]["AAA"]["ltp"] == 100.0 and "as_of" in data and "stale" in data


def test_lease_outlives_the_gap_between_passes():
    assert make_feed(cadence=120)._lease_ttl == 255 and make_feed(cadence=5)._lease_ttl == feed_mod.LEASE_TTL_SECONDS


def test_universe_helpers():
    assert uni.index_symbols(NSE) == ["NIFTY 50", "NIFTY BANK"]
    assert uni.fno_underlyings(NFO) == ["AAA", "EEE"]
    assert gw.canon("NSE:Nifty Financial Services") == "NIFTY FIN SERVICE"
