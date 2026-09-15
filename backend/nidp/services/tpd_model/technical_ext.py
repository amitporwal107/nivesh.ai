"""v3 technical extensions (PRD §6-12), computed for one symbol from its last WINDOW bars up to T.

Everything is derived from a fixed-length slice so a value never depends on how much older history the caller
happened to pass (Wilder smoothing and EMAs carry memory of where they were seeded).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from nidp.services.technical_indicator_engine import calculator as calc

from .features import WINDOW

TECHNICAL_EXT_FEATURES = (
    "vol_ratio_5", "vol_ratio_20", "vol_ratio_50", "vol_ratio_100", "vol_ratio_250",
    "vol_accel_5_20", "vol_accel_10_50", "vol_accel_20_100",
    "atr5_atr20", "atr20_atr100", "macd_hist_pct", "adx14", "donchian20_pos",
    "dist_sma100", "dist_sma200", "range20_pct", "range20_vs_100",
)


def _num(x) -> float:
    return float("nan") if x is None or not np.isfinite(x) else float(x)


def _ratio(a, b) -> float:
    a, b = _num(a), _num(b)
    return a / b if np.isfinite(a) and np.isfinite(b) and b != 0 else float("nan")


def _mean_ratio(v: np.ndarray, short: int, long: int) -> float:
    if len(v) < long:
        return float("nan")
    return _ratio(np.nanmean(v[-short:]), np.nanmean(v[-long:]))


def wilder_adx(h: np.ndarray, lo: np.ndarray, c: np.ndarray, period: int = 14) -> float:
    if len(c) < 2 * period + 1:
        return float("nan")
    up, dn = h[1:] - h[:-1], lo[:-1] - lo[1:]
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum(h[1:] - lo[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(lo[1:] - c[:-1])))

    def smooth(x):
        s = np.empty(len(x) - period + 1)
        s[0] = x[:period].sum()
        for i in range(1, len(s)):
            s[i] = s[i - 1] - s[i - 1] / period + x[period + i - 1]
        return s

    s_tr, s_plus, s_minus = smooth(tr), smooth(plus_dm), smooth(minus_dm)
    with np.errstate(divide="ignore", invalid="ignore"):
        di_plus, di_minus = 100 * s_plus / s_tr, 100 * s_minus / s_tr
        dx = 100 * np.abs(di_plus - di_minus) / (di_plus + di_minus)
    dx = np.where(np.isfinite(dx), dx, 0.0)
    if len(dx) < period:
        return float("nan")
    adx = dx[:period].mean()
    for i in range(period, len(dx)):
        adx = (adx * (period - 1) + dx[i]) / period
    return float(adx)


def extended_technical(w: pd.DataFrame) -> dict[str, float]:
    w = w.sort_values("as_of_date", kind="mergesort").tail(WINDOW)
    h, lo, c, v = (w[col].to_numpy(np.float64) for col in ("high", "low", "close", "volume"))
    n = len(c)
    f: dict[str, float] = {}
    for p in (5, 20, 50, 100, 250):
        f[f"vol_ratio_{p}"] = _ratio(v[-1], np.nanmean(v[-1 - p:-1])) if n > p else float("nan")
    f["vol_accel_5_20"] = _mean_ratio(v, 5, 20)
    f["vol_accel_10_50"] = _mean_ratio(v, 10, 50)
    f["vol_accel_20_100"] = _mean_ratio(v, 20, 100)
    atr = {p: calc.atr(h, lo, c, period=p) for p in (5, 20, 100)}
    f["atr5_atr20"] = _ratio(atr[5], atr[20])
    f["atr20_atr100"] = _ratio(atr[20], atr[100])
    _, _, hist = calc.macd(c)
    f["macd_hist_pct"] = _ratio(hist, c[-1]) * 100 if hist is not None else float("nan")
    f["adx14"] = wilder_adx(h, lo, c)
    if n >= 20:
        hi20, lo20 = h[-20:].max(), lo[-20:].min()
        f["donchian20_pos"] = _ratio(c[-1] - lo20, hi20 - lo20)
        f["range20_pct"] = _ratio(hi20 - lo20, c[-1]) * 100
    else:
        f["donchian20_pos"] = f["range20_pct"] = float("nan")
    f["range20_vs_100"] = _ratio(f["range20_pct"], _ratio(h[-100:].max() - lo[-100:].min(), c[-1]) * 100) if n >= 100 else float("nan")
    f["dist_sma100"] = _num(calc.dist_from_level(float(c[-1]), calc.sma(c, 100)))
    f["dist_sma200"] = _num(calc.dist_from_level(float(c[-1]), calc.sma(c, 200)))
    return {k: float(f[k]) for k in TECHNICAL_EXT_FEATURES}
