"""research/early_signals/context.py: timing helpers. MOCK — hand-made candles."""
from datetime import datetime, timedelta, timezone

import numpy as np

from research.early_signals import context as X

IST = timezone(timedelta(hours=5, minutes=30))


def test_step_end_is_ist_session_time():
    d = np.datetime64("2026-11-03")
    assert X.step_end_ts(d, 3) == datetime(2026, 11, 3, 9, 30, tzinfo=IST).timestamp()
    assert X.step_end_ts(d, 75) == datetime(2026, 11, 3, 15, 30, tzinfo=IST).timestamp()


def test_future_oi_so_far_vs_previous_sessions_last(tmp_path):
    def ts(day, hh, mm):
        return int(datetime(2026, 11, day, hh, mm, tzinfo=IST).timestamp())
    t = np.array([ts(2, 15, 20), ts(2, 15, 25), ts(3, 9, 15), ts(3, 9, 20), ts(3, 9, 25)], dtype=np.int64)
    oi = np.array([1000.0, 1100.0, 1150.0, 1250.0, 1300.0])
    px = np.array([10.0, 10.0, 10.2, 10.4, 10.5])
    p = tmp_path / "AAA.npz"
    np.savez(p, ts=t, o=px, h=px, l=px, c=px, v=np.ones(5), oi=oi)
    fo = X.FutOI(str(p))
    assert fo.oi_so_far(np.datetime64("2026-11-03"), 2) == (1250.0, 1100.0)    # 09:15 + 09:20 candles; 2 Nov's last
    assert fo.oi_so_far(np.datetime64("2026-11-04"), 2) == (None, None)
