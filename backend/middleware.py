"""Middleware — rate limiting, env validation, request logging, security headers."""
import os
import time
import logging
import secrets as _stdlib_secrets
from collections import defaultdict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from core.logging_config import (
    get_correlation_id,
    set_request_context,
    reset_request_context,
)

logger = logging.getLogger(__name__)
_req_logger = logging.getLogger("nivesh.access")

# ── Rate Limiter ──

class RateLimitStore:
    """In-memory sliding window rate limiter."""
    def __init__(self):
        self._requests = defaultdict(list)

    def is_allowed(self, key: str, max_requests: int = 60, window_seconds: int = 60) -> bool:
        now = time.time()
        cutoff = now - window_seconds
        # Clean old entries
        self._requests[key] = [t for t in self._requests[key] if t > cutoff]
        if len(self._requests[key]) >= max_requests:
            return False
        self._requests[key].append(now)
        return True


rate_limiter = RateLimitStore()


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for non-API routes
        if not request.url.path.startswith("/api"):
            return await call_next(request)

        # Use session token or IP as rate limit key
        session = request.cookies.get("session_token", "")
        auth = request.headers.get("Authorization", "")
        key = session or auth or request.client.host if request.client else "unknown"

        # Per-path budgets. Numbers reflect typical UI patterns: ChatView
        # mount alone hits /chat/sessions + /chat/messages + /chat/warmup +
        # /copilot/suggested-prompts on every open, ClientSnapshot polls
        # /insights/analysis up to 5×, and a normal session opens the
        # Copilot drawer multiple times — the old 60/min cap collapsed
        # under that load even with no abuse.
        path = request.url.path
        if "/chat/stream" in path:
            max_req = 30  # SSE streams are long-lived, fewer needed
        elif path.endswith("/chat/warmup"):
            # Idempotent fire-and-forget — exempt from limiting so a
            # rapid open-close-open of the drawer doesn't burn the bucket.
            return await call_next(request)
        elif "/chat/" in path or "/insights/" in path:
            max_req = 200
        else:
            max_req = 300

        if not rate_limiter.is_allowed(key, max_requests=max_req, window_seconds=60):
            logger.warning(
                "Rate limit exceeded",
                extra={"path": path, "max_req": max_req, "window_s": 60},
            )
            cid = get_correlation_id() or getattr(
                getattr(request, "state", None), "correlation_id", ""
            )
            import time as _time
            return JSONResponse(
                status_code=429,
                content={
                    "timestamp": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
                    "status": 429,
                    "error": "RATE_LIMIT_ERROR",
                    "code": "RATE-001",
                    "message": "Too many requests. Please wait a moment.",
                    "details": [],
                    "correlationId": cid,
                    "path": path,
                },
            )

        return await call_next(request)


# ── Security Headers ──
# PRD §12 / FR-API: every response sets the OWASP-recommended hardening headers.
# CSP allows Google OAuth (accounts.google.com) and our own origin; everything
# else falls back to default-src 'self'. A per-request nonce is exposed via
# request.state.csp_nonce so route handlers can inline it on bootstrap HTML.

_CSP_DIRECTIVES = (
    "default-src 'self'",
    "script-src 'self' https://accounts.google.com 'nonce-{nonce}'",
    "style-src 'self' 'unsafe-inline'",  # CRA inlines critical CSS
    "img-src 'self' data: https:",
    "connect-src 'self' https://accounts.google.com https://www.googleapis.com",
    "frame-src https://accounts.google.com",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Set OWASP hardening headers on every response.

    HSTS is only set when the request was served over HTTPS (otherwise the
    browser ignores it and we'd just be lying in dev). The CSP nonce is fresh
    per request and surfaced to handlers via ``request.state.csp_nonce``.
    """

    async def dispatch(self, request: Request, call_next):
        nonce = _stdlib_secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce

        response = await call_next(request)

        csp = "; ".join(_CSP_DIRECTIVES).format(nonce=nonce)
        response.headers.setdefault("Content-Security-Policy", csp)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )
        # HSTS only if we're on HTTPS (request.url.scheme reflects whatever
        # the upstream proxy sets via X-Forwarded-Proto when uvicorn runs
        # with --proxy-headers).
        if request.url.scheme == "https":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains; preload",
            )
        return response


# ── Request Logging ──────────────────────────────────────────────────────────
# Logs every HTTP request once at completion with all 14 GCP dashboard fields.
# Runs outermost (after CorrelationMiddleware so correlationId is already set)
# so it measures the true total latency including all inner middleware.

# Admin-prefixed paths are tagged as admin-app; everything else is the main app.
_ADMIN_PREFIXES = ("/api/admin",)


def _classify_application(path: str) -> str:
    for prefix in _ADMIN_PREFIXES:
        if path.startswith(prefix):
            return "admin-app"
    return "nivesh-main-app"


def _extract_trace_id(request: Request) -> str:
    """Parse X-Cloud-Trace-Context: TRACE_ID/SPAN_ID;o=TRACE_TRUE"""
    header = request.headers.get("X-Cloud-Trace-Context", "")
    if header and "/" in header:
        return header.split("/")[0]
    return ""


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Emit one structured access log per request with all required GCP fields.

    Also populates per-request context vars (application, traceId) so that
    every *inner* log call during that request automatically inherits them —
    no need to pass them manually.
    """

    async def dispatch(self, request: Request, call_next):
        start = time.monotonic()
        path = request.url.path
        application = _classify_application(path)
        trace_id = _extract_trace_id(request)
        cid = getattr(getattr(request, "state", None), "correlation_id", "") or get_correlation_id()

        tokens = set_request_context(
            correlation_id=cid,
            trace_id=trace_id,
            application=application,
            endpoint=path,
        )
        try:
            response = await call_next(request)
        except Exception:
            elapsed = int((time.monotonic() - start) * 1000)
            _req_logger.error(
                "%s %s → unhandled exception",
                request.method, path,
                extra={
                    "application": application,
                    "endpoint": path,
                    "httpStatus": 500,
                    "responseTimeMs": elapsed,
                    "correlationId": cid,
                    "traceId": trace_id,
                    "eventType": "REQUEST",
                },
            )
            raise
        finally:
            reset_request_context(tokens)

        elapsed = int((time.monotonic() - start) * 1000)
        status = response.status_code

        # Choose log level based on status code.
        if status >= 500:
            log_fn = _req_logger.error
        elif status >= 400:
            log_fn = _req_logger.warning
        else:
            log_fn = _req_logger.info

        log_fn(
            "%s %s %d (%dms)",
            request.method, path, status, elapsed,
            extra={
                "application": application,
                "endpoint": path,
                "httpStatus": status,
                "responseTimeMs": elapsed,
                "correlationId": cid,
                "traceId": trace_id,
                "eventType": "REQUEST",
            },
        )
        return response


# ── Env Validation ──

def validate_env():
    """Validate required environment variables on startup."""
    required = {
        "MONGO_URL": "MongoDB connection string",
        "DB_NAME": "Database name",
    }
    missing = []
    for key, desc in required.items():
        if not os.environ.get(key):
            missing.append(f"  {key}: {desc}")

    if missing:
        msg = "Missing required environment variables:\n" + "\n".join(missing)
        logger.critical("Startup check failed — missing env vars: %s", missing)
        raise RuntimeError(msg)

    # Warn for optional but important
    if not os.environ.get("EMERGENT_LLM_KEY"):
        logger.warning("EMERGENT_LLM_KEY not set — AI features will not work")

    logger.info("Environment validation passed")
