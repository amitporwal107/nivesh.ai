"""Market Desk › Market Recovery (docs/market_recovery/DESIGN.md): is the market recovering, which sectors lead, and which
Nifty 500 stocks are recovering faster than the market.

    GET /api/market-recovery   -> the whole page (recovery check, breadth series, sectors, candidates, excluded), as of the
                                  last end-of-day session; one computation per worker per end-of-day date, reused 15 minutes

Signed-in user, behind the `market_recovery` feature flag (403 when off). Typed errors, the scan builder's shape:
{"detail": {"code", "message"}} plus status/error/code/message at the top level: data_unavailable (503), stale_data (503).
Reads market data only; nothing is stored and no order is placed.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from feature_gate import require_feature
from services.market_recovery import service
from services.market_recovery.engine import StaleData
from services.scan_builder.data import DataUnavailable

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
