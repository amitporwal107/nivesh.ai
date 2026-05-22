"""Liveness probe contract."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthz_returns_service_identity(client: TestClient) -> None:
    response = client.get("/api/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "ok",
        "service": "portfolio_ingestion",
        "version": "0.1.0",
        "env": "test",
    }


def test_healthz_content_type(client: TestClient) -> None:
    response = client.get("/api/healthz")
    assert response.headers["content-type"].startswith("application/json")


def test_unknown_path_returns_404(client: TestClient) -> None:
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
