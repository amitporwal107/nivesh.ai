"""Cross-cutting middleware: rate-limit headers, request-id, usage log."""
from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from nidp.shared.storage.pg import get_pool


logger = logging.getLogger(__name__)


_LOG_REQUESTS = os.environ.get("NIDP_DAAS_LOG_REQUESTS", "1") not in ("0", "false", "False", "")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Stamps each request with an id, attaches rate-limit headers from
    the auth dependency's decision, and (when enabled) writes a row to
    nidp.daas_usage_log. Failures here MUST NOT take the API down."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        t0 = time.perf_counter()
        response: Optional[Response] = None
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        finally:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            try:
                # Headers — every response, including errors thrown from
                # auth (which sets the decision before raising).
                if response is not None:
                    response.headers["X-Request-Id"] = request_id
                    response.headers["X-Service"] = "nidp-daas-api"
                    decision = getattr(request.state, "daas_decision", None)
                    if decision is not None:
                        response.headers["X-RateLimit-Limit"] = str(decision.limit_rpm)
                        response.headers["X-RateLimit-Remaining"] = str(max(decision.remaining_rpm, 0))
                        response.headers["X-RateLimit-Reset"] = str(decision.reset_seconds)
                        if decision.daily_quota is not None:
                            response.headers["X-Daily-Limit"] = str(decision.daily_quota)
                            response.headers["X-Daily-Remaining"] = str(
                                decision.daily_remaining if decision.daily_remaining is not None else 0
                            )
                # Usage log — best-effort, never block the response.
                if _LOG_REQUESTS:
                    await _log_request(request, status_code, latency_ms)
            except Exception as e:                                    # noqa: BLE001
                logger.warning("daas-api: middleware tail failure: %s", e)
        return response  # type: ignore[return-value]


async def _log_request(request: Request, status_code: int, latency_ms: int) -> None:
    rec = getattr(request.state, "daas_key", None)
    if rec is None:
        return    # unauthenticated requests aren't logged here
    try:
        pool = await get_pool()
        client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
            request.client.host if request.client else None
        )
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO nidp.daas_usage_log
                    (key_id, method, path, query_string,
                     status_code, latency_ms, client_ip, user_agent)
                VALUES ($1, $2, $3, $4, $5, $6, $7::inet, $8)
                """,
                rec.key_id,
                request.method,
                request.url.path,
                request.url.query[:500] if request.url.query else None,
                status_code,
                latency_ms,
                client_ip,
                (request.headers.get("user-agent") or "")[:255],
            )
        if status_code >= 400:
            await _bump_error(rec.key_id)
    except Exception as e:                                            # noqa: BLE001
        logger.debug("daas-api: usage log insert failed: %s", e)


async def _bump_error(key_id: str) -> None:
    try:
        pool = await get_pool()
        from datetime import date as _date
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE nidp.daas_daily_usage
                   SET error_count = error_count + 1
                 WHERE key_id = $1 AND day = $2
                """,
                key_id, _date.today(),
            )
    except Exception:                                                  # noqa: BLE001
        pass
