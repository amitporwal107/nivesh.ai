import os, sys
import pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from outcomes import signals_for, select_capped

W = pd.DataFrame({"symbol": list("ABCDEFG"), "p0_adj": [100.0] * 7, "p0_raw": [100.0] * 7,
                  "value20": [1e9, 2e9, 3e9, 4e9, 5e9, 6e9, 7e9]})
PX = pd.DataFrame({"symbol": list("ABCDEF"), "open_price": [96.0, 95.0, 90.0, 99.0, 94.0, 96.0], "close_price": [97.0] * 6})

def test_signal_gap_and_band_flags():
    s = signals_for(W, PX).set_index("symbol")
    assert bool(s.loc["A", "signal"]) and not bool(s.loc["D", "signal"])          # -4% signals, -1% does not
    assert bool(s.loc["B", "at_band"]) and bool(s.loc["C", "at_band"])            # -5% and -10% opens sit at a band
    assert not bool(s.loc["G", "has_price"]) and not bool(s.loc["G", "signal"])   # no official price -> never a signal

def test_cap_orders_deepest_then_value():
    s = signals_for(W, PX); sig = s[s.signal & ~s.at_band]                        # A -4%, E -6%, F -4%
    assert list(select_capped(sig, 2).symbol) == ["E", "F"]                       # deepest first; tie A/F -> higher value (F)
