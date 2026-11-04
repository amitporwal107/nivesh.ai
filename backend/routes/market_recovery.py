"""Market Desk › Market Recovery (docs/market_recovery/DESIGN.md): is the market recovering, which sectors lead, and which
Nifty 500 stocks are recovering faster than the market.

    GET /api/market-recovery   -> the whole page (recovery check, breadth series, sectors, candidates, excluded), as of the
                                  last end-of-day session; one computation per worker per end-of-day date, reused 15 minutes
    GET /api/market-recovery/indices
                               -> Nifty 50 and Bank Nifty: technicals, pivots, futures build-up, levels, and the option positioning
                                  and setups of EVERY live expiry (weekly and monthly) separately (DESIGN.md §9); cached 15 minutes
    GET /api/market-recovery/strategies/{symbol}
                               -> the five strategies with downside protection for one scored stock (DESIGN.md §8), or the
                                  Nifty put hedge for a stock without stock options; end-of-day option prices, cached 15 minutes

Signed-in user, behind the `market_recovery` feature flag (403 when off). Typed errors, the scan builder's shape:
{"detail": {"code", "message"}} plus status/error/code/message at the top level: data_unavailable (503), stale_data (503),
not_scored (404), chain_unavailable (503).
Reads market data only; nothing is stored and no order is placed.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import JSONResponse

from feature_gate import require_feature
from services.market_recovery import indices, service, strategies
from services.market_recovery.engine import StaleData
from services.scan_builder.data import DataUnavailable, get_data

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/market-recovery", tags=["market-recovery"],
                   dependencies=[Depends(require_feature("market_recovery"))])


def _answer(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": {"code": code, "message": message}, "status": status,
                                                     "error": code, "code": code, "message": message})


@router.get("")
async def market_recovery():
    try:
        return await service.get_service().get()
    except StaleData as e:
        return _answer(503, "stale_data", e.message)
    except DataUnavailable as e:
        logger.warning("market recovery: data unavailable: %s", e.message)
        return _answer(503, "data_unavailable", e.message)


@router.get("/strategies/{symbol}")
async def market_recovery_strategies(request: Request,
                                     symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[A-Za-z0-9&_.-]+$")):
    sym = symbol.upper()
    try:
        svc = service.get_service()
        page = await svc.get()
        ctx = await svc.stock_context(sym)
        if ctx is None:
            return _answer(404, "not_scored", f"{sym} is not among the stocks scored on this page ({page.get('as_of')}).")
        ref = await get_data().reference()
        return await strategies.get_service().for_stock(request, sym, ctx, sym in ref.fno, str(page.get("as_of")))
    except strategies.ChainUnavailable as e:
        return _answer(503, "chain_unavailable", e.message)
    except StaleData as e:
        return _answer(503, "stale_data", e.message)
    except DataUnavailable as e:
        logger.warning("market recovery strategies: data unavailable: %s", e.message)
        return _answer(503, "data_unavailable", e.message)


@router.get("/indices")
async def market_recovery_indices(request: Request):
    try:
        return await indices.get_service().get(request)
    except DataUnavailable as e:
        logger.warning("market recovery indices: data unavailable: %s", e.message)
        return _answer(503, "data_unavailable", e.message)
