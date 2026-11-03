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
    yield
    SIG._seen.clear()


# ── the plan ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_long_plan_stop_at_the_lower_of_day_low_and_one_atr_targets_at_two_and_three_risk():
    p = SIG.make_plan("long", 100, 98, 101, 3, 120, 80)
    assert (p["stop_loss"], p["stop_basis"]) == (97.0, "1 × ATR(14) below entry")
    assert (p["risk_per_share"], p["target_1"], p["target_2"]) == (3.0, 106.0, 109.0)
    assert (p["rr_1"], p["rr_2"], p["target_1_basis"], p["plan_ok"]) == (2.0, 3.0, "2 × risk", True)
    p = SIG.make_plan("long", 100, 95, 101, 3, 130, 80)                         # today's low is lower than 1 ATR
    assert (p["stop_loss"], p["stop_basis"], p["target_1"]) == (95.0, "today's low", 110.0)


def test_target_1_is_capped_at_the_20_session_high_and_too_little_room_means_no_plan():
    p = SIG.make_plan("long", 100, 98, 101, 3, 105, 80)                         # 105 < 106: capped, 5/3 = 1.67
    assert (p["target_1"], p["target_1_basis"], p["rr_1"], p["plan_ok"]) == (105.0, "the previous 20 sessions' high", 1.67, True)
    p = SIG.make_plan("long", 100, 98, 101, 3, 104, 80)                         # 4/3 = 1.33 < 1.5
    assert p["plan_ok"] is False and "only 1.33 × the risk" in p["plan_note"] and p["target_1"] == 104.0
    p = SIG.make_plan("long", 100, 98, 101, 3, 99, 80)                          # the high is below entry (a breakout): no cap
    assert (p["target_1"], p["target_1_basis"]) == (106.0, "2 × risk")


def test_short_plan_is_the_mirror():
    p = SIG.make_plan("short", 100, 98, 101, 3, 120, 90)
    assert (p["stop_loss"], p["stop_basis"], p["target_1"], p["target_2"]) == (103.0, "1 × ATR(14) above entry", 94.0, 91.0)
    assert p["plan_ok"] is True
    p = SIG.make_plan("short", 100, 98, 101, 3, 120, 96)                        # capped at the 20-session low: 4/3
    assert p["target_1"] == 96.0 and p["plan_ok"] is False


def test_no_price_or_no_room_gives_no_plan_with_a_reason():
    assert SIG.make_plan("long", None, 98, 101, 3, 120, 80)["plan_note"].startswith("No live price")
    p = SIG.make_plan("long", 100, 100, 101, None, 120, 80)                     # low = price, no ATR: no risk distance
    assert p["plan_ok"] is False and "stop loss" in p["plan_note"]


def test_plan_words_are_the_owners_choice_and_nothing_else_is_barred():
    import re
    text = json.dumps([SIG.make_plan(d, 100, 98, 101, 3, 104, 96) for d in ("long", "short")]) + SIG.RULES_TEXT + SIG.CAVEAT
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
    assert by["n50_gainers:AAA"]["entry"] == 100.0 and by["n50_gainers:AAA"]["plan_ok"] is True
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
