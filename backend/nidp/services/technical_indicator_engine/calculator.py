"""Pure-numpy technical indicator calculations.

All functions take numpy arrays (oldest-first) and return a scalar for the
last bar, or a tuple of scalars when multiple outputs are needed.
No external dependencies beyond numpy — importable anywhere.
"""
from __future__ import annotations

from typing import Optional
import numpy as np


# ── Moving Averages ─────────────────────────────────────────────────

def sma(arr: np.ndarray, period: int) -> Optional[float]:
    if len(arr) < period:
        return None
    return float(np.mean(arr[-period:]))


def _ema_series(arr: np.ndarray, period: int) -> np.ndarray:
    """Full EMA series (same length as arr). First value = arr[0]."""
    k = 2.0 / (period + 1)
    out = np.empty(len(arr))
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = arr[i] * k + out[i - 1] * (1.0 - k)
    return out


def ema(arr: np.ndarray, period: int) -> Optional[float]:
    if len(arr) < period:
        return None
    return float(_ema_series(arr, period)[-1])


def sma_slope(arr: np.ndarray, period: int, lookback: int = 20) -> Optional[float]:
    """Per-day SMA slope as Δ% over `lookback` bars."""
    if len(arr) < period + lookback:
        return None
    end_sma = sma(arr, period)
    start_sma = sma(arr[:-lookback], period)
    if end_sma is None or start_sma is None or start_sma == 0:
        return None
    return float((end_sma - start_sma) / abs(start_sma) / lookback * 100)


# ── RSI (Wilder's smoothing) ────────────────────────────────────────

def rsi(closes: np.ndarray, period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - 100.0 / (1.0 + rs))


# ── MACD ────────────────────────────────────────────────────────────

def macd(closes: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Returns (macd_line, signal_line, histogram)."""
    min_len = slow + signal
    if len(closes) < min_len:
        return None, None, None

    ema_fast = _ema_series(closes, fast)
    ema_slow = _ema_series(closes, slow)
    macd_line = ema_fast - ema_slow

    # Signal = EMA(9) of macd_line — only from bar `slow` onward to avoid
    # startup noise in the slow EMA
    sig_series = _ema_series(macd_line[slow - 1:], signal)
    macd_val = float(macd_line[-1])
    sig_val = float(sig_series[-1])
    hist_val = macd_val - sig_val
    return macd_val, sig_val, hist_val


# ── ATR (Wilder's) ──────────────────────────────────────────────────

def atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    h, l, c = highs[1:], lows[1:], closes[:-1]
    tr = np.maximum(h - l, np.maximum(np.abs(h - c), np.abs(l - c)))

    # Wilder's smoothing
    avg = float(np.mean(tr[:period]))
    for i in range(period, len(tr)):
        avg = (avg * (period - 1) + tr[i]) / period
    return avg


# ── Bollinger Bands ─────────────────────────────────────────────────

def bollinger(closes: np.ndarray, period: int = 20, n_std: float = 2.0) -> tuple[Optional[float], Optional[float]]:
    """Returns (bb_width, bb_pos). bb_pos ∈ [0,1] roughly."""
    if len(closes) < period:
        return None, None
    window = closes[-period:]
    mid = float(np.mean(window))
    std = float(np.std(window, ddof=1))
    if std == 0 or mid == 0:
        return None, None
    upper = mid + n_std * std
    lower = mid - n_std * std
    width = (upper - lower) / mid
    pos = (closes[-1] - lower) / (upper - lower) if (upper - lower) != 0 else 0.5
    return float(width), float(pos)


# ── Returns ─────────────────────────────────────────────────────────

def pct_return(closes: np.ndarray, bars: int) -> Optional[float]:
    if len(closes) <= bars:
        return None
    base = closes[-(bars + 1)]
    if base == 0:
        return None
    return float((closes[-1] - base) / base * 100)


# ── Volume metrics ───────────────────────────────────────────────────

def volume_stats(volumes: np.ndarray, period: int = 20) -> tuple[Optional[float], Optional[float]]:
    """Returns (avg_volume_20, vol_z20)."""
    if len(volumes) < period:
        return None, None
    window = volumes[-period - 1:-1]   # exclude today from baseline
    if len(window) < period:
        return None, None
    avg = float(np.mean(window))
    std = float(np.std(window, ddof=1))
    z = float((volumes[-1] - avg) / std) if std > 0 else 0.0
    return avg, z


# ── Delivery metrics ────────────────────────────────────────────────

def delivery_stats(deliv_pcts: np.ndarray, period: int = 20) -> tuple[Optional[float], Optional[float]]:
    """Returns (deliv_pct_avg_20, deliv_trend10) where trend is linear slope."""
    valid = deliv_pcts[~np.isnan(deliv_pcts)]
    if len(valid) < 5:
        return None, None
    avg = float(np.mean(valid[-period:])) if len(valid) >= period else float(np.mean(valid))

    # Linear regression slope over last 10 points
    n = min(10, len(valid))
    y = valid[-n:]
    x = np.arange(n, dtype=float)
    if n < 3:
        return avg, None
    slope = float(np.polyfit(x, y, 1)[0])
    return avg, slope


# ── Swing / distance metrics ─────────────────────────────────────────

def swing_high_low(highs: np.ndarray, lows: np.ndarray, period: int = 20) -> tuple[Optional[float], Optional[float]]:
    if len(highs) < period:
        return None, None
    return float(np.max(highs[-period:])), float(np.min(lows[-period:]))


def dist_from_level(close: float, level: Optional[float]) -> Optional[float]:
    if level is None or level == 0:
        return None
    return float((close - level) / abs(level) * 100)


def pivot_breakout(close: float, prev_close: float, swing_high_prev: Optional[float]) -> Optional[bool]:
    """True if today's close crossed above the prior period's swing high."""
    if swing_high_prev is None:
        return None
    return bool(close > swing_high_prev and prev_close <= swing_high_prev)


# ── 52-week high/low ─────────────────────────────────────────────────

def dist_52w(closes: np.ndarray, highs: np.ndarray, lows: np.ndarray) -> tuple[Optional[float], Optional[float]]:
    """Returns (dist_52w_high_pct, dist_52w_low_pct). Both ≤ 0 for high."""
    bars_252 = 252
    if len(closes) < 2:
        return None, None
    h_window = highs[-min(bars_252, len(highs)):]
    l_window = lows[-min(bars_252, len(lows)):]
    high_52 = float(np.max(h_window))
    low_52 = float(np.min(l_window))
    c = float(closes[-1])
    dist_high = dist_from_level(c, high_52)
    dist_low = dist_from_level(c, low_52)
    return dist_high, dist_low


# ── Master feature computation ────────────────────────────────────────

def compute_features(
    closes: np.ndarray,
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    volumes: np.ndarray,
    deliv_pcts: np.ndarray,
) -> dict:
    """Compute all technical features for the last bar. All arrays oldest-first."""
    c = float(closes[-1]) if len(closes) > 0 else 0.0

    sma20_val = sma(closes, 20)
    sma50_val = sma(closes, 50)
    sma100_val = sma(closes, 100)
    sma200_val = sma(closes, 200)

    macd_val, sig_val, hist_val = macd(closes)
    bb_w, bb_p = bollinger(closes)
    avg_vol, vol_z = volume_stats(volumes)
    deliv_avg, deliv_trend = delivery_stats(deliv_pcts)
    swing_h, swing_l = swing_high_low(highs, lows)
    dist_52h, dist_52l = dist_52w(closes, highs, lows)
    atr_val = atr(highs, lows, closes)
    rsi_val = rsi(closes)

    # Pivot breakout: compare with prior period swing high
    prev_swing_h, _ = swing_high_low(highs[:-1], lows[:-1]) if len(highs) > 20 else (None, None)
    breakout = pivot_breakout(c, float(closes[-2]) if len(closes) > 1 else c, prev_swing_h)

    return {
        "close":             c,
        "sma20":             sma20_val,
        "sma50":             sma50_val,
        "sma100":            sma100_val,
        "sma200":            sma200_val,
        "sma50_slope":       sma_slope(closes, 50),
        "dist_200dma_pct":   dist_from_level(c, sma200_val),
        "dist_52w_high_pct": dist_52h,
        "dist_52w_low_pct":  dist_52l,
        "rsi14":             rsi_val,
        "macd":              macd_val,
        "macd_signal":       sig_val,
        "macd_hist":         hist_val,
        "return_5d_pct":     pct_return(closes, 5),
        "return_20d_pct":    pct_return(closes, 20),
        "return_60d_pct":    pct_return(closes, 60),
        "atr14":             atr_val,
        "atr_pct":           float(atr_val / c * 100) if atr_val and c else None,
        "bb_width":          bb_w,
        "bb_pos":            bb_p,
        "avg_volume_20":     int(avg_vol) if avg_vol is not None else None,
        "vol_z20":           vol_z,
        "deliv_pct_avg_20":  deliv_avg,
        "deliv_trend10":     deliv_trend,
        "swing_high_20":     swing_h,
        "swing_low_20":      swing_l,
        "pivot_breakout_flag": breakout,
        "accumulation_score":  None,
        "accumulation_signals": None,
    }
