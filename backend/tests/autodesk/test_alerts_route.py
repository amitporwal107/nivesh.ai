"""AD-AL-26: the admin-only test message. Fake transport (MOCK); nothing reaches Slack."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from autodesk.db import create_pool_for
from autodesk.main import build_state, create_app
from autodesk.notify import runtime
from autodesk.notify.notifier import Notifier
from autodesk.routers.api import current_user
from tests.autodesk import stubs
from tests.autodesk.test_alerts import FakeTransport

USERS = {"u": {"user_id": "al-u", "role": "user"}, "admin": {"user_id": "al-admin", "role": "admin"}}


@pytest.fixture(scope="module")
def client(pg_pool, pg_dsn):
    pools = []

    async def factory():
        pool = await create_pool_for(pg_dsn)
        pools.append(pool)

        async def next_session(now):
            return date(2026, 11, 5)
        return build_state(pool, agents=stubs.agents(), market_factory=stubs.market_factory,
                           sessions_provider=stubs.sessions_provider, next_session=next_session,
                           load_book=stubs.stub_load_book, scope_builder=stubs.stub_scope)

    app = create_app(factory)

    async def fake_user(request: Request):
        who = request.headers.get("X-Test-User")
        if who not in USERS:
            raise HTTPException(401, "Not authenticated")
        return USERS[who]
    app.dependency_overrides[current_user] = fake_user
    with TestClient(app) as c:
        yield c
        for p in pools:
            c.portal.call(p.close)
    runtime.set_notifier(None)


def test_al26_unauthenticated_and_non_admin_refused(client):
    tr = FakeTransport()
    runtime.set_notifier(Notifier(tr))
    assert client.post("/api/v1/alerts/test").status_code == 401
    assert client.post("/api/v1/alerts/test", headers={"X-Test-User": "u"}).status_code == 403
    assert tr.sent == []


def test_al26_admin_sends_one_marked_test_message(client):
    tr = FakeTransport()
    runtime.set_notifier(Notifier(tr))
    r = client.post("/api/v1/alerts/test", headers={"X-Test-User": "admin"})
    assert r.status_code == 200 and r.json() == {"sent": True, "reason": None}
    assert len(tr.sent) == 1 and tr.sent[0].startswith("[TEST]")


def test_al26_disabled_says_so(client):
    runtime.set_notifier(Notifier(None))
    r = client.post("/api/v1/alerts/test", headers={"X-Test-User": "admin"})
    assert r.status_code == 503 and "not configured" in r.json()["detail"]


def test_al26_failed_send_is_reported_without_the_url(client):
    from autodesk.notify.transport import SendResult
    runtime.set_notifier(Notifier(FakeTransport([SendResult(ok=False, permanent=True, reason="invalid_auth")])))
    r = client.post("/api/v1/alerts/test", headers={"X-Test-User": "admin"})
    assert r.status_code == 502 and r.json()["detail"] == "invalid_auth"
