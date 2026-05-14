"""Correlation ID middleware and helpers.

Every inbound HTTP request gets a unique correlation ID:

* If the client sends ``X-Correlation-ID``, that value is reused (allows
  end-to-end tracing across services / browser → API).
* Otherwise a new UUID4 hex string is generated.

The ID is stored in an async context variable so it is available to all
log statements executed during that request without being passed around
explicitly.

The middleware also stamps the ID back onto every response in the
``X-Correlation-ID`` header so callers can correlate log lines to
responses.
"""
from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from core.logging_config import set_correlation_id, reset_correlation_id

HEADER_NAME = "X-Correlation-ID"


def _new_id() -> str:
    return uuid.uuid4().hex


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Attach a correlation ID to every request/response cycle."""

    async def dispatch(self, request: Request, call_next) -> Response:
        cid = request.headers.get(HEADER_NAME) or _new_id()
        # Expose on request.state so route handlers can read it directly.
        request.state.correlation_id = cid

        token = set_correlation_id(cid)
        try:
            response = await call_next(request)
        finally:
            reset_correlation_id(token)

        response.headers[HEADER_NAME] = cid
        return response
