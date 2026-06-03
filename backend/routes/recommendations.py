"""GET /api/recommendations/stocks  — top stock picks via NIDP screening.
GET /api/recommendations/funds   — top fund picks via NIDP scoring.

Per docs/api-changes.md New Endpoints B.13, B.14 (approved 2026-05-24).

Serves screens (mobile + webapp):
  13 Recommendations — stock and fund discovery cards

Both endpoints are NIDP proxies. Nivesh adds:
  - Auth gate (session cookie required)
  - Profile derivation (conservative/balanced/growth from user risk_profile
    when ?profile= is omitted)
  - Compliance footer per SEBI screened-ideas regime

NIDP data sourced from:
  - Stocks: /v1/stocks/scores/ — composite quality/health/exit/add/hold
  - Funds:  /v1/mf/scores/    — composite + sub-scores (returns/cost/consistency)

Additive: no existing endpoints changed.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Query, Request

from deps import db, get_current_user
from services.copilot_tools import daas_client as _daas

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])

COMPLIANCE_NOTE = (
    "SEBI-screened ideas — not personalised buy advice. "
    "Review suitability before investing."
)

RISK_TO_PROFILE = {
    "conservative": "conservative",
    "low": "conservative",
    "moderate": "balanced",
    "medium": "balanced",
    "aggressive": "growth",
    "high": "growth",
}


async def _user_risk_profile(user_id: str) -> str:
    """Resolve the user's stored risk_profile → conservative/balanced/growth."""
    doc = await db.user_profiles.find_one(
        {"user_id": user_id}, {"_id": 0, "risk_profile": 1}
    ) or {}
    raw = (doc.get("risk_profile") or "moderate").lower()
    return RISK_TO_PROFILE.get(raw, "balanced")


@router.get("/stocks")
async def get_recommended_stocks(
    request: Request,
    profile: Optional[str] = Query(None, description="conservative|balanced|growth"),
    top: int = Query(5, ge=1, le=20),
    sector: Optional[str] = Query(None),
) -> dict[str, Any]:
    """Top stocks ranked by NIDP composite score, filtered by risk profile.

    Screen 13 Recommendations (stock list).

    Query params:
      profile — conservative|balanced|growth (default: derived from user risk profile)
      top     — number of results (1–20, default 5)
      sector  — optional sector filter (e.g. "Financials")
    """
    user = await get_current_user(request)
    user_id = user["user_id"]

    resolved_profile = profile or await _user_risk_profile(user_id)

    # Query NIDP for top-scored stocks filtered by profile
    items: list[dict[str, Any]] = []
    try:
        params: dict[str, Any] = {"profile": resolved_profile, "top": top}
        if sector:
            params["sector"] = sector
        payload = await _daas._get("/stocks/scores/", params=params)
        raw_items = (payload or {}).get("data") or (payload or {}).get("items") or []
        for i, s in enumerate(raw_items[:top]):
            sym = s.get("symbol") or s.get("ticker") or ""
            items.append({
                "rank": i + 1,
                "symbol": sym,
                "name": s.get("name") or s.get("company_name") or sym,
                "sector": s.get("sector") or s.get("sector_name") or "—",
                "composite_score": _coerce_score(s.get("composite_score") or s.get("quality_score")),
                "scores": {
                    "fundamentals": _coerce_score(s.get("fundamentals") or s.get("quality")),
                    "technicals": _coerce_score(s.get("technicals") or s.get("health")),
                    "fundamentals_reason": s.get("quality_reason") or s.get("fundamentals_reason") or "",
                    "technicals_reason": s.get("health_reason") or s.get("technicals_reason") or "",
                },
            })
    except Exception as exc:
        logger.warning("recommendations/stocks DAAS error: %s", exc)
        # Return empty but valid response — NIDP may be unavailable
        items = []

    return {
        "profile": resolved_profile,
        "items": items,
        "compliance_note": COMPLIANCE_NOTE,
        "empty": len(items) == 0,
    }


@router.get("/funds")
async def get_recommended_funds(
    request: Request,
    sleeve: str = Query("equity", description="equity|debt|hybrid|liquid"),
    top: int = Query(4, ge=1, le=20),
    category: Optional[str] = Query(None, description="e.g. flexi-cap"),
    profile: Optional[str] = Query(None, description="conservative|balanced|growth"),
) -> dict[str, Any]:
    """Top funds ranked by NIDP composite score (returns/cost/consistency).

    Screen 13 Recommendations (fund list).

    Query params:
      sleeve   — equity|debt|hybrid|liquid (default: equity)
      top      — number of results (1–20, default 4)
      category — optional category filter (e.g. "flexi-cap")
      profile  — conservative|balanced|growth (default: derived from user risk profile)
    """
    user = await get_current_user(request)
    user_id = user["user_id"]

    resolved_profile = profile or await _user_risk_profile(user_id)

    items: list[dict[str, Any]] = []
    try:
        params: dict[str, Any] = {"sleeve": sleeve, "top": top, "profile": resolved_profile}
        if category:
            params["category"] = category
        payload = await _daas._get("/mf/scores/", params=params)
        raw_items = (payload or {}).get("data") or (payload or {}).get("items") or []
        for i, f in enumerate(raw_items[:top]):
            isin = f.get("isin") or f.get("scheme_isin") or ""
            items.append({
                "rank": i + 1,
                "isin": isin,
                "name": f.get("name") or f.get("scheme_name") or isin,
                "category": f.get("category") or f.get("fund_category") or "—",
                "composite_score": _coerce_score(
                    f.get("composite_score") or f.get("quality_score")
                ),
                "scores": {
                    "returns": _coerce_score(f.get("returns") or f.get("performance")),
                    "cost": _coerce_score(f.get("cost") or f.get("expense")),
                    "consistency": _coerce_score(f.get("consistency")),
                },
            })
    except Exception as exc:
        logger.warning("recommendations/funds DAAS error: %s", exc)
        items = []

    return {
        "sleeve": sleeve,
        "profile": resolved_profile,
        "items": items,
        "compliance_note": COMPLIANCE_NOTE,
        "empty": len(items) == 0,
    }


def _coerce_score(v: Any) -> Optional[int]:
    """Normalise a score to 0-100 int. NIDP may return 0-10 scale."""
    if v is None:
        return None
    try:
        f = float(v)
        # If score is on 0-10 scale, rescale to 0-100
        return round(f * 10) if f <= 10 else round(f)
    except (TypeError, ValueError):
        return None
