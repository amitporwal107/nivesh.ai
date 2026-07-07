"""Unit tests for the /readyz readiness endpoints (daas_api + query_api).

Verifies: DB up -> 200; DB down -> 503; and that /health stays 200 (liveness)
regardless of DB state (db_ok reflected only in the body).
"""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("fastapi")  # routers import fastapi; skip where it's absent (repo env)

from nidp.services.daas_api.routers import health as daas_health
from nidp.services.query_api.routers import health as query_health


class _FakeResponse:
    def __init__(self):
        self.status_code = 200


class _FakeConn:
    async def fetchval(self, *a, **k):
        return 1


class _FakeAcquire:
    async def __aenter__(self):
        return _FakeConn()

    async def __aexit__(self, *a):
        return False


class _FakePool:
    def acquire(self):
        return _FakeAcquire()


def _patch_db_up(monkeypatch, mod):
    async def gp():
        return _FakePool()
    monkeypatch.setattr(mod, "get_pool", gp)


def _patch_db_down(monkeypatch, mod):
    async def gp():
        raise ConnectionRefusedError("the database system is in recovery mode")
    monkeypatch.setattr(mod, "get_pool", gp)


@pytest.mark.parametrize("mod", [daas_health, query_health])
def test_readyz_200_when_db_up(monkeypatch, mod):
    _patch_db_up(monkeypatch, mod)
    resp = _FakeResponse()
    out = asyncio.run(mod.readyz(resp))
    assert out["db_ok"] is True
    assert resp.status_code == 200


@pytest.mark.parametrize("mod", [daas_health, query_health])
def test_readyz_503_when_db_down(monkeypatch, mod):
    _patch_db_down(monkeypatch, mod)
    resp = _FakeResponse()
    out = asyncio.run(mod.readyz(resp))
    assert out["db_ok"] is False
    assert resp.status_code == 503          # the key fix: HTTP-visible DB-down
    assert "recovery mode" in (out["error"] or "")


@pytest.mark.parametrize("mod", [daas_health, query_health])
def test_health_liveness_stays_200_when_db_down(monkeypatch, mod):
    """/health is liveness — a running process reports up (200); db_ok in body."""
    _patch_db_down(monkeypatch, mod)
    out = asyncio.run(mod.health())         # returns a plain dict -> FastAPI 200
    assert out["db_ok"] is False
