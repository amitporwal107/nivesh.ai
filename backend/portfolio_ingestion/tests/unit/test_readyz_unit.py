"""Unit-level test of /api/healthz response shape (T4.1)."""
from __future__ import annotations


def test_healthz_returns_ok(client):
    r = client.get("/api/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "portfolio_ingestion"
    assert "version" in body
    assert "env" in body
