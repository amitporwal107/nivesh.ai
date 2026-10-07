"""backend/routes/research_chart_layouts.py (TC-140..TC-152 in test_reports/charting_w2_layouts.md).
No real Mongo: an in-memory fake collection stands in for `deps.db.research_chart_layouts`, and the
feature-gate's user resolver / flag store / clock are injected -- same pattern as
test_research_drawings.py / test_move_odds_routes.py -- so the gate, validation and ownership logic
all run for real. The CSRF cases additionally mount the real `middleware.CsrfProtectMiddleware`."""
from __future__ import annotations

import copy

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import feature_flags as ff
import feature_gate
import routes.research_chart_layouts as rcl
from middleware import CsrfProtectMiddleware


USERS = {"a": {"user_id": "u_a", "email": "a@example.com", "role": "user"},
         "b": {"user_id": "u_b", "email": "b@example.com", "role": "user"},
         "admin": {"user_id": "u_admin", "email": "admin@example.com", "role": "admin", "is_admin": True}}


@pytest.fixture(autouse=True)
def _reset_flags():
    saved = copy.deepcopy(ff._flags)
    feature_gate._state["at"] = float("-inf")
    yield
    ff._flags.clear()
    ff._flags.update(saved)
    feature_gate._state["at"] = float("-inf")


class _FlagColl:
    def __init__(self, flags):
        self.doc = {"key": "feature_flags", "flags": flags}

    async def find_one(self, q, proj=None):
        return copy.deepcopy(self.doc)


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, key, direction=1):
        self._docs.sort(key=lambda d: d.get(key), reverse=(direction < 0))
        return self

    async def to_list(self, n):
        return [dict(d) for d in self._docs[:n]]


class _UpdateResult:
    def __init__(self, matched):
        self.matched_count = matched


class _DeleteResult:
    def __init__(self, deleted):
        self.deleted_count = deleted


def _project(d, proj):
    d = dict(d)
    if proj and proj.get("_id") == 0:
        d.pop("_id", None)
    return d


class _LayoutsColl:
    def __init__(self):
        self.docs: list[dict] = []

    async def insert_one(self, doc):
        self.docs.append(dict(doc))

    async def find_one(self, query, proj=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in query.items()):
                return _project(d, proj)
        return None

    def find(self, query, proj=None):
        matched = [d for d in self.docs if all(d.get(k) == v for k, v in query.items())]
        return _Cursor([_project(d, proj) for d in matched])

    async def update_one(self, query, update):
        for d in self.docs:
            if all(d.get(k) == v for k, v in query.items()):
                d.update(update["$set"])
                return _UpdateResult(1)
        return _UpdateResult(0)

    async def delete_one(self, query):
        for i, d in enumerate(self.docs):
            if all(d.get(k) == v for k, v in query.items()):
                del self.docs[i]
                return _DeleteResult(1)
        return _DeleteResult(0)


class _DB:
    def __init__(self, flags=None):
        self.system_config = _FlagColl(flags or {})
        self.users = _FlagColl({})               # never queried in these tests (no advisor/client impersonation)
        self.research_chart_layouts = _LayoutsColl()


def _client(monkeypatch, db: _DB, clock=lambda: 0.0, with_csrf: bool = False):
    monkeypatch.setattr(rcl, "db", db)

    async def resolve(request: Request):
        return copy.deepcopy(USERS[request.headers["X-Test-User"]])
    gate = feature_gate.require_feature("charting", resolve_user=resolve, get_db=lambda: db, clock=clock)
    app = FastAPI()
    app.include_router(rcl.router)
    if with_csrf:
        app.add_middleware(CsrfProtectMiddleware)
    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        for dep in (dependant.dependencies if dependant else []):
            if dep.call is not None and getattr(dep.call, "__qualname__", "").startswith("require_feature"):
                app.dependency_overrides[dep.call] = gate
    return TestClient(app)


def _allowed_db(*extra_emails):
    return _DB(flags={"charting": {"mode": "allowlist", "allowlist": ["a@example.com", "b@example.com", *extra_emails]}})


def _hdr(who):
    return {"X-Test-User": who}


MINIMAL = {"symbol": "RELIANCE"}

FULL_PAYLOAD = {
    "name": "My swing setup",
    "symbol": "RELIANCE",
    "timeframe": "1D",
    "chart_type": "candles",
    "indicators": [
        {"instance_id": "i1", "indicator_id": "sma", "preset_id": "sma_20", "pane_index": 0,
         "visible": True, "style": {"color": "#0f0"}},
        {"instance_id": "i2", "indicator_id": "rsi", "preset_id": "rsi_14", "pane_index": 1,
         "visible": False, "style": {}},
    ],
    "panes": [
        {"pane_id": "p0", "order": 0, "height": 400.0, "collapsed": False},
        {"pane_id": "p1", "order": 1, "height": 120.0, "collapsed": True},
    ],
    "visible_range": {"from_date": "2024-01-02", "to_date": "2024-06-28"},
    "drawing_visibility": {"drawing-1": True, "drawing-2": False},
    "sidebar_state": {"collapsed": False, "active_tab": "patterns"},
}


# ---------------------------------------------------------------------------
# TC-140 Gate
# ---------------------------------------------------------------------------

def test_tc140_gate_denies_non_allowlisted_account_on_every_verb(monkeypatch):
    db = _allowed_db()
    c = _client(monkeypatch, db)
    r = c.post("/api/research/chart-layouts", json=MINIMAL, headers=_hdr("admin"))
    assert r.status_code == 403 and r.json()["detail"] == "feature_not_enabled"
    assert db.research_chart_layouts.docs == []

    r = c.get("/api/research/chart-layouts", headers=_hdr("admin"))
    assert r.status_code == 403 and r.json()["detail"] == "feature_not_enabled"

    r = c.patch("/api/research/chart-layouts/anything", json={"name": "x"}, headers=_hdr("admin"))
    assert r.status_code == 403 and r.json()["detail"] == "feature_not_enabled"

    r = c.delete("/api/research/chart-layouts/anything", headers=_hdr("admin"))
    assert r.status_code == 403 and r.json()["detail"] == "feature_not_enabled"


# ---------------------------------------------------------------------------
# TC-141 POST create
# ---------------------------------------------------------------------------

def test_tc141_post_returns_201_with_server_assigned_id_owner_timestamps_and_default_name(monkeypatch):
    import uuid
    db = _allowed_db()
    c = _client(monkeypatch, db)
    r = c.post("/api/research/chart-layouts", json=MINIMAL, headers=_hdr("a"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user_id"] == "u_a"
    assert uuid.UUID(body["layout_id"])                        # parses as a real UUID
    assert body["name"] == "Unnamed"
    assert body["symbol"] == "RELIANCE"
    assert body["created_at"] == body["updated_at"]
    assert len(db.research_chart_layouts.docs) == 1


# ---------------------------------------------------------------------------
# TC-142 GET list
# ---------------------------------------------------------------------------

def test_tc142_list_returns_only_the_callers_own_layouts_newest_first(monkeypatch):
    db = _allowed_db()
    c = _client(monkeypatch, db)
    c.post("/api/research/chart-layouts", json=dict(MINIMAL, name="first"), headers=_hdr("a"))
    c.post("/api/research/chart-layouts", json=dict(MINIMAL, name="second"), headers=_hdr("a"))
    c.post("/api/research/chart-layouts", json=dict(MINIMAL, name="bs-layout"), headers=_hdr("b"))

    # Force distinct created_at ordering (both were created at the fake clock's fixed instant).
    db.research_chart_layouts.docs[0]["created_at"] = "2024-01-01T00:00:00+00:00"
    db.research_chart_layouts.docs[1]["created_at"] = "2024-01-02T00:00:00+00:00"

    r = c.get("/api/research/chart-layouts", headers=_hdr("a"))
    assert r.status_code == 200
    rows = r.json()
    assert [row["name"] for row in rows] == ["second", "first"]   # newest first
    assert all(row["user_id"] == "u_a" for row in rows)

    r = c.get("/api/research/chart-layouts", headers=_hdr("b"))
    rows = r.json()
    assert len(rows) == 1 and rows[0]["user_id"] == "u_b" and rows[0]["name"] == "bs-layout"


# ---------------------------------------------------------------------------
# TC-143 PATCH rename
# ---------------------------------------------------------------------------

def test_tc143_patch_rename_bumps_updated_at_and_leaves_other_fields(monkeypatch):
    db = _allowed_db()
    c = _client(monkeypatch, db)
    created = c.post("/api/research/chart-layouts", json=MINIMAL, headers=_hdr("a")).json()
    r = c.patch(f"/api/research/chart-layouts/{created['layout_id']}",
               json={"name": "Renamed"}, headers=_hdr("a"))
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Renamed"
    assert body["symbol"] == "RELIANCE"
    assert body["chart_type"] == "candles"
    assert body["updated_at"] >= created["updated_at"]


# ---------------------------------------------------------------------------
# TC-144 Round trip (AC9): a layout restores symbol, timeframe, chart type,
# indicators, panes and range -- assert on the stored document.
# ---------------------------------------------------------------------------

def test_tc144_full_payload_round_trips_on_create_and_on_patch(monkeypatch):
    db = _allowed_db()
    c = _client(monkeypatch, db)
    r = c.post("/api/research/chart-layouts", json=FULL_PAYLOAD, headers=_hdr("a"))
    assert r.status_code == 201, r.text
    body = r.json()

    stored = db.research_chart_layouts.docs[0]
    for field in ("symbol", "timeframe", "chart_type", "indicators", "panes",
                  "visible_range", "drawing_visibility", "sidebar_state"):
        assert stored[field] == FULL_PAYLOAD[field], field
        assert body[field] == FULL_PAYLOAD[field], field

    # Now PATCH a new visible_range + drop to one indicator; everything else must survive untouched.
    new_range = {"from_date": "2024-03-01", "to_date": "2024-09-01"}
    new_indicators = [FULL_PAYLOAD["indicators"][0]]
    r = c.patch(f"/api/research/chart-layouts/{body['layout_id']}",
               json={"visible_range": new_range, "indicators": new_indicators}, headers=_hdr("a"))
    assert r.status_code == 200, r.text
    patched = r.json()
    assert patched["visible_range"] == new_range
    assert patched["indicators"] == new_indicators
    assert patched["panes"] == FULL_PAYLOAD["panes"]              # untouched by this PATCH
    assert patched["symbol"] == FULL_PAYLOAD["symbol"]
    assert patched["chart_type"] == FULL_PAYLOAD["chart_type"]

    stored = db.research_chart_layouts.docs[0]
    assert stored["visible_range"] == new_range
    assert stored["indicators"] == new_indicators
    assert stored["panes"] == FULL_PAYLOAD["panes"]


# ---------------------------------------------------------------------------
# TC-145 DELETE
# ---------------------------------------------------------------------------

def test_tc145_delete_removes_the_layout_and_is_idempotent_404_on_second_call(monkeypatch):
    db = _allowed_db()
    c = _client(monkeypatch, db)
    created = c.post("/api/research/chart-layouts", json=MINIMAL, headers=_hdr("a")).json()
    r = c.delete(f"/api/research/chart-layouts/{created['layout_id']}", headers=_hdr("a"))
    assert r.status_code == 200 and r.json() == {"status": "deleted", "layout_id": created["layout_id"]}
    assert db.research_chart_layouts.docs == []
    r2 = c.delete(f"/api/research/chart-layouts/{created['layout_id']}", headers=_hdr("a"))
    assert r2.status_code == 404


# ---------------------------------------------------------------------------
# TC-146 Ownership -- 404 not 403, no leak, target row untouched
# ---------------------------------------------------------------------------

def test_tc146_user_b_patch_delete_on_user_as_layout_is_404_and_leaves_it_unchanged(monkeypatch):
    db = _allowed_db()
    c = _client(monkeypatch, db)
    created = c.post("/api/research/chart-layouts", json=MINIMAL, headers=_hdr("a")).json()
    layout_id = created["layout_id"]
    original_updated_at = created["updated_at"]

    r = c.patch(f"/api/research/chart-layouts/{layout_id}", json={"name": "hijacked"}, headers=_hdr("b"))
    assert r.status_code == 404 and r.json()["detail"] == "not_found"

    r = c.delete(f"/api/research/chart-layouts/{layout_id}", headers=_hdr("b"))
    assert r.status_code == 404 and r.json()["detail"] == "not_found"

    current = db.research_chart_layouts.docs[0]
    assert current["updated_at"] == original_updated_at
    assert current["name"] == "Unnamed"

    # B's own list never contained A's layout in the first place.
    r = c.get("/api/research/chart-layouts", headers=_hdr("b"))
    assert r.json() == []

    # Owner A can still patch/delete her own layout -- the 404s above were scoped to B.
    r = c.patch(f"/api/research/chart-layouts/{layout_id}", json={"name": "still mine"}, headers=_hdr("a"))
    assert r.status_code == 200 and r.json()["name"] == "still mine"


def test_tc146_unknown_layout_id_is_also_404_no_leak_between_the_two_cases(monkeypatch):
    db = _allowed_db()
    c = _client(monkeypatch, db)
    r1 = c.delete("/api/research/chart-layouts/does-not-exist-at-all", headers=_hdr("a"))
    created = c.post("/api/research/chart-layouts", json=MINIMAL, headers=_hdr("a")).json()
    r2 = c.delete(f"/api/research/chart-layouts/{created['layout_id']}", headers=_hdr("b"))
    assert r1.status_code == r2.status_code == 404
    assert r1.json() == r2.json() == {"detail": "not_found"}


# ---------------------------------------------------------------------------
# TC-147 CSRF origin check on POST/PATCH/DELETE
# ---------------------------------------------------------------------------

def test_tc147_csrf_blocks_disallowed_cross_origin_mutations_with_a_session_cookie(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    db = _allowed_db()
    c = _client(monkeypatch, db, with_csrf=True)
    cookie_and_origin = {"Cookie": "session_token=faketoken", "Origin": "https://evil.example.com",
                         **_hdr("a")}

    r = c.post("/api/research/chart-layouts", json=MINIMAL, headers=cookie_and_origin)
    assert r.status_code == 403 and r.json()["error"] == "CSRF_BLOCKED"
    assert db.research_chart_layouts.docs == []                  # never reached the route

    r = c.patch("/api/research/chart-layouts/whatever", json={"name": "x"}, headers=cookie_and_origin)
    assert r.status_code == 403 and r.json()["error"] == "CSRF_BLOCKED"

    r = c.delete("/api/research/chart-layouts/whatever", headers=cookie_and_origin)
    assert r.status_code == 403 and r.json()["error"] == "CSRF_BLOCKED"


def test_tc147_csrf_allows_same_origin_and_no_origin_mutations_through_to_the_route(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    db = _allowed_db()
    c = _client(monkeypatch, db, with_csrf=True)

    # Browser same-site request: allowed Origin.
    good = {"Cookie": "session_token=faketoken", "Origin": "https://staging.niveshcopilot.com", **_hdr("a")}
    r = c.post("/api/research/chart-layouts", json=MINIMAL, headers=good)
    assert r.status_code == 201, r.text

    # Non-browser / same-origin fetch with no Origin header at all: middleware only checks when Origin is present.
    no_origin = {"Cookie": "session_token=faketoken", **_hdr("a")}
    r = c.delete(f"/api/research/chart-layouts/{r.json()['layout_id']}", headers=no_origin)
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# TC-148..151 Validation -- reason codes, nothing stored
# ---------------------------------------------------------------------------

def test_tc148_too_many_indicator_instances_is_422_too_long(monkeypatch):
    db = _allowed_db()
    c = _client(monkeypatch, db)
    too_many = dict(MINIMAL, indicators=[
        {"instance_id": f"i{n}", "indicator_id": "sma", "preset_id": "sma_20", "pane_index": 0}
        for n in range(41)
    ])
    r = c.post("/api/research/chart-layouts", json=too_many, headers=_hdr("a"))
    assert r.status_code == 422
    errors = r.json()["detail"]
    assert any(e.get("type") == "too_long" and e["loc"][-1] == "indicators" for e in errors), errors
    assert db.research_chart_layouts.docs == []


def test_tc149_wrong_type_for_indicators_is_422(monkeypatch):
    db = _allowed_db()
    c = _client(monkeypatch, db)
    bad = dict(MINIMAL, indicators="not-a-list")
    r = c.post("/api/research/chart-layouts", json=bad, headers=_hdr("a"))
    assert r.status_code == 422
    errors = r.json()["detail"]
    assert any(e["loc"][-1] == "indicators" for e in errors), errors
    assert db.research_chart_layouts.docs == []


def test_tc150_unknown_top_level_field_is_422_extra_forbidden(monkeypatch):
    db = _allowed_db()
    c = _client(monkeypatch, db)
    bad = dict(MINIMAL, some_field_that_does_not_exist="x")
    r = c.post("/api/research/chart-layouts", json=bad, headers=_hdr("a"))
    assert r.status_code == 422
    errors = r.json()["detail"]
    assert any(e.get("type") == "extra_forbidden" for e in errors), errors
    assert db.research_chart_layouts.docs == []


def test_tc151_invalid_chart_type_is_422_with_reason_code_on_create_and_patch(monkeypatch):
    db = _allowed_db()
    c = _client(monkeypatch, db)
    bad = dict(MINIMAL, chart_type="candlesticks")
    r = c.post("/api/research/chart-layouts", json=bad, headers=_hdr("a"))
    assert r.status_code == 422
    assert r.json()["detail"].startswith("chart_type: must be one of")
    assert db.research_chart_layouts.docs == []

    created = c.post("/api/research/chart-layouts", json=MINIMAL, headers=_hdr("a")).json()
    r = c.patch(f"/api/research/chart-layouts/{created['layout_id']}",
               json={"chart_type": "candlesticks"}, headers=_hdr("a"))
    assert r.status_code == 422
    assert r.json()["detail"].startswith("chart_type: must be one of")


# ---------------------------------------------------------------------------
# TC-152 PATCH with no fields
# ---------------------------------------------------------------------------

def test_tc152_patch_with_no_fields_is_400(monkeypatch):
    db = _allowed_db()
    c = _client(monkeypatch, db)
    created = c.post("/api/research/chart-layouts", json=MINIMAL, headers=_hdr("a")).json()
    r = c.patch(f"/api/research/chart-layouts/{created['layout_id']}", json={}, headers=_hdr("a"))
    assert r.status_code == 400
    assert r.json()["detail"] == "no_fields_to_update"
