"""App routes GET /api/markets/events-calendar and /history (routes/events_calendar.py → DaaS /v1/desk/events-calendar*).

No network and no Mongo: `daas_client.get_raw` is replaced by a recorder answering with MOCK fixtures in the shape
the data platform sends, so the route's own work runs for real: auth, parameter validation, what is forwarded, the
pass-through and the error mapping. The figures are tested in nidp/tests/services/test_daas_desk_events.py.
"""
from __future__ import annotations

import copy
from typing import Any, List, Optional, Tuple

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from routes import events_calendar as route
from services.copilot_tools import daas_client

Calls = List[Tuple[str, Optional[dict]]]
CAL = {"month": "2026-10", "universe": "fno", "events": [{"id": "2026-10-09|TCS|RESULTS|mtg", "symbol": "TCS"}], "holidays": [],
       "index_closes": [], "gaps": []}
HIST = {"symbol": "TCS", "type": "RESULTS", "n": 1, "occurrences": [{"date": "2026-01-06", "event_day_pct": 4.5}], "stats": {}}


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


def test_calendar_forwards_month_and_universe_and_passes_through(monkeypatch):
    c, calls = _client(monkeypatch, (200, CAL))
    r = c.get("/api/markets/events-calendar?month=2026-10&universe=n50")
    assert r.status_code == 200 and r.json() == CAL
    assert calls == [("/desk/events-calendar", {"month": "2026-10", "universe": "n50"})]


def test_calendar_default_universe_is_fno(monkeypatch):
    c, calls = _client(monkeypatch, (200, CAL))
    c.get("/api/markets/events-calendar?month=2026-10")
    assert calls[0][1] == {"month": "2026-10", "universe": "fno"}


@pytest.mark.parametrize("qs", ["", "?month=2026-13", "?month=oct", "?month=2026-10&universe=nse"])
def test_calendar_rejects_bad_params_before_calling_upstream(monkeypatch, qs):
    c, calls = _client(monkeypatch, (200, CAL))
    assert c.get("/api/markets/events-calendar" + qs).status_code == 422
    assert calls == []


def test_history_forwards_upper_cased_symbol_and_type(monkeypatch):
    c, calls = _client(monkeypatch, (200, HIST))
    r = c.get("/api/markets/events-calendar/history?symbol=tcs&type=RESULTS")
    assert r.status_code == 200 and r.json() == HIST
    assert calls == [("/desk/events-calendar/history", {"symbol": "TCS", "type": "RESULTS"})]


@pytest.mark.parametrize("qs", ["?type=RESULTS", "?symbol=TCS", "?symbol=TCS&type=NOPE", "?symbol=T%20CS&type=RESULTS", "?symbol=TCS&type=results"])
def test_history_rejects_bad_params(monkeypatch, qs):
    c, calls = _client(monkeypatch, (200, HIST))
    assert c.get("/api/markets/events-calendar/history" + qs).status_code == 422 and calls == []


@pytest.mark.parametrize("reply", [
    pytest.param(daas_client.DaasError("timed out"), id="unreachable"),
    pytest.param((500, {"detail": "x"}), id="upstream-500"),
    pytest.param((200, {"nope": 1}), id="wrong-shape"),
])
@pytest.mark.parametrize("path", ["/api/markets/events-calendar?month=2026-10", "/api/markets/events-calendar/history?symbol=TCS&type=RESULTS"])
def test_upstream_trouble_is_502_never_an_empty_calendar(monkeypatch, reply, path):
    c, _ = _client(monkeypatch, reply)
    r = c.get(path)
    assert (r.status_code, r.json()) == (502, {"detail": "upstream_unavailable"})


def test_not_configured_is_502(monkeypatch):
    c, calls = _client(monkeypatch, (200, CAL), configured=False)
    assert c.get("/api/markets/events-calendar?month=2026-10").status_code == 502 and calls == []


@pytest.mark.parametrize("path", ["/api/markets/events-calendar?month=2026-10", "/api/markets/events-calendar/history?symbol=TCS&type=RESULTS"])
def test_signed_out_is_401(monkeypatch, path):
    c, calls = _client(monkeypatch, (200, CAL), signed_in=False)
    r = c.get(path)
    assert (r.status_code, r.json()) == (401, {"detail": "Not authenticated"}) and calls == []


# ── /expectation ─────────────────────────────────────────────────────────────

EXPECT = {"symbol": "TCS", "event_date": "2026-10-08", "status": "declared", "metrics": [{"key": "revenue"}], "gaps": []}


def test_expectation_forwards_upper_cased_symbol_and_date_and_passes_through(monkeypatch):
    c, calls = _client(monkeypatch, (200, EXPECT))
    r = c.get("/api/markets/events-calendar/expectation?symbol=tcs&date=2026-10-08")
    assert r.status_code == 200 and r.json() == EXPECT
    assert calls == [("/desk/events-calendar/expectation", {"symbol": "TCS", "date": "2026-10-08"})]


@pytest.mark.parametrize("qs", ["", "?symbol=TCS", "?date=2026-10-08", "?symbol=TCS&date=oct", "?symbol=TCS&date=2026-1-8", "?symbol=T%20CS&date=2026-10-08"])
def test_expectation_rejects_bad_params_before_calling_upstream(monkeypatch, qs):
    c, calls = _client(monkeypatch, (200, EXPECT))
    assert c.get("/api/markets/events-calendar/expectation" + qs).status_code == 422 and calls == []


def test_expectation_no_results_meeting_is_404_not_502(monkeypatch):
    c, _ = _client(monkeypatch, (404, {"detail": "no results meeting"}))
    r = c.get("/api/markets/events-calendar/expectation?symbol=TCS&date=2026-10-08")
    assert r.status_code == 404


@pytest.mark.parametrize("reply", [pytest.param(daas_client.DaasError("timed out"), id="unreachable"),
                                   pytest.param((500, {"detail": "x"}), id="upstream-500"),
                                   pytest.param((200, {"nope": 1}), id="wrong-shape")])
def test_expectation_upstream_trouble_is_502(monkeypatch, reply):
    c, _ = _client(monkeypatch, reply)
    r = c.get("/api/markets/events-calendar/expectation?symbol=TCS&date=2026-10-08")
    assert (r.status_code, r.json()) == (502, {"detail": "upstream_unavailable"})


def test_expectation_signed_out_is_401(monkeypatch):
    c, calls = _client(monkeypatch, (200, EXPECT), signed_in=False)
    assert c.get("/api/markets/events-calendar/expectation?symbol=TCS&date=2026-10-08").status_code == 401 and calls == []


# ── /expectations (the desk's results today & tomorrow board) ────────────────

BATCH = {"from": "2026-10-21", "to": "2026-10-22", "events": [{"symbol": "TCS"}], "count": 1}  # MOCK — not real data


def test_expectations_forwards_window_and_universe_and_passes_through(monkeypatch):
    c, calls = _client(monkeypatch, (200, BATCH))
    r = c.get("/api/markets/events-calendar/expectations?from=2026-10-21&to=2026-10-22&universe=n50")
    assert r.status_code == 200 and r.json() == BATCH
    assert calls == [("/desk/events-calendar/expectations", {"from": "2026-10-21", "to": "2026-10-22", "universe": "n50"})]


def test_expectations_universe_defaults_to_fno(monkeypatch):
    c, calls = _client(monkeypatch, (200, BATCH))
    c.get("/api/markets/events-calendar/expectations?from=2026-10-21&to=2026-10-21")
    assert calls[0][1]["universe"] == "fno"


@pytest.mark.parametrize("qs", [
    "", "?from=2026-10-21", "?to=2026-10-21", "?from=oct&to=2026-10-21", "?from=2026-10-21&to=2026-1-22",
    "?from=2026-10-22&to=2026-10-21",              # from after to
    "?from=2026-10-21&to=2026-10-24",              # 4 days
    "?from=2026-02-30&to=2026-03-01",              # not a real date
    "?from=2026-10-21&to=2026-10-22&universe=nifty",
])
def test_expectations_rejects_bad_window_before_calling_upstream(monkeypatch, qs):
    c, calls = _client(monkeypatch, (200, BATCH))
    assert c.get("/api/markets/events-calendar/expectations" + qs).status_code == 422 and calls == []


def test_expectations_three_day_window_is_allowed(monkeypatch):
    c, calls = _client(monkeypatch, (200, BATCH))
    assert c.get("/api/markets/events-calendar/expectations?from=2026-10-21&to=2026-10-23").status_code == 200 and len(calls) == 1


@pytest.mark.parametrize("reply", [pytest.param(daas_client.DaasError("timed out"), id="unreachable"),
                                   pytest.param((500, {"detail": "x"}), id="upstream-500"),
                                   pytest.param((200, {"nope": 1}), id="wrong-shape")])
def test_expectations_upstream_trouble_is_502(monkeypatch, reply):
    c, _ = _client(monkeypatch, reply)
    r = c.get("/api/markets/events-calendar/expectations?from=2026-10-21&to=2026-10-22")
    assert (r.status_code, r.json()) == (502, {"detail": "upstream_unavailable"})


def test_expectations_signed_out_is_401(monkeypatch):
    c, calls = _client(monkeypatch, (200, BATCH), signed_in=False)
    r = c.get("/api/markets/events-calendar/expectations?from=2026-10-21&to=2026-10-22")
    assert (r.status_code, r.json()) == (401, {"detail": "Not authenticated"}) and calls == []
