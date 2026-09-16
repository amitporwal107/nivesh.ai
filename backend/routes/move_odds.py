"""Move odds — the Research page's Ten-Percent Days screen (docs/ai_research/designs/Nivesh Move Odds (standalone).html).

    GET /api/move-odds/latest?head=p_up5_1d   → DaaS /v1/move-odds/latest (model v4)
    GET /api/move-odds/stocks/{symbol}        → DaaS /v1/move-odds/stocks/{symbol}

Only accounts on the move_odds allowlist get past the gate (403 feature_not_enabled otherwise, admins included).
The payload is passed through unchanged, so every number shown is the published, frozen one (spec C7). A DaaS
503 withheld answer is passed through with its reason; an unreachable DaaS is 502 upstream_unavailable, never an
older or cached run.
"""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import JSONResponse

from feature_gate import require_feature

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/move-odds", tags=["move_odds"])
FLAG = "move_odds"
MODEL = "v4"
Head = Literal["p_up5_1d", "p_down5_1d", "p_up10_1d", "p_down10_1d"]


async def _proxy(path: str, params: dict):
    from services.copilot_tools import daas_client
    if not daas_client.is_configured():
        raise HTTPException(status_code=502, detail="upstream_unavailable")
    try:
        status, body = await daas_client.get_raw(path, params)
    except daas_client.DaasError as e:
        logger.warning("move-odds DaaS %s failed: %s", path, e)
        raise HTTPException(status_code=502, detail="upstream_unavailable")
    if status == 200 and isinstance(body, dict):
        return body
    if status == 503 and isinstance(body, dict) and (body.get("data") or {}).get("status") == "withheld":
        # `detail` is the one field every client error parser reads; `data` keeps the structured reason
        return JSONResponse(status_code=503, content={"detail": f"withheld: {body['data'].get('reason')}", "data": body["data"]})
    if status == 404:
        raise HTTPException(status_code=404, detail="not_found")
    logger.warning("move-odds DaaS %s answered HTTP %s", path, status)
    raise HTTPException(status_code=502, detail="upstream_unavailable")


@router.get("/latest")
async def latest(head: Head = "p_up5_1d", user: dict = Depends(require_feature(FLAG))):
    return await _proxy("/move-odds/latest", {"head": head, "model": MODEL})


@router.get("/stocks/{symbol}")
async def stock(symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[A-Za-z0-9&\-]+$"), user: dict = Depends(require_feature(FLAG))):
    return await _proxy(f"/move-odds/stocks/{symbol.upper()}", {"model": MODEL})
