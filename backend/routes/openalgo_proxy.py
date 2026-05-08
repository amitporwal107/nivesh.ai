"""Reverse-proxy `/api/openalgo/*` to the Nivesh-hosted OpenAlgo instance.

End-users need to reach the OpenAlgo dashboard from a browser to sign in,
connect their broker, and copy a read-only API key. OpenAlgo binds to
127.0.0.1:5000 (internal-only); the Emergent preview ingress only exposes
8001 (Nivesh backend) and 3000 (frontend) to the public hostname.

This module exposes OpenAlgo's HTTP surface under the same public host at
`/api/openalgo/*`. It mirrors method, body, query string, and most
headers; OpenAlgo's WSGI `DispatcherMiddleware` (see openalgo/app.py)
mounts the Flask app at the same prefix so `url_for()` and redirects
render with `/api/openalgo/...`.

Tricky bit: OpenAlgo's React frontend (Vite-built `frontend/dist/`) emits
**hardcoded absolute paths** like `/assets/index-xxx.js`, `/auth/csrf-
token`, `/api/v1/funds`, `/favicon.ico`. Flask's `SCRIPT_NAME` only
prefixes Flask-generated URLs — it can't touch these compiled string
literals. So this proxy also **rewrites** those known prefixes in `text/*`
and `application/javascript` responses on the way back to the browser.

WebSocket endpoints (port 8765, plus Flask-SocketIO at `/socket.io/`)
are NOT proxied — the broker-connect / API-key minting flow is
entirely HTTP and doesn't need real-time streams.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/openalgo")

# Singleton-instance prefix (port 5000, supervisor-managed). Browser-
# served HTML/JS rewrites against this prefix.
PREFIX = "/api/openalgo"

# Per-account-instance prefix. The instance manager allocates a unique
# port per `broker_account_id`; this proxy resolves that port at request
# time and forwards. Browser-side rewrites bake `/api/openalgo/c/<id>/`
# in front of OpenAlgo's hardcoded `/assets/`, `/api/v1/`, `/auth/` etc.
PER_ACCOUNT_PREFIX_RE = "c/{account_id}"

# Hop-by-hop headers MUST NOT be forwarded — they apply to a single
# transport hop and can confuse the proxy chain.
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
    # Let httpx + Starlette set these per response.
    "content-encoding", "content-length",
    # Prevent the upstream Host header from leaking to OpenAlgo.
    "host",
}

_REWRITABLE_TYPES = (
    "text/html", "text/css", "text/javascript", "text/plain",
    "application/javascript", "application/json", "application/xml",
)

_PROXY_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)


def _hosted_url() -> str:
    """Resolve the internal OpenAlgo URL (singleton instance) from secrets."""
    try:
        from helpers import secrets as _s
        return (_s.get("OPENALGO_BASE_URL") or "").strip().rstrip("/")
    except Exception:  # noqa: BLE001
        import os as _os
        return (_os.environ.get("OPENALGO_BASE_URL") or "").strip().rstrip("/")


async def _instance_url(account_id: str) -> str:
    """Look up the per-account instance's base URL via the manager.
    Empty string when the row is missing or the process died.
    """
    try:
        from deps import db
        from services import openalgo_instance_manager as _mgr
        return (await _mgr.get_base_url(db, account_id)) or ""
    except Exception as e:  # noqa: BLE001
        logger.warning("openalgo proxy: instance lookup failed: %s", e)
        return ""


def _build_rewrites(prefix: str) -> list[tuple[bytes, bytes]]:
    """Asset-path rewrite table parameterised by the public-facing
    prefix. Singleton uses `/api/openalgo`; per-account uses
    `/api/openalgo/c/<account_id>`. Same shape, different prefix.
    """
    p = prefix.encode("ascii")
    return [
        (b'"/api/v1/', b'"' + p + b'/api/v1/'),
        (b"'/api/v1/", b"'" + p + b'/api/v1/'),
        (b'"/api/websocket/', b'"' + p + b'/api/websocket/'),
        (b"'/api/websocket/", b"'" + p + b'/api/websocket/'),
        (b'"/auth/', b'"' + p + b'/auth/'),
        (b"'/auth/", b"'" + p + b'/auth/'),
        (b'"/assets/', b'"' + p + b'/assets/'),
        (b"'/assets/", b"'" + p + b'/assets/'),
        (b'"/static/', b'"' + p + b'/static/'),
        (b"'/static/", b"'" + p + b'/static/'),
        (b'href="/favicon.ico"', b'href="' + p + b'/favicon.ico"'),
        (b'href="/apple-touch-icon.png"', b'href="' + p + b'/apple-touch-icon.png"'),
        (b'"/socket.io/', b'"' + p + b'/socket.io/'),
        (b"'/socket.io/", b"'" + p + b'/socket.io/'),
    ]


# Singleton-instance rewrite table — built once at import (now that
# `_build_rewrites` is defined above). Per-account variants are built
# dynamically per request via `_build_rewrites(<prefix>)`.
_BODY_REWRITES: list[tuple[bytes, bytes]] = _build_rewrites(PREFIX)


def _filter_request_headers(req: Request) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in req.headers.items():
        if k.lower() in _HOP_BY_HOP:
            continue
        out[k] = v
    fwd = req.client.host if req.client else ""
    if fwd:
        out["X-Forwarded-For"] = fwd
    out["X-Forwarded-Proto"] = req.url.scheme
    out["X-Forwarded-Host"] = req.headers.get("host", "")
    # Critical for OpenAlgo's url_for / redirects: Werkzeug honours
    # SCRIPT_NAME in the WSGI env. Flask-SocketIO + DispatcherMiddleware
    # in OpenAlgo already sets SCRIPT_NAME via the dispatcher — we just
    # ensure the upstream sees the prefix in the request line.
    return out


def _filter_response_headers(
    headers: httpx.Headers, prefix: str = PREFIX,
) -> list[tuple[bytes, bytes]]:
    out: list[tuple[bytes, bytes]] = []
    for k, v in headers.raw:
        name = k.decode("latin-1").lower()
        if name in _HOP_BY_HOP:
            continue
        # Rewrite Location for absolute paths that lack the prefix —
        # Flask's url_for usually produces prefixed URLs (because of
        # DispatcherMiddleware) but a few code paths build redirects
        # manually with a leading slash.
        if name == "location":
            try:
                v_str = v.decode("latin-1")
                if v_str.startswith("/") and not v_str.startswith(prefix + "/") and v_str != prefix:
                    v = (prefix + v_str).encode("latin-1")
            except Exception:  # noqa: BLE001
                pass
        out.append((k, v))
    return out


def _rewrite_body(
    body: bytes, content_type: str,
    rewrites: Optional[list[tuple[bytes, bytes]]] = None,
) -> bytes:
    """Inject prefix into hardcoded absolute paths inside a textual
    response body. No-op for binary types (images, fonts).
    """
    if not body:
        return body
    ct = (content_type or "").lower().split(";", 1)[0].strip()
    if not any(ct.startswith(p) for p in _REWRITABLE_TYPES):
        return body
    table = rewrites if rewrites is not None else _BODY_REWRITES
    out = body
    for needle, repl in table:
        if needle in out:
            out = out.replace(needle, repl)
    return out


@router.api_route(
    "/c/{account_id}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
)
async def proxy_to_per_account(
    account_id: str, path: str, request: Request,
) -> Response:
    """Forward to the per-account OpenAlgo subprocess on its allocated port."""
    base = await _instance_url(account_id)
    if not base:
        return Response(
            content=b"OpenAlgo instance for this broker connection is not running. Re-connect the broker.",
            status_code=503,
            media_type="text/plain",
        )

    public_prefix = f"{PREFIX}/c/{account_id}"
    upstream_url = f"{base}{public_prefix}/{path}"
    qs = request.url.query
    if qs:
        upstream_url = f"{upstream_url}?{qs}"

    body: Optional[bytes] = None
    if request.method not in ("GET", "HEAD"):
        body = await request.body()

    try:
        async with httpx.AsyncClient(
            follow_redirects=False, timeout=_PROXY_TIMEOUT,
        ) as client:
            upstream = await client.request(
                request.method,
                upstream_url,
                headers=_filter_request_headers(request),
                content=body,
            )
    except httpx.ConnectError as e:
        logger.warning("openalgo per-account proxy: connect failed: %s", e)
        return Response(
            content=b"OpenAlgo instance unreachable.", status_code=502,
            media_type="text/plain",
        )
    except httpx.TimeoutException:
        return Response(
            content=b"OpenAlgo timed out.", status_code=504,
            media_type="text/plain",
        )

    rewrites = _build_rewrites(public_prefix)
    rewritten = _rewrite_body(
        upstream.content, upstream.headers.get("content-type", ""), rewrites,
    )
    resp = Response(content=rewritten, status_code=upstream.status_code)
    for name_b, val_b in _filter_response_headers(upstream.headers, public_prefix):
        resp.raw_headers.append((name_b, val_b))
    return resp


@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
)
async def proxy_to_openalgo(path: str, request: Request) -> Response:
    base = _hosted_url()
    if not base:
        return Response(
            content=b"OpenAlgo is not configured for this environment.",
            status_code=503,
            media_type="text/plain",
        )

    # Forward to OpenAlgo with the SAME prefix the browser used.
    # OpenAlgo's WSGI DispatcherMiddleware strips it on entry, Flask serves
    # the route, and url_for reattaches it on the way out.
    upstream_url = f"{base}{PREFIX}/{path}"
    qs = request.url.query
    if qs:
        upstream_url = f"{upstream_url}?{qs}"

    body: Optional[bytes] = None
    if request.method not in ("GET", "HEAD"):
        body = await request.body()

    try:
        async with httpx.AsyncClient(
            follow_redirects=False, timeout=_PROXY_TIMEOUT,
        ) as client:
            upstream = await client.request(
                request.method,
                upstream_url,
                headers=_filter_request_headers(request),
                content=body,
            )
    except httpx.ConnectError as e:
        logger.warning("openalgo proxy: connect failed: %s", e)
        return Response(
            content=b"OpenAlgo is unreachable.", status_code=502,
            media_type="text/plain",
        )
    except httpx.TimeoutException:
        return Response(
            content=b"OpenAlgo timed out.", status_code=504,
            media_type="text/plain",
        )

    rewritten = _rewrite_body(
        upstream.content, upstream.headers.get("content-type", ""),
    )
    resp = Response(content=rewritten, status_code=upstream.status_code)
    for name_b, val_b in _filter_response_headers(upstream.headers):
        resp.raw_headers.append((name_b, val_b))
    return resp


@router.get("", include_in_schema=False)
async def _root_redirect() -> Response:
    return RedirectResponse(url="/api/openalgo/")
