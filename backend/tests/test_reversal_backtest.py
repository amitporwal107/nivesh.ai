"""reversal_backtest.py: point-in-time backtest mechanics (BT-1 .. BT-4).

Every panel is MOCK — not real data: seeded random walks on consecutive weekdays. The real-data run is a separate step
(scripts/run_reversal_backtest.py); these tests check the mechanics against answers worked out by hand.

Worked examples
  costs     base round trip = 0.25 + 0.10 = 0.35 %, higher = 0.40 + 0.20 = 0.60 %, deducted ONCE per trade:
            gross +2.00 % -> net +1.65 % (base), +1.40 % (higher)
  forward   signal on bar i, entry = open of bar i+1 (100), exit = close of bar i+h (h = 4: bar 4); high 106 -> +5 % touched, +10 % not
  split     a 2:1 split (previous close restated 100 -> 50) halves every earlier price and doubles earlier volume
"""
from __future__ import annotations

import copy
import random
from datetime import date, timedelta

import pytest

from services.positional_engine import reversal_backtest as bt


def _cal(n, start=date(2024, 1, 1)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _walk(cal, seed, drift=0.0, vol=0.012, start=100.0, volume=5_000_000):
    rng = random.Random(seed)
    bars, prev = [], start
    for d in cal:
        o = prev * (1 + rng.gauss(0, 0.003))
        c = o * (1 + rng.gauss(drift, vol))
        bars.append({"d": d, "o": o, "h": max(o, c) * 1.004, "l": min(o, c) * 0.996, "c": c, "pc": prev, "v": volume})
        prev = c
    return bars


def _panel(n_sym=120, n_days=430, seed=1):
    cal = _cal(n_days)
    by = {f"S{i:03d}": _walk(cal, seed * 1000 + i, drift=0.0002 * ((i % 7) - 3)) for i in range(n_sym)}
    return by, {f"S{i:03d}": ("Alpha" if i % 2 else "Beta") for i in range(n_sym)}, cal


# ── costs and statistics ─────────────────────────────────────────────────────

def test_round_trip_costs_are_deducted_once():
    assert bt.round_trip_pct("base") == pytest.approx(0.35)
    assert bt.round_trip_pct("higher") == pytest.approx(0.60)
    f = {"ret": 2.0, "mae": -1.0, "mfe": 6.0, "hit5": True, "hit10": False, "inval": None, "failed_breakout": None}
    ev = [{"symbol": "A", "t": 1, "status": "early_reversal", "fwd": {5: f}}]
    uni = {1: {5: 0.5}}
    base = bt.stats(ev, uni, 5, "base", boot=False)
    high = bt.stats(ev, uni, 5, "higher", boot=False)
    assert base["mean_gross"] == 2.0 and base["mean_net"] == pytest.approx(1.65)
    assert high["mean_net"] == pytest.approx(1.40)
    assert base["mean_excess_gross"] == pytest.approx(1.5) and base["mean_excess_net"] == pytest.approx(1.15)
    assert base["round_trip_cost_pct"] == pytest.approx(0.35) and high["round_trip_cost_pct"] == pytest.approx(0.60)


def test_stats_metrics_on_known_answers():
    mk = lambda r, mae, mfe, inv=None: {"ret": r, "mae": mae, "mfe": mfe, "hit5": mfe >= 5, "hit10": mfe >= 10,
                                       "inval": inv, "failed_breakout": None}
    fw = [mk(10.0, -2.0, 11.0, False), mk(-4.0, -6.0, 1.0, True), mk(0.2, -1.0, 6.0, False), mk(-1.0, -3.0, 2.0, True)]
    ev = [{"symbol": f"A{i}", "t": i, "status": "x", "fwd": {10: f}} for i, f in enumerate(fw)]
    s = bt.stats(ev, {i: {10: 1.0} for i in range(4)}, 10, "base", boot=False)
    assert s["n"] == 4 and s["win_rate_gross"] == 50.0 and s["win_rate_net"] == 25.0   # 0.2 - 0.35 < 0
    assert s["mean_gross"] == pytest.approx(1.3) and s["median_gross"] == pytest.approx(-0.4)
    assert s["hit5_pct"] == 50.0 and s["hit10_pct"] == 25.0
    assert s["mae_mean"] == pytest.approx(-3.0) and s["invalidation_hit_pct"] == 50.0


def test_events_without_an_outcome_are_not_counted_as_zero():
    ev = [{"symbol": "A", "t": 1, "status": "x", "fwd": {5: None}}]
    s = bt.stats(ev, {1: {5: 0.0}}, 5)
    assert s["n"] == 0 and s["events"] == 1 and "mean_net" not in s


def test_forward_enters_next_open_and_measures_adverse_excursion():
    bars = [{"d": f"2026-01-{i + 1:02d}", "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.0} for i in range(10)]
    bars[1].update(o=100.0, l=97.0)                 # entry bar: low 97 -> MAE -3 %
    bars[3].update(h=106.0)                         # +6 % touch
    bars[4].update(c=104.0)                         # exit at h = 4: the close of bar i+4
    f = bt.forward(bars, list(range(10)), 0, 4)
    assert f["ret"] == pytest.approx(4.0) and f["mae"] == pytest.approx(-3.0) and f["mfe"] == pytest.approx(6.0)
    assert f["hit5"] is True and f["hit10"] is False
    assert bt.forward(bars, list(range(10)), 8, 4) is None                     # not enough future bars
    assert bt.forward(bars, [0, 1, 2, 20, 21, 22, 23, 24, 25, 26], 0, 4) is None   # a 17-session hole inside the window is not 4 sessions


def test_forward_flags_invalidation_and_failed_breakout():
    bars = [{"d": f"d{i}", "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.0} for i in range(12)]
    bars[3]["c"] = 94.0
    f = bt.forward(bars, list(range(12)), 0, 10, invalidation=95.0, resistance=98.0)
    assert f["inval"] is True and f["failed_breakout"] is True
    f2 = bt.forward(bars, list(range(12)), 0, 10, invalidation=90.0, resistance=93.0)
    assert f2["inval"] is False and f2["failed_breakout"] is False


def test_failed_breakout_is_only_counted_for_confirmed_breakouts():
    f_fail = {"ret": -1.0, "mae": -2.0, "mfe": 1.0, "hit5": False, "hit10": False, "inval": False, "failed_breakout": True}
    f_hold = dict(f_fail, failed_breakout=False)
    ev = [{"symbol": "A", "t": 1, "status": "confirmed", "fwd": {5: f_fail}},
          {"symbol": "B", "t": 2, "status": "confirmed", "fwd": {5: f_hold}},
          {"symbol": "C", "t": 3, "status": "trigger_ready", "fwd": {5: f_fail}},      # still below resistance by definition
          {"symbol": "D", "t": 4, "status": "early_reversal", "fwd": {5: f_fail}}]
    s = bt.stats(ev, {t: {5: 0.0} for t in range(1, 5)}, 5, boot=False)
    assert s["failed_breakout_pct"] == 50.0 and s["failed_breakout_n"] == 2
    none = bt.stats(ev[2:], {3: {5: 0.0}, 4: {5: 0.0}}, 5, boot=False)
    assert none["failed_breakout_pct"] is None and none["failed_breakout_n"] == 0


# ── adjusted prices ──────────────────────────────────────────────────────────

def test_action_factors_from_exchange_terms():
    assert bt.action_factor("SPLIT", "10:2", 10.0, 2.0) == pytest.approx(0.2)
    assert bt.action_factor("SPLIT", "10:5") == pytest.approx(0.5)
    assert bt.action_factor("BONUS", "1:1") == pytest.approx(0.5)
    assert bt.action_factor("BONUS", "1:2") == pytest.approx(2 / 3)
    assert bt.action_factor("BONUS", "3:1") == pytest.approx(0.25)
    assert bt.action_factor("RIGHTS", "1:5") is None and bt.action_factor("DIVIDEND", "") is None
    assert bt.action_factor("BONUS", "x:y") is None and bt.action_factor("SPLIT", "2:10") is None   # a reverse split is not handled


def _split_panel():
    cal = _cal(40)
    by = {f"S{i}": _walk(cal, i) for i in range(5)}
    s = by["S0"]
    for i in range(20, 40):                       # 2:1 split on bar 20: prices halve, volume doubles
        for k in ("o", "h", "l", "c", "pc"):
            s[i][k] /= 2.0
        s[i]["v"] *= 2
    return cal, by


def test_split_is_back_adjusted_from_the_action_file_not_from_previous_close():
    cal, by = _split_panel()
    before = copy.deepcopy(by)
    adj, diag = bt.adjust_actions(by, cal, [{"symbol": "S0", "ex_date": cal[20], "factor": 0.5}])
    assert diag["applied"] == 1 and diag["inconsistent"] == 0 and diag["segments_cut"] == 0
    assert adj["S0"][5]["c"] == pytest.approx(before["S0"][5]["c"] / 2.0)
    assert adj["S0"][5]["v"] == pytest.approx(before["S0"][5]["v"] * 2)
    assert adj["S0"][25]["c"] == before["S0"][25]["c"]
    assert max(abs(adj["S0"][i + 1]["c"] / adj["S0"][i]["c"] - 1) for i in range(39)) < 0.1     # no cliff left
    assert adj["S1"] == before["S1"] and by == before                                          # others and the input untouched


def test_an_action_that_does_not_match_the_price_is_counted_but_not_hidden():
    cal, by = _split_panel()
    _, diag = bt.adjust_actions(by, cal, [{"symbol": "S0", "ex_date": cal[20], "factor": 0.2}])
    assert diag["applied"] == 1 and diag["inconsistent"] == 1


def test_a_jump_no_action_explains_cuts_the_series_into_segments():
    cal = _cal(60)
    by = {"S0": _walk(cal, 1)}
    for i in range(30, 60):
        for k in ("o", "h", "l", "c", "pc"):
            by["S0"][i][k] *= 0.4                  # a 60 % one-session drop, no corporate action on file
    adj, diag = bt.adjust_actions(by, cal, [])
    assert sorted(adj) == ["S0", "S0#1"] and diag["segments_cut"] == 1 and diag["symbols_cut"] == ["S0"]
    assert len(adj["S0"]) == 30 and len(adj["S0#1"]) == 30 and adj["S0#1"][0]["d"] == cal[30]


def test_a_move_inside_the_circuit_limit_is_not_a_break():
    cal = _cal(40)
    by = {"S0": _walk(cal, 1)}
    for i in range(20, 40):
        for k in ("o", "h", "l", "c"):
            by["S0"][i][k] *= 0.8                  # exactly the 20 % circuit move
    adj, diag = bt.adjust_actions(by, cal, [])
    assert list(adj) == ["S0"] and diag["segments_cut"] == 0


# ── no look-ahead ────────────────────────────────────────────────────────────

def _strip(events):
    keys = ("symbol", "t", "date", "dist", "status", "core_true", "core_unknown", "quadrant", "rvol", "invalidation", "resistance")
    return [{k: e[k] for k in keys} for e in events]


def test_decisions_do_not_depend_on_later_data():
    by, ind, cal = _panel()
    D = 330
    full = bt.run(by, ind, first_signal=cal[300], last_signal=cal[D])
    assert full["events"], "mock panel must produce reversal-pool events"
    truncated = {s: [b for b in bars if b["d"] <= cal[D]] for s, bars in by.items()}
    short = bt.run(truncated, ind, first_signal=cal[300], last_signal=cal[D])
    assert _strip(full["events"]) == _strip(short["events"])
    scrambled = {s: [dict(b, o=b["o"] * 3, h=b["h"] * 3, l=b["l"] * 3, c=b["c"] * 3, pc=b["pc"] * 3) if b["d"] > cal[D] else b
                     for b in bars] for s, bars in by.items()}
    sc = bt.run(scrambled, ind, first_signal=cal[300], last_signal=cal[D])
    assert _strip(full["events"]) == _strip(sc["events"])


def test_entry_is_the_next_session_open_not_the_signal_close():
    by, ind, cal = _panel(n_sym=110, n_days=420)
    rec = bt.run(by, ind, first_signal=cal[300], last_signal=cal[330])
    e = next(e for e in rec["events"] if e["fwd"][5])
    bars = by[e["symbol"]]
    i = [b["d"] for b in bars].index(e["date"])
    entry = bars[i + 1]["o"]
    exit_c = bars[i + 5]["c"]
    assert e["fwd"][5]["ret"] == pytest.approx((exit_c / entry - 1) * 100)


# ── selection, cooldown, blocks, walk-forward ────────────────────────────────

def test_cooldown_keeps_the_first_trigger_per_stock():
    ev = [{"symbol": "A", "t": t, "dist": 5.0, "status": "early_reversal", "quadrant": "leading"} for t in (1, 5, 21, 22, 41)]
    kept = bt.select(ev, "technical_reversal", 15.0)
    assert [e["t"] for e in kept] == [1, 21, 41]


def test_variants_are_nested_and_thresholds_filter_distance():
    ev = [{"symbol": "A", "t": 1, "dist": 8.0, "status": "trigger_ready", "quadrant": "leading"},
          {"symbol": "B", "t": 1, "dist": 12.0, "status": "early_reversal", "quadrant": "lagging"},
          {"symbol": "C", "t": 1, "dist": 18.0, "status": "early_reversal", "quadrant": "improving"},
          {"symbol": "D", "t": 1, "dist": 9.0, "status": "near_low_no_evidence", "quadrant": "leading"}]
    names = lambda v, p: sorted(e["symbol"] for e in bt.select(ev, v, p))
    assert names("near_low_only", 15.0) == ["A", "B", "D"] and names("near_low_only", 20.0) == ["A", "B", "C", "D"]
    assert names("technical_reversal", 15.0) == ["A", "B"] and names("technical_reversal", 10.0) == ["A"]
    assert names("sector_plus_technical", 20.0) == ["A", "C"]
    assert names("trigger_or_confirmed", 20.0) == ["A"]


def test_blocks_are_chronological_and_events_do_not_straddle_them():
    blocks = bt.split_blocks(list(range(100, 200)))
    assert blocks == {"train": (100, 159), "validation": (160, 179), "out_of_sample": (180, 199)}
    ev = [{"t": t} for t in range(100, 200)]
    tr = bt.in_block(ev, blocks["train"])
    assert max(e["t"] for e in tr) == 159 - 20 and min(e["t"] for e in tr) == 100
    assert bt.split_blocks([1, 2, 3]) == {}


def test_choice_never_reads_the_out_of_sample_block():
    base = {"A": {"train": {"mean_excess_net": 1.0}, "validation": {"mean_excess_net": 1.0}},
            "B": {"train": {"mean_excess_net": 0.5}, "validation": {"mean_excess_net": 0.4}}}
    poisoned = copy.deepcopy(base)
    poisoned["A"]["out_of_sample"] = {"mean_excess_net": -99.0}
    poisoned["B"]["out_of_sample"] = {"mean_excess_net": 99.0}
    assert bt.choose_variant(base) == "A" == bt.choose_variant(poisoned)


def test_bootstrap_interval_is_reproducible_and_brackets_the_mean():
    by_date = {t: [1.0 + (t % 3)] * 4 for t in range(30)}
    a, b = bt._bootstrap_ci(by_date), bt._bootstrap_ci(by_date)
    assert a == b and a[0] <= 2.0 <= a[1]
    assert bt._bootstrap_ci({1: [1.0], 2: [2.0]}) is None


# ── sector rotation on the panel ─────────────────────────────────────────────

def test_sector_state_quadrants_use_only_data_up_to_t():
    by, ind, cal = _panel()
    rec = bt.run(by, ind, first_signal=cal[300], last_signal=cal[320])
    quads = {e["quadrant"] for e in rec["events"]}
    assert quads <= {"leading", "improving", "weakening", "lagging", "unknown"}
    assert rec["coverage"]["signal_sessions"] > 0 and rec["coverage"]["symbols_with_industry"] == 120
