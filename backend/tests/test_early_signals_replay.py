"""research/early_signals/replay.py: the pure parts (candle slots, D's candle so far, aggregation). MOCK — hand-made candles."""
from datetime import datetime, timedelta, timezone

import numpy as np

from research.early_signals import replay as R

IST = timezone(timedelta(hours=5, minutes=30))


def _ts(day, hh, mm):
    return int(datetime(2026, 11, day, hh, mm, tzinfo=IST).timestamp())


def _candles(day=3, n=75, start=100.0):
    ts = np.array([_ts(day, 9, 15) + 300 * i for i in range(n)], dtype=np.int64)
    c = start + np.arange(n, dtype=float)
    return ts, c - 0.5, c + 1.0, c - 1.0, c, np.full(n, 1000.0)


def test_slots_follow_ist_session_time():
    day, slot = R.slot_of(np.array([_ts(3, 9, 15), _ts(3, 9, 20), _ts(3, 15, 25), _ts(3, 15, 30)]))
    assert [str(x) for x in day] == ["2026-11-03"] * 4
    assert slot.tolist() == [0, 1, 74, 75]                       # 15:30 is outside the session (slot 75 dropped)


def test_overlay_is_the_days_candle_so_far():
    c = R.Candles(*_candles())
    m = R.day_matrix({"AAA": c, "BBB": c}, ["AAA", "BBB", "ZZZ"], np.datetime64("2026-11-03"))
    ov, have = R.overlay_at(m, 3)                                # 09:15, 09:20, 09:25 candles = the state at 09:30
    assert have.tolist() == [True, True, False]
    o, h, l, cl, v = ov[:, 0]
    assert (o, h, l, cl, v) == (99.5, 103.0, 99.0, 102.0, 3000.0)
    assert np.isnan(ov[:, 2]).all()
    assert R.step_label(3) == "09:30" and R.step_label(75) == "15:30"


def test_overlay_skips_a_missing_candle():
    ts, o, h, l, c, v = _candles(n=4)
    keep = np.array([True, False, True, True])                   # no 09:20 candle
    m = R.day_matrix({"AAA": R.Candles(ts[keep], o[keep], h[keep], l[keep], c[keep], v[keep])}, ["AAA"],
                     np.datetime64("2026-11-03"))
    ov, have = R.overlay_at(m, 2)                                # up to 09:25: only the 09:15 candle
    assert have.tolist() == [True] and ov[3, 0] == 100.0 and ov[4, 0] == 1000.0


def test_aggregation_to_15_minute_and_1_hour_candles():
    prev = _candles(day=2)
    today = _candles(day=3, start=200.0)
    ts = np.concatenate([prev[0], today[0]])
    cols = [np.concatenate([a, b]) for a, b in zip(prev[1:], today[1:])]
    c = R.Candles(ts, *cols)
    b15 = c.bars(15, np.datetime64("2026-11-03"), 6)             # yesterday's 25 candles + today's first two (09:15, 09:30)
    assert len(b15) == 25 + 2
    assert b15[-2] == ["2026-11-03T09:15:00+05:30", 199.5, 203.0, 199.0, 202.0, 3000.0]
    assert b15[-1][0] == "2026-11-03T09:30:00+05:30" and b15[-1][4] == 205.0
    b60 = c.bars(60, np.datetime64("2026-11-03"), 75)
    today60 = [b for b in b60 if b[0].startswith("2026-11-03")]
    assert [b[0][11:16] for b in today60] == ["09:15", "10:15", "11:15", "12:15", "13:15", "14:15", "15:15"]
    assert today60[-1][5] == 3000.0                              # 15:15–15:30: three 5-minute candles


def test_five_minute_bars_are_the_slots_themselves():
    c = R.Candles(*_candles(n=5))
    b5 = c.bars(5, np.datetime64("2026-11-03"), 3)
    assert b5 == [["2026-11-03T09:15:00+05:30", 99.5, 101.0, 99.0, 100.0, 1000.0],
                  ["2026-11-03T09:20:00+05:30", 100.5, 102.0, 100.0, 101.0, 1000.0],
                  ["2026-11-03T09:25:00+05:30", 101.5, 103.0, 101.0, 102.0, 1000.0]]
