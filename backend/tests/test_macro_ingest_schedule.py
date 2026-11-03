"""The macro regime feed's schedule and source (fix of 2026-10-27; test cases in
test_reports/macro_ingest_fix_TESTCASES.md, MI-1..MI-9).

The defect: `CronTrigger(hour=18, minute=35)` had no timezone, so in the UTC backend container the job ran at 00:05 IST,
when yfinance often left out the session that had just closed; macro_daily lagged and the risk service's regime read
three sessions old. The fix runs it at 19:30 IST (+ a 21:30 retry) and reads Nifty 50 and India VIX from the warehouse
first, dated by the warehouse session.

MOCK — not real data: every price below is made up; no network, no database.
"""
from __future__ import annotations

import asyncio
import inspect
from datetime import date

import pytest

from services import macro_engine, macro_ingester as mi
from services.copilot_tools import daas_client


# ── MI-1..MI-3: the triggers name Asia/Kolkata ─────────────────────────────────────────────
def _registered(job_ids):
    from services import mf_scheduler as sched

    async def go():
        sched.start()
        try:
            out = {}
            for jid in job_ids:
                job = sched._scheduler.get_job(jid)
                out[jid] = None if job is None else (job.func, str(job.trigger.timezone), job.max_instances,
                                                     job.next_run_time.strftime("%H:%M %z"), job.next_run_time.weekday())
            ids = [j.id for j in sched._scheduler.get_jobs()]
            return out, ids, sched
        finally:
            sched.stop()
            await asyncio.sleep(0.05)
    return asyncio.run(go())


def test_mi1_mi2_macro_job_runs_weekdays_at_1930_ist_with_a_2130_retry():
    out, ids, sched = _registered(["macro_intelligence_daily", "macro_intelligence_retry"])
    for jid, hhmm in (("macro_intelligence_daily", "19:30 +0530"), ("macro_intelligence_retry", "21:30 +0530")):
        func, tz, max_instances, next_run, weekday = out[jid]
        assert func is sched._macro_intelligence_job, jid
        assert tz == "Asia/Kolkata" and next_run == hhmm, (jid, tz, next_run)   # IST whatever the container zone
        assert weekday < 5, jid                                                  # Mon–Fri only
        assert max_instances == 1, jid
        assert ids.count(jid) == 1, jid


def test_mi3_benchmark_job_keeps_1830_but_in_ist():
    out, _, sched = _registered(["benchmark_index_daily"])
    func, tz, _, next_run, _ = out["benchmark_index_daily"]
    assert func is sched._benchmark_refresh_job
    assert tz == "Asia/Kolkata" and next_run == "18:30 +0530"


# ── MI-4..MI-8: ingest_today reads the warehouse first ────────────────────────────────────
class _World:
    def __init__(self, monkeypatch, warehouse, yf):
        self.yf_calls, self.upserts, self.wh_calls = [], [], []

        async def fake_history(index_name, start=None, end=None, **kw):
            self.wh_calls.append((index_name, start, end))
            rows = warehouse(index_name) if callable(warehouse) else warehouse.get(index_name, [])
            if isinstance(rows, Exception):
                raise rows
            return [r for r in rows if end is None or r["as_of_date"] <= end]

        def fake_yf(chain):
            self.yf_calls.append(tuple(chain))
            return yf.get(chain[0], (None, None, None))

        async def no_av(*a, **k):
            return None, None, None

        async def no_prev(metric, today):
            return None

        async def capture(d, fields):
            self.upserts.append((d, dict(fields)))

        async def no_schema():
            return None

        monkeypatch.setattr(daas_client, "get_index_eod_history", fake_history)
        monkeypatch.setattr(mi, "_fetch_latest_close", fake_yf)
        monkeypatch.setattr(mi, "_fetch_alpha_vantage", no_av)
        monkeypatch.setattr(mi, "_previous_value", no_prev)
        monkeypatch.setattr(mi, "_upsert", capture)
        monkeypatch.setattr(macro_engine, "ensure_schema", no_schema)


def _rows(*pairs):
    return [{"as_of_date": d, "close_price": c} for d, c in pairs]


WAREHOUSE = {"Nifty 50": _rows(("2026-10-23", 22600.0), ("2026-10-26", 22753.2)),       # MOCK
             "India VIX": _rows(("2026-10-23", 16.86), ("2026-10-26", 17.16))}          # MOCK
YF = {"^NSEI": (22749.75, "^NSEI", date(2026, 10, 27)), "^INDIAVIX": (16.40, "^INDIAVIX", date(2026, 10, 27)),  # MOCK
      "^GSPC": (5800.0, "^GSPC", date(2026, 10, 24))}


def test_mi4_the_warehouse_session_dates_the_row_and_yfinance_is_not_asked_for_nifty_or_vix(monkeypatch):
    w = _World(monkeypatch, WAREHOUSE, YF)
    out = asyncio.run(mi.ingest_today(target_date=date(2026, 10, 26)))
    assert out["as_of_date"] == "2026-10-26" and out["market_open_today"] is True
    (d, fields), = w.upserts
    assert d == date(2026, 10, 26)
    assert (fields["nifty"], fields["source_nifty"], fields["confidence_nifty"]) == (22753.2, mi.WAREHOUSE_SOURCE, 1.0)
    assert (fields["india_vix"], fields["source_india_vix"]) == (17.16, mi.WAREHOUSE_SOURCE)
    assert ("^NSEI",) not in w.yf_calls and ("^INDIAVIX",) not in w.yf_calls
    assert fields["sp500"] == 5800.0                                  # the global series still come from yfinance


def test_mi5_a_failed_or_empty_warehouse_falls_back_to_yfinance(monkeypatch):
    for warehouse in ({"Nifty 50": [], "India VIX": []}, lambda name: RuntimeError("daas down")):
        w = _World(monkeypatch, warehouse, YF)
        out = asyncio.run(mi.ingest_today(target_date=date(2026, 10, 27)))
        (d, fields), = w.upserts
        assert d == date(2026, 10, 27) and out["as_of_date"] == "2026-10-27"
        assert (fields["nifty"], fields["source_nifty"]) == (22749.75, "^NSEI")
        assert (fields["india_vix"], fields["source_india_vix"]) == (16.40, "^INDIAVIX")


def test_mi6_a_warehouse_a_session_behind_dates_the_row_by_that_session_not_by_today(monkeypatch):
    w = _World(monkeypatch, WAREHOUSE, YF)                         # the warehouse has no 27 Oct yet
    out = asyncio.run(mi.ingest_today(target_date=date(2026, 10, 27)))
    (d, fields), = w.upserts
    assert d == date(2026, 10, 26) and out["as_of_date"] == "2026-10-26" and out["market_open_today"] is False
    assert fields["nifty"] == 22753.2


def test_mi7_a_past_target_date_gets_that_session_from_the_warehouse(monkeypatch):
    w = _World(monkeypatch, WAREHOUSE, YF)
    asyncio.run(mi.ingest_today(target_date=date(2026, 10, 23)))
    (d, fields), = w.upserts
    assert d == date(2026, 10, 23) and (fields["nifty"], fields["india_vix"]) == (22600.0, 16.86)
    assert all(end == "2026-10-23" for _, _, end in w.wh_calls)


def test_mi8_a_vix_from_another_session_is_not_stored_against_the_row(monkeypatch):
    warehouse = {"Nifty 50": WAREHOUSE["Nifty 50"], "India VIX": []}          # VIX falls back to yfinance (27 Oct bar)
    w = _World(monkeypatch, warehouse, YF)
    out = asyncio.run(mi.ingest_today(target_date=date(2026, 10, 26)))
    (d, fields), = w.upserts
    assert d == date(2026, 10, 26) and "india_vix" not in fields
    assert out["metrics"]["india_vix"]["reason"] == "session_mismatch"


# ── MI-9: the fallback log no longer calls a lag a holiday ────────────────────────────────
def test_mi9_latest_state_log_says_not_ingested_yet_not_holiday():
    src = inspect.getsource(macro_engine.latest_state)
    assert "likely NSE holiday" not in src
    assert "not ingested yet, or not a session" in src
