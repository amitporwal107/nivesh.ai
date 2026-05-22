"""Integration tests for POST /api/casparser/token.

Runs against the in-process FastAPI app. Doesn't need Postgres or Mongo —
the endpoint is stateless. Uses the stub-mode path so we don't need real
CASParser credentials on staging.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from portfolio_ingestion.config import reset_settings_for_test


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch):
    """Build the FastAPI app with the stub-mode env."""
    monkeypatch.delenv("PI_CASPARSER_API_KEY", raising=False)
    reset_settings_for_test()
    from portfolio_ingestion.main import create_app

    return create_app()


@pytest.mark.integration
async def test_issue_token_happy_path(app) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/casparser/token",
            headers={"X-User-External-Id": "user-abc"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"].startswith("stub-at-")
    assert body["stub"] is True
    assert body["expires_at"]


@pytest.mark.integration
async def test_issue_token_requires_header(app) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/casparser/token")
    assert resp.status_code == 422
