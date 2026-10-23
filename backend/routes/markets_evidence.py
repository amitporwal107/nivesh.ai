"""Evidence & Validation — forwarded to the data platform's /v1/desk/evidence/post-disclosure-study
(nidp/services/daas_api/routers/evidence_validation.py).

    GET /api/markets/evidence/post-disclosure-study   the frozen, pre-registered post-disclosure
                                                       forward-returns study: its contract and its
                                                       real, already-run result, one row per horizon

This is a RESEARCH ARTIFACT, not a product feature, and this layer adds nothing and derives
nothing: it forwards to the data platform and passes the answer through unchanged. The study's
verdict is INCONCLUSIVE and stays the loud, primary fact — 10 formation quarters against a
pre-registered review floor of 12, a 20-session spread whose 95% CI straddles zero, and a sign that
is not robust across three reasonable specifications of the same grouping variable. The reasons are
in the upstream router's docstring.

No predictive score, no ranking, no buy/sell framing is forwarded, because none exists: this
reports what was tested and what the result was, nothing more. No Nifty 500 TRI row is forwarded
either — this warehouse holds no total-return index, and the study's estimand is market-neutral by
construction, so none is needed.

Signed-in users only, like the rest of /api/markets. Errors: a data platform that is not
configured, unreachable or failing is 502 upstream_unavailable — never a cached or fabricated
result, because a plausible-looking fallback here would misstate a locked research finding.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from deps import get_current_user
from services.copilot_tools import daas_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/markets/evidence", tags=["markets-evidence"])

_UNAVAILABLE = "upstream_unavailable"


@router.get("/post-disclosure-study")
async def post_disclosure_study(request: Request) -> Dict[str, Any]:
    """The pre-registered NIDP-SHP-FWD-001 study: its frozen contract (study period, quarters,
    horizons, hurdle, cost schedule) and its real, already-run result (`rows`, one per horizon),
    with the INCONCLUSIVE verdict carried at the top level so the UI never has to derive it."""
    await get_current_user(request)
    if not daas_client.is_configured():
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    try:
        status, body = await daas_client.get_raw("/desk/evidence/post-disclosure-study", None)
    except daas_client.DaasError as e:
        logger.warning("evidence DaaS post-disclosure-study failed: %s", e)
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    if status == 200 and isinstance(body, dict) and isinstance(body.get("rows"), list):
        return body
    logger.warning("evidence DaaS post-disclosure-study answered HTTP %s", status)
    raise HTTPException(status_code=502, detail=_UNAVAILABLE)
