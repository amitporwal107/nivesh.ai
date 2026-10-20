"""Strategy Builder calculation routes (PRD §16, §17.4).

POST /api/desk/strategy/payoff: a pure calculation of the expiry payoff (and, when asked, the pre-expiry estimate) of
cash, futures and defined-risk options legs. Signed-in users only. Nothing is stored and nothing is sent to a broker
(`sent_to_broker: false`). Malformed JSON is 422; an invalid strategy is a 200 with `valid: false` and `problems`.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from deps import get_current_user
from services.strategy_plan import compute_payoff

router = APIRouter(prefix="/api/desk/strategy", tags=["desk"])


@router.post("/payoff")
async def strategy_payoff(request: Request) -> Dict[str, Any]:
    await get_current_user(request)
    try:
        body = json.loads(await request.body())
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_body")
    return compute_payoff(body, date.today())
