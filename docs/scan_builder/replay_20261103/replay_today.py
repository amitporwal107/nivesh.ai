"""Replay of 3 Nov 2026: both scan dashboards (atlas = Chartink 247498, daytrade = 503347) rebuilt every STEP minutes as
they would have looked during the session, from today's 1-minute Kite candles. Read-only research.

Runs inside nivesh-staging-app-backend with the branch's scan_builder package at /tmp/dt/scan_builder:
  * daily history: the scan builder's adjusted NSE end-of-day panel to 2 Nov (the live dashboard's own panel file);
  * today's candle at step T: open = the first 1-minute open, high / low = the extremes of the minutes before T, close = the
    last 1-minute close before T, volume = the 1-minute volumes summed (Kite candles, raw prices);
  * intraday conditions: candles of the widget's interval built from the same 1-minute candles up to T (the candle in
    progress included, as live), over the earlier sessions' Kite 5-minute candles stored by session fffb64a1's study
    (/tmp/early_signals/bars5, 1,593 liquid stocks; a stock without them cannot pass a condition that needs history);
  * fundamentals and company results as loaded today (a look-ahead for results announced during today's session);
  * NOT replayed: the TrueData trade-side condition of "10x volume first 5 min" (TrueData's login is refused since ~17:40,
    so that widget lists the stocks passing its other conditions), index levels (not a stock list).
Every widget is computed by market_dashboard.compute itself: the replay only replaces the data edges.

Writes OUT/flags.csv (step, dashboard, widget, title, symbol, price) and OUT/days.csv (per-stock day path summary).
"""
import asyncio
import csv
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

import numpy as np

sys.path.insert(0, "/app/backend")
import services  # noqa: E402

services.__path__.insert(0, "/tmp/dt")
from services.scan_builder import intraday as SI  # noqa: E402
from services.scan_builder import market_dashboard as MD  # noqa: E402
from services.scan_builder.data import TodayOverlay, get_data  # noqa: E402

assert MD.__file__.startswith("/tmp/dt"), MD.__file__

DAY = "2026-11-03"
MINUTES = "/tmp/replay_20261103/minutes.jsonl"
BARS5 = "/tmp/early_signals/bars5"
OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/replay_20261103/out"
STEP = int(sys.argv[2]) if len(sys.argv) > 2 else 5
N_MIN = 375                                   # 09:15 … 15:29
OPEN_MIN = 9 * 60 + 15
IST_S = 5 * 3600 + 30 * 60
GAP_SKIP = 0.25                               # today's first open vs the adjusted previous close: beyond this, a corporate action


def hhmm(m: int) -> str:
    t = OPEN_MIN + m
    return f"{t // 60:02d}:{t % 60:02d}"


def load_minutes(symbols: List[str]):
    pos = {s: j for j, s in enumerate(symbols)}
    a = np.full((5, len(symbols), N_MIN), np.nan)
    seen = set()
    for ln in open(MINUTES):
        r = json.loads(ln)
        s = r.get("s")
        if s not in pos or s in seen or not r.get("b"):
            continue
        seen.add(s)
        j = pos[s]
        for b in r["b"]:
            m = int(b[0][11:13]) * 60 + int(b[0][14:16]) - OPEN_MIN
            if 0 <= m < N_MIN:
                a[:, j, m] = b[1:6]
    return a, seen


def prior_5m(sym: str) -> List[list]:
    """Earlier sessions' Kite 5-minute candles as [iso IST, o, h, l, c, v], oldest first (empty without a stored file)."""
    p = os.path.join(BARS5, f"{sym}.npz")
    if not os.path.exists(p):
        return []
    z = np.load(p)
    out = []
    for ts, o, h, l, c, v in zip(z["ts"], z["o"], z["h"], z["l"], z["c"], z["v"]):
        t = int(ts) + IST_S
        d = np.datetime64(t // 86400, "D").astype(str)
        if d >= DAY:
            continue
        mm = (t % 86400) // 60
        out.append([f"{d}T{mm // 60:02d}:{mm % 60:02d}:00+05:30", float(o), float(h), float(l), float(c), float(v)])
    return out


@dataclass
class Res:
    values: Dict[str, Dict[str, Optional[float]]]
    as_of: Optional[str]
    source: str = "REPLAY: Kite 1-minute candles of 3 Nov 2026 over stored Kite 5-minute candles"
    warnings: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)


class Replay:
    def __init__(self, base, ref, results, mins, symbols):
        self.base, self.ref, self.results, self.mins = base, ref, results, mins
        self.symbols = symbols
        self.col = {s: j for j, s in enumerate(symbols)}
        self.t_end = 0
        self._prior: Dict[tuple, List[list]] = {}
        o, h, l, c, v = mins
        traded = ~np.isnan(c)
        self.first_open = np.full(len(symbols), np.nan)
        any_t = traded.any(axis=1)
        first = np.argmax(traded, axis=1)
        self.first_open[any_t] = o[np.flatnonzero(any_t), first[any_t]]
        self.cum_h = np.fmax.accumulate(h, axis=1)
        self.cum_l = np.fmin.accumulate(l, axis=1)
        self.cum_v = np.nancumsum(v, axis=1)
        idx = np.where(traded, np.arange(N_MIN)[None, :], -1)
        self.last_idx = np.maximum.accumulate(idx, axis=1)
        prev = base.close[-1]
        self.skip = set()
        for j, s in enumerate(symbols):
            p = prev[base.index[s]] if s in base.index else np.nan
            if np.isfinite(self.first_open[j]) and np.isfinite(p) and p > 0 and abs(self.first_open[j] / p - 1) > GAP_SKIP:
                self.skip.add(s)

    # ── the data edges market_dashboard.compute reads ──
    async def panel(self):
        return self.base

    async def reference(self):
        return self.ref

    async def results_fields(self, wait=False):
        return self.results

    async def today(self, base, syms):
        t = self.t_end - 1
        bars = {}
        for s in syms:
            j = self.col.get(s)
            if j is None or s in self.skip:
                continue
            li = self.last_idx[j, t]
            if li < 0:
                continue                                         # not traded yet at this step
            bars[base.index[s]] = [float(self.first_open[j]), float(self.cum_h[j, t]), float(self.cum_l[j, t]),
                                   float(self.mins[3][j, li]), float(self.cum_v[j, t])]
        return TodayOverlay(mode="live", day=date.fromisoformat(DAY), bars=bars, quote_as_of=f"{DAY}T{hhmm(self.t_end)}:00+05:30",
                            counts={}, warnings=[], session_open=True)

    def _today_candles(self, j: int, minutes: int) -> List[list]:
        o, h, l, c, v = (a[j, :self.t_end] for a in self.mins)
        out = []
        for g in range(0, self.t_end, minutes):
            sl = slice(g, min(g + minutes, self.t_end))
            cc = c[sl]
            ok = ~np.isnan(cc)
            if not ok.any():
                continue
            k = np.flatnonzero(ok)
            out.append([f"{DAY}T{hhmm(g)}:00+05:30", float(o[sl][k[0]]), float(np.nanmax(h[sl])), float(np.nanmin(l[sl])),
                        float(cc[k[-1]]), float(np.nansum(v[sl]))])
        return out

    def _prior_candles(self, s: str, minutes: int) -> List[list]:
        key = (s, minutes)
        if key not in self._prior:
            b5 = prior_5m(s)
            self._prior[key] = b5 if minutes == 5 else SI.regroup(b5, minutes)
        return self._prior[key]

    async def intraday_values(self, symbols, interval, needs, *, lookback_days, live_prices=None):
        minutes = SI.INTERVALS[interval][1]
        have, missing = {}, []
        for s in symbols:
            j = self.col.get(s)
            today = self._today_candles(j, minutes) if j is not None else []
            if not today:
                missing.append(s)
                continue
            prior = self._prior_candles(s, minutes)
            if prior:
                days = sorted({b[0][:10] for b in prior})[-(max(1, lookback_days) - 1):] if lookback_days > 1 else []
                prior = [b for b in prior if b[0][:10] in days]
            have[s] = prior + today
        vals = SI.compute(have, needs) if have else {}
        as_of = f"{DAY}T{hhmm(((self.t_end - 1) // minutes) * minutes)}:00+05:30"
        return Res(values=vals, as_of=as_of, missing=missing)

    async def tick_flow(self, symbols):
        return Res(values={}, as_of=None, source="",
                   warnings=["not replayed: TrueData tick history is unavailable (login refused since 3 Nov ~17:40)"])

    async def index_result(self, names):
        return {"rows": [], "warnings": [], "basis": {"text": "not replayed"}}


async def main():
    os.makedirs(OUT, exist_ok=True)
    real = get_data()
    base = await real.panel()
    ref = await real.reference()
    results = await real.results_fields(wait=True)
    assert str(base.eod_date) == "2026-11-02", base.eod_date
    symbols = list(base.symbols)
    mins, seen = load_minutes(symbols)
    rp = Replay(base, ref, results, mins, symbols)
    print(f"panel {len(symbols)} stocks to {base.eod_date}; minute candles for {len(seen)}; skipped (gap > 25 %): "
          f"{sorted(rp.skip)}", flush=True)

    # per-stock day summary from the 1-minute path
    o, h, l, c, v = mins
    with open(os.path.join(OUT, "days.csv"), "w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["symbol", "prev_close", "open", "high", "low", "close", "volume", "high_min", "low_min", "range_pct",
                     "range5_min", "avg_vol20", "fno", "nifty50", "skipped"])
        prev = base.close[-1]
        v20 = np.nanmean(base.volume[-20:], axis=0)
        for j, s in enumerate(symbols):
            if s not in seen:
                continue
            op = rp.first_open[j]
            if not np.isfinite(op):
                continue
            hh, ll = np.nanmax(h[j]), np.nanmin(l[j])
            rng = (rp.cum_h[j] - rp.cum_l[j]) / op * 100
            hit = np.flatnonzero(rng >= 5.0)
            wr.writerow([s, round(float(prev[base.index[s]]), 4), op, hh, ll, float(c[j, rp.last_idx[j, -1]]),
                         float(np.nansum(v[j])), int(np.nanargmax(h[j])), int(np.nanargmin(l[j])),
                         round(float((hh - ll) / op * 100), 3), int(hit[0]) if hit.size else "",
                         round(float(v20[base.index[s]]), 0), int(s in ref.fno),
                         int(s in (ref.members.get("nifty50") or set())), int(s in rp.skip)])

    t0 = time.monotonic()
    with open(os.path.join(OUT, "flags.csv"), "w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["step_min", "step", "dashboard", "widget", "title", "symbol", "price"])
        status_log = {}
        for t_end in range(STEP, N_MIN + 1, STEP):
            rp.t_end = t_end
            for key in ("atlas", "daytrade"):
                out = await MD.compute(rp, dashboard=key, intraday_values=rp.intraday_values,
                                       index_result=rp.index_result, tick_flow=rp.tick_flow)
                for w in out["widgets"]:
                    status_log.setdefault((key, w["id"]), {}).setdefault(w["status"], 0)
                    status_log[(key, w["id"])][w["status"]] += 1
                    if w["row_kind"] != "symbol" or w["status"] in ("not_computed", "pending", "error"):
                        continue
                    for r in w["rows"]:
                        wr.writerow([t_end, hhmm(t_end), key, w["id"], w["title"], r[0], r[2]])
            if t_end % 30 == 0 or t_end == STEP:
                print(f"step {hhmm(t_end)} done, {time.monotonic() - t0:.0f}s", flush=True)
    json.dump({f"{k}:{w}": s for (k, w), s in status_log.items()}, open(os.path.join(OUT, "statuses.json"), "w"), indent=1)
    print(f"DONE {time.monotonic() - t0:.0f}s", flush=True)


asyncio.run(main())
