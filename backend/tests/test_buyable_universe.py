"""Unit tests for services.buyable_universe (Deliverable 2 — buyable universe).

Pure-function tests for is_direct_growth() (truth table with teeth), plus
get_buyable_isins() exercised against a FAKE pool/conn (no real DB — this env
has none, so the live query is UNVERIFIED). The None-pool degrade is verified:
it must return an empty set so selection.intersect_buyable falls back to
passthrough (decision NI-1).
"""
import asyncio

import pytest

from services import buyable_universe as bu


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── is_direct_growth() truth table ────────────────────────────────────────────────
@pytest.mark.parametrize(
    "name,expected",
    [
        ("X Direct Growth", True),                 # teeth: direct + growth
        ("X Regular Growth", False),               # teeth: regular plan, not direct
        ("X Direct IDCW", False),                  # teeth: direct but income option
        ("Axis Bluechip Fund - Direct Plan - Growth", True),
        ("Axis Bluechip Fund - Direct Plan", True),  # growth implied (no income token)
        ("Axis Bluechip Fund - Direct - IDCW Payout", False),
        ("SBI Bond Fund - Direct - Dividend", False),
        ("HDFC Flexi Cap - Direct - IDCW Reinvestment", False),
        ("HDFC Flexi Cap - Regular - Growth", False),
        ("DIRECT GROWTH (uppercase)", True),       # case-insensitive
        ("", False),
        (None, False),
    ],
)
def test_is_direct_growth_truth_table(name, expected):
    assert bu.is_direct_growth(name) is expected


# ── get_buyable_isins(): None pool → empty set (safe passthrough degrade) ──────────
def test_get_buyable_isins_empty_when_no_pool(monkeypatch):
    async def _no_pool():
        return None

    monkeypatch.setattr(bu.pg_client, "get_pool", _no_pool)
    result = _run(bu.get_buyable_isins())
    assert result == set()


# ── Fake pool/conn so the build path can be exercised without a real DB ────────────
class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, query, *args):
        return self._rows


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, rows):
        self._conn = _FakeConn(rows)

    def acquire(self):
        return _FakeAcquire(self._conn)


def test_get_buyable_isins_builds_set_from_pool(monkeypatch):
    rows = [
        {"isin": "INF001", "scheme_name": "Axis Bluechip - Direct Plan - Growth"},  # keep
        {"isin": "INF002", "scheme_name": "Axis Bluechip - Regular Plan - Growth"},  # drop (regular)
        {"isin": "INF003", "scheme_name": "SBI Bond - Direct - IDCW"},               # drop (income)
        {"isin": "INF004", "scheme_name": "HDFC Flexi Cap - Direct - Growth"},       # keep
        {"isin": None, "scheme_name": "Mystery - Direct - Growth"},                  # drop (no isin)
    ]
    pool = _FakePool(rows)

    async def _pool():
        return pool

    monkeypatch.setattr(bu.pg_client, "get_pool", _pool)
    result = _run(bu.get_buyable_isins())
    assert result == {"INF001", "INF004"}


def test_get_buyable_isins_empty_on_query_error(monkeypatch):
    """A query that raises must degrade to empty set, never propagate (passthrough)."""

    class _BoomConn:
        async def fetch(self, query, *args):
            raise RuntimeError("db exploded")

    class _BoomPool:
        def acquire(self):
            return _FakeAcquire(_BoomConn())

    async def _pool():
        return _BoomPool()

    monkeypatch.setattr(bu.pg_client, "get_pool", _pool)
    assert _run(bu.get_buyable_isins()) == set()
