"""Unit tests for the CASParser token-mint client.

Uses httpx.MockTransport so the test is fully offline. Real HTTP happens in
the integration tests (which run inside the container against either a
configured CASParser sandbox or stub mode).
"""
from __future__ import annotations

import datetime as dt

import httpx
import pytest

from portfolio_ingestion.clients import casparser as cp


# ── Stub mode: no API key → deterministic fake token ─────────────────────


async def test_stub_mode_returns_synthetic_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PI_CASPARSER_API_KEY", raising=False)
    tok = await cp.mint()
    assert tok.stub is True
    assert tok.access_token.startswith("stub-at-")
    assert tok.expires_at > dt.datetime.now(dt.timezone.utc)


# ── Real call: 200 OK → AccessToken ──────────────────────────────────────


async def test_real_call_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PI_CASPARSER_API_KEY", "k-test")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "k-test"
        return httpx.Response(
            200, json={"access_token": "at_real_123", "expires_in": 1800},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        tok = await cp.mint(http_client=client)

    assert tok.stub is False
    assert tok.access_token == "at_real_123"


# ── Real call: non-2xx → CasparserUpstreamError ──────────────────────────


async def test_real_call_4xx_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PI_CASPARSER_API_KEY", "k-test")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "forbidden"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(cp.CasparserUpstreamError, match="403"):
            await cp.mint(http_client=client)


async def test_real_call_missing_token_field_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PI_CASPARSER_API_KEY", "k-test")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"oops": "no token here"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(cp.CasparserUpstreamError, match="missing access_token"):
            await cp.mint(http_client=client)


# ── TTL clamping ──────────────────────────────────────────────────────────


async def test_ttl_is_capped_at_30_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PI_CASPARSER_API_KEY", raising=False)
    tok = await cp.mint(ttl_seconds=3600)   # ask for 1h, should clamp
    expiry_delta = (tok.expires_at - dt.datetime.now(dt.timezone.utc)).total_seconds()
    assert expiry_delta <= cp.DEFAULT_TTL_SECONDS + 5
