"""Shared fakes for the Paper Trading v2 backend suites (tests/test_paper_v2_*.py). Not a test module.

MOCK — not real data. Every user, symbol, price, position, chain row and signal here is made up; no staging data is read.
Builds on tests/spt_b_fakes.World (in-memory Mongo with unique indexes, the clock at Thursday 5 Nov 2026 10:30 IST, the
quote cache and the risk inputs replaced); everything else (risk profile, SPT config, risk book, allocation, the risk
service) runs for real. `client` mounts the SPT routers and the Paper Trading v2 routers with a header-based session:
X-Test-User names a user in USERS (none → 401); "adm" is an admin.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

import deps
from tests.spt_b_fakes import NOW, U1, U2, World  # noqa: F401

USERS = {U1: {"user_id": U1, "email": "u1@example.com"}, U2: {"user_id": U2, "email": "u2@example.com"},
         "adm": {"user_id": "adm", "email": "adm@example.com", "role": "admin"}}
A = {"X-Test-User": U1}
B = {"X-Test-User": U2}
ADM = {"X-Test-User": "adm"}

MOCK_FEED_LIVE = {"mode": "live", "age_s": 1.2, "session": "open"}


@pytest.fixture
def world(monkeypatch):
    return World(monkeypatch)


@pytest.fixture
def client(world, monkeypatch):
    from routes import spt_accounts, spt_paper_v2, spt_risk
    from services.spt import overview

    for mod in (spt_accounts, spt_risk, spt_paper_v2):
        monkeypatch.setattr(mod, "db", world.db)

    async def current_user(request: Request) -> Dict[str, Any]:
        who = request.headers.get("X-Test-User")
        if who not in USERS:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return dict(USERS[who])

    for mod in (spt_accounts, spt_risk, spt_paper_v2):
        monkeypatch.setattr(mod, "get_current_user", current_user)
    monkeypatch.setattr(deps, "get_current_user", current_user)        # what require_role("admin") calls

    async def feed(now):                                                # MOCK feed status: live, ticking
        return dict(MOCK_FEED_LIVE)
    monkeypatch.setattr(overview, "_feed", feed)

    async def no_margin(db, underlying, legs, key):                     # MOCK: no Kite session in tests
        return None, "MOCK: no Kite session in the test"
    from services.spt import fno_structures
    monkeypatch.setattr(fno_structures, "zerodha_margin", no_margin)

    async def no_bars(symbol, now):                                     # MOCK: no data platform in tests
        return {"bars": [], "error": "MOCK: no data platform in the test", "source": "MOCK"}
    from services.spt import correlation
    monkeypatch.setattr(correlation, "_default_bars", no_bars)

    from services.paper_pnl import book as book_mod

    async def empty_book(db, uid, **kw):                                # MOCK: an empty desk book (a test that needs
        return book_mod.Book()                                          # structures patches its own)
    monkeypatch.setattr(book_mod, "read_book", empty_book)

    app = FastAPI()
    for r in (spt_accounts.router, spt_accounts.admin_router, spt_risk.router, spt_paper_v2.router,
              spt_paper_v2.admin_router):
        app.include_router(r)
    c = TestClient(app)
    c.world = world
    return c
