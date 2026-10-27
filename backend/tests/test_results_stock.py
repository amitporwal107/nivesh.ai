"""Results This Week (docs/EARNINGS_SURPRISE_TRACKER.md §9): fno_track snapshots, the per-stock results file, its route.

MOCK — not real data: every row and document below is synthetic, except the cases marked "staging 2026-10-27", whose
figures were copied from the staging warehouse that day (MANKIND / BAJAJ-AUTO build-up rows and rollover readings).
"""
from __future__ import annotations

import asyncio
import copy
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from routes import results_week as route
from services.results_week import stock as rs
from services.results_week import track as tr

DAY = date(2026, 10, 27)
SESS = [date(2026, 10, 1) + timedelta(days=i) for i in range(40) if (date(2026, 10, 1) + timedelta(days=i)).weekday() < 5
        and date(2026, 10, 1) + timedelta(days=i) != date(2026, 10, 20)]
IST = timezone(timedelta(hours=5, minutes=30))


def bu(oi, oi_chg_pct, cash_close, cash_chg_pct):
    return {"symbol": "MOCK", "oi": oi, "oi_chg_pct": oi_chg_pct, "cash_close": cash_close, "cash_chg_pct": cash_chg_pct}


# ── §9a snapshots ──────────────────────────────────────────────────────────────────────────────────────────────

def test_snap_day_reads_the_sessions_own_buildup():
    s = tr.snap_day("2026-10-26", bu(3847250, 9.6, 2311.7, 4.49))          # staging 2026-10-27: MANKIND on 26 Oct
    assert (s["state"], s["text"], s["price_pct"], s["oi_pct"]) == ("long_buildup", "long build-up", 4.49, 9.6)
    assert tr.snap_day("2026-10-26", None) is None


def test_snap_span_without_an_expiry_reads_the_state():
    s = tr.snap_span("2026-10-22", bu(100, 0, 100.0, 0), "2026-10-23", bu(110, 0, 103.0, 0), expiries=[date(2026, 10, 27)])
    assert s["state"] == "long_buildup" and s["oi_comparable"] is True and s["price_pct"] == 3.0 and s["oi_pct"] == 10.0


@pytest.mark.parametrize("oi1", [90, 118])                                     # falling and rising OI across the expiry
def test_snap_span_across_an_expiry_is_not_read_either_way(oi1):
    s = tr.snap_span("2026-10-26", bu(100, 0, 100.0, 0), "2026-10-27", bu(oi1, 0, 103.0, 0), expiries=[date(2026, 10, 27)])
    assert s["state"] is None and s["oi_comparable"] is False and s["text"] == "spans an expiry: OI not comparable"
    assert "not comparable" in s["note"]


def test_carry_text_is_the_standard_rollover_against_its_usual():
    rb = {"pct": 79.8, "past": [{"pct": 83.7}, {"pct": 90.7}, {"pct": 78.9}, {"pct": 87.3}, {"pct": 89.2}]}   # staging: BAJAJ-AUTO
    assert tr.roll_carry(rb) == -6.2
    assert tr.carry_text(rb) == "rollover 79.8 % vs its usual 86.0 % (lower than usual)"
    assert tr.carry_text({"pct": 92.6, "past": [{"pct": 93.4}, {"pct": 95.2}, {"pct": 90.0}, {"pct": 93.4}, {"pct": 96.1}]}).endswith("(normal)")
    assert tr.carry_text({"pct": 80.0, "past": []}) is None and tr.carry_text(None) is None


def row(status="declared", fno=True, first="2026-10-27", **kw):
    r = {"symbol": "MOCK", "status": status, "fno": fno, "event_date": "2026-10-26", "filed_at": "2026-10-26T15:29:10+00:00",
         "reaction": {"first_session": first} if first else None, "fno_buildup": None}
    r.update(kw)
    return r


def test_fno_track_declared_before_and_after_with_the_expiry_carry():
    by = {"2026-10-26": {"MOCK": bu(100, 3.5, 100.0, -0.01)}, "2026-10-27": {"MOCK": bu(118.5, 18.5, 103.17, 3.17)}}
    rb = {"as_of": "2026-10-27", "rollover": {"pct": 79.8, "past": [{"pct": 86.0}]}}
    t = tr.fno_track(row(fno_buildup=rb), SESS, date(2026, 10, 27), by, [date(2026, 10, 27)])
    assert t["before"]["date"] == "2026-10-26" and t["before"]["text"] == "no clear signal"
    assert t["after"]["oi_comparable"] is False and t["after"]["carry_vs_usual_pp"] == -6.2
    assert t["after"]["text"] == "rollover 79.8 % vs its usual 86.0 % (lower than usual)"


def test_fno_track_upcoming_and_non_fno():
    by = {"2026-10-27": {"MOCK": bu(100, -12.04, 5218.5, 0.38)}}
    t = tr.fno_track(row(status="upcoming", first=None, filed_at=None), SESS, date(2026, 10, 27), by, [])
    assert t["after"] is None and t["before"]["date"] == "2026-10-27"
    assert tr.fno_track(row(fno=False), SESS, date(2026, 10, 27), by, []) is None


def test_window_runs_from_five_before_to_the_latest_loaded():
    anchor, win = tr.window(date(2026, 10, 27), None, SESS, date(2026, 10, 27))
    assert anchor == date(2026, 10, 27) and [r for r, _ in win] == [-5, -4, -3, -2, -1, 0]
    assert date(2026, 10, 20) not in [d for _, d in win]                        # a holiday is not a session
    anchor, win = tr.window(None, date(2026, 10, 28), SESS, date(2026, 10, 27))  # upcoming: rel 0 is the meeting session
    assert anchor == date(2026, 10, 28) and win[-1][0] == -1


def test_session_rows_volume_and_excess():
    bars = {d: (100.0 + i, 1000.0) for i, d in enumerate(SESS)}
    nifty = {d: 1000.0 for d in SESS}
    _, win = tr.window(date(2026, 10, 27), None, SESS, date(2026, 10, 27))
    rows = tr.session_rows(win, "MOCK", bars, nifty, {}, SESS, tr.volume_base(bars, win[0][1], SESS))
    assert rows[-1]["volume_x"] == 1.0 and rows[-1]["excess_pct"] == rows[-1]["chg_pct"] and rows[-1]["fut"] is None


def test_pcr_and_next_premium():
    opts = [{"option_type": "PE", "open_interest": 50}, {"option_type": "CE", "open_interest": 100}, {"option_type": "PE", "open_interest": 30}]
    assert tr.pcr(opts) == 0.8 and tr.pcr([{"option_type": "PE", "open_interest": 5}]) is None
    fut = [{"expiry_date": "2026-10-27", "close_price": 101, "underlying_price": 100}, {"expiry_date": "2026-11-23", "close_price": 102, "underlying_price": 100}]
    assert tr.next_premium(fut, date(2026, 10, 27)) == 2.0 and tr.next_premium(fut, date(2026, 10, 26)) == 1.0


# ── §9b commentary and preview ──────────────────────────────────────────────────────────────────────────────────

def doc(aid, ts, cat, et, band="moderately_positive", conf=80, analyzed=None, **a):
    return {"announcement_id": aid, "event_ts": ts, "analyzed_at": analyzed or ts, "exchange_category": cat, "event_type": et,
            "net_band": band, "net_impact_score": 30, "confidence_score": conf, "mode": "single_full",
            "analysis": {"sum": f"MOCK summary {aid}", "pf": [["minor plus", 20], ["main plus", 70]], "nf": [["a minus", 40]],
                         "amt": [{"v": 4338, "u": "cr", "what": "Q2 revenue"}], "unk": ["guidance for H2"], **a}}


def test_commentary_splits_by_the_results_filing_and_keeps_the_latest_analysis():
    filed = datetime(2026, 10, 26, 15, 29, tzinfo=timezone.utc)
    docs = [doc("a1", datetime(2026, 10, 15, 8, 25), "Acquisition", "ACQUISITION", band="slightly_positive", conf=72),
            doc("r1", datetime(2026, 10, 26, 15, 30), "Outcome of Board Meeting", "QUARTERLY RESULTS", conf=80),
            doc("r1", datetime(2026, 10, 26, 15, 30), "Outcome of Board Meeting", "QUARTERLY RESULTS", conf=88,
                analyzed=datetime(2026, 10, 26, 20, 0)),
            doc("p1", datetime(2026, 10, 26, 16, 0), "Investor Presentation", "RESULTS", conf=85),
            doc("c1", datetime(2026, 10, 29, 10, 0), "Analysts/Institutional Investor Meet/Con. Call Updates", "EARNINGS CALL", conf=70)]
    c = rs.split_commentary(docs, filed, {"r1": "https://x/r1.pdf"})
    assert [i["announcement_id"] for i in c["pre"]] == ["a1"]
    assert [i["announcement_id"] for i in c["results"]] == ["r1", "p1"] and c["results"][0]["confidence"] == 88
    assert [i["kind"] for i in c["post"]] == ["earnings_call"]          # NSE files calls under "… Investor Meet/Con. Call Updates"
    assert c["results"][0]["positives"] == ["main plus", "minor plus"] and c["results"][0]["url"] == "https://x/r1.pdf"
    assert c["results"][0]["amounts"] == ["Q2 revenue: 4338 ₹ crore"] and c["results"][0]["open_questions"] == ["guidance for H2"]
    assert c["sentiment"]["band"] == "moderately_positive" and c["sentiment"]["confidence"] == 88 and c["sentiment"]["n"] == 2
    assert c["analysed"] == 4


def test_kinds():
    assert rs.kind_of({"exchange_category": "Investor Presentation", "event_type": "RESULTS"}) == "presentation"
    assert rs.kind_of({"exchange_category": "Outcome of Board Meeting", "event_type": "QUARTERLY RESULTS"}) == "results"
    assert rs.kind_of({"exchange_category": "Outcome of Board Meeting", "event_type": "DIVIDEND"}) == "board_outcome"
    assert rs.kind_of({"exchange_category": "Press Release", "event_type": "ORDER"}) == "press_release"
    assert rs.kind_of({"exchange_category": "Change in Director(s)", "event_type": "MANAGEMENT"}) == "other"


def test_no_results_analysis_means_no_sentiment():
    c = rs.split_commentary([], datetime(2026, 10, 26, 15, 0, tzinfo=timezone.utc), {})
    assert c["sentiment"] is None and c["results"] == [] and c["analysed"] == 0


def test_preview_lines_are_from_the_data_and_say_baseline_not_consensus():
    r = {"period_label": "Q2 FY27", "components": {"surprise": {"metrics": {
        "revenue": {"reliable": True, "expected": {"low": 3909, "mid": 4154, "high": 4810}},
        "pat": {"reliable": False, "note": "baseline too uncertain"}}}}}
    q = [{"period_end": "2026-09-30", "revenue_yoy_pct": 17.3, "pat_yoy_pct": 40.0, "ebitda_margin_pct": 27.0}]
    past = {"n": 10, "event_day_avg_pct": 0.77, "d1_avg_pct": -0.61, "w1_avg_pct": 1.0, "up_share_pct": 30.0}
    before = {"date": "2026-10-26", "state": "long_buildup", "text": "long build-up", "price_pct": 4.49, "oi_pct": 9.6}
    lines = rs.preview_lines(r, q, past, before)
    assert lines[0].startswith("Revenue baseline for Q2 FY27: ₹3,909–4,810 crore (mid ₹4,154 crore)") and "not analyst consensus" in lines[0]
    assert lines[1] == "Profit (PAT): no reliable baseline (baseline too uncertain)."
    assert "PAT +40.0 % YoY" in lines[2] and "up on 30 % of them" in lines[3] and "long build-up (spot +4.49 %, total OI +9.60 %)" in lines[4]
    text = " ".join(lines).lower()
    for w in ("buy", "sell", "recommend", "pick", "beat"):
        assert w not in text


def test_past_stats_and_quarters_table():
    p = rs.past_stats({"occurrences": [{"event_day_pct": 2.0, "d1_pct": 1.0, "w1_pct": 3.0}, {"event_day_pct": -1.0, "d1_pct": None, "w1_pct": 1.0}]})
    assert p == {"n": 2, "event_day_avg_pct": 0.5, "d1_avg_pct": 1.0, "w1_avg_pct": 2.0, "up_share_pct": 50.0}
    assert rs.past_stats({"occurrences": []}) is None
    fin = [{"period_end": f"{y}-{m}", "period_type": "quarterly", "revenue_from_ops_cr": rev, "ebitda_cr": rev / 4, "pat_cr": rev / 8}
           for y, m, rev in [("2025", "09-30", 100.0), ("2026", "06-30", 110.0), ("2026", "09-30", 120.0)]]
    t = rs.quarters_table(fin, date(2026, 9, 30), declared=True)
    assert t[0]["period_end"] == "2026-09-30" and t[0]["revenue_yoy_pct"] == 20.0 and t[0]["ebitda_margin_pct"] == 25.0
    assert rs.quarters_table(fin, date(2026, 9, 30), declared=False)[0]["period_end"] == "2026-06-30"


# ── the route ──────────────────────────────────────────────────────────────────────────────────────────────────

def client(monkeypatch, *, signed_in=True, body=None, stored=None):
    if signed_in:
        async def user(request: Request):
            return {"user_id": "u1"}
        monkeypatch.setattr(route, "get_current_user", user)

    async def build_day(day, now=None, live=True, db=None):
        return copy.deepcopy(body)

    async def get_day(d, db=None):
        return copy.deepcopy(stored)

    async def build_stock(row, day, db=None, now=None):
        return {"schema": rs.SCHEMA, "symbol": row["symbol"], "row": row}

    route._live.clear()
    monkeypatch.setattr(route.rw_build, "build_day", build_day)
    monkeypatch.setattr(route.store, "get_day", get_day)
    monkeypatch.setattr(route.rw_stock, "build_stock", build_stock)
    monkeypatch.setattr(route, "today_ist", lambda: DAY)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app)


WEEK = {"results": [{"symbol": "MANKIND", "status": "declared"}, {"symbol": "M&M", "status": "upcoming"}], "gaps": []}


def test_route_signed_out_is_401(monkeypatch):
    assert client(monkeypatch, signed_in=False, body=WEEK).get("/api/desk/results-week/stock/MANKIND").status_code == 401


@pytest.mark.parametrize("path", ["/api/desk/results-week/stock/bad%20sym", "/api/desk/results-week/stock/MANKIND?date=2026-13-01",
                                  "/api/desk/results-week/stock/MANKIND?date=2026-10-28"])
def test_route_bad_symbol_or_date_is_422(monkeypatch, path):
    assert client(monkeypatch, body=WEEK).get(path).status_code == 422


def test_route_answers_a_listed_stock_and_404s_another(monkeypatch):
    c = client(monkeypatch, body=WEEK)
    r = c.get("/api/desk/results-week/stock/mankind")
    assert r.status_code == 200 and r.json()["symbol"] == "MANKIND" and r.json()["schema"] == "results-stock-v1"
    assert c.get("/api/desk/results-week/stock/M%26M").status_code == 200           # & is a valid NSE symbol character
    nf = c.get("/api/desk/results-week/stock/INFY")
    assert nf.status_code == 404 and nf.json()["detail"]["code"] == "no_results_meeting"


def test_route_past_day_uses_the_stored_snapshot(monkeypatch):
    assert client(monkeypatch, body=WEEK).get("/api/desk/results-week/stock/MANKIND?date=2026-10-26").status_code == 404
    c = client(monkeypatch, body={}, stored=WEEK)
    assert c.get("/api/desk/results-week/stock/MANKIND?date=2026-10-26").status_code == 200


# ── expiry sessions and the first public filing (added after the staging dry run of 28 Oct) ───────────────────────

def test_a_session_straddling_an_expiry_has_no_state():
    bars = {d: (100.0, 1000.0) for d in SESS}
    by = {d.isoformat(): {"MOCK": bu(100, -6.08, 100.0, 8.24)} for d in SESS}
    _, win = tr.window(date(2026, 10, 28), None, SESS, date(2026, 10, 28))
    rows = {r["date"]: r for r in tr.session_rows(win, "MOCK", bars, {}, by, SESS, None, expiries=[date(2026, 10, 27)])}
    assert rows["2026-10-27"]["fut"]["state"] is None and rows["2026-10-27"]["fut"]["text"] == "expiry: OI not comparable"
    assert rows["2026-10-27"]["fut"]["expiry_day"] is True and rows["2026-10-28"]["fut"]["oi_comparable"] is False
    assert rows["2026-10-26"]["fut"]["state"] == "short_covering" and rows["2026-10-26"]["fut"]["oi_comparable"] is True


def test_the_first_public_results_filing_decides_the_reaction_session():
    from services.results_week import build
    ev = {"event_date": "2026-10-27", "filing": None,
          "metrics": [{"key": "pat", "filed": {"broadcast_at": "2026-10-27T10:44:04+00:00"}}]}         # staging: BAJAJ-AUTO, 16:14 IST
    exch = [datetime(2026, 10, 27, 9, 51, 27, tzinfo=timezone.utc),                                     # 15:21 IST outcome filing
            datetime(2026, 10, 20, 5, 0, tzinfo=timezone.utc)]                                          # an older filing: ignored
    t = build.filed_at_of(ev, exch)
    assert t == datetime(2026, 10, 27, 9, 51, 27, tzinfo=timezone.utc)
    from services.results_week import scoring as sc
    assert sc.first_session(t, SESS) == date(2026, 10, 27)                       # before the close: reacts the same day
    assert sc.first_session(build.filed_at_of(ev), SESS) == date(2026, 10, 28)    # figures time alone: the next day
