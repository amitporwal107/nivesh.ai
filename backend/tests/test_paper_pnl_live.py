"""P&L dashboard v2 (docs/paper_pnl_dashboard/DESIGN.md "v2"; test cases test_reports/paper_pnl_dashboard_v2_TESTCASES.md):
LIVE (broker) positions, the mode / account selection, `accounts` and `modes`, the per-trade curve and the journal.

MOCK — not real data: every symbol, quantity, price and P&L below is made up; each expected figure is worked out by hand here.
Broker rows have the HubPosition shape (services/brokers/base.py) with the positions workspace's private keys (_account_id, ...).
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from routes import desk_pnl as pnl_route
from services import desk_cost_card as cost_card
from services import desk_trading as svc
from services.brokers import hub_reads as hub
from services.paper_pnl import book as bk
from services.paper_pnl import dashboard as dash
from services.paper_pnl import journal as jr
from services.paper_pnl import live, prices, timeseries
from services.paper_pnl.ledger import Execution
from services.paper_pnl.prices import DELAYED, EOD, LIVE, MISSING, Quote

from tests.test_desk_trading import A, TRADES_URL, api, world  # noqa: F401  (fixtures)
from tests.test_paper_pnl import (ACCOUNT, LIMITS, MARKET_OPEN, NOW, TODAY, cash_pub, pnl_api, q,  # noqa: F401
                                  spread_pub)

ZID, IID = "acc-zerodha-1", "acc-icici-1"
READ_AT = "2026-11-04T04:59:30+00:00"                  # 30 s before NOW


def brow(symbol: str, qty: float, avg: float, *, account: str = ZID, broker: str = "zerodha", display: str = "Zerodha",
         last: Optional[float] = None, pnl: Optional[float] = 0.0, segment: str = "fno", itype: Optional[str] = None,
         expiry: Optional[str] = None, strike: Optional[float] = None, exchange: str = "NFO", product: str = "carryforward",
         read_at: str = READ_AT) -> Dict[str, Any]:
    """A broker NET position row as read_broker returns it (HubPosition dict + its private keys). MOCK."""
    return {"symbol": symbol, "exchange": exchange, "quantity": qty, "avg_price": avg, "last_price": last, "pnl": pnl,
            "product": product, "product_raw": {"carryforward": "NRML", "delivery": "CNC", "intraday": "MIS"}.get(product),
            "segment": segment, "is_intraday": product == "intraday", "instrument_type": itype, "expiry": expiry,
            "strike": strike, "kind": "net", "name": None,
            "_account_id": account, "_broker": broker, "_broker_display": display, "_read_at": read_at}


def entry(account: str = ZID, broker: str = "zerodha", display: str = "Zerodha", *, ok: bool = True, code: Optional[str] = None,
          message: Optional[str] = None, read_at: str = READ_AT) -> Dict[str, Any]:
    return {"source": "broker", "account_id": account, "broker": broker, "broker_display": display, "label": None, "ok": ok,
            "error": None if ok else {"code": code, "message": message}, "read_at": read_at if ok else None, "rows": 0}


def live_view(rows: List[Dict[str, Any]], entries: List[Dict[str, Any]], quotes: Dict[str, Quote]) -> live.LiveView:
    bb = live.BrokerBook(entries=entries, rows=rows, read_mono=0.0)
    lives = live.legs(bb)
    accts = live.accounts(bb, NOW)
    by_symbol = {l.leg.position_key: quotes.get(l.leg.symbol) for l in lives}
    priced = {k: v for k, v in by_symbol.items() if v is not None}
    return live.LiveView(live.position_rows(lives, priced, today=TODAY, now=NOW), accts, live.unavailable_note(bb, accts), lives)


def build(open_items=(), *, lv: Optional[live.LiveView] = None, mode="ALL", account="ALL", segment="ALL", quotes=None):
    book = bk.Book(open=list(open_items), closed=[])
    f = dash.make_filters(segment, "ALL", None, None, date(2026, 11, 4), mode, account)
    return dash.build(book, quotes or {}, MARKET_OPEN, ACCOUNT, LIMITS, f, now=NOW, underlying_ltp={}, live=lv)


def paper_item(tid="c1", sym="AAA", qty=10, fill=100.0):
    pub = cash_pub(tid, sym, qty, fill, stop=95.0, target=120.0)
    return bk.cash_item(pub)


def round_trip(seg: str, qty: float, avg: float, ltp: float) -> float:
    o, c = ("BUY", "SELL") if qty > 0 else ("SELL", "BUY")
    return cost_card.add(cost_card.order_side(seg, o, abs(qty) * avg, svc.COST_MODEL),
                         cost_card.order_side(seg, c, abs(qty) * ltp, svc.COST_MODEL))["total"]


THREE = [brow("INFY", 50, 1500.0, segment="equity", exchange="NSE", product="delivery", pnl=900.0),
         brow("SONBLW", -1225, 890.0, account=IID, broker="icicidirect", display="ICICI Direct", itype="FUT",
              expiry="2026-11-24", pnl=-1200.0),
         brow("NIFTY26N1226000CE", 75, 120.0, itype="CE", expiry="2026-11-12", strike=26000, pnl=None)]
QUOTES = {"INFY": q(1518.0), "SONACOMS": q(888.0), "NIFTY": q(150.0)}


# ── V2-05 live rows ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_v2_05_live_rows_signed_quantity_unrealized_and_broker_figure():
    lv = live_view(THREE, [entry(), entry(IID, "icicidirect", "ICICI Direct")], QUOTES)
    by = {r["symbol"]: r for r in lv.positions}
    infy, sona, nifty = by["INFY"], by["SONACOMS"], by["NIFTY"]          # SONBLW is ICICI's code for SONACOMS
    assert infy["mode"] == "LIVE" and infy["account_id"] == ZID and infy["account"] == "Zerodha"
    assert infy["side"] == "LONG" and infy["net_quantity"] == 50 and infy["segment"] == "EQUITY"
    assert infy["unrealized_pnl"] == 900.0                               # (1518 − 1500) × 50
    assert infy["realized_pnl"] is None and infy["broker_pnl"] == 900.0 and infy["gross_pnl"] == 900.0
    assert infy["charges_estimated"] == round(round_trip("equity_delivery", 50, 1500.0, 1518.0), 2)
    assert infy["net_pnl"] == round(900.0 - infy["charges_estimated"], 2)
    assert infy["exposure_rs"] == 75900.0 and infy["price_status"] == LIVE and infy["product"] == "delivery"
    assert sona["side"] == "SHORT" and sona["segment"] == "FUTURES" and sona["instrument"].startswith("SONACOMS")
    assert sona["unrealized_pnl"] == 2450.0                              # (888 − 890) × −1225
    assert sona["account_id"] == IID and sona["broker_pnl"] == -1200.0
    assert nifty["segment"] == "OPTIONS" and nifty["unrealized_pnl"] == 2250.0    # (150 − 120) × 75
    assert nifty["broker_pnl"] is None                                   # the broker sent none: never 0
    assert nifty["expiry"] == "2026-11-12" and "26000" in nifty["instrument"]


# ── V2-09 no levels, journal or edit for live ──────────────────────────────────────────────────────────────────────────
def test_v2_09_live_rows_have_no_levels_and_are_not_editable():
    lv = live_view(THREE, [entry(), entry(IID, "icicidirect", "ICICI Direct")], QUOTES)
    for r in lv.positions:
        assert r["stop_loss"] is None and r["target"] is None and r["pending_levels"] is None
        assert r["editable_levels"] is False and r["executions"] == [] and r["executions_note"]
        assert r["risk_used_pct"] is None and r["day_pnl"] is None and r["opened_at"] is None


# ── V2-08 unmapped / unpriced ──────────────────────────────────────────────────────────────────────────────────────────
def test_v2_08_unmapped_contract_without_a_price_is_missing_and_left_out():
    rows = [brow("ZZZQQQ", 10, 50.0, account=IID, broker="icicidirect", display="ICICI Direct", itype="FUT", expiry="2026-11-24"),
            brow("INFY", 10, 1500.0, segment="equity", exchange="NSE", product="delivery")]
    lv = live_view(rows, [entry(IID, "icicidirect", "ICICI Direct"), entry()], {"INFY": q(1510.0)})
    bad = next(r for r in lv.positions if r["account_id"] == IID)
    assert bad["price_status"] == MISSING and bad["unrealized_pnl"] is None and bad["net_pnl"] is None
    assert bad["contract_problem"] and "ZZZQQQ" in bad["contract_problem"]
    d = build(lv=lv, mode="LIVE")
    assert d["summary"]["complete"] is False and d["summary"]["unpriced_positions"] == 1
    assert d["summary"]["unrealized_pnl"] == 100.0                        # INFY only: (1510 − 1500) × 10
    assert any(a["type"] == "MISSING_PRICE" for a in d["risk"]["alerts"])


def test_v2_08_unmapped_contract_with_the_brokers_price_is_priced_at_it_and_says_so():
    rows = [brow("ZZZQQQ", 10, 50.0, account=IID, broker="icicidirect", display="ICICI Direct", itype="FUT", expiry="2026-11-24",
                 last=52.0)]
    lv = live_view(rows, [entry(IID, "icicidirect", "ICICI Direct")], {})
    r = lv.positions[0]
    assert r["ltp"] == 52.0 and r["price_status"] == DELAYED and "Broker" in r["price_source"]
    assert r["unrealized_pnl"] == 20.0


# ── V2-01 / V2-02 / V2-04 the selection ───────────────────────────────────────────────────────────────────────────────
def test_v2_01_02_04_mode_and_account_select_but_modes_and_accounts_cover_everything():
    lv = live_view(THREE, [entry(), entry(IID, "icicidirect", "ICICI Direct")], QUOTES)
    item = paper_item()
    quotes = {"c1": q(110.0)}
    every = build([item], lv=lv, quotes=quotes)
    paper = build([item], lv=lv, quotes=quotes, mode="PAPER")
    only_live = build([item], lv=lv, quotes=quotes, mode="LIVE")
    icici = build([item], lv=lv, quotes=quotes, account=IID)
    acct_paper = build([item], lv=lv, quotes=quotes, account="paper")
    assert every["mode"] == "ALL" and {p["mode"] for p in every["positions"]} == {"PAPER", "LIVE"} and len(every["positions"]) == 4
    assert [p["mode"] for p in paper["positions"]] == ["PAPER"] and paper["mode"] == "PAPER"
    assert {p["mode"] for p in only_live["positions"]} == {"LIVE"} and len(only_live["positions"]) == 3
    assert [p["account_id"] for p in icici["positions"]] == [IID]
    assert [p["account_id"] for p in acct_paper["positions"]] == ["paper"]
    assert icici["filters"]["account"] == IID and only_live["filters"]["mode"] == "LIVE"
    # the summary is the selection's: Live has no realized and no capital, so no return %
    assert only_live["summary"]["unrealized_pnl"] == 900.0 + 2450.0 + 2250.0
    assert only_live["summary"]["return_pct"] is None and only_live["summary"]["allocated_capital"] is None
    assert paper["summary"]["unrealized_pnl"] == 100.0 and paper["summary"]["return_pct"] is not None
    assert every["summary"]["return_pct"] is None                       # broker rows in it: no capital for them
    # modes and accounts are the same whatever the selection
    for d in (every, paper, only_live, icici, acct_paper):
        assert d["modes"] == every["modes"]
        assert [a["account_id"] for a in d["accounts"]] == ["paper", ZID, IID]
    m = every["modes"]
    assert m["PAPER"]["unrealized_pnl"] == 100.0 and m["PAPER"]["open_positions"] == 1 and m["PAPER"]["available"] is True
    assert m["LIVE"]["unrealized_pnl"] == 5600.0 and m["LIVE"]["realized_pnl"] is None and m["LIVE"]["open_positions"] == 3
    assert m["LIVE"]["available"] is True and m["LIVE"]["capital"] is None and m["LIVE"]["return_pct"] is None
    accts = {a["account_id"]: a for a in every["accounts"]}
    assert accts[ZID]["open_positions"] == 2 and accts[IID]["open_positions"] == 1 and accts["paper"]["open_positions"] == 1
    assert accts[IID]["net_pnl"] == next(p for p in every["positions"] if p["account_id"] == IID)["net_pnl"]
    # by segment and exposure follow the selection
    assert {s["segment"] for s in only_live["by_segment"]} == {"EQUITY", "FUTURES", "OPTIONS"}
    assert only_live["summary"]["exposure_rs"] == round(75900.0 + 1225 * 888.0 + 75 * 150.0, 2)
    assert only_live["risk"]["margin"]["used_pct"] is None and paper["risk"]["margin"]["used_pct"] == 10.0
    assert only_live["strategies"] == [] and only_live["closed"] == [] and only_live["pending_entries"] == []


def test_v2_segment_filter_applies_to_live_rows_and_modes():
    lv = live_view(THREE, [entry(), entry(IID, "icicidirect", "ICICI Direct")], QUOTES)
    d = build([], lv=lv, segment="OPTIONS")
    assert [p["symbol"] for p in d["positions"]] == ["NIFTY"]
    assert d["modes"]["LIVE"]["open_positions"] == 1


def test_v2_02_bad_mode_and_account_shapes_are_refused():
    with pytest.raises(ValueError, match="invalid_mode"):
        dash.make_filters("ALL", "ALL", None, None, date(2026, 11, 4), "XYZ")
    with pytest.raises(ValueError, match="invalid_account"):
        dash.make_filters("ALL", "ALL", None, None, date(2026, 11, 4), "ALL", "bad id!")
    assert dash.make_filters("ALL", "ALL", None, None, date(2026, 11, 4), "live", "Paper").account == "paper"


# ── V2-03 / V2-06 / V2-07 accounts, failures, cache ───────────────────────────────────────────────────────────────────
def test_v2_03_account_states():
    old = (NOW - timedelta(seconds=500)).isoformat()
    cases = [(entry(), "OK"), (entry(read_at=old), "STALE"),
             (entry(ok=False, code=hub.CODE_SESSION_EXPIRED, message="Your Zerodha session has ended."), "SIGN_IN"),
             (entry(ok=False, code=hub.CODE_READ_FAILED, message="Could not read."), "ERROR"),
             (entry(ok=False, code="BROKER_HUB_OFF", message="Broker connections are not enabled."), "OFF")]
    for e, want in cases:
        state, note = live.account_state(e, NOW, ttl=60)
        assert state == want, (e, state)
        assert (note is None) == (want == "OK")


def test_v2_06_every_account_signed_out_makes_live_unavailable_with_the_reasons():
    es = [entry(ok=False, code=hub.CODE_SESSION_EXPIRED, message="Your Zerodha session has ended. Reconnect the account to continue."),
          entry(IID, "icicidirect", "ICICI Direct", ok=False, code=hub.CODE_SESSION_EXPIRED,
                message="Your ICICI Direct session has ended. Reconnect the account to continue.")]
    lv = live_view([], es, {})
    d = build([paper_item()], lv=lv, quotes={"c1": q(110.0)})
    assert d["modes"]["LIVE"]["available"] is False and "Zerodha" in d["modes"]["LIVE"]["note"] and "ICICI" in d["modes"]["LIVE"]["note"]
    assert [a["state"] for a in d["accounts"]] == ["OK", "SIGN_IN", "SIGN_IN"]
    assert sum(1 for a in d["risk"]["alerts"] if a["type"] == "BROKER") == 2
    assert d["summary"]["return_pct"] is not None                       # no broker rows: the paper return stands


def test_v2_07_one_broker_read_per_ttl_and_a_failed_refresh_keeps_the_last_read(monkeypatch):
    monkeypatch.setattr(live, "_CACHE", {})
    calls = {"n": 0, "fail": False}

    async def reader(request, db, uid):
        calls["n"] += 1
        if calls["fail"]:
            raise RuntimeError("broker down")
        return [entry()], [brow("INFY", 1, 10.0, segment="equity", exchange="NSE")]

    async def go():
        a = await live.read_broker_book(None, None, "u1", reader=reader, ttl=60)
        b = await live.read_broker_book(None, None, "u1", reader=reader, ttl=60)
        assert a is b and calls["n"] == 1
        calls["fail"] = True
        c = await live.read_broker_book(None, None, "u1", reader=reader, ttl=0)    # due again, the read fails
        assert calls["n"] == 2 and c.rows and c.entries[0]["ok"]                    # the last read is kept
        d = await live.read_broker_book(None, None, "u2", reader=reader, ttl=60)    # nothing earlier for u2
        assert d.error and d.rows == [] and d.entries == []
    asyncio.run(go())


def test_v2_07_a_transient_account_failure_keeps_that_accounts_last_rows(monkeypatch):
    first = ([entry(), entry(IID, "icicidirect", "ICICI Direct")],
             [brow("INFY", 1, 10.0, segment="equity", exchange="NSE"),
              brow("SONBLW", 1, 5.0, account=IID, broker="icicidirect", display="ICICI Direct", itype="FUT", expiry="2026-11-24")])
    second = ([entry(), entry(IID, "icicidirect", "ICICI Direct", ok=False, code=hub.CODE_READ_FAILED, message="x")],
              [brow("INFY", 2, 10.0, segment="equity", exchange="NSE")])
    old = live.BrokerBook(first[0], first[1], 0.0)
    new = live._merge(old, second[0], second[1], 1.0)
    assert [r["symbol"] for r in new.rows] == ["INFY", "SONBLW"] and new.rows[0]["quantity"] == 2
    ic = next(e for e in new.entries if e["account_id"] == IID)
    assert ic["ok"] and ic["refresh_error"]["code"] == hub.CODE_READ_FAILED
    expired = ([entry(), entry(IID, "icicidirect", "ICICI Direct", ok=False, code=hub.CODE_SESSION_EXPIRED, message="x")], second[1])
    gone = live._merge(old, expired[0], expired[1], 1.0)
    assert [r["symbol"] for r in gone.rows] == ["INFY"]                  # an ended session keeps nothing


# ── the routes: mode / account / accounts on the real desk harness ────────────────────────────────────────────────────
def test_v2_01_02_03_route_mode_account_and_accounts(world, api, pnl_api):
    client, livep = pnl_api
    fresh = datetime.now(timezone.utc).isoformat()                       # the route ages a read against the real clock
    client.brokers["entries"] = [entry(read_at=fresh), entry(IID, "icicidirect", "ICICI Direct", ok=False, code=hub.CODE_SESSION_EXPIRED,
                                                message="Your ICICI Direct session has ended. Reconnect the account to continue.")]
    client.brokers["rows"] = [brow("INFY", 50, 1500.0, segment="equity", exchange="NSE", product="delivery")]
    livep["INFY"] = 1518.0
    r = api.post(TRADES_URL, json={"symbol": "FIXA", "quantity": 10, "entry_price": 100.0, "stop_price": 95.0, "target_price": 110.0}, headers=A)
    assert r.status_code == 201, r.text
    body = client.get("/api/desk/pnl", params={"period": "ALL"}, headers=A).json()
    assert {p["mode"] for p in body["positions"]} == {"PAPER", "LIVE"}
    assert [(a["account_id"], a["state"]) for a in body["accounts"]] == [("paper", "OK"), (ZID, "OK"), (IID, "SIGN_IN")]
    infy = next(p for p in body["positions"] if p["mode"] == "LIVE")
    assert infy["unrealized_pnl"] == 900.0 and infy["price_status"] == LIVE
    only_live = client.get("/api/desk/pnl", params={"period": "ALL", "mode": "LIVE"}, headers=A).json()
    assert {p["mode"] for p in only_live["positions"]} == {"LIVE"}
    by_acct = client.get("/api/desk/pnl", params={"period": "ALL", "account": ZID}, headers=A).json()
    assert [p["account_id"] for p in by_acct["positions"]] == [ZID]
    assert client.get("/api/desk/pnl", params={"mode": "XYZ"}, headers=A).status_code == 422
    bad = client.get("/api/desk/pnl", params={"account": "someone-elses"}, headers=A)
    assert bad.status_code == 422 and bad.json()["detail"] == "invalid_account"
    assert client.get("/api/desk/pnl/stream", params={"account": "someone-elses"}, headers=A).status_code == 422
    assert client.brokers["reads"] == 1                                  # one broker read for all of the above (TTL)


def test_v2_06_route_answers_when_the_broker_read_fails(world, api, pnl_api):
    client, _ = pnl_api
    client.brokers["fail"] = RuntimeError("down")
    got = client.get("/api/desk/pnl", headers=A)
    assert got.status_code == 200
    body = got.json()
    assert body["modes"]["LIVE"]["available"] is False and "could not be read" in body["modes"]["LIVE"]["note"]
    assert [a["account_id"] for a in body["accounts"]] == ["paper"]


# ── V2-10 the curves ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_v2_10_trade_curve_since_entry_carries_forward_and_nets_the_charges():
    series = {"t1": [["2026-11-03T09:15:00+05:30", 0, 0, 0, 101.0, 0], ["2026-11-03T15:15:00+05:30", 0, 0, 0, 104.0, 0],
                     ["2026-11-04T09:15:00+05:30", 0, 0, 0, 99.0, 0]]}
    lines = [{"key": "t1", "net_quantity": 10, "avg_price": 100.0, "multiplier": 1.0, "prev_close": None}]
    out = timeseries.trade_curve(series, lines, charges=40.0, start="2026-11-03T10:00:00+05:30")
    assert [p["t"][:16] for p in out["points"]] == ["2026-11-03T15:15", "2026-11-04T09:15"]   # before the fill: not drawn
    assert out["points"][0]["gross_pnl"] == 40.0 and out["points"][0]["net_pnl"] == 0.0
    assert out["points"][1]["gross_pnl"] == -10.0 and out["points"][1]["net_pnl"] == -50.0
    gone = timeseries.trade_curve({}, lines, charges=0.0, start="2026-11-03T00:00:00+05:30")
    assert gone["points"] == [] and gone["partial"] is True


@pytest.fixture
def fake_candles(monkeypatch):
    seen: List[Dict[str, Any]] = []

    async def fake_series(lines, iv, kname, *, sessions, session_open, now):
        seen.append({"keys": [ln["key"] for ln in lines], "sessions": sessions})
        out = {}
        for ln in lines:
            base = ln["avg_price"]
            out[ln["key"]] = [["2026-10-09T09:15:00+05:30", 0, 0, 0, base, 0], ["2026-10-12T09:15:00+05:30", 0, 0, 0, base + 1, 0],
                              ["2026-10-12T11:15:00+05:30", 0, 0, 0, base + 2, 0]]
        return out, []

    monkeypatch.setattr(timeseries, "_series", fake_series)
    return seen


def test_v2_10_route_curves_by_mode_and_by_trade(world, api, pnl_api, fake_candles, monkeypatch):
    client, livep = pnl_api

    class AtTheDesk(datetime):                                           # the desk harness's day: 12 Oct, 11:30 IST
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 12, 6, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(pnl_route, "datetime", AtTheDesk)
    client.brokers["entries"] = [entry()]
    client.brokers["rows"] = [brow("INFY", 5, 1500.0, segment="equity", exchange="NSE", product="delivery")]
    livep["INFY"] = 1502.0
    r = api.post(TRADES_URL, json={"symbol": "FIXA", "quantity": 10, "entry_price": 100.0, "stop_price": 95.0, "target_price": 110.0}, headers=A)
    tid = r.json()["trade"]["id"]
    lv = client.get("/api/desk/pnl/timeseries", params={"interval": "15m", "mode": "LIVE"}, headers=A)
    assert lv.status_code == 200, lv.text
    assert lv.json()["mode"] == "LIVE" and fake_candles[-1]["keys"][0].startswith("live:")
    paper = client.get("/api/desk/pnl/timeseries", params={"interval": "15m", "mode": "PAPER"}, headers=A).json()
    assert paper["mode"] == "PAPER" and fake_candles[-1]["keys"] == [tid]
    tr = client.get("/api/desk/pnl/timeseries", params={"interval": "15m", "trade": tid}, headers=A)
    assert tr.status_code == 200, tr.text
    body = tr.json()
    assert body["trade"] == tid and body["mode"] == "PAPER" and body["points"]
    assert body["points"][0]["t"] >= "2026-10-12T10:30" and body["since_entry"] is True   # opened 10:30 IST: from the fill
    live_id = next(k for k in fake_candles[0]["keys"] if k.startswith("live:"))
    lt = client.get("/api/desk/pnl/timeseries", params={"interval": "15m", "trade": live_id}, headers=A).json()
    assert lt["mode"] == "LIVE" and lt["since_entry"] is False and "broker" in lt["basis"].lower()
    assert client.get("/api/desk/pnl/timeseries", params={"trade": "nope"}, headers=A).status_code == 404
    assert client.get("/api/desk/pnl/timeseries", params={"mode": "X"}, headers=A).status_code == 422


# ── V2-11 the journal ─────────────────────────────────────────────────────────────────────────────────────────────────
class FakeStore:
    """The Scan dashboard's Redis store, in memory. MOCK records."""

    def __init__(self, strong: Dict[str, List[Dict[str, Any]]] = None, scores: Dict[str, Dict[str, Any]] = None,
                 marks: Dict[str, List[Dict[str, Any]]] = None, fail: bool = False):
        self.strong, self.scores, self.marks, self.fail = strong or {}, scores or {}, marks or {}, fail
        self.writes = 0

    async def read(self, index: str, last: int) -> List[str]:
        if self.fail:
            raise RuntimeError("redis down")
        day = index.split(":")[3]
        if index.endswith(":strong"):
            return [json.dumps(r) for r in self.strong.get(day, [])]
        return [json.dumps(m) for m in self.marks.get(day, [])]

    async def get(self, key: str) -> Optional[str]:
        if self.fail:
            raise RuntimeError("redis down")
        day = key.split(":")[3]
        doc = self.scores.get(day)
        return json.dumps(doc) if doc else None

    async def add(self, *a, **k):
        self.writes += 1

    async def put(self, *a, **k):
        self.writes += 1


STRONG = {"symbol": "AAA", "name": "Aaa Ltd", "score_at": 82, "parts_at": {"quality": 24, "trend": 16, "reason": 14, "size": 10,
          "participation": 6, "penalty": 0}, "reasons_at": ["RSI(14) 58", "Above 6 of 8 daily averages (5 to 200 day)"],
          "penalties_at": [], "lists_at": [{"id": "w1", "title": "Breakout"}], "rules": "scan-plan-v3", "entry": 1245.0,
          "stop_loss": 1220.0, "target_1": 1295.0, "target_2": 1345.0, "risk_per_share": 25.0, "rr_1": 2, "rr_2": 4,
          "atr": 12.5, "sma20": 1230.0, "trend_exit": "A daily close below the 20-day average.", "plan_ok": True,
          "plan_note": None, "first_strong": "2026-11-04T10:02:11+05:30"}


def jbook(opened="2026-11-04T04:40:00+00:00", kind="cash", source=None):
    if kind == "cash":
        pub = cash_pub("c1", "AAA", 10, 100.0, stop=95.0)
        pub.update(opened_at=opened, source=source, rationale="Breakout on volume", note="MOCK")
        return bk.Book(open=[bk.cash_item(pub)])
    return bk.Book(open=[bk.strategy_item(spread_pub("st1"))])


def test_v2_11_journal_finds_the_strong_record_of_the_signal_day():
    store = FakeStore(strong={"2026-11-04": [{**STRONG, "symbol": "BBB"}, STRONG]})
    body = asyncio.run(jr.journal(jbook(), "c1", now=NOW, store=store))
    assert body["found"] is True and body["entry_day"] == "2026-11-04" and body["symbol"] == "AAA"
    s = body["signal"]
    assert s["kind"] == "strong" and s["score"] == 82 and s["parts"]["quality"] == 24 and s["lists"] == [{"id": "w1", "title": "Breakout"}]
    assert (s["entry"], s["stop_loss"], s["target_1"], s["target_2"], s["rr_1"], s["rr_2"]) == (1245.0, 1220.0, 1295.0, 1345.0, 2, 4)
    assert body["trade"]["rationale"] == "Breakout on volume" and store.writes == 0


def test_v2_11_journal_falls_back_to_the_days_score_then_says_why():
    store = FakeStore(scores={"2026-11-04": {"as_of": "x", "scores": {"AAA": {"score": 55, "parts": {"quality": 20}, "reasons": ["r1"],
                                                                            "penalties": [], "note": None}}}},
                      marks={"2026-11-04": [{"symbol": "AAA", "widget_id": "w2", "widget_title": "Volume spike"},
                                            {"symbol": "AAA", "widget_id": "w2", "widget_title": "Volume spike"}]})
    body = asyncio.run(jr.journal(jbook(), "c1", now=NOW, store=store))
    assert body["found"] and body["signal"]["kind"] == "scored" and body["signal"]["score"] == 55
    assert body["signal"]["lists"] == [{"id": "w2", "title": "Volume spike"}] and body["signal"]["stop_loss"] is None
    none = asyncio.run(jr.journal(jbook(), "c1", now=NOW, store=FakeStore()))
    assert none["found"] is False and none["why"] == "No scan signal for AAA on 4 Nov."
    old = asyncio.run(jr.journal(jbook(opened="2026-10-28T04:40:00+00:00"), "c1", now=NOW, store=FakeStore()))
    assert old["found"] is False and "kept 3 days" in old["why"] and "28 Oct" in old["why"]
    src = asyncio.run(jr.journal(jbook(opened="2026-11-04T04:40:00+00:00", source={"kind": "scanner", "bucket": "b", "signal_date": "2026-11-03"}),
                                 "c1", now=NOW, store=FakeStore(strong={"2026-11-03": [STRONG]})))
    assert src["entry_day"] == "2026-11-03" and src["found"]              # the trade's own signal date wins
    down = asyncio.run(jr.journal(jbook(), "c1", now=NOW, store=FakeStore(fail=True)))
    assert down["found"] is False and "could not be read" in down["why"]


def test_v2_11_journal_is_for_paper_share_trades_only(world, api, pnl_api, monkeypatch):
    assert asyncio.run(jr.journal(jbook(kind="strategy"), "st1", now=NOW, store=FakeStore())) is None
    assert asyncio.run(jr.journal(jbook(), "someone-elses", now=NOW, store=FakeStore())) is None
    client, _ = pnl_api
    from services.scan_builder import signals as sig
    monkeypatch.setattr(sig, "get_store", lambda: FakeStore())
    r = api.post(TRADES_URL, json={"symbol": "FIXA", "quantity": 10, "entry_price": 100.0, "stop_price": 95.0, "target_price": 110.0}, headers=A)
    tid = r.json()["trade"]["id"]
    got = client.get(f"/api/desk/pnl/journal/{tid}", headers=A)
    assert got.status_code == 200 and got.json()["symbol"] == "FIXA" and got.json()["found"] is False
    assert client.get("/api/desk/pnl/journal/live:acc:NSE:INFY:CNC", headers=A).status_code == 404
    assert client.get(f"/api/desk/pnl/journal/{tid}", headers={"X-Test-User": "user_b"}).status_code == 404
    assert client.get(f"/api/desk/pnl/journal/{tid}").status_code == 401


# ── v2 paper fields ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_v2_paper_rows_carry_levels_in_force_pending_change_and_editability():
    pub = cash_pub("c1", "AAA", 10, 100.0, stop=95.0, target=120.0)
    pub.update(current_stop=97.0, current_target=125.0,
               pending_levels={"stop_loss": 98.0, "target": 130.0, "from_session": "2026-11-05", "version": 2})
    d = build([bk.cash_item(pub)], quotes={"c1": q(110.0)})
    r = d["positions"][0]
    assert r["stop_loss"] == 97.0 and r["target"] == 125.0
    assert r["pending_levels"] == {"stop_loss": 98.0, "target": 130.0, "from_session": "2026-11-05", "version": 2}
    assert r["editable_levels"] is True and r["account_id"] == "paper" and r["exposure_rs"] == 1100.0
    old = build([bk.cash_item(cash_pub("c2", "BBB", 10, 100.0, stop=95.0, target=120.0))], quotes={"c2": q(110.0)})
    assert old["positions"][0]["target"] == 120.0 and old["positions"][0]["pending_levels"] is None   # older ledger: v1
    st = build([bk.strategy_item(spread_pub("st1"))], quotes={"st1:0": q(200.0), "st1:1": q(110.0)})
    assert all(p["editable_levels"] is False for p in st["positions"])


# ── V2-18 read-only ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_v2_18_reads_write_nothing_and_no_order_call_exists(world, api, pnl_api, fake_candles, monkeypatch):
    client, livep = pnl_api
    client.brokers["entries"] = [entry()]
    client.brokers["rows"] = [brow("INFY", 5, 1500.0, segment="equity", exchange="NSE")]
    livep["INFY"] = 1502.0
    from services.scan_builder import signals as sig
    store = FakeStore()
    monkeypatch.setattr(sig, "get_store", lambda: store)
    r = api.post(TRADES_URL, json={"symbol": "FIXA", "quantity": 10, "entry_price": 100.0, "stop_price": 95.0, "target_price": 110.0}, headers=A)
    tid = r.json()["trade"]["id"]
    writes = sum(c.writes for c in world.db.cols.values())
    for mode in ("ALL", "PAPER", "LIVE"):
        assert client.get("/api/desk/pnl", params={"mode": mode, "period": "ALL"}, headers=A).status_code == 200
        assert client.get("/api/desk/pnl/timeseries", params={"mode": mode}, headers=A).status_code == 200
    assert client.get("/api/desk/pnl/timeseries", params={"trade": tid}, headers=A).status_code == 200
    assert client.get(f"/api/desk/pnl/journal/{tid}", headers=A).status_code == 200
    assert sum(c.writes for c in world.db.cols.values()) == writes and store.writes == 0
    root = Path(__file__).resolve().parents[1]
    order = re.compile(r"\b(place_order|modify_order|cancel_order|place_gtt|modify_gtt|exit_order)\b")
    for f in list((root / "services" / "paper_pnl").glob("*.py")) + [root / "routes" / "desk_pnl.py"]:
        assert not order.search(f.read_text()), f.name
