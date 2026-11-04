"""Early signals and trading plans of the Scan dashboard (services/scan_builder/signals.py, DESIGN.md §9).

All prices and stocks below are hand-made (MOCK — not real data)."""
import asyncio
import json
from datetime import datetime

import numpy as np
import pytest

from services.scan_builder import engine, indicators as I
from services.scan_builder import signals as SIG

IST = SIG.IST


def at(h, m, day=3):
    return datetime(2026, 11, day, h, m, tzinfo=IST)


@pytest.fixture(autouse=True)
def _clean():
    SIG._seen.clear()
    SIG._seen_strong.clear()
    yield
    SIG._seen.clear()
    SIG._seen_strong.clear()


# ── a list entry carries no plan (4 Nov: plans go to strong signals only, DESIGN.md §11) ─────────────────────────────

def test_a_list_entry_keeps_the_price_and_the_day_but_no_plan():
    p = SIG.list_entry("long", 100, 98, 101, 3)
    assert (p["entry"], p["day_low"], p["day_high"], p["atr"]) == (100.0, 98.0, 101.0, 3.0)
    assert (p["stop_loss"], p["target_1"], p["target_2"], p["plan_ok"]) == (None, None, None, False)
    assert p["plan_note"] == SIG.NO_PLAN_NOTE and "70" in p["plan_note"]


def test_no_barred_words_in_the_list_texts():
    import re
    text = json.dumps([SIG.list_entry(d, 100, 98, 101, 3) for d in ("long", "short")]) + SIG.RULES_TEXT
    assert not re.search(r"\b(buy\w*|sell\w*|recommend\w*|pick\w*|target\w*|entry|exit\w*)\b", SIG.RULES_TEXT, re.I)
    assert not re.search(r"\b(buy\w*|sell\w*|recommend\w*|pick\w*)\b", text, re.I)


# ── plan inputs come from the engine on the dashboard's panel ───────────────────────────────────────────────────────

def test_plan_inputs_are_the_engines_atr_and_previous_20_session_extremes():
    rng = np.random.RandomState(3)
    k, syms = 40, ["AAA", "BBB"]
    close = 100 + np.cumsum(rng.randn(k, 2), axis=0)
    high, low = close + rng.rand(k, 2) * 2, close - rng.rand(k, 2) * 2
    openp, vol = close + rng.randn(k, 2) * 0.3, np.full((k, 2), 1000.0)
    dates = np.arange(np.datetime64("2026-09-01"), np.datetime64("2026-09-01") + k)
    panel = engine.Panel(symbols=syms, dates=dates, open=openp, high=high, low=low, close=close, volume=vol)
    got = SIG.plan_inputs(panel, ["BBB", "ZZZ"])
    assert list(got) == ["BBB"]
    b = got["BBB"]
    assert b["atr"] == pytest.approx(I.atr(high, low, close, 14)[-2, 1])
    assert b["swing_high"] == pytest.approx(high[-21:-1, 1].max()) and b["swing_low"] == pytest.approx(low[-21:-1, 1].min())
    assert (b["close"], b["low"], b["high"]) == pytest.approx((close[-1, 1], low[-1, 1], high[-1, 1]))
    assert b["chg"] == pytest.approx((close[-1, 1] - close[-2, 1]) / close[-2, 1] * 100)


# ── recording ───────────────────────────────────────────────────────────────────────────────────────────────────────

def W(wid, rows, status="ok", applied=(True,), kind="symbol"):
    return {"id": wid, "title": wid.title(), "row_kind": kind, "status": status, "rows": [[s, 1, 2, 3] for s in rows],
            "criteria": [{"text": "x", "applied": a} for a in applied]}


def inputs(syms):
    base = {"AAA": (100, 98, 101, 3, 120, 80, 2.0), "BBB": (50, 49, 51, 1, 60, 40, -6.0), "CCC": (10, 9.9, 10.1, 0.2, 12, 8, 1)}
    keys = ("close", "low", "high", "atr", "swing_high", "swing_low", "chg")
    return {s: dict(zip(keys, base[s])) for s in syms if s in base}


def test_only_fully_applied_stock_lists_are_recorded():
    assert SIG.recordable(W("n50", ["AAA"]))
    assert SIG.recordable(W("n50", ["AAA"], status="partial"))                      # left out stocks without candles
    assert not SIG.recordable(W("n50", ["AAA"], status="partial", applied=(True, False)))   # daily-only survivors
    assert not SIG.recordable(W("mcap", ["Largecap"], kind="group"))
    assert not SIG.recordable(W("n50", ["AAA"], status="pending"))


def test_record_once_per_day_widget_stock_first_writer_wins_and_falling_oi_stocks_are_short():
    store = SIG.LocalSignalStore()
    widgets = [W("n50_gainers", ["AAA"]), W("open_interest", ["BBB", "AAA"]),
               W("strong_movers", ["CCC"], status="partial", applied=(True, False))]
    got = asyncio.run(SIG.record(widgets, inputs, at(9, 18), store=store))
    assert [g["id"] for g in got] == ["n50_gainers:AAA", "open_interest:BBB", "open_interest:AAA"]
    by = {g["id"]: g for g in got}
    assert by["open_interest:BBB"]["direction"] == "short" and by["open_interest:AAA"]["direction"] == "long"
    assert all(g["at_open"] for g in got) and by["n50_gainers:AAA"]["first_seen"] == "2026-11-03T09:18:00+05:30"
    assert by["n50_gainers:AAA"]["entry"] == 100.0 and by["n50_gainers:AAA"]["plan_ok"] is False
    assert by["n50_gainers:AAA"]["rules"] == SIG.LIST_RULES
    assert asyncio.run(SIG.record(widgets, inputs, at(9, 30), store=store)) == []           # already handled here
    SIG._seen.clear()                                                                      # another worker, same store
    assert asyncio.run(SIG.record(widgets, inputs, at(9, 31), store=store)) == []           # first writer won
    later = asyncio.run(SIG.record([W("n50_gainers", ["AAA", "CCC"])], inputs, at(10, 5), store=store))
    assert [g["id"] for g in later] == ["n50_gainers:CCC"] and later[0]["at_open"] is False


def test_today_lists_newest_first_with_price_now_and_the_move_since():
    store = SIG.LocalSignalStore()
    asyncio.run(SIG.record([W("n50_gainers", ["AAA"])], inputs, at(9, 18), store=store))
    asyncio.run(SIG.record([W("open_interest", ["BBB"])], inputs, at(10, 2), store=store))
    t = asyncio.run(SIG.today(at(11, 0), {"AAA": 103.0, "BBB": 49.0}, store=store))
    assert t["error"] is None and [s["symbol"] for s in t["signals"]] == ["BBB", "AAA"]
    assert t["signals"][1]["price_now"] == 103.0 and t["signals"][1]["move_since_pct"] == 3.0
    assert t["signals"][0]["move_since_pct"] == -2.0                                       # the price's move, short or long
    assert asyncio.run(SIG.today(at(11, 0, day=4), {}, store=store))["signals"] == []        # another day


def test_a_store_that_cannot_be_read_gives_an_empty_list_and_a_reason():
    class Broken(SIG.LocalSignalStore):
        async def read(self, index, last):
            raise RuntimeError("redis down")
    t = asyncio.run(SIG.today(at(11, 0), {}, store=Broken()))
    assert t["signals"] == [] and "could not be read" in t["error"]


# ── the loop ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_one_leader_computes_in_the_session_only():
    store, ran = SIG.LocalSignalStore(), []

    async def run():
        ran.append(1)
    assert asyncio.run(SIG.loop_once(at(9, 0), store=store, run=run, me="w1")) is False      # before the open
    assert asyncio.run(SIG.loop_once(at(9, 15), store=store, run=run, me="w1")) is True
    assert asyncio.run(SIG.loop_once(at(9, 15), store=store, run=run, me="w2")) is False     # w1 holds the lock
    assert asyncio.run(SIG.loop_once(at(15, 31), store=store, run=run, me="w1")) is False    # after the close
    assert asyncio.run(SIG.loop_once(datetime(2026, 11, 7, 10, 0, tzinfo=IST), store=store, run=run, me="w1")) is False  # Saturday
    assert ran == [1]


def test_the_loop_runs_on_staging_and_can_be_switched():
    assert SIG.enabled({"APP_ENV": "staging"}) is True
    assert SIG.enabled({"APP_ENV": "prod"}) is False
    assert SIG.enabled({"APP_ENV": "staging", "SCAN_SIGNALS_ENABLED": "0"}) is False
    assert SIG.enabled({"APP_ENV": "prod", "SCAN_SIGNALS_ENABLED": "1"}) is True


# ── strong signals (score ≥ 70): once per (day, stock), first writer wins, plan frozen (DESIGN.md §11) ─────────────────

def cand(sym, score=82, entry=100.0):
    return {"symbol": sym, "name": f"{sym} Ltd", "score_at": score, "parts_at": {"quality": 30}, "reasons_at": ["x"],
            "penalties_at": [], "lists_at": [{"id": "dt_52w_high", "title": "52 week high"}], "rules": "scan-plan-v3",
            "entry": entry, "stop_loss": entry - 4, "target_1": entry + 8, "target_2": entry + 16, "plan_ok": True}


def test_strong_signals_are_recorded_once_per_day_and_stock_first_writer_wins():
    store = SIG.LocalSignalStore()
    got = asyncio.run(SIG.record_strong([cand("AAA"), cand("BBB")], at(10, 5), store=store))
    assert [g["id"] for g in got] == ["strong:AAA", "strong:BBB"] and got[0]["first_strong"] == "2026-11-03T10:05:00+05:30"
    assert asyncio.run(SIG.record_strong([cand("AAA", 90, 120.0)], at(11, 0), store=store)) == []      # handled here
    SIG._seen_strong.clear()                                                                            # another worker
    assert asyncio.run(SIG.record_strong([cand("AAA", 90, 120.0)], at(11, 1), store=store)) == []      # first writer won
    t = asyncio.run(SIG.strong_today(at(11, 2), {"AAA": 105.0}, {"AAA": {"score": 75, "parts": {"quality": 28}}},
                                     store=store))
    a = next(r for r in t["strong"] if r["symbol"] == "AAA")
    assert (a["entry"], a["score_at"], a["score_now"], a["price_now"], a["move_since_pct"]) == (100.0, 82, 75, 105.0, 5.0)
    assert a["parts_now"] == {"quality": 28} and t["error"] is None


def test_strong_signals_newest_first_and_a_new_day_starts_empty():
    store = SIG.LocalSignalStore()
    asyncio.run(SIG.record_strong([cand("AAA")], at(10, 0), store=store))
    asyncio.run(SIG.record_strong([cand("BBB")], at(10, 30), store=store))
    t = asyncio.run(SIG.strong_today(at(11, 0), {}, {}, store=store))
    assert [r["symbol"] for r in t["strong"]] == ["BBB", "AAA"] and t["strong"][0]["price_now"] is None
    assert asyncio.run(SIG.strong_today(at(9, 30, day=4), {}, {}, store=store))["strong"] == []


def test_an_unreadable_strong_list_gives_an_empty_list_and_a_reason():
    class Broken(SIG.LocalSignalStore):
        async def read(self, index, last):
            raise RuntimeError("redis down")
    t = asyncio.run(SIG.strong_today(at(11, 0), {}, {}, store=Broken()))
    assert t["strong"] == [] and "could not be read" in t["error"]


# ── a whole day by company (DESIGN.md §11.1) ────────────────────────────────────────────────────────────────────────

def mark(sym, wid, hh, mm, ss=0, price=100.0, day=3):
    return {"id": f"{wid}:{sym}", "widget_id": wid, "widget_title": wid.replace("_", " ").title(), "symbol": sym,
            "first_seen": at(hh, mm, day).replace(second=ss).isoformat(timespec="seconds"), "entry": price,
            "direction": "long"}


async def _fill(store, marks):
    index, kp = SIG._day_keys("2026-11-03")
    for m in marks:
        await store.add(kp + m["id"], index, json.dumps(m), SIG.TTL_S)


def test_day_marks_reads_the_whole_day_oldest_first_beyond_the_feed_cap(monkeypatch):
    monkeypatch.setattr(SIG, "MAX_LISTED", 2)
    store = SIG.LocalSignalStore()
    asyncio.run(_fill(store, [mark(f"S{i}", "n50_gainers", 10, i) for i in range(5)][::-1]))
    assert len(asyncio.run(SIG.today(at(11, 0), {}, store=store))["signals"]) == 2              # the feed's cap
    got = asyncio.run(SIG.day_marks("2026-11-03", store=store))
    assert [m["symbol"] for m in got] == ["S0", "S1", "S2", "S3", "S4"]


def test_scores_round_trip_keeps_three_reasons():
    store = SIG.LocalSignalStore()
    scores = {"AAA": {"name": "Aaa Ltd", "score": 74, "parts": {"quality": 26}, "reasons": ["a", "b", "c", "d"],
                      "penalties": [{"text": "x", "points": 5}], "note": None, "atr": 2.0}}
    assert asyncio.run(SIG.save_scores("2026-11-03", scores, at(14, 5), store=store))
    doc = asyncio.run(SIG.load_scores("2026-11-03", store=store))
    assert doc["as_of"] == "2026-11-03T14:05:00+05:30"
    assert doc["scores"]["AAA"] == {"name": "Aaa Ltd", "score": 74, "parts": {"quality": 26}, "reasons": ["a", "b", "c"],
                                    "penalties": [{"text": "x", "points": 5}], "note": None}
    assert asyncio.run(SIG.load_scores("2026-11-02", store=store)) == {"as_of": None, "scores": {}}


def test_group_day_companies_newest_activity_first_marks_oldest_first_with_the_strong_record():
    marks = [mark("SAREGAMA", "dt_52w_high", 10, 49, 22, 575.25), mark("ITC", "vol_10x_5min", 9, 17, 0, 282.0),
             mark("SAREGAMA", "dt_vol_price_breakout", 13, 5, 3, 617.6), mark("SAREGAMA", "early_movers", 12, 47, 32, 614.8)]
    strong = [{"symbol": "SAREGAMA", "name": "Saregama India Limited", "first_strong": "2026-11-03T12:47:32+05:30",
               "score_at": 74, "entry": 614.8, "stop_loss": 576.82, "target_1": 690.76, "target_2": 766.72, "plan_ok": True,
               "trend_exit": "A daily close below the 20-day average", "rules": "scan-plan-v3", "reasons_at": ["kept out"]}]
    scores = {"SAREGAMA": {"name": "Saregama India Limited", "score": 74, "parts": {"quality": 26}, "reasons": ["r1"],
                           "penalties": [], "note": None},
              "ITC": {"name": "ITC Ltd", "score": 52, "parts": {}, "reasons": [], "penalties": [], "note": None}}
    companies, lists = SIG.group_day(marks, strong, scores)
    assert [c["symbol"] for c in companies] == ["SAREGAMA", "ITC"]
    s = companies[0]
    assert (s["n"], s["first_seen"][11:19], s["last_seen"][11:19], s["score"]) == (3, "10:49:22", "13:05:03", 74)
    assert [m["time"] for m in s["marks"]] == ["10:49:22", "12:47:32", "13:05:03"]
    assert s["marks"][0] == {"time": "10:49:22", "list": "dt_52w_high", "price": 575.25, "direction": "long"}
    assert s["strong"]["score_at"] == 74 and s["strong"]["stop_loss"] == 576.82 and "reasons_at" not in s["strong"]
    assert companies[1]["strong"] is None and lists["dt_52w_high"] == "Dt 52W High"


def test_day_view_counts_and_says_what_is_missing():
    store = SIG.LocalSignalStore()
    asyncio.run(_fill(store, [mark("AAA", "n50_gainers", 10, 0), mark("AAA", "strong_movers", 10, 5), mark("BBB", "x", 11, 0)]))
    v = asyncio.run(SIG.day_view("2026-11-03", store=store))
    assert (v["count"], v["companies_count"], v["threshold"]) == (3, 2, 70)
    assert v["companies"][0]["symbol"] == "BBB" and v["companies"][1]["n"] == 2
    assert any("not stored yet" in w for w in v["warnings"])
    asyncio.run(SIG.save_scores("2026-11-03", {"AAA": {"score": 80}}, at(11, 1), store=store))
    v = asyncio.run(SIG.day_view("2026-11-03", store=store))
    assert v["warnings"] == [] and v["companies"][1]["score"] == 80 and v["scores_as_of"] == "2026-11-03T11:01:00+05:30"

    class Broken(SIG.LocalSignalStore):
        async def read(self, index, last):
            raise RuntimeError("redis down")
    v = asyncio.run(SIG.day_view("2026-11-03", store=Broken()))
    assert v["companies"] == [] and v["count"] == 0 and "could not be read" in v["warnings"][0]
