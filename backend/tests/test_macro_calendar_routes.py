"""App routes GET /api/markets/macro-calendar and /history (routes/macro_calendar.py → DaaS /v1/desk/macro-calendar*).

No network and no Mongo: `daas_client.get_raw` is replaced by a recorder answering with MOCK fixtures in the shape the data
platform sends, so the route's own work runs for real: auth, parameter validation, what is forwarded, the pass-through and
the error mapping. The figures are tested in nidp/tests/services/test_daas_desk_macro.py.
"""
from __future__ import annotations

import copy
from typing import Any, List, Optional, Tuple

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from routes import macro_calendar as route
from services.copilot_tools import daas_client

Calls = List[Tuple[str, Optional[dict]]]
CAL = {"month": "2026-11", "events": [{"id": "2026-11-10|US_CPI_YOY", "code": "US_CPI_YOY", "estimate": None}], "holidays": [],
       "index_closes": [], "gaps": ["consensus estimates are not shown"]}
HIST = {"code": "US_CPI_YOY", "n": 1, "occurrences": [{"date": "2026-10-14", "event_day_pct": 1.0}], "stats": {}}


def _client(monkeypatch, reply: Any, *, signed_in: bool = True, configured: bool = True) -> Tuple[TestClient, Calls]:
    calls: Calls = []

    async def get_raw(path: str, params: Optional[dict] = None, timeout: float = 10.0):
        calls.append((path, params))
        r = reply(path) if callable(reply) else reply
        if isinstance(r, Exception):
            raise r
        return copy.deepcopy(r)

    monkeypatch.setattr(daas_client, "get_raw", get_raw)
    monkeypatch.setattr(daas_client, "is_configured", lambda: configured)
    if signed_in:
        async def fake_user(request: Request):
            return {"user_id": "u1", "email": "u1@example.com"}
        monkeypatch.setattr(route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app), calls


def test_calendar_forwards_month_country_impact_and_passes_through(monkeypatch):
    c, calls = _client(monkeypatch, (200, CAL))
    r = c.get("/api/markets/macro-calendar?month=2026-11&country=US&impact=H,M")
    assert r.status_code == 200 and r.json() == CAL
    assert calls == [("/desk/macro-calendar", {"month": "2026-11", "country": "US", "impact": "H,M"})]


def test_calendar_defaults_are_both_countries_and_all_impacts(monkeypatch):
    c, calls = _client(monkeypatch, (200, CAL))
    c.get("/api/markets/macro-calendar?month=2026-11")
    assert calls[0][1] == {"month": "2026-11", "country": "IN,US", "impact": "H,M,L"}


@pytest.mark.parametrize("qs", ["", "?month=2026-13", "?month=nov", "?month=2026-11&country=UK", "?month=2026-11&country=in",
                                "?month=2026-11&impact=X", "?month=2026-11&impact=", "?month=2026-11&country=IN,"])
def test_calendar_rejects_bad_params_before_calling_upstream(monkeypatch, qs):
    c, calls = _client(monkeypatch, (200, CAL))
    assert c.get("/api/markets/macro-calendar" + qs).status_code == 422
    assert calls == []


def test_history_forwards_code_and_optional_country(monkeypatch):
    c, calls = _client(monkeypatch, (200, HIST))
    assert c.get("/api/markets/macro-calendar/history?code=US_CPI_YOY").json() == HIST
    c.get("/api/markets/macro-calendar/history?code=IN_CPI&country=IN")
    assert calls == [("/desk/macro-calendar/history", {"code": "US_CPI_YOY"}),
                     ("/desk/macro-calendar/history", {"code": "IN_CPI", "country": "IN"})]


@pytest.mark.parametrize("qs", ["", "?code=us_cpi", "?code=X", "?code=US_CPI_YOY&country=UK", "?code=US%20CPI"])
def test_history_rejects_bad_params(monkeypatch, qs):
    c, calls = _client(monkeypatch, (200, HIST))
    assert c.get("/api/markets/macro-calendar/history" + qs).status_code == 422 and calls == []


@pytest.mark.parametrize("reply", [
    pytest.param(daas_client.DaasError("timed out"), id="unreachable"),
    pytest.param((500, {"detail": "x"}), id="upstream-500"),
    pytest.param((200, {"nope": 1}), id="wrong-shape"),
])
@pytest.mark.parametrize("path", ["/api/markets/macro-calendar?month=2026-11", "/api/markets/macro-calendar/history?code=US_CPI_YOY"])
def test_upstream_trouble_is_502_never_an_empty_calendar(monkeypatch, reply, path):
    c, _ = _client(monkeypatch, reply)
    r = c.get(path)
    assert (r.status_code, r.json()) == (502, {"detail": "upstream_unavailable"})


def test_not_configured_is_502(monkeypatch):
    c, calls = _client(monkeypatch, (200, CAL), configured=False)
    assert c.get("/api/markets/macro-calendar?month=2026-11").status_code == 502 and calls == []


@pytest.mark.parametrize("path", ["/api/markets/macro-calendar?month=2026-11", "/api/markets/macro-calendar/history?code=US_CPI_YOY"])
def test_signed_out_is_401(monkeypatch, path):
    c, calls = _client(monkeypatch, (200, CAL), signed_in=False)
    r = c.get(path)
    assert (r.status_code, r.json()) == (401, {"detail": "Not authenticated"}) and calls == []
