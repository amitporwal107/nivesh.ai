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

from outcomes import apply_v3, first_bar_locked

def test_v3_live_bands_etf_and_no_band():
    w = pd.DataFrame({"symbol": ["BAN", "FNO", "ETFX", "MISS"], "p0_adj": [100.0] * 4, "p0_raw": [100.0] * 4, "value20": [1e9] * 4})
    px = pd.DataFrame({"symbol": ["BAN", "FNO", "ETFX", "MISS"], "open_price": [95.0, 95.0, 90.0, 95.0], "close_price": [96.0] * 4})
    bands = pd.DataFrame({"symbol": ["BAN", "FNO", "ETFX"], "band_raw": ["5", "No Band", "10"], "price_band_pct": [5.0, None, 10.0], "is_etf": [False, False, True]})
    s = apply_v3(signals_for(w, px), bands, set()).set_index("symbol")
    assert s.loc["BAN", "v3_excluded"] == "OPEN_AT_OWN_BAND"      # 5% band, opened exactly at 95.00
    assert s.loc["FNO", "v3_excluded"] == ""                      # No Band (F&O): a -5% open is NOT excluded under v3
    assert s.loc["ETFX", "v3_excluded"] == "ETF"
    assert s.loc["MISS", "v3_excluded"] == "BAND_UNKNOWN"         # no band row for the session -> not traded

def test_v3_20pct_band_stock_opening_minus5_is_not_excluded():
    w = pd.DataFrame({"symbol": ["S20"], "p0_adj": [100.0], "p0_raw": [100.0], "value20": [1e9]})
    px = pd.DataFrame({"symbol": ["S20"], "open_price": [94.9], "close_price": [96.0]})
    s = apply_v3(signals_for(w, px), pd.DataFrame({"symbol": ["S20"], "band_raw": ["20"], "price_band_pct": [20.0], "is_etf": [False]}), set())
    assert s.v3_excluded.iloc[0] == "" and bool(s.at_band_v2.iloc[0])  # v2 would have excluded it; v3 does not

def test_first_bar_locked_fallback():
    assert first_bar_locked(95.0, 95.0, -0.05) and not first_bar_locked(95.0, 94.8, -0.05) and not first_bar_locked(96.5, 96.5, -0.035)

def test_v3_is_etf_parses_psql_text_booleans():
    w = pd.DataFrame({"symbol": ["STK", "ETFX"], "p0_adj": [100.0] * 2, "p0_raw": [100.0] * 2, "value20": [1e9] * 2})
    px = pd.DataFrame({"symbol": ["STK", "ETFX"], "open_price": [96.0, 96.0], "close_price": [97.0] * 2})
    bands = pd.DataFrame({"symbol": ["STK", "ETFX"], "band_raw": ["20", "20"], "price_band_pct": [20.0, 20.0], "is_etf": ["f", "t"]})
    s = apply_v3(signals_for(w, px), bands, set()).set_index("symbol")
    assert s.loc["STK", "v3_excluded"] == "" and s.loc["ETFX", "v3_excluded"] == "ETF"
