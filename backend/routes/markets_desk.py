"""Smart trading desk — market reads, forwarded to the data platform's /v1/desk/* (nidp/services/daas_api/routers/desk_market.py).

    GET /api/markets/sector-returns                       NSE sectoral indices: latest close and 1-day / 1-week / 1-month returns,
                                                          and breadth within each index that has a constituent list
    GET /api/markets/sector-constituents?index=           one sector index's constituents with their move on its latest
                                                          close day, and the breadth within it (`available: false` and a
                                                          `reason` for an index with no constituent list)
    GET /api/markets/sector-heatmap?index=                an index's stocks grouped by industry with 1d / 1w / 1m returns, weights,
                                                          contribution, breadth, traded value (404 unknown_index)
    GET /api/markets/deals?days=5&kind=all&symbol=&limit= NSE bulk and block deals over the last `days` calendar days (1–30)

The rows live in nidp.index_eod, nidp.bulk_deals and nidp.block_deals, which only the data platform can read, so each
route forwards there and passes the answer through unchanged: every figure, the source and the as-of date are the
data platform's. Definitions (session counts, the deal window, value in ₹ crore) are in that router's docstring.

Signed-in users only, like the rest of /api/markets. Errors: a data platform that is not configured, unreachable or
failing is 502 upstream_unavailable, never an empty or an older list. No deals in the window is 200 with `rows: []`.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from deps import get_current_user
from services.copilot_tools import daas_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/markets", tags=["markets-desk"])

SYMBOL_PATTERN = r"^[A-Za-z0-9&\-]+$"
INDEX_PATTERN = r"^[A-Za-z0-9 &\-]+$"
_UNAVAILABLE = "upstream_unavailable"


async def _daas(path: str, params: Dict[str, Any], list_key: str) -> Dict[str, Any]:
    """The data platform's answer for `path`, which must carry a list under `list_key`; else 502."""
    if not daas_client.is_configured():
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    try:
        status, body = await daas_client.get_raw(path, params or None)
    except daas_client.DaasError as e:
        logger.warning("markets-desk DaaS %s failed: %s", path, e)
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    if status == 200 and isinstance(body, dict) and isinstance(body.get(list_key), list):
        return body
    logger.warning("markets-desk DaaS %s answered HTTP %s", path, status)
    raise HTTPException(status_code=502, detail=_UNAVAILABLE)


@router.get("/sector-returns")
async def sector_returns(request: Request) -> Dict[str, Any]:
    """NSE sectoral index closes with 1-day, 1-week (5 sessions) and 1-month (21 sessions) returns, each against
    that index's own earlier close; null where the index's history is too short."""
    await get_current_user(request)
    return await _daas("/desk/sector-returns", {}, "sectors")


@router.get("/sector-constituents")
async def sector_constituents(
    request: Request,
    index: str = Query(..., min_length=3, max_length=60, pattern=INDEX_PATTERN, description="e.g. 'Nifty Bank'"),
) -> Dict[str, Any]:
    """A sector index's latest constituent list, each stock's close vs its previous close on the index's latest close
    day, and the advances / declines / unchanged within the sector. Passed through unchanged."""
    await get_current_user(request)
    return await _daas("/desk/sector-constituents", {"index": index.strip()}, "rows")


@router.get("/sector-heatmap")
async def sector_heatmap(
    request: Request,
    index: str = Query("Nifty 50", min_length=3, max_length=60, pattern=INDEX_PATTERN,
                       description="An index in the data platform's constituent lists, e.g. 'Nifty 50'"),
) -> Dict[str, Any]:
    """An index's stocks grouped by industry with 1-day / 1-week (5 sessions) / 1-month (21 sessions) adjusted-close
    returns, weights, contribution to the index move, breadth, traded value and relative volume. Passed through
    unchanged (the rules and anything unsourced are in the payload). An index the data platform does not hold is 404
    `unknown_index`."""
    await get_current_user(request)
    if not daas_client.is_configured():
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    try:
        status, body = await daas_client.get_raw("/desk/sector-heatmap", {"index": index.strip()}, timeout=30.0)
    except daas_client.DaasError as e:
        logger.warning("markets-desk DaaS /desk/sector-heatmap failed: %s", e)
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    if status == 200 and isinstance(body, dict) and isinstance(body.get("sectors"), list):
        return body
    if status == 404 and isinstance(body, dict):
        msg = str((body.get("error") or {}).get("message") or "")
        code = "unknown_index" if msg.startswith("unknown_index") else "no_constituents"
        raise HTTPException(status_code=404, detail={"code": code, "message": msg})
    logger.warning("markets-desk DaaS /desk/sector-heatmap answered HTTP %s", status)
    raise HTTPException(status_code=502, detail=_UNAVAILABLE)


@router.get("/deals")
async def deals(
    request: Request,
    days: int = Query(5, ge=1, le=30, description="Calendar days ending at the latest deal date"),
    kind: Literal["all", "bulk", "block"] = Query("all"),
    symbol: Optional[str] = Query(None, min_length=1, max_length=20, pattern=SYMBOL_PATTERN),
    limit: int = Query(500, ge=1, le=2000, description="Rows returned, largest value first within each day"),
) -> Dict[str, Any]:
    """NSE bulk and block deals: date, kind, symbol, client, side, quantity, average price and value (₹ crore).
    `total` counts every deal in the window; `count` the rows returned."""
    await get_current_user(request)
    params: Dict[str, Any] = {"days": days, "kind": kind, "limit": limit}
    if symbol:
        params["symbol"] = symbol.upper()
    return await _daas("/desk/deals", params, "rows")
