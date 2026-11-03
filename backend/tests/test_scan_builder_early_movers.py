"""Early movers (services/scan_builder/early_movers.py): the 3 Nov study's top rule as a live list. Hand-made numbers (MOCK)."""
from datetime import datetime

import numpy as np
import pytest

from services.scan_builder import early_movers as EM
from services.scan_builder.signals import IST


def t(h, m, s=0):
    return datetime(2026, 11, 4, h, m, s, tzinfo=IST)


def test_the_curve_is_a_cumulative_share_of_the_day():
    c = EM.VOLUME_CURVE
    assert len(c) == 75 and c[-1] == 1.0 and all(b >= a for a, b in zip(c, c[1:]))


def test_usual_share_by_time_of_day():
    assert EM.usual_share(t(9, 25), True) is None                     # before 09:30, the study's first step
    assert EM.usual_share(t(9, 30), True) == pytest.approx(EM.VOLUME_CURVE[2])          # end of the 3rd candle
    mid = EM.usual_share(t(9, 32, 30), True)                                            # half-way through the 4th
    assert mid == pytest.approx((EM.VOLUME_CURVE[2] + EM.VOLUME_CURVE[3]) / 2)
    assert EM.usual_share(t(15, 29), True) <= 1.0 and EM.usual_share(t(16, 0), False) == 1.0


def test_rows_apply_volume_multiple_over_open_and_the_liquidity_universe():
    syms = ["UP5X", "UP2X", "FLAT", "THIN", "CHEAP", "NEW"]
    hist = np.full((20, 6), 100_000.0)
    hist[:, 3] = 40_000.0                                   # THIN: average below 50,000
    hist[:15, 5] = np.nan                                   # NEW: only 5 sessions of history
    open_ = np.array([100, 100, 100, 100, 10, 100.0])
    close = np.array([103, 103, 101, 103, 10.5, 103.0])     # FLAT only +1 %; CHEAP below price 20
    share = 0.2
    vol = np.array([120_000, 50_000, 200_000, 60_000, 200_000, 200_000.0])   # usual by now = 20,000 (THIN 8,000)
    out = EM.rows(syms, open_, close, vol, hist, np.ones(6, dtype=bool), share)
    assert [r[0] for r in out] == ["UP5X"]                  # 6× and +3 %; UP2X only 2.5×
    assert out[0][1:] == [3.0, 103.0, 120000, 6.0]


def test_criteria_say_what_is_applied_and_when():
    lines = EM.criteria(t(11, 5), True, 0.41286)
    assert "by 11:05" in lines[1]["text"] and "41.3%" in lines[1]["text"] and all(ln["applied"] for ln in lines)
    early = EM.criteria(t(9, 20), True, None)
    assert early[1]["applied"] is False and "09:30" in early[1]["text"]
    assert "whole day" in EM.criteria(t(16, 0), False, 1.0)[1]["text"]
