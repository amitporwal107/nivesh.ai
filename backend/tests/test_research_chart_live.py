"""Research → Charts LIVE bars (/api/research/chart-live/{symbol}/ohlcv).

The route exists because the frozen snapshot holds 50 large caps and a paper trade is almost never
one of them. What it must never do is launder live DB reads into the snapshot's guarantees, so the
provenance and pit_status assertions below are as much the point as the bar shaping.
"""
import copy

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import feature_flags as ff
import feature_gate


class _Coll:
    def __init__(self, docs): self.docs = docs
    async def find_one(self, q, *a, **k):
        for d in self.docs:
            if all(d.get(key) == v for key, v in q.items()):
                return copy.deepcopy(d)
        return None


class _DB:
    def __init__(self, flags=None):
        self.system_config = _Coll([{"key": "feature_flags", "flags": flags or {}}])
        self.users = _Coll([])


USERS = {"invited": {"user_id": "u1", "email": "invited@example.com", "role": "user"},
         "other": {"user_id": "u2", "email": "other@example.com", "role": "user"}}
ALLOW = {"charting": {"mode": "allowlist", "allowlist": ["invited@example.com"]}}


def _rows(*rows):
    """DaaS returns newest-first; these helpers keep that direction so the reversal is really tested."""
    return {"data": list(rows)}


def _row(d, o, h, l, c, v=1000.0, **extra):
    base = {"symbol": "PNCINFRA", "as_of_date": d, "adj_open": o, "adj_high": h,
            "adj_low": l, "adj_close": c, "adj_volume": v}
    base.update(extra)
    return base


@pytest.fixture(autouse=True)
def _reset_flags():
    saved = copy.deepcopy(ff._flags); feature_gate._state["at"] = float("-inf")
    yield
    ff._flags.clear(); ff._flags.update(saved); feature_gate._state["at"] = float("-inf")


def _client(monkeypatch, db, daas=(200, None), configured=True):
    import routes.research_chart_live as rcl
    from services.copilot_tools import daas_client

    async def resolve(request: Request):
        return copy.deepcopy(USERS[request.headers["X-Test-User"]])
    gate = feature_gate.require_feature("charting", resolve_user=resolve, get_db=lambda: db, clock=lambda: 0.0)
    calls = []

    async def get_raw(path, params=None, timeout=30):
        calls.append((path, params))
        if isinstance(daas, Exception):
            raise daas
        return daas
    monkeypatch.setattr(daas_client, "get_raw", get_raw)
    monkeypatch.setattr(daas_client, "is_configured", lambda: configured)
    app = FastAPI(); app.include_router(rcl.router)
    for route in app.routes:
        dep_list = getattr(route, "dependant", None).dependencies if getattr(route, "dependant", None) else []
        for dep in dep_list:
            if dep.call is not None and getattr(dep.call, "__qualname__", "").startswith("require_feature"):
                app.dependency_overrides[dep.call] = gate
    return TestClient(app), calls


def _get(c, path, who="invited"):
    return c.get(path, headers={"X-Test-User": who})


THREE = _rows(_row("2026-09-18", 12.0, 13.0, 11.5, 12.5, last_event_type="SPLIT"),
              _row("2026-09-17", 11.0, 12.2, 10.9, 12.0),
              _row("2026-09-16", 10.0, 11.0, 9.8, 10.8))


def test_the_charting_allowlist_gates_it(monkeypatch):
    c, _ = _client(monkeypatch, _DB(flags=ALLOW), daas=(200, THREE))
    assert _get(c, "/api/research/chart-live/PNCINFRA/ohlcv", "other").status_code == 403
    assert _get(c, "/api/research/chart-live/PNCINFRA/ohlcv", "invited").status_code == 200


def test_bars_come_back_oldest_first(monkeypatch):
    """DaaS pages newest-first; a chart plots oldest-first. Getting this backwards draws the trade in reverse."""
    c, _ = _client(monkeypatch, _DB(flags=ALLOW), daas=(200, THREE))
    bars = _get(c, "/api/research/chart-live/PNCINFRA/ohlcv").json()["bars"]
    assert [b[0] for b in bars] == ["2026-09-16", "2026-09-17", "2026-09-18"]
    assert bars[0] == ["2026-09-16", 10.0, 11.0, 9.8, 10.8, 1000.0]


def test_it_asks_the_adjusted_endpoint_not_the_raw_one(monkeypatch):
    """Raw bhavcopy joined to anything adjusted reads a 1:6 split as -83%. Never serve raw here."""
    c, calls = _client(monkeypatch, _DB(flags=ALLOW), daas=(200, THREE))
    _get(c, "/api/research/chart-live/PNCINFRA/ohlcv")
    path, params = calls[0]
    assert path == "/prices/adjusted/PNCINFRA"
    assert "/eod/" not in path
    assert params["limit"] == 5000


def test_it_never_claims_the_snapshot_guarantees(monkeypatch):
    c, _ = _client(monkeypatch, _DB(flags=ALLOW), daas=(200, THREE))
    body = _get(c, "/api/research/chart-live/PNCINFRA/ohlcv").json()
    assert body["pit_status"] == "PIT_UNVERIFIED"
    assert body["provenance"]["source_mode"] == "live"
    assert body["provenance"]["adjustment_status"] == "SPLIT_BONUS_ADJUSTED"
    assert body["provenance"]["provider"] == "nidp.prices_eod_adjusted"


@pytest.mark.parametrize("bad, why", [
    (_row("2026-09-18", 12.0, 13.0, 11.5, None), "missing close"),
    (_row("2026-09-18", 12.0, 11.0, 11.5, 12.5), "high below the open"),
    (_row("2026-09-18", 12.0, 13.0, 12.5, 12.4), "low above the close"),
    (_row("2026-09-18", 0.0, 13.0, 11.5, 12.5), "non-positive price"),
])
def test_an_impossible_bar_is_dropped_and_declared(monkeypatch, bad, why):
    c, _ = _client(monkeypatch, _DB(flags=ALLOW),
                   daas=(200, _rows(bad, _row("2026-09-17", 11.0, 12.2, 10.9, 12.0))))
    body = _get(c, "/api/research/chart-live/PNCINFRA/ohlcv").json()
    assert len(body["bars"]) == 1, why
    assert body["data_quality_status"] == "PARTIAL"
    assert body["findings"][0]["rule_id"] == "incomplete_bars_dropped"
    assert body["findings"][0]["observed"]["dropped"] == 1


def test_a_clean_page_is_valid_with_no_findings(monkeypatch):
    c, _ = _client(monkeypatch, _DB(flags=ALLOW), daas=(200, THREE))
    body = _get(c, "/api/research/chart-live/PNCINFRA/ohlcv").json()
    assert body["data_quality_status"] == "VALID"
    assert body["findings"] == []
    assert body["provenance"]["last_bar_date"] == "2026-09-18"


def test_a_symbol_with_no_bars_is_404_not_an_empty_chart(monkeypatch):
    c, _ = _client(monkeypatch, _DB(flags=ALLOW), daas=(200, {"data": []}))
    assert _get(c, "/api/research/chart-live/NOSUCH/ohlcv").status_code == 404


def test_all_bars_unplottable_is_404_rather_than_an_empty_series(monkeypatch):
    c, _ = _client(monkeypatch, _DB(flags=ALLOW),
                   daas=(200, _rows(_row("2026-09-18", 12.0, 11.0, 11.5, 12.5))))
    r = _get(c, "/api/research/chart-live/PNCINFRA/ohlcv")
    assert r.status_code == 404 and r.json()["detail"] == "no_plottable_bars"


def test_an_unexpected_upstream_shape_is_502(monkeypatch):
    c, _ = _client(monkeypatch, _DB(flags=ALLOW), daas=(200, {"unexpected": True}))
    assert _get(c, "/api/research/chart-live/PNCINFRA/ohlcv").status_code == 502


def test_the_date_range_is_passed_through(monkeypatch):
    c, calls = _client(monkeypatch, _DB(flags=ALLOW), daas=(200, THREE))
    _get(c, "/api/research/chart-live/PNCINFRA/ohlcv?start=2026-01-01&end=2026-09-18")
    _, params = calls[0]
    assert params["start"] == "2026-01-01" and params["end"] == "2026-09-18"


def test_a_malformed_symbol_is_refused_before_any_upstream_call(monkeypatch):
    c, calls = _client(monkeypatch, _DB(flags=ALLOW), daas=(200, THREE))
    assert _get(c, "/api/research/chart-live/no%20such/ohlcv").status_code == 422
    assert calls == []
