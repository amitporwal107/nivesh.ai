"""Request metrics middleware (T4.2).

Emits one structured log line per request with method, path, status, and
latency_ms. Downstream this becomes a Cloud Logging log-based metric — no
Prometheus exporter dependency required.

The log line is tagged ``eventType=HTTP_REQUEST`` so log-based metric filters
can pick it up cleanly.
"""
from __future__ import annotations

import logging
import time
from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = logging.getLogger(__name__)


class RequestMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start = time.perf_counter()
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            log.exception(
                "request failed",
                extra={
                    "eventType": "HTTP_REQUEST",
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": 500,
                    "latency_ms": elapsed_ms,
                },
            )
            raise

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        log.info(
            "request",
            extra={
                "eventType": "HTTP_REQUEST",
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "latency_ms": elapsed_ms,
            },
        )
        return response
