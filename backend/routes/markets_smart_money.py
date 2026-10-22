"""Smart Money Movement — forwarded to the data platform's /v1/desk/smart-money/*
(nidp/services/daas_api/routers/smart_money.py).

    GET /api/markets/smart-money/feeds            per-feed status with the real data as-of date
    GET /api/markets/smart-money/flows?window=    FII/DII cash net + cumulative (1M/3M/6M daily, 1Y monthly)
    GET /api/markets/smart-money/sectors          disclosed MF holdings change by industry
    GET /api/markets/smart-money/breadth          how many names carry disclosed vs proxy-only evidence
    GET /api/markets/smart-money/scanner          one row per Nifty 500 stock: the evidence behind it

The rows live in nidp.mf_holdings_deltas, nidp.fii_dii_flows, nidp.shareholding_pattern,
nidp.v_trendlyne_deals_net and nidp.smart_money_scores_daily, which only the data platform can read, so
each route forwards there and passes the answer through unchanged: every figure, the source, the
disclosure line and the as-of date are the data platform's.

This screen serves EVIDENCE, not a verdict. No score, no ranking by a score and no hit rate is
forwarded, because none is authorised: the smart-money validation study returned INCONCLUSIVE at stage
'exploratory' and nidp.smart_money_promotion_decisions holds no APPROVED row. The reasons per field are
in the upstream router's docstring; `breadth` carries `validated_study` so the UI can say so in words.

Signed-in users only, like the rest of /api/markets. Errors: a data platform that is not configured,
unreachable or failing is 502 upstream_unavailable, never an empty or an older list. No rows in the
window is 200 with `rows: []`.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from deps import get_current_user
from services.copilot_tools import daas_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/markets/smart-money", tags=["markets-smart-money"])

_UNAVAILABLE = "upstream_unavailable"


async def _daas(path: str, params: Dict[str, Any], list_key: Optional[str]) -> Dict[str, Any]:
    """The data platform's answer for `path`. `list_key` names a list the answer must carry
    (None for the object-shaped reads); anything else is 502 rather than a quietly empty screen."""
    if not daas_client.is_configured():
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    try:
        status, body = await daas_client.get_raw(path, params or None)
    except daas_client.DaasError as e:
        logger.warning("smart-money DaaS %s failed: %s", path, e)
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    if status == 200 and isinstance(body, dict) and (list_key is None or isinstance(body.get(list_key), list)):
        return body
    logger.warning("smart-money DaaS %s answered HTTP %s", path, status)
    raise HTTPException(status_code=502, detail=_UNAVAILABLE)


@router.get("/feeds")
async def smart_money_feeds(request: Request) -> Dict[str, Any]:
    """Each feed behind this screen: its status, and the newest data period as distinct from the
    last ingest run. The two differ by weeks on the quarterly and monthly feeds."""
    await get_current_user(request)
    return await _daas("/desk/smart-money/feeds", {}, "rows")


@router.get("/flows")
async def smart_money_flows(
    request: Request,
    window: str = Query("3M", pattern="^(1M|3M|6M|1Y)$"),
) -> Dict[str, Any]:
    """Market-wide FII/DII cash flows over the window, per period and cumulative. 1M/3M/6M are
    daily; 1Y is monthly, because the daily series only begins 2026-04-01 and would truncate."""
    await get_current_user(request)
    return await _daas("/desk/smart-money/flows", {"window": window}, "rows")


@router.get("/sectors")
async def smart_money_sectors(
    request: Request,
    window: str = Query("3M", pattern="^(1M|3M|6M|1Y)$"),
    universe: str = Query("nifty500", pattern="^(nifty50|nifty100|nifty200|nifty500|total)$"),
) -> Dict[str, Any]:
    """Disclosed month-on-month MF holdings change by industry, valued at the disclosure month's
    VWAP. The 11 disclosing AMCs only — not mutual funds as a whole. `mf_window` reports the
    window actually served against the one requested: only a one-month pair is disclosed."""
    await get_current_user(request)
    return await _daas("/desk/smart-money/sectors", {"window": window, "universe": universe}, "rows")


@router.get("/breadth")
async def smart_money_breadth(request: Request) -> Dict[str, Any]:
    """How many names carry a disclosed holdings change, how many only a market proxy, and how many
    rest on a single AMC. Object-shaped: `metrics` plus `validated_study`."""
    await get_current_user(request)
    return await _daas("/desk/smart-money/breadth", {}, None)


@router.get("/scanner")
async def smart_money_scanner(
    request: Request,
    window: str = Query("3M", pattern="^(1M|3M|6M|1Y)$"),
    universe: str = Query("nifty500", pattern="^(nifty50|nifty100|nifty200|nifty500|total)$"),
    sector: Optional[str] = Query(None, min_length=2, max_length=60, pattern=r"^[A-Za-z0-9 &\-]+$"),
    direction: str = Query("all", pattern="^(all|accumulation|distribution)$"),
    lane: str = Query("all", pattern="^(all|disclosed|proxy)$"),
    freshness: str = Query("any", pattern="^(any|fresh|ageing|stale)$"),
    symbol: Optional[str] = Query(None, min_length=1, max_length=20, pattern=r"^[A-Za-z0-9&\-]+$"),
    limit: int = Query(100, ge=1, le=500),
) -> Dict[str, Any]:
    """One row per stock with the disclosed evidence behind it, ordered by evidence class then
    scheme breadth — never by a score. A null deal column with `deals_checked` false means the
    symbol was never queried, not that nothing happened. `lanes` and `classes` count the matched
    set BEFORE the lane filter, so an empty lane can say "none in this universe"."""
    await get_current_user(request)
    params: Dict[str, Any] = {"window": window, "universe": universe, "direction": direction,
                              "lane": lane, "freshness": freshness, "limit": limit}
    if sector:
        params["sector"] = sector
    if symbol:
        params["symbol"] = symbol
    return await _daas("/desk/smart-money/scanner", params, "rows")
