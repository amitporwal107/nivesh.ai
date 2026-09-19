"""Arm C — close-entry variants of E2 and E3 on a 15:15 snapshot (PREREGISTRATION.md §4, FROZEN fe60155f).

The snapshot of session t uses 5-minute bars that START before 15:15 (09:15 ... 15:10; the 15:10 bar closes at 15:15):
open = first bar open, high/low = extremes, last = the 15:10 bar's close, vol1515 = volume to 15:15. Everything else
is the previous full session's value, updated with the snapshot the way the daily indicator would be:
EMA_t = a*last + (1-a)*EMA_{t-1}; ATR_t = ATR_{t-1} + (TR_t - ATR_{t-1})/14 (Wilder, as Phase 1).
Implementation notes (readings of the frozen text, recorded in RESULTS.md):
- relative strength uses the Nifty 500's 20-day return to t-1 (no intraday index bars exist), the stock's to 15:15;
- eligibility uses value20 as of t-1 (t's full-day turnover is not known at 15:15);
- E3's volume test compares vol1515 with the 20-session average of vol1515 (the frozen text), E2's volume test is on
  the full days t-4..t-1 (unchanged).
"""
from __future__ import annotations

import glob
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "phase1"))
import phase1_common as C  # noqa: E402
import signals as S  # noqa: E402

FIVE = "/app/research/kite_history/five_min_2024/part-*.csv.gz"
CUTOFF = "15:15"


def snapshots(symbols: set, pattern: str = FIVE) -> pd.DataFrame:
    parts = []
    for f in sorted(glob.glob(pattern)):
        for ch in pd.read_csv(f, usecols=["symbol", "ts", "open", "high", "low", "close", "volume"], chunksize=2_000_000):
            ch = ch[ch.symbol.isin(symbols)]
            hhmm = ch.ts.str[11:16]
            ch = ch[hhmm < CUTOFF].copy()
            ch["date"] = pd.to_datetime(ch.ts.str[:10])
            parts.append(ch)
    x = pd.concat(parts).sort_values(["symbol", "ts"]).drop_duplicates(["symbol", "ts"])
    assert x.date.min() >= C.DISCOVERY_START, "sealed data in the 5-minute bars"
    g = x.groupby(["symbol", "date"], sort=True)
    snap = g.agg(s_open=("open", "first"), s_high=("high", "max"), s_low=("low", "min"), s_last=("close", "last"),
                 s_vol=("volume", "sum"), s_last_ts=("ts", "last")).reset_index()
    return snap


def snapshot_features(d: pd.DataFrame, snap: pd.DataFrame, idx: pd.DataFrame) -> pd.DataFrame:
    """Per (symbol, t) features for the C arms from the previous full sessions plus t's 15:15 snapshot ONLY — no
    full-day value of t (close, high, low, volume, EMA/ATR/relative strength/value20 of t) is read."""
    d = d.sort_values(["symbol", "date"]).reset_index(drop=True)
    g = d.groupby("symbol", sort=False)
    prev = pd.DataFrame({
        "symbol": d.symbol, "date": d.date, "hist_n": d.hist_n, "hi55": d.hi55,
        "prev_close": g.close.shift(1), "prev_close2": g.close.shift(2), "close_20ago": g.close.shift(20),
        "ema20_prev": g.ema20.shift(1), "ema50_prev": g.ema50.shift(1), "atr_prev": g.atr14.shift(1),
        "value20_prev": g.value20.shift(1),
        "hi54_prev": g.high.transform(lambda s: s.shift(1).rolling(54).max()),
        "hi14_prev": g.high.transform(lambda s: s.shift(1).rolling(14).max()),
        "low4_prev": g.low.transform(lambda s: s.shift(1).rolling(4).min()),
        "down4_prev": (d.close < g.close.shift(1)).astype(float).where(g.close.shift(1).notna())
                      .groupby(d.symbol).transform(lambda s: s.shift(1).rolling(4).sum()),
        "vol4_prev": g.volume.transform(lambda s: s.shift(1).rolling(4).mean()),
        "vol20": g.volume.transform(lambda s: s.shift(1).rolling(20).mean())})
    ix = idx.copy()
    ix["idx_ret20_prev"] = (ix.idx_close / ix.idx_close.shift(20) - 1).shift(1)
    prev = prev.merge(ix[["date", "idx_ret20_prev"]], on="date", how="left")
    s = snap.sort_values(["symbol", "date"]).copy()
    s["vol1515_avg20"] = s.groupby("symbol", sort=False).s_vol.transform(lambda v: v.shift(1).rolling(20).mean())
    x = prev.merge(s, on=["symbol", "date"], how="inner")
    last = x.s_last
    tr = np.maximum(x.s_high - x.s_low, np.maximum((x.s_high - x.prev_close).abs(), (x.s_low - x.prev_close).abs()))
    rng = x.s_high - x.s_low
    x["last"] = last
    x["ema20_s"] = (2 / 21) * last + (1 - 2 / 21) * x.ema20_prev
    x["ema50_s"] = (2 / 51) * last + (1 - 2 / 51) * x.ema50_prev
    x["atr_s"] = x.atr_prev + (tr - x.atr_prev) / 14
    x["close_pos_s"] = ((last - x.s_low) / rng).where(rng > 0, 0.5)
    x["rvol_s"] = x.s_vol / x.vol1515_avg20
    x["rs20_s"] = (last / x.close_20ago - 1) - x.idx_ret20_prev
    x["elig_s"] = (x.hist_n >= 60) & (x.value20_prev >= 5e7) & (last >= 50)
    x["low5_s"] = np.minimum(x.low4_prev, x.s_low)
    return x


def snapshot_signals(d: pd.DataFrame, snap: pd.DataFrame, idx: pd.DataFrame) -> pd.DataFrame:
    x = snapshot_features(d, snap, idx)
    last = x["last"]
    # C-E3: the B55 screen on the snapshot
    m3 = (x.elig_s & (x.rvol_s >= 1.5) & (x.close_pos_s >= 0.75) & (last > x.ema20_s) & (last > x.ema50_s) & (x.rs20_s > 0)
          & (last > x.hi55))
    # C-E2: the pullback screen, t's values from the snapshot
    trend = (last > x.ema50_s) & (np.maximum(x.hi54_prev, x.s_high) == np.maximum(x.hi14_prev, x.s_high))
    pull = ((x.down4_prev >= 3) & (x.low4_prev >= x.ema20_prev - x.atr_prev) & (x.low4_prev <= x.ema20_prev + x.atr_prev)
            & (x.vol4_prev < x.vol20))
    first_up = (last > x.prev_close) & (last > x.s_open) & (x.prev_close <= x.prev_close2)
    m2 = x.elig_s & trend & pull & first_up
    f = x.assign(close=last, atr14=x.atr_s, rs20=x.rs20_s)
    a = S._frame(f, m3, "C-E3", "MOC", last, last - 2 * x.atr_s)
    b = S._frame(f, m2, "C-E2", "MOC", last, x.low5_s - 0.5 * x.atr_s)
    return pd.concat([a, b], ignore_index=True)
