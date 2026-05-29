"""GET /api/portfolio/composition

Composition Explorer endpoint for the v5 Performance Dashboard.

Returns portfolio breakdown segmented by one of four dimensions:
  asset_class  — Equity / Debt / Hybrid / Gold / International / MF
  sector       — sector name from holdings
  fund         — individual fund / holding name
  group        — conglomerate parent (HDFC Group, Tata Group, etc.)

Each segment carries weight_pct, current_value, invested, pnl_pct,
and an optional xirr_pct. Concentration breach flags are included
so the frontend can render warning chips without a second call.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Optional

from fastapi import APIRouter, Request

from deps import db, get_current_user
from services.portfolio_concentration import _group_for  # reuse existing group logic

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/portfolio", tags=["portfolio-composition"])

# Concentration thresholds (matches portfolio_remediation._CAP)
_THRESHOLDS: dict[str, float] = {
    "asset_class": 80.0,   # not usually breached; included for completeness
    "sector": 35.0,
    "fund": 10.0,
    "group": 15.0,
}

_VALID_DIMENSIONS = {"asset_class", "sector", "fund", "group"}
_VALID_METRICS = {"weight", "invested", "current"}


def _asset_class_for(asset_type: str, category: str) -> str:
    at = (asset_type or "").lower()
    cat = (category or "").lower()
    if at in {"equity", "stock"}:
        return "Equity"
    if at == "gold" or at == "sgb":
        return "Gold"
    if at == "debt":
        return "Debt"
    if at == "cash":
        return "Cash"
    # MF/ETF — refine by category
    if any(k in cat for k in {"liquid", "debt", "bond", "gilt", "corporate",
                               "short term", "low duration", "overnight", "money market"}):
        return "Debt"
    if any(k in cat for k in {"hybrid", "balanced", "multi asset", "arbitrage"}):
        return "Hybrid"
    if "gold" in cat or "commodity" in cat:
        return "Gold"
    if any(k in cat for k in {"international", "global", "overseas", "us equity", "nasdaq"}):
        return "International"
    return "Equity"


@router.get("/composition")
async def get_composition(
    request: Request,
    dimension: str = "asset_class",
    metric: str = "weight",
    period: Optional[str] = None,   # reserved for future period-scoped XIRR
) -> dict[str, Any]:
    """Portfolio composition breakdown for the Composition Explorer.

    Query params:
      dimension: asset_class | sector | fund | group  (default: asset_class)
      metric:    weight | invested | current           (default: weight)
      period:    1M|3M|6M|1Y|3Y|inception              (reserved; echoed back)
    """
    if dimension not in _VALID_DIMENSIONS:
        from fastapi import HTTPException
        raise HTTPException(status_code=422,
                            detail=f"dimension must be one of {sorted(_VALID_DIMENSIONS)}")
    if metric not in _VALID_METRICS:
        from fastapi import HTTPException
        raise HTTPException(status_code=422,
                            detail=f"metric must be one of {sorted(_VALID_METRICS)}")

    user = await get_current_user(request)
    user_id = user["user_id"]

    holdings: list[dict] = await db.holdings.find(
        {"user_id": user_id},
        {"_id": 0, "name": 1, "ticker": 1, "asset_type": 1, "sector": 1,
         "category": 1, "amc_name": 1, "quantity": 1, "buy_price": 1,
         "current_price": 1, "amfi_matched": 1},
    ).to_list(2000)

    if not holdings:
        return _empty_response(dimension, metric, period)

    # Compute per-holding values
    total_current = 0.0
    total_invested = 0.0
    rows: list[dict] = []
    for h in holdings:
        qty = float(h.get("quantity") or 0)
        bp = float(h.get("buy_price") or 0)
        cp = float(h.get("current_price") or 0)
        current = qty * cp
        invested = qty * bp if bp > 0 else 0.0
        total_current += current
        if bp > 0:
            total_invested += invested

        at = (h.get("asset_type") or "").lower()
        cat = h.get("category") or ""
        name = h.get("name") or "Unknown"

        rows.append({
            "name": name,
            "asset_class": _asset_class_for(at, cat),
            "sector": h.get("sector") or "Other",
            "group": _group_for(name) or "Other",
            "amc": h.get("amc_name") or "Other",
            "current": current,
            "invested": invested,
            "amfi_matched": bool(h.get("amfi_matched", False)),
        })

    if total_current == 0:
        return _empty_response(dimension, metric, period)

    # Bucket by dimension
    buckets: dict[str, dict[str, float]] = defaultdict(lambda: {"current": 0.0, "invested": 0.0})
    for r in rows:
        key = _dimension_key(r, dimension)
        buckets[key]["current"] += r["current"]
        buckets[key]["invested"] += r["invested"]

    # Build segments
    threshold = _THRESHOLDS.get(dimension, 35.0)
    segments = []
    for seg_name, vals in buckets.items():
        weight_pct = vals["current"] / total_current * 100 if total_current > 0 else 0.0
        inv = vals["invested"]
        pnl_pct = ((vals["current"] - inv) / inv * 100) if inv > 0 else None

        # Metric basis value (what the chart sizes/proportions use)
        if metric == "weight":
            metric_value = round(weight_pct, 2)
        elif metric == "invested":
            metric_value = round(inv, 2)
        else:  # current
            metric_value = round(vals["current"], 2)

        segments.append({
            "name": seg_name,
            "weight_pct": round(weight_pct, 2),
            "current_value": round(vals["current"], 2),
            "invested": round(inv, 2) if inv > 0 else None,
            "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
            "metric_value": metric_value,
            "breach": weight_pct >= threshold,
            "breach_threshold": threshold,
        })

    # Sort by current value descending
    segments.sort(key=lambda s: s["current_value"], reverse=True)

    # Concentration breach summary
    breaches = [
        {"segment": s["name"], "weight_pct": s["weight_pct"], "threshold": threshold}
        for s in segments if s["breach"]
    ]

    return {
        "dimension": dimension,
        "metric": metric,
        "period": period,
        "segments": segments,
        "totals": {
            "current_value": round(total_current, 2),
            "invested": round(total_invested, 2) if total_invested > 0 else None,
        },
        "concentration_breaches": breaches,
        "threshold": threshold,
    }


def _dimension_key(row: dict, dimension: str) -> str:
    if dimension == "asset_class":
        return row["asset_class"]
    if dimension == "sector":
        return row["sector"] or "Other"
    if dimension == "fund":
        return row["name"]
    if dimension == "group":
        return row["group"] or "Other"
    return "Other"


def _empty_response(dimension: str, metric: str, period: Optional[str]) -> dict:
    return {
        "dimension": dimension,
        "metric": metric,
        "period": period,
        "segments": [],
        "totals": {"current_value": 0.0, "invested": None},
        "concentration_breaches": [],
        "threshold": _THRESHOLDS.get(dimension, 35.0),
    }
