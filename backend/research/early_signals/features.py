"""Candidate early indicators, replayed through past sessions on Kite 5-minute candles (research, read-only).

Owner, 3 Nov 2026: "establish the early indicators of such trades" — stocks that rise >= 5 % above the day's OPEN. This module
writes, for every session, every 15-minute step and every stock, which candidate indicators hold at that step, using only what
was known then; outcomes.py / report.py score them exactly like the dashboard's widgets (precision vs the base rate at the same
step, lead time before the +5 % move, upside and drawdown after the first flag).

Indicators computed here (price and volume; context, events, F&O and fund holdings are added from their own sources):
  rvol{k}            volume so far >= k x the stock's average volume up to the same time of day over its previous 20 sessions
  rvol{k}_up{r}      rvol{k} and the price r % or more above the open
  vwap_up{r}         price above the session VWAP so far and r % or more above the open
  gap{g}_hold        opened g % or more above the previous close and the price is still above the open
  orb                high so far above the first 15 minutes' high (from 09:45)
  first_hour_up{r}   at 10:15 the price is r % or more above the open (fires at 10:15 only)
  brk_prev_day       high so far above the previous session's high
  brk_20d / brk_52w / brk_all   high so far above the highest high of the previous 20 / 250 sessions / all history loaded
  low52_recovery     previous close within 15 % above the 52-week low and the price 1 % or more above the open
  mom_up             previous close > EMA20 > EMA50, 20-session return > 5 %, and the price 1 % or more above the open

Output: features.csv in flags.csv's format (day, step, symbol, widget = indicator id, close_at_step), so report.py reads both.
Run inside the staging backend container:
    python -m research.early_signals.features --bars /tmp/early_signals/bars5 --out /tmp/early_signals [--days N]
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import time
from typing import Any, Dict, Optional

import numpy as np

from .replay import SLOTS, Candles, day_matrix, load_candles, step_label

RVOL_K = (2, 3, 5)
UP_R = (1, 2)
GAP_G = (1, 2)
FIRST_HOUR_R = (2, 3)
RVOL_LOOKBACK = 20
MIN_RVOL_SESSIONS = 10


def _ema(x: np.ndarray, n: int) -> np.ndarray:
    """EMA along axis 0 (rows = days) with the SMA seed, NaN-tolerant per column (same convention as indicators.ema)."""
    from services.scan_builder import indicators as ind
    return ind.ema(x, n)


def cumulative(m: np.ndarray) -> Dict[str, np.ndarray]:
    """Per stock and slot: running high, low, close, volume and VWAP of the day so far ((N, 75) each; NaN before a candle)."""
    o, h, l, c, v = m
    have = ~np.isnan(c)
    vol = np.where(have, v, 0.0)
    cumv = np.cumsum(vol, axis=1)
    tp = np.where(have, (h + l + c) / 3.0, 0.0)
    cumpv = np.cumsum(tp * vol, axis=1)
    with np.errstate(all="ignore"):
        hi = np.fmax.accumulate(np.where(have, h, np.nan), axis=1)
        lo = np.fmin.accumulate(np.where(have, l, np.nan), axis=1)
        # last close so far: forward-fill the closes
        idx = np.where(have, np.arange(SLOTS)[None, :], 0)
        np.maximum.accumulate(idx, axis=1, out=idx)
        last = np.take_along_axis(np.where(have, c, np.nan), idx, axis=1)
        started = np.maximum.accumulate(have, axis=1)
        last = np.where(started, last, np.nan)
        vwap = np.where(cumv > 0, cumpv / cumv, np.nan)
        first = np.where(have.any(axis=1), o[np.arange(o.shape[0]), have.argmax(axis=1)], np.nan)
    return {"high": hi, "low": lo, "close": last, "cumvol": np.where(started, cumv, np.nan), "vwap": vwap,
            "open": first, "started": started}


async def run(bars_dir: str, out_dir: str, days: Optional[int], step_min: int = 15) -> Dict[str, Any]:
    from services.scan_builder.data import get_data

    t0 = time.monotonic()
    base = await (get_data()).panel()
    fetched = sorted(f[:-4] for f in os.listdir(bars_dir) if f.endswith(".npz"))
    symbols = [s for s in fetched if s in base.index]
    cols = np.array([base.index[s] for s in symbols])
    cands: Dict[str, Candles] = load_candles(bars_dir, symbols)
    all_days = sorted({d for c in cands.values() for d in c.days})
    run_days = all_days[-days:] if days else all_days
    mats = {d: day_matrix(cands, symbols, d) for d in all_days}
    cums = {d: cumulative(mats[d]) for d in all_days}
    pdates = base.dates
    hi_all, lo_all, cl_all = base.high[:, cols], base.low[:, cols], base.close[:, cols]
    ema20, ema50 = _ema(cl_all, 20), _ema(cl_all, 50)
    per_step = max(1, step_min // 5)
    os.makedirs(out_dir, exist_ok=True)
    f = open(os.path.join(out_dir, "features.csv"), "w", newline="")
    w = csv.writer(f)
    w.writerow(["day", "step", "symbol", "widget", "close_at_step"])
    counts: Dict[str, int] = {}
    for d in run_days:
        idx = int(np.searchsorted(pdates, d)) - 1                     # previous session's EOD row
        if idx < 260:
            continue
        cu = cums[d]
        prev_close, prev_high = cl_all[idx], hi_all[idx]
        hi20 = np.nanmax(hi_all[idx - 19:idx + 1], axis=0)
        hi250 = np.nanmax(hi_all[max(0, idx - 249):idx + 1], axis=0)
        hiall = np.nanmax(hi_all[:idx + 1], axis=0)
        lo250 = np.nanmin(lo_all[max(0, idx - 249):idx + 1], axis=0)
        ret20 = cl_all[idx] / cl_all[idx - 20] - 1.0
        trend = (cl_all[idx] > ema20[idx]) & (ema20[idx] > ema50[idx]) & (ret20 > 0.05)
        near_low = (prev_close <= lo250 * 1.15)
        prior = [x for x in all_days if x < d][-RVOL_LOOKBACK:]
        if len(prior) >= MIN_RVOL_SESSIONS:
            with np.errstate(all="ignore"):
                avg_cumv = np.nanmean(np.stack([cums[x]["cumvol"] for x in prior]), axis=0)     # (N, 75)
        else:
            avg_cumv = None
        o = cu["open"]
        with np.errstate(all="ignore"):
            gap = o / prev_close - 1.0
            orb_high = cu["high"][:, 2]                               # first 15 minutes = slots 0–2
        for k in range(per_step, SLOTS + 1, per_step):
            s = k - 1                                                 # last slot inside the step
            c, hi, vw = cu["close"][:, s], cu["high"][:, s], cu["vwap"][:, s]
            ok = cu["started"][:, s] & np.isfinite(c) & np.isfinite(o)
            with np.errstate(all="ignore"):
                up = c / o - 1.0
                sig: Dict[str, np.ndarray] = {}
                if avg_cumv is not None:
                    rv = cu["cumvol"][:, s] / avg_cumv[:, s]
                    for kk in RVOL_K:
                        sig[f"rvol{kk}"] = rv >= kk
                        for r in UP_R:
                            sig[f"rvol{kk}_up{r}"] = (rv >= kk) & (up >= r / 100.0)
                for r in UP_R:
                    sig[f"vwap_up{r}"] = (c > vw) & (up >= r / 100.0)
                for g in GAP_G:
                    sig[f"gap{g}_hold"] = (gap >= g / 100.0) & (c > o)
                if k > 6:                                             # from 09:45
                    sig["orb"] = hi > orb_high
                if k == 12:                                           # 10:15
                    for r in FIRST_HOUR_R:
                        sig[f"first_hour_up{r}"] = up >= r / 100.0
                sig["brk_prev_day"] = hi > prev_high
                sig["brk_20d"] = hi > hi20
                sig["brk_52w"] = hi > hi250
                sig["brk_all"] = hi > hiall
                sig["low52_recovery"] = near_low & (up >= 0.01)
                sig["mom_up"] = trend & (up >= 0.01)
            label = step_label(k)
            for name, mask in sig.items():
                hit = np.flatnonzero(ok & np.nan_to_num(mask, nan=0).astype(bool))
                for i in hit:
                    w.writerow([str(d), label, symbols[i], name, round(float(c[i]), 4)])
                counts[name] = counts.get(name, 0) + len(hit)
        f.flush()
        print(json.dumps({"day": str(d), "elapsed_s": round(time.monotonic() - t0, 1)}), flush=True)
    f.close()
    stats = {"symbols": len(symbols), "days": [str(d) for d in run_days], "rows_by_indicator": counts,
             "elapsed_s": round(time.monotonic() - t0, 1)}
    json.dump(stats, open(os.path.join(out_dir, "features_stats.json"), "w"), indent=1)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bars", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--days", type=int, default=None)
    a = ap.parse_args()
    s = asyncio.run(run(a.bars, a.out, a.days))
    print(json.dumps({k: v for k, v in s.items() if k != "days"}), flush=True)


if __name__ == "__main__":
    main()
