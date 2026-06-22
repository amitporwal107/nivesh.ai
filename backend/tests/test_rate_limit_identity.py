"""RateLimitMiddleware identity resolution.

Regression for the Gmail-login "Too many requests" bug: behind
Cloudflare→nginx→uvicorn, request.client.host is the proxy hop and is identical
for every visitor, so all anonymous logins collapsed into ONE auth-strict bucket
(5/min) shared platform-wide. Identity must instead derive from the real client
IP (CF-Connecting-IP / X-Forwarded-For), so each user gets an independent bucket.
"""
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from middleware import RateLimitMiddleware, rate_limiter


def _build_client():
    async def google(request):  # POST /api/auth/google → auth-strict, 5/min
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/api/auth/google", google, methods=["POST"])])
    app.add_middleware(RateLimitMiddleware)
    return TestClient(app)


def setup_function(_):
    # The limiter is a process-global; isolate each test.
    rate_limiter._requests.clear()


def test_auth_strict_bucket_isolated_per_real_client_ip():
    """Each Cloudflare client IP gets its own 5/min auth-strict budget."""
    client = _build_client()

    # IP A burns its full auth-strict budget (5/min), 6th request is throttled.
    for i in range(5):
        r = client.post("/api/auth/google", headers={"CF-Connecting-IP": "1.1.1.1"})
        assert r.status_code == 200, f"request {i} unexpectedly throttled"
    throttled = client.post("/api/auth/google", headers={"CF-Connecting-IP": "1.1.1.1"})
    assert throttled.status_code == 429
    assert throttled.json()["code"] == "RATE-001"

    # A DIFFERENT client IP is unaffected — buckets are not shared. This is the
    # exact case that was broken when identity collapsed to the proxy IP.
    other = client.post("/api/auth/google", headers={"CF-Connecting-IP": "2.2.2.2"})
    assert other.status_code == 200


def test_x_forwarded_for_leftmost_is_used_when_no_cf_header():
    """Falls back to the left-most X-Forwarded-For entry (the real client)."""
    client = _build_client()

    for _ in range(5):
        assert client.post(
            "/api/auth/google", headers={"X-Forwarded-For": "9.9.9.9, 10.0.0.1"}
        ).status_code == 200
    assert client.post(
        "/api/auth/google", headers={"X-Forwarded-For": "9.9.9.9, 10.0.0.1"}
    ).status_code == 429
    # Different real client, same proxy hop → still independent.
    assert client.post(
        "/api/auth/google", headers={"X-Forwarded-For": "8.8.8.8, 10.0.0.1"}
    ).status_code == 200
