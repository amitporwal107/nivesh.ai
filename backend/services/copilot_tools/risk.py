"""Risk analytics tools for the Nivesh Copilot.

TASK-039: Risk suitability — compare user risk profile vs portfolio beta/volatility/sector.
TASK-040: Portfolio VaR — parametric VaR using volatility_20d from DAAS stock features.

Functions:
  get_risk_suitability(user_id)               → RiskResult
  get_portfolio_var(user_id, confidence=0.95) → RiskResult
"""
from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Z-scores for parametric VaR ──────────────────────────────────────────────
_Z = {0.95: 1.645, 0.99: 2.326}

# ── Risk band → acceptable portfolio metrics ──────────────────────────────────
_PROFILE_BOUNDS: Dict[str, Dict[str, float]] = {
    "conservative": {"max_beta": 0.7,  "max_small_mid_pct": 20.0, "max_equity_pct": 50.0},
    "moderate":     {"max_beta": 1.1,  "max_small_mid_pct": 40.0, "max_equity_pct": 75.0},
    "aggressive":   {"max_beta": 1.5,  "max_small_mid_pct": 70.0, "max_equity_pct": 100.0},
}

# Annualised volatility → risk rating thresholds (daily vol × √252)
_VAR_RATING_THRESHOLDS = [
    (0.08, "LOW"),
    (0.15, "MEDIUM"),
    (0.22, "HIGH"),
]


@dataclass
class RiskResult:
    ok: bool
    summary: str
    risk_rating: str = "UNKNOWN"
    risk_score_0_to_10: float = 0.0
    user_profile_category: str = "moderate"
    misalignment: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def as_llm_context(self) -> str:
        parts = [f"risk_rating={self.risk_rating}", f"risk_score={self.risk_score_0_to_10:.1f}/10"]
        if self.misalignment:
            parts.append("misalignment: " + "; ".join(self.misalignment))
        if self.data:
            for k, v in self.data.items():
                if k not in ("rows",):
                    parts.append(f"{k}={v}")
        return self.summary + " | " + ", ".join(parts)


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _load_holdings(user_id: str) -> List[Dict[str, Any]]:
    from deps import db
    raw: List[Dict[str, Any]] = []
    async for h in db.holdings.find({"user_id": user_id}, {"_id": 0}):
        raw.append(h)
    if not raw:
        async for h in db.portfolio_holdings.find({"user_id": user_id}, {"_id": 0}):
            raw.append(h)
    return raw


async def _load_user_risk_profile(user_id: str) -> Dict[str, Any]:
    """Fetch user risk profile from DB. Returns default moderate profile if not found."""
    try:
        from deps import db
        profile = await db.user_profiles.find_one(
            {"user_id": user_id}, {"_id": 0, "risk_profile": 1}
        )
        if profile and profile.get("risk_profile"):
            return profile["risk_profile"]
    except Exception as exc:
        logger.debug("could not load risk profile for %s: %s", user_id, exc)
    return {"category": "moderate", "score": 50, "loss_tolerance_pct": 15.0, "horizon_years": 5}


# ── DAAS feature fetch (with concurrency limit) ───────────────────────────────

async def _fetch_volatilities(symbols: List[str]) -> Dict[str, Optional[float]]:
    """Fetch volatility_20d for each symbol from DAAS. Returns symbol → vol or None."""
    from services.copilot_tools.daas_client import get_stock_features_latest, DaasError

    sem = asyncio.Semaphore(8)

    async def _one(sym: str) -> tuple[str, Optional[float]]:
        async with sem:
            try:
                feat = await get_stock_features_latest(sym)
                if feat and feat.get("volatility_20d") is not None:
                    return sym, float(feat["volatility_20d"])
            except DaasError:
                pass
        return sym, None

    results = await asyncio.gather(*[_one(s) for s in symbols])
    return dict(results)


# ── TASK-039: Risk Suitability ────────────────────────────────────────────────

async def get_risk_suitability(user_id: str) -> RiskResult:
    """Compare the user's stored risk profile against portfolio characteristics.

    Looks at:
    - Equity allocation % vs profile's max_equity_pct
    - Small/mid cap exposure vs profile's max_small_mid_pct
    - Weighted portfolio beta (using volatility_20d as beta proxy for MFs)
    Returns a risk rating (LOW/MEDIUM/HIGH/VERY HIGH) and misalignment list.
    """
    try:
        holdings = await _load_holdings(user_id)
    except Exception as exc:
        return RiskResult(ok=False, summary="Could not load holdings", error=str(exc))

    if not holdings:
        return RiskResult(ok=False, summary="No holdings found for risk assessment", error="no_holdings")

    profile = await _load_user_risk_profile(user_id)
    category = profile.get("category", "moderate")
    bounds = _PROFILE_BOUNDS.get(category, _PROFILE_BOUNDS["moderate"])

    # ── Compute portfolio-level metrics from holdings ─────────────────────────
    total_value = 0.0
    equity_value = 0.0
    small_mid_value = 0.0
    sector_buckets: Dict[str, float] = {}

    rows: List[Dict[str, Any]] = []

    for h in holdings:
        price = float(h.get("current_price") or h.get("buy_price") or 0)
        qty = float(h.get("quantity") or 0)
        value = price * qty
        total_value += value

        asset_type = str(h.get("asset_type", "")).upper()
        sector = h.get("sector") or "Other"
        eq_pct = h.get("equity_allocation_pct")  # for MFs

        # Classify as equity
        is_equity = asset_type in ("STOCK", "ETF") or (
            asset_type == "MF" and eq_pct is not None and float(eq_pct) >= 65.0
        )
        if is_equity:
            equity_value += value

        # Small/mid cap proxy via sector keyword
        name_lower = (h.get("name") or "").lower()
        if any(kw in name_lower for kw in ("small cap", "smallcap", "mid cap", "midcap",
                                            "small & mid", "small and mid")):
            small_mid_value += value

        # Sector concentration
        if asset_type == "STOCK":
            bucket = sector_buckets.setdefault(sector, 0.0)
            sector_buckets[sector] = bucket + value

        rows.append({
            "name": h.get("name", ""),
            "asset_type": asset_type,
            "value": round(value, 2),
            "equity": is_equity,
        })

    equity_pct = (equity_value / total_value * 100) if total_value > 0 else 0.0
    small_mid_pct = (small_mid_value / total_value * 100) if total_value > 0 else 0.0

    top_sector = max(sector_buckets, key=sector_buckets.get) if sector_buckets else None
    top_sector_pct = (
        sector_buckets[top_sector] / total_value * 100 if top_sector and total_value > 0 else 0.0
    )

    # ── Fetch DAAS volatility for stocks ─────────────────────────────────────
    stock_symbols = [
        h.get("symbol") or h.get("name", "")
        for h in holdings
        if str(h.get("asset_type", "")).upper() == "STOCK" and h.get("symbol")
    ]
    vol_map: Dict[str, Optional[float]] = {}
    if stock_symbols:
        try:
            vol_map = await _fetch_volatilities(stock_symbols)
        except Exception:
            pass

    # Weighted average beta (daily vol × 252^0.5 / 0.16 as market proxy)
    weighted_beta_num = 0.0
    weighted_beta_den = 0.0
    for h in holdings:
        sym = h.get("symbol")
        if not sym:
            continue
        vol = vol_map.get(sym)
        if vol is None:
            continue
        price = float(h.get("current_price") or 0)
        qty = float(h.get("quantity") or 0)
        val = price * qty
        annual_vol = vol * math.sqrt(252)
        beta_proxy = annual_vol / 0.16  # market σ ≈ 16%
        weighted_beta_num += beta_proxy * val
        weighted_beta_den += val

    portfolio_beta = (weighted_beta_num / weighted_beta_den) if weighted_beta_den > 0 else None

    # ── Detect misalignments ──────────────────────────────────────────────────
    misalignment: List[str] = []

    if equity_pct > bounds["max_equity_pct"]:
        misalignment.append(
            f"Equity allocation {equity_pct:.0f}% exceeds {category} limit {bounds['max_equity_pct']:.0f}%"
        )
    if small_mid_pct > bounds["max_small_mid_pct"]:
        misalignment.append(
            f"Small/mid-cap exposure {small_mid_pct:.0f}% exceeds {category} limit {bounds['max_small_mid_pct']:.0f}%"
        )
    if portfolio_beta is not None and portfolio_beta > bounds["max_beta"]:
        misalignment.append(
            f"Portfolio beta {portfolio_beta:.2f} exceeds {category} limit {bounds['max_beta']:.1f}"
        )
    if top_sector_pct > 35.0:
        misalignment.append(
            f"Sector concentration in {top_sector}: {top_sector_pct:.0f}% of equity"
        )

    # ── Risk rating ───────────────────────────────────────────────────────────
    score = 5.0  # base
    score += min(3.0, equity_pct / 33.3)  # equity exposure → +0 to +3
    score -= min(2.0, len(misalignment) * 0.75)  # each misalignment → penalty

    if portfolio_beta is not None:
        if portfolio_beta > 1.3:
            score = min(10.0, score + 1.5)
        elif portfolio_beta < 0.7:
            score = max(0.0, score - 1.0)

    score = round(max(0.0, min(10.0, score)), 2)

    ann_vol_proxy = equity_pct / 100 * 0.18 + (1 - equity_pct / 100) * 0.04
    if ann_vol_proxy < 0.08:
        rating = "LOW"
    elif ann_vol_proxy < 0.15:
        rating = "MEDIUM"
    elif ann_vol_proxy < 0.22:
        rating = "HIGH"
    else:
        rating = "VERY HIGH"

    # Override upward when strongly misaligned
    if len(misalignment) >= 2 and rating in ("LOW", "MEDIUM"):
        rating = "HIGH"

    summary = (
        f"Risk rating: {rating} (score {score:.1f}/10). "
        f"Equity {equity_pct:.0f}%, Small/mid {small_mid_pct:.0f}%. "
        f"User profile: {category}. "
        + (f"{len(misalignment)} misalignment(s) detected." if misalignment else "Portfolio aligned with risk profile.")
    )

    return RiskResult(
        ok=True,
        summary=summary,
        risk_rating=rating,
        risk_score_0_to_10=score,
        user_profile_category=category,
        misalignment=misalignment,
        data={
            "equity_pct": round(equity_pct, 1),
            "small_mid_pct": round(small_mid_pct, 1),
            "portfolio_beta": round(portfolio_beta, 3) if portfolio_beta is not None else None,
            "top_sector": top_sector,
            "top_sector_pct": round(top_sector_pct, 1),
            "total_portfolio_value": round(total_value, 2),
            "user_profile_score": profile.get("score", 50),
            "loss_tolerance_pct": profile.get("loss_tolerance_pct", 15.0),
            "horizon_years": profile.get("horizon_years", 5),
            "misalignment_count": len(misalignment),
        },
        rows=rows,
        error=None,
    )


# ── TASK-040: Portfolio VaR ───────────────────────────────────────────────────

async def get_portfolio_var(
    user_id: str,
    confidence: float = 0.95,
    holding_period_days: int = 1,
) -> RiskResult:
    """Compute parametric Value at Risk for the portfolio.

    Method: weighted portfolio daily volatility from stock_features_daily.volatility_20d.
    VaR = portfolio_value × portfolio_vol × z × √holding_period

    For MF holdings without a symbol, we use equity_allocation_pct to proxy
    equity risk at 18% annual vol and debt at 4% annual vol, converted to daily.

    Returns VaR at the requested confidence level plus 10-day VaR at both
    95% and 99% in the data dict.
    """
    try:
        holdings = await _load_holdings(user_id)
    except Exception as exc:
        return RiskResult(ok=False, summary="Could not load holdings for VaR", error=str(exc))

    if not holdings:
        return RiskResult(ok=False, summary="No holdings found for VaR", error="no_holdings")

    # ── Fetch volatilities for stock/ETF holdings ─────────────────────────────
    stock_holdings = [
        h for h in holdings
        if str(h.get("asset_type", "")).upper() in ("STOCK", "ETF") and h.get("symbol")
    ]
    symbols = [h["symbol"] for h in stock_holdings]
    vol_map: Dict[str, Optional[float]] = {}
    if symbols:
        try:
            vol_map = await _fetch_volatilities(symbols)
        except Exception as exc:
            logger.warning("VaR: could not fetch volatilities: %s", exc)

    # ── Build position-level vol × weight ─────────────────────────────────────
    total_value = 0.0
    position_rows: List[Dict[str, Any]] = []

    for h in holdings:
        price = float(h.get("current_price") or h.get("buy_price") or 0)
        qty = float(h.get("quantity") or 0)
        value = price * qty
        total_value += value

        asset_type = str(h.get("asset_type", "")).upper()
        sym = h.get("symbol")

        if asset_type in ("STOCK", "ETF") and sym and sym in vol_map and vol_map[sym] is not None:
            daily_vol = float(vol_map[sym])
        elif asset_type == "MF":
            eq_pct = float(h.get("equity_allocation_pct") or 0.0) / 100.0
            # Blend: equity daily vol ≈ 18%/√252, debt daily vol ≈ 4%/√252
            daily_vol = eq_pct * (0.18 / math.sqrt(252)) + (1 - eq_pct) * (0.04 / math.sqrt(252))
        elif asset_type in ("BOND", "DEBT"):
            daily_vol = 0.04 / math.sqrt(252)
        elif asset_type == "GOLD":
            daily_vol = 0.10 / math.sqrt(252)
        else:
            # Fallback: moderate equity assumption
            daily_vol = 0.15 / math.sqrt(252)

        position_rows.append({
            "name": h.get("name", sym or ""),
            "asset_type": asset_type,
            "value": round(value, 2),
            "daily_vol": round(daily_vol, 6),
        })

    if total_value == 0:
        return RiskResult(ok=False, summary="Holdings have zero value", error="zero_value")

    # ── Weighted portfolio vol (assume uncorrelated positions as conservative approx) ──
    # σ_p = sqrt( Σ (w_i × σ_i)^2 )  with correlation = 0 → lower bound
    # For a more realistic estimate we use simple weighted sum (correlation = 1)
    # which gives an upper bound and is more prudent for risk management.
    weighted_vol_sum = sum(
        (row["value"] / total_value) * row["daily_vol"]
        for row in position_rows
    )

    z = _Z.get(confidence, 1.645)
    var_1d = total_value * weighted_vol_sum * z
    var_10d = var_1d * math.sqrt(10)
    var_1d_99 = total_value * weighted_vol_sum * _Z[0.99]
    var_10d_99 = var_1d_99 * math.sqrt(10)

    annual_vol = weighted_vol_sum * math.sqrt(252)
    if annual_vol < 0.08:
        rating = "LOW"
    elif annual_vol < 0.15:
        rating = "MEDIUM"
    elif annual_vol < 0.22:
        rating = "HIGH"
    else:
        rating = "VERY HIGH"

    conf_pct = int(confidence * 100)
    summary = (
        f"1-day {conf_pct}% VaR: ₹{var_1d:,.0f} | 10-day {conf_pct}% VaR: ₹{var_10d:,.0f}. "
        f"Portfolio vol (annual): {annual_vol*100:.1f}%. Risk rating: {rating}."
    )

    return RiskResult(
        ok=True,
        summary=summary,
        risk_rating=rating,
        risk_score_0_to_10=round(min(10.0, annual_vol / 0.03), 2),  # 30% vol → 10
        data={
            "var_1d_95_rs": round(var_1d if confidence == 0.95 else total_value * weighted_vol_sum * _Z[0.95], 2),
            "var_1d_99_rs": round(var_1d_99, 2),
            "var_10d_95_rs": round(var_10d if confidence == 0.95 else var_1d * math.sqrt(10), 2),
            "var_10d_99_rs": round(var_10d_99, 2),
            "portfolio_daily_vol": round(weighted_vol_sum, 6),
            "portfolio_annual_vol_pct": round(annual_vol * 100, 2),
            "total_portfolio_value_rs": round(total_value, 2),
            "confidence_level": confidence,
            "positions_with_vol_data": sum(1 for r in position_rows if r["daily_vol"] > 0),
        },
        rows=position_rows,
        error=None,
    )
