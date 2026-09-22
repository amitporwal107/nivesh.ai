"""Sealed window as an INPUT, not only as an output date (review of defect-#1 fix, 2026-09-22).

A research evaluation dated entirely outside 2023-01-01..2024-07-31 can still read sealed bars:
replay's lookback (detect_as_of sees every earlier bar) and movement's ATR warm-up and forward
exit bar. Each case below passed the window/entry-date-only guard and must now raise; the same
evaluation on bars that stay on one side of the block must run."""
from __future__ import annotations

import pandas as pd
import pytest

from research.charting import movement, replay, research_window
from research.charting.tests import synth


def _bars(start: str, n: int) -> pd.DataFrame:
    return synth.bars_from_closes([100.0 + (i % 7) * 0.4 + i * 0.05 for i in range(n)], start_date=start)


def _event(date: str) -> dict:
    return {"pattern_id": "SYN1:rect:1", "pattern_type": "RECTANGLE", "direction": "BULLISH",
            "events": [{"event_type": movement._CONFIRMED_EVENT_TYPE, "date": date}]}


def test_replay_of_a_post_sealed_window_with_sealed_lookback_raises():
    bars = _bars("2024-05-01", 140)
    start = int((bars["date"] > research_window.SEALED_GAP_END).idxmax())
    assert bars["date"].iloc[0] < research_window.SEALED_GAP_END < bars["date"].iloc[start]  # lookback is sealed
    assert not research_window.overlaps_sealed_gap(bars["date"].iloc[start], bars["date"].iloc[-1])  # window is not
    with pytest.raises(research_window.SealedWindowError):
        replay.replay(bars, symbol="SYN1", start_index=start)


def test_replay_of_the_same_window_on_post_sealed_bars_only_runs():
    bars = _bars("2024-05-01", 140)
    post = bars[bars["date"] > research_window.SEALED_GAP_END].reset_index(drop=True)
    result = replay.replay(post, symbol="SYN1")
    assert result.end_index == len(post) - 1


def test_movement_event_whose_forward_bars_reach_the_sealed_window_raises():
    bars = _bars("2022-06-01", 170)  # runs into 2023
    assert bars["date"].iloc[-1] > research_window.SEALED_GAP_START
    with pytest.raises(research_window.SealedWindowError):
        movement.movement_vs_direction_report([_event("2022-12-28")], {"SYN1": bars}, horizons=(5,))


def test_movement_event_whose_atr_warms_up_on_sealed_bars_raises():
    bars = _bars("2024-05-01", 140)
    with pytest.raises(research_window.SealedWindowError):
        movement.movement_vs_direction_report([_event("2024-09-16")], {"SYN1": bars}, horizons=(1,))


def test_movement_on_pre_sealed_bars_only_skips_the_horizon_it_cannot_measure():
    bars = _bars("2022-06-01", 170)
    pre = bars[bars["date"] < research_window.SEALED_GAP_START].reset_index(drop=True)
    last = pre["date"].iloc[-3].strftime("%Y-%m-%d")  # 2 bars of forward data left
    report = movement.movement_vs_direction_report([_event(last)], {"SYN1": pre}, horizons=(5,))
    assert report[("RECTANGLE", 5)].move.n == 0  # no exit bar inside the pre-sealed frame
