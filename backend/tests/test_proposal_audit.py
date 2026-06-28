"""Unit tests for services.portfolio_proposal_audit (Deliverable 3 — audit
persistence, PRD D4 / plan Step 7).

Pure-function coverage for to_row() (every column present, jsonb fields are
valid JSON that round-trips, and a missing required field is flagged), plus the
async persist() degrade/success paths exercised against a FAKE pool (this env
has NO DB / NO network, so the live INSERT is UNVERIFIED). Verified here:
  - None pool  -> persist() returns None (audit silently degrades, never raises)
  - fake pool  -> persist() returns a uuid string after the INSERT executes
"""
import asyncio
import json
import uuid

import pytest

from services import portfolio_proposal_audit as ppa
from services import selection as sel


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _audit_record():
    """A representative build_audit_record() output."""
    selected = [{
        "isin": "INF001", "scheme_name": "Axis Bluechip - Direct - Growth",
        "quality_score": 72.5,
        "gate_results": [{"gate": "aum_floor", "status": "passed", "reason": ""}],
        "overlap_status": "evaluated",
    }]
    rejected = [{
        "isin": "INF002", "scheme_name": "Small Co - Direct - Growth",
        "gate_failed": ["aum_floor"], "gate_reason": "aum 100cr < 500cr floor",
        "overlap_status": None, "overlap_pct": None,
    }]
    return sel.build_audit_record(
        inputs={"asset_class": "equity", "monthly_sip_rs": 10000, "horizon_years": 7},
        selected=selected,
        rejected=rejected,
        weights={"quality": 0.6, "expense": 0.4},
        scoring_config_version="1.0.0",
    )


# ── to_row(): all columns present, jsonb fields are valid round-trippable JSON ─────
def test_to_row_has_all_columns():
    pid = str(uuid.uuid4())
    row = ppa.to_row(_audit_record(), proposal_id=pid, user_id="user_abc")
    assert set(row.keys()) == {
        "proposal_id", "user_id", "inputs", "weights",
        "scoring_config_version", "picks", "rejected",
    }
    assert row["proposal_id"] == pid
    assert row["user_id"] == "user_abc"
    assert row["scoring_config_version"] == "1.0.0"


def test_to_row_jsonb_fields_are_valid_json_and_roundtrip():
    rec = _audit_record()
    row = ppa.to_row(rec, proposal_id=str(uuid.uuid4()))
    # Each jsonb column must be a JSON STRING that parses back to the original.
    for col in ("inputs", "weights", "picks", "rejected"):
        assert isinstance(row[col], str), f"{col} must be json.dumps'd"
        assert json.loads(row[col]) == rec[col]
    # Spot-check a nested value survived the round-trip.
    assert json.loads(row["inputs"])["asset_class"] == "equity"
    assert json.loads(row["picks"])[0]["isin"] == "INF001"


def test_to_row_user_id_defaults_to_none():
    row = ppa.to_row(_audit_record(), proposal_id=str(uuid.uuid4()))
    assert row["user_id"] is None


# ── to_row(): missing required field is flagged, never silently persisted ──────────
def test_to_row_flags_missing_scoring_config_version():
    rec = _audit_record()
    rec.pop("scoring_config_version")
    with pytest.raises(ValueError) as ei:
        ppa.to_row(rec, proposal_id=str(uuid.uuid4()))
    assert "scoring_config_version" in str(ei.value)


def test_to_row_flags_missing_inputs():
    rec = _audit_record()
    rec.pop("inputs")
    with pytest.raises(ValueError) as ei:
        ppa.to_row(rec, proposal_id=str(uuid.uuid4()))
    assert "inputs" in str(ei.value)


# ── persist(): None pool degrades to None (never raises into the builder) ──────────
def test_persist_returns_none_when_no_pool(monkeypatch):
    async def _no_pool():
        return None

    monkeypatch.setattr(ppa.pg_client, "get_pool", _no_pool)
    assert _run(ppa.persist(_audit_record())) is None


def test_persist_returns_none_on_unpersistable_record(monkeypatch):
    """A record missing a required field must not even reach the DB."""
    def _boom():
        raise AssertionError("get_pool must not be called for a bad record")

    monkeypatch.setattr(ppa.pg_client, "get_pool", _boom)
    rec = _audit_record()
    rec.pop("scoring_config_version")
    assert _run(ppa.persist(rec)) is None


# ── persist(): fake pool → returns a uuid string after the INSERT executes ─────────
class _FakeConn:
    def __init__(self, sink):
        self._sink = sink

    async def execute(self, query, *args):
        self._sink["query"] = query
        self._sink["args"] = args
        return "INSERT 0 1"


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, sink):
        self._conn = _FakeConn(sink)

    def acquire(self):
        return _FakeAcquire(self._conn)


def test_persist_returns_uuid_with_fake_pool(monkeypatch):
    sink = {}
    pool = _FakePool(sink)

    async def _pool():
        return pool

    monkeypatch.setattr(ppa.pg_client, "get_pool", _pool)
    pid = _run(ppa.persist(_audit_record(), user_id="user_xyz"))

    # Returned id is a valid uuid string...
    assert isinstance(pid, str)
    assert str(uuid.UUID(pid)) == pid
    # ...and the INSERT actually fired with that id + user as the first args.
    assert "INSERT INTO portfolio_proposal_audit" in sink["query"]
    assert sink["args"][0] == pid
    assert sink["args"][1] == "user_xyz"


def test_persist_uses_given_proposal_id(monkeypatch):
    sink = {}

    async def _pool():
        return _FakePool(sink)

    monkeypatch.setattr(ppa.pg_client, "get_pool", _pool)
    given = str(uuid.uuid4())
    pid = _run(ppa.persist(_audit_record(), proposal_id=given))
    assert pid == given
    assert sink["args"][0] == given


def test_persist_returns_none_on_db_error(monkeypatch):
    """A DB execute that raises must degrade to None, never propagate."""
    class _BoomConn:
        async def execute(self, query, *args):
            raise RuntimeError("db exploded")

    class _BoomPool:
        def acquire(self):
            return _FakeAcquire(_BoomConn())

    async def _pool():
        return _BoomPool()

    monkeypatch.setattr(ppa.pg_client, "get_pool", _pool)
    assert _run(ppa.persist(_audit_record())) is None
