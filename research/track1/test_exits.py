import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from exits import stop_target_exit as X, hb_confirmation as C

E = 100.0
def test_time_exit_at_official_close():   assert X([(100, 101, 99, 100.5)], E, 100.7) == (100.7, "TIME")
def test_target_touch():                  assert X([(100, 103.2, 99.5, 102)], E, 101) == (103.0, "TARGET")
def test_stop_touch():                    assert X([(100, 101, 97.9, 99)], E, 101) == (98.0, "STOP")
def test_both_touched_counts_stop():      assert X([(100, 103.5, 97.5, 101)], E, 101) == (98.0, "STOP")
def test_gap_through_stop_fills_at_open():assert X([(100, 100, 99.5, 99.8), (96.5, 97, 96, 96.2)], E, 99) == (96.5, "STOP_GAP")
def test_gap_through_target_at_open():    assert X([(100, 100.5, 99.8, 100), (103.6, 104, 103, 103.5)], E, 104) == (103.6, "TARGET_GAP")
def test_first_touch_wins():              assert X([(100, 103.1, 99.5, 102), (102, 102, 97, 97)], E, 97) == (103.0, "TARGET")

OBS = [(100, 100.4, 98.8, 99.2, 1000), (99.2, 99.6, 98.6, 99.0, 800), (99.0, 99.9, 98.9, 99.8, 900),
       (99.8, 100.3, 99.6, 100.1, 700), (100.1, 100.5, 100.0, 100.4, 600), (100.4, 100.6, 100.2, 100.5, 500)]
def test_confirmation_uses_only_completed_bars():
    ok, p945, vwap, why = C(OBS, 100.0); assert ok and why == "CONFIRMED" and p945 == 100.5 and vwap < 100.5
def test_drawdown_rejects():
    bars = OBS[:-1] + [(99.0, 99.2, 98.9, 99.0, 500)]; assert C(bars, 100.0)[3] in ("DRAWDOWN", "BOTH")
def test_missing_bars():                  assert C(OBS[:5], 100.0)[3] == "MISSING_BARS"
