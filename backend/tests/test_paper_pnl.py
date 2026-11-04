"""Real-time paper P&L dashboard (docs/paper_pnl_dashboard/DESIGN.md; test cases test_reports/paper_pnl_dashboard_TESTCASES.md).

Covers services/paper_pnl/{ledger,book,prices,dashboard,timeseries}.py and routes/desk_pnl.py. The spec's own calculation
tests keep their numbers (TC-001 … TC-012). Route tests reuse the desk's in-memory harness (tests/test_desk_trading.py: a fake
Mongo, a fake data platform, the clock) so a trade is opened by the REAL POST route and then read by the P&L route.

MOCK — not real data: every symbol, price, quantity and P&L below is made up; each expected figure is worked out by hand in
the test, not read back from the code. Cost model FLAT20 (desk-flat-v1, ₹20 brokerage a side, no slippage) keeps charges
hand-checkable: ₹40 a round trip per position.
"""
from __future__ import annotations

import ast
import asyncio
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from routes import desk_pnl as pnl_route
from services.paper_pnl import book as bk
from services.paper_pnl import dashboard as dash
from services.paper_pnl import ledger, prices, timeseries
from services.paper_pnl.ledger import Execution
from services.paper_pnl.prices import CLOSE, DELAYED, EOD, LIVE, MISSING, Quote

from tests.test_desk_trading import A, TRADES_URL, api, world  # noqa: F401  (fixtures)

FLAT20 = {"name": "test flat", "version": "desk-flat-v1", "slippage_pct_per_side": 0.0, "brokerage_rs_per_side": 20.0}
NOW = datetime(2026, 11, 4, 5, 0, tzinfo=timezone.utc)          # Wednesday 10:30 IST (session open)
TODAY = "2026-11-04"
ACCOUNT = {"starting_capital_rs": 1_000_000.0, "cash_rs": 1_000_000.0, "blocked_rs": 100_000.0}
LIMITS = {"max_open_risk_pct": 3.0, "daily_loss_pct": 2.0}
MARKET_OPEN = {"session": "open", "feed": "live", "day": TODAY}


def ex(eid: str, side: int, qty: float, price: float, key: str = "p", at: Optional[str] = None) -> Execution:
    return Execution(eid, key, side, qty, price, at=at)


def q(ltp: Optional[float], status: str = LIVE, prev: Optional[float] = None, day: str = TODAY, age: float = 1.0) -> Quote:
    return Quote(ltp=ltp, prev_close=prev, status=status, source="test", at=None, age_seconds=age, day=day)


def cash_pub(tid: str, symbol: str, qty: int, fill: float, *, status: str = "open", stop: float = 0.0, target: Optional[float] = None,
             exit_price: Optional[float] = None, exit_session: Optional[str] = None, realized: Optional[float] = None,
             costs: Optional[float] = None, entry_status: str = "assumed", entry_session: str = "2026-10-30",
             last_close: Optional[float] = None) -> Dict[str, Any]:
    """A share trade the way svc.public_trade sends it (only the fields the dashboard reads). MOCK."""
    return {"id": tid, "kind": "cash", "symbol": symbol, "quantity": qty, "entry_price": fill, "sim_entry_price": fill if entry_status in ("assumed", "reached") else None,
            "entry_status": entry_status, "entry_rule": "at_once" if entry_status == "assumed" else "break_above",
            "entry_session": entry_session, "stop_price": stop, "current_stop": stop, "target_price": target,
            "status": status, "opened_at": f"{entry_session}T04:00:00+00:00", "closed_at": f"{exit_session}T10:00:00+00:00" if exit_session else None,
            "exit_price": exit_price, "exit_session": exit_session, "exit_reason": "stop" if status == "closed" else None,
            "realized_pnl_rs": realized, "costs_rs": costs, "net_pnl_rs": None if realized is None or costs is None else round(realized - costs, 2),
            "last_close": last_close, "last_close_date": "2026-11-03" if last_close else None, "cost_model": FLAT20}


def spread_pub(tid: str = "st1", *, status: str = "open", marks=(None, None), realized: Optional[float] = None,
               expiry: str = "2026-11-25", stop_u: Optional[float] = None, target_u: Optional[float] = None) -> Dict[str, Any]:
    """A bull call spread the way strat.public_strategy_trade sends it. MOCK: NIFTY, 1 lot of 75, buy 26000 CE at 180, sell
    26200 CE at 100."""
    legs = [
        {"index": 0, "kind": "option", "side": "buy", "lots": 1, "lot_size": 75, "entry_price": 180.0, "expiry": expiry,
         "strike": 26000.0, "option_type": "call", "mark": marks[0], "mark_date": "2026-11-03" if marks[0] else None, "mark_basis": "close" if marks[0] else None},
        {"index": 1, "kind": "option", "side": "sell", "lots": 1, "lot_size": 75, "entry_price": 100.0, "expiry": expiry,
         "strike": 26200.0, "option_type": "call", "mark": marks[1], "mark_date": "2026-11-03" if marks[1] else None, "mark_basis": "close" if marks[1] else None},
    ]
    return {"id": tid, "kind": "strategy", "symbol": "NIFTY", "underlying": "NIFTY", "direction": "bullish", "family": "bull_call_spread",
            "family_name": "Bull call spread", "summary_text": "Bull call spread 26000/26200", "legs": legs, "status": status,
            "opened_at": "2026-10-30T04:00:00+00:00", "closed_at": "2026-11-03T10:00:00+00:00" if status == "closed" else None,
            "exit_session": "2026-11-03" if status == "closed" else None, "exit_reason": "target" if status == "closed" else None,
            "realized_pnl_rs": realized, "costs_rs": 80.0 if status == "closed" else None,
            "net_pnl_rs": None if realized is None else round(realized - 80.0, 2), "net_premium_rs": -6000.0,
            "stop_underlying": stop_u, "target_underlying": target_u, "cost_model": FLAT20}


def build(open_items=(), closed_items=(), quotes=None, *, filters=None, market=None, account=None, und=None):
    book = bk.Book(open=list(open_items), closed=list(closed_items))
    filters = filters or dash.make_filters("ALL", "ALL", None, None, date(2026, 11, 4))
    return dash.build(book, quotes or {}, market or MARKET_OPEN, account or ACCOUNT, LIMITS, filters, now=NOW, underlying_ltp=und or {})


# ── ledger: the spec's calculation tests ────────────────────────────────────────────────────────────────────────────
def test_tc001_long_unrealized():
    p = ledger.build([ex("e1", 1, 100, 500)])["p"]
    assert p.unrealized(510) == 1000.0 and p.side == "LONG"


def test_tc002_tc003_partial_exit():
    p = ledger.build([ex("e1", 1, 100, 500, at="1"), ex("e2", -1, 40, 520, at="2")])["p"]
    assert p.realized_pnl == 800.0                                   # (520 − 500) × 40
    assert p.net_quantity == 60 and p.average_price == 500
    assert p.unrealized(530) == 1800.0                               # (530 − 500) × 60
    assert p.realized_pnl + p.unrealized(530) == 2600.0


def test_tc004_reversal():
    p = ledger.build([ex("e1", 1, 100, 500, at="1"), ex("e2", -1, 150, 490, at="2")])["p"]
    assert p.realized_pnl == -1000.0                                 # (490 − 500) × 100 closed
    assert p.net_quantity == -50 and p.average_price == 490 and p.side == "SHORT"


def test_tc005_short_unrealized():
    p = ledger.build([ex("e1", -1, 100, 500)])["p"]
    assert p.unrealized(490) == 1000.0                               # (490 − 500) × −100


def test_tc007_duplicate_execution_counted_once():
    p = ledger.build([ex("e1", 1, 100, 500), ex("e1", 1, 100, 500)])["p"]
    assert p.net_quantity == 100 and len(p.executions) == 1


def test_tc013_weighted_average_of_fills():
    p = ledger.build([ex("e1", 1, 100, 500, at="1"), ex("e2", 1, 50, 530, at="2")])["p"]
    assert p.average_price == pytest.approx(510.0)                   # (100×500 + 50×530) / 150
    assert p.unrealized(520) == 1500.0                               # 10 × 150


def test_ledger_rejects_bad_execution():
    with pytest.raises(ValueError):
        Execution("x", "p", 2, 1, 1)
    with pytest.raises(ValueError):
        Execution("x", "p", 1, 0, 1)


# ── positions, strategies and the summary ──────────────────────────────────────────────────────────────────────────
def test_tc006_strategy_is_the_sum_of_its_legs_and_not_counted_twice():
    item = bk.strategy_item(spread_pub(marks=(170.0, 95.0)))
    quotes = {"st1:0": q(220.0), "st1:1": q(120.0)}
    d = build([item], quotes=quotes)
    legs = {p["position_id"]: p for p in d["positions"]}
    assert legs["st1:0"]["unrealized_pnl"] == 3000.0                 # (220 − 180) × 75
    assert legs["st1:1"]["unrealized_pnl"] == -1500.0                # (120 − 100) × −75
    assert legs["st1:1"]["side"] == "SHORT"
    s = d["strategies"][0]
    assert s["unrealized_pnl"] == 1500.0 and s["legs"] == ["st1:0", "st1:1"]
    assert s["charges_estimated"] == 80.0 and s["net_pnl"] == 1420.0   # ₹40 a leg (FLAT20)
    assert d["summary"]["unrealized_pnl"] == 1500.0                  # the legs once, not legs + strategy
    assert d["summary"]["open_positions"] == 1 and d["summary"]["open_legs"] == 2
    assert s["current_value"] == pytest.approx(-220 * 75 + 120 * 75)  # premium at the live prices (debit)


def test_tc009_same_instrument_in_two_trades_stays_two_positions():
    a = bk.cash_item(cash_pub("t1", "FIXA", 10, 100.0, stop=90))
    b = bk.cash_item(cash_pub("t2", "FIXA", 20, 105.0, stop=95))
    d = build([a, b], quotes={"t1": q(110.0), "t2": q(110.0)})
    rows = {p["position_id"]: p for p in d["positions"]}
    assert rows["t1"]["unrealized_pnl"] == 100.0 and rows["t2"]["unrealized_pnl"] == 100.0
    assert all(p["mode"] == "PAPER" for p in d["positions"])


def test_tc010_closed_strategy_reconciles_per_leg():
    # Exit marks 250 / 140: (250 − 180) × 75 + (140 − 100) × −75 = 5,250 − 3,000 = 2,250
    item = bk.strategy_item(spread_pub("st2", status="closed", marks=(250.0, 140.0), realized=2250.0))
    d = build(closed_items=[item])
    assert d["reconciliation"]["checked"] == 1 and d["reconciliation"]["mismatches"] == []
    assert d["closed"][0]["realized_pnl"] == 2250.0 and d["closed"][0]["net_pnl"] == 2170.0


def test_tc011_mismatch_is_an_alert():
    item = bk.cash_item(cash_pub("t3", "FIXB", 10, 100.0, status="closed", exit_price=90.0, exit_session="2026-11-03",
                                 realized=-50.0, costs=40.0))          # the fills say −100
    d = build(closed_items=[item])
    m = d["reconciliation"]["mismatches"]
    assert m and m[0]["engine_realized_pnl"] == -100.0 and m[0]["ledger_realized_pnl"] == -50.0
    assert any(a["type"] == "RECONCILIATION_MISMATCH" for a in d["risk"]["alerts"])


def test_tc012_charges_move_net_not_gross():
    pub = cash_pub("t4", "FIXA", 10, 100.0, stop=90)
    d1 = build([bk.cash_item(pub)], quotes={"t4": q(110.0)})
    pub2 = dict(pub, cost_model=dict(FLAT20, brokerage_rs_per_side=50.0))
    d2 = build([bk.cash_item(pub2)], quotes={"t4": q(110.0)})
    assert d1["summary"]["gross_pnl"] == d2["summary"]["gross_pnl"] == 100.0
    assert d1["summary"]["charges_estimated"] == 40.0 and d2["summary"]["charges_estimated"] == 100.0
    assert d1["summary"]["net_pnl"] == 60.0 and d2["summary"]["net_pnl"] == 0.0


def test_tc014_unpriced_position_is_null_never_zero():
    a = bk.cash_item(cash_pub("t1", "FIXA", 10, 100.0, stop=90))
    b = bk.cash_item(cash_pub("t2", "FIXB", 10, 200.0, stop=190))
    d = build([a, b], quotes={"t1": q(110.0), "t2": q(None, MISSING)})
    row = next(p for p in d["positions"] if p["position_id"] == "t2")
    assert row["unrealized_pnl"] is None and row["net_pnl"] is None and row["price_status"] == MISSING
    assert d["summary"]["complete"] is False and d["summary"]["unpriced_positions"] == 1
    assert d["summary"]["unrealized_pnl"] == 100.0                   # the priced one only, said to be partial
    assert any(a["type"] == "MISSING_PRICE" and a["severity"] == "CRITICAL" for a in d["risk"]["alerts"])


def test_tc017_waiting_entry_is_not_a_position():
    pend = bk.cash_item(cash_pub("t5", "FIXC", 10, 300.0, stop=290, entry_status="waiting"))
    assert pend.executions == [] and not pend.entered
    d = build([pend], quotes={"t5": q(295.0)})
    assert d["positions"] == [] and d["summary"]["open_positions"] == 0
    assert d["pending_entries"][0]["trade_id"] == "t5" and d["pending_entries"][0]["ltp"] == 295.0


def test_tc018_stop_and_target_states():
    hit = bk.cash_item(cash_pub("h", "HIT", 10, 100.0, stop=95, target=120))
    near = bk.cash_item(cash_pub("n", "NEAR", 10, 100.0, stop=95, target=120))
    tgt = bk.cash_item(cash_pub("t", "TGT", 10, 100.0, stop=95, target=120))
    d = build([hit, near, tgt], quotes={"h": q(94.0), "n": q(95.8), "t": q(121.0)})
    st = {p["position_id"]: p["status"] for p in d["positions"]}
    assert st == {"h": "STOP_LOSS_HIT", "n": "NEAR_STOP_LOSS", "t": "TARGET_REACHED"}
    kinds = {(a["type"], a["severity"]) for a in d["risk"]["alerts"]}
    assert ("STOP_LOSS_HIT", "CRITICAL") in kinds and ("NEAR_STOP_LOSS", "WARNING") in kinds and ("TARGET_REACHED", "INFO") in kinds
    assert d["risk"]["alerts"][0]["severity"] == "CRITICAL"          # most severe first
    hit_alert = next(a for a in d["risk"]["alerts"] if a["type"] == "STOP_LOSS_HIT")
    assert "evening check" in hit_alert["message"]                  # says nothing was closed by the live touch


def test_tc019_exit_due_when_eod_rule_fired_but_not_written():
    item = bk.cash_item(cash_pub("t6", "FIXA", 10, 100.0, stop=95), pending_exit={"exit_reason": "stop", "exit_session": "2026-11-03"})
    d = build([item], quotes={"t6": q(96.0)})
    assert d["positions"][0]["status"] == "EXIT_DUE"
    assert any(a["type"] == "EXIT_DUE" and "2026-11-03" in a["message"] for a in d["risk"]["alerts"])


def test_tc020_expiry_today_alert():
    item = bk.strategy_item(spread_pub(expiry=TODAY))
    d = build([item], quotes={"st1:0": q(200.0), "st1:1": q(110.0)})
    e = [a for a in d["risk"]["alerts"] if a["type"] == "EXPIRY"]
    assert len(e) == 2 and all("today" in a["message"] and a["severity"] == "WARNING" for a in e)


def test_tc021_segment_and_period_filters():
    cash = bk.cash_item(cash_pub("c1", "FIXA", 10, 100.0, stop=90))
    spread = bk.strategy_item(spread_pub())
    old = bk.cash_item(cash_pub("old", "OLD", 10, 100.0, status="closed", exit_price=110.0, exit_session="2026-10-01", realized=100.0, costs=40.0))
    new = bk.cash_item(cash_pub("new", "NEW", 10, 100.0, status="closed", exit_price=90.0, exit_session="2026-11-02", realized=-100.0, costs=40.0))
    quotes = {"c1": q(105.0), "st1:0": q(200.0), "st1:1": q(110.0)}
    only_opt = build([cash, spread], [old, new], quotes, filters=dash.make_filters("OPTIONS", "ALL", None, None, date(2026, 11, 4)))
    assert {p["segment"] for p in only_opt["positions"]} == {"OPTIONS"} and only_opt["closed"] == []
    assert only_opt["summary"]["unrealized_pnl"] == 750.0           # (200−180)×75 + (110−100)×−75
    week = build([cash], [old, new], quotes, filters=dash.make_filters("ALL", "1W", None, None, date(2026, 11, 4)))
    assert [c["trade_id"] for c in week["closed"]] == ["new"] and week["summary"]["realized_pnl"] == -100.0
    assert week["summary"]["charges_booked"] == 40.0
    with pytest.raises(ValueError):
        dash.make_filters("FOO", "ALL", None, None, date(2026, 11, 4))
    with pytest.raises(ValueError):
        dash.make_filters("ALL", "CUSTOM", "2026-11-05", "2026-11-01", date(2026, 11, 4))


def test_tc022_analytics():
    rows = [("a", "2026-10-28", 3040.0), ("b", "2026-10-29", -960.0), ("c", "2026-10-30", -960.0)]   # nets 3000, −1000, −1000
    closed = [bk.cash_item(cash_pub(t, t.upper(), 10, 1000.0, status="closed", exit_price=1000.0 + r / 10, exit_session=d, realized=r, costs=40.0))
              for t, d, r in rows]
    a = build(closed_items=closed)["analytics"]
    assert a["trades"] == 3 and a["wins"] == 1 and a["losses"] == 2
    assert a["win_rate_pct"] == 33.3 and a["profit_factor"] == 1.5
    assert a["max_drawdown_rs"] == -2000.0 and a["avg_loss"] == -1000.0
    assert [x["date"] for x in a["daily"]] == ["2026-10-28", "2026-10-29", "2026-10-30"]


def test_tc023_day_pnl():
    held = bk.cash_item(cash_pub("h", "HELD", 10, 100.0, stop=80, entry_session="2026-10-30"))
    new = bk.cash_item(cash_pub("n", "NEW", 10, 100.0, stop=80, entry_session=TODAY))
    d = build([held, new], quotes={"h": q(112.0, prev=108.0), "n": q(103.0, prev=99.0)})
    rows = {p["position_id"]: p for p in d["positions"]}
    assert rows["h"]["day_pnl"] == 40.0                              # (112 − 108) × 10: held into today
    assert rows["n"]["day_pnl"] == 30.0                              # (103 − 100) × 10: opened today
    assert d["summary"]["day_pnl"] == 70.0


def test_risk_capital_and_limits():
    item = bk.cash_item(cash_pub("t", "FIXA", 100, 100.0, stop=90))
    d = build([item], quotes={"t": q(95.0, prev=110.0)})
    r = d["risk"]
    assert r["capital"]["utilisation_pct"] == 10.0 and r["capital"]["available"] == 900_000.0
    assert r["open_risk_rs"] == -500.0                               # (90 − 95) × 100 more to the stop
    assert r["open_risk_limit_rs"] == 30_000.0 and r["daily_loss_limit_rs"] == 20_000.0
    assert r["daily_loss_used_pct"] == 7.5                           # (95 − 110) × 100 = −1,500 of 20,000


def test_tc008_session_open_but_delayed_price_is_flagged():
    item = bk.cash_item(cash_pub("t", "FIXA", 10, 100.0, stop=90))
    d = build([item], quotes={"t": q(101.0, DELAYED, age=400)})
    assert d["positions"][0]["price_status"] == DELAYED and d["summary"]["stale_positions"] == 1
    assert any(a["type"] == "STALE_PRICE" for a in d["risk"]["alerts"])
    d2 = build([item], quotes={"t": q(101.0)}, market={"session": "open", "feed": "not_connected", "day": TODAY})
    assert any(a["type"] == "FEED" and a["severity"] == "CRITICAL" for a in d2["risk"]["alerts"])


# ── prices ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_live_quote_freshness():
    now = datetime(2026, 11, 4, 5, 0, tzinfo=timezone.utc)                    # 10:30 IST
    # A feed quote is aged from received_at. Its exchange_ts is ignored: on staging it is the UTC clock labelled +05:30
    # (the row below copies that shape: 05:00 "+05:30" at 10:30 IST would read 5 h 30 m old).
    fresh = prices.live_quote({"ltp": 101.0, "close": 99.0, "exchange_ts": "2026-11-04T04:59:58+05:30",
                               "received_at": "2026-11-04T10:29:58.000+05:30"}, now, 75, "live")
    old = prices.live_quote({"ltp": 101.0, "close": 99.0, "received_at": "2026-11-04T10:20:00+05:30"}, now, 75, "live")
    assert fresh.status == LIVE and fresh.age_seconds == 2.0 and fresh.prev_close == 99.0
    assert old.status == DELAYED and old.age_seconds == 600.0
    assert prices.live_quote({"ltp": None}, now, 75, "live") is None
    assert prices.live_quote({"ltp": 101.0, "received_at": "2026-11-04T10:29:58+05:30"}, now, 75, "delayed").status == DELAYED
    # A REST quote is aged from Kite's last trade time (IST text)
    rest = prices.live_quote({"ltp": 222.0, "exchange_ts": "2026-11-04 10:25:00"}, now, 75, "live", source="kite_rest")
    assert rest.status == DELAYED and rest.age_seconds == 300.0


def test_choose_follows_the_rule():
    live, close, eod = q(101.0), q(100.0, CLOSE, day="2026-11-04"), q(99.0, EOD, day="2026-11-03")
    assert prices.choose(in_session=True, live=live, close=None, eod=eod) is live
    assert prices.choose(in_session=True, live=None, close=None, eod=eod) is eod
    assert prices.choose(in_session=False, live=live, close=close, eod=eod) is close        # TC-015: newer Kite close
    same_day_eod = q(100.5, EOD, day="2026-11-04")
    assert prices.choose(in_session=False, live=None, close=close, eod=same_day_eod) is same_day_eod   # EOD wins a tie
    assert prices.choose(in_session=False, live=None, close=None, eod=None).status == MISSING


class FakeFeed:
    def __init__(self, status, snap, close_doc=None):
        self._status, self._snap, self._close = status, snap, close_doc
        self.db = object()

    async def read_status(self):
        return self._status

    async def read_snapshot(self):
        return self._snap

    async def read_close(self, day=None):
        return self._close


class FakeKite:
    def __init__(self, quote_rows):
        self.rows = quote_rows
        self.quote_calls: List[List[str]] = []

    def instruments(self, exchange):
        assert exchange == "NFO"
        return [{"name": "NIFTY", "expiry": date(2026, 11, 25), "strike": 26000.0, "instrument_type": "CE", "tradingsymbol": "NIFTY25NOV26000CE", "instrument_token": 11},
                {"name": "NIFTY", "expiry": date(2026, 11, 25), "strike": 26200.0, "instrument_type": "CE", "tradingsymbol": "NIFTY25NOV26200CE", "instrument_token": 12}]

    def quote(self, keys):
        self.quote_calls.append(list(keys))
        return {k: v for k, v in self.rows.items() if k in keys}


def _patch_prices(monkeypatch, *, cached=None, kite=None, token_ok=True):
    async def read_quotes(symbols):
        return {s: r for s, r in (cached or {}).items() if s in symbols}

    async def token_status(db, now=None):
        return {"stored": token_ok, "expired": False}

    async def refresh_cache(db, now=None):
        return token_ok

    monkeypatch.setattr(prices.qc, "read_quotes", read_quotes)
    monkeypatch.setattr(prices.pt, "token_status", token_status)
    monkeypatch.setattr(prices.pt, "refresh_cache", refresh_cache)
    monkeypatch.setattr(prices, "_TOKEN_AT", [0.0])
    monkeypatch.setattr(prices, "_kite", lambda: kite)
    monkeypatch.setattr(prices, "_NFO", (None, {}, {}))
    monkeypatch.setattr(prices, "_REST", {})


def test_tc016_resolve_stock_from_cache_and_contract_off_feed_over_rest(monkeypatch):
    cash = bk.cash_item(cash_pub("c1", "FIXA", 10, 100.0, stop=90, last_close=104.0))
    spread = bk.strategy_item(spread_pub(marks=(170.0, 95.0)))
    kite = FakeKite({"NFO:NIFTY25NOV26000CE": {"last_price": 222.0, "ohlc": {"close": 210.0}, "last_trade_time": "2026-11-04 10:29:59"},
                     # not traded today; its last trade is from the previous session (T-1): used, DELAYED, no day figure
                     "NFO:NIFTY25NOV26200CE": {"last_price": 101.0, "ohlc": {"close": 101.0}, "last_trade_time": "2026-11-03 15:10:00"}})
    row = {"symbol": "FIXA", "ltp": 107.5, "ohlc": {"close": 104.0}, "exchange_ts": "2026-11-04T04:59:59+05:30", "received_at": "2026-11-04T10:29:59.500+05:30"}
    _patch_prices(monkeypatch, cached={"FIXA": row}, kite=kite)
    feed = FakeFeed({"state": "live", "session": "open", "cadence_seconds": 30}, {"data_at": "2026-11-04T04:59:59+00:00", "quotes": []})
    out, market = asyncio.run(prices.resolve(cash.legs + spread.legs, now=NOW, feed=feed))
    assert market["session"] == "open" and market["feed"] == "live"
    assert out["c1"].ltp == 107.5 and out["c1"].status == LIVE and out["c1"].prev_close == 104.0
    assert out["st1:0"].ltp == 222.0 and out["st1:0"].status == LIVE and "Kite quote" in out["st1:0"].source
    assert out["st1:1"].ltp == 101.0 and out["st1:1"].status == DELAYED and out["st1:1"].day == "2026-11-03"
    assert kite.quote_calls == [["NFO:NIFTY25NOV26000CE", "NFO:NIFTY25NOV26200CE"]]
    d = build([spread], quotes=out)
    assert next(p for p in d["positions"] if p["position_id"] == "st1:1")["day_pnl"] is None
    # an older last trade (two sessions back) is not used: the leg falls back to its end-of-day mark, labelled EOD, never 0
    kite.rows["NFO:NIFTY25NOV26200CE"]["last_trade_time"] = "2026-10-31 15:10:00"
    monkeypatch.setattr(prices, "_REST", {})
    out2, _ = asyncio.run(prices.resolve(spread.legs, now=NOW, feed=feed))
    assert out2["st1:1"].ltp == 95.0 and out2["st1:1"].status == EOD


def test_tc015_after_close_uses_the_saved_kite_close(monkeypatch):
    cash = bk.cash_item(cash_pub("c1", "FIXA", 10, 100.0, stop=90, last_close=104.0))
    _patch_prices(monkeypatch)
    after = datetime(2026, 11, 4, 11, 0, tzinfo=timezone.utc)        # 16:30 IST
    close_doc = {"data_at": "2026-11-04T10:01:00+00:00",
                 "quotes": [{"symbol": "FIXA", "ltp": 109.0, "close": 104.0, "volume": 5000, "exchange_ts": "2026-11-04T15:29:59"}]}
    feed = FakeFeed({"state": "market_closed", "session": "closed"}, {}, close_doc)
    out, market = asyncio.run(prices.resolve(cash.legs, now=after, feed=feed))
    assert market["session"] == "closed"
    assert out["c1"].status == CLOSE and out["c1"].ltp == 109.0 and "provisional" in out["c1"].source


def test_no_kite_session_prices_contracts_at_eod_and_says_so(monkeypatch):
    spread = bk.strategy_item(spread_pub(marks=(170.0, 95.0)))
    _patch_prices(monkeypatch, kite=None, token_ok=False)
    feed = FakeFeed({"state": "live", "session": "open", "cadence_seconds": 30}, {"data_at": "2026-11-04T04:59:59+00:00", "quotes": []})
    out, market = asyncio.run(prices.resolve(spread.legs, now=NOW, feed=feed))
    assert out["st1:0"].status == EOD and out["st1:0"].ltp == 170.0
    assert any("No Kite session" in n for n in market["notes"])


# ── the intraday curve ─────────────────────────────────────────────────────────────────────────────────────────────
def test_tc024_curve_carries_forward_and_lists_missing():
    series = {"a": [["2026-11-04T09:15:00+05:30", 0, 0, 0, 101.0, 0], ["2026-11-04T09:20:00+05:30", 0, 0, 0, 103.0, 0]],
              "b": [["2026-11-04T09:15:00+05:30", 0, 0, 0, 50.0, 0]],                       # no 09:20 candle: carried
              "old": [["2026-11-03T15:25:00+05:30", 0, 0, 0, 1.0, 0]]}
    books = [{"key": "a", "net_quantity": 10, "avg_price": 100.0, "multiplier": 1.0, "prev_close": 100.5},
             {"key": "b", "net_quantity": -20, "avg_price": 52.0, "multiplier": 1.0, "prev_close": 51.0},
             {"key": "none", "net_quantity": 5, "avg_price": 10.0, "multiplier": 1.0, "prev_close": 10.0}]
    out = timeseries.curve(series, books, realized=100.0, charges=40.0, day=TODAY)
    p = out["points"]
    assert [x["t"][11:16] for x in p] == ["09:15", "09:20"]
    assert p[0]["unrealized_pnl"] == 50.0                            # 1×10 + 2×20
    assert p[1]["unrealized_pnl"] == 70.0                            # 3×10 + 2×20 (b carried at 50)
    assert p[1]["gross_pnl"] == 170.0 and p[1]["net_pnl"] == 130.0
    assert out["baseline_gross"] == 125.0                            # 0.5×10 + 1×20 + 100 realized
    assert p[1]["change_since_baseline"] == 45.0
    assert out["missing"] == [{"position_id": "none", "reason": "no intraday candles for this instrument in the session"}]
    assert out["partial"] is True


# ── the route, on the desk's own harness (a trade opened by the REAL POST route) ─────────────────────────────────────
@pytest.fixture
def pnl_api(world, monkeypatch):
    monkeypatch.setattr(pnl_route, "db", world.db)

    async def fake_user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": uid}

    monkeypatch.setattr(pnl_route, "get_current_user", fake_user)
    live: Dict[str, float] = {}

    async def fake_resolve(legs, *, now=None, feed=None):
        out = {}
        for l in legs:
            if l.symbol in live:
                out[l.position_key] = q(live[l.symbol])
            else:
                out[l.position_key] = prices.choose(in_session=False, live=None, close=None, eod=prices.eod_quote(l))
        return out, {"session": "closed", "feed": "closed", "day": TODAY, "notes": []}

    monkeypatch.setattr(pnl_route.prices, "resolve", fake_resolve)
    monkeypatch.setattr(bk, "_CACHE", {})
    # v2: the broker side (services/paper_pnl/live.py) is read through a fake: no account unless a test adds some.
    brokers: Dict[str, Any] = {"entries": [], "rows": [], "reads": 0, "fail": None}

    async def fake_read(request, db, uid):
        brokers["reads"] += 1
        if brokers["fail"] is not None:
            raise brokers["fail"]
        return [dict(e) for e in brokers["entries"]], [dict(r) for r in brokers["rows"]]

    monkeypatch.setattr(pnl_route.live, "_read", fake_read)
    monkeypatch.setattr(pnl_route.live, "_CACHE", {})
    monkeypatch.setattr(timeseries, "_CACHE", {})
    trades = world.db.cols[bk.svc.TRADES]
    plain_find = trades.find
    monkeypatch.setattr(trades, "find", lambda query, projection=None: plain_find(query))   # the fake ignores projections
    app = FastAPI()
    app.include_router(pnl_route.router)
    client = TestClient(app)
    client.brokers = brokers                                     # type: ignore[attr-defined]
    return client, live


def test_tc025_route_reads_without_writing_and_matches_the_desk(world, api, pnl_api):
    client, live = pnl_api
    r = api.post(TRADES_URL, json={"symbol": "FIXA", "quantity": 10, "entry_price": 100.0, "stop_price": 95.0, "target_price": 110.0}, headers=A)
    assert r.status_code == 201, r.text
    tid = r.json()["trade"]["id"]
    writes = sum(c.writes for c in world.db.cols.values())
    got = client.get("/api/desk/pnl", params={"period": "ALL"}, headers=A)
    assert got.status_code == 200, got.text
    assert sum(c.writes for c in world.db.cols.values()) == writes    # nothing written by the dashboard
    body = got.json()
    desk = api.get(TRADES_URL, params={"status": "all"}, headers=A).json()
    trade = next(t for t in desk["trades"] if t["id"] == tid)
    row = next(p for p in body["positions"] if p["trade_id"] == tid)
    assert row["avg_price"] == trade["sim_entry_price"] and row["ltp"] == trade["last_close"]
    assert row["unrealized_pnl"] == trade["unrealized_pnl_rs"] and row["price_status"] == EOD
    assert row["charges_estimated"] == trade["costs_rs"] and row["net_pnl"] == trade["net_pnl_rs"]
    # v2: `mode` is the selected mode (ALL by default); every paper row still says PAPER
    assert body["mode"] == "ALL" and body["read_only"] is True and isinstance(body["sequence"], int)
    assert all(p["mode"] == "PAPER" and p["account_id"] == "paper" for p in body["positions"])
    # a live price moves the dashboard and nothing else
    live["FIXA"] = 104.0
    body2 = client.get("/api/desk/pnl", params={"period": "ALL"}, headers=A).json()
    row2 = next(p for p in body2["positions"] if p["trade_id"] == tid)
    assert row2["unrealized_pnl"] == round((104.0 - row["avg_price"]) * 10, 2) and row2["price_status"] == LIVE
    assert body2["sequence"] >= body["sequence"]


def test_route_auth_and_bad_filters(pnl_api):
    client, _ = pnl_api
    assert client.get("/api/desk/pnl").status_code == 401
    assert client.get("/api/desk/pnl", params={"segment": "FOO"}, headers=A).status_code == 422
    assert client.get("/api/desk/pnl/timeseries", params={"interval": "7m"}, headers=A).status_code == 422
    assert client.get("/api/desk/pnl/stream").status_code == 401


def test_stream_sends_rising_snapshots(world, api, pnl_api, monkeypatch):
    client, _ = pnl_api
    monkeypatch.setattr(pnl_route, "STREAM_MAX_SECONDS", 1.0)
    monkeypatch.setenv("PNL_STREAM_CLOSED_SECONDS", "1")
    seqs = []
    with client.stream("GET", "/api/desk/pnl/stream", params={"period": "ALL"}, headers=A) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        text = "".join(r.iter_text())
    assert text.startswith("retry: 3000")
    for m in re.finditer(r'"sequence":(\d+)', text):
        seqs.append(int(m.group(1)))
    assert len(seqs) >= 1 and seqs == sorted(seqs)
    assert "event: snapshot" in text


# ── wording (TC-040): the owner approved the standard trading words on this screen, never a recommendation ───────────
def test_tc040_no_recommendation_words_in_user_text():
    banned = re.compile(r"\b(recommend\w*|picks?|suggested|best trade)\b", re.I)
    root = Path(__file__).resolve().parents[1]
    files = list((root / "services" / "paper_pnl").glob("*.py")) + [root / "routes" / "desk_pnl.py"]
    hits = []
    for f in files:
        tree = ast.parse(f.read_text())
        docstrings = {id(n.body[0].value) for n in ast.walk(tree)                 # docstrings are for developers, not shown
                      if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                      and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        for node in ast.walk(tree):
            if id(node) in docstrings:
                continue
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and banned.search(node.value):
                hits.append((f.name, node.value[:60]))
    assert hits == []
