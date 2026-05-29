"""V3 Risk Analytics endpoint.

Single endpoint: GET /api/portfolio/risk-analytics

Computes portfolio-level risk metrics by:
  1. Loading user's MF + stock holdings from Mongo.
  2. Calling NIDP DAAS V3 primitives in bulk for both asset classes.
  3. Weight-averaging beta_1y, sharpe_1y, volatility_1y across holdings.
  4. Surfacing top risk drivers (high-beta, high-vol, sector concentration).

Distinct from /api/copilot/widgets/risk_suitability (which is a beta-proxy
heuristic on volatility_20d). This one uses the proper V3 primitives —
real beta_1y, real sharpe_1y, real volatility_1y from NIDP's analytics layer.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Request

from deps import db, get_current_user
from services.copilot_tools import daas_client as _daas

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/portfolio", tags=["portfolio-risk"])


def _vol_to_rating(vol_annual: float | None) -> str:
    """Annualised volatility → 4-band rating. Aligned with copilot_tools/risk.py
    bands so the same scale powers both widgets."""
    if vol_annual is None:
        return "UNKNOWN"
    if vol_annual < 0.10:
        return "LOW"
    if vol_annual < 0.18:
        return "MEDIUM"
    if vol_annual < 0.28:
        return "HIGH"
    return "VERY_HIGH"


def _risk_score(vol_annual: float | None) -> float | None:
    """Map annualised vol to 0-10 score (10 = highest risk). Linear in
    [0, 0.40] saturating at 10."""
    if vol_annual is None:
        return None
    return round(min(10.0, max(0.0, (vol_annual / 0.04))), 1)


@router.get("/risk-analytics")
async def get_risk_analytics(request: Request, period: Optional[str] = None) -> dict[str, Any]:
    """Portfolio-level risk metrics powered by NIDP V3 primitives.

    period: optional hint for period-scoped Sharpe/volatility display (1M/3M/6M/1Y/3Y/inception).
    Currently passed through to the response so the frontend can label the Sharpe card correctly;
    the underlying DAAS primitives are rolling-window by nature (sharpe_1y etc.).
    """
    user = await get_current_user(request)
    user_id = user["user_id"]

    holdings: list[dict] = await db.holdings.find(
        {"user_id": user_id},
        {"_id": 0, "name": 1, "ticker": 1, "asset_type": 1,
         "quantity": 1, "current_price": 1, "sector": 1, "amc_name": 1,
         "category": 1, "instrument_id": 1},
    ).to_list(1000)
    if not holdings:
        from services.pi_bridge import pi_holdings_for_user  # noqa: WPS433
        holdings = await pi_holdings_for_user(user_id)

    if not holdings:
        return {
            "empty": True,
            "total_value": 0,
            "risk_score": None, "risk_rating": "UNKNOWN",
            "weighted_beta": None, "weighted_sharpe": None, "weighted_volatility": None,
            "equity_pct": 0, "debt_pct": 0, "gold_pct": 0, "other_pct": 0,
            "risk_drivers": [], "fund_breakdown": [], "stock_breakdown": [],
            "coverage_pct": 0, "data_source": "DAAS",
        }

    # Bucket holdings by asset type
    mf_isins: list[str] = []
    stock_symbols: list[str] = []
    total_value = 0.0
    asset_value = {"equity": 0.0, "debt": 0.0, "gold": 0.0, "other": 0.0}

    for h in holdings:
        qty = float(h.get("quantity") or 0)
        price = float(h.get("current_price") or 0)
        value = qty * price
        total_value += value
        atype = (h.get("asset_type") or "").lower()
        if atype in {"mutual_fund", "etf"}:
            if h.get("ticker"):
                mf_isins.append(h["ticker"])
            cat = (h.get("category") or "").lower()
            if "equity" in cat or "equity" in atype:
                asset_value["equity"] += value
            elif "debt" in cat or "bond" in cat or "liquid" in cat:
                asset_value["debt"] += value
            elif "gold" in cat:
                asset_value["gold"] += value
            else:
                asset_value["other"] += value
        elif atype in {"stock", "equity"}:
            if h.get("ticker"):
                stock_symbols.append(h["ticker"])
            asset_value["equity"] += value
        elif atype == "gold":
            asset_value["gold"] += value
        else:
            asset_value["other"] += value

    # Parallel bulk fetches (both safely degrade to {} on DAAS failure)
    mf_primitives, stock_primitives = {}, {}
    if mf_isins:
        mf_primitives = await _daas.get_v3_mf_primitives_bulk(list(set(mf_isins)))
    if stock_symbols:
        stock_primitives = await _daas.get_v3_stock_primitives_bulk(list(set(stock_symbols)))

    # Weighted aggregates
    beta_num = beta_den = 0.0
    sharpe_num = sharpe_den = 0.0
    vol_num = vol_den = 0.0
    covered_value = 0.0
    fund_breakdown: list[dict] = []
    stock_breakdown: list[dict] = []
    # factor exposure accumulators for bar-chart risk drivers
    smallcap_val = high_beta_val = cyclical_val = 0.0
    _CYCLICAL_KW = {"bank", "nbfc", "finance", "metal", "real estate", "auto", "construct", "oil", "chemical"}

    for h in holdings:
        qty = float(h.get("quantity") or 0)
        price = float(h.get("current_price") or 0)
        value = qty * price
        if value <= 0:
            continue
        atype = (h.get("asset_type") or "").lower()
        prim = None
        if atype in {"mutual_fund", "etf"} and h.get("ticker"):
            prim = mf_primitives.get(h["ticker"])
        elif atype in {"stock", "equity"} and h.get("ticker"):
            prim = stock_primitives.get(h["ticker"])

        # Factor exposure tracking — runs even when prim is missing
        _cat        = ((prim.get("sub_category") or prim.get("category") or "") if prim else "").lower()
        _cap_bucket = ((prim.get("market_cap_bucket") or "") if prim else "").lower()
        _sect       = (h.get("sector") or "").lower()
        # Smallcap: MF sub_category "Small Cap" OR stock market_cap_bucket SMALL/MICRO
        if "small" in _cat or "small" in _cap_bucket or "micro" in _cap_bucket:
            smallcap_val += value
        if any(kw in _sect for kw in _CYCLICAL_KW):
            cyclical_val += value
        if prim and isinstance(prim.get("beta_1y"), (int, float)) and float(prim["beta_1y"]) > 1.3:
            high_beta_val += value

        if not prim:
            continue

        beta = prim.get("beta_1y")
        sharpe = prim.get("sharpe_1y")
        vol = prim.get("volatility_1y") or prim.get("volatility_1y_pct")
        if isinstance(vol, (int, float)) and vol > 5:
            # primitives sometimes store vol as percent (e.g. 18.5 not 0.185)
            vol = float(vol) / 100.0

        has_data = False
        if isinstance(beta, (int, float)):
            beta_num += float(beta) * value
            beta_den += value
            has_data = True
        if isinstance(sharpe, (int, float)):
            sharpe_num += float(sharpe) * value
            sharpe_den += value
            has_data = True
        if isinstance(vol, (int, float)):
            vol_num += float(vol) * value
            vol_den += value
            has_data = True
        if has_data:
            covered_value += value

        row = {
            "name": h.get("name"),
            "ticker": h.get("ticker"),
            "value_rs": round(value, 2),
            "weight_pct": round(100 * value / total_value, 2) if total_value > 0 else 0,
            "beta_1y": float(beta) if isinstance(beta, (int, float)) else None,
            "sharpe_1y": float(sharpe) if isinstance(sharpe, (int, float)) else None,
            "volatility_1y": float(vol) if isinstance(vol, (int, float)) else None,
        }
        if atype in {"mutual_fund", "etf"}:
            row["category"] = prim.get("category") or h.get("category")
            fund_breakdown.append(row)
        else:
            row["sector"] = h.get("sector")
            stock_breakdown.append(row)

    weighted_beta = round(beta_num / beta_den, 3) if beta_den > 0 else None
    weighted_sharpe = round(sharpe_num / sharpe_den, 3) if sharpe_den > 0 else None
    weighted_vol = round(vol_num / vol_den, 4) if vol_den > 0 else None

    # Risk drivers — factor-exposure bars for the v4 risk dashboard.
    # Each entry has a `pct` field so the frontend can render a horizontal bar.
    risk_drivers: list[dict] = []
    if total_value > 0:
        smallcap_pct = round(100 * smallcap_val / total_value, 1)
        high_beta_pct = round(100 * high_beta_val / total_value, 1)
        cyclical_pct  = round(100 * cyclical_val / total_value, 1)
        dg_pct = round(100 * (asset_value["debt"] + asset_value["gold"]) / total_value, 1)

        if smallcap_pct >= 10:
            risk_drivers.append({
                "type": "SMALLCAP_WEIGHT", "label": "Smallcap weight",
                "pct": smallcap_pct,
                "impact": "HIGH" if smallcap_pct > 30 else "MEDIUM",
            })
        if high_beta_pct >= 20:
            risk_drivers.append({
                "type": "HIGH_BETA_NAMES", "label": "High-beta names",
                "pct": high_beta_pct,
                "impact": "HIGH" if high_beta_pct > 40 else "MEDIUM",
            })
        if cyclical_pct >= 25:
            risk_drivers.append({
                "type": "CYCLICAL_SECTORS", "label": "Cyclical sectors",
                "pct": cyclical_pct,
                "impact": "HIGH" if cyclical_pct > 50 else "MEDIUM",
            })
        # Buffer row always shown — a low buffer (high impact) warns; adequate buffer reassures.
        risk_drivers.append({
            "type": "DEBT_GOLD_BUFFER", "label": "Debt + gold buffer",
            "pct": dg_pct,
            "impact": "LOW" if dg_pct >= 15 else ("MEDIUM" if dg_pct >= 5 else "HIGH"),
        })

    # Top 3 highest-vol holdings
    contributors = sorted(
        [r for r in fund_breakdown + stock_breakdown if r["volatility_1y"]],
        key=lambda r: (r["volatility_1y"] or 0) * r["weight_pct"],
        reverse=True,
    )[:3]

    # v4 additions per docs/api-changes.md Modified Endpoint C.3
    # Parametric 1-day VaR at 95% confidence: VaR = value × σ × z(0.95) / √252
    # (z(0.95) = 1.645; σ is annualised; dividing by √252 converts to 1-day)
    var_1d_rs: Optional[float] = None
    var_1d_pct: Optional[float] = None
    var_confidence = 0.95
    if weighted_vol is not None and total_value > 0:
        import math
        sigma_1d = float(weighted_vol) / math.sqrt(252)
        var_1d_pct = round(sigma_1d * 1.645 * 100, 2)
        var_1d_rs = round(total_value * sigma_1d * 1.645, 0)

    # Max drawdown — not yet exposed by NIDP primitives; signal missing
    # via None so the UI can render "—". Future: pull max_drawdown_1y from
    # /v1/intelligence/portfolio/{user_id}/snapshot once available.
    max_drawdown_pct: Optional[float] = None

    return {
        "empty": False,
        "total_value": round(total_value, 2),
        "risk_score": _risk_score(weighted_vol),
        "risk_rating": _vol_to_rating(weighted_vol),
        "weighted_beta": weighted_beta,
        "weighted_sharpe": weighted_sharpe,
        "weighted_volatility": weighted_vol,
        # v4 additions (Modified Endpoint C.3)
        "max_drawdown_pct": max_drawdown_pct,
        "var_1d_rs": var_1d_rs,
        "var_1d_pct": var_1d_pct,
        "portfolio_value_rs": round(total_value, 2),
        "var_confidence": var_confidence,
        # Existing fields unchanged
        "equity_pct": round(100 * asset_value["equity"] / total_value, 1) if total_value > 0 else 0,
        "debt_pct": round(100 * asset_value["debt"] / total_value, 1) if total_value > 0 else 0,
        "gold_pct": round(100 * asset_value["gold"] / total_value, 1) if total_value > 0 else 0,
        "other_pct": round(100 * asset_value["other"] / total_value, 1) if total_value > 0 else 0,
        "risk_drivers": risk_drivers,
        "top_contributors": [
            {"name": r["name"], "weight_pct": r["weight_pct"], "volatility_1y": r["volatility_1y"]}
            for r in contributors
        ],
        "fund_breakdown": sorted(fund_breakdown, key=lambda r: r["weight_pct"], reverse=True)[:10],
        "stock_breakdown": sorted(stock_breakdown, key=lambda r: r["weight_pct"], reverse=True)[:10],
        "coverage_pct": round(100 * covered_value / total_value, 1) if total_value > 0 else 0,
        "data_source": "DAAS",
        "period": period,  # echo back for frontend Sharpe card labelling
    }
