"""The AI scanner's bar store: a file is never stamped with a date it does not carry, a non-session date is never
ingested or scored, missed sessions are back-filled once, features never straddle a split, and the repair tool plans,
applies (once), and restores exactly. Test cases: test_reports/scanner_bar_integrity_TESTCASES.md (TC-1..TC-25).

No database, no NSE, no data platform: every outside call is a stub or an in-memory fake. The bhavcopy fixtures are
real rows (header and values exactly as NSE serves them) from sec_bhavdata_full_02102026.csv, which NSE answered for
the 2 Oct 2026 holiday with 1 Oct's file, and sec_bhavdata_full_21102026.csv.
"""
from __future__ import annotations

import asyncio
import json
import math
from datetime import date, timedelta

import pytest

from scripts import run_positional_engine as runner
from services.positional_engine import (
    ENGINE_VERSION,
    bar_quality,
    bar_repair,
    bhavcopy_ingester as bi,
    feature_calculator as fc,
    ohlcv_store,
    pipeline,
    price_adjustment as pa,
    session_calendar as cal,
)

HEADER = ("SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE,"
          " TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER\n")
FILE_01_OCT = HEADER + (
    "INFY, EQ, 01-Oct-2026, 994.10, 1010.00, 1035.00, 999.15, 1035.00, 1035.00, 1016.03, 15166446, 154095.41, 227162, 7881166, 51.96\n"
    "KOTAKBANK, EQ, 01-Oct-2026, 417.00, 426.00, 435.60, 416.05, 418.35, 418.35, 426.86, 76637247, 327133.13, 358247, 44580122, 58.17\n"
    "AAKAAR, SM, 01-Oct-2026, 65.95, 65.90, 67.00, 65.00, 65.00, 65.00, 65.97, 4800, 3.17, 3, 4800, 100.00\n"
    "3IINFOLTD, BE, 01-Oct-2026, 22.52, 22.52, 22.91, 22.12, 22.67, 22.45, 22.47, 285733, 64.22, 695, -, -\n"
)
FILE_21_OCT = HEADER + (
    "INFY, EQ, 21-Oct-2026, 1130.70, 1154.85, 1170.90, 1147.95, 1168.00, 1168.00, 1162.71, 18597997, 216241.57, 327429, 9335091, 50.19\n"
    "KOTAKBANK, EQ, 21-Oct-2026, 442.30, 444.45, 446.85, 434.50, 437.80, 437.80, 438.28, 11861936, 51988.50, 174162, 7952885, 67.05\n"
)
OCT01, OCT02, OCT21 = date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 21)
HOLIDAYS_2026 = {date(2026, 10, 2): "Mahatma Gandhi Jayanti", date(2026, 10, 20): "Dussehra"}


def run(coro):
    return asyncio.run(coro)


async def a_session(d):
    return cal.classify(d, HOLIDAYS_2026)


@pytest.fixture
def upserts(monkeypatch):
    seen: list = []

    async def upsert(bars):
        seen.append(list(bars))
        return len(seen[-1])

    monkeypatch.setattr(ohlcv_store, "upsert_bars", upsert)
    return seen


# ── TC-1..TC-6: the ingester (gate 5) ────────────────────────────────────
def test_tc1_holiday_url_answered_with_previous_session_is_refused(upserts):
    with pytest.raises(bi.BhavcopyDateMismatch) as e:
        bi.parse_bhavcopy_csv(FILE_01_OCT, OCT02)
    assert e.value.found == {OCT01} and "2026-10-01" in str(e.value)
    # even with a calendar that (wrongly) calls 2 Oct a session, nothing is written
    res = run(bi.ingest(OCT02, session_check=lambda d: _true(d), fetch=lambda url: FILE_01_OCT))
    assert res["status"] == "date_mismatch" and res["rows_written"] == 0 and res["file_dates"] == ["2026-10-01"]
    assert upserts == []


async def _true(d):
    return True, "test: treated as a session"


def test_tc2_matching_file_is_written_with_its_own_trade_date(upserts):
    bars = bi.parse_bhavcopy_csv(FILE_21_OCT, OCT21)
    assert [(b["nse_symbol"], b["bar_date"], b["close"]) for b in bars] == [
        ("INFY", OCT21, 1168.0), ("KOTAKBANK", OCT21, 437.8)]
    urls: list = []
    res = run(bi.ingest(OCT21, session_check=a_session, fetch=lambda url: urls.append(url) or FILE_21_OCT))
    assert res == {"date": "2026-10-21", "rows_written": 2, "status": "written"}
    assert urls == ["https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_21102026.csv"]
    assert [b["bar_date"] for b in upserts[0]] == [OCT21, OCT21]


@pytest.mark.parametrize("blob", [
    FILE_21_OCT + "TCS, EQ, 20-Oct-2026, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1\n",                 # mixed dates
    FILE_21_OCT.replace("DATE1", "TRADE_DT"),                                                   # no DATE1 column
    FILE_21_OCT.replace(" 21-Oct-2026,", " ,", 1),                                               # one blank DATE1
])
def test_tc3_mixed_missing_or_blank_trade_date_is_refused(upserts, blob):
    with pytest.raises(bi.BhavcopyDateMismatch):
        bi.parse_bhavcopy_csv(blob, OCT21)
    res = run(bi.ingest(OCT21, session_check=a_session, fetch=lambda url: blob))
    assert res["status"] == "date_mismatch" and upserts == []


def test_tc4_holiday_is_refused_before_nse_is_asked(upserts):
    asked: list = []
    res = run(bi.ingest(OCT02, session_check=a_session, fetch=lambda url: asked.append(url)))
    assert res["status"] == "not_a_session" and res["reason"] == "NSE holiday: Mahatma Gandhi Jayanti"
    assert asked == [] and upserts == []


def test_tc5_calendar_unavailable_refuses_before_nse_is_asked(upserts):
    async def broken(d):
        raise cal.CalendarUnavailable("the NSE holiday list (segment CM) has no rows for 2027")
    asked: list = []
    res = run(bi.ingest(date(2027, 1, 4), session_check=broken, fetch=lambda url: asked.append(url)))
    assert res["status"] == "calendar_unavailable" and "2027" in res["reason"]
    assert asked == [] and upserts == []


def test_tc6_no_file_writes_nothing_and_the_count_api_says_zero(upserts, monkeypatch):
    res = run(bi.ingest(OCT21, session_check=a_session, fetch=lambda url: None))
    assert res["status"] == "not_published" and upserts == []

    async def refused(d, **kw):
        return {"date": d.isoformat(), "status": "date_mismatch", "rows_written": 0}
    monkeypatch.setattr(bi, "ingest", refused)
    assert run(bi.ingest_for_date(OCT02)) == 0


# ── TC-7, TC-8: the calendar ─────────────────────────────────────────────
def test_tc7_classify():
    assert cal.classify(date(2026, 10, 3), HOLIDAYS_2026) == (False, "weekend")
    assert cal.classify(OCT02, HOLIDAYS_2026) == (False, "NSE holiday: Mahatma Gandhi Jayanti")
    assert cal.classify(OCT21, HOLIDAYS_2026)[0] is True


@pytest.mark.parametrize("status, body", [(200, {"data": []}), (503, None), (200, {"detail": "x"})])
def test_tc8_empty_or_unreadable_holiday_list_is_calendar_unavailable(monkeypatch, status, body):
    from services.copilot_tools import daas_client

    async def get_raw(path, params, timeout=10.0):
        return status, body
    monkeypatch.setattr(daas_client, "get_raw", get_raw)
    cal._holiday_cache.clear()
    with pytest.raises(cal.CalendarUnavailable):
        run(cal.check_session(date(2027, 1, 4)))


def test_tc8b_holiday_list_read_once_per_year(monkeypatch):
    from services.copilot_tools import daas_client
    calls: list = []

    async def get_raw(path, params, timeout=10.0):
        calls.append(params)
        return 200, {"data": [{"holiday_date": "2026-10-02", "description": "Mahatma Gandhi Jayanti"}]}
    monkeypatch.setattr(daas_client, "get_raw", get_raw)
    cal._holiday_cache.clear()
    assert run(cal.check_session(OCT02)) == (False, "NSE holiday: Mahatma Gandhi Jayanti")
    assert run(cal.check_session(OCT21))[0] is True
    assert calls == [{"segment": "CM", "from": "2026-01-01", "to": "2026-12-31", "limit": 1000}]
    cal._holiday_cache.clear()


# ── TC-9, TC-10: the runner refuses before anything else ─────────────────
@pytest.fixture
def runner_calls(monkeypatch):
    from services.positional_engine import scan_config
    seen = {"ingest": 0, "pipeline": 0, "scans": 0, "signals_on": 0}

    async def ingest(d):
        seen["ingest"] += 1
        return {"date": d.isoformat(), "status": "written", "rows_written": 1}

    async def run_for_date(d):
        seen["pipeline"] += 1
        return {"ok": True}

    async def load(db):
        seen["scans"] += 1
        return []

    async def signals_on(d):
        seen["signals_on"] += 1
        return 0

    monkeypatch.setattr(bi, "ingest", ingest)
    monkeypatch.setattr(pipeline, "run_for_date", run_for_date)
    monkeypatch.setattr(scan_config, "load", load)
    monkeypatch.setattr(runner, "signals_on", signals_on)
    return seen


def test_tc9_runner_refuses_a_holiday(monkeypatch, runner_calls):
    monkeypatch.setattr(cal, "check_session", a_session)
    out = run(runner.run(OCT02, fetch_bhavcopy=True, fetch_scans=True, require_bars=True, skip_if_done=True))
    assert out["skipped"] == "not_a_session" and out["ok"] is False and "Gandhi" in out["reason"]
    assert runner_calls == {"ingest": 0, "pipeline": 0, "scans": 0, "signals_on": 0}


def test_tc10_runner_refuses_when_the_calendar_is_unavailable(monkeypatch, runner_calls):
    async def broken(d):
        raise cal.CalendarUnavailable("holiday list: HTTP 503")
    monkeypatch.setattr(cal, "check_session", broken)
    out = run(runner.run(OCT21, fetch_bhavcopy=True, fetch_scans=True))
    assert out["skipped"] == "calendar_unavailable"
    assert runner_calls == {"ingest": 0, "pipeline": 0, "scans": 0, "signals_on": 0}


@pytest.mark.parametrize("skipped, code", [("not_a_session", 3), ("calendar_unavailable", 4), ("dirty_bars", 5)])
def test_tc9_tc10_exit_codes(monkeypatch, skipped, code):
    async def fake_run(d, **kw):
        return {"date": str(d), "steps": {}, "ok": False, "skipped": skipped}
    monkeypatch.setattr(runner, "run", fake_run)
    monkeypatch.setattr("sys.argv", ["run_positional_engine", "--date", "2026-10-02"])
    assert runner.main() == code


def test_require_clean_refuses_to_score_a_dirty_store(monkeypatch, runner_calls):
    monkeypatch.setattr(cal, "check_session", a_session)

    async def quality(d):
        return {"ok": True, "clean": False, "problems": ["copied_sessions=14"], "report": {}}
    monkeypatch.setattr(runner, "quality", quality)
    out = run(runner.run(OCT21, fetch_bhavcopy=False, fetch_scans=True, require_clean=True))
    assert out["skipped"] == "dirty_bars" and runner_calls["pipeline"] == 0 and runner_calls["scans"] == 0


def test_quality_check_reports_but_does_not_block_without_require_clean(monkeypatch, runner_calls):
    monkeypatch.setattr(cal, "check_session", a_session)

    async def quality(d):
        return {"ok": True, "clean": False, "problems": ["copied_sessions=14"], "report": {}}
    monkeypatch.setattr(runner, "quality", quality)
    out = run(runner.run(OCT21, fetch_bhavcopy=False, fetch_scans=True, quality_check=True))
    assert "skipped" not in out and out["steps"]["quality"]["problems"] == ["copied_sessions=14"]
    assert runner_calls["pipeline"] == 1


# ── TC-11: the pipeline refuses a non-session date ───────────────────────
def test_tc11_pipeline_refuses_a_holiday(monkeypatch):
    from services import pg_client

    async def pool():
        return object()

    async def must_not_score(*a, **kw):
        raise AssertionError("scored a holiday")
    monkeypatch.setattr(pg_client, "get_pool", pool)
    monkeypatch.setattr(cal, "check_session", a_session)
    monkeypatch.setattr(pipeline, "score_universe", must_not_score)
    out = run(pipeline.run_for_date(OCT02))
    assert out["ok"] is False and out["error"] == "not_a_session" and "Gandhi" in out["reason"]


# ── TC-12..TC-14: back-fill ──────────────────────────────────────────────
@pytest.fixture
def bf_world(monkeypatch):
    world = {"store": {date(2026, 10, 19), date(2026, 10, 23)},
             "warehouse": {date(2026, 10, 19), OCT21, date(2026, 10, 22), date(2026, 10, 23)},
             "ingested": [], "wh_reads": 0}

    async def sessions(start, end, extra=()):
        world["wh_reads"] += 1
        return {d for d in world["warehouse"] if start <= d <= end}

    async def dates_between(start, end):
        return {d for d in world["store"] if start <= d <= end}

    async def ingest(d):
        world["ingested"].append(d)
        world["store"].add(d)
        return {"date": d.isoformat(), "status": "written", "rows_written": 2916}

    monkeypatch.setattr(cal, "warehouse_sessions", sessions)
    monkeypatch.setattr(ohlcv_store, "dates_between", dates_between)
    monkeypatch.setattr(bi, "ingest", ingest)
    return world


def test_tc12_backfill_ingests_the_missing_sessions(bf_world):
    out = run(bi.backfill_missing(date(2026, 10, 13), date(2026, 10, 26)))
    assert out["ok"] is True and out["missing"] == ["2026-10-21", "2026-10-22"]
    assert bf_world["ingested"] == [OCT21, date(2026, 10, 22)]


def test_tc13_backfill_twice_is_a_no_op(bf_world):
    run(bi.backfill_missing(date(2026, 10, 13), date(2026, 10, 26)))
    out = run(bi.backfill_missing(date(2026, 10, 13), date(2026, 10, 26)))
    assert out["ok"] is True and out["missing"] == [] and out["results"] == []
    assert bf_world["ingested"] == [OCT21, date(2026, 10, 22)]


def test_tc14_backfill_without_warehouse_sessions_ingests_nothing(bf_world, monkeypatch):
    async def broken(start, end, extra=()):
        raise cal.CalendarUnavailable("/prices/eod: HTTP 502")
    monkeypatch.setattr(cal, "warehouse_sessions", broken)
    out = run(bi.backfill_missing(date(2026, 10, 13), date(2026, 10, 26)))
    assert out["ok"] is False and out["error"] == "warehouse_sessions_unavailable" and bf_world["ingested"] == []


# ── TC-15..TC-19: adjusted prices (gate 6) ───────────────────────────────
EX_DATE = date(2026, 1, 14)
N_BARS = 260
SPLIT_AT = 200          # bar index of the ex-date: 60 post-split bars, as on the KOTAKBANK window of mid-April


def _weekdays_around(anchor, before, after):
    """`before` weekdays ending the day before `anchor`, `anchor`, then `after` weekdays: ascending."""
    out, d = [], anchor
    while len(out) < before:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    out = out[::-1] + [anchor]
    d = anchor
    while len(out) < before + 1 + after:
        d += timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return out


def kotak_like():
    """Raw bars of a stock that splits 5:1 at bar SPLIT_AT (2133.30 -> 421.00 on the ex-date, as KOTAKBANK did),
    the same stock on one continuous (post-split) scale, and the warehouse factors (0.2 before the ex-date)."""
    days = _weekdays_around(EX_DATE, SPLIT_AT, N_BARS - SPLIT_AT - 1)
    assert days[SPLIT_AT - 1] == date(2026, 1, 13) and len(days) == N_BARS
    continuous, raw, factors = [], [], {}
    for i, d in enumerate(days):
        c = 421.0 * (1 + 0.15 * math.sin(i / 9.0)) * (1 + 0.0004 * (i - SPLIT_AT))
        if i == SPLIT_AT - 1:
            c = 2133.30 / 5
        if i == SPLIT_AT:
            c = 421.0
        bar = {"bar_date": d, "open": c * 0.995, "high": c * 1.01, "low": c * 0.985, "close": c,
               "volume": 1_000_000 + 7_920 * (i % 13), "delivery_pct": 55.0}
        continuous.append(bar)
        f = 0.2 if d < EX_DATE else 1.0
        factors[d] = f
        raw.append({**bar, **{k: bar[k] / f for k in ("open", "high", "low", "close")},
                    "volume": int(round(bar["volume"] * f))})
    return raw, continuous, factors


def test_tc15_kotak_split_does_not_show_in_adjusted_features():
    raw, continuous, factors = kotak_like()
    assert raw[SPLIT_AT - 1]["close"] == pytest.approx(2133.30) and raw[SPLIT_AT]["close"] == 421.0
    assert pa.adjustment_break(raw) == SPLIT_AT                       # the raw series shows the break

    adj, info = pa.adjust_bars(raw, factors)
    assert info == {"price_basis": "warehouse_adjusted", "factor_steps": 1, "break_truncated_at": None,
                    "bars_dropped": 0}
    assert len(adj) == N_BARS and pa.adjustment_break(adj) is None
    assert adj[SPLIT_AT - 1]["close"] == pytest.approx(426.66)       # the warehouse's adj_close for 2026-01-13
    f_adj, f_cont, f_raw = fc.compute_features(adj), fc.compute_features(continuous), fc.compute_features(raw)
    for k in ("sma_20", "sma_50", "sma_200", "ema_20", "atr_14", "return_20d_pct", "return_60d_pct",
              "swing_low_20", "swing_high_20", "high_52w", "low_52w", "volume_z_20", "rsi_14"):
        assert f_adj[k] == pytest.approx(f_cont[k], rel=1e-6, abs=1e-6), k
    assert f_raw["sma_200"] > 1.5 * f_adj["sma_200"]                  # what the scanner computed before
    assert f_raw["high_52w"] > 4 * f_adj["high_52w"]


def test_tc15b_ex_date_inside_the_20_bar_window():
    """Scored ten sessions after the ex-date: the 20-session return and swing levels straddle the split."""
    raw, continuous, factors = kotak_like()
    raw, continuous = raw[:SPLIT_AT + 10], continuous[:SPLIT_AT + 10]
    adj, _ = pa.adjust_bars(raw, {d: f for d, f in factors.items() if d <= raw[-1]["bar_date"]})
    f_adj, f_cont, f_raw = fc.compute_features(adj), fc.compute_features(continuous), fc.compute_features(raw)
    assert f_adj["return_20d_pct"] == pytest.approx(f_cont["return_20d_pct"])
    assert f_raw["return_20d_pct"] < -70                               # the phantom crash a raw window reports
    assert f_adj["atr_14"] == pytest.approx(f_cont["atr_14"]) and f_raw["atr_14"] > 3 * f_adj["atr_14"]


def test_tc16_no_factors_truncates_at_the_break():
    raw, _continuous, _ = kotak_like()
    adj, info = pa.adjust_bars(raw, None)
    assert info["price_basis"] == "raw_no_factors" and info["break_truncated_at"] == "2026-01-14"
    assert info["bars_dropped"] == SPLIT_AT and len(adj) == N_BARS - SPLIT_AT and adj[0]["close"] == 421.0


def test_tc17_ex_date_on_the_run_date_is_truncated_and_not_scored():
    raw, _continuous, factors = kotak_like()
    raw = raw[:SPLIT_AT + 1]                                          # the run date is the ex-date
    known = {d: (0.2 if d < EX_DATE else 1.0) for d in factors if d < EX_DATE}   # price_adjuster has not run yet
    adj, info = pa.adjust_bars(raw, known)
    assert info["break_truncated_at"] == "2026-01-14" and len(adj) == 1 < pipeline.MIN_BARS


def test_tc18_factor_one_leaves_bars_untouched():
    raw, _c, _f = kotak_like()
    plain = raw[SPLIT_AT:]
    adj, info = pa.adjust_bars(plain, {b["bar_date"]: 1.0 for b in plain})
    assert adj == plain and info["factor_steps"] == 0 and info["price_basis"] == "warehouse_adjusted"


def test_tc19_factor_read_failure_refuses_the_run(monkeypatch):
    async def universe(d):
        return ["KOTAKBANK"]

    async def broken(symbols, start, end):
        raise pa.FactorsUnavailable("adjusted prices for 1 symbols: DAAS connectivity error")
    monkeypatch.setattr(pipeline, "universe_for", universe)
    monkeypatch.setattr(pa, "load_factors", broken)
    summary, rows = run(pipeline.score_universe(OCT21))
    assert summary["ok"] is False and summary["error"] == "adjustment_factors_unavailable" and rows == []


def test_score_universe_scores_adjusted_bars_and_records_the_basis(monkeypatch):
    raw, _c, factors = kotak_like()

    async def universe(d):
        return ["KOTAKBANK"]

    async def load(sym, end, n):
        return raw

    async def nothing(*a, **kw):
        return None

    async def no_hits(d, s):
        return []
    monkeypatch.setattr(pipeline, "universe_for", universe)
    monkeypatch.setattr(pipeline, "_sector_key_for", nothing)
    monkeypatch.setattr(pipeline.sector_strength, "load_bench_return", nothing)
    monkeypatch.setattr(pipeline.chartink_loader, "get_scans_for", no_hits)
    from services import macro_engine
    monkeypatch.setattr(macro_engine, "latest_state", nothing)
    summary, rows = run(pipeline.score_universe(raw[-1]["bar_date"], load_bars=load, factors={"KOTAKBANK": factors}))
    assert summary["ok"] and summary["scored"] == 1 and summary["price_basis"]["warehouse_adjusted"] == 1
    assert rows[0]["price_adjustment"]["factor_steps"] == 1
    assert rows[0]["features"]["sma_200"] < 600                        # one scale: about 421, not about 1800


# ── TC-20: data quality ──────────────────────────────────────────────────
def test_tc20_quality_checks_count_each_problem():
    d1, d2, hol, d4 = date(2026, 9, 30), OCT01, OCT02, date(2026, 10, 5)
    day1 = {"AAA": (10, 11, 9, 10.5, 100), "BBB": (20, 21, 19, 20.5, 200), "OLD": (5, 5, 5, 5, 10)}
    day2 = {"AAA": (10.5, 12, 10, 11.0, 150), "BBB": (20.5, 22, 20, 21.0, 0), "OLD": (5, 5, 5, 5, 10)}
    q = bar_quality.BarQuality(sessions={d1, d2, date(2026, 10, 3), d4})   # the store lacks a session on 10-03
    q.add_date(d1, day1)
    q.add_date(d2, day2)
    q.add_date(hol, dict(day2))                                         # a holiday copying 1 Oct
    q.add_date(d4, {"AAA": (11, 10, 12, 11.5, 90), "BBB": (21, 22, 20, 21.5, 120)})   # high < low; OLD stale
    r = q.report()
    assert r["missing_sessions"] == {"count": 1, "dates": ["2026-10-03"]}
    assert r["extra_dates"] == {"count": 1, "dates": ["2026-10-02"]}
    assert r["copied_sessions"]["count"] == 1 and r["copied_sessions"]["dates"][0]["date"] == "2026-10-02"
    assert r["duplicate_bars"]["count"] == 4 and r["duplicate_bars"]["outside_copied_sessions"] == 1
    assert r["duplicate_bars"]["sample"] == ["OLD 2026-10-01"]
    assert r["invalid_ohlc"]["count"] == 1 and r["invalid_ohlc"]["by_rule"] == {"high_below_low": 1}
    assert r["zero_volume"]["count"] == 2                               # BBB on 10-01 and on its copy
    assert r["stale_symbols"]["count"] == 1 and r["stale_symbols"]["sample"][0]["symbol"] == "OLD"
    assert bar_quality.is_clean(r) == (False, ["missing_sessions=1", "extra_dates=1", "copied_sessions=1",
                                               "invalid_ohlc=1"])


# ── TC-21..TC-25: the repair tool on an in-memory store ──────────────────
class FakeStore:
    """stock_ohlcv + derived tables as row dicts; counts every write."""

    def __init__(self, ohlcv, derived):
        self.t = {"stock_ohlcv": ohlcv, **derived}
        self.writes = 0
        self.ingested: list = []

    def _col(self, table):
        return dict(bar_repair.TABLES)[table]

    async def bounds(self):
        ds = [r["bar_date"] for r in self.t["stock_ohlcv"]]
        return min(ds), max(ds)

    async def dates(self, start, end):
        return sorted({r["bar_date"] for r in self.t["stock_ohlcv"] if start <= r["bar_date"] <= end})

    async def bars_on(self, d):
        return {r["nse_symbol"]: (r["o"], r["h"], r["l"], r["c"], r["v"]) for r in self.t["stock_ohlcv"]
                if r["bar_date"] == d}

    async def derived_counts(self):
        out = {}
        for table, col in bar_repair.DERIVED:
            per = {}
            for r in self.t[table]:
                e = per.setdefault(r[col], {"rows": 0, "versions": set()})
                e["rows"] += 1
                e["versions"].add(r["engine_version"])
            out[table] = {d: {"rows": e["rows"], "versions": sorted(e["versions"])} for d, e in per.items()}
        return out

    async def rows(self, table, col, dates):
        ds = set(dates)
        return [json.loads(json.dumps(r, default=str)) for r in self.t[table] if r[col] in ds]

    async def delete_dates(self, dates):
        ds, out = set(dates), {}
        for table, col in bar_repair.TABLES:
            keep = [r for r in self.t[table] if r[col] not in ds]
            out[table] = len(self.t[table]) - len(keep)
            self.writes += out[table]
            self.t[table] = keep
        return out

    async def replace_scored(self, d, scored):
        for table, col in bar_repair.DERIVED:
            self.t[table] = [r for r in self.t[table] if r[col] != d]
        for s in scored:
            self.t["stock_technical_features"].append({"nse_symbol": s["nse_symbol"], "as_of_date": d,
                                                       "engine_version": ENGINE_VERSION})
            if s["actionable"]:
                self.t["positional_signals"].append({"nse_symbol": s["nse_symbol"], "signal_date": d,
                                                     "engine_version": ENGINE_VERSION})
        self.writes += 1

    async def restore(self, snap):
        back = {date.fromisoformat(d) for d in snap["backfill_dates"]}
        self.t["stock_ohlcv"] = [r for r in self.t["stock_ohlcv"] if r["bar_date"] not in back]
        for table, col in bar_repair.TABLES:
            ds = {date.fromisoformat(d) for d in snap["dates"][table]}
            self.t[table] = [r for r in self.t[table] if r[col] not in ds]
            for r in snap["rows"][table]:
                self.t[table].append({k: (date.fromisoformat(v) if k == col else v) for k, v in r.items()})
        self.writes += 1
        return {}

    def state(self):
        return {t: sorted(json.dumps(r, sort_keys=True, default=str) for r in rows) for t, rows in self.t.items()}


class FakeWarehouse:
    def __init__(self, sessions, rows):
        self.s, self.r = sessions, rows

    async def sessions(self, start, end, extra=()):
        return {d for d in self.s if start <= d <= end}

    async def rows(self, d):
        return self.r[d]


S1, S2, S3, HOL, PART, MISS = (date(2026, 9, 29), date(2026, 9, 30), OCT01, OCT02, date(2026, 10, 3), date(2026, 10, 5))
LAST = date(2026, 10, 6)


def _bar(sym, d, c):
    return {"nse_symbol": sym, "bar_date": d, "o": c, "h": c + 1, "l": c - 1, "c": c, "v": 1000}


def world():
    ohlcv = []
    for d, ca, cb in ((S1, 10, 20), (S2, 11, 21), (S3, 12, 22), (LAST, 13, 23)):
        ohlcv += [_bar("AAA", d, ca), _bar("BBB", d, cb)]
    ohlcv += [_bar("AAA", HOL, 12), _bar("BBB", HOL, 22)]                 # 2 Oct: a 100% copy of 1 Oct
    ohlcv += [_bar("AAA", PART, 12), _bar("BBB", PART, 99)]               # 3 Oct (Saturday): half a copy
    derived = {"stock_technical_features": [], "positional_signals": []}
    for d in (S3, HOL, LAST):
        for s in ("AAA", "BBB"):
            derived["stock_technical_features"].append({"nse_symbol": s, "as_of_date": d, "engine_version": "positional.v1.0"})
        derived["positional_signals"].append({"nse_symbol": "AAA", "signal_date": d, "engine_version": "positional.v1.0"})
    store = FakeStore(ohlcv, derived)
    wh = FakeWarehouse({S1, S2, S3, MISS, LAST}, {MISS: 2916})
    return store, wh


def fake_ingest(store):
    async def ingest(d):
        store.ingested.append(d)
        store.t["stock_ohlcv"] += [_bar("AAA", d, 12.5), _bar("BBB", d, 22.5)]
        store.writes += 1
        return {"date": d.isoformat(), "status": "written", "rows_written": 2}
    return ingest


async def fake_score(d):
    return {"ok": True}, [{"nse_symbol": "AAA", "actionable": True}, {"nse_symbol": "BBB", "actionable": False}]


def test_tc21_dry_run_plan_reports_exactly_and_writes_nothing():
    store, wh = world()
    before = store.state()
    plan = run(bar_repair.plan_repair(store, wh))
    assert [(p["date"], p["rows"], p["identical"]) for p in plan["phantom"]] == [(HOL, 2, 2)]
    assert [(u["date"], u["rows"], u["identical"]) for u in plan["unverified_extra"]] == [(PART, 2, 1)]
    assert plan["missing"] == [{"date": MISS, "warehouse_rows": 2916}]
    assert plan["derived_on_phantom"] == {"stock_technical_features": {HOL: 2}, "positional_signals": {HOL: 1}}
    assert plan["recompute_dates"] == [LAST] and plan["affected_not_recomputed"] == []   # 1 Oct predates both
    assert plan["affected_dates"] == 1
    assert bar_repair.apply_actions(plan) == {"delete_dates": [HOL], "backfill_dates": [MISS], "recompute_dates": [LAST]}
    assert store.writes == 0 and store.state() == before


def test_tc22_apply_snapshots_first_then_repairs(tmp_path):
    store, wh = world()
    snap = tmp_path / "snap.json"
    out = run(bar_repair.apply_repair(store, wh, fake_ingest(store), fake_score, str(snap)))
    assert out["changed"] and out["deleted"] == {"stock_ohlcv": 2, "stock_technical_features": 2, "positional_signals": 1}
    assert store.ingested == [MISS] and out["recomputed"] == {"2026-10-06": {"scored": 2, "actionable": 1}}
    assert out["after"]["phantom"] == 0 and out["after"]["missing"] == 0
    assert out["after"]["pending"] == {"delete_dates": [], "backfill_dates": [], "recompute_dates": []}
    assert out["after"]["unverified_extra"] == 1                       # 3 Oct: reported, never deleted
    assert not any(r["bar_date"] == HOL for r in store.t["stock_ohlcv"])
    assert {r["engine_version"] for r in store.t["stock_technical_features"] if r["as_of_date"] == LAST} == {ENGINE_VERSION}
    s = json.loads(snap.read_text())
    assert s["backfill_dates"] == ["2026-10-05"] and s["dates"]["stock_ohlcv"] == ["2026-10-02"]
    assert len(s["rows"]["stock_ohlcv"]) == 2 and len(s["rows"]["stock_technical_features"]) == 4
    assert len(s["rows"]["positional_signals"]) == 2


def test_tc23_apply_twice_changes_nothing(tmp_path):
    store, wh = world()
    run(bar_repair.apply_repair(store, wh, fake_ingest(store), fake_score, str(tmp_path / "1.json")))
    writes, state = store.writes, store.state()
    out = run(bar_repair.apply_repair(store, wh, fake_ingest(store), fake_score, str(tmp_path / "2.json")))
    assert out["changed"] is False and store.writes == writes and store.state() == state
    assert not (tmp_path / "2.json").exists()


def test_tc24_restore_returns_the_exact_pre_apply_state_and_is_idempotent(tmp_path):
    store, wh = world()
    before = store.state()
    snap = tmp_path / "snap.json"
    run(bar_repair.apply_repair(store, wh, fake_ingest(store), fake_score, str(snap)))
    assert store.state() != before
    run(bar_repair.restore_snapshot(store, str(snap)))
    assert store.state() == before
    run(bar_repair.restore_snapshot(store, str(snap)))
    assert store.state() == before


def test_tc25_apply_never_overwrites_an_existing_snapshot(tmp_path):
    store, wh = world()
    snap = tmp_path / "snap.json"
    snap.write_text("earlier snapshot")
    with pytest.raises(FileExistsError):
        run(bar_repair.apply_repair(store, wh, fake_ingest(store), fake_score, str(snap)))
    assert store.writes == 0 and snap.read_text() == "earlier snapshot"


def test_tc25b_cli_apply_without_snapshot_is_refused(monkeypatch):
    from scripts import repair_scanner_bars as cli
    from services import pg_client

    async def pool():
        return object()
    monkeypatch.setattr(pg_client, "get_pool", pool)

    class A:
        restore = None
        apply = True
        snapshot = None
        recompute_from = None
    assert run(cli.main(A())) == 1


def test_apply_skips_recompute_when_a_backfill_is_refused(tmp_path):
    store, wh = world()

    async def refused(d):
        return {"date": d.isoformat(), "status": "date_mismatch", "rows_written": 0}
    out = run(bar_repair.apply_repair(store, wh, refused, fake_score, str(tmp_path / "s.json")))
    assert "skipped" in out["recomputed"] and out["after"]["missing"] == 1
    assert {r["engine_version"] for r in store.t["stock_technical_features"] if r["as_of_date"] == LAST} == {"positional.v1.0"}


def test_compare_runs_reports_top_entries_exits_and_shifts():
    before_f = {s: {"final_score": v, "stage": "BREAKOUT"} for s, v in (("A", .9), ("B", .8), ("C", .7), ("D", .6))}
    after_f = {**before_f, "A": {"final_score": .65, "stage": "ACCUMULATION"}, "E": {"final_score": .95, "stage": "BREAKOUT"}}
    sig = lambda f, syms: [{"symbol": s, "final_score": f[s]["final_score"], "risk_reward": 2.0} for s in syms]  # noqa: E731
    out = bar_repair.compare_runs(before_f, sig(before_f, "ABC"), after_f, sig(after_f, "EBC"), top=2)
    assert out["top2"] == {"before": ["A", "B"], "after": ["E", "B"], "entered": ["E"], "exited": ["A"],
                           "rank_shifts": []}
    assert out["actionable"] == {"before": 3, "after": 3, "added": 1, "removed": 1}
    assert out["stage_changes"] == 1 and out["final_score_delta"]["changed_gt_0_01"] == 1
