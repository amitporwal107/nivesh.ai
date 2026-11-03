"""Who may read a stored backtest run: GET /api/strategy-builder/runs/{run_id} (Strategy Copilot PRD §15, §19.2,
Appendix A: "User requests another user's run ID → deny access and log the authorization event").

Before this fix any signed-in user could read any run of a public template, including another user's trade ledger,
and a run of someone else's private strategy answered 403 (which tells the caller the run exists).

Covers TC-1 … TC-10 of test_reports/strategy_phase0_runs_20261028_0528.md.

No network, no database. Replaced, and by what:
  * `route.get_current_user`  reads the test's `X-Test-User` header; no header → 401, like the real dependency.
                              MOCK — the real one needs Mongo.
  * `pg_client.get_pool`      a fake pool that answers the route's three statements from Python dicts and counts
                              them. MOCK — not a database.
  * `audit.record`            appends to a list instead of writing Mongo `audit_log`. MOCK.

MOCK — not real data: every id and user here is invented.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List

import asyncpg
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from routes import strategy_builder as route
from services import audit, pg_client

A, B, C = "user_a", "user_b", "user_c"                      # MOCK users
S_PRIVATE = "11111111-1111-4111-8111-111111111111"          # A's private strategy
S_TEMPLATE = "22222222-2222-4222-8222-222222222222"         # A's public template
R_PRIVATE = "aaaaaaaa-0000-4000-8000-000000000001"          # A's run of S_PRIVATE
R_TPL_B = "aaaaaaaa-0000-4000-8000-000000000002"            # B's run of A's template
R_TPL_A = "aaaaaaaa-0000-4000-8000-000000000003"            # A's own run of the template
R_SYSTEM = "aaaaaaaa-0000-4000-8000-000000000004"           # a system run (no trigger) of S_PRIVATE
R_UNKNOWN = "aaaaaaaa-0000-4000-8000-0000000000ff"


def _run(run_id: str, strategy_id: str, triggered_by, owner: str, public: bool) -> Dict[str, Any]:
    return {"id": run_id, "strategy_id": strategy_id, "version_id": "v-" + strategy_id[:4], "run_type": "BACKTEST",
            "status": "OK", "metrics": json.dumps({"trade_count": 1}), "equity_curve": "[]", "trade_count": 1,
            "snapshot_as_of": None, "error_message": None, "triggered_by": triggered_by,
            "strategy_owner": owner, "is_public_template": public}


class Db:
    def __init__(self):
        self.runs = {
            R_PRIVATE: _run(R_PRIVATE, S_PRIVATE, A, A, False),
            R_TPL_B: _run(R_TPL_B, S_TEMPLATE, B, A, True),
            R_TPL_A: _run(R_TPL_A, S_TEMPLATE, A, A, True),
            R_SYSTEM: _run(R_SYSTEM, S_PRIVATE, None, A, False),
        }
        self.queries = 0
        self.audit: List[Dict[str, Any]] = []


class Conn:
    def __init__(self, db: Db):
        self.db = db

    async def fetchrow(self, q: str, *args):
        self.db.queries += 1
        if "FROM strategy_runs" in q:
            try:
                uuid.UUID(str(args[0]))
            except ValueError:
                # What asyncpg does with a non-UUID argument for a UUID column, before postgres sees it.
                raise asyncpg.DataError(f"invalid input for query argument $1: {args[0]!r} (invalid UUID)")
            return self.db.runs.get(str(args[0]))
        if "FROM strategy_versions" in q:
            return {"definition": json.dumps({"version": "1"})}
        raise AssertionError(f"unexpected fetchrow: {q}")

    async def fetch(self, q: str, *args):
        self.db.queries += 1
        assert "FROM strategy_trades" in q, q
        return [{"run_id": args[0], "symbol": "MOCKCO", "pnl_abs": 10.0}]


class Pool:
    def __init__(self, db: Db):
        self.db = db

    def acquire(self):
        conn = Conn(self.db)

        class _CM:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, *exc):
                return False
        return _CM()


@pytest.fixture
def db(monkeypatch) -> Db:
    d = Db()

    async def fake_user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": uid}

    async def get_pool():
        return Pool(d)

    async def fake_record(**kw):
        d.audit.append(kw)
        return "aud_test"

    monkeypatch.setattr(route, "get_current_user", fake_user)
    monkeypatch.setattr(pg_client, "get_pool", get_pool)
    monkeypatch.setattr(audit, "record", fake_record)
    return d


@pytest.fixture
def api(db) -> TestClient:
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app)


def get(api: TestClient, run_id: str, user=None):
    return api.get(f"/api/strategy-builder/runs/{run_id}", headers={"X-Test-User": user} if user else {})


def test_tc1_owner_reads_a_run_of_their_private_strategy(api, db):
    r = get(api, R_PRIVATE, A)
    assert r.status_code == 200
    body = r.json()
    assert body["run"]["id"] == R_PRIVATE and len(body["trades"]) == 1 and "provenance" in body
    assert db.audit == []


def test_tc2_another_user_gets_404_and_the_denial_is_audited(api, db):
    r = get(api, R_PRIVATE, B)
    assert r.status_code == 404 and r.json() == {"detail": "run not found"}
    assert len(db.audit) == 1
    entry = db.audit[0]
    assert entry["user_id"] == B and entry["action"] == "strategy_run_view" and entry["outcome"] == "denied"
    assert entry["resource"] == f"strategy_run:{R_PRIVATE}"


def test_tc3_a_user_reads_their_own_run_of_someone_elses_public_template(api):
    r = get(api, R_TPL_B, B)
    assert r.status_code == 200 and r.json()["run"]["id"] == R_TPL_B


def test_tc4_a_third_user_cannot_read_another_users_run_of_a_public_template(api, db):
    r = get(api, R_TPL_B, C)
    assert r.status_code == 404 and r.json() == {"detail": "run not found"}
    assert [e["user_id"] for e in db.audit] == [C]


def test_tc5_the_template_owner_cannot_read_another_users_run_of_the_template(api, db):
    r = get(api, R_TPL_B, A)
    assert r.status_code == 404
    assert [e["user_id"] for e in db.audit] == [A]


def test_tc6_the_template_owner_reads_their_own_run_of_the_template(api):
    assert get(api, R_TPL_A, A).status_code == 200


def test_tc7_a_system_run_is_readable_by_the_strategy_owner_only(api, db):
    assert get(api, R_SYSTEM, A).status_code == 200
    r = get(api, R_SYSTEM, B)
    assert r.status_code == 404
    assert [e["user_id"] for e in db.audit] == [B]


def test_tc8_a_malformed_run_id_is_404_not_a_500(api, db):
    r = get(api, "not-a-uuid", A)
    assert r.status_code == 404 and r.json() == {"detail": "run not found"}
    assert db.audit == []                                     # not an authorisation event


def test_tc9_an_unknown_run_answers_exactly_like_a_refused_one(api, db):
    unknown = get(api, R_UNKNOWN, A)
    refused = get(api, R_PRIVATE, B)
    assert unknown.status_code == refused.status_code == 404
    assert unknown.json() == refused.json()
    assert [e["user_id"] for e in db.audit] == [B]            # only the refusal is audited


def test_tc10_no_session_is_401(api, db):
    assert get(api, R_PRIVATE).status_code == 401
    assert db.queries == 0
