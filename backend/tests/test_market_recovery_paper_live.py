"""Market Recovery › live paper trades: TC-P3 … TC-P7 of docs/market_recovery/DESIGN.md §10.

Runs on the desk suites' in-memory world (tests/test_desk_trading.py `world` / `api`, tests/test_desk_strategy_trades.py
`sworld`): the real desk route, risk gate, paper account and close writers; quotes are injected. The clock is the desk
suite's NOW, Monday 2026-10-12 10:30 IST (in the session). MOCK — not real data: FIXA / FIXU and every price below are made up.
"""
from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import feature_flags as ff
import feature_gate
from services import desk_trading as svc
from services import paper_account as acct
from services.kite_live_feed import day_quote
from services.market_recovery import paper_live as pl
from tests.test_desk_strategy_trades import EXPIRY, open_strategy, signal, sworld  # noqa: F401  (sworld is a fixture)
from tests.test_desk_trading import A, B, NOW, TRADES_URL, api, open_trade, trade_body, world  # noqa: F401  (fixtures)

TODAY = "2026-10-12"
LIVE_AT = "2026-10-12T04:59:00+00:00"
TAG = {"kind": "market_recovery", "bucket": "shares", "signal_date": "2026-10-09"}


def live(quotes: Dict[str, Dict[str, Any]], source: str = "kite_live", day: str = TODAY) -> Dict[str, Any]:
    return {"source": source, "day": day, "as_of": LIVE_AT, "quotes": quotes, "why": None}


def q(ltp: float, low: float = None, high: float = None) -> Dict[str, Any]:
    return {"ltp": ltp, "open": ltp, "low": low if low is not None else ltp, "high": high if high is not None else ltp,
            "close": ltp, "volume": 5000}


def readers(stock: Dict[str, Any], options: Dict[str, Any] = None, seen: Dict[str, Any] = None):
    async def s(symbols):
        if seen is not None:
            seen["symbols"] = list(symbols)
        return stock

    async def o(legs):
        if seen is not None:
            seen["legs"] = copy.deepcopy(legs)
        return options or {"available": False, "reason": "none", "quotes": {}}
    return s, o


# ── TC-P3 live entry on the desk ─────────────────────────────────────────────────────────────────────────────────

def _live_day(monkeypatch, answer):
    async def fake(symbols, **kw):
        return answer
    monkeypatch.setattr(day_quote, "day_quotes", fake)


def test_tc_p3_live_entry_inside_todays_live_range_is_filled(api, world, monkeypatch):
    # FIXA's last completed session (12 Oct bars, MOCK) is 94–104: 106 would be refused at once without a live price
    _live_day(monkeypatch, live({"FIXA": q(106.0, 102.0, 107.0)}))
    r = api.post(TRADES_URL, json=trade_body(entry_price=106.0, stop_price=101.0, target_price=116.0, source=TAG,
                                             price_source={"kind": "kite_live", "at": LIVE_AT}), headers=A)
    assert r.status_code == 201, r.text
    doc = world.db.trades.docs[0]
    assert doc["price_source"] == {"kind": "kite_live", "at": "2026-10-12T04:59:00+00:00"}
    assert doc["entry_range_checked"] == {"date": TODAY, "low": 102.0, "high": 107.0, "basis": "kite_live", "at": LIVE_AT}


def test_tc_p3_live_entry_refused_without_a_live_quote_of_today(api, world, monkeypatch):
    _live_day(monkeypatch, {"source": None, "day": TODAY, "as_of": None, "quotes": {}, "why": "feed_not_live"})
    r = api.post(TRADES_URL, json=trade_body(entry_price=106.0, stop_price=101.0, target_price=116.0,
                                             price_source={"kind": "kite_live", "at": LIVE_AT}), headers=A)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "entry_unverifiable"
    assert "feed_not_live" in r.json()["detail"]["message"] and world.db.trades.docs == []


def test_tc_p3_live_entry_outside_todays_range_is_refused(api, world, monkeypatch):
    _live_day(monkeypatch, live({"FIXA": q(106.0, 102.0, 107.0)}))
    r = api.post(TRADES_URL, json=trade_body(entry_price=110.0, stop_price=101.0, target_price=120.0,
                                             price_source={"kind": "kite_live", "at": LIVE_AT}), headers=A)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "entry_not_tradable"
    assert "today's range" in r.json()["detail"]["message"]


def test_tc_p3_without_price_source_the_end_of_day_rule_is_unchanged(api, world, monkeypatch):
    called = []

    async def fake(symbols, **kw):
        called.append(symbols)
        return live({"FIXA": q(106.0, 102.0, 107.0)})
    monkeypatch.setattr(day_quote, "day_quotes", fake)
    r = api.post(TRADES_URL, json=trade_body(entry_price=106.0, stop_price=101.0, target_price=116.0), headers=A)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "entry_not_tradable" and called == []
    assert open_trade(api, A)["symbol"] == "FIXA"                         # 100 inside 94–104: filled as before


@pytest.mark.parametrize("ps", [{"kind": "kite_live", "at": "2026-10-11T09:00:00+00:00"},      # yesterday (IST)
                                {"kind": "kite_live", "at": "2026-10-12T06:00:00+00:00"},      # after now
                                {"kind": "broker", "at": LIVE_AT}, {"kind": "kite_live"}])
def test_tc_p3_price_source_must_be_a_live_quote_of_today(api, world, monkeypatch, ps):
    _live_day(monkeypatch, live({"FIXA": q(106.0, 102.0, 107.0)}))
    r = api.post(TRADES_URL, json=trade_body(entry_price=106.0, stop_price=101.0, target_price=116.0, price_source=ps), headers=A)
    assert r.status_code == 422
    assert (r.json()["detail"] if isinstance(r.json()["detail"], str) else r.json()["detail"]["code"]) == "invalid_price_source"


# ── TC-P4 live marks and P&L ─────────────────────────────────────────────────────────────────────────────────────

def test_tc_p4_marks_shares_and_a_two_leg_structure(api, sworld):
    open_trade(api, A, source=TAG)                                        # FIXA 10 @ 100, Stop loss 95, Target 1 110
    open_strategy(api, signal=signal(source_refs=[{"kind": "market_recovery", "ref": "FIXU:bull_call_spread", "as_of": "2026-10-09"}]))
    seen: Dict[str, Any] = {}
    s, o = readers(live({"FIXA": q(103.0), "FIXU": q(1250.0)}),
                   {"available": True, "reason": None, "quotes": {"0": {"last_price": 52.0}, "1": {"last_price": 21.0}}}, seen)
    trades = sworld.db.trades.docs
    marked, market = asyncio.run(pl.read_marks(trades, stock_reader=s, option_reader=o))
    assert seen["symbols"] == ["FIXA", "FIXU"]
    assert seen["legs"] == [{"underlying": "FIXU", "expiry": EXPIRY, "strike": 1300.0, "kind": "option", "option_type": "call"},
                            {"underlying": "FIXU", "expiry": EXPIRY, "strike": 1360.0, "kind": "option", "option_type": "call"}]
    by = {m["trade"]["symbol"]: m for m in marked}
    assert by["FIXA"]["pnl_rs"] == 30.0 and by["FIXA"]["risk_rs"] == 50.0               # (103 − 100) × 10; (100 − 95) × 10
    # (52 − 40) × 250 − (21 − 15) × 250 = 3,000 − 1,500; capital at risk = what the trade reserved, (1360 − 1300) × 250
    assert by["FIXU"]["pnl_rs"] == 1500.0 and by["FIXU"]["risk_rs"] == 15000.0 and by["FIXU"]["live"] == 1250.0
    assert market == {"live": True, "source": "kite_live", "why": None, "as_of": LIVE_AT, "day": TODAY,
                      "options_live": True, "options_why": None}


def test_tc_p4_a_missing_quote_gives_no_pnl_never_an_older_price(api, sworld):
    open_strategy(api, signal=signal(source_refs=[{"kind": "market_recovery", "ref": "FIXU:x", "as_of": "2026-10-09"}]))
    s, o = readers(live({"FIXU": q(1250.0)}), {"available": True, "quotes": {"0": {"last_price": 52.0}}})
    [m], _ = asyncio.run(pl.read_marks(sworld.db.trades.docs, stock_reader=s, option_reader=o))
    assert m["pnl_rs"] is None and m["flags"] == ["no_live_quote"] and m["legs"] == [52.0, None]


# ── TC-P5 live exits ─────────────────────────────────────────────────────────────────────────────────────────────

def _book(world, stock, options=None):
    s, o = readers(stock, options)
    return asyncio.run(pl.live_book(world.db, "user_a", stock_reader=s, option_reader=o))


def test_tc_p5_shares_close_at_the_live_price_through_the_stop_loss(api, world):
    t = open_trade(api, A, source=TAG)
    blocked = asyncio.run(acct.read(world.db, "user_a"))["blocked_rs"]
    assert blocked > 0
    book = _book(world, live({"FIXA": q(94.0)}))
    assert book["closed_now"] == [t["id"]]
    stored = world.db.trades.docs[0]
    assert (stored["status"], stored["exit_reason"], stored["exit_price"], stored["realized_pnl_rs"]) == ("closed", "stop_live", 94.0, -60.0)
    assert "reached the Stop loss (95.00)" in stored["exit_note"] and stored["exit_session"] == TODAY
    assert asyncio.run(acct.read(world.db, "user_a"))["blocked_rs"] == 0.0              # the reservation came back
    [row] = book["trades"]
    assert row["status"] == "closed" and row["exit"]["reason"] == "stop_live" and book["totals"]["closed_today_count"] == 1


def test_tc_p5_shares_close_at_target_1(api, world):
    open_trade(api, A, source=TAG)
    _book(world, live({"FIXA": q(111.0)}))
    assert (world.db.trades.docs[0]["exit_reason"], world.db.trades.docs[0]["exit_price"]) == ("target_live", 111.0)


def test_tc_p5_no_close_without_live_quotes_and_untagged_trades_untouched(api, world):
    open_trade(api, A, source=TAG)
    book = _book(world, live({"FIXA": q(90.0)}, source="kite_close"))      # after the close: a mark, never a live exit
    assert book["closed_now"] == [] and world.db.trades.docs[0]["status"] == "open"
    assert book["trades"][0]["pnl_rs"] == -100.0 and book["market"]["live"] is False
    open_trade(api, A, symbol="FIXB", entry_price=500.0, stop_price=480.0, target_price=540.0)      # not market_recovery
    book = _book(world, live({"FIXA": q(101.0), "FIXB": q(470.0)}))
    assert [r["symbol"] for r in book["trades"]] == ["FIXA"] and book["closed_now"] == []
    assert next(d for d in world.db.trades.docs if d["symbol"] == "FIXB")["status"] == "open"


def test_tc_p5_structure_closes_every_leg_at_its_live_price(api, sworld):
    t = open_strategy(api, signal=signal(source_refs=[{"kind": "market_recovery", "ref": "FIXU:bull_call_spread", "as_of": "2026-10-09"}]))
    opts = {"available": True, "reason": None, "quotes": {"0": {"last_price": 22.0}, "1": {"last_price": 8.0}}}
    book = _book(sworld, live({"FIXU": q(1175.0)}), opts)                  # through the 1,180 Stop loss level
    assert book["closed_now"] == [t["id"]]
    stored = sworld.db.trades.docs[0]
    assert stored["status"] == "closed" and stored["exit_reason"] == "stop_live" and stored["exit_basis"] == "kite_live"
    assert [l["exit_mark"] for l in stored["exit_legs"]] == [22.0, 8.0]
    assert stored["realized_pnl_rs"] == (22 - 40) * 250 - (8 - 15) * 250          # −2,750
    assert asyncio.run(acct.read(sworld.db, "user_a"))["blocked_rs"] == 0.0


def test_tc_p5_structure_not_closed_when_a_leg_has_no_live_quote(api, sworld):
    open_strategy(api, signal=signal(source_refs=[{"kind": "market_recovery", "ref": "FIXU:x", "as_of": "2026-10-09"}]))
    book = _book(sworld, live({"FIXU": q(1175.0)}), {"available": True, "quotes": {"0": {"last_price": 22.0}}})
    assert book["closed_now"] == [] and sworld.db.trades.docs[0]["status"] == "open"
    assert book["trades"][0]["flags"] == ["no_live_quote"]


# ── TC-P6 the scheduler job ──────────────────────────────────────────────────────────────────────────────────────

def test_tc_p6_job_does_nothing_outside_market_hours(api, world):
    open_trade(api, A, source=TAG)
    s, o = readers(live({"FIXA": q(90.0)}))
    evening = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)          # 17:30 IST
    assert asyncio.run(pl.run_live_exits(world.db, now=evening, stock_reader=s, option_reader=o)) == {"skipped": "outside market hours"}
    assert world.db.trades.docs[0]["status"] == "open"
    out = asyncio.run(pl.run_live_exits(world.db, now=NOW, stock_reader=s, option_reader=o))
    assert out["closed"] == [world.db.trades.docs[0]["_id"]] and world.db.trades.docs[0]["exit_reason"] == "stop_live"


def test_tc_p6_job_is_registered_every_minute_in_market_hours():
    import inspect
    from services import mf_scheduler
    src = inspect.getsource(mf_scheduler.start)
    assert "_market_recovery_live_exits_job" in src and 'hour="9-15", minute="*"' in src


# ── the coordinator's quote interface ────────────────────────────────────────────────────────────────────────────

def test_option_quotes_reads_named_contracts_like_the_fno_quotes_route(monkeypatch):
    from services import market_freshness
    from services.kite_live_feed import config as cfg
    from services.kite_live_feed import feed as feedmod
    from services.kite_live_feed import gateway as gw
    from services.kite_live_feed import platform_token as pt

    class Kite:
        def instruments(self, ex):
            return [{"instrument_type": "CE", "name": "FIXU", "expiry": EXPIRY, "strike": 1300.0, "tradingsymbol": "FIXU26OCT1300CE"}]

        def quote(self, names):
            return {"NFO:FIXU26OCT1300CE": {"last_price": 41.5, "last_trade_time": "2026-10-12 10:29:00", "ohlc": {"close": 40.0}}}

    class W:
        floor = datetime(2026, 10, 9).date()

    async def window():
        return W()

    async def status(db):
        return {"stored": True, "expired": False}

    async def refresh(db):
        return True
    monkeypatch.setattr(cfg, "enabled", lambda: True)
    monkeypatch.setattr(cfg, "get_api_key", lambda: "k")
    monkeypatch.setattr(cfg, "get_token", lambda: "t")
    monkeypatch.setattr(pt, "token_status", status)
    monkeypatch.setattr(pt, "refresh_cache", refresh)
    monkeypatch.setattr(gw, "default_kite_factory", lambda k, a: Kite())
    monkeypatch.setattr(feedmod, "get_feed", lambda: type("F", (), {"db": None})())
    monkeypatch.setattr(market_freshness, "window", window)
    monkeypatch.setitem(pl._instruments, "map", None)
    legs = [{"underlying": "FIXU", "expiry": EXPIRY, "strike": 1300, "kind": "option", "option_type": "call"},
            {"underlying": "FIXU", "expiry": EXPIRY, "strike": 9999, "kind": "option", "option_type": "call"}]
    out = asyncio.run(pl.option_quotes(legs))
    assert out["available"] is True and out["quotes"]["0"]["last_price"] == 41.5 and out["quotes"]["0"]["previous_close"] == 40.0
    assert [u["index"] for u in out["unresolved"]] == [1] and out["read_only"] is True
    monkeypatch.setattr(cfg, "enabled", lambda: False)
    assert asyncio.run(pl.option_quotes(legs)) == {"available": False, "reason": "the live feed is disabled", "quotes": {},
                                                    "unresolved": [], "source": None, "read_only": True}


# ── TC-P7 the live route ─────────────────────────────────────────────────────────────────────────────────────────

class _Coll:
    def __init__(self, docs): self.docs = docs
    async def find_one(self, qy, proj=None):
        return next((copy.deepcopy(d) for d in self.docs if all(d.get(k) == v for k, v in qy.items())), None)


class _FlagDB:
    def __init__(self): self.system_config = _Coll([{"key": "feature_flags", "flags": {}}])
    def __getitem__(self, name): return getattr(self, name)


def test_tc_p7_live_route(api, world, monkeypatch):
    import deps
    import routes.market_recovery as rmr
    saved = copy.deepcopy(ff._flags); feature_gate._state["at"] = float("-inf")
    try:
        open_trade(api, A, source=TAG)
        users = {"owner": {"user_id": "user_a", "email": "aporwal107@gmail.com"}, "other": {"user_id": "u2", "email": "x@example.com"}}

        async def resolve(request: Request):
            return users[request.headers["X-Test-User"]]
        fdb = _FlagDB()
        gate = feature_gate.require_feature("market_recovery", resolve_user=resolve, get_db=lambda: fdb, clock=lambda: 0.0)
        app = FastAPI(); app.include_router(rmr.router)
        for route in app.routes:
            dep_ = getattr(route, "dependant", None)
            for dep in (dep_.dependencies if dep_ else []):
                if dep.call is not None and getattr(dep.call, "__qualname__", "").startswith("require_feature"):
                    app.dependency_overrides[dep.call] = gate
        monkeypatch.setattr(deps, "db", world.db)
        monkeypatch.setattr(deps, "get_current_user", resolve)
        s, o = readers(live({"FIXA": q(103.0)}))
        monkeypatch.setattr(pl, "stock_quotes", s)
        monkeypatch.setattr(pl, "option_quotes", o)
        c = TestClient(app)
        r = c.get("/api/market-recovery/paper-trades/live", headers={"X-Test-User": "owner"})
        assert r.status_code == 200
        body = r.json()
        assert body["totals"]["open_count"] == 1 and body["totals"]["open_pnl_rs"] == 30.0
        assert body["trades"][0]["pnl_pct"] == 60.0 and body["market"]["live"] is True
        assert c.get("/api/market-recovery/paper-trades/live", headers={"X-Test-User": "other"}).status_code == 403
    finally:
        ff._flags.clear(); ff._flags.update(saved); feature_gate._state["at"] = float("-inf")


# ── wording ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_wording_of_the_live_book(api, sworld):
    import re
    from tests.test_compliance_wording_lint import hits
    open_trade(api, A, source=TAG)
    book = _book(sworld, live({"FIXA": q(94.0)}))
    plan = re.compile(r"\b(?:stop loss|target 1)\b", re.I)

    def strings(x, key=None):
        if isinstance(x, str):
            if key not in ("action", "reason", "id", "symbol", "opened_at", "at", "kind", "status", "source", "day", "as_of"):
                yield x
        elif isinstance(x, dict):
            for k, v in x.items():
                yield from strings(v, k)
        elif isinstance(x, list):
            for v in x:
                yield from strings(v, key)
    bad = [(s, hits(plan.sub(" ", s))) for s in strings(book)]
    assert [b for b in bad if b[1]] == []
