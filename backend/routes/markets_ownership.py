"""Historical Smart Money Movement — forwarded to the data platform's /v1/desk/ownership/*
(nidp/services/daas_api/routers/ownership.py).

    GET /api/markets/ownership/reaction   quarterly institutional ownership change beside the SAME
                                          quarter's price return, volume ratio and delivery shift

The rows live in nidp.shareholding_pattern, nidp.prices_eod and nidp.index_constituents, which only
the data platform can read, so this route forwards there and passes the answer through unchanged:
every figure, threshold, source line and as-of date is the data platform's. This layer adds nothing
and derives nothing.

This screen is DESCRIPTIVE AND RETROSPECTIVE and is not a trading signal. The Jul-Sep shareholding
pattern is published in late October, so the price move it sits beside was already over before the
ownership figure existed. No score and no ranking by one is forwarded, and none exists: the
smart-money validation study returned INCONCLUSIVE and nidp.smart_money_promotion_decisions holds
no APPROVED row, which the upstream `validated_study` field reports live so the UI can say so in
words. The per-field reasons are in the upstream router's docstring.

Signed-in users only, like the rest of /api/markets. Errors: a data platform that is not
configured, unreachable or failing is 502 upstream_unavailable — never an empty or an older list,
because a blank panel here would read as "no institution moved", which is a different and false
claim. No rows for the quarter is 200 with `rows: []`.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from deps import get_current_user
from services.copilot_tools import daas_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/markets/ownership", tags=["markets-ownership"])

_UNAVAILABLE = "upstream_unavailable"


async def _daas(path: str, params: Dict[str, Any], list_key: Optional[str]) -> Dict[str, Any]:
    """The data platform's answer for `path`. `list_key` names a list the answer must carry;
    anything else is 502 rather than a quietly empty screen."""
    if not daas_client.is_configured():
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    try:
        status, body = await daas_client.get_raw(path, params or None)
    except daas_client.DaasError as e:
        logger.warning("ownership DaaS %s failed: %s", path, e)
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    if status == 200 and isinstance(body, dict) and (list_key is None or isinstance(body.get(list_key), list)):
        return body
    logger.warning("ownership DaaS %s answered HTTP %s", path, status)
    raise HTTPException(status_code=502, detail=_UNAVAILABLE)


@router.get("/reaction")
async def ownership_reaction(
    request: Request,
    view: str = Query("all", pattern="^(all|reduced|raised|divergence)$"),
    reaction: str = Query("any", pattern="^(any|strong_positive|neutral|negative)$"),
    status: str = Query("any",
                        pattern="^(any|accumulation|breakout_watch|reversal_watch|distribution_risk|divergence|insufficient_data|none)$"),
    basis: str = Query("any", pattern="^(any|same_source)$"),
    sort: str = Query("inst_delta", pattern="^(inst_delta|ret|vol_ratio|symbol)$"),
    limit: int = Query(100, ge=1, le=500),
) -> Dict[str, Any]:
    """One row per Nifty-500 name with a computable quarterly FII/DII change, set against that
    same quarter's tape. `view=reduced` is the "institutions sold into this" cut and
    `view=divergence` is the "ownership and price disagreed" cut.

    `thresholds` carries the percentiles the reaction label is built from, so the UI prints the
    cut-points instead of asserting them. `coverage` carries the real denominator — the change is
    computable for far fewer names than the universe holds, and `basis` separates a change measured
    within one publisher from one that differences two.
    """
    await get_current_user(request)
    return await _daas("/desk/ownership/reaction", {
        "view": view, "reaction": reaction, "status": status, "basis": basis,
        "sort": sort, "limit": limit,
    }, "rows")
