"""The B0-B5 nested baseline ladder from PATTERN_VALIDATION_PRD_V1 §§5-9.

WHY A LADDER AND NOT A BASELINE
-------------------------------
The PRD's §4 is explicit: do not compare `Pattern vs Volatility` only. The reason is measured, not
theoretical -- on this study's own rows, predicting `up_5 @ H=20`:

    atr_pct  (the volatility rung)   0.635
    -entry price                     0.706    <- BEATS it
    -log(ADV)                        0.688    <- BEATS it
    calendar-month base rate         0.715    <- beats all three, with NO stock information

So "does the pattern beat ATR?" is passable by a model that has learned only that cheap, illiquid
stocks move more. Each rung must therefore be a strict SUBSET of the next, fit the same way on the
same rows, and the reported statistic is the INCREMENT -- never a model's absolute AUC against a
smaller one, which a richer model wins on capacity alone.

WHAT IS ACTUALLY AVAILABLE
--------------------------
Every feature below is extracted from a real event row. Where the PRD names a feature this codebase
does not compute, it is listed in `MISSING` rather than quietly dropped: a rung that silently omits
half its specification is a weaker control than it appears, and the whole point of the ladder is
that the controls are strong.
"""
from __future__ import annotations

import math
from typing import Callable, Mapping, Optional


def _get(row: Mapping, *path, default=None):
    cur = row
    for k in path:
        if not isinstance(cur, Mapping):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def _price(row: Mapping) -> Optional[float]:
    p = _get(row, "entry", "primary", "price")
    return float(p) if p and p > 0 else None


def _ratio(num, den) -> Optional[float]:
    """`num/den - 1`: a DISTANCE, not a level. A raw SMA is mostly a proxy for the share price,
    which B2 already controls; the distance is the part that carries technical information."""
    if num is None or den is None or den == 0:
        return None
    return float(num) / float(den) - 1.0


def _log(x) -> Optional[float]:
    return math.log(float(x)) if x and x > 0 else None


# ── the rungs ───────────────────────────────────────────────────────────────────────────────────
#
# Each entry: name -> extractor. Order is the PRD's order; each rung is added to the one above it.

B1_VOLATILITY: dict = {
    "atr_pct":        lambda r: (_get(r, "atr_at_t") / _price(r)) if (_get(r, "atr_at_t") and _price(r)) else None,
    "atr_14":         lambda r: _get(r, "context", "trend_atr_14"),
    "india_vix":      lambda r: _get(r, "context", "india_vix_close"),
    "nifty_atr_14":   lambda r: _get(r, "context", "regime_nifty_atr_14"),
}

B2_PRICE_SIZE: dict = {
    # §6: price level is NOT economic cheapness, and is not labelled as such anywhere here.
    "log_price":      lambda r: _log(_price(r)),
}

B3_LIQUIDITY: dict = {
    # §7: the primary measure is RUPEE TURNOVER, not share volume -- 1M shares at Rs10 is not
    # 1M shares at Rs1,000.
    "log_adv_inr":    lambda r: _log(_get(r, "liquidity", "adv_inr_at_t")),
    "relative_volume": lambda r: _get(r, "relative_volume_at_t"),
    "participation":  lambda r: _get(r, "liquidity", "participation_ratio"),
}

B4_MARKET_REGIME: dict = {
    "breadth_ad_ratio":     lambda r: _get(r, "context", "breadth_advance_decline_ratio"),
    "breadth_above_sma50":  lambda r: _get(r, "context", "breadth_pct_above_sma50"),
    "breadth_above_sma200": lambda r: _get(r, "context", "breadth_pct_above_sma200"),
    "breadth_new_highs":    lambda r: _get(r, "context", "breadth_new_52w_highs"),
    "breadth_new_lows":     lambda r: _get(r, "context", "breadth_new_52w_lows"),
    "nifty_adx_14":         lambda r: _get(r, "context", "market_trend_class_adx_14"),
    "nifty_slope":          lambda r: _get(r, "context", "market_trend_class_slope_pct_per_day"),
    "nifty_dist_sma200":    lambda r: _ratio(_get(r, "context", "regime_close"),
                                             _get(r, "context", "regime_sma_200")),
    "nifty_sma200_slope":   lambda r: _get(r, "context", "regime_sma_200_slope"),
}

B5_TECHNICAL: dict = {
    "adx_14":         lambda r: _get(r, "context", "trend_adx_14"),
    "rs_5":           lambda r: _get(r, "context", "rs_5"),
    "rs_20":          lambda r: _get(r, "context", "rs_20"),
    "rs_50":          lambda r: _get(r, "context", "rs_50"),
    "rs_100":         lambda r: _get(r, "context", "rs_100"),
    "dist_sma_20":    lambda r: _ratio(_get(r, "context", "trend_close"), _get(r, "context", "trend_sma_20")),
    "dist_sma_50":    lambda r: _ratio(_get(r, "context", "trend_close"), _get(r, "context", "trend_sma_50")),
    "dist_sma_200":   lambda r: _ratio(_get(r, "context", "trend_close"), _get(r, "context", "trend_sma_200")),
    "dist_ema_20":    lambda r: _ratio(_get(r, "context", "trend_close"), _get(r, "context", "trend_ema_20")),
    "dist_ema_50":    lambda r: _ratio(_get(r, "context", "trend_close"), _get(r, "context", "trend_ema_50")),
    "sma_20_slope":   lambda r: _get(r, "context", "trend_sma_20_slope"),
    "sma_50_slope":   lambda r: _get(r, "context", "trend_sma_50_slope"),
    "sma_200_slope":  lambda r: _get(r, "context", "trend_sma_200_slope"),
    "stock_slope":    lambda r: _get(r, "context", "trend_class_slope_pct_per_day"),
}

#: §5-9 features this codebase does not compute. Listed, not silently dropped: a rung missing half
#: its specification is a WEAKER control than it looks, which biases the ladder toward finding
#: pattern value that is really unmodelled baseline value.
MISSING: dict = {
    "B1": ["HV10", "HV20", "HV60", "realised_vol_20d", "range_10d", "range_20d",
           "recent_absolute_returns"],
    "B2": ["market_cap", "price_bucket (derivable, not yet defined)"],
    "B3": ["turnover_20d_median", "volume_20d_median", "bid_ask_spread", "free_float_mcap",
           "turnover_over_mcap"],
    "B4": ["nifty_return_1d", "nifty_return_5d", "nifty_return_20d",
           "SECTOR: return 1d/5d/20d, relative strength, trend, volatility — the whole sector "
           "rung is absent from the model path (PRD §A1); 14 sector CSVs and "
           "context.build_sector_index() exist but nothing wires them to a row"],
    "B5": ["RSI14", "ROC5", "ROC10", "ROC20", "MACD_histogram",
           "distance_20d_high", "distance_20d_low", "distance_52w_high", "distance_52w_low",
           "OBV_slope", "CMF20", "RS_vs_sector"],
}

#: §A2: a bare calendar-month lookup scored 0.715 -- higher than ATR, price or liquidity -- with no
#: stock information at all. A ladder without a time rung lets a model absorb that and report it as
#: chart skill, so it is carried explicitly rather than left for the pattern block to soak up.
B4_TIME: dict = {
    "month_index": lambda r: (lambda d: (int(d[:4]) * 12 + int(d[5:7])) if d and len(d) >= 7 else None)(
        _get(r, "signal_date") or ""),
}

RUNGS: list = [
    ("B0", {}),
    ("B1", B1_VOLATILITY),
    ("B2", B2_PRICE_SIZE),
    ("B3", B3_LIQUIDITY),
    ("B4", {**B4_MARKET_REGIME, **B4_TIME}),
    ("B5", B5_TECHNICAL),
]


def cumulative_features(upto: str) -> dict:
    """Every feature in rungs B0..`upto`, inclusive. Each rung is a strict SUPERSET of the last --
    that is what makes the increment interpretable rather than a comparison of two unrelated
    models."""
    out: dict = {}
    for name, feats in RUNGS:
        out.update(feats)
        if name == upto:
            return out
    raise ValueError(f"unknown rung {upto!r}; expected one of {[n for n, _ in RUNGS]}")


def extract(row: Mapping, features: Mapping[str, Callable]) -> dict:
    return {name: fn(row) for name, fn in features.items()}
