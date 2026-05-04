"""Pure-Python technical feature calculator.

All functions take a chronologically-ordered list of bar dicts:
    {bar_date, open, high, low, close, volume, delivery_pct}

Conventions:
- Bars MUST be sorted ascending by date. The most recent bar is bars[-1].
- Functions return None when there are not enough bars to compute reliably.
- No numpy / pandas: keeps the engine import-light and portable.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence


Bar = Dict[str, float]


# ── Helpers ──────────────────────────────────────────────────────────────
def _closes(bars: Sequence[Bar]) -> List[float]:
    return [float(b["close"]) for b in bars]


def _highs(bars: Sequence[Bar]) -> List[float]:
    return [float(b["high"]) for b in bars]


def _lows(bars: Sequence[Bar]) -> List[float]:
    return [float(b["low"]) for b in bars]


def _volumes(bars: Sequence[Bar]) -> List[float]:
    return [float(b.get("volume") or 0) for b in bars]


def _delivery(bars: Sequence[Bar]) -> List[Optional[float]]:
    return [b.get("delivery_pct") for b in bars]


# ── Moving averages ──────────────────────────────────────────────────────
def sma(values: Sequence[float], period: int) -> Optional[float]:
    if len(values) < period or period <= 0:
        return None
    return sum(values[-period:]) / period


def ema_series(values: Sequence[float], period: int) -> List[Optional[float]]:
    """Standard EMA with SMA seed at index `period - 1`."""
    if period <= 0:
        return [None] * len(values)
    out: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    k = 2.0 / (period + 1)
    for i in range(period, len(values)):
        prev = out[i - 1]
        assert prev is not None
        out[i] = (values[i] - prev) * k + prev
    return out


def ema(values: Sequence[float], period: int) -> Optional[float]:
    s = ema_series(values, period)
    return s[-1] if s else None


# ── RSI (Wilder's smoothing) ─────────────────────────────────────────────
def rsi(values: Sequence[float], period: int = 14) -> Optional[float]:
    if len(values) < period + 1:
        return None
    gains: List[float] = []
    losses: List[float] = []
    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


# ── MACD ─────────────────────────────────────────────────────────────────
def macd(values: Sequence[float],
         fast: int = 12, slow: int = 26, signal: int = 9
         ) -> Optional[Dict[str, float]]:
    if len(values) < slow + signal:
        return None
    fast_s = ema_series(values, fast)
    slow_s = ema_series(values, slow)
    macd_line: List[Optional[float]] = []
    for f, s in zip(fast_s, slow_s):
        macd_line.append(f - s if (f is not None and s is not None) else None)
    valid = [m for m in macd_line if m is not None]
    if len(valid) < signal:
        return None
    sig_s = ema_series(valid, signal)
    sig = sig_s[-1]
    line = macd_line[-1]
    if sig is None or line is None:
        return None
    return {"macd": line, "signal": sig, "hist": line - sig}


# ── ATR (Wilder's True Range) ────────────────────────────────────────────
def atr(bars: Sequence[Bar], period: int = 14) -> Optional[float]:
    if len(bars) < period + 1:
        return None
    trs: List[float] = []
    for i in range(1, len(bars)):
        h = float(bars[i]["high"])
        l = float(bars[i]["low"])
        pc = float(bars[i - 1]["close"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        a = (a * (period - 1) + trs[i]) / period
    return a


# ── Bollinger band width (squeeze detection) ─────────────────────────────
def bollinger_width(values: Sequence[float], period: int = 20,
                    mult: float = 2.0) -> Optional[float]:
    if len(values) < period:
        return None
    window = values[-period:]
    mean = sum(window) / period
    var = sum((v - mean) ** 2 for v in window) / period
    std = math.sqrt(var)
    if mean == 0:
        return None
    return (2 * mult * std) / mean   # normalised width


# ── Slope of close (linear regression, last N bars) ──────────────────────
def slope_pct(values: Sequence[float], period: int) -> Optional[float]:
    """Slope of close over `period` bars, expressed as % per bar of last close."""
    if len(values) < period or period < 2:
        return None
    y = values[-period:]
    n = period
    x_mean = (n - 1) / 2.0
    y_mean = sum(y) / n
    num = sum((i - x_mean) * (y[i] - y_mean) for i in range(n))
    den = sum((i - x_mean) ** 2 for i in range(n))
    if den == 0:
        return None
    slope = num / den
    last = y[-1]
    if last == 0:
        return None
    return (slope / last) * 100.0


# ── Returns over windows ─────────────────────────────────────────────────
def return_pct(values: Sequence[float], lookback: int) -> Optional[float]:
    if len(values) <= lookback or lookback <= 0:
        return None
    base = values[-1 - lookback]
    if base == 0:
        return None
    return (values[-1] / base - 1.0) * 100.0


# ── Range highs / lows ───────────────────────────────────────────────────
def highest(values: Sequence[float], period: int) -> Optional[float]:
    if len(values) < period or period <= 0:
        return None
    return max(values[-period:])


def lowest(values: Sequence[float], period: int) -> Optional[float]:
    if len(values) < period or period <= 0:
        return None
    return min(values[-period:])


# ── Pivot-based swing levels (for support/resistance, stop placement) ────
def swing_low(bars: Sequence[Bar], lookback: int = 20) -> Optional[float]:
    """Lowest low in last `lookback` bars (excluding today)."""
    if len(bars) < lookback + 1:
        return None
    return min(float(b["low"]) for b in bars[-lookback - 1:-1])


def swing_high(bars: Sequence[Bar], lookback: int = 20) -> Optional[float]:
    if len(bars) < lookback + 1:
        return None
    return max(float(b["high"]) for b in bars[-lookback - 1:-1])


# ── Volume Z-score and dry-up detection ──────────────────────────────────
def volume_zscore(bars: Sequence[Bar], period: int = 20) -> Optional[float]:
    vols = _volumes(bars)
    if len(vols) < period + 1:
        return None
    window = vols[-period - 1:-1]
    mean = sum(window) / period
    var = sum((v - mean) ** 2 for v in window) / period
    std = math.sqrt(var) if var > 0 else 0
    if std == 0:
        return None
    return (vols[-1] - mean) / std


def delivery_trend_pct(bars: Sequence[Bar], period: int = 10) -> Optional[float]:
    """Recent vs prior delivery %, expressed as relative change.
    >0 means delivery % is rising (accumulation signal)."""
    dlv = [d for d in _delivery(bars) if d is not None]
    if len(dlv) < period * 2:
        return None
    recent = sum(dlv[-period:]) / period
    prior = sum(dlv[-period * 2:-period]) / period
    if prior == 0:
        return None
    return (recent / prior - 1.0) * 100.0


# ── Smart-money / accumulation signals ──────────────────────────────────
# Building blocks for a TRUE accumulation classifier (per PRD §smart-edge):
#   range_pct_n    — high-low band as % of close over last N days
#   volume_drying  — slope of volume over last N days (negative = drying)
#   volume_spike   — last 3d avg volume / N-day avg
#   higher_lows    — count of higher swing lows in last N bars (proxy for
#                    base-building structure)
#   upper_wick_pct — how much of recent range is in the upper wick
#                    (high selling pressure if large)

def range_pct_n(bars: Sequence[Bar], lookback: int = 15) -> Optional[float]:
    """High-low band over last N days as % of last close.
    A tight base typically prints < 8% on this metric."""
    if len(bars) < lookback:
        return None
    window = bars[-lookback:]
    hi = max(float(b["high"]) for b in window)
    lo = min(float(b["low"]) for b in window)
    last_close = float(bars[-1]["close"])
    if last_close <= 0:
        return None
    return (hi - lo) / last_close * 100.0


def volume_drying(bars: Sequence[Bar], lookback: int = 10) -> Optional[float]:
    """Linear slope of volume over the last N bars, normalised to %/bar.
    Negative → volume is drying up (textbook accumulation precondition).
    Positive → volume rising (good for breakout, bad for accumulation)."""
    vols = _volumes(bars)
    if len(vols) < lookback:
        return None
    window = vols[-lookback:]
    n = len(window)
    mean_v = sum(window) / n
    if mean_v <= 0:
        return None
    # OLS slope on (i, vol) — index normalised so result is %/bar of mean_v
    mean_x = (n - 1) / 2.0
    num = sum((i - mean_x) * (window[i] - mean_v) for i in range(n))
    den = sum((i - mean_x) ** 2 for i in range(n))
    if den == 0:
        return None
    slope = num / den
    return slope / mean_v * 100.0   # %/bar of mean volume


def volume_spike_ratio(bars: Sequence[Bar], spike_n: int = 3,
                       baseline: int = 20) -> Optional[float]:
    """Avg volume over last `spike_n` bars / avg over `baseline` bars.
    > 1.5 is the breakout-confirmation rule of thumb. > 2 is strong."""
    vols = _volumes(bars)
    if len(vols) < baseline + spike_n:
        return None
    recent = sum(vols[-spike_n:]) / spike_n
    base = sum(vols[-baseline:]) / baseline
    if base <= 0:
        return None
    return recent / base


def higher_lows_count(bars: Sequence[Bar], lookback: int = 20,
                      pivot_window: int = 3) -> int:
    """Count of higher swing lows in the lookback window. A swing low is
    a bar whose low is the minimum within ± `pivot_window` bars. Each
    swing low that's above the previous swing low counts as a "higher low".
    More higher lows → cleaner ascending-base structure (bullish)."""
    if len(bars) < lookback + pivot_window:
        return 0
    window = bars[-lookback:]
    lows = [float(b["low"]) for b in window]
    swing_lows: List[float] = []
    for i in range(pivot_window, len(window) - pivot_window):
        left = lows[i - pivot_window:i]
        right = lows[i + 1:i + 1 + pivot_window]
        if all(lows[i] <= x for x in left) and all(lows[i] <= x for x in right):
            swing_lows.append(lows[i])
    if len(swing_lows) < 2:
        return 0
    return sum(1 for i in range(1, len(swing_lows)) if swing_lows[i] > swing_lows[i - 1])


def upper_wick_pct(bars: Sequence[Bar], lookback: int = 5) -> Optional[float]:
    """Mean (high − close) / (high − low) over last N bars.
    Higher → bigger upper wicks → distribution / supply hits at highs.
    < 0.3 is healthy; > 0.5 is a warning (sellers showing up at highs)."""
    if len(bars) < lookback:
        return None
    window = bars[-lookback:]
    ratios: List[float] = []
    for b in window:
        h, l, c = float(b["high"]), float(b["low"]), float(b["close"])
        rng = h - l
        if rng <= 0:
            continue
        ratios.append((h - c) / rng)
    if not ratios:
        return None
    return sum(ratios) / len(ratios)


# ── Top-level: compute the full feature pack for a symbol ────────────────
def compute_features(bars: Sequence[Bar]) -> Dict[str, Optional[float]]:
    """Return all primitive features needed by the scorer.

    Caller is responsible for sorting `bars` ascending by date and supplying
    enough history (≥ 220 bars recommended for SMA200 + buffer).
    """
    if not bars:
        return {}
    closes = _closes(bars)
    highs = _highs(bars)
    lows = _lows(bars)
    last = closes[-1]

    feat: Dict[str, Optional[float]] = {
        "close": last,
        "sma_20": sma(closes, 20),
        "sma_50": sma(closes, 50),
        "sma_200": sma(closes, 200),
        "ema_20": ema(closes, 20),
        "rsi_14": rsi(closes, 14),
        "atr_14": atr(bars, 14),
        "bb_width_20": bollinger_width(closes, 20),
        "slope_20_pct": slope_pct(closes, 20),
        "return_5d_pct": return_pct(closes, 5),
        "return_10d_pct": return_pct(closes, 10),
        "return_20d_pct": return_pct(closes, 20),
        "return_60d_pct": return_pct(closes, 60),
        "high_20d": highest(highs, 20),
        "low_20d": lowest(lows, 20),
        "high_52w": highest(highs, 252),
        "low_52w": lowest(lows, 252),
        "swing_low_20": swing_low(bars, 20),
        "swing_high_20": swing_high(bars, 20),
        "volume_z_20": volume_zscore(bars, 20),
        "delivery_trend_pct": delivery_trend_pct(bars, 10),
    }

    macd_v = macd(closes)
    if macd_v:
        feat["macd"] = macd_v["macd"]
        feat["macd_signal"] = macd_v["signal"]
        feat["macd_hist"] = macd_v["hist"]
    else:
        feat["macd"] = feat["macd_signal"] = feat["macd_hist"] = None

    # Derived: distance to support, range tightness, breakout proximity
    if feat["close"] and feat["swing_low_20"]:
        feat["dist_to_support_pct"] = (last - feat["swing_low_20"]) / last * 100.0
    else:
        feat["dist_to_support_pct"] = None

    if feat["close"] and feat["high_20d"]:
        # >= 0 means breaking out; < 0 means below recent high
        feat["breakout_proximity_pct"] = (last - feat["high_20d"]) / feat["high_20d"] * 100.0
    else:
        feat["breakout_proximity_pct"] = None

    if feat["atr_14"] and feat["close"]:
        feat["atr_pct"] = feat["atr_14"] / feat["close"] * 100.0
    else:
        feat["atr_pct"] = None

    return feat
