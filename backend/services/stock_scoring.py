"""V3 Stock Scoring Engine — direct equity composite scores.

Implements the refined V3 framework (user-approved Feb 2026) producing 4
orthogonal composite scores per stock:

  Quality  — long-term strength (non-market dependent)
  Health   — current trajectory (momentum + stability)
  Exit     — sell-signal (portfolio-aware friction)
  Add      — buy/top-up signal (portfolio-aware gap fit)

Weights are editable via admin UI (MongoDB `system_config.v3_stock_weights`).
Scoring is pure-Python, deterministic, unit-testable. Each primitive is
normalised to 0-100 via a linear band before being weighted.

DESIGN PRINCIPLES (per user spec):
  - PE band OUT of Quality (valuation ≠ quality).
  - Beta OUT of Health (poor retail signal).
  - Dividend reduced (growth investors don't care).
  - Add becomes portfolio-driven, not stock-driven.
  - Each score has minimal cross-dependency on the others.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Optional

# ── Default weight profiles (user's refined V3 framework) ──────────────
DEFAULT_STOCK_WEIGHTS: Dict[str, Dict[str, int]] = {
    "quality": {
        "roe": 25,
        "debt_to_equity": 15,
        "eps_growth_3y": 20,
        "promoter_holding": 10,
        "market_cap_stability": 10,
        "earnings_consistency": 20,
    },
    "health": {
        "revenue_growth": 25,
        "profit_margin_trend": 20,
        "debt_trend": 15,
        "earnings_surprise": 15,
        "volatility": 10,
        "dividend_yield": 5,
        # sum: 90 → 10% reserved for padding / future drift
        "reserved": 10,
    },
    "exit": {
        "pe_overvaluation": 25,
        "earnings_decline": 25,
        "quality_deterioration": 20,
        "debt_spike": 10,
        "liquidity_risk": 10,
        "tax_impact": 10,
    },
    "add": {
        "sector_gap": 30,
        "low_overlap": 25,
        "relative_valuation": 15,
        "quality": 15,
        "momentum": 10,
        "dividend": 5,
    },
}

_weights_cache: Dict[str, Dict[str, int]] = deepcopy(DEFAULT_STOCK_WEIGHTS)
CONFIG_DOC_ID = "v3_stock_weights"
ENGINE_VERSION = "v3.stock.1"


# ── Primitive normalisers (0-100, higher = better) ────────────────────
def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _band(value: Optional[float], low: float, high: float,
          *, good_is_high: bool = True) -> float:
    """Linear-map `value` to 0-100 given `low`→0 and `high`→100 bands.
    If `good_is_high=False` the mapping is inverted (lower input = higher score).
    Missing values → neutral 50."""
    if value is None:
        return 50.0
    if high == low:
        return 50.0
    pct = (value - low) / (high - low)
    score = pct * 100.0 if good_is_high else (1 - pct) * 100.0
    return _clamp(score)


def norm_roe(roe_pct: Optional[float]) -> float:
    # India context: ROE < 10% weak, ≥ 22% world-class
    return _band(roe_pct, low=10.0, high=22.0, good_is_high=True)


def norm_debt_to_equity(de: Optional[float]) -> float:
    # Lower = better. D/E > 1.5 penalty, ≤ 0.3 ideal
    return _band(de, low=0.3, high=1.5, good_is_high=False)


def norm_eps_growth(cagr_pct: Optional[float]) -> float:
    # 3y EPS CAGR: <5% weak, ≥20% strong
    return _band(cagr_pct, low=5.0, high=20.0, good_is_high=True)


def norm_promoter_holding(pct: Optional[float]) -> float:
    # <35% weak governance, ≥60% strong
    return _band(pct, low=35.0, high=60.0, good_is_high=True)


def norm_market_cap_stability(cap_bucket: Optional[str]) -> float:
    return {"large": 90.0, "mid": 60.0, "small": 40.0}.get(
        (cap_bucket or "unknown").lower(), 50.0,
    )


def norm_earnings_consistency(score_0_100: Optional[float]) -> float:
    if score_0_100 is None:
        return 50.0
    return _clamp(float(score_0_100))


def norm_revenue_growth(cagr_pct: Optional[float]) -> float:
    return _band(cagr_pct, low=5.0, high=25.0, good_is_high=True)


def norm_profit_margin_trend(pct_delta: Optional[float]) -> float:
    # YoY change in PM. -5pp → 0, +5pp → 100
    return _band(pct_delta, low=-5.0, high=5.0, good_is_high=True)


def norm_debt_trend(pct_delta: Optional[float]) -> float:
    # YoY debt change; reducing debt = better. -20% → 100, +20% → 0
    return _band(pct_delta, low=-20.0, high=20.0, good_is_high=False)


def norm_earnings_surprise(pct: Optional[float]) -> float:
    # -10% → 0, +10% → 100
    return _band(pct, low=-10.0, high=10.0, good_is_high=True)


def norm_volatility(vol_1y_pct: Optional[float]) -> float:
    # Lower vol = better. 10% → 100, 45% → 0
    return _band(vol_1y_pct, low=10.0, high=45.0, good_is_high=False)


def norm_dividend_yield(dy_pct: Optional[float]) -> float:
    # 0 → 40 (not penalising growth stocks), 4% → 100
    if dy_pct is None:
        return 50.0
    return _clamp(40.0 + float(dy_pct) * 15.0)


def norm_pe_overvaluation(over_pct: Optional[float]) -> float:
    # PE vs historical median: 0% over → 0 exit signal, +50% → 100
    return _band(over_pct, low=0.0, high=50.0, good_is_high=True)


def norm_earnings_decline(flag_or_pct: Any) -> float:
    # Flag (bool) → 100 if declining else 0. Or numeric YoY decline: -20% → 100
    if isinstance(flag_or_pct, bool):
        return 100.0 if flag_or_pct else 0.0
    if flag_or_pct is None:
        return 30.0
    return _band(flag_or_pct, low=-20.0, high=0.0, good_is_high=False)


def norm_quality_deterioration(
    current_q: Optional[float], prior_q: Optional[float],
) -> float:
    # Drop ≥ 15 points → 100 exit signal. No drop → 0.
    if current_q is None or prior_q is None:
        return 30.0
    drop = max(0.0, float(prior_q) - float(current_q))
    return _band(drop, low=0.0, high=15.0, good_is_high=True)


def norm_debt_spike(flag_or_pct: Any) -> float:
    if isinstance(flag_or_pct, bool):
        return 100.0 if flag_or_pct else 0.0
    if flag_or_pct is None:
        return 20.0
    # 20% YoY debt rise → 100 exit
    return _band(flag_or_pct, low=0.0, high=20.0, good_is_high=True)


def norm_liquidity_risk(liquidity_score: Optional[float]) -> float:
    # Higher liquidity = lower exit. Invert.
    if liquidity_score is None:
        return 50.0
    return _clamp(100.0 - float(liquidity_score))


def norm_tax_impact(tax_ratio: Optional[float], is_stcg: bool = False) -> float:
    # tax_ratio = tax_liability / exit_value (0-1). STCG adds flat 20 penalty.
    base = _band((tax_ratio or 0) * 100, low=0.0, high=30.0, good_is_high=True)
    if is_stcg:
        base = min(100.0, base + 20.0)
    return base


def norm_sector_gap(gap_pct: Optional[float]) -> float:
    # Portfolio-aware: % under-allocated vs ideal. 0pp gap → 0, 15pp → 100
    return _band(gap_pct, low=0.0, high=15.0, good_is_high=True)


def norm_low_overlap(overlap_pct: Optional[float]) -> float:
    # Already-owned stock has high overlap. Low overlap = good Add signal.
    if overlap_pct is None:
        return 70.0
    return _clamp(100.0 - float(overlap_pct))


def norm_relative_valuation(pe_vs_peer_ratio: Optional[float]) -> float:
    # 0.7 (30% cheaper than sector) → 100. 1.3 (30% premium) → 0.
    if pe_vs_peer_ratio is None:
        return 50.0
    return _band(pe_vs_peer_ratio, low=0.7, high=1.3, good_is_high=False)


def norm_momentum(momentum_score: Optional[float]) -> float:
    if momentum_score is None:
        return 50.0
    return _clamp(float(momentum_score))


# ── Composite score builders ───────────────────────────────────────────
def _weighted_avg(components: Dict[str, float], weights: Dict[str, int]) -> Dict[str, Any]:
    """Weighted average of `components` using `weights`. Skips `reserved`
    weight slots. Normalises so sum of used weights = 100."""
    total_w = 0
    total_val = 0.0
    used = {}
    for k, w in weights.items():
        if k == "reserved":
            continue
        if k not in components:
            continue
        total_w += w
        total_val += components[k] * w
        used[k] = {"value": round(components[k], 2), "weight": w}
    if total_w <= 0:
        return {"score": None, "components": used}
    return {"score": round(total_val / total_w, 2), "components": used}


def compute_quality_score(primitives: Dict[str, Any]) -> Dict[str, Any]:
    comps = {
        "roe": norm_roe(primitives.get("roe_pct")),
        "debt_to_equity": norm_debt_to_equity(primitives.get("debt_to_equity")),
        "eps_growth_3y": norm_eps_growth(primitives.get("eps_growth_3y_cagr_pct")),
        "promoter_holding": norm_promoter_holding(primitives.get("promoter_holding_pct")),
        "market_cap_stability": norm_market_cap_stability(primitives.get("cap_bucket")),
        "earnings_consistency": norm_earnings_consistency(primitives.get("earnings_consistency_score")),
    }
    return _weighted_avg(comps, _weights_cache.get("quality", DEFAULT_STOCK_WEIGHTS["quality"]))


def compute_health_score(primitives: Dict[str, Any]) -> Dict[str, Any]:
    comps = {
        "revenue_growth": norm_revenue_growth(primitives.get("revenue_growth_3y_cagr_pct")),
        "profit_margin_trend": norm_profit_margin_trend(primitives.get("profit_margin_trend_pct")),
        "debt_trend": norm_debt_trend(primitives.get("debt_trend_pct")),
        "earnings_surprise": norm_earnings_surprise(primitives.get("earnings_surprise_pct")),
        "volatility": norm_volatility(primitives.get("volatility_1y_pct")),
        "dividend_yield": norm_dividend_yield(primitives.get("dividend_yield_pct")),
    }
    return _weighted_avg(comps, _weights_cache.get("health", DEFAULT_STOCK_WEIGHTS["health"]))


def compute_exit_score(
    primitives: Dict[str, Any],
    *,
    current_quality: Optional[float] = None,
    prior_quality: Optional[float] = None,
    tax_ratio: Optional[float] = None,
    is_stcg: bool = False,
) -> Dict[str, Any]:
    comps = {
        "pe_overvaluation": norm_pe_overvaluation(primitives.get("pe_overvaluation_pct")),
        "earnings_decline": norm_earnings_decline(primitives.get("earnings_decline_flag")),
        "quality_deterioration": norm_quality_deterioration(current_quality, prior_quality),
        "debt_spike": norm_debt_spike(primitives.get("debt_spike_flag")),
        "liquidity_risk": norm_liquidity_risk(primitives.get("liquidity_score")),
        "tax_impact": norm_tax_impact(tax_ratio, is_stcg),
    }
    return _weighted_avg(comps, _weights_cache.get("exit", DEFAULT_STOCK_WEIGHTS["exit"]))


def compute_add_score(
    primitives: Dict[str, Any],
    *,
    sector_gap_pct: Optional[float] = None,
    portfolio_overlap_pct: Optional[float] = None,
    quality_score: Optional[float] = None,
    pe_vs_peer_ratio: Optional[float] = None,
) -> Dict[str, Any]:
    comps = {
        "sector_gap": norm_sector_gap(sector_gap_pct),
        "low_overlap": norm_low_overlap(portfolio_overlap_pct),
        "relative_valuation": norm_relative_valuation(pe_vs_peer_ratio),
        "quality": _clamp(float(quality_score)) if quality_score is not None else 50.0,
        "momentum": norm_momentum(primitives.get("momentum_score")),
        "dividend": norm_dividend_yield(primitives.get("dividend_yield_pct")),
    }
    return _weighted_avg(comps, _weights_cache.get("add", DEFAULT_STOCK_WEIGHTS["add"]))


# ── Full per-stock score bundle ────────────────────────────────────────
def score_stock(
    primitives: Dict[str, Any],
    *,
    prior_quality: Optional[float] = None,
    tax_ratio: Optional[float] = None,
    is_stcg: bool = False,
    sector_gap_pct: Optional[float] = None,
    portfolio_overlap_pct: Optional[float] = None,
    pe_vs_peer_ratio: Optional[float] = None,
) -> Dict[str, Any]:
    """Compute all 4 composite scores for a single stock. Returns a bundle
    suitable for persistence in `stock_scores`."""
    q = compute_quality_score(primitives)
    h = compute_health_score(primitives)
    e = compute_exit_score(
        primitives, current_quality=q.get("score"),
        prior_quality=prior_quality, tax_ratio=tax_ratio, is_stcg=is_stcg,
    )
    a = compute_add_score(
        primitives, sector_gap_pct=sector_gap_pct,
        portfolio_overlap_pct=portfolio_overlap_pct,
        quality_score=q.get("score"), pe_vs_peer_ratio=pe_vs_peer_ratio,
    )

    return {
        "quality_score": q.get("score"),
        "health_score": h.get("score"),
        "exit_score": e.get("score"),
        "add_score": a.get("score"),
        "quality_components": q.get("components"),
        "health_components": h.get("components"),
        "exit_components": e.get("components"),
        "add_components": a.get("components"),
        "engine_version": ENGINE_VERSION,
        "recommendation": derive_recommendation(q.get("score"), h.get("score"), e.get("score"), a.get("score")),
    }


def derive_recommendation(
    quality: Optional[float], health: Optional[float],
    exit_: Optional[float], add: Optional[float],
) -> Dict[str, str]:
    """Map composite scores to BUY / HOLD / TRIM / EXIT / REVIEW."""
    if quality is None and health is None:
        return {"action": "REVIEW", "reason": "Insufficient data to score this stock."}
    q, h, e, a = quality or 0, health or 0, exit_ or 0, add or 0
    if e >= 75:
        return {"action": "EXIT", "reason": f"Exit score {e:.0f} (≥75)."}
    if e >= 60:
        return {"action": "TRIM", "reason": f"Elevated exit score {e:.0f}."}
    if a >= 75 and q >= 65:
        return {"action": "BUY", "reason": f"High Add score {a:.0f} with strong Quality {q:.0f}."}
    if q >= 70 and h >= 65:
        return {"action": "HOLD", "reason": f"Quality {q:.0f} + Health {h:.0f} remain healthy."}
    if q < 45 or h < 45:
        return {"action": "REVIEW", "reason": f"Quality {q:.0f} / Health {h:.0f} below threshold."}
    return {"action": "HOLD", "reason": "Scores in neutral band."}


# ── Weights management (parallels services.v3_weights) ────────────────
def get_full_config() -> Dict[str, Dict[str, int]]:
    return deepcopy(_weights_cache)


def get_weights(dimension: str) -> Dict[str, int]:
    return deepcopy(_weights_cache.get(dimension, {}))


def set_weights(dimension: str, weights: Dict[str, int]) -> None:
    _weights_cache[dimension] = {k: int(v) for k, v in weights.items()}


async def hydrate_from_db(db) -> None:
    """Load stock weights from `system_config.v3_stock_weights` Mongo doc."""
    try:
        doc = await db["system_config"].find_one({"_id": CONFIG_DOC_ID})
    except Exception:  # noqa: BLE001
        return
    if not doc:
        return
    weights = doc.get("weights")
    if not isinstance(weights, dict):
        return
    for dim, w_map in weights.items():
        if isinstance(w_map, dict):
            _weights_cache[dim] = {k: int(v) for k, v in w_map.items() if isinstance(v, (int, float))}


async def persist_to_db(db) -> None:
    try:
        await db["system_config"].update_one(
            {"_id": CONFIG_DOC_ID},
            {"$set": {"weights": _weights_cache}},
            upsert=True,
        )
    except Exception:  # noqa: BLE001
        pass
