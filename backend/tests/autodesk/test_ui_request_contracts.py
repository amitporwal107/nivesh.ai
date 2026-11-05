"""AD-UI contracts: every request body the desk web app sends, posted to the real FastAPI app.

The web app's Playwright specs check that the UI sends exactly the bodies kept in
frontend-v5/e2e/fixtures/autodesk/requests/*.json (one file per screen). This test posts each of those bodies to the
desk API — real request models, real store, TEST-DOUBLE agents and crafted market data (tests/autodesk/stubs.py) —
and checks the status the contract expects. A mocked UI test alone would not catch a body the API refuses (422).

Placeholders in a contract's path or body are filled from entities this test creates for a fresh tenant per contract:
{account_id} {policy_id} {approval_id} {plan_hash} {trade_id} {plan_version} {signal_id} {simulation_id}
{workflow_id} {start_date} {end_date} {session_date}. The simulation's state follows the action in the path
(start → CREATED, resume → PAUSED, other actions → RUNNING).
"""
from __future__ import annotations

import json
import re
import time
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from autodesk.db import create_pool_for
from autodesk.main import build_state, create_app
from autodesk.routers.api import current_user
from tests.autodesk import stubs

REQ_DIR = Path(__file__).resolve().parents[3] / "frontend-v5" / "e2e" / "fixtures" / "autodesk" / "requests"
pytestmark = pytest.mark.skipif(not REQ_DIR.is_dir(), reason="the web app's request fixtures are not in this checkout")

PLACEHOLDER = re.compile(r"\{(\w+)\}")
SIM_DATES = {"start_date": "2026-11-04", "end_date": "2026-11-05", "session_date": "2026-11-05"}


def _contracts() -> list[tuple[str, str, dict]]:
    out = []
    if not REQ_DIR.is_dir():
        return out
    for f in sorted(REQ_DIR.glob("*.json")):
        for name, c in json.loads(f.read_text()).items():
            out.append((f.stem, name, c))
    return out


@pytest.fixture(scope="module")
def client(pg_pool, pg_dsn):
    pools = []

    async def factory():
        pool = await create_pool_for(pg_dsn)
        pools.append(pool)

        async def next_session(now):
            return date(2026, 11, 5)

        st = build_state(pool, agents=stubs.agents(), market_factory=stubs.market_factory,
                         sessions_provider=stubs.sessions_provider, next_session=next_session,
                         load_book=stubs.stub_load_book, scope_builder=stubs.stub_scope)
        st.orchestrator.task_deadline_s = 1.0
        await st.orchestrator.register_agents()
        return st

    app = create_app(factory)

    async def fake_user(request: Request):
        who = request.headers.get("X-Test-User") or ""
        if not who.startswith("ui-"):
            raise HTTPException(401, "Not authenticated")
        return {"user_id": who, "role": "user"}

    app.dependency_overrides[current_user] = fake_user
    with TestClient(app) as c:
        yield c
        for p in pools:
            c.portal.call(p.close)


class Ctx:
    """Creates what a contract's placeholders need, once per tenant."""

    def __init__(self, client: TestClient, tenant: str, action: str):
        self.c, self.h, self.action = client, {"X-Test-User": tenant}, action
        self.v: dict[str, str] = dict(SIM_DATES)

    def _ok(self, r, *codes):
        assert r.status_code in codes, f"setup {r.request.method} {r.request.url.path} → {r.status_code} {r.text}"
        return r.json()

    def get(self, key: str) -> str:
        if key in self.v:
            return self.v[key]
        if key == "account_id":
            self.v[key] = self._ok(self.c.post("/api/v1/accounts", json={"name": "contract", "operating_mode": "ASSISTED"},
                                               headers=self.h), 201)["account_id"]
        elif key == "policy_id":
            self.v[key] = self._ok(self.c.get("/api/v1/policies", headers=self.h), 200)[0]["policy_id"]
        elif key in ("workflow_id", "signal_id"):
            cyc = self._ok(self.c.post("/api/v1/desk/workflows", json={"kind": "SESSION_CYCLE", "account_id": self.get("account_id"),
                                                                       "max_proposals": 1, "wait": True}, headers=self.h), 202)
            self.v["workflow_id"] = cyc["workflow_id"]
            self.v["signal_id"] = self._ok(self.c.get("/api/v1/signals", headers=self.h), 200)[0]["signal_id"]
        elif key in ("approval_id", "plan_hash", "trade_id", "plan_version"):
            # A request waiting on a person, from an ASSISTED simulation stepped to its PROPOSALS phase. A desk cycle
            # would do too, but its request expires at that session's close on the wall clock (409 "the approval
            # window has closed" when this runs after 15:30 IST); the simulated clock does not move. Same endpoint,
            # same body model.
            body = {"name": "contract approvals", "start_date": SIM_DATES["start_date"], "end_date": SIM_DATES["end_date"],
                    "operating_mode": "ASSISTED", "max_proposals_per_session": 1}
            sid = self._ok(self.c.post("/api/v1/simulations", json=body, headers=self.h), 201)["simulation_id"]
            self._ok(self.c.post(f"/api/v1/simulations/{sid}/start", headers=self.h), 200)
            for _ in range(3):
                self._ok(self.c.post(f"/api/v1/simulations/{sid}/step", json={"unit": "PHASE"}, headers=self.h), 200)
            pend = self._ok(self.c.get(f"/api/v1/approvals?pending=true&simulation_id={sid}", headers=self.h), 200)
            assert pend, "setup: the ASSISTED simulation left no pending approval"
            a = pend[0]
            plan = self._ok(self.c.get(f"/api/v1/trade-plans/{a['trade_id']}?version={a['plan_version']}", headers=self.h), 200)
            self.v.update(approval_id=a["approval_id"], trade_id=a["trade_id"], plan_version=str(a["plan_version"]),
                          plan_hash=plan["plan_hash"])
        elif key == "simulation_id":
            body = {"name": "contract sim", "start_date": SIM_DATES["start_date"], "end_date": SIM_DATES["end_date"],
                    "operating_mode": "ASSISTED", "max_proposals_per_session": 1}
            sid = self._ok(self.c.post("/api/v1/simulations", json=body, headers=self.h), 201)["simulation_id"]
            if self.action != "start":
                self._ok(self.c.post(f"/api/v1/simulations/{sid}/start", headers=self.h), 200)
            if self.action == "resume":
                self._ok(self.c.post(f"/api/v1/simulations/{sid}/pause", headers=self.h), 200)
            self.v[key] = sid
        else:
            raise AssertionError(f"no setup for placeholder {{{key}}}")
        return self.v[key]

    def fill(self, v):
        if isinstance(v, str):
            whole = PLACEHOLDER.fullmatch(v)
            if whole:
                return self.get(whole.group(1))
            return PLACEHOLDER.sub(lambda m: self.get(m.group(1)), v)
        if isinstance(v, list):
            return [self.fill(x) for x in v]
        if isinstance(v, dict):
            return {k: self.fill(x) for k, x in v.items()}
        return v


CONTRACTS = _contracts()


def test_contract_files_present():
    assert CONTRACTS, f"no request contracts under {REQ_DIR}"
    for file, name, c in CONTRACTS:
        assert c.get("method") in ("POST", "PUT", "PATCH", "DELETE"), (file, name)
        assert c.get("path", "").startswith("/") and isinstance(c.get("expect"), list) and c["expect"], (file, name)


@pytest.mark.parametrize("file,name,c", CONTRACTS, ids=[f"{f}.{n}" for f, n, _ in CONTRACTS])
def test_ui_request_contract(client, file, name, c):
    tenant = f"ui-{file}-{name}"[:60]
    action = c["path"].rstrip("/").split("/")[-1]
    ctx = Ctx(client, tenant, action)
    path = ctx.fill(c["path"])
    body = ctx.fill(c.get("body"))
    r = client.request(c["method"], f"/api/v1{path}", json=body, headers=ctx.h)
    assert r.status_code in c["expect"], f"{file}.{name}: {c['method']} {path} {body} → {r.status_code} {r.text}"
    if action == "run" and "simulation_id" in ctx.v:
        # `run` replays in the background; stop it and wait for the job to end, so it does not outlive the test's
        # database pool (that only adds "pool is closing" noise to the log).
        sid = ctx.v["simulation_id"]
        client.post(f"/api/v1/simulations/{sid}/stop", headers=ctx.h)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if not client.get(f"/api/v1/simulations/{sid}", headers=ctx.h).json().get("background_run"):
                break
            time.sleep(0.1)
