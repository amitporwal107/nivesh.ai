"""research/early_signals/features.py: the day-so-far arithmetic. MOCK — hand-made 5-minute candles."""
import numpy as np

from research.early_signals import features as F
from research.early_signals.replay import SLOTS


def _m(rows):
    """(5, N, 75) from per-stock lists of (slot, o, h, l, c, v)."""
    m = np.full((5, len(rows), SLOTS), np.nan)
    for j, cand in enumerate(rows):
        for slot, *vals in cand:
            m[:, j, slot] = vals
    return m


def test_cumulative_day_so_far():
    m = _m([[(0, 100, 102, 99, 101, 1000), (1, 101, 104, 100, 103, 3000), (3, 103, 103, 98, 99, 2000)],
            [(2, 50, 51, 49, 50, 10)]])
    cu = F.cumulative(m)
    a = {k: v[0] for k, v in cu.items()}
    assert a["open"] == 100 and a["high"][1] == 104 and a["low"][3] == 98
    assert a["close"].tolist()[:4] == [101, 103, 103, 99]          # slot 2 had no candle: the close carries
    assert a["cumvol"].tolist()[:4] == [1000, 4000, 4000, 6000]
    vw1 = (1000 * (102 + 99 + 101) / 3 + 3000 * (104 + 100 + 103) / 3) / 4000
    assert abs(a["vwap"][1] - vw1) < 1e-9
    b = {k: v[1] for k, v in cu.items()}
    assert b["open"] == 50 and np.isnan(b["close"][1]) and b["close"][2] == 50 and not b["started"][1] and b["started"][2]
