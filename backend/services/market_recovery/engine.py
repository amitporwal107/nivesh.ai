"""Market Recovery (recovery-radar-v1): the computation behind GET /api/market-recovery.

The rules are docs/market_recovery/DESIGN.md §"Rules"; the section numbers below refer to it. Weights are the owner's pasted
proposal (3 Nov 2026), thresholds are untuned, and nothing here has been back-tested: the page says so.

No I/O here. service.py loads the data into `Inputs` and calls `compute()`. The price arrays are the scan builder's
common-calendar panel (rows = sessions ascending, the last row is the scored session; columns = stocks; NaN = no bar), so
"n sessions ago" is a row offset and every indicator comes from services/scan_builder/indicators.py.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import numpy as np

from services.scan_builder import indicators as ind

METHOD = "recovery-radar-v1"
PLAN_METHOD = "recovery-plan-v1"
PRIORITY_SCORE = 75.0
MIN_TRADED_VALUE_CR = 5.0
MIN_MARKET_CAP_CR = 1000.0
MIN_HISTORY = 60
SERIES_SESSIONS = 30
LEADER_COUNT = 5
MIN_SECTOR_MEMBERS = 5
TOP_N = 10
EXCLUDED_N = 10
FINANCIALS = "Financial Services"
LAG = 5                                    # "5 sessions ago"

Num = Optional[float]


# ── small helpers ─────────────────────────────────────────────────────────────────────────────────────────────────────

def fnum(v: Any) -> Num:
    """A finite float, or None (NaN, None, text, bool)."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def ramp(x: Num, lo: float, hi: float) -> Num:
    """0 at or below lo, 1 at or above hi, linear between; None when x is None."""
    if x is None:
        return None
    if x <= lo:
        return 0.0
    if x >= hi:
        return 1.0
    return (x - lo) / (hi - lo)


def r1(v: Num, dp: int = 1) -> Num:
    return None if v is None else round(v, dp)


def pct_of(flags: Iterable[Optional[bool]]) -> Tuple[Num, int]:
    """(% of the known flags that are True, how many were known)."""
    known = [f for f in flags if f is not None]
    if not known:
        return None, 0
    return 100.0 * sum(1 for f in known if f) / len(known), len(known)


def _at(a: np.ndarray, row: int, j: int) -> Num:
    """a[row, j] as a float, or None (row counts from the end when negative)."""
    if -a.shape[0] <= row < a.shape[0]:
        return fnum(a[row, j])
    return None


def pct_ranks(values: Dict[str, Num]) -> Dict[str, float]:
    """Percentile rank 0..1 (ties share the average rank) of each known value."""
    known = [(k, v) for k, v in values.items() if v is not None]
    if not known:
        return {}
    if len(known) == 1:
        return {known[0][0]: 0.5}
    xs = np.array([v for _, v in known])
    order = xs.argsort(kind="stable")
    ranks = np.empty(len(xs))
    ranks[order] = np.arange(len(xs), dtype=float)
    for v in np.unique(xs):                                      # average rank for ties
        m = xs == v
        if m.sum() > 1:
            ranks[m] = ranks[m].mean()
    ranks /= (len(xs) - 1)
    return {k: float(r) for (k, _), r in zip(known, ranks)}


# ── inputs ────────────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class Inputs:
    as_of: date
    dates: np.ndarray                                 # (T,) datetime64[D] ascending; the last row is `as_of`
    symbols: List[str]                                # N columns
    close: np.ndarray                                 # (T, N) split/bonus adjusted
    high: np.ndarray
    low: np.ndarray
    volume: np.ndarray
    industry: Dict[str, str]                          # symbol -> NSE industry (Nifty 500 constituent list)
    names: Dict[str, str] = field(default_factory=dict)
    caps: Dict[str, Set[str]] = field(default_factory=dict)          # "large" | "mid" | "small" -> members
    nifty50: List[Tuple[date, float]] = field(default_factory=list)  # ascending, up to as_of
    nifty500: List[Tuple[date, float]] = field(default_factory=list)
    vix: List[Tuple[date, float]] = field(default_factory=list)
    features_now: Dict[str, Dict[str, Any]] = field(default_factory=dict)   # symbol -> stock_features_daily row
    features_then: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # the row 5 sessions earlier
    features_as_of: Optional[str] = None
    delivery: Dict[str, List[float]] = field(default_factory=dict)          # symbol -> last <= 5 delivery %, oldest first
    delivery_as_of: Optional[str] = None
    fno: Dict[str, Dict[str, Num]] = field(default_factory=dict)            # symbol -> price_chg, oi_chg, prev_price_chg, prev_oi_chg
    fno_as_of: Optional[str] = None
    members_total: int = 0
    members_as_of: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    sources: List[Dict[str, Any]] = field(default_factory=list)


class StaleData(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# ── arrays ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def indicator_arrays(close: np.ndarray, high: np.ndarray, low: np.ndarray, volume: np.ndarray) -> Dict[str, np.ndarray]:
    """Every (T, N) series the rules read."""
    c, h, l, v = close, high, low, volume
    prev = ind.shift(c, 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        up = np.where(np.isnan(c) | np.isnan(prev), np.nan, (c > prev).astype(float))
        down = np.where(np.isnan(c) | np.isnan(prev), np.nan, (c < prev).astype(float))
        vol_up = np.where(up == 1.0, v, np.where(np.isnan(up), np.nan, 0.0))
        vol_down = np.where(down == 1.0, v, np.where(np.isnan(down), np.nan, 0.0))
        avg20_prev = ind.shift(ind.sma(v, 20), 1)                  # the 20 sessions before the row
        upvol_day = np.where(np.isnan(up) | np.isnan(avg20_prev), np.nan, ((up == 1.0) & (v > avg20_prev)).astype(float))
        out = {
            "close": c, "high": h, "low": l, "volume": v,
            "sma20": ind.sma(c, 20), "sma50": ind.sma(c, 50), "sma200": ind.sma(c, 200),
            "ema20": ind.ema(c, 20), "ema50": ind.ema(c, 50),
            "rsi14": ind.rsi(c, 14), "atr14": ind.atr(h, l, c, 14),
            "r5": c / ind.shift(c, 5) - 1.0, "r10": c / ind.shift(c, 10) - 1.0, "r20": c / ind.shift(c, 20) - 1.0,
            "up": up,
            "vol_ratio": ind.sma(v, 5) / ind.shift(ind.sma(v, 50), 5),          # 5-session avg ÷ the 50 sessions before
            "vol_base50": ind.shift(ind.sma(v, 50), 5),
            "vol_avg250": ind.sma(v, 250),
            "vol_avg20_prev": avg20_prev,
            "ud10": ind.sma(vol_up, 10) / ind.sma(vol_down, 10),                 # up-day ÷ down-day volume, 10 sessions
            "tv20_cr": ind.sma(c * v, 20) / 1e7,                                 # ₹ crore
            "low10": ind.rolling_min(l, 10),
            "high20_prev": ind.shift(ind.rolling_max(h, 20), 1),
            "high20": ind.rolling_max(h, 20), "low20": ind.rolling_min(l, 20),
            "high60": ind.rolling_max(h, 60),
            "upvol5": ind.sma(upvol_day, 5) * 5,
        }
        out["higher_low"] = np.where(np.isnan(out["low10"]) | np.isnan(ind.shift(out["low10"], 10)), np.nan,
                                     (out["low10"] > ind.shift(out["low10"], 10)).astype(float))
    return out


def breadth_at(a: Dict[str, np.ndarray], row: int, cols: Optional[Sequence[int]] = None) -> Dict[str, Num]:
    """% above SMA20 / SMA50 and % advancers on one row, over `cols` (all when None)."""
    sl = slice(None) if cols is None else list(cols)
    c, s20, s50, up = a["close"][row, sl], a["sma20"][row, sl], a["sma50"][row, sl], a["up"][row, sl]
    with np.errstate(invalid="ignore"):
        ok20 = ~np.isnan(c) & ~np.isnan(s20)
        ok50 = ~np.isnan(c) & ~np.isnan(s50)
        okup = ~np.isnan(up)
        return {
            "above20_pct": float(100.0 * (c[ok20] > s20[ok20]).mean()) if ok20.any() else None,
            "above50_pct": float(100.0 * (c[ok50] > s50[ok50]).mean()) if ok50.any() else None,
            "advancers_pct": float(100.0 * up[okup].mean()) if okup.any() else None,
            "counted": int(ok20.sum()),
        }


# ── index series ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _closes(series: Sequence[Tuple[date, float]], as_of: date) -> Tuple[List[float], Optional[date]]:
    xs = [(d, fnum(c)) for d, c in series if d <= as_of and fnum(c) is not None]
    return [c for _, c in xs], (xs[-1][0] if xs else None)


def idx_ret(closes: Sequence[float], n: int, back: int = 0) -> Num:
    """n-session return ending `back` sessions ago, %."""
    i = len(closes) - 1 - back
    if i - n < 0 or i < 0:
        return None
    return 100.0 * (closes[i] / closes[i - n] - 1.0)


def _sma_last(closes: Sequence[float], n: int, back: int = 0) -> Num:
    end = len(closes) - back
    if end - n < 0:
        return None
    return float(np.mean(closes[end - n:end]))


# ── §1 recovery check ─────────────────────────────────────────────────────────────────────────────────────────────────

REGIME_LABEL = {
    "confirmed": "Recovery confirmed", "underway": "Recovery under way", "early": "Early signs",
    "fragile": "Narrow rally", "none": "No recovery yet",
}


def _fmt(v: Num, dp: int = 1, sign: bool = False) -> str:
    if v is None:
        return "n/a"
    s = f"{v:+,.{dp}f}" if sign else f"{v:,.{dp}f}"
    return s


def regime_status(*, above_20dma: Optional[bool], sma_rising: Optional[bool], breadth_expanding: Optional[bool],
                  above20: Num, above50: Num) -> str:
    """DESIGN §1, first match."""
    if above_20dma and sma_rising and (above20 or 0) >= 60 and (above50 or 0) >= 50:
        return "confirmed"
    if above_20dma and breadth_expanding:
        return "underway"
    if above_20dma is False and breadth_expanding:
        return "early"
    if above_20dma and above20 is not None and above20 < 50:
        return "fragile"
    return "none"


def recovery_check(inp: Inputs, a: Dict[str, np.ndarray]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    n50, n50_day = _closes(inp.nifty50, inp.as_of)
    if n50_day is not None and n50_day != inp.as_of:
        inp.warnings.append(f"Nifty 50's latest close is from {n50_day.isoformat()}, not {inp.as_of.isoformat()}.")
    close = n50[-1] if n50 else None
    sma20, sma20_then = _sma_last(n50, 20), _sma_last(n50, 20, back=LAG)
    pct_vs = None if close is None or not sma20 else 100.0 * (close / sma20 - 1.0)
    now, then = breadth_at(a, -1), breadth_at(a, -1 - LAG)
    adv5 = [breadth_at(a, -1 - k)["advancers_pct"] for k in range(5)]
    adv5 = [x for x in adv5 if x is not None]
    vix_closes, _ = _closes(inp.vix, inp.as_of)
    vix = None
    if len(vix_closes) > LAG:
        v_now, v_then = vix_closes[-1], vix_closes[-1 - LAG]
        vix = {"close": r1(v_now, 2), "close_5ago": r1(v_then, 2), "change_pct": r1(100.0 * (v_now / v_then - 1.0))}

    above_20dma = None if close is None or sma20 is None else close > sma20
    sma_rising = None if sma20 is None or sma20_then is None else sma20 > sma20_then
    adv_ok = None if now["advancers_pct"] is None else now["advancers_pct"] >= 60.0
    expanding = (None if now["above20_pct"] is None or then["above20_pct"] is None
                 else now["above20_pct"] - then["above20_pct"] >= 5.0)
    vix_ok = None if vix is None else vix["close"] < vix["close_5ago"]
    checks = [
        {"id": "nifty_above_20dma", "label": "Nifty 50 above its 20-day average", "importance": "high", "pass": above_20dma,
         "value": f"{_fmt(close)} vs {_fmt(sma20)} ({_fmt(pct_vs, 1, True)}%)"},
        {"id": "nifty_20dma_rising", "label": "Nifty 50's 20-day average rising", "importance": "high", "pass": sma_rising,
         "value": f"{_fmt(sma20)} now vs {_fmt(sma20_then)} 5 sessions ago"},
        {"id": "advancers_60", "label": "At least 60% of Nifty 500 stocks rose on the day", "importance": "high", "pass": adv_ok,
         "value": f"{_fmt(now['advancers_pct'])}% rose (5-session average {_fmt(float(np.mean(adv5)) if adv5 else None)}%)"},
        {"id": "breadth_expanding", "label": "More Nifty 500 stocks above their 20-day average than a week ago",
         "importance": "very_high", "pass": expanding,
         "value": f"{_fmt(now['above20_pct'])}% now vs {_fmt(then['above20_pct'])}% 5 sessions ago"},
        {"id": "vix_falling", "label": "India VIX falling", "importance": "medium", "pass": vix_ok,
         "value": ("not available" if vix is None else f"{_fmt(vix['close'], 2)} vs {_fmt(vix['close_5ago'], 2)} 5 sessions ago")},
    ]
    status = regime_status(above_20dma=above_20dma, sma_rising=sma_rising, breadth_expanding=expanding,
                           above20=now["above20_pct"], above50=now["above50_pct"])
    line = _regime_line(status, close, sma20, sma_rising, now, then)
    caps = []
    col = {s: j for j, s in enumerate(inp.symbols)}
    for key, label in (("large", "Nifty 100"), ("mid", "Nifty Midcap 150"), ("small", "Nifty Smallcap 250")):
        members = inp.caps.get(key) or set()
        cols = [col[s] for s in members if s in col]
        if not cols:
            continue
        b, b5 = breadth_at(a, -1, cols), breadth_at(a, -1 - LAG, cols)
        caps.append({"key": key, "label": label, "members": len(cols), "above20_pct": r1(b["above20_pct"]),
                     "above20_pct_5ago": r1(b5["above20_pct"]), "above50_pct": r1(b["above50_pct"])})
    out = {
        "status": status, "label": REGIME_LABEL[status], "line": line,
        "passed": sum(1 for c in checks if c["pass"]), "total": len(checks), "checks": checks,
        "nifty": {"index": "Nifty 50", "close": r1(close, 2), "sma20": r1(sma20, 2), "sma20_5ago": r1(sma20_then, 2),
                  "pct_vs_sma20": r1(pct_vs, 2)},
        "breadth": {"counted": now["counted"], "advancers_pct": r1(now["advancers_pct"]),
                    "advancers_pct_5d_avg": r1(float(np.mean(adv5)) if adv5 else None),
                    "above20_pct": r1(now["above20_pct"]), "above20_pct_5ago": r1(then["above20_pct"]),
                    "above50_pct": r1(now["above50_pct"]), "above50_pct_5ago": r1(then["above50_pct"])},
        "vix": vix, "caps": caps,
    }
    series = []
    n50_by_day = {d: c for d, c in inp.nifty50}
    t = a["close"].shape[0]
    for k in range(min(SERIES_SESSIONS, t), 0, -1):
        b = breadth_at(a, -k)
        d = date.fromisoformat(str(inp.dates[-k])[:10])
        series.append({"date": d.isoformat(), "above20_pct": r1(b["above20_pct"]), "above50_pct": r1(b["above50_pct"]),
                       "advancers_pct": r1(b["advancers_pct"]), "nifty_close": r1(fnum(n50_by_day.get(d)), 2)})
    return out, series


def _regime_line(status: str, close: Num, sma20: Num, rising: Optional[bool], now: Dict[str, Num], then: Dict[str, Num]) -> str:
    a20, a20t = now["above20_pct"], then["above20_pct"]
    where = ("above" if close is not None and sma20 is not None and close > sma20 else "below")
    trend = "a rising" if rising else "a flat or falling"
    share = (f"{_fmt(a20, 0)}% of Nifty 500 stocks are above their own 20-day average, against {_fmt(a20t, 0)}% "
             f"5 sessions ago")
    if status == "confirmed":
        return f"Nifty 50 is above {trend} 20-day average and the move is broad: {share}."
    if status == "underway":
        return f"Nifty 50 is above its 20-day average and participation is widening: {share}."
    if status == "early":
        return f"Nifty 50 is still below its 20-day average, but more stocks are turning up: {share}."
    if status == "fragile":
        return f"Nifty 50 is above its 20-day average but few stocks are joining in: {share}."
    return f"Nifty 50 is {where} its 20-day average and participation is not widening: {share}."


# ── §2 sectors ────────────────────────────────────────────────────────────────────────────────────────────────────────

SECTOR_LABEL = {"leadership": "Leadership", "recovery": "Recovery", "emerging": "Emerging", "weak": "Weak — avoid for now",
                "neutral": "Neutral"}


def sector_state(rs_20d: Num, rs_change: Num, above20: Num, above50: Num) -> str:
    if rs_20d is not None and rs_20d > 0 and above50 is not None and above50 >= 60:
        return "leadership"
    if rs_change is not None and rs_change > 0 and above20 is not None and above20 >= 60:
        return "recovery"
    if rs_change is not None and rs_change > 0 and above20 is not None and above20 >= 40:
        return "emerging"
    if rs_20d is not None and rs_20d < 0 and above20 is not None and above20 < 40:
        return "weak"
    return "neutral"


def _median(xs: Iterable[Num]) -> Num:
    v = [x for x in xs if x is not None]
    return float(np.median(v)) if v else None


def sector_table(stocks: Dict[str, Dict[str, Any]], index_ret: Dict[str, Num]) -> List[Dict[str, Any]]:
    """`stocks`: symbol -> scalars with sector, r5/r10/r20/r20_then (%), above20/above50 (bool), deliv_up (bool|None).
    `index_ret`: r5 / r10 / r20 / r20_then of the Nifty 500 index (%)."""
    by: Dict[str, List[Dict[str, Any]]] = {}
    for s in stocks.values():
        if s.get("sector"):
            by.setdefault(s["sector"], []).append(s)
    rows = []
    for name, ms in by.items():
        if len(ms) < MIN_SECTOR_MEMBERS:
            continue
        ret = {n: _median(m.get(n) for m in ms) for n in ("r5", "r10", "r20", "r20_then")}
        rs = {n: (None if ret[n] is None or index_ret.get(n) is None else ret[n] - index_ret[n]) for n in ret}
        rs_change = None if rs["r20"] is None or rs["r20_then"] is None else rs["r20"] - rs["r20_then"]
        a20, _ = pct_of(m.get("above20") for m in ms)
        a50, _ = pct_of(m.get("above50") for m in ms)
        dup, _ = pct_of(m.get("deliv_up") for m in ms)
        state = sector_state(rs["r20"], rs_change, a20, a50)
        rows.append({"sector": name, "members": len(ms), "ret_5d": r1(ret["r5"]), "ret_10d": r1(ret["r10"]),
                     "ret_20d": r1(ret["r20"]), "rs_5d": r1(rs["r5"]), "rs_10d": r1(rs["r10"]), "rs_20d": r1(rs["r20"]),
                     "rs_20d_5ago": r1(rs["r20_then"]), "rs_change": r1(rs_change), "above20_pct": r1(a20),
                     "above50_pct": r1(a50), "delivery_up_pct": r1(dup), "state": state, "state_label": SECTOR_LABEL[state],
                     "_rs": rs["r20"], "_chg": rs_change, "_a20": a20})
    pr_rs = pct_ranks({r["sector"]: r["_rs"] for r in rows})
    pr_chg = pct_ranks({r["sector"]: r["_chg"] for r in rows})
    pr_a20 = pct_ranks({r["sector"]: r["_a20"] for r in rows})
    for r in rows:
        r["_score"] = (0.4 * pr_rs.get(r["sector"], 0.0) + 0.3 * pr_chg.get(r["sector"], 0.0)
                       + 0.3 * pr_a20.get(r["sector"], 0.0))
    rows.sort(key=lambda r: (-r["_score"], r["sector"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r["leader"] = i <= LEADER_COUNT
        for k in ("_rs", "_chg", "_a20", "_score"):
            r.pop(k)
    return rows


# ── §3–§7 one stock ───────────────────────────────────────────────────────────────────────────────────────────────────

def stock_scalars(a: Dict[str, np.ndarray], j: int) -> Dict[str, Any]:
    """The per-stock values the rules read, from the arrays (column j). Percentages are in %."""
    g = lambda k, row=-1: _at(a[k], row, j)                                     # noqa: E731
    close, ema20 = g("close"), g("ema20")
    s = {
        "close": close, "high": g("high"), "low": g("low"), "volume": g("volume"),
        "sma20": g("sma20"), "sma50": g("sma50"), "sma50_10ago": g("sma50", -11), "sma200": g("sma200"),
        "ema20": ema20, "ema50": g("ema50"), "ema20_then": g("ema20", -1 - LAG), "ema50_then": g("ema50", -1 - LAG),
        "close_then": g("close", -1 - LAG),
        "rsi": g("rsi14"), "rsi_then": g("rsi14", -1 - LAG), "atr": g("atr14"),
        "r5": None, "r10": None, "r20": None, "r20_then": None,
        "vol_ratio": g("vol_ratio"), "vol_ratio_then": g("vol_ratio", -1 - LAG),
        "vol_base50": g("vol_base50"), "vol_avg250": g("vol_avg250"), "vol_avg20_prev": g("vol_avg20_prev"),
        "ud10": g("ud10"), "tv20_cr": g("tv20_cr"), "low10": g("low10"),
        "high20_prev": g("high20_prev"), "high20": g("high20"), "low20": g("low20"), "high60": g("high60"),
        "upvol5": g("upvol5"), "higher_low": None,
        "closes_prev5": [g("close", -1 - k) for k in range(1, LAG + 1)],
        "ema20_prev5": [g("ema20", -1 - k) for k in range(1, LAG + 1)],
        "history": int((~np.isnan(a["close"][:, j])).sum()),
    }
    for k in ("r5", "r10", "r20"):
        v = g(k)
        s[k] = None if v is None else 100.0 * v
    v = g("r20", -1 - LAG)
    s["r20_then"] = None if v is None else 100.0 * v
    hl = g("higher_low")
    s["higher_low"] = None if hl is None else hl == 1.0
    up = g("up")
    s["up_today"] = None if up is None else up == 1.0
    return s


def _part(label: str, points: Num, mx: float, value: str, ok: Optional[bool]) -> Dict[str, Any]:
    return {"label": label, "points": None if points is None else round(points, 2), "max": mx, "value": value, "ok": ok}


def _component(key: str, label: str, mx: float, parts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Sum the parts; rescale over the measurable parts when they carry at least half the max (DESIGN §3)."""
    have = [p for p in parts if p["points"] is not None]
    have_max = sum(p["max"] for p in have)
    got = sum(p["points"] for p in have)
    rescaled = False
    if have_max >= mx - 1e-9:
        pts = got
    elif have_max >= mx / 2.0:
        pts, rescaled = got * mx / have_max, True
    else:
        pts = 0.0
    return {"key": key, "label": label, "points": round(pts, 2), "max": mx, "rescaled": rescaled, "parts": parts}


def _pp(v: Num) -> str:
    return "n/a" if v is None else f"{v:+.1f} pp"


def score_stock(s: Dict[str, Any], f: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """The 100-point score (DESIGN §3). `s` = stock_scalars (+ rs, rs_sector, deliv_ratio, sector), `f` = the feature row,
    `ctx` = {"financial": bool}. Returns {"score", "components", "gaps", "cautions", "low_base"}."""
    gaps: List[str] = []
    cautions: List[str] = []
    # Relative strength 25
    rs, rss = s.get("rs"), s.get("rs_sector")
    rs_parts = [
        _part("vs Nifty 500, 20 sessions", None if rs is None else 12.5 * ramp(rs, 0.0, 10.0), 12.5, _pp(rs),
              None if rs is None else rs > 0),
        _part("vs its sector, 20 sessions", None if rss is None else 12.5 * ramp(rss, 0.0, 7.5), 12.5, _pp(rss),
              None if rss is None else rss > 0),
    ]
    # Technical recovery 25
    c, e20, e50 = s.get("close"), s.get("ema20"), s.get("ema50")
    gap_now = None if e20 is None or e50 is None or e50 == 0 else (e20 - e50) / e50
    gap_then = (None if s.get("ema20_then") is None or s.get("ema50_then") in (None, 0)
                else (s["ema20_then"] - s["ema50_then"]) / s["ema50_then"])
    rsi = s.get("rsi")
    rsi_pts = None if rsi is None else (5.0 if 50 <= rsi <= 70 else 2.5 if (45 <= rsi < 50 or 70 < rsi <= 75) else 0.0)
    above20 = None if c is None or e20 is None else c > e20
    above50 = None if c is None or e50 is None else c > e50
    improving = None if gap_now is None or gap_then is None else gap_now > gap_then
    hl = s.get("higher_low")
    tech_parts = [
        _part("Above its 20-day average (EMA)", None if above20 is None else 5.0 * above20, 5, _rel(c, e20), above20),
        _part("Above its 50-day average (EMA)", None if above50 is None else 5.0 * above50, 5, _rel(c, e50), above50),
        _part("20-day average gaining on the 50-day", None if improving is None else 5.0 * improving, 5,
              "n/a" if gap_now is None or gap_then is None else f"{100 * gap_then:+.1f}% → {100 * gap_now:+.1f}%", improving),
        _part("RSI(14) in 50–70", rsi_pts, 5, "n/a" if rsi is None else f"{rsi:.0f}", None if rsi is None else 50 <= rsi <= 70),
        _part("Higher lows (10 sessions vs the 10 before)", None if hl is None else 5.0 * hl, 5,
              "yes" if hl else "no" if hl is not None else "n/a", hl),
    ]
    # Volume & delivery 20
    vr, base, v250 = s.get("vol_ratio"), s.get("vol_base50"), s.get("vol_avg250")
    low_base = bool(base is not None and v250 is not None and v250 > 0 and base < 0.5 * v250)
    vr_pts = None if vr is None else (0.0 if low_base else 7.0 * ramp(vr, 1.0, 1.5))
    if low_base and vr is not None and vr >= 1.0:
        cautions.append(f"Low-base volume: the usual volume is under half its 1-year average, so the {vr:.1f}× volume "
                        f"ratio overstates the pickup (not scored).")
    ud = s.get("ud10")
    dr = s.get("deliv_ratio")
    if dr is None:
        gaps.append("Delivery % not available")
    vol_parts = [
        _part("Volume, 5 sessions vs the 50 before", vr_pts, 7, "n/a" if vr is None else f"{vr:.2f}×",
              None if vr is None else (vr >= 1.5 and not low_base)),
        _part("Up-day vs down-day volume, 10 sessions", None if ud is None else 6.0 * ramp(ud, 1.0, 1.5), 6,
              "n/a" if ud is None else f"{ud:.2f}×", None if ud is None else ud > 1.0),
        _part("Delivery %, 5 sessions vs 20", None if dr is None else 7.0 * ramp(dr, 1.0, 1.2), 7,
              "n/a" if dr is None else f"{s.get('deliv_5d', 0):.0f}% vs {s.get('deliv_20d', 0):.0f}%",
              None if dr is None else dr > 1.0),
    ]
    # Fundamental quality 20
    roce, roe, de = fnum(f.get("roce_pct")), fnum(f.get("roe_pct")), fnum(f.get("debt_to_equity"))
    patg, cfo = fnum(f.get("pat_growth_yoy_pct")), fnum(f.get("cfo_pat_ratio"))
    if ctx.get("financial"):
        fund_parts = [
            _part("ROE (financials)", None if roe is None else 10.0 * ramp(roe, 8.0, 16.0), 10,
                  "n/a" if roe is None else f"{roe:.1f}%", None if roe is None else roe >= 12),
            _part("Profit growth, year on year", None if patg is None else 10.0 * ramp(patg, 0.0, 15.0), 10,
                  "n/a" if patg is None else f"{patg:+.1f}%", None if patg is None else patg > 0),
        ]
    else:
        de_score = None if de is None else (1.0 if de <= 0.5 else max(0.0, 1.0 - (de - 0.5)))
        fund_parts = [
            _part("ROCE", None if roce is None else 5.0 * ramp(roce, 10.0, 20.0), 5,
                  "n/a" if roce is None else f"{roce:.1f}%", None if roce is None else roce >= 15),
            _part("Debt / equity", None if de_score is None else 5.0 * de_score, 5,
                  "n/a" if de is None else f"{de:.2f}", None if de is None else de <= 0.5),
            _part("Profit growth, year on year", None if patg is None else 5.0 * ramp(patg, 0.0, 15.0), 5,
                  "n/a" if patg is None else f"{patg:+.1f}%", None if patg is None else patg > 0),
            _part("Cash flow (CFO / PAT)", None if cfo is None else 5.0 * ramp(cfo, 0.5, 1.0), 5,
                  "n/a" if cfo is None else f"{cfo:.2f}", None if cfo is None else cfo >= 0.8),
        ]
    for p in fund_parts:
        if p["points"] is None:
            gaps.append(f"{p['label']} not available")
    # Smart money 10
    fii, acc, pv = fnum(f.get("fii_pct_change_qoq")), fnum(f.get("accumulation_score")), s.get("upvol5")
    sm_parts = [
        _part("FII stake change, last quarter", None if fii is None else 4.0 * ramp(fii, 0.0, 1.0), 4, _pp(fii),
              None if fii is None else fii > 0),
        _part("Accumulation score (0–100)", None if acc is None else 3.0 * max(0.0, min(acc, 100.0)) / 100.0, 3,
              "n/a" if acc is None else f"{acc:.0f}", None if acc is None else acc >= 50),
        _part("Up sessions on above-average volume, last 5", None if pv is None else 3.0 * ramp(pv, 0.0, 3.0), 3,
              "n/a" if pv is None else f"{pv:.0f} of 5", None if pv is None else pv >= 2),
    ]
    for p in sm_parts[:2]:
        if p["points"] is None:
            gaps.append(f"{p['label']} not available")
    comps = [
        _component("relative_strength", "Relative strength", 25, rs_parts),
        _component("technical", "Technical recovery", 25, tech_parts),
        _component("volume_delivery", "Volume and delivery", 20, vol_parts),
        _component("fundamental", "Fundamental quality", 20, fund_parts),
        _component("smart_money", "Smart money signals", 10, sm_parts),
    ]
    if rsi is not None and rsi > 70:
        cautions.append(f"RSI {rsi:.0f}: above the 50–70 band, the move may be stretched.")
    return {"score": round(sum(c["points"] for c in comps), 1), "components": comps, "gaps": gaps, "cautions": cautions,
            "low_base": low_base}


def _rel(c: Num, ref: Num) -> str:
    if c is None or ref is None or ref == 0:
        return "n/a"
    return f"{100.0 * (c / ref - 1.0):+.1f}% from it"


# §5 setups

SETUP_LABEL = {"breakout": "Early breakout", "ema_reclaim": "20-day average reclaim", "pullback": "Pullback in an uptrend",
               "accumulation": "Accumulation", "relative_strength": "Relative strength"}


def classify_setup(s: Dict[str, Any]) -> Dict[str, str]:
    c, rsi, e20 = s.get("close"), s.get("rsi"), s.get("ema20")
    vol, avg20 = s.get("volume"), s.get("vol_avg20_prev")
    hi20 = s.get("high20_prev")
    day_vr = None if vol is None or not avg20 else vol / avg20
    if c is not None and hi20 is not None and day_vr is not None and rsi is not None \
            and c > hi20 and day_vr >= 1.5 and rsi >= 50:
        return _setup("breakout", f"Closed above its 20-session high ({hi20:,.2f}) on {day_vr:.1f}× its usual volume.")
    prev = [(pc, pe) for pc, pe in zip(s.get("closes_prev5") or [], s.get("ema20_prev5") or [])
            if pc is not None and pe is not None]
    if c is not None and e20 is not None and rsi is not None and c > e20 and rsi >= 50 and any(pc < pe for pc, pe in prev):
        return _setup("ema_reclaim", "Moved back above its 20-day average within the last 5 sessions, RSI at or above 50.")
    sma50, hl, rs_chg, ud = s.get("sma50"), s.get("higher_low"), s.get("rs_change"), s.get("ud10")
    if c is not None and sma50 is not None and e20 and hl and rs_chg is not None and ud is not None \
            and c > sma50 and rs_chg > 0 and ud > 1.0 and abs(c / e20 - 1.0) <= 0.05:
        return _setup("pullback", "Above its 50-day average with higher lows; pullbacks came on lighter volume.")
    h20, l20, dr = s.get("high20"), s.get("low20"), s.get("deliv_ratio")
    rng = None if h20 is None or not l20 else h20 / l20 - 1.0
    if rng is not None and dr is not None and ud is not None and rng <= 0.12 and dr > 1.0 and ud > 1.0:
        return _setup("accumulation", f"Moving sideways in a {100 * rng:.0f}% range while delivery and up-day volume rise.")
    return _setup("relative_strength", "Outperforming the market without a distinct chart setup yet.")


def _setup(key: str, why: str) -> Dict[str, str]:
    return {"key": key, "label": SETUP_LABEL[key], "why": why}


# §6 traps

TRAP_LABEL = {"dead_cat": "Dead-cat bounce", "short_covering": "Short covering", "extended": "Extended"}


def find_trap(s: Dict[str, Any], fno: Optional[Dict[str, Num]]) -> Optional[Dict[str, str]]:
    c, s50, s50o, s200 = s.get("close"), s.get("sma50"), s.get("sma50_10ago"), s.get("sma200")
    if None not in (c, s50, s50o, s200) and c < s50 and c < s200 and s50 < s50o:
        r5 = s.get("r5")
        lead = f"Up {r5:.1f}% in 5 sessions but b" if r5 is not None and r5 > 0 else "B"
        return {"trap": "dead_cat", "label": TRAP_LABEL["dead_cat"],
                "reason": f"{lead}elow a falling 50-day average and its 200-day average."}
    if fno:
        p, o, pp, po = fno.get("price_chg"), fno.get("oi_chg"), fno.get("prev_price_chg"), fno.get("prev_oi_chg")
        one_day = p is not None and o is not None and p > 1.0 and o < -3.0
        two_days = None not in (p, o, pp, po) and p > 0 and o <= -1.0 and pp > 0 and po <= -1.0
        if one_day:
            return {"trap": "short_covering", "label": TRAP_LABEL["short_covering"],
                    "reason": f"Futures price {p:+.1f}% with open interest {o:+.1f}% on the latest F&O session: shorts closing, "
                              f"not fresh buying."}
        if two_days:
            return {"trap": "short_covering", "label": TRAP_LABEL["short_covering"],
                    "reason": f"Futures price up with open interest down on both of the last two F&O sessions ({pp:+.1f}% / "
                              f"{po:+.1f}%, then {p:+.1f}% / {o:+.1f}%): shorts closing, not fresh buying."}
    e20 = s.get("ema20")
    if c is not None and e20 and c > 1.10 * e20:
        return {"trap": "extended", "label": TRAP_LABEL["extended"],
                "reason": f"{100 * (c / e20 - 1):.1f}% above its 20-day average: chasing risk is high."}
    return None


# §7 plan

def trade_plan(s: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    c, atr, e20, low10, h60 = s.get("close"), s.get("atr"), s.get("ema20"), s.get("low10"), s.get("high60")
    if c is None or atr is None or atr <= 0 or low10 is None:
        return None
    entry_low = max(e20 if e20 is not None else -math.inf, c - 0.5 * atr)
    entry_low = min(entry_low, c)
    stop = low10 - 0.25 * atr
    stop = min(stop, c - 1.0 * atr)                    # at least 1 ATR of room
    stop = max(stop, c - 3.0 * atr)                    # at most 3 ATR of risk
    risk = c - stop
    if h60 is not None and c + 1.0 * risk <= h60 <= c + 3.0 * risk:
        t1, t1_basis = h60, "the 60-session high"
    else:
        t1, t1_basis = c + 2.0 * risk, "2× the risk"
    t2 = max(c + 3.0 * risk, t1 + 1.0 * risk)
    return {
        "entry_low": round(entry_low, 2), "entry_high": round(c, 2), "stop_loss": round(stop, 2),
        "target_1": round(t1, 2), "target_2": round(t2, 2),
        "rr_1": round((t1 - c) / risk, 2), "rr_2": round((t2 - c) / risk, 2), "risk_pct": round(100.0 * risk / c, 2),
        "basis": (f"{PLAN_METHOD}: entry zone from the 20-day average (or half an ATR) up to the close; stop loss under the "
                  f"10-session low, kept 1–3 ATR away (ATR {atr:,.2f}); Target 1 = {t1_basis}; Target 2 = 3× the risk "
                  f"or Target 1 + 1× the risk. Not back-tested."),
    }


def reasons_for(s: Dict[str, Any], comps: List[Dict[str, Any]], sector: Optional[Dict[str, Any]]) -> List[str]:
    out = []
    if s.get("rs") is not None and s["rs"] > 0:
        out.append(f"Outperformed Nifty 500 by {s['rs']:.1f} pp over 20 sessions")
    if s.get("rs_sector") is not None and s["rs_sector"] > 0:
        out.append(f"Ahead of its sector by {s['rs_sector']:.1f} pp over 20 sessions")
    c, e20, e50 = s.get("close"), s.get("ema20"), s.get("ema50")
    if None not in (c, e20, e50) and c > e20 and c > e50:
        out.append("Above its 20- and 50-day averages")
    if s.get("rsi") is not None and 50 <= s["rsi"] <= 70:
        out.append(f"RSI {s['rsi']:.0f}, in the 50–70 band")
    vr = s.get("vol_ratio")
    if vr is not None and vr >= 1.3:
        out.append(f"Volume {vr:.1f}× its usual over the last 5 sessions")
    if s.get("deliv_ratio") is not None and s["deliv_ratio"] > 1.05:
        out.append(f"Delivery {s['deliv_5d']:.0f}% vs a {s['deliv_20d']:.0f}% 20-session average")
    fund = next(c for c in comps if c["key"] == "fundamental")
    if fund["points"] >= 14:
        out.append(f"Fundamental quality {fund['points']:.0f} of 20")
    if sector and sector.get("leader"):
        out.append(f"In a leading sector: {sector['sector']} (rank {sector['rank']}, {sector['state_label']})")
    return out


# ── the whole page ────────────────────────────────────────────────────────────────────────────────────────────────────

def _deliv(inp: Inputs, sym: str, f: Dict[str, Any]) -> Tuple[Num, Num, Num]:
    vals = [v for v in (fnum(x) for x in inp.delivery.get(sym) or []) if v is not None]
    d5 = float(np.mean(vals)) if len(vals) >= 3 else None
    d20 = fnum(f.get("deliv_pct_avg_20"))
    ratio = None if d5 is None or not d20 else d5 / d20
    return d5, d20, ratio


def compute(inp: Inputs, *, today: Optional[date] = None, computed_at: Optional[str] = None) -> Dict[str, Any]:
    if today is not None and (today - inp.as_of).days > 4:
        raise StaleData(f"The latest end-of-day prices are from {inp.as_of.isoformat()}. This page shows only the latest or "
                        f"the previous session's data, so it is not scored on older prices.")
    a = indicator_arrays(inp.close, inp.high, inp.low, inp.volume)
    regime, series = recovery_check(inp, a)

    n500, _ = _closes(inp.nifty500, inp.as_of)
    index_ret = {"r5": idx_ret(n500, 5), "r10": idx_ret(n500, 10), "r20": idx_ret(n500, 20), "r20_then": idx_ret(n500, 20, LAG)}

    left_out = {"no_bar": 0, "history": 0, "liquidity": 0, "market_cap": 0}
    stocks: Dict[str, Dict[str, Any]] = {}
    for j, sym in enumerate(inp.symbols):
        s = stock_scalars(a, j)
        f = inp.features_now.get(sym) or {}
        if s["close"] is None:
            left_out["no_bar"] += 1
            continue
        if s["history"] < MIN_HISTORY:
            left_out["history"] += 1
            continue
        if s["tv20_cr"] is None or s["tv20_cr"] < MIN_TRADED_VALUE_CR:
            left_out["liquidity"] += 1
            continue
        mcap = fnum(f.get("market_cap_cr"))
        if mcap is not None and mcap < MIN_MARKET_CAP_CR:
            left_out["market_cap"] += 1
            continue
        s["symbol"], s["market_cap_cr"] = sym, mcap
        s["sector"] = inp.industry.get(sym) or (f.get("sector") or None)
        s["above20"] = None if s["sma20"] is None else s["close"] > s["sma20"]
        s["above50"] = None if s["sma50"] is None else s["close"] > s["sma50"]
        s["deliv_5d"], s["deliv_20d"], s["deliv_ratio"] = _deliv(inp, sym, f)
        s["deliv_up"] = None if s["deliv_ratio"] is None else s["deliv_ratio"] > 1.0
        stocks[sym] = s

    sectors = sector_table(stocks, index_ret)
    sec_by = {r["sector"]: r for r in sectors}
    leaders = [r["sector"] for r in sectors if r["leader"]]
    sec_median = {}
    for name in sec_by:
        sec_median[name] = (_median(s["r20"] for s in stocks.values() if s.get("sector") == name),
                            _median(s["r20_then"] for s in stocks.values() if s.get("sector") == name))

    scored: Dict[str, Dict[str, Any]] = {}
    deltas: Dict[str, Dict[str, Num]] = {k: {} for k in ("rs", "rsi", "dist_ema20", "vol_ratio", "deliv_trend", "sector_rs")}
    for sym, s in stocks.items():
        f = inp.features_now.get(sym) or {}
        ft = inp.features_then.get(sym) or {}
        sec = sec_by.get(s.get("sector") or "")
        s["rs"] = None if s["r20"] is None or index_ret["r20"] is None else s["r20"] - index_ret["r20"]
        rs_then = None if s["r20_then"] is None or index_ret["r20_then"] is None else s["r20_then"] - index_ret["r20_then"]
        s["rs_change"] = None if s["rs"] is None or rs_then is None else s["rs"] - rs_then
        med = sec_median.get(s.get("sector") or "")
        s["rs_sector"] = None if not med or med[0] is None or s["r20"] is None else s["r20"] - med[0]
        res = score_stock(s, f, {"financial": s.get("sector") == FINANCIALS})
        dist_now = None if s["ema20"] in (None, 0) else 100.0 * (s["close"] / s["ema20"] - 1.0)
        dist_then = (None if s["ema20_then"] in (None, 0) or s["close_then"] is None
                     else 100.0 * (s["close_then"] / s["ema20_then"] - 1.0))
        dt_now, dt_then = fnum(f.get("deliv_trend10")), fnum(ft.get("deliv_trend10"))
        sec_now = None if not sec else sec.get("rs_20d")
        sec_then = None if not sec else sec.get("rs_20d_5ago")
        rows = [
            ("rs", "Relative strength vs Nifty 500 (20D)", "pp", rs_then, s["rs"]),
            ("rsi", "RSI (14)", "rsi", s["rsi_then"], s["rsi"]),
            ("dist_ema20", "Distance from the 20-day average", "pct", dist_then, dist_now),
            ("vol_ratio", "Volume ratio (5 vs 50 sessions)", "ratio", s["vol_ratio_then"], s["vol_ratio"]),
            ("deliv_trend", "Delivery % trend (10-session slope)", "pp", dt_then, dt_now),
            ("sector_rs", "Sector relative strength (20D)", "pp", sec_then, sec_now),
        ]
        acc_rows = []
        for key, label, unit, then, now in rows:
            d = None if then is None or now is None else now - then
            deltas[key][sym] = d
            acc_rows.append({"key": key, "label": label, "unit": unit, "then": r1(then, 2), "now": r1(now, 2),
                             "improving": None if d is None else d > 0})
        trap = find_trap(s, inp.fno.get(sym))
        scored[sym] = {"s": s, "f": f, "res": res, "acc_rows": acc_rows, "trap": trap, "sector": sec}

    ranks = {k: pct_ranks(v) for k, v in deltas.items()}
    for sym, item in scored.items():
        rs_ = [ranks[k][sym] for k in ranks if sym in ranks[k]]
        known = [r for r in item["acc_rows"] if r["improving"] is not None]
        item["acc"] = {"score": None if not rs_ else round(100.0 * float(np.mean(rs_))),
                       "improving": sum(1 for r in known if r["improving"]), "of": len(known), "rows": item["acc_rows"]}

    def card(rank: int, sym: str) -> Dict[str, Any]:
        it = scored[sym]
        s, f, res, sec = it["s"], it["f"], it["res"], it["sector"]
        return {
            "rank": rank, "symbol": sym, "name": inp.names.get(sym) or sym, "sector": s.get("sector"),
            "sector_rank": None if not sec else sec["rank"], "sector_state": None if not sec else sec["state"],
            "close": r1(s["close"], 2), "score": res["score"], "meets_priority": res["score"] >= PRIORITY_SCORE,
            "components": res["components"], "acceleration": it["acc"], "setup": classify_setup(s),
            "plan": trade_plan(s),
            "metrics": {
                "rs_vs_index_20d": r1(s["rs"]), "rs_vs_sector_20d": r1(s["rs_sector"]), "rsi14": r1(s["rsi"]),
                "volume_ratio": r1(s["vol_ratio"], 2),
                "pct_vs_ema20": r1(None if s["ema20"] in (None, 0) else 100.0 * (s["close"] / s["ema20"] - 1.0)),
                "deliv_5d": r1(s["deliv_5d"]), "deliv_20d": r1(s["deliv_20d"]), "atr14": r1(s["atr"], 2),
                "traded_value_cr_20d": r1(s["tv20_cr"]), "market_cap_cr": r1(s["market_cap_cr"], 0),
                "roce": r1(fnum(f.get("roce_pct"))), "roe": r1(fnum(f.get("roe_pct"))), "de": r1(fnum(f.get("debt_to_equity")), 2),
                "pat_growth": r1(fnum(f.get("pat_growth_yoy_pct"))), "cfo_pat": r1(fnum(f.get("cfo_pat_ratio")), 2),
                "fii_change_qoq": r1(fnum(f.get("fii_pct_change_qoq")), 2),
            },
            "reasons": reasons_for(s, res["components"], sec), "cautions": res["cautions"], "gaps": res["gaps"],
        }

    order = sorted(scored, key=lambda k: (-scored[k]["res"]["score"], -(scored[k]["acc"]["score"] or 0), k))
    clean = [k for k in order if scored[k]["trap"] is None]
    in_lead = [k for k in clean if scored[k]["s"].get("sector") in leaders][:TOP_N]
    outside = [k for k in clean if scored[k]["s"].get("sector") not in leaders][:TOP_N]
    trapped = [k for k in order if scored[k]["trap"] is not None][:EXCLUDED_N]

    return {
        "method": METHOD,
        "as_of": inp.as_of.isoformat(),
        "computed_at": computed_at,
        "universe": {"name": "Nifty 500", "members": inp.members_total or len(inp.symbols), "members_as_of": inp.members_as_of,
                     "scored": len(scored), "left_out": left_out},
        "regime": regime,
        "breadth_series": series,
        "sectors": sectors,
        "leaders": leaders,
        "candidates": [card(i, k) for i, k in enumerate(in_lead, 1)],
        "others": [card(i, k) for i, k in enumerate(outside, 1)],
        "excluded": [{"symbol": k, "name": inp.names.get(k) or k, "sector": scored[k]["s"].get("sector"),
                      "score": scored[k]["res"]["score"], **scored[k]["trap"]} for k in trapped],
        "thresholds": {"priority_score": PRIORITY_SCORE, "min_traded_value_cr": MIN_TRADED_VALUE_CR,
                       "min_market_cap_cr": MIN_MARKET_CAP_CR},
        "sources": inp.sources,
        "notes": NOTES,
        "warnings": inp.warnings,
    }


NOTES = [
    "Rules: docs/market_recovery/DESIGN.md (recovery-radar-v1). Weights follow the proposal; thresholds are untuned.",
    "Not back-tested yet. Our earlier backtest of a similar reversal score found no excess return after costs, so treat the "
    "score as a way to order stocks for review, not as a forecast.",
    "Breadth and sector figures use today's Nifty 500 members over the whole window (survivorship bias).",
    "Prices are end-of-day bars, split/bonus adjusted; the scan does not use today's live quotes.",
]
