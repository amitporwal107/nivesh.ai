"""backend/routes/research_drawings.py (TC-11..TC-14 in test_reports/charting_v1_app_surface.md).
No real Mongo: an in-memory fake collection stands in for `deps.db.research_drawings`, and the
feature-gate's user resolver / flag store / clock are injected -- same pattern as
test_move_odds_routes.py / test_research_chart.py -- so the gate, validation and ownership logic
all run for real."""
from __future__ import annotations

import copy

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import feature_flags as ff
import feature_gate
import routes.research_drawings as rd


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


class _DrawingsColl:
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
        self.research_drawings = _DrawingsColl()


def _client(monkeypatch, db: _DB, clock=lambda: 0.0):
    monkeypatch.setattr(rd, "db", db)

    async def resolve(request: Request):
        return copy.deepcopy(USERS[request.headers["X-Test-User"]])
    gate = feature_gate.require_feature("charting", resolve_user=resolve, get_db=lambda: db, clock=clock)
    app = FastAPI()
    app.include_router(rd.router)
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


TRENDLINE = {"symbol": "RELIANCE", "timeframe": "1D", "drawing_type": "TRENDLINE",
             "anchor_points": [{"date": "2024-01-02", "price": 100.0}, {"date": "2024-02-01", "price": 110.0}],
             "style": {"color": "#0f0"}}

HLINE = {"symbol": "RELIANCE", "timeframe": "1D", "drawing_type": "HORIZONTAL_LINE",
        "anchor_points": [{"date": "2024-01-02", "price": 105.0}], "style": {}}


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------

def test_gate_denies_non_allowlisted_accounts(monkeypatch):
    db = _allowed_db()
    c = _client(monkeypatch, db)
    r = c.post("/api/research/drawings", json=TRENDLINE, headers=_hdr("admin"))
    assert r.status_code == 403 and r.json()["detail"] == "feature_not_enabled"
    assert db.research_drawings.docs == []


# ---------------------------------------------------------------------------
# TC-11 POST trendline
# ---------------------------------------------------------------------------

def test_tc11_post_trendline_returns_201_with_caller_user_id_and_a_uuid_drawing_id(monkeypatch):
    import uuid
    db = _allowed_db()
    c = _client(monkeypatch, db)
    r = c.post("/api/research/drawings", json=TRENDLINE, headers=_hdr("a"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user_id"] == "u_a"
    assert uuid.UUID(body["drawing_id"])                       # parses as a real UUID
    assert body["symbol"] == "RELIANCE" and body["drawing_type"] == "TRENDLINE"
    assert body["created_at"] == body["updated_at"]
    assert len(db.research_drawings.docs) == 1


def test_post_horizontal_line_needs_exactly_one_anchor(monkeypatch):
    db = _allowed_db()
    c = _client(monkeypatch, db)
    r = c.post("/api/research/drawings", json=HLINE, headers=_hdr("a"))
    assert r.status_code == 201, r.text
    assert len(r.json()["anchor_points"]) == 1


# ---------------------------------------------------------------------------
# TC-12 GET ?symbol=
# ---------------------------------------------------------------------------

def test_tc12_list_only_returns_the_callers_own_drawings_for_that_symbol(monkeypatch):
    db = _allowed_db()
    c = _client(monkeypatch, db)
    c.post("/api/research/drawings", json=TRENDLINE, headers=_hdr("a"))
    c.post("/api/research/drawings", json=dict(HLINE, symbol="TCS"), headers=_hdr("a"))
    c.post("/api/research/drawings", json=TRENDLINE, headers=_hdr("b"))

    r = c.get("/api/research/drawings?symbol=RELIANCE", headers=_hdr("a"))
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1 and rows[0]["user_id"] == "u_a" and rows[0]["symbol"] == "RELIANCE"

    r = c.get("/api/research/drawings?symbol=TCS", headers=_hdr("a"))
    assert len(r.json()) == 1

    r = c.get("/api/research/drawings?symbol=RELIANCE", headers=_hdr("b"))
    assert len(r.json()) == 1 and r.json()[0]["user_id"] == "u_b"


# ---------------------------------------------------------------------------
# TC-13 ownership -- 404, not 403; the other user's doc is untouched
# ---------------------------------------------------------------------------

def test_tc13_user_b_get_patch_delete_on_user_as_drawing_is_404_and_leaves_it_unchanged(monkeypatch):
    db = _allowed_db()
    c = _client(monkeypatch, db)
    created = c.post("/api/research/drawings", json=TRENDLINE, headers=_hdr("a")).json()
    drawing_id = created["drawing_id"]
    original_updated_at = created["updated_at"]

    r = c.get(f"/api/research/drawings/{drawing_id}", headers=_hdr("b"))
    assert r.status_code == 404 and r.json()["detail"] == "not_found"

    r = c.patch(f"/api/research/drawings/{drawing_id}", json={"style": {"color": "#f00"}}, headers=_hdr("b"))
    assert r.status_code == 404 and r.json()["detail"] == "not_found"

    r = c.delete(f"/api/research/drawings/{drawing_id}", headers=_hdr("b"))
    assert r.status_code == 404 and r.json()["detail"] == "not_found"

    current = db.research_drawings.docs[0]
    assert current["updated_at"] == original_updated_at
    assert current["style"] == TRENDLINE["style"]

    # Owner A can still fetch/patch/delete their own drawing -- the 404s above were scoped to B.
    r = c.get(f"/api/research/drawings/{drawing_id}", headers=_hdr("a"))
    assert r.status_code == 200 and r.json()["drawing_id"] == drawing_id


def test_unknown_drawing_id_is_also_404_no_leak_between_the_two_cases(monkeypatch):
    db = _allowed_db()
    c = _client(monkeypatch, db)
    r1 = c.get("/api/research/drawings/does-not-exist-at-all", headers=_hdr("a"))
    created = c.post("/api/research/drawings", json=TRENDLINE, headers=_hdr("a")).json()
    r2 = c.get(f"/api/research/drawings/{created['drawing_id']}", headers=_hdr("b"))
    assert r1.status_code == r2.status_code == 404
    assert r1.json() == r2.json() == {"detail": "not_found"}


# ---------------------------------------------------------------------------
# TC-14 invalid drawing_type / wrong anchor count
# ---------------------------------------------------------------------------

def test_tc14_invalid_drawing_type_is_422(monkeypatch):
    db = _allowed_db()
    c = _client(monkeypatch, db)
    bad = dict(TRENDLINE, drawing_type="RECTANGLE")
    r = c.post("/api/research/drawings", json=bad, headers=_hdr("a"))
    assert r.status_code == 422
    assert db.research_drawings.docs == []


def test_tc14_trendline_with_fewer_than_two_anchors_is_422(monkeypatch):
    db = _allowed_db()
    c = _client(monkeypatch, db)
    bad = dict(TRENDLINE, anchor_points=[{"date": "2024-01-02", "price": 100.0}])
    r = c.post("/api/research/drawings", json=bad, headers=_hdr("a"))
    assert r.status_code == 422
    assert db.research_drawings.docs == []


def test_tc14_horizontal_line_with_two_anchors_is_422(monkeypatch):
    db = _allowed_db()
    c = _client(monkeypatch, db)
    bad = dict(HLINE, anchor_points=TRENDLINE["anchor_points"])
    r = c.post("/api/research/drawings", json=bad, headers=_hdr("a"))
    assert r.status_code == 422


def test_tc14_patch_changing_only_anchor_points_still_checks_the_existing_drawing_type(monkeypatch):
    db = _allowed_db()
    c = _client(monkeypatch, db)
    created = c.post("/api/research/drawings", json=TRENDLINE, headers=_hdr("a")).json()
    r = c.patch(f"/api/research/drawings/{created['drawing_id']}",
               json={"anchor_points": [{"date": "2024-01-02", "price": 100.0}]}, headers=_hdr("a"))
    assert r.status_code == 422                     # still TRENDLINE, now only 1 anchor -> invalid


def test_patch_updates_fields_and_bumps_updated_at(monkeypatch):
    db = _allowed_db()
    c = _client(monkeypatch, db)
    created = c.post("/api/research/drawings", json=TRENDLINE, headers=_hdr("a")).json()
    r = c.patch(f"/api/research/drawings/{created['drawing_id']}",
               json={"style": {"color": "#00f"}}, headers=_hdr("a"))
    assert r.status_code == 200
    body = r.json()
    assert body["style"] == {"color": "#00f"}
    assert body["updated_at"] >= created["updated_at"]


def test_patch_with_no_fields_is_400(monkeypatch):
    db = _allowed_db()
    c = _client(monkeypatch, db)
    created = c.post("/api/research/drawings", json=TRENDLINE, headers=_hdr("a")).json()
    r = c.patch(f"/api/research/drawings/{created['drawing_id']}", json={}, headers=_hdr("a"))
    assert r.status_code == 400


def test_delete_removes_the_drawing_and_is_idempotent_404_on_second_call(monkeypatch):
    db = _allowed_db()
    c = _client(monkeypatch, db)
    created = c.post("/api/research/drawings", json=TRENDLINE, headers=_hdr("a")).json()
    r = c.delete(f"/api/research/drawings/{created['drawing_id']}", headers=_hdr("a"))
    assert r.status_code == 200 and r.json() == {"status": "deleted", "drawing_id": created["drawing_id"]}
    assert db.research_drawings.docs == []
    r2 = c.delete(f"/api/research/drawings/{created['drawing_id']}", headers=_hdr("a"))
    assert r2.status_code == 404
