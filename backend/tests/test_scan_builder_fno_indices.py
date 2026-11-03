"""Scan dashboard data: the F&O fields (TC-F1) and the Index stats widget (TC-I1) of test_reports/scan_builder_20261103_0431.md.

MOCK — not real data. DaaS answers, Kite quotes and the trading-day window below are hand-written to the contract
(docs/scan_builder/DESIGN.md §7.3, §7.4); the symbols and figures are invented.
"""
import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timezone

from services.scan_builder import data as sd
from services.scan_builder import indices

NOW = datetime(2026, 11, 3, 4, 0, tzinfo=timezone.utc)          # Tue 3 Nov 2026, 09:30 IST


@dataclass(frozen=True)
class FakeWindow:
    """MOCK market_freshness.Window: data on or after `floor` is current."""
    floor: date

    def current(self, day):
        return day is not None and date.fromisoformat(str(day)[:10]) >= self.floor

    def stale_reason(self, what, day):
        return f"No current data for {what}: the latest is {day}, older than the previous session ({self.floor.isoformat()})."


def window_from(floor):
    async def read(now):
        return FakeWindow(floor)
    return read


class FnoDaas:
    """MOCK DaaS /desk/fno-buildup: `days` maps an ISO day to its rows; no date = the latest day."""

    def __init__(self, latest, days, fail_on=None):
        self.latest, self.days, self.fail_on = latest, days, fail_on
        self.calls = []

    async def get(self, path, params=None, timeout=None):
        assert path == "/desk/fno-buildup", path
        day = (params or {}).get("date")
        self.calls.append(day)
        if self.fail_on is not None and day == self.fail_on:
            raise RuntimeError("daas down")
        key = day or self.latest
        return {"as_of": key, "rows": self.days.get(key, [])}

    async def post(self, path, body, timeout=None):
        raise AssertionError("no POST expected")


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(daas, floor=date(2026, 11, 2), clock=None, tmp=None):
    return sd.ScanData(daas_get=daas.get, daas_post=daas.post, cache_dir=tmp, now=lambda: NOW,
                       clock=clock or Clock(), freshness=window_from(floor))


ROWS_MON = [  # Mon 2 Nov
    {"symbol": "AAA", "price_chg_pct": 2.5, "oi_chg_pct": 8.0},
    {"symbol": "BBB", "price_chg_pct": -1.0, "oi_chg_pct": None},
    {"symbol": "CCC", "price_chg_pct": None, "oi_chg_pct": 3.0},
]
ROWS_FRI = [  # Fri 30 Oct
    {"symbol": "AAA", "price_chg_pct": -0.5, "oi_chg_pct": 1.0},
    {"symbol": "CCC", "price_chg_pct": 1.5, "oi_chg_pct": -2.0},
]


# ── TC-F1 ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_f1_fields_from_latest_and_previous_session_over_a_weekend(tmp_path):
    daas = FnoDaas("2026-11-02", {"2026-11-02": ROWS_MON, "2026-10-30": ROWS_FRI})
    f = asyncio.run(make(daas, tmp=tmp_path).fno_fields())
    assert f.as_of == "2026-11-02" and f.prev_as_of == "2026-10-30"
    # the walk back skipped Sat 31 Oct and Sun 1 Nov: latest, then Fri only
    assert daas.calls == [None, "2026-10-30"]
    assert f.values["fno_price_chg_pct"] == {"AAA": 2.5, "BBB": -1.0}          # CCC's null stays missing
    assert f.values["fno_oi_chg_pct"] == {"AAA": 8.0, "CCC": 3.0}              # BBB's null stays missing
    assert f.values["fno_prev_price_chg_pct"] == {"AAA": -0.5, "CCC": 1.5}
    assert f.values["fno_prev_oi_chg_pct"] == {"AAA": 1.0, "CCC": -2.0}
    assert f.warnings == []
    assert "02 Nov 2026" in f.source and "session before: 30 Oct 2026" in f.source


def test_f1_previous_session_walk_skips_a_holiday(tmp_path):
    # Fri 30 Oct is a holiday (no rows): the session before Mon 2 Nov is Thu 29 Oct.
    daas = FnoDaas("2026-11-02", {"2026-11-02": ROWS_MON, "2026-10-29": ROWS_FRI})
    f = asyncio.run(make(daas, tmp=tmp_path).fno_fields())
    assert f.prev_as_of == "2026-10-29"
    assert daas.calls == [None, "2026-10-30", "2026-10-29"]
    assert f.values["fno_prev_oi_chg_pct"] == {"AAA": 1.0, "CCC": -2.0}


def test_f1_stale_latest_session_gives_no_values_and_says_why(tmp_path):
    # Today's window floor is Mon 2 Nov; DaaS's latest is Thu 29 Oct -> stale, nothing used.
    daas = FnoDaas("2026-10-29", {"2026-10-29": ROWS_MON})
    f = asyncio.run(make(daas, floor=date(2026, 11, 2), tmp=tmp_path).fno_fields())
    assert f.values == {} and f.as_of == "2026-10-29" and f.prev_as_of is None and f.source is None
    assert len(f.warnings) == 1 and "the F&O fields" in f.warnings[0] and "2026-10-29" in f.warnings[0]
    assert daas.calls == [None]                                                 # no walk back for a stale day


def test_f1_daas_failure_never_raises(tmp_path):
    daas = FnoDaas("2026-11-02", {}, fail_on=None)

    async def boom(path, params=None, timeout=None):
        raise RuntimeError("daas down")
    daas.get = boom
    f = asyncio.run(make(daas, tmp=tmp_path).fno_fields())
    assert f.values == {} and f.as_of is None
    assert f.warnings == ["The F&O fields are not available: the F&O data could not be read."]


def test_f1_previous_session_failure_keeps_latest_fields(tmp_path):
    daas = FnoDaas("2026-11-02", {"2026-11-02": ROWS_MON}, fail_on="2026-10-30")
    f = asyncio.run(make(daas, tmp=tmp_path).fno_fields())
    assert f.values["fno_price_chg_pct"] == {"AAA": 2.5, "BBB": -1.0}
    assert f.values["fno_prev_price_chg_pct"] == {} and f.prev_as_of is None
    assert len(f.warnings) == 1 and "session before" in f.warnings[0]


def test_f1_empty_latest_rows(tmp_path):
    daas = FnoDaas("2026-11-02", {"2026-11-02": []})
    f = asyncio.run(make(daas, tmp=tmp_path).fno_fields())
    assert f.values == {} and f.warnings and "no stock-futures rows" in f.warnings[0]


def test_f1_cached_within_ttl_then_reloaded(tmp_path):
    clock = Clock()
    daas = FnoDaas("2026-11-02", {"2026-11-02": ROWS_MON, "2026-10-30": ROWS_FRI})
    d = make(daas, clock=clock, tmp=tmp_path)

    async def go():
        a = await d.fno_fields()
        clock.t += sd.FNO_TTL_S - 1
        b = await d.fno_fields()
        assert b is a and len(daas.calls) == 2                                  # served from the cache
        clock.t += 2
        c = await d.fno_fields()
        assert c is not a and len(daas.calls) == 4                              # reloaded after the TTL
    asyncio.run(go())


def test_f1_concurrent_callers_share_one_load(tmp_path):
    daas = FnoDaas("2026-11-02", {"2026-11-02": ROWS_MON, "2026-10-30": ROWS_FRI})
    d = make(daas, tmp=tmp_path)

    async def go():
        return await asyncio.gather(*(d.fno_fields() for _ in range(5)))
    res = asyncio.run(go())
    assert all(r is res[0] for r in res) and daas.calls == [None, "2026-10-30"]


# ── TC-I1 ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def quotes_fn(answer):
    seen = {}

    async def day_quotes(symbols, now=None):
        seen["symbols"] = list(symbols)
        return answer
    return day_quotes, seen


def test_i1_live_quotes_rows_in_order_with_short_names():
    dq, seen = quotes_fn({"source": "kite_live", "day": "2026-11-03", "as_of": "2026-11-03T04:45:32+00:00", "why": None,
                          "quotes": {"NIFTY 50": {"ltp": 23440.8, "close": 23053.5},
                                     "NIFTY BANK": {"ltp": 55002.2, "close": 54684.25}}})
    r = asyncio.run(indices.index_result(["NIFTY BANK", "Nifty 50"], day_quotes=dq))
    assert seen["symbols"] == ["NIFTY BANK", "NIFTY 50"]                       # canonical feed keys, order kept
    assert r["ok"] is True and r["kind"] == "indices" and r["group_by"] == "symbol"
    assert r["basis"] == {"mode": "live", "day": "2026-11-03", "quote_as_of": "2026-11-03T04:45:32+00:00",
                          "text": "Kite live 10:15:32 IST"}
    assert r["columns"] == [{"id": "ltp", "alias": "LTP", "format": "price"}, {"id": "chg", "alias": "% chg", "format": "pct"}]
    assert [x["symbol"] for x in r["rows"]] == ["BANKNIFTY", "NIFTY"]
    assert r["rows"][0] == {"symbol": "BANKNIFTY", "name": "NIFTY BANK", "values": [55002.2, round((55002.2 - 54684.25) / 54684.25 * 100, 2)],
                            "today": "live"}
    assert r["rows"][1]["values"] == [23440.8, 1.68]
    assert r["counts"] == {"matched": 2} and r["warnings"] == []


def test_i1_kite_close_after_the_session():
    dq, _ = quotes_fn({"source": "kite_close", "day": "2026-11-02", "as_of": "2026-11-02T10:00:05+00:00", "why": None,
                       "quotes": {"NIFTY 50": {"ltp": 100.0, "close": 0}}})
    r = asyncio.run(indices.index_result(["NIFTY 50"], day_quotes=dq))
    assert r["basis"]["mode"] == "kite_close" and r["basis"]["text"] == "Kite close, 02 Nov 2026"
    assert r["rows"] == [{"symbol": "NIFTY", "name": "NIFTY 50", "values": [100.0, None], "today": "kite_close"}]  # no prev close


def test_i1_no_quotes_says_why():
    dq, _ = quotes_fn({"source": None, "day": "2026-11-03", "as_of": None, "why": "feed_not_live", "quotes": {}})
    r = asyncio.run(indices.index_result(["NIFTY 50", "NIFTY BANK"], day_quotes=dq))
    assert r["basis"]["mode"] == "none"
    assert r["basis"]["text"] == "Index quotes are not available (the Kite live feed is not running)"
    assert r["rows"] == [] and r["counts"] == {"matched": 0} and r["warnings"] == []


def test_i1_a_name_without_a_quote_is_left_out_and_named():
    dq, _ = quotes_fn({"source": "kite_live", "day": "2026-11-03", "as_of": None, "why": None,
                       "quotes": {"NIFTY 50": {"ltp": 23440.8, "close": 23053.5}}})
    r = asyncio.run(indices.index_result(["NIFTY 50", "NIFTY MIDCAP SELECT"], day_quotes=dq))
    assert [x["symbol"] for x in r["rows"]] == ["NIFTY"]
    assert r["basis"]["text"] == "Kite live"
    assert r["warnings"] == ["No Kite quote for NIFTY MID SELECT on 03 Nov 2026; left out."]


# ── TC-I1: the index reader itself (Kite sends no volume for an index) ────────────────────────────────────────────────

class FakeFeed:
    """MOCK live feed: a saved close doc and a live snapshot, as services.kite_live_feed.feed stores them."""

    def __init__(self, close=None, snap=None, status=None):
        self.close, self.snap, self.status = close, snap, status

    async def read_close(self, day):
        return self.close if self.close and self.close.get("day") == day else None

    async def read_snapshot(self):
        return self.snap

    async def read_status(self):
        return self.status


IDX_CLOSE = {"day": "2026-11-02", "data_at": "2026-11-02T10:01:14+00:00", "quotes": [
    {"symbol": "NIFTY 50", "ltp": 23440.8, "close": 23053.1, "exchange_ts": "2026-11-02T15:31:11+05:30", "volume": None},
    {"symbol": "NIFTY BANK", "ltp": 55002.2, "close": 54686.95, "exchange_ts": "2026-11-02T15:31:11+05:30", "volume": None},
    {"symbol": "NIFTY IT", "ltp": 30000.0, "close": 29900.0, "exchange_ts": "2026-10-30T15:31:11+05:30", "volume": None},
]}
PRE_OPEN = datetime(2026, 11, 3, 3, 30, tzinfo=timezone.utc)                      # 09:00 IST, before the session


def test_i1_saved_close_indices_without_volume_are_kept():
    got = asyncio.run(indices.index_day_quotes(["NIFTY 50", "Nifty Bank"], now=PRE_OPEN, feed=FakeFeed(close=IDX_CLOSE)))
    assert got["source"] == "kite_close" and got["day"] == "2026-11-02" and got["why"] is None
    assert sorted(got["quotes"]) == ["NIFTY 50", "NIFTY BANK"]


def test_i1_an_index_stamped_on_another_day_is_dropped():
    got = asyncio.run(indices.index_day_quotes(["NIFTY IT"], now=PRE_OPEN, feed=FakeFeed(close=IDX_CLOSE)))
    assert got["quotes"] == {}


def test_i1_no_saved_close_and_unreadable_feed():
    got = asyncio.run(indices.index_day_quotes(["NIFTY 50"], now=PRE_OPEN, feed=FakeFeed(close=None)))
    assert got["why"] == "no_saved_close" and got["quotes"] == {}

    class Broken(FakeFeed):
        async def read_close(self, day):
            raise RuntimeError("redis down")
    got = asyncio.run(indices.index_day_quotes(["NIFTY 50"], now=PRE_OPEN, feed=Broken()))
    assert got["why"] == "unreadable" and got["quotes"] == {}


def test_i1_index_result_end_to_end_on_a_saved_close():
    async def dq_(names, now=None):
        return await indices.index_day_quotes(names, now=PRE_OPEN, feed=FakeFeed(close=IDX_CLOSE))
    r = asyncio.run(indices.index_result(["NIFTY BANK", "NIFTY 50"], day_quotes=dq_))
    assert r["basis"]["text"] == "Kite close, 02 Nov 2026"
    assert r["rows"] == [
        {"symbol": "BANKNIFTY", "name": "NIFTY BANK", "values": [55002.2, 0.58], "today": "kite_close"},
        {"symbol": "NIFTY", "name": "NIFTY 50", "values": [23440.8, 1.68], "today": "kite_close"},
    ]


def test_i1_live_feed_not_fresh_says_why():
    live_now = datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc)                   # 10:30 IST, in session
    feed = FakeFeed(snap={"data_at": "2026-11-03T03:00:00+00:00", "quotes": []}, status={"state": "stopped"})
    got = asyncio.run(indices.index_day_quotes(["NIFTY 50"], now=live_now, feed=feed))
    assert got["source"] is None and got["why"] == "feed_not_live"
