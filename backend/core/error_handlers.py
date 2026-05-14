"""Centralized exception handlers for FastAPI.

Registers handlers for:

1. NiveshException subclasses   → domain-specific HTTP status + error code
2. HTTPException                → preserve status, wrap in standard schema
3. RequestValidationError       → 422 with per-field detail
4. Generic Exception            → 500 SYS-001 (stack trace logged, safe msg
                                   returned to client)

Every response uses the standard error envelope:

    {
      "timestamp":     "2026-05-14T10:30:00.000Z",
      "status":        400,
      "error":         "VALIDATION_ERROR",
      "code":          "VAL-001",
      "message":       "Invalid request",
      "details":       [{"field": "email", "message": "Email is invalid"}],
      "correlationId": "a1b2c3d4",
      "path":          "/api/users"
    }

Wire up by calling ``register_error_handlers(app)`` in server.py.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.exceptions import (
    AuthenticationException,
    AuthorizationException,
    BusinessException,
    IntegrationException,
    NiveshException,
    RateLimitException,
    ResourceNotFoundException,
    SystemException,
    ValidationException,
)
from core.logging_config import get_correlation_id

logger = logging.getLogger(__name__)

# Map domain exception type → human-readable "error" label for the envelope.
_DOMAIN_LABELS: dict[type[NiveshException], str] = {
    ValidationException: "VALIDATION_ERROR",
    BusinessException: "BUSINESS_ERROR",
    ResourceNotFoundException: "NOT_FOUND",
    IntegrationException: "INTEGRATION_ERROR",
    AuthenticationException: "AUTHENTICATION_ERROR",
    AuthorizationException: "AUTHORIZATION_ERROR",
    RateLimitException: "RATE_LIMIT_ERROR",
    SystemException: "SYSTEM_ERROR",
}

# Default HTTP status → label for wrapped HTTPExceptions.
_HTTP_LABELS: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "UNPROCESSABLE_ENTITY",
    429: "TOO_MANY_REQUESTS",
    500: "INTERNAL_SERVER_ERROR",
    502: "BAD_GATEWAY",
    503: "SERVICE_UNAVAILABLE",
    504: "GATEWAY_TIMEOUT",
}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def _envelope(
    request: Request,
    *,
    status: int,
    error: str,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    cid = get_correlation_id() or getattr(
        getattr(request, "state", None), "correlation_id", ""
    )
    return JSONResponse(
        status_code=status,
        content={
            "timestamp": _now_iso(),
            "status": status,
            "error": error,
            "code": code,
            "message": message,
            "details": details or [],
            "correlationId": cid,
            "path": str(request.url.path),
        },
    )


# ── Handlers ─────────────────────────────────────────────────────────────────

async def _handle_nivesh_exception(
    request: Request, exc: NiveshException
) -> JSONResponse:
    label = _DOMAIN_LABELS.get(type(exc), "DOMAIN_ERROR")

    # Only log at ERROR for 5xx; WARN for 4xx.  Inner layers must NOT log
    # before re-raising, so each error is logged exactly once here.
    if exc.http_status >= 500:
        logger.error(
            "Domain error: %s",
            exc.message,
            exc_info=exc.__cause__ or exc,
            extra={
                "error_code": exc.code,
                "http_status": exc.http_status,
                "path": str(request.url.path),
                **exc.context,
            },
        )
    else:
        logger.warning(
            "Client error: %s",
            exc.message,
            extra={
                "error_code": exc.code,
                "http_status": exc.http_status,
                "path": str(request.url.path),
                **exc.context,
            },
        )

    return _envelope(
        request,
        status=exc.http_status,
        error=label,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


async def _handle_http_exception(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    label = _HTTP_LABELS.get(exc.status_code, "HTTP_ERROR")
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)

    if exc.status_code >= 500:
        logger.error(
            "HTTP error %s: %s",
            exc.status_code,
            detail,
            extra={"path": str(request.url.path)},
        )
    # 4xx are expected; no server-side log needed (rate limiter already logs).

    # Map HTTP status to a domain-ish code for uniformity.
    _CODE_MAP = {
        400: "VAL-001", 401: "AUTH-001", 403: "AUTHZ-001",
        404: "RES-001", 409: "BIZ-002", 422: "VAL-001",
        429: "RATE-001", 500: "SYS-001", 502: "INT-001",
        503: "INT-001", 504: "INT-002",
    }
    code = _CODE_MAP.get(exc.status_code, "SYS-000")

    return _envelope(
        request,
        status=exc.status_code,
        error=label,
        code=code,
        message=detail,
    )


async def _handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    details = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", []) if p != "body")
        details.append({"field": loc or "request", "message": err.get("msg", "")})

    logger.warning(
        "Request validation failed",
        extra={"path": str(request.url.path), "error_count": len(details)},
    )

    return _envelope(
        request,
        status=422,
        error="VALIDATION_ERROR",
        code="VAL-001",
        message="Request validation failed",
        details=details,
    )


async def _handle_unhandled_exception(
    request: Request, exc: Exception
) -> JSONResponse:
    logger.error(
        "Unhandled exception on %s",
        request.url.path,
        exc_info=exc,
        extra={"path": str(request.url.path)},
    )
    return _envelope(
        request,
        status=500,
        error="SYSTEM_ERROR",
        code="SYS-001",
        message="An unexpected error occurred. Please try again or contact support.",
    )


# ── Registration ──────────────────────────────────────────────────────────────

def register_error_handlers(app: FastAPI) -> None:
    """Wire all handlers into a FastAPI application."""
    app.add_exception_handler(NiveshException, _handle_nivesh_exception)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, _handle_unhandled_exception)
