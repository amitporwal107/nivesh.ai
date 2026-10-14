"""GET /api/markets/circulars (routes/circulars.py) → DaaS /v1/circulars/sebi.

No network and no Mongo: `daas_client.get_raw` is replaced by a recorder that answers with a fixture body (MOCK — not
real data) in the shape the data platform sends, so the route's own work runs for real: auth, parameter validation,
what is forwarded, the pass-through and the error mapping. The DaaS router is tested in
nidp/tests/services/test_daas_circulars.py.
"""
from __future__ import annotations

import copy
from typing import List, Optional, Tuple

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from routes import circulars as route

BODY = {"as_of": "2026-10-14", "checked_at": "2026-10-14T06:45:03+00:00",
        "source": "SEBI RSS (sebi.gov.in) — circulars and master circulars", "days": 30, "from": "2026-09-14", "count": 1,
        "rows": [{"title": "Synthetic circular", "url": "https://www.sebi.gov.in/legal/circulars/oct-2026/a_1.html",
                  "kind": "circular", "issued_on": "2026-10-13", "department": None}]}


def _client(monkeypatch, reply, *, signed_in=True, configured=True) -> Tuple[TestClient, List[Tuple[str, Optional[dict]]]]:
    calls: List[Tuple[str, Optional[dict]]] = []

    async def get_raw(path, params=None, timeout=10.0):
        calls.append((path, params))
        if isinstance(reply, Exception):
            raise reply
        return copy.deepcopy(reply)

    monkeypatch.setattr(route.daas_client, "get_raw", get_raw)
    monkeypatch.setattr(route.daas_client, "is_configured", lambda: configured)
    if signed_in:
        async def fake_user(request: Request):
            return {"user_id": "u1", "email": "u1@example.com"}
        monkeypatch.setattr(route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app), calls


def test_passes_the_data_platform_answer_through(monkeypatch):
    c, calls = _client(monkeypatch, (200, BODY))
    r = c.get("/api/markets/circulars")
    assert r.status_code == 200
    assert r.json() == BODY
    assert calls == [("/circulars/sebi", {"days": 30, "limit": 50})]


def test_forwards_days_and_limit(monkeypatch):
    c, calls = _client(monkeypatch, (200, BODY))
    assert c.get("/api/markets/circulars?days=7&limit=5").status_code == 200
    assert calls == [("/circulars/sebi", {"days": 7, "limit": 5})]


def test_no_circular_in_the_window_is_200_with_an_empty_list(monkeypatch):
    empty = {**BODY, "count": 0, "rows": []}
    c, _ = _client(monkeypatch, (200, empty))
    r = c.get("/api/markets/circulars")
    assert r.status_code == 200 and r.json()["rows"] == [] and r.json()["as_of"] == "2026-10-14"


@pytest.mark.parametrize("qs", ["days=0", "days=366", "limit=0", "limit=201", "days=abc"])
def test_rejects_out_of_range_parameters_without_calling_the_data_platform(monkeypatch, qs):
    c, calls = _client(monkeypatch, (200, BODY))
    assert c.get(f"/api/markets/circulars?{qs}").status_code == 422
    assert calls == []


@pytest.mark.parametrize("reply", [
    (500, {"detail": "boom"}),
    (404, {"detail": "Not Found"}),          # a data platform without the router yet
    (200, {"as_of": "2026-10-14"}),          # no rows list
    (200, None),
    route.daas_client.DaasError("timed out"),
])
def test_data_platform_failure_is_502_never_an_empty_list(monkeypatch, reply):
    c, _ = _client(monkeypatch, reply)
    r = c.get("/api/markets/circulars")
    assert r.status_code == 502
    assert r.json() == {"detail": "upstream_unavailable"}


def test_unconfigured_data_platform_is_502(monkeypatch):
    c, calls = _client(monkeypatch, (200, BODY), configured=False)
    assert c.get("/api/markets/circulars").status_code == 502
    assert calls == []


def test_needs_a_signed_in_user(monkeypatch):
    c, calls = _client(monkeypatch, (200, BODY), signed_in=False)
    assert c.get("/api/markets/circulars").status_code == 401
    assert calls == []
