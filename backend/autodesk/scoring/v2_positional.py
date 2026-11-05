"""v2-positional — the revised signal hierarchy for 10–20-session positional trades (SHADOW; registry.py).

Spec: docs/signal_intelligence/SIGNAL_TIER_HIERARCHY.md §10–§11 (owner, 5 Nov 2026). Calibrated on daily data Apr 2024 –
Sep 2025 and judged on Oct 2025 – Nov 2026: only trend-persistence and relative-strength signals held at 10–20 sessions.

    score (0–100) = signal quality 45 + trend confirmation 30 + relative strength 15 + supporting evidence 10
                    − 10 when a bearish warning is present                        (clamped 0–100)

Signal quality: the highest-tier ENTRY signal that fired on the last bar sets the points; +3 for each further entry signal from
a different family (correlated signals of one family count once); capped at 45. Context-only signals earn no quality points.
Bearish signals are never entries: they are listed as warnings (risk / exit information) and cost 10 points.
Overlap: when HH-HL is the primary signal the trend dimension does not score HH-HL again; when the relative-strength breakout is
primary the relative-strength dimension scores half. No chasing penalty; RSI 75–80 is the best momentum band; volume above
1.5× earns no more than 1.5× does (the study found no consistent gain from bigger volume).

No look-ahead: every value at bar t uses bars ≤ t only (prior windows exclude t where the rule says "prior"; swing points are
used two bars after they form). `features()` runs once over a whole series, `score_at(f, t)` scores any bar, so the live scan
(last bar) and the history study use the same code.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, Sequence

import numpy as np

from ..contracts import ScoreComponent, ShadowScore
from ..market.view import Bar
from .registry import V2_WEIGHTS

VERSION = "v2-positional"
RULES = "v2-positional-2026-11-05"
NAN = float("nan")
MIN_BARS = 60
MIN_TRADED_RS = 5e7          # 20-session average traded value below ₹5 crore → not scored
CONFLUENCE = 3
BEARISH_PENALTY = 10

# entry signal → (tier, quality points, family)
ENTRY = {
    "RS_BREAKOUT": ("TIER_1", 45, "relative_strength"),
    "SETUP_B_PULLBACK": ("TIER_1", 40, "pullback"),
    "HH_HL_CONFIRMED": ("TIER_1", 38, "trend"),
    "MACD_BULL_CROSS": ("TIER_1", 36, "trend"),
    "BREAKOUT_RETEST": ("TIER_1_PROVISIONAL", 32, "breakout"),
    "SETUP_A_ACCUMULATION": ("TIER_2", 24, "breakout"),
    "MULTIYEAR_BREAKOUT": ("TIER_2", 22, "breakout"),
    "VOLUME_BREAKOUT": ("TIER_2", 20, "breakout"),
}
CONTEXT = ("RSI_DIVERGENCE_BULL", "SETUP_C_MOMENTUM_REVERSAL", "SETUP_E_FAILED_BREAKDOWN", "SUPERTREND_FLIP_UP",
           "ENGULFING_AT_SUPPORT", "BOLLINGER_SQUEEZE_BREAKOUT")
WARNINGS = ("BREAKDOWN_ON_VOLUME", "LOWER_HIGHS_LOWER_LOWS", "EMA20_50_BEARISH_CROSS", "RSI_DIVERGENCE_BEAR",
            "FAILED_BREAKOUT", "MACD_BEAR_CROSS", "SUPERTREND_FLIP_DOWN", "BREAKDOWN_52W_2X")
BANDS = ((85, "Exceptional"), (75, "Strong"), (65, "Developing"), (50, "Weak"), (0, "Avoid"))


def band(score: float) -> str:
    return next(name for floor, name in BANDS if score >= floor)


# ── indicators (causal) ────────────────────────────────────────────────────────────────────────────────────────────

def _ewm(x: np.ndarray, alpha: float, min_periods: int) -> np.ndarray:
    """Recursive exponential mean (pandas ewm adjust=False): y0 = x0; NaN until `min_periods` values have been seen."""
    out = np.full(len(x), NAN)
    prev, seen = NAN, 0
    for i, v in enumerate(x):
        if math.isnan(v):
            if seen >= min_periods:
                out[i] = prev
            continue
        prev = v if seen == 0 else alpha * v + (1 - alpha) * prev
        seen += 1
        if seen >= min_periods:
            out[i] = prev
    return out


def ema(x, n):
    return _ewm(x, 2 / (n + 1), n)


def wilder(x, n):
    return _ewm(x, 1 / n, n)


def _prior(x: np.ndarray, w: int, fn) -> np.ndarray:
    """fn over the `w` values BEFORE each bar (bar t excluded); NaN until w earlier values exist."""
    out = np.full(len(x), NAN)
    for t in range(w, len(x)):
        win = x[t - w:t]
        if not np.isnan(win).any():
            out[t] = fn(win)
    return out


@dataclass
class Features:
    days: list
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    dl: np.ndarray
    nb: np.ndarray                  # Nifty close aligned to the stock's days (NaN where missing)
    arr: dict = field(default_factory=dict)
    sector_bull: Optional[np.ndarray] = None
    sector_name: Optional[str] = None

    def __len__(self):
        return len(self.c)


def features(bars: Sequence[Bar], bench: Sequence[Bar], sector: Optional[Sequence[Bar]] = None,
             sector_name: Optional[str] = None) -> Features:
    f = lambda xs: np.array([float(x) if x is not None else NAN for x in xs], dtype=float)
    days = [b.day for b in bars]
    o, h, l, c = f([b.open for b in bars]), f([b.high for b in bars]), f([b.low for b in bars]), f([b.close for b in bars])
    v = f([b.volume for b in bars]); dl = f([b.deliv_pct for b in bars])
    bmap = {b.day: float(b.close) for b in bench}
    nb = np.array([bmap.get(d, NAN) for d in days], dtype=float)
    F = Features(days, o, h, l, c, v, dl, nb, sector_name=sector_name)
    a = F.arr
    a["e20"], a["e50"], a["e200"] = ema(c, 20), ema(c, 50), ema(c, 200)
    d = np.diff(c, prepend=NAN)
    up, dn = np.where(np.isnan(d), NAN, np.clip(d, 0, None)), np.where(np.isnan(d), NAN, np.clip(-d, 0, None))
    au, ad = wilder(up, 14), wilder(dn, 14)
    with np.errstate(divide="ignore", invalid="ignore"):
        a["rsi"] = np.where(ad == 0, 100.0, 100 - 100 / (1 + au / ad))
    pc = np.concatenate([[NAN], c[:-1]])
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    tr[0] = h[0] - l[0]
    a["atr"] = wilder(tr, 14)
    macd = ema(c, 12) - ema(c, 26)
    a["macd"], a["macds"] = macd, ema(macd, 9)
    mid = np.full(len(c), NAN); sd = np.full(len(c), NAN)
    for t in range(19, len(c)):
        win = c[t - 19:t + 1]; mid[t], sd[t] = win.mean(), win.std(ddof=1)
    a["bbu"] = mid + 2 * sd
    with np.errstate(divide="ignore", invalid="ignore"):
        bbw = 4 * sd / mid
    pct = np.full(len(c), NAN)
    for t in range(119, len(c)):
        win = bbw[t - 119:t + 1]
        if not np.isnan(win).any():
            pct[t] = (np.sum(win < bbw[t]) + (np.sum(win == bbw[t]) + 1) / 2) / len(win)
    a["bbw_pct"] = pct
    a["vol20"] = _prior(v, 20, np.mean)
    with np.errstate(divide="ignore", invalid="ignore"):
        a["rvol"] = v / a["vol20"]
    a["traded20"] = _prior(c * v, 20, np.mean)
    a["hi20"], a["lo20"] = _prior(h, 20, np.max), _prior(l, 20, np.min)
    a["hi250"], a["lo250"] = _prior(h, 250, np.max), _prior(l, 250, np.min)
    a["hi480"] = _prior(h, 480, np.max)
    rs = c / nb
    a["rsline"] = rs
    a["rsmax250"] = _prior(rs, 250, np.max)
    with np.errstate(divide="ignore", invalid="ignore"):
        rng = h - l
        a["cloc"] = np.where(rng > 0, (c - l) / rng, NAN)
    # Supertrend (10, 3)
    atr10 = wilder(tr, 10); hl2 = (h + l) / 2; ub, lb = hl2 + 3 * atr10, hl2 - 3 * atr10
    st = np.zeros(len(c)); fu, fl = ub.copy(), lb.copy()
    for i in range(1, len(c)):
        if np.isnan(ub[i]) or np.isnan(fu[i - 1]):
            st[i] = st[i - 1]; continue
        fu[i] = ub[i] if (ub[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lb[i] if (lb[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        st[i] = 1 if c[i] > fu[i - 1] else -1 if c[i] < fl[i - 1] else st[i - 1]
    a["st"] = st
    # swing points (5 bars, used two bars after they form), structure state, RSI divergences confirmed by an EMA20 cross
    n = len(c); hhhl = np.zeros(n, bool); lhll = np.zeros(n, bool); lastsh = np.full(n, NAN)
    divb = np.zeros(n, bool); divs = np.zeros(n, bool); rv, e20 = a["rsi"], a["e20"]
    sh: list[int] = []; sl: list[int] = []; pend_b = pend_s = None
    for t in range(n):
        k = t - 2
        if k >= 2:
            if h[k] == np.max(h[k - 2:k + 3]):
                if sh and 5 <= k - sh[-1] <= 40 and h[k] > h[sh[-1]] and not math.isnan(rv[k]) and rv[k] < rv[sh[-1]] and rv[sh[-1]] > 60:
                    pend_s = t
                sh.append(k)
            if l[k] == np.min(l[k - 2:k + 3]):
                if sl and 5 <= k - sl[-1] <= 40 and l[k] < l[sl[-1]] and not math.isnan(rv[k]) and rv[k] > rv[sl[-1]] and rv[sl[-1]] < 40:
                    pend_b = t
                sl.append(k)
        if len(sh) >= 2 and len(sl) >= 2:
            hhhl[t] = h[sh[-1]] > h[sh[-2]] and l[sl[-1]] > l[sl[-2]]
            lhll[t] = h[sh[-1]] < h[sh[-2]] and l[sl[-1]] < l[sl[-2]]
        if sh:
            lastsh[t] = h[sh[-1]]
        if pend_b is not None:
            if t - pend_b > 10:
                pend_b = None
            elif c[t] > e20[t]:
                divb[t] = True; pend_b = None
        if pend_s is not None:
            if t - pend_s > 10:
                pend_s = None
            elif c[t] < e20[t]:
                divs[t] = True; pend_s = None
    a["hhhl"], a["lhll"], a["lastsh"], a["divb"], a["divs"] = hhhl, lhll, lastsh, divb, divs
    if sector is not None:
        smap = {b.day: float(b.close) for b in sector}
        s = np.array([smap.get(d, NAN) for d in days], dtype=float)
        se20 = ema(s, 20)
        bull = np.zeros(n, bool)
        for t in range(5, n):
            if not (math.isnan(s[t]) or math.isnan(se20[t]) or math.isnan(s[t - 5]) or math.isnan(nb[t]) or math.isnan(nb[t - 5])):
                bull[t] = s[t] > se20[t] and (s[t] / s[t - 5]) > (nb[t] / nb[t - 5])
        F.sector_bull = bull
    return F


# ── signals at bar t ───────────────────────────────────────────────────────────────────────────────────────────────

def _ok(*xs) -> bool:
    return not any(x is None or (isinstance(x, float) and math.isnan(x)) for x in xs)


def _any(arr, lo: int, hi: int) -> bool:
    lo = max(lo, 0)
    return bool(np.any(arr[lo:hi])) if hi > lo else False


def detect(F: Features, t: int) -> tuple[list[str], list[str], list[str], dict]:
    a, c, o, h, l, v = F.arr, F.c, F.o, F.h, F.l, F.v
    e20, e50, rsi, rvol = a["e20"][t], a["e50"][t], a["rsi"][t], a["rvol"][t]
    hi20, lo20 = a["hi20"], a["lo20"]
    bo = lambda s: _ok(c[s], hi20[s]) and c[s] > hi20[s]
    bd = lambda s: _ok(c[s], lo20[s]) and c[s] < lo20[s]
    macd, macds = a["macd"], a["macds"]
    cross_up = lambda s: s >= 1 and _ok(macd[s], macds[s], macd[s - 1], macds[s - 1]) and macd[s] > macds[s] and macd[s - 1] <= macds[s - 1]
    cross_dn = lambda s: s >= 1 and _ok(macd[s], macds[s], macd[s - 1], macds[s - 1]) and macd[s] < macds[s] and macd[s - 1] >= macds[s - 1]
    vol_ok = _ok(rvol)
    entries, ctx, warn = [], [], []
    facts: dict = {}
    # entries
    if _ok(a["rsline"][t], a["rsmax250"][t]) and a["rsline"][t] > a["rsmax250"][t]:
        entries.append("RS_BREAKOUT")
    if t >= 5 and _ok(e20, e50, rvol, a["vol20"][t]):
        pre = v[t - 5:t].mean()
        if (a["hhhl"][t] and np.nanmin(l[t - 4:t + 1]) <= e20 * 1.015 and c[t] > e50 and pre < a["vol20"][t]
                and c[t] > o[t] and _ok(a["cloc"][t]) and a["cloc"][t] >= 0.5 and v[t] > pre):
            entries.append("SETUP_B_PULLBACK")
    if a["hhhl"][t] and t >= 5 and not np.all(a["hhhl"][t - 5:t]):
        entries.append("HH_HL_CONFIRMED")
    if cross_up(t):
        entries.append("MACD_BULL_CROSS")
    recent = [s for s in range(max(0, t - 15), t - 2) if bo(s)]
    if recent and not bo(t):
        lvl = hi20[recent[-1]]
        if l[t] <= lvl * 1.015 and c[t] > lvl and c[t] > o[t]:
            entries.append("BREAKOUT_RETEST")
    sb = F.sector_bull[t] if F.sector_bull is not None else None
    rs20 = (c[t] / c[t - 20]) - (F.nb[t] / F.nb[t - 20]) if t >= 20 and _ok(F.nb[t], F.nb[t - 20]) else NAN
    facts["rs20"] = rs20
    if (bo(t) and vol_ok and rvol > 1.5 and _ok(e20, e50, rsi, rs20) and c[t] > e20 and c[t] > e50 and 55 <= rsi <= 75
            and rs20 > 0 and sb):
        entries.append("SETUP_A_ACCUMULATION")
    facts["setup_a_sector"] = "not available" if sb is None else ("bullish" if sb else "not bullish")
    if _ok(a["hi480"][t]) and c[t] > a["hi480"][t] and vol_ok and rvol >= 2:
        entries.append("MULTIYEAR_BREAKOUT")
    if bo(t) and vol_ok and rvol >= 1.5:
        entries.append("VOLUME_BREAKOUT")
    # context (supporting information only)
    if _any(a["divb"], t - 4, t + 1):
        ctx.append("RSI_DIVERGENCE_BULL")
    if (_any(a["divb"], t - 9, t + 1) and _ok(e20) and c[t] > e20 and any(cross_up(s) for s in range(max(1, t - 4), t + 1))
            and t >= 1 and _ok(a["lastsh"][t - 1]) and c[t] > a["lastsh"][t - 1] and vol_ok and rvol >= 1.5):
        ctx.append("SETUP_C_MOMENTUM_REVERSAL")
    past_bd = [s for s in range(max(0, t - 5), t) if bd(s)]
    if past_bd and not bd(t) and c[t] > lo20[past_bd[-1]] and vol_ok and rvol >= 1.5:
        ctx.append("SETUP_E_FAILED_BREAKDOWN")
    if t >= 1 and a["st"][t] == 1 and a["st"][t - 1] == -1:
        ctx.append("SUPERTREND_FLIP_UP")
    if (t >= 1 and c[t] > o[t] and o[t - 1] > c[t - 1] and c[t] >= o[t - 1] and o[t] <= c[t - 1]
            and ((_ok(lo20[t]) and l[t] <= lo20[t] * 1.02) or (_ok(e50) and abs(l[t] - e50) <= e50 * 0.02))):
        ctx.append("ENGULFING_AT_SUPPORT")
    if t >= 5 and _ok(a["bbu"][t]) and not np.isnan(a["bbw_pct"][t - 5:t]).all() and np.nanmin(a["bbw_pct"][t - 5:t]) <= 0.10 and c[t] > a["bbu"][t]:
        ctx.append("BOLLINGER_SQUEEZE_BREAKOUT")
    # bearish → warnings only
    if bd(t) and vol_ok and rvol >= 1.5:
        warn.append("BREAKDOWN_ON_VOLUME")
    if a["lhll"][t]:
        warn.append("LOWER_HIGHS_LOWER_LOWS")
    e20a, e50a = a["e20"], a["e50"]
    for s in range(max(1, t - 4), t + 1):
        if _ok(e20a[s], e50a[s], e20a[s - 1], e50a[s - 1]) and e20a[s] < e50a[s] and e20a[s - 1] >= e50a[s - 1]:
            if _ok(e20, e50) and c[t] < e20 and c[t] < e50:
                warn.append("EMA20_50_BEARISH_CROSS")
            break
    if _any(a["divs"], t - 4, t + 1):
        warn.append("RSI_DIVERGENCE_BEAR")
    past_bo = [s for s in range(max(0, t - 5), t) if bo(s)]
    if past_bo and not bo(t) and c[t] < hi20[past_bo[-1]] and vol_ok and rvol >= 1.5:
        warn.append("FAILED_BREAKOUT")
    if cross_dn(t):
        warn.append("MACD_BEAR_CROSS")
    if t >= 1 and a["st"][t] == -1 and a["st"][t - 1] == 1:
        warn.append("SUPERTREND_FLIP_DOWN")
    if _ok(a["lo250"][t]) and c[t] < a["lo250"][t] and vol_ok and rvol >= 2:
        warn.append("BREAKDOWN_52W_2X")
    return entries, ctx, warn, facts


# ── score at bar t ─────────────────────────────────────────────────────────────────────────────────────────────────

def _comp(dim: str, points: float, detail: str, available: bool = True, weight: Optional[Decimal] = None) -> ScoreComponent:
    w = V2_WEIGHTS[dim] if weight is None else weight
    return ScoreComponent(dimension=dim, weight=w, points=Decimal(str(round(points, 2))), available=available, detail=detail)


def score_at(F: Features, t: int) -> ShadowScore:
    base = dict(version=VERSION, horizon="POSITIONAL", status="SHADOW", bars_used=t + 1)
    if t + 1 < MIN_BARS:
        return ShadowScore(**base, reasons=[f"{t + 1} sessions of history; v2 needs {MIN_BARS}"])
    a, c = F.arr, F.c
    tv = a["traded20"][t]
    if not _ok(tv) or tv < MIN_TRADED_RS:
        return ShadowScore(**base, reasons=["20-session average traded value below ₹5 crore" if _ok(tv) else "no traded-value history"])
    entries, ctx, warn, facts = detect(F, t)
    reasons: list[str] = []
    # signal quality
    if entries:
        primary = max(entries, key=lambda s: ENTRY[s][1])
        tier = ENTRY[primary][0]
        fams = {ENTRY[s][2] for s in entries if s != primary} - {ENTRY[primary][2]}
        q = min(45, ENTRY[primary][1] + CONFLUENCE * len(fams))
        qd = f"{primary.replace('_', ' ').lower()} ({tier.replace('_', ' ').lower()}, {ENTRY[primary][1]})"
        if fams:
            qd += f" + {CONFLUENCE} × {len(fams)} other famil{'y' if len(fams) == 1 else 'ies'} ({', '.join(sorted(fams))})"
    else:
        primary, tier, q, qd = None, ("CONTEXT" if ctx else "NONE"), 0, "no entry signal on this bar"
    comps = [_comp("signal_quality", q, qd)]
    # trend confirmation (30)
    e20, e50, e200 = a["e20"][t], a["e50"][t], a["e200"][t]
    tp, td = 0.0, []
    if _ok(e50) and t >= 5 and _ok(a["e50"][t - 5]) and c[t] > e50 and e50 > a["e50"][t - 5]:
        tp += 12; td.append("above a rising EMA50 (12)")
    if _ok(e20, e50) and c[t] > e20 > e50:
        tp += 8; td.append("price > EMA20 > EMA50 (8)")
        if _ok(e200):
            if e50 > e200:
                tp += 4; td.append("EMA50 > EMA200 (4)")
        else:
            td.append("EMA200 needs 200 sessions")
    if a["hhhl"][t]:
        if primary == "HH_HL_CONFIRMED":
            td.append("higher highs + higher lows counted in signal quality")
        else:
            tp += 6; td.append("higher highs + higher lows (6)")
    comps.append(_comp("trend_confirmation", min(tp, 30), "; ".join(td) or "no trend confirmation"))
    # relative strength (15)
    rs20 = facts["rs20"]
    if _ok(rs20):
        rp = 15 if rs20 >= 0.10 else 11 if rs20 >= 0.05 else 7 if rs20 >= 0 else 0
        rdet = f"20-session return {rs20 * 100:+.1f} % vs the Nifty"
        if primary == "RS_BREAKOUT":
            rp = rp / 2; rdet += " (half: the primary signal is the relative-strength breakout)"
        comps.append(_comp("relative_strength", rp, rdet))
    else:
        comps.append(_comp("relative_strength", 0, "Nifty history missing", available=False))
    # supporting evidence (10)
    sp, sdt = 0.0, []
    rsi = a["rsi"][t]
    if _ok(rsi):
        rp = 4 if 75 <= rsi <= 80 else 3 if 65 <= rsi < 75 else 2 if rsi > 80 or 55 <= rsi < 65 else 0
        sp += rp; sdt.append(f"RSI14 {rsi:.1f} ({rp})")
    if _ok(F.dl[t]):
        if F.dl[t] >= 50:
            sp += 3; sdt.append(f"delivery {F.dl[t]:.0f} % (3)")
        else:
            sdt.append(f"delivery {F.dl[t]:.0f} % (0)")
    else:
        sdt.append("delivery not available")
    rv = a["rvol"][t]
    if _ok(rv):
        vp = 1 if rv >= 1.5 else 0
        sp += vp; sdt.append(f"volume {rv:.1f}× its 20-session average ({vp}; more volume earns no more)")
    if ctx:
        sp += 2; sdt.append(f"context: {', '.join(x.replace('_', ' ').lower() for x in ctx)} (2)")
    comps.append(_comp("supporting_evidence", min(sp, 10), "; ".join(sdt)))
    total = float(sum(x.points for x in comps))
    if warn:
        comps.append(ScoreComponent(dimension="bearish_warning", weight=Decimal(BEARISH_PENALTY), points=Decimal(-BEARISH_PENALTY),
                                    available=True, detail="bearish warning present: " + ", ".join(w.replace("_", " ").lower() for w in warn)))
        total -= BEARISH_PENALTY
    total = max(0.0, min(100.0, total))
    return ShadowScore(**base, score=Decimal(str(round(total, 2))), band=band(total), tier=tier, primary_signal=primary,
                       signals=entries, context_signals=ctx, warnings=warn, components=comps, reasons=reasons)


def score_last(bars: Sequence[Bar], bench: Sequence[Bar], sector: Optional[Sequence[Bar]] = None,
               sector_name: Optional[str] = None) -> ShadowScore:
    if not bars:
        return ShadowScore(version=VERSION, horizon="POSITIONAL", status="SHADOW", reasons=["no bars"])
    F = features(bars, bench, sector, sector_name)
    return score_at(F, len(F) - 1)


# industry (index-constituent classification) → sector index used for setup A's "sector index also bullish"
SECTOR_INDEX = {"Automobile and Auto Components": "Nifty Auto", "Financial Services": "Nifty Financial Services",
                "Banking and Finance": "Nifty Bank", "Capital Goods": "Nifty Capital Goods", "Chemicals": "Nifty Chemicals",
                "Construction": "Nifty Infrastructure", "Construction Materials": "Nifty Cement",
                "Consumer Durables": "Nifty Consumer Durables", "Consumer Services": "Nifty Consumer Services",
                "Fast Moving Consumer Goods": "Nifty FMCG", "Healthcare": "Nifty Healthcare Index",
                "Information Technology": "Nifty IT", "Metals & Mining": "Nifty Metal",
                "Oil Gas & Consumable Fuels": "Nifty Oil & Gas", "Power": "Nifty Energy", "Realty": "Nifty Realty",
                "Services": "Nifty India Infrastructure & Logistics", "Telecommunication": "Nifty Media",
                "Media Entertainment & Publication": "Nifty Media"}
