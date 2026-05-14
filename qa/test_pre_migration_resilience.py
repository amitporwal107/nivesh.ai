"""Regression tests for BUG-2026-001, 002, 003, 004, 006.

Verifies that admin/portfolio endpoints return graceful empty responses
(not 500s) when underlying DB tables don't yet exist — pre-migration state.

Run with:  pytest qa/test_pre_migration_resilience.py -v
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── BUG-2026-001: _last_nav_cron_summary must not raise ─────────────────────

@pytest.mark.asyncio
async def test_last_nav_cron_summary_table_missing():
    """Returns None (not raises) when amfi_nav_fetch_log doesn't exist."""
    import asyncpg
    from services.nav_analytics_sweep import _last_nav_cron_summary

    mock_conn = AsyncMock()
    mock_conn.fetchrow.side_effect = asyncpg.UndefinedTableError("relation does not exist")
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_conn),
        __aexit__=AsyncMock(return_value=False),
    ))

    with patch("services.nav_analytics_sweep.pg_client") as mock_pg:
        mock_pg.get_pool = AsyncMock(return_value=mock_pool)
        result = await _last_nav_cron_summary()

    assert result is None, "Must return None, not raise, when table is missing"


@pytest.mark.asyncio
async def test_pipeline_status_survives_missing_nav_log():
    """pipeline_status() returns a dict (no 500) even when amfi_nav_fetch_log absent."""
    import asyncpg
    from services.nav_analytics_sweep import pipeline_status

    mock_conn = AsyncMock()
    mock_conn.fetchrow.side_effect = asyncpg.UndefinedTableError("relation does not exist")
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_conn),
        __aexit__=AsyncMock(return_value=False),
    ))

    with patch("services.nav_analytics_sweep.pg_client") as mock_pg, \
         patch("services.nav_analytics_sweep.v3_score_cache") as mock_cache, \
         patch("services.nav_analytics_sweep.mf_scheduler", create=True), \
         patch("services.nav_analytics_sweep.pipeline_progress", create=True) as mock_pp:
        mock_pg.get_pool = AsyncMock(return_value=mock_pool)
        mock_cache.get_stats = AsyncMock(return_value={})
        mock_pp.read_all = AsyncMock(return_value=[])
        result = await pipeline_status()

    assert isinstance(result, dict), "Must return dict, not raise"
    assert "jobs" in result


# ── BUG-2026-002: list_scraped_funds must not raise ─────────────────────────

@pytest.mark.asyncio
async def test_list_scraped_funds_table_missing():
    """Returns [] (not raises) when instrument_master doesn't exist."""
    import asyncpg
    from services.pg_writer import list_scraped_funds

    mock_conn = AsyncMock()
    mock_conn.fetch.side_effect = asyncpg.UndefinedTableError("relation does not exist")
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_conn),
        __aexit__=AsyncMock(return_value=False),
    ))

    with patch("services.pg_writer.pg_client") as mock_pg:
        mock_pg.get_pool = AsyncMock(return_value=mock_pool)
        result = await list_scraped_funds()

    assert result == [], "Must return [], not raise, when table is missing"


# ── BUG-2026-003: list_audit_log must not raise ─────────────────────────────

@pytest.mark.asyncio
async def test_list_audit_log_table_missing():
    """Returns [] (not raises) when scrape_audit_log doesn't exist."""
    import asyncpg
    from services.pg_writer import list_audit_log

    mock_conn = AsyncMock()
    mock_conn.fetch.side_effect = asyncpg.UndefinedTableError("relation does not exist")
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_conn),
        __aexit__=AsyncMock(return_value=False),
    ))

    with patch("services.pg_writer.pg_client") as mock_pg:
        mock_pg.get_pool = AsyncMock(return_value=mock_pool)
        result = await list_audit_log()

    assert result == [], "Must return [], not raise, when table is missing"


# ── BUG-2026-004: market_dashboard route must not 500 ───────────────────────

@pytest.mark.asyncio
async def test_market_dashboard_build_failure_returns_error_shape():
    """Route returns {ok: False, error: ...} (not 500) when build() raises."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from routes.positional import router
    from unittest.mock import patch, AsyncMock

    app = FastAPI()
    app.include_router(router)

    with patch("deps.get_current_user", return_value={"uid": "test"}), \
         patch("services.positional_engine.market_dashboard.build",
               new_callable=AsyncMock,
               side_effect=Exception("stock_ohlcv does not exist")):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/positional/market-dashboard",
                          headers={"Authorization": "Bearer test"})

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("ok") is False
    assert "error" in body


# ── BUG-2026-006: close_pool must close nse_fetcher session ─────────────────

@pytest.mark.asyncio
async def test_close_pool_closes_nse_fetcher():
    """close_pool() also closes the nse_fetcher session to prevent asyncio warnings."""
    from nidp.shared.storage import pg as pg_module

    close_called = False

    async def mock_nse_close():
        nonlocal close_called
        close_called = True

    mock_nse_fetcher = MagicMock()
    mock_nse_fetcher.close = mock_nse_close

    with patch.dict("sys.modules", {"nidp.shared.sources.nse_fetcher": mock_nse_fetcher}):
        # Ensure pool is None so we don't need a real DB connection
        pg_module._pool = None
        await pg_module.close_pool()

    assert close_called, "close_pool() must call nse_fetcher.close()"
