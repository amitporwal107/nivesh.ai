"""Scan Builder data layer (services/scan_builder/data.py): TC-U17 … TC-U20 of test_reports/scan_builder_20261103_0431.md.

No network, no Mongo, no Kite: DaaS, the live feed's day quotes, holidays, the Kite client and the clocks are injected.
Every figure below is hand-made test input (MOCK — not real data)."""
import asyncio
from datetime import date, datetime, timezone

import numpy as np
import pytest

from services.scan_builder import data as sd

IST_OPEN = datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc)        # 10:30 IST Tuesday: session open
IST_EVENING = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)    # 17:30 IST: after the close
IST_PREOPEN = datetime(2026, 11, 3, 2, 0, tzinfo=timezone.utc)     # 07:30 IST: before the open


def run(coro):
    return asyncio.run(coro)


def bars(sym, days, closes, vol=1000):
    return [{"symbol": sym, "as_of_date": d, "adj_open": c - 1, "adj_high": c + 2, "adj_low": c - 2, "adj_close": c,
             "adj_volume": vol} for d, c in zip(days, closes)]


DAYS = ["2026-10-29", "2026-10-30", "2026-11-02"]
ROWS = {"AAA": bars("AAA", DAYS, [100.0, 101.0, 102.0]),
        "BBB": bars("BBB", DAYS[:2], [50.0, 51.0]),                     # not traded on the last day
        "CCC": bars("CCC", DAYS, [10.0, 10.5, 11.0])}


class FakeDaas:
    """MOCK DaaS: universe, screener, constituents and the bulk endpoint, counting calls."""

    def __init__(self, rows=None, fail=False):
        self.rows = rows if rows is not None else ROWS
        self.fail = fail
        self.bulk_calls = []
        self.gets = []

    async def get(self, path, params=None, timeout=None):
        self.gets.append(path)
        if self.fail:
            raise RuntimeError("daas down")
        if path == "/symbols/universe":
            return {"data": [{"symbol": "AAA", "company_name": "Aaa Ltd", "fno_eligible": True, "last_price_date": "2026-11-02"},
                             {"symbol": "BBB", "company_name": "Bbb Ltd", "fno_eligible": False, "last_price_date": "2026-10-30"},
                             {"symbol": "CCC", "company_name": "Ccc Ltd", "fno_eligible": False, "last_price_date": "2026-11-02"},
                             {"symbol": "OLD", "company_name": "Old Ltd", "fno_eligible": False, "last_price_date": "2025-01-02"}]}
        if path == "/stocks/screener":
            return {"as_of_date": "2026-11-02", "data": [{"symbol": "AAA", "pe_ttm": 12.5, "market_cap_cr": 20000, "sector": "IT"},
                                                          {"symbol": "CCC", "pe_ttm": None, "market_cap_cr": 500}]}
        if path.startswith("/indices/"):
            if "Nifty%2050" in path:
                return {"as_of": "2026-11-01", "data": [{"symbol": "AAA"}]}
            return {"as_of": "2026-11-01", "data": []}
        raise AssertionError(path)

    async def post(self, path, body, timeout=None):
        assert path == "/prices/adjusted/bulk"
        if self.fail:
            raise RuntimeError("daas down")
        self.bulk_calls.append(body)
        out = {}
        for s in body["symbols"]:
            rs = [r for r in self.rows.get(s, []) if (body.get("start") is None or r["as_of_date"] >= body["start"])
                  and (body.get("end") is None or r["as_of_date"] <= body["end"])]
            if rs:
                out[s] = rs
        return {"data": out}


def make(tmp_path, daas=None, *, now=IST_OPEN, quotes=None, holidays=None, rest=None, clock=None):
    daas = daas or FakeDaas()
    t = {"v": 0.0}
    seen = {}

    async def day_quotes(symbols, now=None):
        seen["symbols"] = list(symbols)
        return quotes if quotes is not None else {"source": None, "day": None, "as_of": None, "quotes": {}, "why": "feed_not_live"}

    async def hol(a, b):
        return holidays

    d = sd.ScanData(daas_get=daas.get, daas_post=daas.post, cache_dir=tmp_path, clock=clock or (lambda: t["v"]),
                    now=lambda: now, day_quotes=day_quotes, holidays=hol, rest=rest or StubRest({}),
                    probe_symbols=("AAA", "CCC"))
    return d, daas, t, seen


class StubRest:
    def __init__(self, quotes, why=None):
        self.quotes, self.why, self.asked, self.calls, self.last_fetch_at = quotes, why, [], 0, None

    async def get(self, symbols, *, open_session):
        self.asked.append(list(symbols))
        return {s: q for s, q in self.quotes.items() if s in symbols}, self.why


def q(ltp, prev, day="2026-11-03", vol=5000, o=None):
    return {"ltp": ltp, "open": o or prev, "high": max(ltp, prev) + 1, "low": min(ltp, prev) - 1, "close": prev,
            "volume": vol, "exchange_ts": f"{day}T10:29:00+05:30"}


# ── TC-U17 panel build ────────────────────────────────────────────────────────────────────────────────────────────
def test_build_panel_aligns_days_and_marks_missing_bars():
    p = sd.build_panel(ROWS, ["AAA", "BBB", "CCC"])
    assert [str(x) for x in p.dates] == DAYS and p.eod_date == date(2026, 11, 2)
    assert p.close[:, 0].tolist() == [100.0, 101.0, 102.0]
    assert np.isnan(p.close[-1, 1]) and p.close[1, 1] == 51.0          # BBB: no bar on the last day
    assert p.open[0, 2] == 9.0 and p.high[0, 2] == 12.0 and p.volume[2, 0] == 1000
    assert p.index == {"AAA": 0, "BBB": 1, "CCC": 2}


def test_a_row_without_a_positive_close_is_no_bar():
    rows = {"AAA": [{"as_of_date": "2026-11-02", "adj_open": 1, "adj_high": 1, "adj_low": 1, "adj_close": None, "adj_volume": 5}],
            "CCC": bars("CCC", ["2026-11-02"], [11.0])}
    p = sd.build_panel(rows, ["AAA", "CCC"])
    assert [str(x) for x in p.dates] == ["2026-11-02"]
    assert np.isnan(p.close[0, 0]) and np.isnan(p.volume[0, 0]) and p.close[0, 1] == 11.0


def test_panel_file_round_trip(tmp_path):
    p = sd.build_panel(ROWS, ["AAA", "BBB", "CCC"])
    sd.save_panel(p, tmp_path)
    back = sd.load_panel_file(tmp_path)
    assert back.symbols == p.symbols and back.eod_date == p.eod_date
    assert np.allclose(back.close, p.close, equal_nan=True) and np.allclose(back.volume, p.volume, equal_nan=True)
    assert sd.read_meta(tmp_path)["eod_date"] == "2026-11-02"


# ── TC-U20 one DaaS load shared by the workers ────────────────────────────────────────────────────────────────────
def test_first_worker_loads_from_daas_and_writes_the_file_the_second_reads_it(tmp_path):
    d1, daas1, _, _ = make(tmp_path)
    p1 = run(d1.panel())
    assert d1.panel_source == "daas" and p1.symbols == ["AAA", "BBB", "CCC"]   # OLD (stale since 2025) is left out
    loads1 = [b for b in daas1.bulk_calls if b["start"] == "2024-04-01"]
    assert len(loads1) == 1
    d2, daas2, _, _ = make(tmp_path)                                         # another worker, same container folder
    p2 = run(d2.panel())
    assert d2.panel_source == "file"
    assert [b for b in daas2.bulk_calls if b["start"] == "2024-04-01"] == []  # only the cheap probe went to DaaS
    assert np.allclose(p1.close, p2.close, equal_nan=True)


def test_within_the_check_interval_the_panel_is_served_from_memory_without_any_call(tmp_path):
    d, daas, t, _ = make(tmp_path)
    run(d.panel())
    n = len(daas.bulk_calls)
    t["v"] = sd.PANEL_CHECK_S - 1
    run(d.panel())
    assert d.panel_source == "memory" and len(daas.bulk_calls) == n


def test_a_newer_eod_day_reloads_the_panel(tmp_path):
    rows = {k: list(v) for k, v in ROWS.items()}
    daas = FakeDaas(rows=rows)
    d, _, t, _ = make(tmp_path, daas)
    assert run(d.panel()).eod_date == date(2026, 11, 2)
    rows["AAA"] = rows["AAA"] + bars("AAA", ["2026-11-03"], [103.0])
    t["v"] = sd.PANEL_CHECK_S + 1
    p = run(d.panel())
    assert p.eod_date == date(2026, 11, 3) and d.panel_source == "daas"


def test_daas_down_without_any_copy_is_data_unavailable(tmp_path):
    d, _, _, _ = make(tmp_path, FakeDaas(fail=True))
    with pytest.raises(sd.DataUnavailable):
        run(d.panel())


def test_daas_down_later_keeps_the_panel_in_memory(tmp_path):
    daas = FakeDaas()
    d, _, t, _ = make(tmp_path, daas)
    run(d.panel())
    daas.fail = True
    t["v"] = sd.PANEL_CHECK_S + 1
    assert run(d.panel()).eod_date == date(2026, 11, 2) and d.panel_source == "memory"


def test_reference_reads_names_fno_members_and_fundamentals(tmp_path):
    d, _, _, _ = make(tmp_path)
    ref = run(d.reference())
    assert ref.names["AAA"] == "Aaa Ltd" and ref.fno == {"AAA"} and ref.members["nifty50"] == {"AAA"}
    assert ref.fundamentals["pe_ttm"] == {"AAA": 12.5} and ref.fundamentals["market_cap_cr"]["CCC"] == 500
    assert "sector" not in ref.fundamentals and ref.fundamentals_as_of == "2026-11-02"


# ── TC-U18 today's candle ─────────────────────────────────────────────────────────────────────────────────────────
def test_live_quotes_join_when_the_previous_close_matches(tmp_path):
    quotes = {"source": "kite_live", "day": "2026-11-03", "as_of": "2026-11-03T05:00:00+00:00",
              "quotes": {"AAA": q(104.0, 102.0), "CCC": q(11.5, 11.4)}, "why": None}     # CCC: 11.4 != 11.0 -> does not join
    d, _, _, seen = make(tmp_path, quotes=quotes)
    base = run(d.panel())
    ov = run(d.today(base, ["AAA", "CCC"]))
    assert ov.mode == "live" and ov.day == date(2026, 11, 3) and ov.session_open
    assert list(ov.bars) == [0] and ov.bars[0][3] == 104.0
    assert ov.counts["joined"] == 1 and ov.counts["does_not_join"] == 1
    assert any("previous close differs" in w for w in ov.warnings)


def test_stocks_outside_the_feed_get_rest_quotes(tmp_path):
    quotes = {"source": "kite_live", "day": "2026-11-03", "as_of": "x", "quotes": {"AAA": q(104.0, 102.0)}, "why": None}
    rest = StubRest({"CCC": q(11.2, 11.0)})
    d, _, _, _ = make(tmp_path, quotes=quotes, rest=rest)
    base = run(d.panel())
    ov = run(d.today(base, ["AAA", "CCC"]))
    assert rest.asked == [["CCC"]] and sorted(ov.bars) == [0, 2]
    assert ov.counts["feed_quotes"] == 1 and ov.counts["rest_quotes"] == 1


def test_a_rest_quote_from_another_day_is_not_used(tmp_path):
    quotes = {"source": "kite_live", "day": "2026-11-03", "as_of": "x", "quotes": {"AAA": q(104.0, 102.0)}, "why": None}
    rest = StubRest({"CCC": q(11.2, 11.0, day="2026-11-02")})
    d, _, _, _ = make(tmp_path, quotes=quotes, rest=rest)
    ov = run(d.today(run(d.panel()), ["AAA", "CCC"]))
    assert sorted(ov.bars) == [0]


def test_eod_already_in_means_no_overlay(tmp_path):
    d, _, _, seen = make(tmp_path, now=IST_PREOPEN)                    # last close = Mon 2 Nov, which the panel has
    ov = run(d.today(run(d.panel()), ["AAA"]))
    assert ov.mode == "eod" and ov.day == date(2026, 11, 2) and not ov.bars and "symbols" not in seen


def test_after_the_close_the_saved_kite_close_is_used(tmp_path):
    quotes = {"source": "kite_close", "day": "2026-11-03", "as_of": "2026-11-03T10:01:00+00:00",
              "quotes": {"AAA": q(103.0, 102.0)}, "why": None}
    d, _, _, _ = make(tmp_path, now=IST_EVENING, quotes=quotes)
    ov = run(d.today(run(d.panel()), ["AAA"]))
    assert ov.mode == "kite_close" and not ov.session_open and ov.bars[0][3] == 103.0


def test_no_quote_at_all_falls_back_to_the_eod_close_with_the_reason(tmp_path):
    d, _, _, _ = make(tmp_path, rest=StubRest({}, why="no_kite_token"))
    ov = run(d.today(run(d.panel()), ["AAA", "CCC"]))
    assert ov.mode == "eod" and ov.day == date(2026, 11, 2) and ov.session_open
    assert "Kite live feed is not live" in ov.warnings[0] and "2026-11-02 close" in ov.warnings[0]


def test_a_holiday_says_so(tmp_path):
    d, _, _, _ = make(tmp_path, holidays={date(2026, 11, 3)})
    ov = run(d.today(run(d.panel()), ["AAA"]))
    assert ov.mode == "eod" and "NSE holiday" in ov.warnings[0]


def test_a_missing_session_between_eod_and_today_is_not_bridged(tmp_path):
    rows = {"AAA": bars("AAA", ["2026-10-29", "2026-10-30"], [100.0, 101.0])}       # Mon 2 Nov missing, not a holiday
    quotes = {"source": "kite_live", "day": "2026-11-03", "as_of": "x", "quotes": {"AAA": q(104.0, 101.0)}, "why": None}
    daas = FakeDaas(rows=rows)
    d, _, _, _ = make(tmp_path, daas, quotes=quotes, holidays=set())
    base = sd.build_panel(rows, ["AAA"])
    ov = run(d.today(base, ["AAA"]))
    assert ov.mode == "eod" and not ov.bars and "missing" in ov.warnings[0]


# ── TC-U19 REST quote cache ───────────────────────────────────────────────────────────────────────────────────────
class FakeKite:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def quote(self, keys):
        self.calls.append(list(keys))
        if self.fail:
            raise RuntimeError("TokenException")
        return {k: {"last_price": 10.0, "ohlc": {"open": 9.5, "high": 10.5, "low": 9.0, "close": 9.8}, "volume": 100,
                    "timestamp": "2026-11-03 10:29:59"} for k in keys}


def rest_with(kite, token="tok", t=None):
    t = t if t is not None else {"v": 0.0}
    sleeps = []

    async def sleep(s):
        sleeps.append(s)
        t["v"] += s
    r = sd.RestQuotes(token_getter=lambda: token, key_getter=lambda: "key", kite_factory=lambda k, tok: kite,
                      clock=lambda: t["v"], wall=lambda: IST_OPEN, sleep=sleep)
    return r, t, sleeps


def test_rest_batches_of_500_spaced_at_least_1_1_s():
    kite = FakeKite()
    r, t, sleeps = rest_with(kite)
    syms = [f"S{i}" for i in range(1201)]
    out, why = run(r.get(syms, open_session=True))
    assert why is None and len(out) == 1201
    assert [len(c) for c in kite.calls] == [500, 500, 201] and kite.calls[0][0] == "NSE:S0"
    assert sleeps == pytest.approx([1.1, 1.1]) and r.calls == 3
    assert out["S0"]["ltp"] == 10.0 and out["S0"]["close"] == 9.8


def test_rest_copies_are_reused_within_the_ttl_and_refetched_after():
    kite = FakeKite()
    r, t, _ = rest_with(kite)
    run(r.get(["AAA"], open_session=True))
    t["v"] += 29
    run(r.get(["AAA"], open_session=True))
    assert len(kite.calls) == 1
    t["v"] += 2
    run(r.get(["AAA"], open_session=True))
    assert len(kite.calls) == 2


def test_rest_copies_fresh_when_asked_are_not_dropped_while_the_others_are_refetched():
    # Staging 3 Nov 09:39–09:41: the last batch of a fetch (~262 stocks) aged past the TTL WHILE the older batches were being
    # re-read, so every other refresh left those stocks without today's candle. Freshness is judged when the request starts.
    kite = FakeKite()
    r, t, sleeps = rest_with(kite)
    syms = [f"S{i}" for i in range(1201)]                     # batches of 500, 500, 201 at t = 0, 1.1, 2.2
    run(r.get(syms, open_session=True))
    t["v"] = 31.5                                             # batches 1-2 are stale (> 30 s), batch 3 is 29.3 s old
    out, why = run(r.get(syms, open_session=True))
    assert why is None and [len(c) for c in kite.calls[3:]] == [500, 500]     # only the stale batches are re-read …
    assert len(out) == 1201 and "S1200" in out                # … and batch 3, still fresh when asked, is in the answer


def test_rest_without_a_token_calls_nothing():
    kite = FakeKite()
    r, _, _ = rest_with(kite, token="")
    out, why = run(r.get(["AAA"], open_session=True))
    assert out == {} and why == "no_kite_token" and kite.calls == []


def test_rest_refusal_backs_off():
    kite = FakeKite(fail=True)
    r, t, _ = rest_with(kite)
    assert run(r.get(["AAA"], open_session=True)) == ({}, "kite_refused")
    t["v"] += 5
    assert run(r.get(["AAA"], open_session=True)) == ({}, "kite_refused")
    assert len(kite.calls) == 1                                                  # the back-off held
    t["v"] += 30
    run(r.get(["AAA"], open_session=True))
    assert len(kite.calls) == 2
