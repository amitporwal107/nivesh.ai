"""No stale F&O data is shown: today's or the previous session's only (owner rule, 2026-10-28).

Cases TC-1 .. TC-10 of test_reports/no_stale_fno_data_20261028.md. The staging facts behind them (2026-10-28): the data
platform answered EXIDEIND's chain as of 2026-07-28 with 200; SONACOMS's default chain was the 2026-10-27 expiry that had
expired; the 2026-10-27 bhavcopy carried the previous close forward on 14,428 untraded stock-option rows; Kite quoted
`last_price` for contracts whose last trade was days ago or never (1970-01-01).
"""
from __future__ import annotations

import asyncio
import copy
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from routes import fno as route
from services import market_freshness as mf
from services.kite_live_feed import fno_quotes as fq
from tests import market_day
from tests.test_fno_iv_history import _doc, _route_client, _weekdays
from tests.test_fno_routes import CHAIN, _client, _contract, _envelope, _future

IST = timezone(timedelta(hours=5, minutes=30))
TODAY, T1 = "2026-10-28", "2026-10-27"           # a Wednesday and the Tuesday before it


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _holidays(*days: str, readable: bool = True):
    seen = []

    async def read(d: date):
        seen.append(d.isoformat())
        return readable, ("NSE holiday" if readable and d.isoformat() in days else None)
    return read, seen


# ── TC-1 the window ──────────────────────────────────────────────────────────

def test_the_floor_is_the_previous_trading_session():
    read, seen = _holidays()
    w = run(mf.window(datetime(2026, 10, 28, 10, 0, tzinfo=IST), read))
    assert (w.today.isoformat(), w.floor.isoformat(), w.calendar_checked) == (TODAY, T1, True)
    # Monday: the weekend is skipped without asking the calendar
    read, seen = _holidays()
    w = run(mf.window(datetime(2026, 11, 2, 9, 0, tzinfo=IST), read))
    assert w.floor.isoformat() == "2026-10-30" and seen == ["2026-10-30"]


def test_a_holiday_on_the_previous_weekday_is_skipped():
    read, _ = _holidays(T1)
    assert run(mf.window(datetime(2026, 10, 28, 10, 0, tzinfo=IST), read)).floor.isoformat() == "2026-10-26"


def test_an_unreadable_calendar_counts_weekdays_which_is_only_ever_stricter():
    read, _ = _holidays(readable=False)
    w = run(mf.window(datetime(2026, 10, 28, 10, 0, tzinfo=IST), read))
    assert (w.floor.isoformat(), w.calendar_checked) == (T1, False)


def test_today_is_the_ist_day_not_the_utc_one():
    read, _ = _holidays()
    w = run(mf.window(datetime(2026, 10, 27, 20, 0, tzinfo=timezone.utc), read))   # 01:30 IST on the 28th
    assert w.today.isoformat() == TODAY


def test_current_and_live_expiry():
    w = mf.Window(today=date(2026, 10, 28), floor=date(2026, 10, 27), calendar_checked=True)
    assert w.current(T1) and w.current(TODAY) and w.current("2026-10-27T15:30:00")
    assert not w.current("2026-10-22") and not w.current(None) and not w.current("junk")
    assert not w.live_expiry(T1) and w.live_expiry(TODAY) and w.live_expiry("2026-11-23")
    assert "2026-07-28" in w.stale_reason("EXIDEIND F&O", "2026-07-28") and T1 in w.stale_reason("x", "2026-07-28")


# ── TC-2 / TC-3 / TC-6 an underlying that left the F&O list ──────────────────

def _stale_symbol(path: str, params: Optional[dict]):
    if path.endswith("/chain"):
        return 200, {**CHAIN, "symbol": "EXIDEIND", "as_of": "2026-07-28", "expiry": "2026-07-28"}
    if path.endswith("/expiries"):
        return 200, {"symbol": "EXIDEIND", "data": [
            {"expiry_date": "2026-07-28", "ce_count": 40, "pe_count": 40, "futures_count": 1, "latest_seen": "2026-07-28"}]}
    return 200, _envelope([_future("STF", "2026-07-28", 380.0, 380.0, 100, 1, 10, as_of="2026-07-28")], as_of="2026-07-28")


def test_a_symbol_whose_latest_day_is_older_than_the_previous_session_is_404_everywhere(monkeypatch):
    c, _ = _client(monkeypatch, _stale_symbol)
    market_day.pin(monkeypatch, TODAY, T1)
    for path in ("/api/fno/EXIDEIND/chain", "/api/fno/EXIDEIND/expiries", "/api/fno/EXIDEIND/futures"):
        r = c.get(path)
        assert r.status_code == 404, path
        detail = r.json()["detail"]
        assert "2026-07-28" in detail and T1 in detail and "not shown" in detail
        assert "strikes" not in r.json() and "futures" not in r.json()


# ── TC-3 / TC-4 / TC-5 expired contracts ─────────────────────────────────────

def _current_symbol(path: str, params: Optional[dict]):
    if path.endswith("/chain"):
        expiry = (params or {}).get("expiry") or T1        # the data platform's default: the nearest on or after its day
        return 200, {**copy.deepcopy(CHAIN), "as_of": T1, "expiry": expiry}
    if path.endswith("/expiries"):
        return 200, {"symbol": "TESTCO", "data": [
            {"expiry_date": T1, "ce_count": 30, "pe_count": 30, "futures_count": 1, "latest_seen": T1},
            {"expiry_date": "2026-11-23", "ce_count": 30, "pe_count": 30, "futures_count": 1, "latest_seen": T1},
            {"expiry_date": "2026-12-29", "ce_count": 30, "pe_count": 30, "futures_count": 1, "latest_seen": T1}]}
    return 200, _envelope([_future("STF", T1, 109.0, 109.0, 50, -400, 900, as_of=T1),
                           _future("STF", "2026-11-23", 110.0, 110.0, 5000, 300, 1200, as_of=T1)], as_of=T1)


def test_expiries_drop_the_series_that_expired_at_the_previous_close(monkeypatch):
    c, _ = _client(monkeypatch, _current_symbol)
    market_day.pin(monkeypatch, TODAY, T1)
    body = c.get("/api/fno/TESTCO/expiries").json()
    assert body["as_of"] == T1 and [e["expiry"] for e in body["expiries"]] == ["2026-11-23", "2026-12-29"]


def test_the_default_chain_moves_past_an_expired_series_to_the_nearest_live_one(monkeypatch):
    c, calls = _client(monkeypatch, _current_symbol)
    market_day.pin(monkeypatch, TODAY, T1)
    r = c.get("/api/fno/TESTCO/chain")
    assert r.status_code == 200 and r.json()["summary"]["expiry"] == "2026-11-23"
    assert [p for p, q in calls if p.endswith("/chain")] == ["/fno/TESTCO/chain", "/fno/TESTCO/chain"]
    assert ("/fno/TESTCO/chain", {"expiry": "2026-11-23"}) in calls


def test_an_expired_expiry_asked_for_is_404_and_the_chain_is_not_read(monkeypatch):
    c, calls = _client(monkeypatch, _current_symbol)
    market_day.pin(monkeypatch, TODAY, T1)
    r = c.get(f"/api/fno/TESTCO/chain?expiry={T1}")
    assert r.status_code == 404 and "expired" in r.json()["detail"]
    assert not [p for p, _ in calls if p.endswith("/chain")]


def test_futures_drop_the_contract_that_expired_at_the_previous_close(monkeypatch):
    c, _ = _client(monkeypatch, lambda p, q: _current_symbol(p, q) if q.get("instrument_type") == "STF" else (200, _envelope([], as_of=T1)))
    market_day.pin(monkeypatch, TODAY, T1)
    body = c.get("/api/fno/TESTCO/futures").json()
    assert body["as_of"] == T1 and [f["expiry"] for f in body["futures"]] == ["2026-11-23"] and body["count"] == 1


# ── TC-7 a contract that did not trade has no close ──────────────────────────

def test_an_untraded_contract_sends_no_close_but_keeps_settle_and_open_interest():
    held = {**_contract(120.0, "CE", 105.7, 2450, 0, 0), "prev_close_price": 105.7}
    side = route.shape_side(held)
    assert side == {"close": None, "settle": 105.75, "oi": 2450, "change_in_oi": 0, "volume": 0}
    assert route.day_change(held, side) == {"change": None, "change_pct": None, "oi_buildup": None}
    traded = route.shape_side(_contract(120.0, "CE", 0.3, 50, 5, 12))
    assert traded["close"] == 0.3


# ── TC-8 the build-up scans ──────────────────────────────────────────────────

def test_a_stale_default_scan_is_404_but_a_scan_asked_for_by_date_answers(monkeypatch):
    scan = {"as_of": "2026-10-22", "universe": 0, "rows": []}
    c, _ = _client(monkeypatch, (200, scan))
    market_day.pin(monkeypatch, TODAY, T1)
    for path in ("/api/fno/scan/buildup", "/api/fno/scan/candidates"):
        r = c.get(path)
        assert r.status_code == 404 and "2026-10-22" in r.json()["detail"], path
    r = c.get("/api/fno/scan/buildup?date=2026-10-22")
    assert r.status_code == 200 and r.json()["as_of"] == "2026-10-22"
    fresh, _ = _client(monkeypatch, (200, {**scan, "as_of": T1}))
    market_day.pin(monkeypatch, TODAY, T1)
    assert fresh.get("/api/fno/scan/buildup").status_code == 200


# ── TC-9 IV history ──────────────────────────────────────────────────────────

def test_a_stale_latest_iv_session_is_not_sent_as_current_but_the_dated_series_stays(monkeypatch):
    days = _weekdays(4)                                     # 2025-06-02 .. 2025-06-05
    c, _ = _route_client(monkeypatch, [_doc(d, 18.0 + i) for i, d in enumerate(days)])
    market_day.pin(monkeypatch, "2025-06-10", "2025-06-09")
    body = c.get("/api/fno/TESTCO/iv-history").json()
    assert body["current"] is None and body["iv_rank"] is None and body["iv_percentile"] is None
    assert "2025-06-05" in body["reason"] and "not shown" in body["reason"]
    assert [p["date"] for p in body["series"]] == days


# ── TC-10 Kite quotes of contracts that have not traded ──────────────────────

def test_a_kite_quote_counts_only_when_the_contract_traded_today_or_in_the_previous_session():
    keys = {0: "NFO:TODAY", 1: "NFO:T1", 2: "NFO:OLD", 3: "NFO:NEVER", 4: "NFO:UNKNOWN"}
    answer = {"NFO:TODAY": {"last_price": 17.1, "last_trade_time": datetime(2026, 10, 28, 13, 42, 44)},
              "NFO:T1": {"last_price": 4.35, "last_trade_time": "2026-10-27 15:29:58"},
              "NFO:OLD": {"last_price": 43.0, "last_trade_time": "2026-10-21 10:01:00"},
              "NFO:NEVER": {"last_price": 105.7, "last_trade_time": "1970-01-01 05:30:00"},
              "NFO:UNKNOWN": {"last_price": 9.25}}
    priced = fq.prices_from(answer, keys, floor=date(2026, 10, 27))
    assert sorted(priced) == [0, 1]
    assert len(fq.prices_from(answer, keys)) == 5            # without a floor the reader is unchanged
