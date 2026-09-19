"""Exit rules shared by Track 1 (TRACK1_SCOPE_v1 section 5, v2 H-A change). Pure functions; bars are (open, high, low, close)
tuples in time order starting at the entry bar."""
from __future__ import annotations

def stop_target_exit(bars, entry: float, official_close: float, stop_pct: float = 0.02, target_pct: float = 0.03):
    """First-touch exit from the entry bar onward. Returns (exit_price, reason). Priority per bar:
    open <= stop -> STOP_GAP at the open; open >= target -> TARGET_GAP at the open; both touched -> STOP;
    low <= stop -> STOP; high >= target -> TARGET. Neither by the last bar -> TIME at the official close."""
    s, t = entry * (1 - stop_pct), entry * (1 + target_pct)
    for o, h, l, c in bars:
        if o <= s: return o, "STOP_GAP"
        if o >= t: return o, "TARGET_GAP"
        if l <= s and h >= t: return s, "STOP"
        if l <= s: return s, "STOP"
        if h >= t: return t, "TARGET"
    return official_close, "TIME"

def hb_confirmation(obs_bars, open_0915: float):
    """obs_bars = the six bars 09:15..09:40 as (open, high, low, close, volume). Returns (confirmed, p945, vwap, reason)."""
    vol = sum(b[4] for b in obs_bars)
    if len(obs_bars) != 6 or vol <= 0:
        return False, None, None, "MISSING_BARS"
    vwap = sum((b[1] + b[2] + b[3]) / 3 * b[4] for b in obs_bars) / vol
    p945 = obs_bars[-1][3]
    a, b_ = p945 >= open_0915 * 0.995, p945 > vwap
    if a and b_: return True, p945, vwap, "CONFIRMED"
    return False, p945, vwap, "BOTH" if not a and not b_ else "DRAWDOWN" if not a else "BELOW_VWAP"
