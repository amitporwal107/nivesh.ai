"""Trade Desk › Chart Analysis › Live chart: the futures OI build-up by window (per expiry and consolidated), the chart's
EMA 20 / RVOL / signal conditions / markers, and the two read-only routes (test_reports/desk_live_chart_TESTCASES.md).

No network, no Mongo, no Postgres, no Kite: every bar, row and signal below is MOCK — not real data. The Kite candle shape
(date, open, high, low, close, volume, oi) is Kite's historical_data with oi=1; behaviour against the real Kite and the real
bhavcopy is checked separately on staging (test_reports/desk_live_chart_<date>.md).
"""
from __future__ import annotations

import asyncio
import copy
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from routes import desk_live_chart as lc_route
from routes import fno as fno_route
from services import desk_live_chart as lc
from services import fno_oi_windows as ow
from services.kite_live_feed import intraday as it

IST = timezone(timedelta(hours=5, minutes=30))


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def t(day: int, h: int, m: int) -> str:
    return datetime(2026, 10, day, h, m, tzinfo=IST).isoformat()


def bar(day, h, m, c, v=100, oi=None, o=None):
    o = c if o is None else o
    return [t(day, h, m), o, max(o, c) + 1, min(o, c) - 1, c, v, oi]


# ── TC-1 the classifier is the desk board's ──────────────────────────────────

@pytest.mark.parametrize("p,o", [(1, 5), (-1, 5), (1, -5), (-1, -5), (0, 5), (1, 0), (0, 0), (None, 5), (1, None)])
def test_buildup_label_equals_the_board_rule(p, o):
    from nidp.services.daas_api.routers.desk_market import buildup_label
    assert ow.buildup_label(p, o) == buildup_label(p, o)


# ── TC-2 / TC-3 windows by time, baseline trimmed ────────────────────────────

def _session(day, closes, ois, vol=100):
    out, m = [], 9 * 60 + 15
    for c, oi in zip(closes, ois):
        out.append(bar(day, m // 60, m % 60, c, vol, oi))
        m += 15
    return out


def test_windows_are_blocks_of_four_slots_from_the_open():
    bars = _session(27, [100, 101, 102, 103, 104, 103, 102, 101, 102], [1000, 1010, 1020, 1030, 1040, 1035, 1030, 1020, 1025])
    w = ow.series_windows([bars], 15, 4)
    assert [(x["start"][11:16], x["end"][11:16], x["bars"]) for x in w] == [("09:15", "10:15", 4), ("10:15", "11:15", 4), ("11:15", "12:15", 1)]
    # the first window has no baseline; the second: close 101 vs 103, OI 1020 vs 1030 -> long unwinding
    assert w[0]["price_change"] is None and w[0]["label"] is None
    assert (w[1]["price_change"], w[1]["oi_change"], w[1]["label"], w[1]["volume"]) == (-2.0, -10, "long_unwinding", 400)
    assert (w[2]["price_change"], w[2]["oi_change"], w[2]["label"]) == (1.0, 5, "long_buildup")


def test_the_last_window_ends_at_the_close_and_is_incomplete_until_then():
    bars = _session(27, [100] * 25, [10] * 25)
    w = ow.series_windows([bars], 15, 4)
    assert w[-1]["start"][11:16] == "15:15" and w[-1]["end"][11:16] == "15:30"
    now = datetime(2026, 10, 27, 11, 20, tzinfo=IST)
    done = ow.mark_complete(ow.series_windows([bars[:9]], 15, 4), 15, 4, now)
    assert [x["complete"] for x in done] == [True, True, False]


def test_the_baseline_session_is_dropped_so_every_shown_window_has_a_previous_one():
    bars = _session(26, [100, 101], [1000, 1010]) + _session(27, [99, 98, 97, 96], [1020, 1030, 1040, 1050])
    w = ow.trim(ow.series_windows([bars], 15, 4), 1)
    assert [x["day"] for x in w] == ["2026-10-27"]
    assert (w[0]["price_change"], w[0]["oi_change"], w[0]["label"]) == (-5.0, 40, "short_buildup")


# ── TC-4 / TC-5 consolidated ─────────────────────────────────────────────────

def test_consolidated_is_the_near_price_with_oi_and_volume_summed_over_the_three():
    near = _session(27, [100, 101, 102, 103, 104, 105, 106, 107], [1000, 1010, 1020, 1030, 1000, 990, 980, 970], vol=50)
    nxt = _session(27, [101, 102, 103, 104, 105, 106, 107, 108], [500, 510, 520, 530, 560, 570, 580, 590], vol=10)
    far = _session(27, [102] * 8, [100, 100, 100, 100, 120, 120, 120, 120], vol=1)
    per = [ow.series_windows([b], 15, 4) for b in (near, nxt, far)]
    cons = ow.series_windows([near, nxt, far], 15, 4)
    assert cons[1]["oi_change"] == sum(p[1]["oi_change"] for p in per) == -60 + 60 + 20
    assert cons[1]["volume"] == sum(p[1]["volume"] for p in per) == 4 * (50 + 10 + 1)
    assert cons[1]["price_change"] == per[0][1]["price_change"] == 4.0
    assert cons[1]["label"] == "long_buildup" and per[0][1]["label"] == "short_covering"


def test_a_month_that_did_not_trade_keeps_its_oi_and_adds_no_volume():
    near = _session(27, [100, 101, 102, 103, 104, 105, 106, 107], [1000] * 4 + [1100] * 4)
    far = _session(27, [102, 102], [300, 300])                       # traded only in the first window
    cons = ow.series_windows([near, far], 15, 4)
    assert cons[1]["oi"] == 1100 + 300 and cons[1]["oi_change"] == 100 and cons[1]["volume"] == 400


def test_consolidated_oi_is_null_until_every_month_has_an_oi():
    near = _session(27, [100, 101, 102, 103, 104], [1000, 1000, 1000, 1000, 1010])
    far = [b[:6] + [None] for b in _session(27, [102] * 5, [0] * 5)]
    cons = ow.series_windows([near, far], 15, 4)
    assert all(w["oi"] is None and w["label"] is None for w in cons)


# ── the Kite futures reader ──────────────────────────────────────────────────

class FutKite:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def instruments(self, ex):
        self.calls.append(("instruments", ex))
        return [
            {"instrument_type": "FUT", "name": "HDFCBANK", "expiry": date(2026, 12, 29), "instrument_token": 3, "tradingsymbol": "HDFCBANK26DECFUT", "lot_size": 550},
            {"instrument_type": "FUT", "name": "HDFCBANK", "expiry": date(2026, 10, 27), "instrument_token": 1, "tradingsymbol": "HDFCBANK26OCTFUT", "lot_size": 550},
            {"instrument_type": "FUT", "name": "HDFCBANK", "expiry": date(2026, 11, 24), "instrument_token": 2, "tradingsymbol": "HDFCBANK26NOVFUT", "lot_size": 550},
            {"instrument_type": "FUT", "name": "HDFCBANK", "expiry": date(2026, 9, 29), "instrument_token": 9, "tradingsymbol": "OLD", "lot_size": 550},
            {"instrument_type": "CE", "name": "HDFCBANK", "expiry": date(2026, 10, 27), "instrument_token": 7, "tradingsymbol": "X", "lot_size": 550},
        ]

    def historical_data_oi(self, token, f, to, interval):
        self.calls.append(("hist_oi", token, interval))
        if self.fail:
            raise self.fail
        return [{"date": datetime(2026, 10, 27, 9, 15, tzinfo=IST), "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 10, "oi": 1000 + token},
                {"date": datetime(2026, 10, 27, 9, 30, tzinfo=IST), "open": 100, "high": 101, "low": 99, "close": 100.7, "volume": 10, "oi": -5}]


def _svc(kite, token="tok"):
    clock = lambda: datetime(2026, 10, 27, 11, 0, tzinfo=IST)  # noqa: E731

    async def nosleep(s):
        return None
    return it.IntradayService(token_getter=lambda: token, key_getter=lambda: "key", kite_factory=lambda k, tk: kite, clock=clock, sleep=nosleep)


def test_futures_bars_reads_the_three_nearest_listed_futures_with_oi():
    k = FutKite()
    r = run(_svc(k).futures_bars("hdfcbank", "15m", 2))
    assert r["availability"] == "ok"
    assert [c["expiry"] for c in r["contracts"]] == ["2026-10-27", "2026-11-24", "2026-12-29"]
    assert [c for c in k.calls if c[0] == "hist_oi"] == [("hist_oi", 1, "15minute"), ("hist_oi", 2, "15minute"), ("hist_oi", 3, "15minute")]
    assert r["contracts"][0]["bars"][0][6] == 1001 and r["contracts"][0]["bars"][1][6] is None   # a negative OI is not a figure


def test_futures_bars_without_a_token_reads_nothing():
    k = FutKite()
    r = run(_svc(k, token="").futures_bars("HDFCBANK", "15m", 2))
    assert r["availability"] == "token_missing" and r["contracts"] == [] and k.calls == []


# ── TC-6 / TC-7 / TC-8 the oi-buildup route ──────────────────────────────────

def _fno_client(monkeypatch, service, daas_reply=None):
    async def fake_user(request: Request):
        return {"user_id": "u1", "email": "u1@example.com"}

    async def no_refresh():
        return None

    class Feed:
        async def read_status(self):
            return {"session": "open"}

    async def get_raw(path, params=None, timeout=10.0):
        return copy.deepcopy(daas_reply(path, params)) if daas_reply else (404, {})

    import routes.research_chart_intraday as rci
    import services.kite_live_feed.feed as feed_mod
    monkeypatch.setattr(fno_route, "get_current_user", fake_user)
    monkeypatch.setattr(fno_route, "_refresh_platform_token", no_refresh)
    monkeypatch.setattr(rci, "get_service", lambda: service)
    monkeypatch.setattr(feed_mod, "get_feed", lambda: Feed())
    monkeypatch.setattr(fno_route.daas_client, "get_raw", get_raw)
    monkeypatch.setattr(fno_route.daas_client, "is_configured", lambda: True)
    app = FastAPI()
    app.include_router(fno_route.router)
    return TestClient(app)


class FakeFutService:
    def __init__(self, answer):
        self.answer = answer
        self.asked = []

    async def futures_bars(self, sym, interval, sessions, session_open=False):
        self.asked.append((sym, interval, sessions))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_route_intraday_mode_answers_three_months_and_consolidated(monkeypatch):
    near = _session(24, [100, 101], [1000, 1010]) + _session(27, [102, 103, 104, 105, 104], [1020, 1030, 1040, 1050, 1045])
    nxt = _session(24, [101, 102], [500, 505]) + _session(27, [103, 104, 105, 106, 105], [510, 515, 520, 525, 520])
    far = _session(24, [102], [50]) + _session(27, [104], [60])
    svc = FakeFutService({"availability": "ok", "as_of": "2026-10-27T05:45:00+00:00", "source": "Kite intraday, futures with open interest",
                          "contracts": [{"expiry": "2026-10-27", "tradingsymbol": "A", "lot_size": 550, "bars": near},
                                        {"expiry": "2026-11-24", "tradingsymbol": "B", "lot_size": 550, "bars": nxt},
                                        {"expiry": "2026-12-29", "tradingsymbol": "C", "lot_size": 550, "bars": far}]})
    c = _fno_client(monkeypatch, svc)
    r = c.get("/api/fno/hdfcbank/futures/oi-buildup?interval=15m&window=4&sessions=1")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["mode"] == "intraday" and b["read_only"] is True and b["kite_reason"] is None and b["snapshot_at"]
    assert svc.asked == [("HDFCBANK", "15m", 2)]                                    # one extra session: the baseline
    assert [x["slot"] for x in b["contracts"]] == ["current", "next", "far"]
    first = [x["windows"][0] for x in b["contracts"]]
    cons = b["consolidated"]["windows"][0]
    assert cons["oi_change"] == sum(w["oi_change"] for w in first) == (1050 - 1010) + (525 - 505) + (60 - 50)
    assert cons["price_change"] == first[0]["price_change"] == 4.0 and cons["label"] == "long_buildup"
    assert {w["day"] for x in b["contracts"] for w in x["windows"]} == {"2026-10-27"}


def _eod_reply(path, params):
    if params and params.get("instrument_type") == "STF":
        rows = [
            {"as_of_date": "2026-10-27", "expiry_date": e, "option_type": "FUT", "close_price": cl, "settle_price": cl, "prev_close_price": pc,
             "open_interest": oi, "change_in_oi": d, "traded_volume": v, "underlying_price": 1660.0}
            for e, cl, pc, oi, d, v in [("2026-10-27", 1668.0, 1650.0, 9000, -500, 300), ("2026-11-24", 1675.0, 1660.0, 4000, 800, 120),
                                         ("2026-12-29", 1680.0, 1670.0, 500, 50, 4)]]
        return 200, {"data": rows, "as_of": "2026-10-27"}
    return 200, {"data": [], "as_of": "2026-10-27"}


@pytest.mark.parametrize("answer,reason", [({"availability": "token_missing", "contracts": []}, "token_missing"),
                                           ({"availability": "token_expired", "contracts": []}, "token_expired"),
                                           (RuntimeError("upstream_unavailable"), "upstream_unavailable")])
def test_route_without_a_kite_session_falls_back_to_the_bhavcopy_day(monkeypatch, answer, reason):
    c = _fno_client(monkeypatch, FakeFutService(answer), _eod_reply)
    r = c.get("/api/fno/HDFCBANK/futures/oi-buildup")
    assert r.status_code == 200, r.text
    b = r.json()
    assert (b["mode"], b["interval"], b["kite_reason"], b["snapshot_at"]) == ("end_of_day", "1d", reason, "2026-10-27")
    assert "end of day" in b["source"]
    labels = [x["windows"][0]["label"] for x in b["contracts"]]
    assert labels == ["short_covering", "long_buildup", "long_buildup"]
    cons = b["consolidated"]["windows"][0]
    assert (cons["oi"], cons["oi_change"], cons["volume"], cons["price_change"]) == (13500, 350, 424, 18.0)
    assert cons["label"] == "long_buildup"


def test_route_refuses_an_unknown_interval_and_is_get_only(monkeypatch):
    c = _fno_client(monkeypatch, FakeFutService({"availability": "token_missing"}), _eod_reply)
    assert c.get("/api/fno/HDFCBANK/futures/oi-buildup?interval=1m").status_code == 400
    assert c.post("/api/fno/HDFCBANK/futures/oi-buildup").status_code == 405
    methods = {m for r in lc_route.router.routes for m in r.methods}
    assert methods == {"GET"}


# ── TC-9 EMA 20 and RVOL ─────────────────────────────────────────────────────

def test_ema_is_the_indicator_engines_formula():
    from nidp.services.technical_indicator_engine.calculator import _ema_series
    closes = [100 + (i % 7) * 1.5 - i * 0.1 for i in range(40)]
    mine = lc.ema_series(closes)
    ref = _ema_series(np.array(closes, dtype=float), 20)
    assert mine[:19] == [None] * 19
    assert all(abs(a - round(b, 2)) < 1e-9 for a, b in zip(mine[19:], ref[19:]))


def test_rvol_is_volume_over_the_previous_twenty_bars():
    vols = [100] * 20 + [160, 50]
    r = lc.rvol_series(vols)
    assert r[:20] == [None] * 20 and r[20] == 1.6 and r[21] == round(50 / ((100 * 19 + 160) / 20), 2)


# ── TC-11 / TC-12 conditions ─────────────────────────────────────────────────

def _intraday_bars():
    """25 bars on 26 Oct then 10 on 27 Oct: a volume bar, then a pullback on lighter volume. MOCK."""
    out, m = [], 9 * 60 + 15
    for i in range(25):
        out.append([t(26, m // 60, m % 60), 1600 + i, 1602 + i, 1599 + i, 1601 + i, 1000])
        m += 15
    m = 9 * 60 + 15
    seq = [(1660, 1700), (1655, 1200), (1650, 900), (1648, 700), (1646, 600), (1652, 650), (1658, 700), (1661, 800), (1664, 800), (1668, 900)]
    for c, v in seq:
        out.append([t(27, m // 60, m % 60), c - 2, c + 3, c - 4, c, v])
        m += 15
    return out


def test_conditions_on_the_last_completed_bar_with_values():
    bars = _intraday_bars()
    ema, rvol = lc.ema_series([b[4] for b in bars]), lc.rvol_series([b[5] for b in bars])
    now = datetime(2026, 10, 27, 11, 40, tzinfo=IST)                      # the 11:15 bar is complete, 11:30 in progress
    levels = {"entry": 1665.0, "stop": 1593.0, "rule": "break_above", "valid_for_sessions": 3}
    r = lc.conditions(bars, ema, rvol, levels, minutes=15, now=now, tf="15m", signal_day=date(2026, 10, 26), holidays=set(), holidays_checked=True)
    by = {c["key"]: c for c in r["conditions"]}
    assert r["evaluated_at_bar"] == t(27, 11, 15)                         # never the bar still in progress
    assert by["ema20"]["status"] == "met" and by["ema20"]["value"].startswith("1,664.0 >")
    assert by["volume"]["status"] == "met" and by["volume"]["value"] == "1.7×" and by["volume"]["at"] == t(27, 9, 15)
    assert by["pullback"]["status"] == "met"
    assert by["trigger"]["status"] == "waiting" and by["trigger"]["label"] == "15m close above 1,665.0"
    assert by["validity"]["status"] == "met" and by["validity"]["value"] == "2 of 3 sessions left"
    assert by["invalidation"]["status"] == "not_hit" and by["invalidation"]["label"] == "Invalidation: close below 1,593.0"
    assert r["valid_until"] == "2026-10-29T15:30:00+05:30"
    # once the 11:30 bar closes at 1,668 the trigger is met
    later = lc.conditions(bars, ema, rvol, levels, minutes=15, now=now + timedelta(minutes=10), tf="15m", signal_day=date(2026, 10, 26), holidays=set(), holidays_checked=True)
    assert {c["key"]: c for c in later["conditions"]}["trigger"]["status"] == "met"


def test_pullback_trigger_and_a_hit_invalidation():
    bars = _intraday_bars()
    ema, rvol = lc.ema_series([b[4] for b in bars]), lc.rvol_series([b[5] for b in bars])
    now = datetime(2026, 10, 27, 15, 40, tzinfo=IST)
    levels = {"entry": 1645.0, "stop": 1655.0, "rule": "pullback_to", "valid_for_sessions": 1}
    r = lc.conditions(bars, ema, rvol, levels, minutes=15, now=now, tf="15m", signal_day=date(2026, 10, 26), holidays={date(2026, 10, 27)}, holidays_checked=True)
    by = {c["key"]: c for c in r["conditions"]}
    assert by["trigger"]["status"] == "met" and by["trigger"]["at"] == t(27, 10, 0)       # the 10:00 low 1,644 reaches 1,645
    assert by["invalidation"]["status"] == "hit" and by["invalidation"]["at"] == t(27, 9, 45)   # the 9:45 close 1,650 < 1,655
    assert by["validity"]["value"].startswith("1 of 1")                                  # 27 Oct given as a holiday: not counted


# ── TC-13 markers ────────────────────────────────────────────────────────────

def test_stage_markers_follow_the_scanners_stage_changes():
    bars = [[f"2026-10-{d:02d}", 1, 1, 1, 1, 1] for d in (20, 21, 22, 23, 24)]
    sigs = [{"signal_date": "2026-10-20", "stage": "ACCUMULATION"}, {"signal_date": "2026-10-21", "stage": "ACCUMULATION"},
            {"signal_date": "2026-10-22", "stage": "EARLY_BREAKOUT"}, {"signal_date": "2026-10-23", "stage": "BREAKOUT"},
            {"signal_date": "2026-10-24", "stage": "BREAKOUT"}, {"signal_date": "2026-09-01", "stage": "ACCUMULATION"}]
    m = lc.stage_markers(sigs, bars)
    assert [(x["kind"], x["at"]) for x in m] == [("WATCH", "2026-10-20"), ("READY", "2026-10-22"), ("CONFIRMED", "2026-10-23")]
    intraday = _intraday_bars()
    m2 = lc.stage_markers([{"signal_date": "2026-10-26", "stage": "BREAKOUT"}], intraday)
    assert m2[0]["at"] == t(26, 15, 15)                                    # the last bar of the signal's session


# ── TC-10 / TC-14 the live-chart route ───────────────────────────────────────

def _lc_client(monkeypatch, *, intraday=None, daily=None, signals=([], None), plan=None):
    async def user_dep():
        return {"user_id": "u1", "email": "u1@example.com"}

    async def read_intraday(sym, interval, sessions, user):
        if isinstance(intraday, Exception):
            raise intraday
        return intraday or {"availability": "token_missing", "bars": []}

    async def read_daily(sym):
        return daily or []

    async def read_signals(sym, since):
        return signals

    async def read_holidays(a, b):
        return set(), True

    async def load(db, pid, owner):
        return plan if plan and pid == plan["plan_id"] else None

    monkeypatch.setattr(lc_route, "read_intraday", read_intraday)
    monkeypatch.setattr(lc_route, "read_daily", read_daily)
    monkeypatch.setattr(lc_route, "read_signals", read_signals)
    monkeypatch.setattr(lc_route, "read_holidays", read_holidays)
    monkeypatch.setattr(lc_route.tpm, "load", load)
    monkeypatch.setattr(lc_route, "_now_ist", lambda: datetime(2026, 10, 27, 11, 50, tzinfo=IST))
    app = FastAPI()
    app.include_router(lc_route.router)
    for r in lc_route.router.routes:
        for d in r.dependant.dependencies:
            app.dependency_overrides[d.call] = user_dep
    return TestClient(app)


PLAN = {"plan_id": "tp_abc", "instrument": {"symbol": "HDFCBANK"}, "strategy": {"direction": "long"},
        "entry": {"price": 1665.0, "desk_entry_rule": "break_above", "valid_for_sessions": 3, "reference_close": 1640.0},
        "stop": {"price": 1593.0}, "targets": [{"name": "T1", "price": 1720.0, "primary": True}, {"name": "T2", "price": 1760.0}],
        "setup": {"signal_date": "2026-10-26"}}


def test_live_chart_with_kite_candles(monkeypatch):
    bars = _intraday_bars()
    sigs = [{"signal_date": "2026-10-26", "stage": "BREAKOUT", "revision": 2, "entry": 1665.0, "stop": 1593.0, "target": 1720.0,
             "engine_version": "v2.3", "computed_at": "2026-10-24T14:15:00+00:00", "live": True}]
    c = _lc_client(monkeypatch, intraday={"availability": "ok", "bars": bars, "live_merged": True}, signals=(sigs, None), plan=PLAN)
    r = c.get("/api/desk/live-chart/hdfcbank?plan_id=tp_abc&sessions=1")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["timeframe"]["interval"] == "15m" and b["timeframe"]["source"] == "Kite intraday" and b["timeframe"]["reason"] is None
    assert [x[0][:10] for x in b["bars"]] == ["2026-10-27"] * 10 and len(b["ema20"]) == len(b["rvol"]) == 10
    assert b["levels"]["source"] == "plan" and [x["name"] for x in b["levels"]["targets"]] == ["T1", "T2"]
    assert b["signal"]["kind"] == "CONFIRMED" and b["signal"]["engine_version"] == "v2.3"
    assert [m["kind"] for m in b["markers"]] == ["RVOL"]                    # the 26 Oct CONFIRMED is outside the bars shown
    assert b["read_only"] is True and b["sent_to_broker"] is False and "not a fill" in b["paper_engine"]
    assert {x["key"] for x in b["conditions"]} == {"ema20", "volume", "pullback", "trigger", "validity", "invalidation"}


def test_live_chart_without_kite_falls_back_to_daily_and_says_why(monkeypatch):
    daily = [[(date(2026, 7, 1) + timedelta(days=i)).isoformat(), 100 + i * 0.5, 101 + i * 0.5, 99 + i * 0.5, 100.4 + i * 0.5, 1000 + i] for i in range(90)]
    c = _lc_client(monkeypatch, daily=daily)
    b = c.get("/api/desk/live-chart/HDFCBANK").json()
    assert b["timeframe"]["interval"] == "1d" and b["timeframe"]["reason"] == "token_missing"
    assert b["timeframe"]["reason_text"].startswith("Kite login needed for 15m candles")
    assert len(b["bars"]) == lc_route.DAILY_SHOWN and b["levels"]["source"] is None and b["markers"] == []


def test_live_chart_plan_checks_and_signal_db_down(monkeypatch):
    c = _lc_client(monkeypatch, intraday={"availability": "ok", "bars": _intraday_bars()}, signals=([], "the signal database is not reachable"), plan=PLAN)
    assert c.get("/api/desk/live-chart/HDFCBANK?plan_id=tp_missing").status_code == 404
    assert c.get("/api/desk/live-chart/ICICIBANK?plan_id=tp_abc").status_code == 400
    b = c.get("/api/desk/live-chart/HDFCBANK?plan_id=tp_abc").json()
    assert b["markers_error"] == "the signal database is not reachable" and all(m["kind"] == "RVOL" for m in b["markers"])
    assert c.get("/api/desk/live-chart/HDFCBANK?interval=1m").status_code == 400


def test_a_list_with_two_months_is_read_again_and_the_answer_says_which_are_missing(monkeypatch):
    class TwoThenThree(FutKite):
        def __init__(self):
            super().__init__()
            self.reads = 0

        def instruments(self, ex):
            self.reads += 1
            rows = super().instruments(ex)
            return rows if self.reads > 1 else [r for r in rows if r["instrument_token"] != 3]   # the far month not listed yet

    monkeypatch.setattr(it, "NFO_REREAD_SECONDS", -1)
    k = TwoThenThree()
    s = _svc(k)
    first = run(s.futures_bars("HDFCBANK", "15m", 2))
    assert len(first["contracts"]) == 2
    ans = ow.intraday_answer("HDFCBANK", {**first, "contracts": [{**c, "bars": [b for b in c["bars"]]} for c in first["contracts"]]},
                             "15m", 15, 4, 1, datetime(2026, 10, 27, 11, 0, tzinfo=IST))
    assert ans["missing_slots"] == ["far"] and "consolidated figure sums the 2 listed" in ans["missing_note"]
    s._cache.clear()
    again = run(s.futures_bars("HDFCBANK", "15m", 2))
    assert len(again["contracts"]) == 3 and k.reads == 2
