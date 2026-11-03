"""services/exit_rules.py — the one exit step shared by the backtest and the paper simulators (exit-rules-v1).

Test cases: test_reports/p2_exits_backtest_TESTCASES.md TC-1 .. TC-14. Every number is worked out by hand in the test.
Bars are hypothetical (MOCK — not real data)."""
from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from services import exit_rules as er

D0 = date(2026, 10, 1)


def bar(i: int, o, h, l, c):
    return {"date": D0 + timedelta(days=i), "open": o, "high": h, "low": l, "close": c}


def long_rules(**kw):
    return er.Rules(side="long", **kw)


# ── TC-1 .. TC-4: stop, gap, target, both ─────────────────────────────────────────────────────────────────
def test_tc1_intrabar_touch_of_the_stop_fills_at_the_stop():
    s = er.start(100.0, 95.0, long_rules(target=110.0))
    s, ex = er.step(s, bar(1, 99, 100, 94, 96), long_rules(target=110.0))
    assert ex["reason"] == "stop" and ex["price"] == 95.0 and ex["fill"] == "level" and not ex["gapped"]
    assert s.closed and s.sessions_held == 1


def test_tc2_an_open_through_the_stop_fills_at_the_open():
    s = er.start(100.0, 95.0, long_rules())
    _, ex = er.step(s, bar(1, 92, 93, 90, 91), long_rules())
    assert ex["reason"] == "stop" and ex["price"] == 92.0 and ex["fill"] == "gap_open" and ex["gapped"]


def test_tc3_target_touch_and_target_jump_both_fill_at_the_target():
    r = long_rules(target=110.0)
    _, ex = er.step(er.start(100.0, 95.0, r), bar(1, 105, 111, 104, 109), r)
    assert (ex["reason"], ex["price"]) == ("target", 110.0)
    # Opens at 115, above the target: no credit for the better open (desk FILL MODEL).
    _, ex = er.step(er.start(100.0, 95.0, r), bar(1, 115, 118, 112, 117), r)
    assert (ex["reason"], ex["price"], ex["fill"]) == ("target", 110.0, "level")


def test_tc4_a_bar_touching_both_counts_as_the_stop():
    r = long_rules(target=110.0)
    _, ex = er.step(er.start(100.0, 95.0, r), bar(1, 100, 112, 94, 100), r)
    assert ex["reason"] == "stop" and ex["price"] == 95.0 and ex["both_in_range"]


def test_skip_target_on_a_pullback_entry_session():
    r = long_rules(target=110.0)
    s, ex = er.step(er.start(100.0, 95.0, r), bar(1, 101, 111, 99, 108), r, skip_target=True)
    assert ex is None and not s.closed


# ── TC-5: time in sessions ───────────────────────────────────────────────────────────────────────────────
def test_tc5_time_exit_is_the_close_of_the_nth_session_held():
    r = long_rules(max_hold_sessions=3)
    s = er.start(100.0, 90.0, r)
    # three sessions spread over a weekend: 10 calendar days, 3 sessions
    for i, (day, c) in enumerate([(1, 101), (4, 102), (10, 103)]):
        s, ex = er.step(s, bar(day, c, c + 1, c - 1, c), r)
        if i < 2:
            assert ex is None
    assert ex["reason"] == "time" and ex["price"] == 103 and ex["sessions_held"] == 3


def test_time_exit_waits_for_a_close():
    r = long_rules(max_hold_sessions=1)
    s, ex = er.step(er.start(100.0, 90.0, r), {"date": D0, "open": 100, "high": 101, "low": 99, "close": None}, r)
    assert ex is None


# ── TC-6, TC-7, TC-9: PRD Example H and the same-bar case ────────────────────────────────────────────────
H = long_rules(trail_atr_mult=2.0)


def test_tc6_prd_example_h_trail_is_1040_after_a_1080_high():
    s = er.start(1000.0, 970.0, H, atr=20.0, prev_close=1000.0)
    # True range of the bar with the previous close 1000: max(1080-1045, |1080-1000|, |1045-1000|) = 80
    # → ATR_t = (20 * 13 + 80) / 14 = 24.2857 ... the PRD's 1,040 uses a frozen ATR of 20, so pin that first
    s_frozen = er.start(1000.0, 970.0, er.Rules(side="long", trail_atr_mult=2.0, atr_period=14), atr=20.0, prev_close=1060.0)
    s1, ex = er.step(s_frozen, bar(1, 1060, 1080, 1045, 1070), er.Rules(side="long", trail_atr_mult=2.0))
    assert ex is None
    # TR with previous close 1060: max(35, 20, 15) = 35; ATR = (20*13 + 35)/14 = 21.0714; stop = 1080 − 2 × 21.07 = 1037.86
    assert s1.stop == pytest.approx(1037.86)
    # With the ATR genuinely 20 at that close (a bar whose true range equals the ATR) the trail is the PRD's 1,040.
    s2, ex = er.step(er.start(1000.0, 970.0, H, atr=20.0, prev_close=1070.0), bar(1, 1062, 1080, 1060, 1070), H)
    assert ex is None and s2.atr == pytest.approx(20.0) and s2.stop == 1040.0
    assert [h["reason"] for h in s2.stop_history] == ["initial", "trailing_atr"]
    assert s2.stop_version == 2 and s2.stop_history[1]["session"] == bar(1, 0, 0, 0, 0)["date"].isoformat()


def test_tc7_same_bar_high_1080_low_1035_does_not_exit_at_the_raised_stop():
    s = er.start(1000.0, 970.0, H, atr=20.0, prev_close=1070.0)
    s, ex = er.step(s, bar(1, 1062, 1080, 1035, 1070), H)
    # The stop in force for this bar is 970; the low 1035 is above it: no exit (the old backtest exited at 1040 here).
    assert ex is None
    assert s.stop > 970.0                       # raised AFTER the bar, effective next session
    raised = s.stop
    s, ex = er.step(s, bar(2, 1050, 1052, raised - 1, 1045), H)
    assert ex["reason"] == "trailing_stop" and ex["price"] == raised


def test_tc9_initial_stop_exit_is_stop_not_trailing():
    s = er.start(1000.0, 970.0, H, atr=20.0, prev_close=1000.0)
    _, ex = er.step(s, bar(1, 990, 995, 960, 965), H)
    assert ex["reason"] == "stop"


# ── TC-8: monotone stop, long and short (property) ───────────────────────────────────────────────────────
@pytest.mark.parametrize("side", ["long", "short"])
@pytest.mark.parametrize("seed", range(25))
def test_tc8_the_stop_never_loosens_and_versions_increase(side, seed):
    rnd = random.Random(seed)
    rules = er.Rules(side=side, trail_atr_mult=rnd.choice([1.0, 1.5, 2.0, 3.0]), atr_period=rnd.choice([5, 14]))
    px = 100.0
    s = er.start(px, px * (0.9 if side == "long" else 1.1), rules)
    stops = [s.stop]
    for i in range(200):
        o = px * (1 + rnd.uniform(-0.01, 0.01))
        h = max(o, px) * (1 + rnd.uniform(0, 0.03))
        l = min(o, px) * (1 - rnd.uniform(0, 0.03))
        c = rnd.uniform(l, h)
        s, ex = er.step(s, bar(i, o, h, l, c), rules)
        if ex:
            break
        stops.append(s.stop)
        px = c
    if side == "long":
        assert all(b >= a for a, b in zip(stops, stops[1:]))
    else:
        assert all(b <= a for a, b in zip(stops, stops[1:]))
    versions = [h["version"] for h in s.stop_history]
    assert versions == sorted(set(versions)) and versions[0] == 1


# ── TC-10: rules that are off change nothing (property) ──────────────────────────────────────────────────
@pytest.mark.parametrize("seed", range(25))
def test_tc10_disabled_opt_in_rules_give_identical_exits(seed):
    rnd = random.Random(1000 + seed)
    path, px = [], 100.0
    for i in range(120):
        o = px * (1 + rnd.uniform(-0.02, 0.02))
        h, l = max(o, px) * (1 + rnd.uniform(0, 0.02)), min(o, px) * (1 - rnd.uniform(0, 0.02))
        c = rnd.uniform(l, h)
        path.append(bar(i, o, h, l, c))
        px = c
    base = er.Rules(side="long", target=112.0, max_hold_sessions=60)
    off = er.Rules(side="long", target=112.0, max_hold_sessions=60, trail_atr_mult=None, trend_ema_period=None, atr_period=5)
    a = er.replay(er.start(100.0, 93.0, base), path, base)
    b = er.replay(er.start(100.0, 93.0, off, warmup=path[:3]), path, off)
    assert a[1] == b[1]
    assert a[0].stop_history == b[0].stop_history


# ── TC-11: ATR per bar; zero or missing ATR ──────────────────────────────────────────────────────────────
def test_tc11_wilder_atr_uses_bars_up_to_t_and_seeds_from_warmup():
    rules = er.Rules(side="long", trail_atr_mult=2.0, atr_period=3)
    warm = [bar(0, 100, 102, 98, 100), bar(1, 100, 103, 99, 101), bar(2, 101, 104, 100, 103)]
    # TRs: 4 (h−l, no previous close), max(4, 2, 2) = 4, max(4, 3, 1) = 4 → seed ATR = 4
    s = er.start(103.0, 95.0, rules, warmup=warm)
    assert s.atr == pytest.approx(4.0) and s.prev_close == 103
    s, ex = er.step(s, bar(3, 103, 110, 102, 109), rules)
    # TR = max(8, 7, 1) = 8 → ATR = (4 × 2 + 8) / 3 = 5.3333; mark 110 → stop 110 − 10.67 = 99.33
    assert s.atr == pytest.approx(16 / 3) and s.stop == pytest.approx(99.33)


def test_tc11_no_atr_yet_means_the_trail_does_not_move_and_says_so():
    rules = er.Rules(side="long", trail_atr_mult=2.0, atr_period=14)
    s = er.start(100.0, 90.0, rules)              # no seed, no warm-up: never a stand-in 2% ATR
    s, ex = er.step(s, bar(1, 100, 130, 99, 129), rules)
    assert ex is None and s.stop == 90.0 and s.atr is None
    assert [e["code"] for e in s.events] == ["atr_unavailable"]


def test_tc11_a_zero_or_bad_atr_seed_is_not_used():
    rules = er.Rules(side="long", trail_atr_mult=2.0, atr_period=14)
    for bad in (0, -1, float("nan"), None, "x"):
        assert er.start(100.0, 90.0, rules, atr=bad).atr is None


# ── TC-12: trend exit ────────────────────────────────────────────────────────────────────────────────────
def test_tc12_close_below_the_ema_exits_at_the_next_open():
    rules = er.Rules(side="long", trend_ema_period=3)
    s = er.start(100.0, 80.0, rules, ema=100.0)
    s, ex = er.step(s, bar(1, 100, 101, 95, 96), rules)
    # EMA3: α = 0.5 → 0.5 × 96 + 0.5 × 100 = 98; close 96 < 98 → exit at the next open
    assert ex is None and s.trend_pending and s.ema == pytest.approx(98.0)
    s, ex = er.step(s, bar(2, 97, 99, 96, 98), rules)
    assert (ex["reason"], ex["price"], ex["fill"]) == ("trend", 97, "open")


def test_tc12_a_time_exit_on_the_same_close_wins():
    rules = er.Rules(side="long", trend_ema_period=3, max_hold_sessions=1)
    _, ex = er.step(er.start(100.0, 80.0, rules, ema=100.0), bar(1, 100, 101, 95, 96), rules)
    assert ex["reason"] == "time"


def test_tc12_a_gap_through_the_stop_beats_a_pending_trend_exit():
    rules = er.Rules(side="long", trend_ema_period=3)
    s, _ = er.step(er.start(100.0, 95.0, rules, ema=100.0), bar(1, 100, 101, 96, 97), rules)
    assert s.trend_pending
    _, ex = er.step(s, bar(2, 90, 92, 89, 91), rules)
    assert ex["reason"] == "stop" and ex["price"] == 90 and ex["gapped"]


# ── TC-13: short side ────────────────────────────────────────────────────────────────────────────────────
def test_tc13_short_side_mirror():
    r = er.Rules(side="short", target=90.0, trail_atr_mult=2.0)
    _, ex = er.step(er.start(100.0, 105.0, r, atr=2.0), bar(1, 101, 106, 100, 104), r)
    assert (ex["reason"], ex["price"]) == ("stop", 105.0)
    _, ex = er.step(er.start(100.0, 105.0, r, atr=2.0), bar(1, 108, 109, 107, 108), r)
    assert (ex["reason"], ex["price"], ex["gapped"]) == ("stop", 108, True)
    _, ex = er.step(er.start(100.0, 105.0, r, atr=2.0), bar(1, 95, 96, 89, 92), r)
    assert (ex["reason"], ex["price"]) == ("target", 90.0)
    s, ex = er.step(er.start(100.0, 105.0, r, atr=2.0, prev_close=97.0), bar(1, 97, 97.5, 95.5, 96), r)
    # low-water 95.5; TR = max(2, 0.5, 1.5) = 2 → ATR 2; stop = 95.5 + 4 = 99.5 (lowered from 105)
    assert ex is None and s.stop == pytest.approx(99.5)


# ── TC-14: invalid levels, incomplete bars, missing open ─────────────────────────────────────────────────
@pytest.mark.parametrize("entry,stop,target,side,code", [
    (100, 100, None, "long", "stop_not_below_entry"),
    (100, 101, None, "long", "stop_not_below_entry"),
    (100, 99, 99, "long", "target_not_above_entry"),
    (100, 99, None, "short", "stop_not_above_entry"),
    (0, 99, None, "long", "invalid_entry_price"),
    (100, None, None, "long", "invalid_stop_price"),
    (100, -5, None, "long", "invalid_stop_price"),
])
def test_tc14_invalid_levels_are_refused(entry, stop, target, side, code):
    with pytest.raises(ValueError, match=code):
        er.validate_levels(entry, stop, target, side)


@pytest.mark.parametrize("b", [
    {"date": D0, "open": 100, "high": None, "low": 99, "close": 100},
    {"date": D0, "open": 100, "high": 101, "low": None, "close": 100},
    {"date": D0, "open": 100, "high": 98, "low": 99, "close": 100},      # high below low
    {"date": D0, "open": 100, "high": "x", "low": 99, "close": 100},
])
def test_tc14_a_bar_without_a_usable_range_raises(b):
    with pytest.raises(er.IncompleteBar):
        er.step(er.start(100.0, 95.0, long_rules()), b, long_rules())


def test_tc14_missing_open_fills_at_the_stop_and_says_why():
    s, ex = er.step(er.start(100.0, 95.0, long_rules()), {"date": D0, "open": None, "high": 96, "low": 90, "close": 91}, long_rules())
    assert ex["price"] == 95.0 and [e["code"] for e in s.events] == ["open_unknown"]


def test_stepping_a_closed_position_is_refused():
    s, _ = er.step(er.start(100.0, 95.0, long_rules()), bar(1, 99, 100, 94, 96), long_rules())
    with pytest.raises(ValueError):
        er.step(s, bar(2, 99, 100, 94, 96), long_rules())


def test_the_step_is_pure():
    r = er.Rules(side="long", trail_atr_mult=2.0, target=120.0)
    s0 = er.start(100.0, 95.0, r, atr=2.0, prev_close=100.0)
    b = bar(1, 101, 106, 100, 105)
    assert er.step(s0, b, r) == er.step(s0, b, r)
    assert s0.stop == 95.0 and s0.sessions_held == 0


# ── rule configuration stored on a paper trade ───────────────────────────────────────────────────────────
def test_rule_config_round_trip_and_labels():
    stored = er.clean_rule_config({"trailing_atr": {"k": 2}, "trend_ema": {"period": 20}})
    assert stored == [{"code": "trailing_atr", "version": "trail-atr-v1", "params": {"k": 2.0, "atr_period": 14}},
                      {"code": "trend_ema", "version": "trend-ema-v1", "params": {"period": 20}}]
    labels = er.rule_labels(stored)
    assert labels[0]["label"].startswith("ATR trailing stop: highest high since entry − 2 × ATR(14)")
    assert "opt-in" in labels[0]["label"] and "research rule trend-ema-v1" in labels[1]["label"]
    r = er.rules_from_config(stored, target=110.0, max_hold_sessions=10)
    assert (r.trail_atr_mult, r.atr_period, r.trend_ema_period, r.max_hold_sessions) == (2.0, 14, 20, 10)
    assert er.rules_from_config([], target=110.0).trailing is False
    assert er.clean_rule_config(None) == [] and er.clean_rule_config({}) == []


@pytest.mark.parametrize("raw", [
    [], "trail", {"trailing": {}}, {"trailing_atr": {"k": 0}}, {"trailing_atr": {"k": 11}}, {"trailing_atr": {"k": True}},
    {"trailing_atr": {"k": 2, "atr_period": 1}}, {"trailing_atr": {"k": 2, "x": 1}}, {"trend_ema": {"period": 1}},
    {"trend_ema": {"period": 20.5}}, {"trend_ema": "20"},
])
def test_rule_config_refuses_anything_else(raw):
    with pytest.raises(ValueError, match="invalid_exit_rules"):
        er.clean_rule_config(raw)
