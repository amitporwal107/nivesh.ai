"""Portfolio Diversification & Concentration endpoints.

Powers the Insights tab's three exposure sections:
  - AMC Exposure
  - Sector Exposure
  - Company Exposure

Single endpoint:
  GET /api/portfolio/exposure/concentration → full envelope.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from typing import Any
import logging

from deps import db, get_current_user
from services.portfolio_concentration import compute_concentration

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/portfolio/exposure", tags=["portfolio-exposure"])


async def _load_fund_lookthrough(holdings: list[dict]) -> dict[str, dict]:
    """For all MF/ETF holdings, look up their `fund_holdings_cache`
    document keyed by ISIN and return a {ticker → {holdings, sectors}}
    map. Missing rows just yield no lookthrough — concentration logic
    will fall back to the MF's own sector field."""
    mf_isins = [
        h.get("ticker") for h in holdings
        if (h.get("asset_type") or "").lower() in {"mutual_fund", "etf"} and h.get("ticker")
    ]
    if not mf_isins:
        return {}
    lookup: dict[str, dict] = {}
    async for doc in db.fund_holdings_cache.find(
        {"isin": {"$in": list(set(mf_isins))}},
        {"_id": 0, "isin": 1, "holdings": 1, "sectors": 1},
    ):
        isin = doc.get("isin")
        if not isin:
            continue
        lookup[isin] = {
            "holdings": doc.get("holdings") or [],
            "sectors":  doc.get("sectors")  or [],
        }
    return lookup


@router.get("/concentration")
async def get_concentration(request: Request) -> dict[str, Any]:
    """Return AMC + Sector + Company concentration for the current
    user's portfolio. Pure read; cheap enough to compute on every call.
    """
    user = await get_current_user(request)
    user_id = user["user_id"]

    holdings: list[dict] = []
    async for h in db.holdings.find(
        {"user_id": user_id},
        {"_id": 0, "name": 1, "ticker": 1, "asset_type": 1,
         "quantity": 1, "current_price": 1, "sector": 1},
    ):
        holdings.append(h)

    if not holdings:
        return {
            "total_value": 0,
            "amc":     {"items": [], "all_items_count": 0, "hhi": 0, "effective_n": 0, "largest_pct": 0, "warning": None},
            "sector":  {"items": [], "all_items_count": 0, "hhi": 0, "effective_n": 0, "largest_pct": 0, "warning": None},
            "company": {"items": [], "all_items_count": 0, "hhi": 0, "effective_n": 0, "largest_pct": 0, "warning": None, "top10_pct": 0},
            "holdings_count": 0,
            "empty": True,
        }

    fund_lookthrough = await _load_fund_lookthrough(holdings)
    env = compute_concentration(holdings, fund_lookthrough=fund_lookthrough)
    env["holdings_count"] = len(holdings)
    env["lookthrough_coverage"] = round(
        100 * len(fund_lookthrough) / max(1, sum(
            1 for h in holdings if (h.get("asset_type") or "").lower() in {"mutual_fund", "etf"}
        )),
        1,
    )
    return env
