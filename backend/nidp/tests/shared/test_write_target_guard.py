"""The unwritable-target guard must never mis-classify a healthy table.

nidp.index_eod / nidp.mf_nav_daily are pass-through VIEWS over FDW
foreign tables on staging, so their ingesters can never upsert (253 and
85 consecutive identical failures). The guard turns that into an
accurate SKIP.

The subtle failure mode pinned here: asyncpg returns postgres "char" as
*bytes*, so relkind arrives as b'r'. An un-decoded value matches neither
the writable branch nor a label, which would flag every healthy table as
unwritable and silently stop working feeds.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from nidp.shared import write_target


class _Conn:
    def __init__(self, relkind, base=None):
        self._relkind = relkind
        self._base = base

    async def fetchrow(self, *a):
        return None if self._relkind is None else {"relkind": self._relkind}

    async def fetchval(self, *a):
        return self._base


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self._conn


def _run(relkind, base=None, monkeypatch=None):
    pool = _Pool(_Conn(relkind, base))

    async def _get_pool():
        return pool

    monkeypatch.setattr(write_target, "get_pool", _get_pool)
    return asyncio.run(write_target.upsert_target_problem("nidp.thing"))


@pytest.mark.parametrize("relkind", [b"r", "r", b"p", "p"])
def test_tables_are_reported_writable(relkind, monkeypatch):
    """Bytes or str, a real table must never be flagged."""
    assert _run(relkind, monkeypatch=monkeypatch) is None


@pytest.mark.parametrize("relkind", [b"v", "v"])
def test_views_are_reported_unwritable(relkind, monkeypatch):
    msg = _run(relkind, base="prod_data.thing (f)", monkeypatch=monkeypatch)
    assert msg and "not a writable table" in msg
    assert "view" in msg


def test_view_message_names_the_underlying_relation(monkeypatch):
    msg = _run(b"v", base="prod_data.thing (f)", monkeypatch=monkeypatch)
    assert "prod_data.thing (f)" in msg


def test_foreign_table_is_reported_unwritable(monkeypatch):
    msg = _run(b"f", monkeypatch=monkeypatch)
    assert msg and "foreign table" in msg


def test_missing_relation_defers_to_the_normal_failure_path(monkeypatch):
    """A typo'd table is a real error — the guard must not swallow it."""
    assert _run(None, monkeypatch=monkeypatch) is None


def test_message_is_actionable(monkeypatch):
    msg = _run(b"v", base="prod_data.thing (f)", monkeypatch=monkeypatch)
    for phrase in ("nidp.thing", "conflict target", "Reads still work"):
        assert phrase in msg
