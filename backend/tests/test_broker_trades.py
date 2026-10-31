"""Broker trades in the Copilot's daily review: the read-only trade-book readers (Zerodha, ICICI Direct), the kept daily book
(services/positions/trade_book.py), round-trip matching, plan adherence and the review section (services/copilot_visual/
broker_review.py + builders.daily_review). Test-case ids BT-* match test_reports/copilot_broker_trades_20261031.md.

What is replaced (MOCK — not real data): every broker response. NO broker is ever called here. The Kite client is a fake with a
`trades()` method; ICICI Direct's `/trades` rows are RECORDED-SHAPE fixtures built from the field names ICICI's trade-list
documentation lists (`stock_code`, `action`, `quantity`, `average_price`, `product_type`, `expiry_date`, `right`, `strike_price`,
`exchange_code`, `trade_date`) — NOT seen on a live session (the first real read must be compared with the broker's screen).
Every symbol, quantity and price is invented. Mongo is a small fake; matching, storing, adherence and the blocks run for real.
"""
from __future__ import annotations

import asyncio
import inspect
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from services.brokers import hub_reads as hub, icicidirect, registry, sessions, zerodha
from services.brokers.base import AccessToken, BrokerTrade
from services.brokers.fenix_reader import BrokerNotSupported, BrokerSessionExpired
from services.copilot_visual import broker_review, builders, readers as rd
from services.copilot_visual.intents import Intent
from services.copilot_visual.payload import facts, validate
from services.positions import trade_book as tb
from tests.test_copilot_visual import Src, TODAY, blocks as blocks_of, closed
from tests.test_open_book import FakeDB, doc

IST = timezone(timedelta(hours=5, minutes=30))


def run(coro):
    return asyncio.run(coro)


def fill(symbol, side, qty, price, at="2026-10-30T05:00:00+00:00", exchange="NSE", **kw):
    d = {"symbol": symbol, "exchange": exchange, "side": side, "quantity": qty, "price": price, "traded_at": at, "trade_id": kw.pop("trade_id", f"{symbol}-{at}-{side}-{qty}"),
         "order_id": None, "product_raw": None, "instrument_type": None, "expiry": None, "strike": None, "fees_rs": None}
    d.update(kw)
    return d


def day(d, trades, account="a1", broker="icicidirect", display="ICICI Direct"):
    return {"account_id": account, "broker": broker, "broker_display": display, "day": d, "trades": trades, "last_seen_at": f"{d}T10:00:00+00:00"}


# ── BT-1 / BT-2: the adapters' trade reads ───────────────────────────────────
def test_bt1_zerodha_trades_are_read_from_kites_trades_call_only(monkeypatch):
    called = []

    class Kite:
        def trades(self):
            called.append("trades")
            return [{"tradingsymbol": "RELIANCE", "exchange": "NSE", "transaction_type": "BUY", "quantity": 10, "average_price": 1400.5,
                     "fill_timestamp": datetime(2026, 10, 30, 10, 15, tzinfo=IST), "trade_id": "t1", "order_id": "o1", "product": "MIS"},
                    {"tradingsymbol": "NIFTY26NOV23000CE", "exchange": "NFO", "transaction_type": "SELL", "quantity": 75, "average_price": 120.0,
                     "fill_timestamp": "2026-10-30T11:00:00+05:30", "trade_id": "t2", "product": "NRML"},
                    {"tradingsymbol": "BAD", "exchange": "NSE", "transaction_type": "BUY", "quantity": 0, "average_price": 10}]

        def __getattr__(self, name):                            # any order call would land here and fail the test
            raise AssertionError(f"the trade read touched {name}")
    monkeypatch.setattr(zerodha, "_kite", lambda token="": Kite())
    out = run(zerodha.fetch_trades(AccessToken("T")))
    assert called == ["trades"] and len(out) == 2
    assert (out[0].side, out[0].quantity, out[0].price, out[0].exchange, out[0].product_raw) == ("buy", 10, 1400.5, "NSE", "MIS")
    assert out[0].traded_at.startswith("2026-10-30T10:15") and out[1].symbol == "NIFTY26NOV23000CE" and out[1].side == "sell"


ICICI_ROWS = {  # RECORDED-SHAPE MOCK of /trades rows (field names from ICICI's documentation; not seen live)
    "NSE": [{"book_type": "Normal", "trade_date": "30-Oct-2026 10:15:00", "stock_code": "RELIND", "action": "Buy", "quantity": "10", "average_price": "1400.50",
             "exchange_trade_id": "x1", "order_id": "o1", "product_type": "Cash", "expiry_date": None, "right": None, "strike_price": None, "exchange_code": "NSE"}],
    "NFO": [{"trade_date": "30-Oct-2026", "stock_code": "CNXBAN", "action": "Sell", "quantity": "30", "average_price": "410.25", "exchange_trade_id": "x2",
             "product_type": "Options", "expiry_date": "25-Nov-2026", "right": "Put", "strike_price": "54500", "exchange_code": "NFO"},
            {"trade_date": "30-Oct-2026", "stock_code": "SONBLW", "action": "Buy", "quantity": "1225", "average_price": "890", "product_type": "Futures",
             "expiry_date": "24-Nov-2026", "right": "Others", "strike_price": "0", "exchange_code": "NFO"},
            {"trade_date": "30-Oct-2026", "stock_code": "X", "action": "Hold", "quantity": "1", "average_price": "1", "exchange_code": "NFO"}]}


def test_bt2_icici_trades_call_the_trades_endpoint_once_per_exchange_and_parse_the_rows(monkeypatch):
    seen = []

    async def get(path, payload, token, what):
        seen.append((path, payload["exchange_code"], sorted(payload)))
        return ICICI_ROWS[payload["exchange_code"]]
    monkeypatch.setattr(icicidirect, "_signed_get", get)
    out = run(icicidirect.fetch_trades(AccessToken("T")))
    assert [(p, e) for p, e, _ in seen] == [("trades", "NSE"), ("trades", "NFO")] and all(k == ["exchange_code", "from_date", "to_date"] for _, _, k in seen)
    assert len(out) == 3                                             # the "Hold" row is not a fill
    cash, opt, fut = out
    assert (cash.symbol, cash.side, cash.quantity, cash.price, cash.instrument_type) == ("RELIND", "buy", 10.0, 1400.5, None)
    assert cash.traded_at.startswith("2026-10-30T10:15:00+05:30")
    assert (opt.instrument_type, opt.expiry, opt.strike, opt.side) == ("PE", "2026-11-25", 54500.0, "sell")
    assert (fut.instrument_type, fut.expiry, fut.strike) == ("FUT", "2026-11-24", None)


# ── BT-3: the hub read ───────────────────────────────────────────────────────
def test_bt3_hub_trade_read_rules(monkeypatch):
    ended = []

    async def end(db, account_id, reason, **k):
        ended.append((account_id, reason))
    monkeypatch.setattr(sessions, "end_session", end)
    monkeypatch.setattr(hub, "_live_token", lambda d: AccessToken("T"))
    calls = []

    async def fetch(token):
        calls.append(1)
        return [BrokerTrade("RELIANCE", "NSE", "buy", 5, 100.0, "2026-10-30T10:00:00+05:30")]
    mod = SimpleNamespace(DISPLAY="Fake", IMPLEMENTED=True, fetch_trades=staticmethod(fetch))
    monkeypatch.setattr(registry, "get", lambda slug: mod)
    rows = run(hub.read_account_trades(None, {"account_id": "a1", "broker": "zerodha"}))
    assert rows == [{"symbol": "RELIANCE", "exchange": "NSE", "side": "buy", "quantity": 5, "price": 100.0, "traded_at": "2026-10-30T10:00:00+05:30",
                     "trade_id": None, "order_id": None, "product_raw": None, "instrument_type": None, "expiry": None, "strike": None, "fees_rs": None}]
    # a broker with no trade-book reader is "not supported" with its name, not an empty list
    mod2 = SimpleNamespace(DISPLAY="Angel One", IMPLEMENTED=True)
    monkeypatch.setattr(registry, "get", lambda slug: mod2)
    with pytest.raises(BrokerNotSupported, match="Angel One has no trade-book reader"):
        run(hub.read_account_trades(None, {"account_id": "a2", "broker": "angelone"}))
    monkeypatch.undo()                                   # the real registry: only Zerodha and ICICI Direct have a trade-book reader
    assert hub.supports_trades("zerodha") and hub.supports_trades("icicidirect")
    others = [b.SLUG for b in registry.all_brokers() if b.SLUG not in ("zerodha", "icicidirect")]
    assert len(others) >= 6 and not any(hub.supports_trades(s) for s in others)
    # a refused token ends the session and surfaces as expired
    monkeypatch.setattr(sessions, "end_session", end)
    monkeypatch.setattr(hub, "_live_token", lambda d: AccessToken("T"))

    async def refuse(token):
        raise BrokerSessionExpired("rejected")
    monkeypatch.setattr(registry, "get", lambda slug: SimpleNamespace(DISPLAY="Fake", IMPLEMENTED=True, fetch_trades=staticmethod(refuse)))
    with pytest.raises(BrokerSessionExpired):
        run(hub.read_account_trades(None, {"account_id": "a3", "broker": "zerodha"}))
    assert ended == [("a3", "broker_rejected")]
    # no live session: no broker call at all
    monkeypatch.undo()
    calls.clear()
    with pytest.raises(sessions.SessionEnded):
        run(hub.read_account_trades(None, doc(live=False)))
    assert calls == []


# ── BT-4: the kept day ───────────────────────────────────────────────────────
@pytest.fixture
def kept(monkeypatch):
    db = FakeDB()
    state = SimpleNamespace(reads=0, trades=[fill("RELIANCE", "buy", 10, 100.0)])

    async def read(db_, d):
        state.reads += 1
        return [dict(t) for t in state.trades]
    monkeypatch.setattr(hub, "read_account_trades", read)
    return db, state


def test_bt4_a_day_is_kept_change_only_cached_and_tenant_scoped(kept):
    db, st = kept
    d = {**doc("a1"), "user_id": "u1"}
    t0 = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)
    assert run(tb.capture(db, d, now=t0))["state"] == tb.CAPTURED
    assert run(tb.capture(db, d, now=t0 + timedelta(seconds=30)))["state"] == tb.CACHED and st.reads == 1          # inside the 60 s cache
    res = run(tb.capture(db, d, now=t0 + timedelta(seconds=120)))
    assert res["changed"] is False and st.reads == 2 and len(db["broker_trade_days"].docs) == 1                       # identical: last_seen only
    st.trades.append(fill("RELIANCE", "sell", 10, 110.0, at="2026-10-30T06:00:00+00:00"))
    res = run(tb.capture(db, d, now=t0 + timedelta(seconds=240)))
    kept_doc = db["broker_trade_days"].docs[0]
    assert res["changed"] is True and kept_doc["version"] == 2 and kept_doc["count"] == 2 and len(db["broker_trade_days"].docs) == 1
    assert kept_doc["user_id"] == "u1" and kept_doc["account_id"] == "a1" and kept_doc["day"] == "2026-10-30"
    # a quiet day is kept too (it says "looked, nothing traded")
    st.trades = []
    run(tb.capture(db, {**d, "account_id": "a2"}, now=t0 + timedelta(days=1)))
    assert [x["count"] for x in db["broker_trade_days"].docs] == [2, 0]
    # tenant isolation: another user never sees or overwrites the account's days
    assert run(tb.stored_days(db, "u2", "a1")) == [] and len(run(tb.stored_days(db, "u1", "a1"))) == 1
    flat = json.dumps(db["broker_trade_days"].docs)
    for banned in ("ENC", "access_token", "api_key", "session_token"):
        assert banned not in flat


def test_bt4b_the_daily_sync_keeps_the_book_and_a_failure_never_fails_the_sync(monkeypatch):
    captured, synced = [], []

    async def sync(db, d, trigger="manual"):
        synced.append(d["account_id"])

    async def capture(db, d):
        captured.append(d["account_id"])
        if d["account_id"] == "bad":
            raise RuntimeError("down")
    monkeypatch.setattr(hub, "sync_account", sync)
    monkeypatch.setattr(tb, "capture", capture)

    async def expire(db, **k):
        return 0
    monkeypatch.setattr(sessions, "expire_due_sessions", expire)

    class Coll:
        def find(self, q, p=None):
            return SimpleNamespace(to_list=lambda length=None: _co([doc("ok"), doc("bad")]))

    async def _co(v):
        return v
    out = run(hub.daily_sync(SimpleNamespace(broker_accounts=Coll())))
    assert captured == ["ok", "bad"] and out["synced"] == 2 and out["failed"] == 0


# ── BT-5: matching ───────────────────────────────────────────────────────────
def test_bt5_a_long_round_trip_and_partial_fills_are_one_trip():
    ds = [day("2026-10-30", [fill("RELIANCE", "buy", 4, 100.0, "2026-10-30T04:00:00+00:00"), fill("RELIANCE", "buy", 6, 102.0, "2026-10-30T04:01:00+00:00"),
                             fill("RELIANCE", "sell", 10, 110.0, "2026-10-30T09:00:00+00:00")], broker="zerodha", display="Zerodha")]
    m = tb.match(ds)
    assert len(m["trips"]) == 1 and m["open"] == []
    t = m["trips"][0]
    assert (t["direction"], t["quantity"], t["fills"], t["entry_day"], t["exit_day"]) == ("long", 10.0, 2, "2026-10-30", "2026-10-30")
    assert t["entry_price"] == 101.2 and t["exit_price"] == 110.0 and t["pnl_rs"] == round(4 * 10.0 + 6 * 8.0, 2)
    assert t["label"] == "RELIANCE" and t["broker_display"] == "Zerodha" and t["fees_rs"] is None


def test_bt5b_a_short_round_trip_gains_when_the_price_falls():
    ds = [day("2026-10-30", [fill("INFY", "sell", 5, 200.0, "2026-10-30T04:00:00+00:00"), fill("INFY", "buy", 5, 190.0, "2026-10-30T08:00:00+00:00")])]
    t = tb.match(ds)["trips"][0]
    assert t["direction"] == "short" and t["pnl_rs"] == 50.0


def test_bt5c_an_f_and_o_lot_is_matched_in_units_with_partial_fills():
    nfo = dict(exchange="NFO", instrument_type="FUT", expiry="2026-11-24")
    ds = [day("2026-10-30", [fill("SONBLW", "buy", 1225, 890.0, "2026-10-30T04:00:00+00:00", **nfo),
                             fill("SONBLW", "sell", 600, 900.0, "2026-10-30T07:00:00+00:00", **nfo),
                             fill("SONBLW", "sell", 625, 905.0, "2026-10-30T07:30:00+00:00", **nfo)])]
    m = tb.match(ds)
    assert len(m["trips"]) == 1 and m["open"] == []
    t = m["trips"][0]
    assert t["underlying"] == "SONACOMS" and t["label"] == "SONACOMS 24 Nov 2026 FUT" and t["kind"] == "future"          # ICICI's own code, named as NSE
    assert t["quantity"] == 1225.0 and t["fills"] == 2 and t["pnl_rs"] == round(600 * 10.0 + 625 * 15.0, 2)
    # one lot of a stock option: units, not lots
    o = [day("2026-10-30", [fill("SWILIM", "buy", 1825, 4.0, "2026-10-30T04:00:00+00:00", exchange="NFO", instrument_type="PE", expiry="2026-11-23", strike=170.0),
                            fill("SWILIM", "sell", 1825, 5.0, "2026-10-30T06:00:00+00:00", exchange="NFO", instrument_type="PE", expiry="2026-11-23", strike=170.0)])]
    t2 = tb.match(o)["trips"][0]
    assert t2["pnl_rs"] == 1825.0 and t2["label"] == "SWIGGY 23 Nov 2026 170 PE" and t2["kind"] == "option" and t2["instrument"] == "PE"


def test_bt5d_a_sell_with_no_buy_on_record_is_an_unmatched_leg_never_a_short():
    m = tb.match([day("2026-10-30", [fill("TCS", "sell", 3, 3500.0)])])
    assert m["trips"] == [] and len(m["open"]) == 1
    o = m["open"][0]
    assert (o["side"], o["quantity"], o["avg_price"]) == ("sell", 3.0, 3500.0) and "Not treated as a short" in o["note"]


def test_bt5e_lots_carry_across_the_days_kept_and_open_lots_stop_at_the_asked_day():
    ds = [day("2026-10-28", [fill("TCS", "buy", 10, 3400.0, "2026-10-28T05:00:00+00:00")]),
          day("2026-10-29", [fill("TCS", "sell", 4, 3450.0, "2026-10-29T05:00:00+00:00")]),
          day("2026-10-30", [fill("TCS", "sell", 6, 3300.0, "2026-10-30T05:00:00+00:00")])]
    m = tb.match(ds)
    assert [(t["exit_day"], t["quantity"], t["pnl_rs"], t["entry_day"]) for t in m["trips"]] == [("2026-10-29", 4.0, 200.0, "2026-10-28"), ("2026-10-30", 6.0, -600.0, "2026-10-28")]
    assert m["open"] == []
    assert tb.match(ds, through_day="2026-10-28")["open"][0]["quantity"] == 10.0
    assert [t["exit_day"] for t in tb.match(ds, through_day="2026-10-29")["trips"]] == ["2026-10-29"]


def test_bt5f_fees_only_when_the_broker_sent_every_one_and_accounts_do_not_mix():
    a = day("2026-10-30", [fill("TCS", "buy", 2, 100.0, fees_rs=1.0), fill("TCS", "sell", 2, 101.0, "2026-10-30T09:00:00+00:00", fees_rs=1.5)])
    assert tb.match([a])["trips"][0]["fees_rs"] == 2.5
    b = day("2026-10-30", [fill("TCS", "buy", 2, 100.0), fill("TCS", "sell", 2, 101.0, "2026-10-30T09:00:00+00:00", fees_rs=1.5)])
    assert tb.match([b])["trips"][0]["fees_rs"] is None
    x = day("2026-10-30", [fill("TCS", "buy", 2, 100.0)], account="a1")
    y = day("2026-10-30", [fill("TCS", "sell", 2, 101.0, "2026-10-30T09:00:00+00:00")], account="a2")
    m = tb.match([x, y])
    assert m["trips"] == [] and len(m["open"]) == 2                              # a buy in one account is not closed by a sell in another


# ── BT-6: the accounts' states ───────────────────────────────────────────────
def test_bt6_review_data_reports_each_accounts_state_with_its_reason(monkeypatch):
    import deps
    from routes import broker_connect as bc
    db = FakeDB()
    monkeypatch.setattr(deps, "db", db)
    accts = [doc("a1"), doc("a2", "zerodha", live=False), {**doc("a3", "angelone"), "native": True}, {**doc("a4", "dhan"), "native": False}]

    async def hub_user(request):
        return {"user_id": "u1"}

    async def accounts(uid):
        return [dict(a) for a in accts]
    monkeypatch.setattr(bc, "_hub_user", hub_user)
    monkeypatch.setattr(bc, "_user_accounts", accounts)
    names = {"icicidirect": "ICICI Direct", "zerodha": "Zerodha", "angelone": "Angel One", "dhan": "Dhan"}
    monkeypatch.setattr(bc, "_account_entry", lambda d: {"account_id": d["account_id"], "broker": d["broker"], "broker_display": names[d["broker"]], "label": None})

    async def capture(db_, d, **k):
        return {"state": tb.CAPTURED}
    monkeypatch.setattr(tb, "capture", capture)
    monkeypatch.setattr(hub, "supports_trades", lambda s: s in ("icicidirect", "zerodha"))
    db["broker_trade_days"].docs.append({"_id": "bt_a2_2026-10-29", "user_id": "u1", "account_id": "a2", "broker": "zerodha", "day": "2026-10-29",
                                         "trades": [fill("TCS", "buy", 1, 1.0)], "last_seen_at": "2026-10-29T10:00:00+00:00"})
    out = run(tb.review_data("REQ", db, "u1"))
    st = {a["account_id"]: a for a in out["accounts"]}
    assert st["a1"]["state"] == tb.CAPTURED and st["a2"]["state"] == tb.ENDED and st["a2"]["days"] == 1 and st["a2"]["last_day"] == "2026-10-29"
    assert st["a3"]["state"] == tb.UNSUPPORTED and "Angel One has no trade-book reader" in st["a3"]["error"]["message"]
    assert st["a4"]["state"] == tb.UNREADABLE
    assert [d["account_id"] for d in out["stored"]] == ["a2"] and out["stored"][0]["broker_display"] == "Zerodha"

    from fastapi import HTTPException

    async def off(request):
        raise HTTPException(status_code=403, detail="off")
    monkeypatch.setattr(bc, "_hub_user", off)
    assert run(tb.review_data("REQ", db, "u1")) == {"hub": "off", "accounts": [], "stored": []}


# ── BT-7: did you follow your rules ──────────────────────────────────────────
def trip(direction="long", entry=100.0, exit_=95.0, kind="cash", instrument="EQ", exit_at="2026-10-30T09:00:00+00:00", entry_at="2026-10-30T04:00:00+00:00"):
    pnl = (exit_ - entry) * 10 if direction == "long" else (entry - exit_) * 10
    return {"account_id": "a1", "broker_display": "Zerodha", "key": [], "underlying": "TCS", "label": "TCS", "kind": kind, "instrument": instrument, "direction": direction,
            "quantity": 10.0, "entry_price": entry, "exit_price": exit_, "entry_at": entry_at, "exit_at": exit_at, "entry_day": "2026-10-30", "exit_day": "2026-10-30",
            "pnl_rs": round(pnl, 2), "fees_rs": None, "fills": 2}


def lv(stop=None, target=None, at="2026-10-29T10:00:00+00:00"):
    return {"stop": stop, "target": target, "updated_at": at}


def pl(direction="bullish", entry=100.0, stop=96.0, target=110.0, at="2026-10-29T10:00:00+00:00"):
    return {"plan_id": "tp_1", "created_at": at, "direction": direction, "entry": entry, "stop": stop, "target": target}


def test_bt7_adherence_is_assessed_only_where_a_stop_or_plan_was_in_force():
    a = broker_review.adherence(trip(), None, None)
    assert a["cell"] == "No plan recorded" and not a["assessed"] and a["facts"] == []                               # never guessed
    b = broker_review.adherence(trip(exit_=94.0), lv(stop=96.0), None)
    assert b["cell"] == "Stop not honoured" and any("beyond your stop" in f["text"] and f["tone"] == "warn" for f in b["facts"])
    c = broker_review.adherence(trip(exit_=98.0), lv(stop=96.0), None)
    assert c["cell"] == "Exited before the stop"
    d = broker_review.adherence(trip(exit_=112.0), lv(stop=96.0, target=110.0), None)
    assert d["cell"] == "Target reached"
    e = broker_review.adherence(trip(direction="short", entry=100.0, exit_=104.0), lv(stop=102.0), None)           # a short's stop is above
    assert e["cell"] == "Stop not honoured"


def test_bt7b_a_stop_set_after_the_trade_closed_and_a_plan_recorded_after_it_opened_are_not_used():
    a = broker_review.adherence(trip(), lv(stop=96.0, at="2026-10-31T10:00:00+00:00"), None)
    assert not a["assessed"] and a["cell"] == "No plan recorded" and any("after this trade closed" in f["text"] for f in a["facts"])
    b = broker_review.adherence(trip(), None, pl(at="2026-10-30T08:00:00+00:00"))
    assert not b["assessed"] and any("after this trade opened" in f["text"] for f in b["facts"])


def test_bt7c_a_plan_gives_the_entry_offset_a_conflict_and_options_are_compared_by_direction_only():
    a = broker_review.adherence(trip(entry=102.0, exit_=108.0), None, pl())
    assert any("2.00% above the plan's entry" in f["text"] for f in a["facts"]) and a["assessed"] and a["cell"] in ("Within your stop", "Plan recorded")
    b = broker_review.adherence(trip(), None, pl(direction="bearish"))
    assert b["cell"] in ("Against the plan", "Stop not honoured") and any("against a bearish plan" in f["text"] for f in b["facts"])
    c = broker_review.adherence(trip(kind="option", instrument="PE", exit_=90.0), lv(stop=96.0), pl(direction="bearish"))
    assert not any("beyond" in f["text"] for f in c["facts"])                              # a premium is not compared with a level on the underlying
    assert any("same way as the bearish plan" in f["text"] for f in c["facts"])             # a long put is a bearish view


# ── BT-8: the review ─────────────────────────────────────────────────────────
@pytest.fixture
def src(monkeypatch):
    return Src(monkeypatch)


def review(src, mode="day"):
    p = asyncio.run(builders.build(Intent("daily_review", params={"period": mode}), {"user_id": "u1"}, request="REQ"))
    assert validate(p) == [], validate(p)
    return p


def bdata(days, accounts=None):
    return {"hub": "on", "accounts": accounts if accounts is not None else [{"account_id": "a1", "broker": "icicidirect", "broker_display": "ICICI Direct", "state": tb.CAPTURED,
            "error": None, "days": len(days), "last_day": days[-1]["day"] if days else None}], "stored": days}


def test_bt8_the_paper_review_is_unchanged_when_no_broker_has_trades(src):
    base = review(src)
    src.v["broker_trades"] = bdata([], accounts=[])
    again = review(src)
    assert [b.get("id") for b in again["blocks"]] == [b.get("id") for b in base["blocks"]] and again["headline"] == base["headline"]
    assert not [b for b in again["blocks"] if str(b.get("id", "")).startswith("broker")]


def test_bt8b_broker_round_trips_are_a_labelled_section_beside_the_paper_review(src):
    paper = review(src)
    src.v["broker_trades"] = bdata([day("2026-10-30", [fill("TCS", "buy", 10, 100.0, "2026-10-30T04:00:00+00:00"), fill("TCS", "sell", 10, 95.0, "2026-10-30T09:00:00+00:00"),
                                                       fill("INFY", "sell", 3, 1500.0, "2026-10-30T09:30:00+00:00")])])
    src.v["broker_refs"] = {"levels": {"TCS": {"stop": 97.0, "target": None, "updated_at": "2026-10-29T10:00:00+00:00"}}, "plans": {}}
    p = review(src)
    ids = [b.get("id") for b in p["blocks"]]
    for want in ("broker_record", "broker_trips", "broker_rules", "broker_open"):
        assert want in ids
    # every paper block is still there, in the same order, untouched
    assert [i for i in ids if not str(i).startswith("broker")] == [b.get("id") for b in paper["blocks"]]
    assert blocks_of(p, "ranked")[0]["id"] == paper_first_ranked(paper)
    rec = next(b for b in p["blocks"] if b.get("id") == "broker_record")
    assert "Broker trades" in rec["title"] and "Labelled Broker" in rec["note"]
    k = {i["label"]: i["value"] for i in rec["items"]}
    assert k["Round trips closed"] == "1" and k["Wins / losses"] == "0 / 1" and k["Realised P&L"] == "−₹50.00" and k["Unmatched legs"] == "1"
    trips = next(b for b in p["blocks"] if b.get("id") == "broker_trips")
    row = trips["rows"][0]
    assert row["badge"] == "Broker" and row["cells"]["plan"] == "Stop not honoured" and row["cells"]["pnl"] == -50.0
    assert "gross" in trips["columns"][6]["label"]
    rules = next(b for b in p["blocks"] if b.get("id") == "broker_rules")
    assert any("1 of 1 round trip" in i["text"] for i in rules["items"])
    assert p["headline"]["text"].startswith(paper["headline"]["text"]) and "Broker: 1 round trip closed (0 wins, 1 loss), realised −₹50.00 gross" in p["headline"]["text"]
    assert any(s["name"] == broker_review.SRC_TRADES and s["status"] == "fresh" for s in p["data_quality"]["sources"])
    assert "Broker round trips" in facts(p)


def paper_first_ranked(p):
    return blocks_of(p, "ranked")[0]["id"]


def test_bt8c_a_trip_with_no_stop_or_plan_says_no_plan_recorded(src):
    src.v["broker_trades"] = bdata([day("2026-10-30", [fill("TCS", "buy", 10, 100.0, "2026-10-30T04:00:00+00:00"), fill("TCS", "sell", 10, 105.0, "2026-10-30T09:00:00+00:00")])])
    p = review(src)
    row = next(b for b in p["blocks"] if b.get("id") == "broker_trips")["rows"][0]
    assert row["cells"]["plan"] == "No plan recorded"
    rules = next(b for b in p["blocks"] if b.get("id") == "broker_rules")
    assert "0 of 1 round trip" in rules["items"][-1]["text"] and "not assessed" in rules["items"][-1]["text"]


def test_bt8d_accounts_that_cannot_supply_trades_say_why(src):
    accts = [{"account_id": "a1", "broker": "angelone", "broker_display": "Angel One", "state": tb.UNSUPPORTED, "days": 0, "last_day": None,
              "error": {"code": "BROKER_READ_NOT_SUPPORTED", "message": "Angel One has no trade-book reader yet, so its trades are not in this review."}},
             {"account_id": "a2", "broker": "zerodha", "broker_display": "Zerodha", "state": tb.ENDED, "days": 2, "last_day": "2026-10-29",
              "error": {"code": "BROKER_SESSION_EXPIRED", "message": "Your Zerodha session has ended."}}]
    src.v["broker_trades"] = bdata([day("2026-10-29", [fill("TCS", "buy", 1, 1.0)], account="a2", broker="zerodha", display="Zerodha")], accounts=accts)
    p = review(src)
    ns = {n["id"]: n for n in p["blocks"] if n["type"] == "notice" and str(n["id"]).startswith("broker-")}
    assert "Angel One has no trade-book reader yet" in ns["broker-angelone-0-unsupported"]["text"]
    z = ns["broker-zerodha-1-ended"]
    assert z["actions"] == [{"kind": "connect_broker", "label": "Sign in to Zerodha again"}] and "2 days of its trade book kept so far (latest 29 Oct 2026)" in z["text"]


def test_bt8e_the_week_reads_the_kept_days_and_a_failed_read_is_a_missing_source(src):
    days = [day("2026-10-27", [fill("TCS", "buy", 10, 100.0, "2026-10-27T04:00:00+00:00")]),
            day("2026-10-29", [fill("TCS", "sell", 10, 110.0, "2026-10-29T04:00:00+00:00")])]
    src.v["broker_trades"] = bdata(days)
    p = review(src, "week")
    rec = next(b for b in p["blocks"] if b.get("id") == "broker_record")
    assert {i["label"]: i["value"] for i in rec["items"]}["Realised P&L"] == "+₹100.00"
    src.fail.add("broker_trades")
    q = review(src, "week")
    assert any("Your broker trade book" in m and "MOCK broker_trades down" in m for m in q["data_quality"]["missing"]) and not [b for b in q["blocks"] if str(b.get("id", "")).startswith("broker_")]


def test_bt9_this_code_can_only_read():
    for mod in (tb, broker_review, zerodha.fetch_trades, icicidirect.fetch_trades):
        text = inspect.getsource(mod)
        for call in ("place_order", "modify_order", "cancel_order", "place_gtt", "basket_order(", ".orders("):
            assert call not in text, (getattr(mod, "__name__", mod), call)
