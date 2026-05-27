"""Cross-sector technical sub-score.

Applied uniformly across all sector profiles; weighting in the final
composite varies per sector (e.g. 25% for FMCG, 40% for CAPGOODS).

Formula (PRD §7):
    Technical = (Trend × 0.35) + (Relative_Strength × 0.25)
              + (Momentum × 0.20) + (Volume_Confirmation × 0.10)
              + (Volatility_Adj × 0.10)

Inputs:
    prims     — from nidp.v_v3_stock_primitives
    tech_data — additional fields from nidp.stock_features_daily
                (sma50, sma200, dist_52w_high_pct, deliv_pct_avg_20, vol_z20)
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .normalizers import hib, lib, weighted


def score_technical(
    prims: Dict[str, Any],
    tech_data: Dict[str, Any],
) -> tuple[float, Dict[str, float]]:
    """Return (technical_score 0–100, sub_scores dict)."""

    def _p(key: str) -> Optional[float]:
        v = prims.get(key)
        return float(v) if v is not None else None

    def _t(key: str) -> Optional[float]:
        v = tech_data.get(key)
        return float(v) if v is not None else None

    # ── 1. Trend Score (35%) ──────────────────────────────────────────
    close    = _t("close")
    sma50    = _t("sma50")
    sma200   = _t("sma200")
    sma50_slope = _t("sma50_slope")          # slope of 50DMA (proxy for 200DMA direction)
    dist_52w = _t("dist_52w_high_pct")       # negative = below 52W high

    above_200 = 30.0 if (close and sma200 and close > sma200) else 0.0
    above_50  = 25.0 if (close and sma50  and close > sma50)  else 0.0
    slope_ok  = 25.0 if (sma50_slope and sma50_slope > 0)     else 0.0

    # Price vs 52W High: within 25% of high scores well
    # dist_52w_high_pct is typically negative (below high) or 0 (at high)
    if dist_52w is not None:
        # dist_52w = (price - 52W_high) / 52W_high * 100, so negative = below high
        # If at high (0%), score = 100; if 25% below, score = 0
        pct_of_high = 100.0 + dist_52w  # convert to % of 52W high
        price_vs_high_score = max(0.0, min(100.0, (pct_of_high - 75.0) / 25.0 * 100.0))
    else:
        price_vs_high_score = 50.0

    trend_score = above_200 + above_50 + slope_ok + price_vs_high_score * 0.20
    trend_score = min(100.0, max(0.0, trend_score))

    # ── 2. Relative Strength (25%) ────────────────────────────────────
    # Use return_252d_pct as a proxy (sector-relative percentile computed
    # at the engine level where peer data is available; here use raw return).
    # If sector index return is available in tech_data, use relative return.
    ret_252d = _p("return_252d_pct")
    sector_ret = _t("sector_index_return_252d_pct")   # optional, populated by engine
    if ret_252d is not None and sector_ret is not None:
        relative_return = ret_252d - sector_ret
    elif ret_252d is not None:
        relative_return = ret_252d  # absolute return as fallback
    else:
        relative_return = None

    # Map: +20% outperformance → 100; -20% → 0
    rs_score = hib(relative_return, floor=-20.0, ceiling=20.0)

    # ── 3. Momentum (20%) ─────────────────────────────────────────────
    rsi   = _p("rsi14")
    macd  = _p("macd")
    macs  = _p("macd_signal")
    mach  = _p("macd_hist")

    # RSI sweet spot 50–65 → 100; overbought >80 or oversold <30 → 0
    if rsi is None:
        rsi_score = 50.0
    elif 50 <= rsi <= 65:
        rsi_score = 100.0
    elif 40 <= rsi < 50 or 65 < rsi <= 75:
        rsi_score = 70.0
    elif 30 <= rsi < 40 or 75 < rsi <= 80:
        rsi_score = 30.0
    else:
        rsi_score = 0.0  # deeply oversold (<30) or overbought (>80)

    # MACD scoring
    if macd is None or macs is None:
        macd_score = 50.0
    elif macd > macs and mach is not None and mach > 0:
        macd_score = 100.0   # above signal + rising histogram
    elif macd > macs:
        macd_score = 50.0    # above signal but histogram flat/falling
    elif macd < macs and mach is not None and mach > 0:
        macd_score = 25.0    # below signal but histogram rising (early reversal)
    else:
        macd_score = 0.0     # below signal and falling

    # Price ROC: use 60-day return (return_60d not in prims — use 252d/4 as proxy)
    ret_60d = _t("return_60d_pct")
    roc_score = hib(ret_60d, floor=-15.0, ceiling=20.0) if ret_60d else 50.0

    momentum_score = weighted([
        (rsi_score,  40),
        (macd_score, 30),
        (roc_score,  30),
    ])

    # ── 4. Volume Confirmation (10%) ──────────────────────────────────
    deliv_pct = _t("deliv_pct_avg_20")
    vol_z     = _t("vol_z20")            # volume z-score vs 20D avg

    deliv_score  = hib(deliv_pct, floor=30.0, ceiling=70.0)

    # Volume vs 30D avg: moderate surge (1.0–2.0 std) is positive;
    # extreme surge may indicate distribution
    if vol_z is None:
        vol_avg_score = 50.0
    elif 0.5 <= vol_z <= 2.0:
        vol_avg_score = 80.0
    elif vol_z > 2.0:
        vol_avg_score = 60.0   # very high volume — can be accumulation or distribution
    else:
        vol_avg_score = 30.0   # low volume — weak confirmation

    # OBV trend: use accumulation_score from stock_features_daily
    obv_score = _p("accumulation_score") or 50.0
    obv_score = max(0.0, min(100.0, float(obv_score)))

    volume_score = weighted([
        (deliv_score,  50),
        (vol_avg_score, 30),
        (obv_score,    20),
    ])

    # ── 5. Volatility Adjustment (10%) ────────────────────────────────
    vol_1y = _p("volatility_1y_pct")
    vol_score = lib(vol_1y, floor=15.0, ceiling=50.0)

    # ── Composite ─────────────────────────────────────────────────────
    score = weighted([
        (trend_score,    35),
        (rs_score,       25),
        (momentum_score, 20),
        (volume_score,   10),
        (vol_score,      10),
    ])

    sub = {
        "trend":          round(trend_score, 2),
        "relative_strength": round(rs_score, 2),
        "momentum":       round(momentum_score, 2),
        "volume":         round(volume_score, 2),
        "volatility_adj": round(vol_score, 2),
        "_rsi":           round(rsi_score, 2),
        "_macd":          round(macd_score, 2),
    }
    return score, sub
