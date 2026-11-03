"""What happened after each dashboard flag, measured on the same 5-minute candles the replay used.

Definitions (owner, 3 Nov 2026: a move is measured FROM THE DAY'S OPEN, up moves only):
  open        the open of the stock-day's first 5-minute candle
  t5          the END time of the first 5-minute candle whose high is at least 1.05 x open (None: never that day)
  flag time   the end of the replay step at which the flag was raised ("HH:MM" IST); only candles ending at or before it
              were known to the replay
  early       the stock had not yet reached +5% at the flag time (t5 is None or t5 > flag time). A flag at or after t5 is
              "late": the move had already happened, so it is not counted as an early signal
  hit         early and the stock then reached +5% above the open (t5 > flag time)
  lead time   t5 - flag time, minutes (hits only)
  move done   (flag price - open) / open, % — how much of the move had happened by the flag
  upside      highest high of the candles from the flag time to the close, as % above the flag price
  drawdown    lowest low from the flag time up to and including the candle of that highest high, as % below the flag
              price; 0 when it never traded below the flag price
  close       (day's close - flag price) / flag price, %

Signals measured, each by its FIRST flag per stock-day:
  w:<widget>      one widget
  k>=<k>          confluence: the first step at which at least k distinct widgets flag the stock at the same step (k = 1..4)
  p:<a>+<b>       a pair: the first step at which both widgets flag the stock at the same step
Candles are Kite's raw 5-minute candles (timestamps = candle START, epoch seconds). Research only.
"""
from __future__ import annotations

import csv
import itertools
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

IST = timezone(timedelta(hours=5, minutes=30))
CANDLE_S = 300
MOVE = 0.05
MAX_K = 4
OUTCOME_COLUMNS = ["signal", "kind", "day", "symbol", "step", "flag_ts", "flag_price", "open", "move_done_pct", "early",
                   "hit", "late", "lead_min", "upside_pct", "drawdown_pct", "close_vs_flag_pct", "reached5"]


@dataclass
class Day:
    """One stock-day of 5-minute candles (sorted by start time) and its summary."""
    ts: np.ndarray            # candle start, epoch s
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    open: float
    t5: Optional[int]         # end of the first candle with high >= 1.05 x open, epoch s
    high: float
    high_ts: int              # start of the candle that made the day's high
    close: float


def step_ts(day: str, step: str) -> int:
    """Epoch seconds of "HH:MM" IST on `day` (YYYY-MM-DD)."""
    hh, mm = (int(x) for x in step.split(":"))
    return int(datetime.combine(date.fromisoformat(day), time(hh, mm), tzinfo=IST).timestamp())


def _ist_day(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), IST).date().isoformat()


def load_npz(path: str) -> Dict[str, np.ndarray]:
    with np.load(path) as z:
        return {k: np.asarray(z[k]) for k in ("ts", "o", "h", "l", "c", "v") if k in z.files}


def split_days(bars: Dict[str, np.ndarray]) -> Dict[str, Day]:
    """{YYYY-MM-DD: Day} from one symbol's candles. Candles with a missing price are dropped."""
    ts = np.asarray(bars["ts"], dtype=np.int64)
    o, h, l, c = (np.asarray(bars[k], dtype=float) for k in ("o", "h", "l", "c"))
    ok = np.isfinite(o) & np.isfinite(h) & np.isfinite(l) & np.isfinite(c) & (o > 0)
    ts, o, h, l, c = ts[ok], o[ok], h[ok], l[ok], c[ok]
    order = np.argsort(ts, kind="stable")
    ts, o, h, l, c = ts[order], o[order], h[order], l[order], c[order]
    days: Dict[str, Day] = {}
    keys = np.array([_ist_day(t) for t in ts]) if len(ts) else np.array([])
    for d in dict.fromkeys(keys.tolist()):
        m = keys == d
        days[d] = make_day(ts[m], o[m], h[m], l[m], c[m])
    return days


def make_day(ts, o, h, l, c) -> Day:
    ts = np.asarray(ts, dtype=np.int64)
    o, h, l, c = (np.asarray(x, dtype=float) for x in (o, h, l, c))
    op = float(o[0])
    hit = np.flatnonzero(h >= (1 + MOVE) * op)
    t5 = int(ts[hit[0]]) + CANDLE_S if len(hit) else None
    j = int(np.argmax(h))
    return Day(ts, o, h, l, c, op, t5, float(h[j]), int(ts[j]), float(c[-1]))


def price_at(day: Day, at_ts: int) -> Optional[float]:
    """Close of the last candle that ENDED at or before `at_ts` (what the replay could see)."""
    known = np.flatnonzero(day.ts + CANDLE_S <= at_ts)
    return float(day.c[known[-1]]) if len(known) else None


def after_flag(day: Day, flag_ts: int, flag_price: float) -> Tuple[Optional[float], Optional[float]]:
    """(upside %, drawdown %) after the flag: candles starting at or after the flag time, to the close."""
    idx = np.flatnonzero(day.ts >= flag_ts)
    if not len(idx) or not flag_price > 0:
        return None, None
    hs = day.h[idx]
    j = int(np.argmax(hs))
    upside = (float(hs[j]) / flag_price - 1) * 100
    low = float(np.min(day.l[idx[: j + 1]]))
    drawdown = min(0.0, (low / flag_price - 1) * 100)
    return upside, drawdown


def outcome(day: Day, d: str, symbol: str, signal: str, kind: str, step: str, flag_price: Optional[float]) -> Dict:
    fts = step_ts(d, step)
    price = flag_price if flag_price is not None and np.isfinite(flag_price) and flag_price > 0 else price_at(day, fts)
    late = day.t5 is not None and day.t5 <= fts
    hit = day.t5 is not None and day.t5 > fts
    up, dd = after_flag(day, fts, price) if price else (None, None)
    return {
        "signal": signal, "kind": kind, "day": d, "symbol": symbol, "step": step, "flag_ts": fts,
        "flag_price": price, "open": day.open,
        "move_done_pct": (price / day.open - 1) * 100 if price else None,
        "early": not late, "hit": hit, "late": late,
        "lead_min": (day.t5 - fts) / 60 if hit else None,
        "upside_pct": up, "drawdown_pct": dd,
        "close_vs_flag_pct": (day.close / price - 1) * 100 if price else None,
        "reached5": day.t5 is not None,
    }


def read_flags(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"day": str, "step": str, "symbol": str, "widget": str})
    if "close_at_step" not in df.columns:
        df["close_at_step"] = np.nan
    return df[["day", "step", "symbol", "widget", "close_at_step"]]


def read_universe(path: str) -> pd.DataFrame:
    """The stock-days the replay looked at, without those it skipped (Kite vs warehouse scale mismatch)."""
    u = pd.read_csv(path, dtype={"day": str, "symbol": str})
    if "skipped" in u.columns:
        u = u[pd.to_numeric(u["skipped"], errors="coerce").fillna(0).astype(int) == 0]
    return u[["day", "symbol"]].drop_duplicates()


def first_signals(flags: pd.DataFrame, max_k: int = MAX_K, pairs: bool = True) -> pd.DataFrame:
    """One row per (signal, day, symbol): the FIRST step of each widget, of each confluence level k, and of each pair."""
    if flags.empty:
        return pd.DataFrame(columns=["signal", "kind", "day", "symbol", "step", "price"])
    f = flags.copy()
    f["_t"] = f["step"].map(lambda s: tuple(int(x) for x in s.split(":")))
    rows: List[Tuple[str, str, str, str, str, float]] = []
    # one widget: its first step
    w = f.sort_values("_t").drop_duplicates(["day", "symbol", "widget"], keep="first")
    rows += [(f"w:{r.widget}", "widget", r.day, r.symbol, r.step, r.close_at_step) for r in w.itertuples()]
    # widgets flagging the stock at each step
    g = (f.sort_values("_t").groupby(["day", "symbol", "step"], sort=False)
         .agg(widgets=("widget", lambda s: tuple(sorted(set(s)))), price=("close_at_step", "first"), _t=("_t", "first"))
         .reset_index().sort_values(["day", "symbol", "_t"]))
    seen_k: set = set()
    seen_p: set = set()
    for r in g.itertuples():
        n = len(r.widgets)
        for k in range(1, min(n, max_k) + 1):
            key = (r.day, r.symbol, k)
            if key not in seen_k:
                seen_k.add(key)
                rows.append((f"k>={k}", "confluence", r.day, r.symbol, r.step, r.price))
        if pairs and n >= 2:
            for a, b in itertools.combinations(r.widgets, 2):
                key = (r.day, r.symbol, a, b)
                if key not in seen_p:
                    seen_p.add(key)
                    rows.append((f"p:{a}+{b}", "pair", r.day, r.symbol, r.step, r.price))
    return pd.DataFrame(rows, columns=["signal", "kind", "day", "symbol", "step", "price"])


def load_days(bars_dir: str, symbols: Iterable[str]) -> Dict[str, Dict[str, Day]]:
    """{symbol: {day: Day}} for every symbol with a {symbol}.npz in `bars_dir`."""
    out: Dict[str, Dict[str, Day]] = {}
    for s in sorted(set(symbols)):
        p = os.path.join(bars_dir, f"{s}.npz")
        if os.path.exists(p):
            out[s] = split_days(load_npz(p))
    return out


def stock_days(days: Dict[str, Dict[str, Day]], universe: pd.DataFrame) -> pd.DataFrame:
    """The universe's stock-days that have candles: open, t5, day high (+ its candle start), close."""
    rows = []
    for r in universe.itertuples():
        dd = days.get(r.symbol, {}).get(r.day)
        if dd is None:
            continue
        rows.append({"day": r.day, "symbol": r.symbol, "open": dd.open, "t5": dd.t5, "high": dd.high,
                     "high_ts": dd.high_ts, "close": dd.close})
    return pd.DataFrame(rows, columns=["day", "symbol", "open", "t5", "high", "high_ts", "close"])


def outcomes(firsts: pd.DataFrame, days: Dict[str, Dict[str, Day]]) -> pd.DataFrame:
    """One outcome row per first signal whose stock-day has candles (OUTCOME_COLUMNS)."""
    rows = []
    for r in firsts.itertuples():
        dd = days.get(r.symbol, {}).get(r.day)
        if dd is None:
            continue
        rows.append(outcome(dd, r.day, r.symbol, r.signal, r.kind, r.step, r.price))
    return pd.DataFrame(rows, columns=OUTCOME_COLUMNS)


def base_rates(sd: pd.DataFrame, steps: Sequence[str]) -> Dict[Tuple[str, str], float]:
    """{(day, step): share of the day's stock-days not yet at +5% at that step that reach +5% later}."""
    out: Dict[Tuple[str, str], float] = {}
    for d, grp in sd.groupby("day"):
        t5 = pd.to_numeric(grp["t5"], errors="coerce").to_numpy(dtype=float)   # NaN = never
        for s in steps:
            ts = step_ts(d, s)
            eligible = np.isnan(t5) | (t5 > ts)
            n = int(eligible.sum())
            out[(d, s)] = float(np.sum(eligible & ~np.isnan(t5)) / n) if n else float("nan")
    return out


def write_csv(df: pd.DataFrame, path: str) -> None:
    df.to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)
