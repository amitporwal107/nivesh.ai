"""Live chart events: GET /api/desk/chart-events/{symbol} (routes/desk_chart_events.py) and the pure event / reaction work
(services/desk_chart_events.py). Contract C, tests C1–C5 of test_reports/live_chart_comprehensive_TESTCASES.md.

No network, no Mongo, no Postgres, no Kite: `daas_client.get_raw` is replaced by a fake answering every source in the
shape the data platform sends, and the Kite day quote by a fake saved close. Every row below is MOCK — not real data.
The real sources are checked on staging separately (S3 / S4).
"""
from __future__ import annotations

import asyncio
import copy
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from routes import desk_chart_events as route
from services import desk_chart_events as ce
from services.copilot_tools import daas_client

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 10, 29, 17, 0, tzinfo=IST)            # after the close, before the exchange's EOD file
HOLIDAY = date(2026, 10, 2)                                  # MOCK NSE holiday (a Friday)
SYM = "ADANIPORTS"


# ── MOCK fixtures ────────────────────────────────────────────────────────────

def _weekdays(a: date, b: date, skip=()) -> List[date]:
    out, d = [], a
    while d <= b:
        if d.weekday() < 5 and d != HOLIDAY and d not in skip:
            out.append(d)
        d += timedelta(days=1)
    return out


# day → (open, close, volume); every other bar opens and closes at 100 with volume 1000
OVERRIDES = {
    "2026-09-14": (150.0, 150.0, 1000.0), "2026-09-15": (147.0, 148.5, 2000.0), "2026-09-16": (150.0, 151.47, 1000.0),
    "2026-10-27": (200.0, 200.0, 1000.0), "2026-10-28": (204.0, 210.0, 3000.0),
}


def price_rows(skip=()) -> List[Dict[str, Any]]:
    """DaaS /prices/adjusted rows, newest first (MOCK)."""
    rows = []
    for d in _weekdays(date(2026, 6, 1), date(2026, 10, 28), skip):
        o, c, v = OVERRIDES.get(d.isoformat(), (100.0, 100.0, 1000.0))
        rows.append({"symbol": SYM, "as_of_date": d.isoformat(), "adj_open": o, "adj_high": max(o, c) + 1, "adj_low": min(o, c) - 1,
                     "adj_close": c, "adj_volume": v})
    return list(reversed(rows))


CALENDAR = [  # DaaS /events/{symbol} (nidp.event_calendar), MOCK
    {"symbol": SYM, "event_type": "quarterly_results", "event_date": "2026-10-28", "period": "Q2 FY27",
     "purpose": "To consider and approve the financial results for the period ended September 30, 2026"},
    {"symbol": SYM, "event_type": "dividend", "event_date": "2026-10-28", "period": None, "purpose": "Interim dividend"},
    {"symbol": SYM, "event_type": "agm", "event_date": "2026-08-12", "period": None, "purpose": "Annual General Meeting"},
    {"symbol": SYM, "event_type": "quarterly_results", "event_date": "2026-07-29", "period": "Q1 FY27", "purpose": "Results"},
]
ACTIONS = [  # DaaS /corporate-actions, MOCK
    {"symbol": SYM, "action_type": "DIVIDEND", "action_subtype": None, "purpose": "Dividend - Rs 7.50 Per Share",
     "dividend_amount": 7.5, "ex_date": "2026-09-15", "record_date": "2026-09-15"},
    {"symbol": SYM, "action_type": "INTEREST_PAYMENT", "purpose": "Interest", "ex_date": "2026-09-20", "record_date": None},
]
FILINGS = [  # DaaS /announcements, MOCK
    {"announcement_id": "nse-1", "source": "NSE_ANN", "filed_at": "2026-10-28T07:11:15+00:00", "subject": "Outcome of Board Meeting",
     "description": "Financial results for the quarter", "attachment_url": "https://example.invalid/a.pdf", "event_category": "earnings"},
    {"announcement_id": "bse-1", "source": "BSE_ANN", "filed_at": "2026-10-28T07:12:00+00:00", "subject": "Outcome of Board Meeting",
     "description": "Financial results for the quarter", "attachment_url": "https://example.invalid/b.pdf", "event_category": "earnings"},
    {"announcement_id": "nse-2", "source": "NSE_ANN", "filed_at": "2026-10-28T11:00:00+00:00", "subject": "Press Release",
     "description": "Press release after the close", "attachment_url": None, "event_category": None},
    {"announcement_id": "nse-3", "source": "NSE_ANN", "filed_at": "2026-10-20T05:00:00+00:00", "subject": "Trading Window",
     "description": "Closure of trading window", "attachment_url": None, "event_category": "regulatory"},
]


def macro_month(month: str) -> Dict[str, Any]:  # DaaS /desk/macro-calendar, MOCK
    ev = {
        "2026-10": [
            {"code": "IN_RBI_MPC", "date": "2026-10-02", "date_ist": "2026-10-02", "time": "10:00", "country": "IN", "short": "RBI rate",
             "name": "RBI interest rate decision", "impact": "H", "source": "RBI", "source_url": None},
            {"code": "US_FOMC", "date": "2026-10-28", "date_ist": "2026-10-28", "time": "23:30", "country": "US", "short": "Fed decision",
             "name": "Fed interest rate decision", "impact": "H", "source": "Fed", "source_url": "https://example.invalid/fomc"},
            {"code": "US_CORE_PCE_YOY", "date": "2026-10-29", "date_ist": "2026-10-29", "time": "18:00", "country": "US", "short": "Core PCE",
             "name": "Core PCE price index YoY", "period": "Sep 2026", "actual": None, "previous": 2.9, "unit": "%", "impact": "H", "source": "FRED"},
            {"code": "US_GDP_QOQ", "date": "2026-10-29", "date_ist": "2026-10-29", "time": "18:00", "country": "US", "short": "GDP",
             "name": "GDP growth rate QoQ, annualised", "impact": "H", "source": "FRED"},
        ],
    }.get(month, [])
    gaps = [] if ev or month < "2026-11" else ["no macro releases are stored for this month: the macro_calendar ingester has not loaded it yet"]
    return {"month": month, "events": ev, "gaps": gaps}


EXPIRIES = {"data": [{"expiry_date": d, "ce_count": 10, "pe_count": 10, "futures_count": 0, "latest_seen": "2026-10-28"}
                     for d in ("2026-08-25", "2026-09-29", "2026-10-27", "2026-11-24", "2026-12-29")]}
NIFTY_EXPIRIES = {"data": [{"expiry_date": d} for d in ("2026-10-06", "2026-10-13", "2026-10-20", "2026-10-27", "2026-11-03",
                                                        "2026-11-24", "2027-03-30")]}


def flows_daily() -> List[Dict[str, Any]]:  # DaaS /market-pulse/fii-dii daily, newest first, MOCK
    days = _weekdays(date(2026, 4, 1), date(2026, 10, 28))
    out = []
    for i, d in enumerate(days):
        big = d.isoformat() == "2026-10-15"
        fii = -9000.0 if big else float((i % 10) * 10) * (1 if i % 2 else -1)
        dii = 0.0 if big else float((i % 7) * 5)
        out.append({"date": d.isoformat(), "fii_net": fii, "dii_net": dii})
    return list(reversed(out))


def kite_close(day="2026-10-29", prev_close=210.0, **q) -> Dict[str, Any]:
    base = {"symbol": SYM, "ltp": 199.5, "open": 209.0, "high": 211.0, "low": 198.0, "close": prev_close, "volume": 5000.0,
            "exchange_ts": f"{day}T15:29:58+05:30"}
    base.update(q)
    return {"source": "kite_close", "day": day, "as_of": f"{day}T10:01:05+00:00", "quotes": {SYM: base}, "why": None}


def default_reply(path: str, params: Optional[dict]):
    if path == f"/events/{SYM}":
        return 200, {"data": CALENDAR}
    if path == "/corporate-actions":
        return 200, {"data": ACTIONS}
    if path == "/announcements":
        return 200, {"data": FILINGS}
    if path == "/desk/macro-calendar":
        return 200, macro_month(params["month"])
    if path == f"/fno/{SYM}/expiries":
        return 200, {"symbol": SYM, **EXPIRIES}
    if path == "/fno/NIFTY/expiries":
        return 200, {"symbol": "NIFTY", **NIFTY_EXPIRIES}
    if path == "/market-pulse/fii-dii":
        return 200, {"daily": flows_daily(), "monthly": []}
    if path == f"/prices/adjusted/{SYM}":
        return 200, {"data": price_rows()}
    return 404, {"detail": "not found"}


def make_client(monkeypatch, reply=default_reply, *, kite=None, holidays=({HOLIDAY}, True), signed_in=True, now=NOW):
    calls: List[tuple] = []

    async def get_raw(path: str, params: Optional[dict] = None, timeout: float = 10.0):
        calls.append((path, copy.deepcopy(params)))
        r = reply(path, params)
        if isinstance(r, BaseException):
            raise r
        return copy.deepcopy(r)

    async def day_quotes(symbols, now=None, feed=None):
        return kite or {"source": None, "day": None, "as_of": None, "quotes": {}, "why": "no_saved_close"}

    async def read_holidays(a, b):
        if isinstance(holidays, BaseException):
            raise holidays
        return holidays

    async def fake_user(request: Request):
        if not signed_in:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": "u1"}

    monkeypatch.setattr(daas_client, "get_raw", get_raw)
    monkeypatch.setattr(daas_client, "is_configured", lambda: True)
    monkeypatch.setattr(route.dq, "day_quotes", day_quotes)
    monkeypatch.setattr(route, "read_holidays", read_holidays)
    monkeypatch.setattr(route, "get_current_user", fake_user)
    monkeypatch.setattr(route, "_now_ist", lambda: now)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app), calls


def by(events, kind, day=None):
    return [e for e in events if e["kind"] == kind and (day is None or e["date"] == day)]


# ── C1 one merged, sorted list from every source ─────────────────────────────

def test_c1_merges_every_source_into_one_sorted_list(monkeypatch):
    c, calls = make_client(monkeypatch)
    r = c.get(f"/api/desk/chart-events/{SYM.lower()}")
    assert r.status_code == 200, r.text
    b = r.json()
    assert (b["symbol"], b["from"], b["to"], b["read_only"]) == (SYM, "2026-07-31", "2026-11-28", True)
    assert b["sources"] == {"events_calendar": "ok", "filings": "ok", "corporate_actions": "ok", "macro": "ok", "fno_expiry": "ok",
                            "fii_dii": "ok", "prices": "ok"}
    ev = b["events"]
    assert {e["kind"] for e in ev} == {"results", "agm", "dividend", "filing", "macro", "fno_expiry", "fii_dii"}
    keys = [(e["date"], e["time"] or "", ce.KIND_ORDER[e["kind"]], e["title"]) for e in ev]
    assert keys == sorted(keys) and len({e["id"] for e in ev}) == len(ev)
    for e in ev:
        assert set(e) == {"id", "date", "time", "kind", "scope", "title", "detail", "source", "url", "reaction"}
        assert e["scope"] == ("market" if e["kind"] in ("macro", "fno_expiry", "fii_dii") else "stock")
    # results day: the dividend board row folds into the results event; the 29 Jul results are outside the window
    res = by(ev, "results")
    assert [(e["date"], e["title"]) for e in res] == [("2026-10-28", "Quarterly results, Q2 FY27")]
    assert "Interim dividend" in res[0]["detail"] and "also on the agenda: dividend" in res[0]["detail"]
    assert not by(ev, "board")
    # corporate action on its ex-date; bond payments left out
    assert [(e["date"], e["title"]) for e in by(ev, "dividend")] == [("2026-09-15", "Ex-dividend ₹7.5 a share")]
    # filings: the BSE copy merges into the NSE one, the regulatory one is left out, times are IST
    fil = by(ev, "filing")
    assert [(e["date"], e["time"], e["title"], e["url"]) for e in fil] == [
        ("2026-10-28", "12:41", "Outcome of Board Meeting", "https://example.invalid/a.pdf"),
        ("2026-10-28", "16:30", "Press Release", None)]
    # macro: the two 18:00 releases of 29 Oct are one event; IST time kept
    mac = by(ev, "macro")
    assert [(e["date"], e["time"], e["title"]) for e in mac] == [
        ("2026-10-02", "10:00", "IN RBI rate"), ("2026-10-28", "23:30", "US Fed decision"), ("2026-10-29", "18:00", "US Core PCE · US GDP")]
    assert "previous 2.9%" in mac[2]["detail"]
    # expiries: the symbol's own, inside the window
    assert [e["date"] for e in by(ev, "fno_expiry")] == ["2026-08-25", "2026-09-29", "2026-10-27", "2026-11-24"]
    # flow days: the big FII sale is one; the rule is stated with the sessions actually used
    big = by(ev, "fii_dii", "2026-10-15")
    assert big and big[0]["title"] == "FII -9,000 Cr"
    assert "90th percentile" in b["fii_dii_rule"] and "fewer than 250" in b["fii_dii_rule"]
    assert any("no releases are stored for 2026-11" in n for n in b["notes"])
    # what was asked of each source
    asked = dict(calls)
    assert asked[f"/events/{SYM}"]["from_date"] == "2026-07-31"
    assert asked["/announcements"] == {"symbol": SYM, "filed_from": "2026-07-30", "filed_to": "2026-11-28", "limit": route.FILINGS_LIMIT}
    assert sorted(p["month"] for path, p in calls if path == "/desk/macro-calendar") == ["2026-07", "2026-08", "2026-09", "2026-10", "2026-11"]


# ── C2 reaction numbers; after 15:30 → next session; a holiday → next session ──

def test_c2_reaction_from_daily_bars(monkeypatch):
    c, _ = make_client(monkeypatch)
    ev = c.get(f"/api/desk/chart-events/{SYM}").json()["events"]
    rx = by(ev, "dividend")[0]["reaction"]
    # 15 Sep: open 147 close 148.5 volume 2000; 14 Sep close 150; 16 Sep close 151.47; the 20 sessions before: volume 1000
    assert rx == {"basis": ce.REACTION_BASIS, "session": "2026-09-15", "day_change_pct": -1.0, "next_day_change_pct": 2.0,
                  "gap_pct": -2.0, "volume_x_avg20": 2.0, "provisional": False}


def test_c2_after_the_close_and_on_a_holiday_react_on_the_next_session(monkeypatch):
    c, _ = make_client(monkeypatch)
    ev = c.get(f"/api/desk/chart-events/{SYM}").json()["events"]
    assert by(ev, "filing")[0]["reaction"]["session"] == "2026-10-28"           # 12:41 IST: that session
    late = by(ev, "filing")[1]["reaction"]                                      # 16:30 IST: the next session (no bar yet → None)
    assert late is None
    assert by(ev, "macro", "2026-10-02")[0]["reaction"]["session"] == "2026-10-05"   # holiday Friday → Monday


def test_c2_pure_reaction_numbers():
    bars = [[(date(2026, 9, 1) + timedelta(days=i)).isoformat(), 100.0, 101.0, 99.0, 100.0, 1000.0] for i in range(25)]
    bars[21] = [bars[21][0], 103.0, 106.0, 102.0, 105.0, 4000.0]
    bars[22] = [bars[22][0], 105.0, 106.0, 99.0, 99.75, 1000.0]
    rx = ce.reaction(bars, 21, None)
    assert (rx["day_change_pct"], rx["gap_pct"], rx["next_day_change_pct"], rx["volume_x_avg20"]) == (5.0, 3.0, -5.0, 4.0)
    assert ce.reaction(bars, 10, None)["volume_x_avg20"] is None                # fewer than 20 sessions before it
    assert ce.reaction(bars, 0, None)["day_change_pct"] is None                 # no previous close
    assert ce.reaction_day("2026-10-28", "15:30") == date(2026, 10, 28)
    assert ce.reaction_day("2026-10-28", "15:31") == date(2026, 10, 29)


# ── C3 future event or a day without bars → reaction null ────────────────────

def test_c3_future_events_and_days_without_bars_have_no_reaction(monkeypatch):
    missing = date(2026, 9, 29)                                                  # a weekday the MOCK prices leave out

    def reply(path, params):
        if path == f"/prices/adjusted/{SYM}":
            return 200, {"data": price_rows(skip={missing})}
        return default_reply(path, params)

    c, _ = make_client(monkeypatch, reply)
    ev = c.get(f"/api/desk/chart-events/{SYM}").json()["events"]
    assert by(ev, "fno_expiry", "2026-11-24")[0]["reaction"] is None            # future
    assert by(ev, "macro", "2026-10-29")[0]["reaction"] is None                 # 18:00 today → tomorrow, no bar
    assert by(ev, "fno_expiry", "2026-09-29")[0]["reaction"] is None            # a weekday without a bar, not a holiday
    assert by(ev, "fno_expiry", "2026-08-25")[0]["reaction"] is not None


def test_c3_without_the_holiday_list_a_skipped_weekday_is_not_guessed(monkeypatch):
    c, _ = make_client(monkeypatch, holidays=(None, False))
    b = c.get(f"/api/desk/chart-events/{SYM}").json()
    assert by(b["events"], "macro", "2026-10-02")[0]["reaction"] is None
    assert any("holiday list could not be read" in n for n in b["notes"])


# ── C4 one source fails → the others still answer ────────────────────────────

@pytest.mark.parametrize("failure,why", [
    (daas_client.DaasError("boom secret-ish text"), "unavailable: the data platform did not answer"),
    ((500, {"detail": "internal"}), "unavailable: the data platform answered HTTP 500"),
    ((200, {"unexpected": True}), "unavailable: the data platform's answer had an unexpected shape"),
])
def test_c4_a_failed_source_is_listed_and_the_rest_answer(monkeypatch, failure, why):
    def reply(path, params):
        return failure if path == "/announcements" else default_reply(path, params)

    c, _ = make_client(monkeypatch, reply)
    r = c.get(f"/api/desk/chart-events/{SYM}")
    assert r.status_code == 200
    b = r.json()
    assert b["sources"]["filings"] == why and "secret" not in r.text
    assert all(v == "ok" for k, v in b["sources"].items() if k != "filings")
    assert not by(b["events"], "filing") and by(b["events"], "results") and by(b["events"], "macro")


def test_c4_a_slow_source_times_out_alone(monkeypatch):
    monkeypatch.setattr(route, "SOURCE_TIMEOUT", 0.05)

    async def read_flows():
        await asyncio.sleep(5)

    monkeypatch.setattr(route, "read_flows", read_flows)
    c, _ = make_client(monkeypatch)
    b = c.get(f"/api/desk/chart-events/{SYM}").json()
    assert b["sources"]["fii_dii"] == "unavailable: no answer within 0.05 s" and not by(b["events"], "fii_dii")
    assert b["sources"]["macro"] == "ok" and b["fii_dii_rule"].startswith("A session where |FII net|")


def test_c4_every_source_down_is_still_200(monkeypatch):
    c, _ = make_client(monkeypatch, lambda p, q: daas_client.DaasError("down"))
    b = c.get(f"/api/desk/chart-events/{SYM}").json()
    assert b["events"] == [] and all(v.startswith("unavailable: ") for v in b["sources"].values())


def test_c4_too_few_flow_sessions_is_unavailable_with_the_reason(monkeypatch):
    def reply(path, params):
        if path == "/market-pulse/fii-dii":
            return 200, {"daily": flows_daily()[:30], "monthly": []}
        return default_reply(path, params)

    c, _ = make_client(monkeypatch, reply)
    b = c.get(f"/api/desk/chart-events/{SYM}").json()
    assert b["sources"]["fii_dii"].startswith("unavailable: only 30 daily FII/DII sessions are stored")


# ── C5 today's Kite bar makes a reaction provisional ─────────────────────────

def test_c5_the_kite_close_bar_is_used_and_flagged(monkeypatch):
    c, _ = make_client(monkeypatch, kite=kite_close())
    ev = c.get(f"/api/desk/chart-events/{SYM}").json()["events"]
    late = by(ev, "filing")[1]["reaction"]                                      # 16:30 IST on 28 Oct → 29 Oct, the Kite close
    assert late["session"] == "2026-10-29" and late["provisional"] is True
    assert late["day_change_pct"] == -5.0 and late["next_day_change_pct"] is None   # 199.5 vs 210
    fed = by(ev, "macro", "2026-10-28")[0]["reaction"]                          # 23:30 IST → the Kite session too
    assert fed["session"] == "2026-10-29" and fed["provisional"] is True
    res = by(ev, "results")[0]["reaction"]                                      # 28 Oct itself, its next day is the Kite bar
    assert (res["session"], res["day_change_pct"], res["gap_pct"], res["volume_x_avg20"], res["next_day_change_pct"],
            res["provisional"]) == ("2026-10-28", 5.0, 2.0, 3.0, -5.0, True)
    assert by(ev, "dividend")[0]["reaction"]["provisional"] is False


def test_c5_a_kite_bar_that_does_not_join_is_not_used(monkeypatch):
    c, _ = make_client(monkeypatch, kite=kite_close(prev_close=180.0))      # not the series' last close (210)
    ev = c.get(f"/api/desk/chart-events/{SYM}").json()["events"]
    assert by(ev, "filing")[1]["reaction"] is None
    assert by(ev, "results")[0]["reaction"]["provisional"] is False


# ── window, auth, fallbacks, rule ────────────────────────────────────────────

@pytest.mark.parametrize("qs,code", [("?from=2026-10-10&to=2026-10-01", 422), ("?from=2025-01-01&to=2026-10-01", 422),
                                     ("?from=2026-02-30", 422), ("?from=20261001", 422)])
def test_bad_windows_are_refused_before_any_read(monkeypatch, qs, code):
    c, calls = make_client(monkeypatch)
    assert c.get(f"/api/desk/chart-events/{SYM}{qs}").status_code == code and calls == []


def test_an_explicit_window_is_honoured(monkeypatch):
    c, _ = make_client(monkeypatch)
    b = c.get(f"/api/desk/chart-events/{SYM}?from=2026-09-01&to=2026-09-30").json()
    assert (b["from"], b["to"]) == ("2026-09-01", "2026-09-30")
    assert all("2026-09-01" <= e["date"] <= "2026-09-30" for e in b["events"])
    assert by(b["events"], "dividend") and not by(b["events"], "results")


def test_login_is_required(monkeypatch):
    c, calls = make_client(monkeypatch, signed_in=False)
    assert c.get(f"/api/desk/chart-events/{SYM}").status_code == 401 and calls == []


def test_a_symbol_without_fno_gets_nifty_monthly_expiries(monkeypatch):
    def reply(path, params):
        if path == f"/fno/{SYM}/expiries":
            return 200, {"symbol": SYM, "data": [], "count": 0}
        return default_reply(path, params)

    c, _ = make_client(monkeypatch, reply)
    b = c.get(f"/api/desk/chart-events/{SYM}").json()
    exp = by(b["events"], "fno_expiry")
    assert [e["date"] for e in exp] == ["2026-10-27", "2026-11-24"] and exp[0]["title"] == "F&O expiry (NIFTY monthly)"
    assert b["sources"]["fno_expiry"] == "ok" and any("NIFTY's monthly expiries" in n for n in b["notes"])


def test_no_bars_leaves_events_without_reactions_and_says_why(monkeypatch):
    def reply(path, params):
        if path == f"/prices/adjusted/{SYM}":
            return 404, {"detail": "not found"}
        return default_reply(path, params)

    c, _ = make_client(monkeypatch, reply)
    b = c.get(f"/api/desk/chart-events/{SYM}").json()
    assert b["sources"]["prices"] == f"unavailable: no daily bars are stored for {SYM}"
    assert b["events"] and all(e["reaction"] is None for e in b["events"])


def test_flow_day_rule_uses_the_90th_percentile_of_each_side():
    days = _weekdays(date(2026, 5, 1), date(2026, 9, 30))[:100]
    daily = [{"date": d.isoformat(), "fii_net": float(i + 1) * (-1 if i % 2 else 1), "dii_net": None} for i, d in enumerate(days)]
    events, rule, err = ce.flow_days(daily, days[0], days[-1])
    assert err is None and ce.percentile([float(i + 1) for i in range(100)], 90) == pytest.approx(90.1)
    assert len(events) == 10 and all(abs(float(e["title"].split()[1].replace(",", ""))) >= 91 for e in events)
    assert "100 sessions used" in rule and "FII 90 Cr" in rule
    _, _, err2 = ce.flow_days(daily[:59], days[0], days[-1])
    assert err2.startswith("only 59 daily FII/DII sessions")


def test_merge_keeps_different_filings_apart_and_ids_unique():
    a = ce.make_event("filing", "2026-10-01", "General Updates", source="s", detail="one", key="x")
    b = ce.make_event("filing", "2026-10-01", "General Updates", source="s", detail="two", key="y")
    m1 = ce.make_event("macro", "2026-10-01", "US CPI", source="s", time="18:00", key="A")
    m2 = ce.make_event("macro", "2026-10-01", "IN RBI rate", source="s", time="10:00", key="B")
    out = ce.merge([a, b, m1, m2, dict(a)])                                      # the repeated filing merges, the rest stay
    assert [(e["title"], e["detail"]) for e in out] == [("General Updates", "one"), ("General Updates", "two"),
                                                       ("IN RBI rate", None), ("US CPI", None)]
    assert len({e["id"] for e in out}) == 4
