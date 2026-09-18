"""v6 regime classifiers and cross-sectional strength (PRD "Ten-Percent Days v6" §5.7, §5.8, §6) — RESEARCH ONLY.

Three things the per-symbol feature engine (technical_v6) cannot do on its own:

  cross_sectional_strength   sector and universe relative strength: needs every peer's row for that session
  market_regime              the market's state that session: needs the index, breadth and dispersion
  technical_regime           the stock's own state: one label per stock-day, from rules fixed here

Every rule is deterministic and written down before any evaluation, per PRD §6. A label describes the tape — it makes no
claim about what happens next, and the PRD is explicit that the classifier is to be judged separately from any outcome
model. Nothing here decides anything.

Two labels are returned for the market rather than one, because trend and volatility are separate questions and
collapsing them would throw away the distinction (a quiet bull market and a violent one are not the same regime).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

REGIME_VERSION = "v6.0"

MARKET_TRENDS = ("BULL_TREND", "BEAR_TREND", "RANGE_BOUND", "BROAD_MARKET_SELL_OFF")
MARKET_VOLATILITY = ("HIGH_VOLATILITY", "NORMAL_VOLATILITY", "LOW_VOLATILITY")
TECHNICAL_REGIMES = ("CAPITULATION", "HIGH_VOLATILITY_EVENT", "DISTRIBUTION", "BREAKOUT_CONFIRMED", "BREAKOUT_ATTEMPT",
                     "MEAN_REVERSION_CANDIDATE", "PULLBACK_IN_UPTREND", "TREND_UP", "TREND_DOWN", "RANGE_BOUND")

NAN = float("nan")


def _f(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return NAN
    return v if np.isfinite(v) else NAN


def cross_sectional_strength(session: pd.DataFrame) -> pd.DataFrame:
    """Relative strength for one session's universe. `session` needs symbol, ret20 and sector (sector may be null).

    Ranks are percentiles within that session only — a stock is strong relative to the names it actually competes with
    that day, never against a fixed historical yardstick. A sector with fewer than 3 members present gets no sector
    figure: a "median" of one or two stocks says nothing.
    """
    out = session[["symbol"]].copy()
    ret = pd.to_numeric(session["ret20"], errors="coerce")
    out["relative_strength_rank_universe"] = ret.rank(pct=True)
    sector = session["sector"] if "sector" in session else pd.Series(np.nan, index=session.index)
    counts = sector.map(sector.value_counts())
    big_enough = counts >= 3
    med = ret.groupby(sector).transform("median").where(big_enough)
    out["sector_relative_strength"] = ret - med
    out["relative_strength_rank_sector"] = ret.groupby(sector).rank(pct=True).where(big_enough)
    return out


def breadth_and_dispersion(session: pd.DataFrame) -> dict[str, float]:
    """Participation and spread for one session: what share of the universe rose, and how far apart the sectors were."""
    ret1 = pd.to_numeric(session["ret1"], errors="coerce")
    out = {"breadth_up_share": _f(ret1.gt(0).mean()) if ret1.notna().any() else NAN, "sector_dispersion": NAN}
    if "sector" in session:
        by_sector = ret1.groupby(session["sector"]).median()
        if by_sector.notna().sum() >= 3:
            out["sector_dispersion"] = _f(by_sector.std(ddof=0))
    return out


def market_regime(index_close: np.ndarray, index_high: np.ndarray | None = None, index_low: np.ndarray | None = None,
                  breadth_up_share: float = NAN, sector_dispersion: float = NAN,
                  dispersion_history: np.ndarray | None = None) -> dict:
    """The market's state at the last bar of the index series.

    trend      BROAD_MARKET_SELL_OFF when the index has fallen hard AND almost nothing participated, since that is a
               different animal from an orderly downtrend; then BULL/BEAR by the 20/50 SMA stack; RANGE_BOUND otherwise.
    volatility the index's own ATR percentile against its last 120 readings — "violent for this market", not an absolute.
    rotation   flagged, not a trend label: sectors far apart while the index itself goes nowhere.
    """
    c = np.asarray(index_close, dtype="float64")
    n = len(c)
    out = {"market_trend": None, "market_volatility": None, "sector_rotation": None,
           "index_ret5": NAN, "index_vs_sma20": NAN, "index_vs_sma50": NAN, "index_atr_percentile_120d": NAN,
           "breadth_up_share": _f(breadth_up_share), "sector_dispersion": _f(sector_dispersion),
           "regime_version": REGIME_VERSION}
    if n < 51:
        return out                                            # not enough index history to call a regime at all

    sma20 = float(np.mean(c[-20:]))
    sma50 = float(np.mean(c[-50:]))
    sma50_prev = float(np.mean(c[-70:-20])) if n >= 70 else NAN
    ret5 = c[-1] / c[-6] - 1 if n > 5 else NAN
    out["index_ret5"] = _f(ret5)
    out["index_vs_sma20"] = _f(c[-1] / sma20 - 1)
    out["index_vs_sma50"] = _f(c[-1] / sma50 - 1)

    if index_high is not None and index_low is not None and n >= 120:
        h, l = np.asarray(index_high, dtype="float64"), np.asarray(index_low, dtype="float64")
        prev = np.roll(c, 1); prev[0] = c[0]
        tr = np.maximum(h - l, np.maximum(np.abs(h - prev), np.abs(l - prev)))
        atr = pd.Series(tr).rolling(14, min_periods=14).mean().to_numpy() / c
        window = atr[-120:][np.isfinite(atr[-120:])]
        if window.size >= 30:
            pctile = float((window <= atr[-1]).sum() / window.size)
            out["index_atr_percentile_120d"] = pctile
            out["market_volatility"] = ("HIGH_VOLATILITY" if pctile >= 0.80 else
                                        "LOW_VOLATILITY" if pctile <= 0.20 else "NORMAL_VOLATILITY")

    b = _f(breadth_up_share)
    if np.isfinite(ret5) and ret5 <= -0.03 and np.isfinite(b) and b <= 0.25:
        out["market_trend"] = "BROAD_MARKET_SELL_OFF"
    elif c[-1] > sma20 > sma50 and (not np.isfinite(sma50_prev) or sma50 > sma50_prev):
        out["market_trend"] = "BULL_TREND"
    elif c[-1] < sma20 < sma50 and (not np.isfinite(sma50_prev) or sma50 < sma50_prev):
        out["market_trend"] = "BEAR_TREND"
    else:
        out["market_trend"] = "RANGE_BOUND"

    d, hist = _f(sector_dispersion), dispersion_history
    if np.isfinite(d) and hist is not None:
        h = np.asarray(hist, dtype="float64")
        h = h[np.isfinite(h)]
        if h.size >= 20 and np.isfinite(ret5):
            # sectors pulling apart while the index goes nowhere
            out["sector_rotation"] = bool(float((h <= d).sum() / h.size) >= 0.80 and abs(ret5) < 0.01)
    return out


def technical_regime(row) -> str | None:
    """One label for one stock-day. `row` carries the v6 features plus close, sma20, ret1, ret3, ret5, rvol, prior_high_20.

    The order below IS the rule: the first match wins, most specific first, so a capitulation day is never also filed as
    a plain downtrend. None when the inputs needed to decide are missing — an unknown state is not RANGE_BOUND.
    """
    def g(k):
        try:
            v = row[k]
        except (KeyError, IndexError, TypeError):
            return NAN
        return _f(v)

    close, sma20, clv = g("close"), g("sma20"), g("close_location_value")
    ret1, ret3, ret5 = g("ret1"), g("ret3"), g("ret5")
    rvol, tr_z = g("relative_volume_20d"), g("true_range_zscore")
    prior_high = g("prior_high_20")
    ema20, ema50, ema50_slope = g("ema20"), g("ema50"), g("ema50_slope_20d")
    rel20 = g("relative_return_20d")
    if not np.isfinite(close):
        return None

    if np.isfinite(ret1) and ret1 <= -0.05 and np.isfinite(rvol) and rvol >= 2.0 and np.isfinite(clv) and clv <= 0.25:
        return "CAPITULATION"
    if np.isfinite(tr_z) and tr_z >= 3.0:
        return "HIGH_VOLATILITY_EVENT"
    if (np.isfinite(rvol) and rvol >= 1.5 and np.isfinite(clv) and clv <= 0.35
            and np.isfinite(ret5) and ret5 < 0):
        return "DISTRIBUTION"
    if np.isfinite(prior_high) and close > prior_high and np.isfinite(clv) and clv >= 0.60:
        return "BREAKOUT_CONFIRMED"
    if np.isfinite(prior_high) and np.isfinite(g("high")) and g("high") > prior_high and close <= prior_high:
        return "BREAKOUT_ATTEMPT"                              # reached above it intraday, could not hold the close
    if np.isfinite(ret3) and ret3 <= -0.04 and np.isfinite(sma20) and close > sma20:
        return "MEAN_REVERSION_CANDIDATE"
    uptrend = (np.isfinite(ema20) and np.isfinite(ema50) and ema20 > ema50
               and np.isfinite(ema50_slope) and ema50_slope > 0)
    if uptrend and np.isfinite(ret3) and ret3 < 0 and np.isfinite(ema20) and close < ema20:
        return "PULLBACK_IN_UPTREND"
    if uptrend and np.isfinite(rel20) and rel20 > 0:
        return "TREND_UP"                                      # the PRD's worked example, §6
    if (np.isfinite(ema20) and np.isfinite(ema50) and ema20 < ema50
            and np.isfinite(ema50_slope) and ema50_slope < 0 and np.isfinite(rel20) and rel20 < 0):
        return "TREND_DOWN"
    if not np.isfinite(ema20) or not np.isfinite(ema50):
        return None                                            # cannot tell: say so rather than defaulting to a label
    return "RANGE_BOUND"
