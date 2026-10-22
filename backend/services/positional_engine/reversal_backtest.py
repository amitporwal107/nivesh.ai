"""Point-in-time backtest of the near-52-week-low reversal rules (reversal_rules.py) against simpler baselines.

Research only. Pure functions over an in-memory price panel; the loader and report writer live in
scripts/run_reversal_backtest.py. Nothing here reads a database or the network.

What it measures (per variant, per horizon 5 / 10 / 20 sessions): win rate, mean and median gross return, net return after
costs, excess return over the same-day universe average, +5 % and +10 % touch rates, maximum adverse excursion,
invalidation-hit rate and failed-breakout rate, with a date-clustered bootstrap interval on the net excess mean.

Look-ahead control
* A decision on session t uses bars up to and including t only. The trade enters at the OPEN of session t+1.
* The universe on t is the top-N stocks by mean traded value over the 60 sessions ending t, with a 20-session traded value
  floor; it is computed from the panel itself, not from today's index constituents.
* Sector relative strength and breadth are computed from the same panel on date t (members' median 20-session return minus
  the equal-weight benchmark's), never from a later date. The industry TAG of a stock is today's classification and is
  therefore not point in time (a stated limitation).
* Prices are back-adjusted for splits and bonuses from the exchange's corporate-action history (dividends and rights are
  NOT adjusted: price returns, not total returns). A remaining one-session jump beyond 25 % cuts the series into segments.

Not tested here (no point-in-time data): fundamental quality groups and catalysts. The variants therefore exclude them.

Costs are round-trip percentages deducted ONCE per trade (`cost_pct + slippage_pct`); they are not applied per side.
"""
from __future__ import annotations

import bisect
import random
import statistics
from collections import defaultdict, deque
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from services.positional_engine import reversal_rules as rr

BACKTEST_VERSION = "reversal-backtest.v1 (2026-10-20)"

HORIZONS = (5, 10, 20)
TARGETS_PCT = (5.0, 10.0)
COOLDOWN_SESSIONS = 20
UNIVERSE = {"top_n": 500, "rank_window": 60, "min_traded_value_cr_20d": 10.0, "min_history": 252}
COST_SCENARIOS: Dict[str, Dict[str, float]] = {
    "base": {"cost_pct": 0.25, "slippage_pct": 0.10},     # 0.35 % round trip in total
    "higher": {"cost_pct": 0.40, "slippage_pct": 0.20},   # 0.60 % round trip in total
}
SPLIT = (0.6, 0.2, 0.2)                                   # train / validation / untouched out-of-sample, chronological
SECTOR_MIN_STOCKS = 5
SECTOR_GOOD = ("leading", "improving")
VARIANTS = ("near_low_only", "technical_reversal", "sector_plus_technical", "trigger_or_confirmed", "momentum_continuation")
MOMENTUM = {"ret20_min": 5.0, "rsi_min": 55.0, "rsi_max": 75.0}   # setup_rules.CATEGORIES["momentum"], computed from the panel
BREAK_PCT = 25.0                  # a one-session move beyond this, after adjustment, starts a new price segment (circuit limits are 20 %)


def round_trip_pct(scenario: str) -> float:
    c = COST_SCENARIOS[scenario]
    return c["cost_pct"] + c["slippage_pct"]


# ── prices ────────────────────────────────────────────────────────────────────
# A bar is {d: ISO date, o, h, l, c, pc: exchange previous close or None, v: volume or None}.

def calendar_of(by_sym: Mapping[str, Sequence[Mapping[str, Any]]]) -> List[str]:
    return sorted({b["d"] for bars in by_sym.values() for b in bars})


def action_factor(action_type: str, ratio: str, fv_pre: Optional[float] = None, fv_post: Optional[float] = None) -> Optional[float]:
    """Price factor on the ex-date: SPLIT = new face value / old (10:2 -> 0.2); BONUS a:b = a new shares per b held -> b / (a + b)
    (1:1 -> 0.5, 1:2 -> 0.667). Anything else (dividends, rights) is not adjusted. None when the terms cannot be read."""
    try:
        if action_type == "SPLIT":
            pre, post = (fv_pre, fv_post) if fv_pre and fv_post else tuple(float(x) for x in ratio.split(":"))
            return post / pre if pre and post and post < pre else None
        if action_type == "BONUS":
            a_, b_ = (float(x) for x in ratio.split(":"))
            return b_ / (a_ + b_) if a_ > 0 and b_ > 0 else None
    except (ValueError, AttributeError):
        return None
    return None


def adjust_actions(by_sym: Mapping[str, List[Dict[str, Any]]], calendar: Sequence[str],
                   actions: Sequence[Mapping[str, Any]]) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, Any]]:
    """Back-adjust OHLC (and volume) for splits and bonuses from the exchange's corporate-action history, then cut a stock's
    series into SEGMENTS wherever a one-session move beyond BREAK_PCT remains (a relisting, a merger, a missing action).

    `actions`: {symbol, ex_date, factor}. Bars dated before the ex-date are multiplied by the factor (volume divided). An
    action is "consistent" when the ex-date close lies within 0.75-1.33 of the adjusted previous close; others are counted
    in the diagnostics (the stock may have traded in a special session) but still applied, as the exchange recorded them.
    A segment boundary is point in time: signals inside a segment never see bars before the break.
    Returns (series keyed 'SYM' or 'SYM#k' for later segments, diagnostics)."""
    by_action: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
    for a in actions:
        if a.get("factor"):
            by_action[a["symbol"]].append((a["ex_date"], float(a["factor"])))
    out: Dict[str, List[Dict[str, Any]]] = {}
    diag = {"actions_in_file": len(actions), "applied": 0, "inconsistent": 0, "segments_cut": 0, "symbols_cut": []}
    for sym, bars in by_sym.items():
        new = [dict(b) for b in bars]
        for ex, f in sorted(by_action.get(sym, ()), reverse=True):
            idx = next((i for i, b in enumerate(new) if b["d"] >= ex), None)
            if idx is None or idx == 0:
                continue                                    # ex-date after the data, or before the first bar
            before = new[idx - 1]["c"] * f
            ratio = new[idx]["c"] / before if before else None
            diag["applied"] += 1
            if ratio is None or not (0.75 <= ratio <= 1.33):
                diag["inconsistent"] += 1
            for b in new[:idx]:
                for k in ("o", "h", "l", "c"):
                    b[k] *= f
                if b.get("v") is not None:
                    b["v"] /= f
        cut = [0]
        for i in range(1, len(new)):
            if abs(new[i]["c"] / new[i - 1]["c"] - 1.0) * 100.0 > BREAK_PCT:
                cut.append(i)
        cut.append(len(new))
        if len(cut) > 2:
            diag["segments_cut"] += len(cut) - 2
            diag["symbols_cut"].append(sym)
        for k in range(len(cut) - 1):
            seg = new[cut[k]:cut[k + 1]]
            if seg:
                out[sym if k == 0 else f"{sym}#{k}"] = seg
    return out, diag


def _rolling_low(lows: Sequence[float], n: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(lows)
    dq: deque = deque()
    for i, v in enumerate(lows):
        while dq and lows[dq[-1]] >= v:
            dq.pop()
        dq.append(i)
        if dq[0] <= i - n:
            dq.popleft()
        if i >= n - 1:
            out[i] = lows[dq[0]]
    return out


def _sma(vals: Sequence[float], n: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(vals)
    s = 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n:
            s -= vals[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


class _Sym:
    """Per-stock arrays computed once; every value at index i uses bars[0..i] only."""

    def __init__(self, sym: str, bars: List[Dict[str, Any]], pos: Mapping[str, int]):
        self.sym, self.bars = sym, bars
        self.cal = [pos[b["d"]] for b in bars]                      # calendar index of each bar
        self.at = {c: i for i, c in enumerate(self.cal)}            # calendar index -> bar index
        c = [b["c"] for b in bars]
        tv = [(b["c"] * (b["v"] or 0.0)) / 1e7 if b.get("v") is not None else None for b in bars]
        self.tv20 = [None] * len(bars)
        self.tv60 = [None] * len(bars)
        for i in range(len(bars)):
            for n, arr in ((20, self.tv20), (60, self.tv60)):
                if i >= n - 1 and all(x is not None for x in tv[i - n + 1:i + 1]):
                    arr[i] = sum(tv[i - n + 1:i + 1]) / n
        self.low252 = _rolling_low([b["l"] for b in bars], rr.NEAR_LOW["window_sessions"])
        self.sma50 = _sma(c, 50)
        self.rsi = rr.rsi(c)
        self.ret20 = [None] * len(bars)
        for i in range(20, len(bars)):
            if self.cal[i] - self.cal[i - 20] <= 24:
                self.ret20[i] = (c[i] / c[i - 20] - 1.0) * 100.0

    def contiguous(self, i: int, n: int) -> bool:
        """The last n bars up to i are n real sessions with at most 4 missing (a halt or a data hole)."""
        return i >= n - 1 and self.cal[i] - self.cal[i - n + 1] <= n + 3


# ── universe, benchmark, sector rotation (all computed from the panel at date t) ─

def _build_universe(syms: Mapping[str, _Sym], calendar: Sequence[str]) -> Dict[int, List[str]]:
    by_date: Dict[int, List[Tuple[float, str]]] = defaultdict(list)
    for s in syms.values():
        for i, b in enumerate(s.bars):
            if s.tv60[i] is not None and s.tv20[i] is not None and s.tv20[i] >= UNIVERSE["min_traded_value_cr_20d"] \
                    and s.contiguous(i, UNIVERSE["min_history"]):
                by_date[s.cal[i]].append((s.tv60[i], s.sym))
    return {d: [sym for _, sym in sorted(v, reverse=True)[:UNIVERSE["top_n"]]] for d, v in by_date.items()}


def _benchmark(syms: Mapping[str, _Sym], universe: Mapping[int, List[str]], n_cal: int) -> List[Optional[float]]:
    """Equal-weight benchmark: the median one-session return of the day's universe, compounded."""
    level: List[Optional[float]] = [None] * n_cal
    cur = 100.0
    started = False
    for t in range(n_cal):
        rets = []
        for sym in universe.get(t, ()):
            s = syms[sym]
            i = s.at.get(t)
            if i and s.cal[i - 1] == t - 1:
                rets.append(s.bars[i]["c"] / s.bars[i - 1]["c"] - 1.0)
        if len(rets) >= 50:
            cur *= 1.0 + statistics.median(rets)
            started = True
        if started:
            level[t] = cur
    return level


def sector_state(t: int, syms: Mapping[str, _Sym], universe: Mapping[int, List[str]], industry: Mapping[str, str],
                 bench: Sequence[Optional[float]], cache: Dict[int, Dict[str, Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    """industry -> {rs_20d, rs_change, breadth_above_50dma_pct, quadrant} on calendar index t (10 sessions back for the change)."""
    if t in cache:
        return cache[t]

    def snap(u: int) -> Dict[str, Tuple[Optional[float], Optional[float], int]]:
        if u < 20 or bench[u] is None or bench[u - 20] is None:
            return {}
        rets: Dict[str, List[float]] = defaultdict(list)
        above: Dict[str, List[int]] = defaultdict(list)
        for sym in universe.get(u, ()):
            ind = industry.get(sym.split("#")[0])
            s = syms[sym]
            i = s.at.get(u)
            if not ind or i is None:
                continue
            if s.ret20[i] is not None:
                rets[ind].append(s.ret20[i])
            if s.sma50[i] is not None:
                above[ind].append(1 if s.bars[i]["c"] > s.sma50[i] else 0)
        b20 = (bench[u] / bench[u - 20] - 1.0) * 100.0
        return {ind: (statistics.median(v) - b20, (100.0 * sum(above[ind]) / len(above[ind])) if above[ind] else None, len(v))
                for ind, v in rets.items() if len(v) >= SECTOR_MIN_STOCKS}
    now, prev = snap(t), snap(t - 10)
    out: Dict[str, Dict[str, Any]] = {}
    for ind, (rs, br, n) in now.items():
        p = prev.get(ind)
        change = None if p is None else rs - p[0]
        out[ind] = {"rs_20d": round(rs, 2), "rs_change": None if change is None else round(change, 2),
                    "breadth_above_50dma_pct": None if br is None else round(br, 1), "stocks": n,
                    "quadrant": rr.quadrant(rs, change)}
    cache[t] = out
    return out


# ── outcomes ──────────────────────────────────────────────────────────────────

def forward(bars: Sequence[Mapping[str, Any]], cal: Sequence[int], i: int, h: int,
            invalidation: Optional[float] = None, resistance: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Trade entered at the open of the next session after bar i, held h sessions (exit at that session's close).

    Needs h further bars with no more than 3 missing sessions in between; else None (the event has no outcome at h)."""
    if i + h >= len(bars) or cal[i + h] - cal[i] > h + 3:
        return None
    entry = bars[i + 1]["o"]
    if not entry:
        return None
    win = bars[i + 1:i + h + 1]
    exit_c = win[-1]["c"]
    out = {"ret": (exit_c / entry - 1.0) * 100.0,
           "mae": (min(b["l"] for b in win) / entry - 1.0) * 100.0,
           "mfe": (max(b["h"] for b in win) / entry - 1.0) * 100.0}
    for tgt in TARGETS_PCT:
        out[f"hit{int(tgt)}"] = out["mfe"] >= tgt
    out["inval"] = None if invalidation is None else any(b["c"] < invalidation for b in win)
    out["failed_breakout"] = None if resistance is None else any(b["c"] < resistance for b in win[:5])
    return out


# ── the run ───────────────────────────────────────────────────────────────────

def run(by_sym: Mapping[str, List[Dict[str, Any]]], industry: Mapping[str, str], actions: Sequence[Mapping[str, Any]] = (),
        first_signal: Optional[str] = None, last_signal: Optional[str] = None, max_near_pct: float = 20.0) -> Dict[str, Any]:
    """Raw event records for every (stock, session) the rules touch, plus universe baselines per session.

    Returns {calendar, events, momentum, universe_fwd, regime, adjustments, coverage}."""
    calendar = calendar_of(by_sym)
    adj, adj_diag = adjust_actions(by_sym, calendar, actions)
    pos = {d: i for i, d in enumerate(calendar)}
    syms = {s: _Sym(s, bars, pos) for s, bars in adj.items() if len(bars) >= 60}
    universe = _build_universe(syms, calendar)
    bench = _benchmark(syms, universe, len(calendar))
    lo = pos[first_signal] if first_signal else 0
    hi = pos[last_signal] if last_signal else len(calendar) - 1
    sector_cache: Dict[int, Dict[str, Dict[str, Any]]] = {}
    events: List[Dict[str, Any]] = []
    momentum: List[Dict[str, Any]] = []
    universe_fwd: Dict[int, Dict[int, Optional[float]]] = {}
    regime: Dict[int, str] = {}
    for t in range(lo, hi + 1):
        members = universe.get(t, [])
        if len(members) < 100 or bench[t] is None:
            continue
        regime[t] = "uptrend" if t >= 60 and bench[t - 60] and bench[t] > bench[t - 60] else "downtrend"
        fw: Dict[int, List[float]] = {h: [] for h in HORIZONS}
        sect = sector_state(t, syms, universe, industry, bench, sector_cache)
        for sym in members:
            s = syms[sym]
            i = s.at.get(t)
            if i is None:
                continue
            for h in HORIZONS:
                f = forward(s.bars, s.cal, i, h)
                if f:
                    fw[h].append(f["ret"])
            # momentum continuation (benchmark strategy)
            m = MOMENTUM
            if (s.ret20[i] is not None and s.rsi[i] is not None and s.sma50[i] is not None and i >= 70
                    and s.sma50[i - 20] is not None and s.ret20[i] >= m["ret20_min"] and m["rsi_min"] <= s.rsi[i] <= m["rsi_max"]
                    and s.bars[i]["c"] > s.sma50[i] and s.sma50[i] > s.sma50[i - 20]):
                momentum.append({"symbol": sym, "t": t, "date": calendar[t], "sym_i": i,
                                 "fwd": {h: forward(s.bars, s.cal, i, h) for h in HORIZONS}})
            # reversal pool
            low = s.low252[i]
            if low is None or not s.contiguous(i, rr.NEAR_LOW["window_sessions"]):
                continue
            dist = (s.bars[i]["c"] / low - 1.0) * 100.0
            if dist > max_near_pct:
                continue
            win = s.bars[max(0, i - 299):i + 1]
            d = rr.distance_from_low(win)
            if d["status"] != "ok":
                continue
            idx = [bench[s.cal[j]] for j in range(max(0, i - 299), i + 1)]
            index_closes = None if any(v is None for v in idx) else idx
            sig = rr.signals(win, d, index_closes)
            lv = rr.levels(win, d)
            rvol = rr.breakout_rvol(win)
            status, ev = rr.classify(d, max_near_pct, sig, lv, rvol, 100.0)
            ctx = sect.get(industry.get(sym.split("#")[0], ""))
            events.append({"symbol": sym, "t": t, "date": calendar[t], "dist": round(dist, 2), "status": status,
                           "core_true": ev["core_true"], "core_unknown": ev["core_unknown"],
                           "quadrant": ctx["quadrant"] if ctx else "unknown", "rvol": rvol,
                           "invalidation": lv.get("invalidation"), "resistance": lv.get("resistance"),
                           "fwd": {h: forward(s.bars, s.cal, i, h, lv.get("invalidation"), lv.get("resistance")) for h in HORIZONS}})
        universe_fwd[t] = {h: (sum(v) / len(v) if len(v) >= 50 else None) for h, v in fw.items()}
    first_d = min((calendar[t] for t in universe_fwd), default=None)
    return {"calendar": calendar, "events": events, "momentum": momentum, "universe_fwd": universe_fwd, "regime": regime,
            "adjustments": adj_diag, "coverage": {
                "sessions_total": len(calendar), "first_session": calendar[0] if calendar else None,
                "last_session": calendar[-1] if calendar else None, "first_signal_session": first_d,
                "signal_sessions": len(universe_fwd), "symbols_loaded": len(syms),
                "symbols_with_industry": sum(1 for s in syms if s.split("#")[0] in industry),
                "avg_universe_size": round(statistics.mean(len(universe[t]) for t in universe_fwd), 1) if universe_fwd else None}}


# ── summarising ───────────────────────────────────────────────────────────────

def select(events: Sequence[Mapping[str, Any]], variant: str, near_pct: float) -> List[Mapping[str, Any]]:
    """The events of one variant at one threshold, after the 20-session per-stock cooldown (first trigger counts)."""
    def ok(e: Mapping[str, Any]) -> bool:
        if e["dist"] > near_pct:
            return False
        if variant == "near_low_only":
            return True
        cand = e["status"] in ("early_reversal", "trigger_ready", "confirmed")
        if variant == "technical_reversal":
            return cand
        if variant == "sector_plus_technical":
            return cand and e["quadrant"] in SECTOR_GOOD
        if variant == "trigger_or_confirmed":
            return e["status"] in ("trigger_ready", "confirmed")
        raise ValueError(variant)
    last: Dict[str, int] = {}
    out = []
    for e in sorted(events, key=lambda x: (x["symbol"], x["t"])):
        if not ok(e):
            continue
        if e["symbol"] in last and e["t"] - last[e["symbol"]] < COOLDOWN_SESSIONS:
            continue
        last[e["symbol"]] = e["t"]
        out.append(e)
    return out


def cooldown(events: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    last: Dict[str, int] = {}
    out = []
    for e in sorted(events, key=lambda x: (x["symbol"], x["t"])):
        if e["symbol"] in last and e["t"] - last[e["symbol"]] < COOLDOWN_SESSIONS:
            continue
        last[e["symbol"]] = e["t"]
        out.append(e)
    return out


def _bootstrap_ci(by_date: Mapping[int, List[float]], n: int = 1000, seed: int = 7) -> Optional[Tuple[float, float]]:
    """95 % interval of the mean, resampling whole signal dates (events on one date share the market's move)."""
    dates = list(by_date)
    if len(dates) < 5:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(n):
        tot = cnt = 0
        for _ in dates:
            v = by_date[dates[rng.randrange(len(dates))]]
            tot += sum(v)
            cnt += len(v)
        means.append(tot / cnt)
    means.sort()
    return round(means[int(0.025 * n)], 3), round(means[int(0.975 * n)], 3)


def stats(events: Sequence[Mapping[str, Any]], universe_fwd: Mapping[int, Mapping[int, Optional[float]]], h: int,
          scenario: str = "base", boot: bool = True) -> Dict[str, Any]:
    """Statistics of one event set at one horizon. Returns are in percent; net = gross - round-trip cost once."""
    rt = round_trip_pct(scenario)
    rows = [(e, e["fwd"].get(h)) for e in events]
    rows = [(e, f) for e, f in rows if f]
    n = len(rows)
    out: Dict[str, Any] = {"horizon": h, "scenario": scenario, "round_trip_cost_pct": rt, "events": len(events), "n": n,
                           "symbols": len({e["symbol"] for e, _ in rows}), "dates": len({e["t"] for e, _ in rows})}
    if n == 0:
        return out
    gross = [f["ret"] for _, f in rows]
    net = [g - rt for g in gross]
    base = [universe_fwd.get(e["t"], {}).get(h) for e, _ in rows]
    exc = [nt - b for nt, b in zip(net, base) if b is not None]
    exc_g = [g - b for g, b in zip(gross, base) if b is not None]
    out.update(
        mean_gross=round(statistics.mean(gross), 3), median_gross=round(statistics.median(gross), 3),
        mean_net=round(statistics.mean(net), 3), median_net=round(statistics.median(net), 3),
        win_rate_gross=round(100.0 * sum(g > 0 for g in gross) / n, 1), win_rate_net=round(100.0 * sum(x > 0 for x in net) / n, 1),
        mean_universe_gross=round(statistics.mean(b for b in base if b is not None), 3) if exc else None,
        mean_excess_gross=round(statistics.mean(exc_g), 3) if exc_g else None,
        mean_excess_net=round(statistics.mean(exc), 3) if exc else None,
        hit5_pct=round(100.0 * sum(f["hit5"] for _, f in rows) / n, 1), hit10_pct=round(100.0 * sum(f["hit10"] for _, f in rows) / n, 1),
        mae_mean=round(statistics.mean(f["mae"] for _, f in rows), 3), mae_median=round(statistics.median(f["mae"] for _, f in rows), 3),
    )
    iv = [f["inval"] for _, f in rows if f.get("inval") is not None]
    out["invalidation_hit_pct"] = round(100.0 * sum(iv) / len(iv), 1) if iv else None
    # A failed breakout is only defined for a stock that had CLOSED through resistance on the signal session (status confirmed):
    # it fails when it closes back below that level within 5 sessions. A trigger_ready stock is still below it by definition.
    fb = [f["failed_breakout"] for e, f in rows if f.get("failed_breakout") is not None and e.get("status") == "confirmed"]
    out["failed_breakout_pct"] = round(100.0 * sum(fb) / len(fb), 1) if fb else None
    out["failed_breakout_n"] = len(fb)
    if boot and exc:
        by_date: Dict[int, List[float]] = defaultdict(list)
        for (e, _), nt, b in zip(rows, net, base):
            if b is not None:
                by_date[e["t"]].append(nt - b)
        out["mean_excess_net_ci95"] = _bootstrap_ci(by_date)
    return out


def momentum_events(rec: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    return cooldown(rec["momentum"])


def split_blocks(signal_ts: Sequence[int]) -> Dict[str, Tuple[int, int]]:
    """Chronological blocks over the signal sessions: train 60 %, validation 20 %, out-of-sample 20 % (inclusive ranges of t)."""
    ts = sorted(set(signal_ts))
    n = len(ts)
    a, b = int(n * SPLIT[0]), int(n * (SPLIT[0] + SPLIT[1]))
    if n < 10:
        return {}
    return {"train": (ts[0], ts[a - 1]), "validation": (ts[a], ts[b - 1]), "out_of_sample": (ts[b], ts[-1])}


def in_block(events: Iterable[Mapping[str, Any]], block: Tuple[int, int], gap: int = max(HORIZONS)) -> List[Mapping[str, Any]]:
    """Events whose signal session lies in the block AND whose longest outcome ends inside it (no outcome leaks across blocks)."""
    lo, hi = block
    return [e for e in events if lo <= e["t"] and e["t"] + gap <= hi]


def choose_variant(results_by_block: Mapping[str, Mapping[str, Mapping[str, Any]]], horizon_key: str = "mean_excess_net") -> Optional[str]:
    """Pick the variant with the best mean net excess return over TRAIN + VALIDATION only. The out-of-sample block is never read."""
    best, best_v = None, None
    for variant, blocks in results_by_block.items():
        vals = [blocks[b].get(horizon_key) for b in ("train", "validation") if b in blocks and blocks[b].get(horizon_key) is not None]
        if not vals:
            continue
        v = sum(vals) / len(vals)
        if best_v is None or v > best_v:
            best, best_v = variant, v
    return best
