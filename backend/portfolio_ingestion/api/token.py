"""POST /api/casparser/token — short-lived SDK access token.

The frontend hits this once before opening the @cas-parser/connect widget
so the API key never leaves the server. PRD §4.2.
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict

from ..clients.casparser import CasparserUpstreamError, mint

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/casparser", tags=["casparser"])


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access_token: str
    expires_at: str          # ISO-8601 UTC
    stub: bool


@router.post(
    "/token",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
)
async def issue_token(
    x_user_external_id: Annotated[str, Header(alias="X-User-External-Id")],
) -> TokenResponse:
    try:
        token = await mint()
    except CasparserUpstreamError as e:
        log.warning(
            "token mint failed",
            extra={"eventType": "CASPARSER_TOKEN_HTTP_FAIL",
                   "external_id": x_user_external_id},
        )
        raise HTTPException(status_code=502, detail=str(e)) from e

    log.info(
        "casparser token issued",
        extra={
            "eventType": "CASPARSER_TOKEN_ISSUED",
            "external_id": x_user_external_id,
            "stub": token.stub,
        },
    )
    return TokenResponse(
        access_token=token.access_token,
        expires_at=token.expires_at.isoformat(),
        stub=token.stub,
    )
