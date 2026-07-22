"""Middleware — rate limiting, env validation, request logging, security headers."""
import os
import re
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
    set_session_capture,
    reset_session_capture,
)
from services import session_log_store, issue_intake

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

    def current_count(self, key: str, window_seconds: int = 60) -> int:
        """Return the number of requests in the current window (without modifying state)."""
        now = time.time()
        cutoff = now - window_seconds
        return sum(1 for t in self._requests[key] if t > cutoff)


rate_limiter = RateLimitStore()


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for non-API routes
        if not request.url.path.startswith("/api"):
            return await call_next(request)

        # Use session token or IP as rate limit identity.
        # NOTE: behind Cloudflare→nginx→uvicorn, request.client.host is the proxy
        # hop (identical for every visitor), which would collapse all anonymous
        # logins into ONE bucket — the global auth-strict 5/min budget would then
        # be shared platform-wide, so a handful of concurrent sign-ins 429s
        # everyone. Resolve the true client IP from Cloudflare's header, falling
        # back to the left-most X-Forwarded-For entry, then the socket peer.
        session = request.cookies.get("session_token", "")
        fwd = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "")
        client_ip = fwd.split(",")[0].strip() or (request.client.host if request.client else "")
        # SECURITY: never key the limiter on the raw Authorization header — it is
        # unvalidated and fully caller-controlled, so an attacker could send a unique
        # junk Bearer per request to get a fresh bucket and defeat the per-IP
        # brute-force budget. Use the session cookie if present, else the resolved
        # client IP (so unauthenticated login attempts are limited per client IP).
        identity = (session or client_ip) or "unknown"

        # Per-category budgets (fintech-appropriate):
        #   Auth     →   5/min  (brute-force protection on login)
        #   Admin    →  10/min  (low-traffic management plane)
        #   Chat/SSE →  30/min  (SSE streams are long-lived)
        #   Analytics→  30/min  (compute-heavy; AI-backed)
        #   Portfolio→  100/min (dashboard interactions)
        #   Chat     →  200/min (general chat, non-streaming)
        #   Insights →  200/min (read-heavy but cached)
        #   Default  →  200/min (catch-all)
        path = request.url.path
        if "/chat/stream" in path:
            category, max_req = "chat-stream", 30   # SSE streams are long-lived, fewer needed
        elif path.endswith("/chat/warmup"):
            # Idempotent fire-and-forget — exempt from limiting so a
            # rapid open-close-open of the drawer doesn't burn the bucket.
            return await call_next(request)
        elif path in ("/api/auth/me", "/api/auth/google-client-id"):
            category, max_req = "auth-session", 60   # Read-only session checks — no brute-force risk
        elif path.startswith("/api/auth/"):
            category, max_req = "auth-strict", 5    # Strict: protects login/oauth from brute-force
        elif path.startswith("/api/admin/"):
            category, max_req = "admin", 10   # Management plane — low expected volume
        elif "/goals/" in path or "/scenarios/" in path or "/analytics/" in path:
            category, max_req = "analytics", 30   # Compute-heavy or AI-backed analytics
        elif path.startswith("/api/portfolio/") or path.startswith("/api/portfolios"):
            category, max_req = "portfolio", 100  # Dashboard holdings/enriched calls
        elif "/chat/" in path or "/insights/" in path:
            category, max_req = "chat", 200  # General chat + cached insight reads
        else:
            category, max_req = "default", 200  # Default for all other /api/* paths

        # Bucket per (identity, category). A single shared bucket would let
        # unrelated traffic (e.g. dashboard portfolio calls) burn the budget of
        # a low-limit category, so the first sign-in POST /api/auth/google (5/min)
        # would 429 because earlier /auth/me + portfolio calls already filled it.
        # Segmenting by category means each limit only counts its own traffic.
        key = f"{identity}:{category}"

        allowed = rate_limiter.is_allowed(key, max_requests=max_req, window_seconds=60)
        remaining = max(0, max_req - rate_limiter.current_count(key, window_seconds=60))

        if not allowed:
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
                headers={
                    "X-RateLimit-Limit": str(max_req),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": "60",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(max_req)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


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


# ── Opt-in per-session log capture (Settings → Logs & Diagnostics) ────────────
# The frontend sends this header on every request while a user has logging on.
DEBUG_SESSION_HEADER = "X-Nivesh-Debug-Session"
_SID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _valid_debug_sid(raw: str | None) -> str | None:
    """Return the debug-session id if it looks well-formed, else None."""
    if raw and _SID_RE.match(raw):
        return raw
    return None


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

        # Opt-in per-session log capture: only requests carrying a well-formed
        # X-Nivesh-Debug-Session header allocate a buffer; everything below
        # (the route + this middleware's access log) is captured into it and
        # flushed to Redis at the end. Near-zero cost for the common (no header) case.
        sid = _valid_debug_sid(request.headers.get(DEBUG_SESSION_HEADER))
        capture_buf: list | None = [] if sid else None
        capture_token = set_session_capture(capture_buf) if capture_buf is not None else None

        try:
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
        finally:
            # Flush the captured records (if any) to Redis. Best-effort: a debug
            # feature must never affect the response, so swallow all errors here.
            if capture_token is not None:
                reset_session_capture(capture_token)
                if capture_buf:
                    try:
                        await session_log_store.append(sid, capture_buf)
                    except Exception:  # noqa: BLE001
                        pass
                    # Auto-file a work issue for any server-side error/exception
                    # captured this request (deduped by sig; best-effort).
                    try:
                        errs = [e for e in capture_buf
                                if str(e.get("severity", "")).upper() in ("ERROR", "CRITICAL")]
                        if errs:
                            await issue_intake.intake_from_server_entries(errs, application=application)
                    except Exception:  # noqa: BLE001
                        pass


# ── JSON Body Size Limit ──────────────────────────────────────────────────────
# Rejects JSON requests whose Content-Length exceeds MAX_JSON_BODY_BYTES before
# the body is read. Protects against OOM from large payloads on non-upload routes.
# File-upload endpoints (/api/portfolio/upload, /api/cas/*) are explicitly
# excluded because they have their own per-endpoint size enforcement.

_MAX_JSON_BODY_BYTES = int(os.environ.get("MAX_JSON_BODY_BYTES", str(1 * 1024 * 1024)))  # 1 MB

# Prefixes that handle their own size validation — skip this middleware for them.
_UPLOAD_PREFIXES = (
    "/api/portfolio/upload",
    "/api/portfolio/upload-raw",
    "/api/cas/uploads",
    "/api/casparser",
)


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject JSON request bodies larger than MAX_JSON_BODY_BYTES (default 1 MB).

    Only applies to requests with a JSON content-type on ``/api/*`` routes.
    Upload endpoints are excluded — they enforce their own limits via
    ``helpers.upload_validation.validate_upload``.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Only guard /api/* JSON requests; skip uploads and non-API paths.
        if not path.startswith("/api"):
            return await call_next(request)
        if any(path.startswith(pfx) for pfx in _UPLOAD_PREFIXES):
            return await call_next(request)

        content_type = request.headers.get("content-type", "")
        if "application/json" not in content_type:
            return await call_next(request)

        # Fast path: Content-Length header present — reject before reading body.
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > _MAX_JSON_BODY_BYTES:
                    logger.warning(
                        "JSON body too large",
                        extra={
                            "path": path,
                            "content_length": content_length,
                            "limit": _MAX_JSON_BODY_BYTES,
                        },
                    )
                    return JSONResponse(
                        status_code=413,
                        content={
                            "status": 413,
                            "error": "PAYLOAD_TOO_LARGE",
                            "code": "VAL-004",
                            "message": f"Request body exceeds the {_MAX_JSON_BODY_BYTES // 1024} KB limit.",
                            "details": [],
                        },
                    )
            except ValueError:
                pass  # Malformed Content-Length — let the body read handle it.

        return await call_next(request)


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


# ── CSRF protection (A4) ──────────────────────────────────────────────────
# Mirrors the CORS allowlist: explicit CORS_ORIGINS when set, else the app's
# own domain families + localhost, plus the native Capacitor origins.
_CSRF_ORIGIN_RE = re.compile(
    r"^https?://(localhost(:\d+)?|([a-z0-9-]+\.)*(niveshcopilot|emergentagent)\.com(:\d+)?)$"
)
_CSRF_NATIVE = {"https://localhost", "capacitor://localhost"}


def _csrf_origin_allowed(origin: str) -> bool:
    env = os.environ.get("CORS_ORIGINS", "").strip()
    if env and env != "*":
        allowed = {o.strip() for o in env.split(",") if o.strip()} | _CSRF_NATIVE
        return origin in allowed
    return origin in _CSRF_NATIVE or bool(_CSRF_ORIGIN_RE.match(origin))


class CsrfProtectMiddleware(BaseHTTPMiddleware):
    """Block CSRF on cookie-authenticated, state-changing /api requests.

    If a request carries our session cookie AND uses a mutating method, any
    browser-supplied Origin must be in the allowlist (browsers always send
    Origin on cross-site POST/PUT/PATCH/DELETE, so a forged cross-site request
    is caught). Bearer-authenticated calls (mobile) carry no cookie and are not
    a CSRF vector, so they pass through. Safe methods and no-cookie requests
    pass through. This is the CSRF defence while the session cookie remains
    SameSite=None; a SameSite=Lax flip is a separate, mobile-tested change.
    """

    _SAFE = {"GET", "HEAD", "OPTIONS", "TRACE"}

    async def dispatch(self, request: Request, call_next):
        if (
            request.url.path.startswith("/api")
            and request.method not in self._SAFE
            and request.cookies.get("session_token")
        ):
            origin = request.headers.get("origin", "")
            if origin and not _csrf_origin_allowed(origin):
                logger.warning("CSRF: blocked %s %s from origin %s",
                               request.method, request.url.path, origin)
                return JSONResponse(
                    {"error": "CSRF_BLOCKED", "message": "Cross-origin request rejected."},
                    status_code=403,
                )
        return await call_next(request)
