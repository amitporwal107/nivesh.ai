"""Replay the Scan dashboard's widgets through past sessions on Kite 5-minute candles (research, read-only).

Owner, 3 Nov 2026: find the early signals in the Scan dashboard for stocks that went on to rise >= 5 % above the day's OPEN.
For every session D in the candle set and every 15-minute step s (09:30 … 15:30 IST) this rebuilds what each widget of
services/scan_builder/market_dashboard.py would have listed at s, using only what was known at s:

  * daily history: the scan builder's adjusted NSE end-of-day panel up to the session BEFORE D;
  * D's candle so far: open = the first 5-minute open, high / low = the extremes so far, close = the last 5-minute close,
    volume = the 5-minute volumes summed (Kite candles, raw prices);
  * intraday conditions (15-minute, 1-hour, 5-minute) on Kite candles aggregated from the 5-minute ones, up to s;
  * fundamentals and company results as loaded today (see LIMITS: a look-ahead for the results-based widgets).

Output (argument --out): flags.csv (day, step, symbol, widget, close_at_step) — one row per step a widget's conditions held —
and universe.csv (day, symbol, skipped) for every stock-day looked at. Outcomes and the report: outcomes.py / report.py.

LIMITS, stated in the report: the trade-side (TrueData) condition of "10x volume first 5 min" is not replayed (TrueData keeps
about a week of ticks); index memberships, fundamentals and company results are today's (survivorship / look-ahead for the
results-based widgets); a stock-day whose raw Kite high differs from the adjusted end-of-day high by > 3 % (a later split or
bonus) is skipped; the "Strong movers" 15-minute column is not a condition and is not replayed.

Run inside the staging backend container (DaaS, the panel cache):
    python -m research.early_signals.replay --bars /tmp/early_signals/bars5 --out /tmp/early_signals [--days N] [--step 15]
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import time
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

IST_OFFSET_S = 5 * 3600 + 30 * 60
OPEN_MIN = 9 * 60 + 15                      # 09:15 IST
SLOTS = 75                                  # 5-minute candles in a full session (09:15–15:30)
HIST_ROWS = 450                             # daily rows kept behind each replay day (weekly 52-period lows need ~260)
JOIN_TOL = 0.03                             # raw Kite high vs adjusted EOD high
SYMBOL_WIDGET_KINDS = ("scan", "strong")
SLOT_TIMES = [f"{(OPEN_MIN + 5 * g) // 60:02d}:{(OPEN_MIN + 5 * g) % 60:02d}" for g in range(SLOTS)]


def slot_of(ts: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """(IST day as datetime64[D], slot index 0..74) for candle START times in epoch seconds."""
    ist = ts.astype(np.int64) + IST_OFFSET_S
    day = (ist // 86400).astype("datetime64[D]")
    minute = (ist % 86400) // 60
    return day, ((minute - OPEN_MIN) // 5).astype(np.int64)


class Candles:
    """One stock's 5-minute candles by day: {day: (5, 75) float array o,h,l,c,v with NaN for a missing slot}."""

    def __init__(self, ts: np.ndarray, o, h, l, c, v):
        day, slot = slot_of(ts)
        keep = (slot >= 0) & (slot < SLOTS)
        self.days: Dict[np.datetime64, np.ndarray] = {}
        self._full: Dict[Tuple[int, np.datetime64], List[list]] = {}      # (interval, day) -> that day's candles, full session
        self._prior: Dict[Tuple[int, np.datetime64], List[list]] = {}     # (interval, day) -> every earlier day's candles
        for d in np.unique(day[keep]):
            m = keep & (day == d)
            a = np.full((5, SLOTS), np.nan)
            for row, src in enumerate((o, h, l, c, v)):
                a[row, slot[m]] = np.asarray(src, dtype=float)[m]
            self.days[d] = a

    def _agg(self, interval_min: int, d: np.datetime64, n: int) -> List[list]:
        per = interval_min // 5
        a = self.days[d]
        if per == 1:                                            # 5-minute: the slots themselves, no aggregation
            idx = np.flatnonzero(~np.isnan(a[3, :n]))
            return [[f"{d}T{SLOT_TIMES[g]}:00+05:30", *map(float, a[:, g])] for g in idx]
        out: List[list] = []
        for g in range(0, n, per):
            seg = a[:, g:min(g + per, n)]
            have = ~np.isnan(seg[3])
            if not have.any():
                continue
            idx = np.flatnonzero(have)
            start = OPEN_MIN + g * 5
            out.append([f"{d}T{start // 60:02d}:{start % 60:02d}:00+05:30", float(seg[0, idx[0]]), float(np.nanmax(seg[1])),
                        float(np.nanmin(seg[2])), float(seg[3, idx[-1]]), float(np.nansum(seg[4]))])
        return out

    def bars(self, interval_min: int, upto_day: np.datetime64, upto_slots: int) -> List[list]:
        """Candles of `interval_min` (5, 15 or 60) aggregated from the 5-minute ones, every day before `upto_day` in full and
        `upto_day` up to its first `upto_slots` 5-minute slots; [iso start, o, h, l, c, v], oldest first (intraday.compute).
        Earlier days are aggregated once and cached: a replay asks for the same history at every step of a day."""
        key = (interval_min, upto_day)
        prior = self._prior.get(key)
        if prior is None:
            prior = []
            for d in sorted(x for x in self.days if x < upto_day):
                full = self._full.get((interval_min, d))
                if full is None:
                    full = self._full[(interval_min, d)] = self._agg(interval_min, d, SLOTS)
                prior.extend(full)
            self._prior[key] = prior
        today = self._agg(interval_min, upto_day, upto_slots) if upto_day in self.days else []
        return prior + today


def load_candles(folder: str, symbols: Sequence[str]) -> Dict[str, Candles]:
    out: Dict[str, Candles] = {}
    for s in symbols:
        p = os.path.join(folder, f"{s}.npz")
        if not os.path.exists(p):
            continue
        z = np.load(p)
        if len(z["ts"]):
            out[s] = Candles(z["ts"], z["o"], z["h"], z["l"], z["c"], z["v"])
    return out


def day_matrix(cands: Dict[str, Candles], symbols: Sequence[str], d: np.datetime64) -> np.ndarray:
    """(5, N, 75) o,h,l,c,v for day d, NaN where a stock has no candle."""
    m = np.full((5, len(symbols), SLOTS), np.nan)
    for j, s in enumerate(symbols):
        a = cands[s].days.get(d) if s in cands else None
        if a is not None:
            m[:, j, :] = a
    return m


def overlay_at(m: np.ndarray, k: int) -> Tuple[np.ndarray, np.ndarray]:
    """D's candle so far from the first k slots: ((5, N) o,h,l,c,v; (N,) has a candle)."""
    seg = m[:, :, :k]
    have = ~np.isnan(seg[3])
    any_ = have.any(axis=1)
    first = np.where(any_, have.argmax(axis=1), 0)
    last = np.where(any_, k - 1 - have[:, ::-1].argmax(axis=1), 0)
    rows = np.arange(m.shape[1])
    with np.errstate(all="ignore"):
        o = np.where(any_, seg[0][rows, first], np.nan)
        h = np.where(any_, np.nanmax(np.where(have, seg[1], -np.inf), axis=1), np.nan)
        l = np.where(any_, np.nanmin(np.where(have, seg[2], np.inf), axis=1), np.nan)
        c = np.where(any_, seg[3][rows, last], np.nan)
        v = np.where(any_, np.nansum(np.where(have, seg[4], 0.0), axis=1), np.nan)
    return np.vstack([o, h, l, c, v]), any_


def step_label(k: int) -> str:
    end = OPEN_MIN + 5 * k
    return f"{end // 60:02d}:{end % 60:02d}"


async def run(bars_dir: str, out_dir: str, days: Optional[int], step_min: int) -> Dict[str, Any]:
    from services.scan_builder import engine
    from services.scan_builder import intraday as I
    from services.scan_builder import market_dashboard as MD
    from services.scan_builder import service as SV
    from services.scan_builder.data import get_data

    t0 = time.monotonic()
    meta = json.load(open(os.path.join(bars_dir, "..", "meta.json"))) if os.path.exists(os.path.join(bars_dir, "..", "meta.json")) else {}
    data = get_data()
    base = await data.panel()
    ref = await data.reference()
    results = await data.results_fields(wait=True)
    fetched = sorted(f[:-4] for f in os.listdir(bars_dir) if f.endswith(".npz"))
    symbols = [s for s in fetched if s in base.index]
    cols = np.array([base.index[s] for s in symbols])
    cands = load_candles(bars_dir, symbols)
    all_days = sorted({d for c in cands.values() for d in c.days})
    if days:
        all_days = all_days[-days:]
    widgets = [w for w in MD.WIDGETS if w.kind in SYMBOL_WIDGET_KINDS and w.spec is not None]
    pos = {s: i for i, s in enumerate(symbols)}
    uni = {}
    for key in MD.UNIVERSE_LABEL:
        mask = np.zeros(len(symbols), dtype=bool)
        for s in SV.universe_symbols(key, base, ref):
            i = pos.get(s)
            if i is not None:
                mask[i] = True
        uni[key] = mask
    funds_base = {}
    for fld in ("pe_ttm", "roce_pct", "market_cap_cr", "debt_to_equity"):
        vals = ref.fundamentals.get(fld) or {}
        funds_base[fld] = np.array([vals.get(s, np.nan) for s in symbols], dtype=float)
    os.makedirs(out_dir, exist_ok=True)
    fflags = open(os.path.join(out_dir, "flags.csv"), "w", newline="")
    funi = open(os.path.join(out_dir, "universe.csv"), "w", newline="")
    wf, wu = csv.writer(fflags), csv.writer(funi)
    wf.writerow(["day", "step", "symbol", "widget", "close_at_step"])
    wu.writerow(["day", "symbol", "skipped"])
    stats = {"days": [], "flags": 0, "stock_days": 0, "skipped_join": 0, "steps": 0}
    per_step = max(1, step_min // 5)
    pdates = base.dates
    for d in all_days:
        idx = int(np.searchsorted(pdates, d)) - 1               # last EOD row before d
        if idx < 60:
            continue
        lo = max(0, idx + 1 - HIST_ROWS)
        hist = [a[lo:idx + 1][:, cols] for a in (base.open, base.high, base.low, base.close, base.volume)]
        hdates = pdates[lo:idx + 1]
        m = day_matrix(cands, symbols, d)
        # A later split / bonus leaves the adjusted history on another scale than D's raw candles: skip such stock-days.
        skip = np.zeros(len(symbols), dtype=bool)
        j = int(np.searchsorted(pdates, d))
        if j < len(pdates) and pdates[j] == d:
            with np.errstate(all="ignore"):
                raw_high = np.nanmax(m[1], axis=1)
                adj_high = base.high[j][cols]
                ratio = raw_high / adj_high
            skip = np.isfinite(ratio) & (np.abs(ratio - 1) > JOIN_TOL)
        has_day = ~np.isnan(m[3]).all(axis=1)
        for jx in np.flatnonzero(has_day):
            wu.writerow([str(d), symbols[jx], int(skip[jx])])
        stats["stock_days"] += int(has_day.sum())
        stats["skipped_join"] += int((skip & has_day).sum())
        funds = dict(funds_base)
        if results is not None:
            funds.update(SV.results_arrays(results, symbols, date.fromisoformat(str(d))))
        day_flags = 0
        for k in range(per_step, SLOTS + 1, per_step):           # 15-minute steps: k = 3 (09:30), 6 (09:45) … 75 (15:30)
            ov, have = overlay_at(m, k)
            elig = have & ~skip
            o, h, l, c, v = (np.vstack([hist[i], ov[i][None, :]]) for i in range(5))
            panel = engine.Panel(symbols=list(symbols), dates=np.append(hdates, d), open=o, high=h, low=l, close=c, volume=v)
            c0, c1 = c[-1], c[-2]
            label = step_label(k)
            for w in widgets:
                try:
                    res = engine.evaluate(w.spec, panel, eligible=elig, universes=uni, fundamentals=funds)
                except Exception:  # noqa: BLE001 — a widget failing on one step is logged and skipped
                    logger.exception("replay: %s failed on %s %s", w.id, d, label)
                    continue
                order = list(res["order"])
                if w.intraday is not None and w.intraday.test is not None and order:
                    iv = int(w.intraday.interval.replace("minute", ""))
                    bars = {symbols[i]: cands[symbols[i]].bars(iv, d, k) for i in order if symbols[i] in cands}
                    vals = I.compute(bars, w.intraday.needs) if bars else {}
                    keys = [n[0] for n in w.intraday.needs]
                    order = [i for i in order if all(vals.get(symbols[i], {}).get(x) is not None for x in keys)
                             and w.intraday.test(vals[symbols[i]], float(c0[i]), float(c1[i]))]
                for i in order:
                    wf.writerow([str(d), label, symbols[i], w.id, round(float(c0[i]), 4)])
                day_flags += len(order)
            stats["steps"] += 1
        stats["flags"] += day_flags
        stats["days"].append({"day": str(d), "flags": day_flags, "stock_days": int(has_day.sum()),
                              "skipped": int((skip & has_day).sum()), "elapsed_s": round(time.monotonic() - t0, 1)})
        fflags.flush()
        funi.flush()
        print(json.dumps(stats["days"][-1]), flush=True)
    fflags.close()
    funi.close()
    stats.update(symbols=len(symbols), widgets=[w.id for w in widgets], elapsed_s=round(time.monotonic() - t0, 1),
                 meta_sessions=len(meta.get("sessions") or []))
    json.dump(stats, open(os.path.join(out_dir, "replay_stats.json"), "w"), indent=1)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bars", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--step", type=int, default=15, help="minutes between replay steps (multiple of 5)")
    a = ap.parse_args()
    s = asyncio.run(run(a.bars, a.out, a.days, a.step))
    print(json.dumps({k: v for k, v in s.items() if k != "days"}), flush=True)


if __name__ == "__main__":
    main()
