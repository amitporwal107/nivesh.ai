"""/api/scan-builder routes: TC-A1 … TC-A6 of test_reports/scan_builder_20261103_0431.md.

The real router, flag gate, spec validation, service and engine run; the user resolver, the flag store, MongoDB and the data
layer's network edges (DaaS, the live feed, Kite) are injected. All prices below are hand-made (MOCK — not real data)."""
import copy

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import feature_flags as ff
import feature_gate
from services.scan_builder import data as sd
from services.scan_builder import spec as specmod
from tests.test_scan_builder_data import IST_PREOPEN, FakeDaas, StubRest, bars


class _Cursor:
    def __init__(self, docs): self.docs = docs
    def sort(self, key, direction):
        self.docs.sort(key=lambda d: d.get(key) or "", reverse=direction < 0)
        return self
    def __aiter__(self):
        self._it = iter(self.docs)
        return self
    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class _Res:
    def __init__(self, matched=0, deleted=0): self.matched_count, self.deleted_count = matched, deleted


def _match(d, q): return all(d.get(k) == v for k, v in q.items())


def _proj(d, proj):
    if not proj:
        return copy.deepcopy(d)
    keep = {k for k, v in proj.items() if v}
    drop = {k for k, v in proj.items() if not v}
    if keep:
        return {k: copy.deepcopy(v) for k, v in d.items() if k in keep}
    return {k: copy.deepcopy(v) for k, v in d.items() if k not in drop}


class _Coll:
    def __init__(self, docs=None): self.docs = docs or []
    async def create_index(self, *a, **k): return "ok"
    async def find_one(self, q, proj=None):
        for d in self.docs:
            if _match(d, q):
                return _proj(d, proj)
        return None
    def find(self, q, proj=None): return _Cursor([_proj(d, proj) for d in self.docs if _match(d, q)])
    async def insert_one(self, doc): self.docs.append(copy.deepcopy(doc))
    async def count_documents(self, q): return sum(1 for d in self.docs if _match(d, q))
    async def update_one(self, q, upd):
        for d in self.docs:
            if _match(d, q):
                d.update(copy.deepcopy(upd["$set"]))
                return _Res(matched=1)
        return _Res()
    async def delete_one(self, q):
        for i, d in enumerate(self.docs):
            if _match(d, q):
                del self.docs[i]
                return _Res(deleted=1)
        return _Res()


class _DB:
    def __init__(self, flags=None):
        self.system_config = _Coll([{"key": "feature_flags", "flags": flags or {}}])
        self.users = _Coll([])
        self.scan_builder_scans = _Coll([])
    def __getitem__(self, name): return getattr(self, name)


USERS = {"owner": {"user_id": "u1", "email": "aporwal107@gmail.com"}, "other": {"user_id": "u2", "email": "other@example.com"}}
DAYS = ["2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-11-02"]
ROWS = {"AAA": bars("AAA", DAYS, [100, 101, 102, 103, 106.0]), "CCC": bars("CCC", DAYS, [10, 10.2, 10.1, 10.0, 9.5])}


@pytest.fixture(autouse=True)
def _reset():
    saved = copy.deepcopy(ff._flags); feature_gate._state["at"] = float("-inf")
    import routes.scan_builder as rsb
    rsb._last_run.clear(); rsb._indexes_ready = False
    yield
    ff._flags.clear(); ff._flags.update(saved); feature_gate._state["at"] = float("-inf")


def _client(monkeypatch, tmp_path, *, flags=None, daas=None):
    import routes.scan_builder as rsb
    db = _DB(flags)

    async def resolve(request: Request):
        return copy.deepcopy(USERS[request.headers["X-Test-User"]])

    async def day_quotes(symbols, now=None):
        return {"source": None, "day": None, "as_of": None, "quotes": {}, "why": None}

    async def hol(a, b):
        return None
    data = sd.ScanData(daas_get=(daas or FakeDaas(rows=ROWS)).get, daas_post=(daas or FakeDaas(rows=ROWS)).post,
                       cache_dir=tmp_path, now=lambda: IST_PREOPEN, day_quotes=day_quotes, holidays=hol, rest=StubRest({}), probe_symbols=("AAA", "CCC"))
    if daas is not None:
        data = sd.ScanData(daas_get=daas.get, daas_post=daas.post, cache_dir=tmp_path, now=lambda: IST_PREOPEN,
                           day_quotes=day_quotes, holidays=hol, rest=StubRest({}), probe_symbols=("AAA", "CCC"))
    monkeypatch.setattr(rsb, "get_current_user", resolve)
    monkeypatch.setattr(rsb, "db", db)
    monkeypatch.setattr(rsb, "get_data", lambda: data)
    gate = feature_gate.require_feature("scan_builder", resolve_user=resolve, get_db=lambda: db, clock=lambda: 0.0)
    app = FastAPI(); app.include_router(rsb.router)
    for route in app.routes:
        dep_ = getattr(route, "dependant", None)
        for dep in (dep_.dependencies if dep_ else []):
            if dep.call is not None and getattr(dep.call, "__qualname__", "").startswith("require_feature"):
                app.dependency_overrides[dep.call] = gate
    return TestClient(app), db


def H(who="owner"): return {"X-Test-User": who}


# ── TC-A5 flag ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_flag_defaults_to_the_owner_only(monkeypatch, tmp_path):
    meta = ff.KNOWN_FEATURES["scan_builder"]
    assert meta["default_mode"] == "allowlist" and meta["default_allowlist"] == ["aporwal107@gmail.com"]
    c, _ = _client(monkeypatch, tmp_path)
    assert c.get("/api/scan-builder/catalog", headers=H("other")).status_code == 403
    assert c.post("/api/scan-builder/run", json={"spec": specmod.default_spec()}, headers=H("other")).status_code == 403
    assert c.get("/api/scan-builder/catalog", headers=H("owner")).status_code == 200


# ── TC-A1 catalog ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_catalog_shape(monkeypatch, tmp_path):
    c, _ = _client(monkeypatch, tmp_path)
    r = c.get("/api/scan-builder/catalog", headers=H()).json()
    assert r["refresh_seconds"] == 10
    keys = [u["key"] for u in r["universes"]]
    assert keys[:2] == ["cash", "fno"] and {"nifty50", "nifty500", "niftybank"} <= set(keys)
    assert next(u for u in r["universes"] if u["key"] == "nifty50")["size"] == 1
    tf = {t["key"]: t for t in r["timeframes"]}
    assert tf["1d"]["available"] and tf["1w"]["available"] and tf["1M"]["available"]
    assert not tf["15m"]["available"] and tf["15m"]["reason"]
    assert {"rsi", "supertrend", "psar", "adx"} <= set(m["key"] for m in r["measures"]) if isinstance(r["measures"], list) \
        else {"rsi", "supertrend", "psar", "adx"} <= set(r["measures"])
    assert r["default_spec"]["filters"]["universe"] == "cash" and len(r["templates"]) == 3
    blob = str(r).lower()
    for word in ("buy", "sell", "target", "stop loss", "picks"):
        assert word not in blob, word


# ── TC-A2 run ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_run_default_spec_returns_rows_by_change(monkeypatch, tmp_path):
    c, _ = _client(monkeypatch, tmp_path)
    r = c.post("/api/scan-builder/run", json={"spec": specmod.default_spec()}, headers=H())
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] and j["basis"]["mode"] == "eod" and j["basis"]["eod_date"] == "2026-11-02"
    assert j["universe"]["key"] == "cash" and j["counts"]["universe"] == 2 and j["counts"]["matched"] == 2
    assert [x["symbol"] for x in j["rows"]] == ["AAA", "CCC"]                         # +2.91 % then -5 %
    chg = j["rows"][0]["values"][0]
    assert chg == pytest.approx((106 - 103) / 103 * 100)
    assert j["rows"][0]["name"] == "Aaa Ltd" and j["market"] == {"open": False, "refresh_seconds": 10}
    assert [c_["alias"] for c_ in j["columns"]] == ["% Change", "Price", "Volume"]


def test_run_with_a_filter_and_a_fundamental(monkeypatch, tmp_path):
    c, _ = _client(monkeypatch, tmp_path)
    spec = specmod.default_spec()
    spec["filters"]["children"] = [{
        "id": "f1", "kind": "filter", "op": "gt",
        "left": {"terms": [{"op": None, "operand": {"kind": "fundamental", "field": "market_cap_cr"}}]},
        "right": {"terms": [{"op": None, "operand": {"kind": "number", "value": 1000}}]}}]
    j = c.post("/api/scan-builder/run", json={"spec": spec}, headers=H()).json()
    assert [x["symbol"] for x in j["rows"]] == ["AAA"] and j["nodes"]["f1"]["passed"] == 1


def test_invalid_spec_is_422_with_the_path(monkeypatch, tmp_path):
    c, _ = _client(monkeypatch, tmp_path)
    spec = specmod.default_spec()
    spec["filters"]["universe"] = "nasdaq"
    r = c.post("/api/scan-builder/run", json={"spec": spec}, headers=H())
    assert r.status_code == 422
    d = r.json()["detail"]
    assert d["code"] == "invalid_spec" and d["path"].startswith("filters.universe")
    assert c.post("/api/scan-builder/run", json={"nope": 1}, headers=H()).status_code == 422


# ── TC-A3 rate limit ──────────────────────────────────────────────────────────────────────────────────────────────
def test_two_runs_within_four_seconds_is_429(monkeypatch, tmp_path):
    c, _ = _client(monkeypatch, tmp_path)
    assert c.post("/api/scan-builder/run", json={"spec": specmod.default_spec()}, headers=H()).status_code == 200
    r = c.post("/api/scan-builder/run", json={"spec": specmod.default_spec()}, headers=H())
    assert r.status_code == 429 and r.json()["detail"]["code"] == "run_too_soon" and 0 < r.json()["detail"]["retry_after_s"] <= 4


# ── TC-A6 data unavailable ────────────────────────────────────────────────────────────────────────────────────────
def test_daas_down_is_a_typed_503(monkeypatch, tmp_path):
    c, _ = _client(monkeypatch, tmp_path, daas=FakeDaas(fail=True))
    r = c.post("/api/scan-builder/run", json={"spec": specmod.default_spec()}, headers=H())
    assert r.status_code == 503 and r.json()["detail"]["code"] == "data_unavailable"


# ── TC-A4 saved scans ─────────────────────────────────────────────────────────────────────────────────────────────
def test_scans_crud_copy_and_owner_scope(monkeypatch, tmp_path):
    c, db = _client(monkeypatch, tmp_path, flags={"scan_builder": {"mode": "everyone", "allowlist": []}})
    spec = specmod.default_spec(); spec["name"] = "My scan"
    made = c.post("/api/scan-builder/scans", json={"spec": spec}, headers=H()).json()["scan"]
    sid = made["id"]
    assert made["name"] == "My scan" and made["spec"]["name"] == "My scan"
    assert [s["name"] for s in c.get("/api/scan-builder/scans", headers=H()).json()["scans"]] == ["My scan"]
    assert c.get(f"/api/scan-builder/scans/{sid}", headers=H("other")).status_code == 404       # another user's id
    spec["name"] = "Renamed"
    assert c.put(f"/api/scan-builder/scans/{sid}", json={"spec": spec}, headers=H()).json()["scan"]["name"] == "Renamed"
    cp = c.post(f"/api/scan-builder/scans/{sid}/copy", headers=H()).json()["scan"]
    assert cp["name"] == "Copy of Renamed" and cp["id"] != sid
    assert c.delete(f"/api/scan-builder/scans/{sid}", headers=H("other")).status_code == 404
    assert c.delete(f"/api/scan-builder/scans/{sid}", headers=H()).json() == {"ok": True}
    assert c.get(f"/api/scan-builder/scans/{sid}", headers=H()).status_code == 404
    assert all("user_id" not in d or d["user_id"] == "u1" for d in db.scan_builder_scans.docs)


def test_the_101st_scan_is_409(monkeypatch, tmp_path):
    from services.scan_builder import store
    c, db = _client(monkeypatch, tmp_path)
    db.scan_builder_scans.docs = [{"id": f"x{i}", "user_id": "u1", "name": "n", "updated_at": "t"}
                                  for i in range(store.MAX_SCANS_PER_USER)]
    r = c.post("/api/scan-builder/scans", json={"spec": specmod.default_spec()}, headers=H())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "too_many_scans"
