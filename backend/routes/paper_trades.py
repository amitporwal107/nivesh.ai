"""Paper trades — the Research page's Ten-Percent Days paper trade simulation (engine: nidp.services.tpd_model.paper).

    GET /api/paper-trades/portfolio?sample=&portfolio=&prediction_date=   → DaaS /v1/paper-trades/portfolio
    GET /api/paper-trades/trades/{trade_id}                               → DaaS /v1/paper-trades/trades/{id}
    GET /api/paper-trades/evaluation?sample=&portfolio=                   → DaaS /v1/paper-trades/evaluation
    GET /api/paper-trades/live?portfolio=                                 → the latest forward selection's target/stop status
                                                                            from Yahoo 5-minute bars (services/paper_trades_live)

Same gate as Move odds: only accounts on the move_odds allowlist (403 feature_not_enabled otherwise, admins included).
Payloads are passed through unchanged, so every number shown is the one the engine stored; an unreachable DaaS is 502
upstream_unavailable, never an older copy.
"""
from __future__ import annotations

import asyncio
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from feature_gate import require_feature
from routes.move_odds import _proxy

router = APIRouter(prefix="/api/paper-trades", tags=["paper_trades"])
FLAG = "move_odds"
Sample = Literal["forward", "replay"]
Portfolio = Literal["P5-NEXT", "P10-NEXT"]


@router.get("/portfolio")
async def portfolio(sample: Sample = "forward", portfolio: Portfolio = "P5-NEXT", prediction_date: Optional[date] = None,
                    top: int = Query(25, ge=5, le=100), user: dict = Depends(require_feature(FLAG))):
    params = {"sample": sample, "portfolio": portfolio, "top": top}
    if prediction_date is not None:
        params["prediction_date"] = prediction_date.isoformat()
    return await _proxy("/paper-trades/portfolio", params)


@router.get("/trades/{trade_id}")
async def trade(trade_id: int = Path(..., ge=1), user: dict = Depends(require_feature(FLAG))):
    return await _proxy(f"/paper-trades/trades/{trade_id}", {})


@router.get("/evaluation")
async def evaluation(sample: Sample = "forward", portfolio: Portfolio = "P5-NEXT", user: dict = Depends(require_feature(FLAG))):
    return await _proxy("/paper-trades/evaluation", {"sample": sample, "portfolio": portfolio})


@router.get("/live")
async def live(portfolio: Portfolio = "P5-NEXT", user: dict = Depends(require_feature(FLAG))):
    """Target/stop status of the latest forward selection on its pre-registered levels. Provisional until tonight's run."""
    from services.paper_trades_live import live_status
    body = await _proxy("/paper-trades/portfolio", {"sample": "forward", "portfolio": portfolio, "top": 5})
    data = body.get("data") or {}
    if data.get("status") != "ok":
        return {"data": {"status": "empty", "portfolio": portfolio, "positions": []}}
    try:
        return {"data": {"status": "ok", **(await asyncio.wait_for(live_status(data), timeout=25.0))}}
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="live_prices_timeout")
