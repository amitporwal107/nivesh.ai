"""Top Movers Dashboard — app-side proxy.

The computation lives in the DaaS API (`nidp/services/daas_api/routers/movers.py`) because that is
where the nidp.* tables are: the app backend's own database has none of them, which is why the first
direct-SQL version of this file answered 500 `relation "nidp.tpd_runs" does not exist` on staging.

This module keeps only what belongs to the app: the login session and the Move-odds feature gate
(everyone off the allowlist gets 403, admins included). Params are validated here, forwarded
verbatim, and the DaaS answer is passed through — a 400/404 stays a 400/404, anything else from
upstream is a 502, never a made-up empty result.

Route order matters: the static paths (/calibration, /flag-lift, /flagged, /forward, /candidates)
must be registered before /{symbol}, or FastAPI matches them as a symbol.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from deps import get_current_user
from feature_gate import require_feature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/movers", tags=["movers"])
FLAG = "move_odds"
HEAD_RE = "^p_(up|down)(5|10)_1d$"
_HEAVY_TIMEOUT = 120.0   # calibration / flag-lift scan a month of runs; DaaS caches them for hours
_PASS_THROUGH = {400, 404, 422}


async def _forward(path: str, params: dict[str, Any], timeout: float = 60.0) -> Any:
    from services.copilot_tools import daas_client
    if not daas_client.is_configured():
        raise HTTPException(status_code=502, detail="upstream_unavailable")
    clean = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in params.items() if v is not None}
    try:
        status, body = await daas_client.get_raw(path, clean, timeout=timeout)
    except daas_client.DaasError as e:
        logger.warning("movers DaaS %s failed: %s", path, e)
        raise HTTPException(status_code=502, detail="upstream_unavailable")
    if status == 200 and body is not None:
        return body
    if status in _PASS_THROUGH:
        detail = body.get("detail") if isinstance(body, dict) else None
        raise HTTPException(status_code=status, detail=detail or "request_rejected")
    logger.warning("movers DaaS %s answered HTTP %s", path, status)
    raise HTTPException(status_code=502, detail="upstream_unavailable")


@router.get("")
async def list_movers(
    request: Request,
    user: dict = Depends(require_feature(FLAG)),
    frm: date = Query(..., alias="from", description="window start (inclusive)"),
    to: date = Query(..., description="window end (inclusive)"),
    min_abs_pct: float = Query(5.0, ge=0, le=100),
    direction: str = Query("both", pattern="^(both|up|down)$"),
    limit: int = Query(100, ge=1, le=500),
    include_ca: bool = Query(False, description="include moves flagged as unadjusted split/bonus"),
) -> Any:
    await get_current_user(request)
    return await _forward("/movers", {"from": frm, "to": to, "min_abs_pct": min_abs_pct,
                                      "direction": direction, "limit": limit,
                                      "include_ca": str(include_ca).lower()})


# Static analytics routes BEFORE /{symbol} (see module docstring).
@router.get("/calibration")
async def calibration(
    request: Request,
    user: dict = Depends(require_feature(FLAG)),
    frm: date = Query(..., alias="from"),
    to: date = Query(..., description="window end (inclusive)"),
    head: str = Query("p_up5_1d", pattern=HEAD_RE),
    horizon: int = Query(3),
) -> Any:
    await get_current_user(request)
    return await _forward("/movers/calibration", {"from": frm, "to": to, "head": head, "horizon": horizon},
                          _HEAVY_TIMEOUT)


@router.get("/flag-lift")
async def flag_lift(
    request: Request,
    user: dict = Depends(require_feature(FLAG)),
    frm: date = Query(..., alias="from"),
    to: date = Query(..., description="window end (inclusive)"),
    head: str = Query("p_up5_1d", pattern=HEAD_RE),
    horizon: int = Query(3),
) -> Any:
    await get_current_user(request)
    return await _forward("/movers/flag-lift", {"from": frm, "to": to, "head": head, "horizon": horizon},
                          _HEAVY_TIMEOUT)


@router.get("/flagged")
async def flagged_no_move(
    request: Request,
    user: dict = Depends(require_feature(FLAG)),
    frm: date = Query(..., alias="from"),
    to: date = Query(..., description="window end (inclusive)"),
    head: str = Query("p_up5_1d", pattern=HEAD_RE),
    horizon: int = Query(3),
    limit: int = Query(100, ge=1, le=500),
) -> Any:
    await get_current_user(request)
    return await _forward("/movers/flagged", {"from": frm, "to": to, "head": head, "horizon": horizon,
                                              "limit": limit}, _HEAVY_TIMEOUT)


@router.get("/forward")
async def forward_list(
    request: Request,
    user: dict = Depends(require_feature(FLAG)),
    session: Optional[date] = Query(None, description="target session; default = the newest one on record"),
    limit: int = Query(15, ge=1, le=100),
) -> Any:
    await get_current_user(request)
    return await _forward("/movers/forward", {"session": session, "limit": limit})


@router.get("/candidates")
async def candidates(
    request: Request,
    user: dict = Depends(require_feature(FLAG)),
    session: Optional[date] = Query(None, description="session to scan; default = newest EQ session on record"),
    limit: int = Query(40, ge=1, le=100),
) -> Any:
    await get_current_user(request)
    return await _forward("/movers/candidates", {"session": session, "limit": limit})


@router.get("/{symbol}")
async def mover_detail(
    request: Request,
    symbol: str,
    user: dict = Depends(require_feature(FLAG)),
    session: date = Query(..., description="the move session T the timeline centres on"),
    range_: str = Query("T7", alias="range", pattern="^(1D|T7|1M|3M|1Y|custom)$"),
    frm: Optional[date] = Query(None, alias="from"),
    to: Optional[date] = Query(None),
    horizon: int = Query(3),
) -> Any:
    await get_current_user(request)
    return await _forward(f"/movers/{symbol.strip().upper()}",
                          {"session": session, "range": range_, "from": frm, "to": to, "horizon": horizon})


@router.get("/{symbol}/analysis")
async def mover_analysis(
    request: Request,
    symbol: str,
    user: dict = Depends(require_feature(FLAG)),
    session: date = Query(...),
    event_id: Optional[str] = Query(None, description="pin the decomposition to one event"),
) -> Any:
    await get_current_user(request)
    return await _forward(f"/movers/{symbol.strip().upper()}/analysis", {"session": session, "event_id": event_id})
