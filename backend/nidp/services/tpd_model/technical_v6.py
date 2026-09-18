"""v6 technical feature engine (PRD "Ten-Percent Days v6" §5, §16) — RESEARCH ONLY, not wired to any model or page yet.

Every value at T is computed from bars up to and including T; nothing reads a later bar. A feature whose window is not
fully present is NaN — missing stays missing rather than being filled with a plausible number (PRD §15).

Scope: the families the current v4 set does not already carry. v4's 84 inputs already include the simple trend distances,
RSI14, ATR ratios, volume ratios/z-scores, gap and range, 52-week distances and Donchian position (design.MODEL_COLUMNS_V4),
so those are not recomputed here. What was genuinely absent, and is added below:

  trend        ema slopes, alignment across four EMAs, Kaufman trend efficiency, higher-high/low counts
  momentum     RSI slope, momentum acceleration, positive-day ratio
  volatility   ATR and Bollinger-width percentiles against the stock's own recent history, range expansion, TR z-score
  volume       up/down volume ratio, OBV slope, CMF, MFI, delivery z-score, high-volume close quality
  price action close location, body and wick geometry in both range and ATR terms
  structure    distance to resistance/support in ATR, breakout age, failed breakouts, consolidation length
  relative     return against an index series the caller supplies (sector strength is cross-sectional: caller's job)

The PRD is explicit that these describe the tape and are not signals: ADX-style trend strength says nothing about
direction, and volatility expansion is not bullish on its own. Nothing here decides anything.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FEATURE_VERSION = "v6.0"

TREND = ("ema20_slope_10d", "ema50_slope_20d", "trend_alignment_score", "trend_efficiency_20d",
         "higher_high_count_20d", "higher_low_count_20d")
MOMENTUM = ("rsi_slope_3d", "momentum_acceleration", "positive_return_day_ratio_10d")
VOLATILITY = ("volatility_percentile_60d", "bollinger_width_percentile", "range_expansion_ratio", "true_range_zscore")
VOLUME = ("up_volume_down_volume_ratio_10d", "obv_slope_10d", "cmf20", "mfi14", "delivery_zscore_20d",
          "high_volume_positive_close_ratio")
PRICE_ACTION = ("close_location_value", "body_pct_of_range", "upper_wick_pct", "lower_wick_pct", "body_to_atr")
STRUCTURE = ("distance_to_resistance_atr", "distance_to_support_atr", "breakout_age_days",
             "failed_breakout_count_60d", "consolidation_days")
RELATIVE = ("relative_return_5d", "relative_return_20d")
FEATURES_V6 = TREND + MOMENTUM + VOLATILITY + VOLUME + PRICE_ACTION + STRUCTURE + RELATIVE

NAN = float("nan")


def _f(x) -> float:
    """float, with every non-finite input collapsing to NaN so a missing window never leaks a 0."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return NAN
    return v if np.isfinite(v) else NAN


def _ratio(a, b) -> float:
    a, b = _f(a), _f(b)
    return a / b if np.isfinite(a) and np.isfinite(b) and b != 0 else NAN


def _pct_rank(series: np.ndarray, value: float) -> float:
    """Where `value` sits inside `series`, 0..1. The stock's own history is the yardstick, not a cross-section."""
    s = series[np.isfinite(series)]
    v = _f(value)
    if s.size < 2 or not np.isfinite(v):
        return NAN
    return float((s <= v).sum() / s.size)


def _ema(x: np.ndarray, span: int) -> np.ndarray:
    return pd.Series(x).ewm(span=span, adjust=False).mean().to_numpy()


def _rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    """Wilder RSI. 100 when a window has no losses at all (the standard degenerate case)."""
    d = np.diff(close, prepend=close[0])
    gain = pd.Series(np.clip(d, 0, None)).ewm(alpha=1 / period, adjust=False).mean().to_numpy()
    loss = pd.Series(np.clip(-d, 0, None)).ewm(alpha=1 / period, adjust=False).mean().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        rsi = 100 - 100 / (1 + gain / loss)
    return np.where(loss <= 0, 100.0, rsi)


def _true_range(h: np.ndarray, l: np.ndarray, c: np.ndarray) -> np.ndarray:
    prev = np.roll(c, 1)
    prev[0] = c[0]
    return np.maximum(h - l, np.maximum(np.abs(h - prev), np.abs(l - prev)))


def _atr(h, l, c, period: int = 14) -> np.ndarray:
    return pd.Series(_true_range(h, l, c)).rolling(period, min_periods=period).mean().to_numpy()


def trend_features(c: np.ndarray, h: np.ndarray, l: np.ndarray) -> dict[str, float]:
    e20, e50, e100, e200 = (_ema(c, n) for n in (20, 50, 100, 200))
    n = len(c)
    out = {
        "ema20_slope_10d": _ratio(e20[-1], e20[-11]) - 1 if n > 10 else NAN,
        "ema50_slope_20d": _ratio(e50[-1], e50[-21]) - 1 if n > 20 else NAN,
        # how much of the last 20 sessions' travel went in one direction: 1 = a straight line, 0 = pure churn
        "trend_efficiency_20d": NAN,
        "higher_high_count_20d": NAN,
        "higher_low_count_20d": NAN,
    }
    # alignment needs enough bars for the slowest EMA to mean anything; below that it would read a seeded value
    if n >= 200:
        checks = [c[-1] > e20[-1], e20[-1] > e50[-1], e50[-1] > e100[-1], e100[-1] > e200[-1]]
        out["trend_alignment_score"] = float(np.mean(checks))
    else:
        out["trend_alignment_score"] = NAN
    if n > 20:
        travel = np.abs(np.diff(c[-21:])).sum()
        out["trend_efficiency_20d"] = _ratio(abs(c[-1] - c[-21]), travel)
        out["higher_high_count_20d"] = float((np.diff(h[-21:]) > 0).sum())
        out["higher_low_count_20d"] = float((np.diff(l[-21:]) > 0).sum())
    return out


def momentum_features(c: np.ndarray) -> dict[str, float]:
    n = len(c)
    rsi = _rsi(c)
    ret5 = _ratio(c[-1], c[-6]) - 1 if n > 5 else NAN
    ret5_prev = _ratio(c[-6], c[-11]) - 1 if n > 10 else NAN
    return {
        "rsi_slope_3d": _f(rsi[-1] - rsi[-4]) if n > 3 else NAN,
        # is the 5-day move faster or slower than the 5 days before it
        "momentum_acceleration": _f(ret5 - ret5_prev) if np.isfinite(ret5) and np.isfinite(ret5_prev) else NAN,
        "positive_return_day_ratio_10d": float((np.diff(c[-11:]) > 0).mean()) if n > 10 else NAN,
    }


def volatility_features(c: np.ndarray, h: np.ndarray, l: np.ndarray) -> dict[str, float]:
    n = len(c)
    tr = _true_range(h, l, c)
    atr14 = _atr(h, l, c, 14)
    sma20 = pd.Series(c).rolling(20, min_periods=20).mean().to_numpy()
    sd20 = pd.Series(c).rolling(20, min_periods=20).std(ddof=0).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        bbw = np.where(sma20 > 0, 4 * sd20 / sma20, np.nan)      # upper minus lower band, as a share of the middle
    tr20 = pd.Series(tr).rolling(20, min_periods=20)
    return {
        # percentile against this stock's own last 60 readings — "wide for this stock", not wide versus the market
        "volatility_percentile_60d": _pct_rank(atr14[-60:], atr14[-1]) if n >= 60 else NAN,
        "bollinger_width_percentile": _pct_rank(bbw[-60:], bbw[-1]) if n >= 60 else NAN,
        "range_expansion_ratio": _ratio(np.nanmean(tr[-5:]), np.nanmean(tr[-20:])) if n >= 20 else NAN,
        "true_range_zscore": _ratio(tr[-1] - tr20.mean().to_numpy()[-1], tr20.std(ddof=0).to_numpy()[-1]) if n >= 20 else NAN,
    }


def volume_features(c: np.ndarray, h: np.ndarray, l: np.ndarray, v: np.ndarray,
                    deliv: np.ndarray | None = None) -> dict[str, float]:
    n = len(c)
    out = {k: NAN for k in VOLUME}
    if n > 10:
        d = np.diff(c[-11:])
        vol = v[-10:]
        up, down = vol[d > 0].sum(), vol[d < 0].sum()
        out["up_volume_down_volume_ratio_10d"] = _ratio(up, down)
        # OBV in units of a normal day's volume, so it compares across stocks
        signed = np.sign(np.diff(c)) * v[1:]
        obv = np.cumsum(signed)
        out["obv_slope_10d"] = _ratio(obv[-1] - obv[-11], np.nanmean(v[-20:])) if n > 11 else NAN
    if n >= 20:
        rng = h[-20:] - l[-20:]
        with np.errstate(invalid="ignore", divide="ignore"):
            mfm = np.where(rng > 0, ((c[-20:] - l[-20:]) - (h[-20:] - c[-20:])) / rng, 0.0)
        out["cmf20"] = _ratio(np.nansum(mfm * v[-20:]), np.nansum(v[-20:]))
        rvol = v[-20:] / np.nanmean(v[-20:]) if np.nanmean(v[-20:]) else np.full(20, np.nan)
        loud = rvol >= 1.5
        if loud.sum() > 0:
            clv = np.where(rng > 0, (c[-20:] - l[-20:]) / rng, 0.5)
            out["high_volume_positive_close_ratio"] = float((clv[loud] >= 0.6).mean())
    if n >= 15:
        tp = (h + l + c) / 3
        flow = tp * v
        d = np.diff(tp[-15:])
        pos = flow[-14:][d > 0].sum()
        neg = flow[-14:][d < 0].sum()
        out["mfi14"] = 100.0 if neg == 0 and pos > 0 else _f(100 - 100 / (1 + _ratio(pos, neg)))
    if deliv is not None and len(deliv) >= 20:
        w = np.asarray(deliv[-20:], dtype="float64")
        if np.isfinite(w).sum() >= 10:
            out["delivery_zscore_20d"] = _ratio(_f(deliv[-1]) - np.nanmean(w), np.nanstd(w))
    return out


def price_action_features(o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray) -> dict[str, float]:
    rng = _f(h[-1] - l[-1])
    atr14 = _atr(h, l, c, 14)
    body = _f(c[-1] - o[-1])
    if not np.isfinite(rng) or rng <= 0:                      # a locked bar has no geometry to read
        return {"close_location_value": NAN, "body_pct_of_range": NAN, "upper_wick_pct": NAN,
                "lower_wick_pct": NAN, "body_to_atr": _ratio(body, atr14[-1])}
    return {
        "close_location_value": _ratio(c[-1] - l[-1], rng),
        "body_pct_of_range": _ratio(abs(body), rng),
        "upper_wick_pct": _ratio(h[-1] - max(o[-1], c[-1]), rng),
        "lower_wick_pct": _ratio(min(o[-1], c[-1]) - l[-1], rng),
        "body_to_atr": _ratio(body, atr14[-1]),               # signed: a long red body is as informative as a long green one
    }


def structure_features(h: np.ndarray, l: np.ndarray, c: np.ndarray) -> dict[str, float]:
    """Room to the nearest overhead supply and to the floor beneath, plus how the last breakouts behaved."""
    n = len(c)
    out = {k: NAN for k in STRUCTURE}
    atr = _atr(h, l, c, 14)[-1]
    if n >= 60 and np.isfinite(atr) and atr > 0:
        res, sup = np.nanmax(h[-60:-1]), np.nanmin(l[-60:-1])
        # above the 60-day high there is no overhead supply left in the window: distance 0, not a negative number
        out["distance_to_resistance_atr"] = max(0.0, _f(res - c[-1])) / atr
        out["distance_to_support_atr"] = max(0.0, _f(c[-1] - sup)) / atr
    if n >= 41:
        prior_high = pd.Series(h).shift(1).rolling(20, min_periods=20).max().to_numpy()
        broke = c > prior_high                                 # closed above the prior 20-day high
        idx = np.where(broke[-60:])[0] if n >= 60 else np.where(broke)[0]
        if idx.size:
            out["breakout_age_days"] = float(len(broke[-60:]) - 1 - idx[-1]) if n >= 60 else float(len(broke) - 1 - idx[-1])
        # reached above the prior high intraday but could not close there
        failed = (h > prior_high) & (c <= prior_high)
        out["failed_breakout_count_60d"] = float(np.nansum(failed[-60:]))
    if n >= 10:
        # longest run back from T whose whole high-low span stays inside 10% of today's close
        run, hi, lo = 0, -np.inf, np.inf
        for i in range(n - 1, -1, -1):
            hi, lo = max(hi, h[i]), min(lo, l[i])
            if not np.isfinite(c[-1]) or c[-1] <= 0 or (hi - lo) / c[-1] > 0.10:
                break
            run += 1
        out["consolidation_days"] = float(run)
    return out


def relative_features(c: np.ndarray, index_close: np.ndarray | None) -> dict[str, float]:
    """Stock return minus index return. The caller passes the index series aligned to the same sessions; sector-relative
    strength is cross-sectional and stays the caller's job (it needs every peer's row for that session)."""
    if index_close is None or len(index_close) != len(c):
        return {"relative_return_5d": NAN, "relative_return_20d": NAN}
    out = {}
    for label, k in (("relative_return_5d", 5), ("relative_return_20d", 20)):
        if len(c) > k and np.isfinite(index_close[-k - 1]) and index_close[-k - 1] != 0:
            out[label] = _f((_ratio(c[-1], c[-k - 1]) - 1) - (_ratio(index_close[-1], index_close[-k - 1]) - 1))
        else:
            out[label] = NAN
    return out


def compute(window: pd.DataFrame, index_close: np.ndarray | None = None) -> dict[str, float]:
    """Every v6 feature for the last row of `window` (one symbol, sorted by date, last row = T).

    `window` needs open/high/low/close/volume and may carry deliverable_pct. Pass at least 200 bars for the full set;
    with fewer, the features whose windows are not covered come back NaN.
    """
    w = window.sort_values("as_of_date")
    o, h, l, c, v = (w[k].to_numpy(dtype="float64") for k in ("open", "high", "low", "close", "volume"))
    deliv = w["deliverable_pct"].to_numpy(dtype="float64") if "deliverable_pct" in w else None
    if len(c) == 0:
        return {k: NAN for k in FEATURES_V6}
    out: dict[str, float] = {}
    out.update(trend_features(c, h, l))
    out.update(momentum_features(c))
    out.update(volatility_features(c, h, l))
    out.update(volume_features(c, h, l, v, deliv))
    out.update(price_action_features(o, h, l, c))
    out.update(structure_features(h, l, c))
    out.update(relative_features(c, index_close))
    return {k: out.get(k, NAN) for k in FEATURES_V6}
