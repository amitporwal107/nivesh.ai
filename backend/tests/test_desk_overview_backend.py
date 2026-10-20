"""Smart trading desk · Overview — the backend rules behind the regime card, the market status and the sector heatmap.

    five regimes            services/macro_engine.py :: classify_desk_regime (PRD OV-003, the user's rule of 2026-10-14)
    /api/macro/today        routes/macro.py :: macro_today → `regime` (the session's breadth read once per session)
    session status          routes/markets.py :: session_state, _nse_holiday, markets_home (PRD §12.5, B1/B2)
    sector constituents     routes/markets_desk.py :: GET /api/markets/sector-constituents → DaaS /v1/desk/sector-constituents

No network, no Postgres, no Mongo. MOCK — not real data: every figure here is a hand-made input whose expected
answer is worked out in the test from the rule (the staging data check runs separately, read-only).
"""
from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Tuple

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from routes import macro as macro_route
from routes import markets
from routes import markets_desk as desk_route
from services import macro_engine
from services.copilot_tools import daas_client

RULE = macro_engine.DESK_REGIME_RULE
IST = timezone(timedelta(hours=5, minutes=30))


def _breadth(adv: int, dec: int, unch: int = 0, day: str = "2026-10-13") -> dict:
    return {"date": day, "advances": adv, "declines": dec, "unchanged": unch, "universe": adv + dec + unch,
            "source": "stock_ohlcv end-of-day bars (NSE bhavcopy)"}


def _regime(nifty=25100.0, avg=25000.0, vix=13.0, breadth=None, session="2026-10-13"):
    return macro_engine.classify_desk_regime(session=session, nifty_close=nifty, nifty_average=avg,
                                             india_vix=vix, breadth=breadth)


# ── the rule: thresholds live in one config ───────────────────────────────

def test_the_rule_config_holds_every_threshold():
    assert RULE == {"version": "desk-regime-v1", "vix_high": 20.0, "trend_average_sessions": 50,
                    "breadth_up_pct": 52.0, "breadth_down_pct": 48.0}
    assert macro_engine.DESK_REGIMES == ("high_volatility", "mixed", "bullish", "sideways", "bearish")
    # the answer carries the rule it used, so the card can show it
    assert _regime()["rule"] == RULE


# ── high volatility: India VIX ≥ 20 wins over everything ─────────────────

def test_vix_exactly_20_is_high_volatility():
    r = _regime(vix=20.0, breadth=_breadth(600, 400))
    assert (r["key"], r["label"]) == ("high_volatility", "High volatility")
    assert r["inputs"]["volatility_high"] is True


def test_vix_just_under_20_is_not_high_volatility():
    r = _regime(vix=19.99, breadth=_breadth(600, 400))           # 60% advancing: breadth up, trend up
    assert r["key"] == "bullish" and r["inputs"]["volatility_high"] is False


def test_high_volatility_overrides_a_disagreement_and_a_down_trend():
    assert _regime(nifty=24000.0, vix=27.5, breadth=_breadth(700, 300))["key"] == "high_volatility"


# ── mixed: trend and breadth disagree ────────────────────────────────────

def test_up_trend_with_breadth_down_is_mixed():
    r = _regime(breadth=_breadth(470, 530))                      # 470 / 1000 = 47.0% ≤ 48 → down
    assert r["key"] == "mixed"
    assert (r["inputs"]["trend"], r["inputs"]["breadth"], r["inputs"]["advancing_share_pct"]) == ("up", "down", 47.0)


def test_down_trend_with_breadth_up_is_mixed():
    assert _regime(nifty=24800.0, breadth=_breadth(530, 470))["key"] == "mixed"   # 53% ≥ 52 → up


def test_breadth_boundaries_are_inclusive():
    # exactly 48.0% advancing is "down"; exactly 52.0% is "up"
    assert _regime(breadth=_breadth(480, 520))["inputs"]["breadth"] == "down"
    assert _regime(breadth=_breadth(480, 520))["key"] == "mixed"
    assert _regime(nifty=24800.0, breadth=_breadth(520, 480))["inputs"]["breadth"] == "up"
    assert _regime(nifty=24800.0, breadth=_breadth(520, 480))["key"] == "mixed"


def test_even_breadth_cannot_disagree():
    r = _regime(nifty=24800.0, breadth=_breadth(500, 500))      # 50% → even
    assert r["inputs"]["breadth"] == "even" and r["key"] == "bearish"


def test_unchanged_stocks_do_not_count_toward_the_share():
    r = _regime(breadth=_breadth(470, 530, unch=900))
    assert r["inputs"]["advancing_share_pct"] == 47.0 and r["inputs"]["unchanged"] == 900


# ── otherwise the existing 50-session rule ───────────────────────────────

def test_trend_rule_gives_bullish_sideways_bearish():
    assert _regime(nifty=25100.0, breadth=_breadth(600, 400))["key"] == "bullish"
    assert _regime(nifty=24900.0, breadth=_breadth(400, 600))["key"] == "bearish"
    r = _regime(nifty=25000.0, breadth=_breadth(600, 400))
    assert r["key"] == "sideways" and r["inputs"]["trend"] == "flat"     # flat trend has no direction to disagree with
    assert r["inputs"]["nifty_vs_average_pct"] == 0.0


def test_no_trend_means_no_regime_never_a_default():
    for nifty, avg in ((None, 25000.0), (25100.0, None)):
        r = _regime(nifty=nifty, avg=avg, breadth=_breadth(600, 400))
        assert r["key"] is None and r["label"] is None and r["invalidation"] == []
        assert "no Nifty 50 close or 50-session average" in r["reason"]


# ── missing inputs skip their check and say so ───────────────────────────

def test_missing_vix_skips_the_volatility_check():
    r = _regime(vix=None, breadth=_breadth(600, 400))
    assert r["key"] == "bullish" and r["inputs"]["volatility_high"] is None
    assert {"check": "high_volatility", "reason": "no India VIX close on record for the session"} in r["skipped"]


def test_breadth_from_another_session_is_not_used():
    r = _regime(breadth=_breadth(100, 900, day="2026-10-12"))   # would be "down" → mixed, but it is a different day
    assert r["key"] == "bullish" and r["inputs"]["breadth"] is None and r["inputs"]["advances"] is None
    assert r["inputs"]["breadth_date"] == "2026-10-12"
    assert r["skipped"] == [{"check": "mixed", "reason": "breadth is for 2026-10-12, not the regime's session"}]


def test_no_breadth_skips_the_mixed_check():
    assert _regime(breadth=None)["skipped"] == [{"check": "mixed", "reason": "no advances and declines on record for the session"}]


# ── invalidation: each single change that moves the reading ──────────────

def test_invalidation_of_a_bullish_reading():
    r = _regime(nifty=25100.0, avg=25000.0, vix=13.0, breadth=_breadth(600, 400))
    assert r["invalidation"] == [
        # a close below the average with breadth still up is a disagreement
        {"input": "nifty_close", "condition": "below", "level": 25000.0, "then": "mixed"},
        {"input": "india_vix", "condition": "at_or_above", "level": 20.0, "then": "high_volatility"},
        {"input": "advancing_share_pct", "condition": "at_or_below", "level": 48.0, "then": "mixed"},
    ]


def test_invalidation_of_high_volatility_names_the_vix_only():
    r = _regime(vix=24.0, breadth=_breadth(600, 400))
    assert r["invalidation"] == [{"input": "india_vix", "condition": "below", "level": 20.0, "then": "bullish"}]


def test_invalidation_of_mixed():
    r = _regime(breadth=_breadth(400, 600))                       # up trend, breadth down
    assert r["invalidation"] == [
        {"input": "nifty_close", "condition": "below", "level": 25000.0, "then": "bearish"},
        {"input": "india_vix", "condition": "at_or_above", "level": 20.0, "then": "high_volatility"},
        {"input": "advancing_share_pct", "condition": "at_or_above", "level": 52.0, "then": "bullish"},
    ]


def test_invalidation_of_sideways_names_both_crossings():
    r = _regime(nifty=25000.0, breadth=_breadth(500, 500))
    assert [(i["input"], i["condition"], i["then"]) for i in r["invalidation"]] == [
        ("nifty_close", "below", "bearish"), ("nifty_close", "above", "bullish"), ("india_vix", "at_or_above", "high_volatility")]


# ── GET /api/macro/today carries the regime, and never fails because of it ──

SNAP = {"date": "2026-10-13", "market": "BULL", "risk": "LOW", "insight": "Fixture insight.",
        "values": {"nifty": 25100.0, "india_vix": 12.4}, "features": {"nifty_50dma": 25000.0}}


def _macro_client(monkeypatch, snap=SNAP, breadth=None, breadth_error: Optional[Exception] = None):
    calls: List[Any] = []

    async def latest_state():
        return copy.deepcopy(snap)

    async def session_breadth(day):
        calls.append(day)
        if breadth_error:
            raise breadth_error
        return breadth

    async def fake_user(request: Request):
        return {"user_id": "u1"}

    monkeypatch.setattr(macro_engine, "latest_state", latest_state)
    monkeypatch.setattr(macro_engine, "session_breadth", session_breadth)
    monkeypatch.setattr(macro_route, "get_current_user", fake_user)
    macro_route._BREADTH_CACHE.clear()
    app = FastAPI()
    app.include_router(macro_route.router)
    return TestClient(app), calls


def test_macro_today_adds_the_regime_for_the_same_session(monkeypatch):
    c, calls = _macro_client(monkeypatch, breadth=_breadth(470, 530))
    d = c.get("/api/macro/today").json()
    assert d["market"] == "BULL" and d["regime"]["key"] == "mixed" and d["regime"]["date"] == "2026-10-13"
    assert d["regime"]["inputs"]["nifty_average"] == 25000.0 and d["regime"]["inputs"]["india_vix"] == 12.4
    # one breadth read per session, kept for ten minutes
    c.get("/api/macro/today")
    assert [str(x) for x in calls] == ["2026-10-13"]


def test_macro_today_breadth_failure_skips_mixed_and_says_why(monkeypatch):
    c, _ = _macro_client(monkeypatch, breadth_error=RuntimeError("pool gone"))
    r = c.get("/api/macro/today")
    assert r.status_code == 200
    reg = r.json()["regime"]
    assert reg["key"] == "bullish"
    assert reg["skipped"] == [{"check": "mixed", "reason": "breadth could not be read (RuntimeError: pool gone)"}]


def test_macro_today_with_no_state_has_no_regime_block(monkeypatch):
    c, _ = _macro_client(monkeypatch, snap=None)

    async def none():
        return None
    monkeypatch.setattr(macro_engine, "latest_state", none)
    d = c.get("/api/macro/today").json()
    assert d["_uninitialised"] is True and "regime" not in d


# ── the NSE session: holidays, weekends, hours (PRD §12.5) ───────────────

def _at(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=IST)


def test_an_nse_holiday_on_a_weekday_in_hours_is_closed():
    # 2026-10-20 is a Tuesday and NSE's Dussehra holiday (nidp.nse_holidays, segment CM)
    s = markets.session_state(_at(2026, 10, 20, 11, 0), calendar_read=True, holiday="Dussehra")
    assert (s["state"], s["trading_day"], s["reason"], s["holiday"]) == ("closed", False, "holiday", "Dussehra")
    assert s["calendar"] == "ok" and s["date"] == "2026-10-20"


def test_a_weekend_is_closed_whatever_the_calendar_says():
    s = markets.session_state(_at(2026, 10, 17, 11, 0), calendar_read=False, holiday=None)   # Saturday
    assert (s["state"], s["trading_day"], s["reason"], s["holiday"]) == ("closed", False, "weekend", None)


def test_a_normal_session_is_open_inside_0915_1530_ist():
    assert markets.session_state(_at(2026, 10, 14, 11, 32), calendar_read=True, holiday=None)["state"] == "open"
    assert markets.session_state(_at(2026, 10, 14, 9, 15), calendar_read=True, holiday=None)["state"] == "open"
    assert markets.session_state(_at(2026, 10, 14, 15, 30), calendar_read=True, holiday=None)["state"] == "open"
    before = markets.session_state(_at(2026, 10, 14, 9, 14), calendar_read=True, holiday=None)
    after = markets.session_state(_at(2026, 10, 14, 15, 31), calendar_read=True, holiday=None)
    assert (before["state"], before["reason"], before["trading_day"]) == ("closed", "before_open", True)
    assert (after["state"], after["reason"]) == ("closed", "after_close")


def test_the_session_is_read_in_ist_whatever_the_clock_zone():
    # 05:45 UTC is 11:15 IST on a Wednesday
    s = markets.session_state(datetime(2026, 10, 14, 5, 45, tzinfo=timezone.utc), calendar_read=True, holiday=None)
    assert s["state"] == "open" and s["reason"] == "in_hours"


def test_an_unread_calendar_follows_the_clock_and_says_so():
    s = markets.session_state(_at(2026, 10, 14, 11, 0), calendar_read=False, holiday=None)
    assert (s["state"], s["trading_day"], s["calendar"]) == ("open", None, "unavailable")
    assert s["calendar_source"] == "NSE trading holidays (nidp.nse_holidays, segment CM)"


def _holiday_reader(monkeypatch, reply, configured=True) -> List[Tuple[str, Optional[dict]]]:
    calls: List[Tuple[str, Optional[dict]]] = []

    async def get_raw(path, params=None, timeout=10.0):
        calls.append((path, params))
        if isinstance(reply, Exception):
            raise reply
        return copy.deepcopy(reply)
    monkeypatch.setattr(daas_client, "get_raw", get_raw)
    monkeypatch.setattr(daas_client, "is_configured", lambda: configured)
    markets._HOLIDAY_CACHE.clear()
    return calls


def test_holiday_lookup_reads_the_cm_list_for_that_day(monkeypatch):
    from datetime import date
    body = {"data": [{"holiday_date": "2026-10-20", "segment": "CM", "description": "Dussehra"}], "count": 1}
    calls = _holiday_reader(monkeypatch, (200, body))
    assert asyncio.run(markets._nse_holiday(date(2026, 10, 20))) == (True, "Dussehra")
    assert calls == [("/holidays", {"segment": "CM", "from": "2026-10-20", "to": "2026-10-20"})]
    # cached for the day
    asyncio.run(markets._nse_holiday(date(2026, 10, 20)))
    assert len(calls) == 1


def test_holiday_lookup_no_row_is_a_trading_day_and_failures_are_unread(monkeypatch):
    from datetime import date
    _holiday_reader(monkeypatch, (200, {"data": [], "count": 0}))
    assert asyncio.run(markets._nse_holiday(date(2026, 10, 14))) == (True, None)
    _holiday_reader(monkeypatch, daas_client.DaasError("down"))
    assert asyncio.run(markets._nse_holiday(date(2026, 10, 14))) == (False, None)
    _holiday_reader(monkeypatch, (500, {"error": "x"}))
    assert asyncio.run(markets._nse_holiday(date(2026, 10, 14))) == (False, None)
    calls = _holiday_reader(monkeypatch, (200, {"data": []}), configured=False)
    assert asyncio.run(markets._nse_holiday(date(2026, 10, 14))) == (False, None) and calls == []


def test_markets_home_is_not_live_on_a_holiday_even_when_the_feed_says_so(monkeypatch):
    from services.positional_engine import market_dashboard as md, nse_live

    async def build():
        return {"as_of_date": "2026-10-19", "is_live": True, "breadth": {}}

    async def live_snapshot():
        return {"is_live": True, "fetched_at": "2026-10-20T05:30:00+00:00"}

    async def nothing():
        return {}

    async def tape():
        return []

    async def movers():
        return {"as_of": None, "gainers": [], "losers": []}

    async def none():
        return None

    async def no_news():
        return []

    holiday = markets.session_state(_at(2026, 10, 20, 11, 0), calendar_read=True, holiday="Dussehra")

    async def session_now():
        return holiday

    async def fake_user(request: Request):
        return {"user_id": "u1"}

    monkeypatch.setattr(md, "build", build)
    monkeypatch.setattr(nse_live, "get_live_snapshot", live_snapshot)
    monkeypatch.setattr(nse_live, "get_global_snapshot", nothing)
    monkeypatch.setattr(nse_live, "get_index_tape", tape)
    monkeypatch.setattr(markets, "_top_movers", movers)
    monkeypatch.setattr(markets, "_fii_dii", none)
    monkeypatch.setattr(markets, "_news", no_news)
    monkeypatch.setattr(markets, "_session_now", session_now)
    monkeypatch.setattr(markets, "get_current_user", fake_user)
    markets._CACHE.update({"ts": 0.0, "data": None})
    app = FastAPI()
    app.include_router(markets.router)
    d = TestClient(app).get("/api/markets/home").json()
    markets._CACHE.update({"ts": 0.0, "data": None})
    assert d["market_state"] == "closed" and d["is_live"] is False
    assert d["session"]["holiday"] == "Dussehra" and d["session"]["reason"] == "holiday"


# ── GET /api/markets/sector-constituents ─────────────────────────────────

CONSTITUENTS = {
    "index": "Nifty Bank", "sector": "Banks", "available": True, "reason": None, "list_date": "2026-10-13",
    "date": "2026-10-14", "source": "NSE index lists (nidp.index_constituents) with NSE bhavcopy closes (nidp.prices_eod)",
    "rule": "advance = …", "breadth": {"members": 2, "advances": 1, "declines": 1, "unchanged": 0, "no_price": 0},
    "count": 2,
    "rows": [{"symbol": "PNB", "company_name": "Punjab National Bank", "industry": "Financial Services", "weight_pct": None,
              "close": 118.5, "prev_close": 116.55, "change_pct": 1.67, "move": "advance"},
             {"symbol": "SBIN", "company_name": "State Bank of India", "industry": "Financial Services", "weight_pct": None,
              "close": 954.9, "prev_close": 957.0, "change_pct": -0.22, "move": "decline"}],
}


def _desk_client(monkeypatch, reply):
    calls: List[Tuple[str, Optional[dict]]] = []

    async def get_raw(path, params=None, timeout=10.0):
        calls.append((path, params))
        if isinstance(reply, Exception):
            raise reply
        return copy.deepcopy(reply)

    async def fake_user(request: Request):
        return {"user_id": "u1"}
    monkeypatch.setattr(daas_client, "get_raw", get_raw)
    monkeypatch.setattr(daas_client, "is_configured", lambda: True)
    monkeypatch.setattr(desk_route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(desk_route.router)
    return TestClient(app), calls


def test_sector_constituents_forwards_the_index_and_passes_the_answer_through(monkeypatch):
    c, calls = _desk_client(monkeypatch, (200, CONSTITUENTS))
    r = c.get("/api/markets/sector-constituents", params={"index": "Nifty Bank"})
    assert r.status_code == 200 and r.json() == CONSTITUENTS
    assert calls == [("/desk/sector-constituents", {"index": "Nifty Bank"})]


def test_sector_constituents_without_a_list_is_passed_through_as_not_available(monkeypatch):
    body = {**CONSTITUENTS, "index": "Nifty Auto", "available": False, "reason": "no constituent list for Nifty Auto in nidp.index_constituents",
            "breadth": None, "count": 0, "rows": []}
    c, _ = _desk_client(monkeypatch, (200, body))
    assert c.get("/api/markets/sector-constituents?index=Nifty%20Auto").json()["available"] is False


@pytest.mark.parametrize("qs", ["", "index=", "index=ab", "index=Nifty%3Bdrop", "index=" + "A" * 61])
def test_sector_constituents_validates_the_index(monkeypatch, qs):
    c, calls = _desk_client(monkeypatch, (200, CONSTITUENTS))
    assert c.get(f"/api/markets/sector-constituents?{qs}").status_code == 422 and calls == []


def test_sector_constituents_upstream_failure_is_502(monkeypatch):
    c, _ = _desk_client(monkeypatch, daas_client.DaasError("down"))
    r = c.get("/api/markets/sector-constituents?index=Nifty%20Bank")
    assert r.status_code == 502 and r.json()["detail"] == "upstream_unavailable"


# ── the Nifty 50 closes fall back to the warehouse when macro_daily is short of sessions ──

def _eod(closes, last="2026-10-13"):
    """MOCK — not real data: `closes` oldest first, one per weekday ending on `last`, in the DaaS /eod row shape."""
    from datetime import date as _d
    day, rows = _d.fromisoformat(last), []
    for c in reversed(closes):
        while day.weekday() >= 5:
            day -= timedelta(days=1)
        rows.append({"as_of_date": day.isoformat(), "close_price": c})
        day -= timedelta(days=1)
    return list(reversed(rows))


SHORT_SNAP = {"date": "2026-10-13", "market": "NEUTRAL", "risk": "LOW", "insight": "Fixture insight.",
              "values": {"nifty": 25100.0, "india_vix": 12.4}, "features": {"nifty_50dma": None}}


def _fallback_client(monkeypatch, rows, calls=None):
    async def history(name, start=None, end=None, **k):
        if calls is not None:
            calls.append((name, start, end))
        if isinstance(rows, Exception):
            raise rows
        return rows

    monkeypatch.setattr(daas_client, "get_index_eod_history", history)
    macro_route._NIFTY_CACHE.clear()
    return _macro_client(monkeypatch, snap=SHORT_SNAP, breadth=_breadth(600, 400))[0]


def test_regime_reads_the_nifty_closes_from_the_warehouse_when_macro_has_no_average(monkeypatch):
    closes = [24000.0 + 10 * i for i in range(50)]                  # 24000 .. 24490 -> average 24245.0 (by hand: 24000 + 10 x 24.5)
    calls = []
    c = _fallback_client(monkeypatch, _eod(closes), calls)
    r = c.get("/api/macro/today").json()["regime"]
    avg = sum(closes) / 50
    assert avg == 24245.0
    assert r["inputs"]["nifty_close"] == closes[-1] and r["inputs"]["nifty_average"] == avg
    assert r["inputs"]["nifty_source"] == macro_route.NIFTY_WAREHOUSE_SOURCE
    assert r["inputs"]["trend"] == "up" and r["key"] == "bullish" and r["reason"] is None
    assert r["rule"] == RULE                                         # the thresholds are untouched
    assert calls == [("Nifty 50", "2026-06-15", "2026-10-13")]


def test_regime_warehouse_average_needs_thirty_sessions(monkeypatch):
    c = _fallback_client(monkeypatch, _eod([24000.0] * 29))
    r = c.get("/api/macro/today").json()["regime"]
    assert r["key"] is None and r["inputs"]["nifty_source"] is None
    assert any(s["check"] == "trend" and "only 29 of the 50 sessions" in s["reason"] for s in r["skipped"])
    c = _fallback_client(monkeypatch, _eod([24000.0] * 30))
    r = c.get("/api/macro/today").json()["regime"]
    assert r["key"] is not None and r["inputs"]["nifty_average"] == 24000.0


def test_regime_warehouse_without_the_session_close_or_unreachable_stays_unavailable(monkeypatch):
    r = _fallback_client(monkeypatch, _eod([24000.0] * 50, last="2026-10-12")).get("/api/macro/today").json()["regime"]
    assert r["key"] is None and any("has no close for 2026-10-13" in s["reason"] for s in r["skipped"])
    r = _fallback_client(monkeypatch, RuntimeError("down")).get("/api/macro/today").json()["regime"]
    assert r["key"] is None and any("could not be read" in s["reason"] for s in r["skipped"])


def test_regime_keeps_the_macro_tables_when_they_hold_the_average(monkeypatch):
    calls = []
    c = _fallback_client(monkeypatch, _eod([1.0] * 50), calls)
    c2, _ = _macro_client(monkeypatch, breadth=_breadth(470, 530))
    r = c2.get("/api/macro/today").json()["regime"]
    assert r["inputs"]["nifty_source"] == macro_route.NIFTY_MACRO_SOURCE and r["inputs"]["nifty_average"] == 25000.0 and calls == []
