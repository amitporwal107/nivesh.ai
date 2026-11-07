"""TrueData long price history + nightly TD_* macro refresh — unit cases TC-01 … TC-12 and TC-17 (route) from
test_reports/truedata_price_history_TESTCASES.md.

No database and no network. Every bar, close and row below is MOCK — not real data: synthetic numbers shaped like the
2 Nov 2026 measurements (RELIANCE-like rounding, ITC-like demerger gap). TrueData is reached only through the repo
client with a fake transport, so a call that should not happen fails the test. Coroutines run under asyncio.run (the
backend image has no pytest-asyncio).
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import date, datetime, timedelta

import pytest

from nidp.shared import deploy_env
from nidp.shared import market_data_source as mds
from nidp.shared.sources import truedata as td
from nidp.services.truedata_history import bars as B
from nidp.services.truedata_history import service as H
from nidp.services.truedata_macro import service as M

READY = {"TRUEDATA_USERNAME": "u", "TRUEDATA_PASSWORD": "p"}


@pytest.fixture(autouse=True)
def _no_host_environment(monkeypatch):
    """The gate reads NIDP_HOME / NIDP_ENV / APP_ENV: keep the runner's own out of these tests."""
    for k in ("NIDP_HOME", "NIDP_ENV", "APP_ENV"):
        monkeypatch.delenv(k, raising=False)


def switch(source: str, env=None):
    return lambda: mds.resolve({"source": source}, READY if env is None else env, integrated=False)


def weekdays(start: date, n: int):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def bar(d, close, vol=1000):
    return {"timestamp": d.isoformat(), "open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
            "volume": vol, "oi": 0}


def r05(x):
    return round(round(x / 0.05) * 0.05, 2)


HIST_DAYS = weekdays(date(2024, 3, 11), 14)                    # 2024-03-11 .. 2024-03-28
WH_DAYS = weekdays(date(2024, 4, 1), 10)                       # 2024-04-01 .. 2024-04-12


def case(td_close, our_factor=1.0, our_round=None):
    """MOCK — not real data. td_close(d) → TrueData close; ours = td-exact x our_factor (unrounded)."""
    hist = [bar(d, r05(td_close(d))) for d in HIST_DAYS]
    over = [bar(d, r05(td_close(d))) for d in HIST_DAYS[-6:] + WH_DAYS]
    wh = [(d, round(td_close(d) * our_factor, our_round or 6)) for d in WH_DAYS]
    return hist, wh, over


# ── TC-01 bars hygiene ──────────────────────────────────────────────────────────────────────────────────────────

def test_tc01_duplicates_collapse_disagreeing_copies_drop_the_date_bad_rows_dropped():
    d1, d2, d3 = date(2020, 6, 16), date(2020, 10, 8), date(2020, 10, 9)
    rows = [bar(d1, 100), bar(d1, 100),                      # exact copy → one bar
            bar(d2, 50), bar(d2, 51),                        # copies disagree → date dropped
            bar(d3, 10),
            {"timestamp": "2020-10-12", "close": None}, {"timestamp": "2020-10-13", "close": -1},
            {"timestamp": "", "close": 5}]
    out, rep = B.clean_bars(rows)
    assert sorted(out) == [d1, d3]
    assert rep.duplicate_dates == 2 and rep.conflicting_dates == [d2] and rep.bad_rows == 3 and rep.rows_in == 8


# ── TC-02 … TC-09 stitching ─────────────────────────────────────────────────────────────────────────────────────

def test_tc02_same_basis_with_truedata_rounding_is_factor_exactly_one():
    hist, wh, over = case(lambda d: 1484.775 + d.toordinal() % 7)          # RELIANCE-like: ours x.775, TD x.80
    r = B.stitch_symbol("RELI", hist, wh, over)
    assert r.status == B.LOADED and r.factor == 1.0 and r.overlap_days == 10
    assert [x["adj_close"] for x in r.rows] == [h["close"] for h in hist]   # history = TrueData's values
    assert r.history_to == date(2024, 3, 28) and r.warehouse_from == date(2024, 4, 1)


def test_tc03_demerger_basis_is_rescaled_and_the_seam_matches_truedatas_own_move():
    hist, wh, over = case(lambda d: 400 + (d.toordinal() % 5), our_factor=426.70 / 402.55)
    r = B.stitch_symbol("ITCX", hist, wh, over)
    assert r.status == B.LOADED and r.factor == pytest.approx(426.70 / 402.55, rel=2e-4)
    assert r.rows[-1]["adj_close"] == pytest.approx(hist[-1]["close"] * r.factor)
    # seam: our first close vs last stitched close moves like TrueData over the same days (within rounding)
    assert (1 + r.seam_move_pct / 100) / (1 + r.td_seam_move_pct / 100) == pytest.approx(1, abs=B._tol(400))
    assert "rescaled" in r.reason


def test_tc04_a_ratio_that_moves_inside_the_overlap_is_unstable_and_not_loaded():
    hist, wh, over = case(lambda d: 500.0)
    wh = [(d, c * (1.01 if i >= 5 else 1.0)) for i, (d, c) in enumerate(wh)]   # 1 % basis change mid-window
    r = B.stitch_symbol("UNST", hist, wh, over)
    assert r.status == B.UNSTABLE and r.rows == [] and r.max_dev_pct > 0.4


def test_tc05_fewer_than_three_overlap_days_is_no_overlap():
    hist, wh, over = case(lambda d: 200.0)
    over = [o for o in over if o["timestamp"] < "2024-04-03"]                  # only 2 of our days have a TD bar
    r = B.stitch_symbol("FEW", hist, wh, over)
    assert r.status == B.NO_OVERLAP and r.overlap_days == 2 and r.rows == []


def test_tc06_a_long_seam_renamed_symbol_or_late_coverage_is_flagged_not_bridged():
    hist, _, over = case(lambda d: 300.0)
    wh = [(d, 300.0) for d in weekdays(date(2025, 10, 1), 10)]
    r = B.stitch_symbol("LTMX", hist, wh, over)
    assert r.status == B.SEAM_GAP and r.rows == [] and "2025-10-01" in r.reason


def test_tc07_truedata_basis_changed_since_the_raw_fetch_or_cannot_be_checked():
    hist, wh, over = case(lambda d: 300.0)
    over_moved = [dict(o, close=o["close"] + 1.0) if o["timestamp"] == "2024-03-27" else o for o in over]
    assert B.stitch_symbol("MOVED", hist, wh, over_moved).status == B.BASIS_CHANGED
    over_no_hist = [o for o in over if o["timestamp"] >= "2024-04-01"]
    r = B.stitch_symbol("NOHB", hist, wh, over_no_hist)
    assert r.status == B.NO_BASIS_CHECK and r.rows == []


def test_tc08_factor_outside_the_range_means_a_missed_split_and_is_not_loaded():
    hist, wh, over = case(lambda d: 100.0, our_factor=5.0)
    r = B.stitch_symbol("SPLT", hist, wh, over)
    assert r.status == B.FACTOR_OUT_OF_RANGE and r.factor == pytest.approx(5.0) and r.rows == []
    # a demerger recorded BEFORE our first day does not explain a gap measured on our first days
    assert B.stitch_symbol("SPLT", hist, wh, over, [date(2024, 3, 1)]).status == B.FACTOR_OUT_OF_RANGE
    # below the range a demerger never explains it (a demerger makes ours HIGHER than TrueData)
    hist2, wh2, over2 = case(lambda d: 100.0, our_factor=0.2)
    assert B.stitch_symbol("LOW", hist2, wh2, over2, [date(2025, 4, 7)]).status == B.FACTOR_OUT_OF_RANGE
    # above DEMERGER_MAX_FACTOR stays flagged even with a demerger
    hist3, wh3, over3 = case(lambda d: 100.0, our_factor=12.0)
    assert B.stitch_symbol("HUGE", hist3, wh3, over3, [date(2025, 4, 7)]).status == B.FACTOR_OUT_OF_RANGE


def test_tc08b_a_large_factor_with_a_demerger_recorded_after_our_first_day_is_loaded():
    """SIEMENS-like (2 Nov real check: factor 2.01, demerger ex-date 2025-04-07 in nidp.corporate_actions)."""
    hist, wh, over = case(lambda d: 1400.0 + d.toordinal() % 3, our_factor=2.01)
    r = B.stitch_symbol("SIEM", hist, wh, over, [date(2025, 4, 7), date(2023, 1, 1)])
    assert r.status == B.LOADED and r.factor == pytest.approx(2.01, rel=1e-4)
    assert "2025-04-07" in r.reason and "2023-01-01" not in r.reason
    assert r.rows[-1]["adj_close"] == pytest.approx(hist[-1]["close"] * r.factor)


def test_tc09_history_on_or_after_our_first_day_is_never_emitted():
    hist, wh, over = case(lambda d: 250.0)
    hist = hist + [bar(d, 250.0) for d in WH_DAYS[:3]]                         # history overlapping the warehouse
    r = B.stitch_symbol("OVLP", hist, wh, over)
    assert r.status == B.LOADED and max(x["as_of_date"] for x in r.rows) == date(2024, 3, 28)


def test_overlap_window_covers_the_last_history_days_and_our_first_n_days():
    start, end = B.overlap_window(date(2024, 3, 28), WH_DAYS)
    assert start == date(2024, 3, 18) and end == WH_DAYS[-1]


# ── TC-10 unfinished bars ───────────────────────────────────────────────────────────────────────────────────────

def test_tc10_today_mcx_never_before_2359_index_after_1600_future_always_dropped():
    today = date(2026, 11, 2)
    bars = {d: B.Bar(d, 1, 1, 1, 1.0, 1) for d in (today - timedelta(days=1), today, today + timedelta(days=1))}
    kept, dropped = B.drop_unfinished(bars, "mcx", datetime(2026, 11, 2, 23, 0))
    assert sorted(kept) == [today - timedelta(days=1)] and dropped == [today, today + timedelta(days=1)]
    kept, _ = B.drop_unfinished(bars, "index", datetime(2026, 11, 2, 15, 45))
    assert today not in kept
    kept, dropped = B.drop_unfinished(bars, "index", datetime(2026, 11, 2, 16, 5))
    assert today in kept and dropped == [today + timedelta(days=1)]
    assert M.last_final_day("mcx", datetime(2026, 11, 3, 0, 15)) == today
    assert M.last_final_day("index", datetime(2026, 11, 2, 15, 0)) == today - timedelta(days=1)


# ── Fakes ───────────────────────────────────────────────────────────────────────────────────────────────────────

class Transport:
    """Fake TrueData HTTP: auth + getbars by symbol. `forbid=True` fails the test on any call."""

    def __init__(self, bars_by_symbol=None, forbid=False, status_by_symbol=None, text_by_symbol=None):
        self.bars, self.forbid = bars_by_symbol or {}, forbid
        self.status, self.text = status_by_symbol or {}, text_by_symbol or {}
        self.calls = []

    def __call__(self, method, url, data, headers, timeout):
        if self.forbid:
            raise AssertionError(f"TrueData must not be called: {method}")
        if "auth.truedata.in" in url:
            return 200, json.dumps({"access_token": "t", "expires_in": 3600}).encode()
        from urllib.parse import parse_qs, urlsplit
        q = parse_qs(urlsplit(url).query)
        sym = q["symbol"][0]
        self.calls.append((sym, q["from"][0], q["to"][0]))
        if sym in self.status:
            return self.status[sym], b"error"
        if sym in self.text:
            return 200, self.text[sym].encode()
        rows = self.bars.get(sym, [])
        body = "timestamp,open,high,low,close,volume,oi\n" + "\n".join(
            f"{r['timestamp']},{r['open']},{r['high']},{r['low']},{r['close']},{r['volume']},0" for r in rows)
        return 200, body.encode()


def client(transport):
    return td.TrueDataClient(td.Credentials("u", "p"), transport=transport, min_interval=0)


class Conn:
    def __init__(self, fetch_answers=None, database="nidp_staging"):
        self.answers = fetch_answers or {}
        self.sql = []
        self.database = database                     # what current_database() answers (the staging gate)

    async def fetch(self, q, *a):
        self.sql.append(q)
        for key, rows in self.answers.items():
            if key in q:
                return rows(a) if callable(rows) else rows
        return []

    async def fetchval(self, q, *a):
        self.sql.append(q)
        if "current_database()" in q:
            if isinstance(self.database, Exception):
                raise self.database
            return self.database
        return 0

    async def copy_records_to_table(self, table, records, columns):
        self.sql.append(f"COPY {table}")
        self.copied = list(records)

    async def execute(self, q, *a, **kw):
        self.sql.append(q)
        if q.startswith("DELETE"):
            return "DELETE 3"
        if "FROM tmp_prices_eod_history" in q:
            return "INSERT 0 %d" % len(self.copied)
        return "INSERT 0 %d" % (len(a[0]) if a and isinstance(a[0], list) else 0)

    def transaction(self, **kw):
        class T:
            async def __aenter__(self_):
                return self_

            async def __aexit__(self_, *e):
                return False
        return T()


class Pool:
    def __init__(self, conn=None, forbid=False):
        self.conn, self.forbid = conn or Conn(), forbid

    def acquire(self):
        if self.forbid:
            raise AssertionError("the database must not be touched")
        conn = self.conn

        class CM:
            async def __aenter__(self_):
                return conn

            async def __aexit__(self_, *e):
                return False
        return CM()


class JobRuns:
    def __init__(self, forbid=False):
        self.forbid, self.runs = forbid, []

    def __call__(self, ingester, target_date=None):
        if self.forbid:
            raise AssertionError("no job_log row expected")
        outer = self

        class Run:
            def __init__(self):
                self.run_id, self.rows_fetched, self.rows_inserted, self.rows_skipped = uuid.uuid4(), 0, 0, 0
                self.metadata, self.final = {}, None

            async def __aenter__(self):
                outer.runs.append(self)
                return self

            async def finalize(self, status, error_message=None, error_class=None):
                self.final = (status, error_class)

            async def __aexit__(self, *e):
                return False
        return Run()


def write_raw(dirpath, symbol, rows=None, empty=None):
    import gzip
    doc = {"symbol": symbol, "from": "2010-01-01", "to": "2024-03-31"}
    doc.update({"empty": empty} if empty else {"rows": rows})
    with gzip.open(H.raw_path(str(dirpath), symbol), "wt") as fh:
        json.dump(doc, fh)


# ── TC-11 switch gating ─────────────────────────────────────────────────────────────────────────────────────────

def test_tc11_loader_at_current_calls_nothing_and_writes_nothing():
    rep = asyncio.run(H.load(["RELI"], client=client(Transport(forbid=True)), switch=switch("current"),
                             pool=Pool(forbid=True), job_run_factory=JobRuns(forbid=True)))
    assert rep["verdict"] == "SWITCHED_OFF"
    forced = switch("shadow", {**READY, "MARKET_DATA_SOURCE_FORCE_CURRENT": "1"})
    rep = asyncio.run(H.load(["RELI"], client=client(Transport(forbid=True)), switch=forced, pool=Pool(forbid=True),
                             job_run_factory=JobRuns(forbid=True), dry_run=True))
    assert rep["verdict"] == "SWITCHED_OFF" and "FORCED_CURRENT_BY_ENV" in rep["message"]


def test_tc11_a_files_only_dry_run_runs_at_current_reads_only_and_calls_nothing(tmp_path):
    hist, wh, over = case(lambda d: 700.0)
    (tmp_path / "raw").mkdir(), (tmp_path / "ov").mkdir()
    write_raw(tmp_path / "raw", "RELI", hist)
    write_raw(tmp_path / "ov", "RELI", over)
    conn = Conn({"prices_eod_adjusted": [{"symbol": "RELI", "as_of_date": d, "adj_close": c} for d, c in wh]})
    rep = asyncio.run(H.load(None, raw_dir=str(tmp_path / "raw"), overlap_dir=str(tmp_path / "ov"),
                             client=client(Transport(forbid=True)), switch=switch("current"), pool=Pool(conn),
                             dry_run=True, job_run_factory=JobRuns(forbid=True)))
    assert rep["verdict"] == "DRY_RUN" and rep["status_counts"] == {"LOADED": 1} and rep["rows_stitched"] == 14
    assert not [q for q in conn.sql if q.lstrip().upper().startswith(("INSERT", "DELETE", "UPDATE", "CREATE"))]


def test_tc11_macro_job_at_current_records_skipped_and_calls_nothing():
    runs = JobRuns()
    rep = asyncio.run(M.refresh(client=client(Transport(forbid=True)), switch=switch("current"), pool=Pool(forbid=True),
                                job_run_factory=runs))
    assert rep["verdict"] == "SWITCHED_OFF" and rep["job_status"] == "SKIPPED"
    assert [r.final for r in runs.runs] == [("SKIPPED", "SWITCHED_OFF")]
    rep = asyncio.run(M.refresh(client=client(Transport(forbid=True)), switch=switch("current"), pool=Pool(forbid=True),
                                job_run_factory=JobRuns(forbid=True), dry_run=True))
    assert rep["verdict"] == "SWITCHED_OFF" and "job_status" not in rep


def test_tc11_rollbacks_run_whatever_the_switch_says():
    conn = Conn()
    out = asyncio.run(H.rollback(str(uuid.uuid4()), pool=Pool(conn)))
    assert out["deleted_rows"] == 3 and any("prices_eod_history_stitch" in q for q in conn.sql)
    out = asyncio.run(M.rollback(str(uuid.uuid4()), pool=Pool(Conn())))
    assert out["deleted_rows"] == 3


# ── Loader with TrueData (fake transport) ───────────────────────────────────────────────────────────────────────

def test_loader_fetch_mode_one_history_call_and_one_overlap_call_per_symbol_seam_gap_needs_no_overlap_call():
    hist, wh, over = case(lambda d: 900.0)
    tr = Transport({"AAA": hist + [o for o in over if o["timestamp"] >= "2024-04-01"], "BBB": hist})
    wh_rows = [{"symbol": "AAA", "as_of_date": d, "adj_close": c} for d, c in wh] + \
              [{"symbol": "BBB", "as_of_date": d, "adj_close": 900.0} for d in weekdays(date(2025, 10, 1), 10)]
    conn = Conn({"prices_eod_adjusted": wh_rows, "DISTINCT symbol FROM nidp.prices_eod_history": []})
    runs = JobRuns()
    rep = asyncio.run(H.load(["AAA", "BBB"], client=client(tr), switch=switch("shadow"), pool=Pool(conn),
                             job_run_factory=runs))
    assert rep["status_counts"] == {"LOADED": 1, "SEAM_GAP": 1} and rep["job_status"] == "OK"
    assert [c[0] for c in tr.calls] == ["AAA", "AAA", "BBB"]                   # BBB: history only
    assert tr.calls[0][1:] == ("100101T00:00:00", "240331T23:59:59")           # 2010-01-01 .. 2024-03-31
    assert tr.calls[1][1:] == ("240318T00:00:00", "240412T23:59:59")           # overlap window
    assert runs.runs[0].final == ("OK", None) and runs.runs[0].rows_inserted == 14


def test_loader_a_truedata_failure_is_fetch_failed_and_the_run_partial():
    hist, wh, over = case(lambda d: 900.0)
    tr = Transport({"AAA": hist + [o for o in over if o["timestamp"] >= "2024-04-01"]}, status_by_symbol={"BAD": 503})
    wh_rows = [{"symbol": s, "as_of_date": d, "adj_close": c} for s in ("AAA", "BAD") for d, c in wh]
    runs = JobRuns()
    rep = asyncio.run(H.load(["AAA", "BAD"], client=client(tr), switch=switch("shadow"),
                             pool=Pool(Conn({"prices_eod_adjusted": wh_rows})), job_run_factory=runs))
    assert rep["status_counts"] == {"LOADED": 1, "FETCH_FAILED": 1} and rep["verdict"] == "PARTIAL"
    assert runs.runs[0].final == ("PARTIAL", "TRUEDATA_FETCH_FAILED")


def test_raw_reader_empty_and_missing_files_are_no_history(tmp_path):
    write_raw(tmp_path, "GONE", empty="EMPTY_RESPONSE")
    assert H.read_raw(str(tmp_path), "GONE") == (None, "TrueData answered EMPTY_RESPONSE")
    assert H.read_raw(str(tmp_path), "NOPE")[1].startswith("no raw file")
    write_raw(tmp_path, "M&M", [bar(date(2024, 3, 28), 10.0)])
    (tmp_path / "PART.json.gz.part").write_text("x")                          # a fetch in progress is ignored
    assert H.list_raw_symbols(str(tmp_path)) == ["GONE", "M&M"]


# ── TC-12 macro refresh ─────────────────────────────────────────────────────────────────────────────────────────

LOADED_2NOV = {"TD_INDIA_VIX", "TD_MCX_ALUMINIUM_1M", "TD_MCX_ALUMINIUM_2M", "TD_MCX_COPPER_1M", "TD_MCX_COPPER_2M",
               "TD_MCX_CRUDEOIL_1M", "TD_MCX_CRUDEOIL_2M", "TD_MCX_GOLD_1M", "TD_MCX_GOLD_2M", "TD_MCX_NATURALGAS_1M",
               "TD_MCX_NATURALGAS_2M", "TD_MCX_SILVER_1M", "TD_MCX_SILVER_2M", "TD_MCX_ZINC_1M", "TD_MCX_ZINC_2M",
               "TD_NIFTY50_USD", "TD_NIFTY_50", "TD_NIFTY_GSEC_10Y", "TD_NIFTY_GSEC_10Y_CLEAN", "TD_NIFTY_GSEC_11_15Y",
               "TD_NIFTY_GSEC_15Y_PLUS", "TD_NIFTY_GSEC_4_8Y", "TD_NIFTY_GSEC_8_13Y", "TD_NIFTY_GSEC_COMPOSITE"}


def test_tc12_series_are_the_24_loaded_on_2_nov_with_their_caveats_and_month_pairs():
    assert {v[0] for v in M.SERIES.values()} == LOADED_2NOV and len(M.SERIES) == 24
    for metal in ("CRUDEOIL", "NATURALGAS", "GOLD", "SILVER", "COPPER", "ALUMINIUM", "ZINC"):
        assert M.SERIES[f"{metal}-I"][0].endswith("_1M") and M.SERIES[f"{metal}-II"][0].endswith("_2M")
        assert M.SERIES[f"{metal}-I"][3] == "mcx"
    assert M.series_label("NIFTY 50") == "Nifty 50, close"
    assert "use weekly returns" in M.series_label("NIFTY GS 10YR") and "max 2.6%" in M.series_label("INDIA VIX")
    assert M.series_label("CRUDEOIL-I") == "MCX crude oil, near-month continuous future, close"


def _last(rows):
    return {"max(as_of_date)": [{"series_id": s, "last": d} for s, d in rows]}


def test_tc12_only_new_days_up_to_date_makes_no_call_empty_is_not_failure_failure_is_partial():
    now = datetime(2026, 11, 3, 0, 15)                         # the cron slot, for Monday 2 Nov
    crude = [bar(date(2026, 10, 30), 5000), bar(date(2026, 11, 2), 5100), bar(date(2026, 11, 2), 5100),
             bar(date(2026, 11, 3), 5200)]                    # a stored day, a new day (twice), today (partial)
    tr = Transport({"CRUDEOIL-I": crude}, text_by_symbol={"CRUDEOIL-II": "No data exists for CRUDEOIL-II"},
                   status_by_symbol={"GOLD-I": 500})
    conn = Conn(_last([("TD_MCX_CRUDEOIL_1M", date(2026, 10, 30)), ("TD_MCX_CRUDEOIL_2M", date(2026, 10, 30)),
                       ("TD_MCX_GOLD_1M", date(2026, 10, 30)), ("TD_NIFTY_50", date(2026, 11, 2))]))
    runs = JobRuns()
    rep = asyncio.run(M.refresh(client=client(tr), switch=switch("shadow"), pool=Pool(conn), now_ist=now,
                                codes=["CRUDEOIL-I", "CRUDEOIL-II", "GOLD-I", "NIFTY 50"], job_run_factory=runs))
    s = rep["series"]
    assert s["NIFTY 50"]["status"] == "UP_TO_DATE" and s["NIFTY 50"]["calls"] == 0
    assert [c[0] for c in tr.calls] == ["CRUDEOIL-I", "CRUDEOIL-II", "GOLD-I"]
    assert tr.calls[0][1:] == ("261031T00:00:00", "261102T23:59:59")          # from the day after the last stored
    assert s["CRUDEOIL-I"]["new_days"] == 1 and s["CRUDEOIL-I"]["first_new"] == date(2026, 11, 2)
    assert s["CRUDEOIL-I"]["unfinished_dropped"] == ["2026-11-03"]
    assert s["CRUDEOIL-II"]["status"] == "OK" and s["CRUDEOIL-II"]["new_days"] == 0
    assert s["GOLD-I"]["status"] == "FAILED" and s["GOLD-I"]["error_code"] == "PROVIDER_UNAVAILABLE"
    assert rep["verdict"] == "PARTIAL" and runs.runs[0].final == ("PARTIAL", "TRUEDATA_CALL_FAILED")
    insert = [q for q in conn.sql if "INSERT INTO nidp.fred_macro" in q]
    assert len(insert) == 1 and "ON CONFLICT (as_of_date, series_id, source) DO NOTHING" in insert[0]


def test_tc12_an_empty_series_starts_in_2010():
    tr = Transport({"ZINC-I": [bar(date(2010, 1, 1), 100)]})
    rep = asyncio.run(M.refresh(client=client(tr), switch=switch("shadow"), pool=Pool(Conn()), dry_run=True,
                                now_ist=datetime(2026, 11, 3, 0, 15), codes=["ZINC-I"]))
    assert tr.calls[0][1] == "100101T00:00:00" and rep["series"]["ZINC-I"]["new_days"] == 1
    assert rep["verdict"] == "DRY_RUN" and rep["rows_inserted"] == 0


# ── TC-17 DaaS route ────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def route_client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from nidp.services.daas_api import auth, keys, ratelimit
    from nidp.services.daas_api.routers import prices

    calls = []

    class RConn:
        async def fetch(self, q, *a):
            calls.append((q, a))
            return [{"symbol": "ITCX", "as_of_date": date(2024, 3, 28), "adj_open": 1.0, "adj_high": 1.0,
                     "adj_low": 1.0, "adj_close": 426.0, "volume": 10, "stitch_factor": 1.06,
                     "basis_source": "truedata_history"}]                        # MOCK — not real data

    async def _get_pool():
        return Pool(RConn())
    monkeypatch.setattr(prices, "get_pool", _get_pool)
    rec = keys.KeyRecord(key_id="00000000-0000-0000-0000-000000000009", key_prefix="nvd_t", name="t",
                         owner_email="t@nivesh", plan="internal", rate_limit_rpm=1500, daily_quota=None,
                         status="active", expires_at=None)

    async def _resolve(_t):
        return rec
    monkeypatch.setattr(auth, "_resolve", _resolve)

    async def _consume(key_id, *, limit_rpm, daily_quota):
        return ratelimit.LimitDecision(allowed=True, limit_rpm=limit_rpm, remaining_rpm=limit_rpm - 1, reset_seconds=60,
                                       daily_quota=daily_quota, daily_used=1, daily_remaining=None, reason=None)
    monkeypatch.setattr(ratelimit, "consume", _consume)
    app = FastAPI()
    app.include_router(prices.router, prefix="/v1")
    return TestClient(app), calls


def test_tc17_research_long_route(route_client):
    c, calls = route_client
    assert c.get("/v1/prices/research-long/itcx").status_code == 401
    r = c.get("/v1/prices/research-long/itcx", headers={"X-API-Key": "nvd_t_x"},
              params={"start": "2010-01-01", "end": "2024-03-31", "limit": 2, "offset": 4})
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "ITCX" and body["data"][0]["basis_source"] == "truedata_history"
    assert "RESEARCH ONLY" in body["note"] and body["pagination"]["offset"] == 4
    q, a = calls[-1]
    assert "nidp.v_prices_eod_long_research" in q and "ORDER BY as_of_date DESC" in q
    assert a == ("ITCX", date(2010, 1, 1), date(2024, 3, 31), 2, 4)
    assert c.get("/v1/prices/research-long/itcx", headers={"X-API-Key": "nvd_t_x"},
                 params={"start": "2010-13-01"}).status_code == 400


# ── TC-21 staging only (owner, 3 Nov 2026: "keep on staging.. on prod please use our snapshot data") ─────────────────

@pytest.mark.parametrize("db, env, expected", [
    ("nidp_staging", {}, "staging"),
    ("nidp_staging", {"NIDP_HOME": "/opt/nidp-staging"}, "staging"),
    ("nidp_staging", {"NIDP_HOME": "/opt/nidp-staging/", "APP_ENV": "staging"}, "staging"),
    ("nidp", {}, "production"),
    ("nidp", {"NIDP_HOME": "/opt/nidp"}, "production"),
    ("nidp_staging", {"NIDP_HOME": "/opt/nidp"}, "production"),           # conflicting: any production signal refuses
    ("nidp_staging", {"NIDP_ENV": "production"}, "production"),
    ("nidp_staging", {"APP_ENV": "Prod"}, "production"),
    ("nivesh", {}, "unknown"),
    ("nidp_test", {"NIDP_ENV": "staging"}, "unknown"),                    # NIDP_ENV=staging alone never allows
    ("nidp_staging", {"NIDP_HOME": "/tmp/somewhere"}, "unknown"),
    (None, {}, "unknown"),
])
def test_tc21_gate_allows_staging_only_and_fails_closed(db, env, expected):
    v = deploy_env.classify(db, env)
    assert v.environment == expected and v.allowed == (expected == "staging")
    if expected == "production":
        assert "staging only" in v.reason


def test_tc21_gate_a_failing_query_is_unknown_and_refused():
    v = asyncio.run(deploy_env.truedata_load_gate(Conn(database=RuntimeError("down")), {}))
    assert (v.environment, v.allowed) == ("unknown", False)


def _data_sql(conn):
    return [q for q in conn.sql if q.lstrip().upper().startswith(("INSERT", "DELETE", "UPDATE", "CREATE", "COPY"))]


@pytest.mark.parametrize("db, env", [("nidp", {}), ("nidp_staging", {"NIDP_HOME": "/opt/nidp"}), ("nivesh", {})])
def test_tc21_loader_off_staging_calls_nothing_writes_nothing_records_skipped(db, env, tmp_path):
    hist, wh, over = case(lambda d: 700.0)
    (tmp_path / "raw").mkdir(), (tmp_path / "ov").mkdir()
    write_raw(tmp_path / "raw", "RELI", hist)
    write_raw(tmp_path / "ov", "RELI", over)
    conn = Conn({"prices_eod_adjusted": [{"symbol": "RELI", "as_of_date": d, "adj_close": c} for d, c in wh]}, database=db)
    runs = JobRuns()
    for kw in ({}, {"raw_dir": str(tmp_path / "raw"), "overlap_dir": str(tmp_path / "ov")}):
        rep = asyncio.run(H.load(["RELI"], client=client(Transport(forbid=True)), switch=switch("shadow"),
                                 pool=Pool(conn), job_run_factory=runs, env=env, **kw))
        assert rep["verdict"] == "NOT_STAGING" and rep["job_status"] == "SKIPPED" and "rows_inserted" not in rep
    assert [r.final for r in runs.runs] == [("SKIPPED", "NOT_STAGING")] * 2 and _data_sql(conn) == []
    rep = asyncio.run(H.load(["RELI"], client=client(Transport(forbid=True)), switch=switch("shadow"), pool=Pool(conn),
                             job_run_factory=JobRuns(forbid=True), env=env, dry_run=True))
    assert rep["verdict"] == "NOT_STAGING" and "job_status" not in rep
    assert not [q for q in conn.sql if "prices_eod_adjusted" in q]       # refused before reading anything else


@pytest.mark.parametrize("db, env", [("nidp", {}), ("nidp_staging", {"APP_ENV": "production"}), ("unit_test", {})])
def test_tc21_macro_off_staging_calls_nothing_writes_nothing_records_skipped(db, env):
    conn, runs = Conn(database=db), JobRuns()
    rep = asyncio.run(M.refresh(client=client(Transport(forbid=True)), switch=switch("shadow"), pool=Pool(conn),
                                job_run_factory=runs, env=env, now_ist=datetime(2026, 11, 3, 0, 15)))
    assert rep["verdict"] == "NOT_STAGING" and rep["job_status"] == "SKIPPED" and rep["environment"] != "staging"
    assert [r.final for r in runs.runs] == [("SKIPPED", "NOT_STAGING")] and _data_sql(conn) == []
    assert not [q for q in conn.sql if "fred_macro" in q]
    rep = asyncio.run(M.refresh(client=client(Transport(forbid=True)), switch=switch("shadow"), pool=Pool(conn),
                                job_run_factory=JobRuns(forbid=True), env=env, dry_run=True))
    assert rep["verdict"] == "NOT_STAGING" and "job_status" not in rep


def test_tc21_on_staging_the_macro_job_runs():
    tr = Transport({"ZINC-I": [bar(date(2026, 11, 2), 300)]})
    rep = asyncio.run(M.refresh(client=client(tr), switch=switch("shadow"), pool=Pool(Conn(database="nidp_staging")),
                                env={"NIDP_HOME": "/opt/nidp-staging"}, codes=["ZINC-I"], dry_run=True,
                                now_ist=datetime(2026, 11, 3, 0, 15)))
    assert rep["environment"] == "staging" and rep["verdict"] == "DRY_RUN" and [c[0] for c in tr.calls] == ["ZINC-I"]
