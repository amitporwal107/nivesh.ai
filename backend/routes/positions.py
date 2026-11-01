"""Open Positions workspace — every open position of the signed-in user, real (broker) and paper, grouped by
underlying, with payoff, Greeks, scenarios, distance to the user's stop, and warnings. Read-only towards brokers:
no route here places, modifies or cancels an order. See services/positions/service.py for sources and prices.

    GET    /api/positions                       the whole book (sources, summary, groups)
    GET    /api/positions/book/live             the Copilot's open-trades blocks again, from the cached broker book and Kite's live
                                                share prices (services/copilot_visual/open_book.live); the page asks every 5 s
    GET    /api/positions/{key}/scenario        one group's scenario table (?moves=-5,-2,0,2,5&iv_shift=3&days_forward=1)
    PUT    /api/positions/{underlying}/levels   the user's stop / target / trailing stop for a broker underlying
    DELETE /api/positions/{underlying}/levels   remove them

Levels are the user's own: brokers send none. A paper trade keeps the levels it was opened with (change them on the
desk), so they cannot be set here.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Path, Query, Request

from deps import db, get_current_user
from services.positions import service, store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/positions", tags=["positions"])

UNDERLYING_PATTERN = r"^[A-Za-z0-9&\-]{1,20}$"
KEY_PATTERN = r"^(broker:[A-Za-z0-9&\-]{1,20}|paper:[A-Za-z0-9_\-]{1,64})$"
MAX_MOVES = 25
MAX_MOVE_PCT = 50.0
MAX_IV_SHIFT = 50.0
MAX_DAYS_FORWARD = 60


@router.get("")
async def get_positions(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    return service.public(await service.build(request, db, user))


@router.get("/book/live")
async def get_book_live(request: Request) -> Dict[str, Any]:
    """The live blocks of the open-trades answer. Never calls a broker more often than services/positions/book.BOOK_TTL_S per
    account (the newest stored read is the cache), however many tabs ask; the user's own accounts only."""
    user = await get_current_user(request)
    from services.copilot_visual import open_book
    try:
        return await open_book.live(request, user)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 — the page keeps its last blocks and says the feed was lost
        logger.warning("open book live: not built (%s)", type(e).__name__, exc_info=True)
        raise HTTPException(status_code=502, detail="book_unavailable")


def _moves(raw: str) -> List[float]:
    try:
        moves = [float(x) for x in raw.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=422, detail="moves must be numbers separated by commas")
    if not moves or len(moves) > MAX_MOVES:
        raise HTTPException(status_code=422, detail=f"give 1 to {MAX_MOVES} moves")
    if any(abs(m) > MAX_MOVE_PCT or m != m for m in moves):
        raise HTTPException(status_code=422, detail=f"each move must be within ±{MAX_MOVE_PCT:g}%")
    return sorted(set(moves))


@router.get("/{key}/scenario")
async def get_scenario(
    request: Request,
    key: str = Path(..., pattern=KEY_PATTERN),
    moves: str = Query("-10,-5,-3,-2,-1,0,1,2,3,5,10", max_length=200),
    iv_shift: float = Query(0.0, ge=-MAX_IV_SHIFT, le=MAX_IV_SHIFT),
    days_forward: int = Query(0, ge=0, le=MAX_DAYS_FORWARD),
) -> Dict[str, Any]:
    user = await get_current_user(request)
    out = await service.group_scenario(request, db, user, key, _moves(moves), iv_shift, days_forward)
    if out is None:
        raise HTTPException(status_code=404, detail="position_not_found")
    return out


async def _body(request: Request) -> Dict[str, Any]:
    try:
        body = json.loads(await request.body() or b"{}")
    except ValueError:
        raise HTTPException(status_code=422, detail="the body is not JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="the body must be an object")
    return body


@router.put("/{underlying}/levels")
async def put_levels(request: Request, underlying: str = Path(..., pattern=UNDERLYING_PATTERN)) -> Dict[str, Any]:
    user = await get_current_user(request)
    try:
        levels = store.validate_levels(await _body(request))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    await store.ensure_indexes(db)
    doc = await store.save_levels(db, user["user_id"], underlying.upper(), levels)
    return {"underlying": underlying.upper(), "stop": doc.get("stop"), "target": doc.get("target"),
            "trail_pct": doc.get("trail_pct"), "updated_at": doc.get("updated_at"), "set_by": "you"}


@router.delete("/{underlying}/levels")
async def delete_levels(request: Request, underlying: str = Path(..., pattern=UNDERLYING_PATTERN)) -> Dict[str, Any]:
    user = await get_current_user(request)
    if not await store.delete_levels(db, user["user_id"], underlying.upper()):
        raise HTTPException(status_code=404, detail="levels_not_found")
    return {"underlying": underlying.upper(), "deleted": True}
