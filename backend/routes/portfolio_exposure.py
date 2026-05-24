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

    holdings: list[dict] = await db.holdings.find(
        {"user_id": user_id},
        {"_id": 0, "name": 1, "ticker": 1, "asset_type": 1,
         "quantity": 1, "current_price": 1, "sector": 1},
    ).to_list(1000)
    if not holdings:
        from services.pi_bridge import pi_holdings_for_user  # noqa: WPS433
        holdings = await pi_holdings_for_user(user_id)

    if not holdings:
        empty_sec = {"items": [], "all_items_count": 0, "hhi": 0,
                     "effective_n": 0, "largest_pct": 0, "warning": None,
                     "hero_insight": None}
        return {
            "total_value": 0,
            "amc":     dict(empty_sec),
            "sector":  dict(empty_sec, cycle_split={"cyclical_pct": 0, "defensive_pct": 0, "other_pct": 0}),
            "company": dict(empty_sec, top10_pct=0, hidden_overlap={"items": [], "count": 0}),
            "group":   dict(empty_sec),
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


# ─── Fund-overlap matrix ──────────────────────────────────────────────────
# V3 Diversification heatmap uses this. Distinct from /concentration above
# (which is single-axis: AMC/sector/company). This one is the full pairwise
# matrix between every MF/ETF holding in the user's portfolio.
#
# Read-only: composes fund_holdings_cache (already populated) + Mongo holdings.
# Identical math to services/portfolio_intelligence.py::_overlap, but
# self-contained so it has zero risk of regressing the intelligence pipeline.

def _stock_key(h: dict) -> str:
    """Canonical key for a stock holding inside a fund — lowercase name,
    matching the convention used by portfolio_intelligence._pairwise_overlap.
    Falls back through name → slug variants."""
    name = (h.get("name") or h.get("stock_name") or h.get("holding_name") or "").strip()
    return name.lower() if name else ""


def _build_fund_weights(fund_doc: dict) -> dict[str, float]:
    """{stock_key: weight_pct} for one fund_holdings_cache doc."""
    out: dict[str, float] = {}
    for h in (fund_doc.get("holdings") or []):
        k = _stock_key(h)
        if not k:
            continue
        try:
            out[k] = float(h.get("pct") or h.get("weight_percent") or 0)
        except (TypeError, ValueError):
            continue
    return out


def _overlap_pct(a: dict[str, float], b: dict[str, float]) -> float:
    """Σ min(w_a(s), w_b(s)) across shared stocks. Returns 0-100."""
    if not a or not b:
        return 0.0
    return round(sum(min(a[s], b[s]) for s in a.keys() & b.keys()), 2)


@router.get("/fund-overlap/matrix")
async def get_fund_overlap_matrix(request: Request) -> dict[str, Any]:
    """Pairwise stock-level overlap matrix between every MF/ETF in the
    user's portfolio.

    Response:
    {
      "funds": [{id, name, amc, category}],
      "matrix": [[100, 42.5, 12.0, ...], ...]   # symmetric, diagonal = 100
      "pairs": [{a, b, a_name, b_name, overlap_pct, shared_count}, ...]  # sorted desc
      "max_pct": 67.2,
      "high_pairs": 3,      # count where overlap_pct >= 65
      "coverage_pct": 78,   # what % of MF AUM has fund_holdings_cache data
      "empty": false
    }
    """
    user = await get_current_user(request)
    user_id = user["user_id"]

    # 1. Load user's MF/ETF holdings — with V3 Postgres fallback for V4 users
    _all_holdings: list[dict] = await db.holdings.find(
        {"user_id": user_id},
        {"_id": 0, "name": 1, "ticker": 1, "asset_type": 1,
         "quantity": 1, "current_price": 1, "amc_name": 1, "category": 1},
    ).to_list(1000)
    if not _all_holdings:
        from services.pi_bridge import pi_holdings_for_user  # noqa: WPS433
        _all_holdings = await pi_holdings_for_user(user_id)
    mf_holdings: list[dict] = [
        h for h in _all_holdings
        if (h.get("asset_type") or "").lower() in {"mutual_fund", "etf"}
    ]

    if len(mf_holdings) < 2:
        return {
            "funds": [], "matrix": [], "pairs": [],
            "max_pct": 0, "high_pairs": 0, "coverage_pct": 0,
            "empty": True,
        }

    # 2. Load fund_holdings_cache for each ISIN
    isins = list({h["ticker"] for h in mf_holdings if h.get("ticker")})
    cache_by_isin: dict[str, dict] = {}
    async for doc in db.fund_holdings_cache.find(
        {"isin": {"$in": isins}},
        {"_id": 0, "isin": 1, "holdings": 1},
    ):
        if doc.get("isin"):
            cache_by_isin[doc["isin"]] = doc

    # 3. Build the list of funds that have cache data
    funds = []
    weights: dict[str, dict[str, float]] = {}
    total_aum = 0.0
    covered_aum = 0.0
    for h in mf_holdings:
        isin = h.get("ticker")
        value = float((h.get("quantity") or 0) * (h.get("current_price") or 0))
        total_aum += value
        if isin not in cache_by_isin:
            continue
        w = _build_fund_weights(cache_by_isin[isin])
        if not w:
            continue
        weights[isin] = w
        covered_aum += value
        funds.append({
            "id": isin,
            "name": h.get("name") or isin,
            "amc": h.get("amc_name"),
            "category": h.get("category"),
            "value_rs": round(value, 2),
        })

    if len(funds) < 2:
        return {
            "funds": funds, "matrix": [], "pairs": [],
            "max_pct": 0, "high_pairs": 0,
            "coverage_pct": round(100 * covered_aum / total_aum, 1) if total_aum > 0 else 0,
            "empty": True,
        }

    # 4. Build the symmetric matrix
    n = len(funds)
    matrix: list[list[float]] = [[0.0] * n for _ in range(n)]
    pairs: list[dict] = []
    max_pct = 0.0
    high_pairs = 0
    for i in range(n):
        matrix[i][i] = 100.0
        for j in range(i + 1, n):
            a_id, b_id = funds[i]["id"], funds[j]["id"]
            ov = _overlap_pct(weights[a_id], weights[b_id])
            matrix[i][j] = ov
            matrix[j][i] = ov
            shared_keys = set(weights[a_id]) & set(weights[b_id])
            pairs.append({
                "a": a_id, "b": b_id,
                "a_name": funds[i]["name"], "b_name": funds[j]["name"],
                "overlap_pct": ov,
                "shared_count": len(shared_keys),
            })
            if ov > max_pct:
                max_pct = ov
            if ov >= 65:
                high_pairs += 1

    pairs.sort(key=lambda p: p["overlap_pct"], reverse=True)

    # v4 addition (Modified Endpoint C.6) — distinct stocks across all funds.
    unique_stocks: set[str] = set()
    for w in weights.values():
        unique_stocks.update(w.keys())

    return {
        "funds": funds,
        "matrix": matrix,
        "pairs": pairs[:25],   # top 25 to keep payload small
        "max_pct": round(max_pct, 2),
        "high_pairs": high_pairs,
        "unique_stocks_count": len(unique_stocks),   # v4
        "coverage_pct": round(100 * covered_aum / total_aum, 1) if total_aum > 0 else 0,
        "empty": False,
    }
