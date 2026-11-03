"""Context early indicators: market / sector tailwind, F&O build-up, results, announcements, quality, accumulation, fund
flows and deals (research, read-only). Same output format as features.py, so report.py scores them the same way.

Inputs (all point-in-time; see the extraction notes in the study report):
  idx5/{INDEX}.npz          Kite 5-minute index candles                       (ts, o, h, l, c, v)
  fut5/{SYMBOL}.npz         Kite 5-minute candles of the Nov-2026 stock future (ts, o, h, l, c, v, oi)
  daily/fut_prev.csv        D-1 futures price / OI change (bhavcopy, OI summed over expiries)
  daily/opt_prev.csv        D-1 nearest-expiry option OI breadth (share of strikes with OI up; OI change %)
  daily/results.csv         quarterly filings with broadcast_at (YoY growth)
  daily/announcements.csv   corporate announcements with broadcast_at, category, sentiment
  daily/feat_prev.csv       the feature store's D-1 row (52-week distances, quality, accumulation, delivery, slope)
  daily/mf.csv              mutual-fund scheme changes per month with known_from
  daily/deals.csv           bulk / block deals (deal date)
  daily/industry.csv        stock → industry → sector index

Every indicator below needs the stock 1 % or more above its open at the step (UP), except where said, so it marks a stock
that is already moving with the context, not a whole sector at 09:15.
  mkt_{idx}_up{r}       index {NIFTY 50, MIDCAP 100, SMALLCAP 100} r % or more above its own open at the step, and UP
  sector_up{r}_rs       the stock's sector index r % or more above its open, the stock above it (relative strength), and UP
  fut_lb_prev           D-1 futures long build-up (price up, OI up >= 5 %), and UP
  fut_oi{x}_up{r}       Nov future's OI x % or more above D-1's last OI and the price r % or more above the open
  call_breadth{s} / put_breadth{s}   D-1 nearest-expiry calls / puts with OI up on >= s % of strikes, and UP
  results_pos{n}        a filing in the last n sessions (broadcast before the step) with net profit YoY >= 20 %, and UP
  ann_pos               a positive announcement (orders, M&A, capex, buyback, rating) since the previous close, and UP
  low52_quality         D-1 within 10–30 % above the 52-week low, 50-day slope > 0, Piotroski >= 6 (from 12 Oct), and UP
  accum                 D-1 accumulation score >= 60 or delivery trend > 0 with volume z-score >= 1, and UP
  mf_net_add            the latest fund-holding month known before D: more schemes adding than reducing, and UP
  deal_prev             a bulk / block deal on the previous session (acquiring side), and UP
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from .features import cumulative
from .replay import IST_OFFSET_S, OPEN_MIN, SLOTS, Candles, day_matrix, load_candles, step_label

UP = 0.01
MKT_INDICES = {"nifty50": "NIFTY 50", "mid100": "NIFTY MIDCAP 100", "small100": "NIFTY SMALLCAP 100"}
MKT_R = (0.5, 1.0)
SECTOR_R = (0.5, 1.0)
OI_X = (5, 10, 20)
OI_R = (1, 2, 3)
BREADTH_S = (60, 75)
RESULTS_N = (1, 3)
POS_CATEGORIES = {"orders", "mna", "capex", "buyback", "rating"}


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if np.isfinite(x) else None


def _rows(path: str) -> List[Dict[str, str]]:
    if not os.path.exists(path):
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def _ts(iso: str) -> Optional[float]:
    try:
        return datetime.fromisoformat(iso).timestamp()
    except (TypeError, ValueError):
        return None


def step_end_ts(d: np.datetime64, k: int) -> float:
    """Epoch seconds of a step's end (k 5-minute slots after 09:15 IST) on day d."""
    day0 = (d - np.datetime64("1970-01-01")).astype(int) * 86400 - IST_OFFSET_S
    return float(day0 + (OPEN_MIN + 5 * k) * 60)


def series_so_far(c: Candles, d: np.datetime64) -> Optional[np.ndarray]:
    """(5, 75) of an index / future on day d, or None."""
    return c.days.get(d)


class FutOI:
    """Nov-future 5-minute candles with OI, by day: oi[d] (75,) NaN-filled; the previous session's last OI."""

    def __init__(self, path: str):
        z = np.load(path)
        self.c = Candles(z["ts"], z["o"], z["h"], z["l"], z["c"], z["oi"])     # OI stored in the volume row
        self.days = sorted(self.c.days)

    def oi_so_far(self, d: np.datetime64, k: int) -> Tuple[Optional[float], Optional[float]]:
        """(OI at the last candle within the first k slots of d, the previous session's last OI)."""
        a = self.c.days.get(d)
        if a is None:
            return None, None
        seg = a[4, :k]
        have = np.flatnonzero(~np.isnan(seg))
        now = float(seg[have[-1]]) if len(have) else None
        prev_days = [x for x in self.days if x < d]
        prev = None
        if prev_days:
            pa = self.c.days[prev_days[-1]][4]
            ph = np.flatnonzero(~np.isnan(pa))
            prev = float(pa[ph[-1]]) if len(ph) else None
        return now, prev


async def run(root: str, out_dir: str, days: Optional[int]) -> Dict[str, Any]:
    from services.scan_builder.data import get_data

    t0 = time.monotonic()
    bars_dir = os.path.join(root, "bars5")
    base = await get_data().panel()
    symbols = [s for s in sorted(f[:-4] for f in os.listdir(bars_dir) if f.endswith(".npz")) if s in base.index]
    cands = load_candles(bars_dir, symbols)
    all_days = sorted({d for c in cands.values() for d in c.days})
    run_days = all_days[-days:] if days else all_days
    pos = {s: i for i, s in enumerate(symbols)}
    N = len(symbols)

    # indices
    idx: Dict[str, Candles] = {}
    idir = os.path.join(root, "idx5")
    for f in (os.listdir(idir) if os.path.isdir(idir) else []):
        if f.endswith(".npz"):
            z = np.load(os.path.join(idir, f))
            idx[f[:-4].replace("_", " ")] = Candles(z["ts"], z["o"], z["h"], z["l"], z["c"], z["v"])
    # futures
    fut: Dict[str, FutOI] = {}
    fdir = os.path.join(root, "fut5")
    for f in (os.listdir(fdir) if os.path.isdir(fdir) else []):
        if f.endswith(".npz") and f[:-4] in pos:
            fut[f[:-4]] = FutOI(os.path.join(fdir, f))
    ddir = os.path.join(root, "daily")
    industry = {r["symbol"]: (r.get("sector_index") or "").strip() for r in _rows(os.path.join(ddir, "industry.csv"))}
    by_day = lambda name: {(r["day"], r["symbol"]): r for r in _rows(os.path.join(ddir, name))}          # noqa: E731
    fut_prev, opt_prev, feat_prev = by_day("fut_prev.csv"), by_day("opt_prev.csv"), by_day("feat_prev.csv")
    results: Dict[str, List[Tuple[float, Optional[float]]]] = defaultdict(list)
    for r in _rows(os.path.join(ddir, "results.csv")):
        t = _ts(r.get("broadcast_at", ""))
        if t is not None:
            results[r["symbol"]].append((t, _f(r.get("pat_yoy_pct"))))
    anns: Dict[str, List[float]] = defaultdict(list)
    for r in _rows(os.path.join(ddir, "announcements.csv")):
        t = _ts(r.get("broadcast_at", ""))
        if t is not None and (r.get("sentiment") or "").lower() == "positive" and (r.get("event_category") or "").lower() in POS_CATEGORIES:
            anns[r["symbol"]].append(t)
    mf: Dict[str, List[Tuple[float, int, int]]] = defaultdict(list)
    for r in _rows(os.path.join(ddir, "mf.csv")):
        t = _ts(r.get("known_from", ""))
        if t is not None:
            mf[r["symbol"]].append((t, int(float(r.get("schemes_up") or 0)), int(float(r.get("schemes_down") or 0))))
    deals: Set[Tuple[str, str]] = set()
    for r in _rows(os.path.join(ddir, "deals.csv")):
        side = (r.get("side") or "").strip().upper()
        if side in ("BUY", "B", "PURCHASE"):                                  # stored values; only the acquiring side counts
            deals.add((r.get("deal_date", "")[:10], r["symbol"]))

    os.makedirs(out_dir, exist_ok=True)
    fh = open(os.path.join(out_dir, "context.csv"), "w", newline="")
    w = csv.writer(fh)
    w.writerow(["day", "step", "symbol", "widget", "close_at_step"])
    counts: Dict[str, int] = defaultdict(int)
    for di, d in enumerate(all_days):
        if d not in run_days:
            continue
        ds = str(d)
        prev_day = str(all_days[di - 1]) if di > 0 else None
        session_start = step_end_ts(d, 0)
        prev_close_ts = step_end_ts(np.datetime64(prev_day), SLOTS) if prev_day else session_start - 86400
        cu = cumulative(day_matrix(cands, symbols, d))
        o = cu["open"]
        idx_open = {n: (c.days[d][0][~np.isnan(c.days[d][3])][0] if d in c.days and (~np.isnan(c.days[d][3])).any() else None)
                    for n, c in idx.items()}
        # per-stock day flags known before the open
        lb_prev = np.zeros(N, bool)
        callb = {s_: np.zeros(N, bool) for s_ in BREADTH_S}
        putb = {s_: np.zeros(N, bool) for s_ in BREADTH_S}
        lowq = np.zeros(N, bool)
        accum = np.zeros(N, bool)
        mfadd = np.zeros(N, bool)
        dealp = np.zeros(N, bool)
        for s, i in pos.items():
            fp = fut_prev.get((ds, s))
            if fp and (_f(fp.get("fut_price_chg_pct")) or 0) > 0 and (_f(fp.get("fut_oi_chg_pct")) or 0) >= 5:
                lb_prev[i] = True
            op = opt_prev.get((ds, s))
            if op:
                for s_ in BREADTH_S:
                    callb[s_][i] = (_f(op.get("call_oi_up_share")) or 0) * (100 if (_f(op.get("call_oi_up_share")) or 0) <= 1 else 1) >= s_
                    putb[s_][i] = (_f(op.get("put_oi_up_share")) or 0) * (100 if (_f(op.get("put_oi_up_share")) or 0) <= 1 else 1) >= s_
            fe = feat_prev.get((ds, s))
            if fe:
                dl, slope, pio = _f(fe.get("dist_52w_low_pct")), _f(fe.get("sma50_slope")), _f(fe.get("piotroski_score"))
                pit = (fe.get("quality_point_in_time") or "").lower() == "true"
                lowq[i] = bool(pit and dl is not None and 10 <= dl <= 30 and (slope or 0) > 0 and (pio or 0) >= 6)
                acc, dtr, vz = _f(fe.get("accumulation_score")), _f(fe.get("deliv_trend10")), _f(fe.get("vol_z20"))
                accum[i] = bool((acc or 0) >= 60 or ((dtr or 0) > 0 and (vz or 0) >= 1))
            known = [m for m in mf.get(s, []) if m[0] < session_start]
            if known:
                latest = max(known)
                mfadd[i] = latest[1] > latest[2]
            dealp[i] = prev_day is not None and (prev_day, s) in deals
        for k in range(3, SLOTS + 1, 3):
            sl = k - 1
            end_ts = step_end_ts(d, k)
            c = cu["close"][:, sl]
            ok = cu["started"][:, sl] & np.isfinite(c) & np.isfinite(o)
            with np.errstate(all="ignore"):
                upr = c / o - 1.0
            up = ok & (upr >= UP)
            sig: Dict[str, np.ndarray] = {}
            for key, name in MKT_INDICES.items():
                ic = idx.get(name)
                if ic is None or d not in ic.days or idx_open.get(name) is None:
                    continue
                a = ic.days[d][3, :k]
                h_ = np.flatnonzero(~np.isnan(a))
                if not len(h_):
                    continue
                ir = a[h_[-1]] / idx_open[name] - 1.0
                for r in MKT_R:
                    sig[f"mkt_{key}_up{r:g}"] = up & (ir >= r / 100.0)
            sec_ret = np.full(N, np.nan)
            for s, i in pos.items():
                nm = industry.get(s)
                ic = idx.get(nm) if nm else None
                if ic is None or d not in ic.days or idx_open.get(nm) is None:
                    continue
                a = ic.days[d][3, :k]
                h_ = np.flatnonzero(~np.isnan(a))
                if len(h_):
                    sec_ret[i] = a[h_[-1]] / idx_open[nm] - 1.0
            for r in SECTOR_R:
                sig[f"sector_up{r:g}_rs"] = up & (sec_ret >= r / 100.0) & (upr > sec_ret)
            sig["fut_lb_prev"] = up & lb_prev
            for s_ in BREADTH_S:
                sig[f"call_breadth{s_}"] = up & callb[s_]
                sig[f"put_breadth{s_}"] = up & putb[s_]
            oi_chg = np.full(N, np.nan)
            for s, fo in fut.items():
                now, prev = fo.oi_so_far(d, k)
                if now and prev:
                    oi_chg[pos[s]] = now / prev - 1.0
            for x in OI_X:
                for r in OI_R:
                    sig[f"fut_oi{x}_up{r}"] = ok & (oi_chg >= x / 100.0) & (upr >= r / 100.0)
            for n_ in RESULTS_N:
                lo_ts = step_end_ts(np.datetime64(str(all_days[max(0, di - n_)])), SLOTS) if di >= n_ else 0
                rp = np.zeros(N, bool)
                for s, lst in results.items():
                    i = pos.get(s)
                    if i is not None and any(lo_ts <= t < end_ts and (g or -1) >= 20 for t, g in lst):
                        rp[i] = True
                sig[f"results_pos{n_}"] = up & rp
            ap = np.zeros(N, bool)
            for s, lst in anns.items():
                i = pos.get(s)
                if i is not None and any(prev_close_ts <= t < end_ts for t in lst):
                    ap[i] = True
            sig["ann_pos"] = up & ap
            sig["low52_quality"] = up & lowq
            sig["accum"] = up & accum
            sig["mf_net_add"] = up & mfadd
            sig["deal_prev"] = up & dealp
            label = step_label(k)
            for name, mask in sig.items():
                for i in np.flatnonzero(np.nan_to_num(mask, nan=0).astype(bool)):
                    w.writerow([ds, label, symbols[i], name, round(float(c[i]), 4)])
                    counts[name] += 1
        fh.flush()
        print(json.dumps({"day": ds, "elapsed_s": round(time.monotonic() - t0, 1)}), flush=True)
    fh.close()
    stats = {"symbols": N, "indices": sorted(idx), "futures": len(fut), "rows_by_indicator": dict(counts),
             "elapsed_s": round(time.monotonic() - t0, 1)}
    json.dump(stats, open(os.path.join(out_dir, "context_stats.json"), "w"), indent=1)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", required=True, help="the study folder (bars5/, idx5/, fut5/, daily/)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--days", type=int, default=None)
    a = ap.parse_args()
    s = asyncio.run(run(a.root, a.out, a.days))
    print(json.dumps(s), flush=True)


if __name__ == "__main__":
    main()
