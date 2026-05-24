"""V4 user-scope fund v3-score endpoint.

Per docs/api-changes.md Modified Endpoint C.4: demotes the existing
admin-only `/api/intelligence/v3-score/{instrument_id}` to a user-scope
route that returns a user-safe subset of the v3 scoring output.

The admin route stays admin (no scope/auth changes there) — this route is
purely additive.

Serves screens: 13 Recommendations (per-fund sub-scores: Returns / Cost /
Consistency, displayed as 3 bars per fund card).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from deps import db, get_current_user
from services import v3_scoring, v3_score_cache, nav_analytics

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


async def _load_fund_primitives_user(isin: str) -> dict[str, Any] | None:
    """Read primitives from mf_master without admin permission."""
    fund = await db.mf_master.find_one(
        {"$or": [{"isin": isin}, {"instrument_id": isin}]},
        {"_id": 0},
    )
    return fund


@router.get("/funds/{isin}/v3-score")
async def get_user_fund_v3_score(isin: str, request: Request) -> dict[str, Any]:
    """User-callable fund v3-score.

    Returns a subset of the admin v3-score response — the three composite
    sub-scores (Returns / Cost / Consistency) that the Recommendations
    screen renders per fund card.

    Response:
      {
        isin, name, composite_score,
        scores: { returns, cost, consistency }
      }
    """
    await get_current_user(request)  # require session

    # Try cache first
    cached = await v3_score_cache.get(isin)
    if cached and cached.get("scores"):
        q = cached["scores"].get("quality") or {}
        comp = q.get("components") or {}
        return {
            "isin": isin,
            "name": cached.get("scheme_name"),
            "composite_score": round(float(q.get("score") or 0) * 10),
            "scores": {
                "returns": round(float(comp.get("performance") or 0) * 10),
                "cost": round(float(comp.get("cost") or 0) * 10),
                "consistency": round(float(comp.get("consistency") or 0) * 10),
            },
            "cached": True,
        }

    fund = await _load_fund_primitives_user(isin)
    if not fund:
        raise HTTPException(status_code=404, detail="Fund not found")

    quality = v3_scoring.compute_quality_score(fund)
    comp = quality.get("components") or {}

    return {
        "isin": isin,
        "name": fund.get("instrument_name") or fund.get("scheme_name"),
        "composite_score": round(float(quality.get("score") or 0) * 10),
        "scores": {
            "returns": round(float(comp.get("performance") or 0) * 10),
            "cost": round(float(comp.get("cost") or 0) * 10),
            "consistency": round(float(comp.get("consistency") or 0) * 10),
        },
        "cached": False,
    }
