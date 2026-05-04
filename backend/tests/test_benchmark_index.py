"""Benchmark Index Data Service tests.

Three layers:

  1. Pure-function metric computation (no DB / network) — guards the
     returns / volatility / drawdown math.
  2. Schema-application + read-API integration (PG-backed; skipped when
     PG isn't available in the test env).
  3. Single live yfinance fetch (slow; gated behind env flag so CI
     doesn't hammer external infra on every run).
"""
from __future__ import annotations

import asyncio
import math
import os
from datetime import date, timedelta

import pytest


# ── Layer 1: pure-function metrics ────────────────────────────────────
def test_compute_metrics_constant_series_zero_returns():
    """Flat series → all returns 0, vol 0, no drawdown."""
    from services.benchmark_index import compute_metrics_from_series
    today = date.today()
    series = [(today - timedelta(days=i), 100.0) for i in range(365 * 5, -1, -1)]
    m = compute_metrics_from_series(series)
    assert m["return_1d"] == 0
    assert m["return_1y"] == 0
    assert m["return_5y"] == 0
    assert m["volatility"] == 0
    assert m["drawdown"] == 0
    assert m["max_drawdown"] == 0


def test_compute_metrics_simple_uptrend():
    """100 → 110 over 1 year: return_1y ≈ +10%, drawdown 0."""
    from services.benchmark_index import compute_metrics_from_series
    today = date.today()
    # Daily linear growth from 100 → 110 over 365 days
    n = 365
    series = []
    for i in range(n + 1):
        d = today - timedelta(days=n - i)
        v = 100.0 + (10.0 * i / n)
        series.append((d, v))
    m = compute_metrics_from_series(series)
    # ~+10% over 1y (allow generous tolerance for trading-day matching)
    assert m["return_1y"] is not None
    assert abs(m["return_1y"] - 0.10) < 0.02, m["return_1y"]
    # Up-only series: drawdown == 0 (close == peak today)
    assert m["drawdown"] == 0
    assert m["max_drawdown"] == 0


def test_compute_metrics_drawdown_after_peak():
    """Series that peaks then falls 20% → drawdown ≈ -20%."""
    from services.benchmark_index import compute_metrics_from_series
    today = date.today()
    series = []
    # 100 → 200 over 200 days (peak), then 200 → 160 over 60 days
    for i in range(200):
        series.append((today - timedelta(days=260 - i), 100 + i * 0.5))
    for i in range(61):
        series.append((today - timedelta(days=60 - i), 200 - (i * 40 / 60)))
    m = compute_metrics_from_series(series)
    # Current close is 160, peak 200 → drawdown -20%
    assert m["drawdown"] is not None
    assert abs(m["drawdown"] - (-0.20)) < 0.02, m["drawdown"]
    assert abs(m["max_drawdown"] - (-0.20)) < 0.02, m["max_drawdown"]


def test_compute_metrics_volatility_annualised():
    """Series with a known daily σ should annualise to σ * √252."""
    from services.benchmark_index import compute_metrics_from_series
    today = date.today()
    # Bouncing ±0.5% every other day for 252 days
    series = []
    p = 100.0
    for i in range(252):
        d = today - timedelta(days=251 - i)
        p = p * (1.005 if i % 2 == 0 else 1 / 1.005)
        series.append((d, p))
    m = compute_metrics_from_series(series)
    # Daily log-return σ ≈ 0.005, annualised ≈ 0.005 * √252 ≈ 0.0794
    assert m["volatility"] is not None
    assert 0.05 < m["volatility"] < 0.12, m["volatility"]


# ── Layer 2: PG-backed integration (skip if unavailable) ──────────────
async def _pg_available() -> bool:
    try:
        from services import pg_client
        pool = await pg_client.get_pool()
        return pool is not None
    except Exception:
        return False


@pytest.fixture
def pg_pool():
    pool_ok = asyncio.get_event_loop().run_until_complete(_pg_available())
    if not pool_ok:
        pytest.skip("Postgres not available in this env")
    return True


def test_ensure_schema_creates_tables(pg_pool):
    """Running ensure_schema must create the three tables and seed
    fund_benchmark_map."""
    from services import benchmark_index as bm
    from services import pg_client
    asyncio.get_event_loop().run_until_complete(bm.ensure_schema())

    async def _check():
        pool = await pg_client.get_pool()
        async with pool.acquire() as conn:
            for tbl in ("market_index_data", "index_metrics", "fund_benchmark_map"):
                row = await conn.fetchrow(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_name=$1", tbl,
                )
                assert row, f"table {tbl} missing"
            # fund_benchmark_map seeded with at least the core categories
            n = await conn.fetchval(
                "SELECT COUNT(*) FROM fund_benchmark_map "
                "WHERE fund_category IN ('Large Cap','Mid Cap','Small Cap','Flexi Cap')"
            )
            assert n >= 4, f"benchmark map seeded only {n} core categories"
    asyncio.get_event_loop().run_until_complete(_check())


def test_prd_core_mapping_pinned(pg_pool):
    """PRD §1 specifies these EXACT four pairings. They must exist
    in fund_benchmark_map after schema apply, and they must NOT drift
    silently — any future change should be a deliberate PRD update."""
    from services import benchmark_index as bm
    asyncio.get_event_loop().run_until_complete(bm.ensure_schema())
    expected = {
        "Large Cap":  "NIFTY_50",
        "Mid Cap":    "NIFTY_MIDCAP_150",
        "Small Cap":  "NIFTY_SMALLCAP_250",
        "Flexi Cap":  "NIFTY_500",
        "Flexicap":   "NIFTY_500",
    }
    for category, benchmark in expected.items():
        actual = asyncio.get_event_loop().run_until_complete(
            bm.get_benchmark_for_category(category)
        )
        assert actual == benchmark, (
            f"PRD core mapping broken: {category!r} → {actual!r} "
            f"(expected {benchmark!r})"
        )


def test_core_indices_have_ticker_chain():
    """Pure test (no DB / no network): every PRD core index must have
    at least one yfinance ticker configured. Without this, the daily
    refresh would silently no-op for that core index."""
    from services.benchmark_index import _CORE_INDICES, _YF_TICKERS
    for idx in _CORE_INDICES:
        chain = _YF_TICKERS.get(idx) or []
        if isinstance(chain, str):
            chain = [chain]
        assert chain, f"core index {idx} has empty ticker chain — daily refresh would no-op"


def test_get_benchmark_for_category(pg_pool):
    """Read API returns the configured benchmark for a known category."""
    from services import benchmark_index as bm
    asyncio.get_event_loop().run_until_complete(bm.ensure_schema())
    bench = asyncio.get_event_loop().run_until_complete(
        bm.get_benchmark_for_category("Mid Cap")
    )
    assert bench == "NIFTY_MIDCAP_150", bench
    bench2 = asyncio.get_event_loop().run_until_complete(
        bm.get_benchmark_for_category("flexi cap")  # case-insensitive
    )
    assert bench2 == "NIFTY_500", bench2
    none = asyncio.get_event_loop().run_until_complete(
        bm.get_benchmark_for_category("totally-bogus-category-xxx")
    )
    assert none is None


def test_upsert_then_read_latest_index(pg_pool):
    """Write 3 daily rows + their metrics, then read via get_latest_index."""
    from services import benchmark_index as bm
    asyncio.get_event_loop().run_until_complete(bm.ensure_schema())
    today = date.today()
    rows = [{
        "index_name": "TEST_FAKE_IDX",
        "date": today - timedelta(days=i),
        "open": 100.0 + i, "high": 101.0 + i, "low": 99.0 + i,
        "close": 100.0 + i, "volume": 1000 * (i + 1),
    } for i in range(3)]
    asyncio.get_event_loop().run_until_complete(bm.upsert_index_data(rows))
    series = [(r["date"], r["close"]) for r in rows]
    metrics = bm.compute_metrics_from_series(series)
    asyncio.get_event_loop().run_until_complete(
        bm.upsert_metrics("TEST_FAKE_IDX", today, metrics)
    )
    snap = asyncio.get_event_loop().run_until_complete(
        bm.get_latest_index("TEST_FAKE_IDX")
    )
    assert snap, "latest snapshot missing after upsert"
    assert snap["index"] == "TEST_FAKE_IDX"
    assert snap["close"] == 100.0  # newest is i=0 → close=100
    assert "metrics" in snap


# ── Layer 3: live yfinance (gated) ────────────────────────────────────
@pytest.mark.skipif(
    os.environ.get("NIVESH_TEST_LIVE_YFINANCE") != "1",
    reason="set NIVESH_TEST_LIVE_YFINANCE=1 to run live network tests",
)
def test_refresh_index_live_nifty50(pg_pool):
    """Live network test — runs only when explicitly enabled."""
    from services import benchmark_index as bm
    asyncio.get_event_loop().run_until_complete(bm.ensure_schema())
    res = asyncio.get_event_loop().run_until_complete(bm.refresh_index("NIFTY_50", period="6mo"))
    assert res.get("ok") is True, res
    assert res.get("rows_written", 0) > 30, res
