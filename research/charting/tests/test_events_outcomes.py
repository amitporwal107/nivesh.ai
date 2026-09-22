"""outcomes.py: entry conventions, forward returns, MFE/MAE, bars-to-target, hit flags, ADV.
All-synthetic (task rule: numeric assertions only against `synth.py`/hand-built fixtures, never
real bars)."""
from __future__ import annotations

import pandas as pd
import pytest

from research.charting.events import outcomes
from research.charting.tests import synth


def _bars(closes, volume=100_000.0):
    return synth.bars_from_closes(closes, volume=volume)


# ── Entry conventions ─────────────────────────────────────────────────────────────────────


def test_primary_entry_is_open_of_t_plus_1():
    bars = _bars([100, 101, 102, 103, 104])
    e = outcomes.primary_entry(bars, 1)
    assert e["method"] == "open_t_plus_1"
    assert e["index"] == 2
    assert e["price"] == pytest.approx(bars["open"].iloc[2])
    assert e["date"] == bars["date"].iloc[2].date().isoformat()


def test_primary_entry_none_when_t_is_the_last_bar():
    bars = _bars([100, 101, 102])
    assert outcomes.primary_entry(bars, 2) is None


def test_alternative_entry_is_close_of_t_and_always_available():
    bars = _bars([100, 101, 102])
    e = outcomes.alternative_entry(bars, 2)
    assert e["method"] == "close_t"
    assert e["index"] == 2
    assert e["price"] == pytest.approx(bars["close"].iloc[2])


# ── Forward returns / MFE / MAE ──────────────────────────────────────────────────────────


def test_forward_return_and_mfe_mae_arithmetic_bullish():
    # entry_index=2, entry_price=100. horizon=1 -> exit_index=3.
    bars = synth.bars_from_closes([100, 100, 100, 110], wick=0.0)  # no wick: high=max(o,c), low=min(o,c)
    fwd = outcomes.forward_outcome_block(bars, entry_index=2, entry_price=100.0, direction="BULLISH", horizons=(1,))
    r = fwd["raw"][1]
    assert r["available"] is True
    assert r["exit_close"] == pytest.approx(110.0)
    assert r["close_return"] == pytest.approx(0.10)
    # window = bars[2..3] inclusive; bar2 close=100 (o=100,c=100 -> hi=lo=100), bar3 o=100,c=110 -> hi=110
    assert r["highest_price"] == pytest.approx(110.0)
    assert r["lowest_price"] == pytest.approx(100.0)
    assert r["mfe"] == pytest.approx(0.10)
    assert r["mae"] == pytest.approx(0.0)
    d = fwd["directional"][1]
    assert d["close_return_directional"] == pytest.approx(0.10)  # BULLISH: unchanged


def test_directional_return_flips_sign_for_bearish_but_raw_stays_long_perspective():
    bars = synth.bars_from_closes([100, 100, 100, 90], wick=0.0)
    fwd = outcomes.forward_outcome_block(bars, entry_index=2, entry_price=100.0, direction="BEARISH", horizons=(1,))
    raw = fwd["raw"][1]
    directional = fwd["directional"][1]
    assert raw["close_return"] == pytest.approx(-0.10)  # raw: always long-perspective
    assert directional["close_return_directional"] == pytest.approx(0.10)  # BEARISH: flipped (short P&L)


def test_neutral_direction_is_not_flipped():
    bars = synth.bars_from_closes([100, 100, 100, 90], wick=0.0)
    fwd = outcomes.forward_outcome_block(bars, entry_index=2, entry_price=100.0, direction="NEUTRAL", horizons=(1,))
    assert fwd["directional"][1]["close_return_directional"] == pytest.approx(-0.10)


def test_horizon_beyond_the_frame_is_unavailable_not_truncated():
    bars = synth.bars_from_closes([100, 101, 102])
    fwd = outcomes.forward_outcome_block(bars, entry_index=1, entry_price=101.0, direction="BULLISH", horizons=(1, 5))
    assert fwd["raw"][1]["available"] is True  # exit_index=2, exists
    assert fwd["raw"][5] == {"available": False, "reason": "insufficient_forward_bars"}
    assert fwd["directional"][5] == {"available": False, "reason": "insufficient_forward_bars"}


# ── bars_to_targets ───────────────────────────────────────────────────────────────────────


def test_bars_to_targets_finds_first_bar_whose_high_reaches_the_target():
    # entry_index=0, entry_price=100. High reaches 102 (+2%) at bar index 2 (bars_elapsed=2).
    bars = synth.bars_from_closes([100, 100.5, 101.9, 100.0, 100.0], wick=0.5)  # wick pads highs by 0.5
    bt = outcomes.bars_to_targets(bars, entry_index=0, entry_price=100.0, targets=(0.02,), max_horizon=4)
    # bar2's high = max(open,close)+0.5 = max(100.5,101.9)+0.5 = 102.4 >= 102 -> found at offset 2
    assert bt[0.02]["bars"] == 2
    assert bt[0.02]["reason"] is None


def test_bars_to_targets_not_reached_within_a_fully_available_window():
    bars = synth.bars_from_closes([100.0] * 10, wick=0.1)  # flat, never reaches +2%
    bt = outcomes.bars_to_targets(bars, entry_index=0, entry_price=100.0, targets=(0.02,), max_horizon=5)
    assert bt[0.02] == {"bars": None, "reason": "not_reached_within_horizon"}


def test_bars_to_targets_insufficient_forward_bars_is_a_distinct_reason():
    bars = synth.bars_from_closes([100.0, 100.1, 100.2], wick=0.05)  # only 2 bars after entry
    bt = outcomes.bars_to_targets(bars, entry_index=0, entry_price=100.0, targets=(0.02,), max_horizon=5)
    assert bt[0.02] == {"bars": None, "reason": "insufficient_forward_bars"}


# ── hit_high_N / hit_close_N (documented interpretation) ────────────────────────────────────


def test_hit_high_5_true_when_plus5pct_reached_within_5_bars():
    bars = synth.bars_from_closes([100.0] + [100.0] * 4 + [106.0] + [100.0] * 20, wick=0.2)
    bt = outcomes.bars_to_targets(bars, entry_index=0, entry_price=100.0)
    fwd = outcomes.forward_outcome_block(bars, entry_index=0, entry_price=100.0, direction="BULLISH")
    flags = outcomes.hit_flags(fwd["raw"], bt)
    assert flags["hit_high_5"] is True  # +5% high reached at bar index 5 (<=5)


def test_hit_flags_none_when_data_insufficient_never_a_guessed_bool():
    bars = synth.bars_from_closes([100.0, 101.0, 102.0])  # far too short for horizon 5/10
    bt = outcomes.bars_to_targets(bars, entry_index=0, entry_price=100.0)
    fwd = outcomes.forward_outcome_block(bars, entry_index=0, entry_price=100.0, direction="BULLISH")
    flags = outcomes.hit_flags(fwd["raw"], bt)
    assert flags["hit_high_5"] is None
    assert flags["hit_close_5"] is None
    assert flags["hit_high_10"] is None
    assert flags["hit_close_10"] is None


def test_hit_close_5_matches_the_horizon_5_raw_close_return_threshold():
    bars = synth.bars_from_closes([100.0, 100, 100, 100, 100, 106] + [106.0] * 20, wick=0.1)
    bt = outcomes.bars_to_targets(bars, entry_index=0, entry_price=100.0)
    fwd = outcomes.forward_outcome_block(bars, entry_index=0, entry_price=100.0, direction="BULLISH")
    flags = outcomes.hit_flags(fwd["raw"], bt)
    assert fwd["raw"][5]["close_return"] == pytest.approx(0.06)
    assert flags["hit_close_5"] is True


# ── ADV ───────────────────────────────────────────────────────────────────────────────────


def test_adv_inr_at_t_is_the_trailing_n_bar_mean_traded_value_inclusive_of_t():
    closes = [10.0] * 5
    vols = [100.0, 200.0, 300.0, 400.0, 500.0]
    bars = synth.bars_from_closes(closes, volume=vols)
    adv = outcomes.adv_inr_at(bars, t=4, n=5)
    expected = sum(10.0 * v for v in vols) / 5
    assert adv == pytest.approx(expected)


def test_adv_inr_at_t_none_when_fewer_than_n_bars_available():
    bars = synth.bars_from_closes([10.0] * 3)
    assert outcomes.adv_inr_at(bars, t=2, n=5) is None


def test_adv_inr_at_t_excludes_bars_after_t():
    closes = [10.0] * 10
    vols = [100.0] * 5 + [999_999.0] * 5  # huge volume only AFTER t=4
    bars = synth.bars_from_closes(closes, volume=vols)
    adv = outcomes.adv_inr_at(bars, t=4, n=5)
    assert adv == pytest.approx(10.0 * 100.0)  # unaffected by the future spike
