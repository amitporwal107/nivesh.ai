"""Middleware — rate limiting, env validation, request logging, security headers."""
import os
import time
import logging
import secrets as _stdlib_secrets
from collections import defaultdict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

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
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please wait a moment."},
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
        logger.critical(msg)
        raise RuntimeError(msg)

    # Warn for optional but important
    if not os.environ.get("EMERGENT_LLM_KEY"):
        logger.warning("EMERGENT_LLM_KEY not set — AI features will not work")

    logger.info("Environment validation passed")
