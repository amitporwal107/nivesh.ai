"""Middleware — rate limiting, env validation, request logging."""
import os
import time
import logging
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

        # Higher limit for AI endpoints (they're slower)
        if "/chat/stream" in request.url.path:
            max_req = 30  # SSE streams are long-lived, fewer needed
        elif "/chat/" in request.url.path or "/insights/" in request.url.path:
            max_req = 60
        else:
            max_req = 200

        if not rate_limiter.is_allowed(key, max_requests=max_req, window_seconds=60):
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please wait a moment."},
            )

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
        logger.critical(msg)
        raise RuntimeError(msg)

    # Warn for optional but important
    if not os.environ.get("EMERGENT_LLM_KEY"):
        logger.warning("EMERGENT_LLM_KEY not set — AI features will not work")

    logger.info("Environment validation passed")
