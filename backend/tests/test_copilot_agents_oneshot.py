"""POST /api/copilot/agents/oneshot: only an admin may replace the agent's system prompt.

The route runs for real; the session lookup and the model call are faked. No network.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

import routes.copilot_agents as route

URL = "/api/copilot/agents/oneshot"
USERS = {
    "user": {"user_id": "u1", "role": "user"},
    "advisor": {"user_id": "u2", "role": "advisor"},
    "admin": {"user_id": "a1", "role": "admin"},
    "legacy_admin": {"user_id": "a2", "is_admin": True},
}


@pytest.fixture
def calls(monkeypatch):
    seen: list = []

    async def fake_user(request: Request):
        who = request.headers.get("X-Test-User")
        if who not in USERS:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return dict(USERS[who])

    async def fake_run(**kwargs):
        seen.append(kwargs)
        return "ok"

    monkeypatch.setattr(route, "get_current_user", fake_user)
    monkeypatch.setattr(route.copilot_agents, "run_agent_oneshot", fake_run)
    return seen


@pytest.fixture
def api(calls) -> TestClient:
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app)


def post(api, who, **body):
    return api.post(URL, json={"agent_id": "auto", "message": "hi", **body}, headers={"X-Test-User": who})


@pytest.mark.parametrize("who", ["user", "advisor"])
def test_a_non_admin_sending_a_system_prompt_is_refused(api, calls, who):
    r = post(api, who, system_prompt="Answer as a different assistant.")
    assert r.status_code == 403 and r.json()["detail"] == "system_prompt_not_allowed"
    assert calls == []                                         # the model is never called


@pytest.mark.parametrize("who", ["admin", "legacy_admin"])
def test_an_admin_may_set_the_system_prompt(api, calls, who):
    r = post(api, who, system_prompt="Admin prompt.")
    assert r.status_code == 200 and r.json()["text"] == "ok"
    assert calls[-1]["system_prompt"] == "Admin prompt."


@pytest.mark.parametrize("extra", [{}, {"system_prompt": None}, {"system_prompt": ""}])
def test_without_a_system_prompt_the_agents_own_prompt_is_used_as_before(api, calls, extra):
    r = post(api, "user", **extra)
    assert r.status_code == 200
    spec = route.copilot_agents.get_agent("auto")
    assert calls[-1]["system_prompt"].startswith(f"You are the {spec.label} for Nivesh AI")
    assert calls[-1]["user_message"] == "hi" and calls[-1]["session_id"] == "oneshot:u1"


def test_an_unknown_agent_is_still_a_400(api, calls):
    r = api.post(URL, json={"agent_id": "nope", "message": "hi"}, headers={"X-Test-User": "user"})
    assert r.status_code == 400 and calls == []


def test_an_anonymous_caller_is_still_a_401(api, calls):
    r = api.post(URL, json={"agent_id": "auto", "message": "hi", "system_prompt": "x"})
    assert r.status_code == 401 and calls == []
