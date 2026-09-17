"""RESEARCH ONLY — REJECTED AS ENTRY SIGNALS. Not imported by any route, page or scheduled job.

Entry setups A–D (+ E RS-accumulation modifier) from the user's specification of 2026-09-17, rules fixed in
docs/ai_research/tpd3/entry_setups/PREREGISTRATION.md before any backtest. The pre-registered backtest (RESULTS.md there)
validated 0 of 8 setup x trade combinations: every one lost money net of costs and none beat the all-stock-day baseline.
Owner decision 2026-09-17: reject all four as entries, keep this code as negative evidence, and do not tune it to rescue
them. The Entry Quality Score below is RETIRED (it rewarded calm, liquid stocks and ranked outcomes the wrong way); it is
kept only so the published result can be reproduced.

    indicators(one_symbol_daily_bars)      → EMA20/50, ATR14, hh20/hh50, RVOL, CLV, ranges, volume and delivery trends
    evaluate_setups(indicators + rs + event) → setup_a..setup_e flags, no_chase, structure stops
    trade_plan(entry, structure_stop, atr, target_pct, atr_mult) → stop, stop %, risk/reward, ok
    simulate_bracket(entry, stop, target, forward bars, cost) → exit, outcome, net
    entry_quality(row) → the 100-point Entry Quality Score and its 0–1 components

Everything at T uses data through the close of T. Long setups only.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

EQS_WEIGHTS = {"price_action": 20, "volume": 20, "trend_rs": 15, "volatility": 15, "catalyst": 15, "regime": 10, "liquidity": 5}
NO_CHASE_CHANGE = 0.095
MIN_ADV20 = 5e7                    # Rs 5 crore
MAX_EXTENSION = 0.10               # close <= EMA20 x 1.10


def indicators(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("as_of_date").reset_index(drop=True).copy()
    c, h, l, v = g["close"], g["high"], g["low"], g["volume"]
    g["ema20"] = c.ewm(span=20, adjust=False).mean()
    g["ema50"] = c.ewm(span=50, adjust=False).mean()
    g["ema20_rising"] = g["ema20"] > g["ema20"].shift(5)
    g["ema50_rising"] = g["ema50"] > g["ema50"].shift(5)
    prev_c = c.shift(1)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    g["atr14"] = tr.rolling(14, min_periods=14).mean()
    g["atr_pct"] = g["atr14"] / c
    g["atr_prev"] = g["atr14"].shift(1)
    g["atr_prev21"] = g["atr14"].shift(21)
    g["vol_avg20"] = v.shift(1).rolling(20, min_periods=20).mean()
    g["rvol"] = v / g["vol_avg20"]
    g["hh20"] = h.shift(1).rolling(20, min_periods=20).max()
    g["hh50"] = h.shift(1).rolling(50, min_periods=50).max()
    g["hh10"] = h.shift(1).rolling(10, min_periods=10).max()
    g["ll10"] = l.shift(1).rolling(10, min_periods=10).min()
    g["range10"] = (g["hh10"] - g["ll10"]) / prev_c
    g["vol_avg10_prev"] = v.shift(1).rolling(10, min_periods=10).mean()
    g["vol_avg_t30_t11"] = v.shift(11).rolling(20, min_periods=20).mean()
    rng = h - l
    g["clv"] = np.where(rng > 0, (c - l) / rng.where(rng > 0, 1), 0.5)
    g["chg"] = c / g["prev_close"] - 1
    g["ret20"] = c / c.shift(20) - 1
    down = c < prev_c
    g["down_vol_mean5"] = v.where(down).shift(1).rolling(5, min_periods=1).mean()
    up_vol20 = v.where(c > prev_c, 0).rolling(20, min_periods=20).sum()
    dn_vol20 = v.where(down, 0).rolling(20, min_periods=20).sum()
    g["updown_ok"] = up_vol20 > dn_vol20
    dp = g["deliverable_pct"] if "deliverable_pct" in g else pd.Series(np.nan, index=g.index)
    g["deliv5"] = dp.rolling(5, min_periods=3).mean()
    g["deliv20"] = dp.rolling(20, min_periods=10).mean()
    g["ll3"] = l.rolling(3, min_periods=3).min()
    g["adv20"] = (c * v).shift(1).rolling(20, min_periods=20).mean()
    g["vol_prev"] = v.shift(1)
    g["locked"] = rng <= 0
    return g


def evaluate_setups(ind: pd.DataFrame) -> pd.DataFrame:
    """Needs rs20_nifty and rs20_sector columns (cross-sectional, computed by the caller); event_positive_today optional.
    Row-wise only (every lag is computed per symbol in indicators), so a multi-symbol frame is safe."""
    x = ind.copy()
    ev = x["event_positive_today"].fillna(False).astype(bool) if "event_positive_today" in x else pd.Series(False, index=x.index)
    c = x["close"]
    x["no_chase"] = ((x["chg"] >= NO_CHASE_CHANGE) & (x["clv"] >= 0.98)) | x["locked"]
    x["setup_a"] = (c > x["hh20"]) & (x["rvol"] >= 1.5) & (x["clv"] >= 0.70) & (x["rs20_nifty"] > 0) & (c > x["ema20"])
    x["setup_b"] = ((x["ema20"] > x["ema50"]) & x["ema20_rising"] & x["ema50_rising"] & (c > x["ema50"]) & (c >= x["ema20"] * 0.97)
                    & (x["ll3"] <= x["ema20"] * 1.02) & (x["down_vol_mean5"] < x["vol_avg20"])
                    & (c > x["open"]) & (c > x["prev_close"]) & (x["clv"] >= 0.60) & (x["volume"] > x["vol_prev"]))
    x["setup_c"] = ev & (x["chg"] >= 0.02) & (x["rvol"] >= 2.0) & (x["clv"] >= 0.70)
    x["setup_d"] = ((x["atr_prev"] < 0.75 * x["atr_prev21"]) & (x["range10"] <= 0.10) & (x["vol_avg10_prev"] < 0.8 * x["vol_avg_t30_t11"])
                    & (c > x["hh10"]) & (x["rvol"] >= 1.5) & (x["clv"] >= 0.70))
    x["setup_e"] = ((x["rs20_nifty"] > 0) & (x["rs20_sector"] > 0) & x["updown_ok"] & (x["deliv5"] > x["deliv20"]) & (c >= 0.95 * x["hh20"]))
    for s in ("setup_a", "setup_b", "setup_c", "setup_d"):
        x[s + "_raw"] = x[s].fillna(False).astype(bool)
        x[s] = x[s + "_raw"] & ~x["no_chase"]
    x["setup_e"] = x["setup_e"].fillna(False).astype(bool)
    x["stop_a"] = x["low"]; x["stop_b"] = x["ll3"]; x["stop_c"] = x["low"]; x["stop_d"] = x["ll10"]
    x["entry_trigger_a"] = x["high"]; x["entry_trigger_d"] = x["high"]
    x["filters_ok"] = (x["adv20"] >= MIN_ADV20) & (c <= x["ema20"] * (1 + MAX_EXTENSION))
    return x


def trade_plan(entry: float, structure_stop: float, atr: float, target_pct: float, atr_mult: float) -> dict:
    stop = max(structure_stop, entry - atr_mult * atr)
    if not (stop < entry) or not atr or np.isnan(atr):
        return {"stop": stop, "stop_pct": None, "rr": None, "ok": False}
    stop_pct = (entry - stop) / entry
    rr = target_pct / stop_pct
    ok = bool(rr >= 2.0 and (entry - stop) >= 0.5 * atr)
    return {"stop": stop, "stop_pct": stop_pct, "rr": rr, "ok": ok}


def simulate_bracket(entry: float, stop: float, target: float, fwd: pd.DataFrame, cost: float) -> dict:
    """fwd: the forward sessions' open/high/low/close in order (up to five). Stop first on a tie; a gap below the stop
    exits at that open; otherwise the last session's close."""
    for i, b in enumerate(fwd.itertuples(index=False), start=1):
        if i > 1 and b.open <= stop:
            return {"exit": float(b.open), "exit_day": i, "outcome": "stop", "net": b.open / entry - 1 - cost}
        if b.low <= stop:
            return {"exit": float(stop), "exit_day": i, "outcome": "stop", "net": stop / entry - 1 - cost}
        if b.high >= target:
            return {"exit": float(target), "exit_day": i, "outcome": "target", "net": target / entry - 1 - cost}
    last = float(fwd["close"].iloc[-1])
    return {"exit": last, "exit_day": len(fwd), "outcome": "time", "net": last / entry - 1 - cost}


def entry_quality(r) -> dict:
    get = (lambda k, d=np.nan: r.get(k, d)) if isinstance(r, dict) else (lambda k, d=np.nan: r[k] if k in r else d)
    def f(v):
        return 0.0 if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)
    atr_pct = f(get("atr_pct")) or 1e-9
    comp = {
        "price_action": 0.5 * f(get("clv")) + 0.5 * min(1.0, max(0.0, (f(get("close")) / (f(get("hh20")) or np.inf) - 1) / atr_pct)),
        "volume": 0.7 * min(1.0, f(get("rvol")) / 3) + 0.3 * float(bool(get("updown_ok", False))),
        "trend_rs": 0.5 * float(f(get("ema20")) > f(get("ema50"))) + 0.5 * float(f(get("rs20_nifty")) > 0),
        "volatility": 0.5 * float(f(get("atr_prev")) < 0.75 * f(get("atr_prev21"))) + 0.5 * float(0 < f(get("range10")) <= 0.10),
        "catalyst": 1.0 if bool(get("event_positive_today", False)) else (0.5 if bool(get("event_recent", False)) else 0.0),
        "regime": 0.5 * float(bool(get("nifty_above_ema50", False))) + 0.5 * float(f(get("nifty_ret5")) >= 0),
        "liquidity": min(1.0, f(get("adv20")) / 5e8),
    }
    return {"eqs": sum(EQS_WEIGHTS[k] * v for k, v in comp.items()), "components": comp}
