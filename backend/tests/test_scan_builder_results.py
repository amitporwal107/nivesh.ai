"""Scan Builder company results (services/scan_builder/data.py: company_results, ScanData.results_fields; DESIGN.md §8).

No network: DaaS is a fake, the clocks are injected. Every figure below is hand-made test input (MOCK — not real data)."""
import asyncio
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from services.scan_builder import data as sd

NOW = datetime(2026, 11, 3, 4, 0, tzinfo=timezone.utc)          # 09:30 IST
QUARTERS = ["2026-09-30", "2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"]


def run(coro):
    return asyncio.run(coro)


def row(end, pat, *, ptype="quarterly", cons=True, pbt=None, dep=None, eps=None):
    return {"symbol": "X", "period_end": end, "period_type": ptype, "consolidated": cons, "pat_cr": pat,
            "pbt_cr": pbt, "depreciation_cr": dep, "eps_basic": eps}


def company(cons=True, scale=1.0, quarters=QUARTERS):
    """PAT 10, 9, 8, … newest first; PBT 2 more than PAT; depreciation 1; FY26 PAT 40 EPS 8, FY25 PAT 30 EPS 6 (× scale)."""
    rows = [row(d, (10 - i) * scale, cons=cons, pbt=(12 - i) * scale, dep=1.0) for i, d in enumerate(quarters)]
    rows += [row("2026-03-31", 40.0 * scale, ptype="annual", cons=cons, eps=8.0 * scale),
             row("2025-03-31", 30.0 * scale, ptype="annual", cons=cons, eps=6.0 * scale)]
    return rows


FULL = {"q_pat": 10.0, "q1_pat": 9.0, "q4_pat": 6.0, "q_pbdt": 13.0, "ttm_pat": 34.0, "y_pat": 40.0, "y_eps": 8.0, "py_eps": 6.0}


# ── the per-company rules (the SQL behind the owner's 2 Nov tables) ──────────────────────────────────────────────────
def test_a_full_company_gives_every_field():
    vals, q_end = sd.company_results(list(reversed(company())))            # any input order
    assert vals == FULL and q_end == "2026-09-30"


def test_consolidated_wins_when_filed_else_standalone():
    assert sd.company_results(company(cons=True) + company(cons=False, scale=2))[0] == FULL
    standalone, _ = sd.company_results(company(cons=False, scale=2))
    assert standalone["q_pat"] == 20.0 and standalone["y_eps"] == 16.0


def test_any_consolidated_row_of_a_type_picks_consolidated_for_that_type_only():
    # The SQL's rule: one consolidated quarterly row anywhere in the history makes the company 'consolidated' for quarters,
    # while its annual rows (standalone only) are read separately.
    rows = [r for r in company(cons=False, scale=2) if r["period_type"] == "quarterly"]
    rows += [row("2024-12-31", 99.0, cons=True)]
    rows += [row("2026-03-31", 80.0, ptype="annual", cons=False, eps=16.0)]
    vals, q_end = sd.company_results(rows)
    assert q_end == "2024-12-31" and vals["q_pat"] == 99.0 and "q1_pat" not in vals and "ttm_pat" not in vals
    assert vals["y_pat"] == 80.0 and vals["y_eps"] == 16.0 and "py_eps" not in vals


def test_a_missing_quarter_breaks_the_one_and_four_quarters_ago_and_ttm_rules():
    gappy = [q for q in QUARTERS if q != "2026-06-30"]                    # rn2 is 6 months back, rn5 is 15 months back
    vals, _ = sd.company_results(company(quarters=gappy))
    assert vals["q_pat"] == 10.0
    assert "q1_pat" not in vals and "q4_pat" not in vals and "ttm_pat" not in vals


def test_quarter_gap_bounds():
    rows = [row("2026-09-30", 5.0), row("2026-07-02", 4.0)]               # 90 days: inside 80-100
    assert sd.company_results(rows)[0]["q1_pat"] == 4.0
    rows = [row("2026-09-30", 5.0), row("2026-07-20", 4.0)]               # 72 days: outside
    assert "q1_pat" not in sd.company_results(rows)[0]


def test_ttm_needs_four_numbers():
    rows = company()
    rows[2]["pat_cr"] = None                                               # rn3 has no PAT
    vals, _ = sd.company_results(rows)
    assert "ttm_pat" not in vals and vals["q_pat"] == 10.0
    assert "ttm_pat" not in sd.company_results(company(quarters=QUARTERS[:3]))[0]


def test_missing_figures_stay_missing_never_zero():
    rows = company()
    rows[0].update(pat_cr=None, pbt_cr=None)                               # rn1: no PAT, no PBT
    rows[6]["eps_basic"] = "n/a"                                           # FY26 EPS not a number
    vals, q_end = sd.company_results(rows)
    assert q_end == "2026-09-30"
    assert "q_pat" not in vals and "q_pbdt" not in vals and "ttm_pat" not in vals and "y_eps" not in vals
    assert vals["py_eps"] == 6.0 and vals["y_pat"] == 40.0
    no_dep = company()
    no_dep[0]["depreciation_cr"] = None                                     # PBDT = PBT when depreciation is not filed
    assert sd.company_results(no_dep)[0]["q_pbdt"] == 12.0
    flag = company()
    flag[0]["pat_cr"] = True                                               # a boolean is not a number
    assert "q_pat" not in sd.company_results(flag)[0]


def test_no_rows_no_fields():
    assert sd.company_results([]) == ({}, None)
    assert sd.company_results([{"period_type": "quarterly", "consolidated": None, "period_end": "2026-09-30", "pat_cr": 1}]) == ({}, None)


# ── the loader ───────────────────────────────────────────────────────────────────────────────────────────────────
class FakeDaas:
    """MOCK DaaS /financials/{symbol}: per-symbol rows, a symbol in `fail` raises, every call is recorded."""

    def __init__(self, books, fail=(), down=False):
        self.books, self.fail, self.down, self.calls = books, set(fail), down, []

    async def get(self, path, params=None, timeout=None):
        self.calls.append(path)
        await asyncio.sleep(0)
        if self.down:
            raise RuntimeError("daas down")
        assert path.startswith("/financials/") and params == {"limit": sd.RESULTS_ROWS}
        sym = path[len("/financials/"):]
        if sym in self.fail:
            raise RuntimeError("HTTP 500")
        return {"data": self.books.get(sym, []), "count": len(self.books.get(sym, []))}

    async def post(self, path, body, timeout=None):
        raise RuntimeError("no prices in this fake")


BOOKS = {"AAA": company(), "M%26M": company(cons=False, scale=2), "NOFIN": []}
SYMS = ["AAA", "M&M", "NOFIN"]


def panel(symbols):
    n = len(symbols)
    ones = np.ones((1, n))
    return sd.BasePanel(symbols=list(symbols), dates=np.array(["2026-11-02"], dtype="datetime64[D]"), open=ones, high=ones,
                        low=ones, close=ones, volume=ones, eod_date=date(2026, 11, 2))


def make(tmp_path, daas, symbols=SYMS, now=None):
    box = {"now": now or NOW, "clock": 0.0}
    d = sd.ScanData(daas_get=daas.get, daas_post=daas.post, cache_dir=tmp_path, clock=lambda: box["clock"],
                    now=lambda: box["now"])
    if symbols is not None:
        d._base, d._checked = panel(symbols), 0.0                         # a loaded panel: panel() answers from memory
    return d, box


@pytest.fixture(autouse=True)
def no_retry_pause(monkeypatch):
    monkeypatch.setattr(sd, "RESULTS_RETRY_S", 0.0)


def test_load_reads_every_company_once_encodes_symbols_and_skips_a_failing_one(tmp_path):
    daas = FakeDaas(BOOKS, fail={"BAD"})
    d, _ = make(tmp_path, daas, symbols=SYMS + ["BAD"])
    got = run(d.results_fields(wait=True))
    assert got.values["q_pat"] == {"AAA": 10.0, "M&M": 20.0}
    assert got.q_end == {"AAA": "2026-09-30", "M&M": "2026-09-30"}
    assert got.symbols == 2 and got.asked == 4
    assert sorted(daas.calls) == sorted(["/financials/AAA", "/financials/M%26M", "/financials/NOFIN", "/financials/BAD",
                                         "/financials/BAD"])                # one retry for the failing company
    assert got.complete is False and any("1 of 4 companies could not be read" in w for w in got.warnings)
    assert got.loaded_at == NOW.isoformat() and "loaded 03 Nov 2026 09:30 IST" in got.source
    assert set(got.values) == set(sd.RESULT_FIELDS)
    assert (tmp_path / sd.RESULTS_FILE).exists()


def test_wait_false_answers_none_during_the_first_load_then_the_copy(tmp_path):
    daas = FakeDaas(BOOKS)

    async def go():
        d, _ = make(tmp_path, daas)
        first = await d.results_fields()                                   # starts the load, answers at once
        got = await d.results_fields(wait=True)                            # awaits that same load
        again = await d.results_fields()                                   # fresh in memory: no call
        return first, got, again

    first, got, again = run(go())
    assert first is None and got is again and got.symbols == 2 and got.complete is True and not got.warnings
    assert len(daas.calls) == 3                                            # one load, one call per company


def test_two_concurrent_waits_share_one_load(tmp_path):
    daas = FakeDaas(BOOKS)

    async def go():
        d, _ = make(tmp_path, daas)
        return await asyncio.gather(d.results_fields(wait=True), d.results_fields(wait=True))

    a, b = run(go())
    assert a is b and len(daas.calls) == 3


def test_a_second_worker_reads_the_file_and_asks_nothing(tmp_path):
    d1, _ = make(tmp_path, FakeDaas(BOOKS))
    got1 = run(d1.results_fields(wait=True))
    other = FakeDaas(BOOKS, down=True)
    d2, _ = make(tmp_path, other, symbols=None)                            # no panel either: the file is enough
    got2 = run(d2.results_fields())
    assert other.calls == [] and got2 is not None
    assert got2.values == got1.values and got2.q_end == got1.q_end and got2.loaded_at == got1.loaded_at


def test_workers_loading_at_once_ask_daas_once(tmp_path):
    daas = FakeDaas(BOOKS)

    async def go():
        d1, _ = make(tmp_path, daas)
        d2, _ = make(tmp_path, daas)
        return await asyncio.gather(d1.results_fields(wait=True), d2.results_fields(wait=True))

    a, b = run(go())
    assert a.values == b.values and len(daas.calls) == 3                 # the second waited on the lock and read the file


def test_the_copy_is_refreshed_after_its_ttl_and_the_old_one_is_served_meanwhile(tmp_path):
    daas = FakeDaas(BOOKS)

    async def go():
        d, box = make(tmp_path, daas)
        old = await d.results_fields(wait=True)
        box["now"] = NOW + timedelta(hours=5)
        within = await d.results_fields()                                   # still fresh: no call
        calls_within = len(daas.calls)
        daas.books = {**BOOKS, "AAA": company(scale=3)}
        box["now"] = NOW + timedelta(seconds=sd.RESULTS_TTL_S + 1)
        meanwhile = await d.results_fields()                                # stale: the old copy, refresh started
        new = await d.results_fields(wait=True)
        return old, within, calls_within, meanwhile, new

    old, within, calls_within, meanwhile, new = run(go())
    assert within is old and calls_within == 3
    assert meanwhile is old
    assert new.values["q_pat"]["AAA"] == 30.0 and new.loaded_at != old.loaded_at and len(daas.calls) == 6


def test_a_partial_copy_is_refreshed_sooner(tmp_path):
    daas = FakeDaas(BOOKS, fail={"NOFIN"})                                  # 1 of 3 unreadable: not complete

    async def go():
        d, box = make(tmp_path, daas)
        first = await d.results_fields(wait=True)
        box["now"] = NOW + timedelta(seconds=sd.RESULTS_PARTIAL_TTL_S + 1)
        daas.fail = set()
        second = await d.results_fields(wait=True)
        return first, second

    first, second = run(go())
    assert first.complete is False and second.complete is True and second.loaded_at != first.loaded_at


def test_no_stock_list_means_a_failed_copy_and_a_pause_before_the_next_attempt(tmp_path):
    daas = FakeDaas(BOOKS)

    async def go():
        d, box = make(tmp_path, daas, symbols=None)                         # panel() must load prices: the fake refuses
        failed = await d.results_fields(wait=True)
        again = await d.results_fields()                                     # within the backoff: no new attempt
        task_after_backoff_check = d._results_task
        box["clock"] = sd.RESULTS_FAIL_BACKOFF_S + 1
        d._base, d._checked = panel(SYMS), box["clock"]
        later = await d.results_fields(wait=True)
        return failed, again, task_after_backoff_check, later

    failed, again, task, later = run(go())
    assert failed.symbols == 0 and "the stock list is unavailable" in failed.warnings[0]
    assert again is failed and task.done()
    assert later.symbols == 2
    assert not (tmp_path / "results.json.tmp").exists()


def test_a_failed_refresh_keeps_the_last_good_copy_and_says_so(tmp_path):
    daas = FakeDaas(BOOKS)

    async def go():
        d, box = make(tmp_path, daas)
        good = await d.results_fields(wait=True)
        daas.down = True
        box["now"] = NOW + timedelta(seconds=sd.RESULTS_TTL_S + 1)
        after = await d.results_fields(wait=True)
        return good, after

    good, after = run(go())
    assert after.values == good.values and after.loaded_at == good.loaded_at
    assert any("could not be loaded" in w for w in after.warnings)


def test_results_file_round_trip(tmp_path):
    rf = sd.ResultsFields(values={f: {} for f in sd.RESULT_FIELDS}, q_end={"AAA": "2026-09-30"}, loaded_at=NOW.isoformat(),
                          symbols=1, warnings=["w"], complete=False, asked=5)
    rf.values["q_pat"]["AAA"] = 1.5
    sd.save_results(rf, tmp_path)
    back = sd.read_results_file(tmp_path)
    assert back == rf
    (tmp_path / sd.RESULTS_FILE).write_text("{not json")
    assert sd.read_results_file(tmp_path) is None


# ── Kite REST quotes: the day's platform token is reloaded before a fetch (live 3 Nov 09:23 IST: TokenException) ───────
class TokenKite:
    """MOCK Kite: answers quote() only with the day's token, like Kite refusing a replaced token."""

    def __init__(self, token, log):
        self.token, self.log = token, log

    def quote(self, keys):
        self.log.append((self.token, list(keys)))
        if self.token != "day":
            raise RuntimeError("TokenException")
        return {k: {"last_price": 10.0, "ohlc": {"open": 9.5, "high": 10.5, "low": 9.0, "close": 9.8}, "volume": 100,
                    "timestamp": "2026-11-03 09:29:59"} for k in keys}


def token_rest(refresher, token_box, t):
    log = []

    async def sleep(s):
        t["v"] += s
    r = sd.RestQuotes(token_getter=lambda: token_box["tok"], key_getter=lambda: "key",
                      kite_factory=lambda k, tok: TokenKite(tok, log), clock=lambda: t["v"], wall=lambda: NOW, sleep=sleep,
                      token_refresher=refresher)
    return r, log


def test_a_stale_token_is_reloaded_once_then_quote_succeeds_and_the_reload_is_throttled():
    box, t, reloads = {"tok": "stale"}, {"v": 0.0}, []

    async def reload():
        reloads.append(t["v"])
        box["tok"] = "day"
    r, log = token_rest(reload, box, t)
    out, why = run(r.get(["AAA"], open_session=True))
    assert why is None and out["AAA"]["ltp"] == 10.0
    assert reloads == [0.0] and log == [("day", ["NSE:AAA"])]
    t["v"] += 31                                                   # the copy is stale (30 s), the reload is not due (300 s)
    run(r.get(["AAA"], open_session=True))
    assert reloads == [0.0] and len(log) == 2
    t["v"] = 0.0 + sd.RestQuotes.TOKEN_REFRESH_S + 1
    run(r.get(["AAA"], open_session=True))
    assert reloads == [0.0, sd.RestQuotes.TOKEN_REFRESH_S + 1] and len(log) == 3


def test_no_reload_while_the_copies_are_fresh_or_kite_is_backed_off():
    box, t, reloads = {"tok": "stale"}, {"v": 0.0}, []

    async def reload():
        reloads.append(t["v"])                                     # the stored token is no better: Kite refuses
    r, log = token_rest(reload, box, t)
    assert run(r.get(["AAA"], open_session=True)) == ({}, "kite_refused")
    t["v"] += 5                                                    # inside the 30 s back-off: no fetch, no reload
    assert run(r.get(["AAA"], open_session=True)) == ({}, "kite_refused")
    assert reloads == [0.0] and len(log) == 1


def test_a_failing_reload_never_stops_the_quotes(caplog):
    t = {"v": 0.0}

    async def boom():
        raise RuntimeError("mongo down")
    r, log = token_rest(boom, {"tok": "day"}, t)
    with caplog.at_level("WARNING"):
        out, why = run(r.get(["AAA"], open_session=True))
    assert why is None and out["AAA"]["ltp"] == 10.0
    assert "platform Kite token could not be reloaded (RuntimeError)" in caplog.text and "day" not in caplog.text


def test_the_default_reload_is_on_only_with_the_default_token_getter():
    assert sd.RestQuotes()._refresh is sd._refresh_platform_token
    assert sd.RestQuotes(token_getter=lambda: "x")._refresh is None
    assert sd.RestQuotes(token_getter=lambda: "x", token_refresher=sd._refresh_platform_token)._refresh is sd._refresh_platform_token


def test_the_default_reload_logs_and_never_raises(monkeypatch, caplog):
    import sys
    monkeypatch.setitem(sys.modules, "deps", None)                 # no app database here: the import fails
    with caplog.at_level("WARNING"):
        assert run(sd._refresh_platform_token()) is None
    assert "platform Kite token could not be reloaded" in caplog.text
