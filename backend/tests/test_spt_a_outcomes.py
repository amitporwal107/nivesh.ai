"""SPT slice A — signal outcomes and scanner analytics (test cases test_reports/spt_a_TESTCASES.md SPT-A-36 … SPT-A-41).

Covers services/spt/outcomes/{tracker,analytics}.py and GET /api/v1/analytics/scanners. No network and no real database.

MOCK — not real data: every bar, price and level below is made up; each expected figure is worked out by hand in the test.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from routes import spt_signals as route
from services.scan_builder import signals as SIG
from services.spt import constants as C
from services.spt.opportunities import consolidate as cons
from services.spt.outcomes import analytics, tracker
from services.spt.signals import ingest
from tests.spt_a_fakes import DAY, DB, D, Inputs, bars_from, ist, mark, reset_module_state, strong, weekdays

NOW = ist(10, 0, 30)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean():
    reset_module_state()
    yield


def series(history, day0, after, *, end_after=None):
    """Bars: `history` closes up to 3 Nov, the detection day's (4 Nov) bar, then `after` bars on the next weekdays.
    `day0` and each of `after` are (open, high, low, close)."""
    hist = bars_from(history, end=date(2026, 11, 3))
    days = weekdays(len(after) + 1, end_after or _nth_after(D, len(after)))
    out = hist + [{"date": D, "open": day0[0], "high": day0[1], "low": day0[2], "close": day0[3], "volume": 1e6}]
    for d, (o, h, lo, c) in zip(days[1:], after):
        out.append({"date": d, "open": o, "high": h, "low": lo, "close": c, "volume": 1e6})
    return out


def _nth_after(d, n):
    x = d
    for _ in range(n):
        x += timedelta(days=1)
        while x.weekday() >= 5:
            x += timedelta(days=1)
    return x


def ohlc(c, rng=1.0):
    return (c, c + rng, c - rng, c)


# ── SPT-A-36: forward returns and excursions ─────────────────────────────────────────────────────────────────────────

def test_SPT_A_36_forward_returns_mfe_mae_by_hand():
    bars = series([98.0] * 30, ohlc(101.0), [ohlc(101.0 + k) for k in range(1, 21)])
    fw = tracker.forward(bars, det_day=D, price=100.0, direction="long")
    assert fw["t0"] == {"status": "done", "day": "2026-11-04", "close": 101.0, "return_pct": 1.0, "raw_return_pct": 1.0}
    assert fw["t1"] == {"status": "done", "day": "2026-11-05", "close": 102.0, "return_pct": 2.0, "raw_return_pct": 2.0,
                        "mfe_pct": 3.0, "mae_pct": 1.0}
    assert (fw["t5"]["close"], fw["t5"]["return_pct"], fw["t5"]["mfe_pct"], fw["t5"]["mae_pct"]) == (106.0, 6.0, 7.0, 1.0)
    assert (fw["t20"]["close"], fw["t20"]["return_pct"], fw["t20"]["mfe_pct"]) == (121.0, 21.0, 22.0)
    assert fw["t20"]["day"] == "2026-12-02" and fw["complete"] is True
    short = tracker.forward(bars, det_day=D, price=100.0, direction="short")
    assert (short["t1"]["return_pct"], short["t1"]["raw_return_pct"]) == (-2.0, 2.0)
    assert (short["t1"]["mfe_pct"], short["t1"]["mae_pct"]) == (-1.0, -3.0)     # a short gains only when the price falls
    part = tracker.forward(bars[:-13], det_day=D, price=100.0, direction="long")
    assert part["t5"]["status"] == "done" and part["t10"] == {"status": "pending", "sessions_known": 7}
    assert part["complete"] is False


# ── SPT-A-37: the hypothetical scan-plan-v3 trade ────────────────────────────────────────────────────────────────────

PLAN = {"rules": "scan-plan-v3", "entry": 100.0, "stop_loss": 96.0, "target_1": 108.0, "target_2": 116.0, "plan_ok": True}


def plan_of(day0, after, history=None):
    return tracker.plan_outcome(series(history or [99.0] * 40, day0, after), det_day=D, plan=PLAN)


def test_SPT_A_37_target_1_first_then_target_2():
    p = plan_of(ohlc(100.0), [ohlc(101.0), ohlc(103.0), ohlc(105.0), (107.0, 108.5, 106.0, 107.0), ohlc(112.0),
                              (115.0, 116.5, 114.0, 115.0)])
    assert (p["first_event"], p["first_event_day"], p["exit_price"], p["r_multiple"]) == ("target_1", "2026-11-10", 108.0, 2.0)
    assert p["hits"] == {"stop": None, "target_1": "2026-11-10", "target_2": "2026-11-12", "trend_exit": None}
    assert p["complete"] is True and p["sessions_checked"] == 6


def test_SPT_A_37_target_and_stop_in_one_session_counts_the_stop():
    p = plan_of(ohlc(100.0), [(101.0, 109.0, 94.0, 95.0)])
    assert (p["first_event"], p["exit_price"], p["r_multiple"], p["conservative_same_bar"]) == ("stop", 95.0, -1.25, True)
    assert p["hits"]["target_1"] is None and p["complete"] is True


def test_SPT_A_37_detection_day_close_below_the_stop_and_a_gap():
    p = plan_of((100.0, 101.0, 94.0, 95.0), [ohlc(110.0)])
    assert (p["first_event"], p["first_event_day"], p["exit_price"]) == ("stop", "2026-11-04", 95.0)
    g = plan_of(ohlc(100.0), [(94.0, 95.0, 93.0, 94.4)])
    assert (g["first_event"], g["exit_price"], g["r_multiple"], g["gap_open"]) == ("stop", 94.4, -1.4, True)


def test_SPT_A_37_trend_exit_time_exit_and_open():
    t = plan_of(ohlc(100.0), [ohlc(99.6, 0.2)], history=[100.0] * 40)        # SMA20 = (19 × 100 + 99.6) / 20 = 99.98
    assert (t["first_event"], t["exit_price"], t["r_multiple"]) == ("trend_exit", 99.6, -0.1)
    rise = [ohlc(round(100.0 + 0.1 * k, 1), 0.5) for k in range(1, 21)]       # never 108, always above its average
    te = plan_of(ohlc(100.0), rise)
    assert (te["first_event"], te["first_event_day"], te["exit_price"], te["r_multiple"]) == ("time_exit", "2026-12-02",
                                                                                              102.0, 0.5)
    op = plan_of(ohlc(100.0), rise[:3])
    assert (op["first_event"], op["complete"], op["sessions_checked"]) == ("open", False, 3)
    assert tracker.plan_outcome([], det_day=D, plan={**PLAN, "plan_ok": False})["first_event"] == "no_plan"


# ── SPT-A-38: a series break after the detection ─────────────────────────────────────────────────────────────────────

def test_SPT_A_38_a_bonus_after_the_signal_ends_the_measurement():
    bars = series([98.0] * 30, ohlc(100.0), [ohlc(101.0), ohlc(50.5)] + [ohlc(51.0)] * 20)
    fw = tracker.forward(bars, det_day=D, price=100.0, direction="long")
    assert fw["t1"]["status"] == "done" and fw["t1"]["return_pct"] == 1.0
    for k in ("t5", "t10", "t20"):
        assert fw[k] == {"status": "series_break", "day": "2026-11-06", "return_pct": None, "raw_return_pct": None,
                         "mfe_pct": None, "mae_pct": None}
    assert fw["complete"] is True
    p = tracker.plan_outcome(bars, det_day=D, plan=PLAN)
    assert (p["first_event"], p["first_event_day"], p["complete"]) == ("series_break", "2026-11-06", True)


# ── SPT-A-39 … 41: fade, storage apart from trades, analytics, the evening run ───────────────────────────────────────

def test_SPT_A_39_fade_from_the_days_scores():
    doc = {"as_of": "2026-11-04T22:45:20+05:30", "scores": {"AAA": {"score": 65}, "BBB": {"score": 80},
                                                             "ETF1": {"score": None, "note": "Not scored: an ETF"}}}
    assert tracker.fade("strong", "AAA", doc) == {"faded": True, "score_at_close": 65,
                                                  "scores_as_of": "2026-11-04T22:45:20+05:30", "reason": None}
    assert tracker.fade("strong", "BBB", doc)["faded"] is False
    assert tracker.fade("list", "BBB", doc)["faded"] is None and tracker.fade("list", "BBB", doc)["score_at_close"] == 80
    assert tracker.fade("strong", "ETF1", doc)["reason"] == "Not scored: an ETF"
    assert tracker.fade("strong", "AAA", None)["faded"] is None and tracker.fade("strong", "AAA", None)["reason"]


def setup_day(db):
    run(ingest.ingest(db, day=DAY, marks=[mark("dt_52w_high", "AAA", ist(9, 30), 100.0),
                                          mark("dt_below_dma", "BBB", ist(9, 31), 100.0),
                                          mark("dt_breakout_15m", "AAA", ist(9, 40), 100.0)],
                      strong=[strong("AAA", ist(9, 45), entry=100.0, atr=2.0)], now=NOW))
    run(cons.consolidate(db, days=[DAY], now=NOW))


def market_after(n_after):
    up = series([98.0] * 30, ohlc(101.0), [ohlc(101.0 + k) for k in range(1, n_after + 1)])
    down = series([98.0] * 30, ohlc(99.0), [ohlc(99.0 - k * 0.5) for k in range(1, n_after + 1)])
    return {"AAA": up, "BBB": down, "RELIANCE": up}


def test_SPT_A_40_outcomes_are_stored_by_signal_apart_from_trades():
    db = DB()
    setup_day(db)
    later = datetime(2026, 12, 2, 15, 0, tzinfo=timezone.utc)
    c = run(tracker.compute(db, now=later, inputs=Inputs(market_after(20)), days=[DAY],
                            scores_docs={DAY: {"as_of": "x", "scores": {"AAA": {"score": 66}}}}))
    assert (c["events"], c["computed"], c["complete"]) == (4, 4, 4)
    by = {d["_id"]: d for d in db["spt_signal_outcomes"].docs}
    assert set(by) == {"sig:2026-11-04:dt_52w_high:AAA", "sig:2026-11-04:dt_below_dma:BBB",
                       "sig:2026-11-04:dt_breakout_15m:AAA", "sig:2026-11-04:strong:AAA"}
    st = by["sig:2026-11-04:strong:AAA"]
    assert st["forward"]["t5"]["return_pct"] == 6.0 and st["plan"]["first_event"] == "target_1"     # 101+k: T1 108 on k=7
    assert st["fade"]["faded"] is True and st["version"] == C.OUTCOME_VERSION
    bbb = by["sig:2026-11-04:dt_below_dma:BBB"]
    assert bbb["direction"] == "short" and bbb["forward"]["t1"]["return_pct"] == 1.5         # 99 − 0.5 = 98.5 from 100
    assert len(st["opportunity_ids"]) == 1 and st["opportunity_ids"] == by["sig:2026-11-04:dt_52w_high:AAA"]["opportunity_ids"]
    assert set(db.c) <= {"spt_signal_events", "spt_events", "spt_opportunities", "spt_signal_outcomes"}   # no trade data
    again = run(tracker.compute(db, now=later, inputs=Inputs(market_after(20)), days=[DAY]))
    assert again["computed"] == 0 and again["skipped"] == 4                                  # complete: not recomputed


def test_SPT_A_40_analytics_groups_with_sample_sizes(monkeypatch):
    db = DB()
    setup_day(db)
    run(tracker.compute(db, now=datetime(2026, 12, 2, 15, 0, tzinfo=timezone.utc), inputs=Inputs(market_after(20)),
                        days=[DAY]))
    rep = run(analytics.scanners(db, day_from="2026-11-01", day_to="2026-11-30"))
    assert rep["totals"]["signals"] == 4 and rep["totals"]["small_sample"] is True and rep["min_sample"] == 30
    t1 = rep["totals"]["horizons"]["t1"]
    # returns at T+1: AAA list +2, AAA 15m +2, strong +2, BBB short +1.5 → 4 of 4 positive
    assert (t1["n"], t1["hit_rate_pct"], t1["avg_return_pct"], t1["median_return_pct"]) == (4, 100.0, 1.88, 2.0)
    assert t1["hit_rate_ci95_pct"] == [51.0, 100.0] and t1["small_sample"] is True
    keys = {r["key"]: r for r in rep["by_scanner"]}
    assert set(keys) == {"dt_52w_high", "dt_below_dma", "dt_breakout_15m", "strength_70"}
    assert keys["strength_70"]["plan"]["decided"] == 1 and keys["strength_70"]["plan"]["target_1_rate_pct"] == 100.0
    assert {r["key"] for r in rep["by_score_band"]} == {"70-79", "unscored"}
    assert {r["key"] for r in rep["by_category"]} == {"breakout", "breakdown"}
    assert "not probabilities" in rep["note"]
    assert analytics.band(None) == "unscored" and analytics.band(70) == "70-79" and analytics.band(95) == "90+"
    assert analytics.wilson(0, 0) is None
    # the route (read-only)
    monkeypatch.setattr(route, "db", db)

    async def fake_user(request: Request):
        if not request.headers.get("X-Test-User"):
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": "u"}

    monkeypatch.setattr(route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(route.router)
    client = TestClient(app)
    assert client.get("/api/v1/analytics/scanners").status_code == 401
    h = {"X-Test-User": "u"}
    writes = db.writes
    r = client.get("/api/v1/analytics/scanners", params={"from": "2026-11-01", "to": "2026-11-30", "kind": "strong"}, headers=h)
    assert r.status_code == 200 and r.json()["totals"]["signals"] == 1 and db.writes == writes
    for params, code in (({"from": "2026-11-30", "to": "2026-11-01"}, "invalid_range"),
                         ({"from": "2026-01-01", "to": "2026-11-30"}, "invalid_range"),
                         ({"kind": "all"}, "invalid_kind"), ({"from": "nope"}, "invalid_day")):
        r = client.get("/api/v1/analytics/scanners", params=params, headers=h)
        assert (r.status_code, r.json()["detail"]) == (422, code), params


def test_SPT_A_41_evening_run_waits_for_the_nse_file_and_runs_once():
    db = DB()
    setup_day(db)
    scan = SIG.LocalSignalStore()
    run(SIG.save_scores(DAY, {"AAA": {"score": 64}}, ist(22, 0), store=scan))
    no_file = {**market_after(0), "RELIANCE": bars_from([100.0] * 30, end=date(2026, 11, 3))}
    assert run(tracker.evening(db, now=ist(18, 0), inputs=Inputs(market_after(0)), scan_store=scan)) == {"skipped": "not_evening"}
    r = run(tracker.evening(db, now=ist(20, 0), inputs=Inputs(no_file), scan_store=scan))
    assert r == {"skipped": "nse_file_not_in", "reference_last_bar": "2026-11-03"} and not db["spt_signal_outcomes"].docs
    inp = Inputs(market_after(0))                                              # 4 Nov's bars are in
    r = run(tracker.evening(db, now=ist(20, 15), inputs=inp, scan_store=scan))
    assert r["computed"] == 4 and r["remaining"] == 0
    st = next(d for d in db["spt_state"].docs if d["_id"] == "spt_a_outcomes")
    assert st["done_day"] == DAY
    strong_doc = next(d for d in db["spt_signal_outcomes"].docs if d["kind"] == "strong")
    assert strong_doc["fade"]["faded"] is True and strong_doc["forward"]["t0"]["return_pct"] == 1.0
    assert strong_doc["forward"]["t1"]["status"] == "pending" and strong_doc["complete"] is False
    assert run(tracker.evening(db, now=ist(20, 20), inputs=inp, scan_store=scan)) == {"skipped": "done"}
    assert run(tracker.evening(db, now=ist(20, 0, day=date(2026, 11, 7)), inputs=inp, scan_store=scan)) == {
        "skipped": "not_evening"}                                             # Saturday
