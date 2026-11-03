"""Intraday candles from Kite on demand: shape, honesty (no fabricated bars, empty when the token is missing), merge of the
live price into the in-progress candle only, Kite's rate limit, cache, and the two routes.

No network, no Mongo, no Kite (MOCK -- not real data). The candle shape follows what kite.historical_data returned in a read-only
check on 2026-10-21 (see test_reports/OVERRIDE_kite_live_feed.md); the route's behaviour against the real Kite is UNVERIFIED in CI.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import research_chart_intraday as route
from services.kite_live_feed import config as cfg
from services.kite_live_feed import intraday as it
from tests.test_kite_live_feed import FakeDB, TokenException, make_feed, run

IST = cfg.IST
NOW = datetime(2026, 10, 21, 11, 7, 30, tzinfo=IST)


def candle(day, h, m, o=100.0, hi=101.0, lo=99.0, c=100.5, v=1000):
    return {"date": datetime(2026, 10, day, h, m, tzinfo=IST), "open": o, "high": hi, "low": lo, "close": c, "volume": v}


class HistKite:
    def __init__(self, rows=None, fail=None):
        self.rows = rows if rows is not None else []
        self.fail = fail
        self.calls = []

    def instruments(self, ex):
        self.calls.append(("instruments", ex))
        return [{"segment": "NSE", "tradingsymbol": "RELIANCE", "instrument_token": 738561, "instrument_type": "EQ"},
                {"segment": "INDICES", "tradingsymbol": "NIFTY 50", "instrument_token": 256265, "instrument_type": "EQ"}]

    def historical_data(self, token, f, t, interval):
        self.calls.append(("hist", token, interval, f, t))
        if self.fail:
            raise self.fail
        return self.rows


class Clock:
    def __init__(self):
        self.now = NOW
        self.slept = []

    def __call__(self):
        return self.now

    async def sleep(self, s):
        self.slept.append(s)


def svc(kite=None, token="tok-SECRET", key="key", clock=None):
    clock = clock or Clock()
    kite = kite or HistKite()
    s = it.IntradayService(token_getter=lambda: token, key_getter=lambda: key, kite_factory=lambda k, t: kite, clock=clock, sleep=clock.sleep)
    return s, kite, clock


def test_bars_are_labelled_sorted_valid_only_and_never_fabricated():
    rows = [candle(21, 9, 20, c=100.8), candle(21, 9, 15), candle(21, 9, 25, hi=98.0),                 # high below the open: dropped
            {"date": datetime(2026, 10, 21, 9, 30, tzinfo=IST), "open": 1, "high": 2, "low": 1}, candle(21, 9, 35, o=0)]
    s, kite, _ = svc(HistKite(rows))
    r = run(s.bars("reliance", "5m", 5))
    assert r["source"] == "Kite intraday" and r["availability"] == "ok" and r["adjusted"] is False
    assert [b[0] for b in r["bars"]] == ["2026-10-21T09:15:00+05:30", "2026-10-21T09:20:00+05:30"] and r["count"] == 2
    assert r["session_dates"] == ["2026-10-21"] and r["as_of"]
    assert kite.calls[1][1:3] == (738561, "5minute")


def test_missing_or_expired_token_gives_empty_with_a_reason_never_bars():
    s, kite, _ = svc(token="")
    r = run(s.bars("RELIANCE", "15m", 5))
    assert r["bars"] == [] and r["availability"] == "token_missing" and kite.calls == []
    s, _, _ = svc(HistKite(fail=TokenException("bad token tok-SECRET")))
    r = run(s.bars("RELIANCE", "15m", 5))
    assert r["bars"] == [] and r["availability"] == "token_expired" and "tok-SECRET" not in str(r)


def test_other_kite_failures_raise_without_the_provider_message():
    s, _, _ = svc(HistKite(fail=RuntimeError("boom tok-SECRET")))
    with pytest.raises(RuntimeError) as e:
        run(s.bars("RELIANCE", "30m", 5))
    assert "tok-SECRET" not in str(e.value)


def test_unknown_symbol_is_reported_not_guessed():
    s, _, _ = svc()
    assert run(s.bars("NOSUCH", "5m", 5))["availability"] == "symbol_not_found"


def test_sessions_keep_the_last_n_days():
    rows = [candle(d, 9, 15) for d in (14, 15, 16, 19, 21)]
    s, _, _ = svc(HistKite(rows))
    r = run(s.bars("RELIANCE", "60m", 2))
    assert r["session_dates"] == ["2026-10-19", "2026-10-21"] and r["count"] == 2


def test_live_price_is_merged_only_into_the_candle_in_progress():
    rows = [candle(21, 11, 0, o=100, hi=101, lo=99, c=100.5)]            # 11:00-11:05 ... for 5m the candle ends 11:05: not in progress at 11:07
    s, _, clock = svc(HistKite(rows))
    r = run(s.bars("RELIANCE", "5m", 5, session_open=True, live_ltp=105.0))
    assert r["live_merged"] is False and r["bars"][-1][4] == 100.5       # no candle is invented for 11:05-11:10
    clock.now = NOW
    s, _, _ = svc(HistKite([candle(21, 11, 5, o=100, hi=101, lo=99, c=100.5)]))
    r = run(s.bars("RELIANCE", "5m", 5, session_open=True, live_ltp=102.0))
    assert r["live_merged"] is True and r["in_progress_bar"] == "2026-10-21T11:05:00+05:30"
    b = r["bars"][-1]
    assert b[4] == 102.0 and b[2] == 102.0 and b[3] == 99.0 and b[1] == 100                        # close and high move; open and low stay
    s, _, _ = svc(HistKite([candle(21, 11, 5, hi=101, lo=99, c=100.5)]))
    assert run(s.bars("RELIANCE", "5m", 5, session_open=False, live_ltp=102.0))["live_merged"] is False   # market closed: no merge


def test_kite_rate_limit_spacing_and_cache():
    s, kite, clock = svc(HistKite([candle(21, 9, 15)]))
    run(s.bars("RELIANCE", "5m", 5))
    assert len([c for c in kite.calls if c[0] == "hist"]) == 1
    run(s.bars("RELIANCE", "5m", 5))                                      # cached
    assert len([c for c in kite.calls if c[0] == "hist"]) == 1
    run(s.bars("RELIANCE", "15m", 5))                                     # new key -> another call, spaced
    assert len([c for c in kite.calls if c[0] == "hist"]) == 2
    assert all(x >= 0.3 for x in clock.slept if x) or clock.slept == []   # asyncio.sleep is faked; the gate asks for >= 1/3 s
    assert it.SPACING_SECONDS >= 1 / 3


def test_window_is_capped_per_interval():
    s, kite, _ = svc(HistKite([candle(21, 9, 15)]))
    run(s.bars("RELIANCE", "5m", 30))
    f, t = kite.calls[-1][3], kite.calls[-1][4]
    assert (t - f).days <= 100


# ── routes ───────────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    db = FakeDB()
    feed = make_feed(db)
    run(feed.tick())
    feed.session = "closed"
    monkeypatch.setattr(route, "get_feed", lambda: feed)
    s, kite, _ = svc(HistKite([candle(21, 9, 15)]))
    monkeypatch.setattr(route, "get_service", lambda: s)
    feed.token_reloads = 0

    async def reload_token():
        feed.token_reloads += 1
    monkeypatch.setattr(route, "_refresh_platform_token", reload_token)
    app = FastAPI()
    app.include_router(route.router)
    for r in route.router.routes:
        for dep in r.dependant.dependencies:
            if getattr(dep.call, "__qualname__", "").startswith("require_feature"):
                app.dependency_overrides[dep.call] = lambda: {"user_id": "u1"}
    return TestClient(app), feed, kite


def test_availability_follows_the_feed_state(client):
    c, feed, _ = client
    r = c.get("/api/research/chart-intraday/availability").json()
    assert r["available"] is True and r["intervals"] == ["5m", "15m", "30m", "60m"] and r["source"] == "Kite intraday"
    feed.state = "expired"
    feed.leader = True
    r = c.get("/api/research/chart-intraday/availability").json()
    assert r["available"] is False and r["intervals"] == [] and r["reason"] == "token_expired"
    feed.state = "not_connected"
    assert c.get("/api/research/chart-intraday/availability").json()["reason"] == "token_missing"


def test_intraday_route_returns_bars_and_validates(client):
    c, feed, kite = client
    r = c.get("/api/research/chart-intraday/RELIANCE", params={"interval": "5m", "sessions": 3})
    assert r.status_code == 200 and r.json()["count"] == 1 and r.json()["source"] == "Kite intraday"
    assert c.get("/api/research/chart-intraday/RELIANCE", params={"interval": "7m"}).status_code == 400
    assert c.get("/api/research/chart-intraday/RELIANCE", params={"sessions": 99}).status_code == 422


def test_route_502_on_provider_failure_without_leaking(monkeypatch, client):
    c, *_ = client
    s, _, _ = svc(HistKite(fail=RuntimeError("tok-SECRET")))
    monkeypatch.setattr(route, "get_service", lambda: s)
    r = c.get("/api/research/chart-intraday/RELIANCE", params={"interval": "30m"})
    assert r.status_code == 502 and "tok-SECRET" not in r.text


def test_the_route_reloads_the_days_kite_login_before_reading(client):
    """A worker that is not the feed's leader kept the token it started with, so the chart said "the platform Kite session
    expired" while the day's login was valid (staging 29 Oct). The route now reloads the stored login first, as routes/fno.py does."""
    c, feed, _ = client
    assert c.get("/api/research/chart-intraday/RELIANCE", params={"interval": "15m"}).status_code == 200
    assert feed.token_reloads == 1


def test_the_reload_helper_never_raises(monkeypatch):
    from services.kite_live_feed import platform_token

    async def broken(db, now=None):
        raise RuntimeError("mongo down")
    monkeypatch.setattr(platform_token, "refresh_cache", broken)
    run(route._refresh_platform_token())
