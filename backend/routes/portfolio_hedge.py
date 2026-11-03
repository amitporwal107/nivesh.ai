"""Quick Hedge API: POST /api/portfolio/quick-hedge.

The request carries only what the user chose: the loss they can tolerate, the fall they fear and the protection period. Everything
else (holdings, beta, fit to Nifty, Nifty's price, lot, expiries and put prices) is read on the server (services/quick_hedge/).
Fail-closed behind the `portfolio_hedge` feature flag. Reads only: nothing is stored and no order is placed."""
from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from deps import db, get_current_user
from feature_gate import require_feature
from services.quick_hedge import service

router = APIRouter(prefix="/api/portfolio/quick-hedge", tags=["portfolio-hedge"], dependencies=[Depends(require_feature("portfolio_hedge"))])


class QuickHedgeBody(BaseModel):
    expected_fall_pct: float = Field(..., gt=0, le=50, description="The Nifty fall the user is worried about, in percent")
    tenor: Literal["1w", "2w", "1m", "3m"] = "1m"
    tolerance_rs: Optional[float] = Field(None, ge=0, description="Rupees the portfolio may lose before protection starts")
    tolerance_pct: Optional[float] = Field(None, ge=0, le=100, description="The same, as a percent of the equity-linked value")


@router.post("")
async def quick_hedge(body: QuickHedgeBody, request: Request) -> Dict[str, Any]:
    """Three hedge choices (Maximum protection, Balanced, Lowest cost) with cost, protection and a scenario table, or the reason none is shown."""
    user = await get_current_user(request)
    if body.tolerance_rs is None and body.tolerance_pct is None:
        raise HTTPException(status_code=422, detail={"code": "tolerance_required", "message": "Send tolerance_rs or tolerance_pct: how much loss you can accept before protection starts."})
    return await service.run(db, user["user_id"], expected_fall_pct=body.expected_fall_pct, tenor=body.tenor,
                             tolerance_rs=body.tolerance_rs, tolerance_pct=body.tolerance_pct)
