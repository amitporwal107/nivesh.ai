"""The shared strategy store, v2, through the real routes on a real PostgreSQL (Strategy Copilot Phase 1.1).

Covers TC-14 … TC-29 of test_reports/strategy_store_v2_20261028.md.

NEEDS a throwaway PostgreSQL 16 server: set STRATEGY_STORE_TEST_PG to a superuser URL (for example
postgresql://postgres:pw@ssv2-pg:5432/postgres). Without it the module is SKIPPED, which is why CI (no Postgres) does not
run it; the pure suites (test_strategy_store_v2_model.py, test_strategy_store_v1_parity.py) do run in CI. The fixture
creates two fresh databases and drops them afterwards:
  * `pre`  — migrations 020, 115, 024 (the schema staging has today) and six staging-shaped v1 strategies;
  * `post` — the same, then backend/migrations/026_strategy_store_v2.sql applied TWICE (TC-29).

Replaced, and by what:
  * `route.get_current_user`              reads the test's `X-Test-User` header (MOCK user ids);
  * `strategy_store.count_open_paper_trades`  a dict (MOCK — the desk's Mongo paper trades);
  * nothing else: the SQL, the migration, the trigger, the validator and the routes run for real.
MOCK — not real data: every strategy, run and price below is invented (the wizard bodies come from the shared contract
fixture frontend-v5/e2e/fixtures/contract-strategy-store-v2.json).
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlsplit, urlunsplit

import pytest

PG = os.environ.get("STRATEGY_STORE_TEST_PG")
pytestmark = pytest.mark.skipif(not PG, reason="needs STRATEGY_STORE_TEST_PG (a throwaway PostgreSQL 16 superuser URL)")

import asyncpg  # noqa: E402
from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from routes import strategy_builder as route  # noqa: E402
from services import pg_client, strategy_store as store  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
BASE_MIGRATIONS = [REPO / "backend/nidp/migrations/020_strategy_builder_core.sql",
                   REPO / "backend/nidp/migrations/115_strategy_userid_text.sql",
                   REPO / "backend/migrations/024_strategy_config.sql"]
STORE_V2 = REPO / "backend/migrations/026_strategy_store_v2.sql"
CONTRACT = json.loads((REPO / "frontend-v5/e2e/fixtures/contract-strategy-store-v2.json").read_text(encoding="utf-8"))
BULL = CONTRACT["create_bull_call_spread"]
COVERED = CONTRACT["create_covered_call_stock"]
API = "/api/strategy-builder"
LEGACY_LIST_KEYS = {"id", "owner_id", "name", "description", "asset_class", "is_public_template", "is_archived",
                    "created_at", "updated_at"}
LEGACY_VERSION_KEYS = {"id", "strategy_id", "version_no", "definition", "dsl_version", "is_active", "created_at", "created_by"}


def v1_definition(name: str) -> Dict[str, Any]:
    """A v1 equity DSL document the staging route accepted on 2026-10-28 (scratchpad staging_phase0_check.py)."""
    return {"version": "1", "asset_class": "STOCK", "name": name, "universe": {"type": "index", "ref": "NIFTY50"},
            "entry": {"all_of": [{"feature": "rsi14", "op": ">", "value": 55}]},
            "exit": {"stoploss_pct": 5, "target_rr": 2, "max_hold_days": 10},
            "ranking": {"by": "return_20d_pct", "limit": 5, "order": "desc"}, "rebalance": "daily"}


def _db_url(name: str) -> str:
    parts = urlsplit(PG)
    return urlunsplit(parts._replace(path="/" + name))


async def _setup(names: Dict[str, str]) -> None:
    admin = await asyncpg.connect(PG)
    try:
        for n in names.values():
            await admin.execute(f'CREATE DATABASE "{n}"')
    finally:
        await admin.close()
    for key, n in names.items():
        conn = await asyncpg.connect(_db_url(n))
        try:
            # 020 records itself in nidp.schema_migrations (the NIDP runner's table); the app database has none.
            await conn.execute("CREATE SCHEMA IF NOT EXISTS nidp; CREATE TABLE IF NOT EXISTS nidp.schema_migrations"
                               "(filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT now())")
            for f in BASE_MIGRATIONS:
                await conn.execute(f.read_text(encoding="utf-8"))
            for i in range(6):                     # staging holds 6 v1 STOCK strategies, one version each
                sid = await conn.fetchval("INSERT INTO strategies (owner_id, name, asset_class) VALUES ($1, $2, 'STOCK') "
                                          "RETURNING id", "user_staging_shape", f"v1 strategy {i}")
                await conn.execute("INSERT INTO strategy_versions (strategy_id, version_no, definition, created_by) "
                                   "VALUES ($1, 1, $2::jsonb, $3)", sid, json.dumps(v1_definition(f"v1 strategy {i}")),
                                   "user_staging_shape")
            if key == "post":
                sql = STORE_V2.read_text(encoding="utf-8")
                await conn.execute(sql)
                await conn.execute(sql)            # TC-29: re-runnable
        finally:
            await conn.close()


async def _teardown(names: Dict[str, str]) -> None:
    admin = await asyncpg.connect(PG)
    try:
        for n in names.values():
            await admin.execute(f'DROP DATABASE IF EXISTS "{n}" WITH (FORCE)')
    finally:
        await admin.close()


@pytest.fixture(scope="module")
def dbs():
    suffix = uuid.uuid4().hex[:8]
    names = {"pre": f"ssv2_pre_{suffix}", "post": f"ssv2_post_{suffix}"}
    asyncio.run(_setup(names))
    yield {k: _db_url(n) for k, n in names.items()}
    asyncio.run(_teardown(names))


def sql(url: str, query: str, *args, fetch: str = "fetch"):
    async def go():
        conn = await asyncpg.connect(url)
        try:
            return await getattr(conn, fetch)(query, *args)
        finally:
            await conn.close()
    return asyncio.run(go())


class Harness:
    def __init__(self, url: str, monkeypatch):
        self.url = url
        self.paper: Dict[str, int] = {}                  # strategy_id → open desk paper trades citing it (MOCK)
        self._pool: Optional[asyncpg.Pool] = None

        async def get_pool():
            if self._pool is None:
                self._pool = await asyncpg.create_pool(url, min_size=1, max_size=4)
            return self._pool

        async def fake_user(request: Request):
            uid = request.headers.get("X-Test-User")
            if not uid:
                raise HTTPException(status_code=401, detail="Not authenticated")
            return {"user_id": uid}

        async def count_open(uid, strategy_ids):
            return {sid: n for sid, n in self.paper.items() if sid in set(strategy_ids)}

        # monkeypatch records the originals and restores them; req() re-installs this harness's pool because a test can
        # hold two harnesses (before / after the migration), each with its own event loop and pool.
        self._get_pool = get_pool
        monkeypatch.setattr(pg_client, "get_pool", get_pool)
        monkeypatch.setattr(route, "get_current_user", fake_user)
        monkeypatch.setattr(store, "count_open_paper_trades", count_open)
        self._count_open = count_open
        app = FastAPI()
        app.include_router(route.router)
        self.client = TestClient(app)
        self.client.__enter__()

    def close(self):
        if self._pool is not None:
            self.client.portal.call(self._pool.close)
        self.client.__exit__(None, None, None)

    def req(self, method: str, path: str, user: Optional[str], body: Any = None, key: Optional[str] = None, params=None):
        pg_client.get_pool = self._get_pool
        store.count_open_paper_trades = self._count_open
        headers = {}
        if user:
            headers["X-Test-User"] = user
        if key:
            headers["Idempotency-Key"] = key
        return self.client.request(method, API + path, json=body, headers=headers, params=params)

    def create(self, user: str, body=None, key: Optional[str] = None):
        r = self.req("POST", "/strategies", user, copy.deepcopy(body or BULL), key=key)
        assert r.status_code == 201, r.text
        return r.json()


@pytest.fixture
def post(dbs, monkeypatch):
    h = Harness(dbs["post"], monkeypatch)
    yield h
    h.close()


@pytest.fixture
def pre(dbs, monkeypatch):
    h = Harness(dbs["pre"], monkeypatch)
    yield h
    h.close()


def new_user() -> str:
    return "user_" + uuid.uuid4().hex[:10]


def new_key() -> str:
    return "k-" + uuid.uuid4().hex


def changed(definition: Dict[str, Any], **top) -> Dict[str, Any]:
    out = copy.deepcopy(definition)
    out["legs"][1]["strike"]["value"] = out["legs"][1]["strike"]["value"] + 100
    out.update(top)
    return out


# ── TC-14: create ────────────────────────────────────────────────────────────
def test_tc14_create_v2(post):
    u = new_user()
    j = post.create(u, key=new_key())
    assert j["version_no"] == 1 and j["schema_version"] == "2" and j["asset_class"] == "FNO"
    assert j["source"] == "template" and j["replayed"] is False
    assert [c for c in j["checks"] if c["severity"] == "blocking"] == []
    row = sql(post.url, "SELECT owner_id, name, source, template_id, underlying, asset_class FROM strategies WHERE id = $1",
              uuid.UUID(j["strategy_id"]), fetch="fetchrow")
    assert dict(row) == {"owner_id": u, "name": "NIFTY bull call spread", "source": "template",
                         "template_id": "bull_call_spread", "underlying": "NIFTY", "asset_class": "FNO"}
    v = sql(post.url, "SELECT schema_version, dsl_version, definition, is_active, parent_version_id, created_by "
                      "FROM strategy_versions WHERE id = $1", uuid.UUID(j["version_id"]), fetch="fetchrow")
    assert (v["schema_version"], v["dsl_version"], v["is_active"], v["parent_version_id"], v["created_by"]) == \
        ("2", "2", True, None, u)
    assert json.loads(v["definition"]) == BULL["definition"]               # stored as sent


def test_tc14_create_without_a_key_and_with_a_bad_key(post):
    u = new_user()
    assert post.create(u)["version_no"] == 1
    r = post.req("POST", "/strategies", u, BULL, key="short")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_idempotency_key"


def test_tc14_create_refuses_a_bad_document_with_every_problem(post):
    bad = copy.deepcopy(BULL)
    bad["definition"]["legs"][0]["lots"] = 0
    bad["definition"]["timeframe"] = "5m"
    r = post.req("POST", "/strategies", new_user(), bad)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "invalid_definition"
    assert {p["field"] for p in detail["problems"]} >= {"definition.legs[0].lots", "definition.timeframe"}


def test_tc14_body_fields_that_disagree_with_the_document_are_refused(post):
    for change, field, code in (({"asset_class": "MIXED"}, "asset_class", "asset_class_mismatch"),
                                ({"name": "other"}, "name", "name_mismatch"),
                                ({"template_id": "iron_condor"}, "template_id", "template_mismatch"),
                                ({"source": "clone"}, "source", "invalid_source"),
                                ({"owner_id": "someone"}, "owner_id", "unknown_field")):
        body = {**copy.deepcopy(BULL), **change}
        r = post.req("POST", "/strategies", new_user(), body)
        assert r.status_code == 422, (change, r.text)
        assert (field, code) in {(p["field"], p["code"]) for p in r.json()["detail"]["problems"]}, change


# ── TC-15: idempotent create ─────────────────────────────────────────────────
def test_tc15_a_replayed_key_answers_the_first_create(post):
    u, key = new_user(), new_key()
    first = post.create(u, key=key)
    again = post.req("POST", "/strategies", u, BULL, key=key)
    assert again.status_code == 200, again.text
    j = again.json()
    assert (j["strategy_id"], j["version_id"], j["version_no"], j["replayed"]) == \
        (first["strategy_id"], first["version_id"], 1, True)
    assert sql(post.url, "SELECT count(*) FROM strategies WHERE owner_id = $1", u, fetch="fetchval") == 1
    other = post.req("POST", "/strategies", u, COVERED, key=key)
    assert other.status_code == 409 and other.json()["detail"]["code"] == "idempotency_conflict"
    assert sql(post.url, "SELECT count(*) FROM strategies WHERE owner_id = $1", u, fetch="fetchval") == 1
    # the same key is another user's own key
    assert post.req("POST", "/strategies", new_user(), BULL, key=key).status_code == 201


# ── TC-16 … TC-18: versions ──────────────────────────────────────────────────
def test_tc16_a_new_version_with_its_diff(post):
    u = new_user()
    c = post.create(u)
    new_def = changed(BULL["definition"], name="NIFTY bull call spread, wider")
    key = new_key()
    r = post.req("POST", f"/strategies/{c['strategy_id']}/versions", u,
                 {"definition": new_def, "parent_version_id": c["version_id"], "change_summary": "wider"}, key=key)
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["version_no"] == 2 and j["parent_version_id"] == c["version_id"] and j["replayed"] is False
    assert j["diff"] == [
        {"path": "legs[L2].strike.value", "before": 25700, "after": 25800},
        {"path": "name", "before": "NIFTY bull call spread", "after": "NIFTY bull call spread, wider"},
    ]
    rows = sql(post.url, "SELECT version_no, is_active, parent_version_id, change_summary FROM strategy_versions "
                         "WHERE strategy_id = $1 ORDER BY version_no", uuid.UUID(c["strategy_id"]))
    assert [(r_["version_no"], r_["is_active"], str(r_["parent_version_id"]) if r_["parent_version_id"] else None,
             r_["change_summary"]) for r_ in rows] == [(1, False, None, None), (2, True, c["version_id"], "wider")]
    assert sql(post.url, "SELECT name FROM strategies WHERE id = $1", uuid.UUID(c["strategy_id"]),
               fetch="fetchval") == "NIFTY bull call spread, wider"
    audit = sql(post.url, "SELECT action FROM strategy_audit WHERE strategy_id = $1 ORDER BY created_at",
                uuid.UUID(c["strategy_id"]))
    assert [a["action"] for a in audit] == ["CREATE", "UPDATE"]
    # the same key again: the version it made, even though its parent is no longer the active one
    again = post.req("POST", f"/strategies/{c['strategy_id']}/versions", u,
                     {"definition": new_def, "parent_version_id": c["version_id"], "change_summary": "wider"}, key=key)
    assert again.status_code == 200 and again.json()["version_id"] == j["version_id"] and again.json()["replayed"] is True
    listed = post.req("GET", f"/strategies/{c['strategy_id']}/versions", u).json()
    assert [(v["version_no"], v["parent_version_id"], v["schema_version"], v["is_active"]) for v in listed["versions"]] == \
        [(2, c["version_id"], "2", True), (1, None, "2", False)]
    one = post.req("GET", f"/strategies/{c['strategy_id']}/versions/{c['version_id']}", u).json()
    assert one["version_no"] == 1 and one["definition"] == BULL["definition"] and one["schema_version"] == "2"


def test_tc17_a_stale_parent_is_409_with_the_active_version(post):
    u = new_user()
    c = post.create(u)
    first = post.req("POST", f"/strategies/{c['strategy_id']}/versions", u,
                     {"definition": changed(BULL["definition"]), "parent_version_id": c["version_id"]})
    assert first.status_code == 201
    second = post.req("POST", f"/strategies/{c['strategy_id']}/versions", u,
                      {"definition": changed(changed(BULL["definition"])), "parent_version_id": c["version_id"]})
    assert second.status_code == 409
    d = second.json()["detail"]
    assert d["code"] == "stale_parent" and d["active_version_id"] == first.json()["version_id"] and d["active_version_no"] == 2


def test_tc18_no_change_and_schema_mismatch(post):
    u = new_user()
    c = post.create(u)
    same = post.req("POST", f"/strategies/{c['strategy_id']}/versions", u,
                    {"definition": BULL["definition"], "parent_version_id": c["version_id"]})
    assert same.status_code == 422 and same.json()["detail"]["code"] == "no_change"
    v1 = post.req("POST", "/strategies", u, {"name": "eq", "asset_class": "STOCK", "definition": v1_definition("eq")})
    assert v1.status_code == 200, v1.text
    v1_id, v1_ver = v1.json()["id"], v1.json()["active_version"]["id"]
    mixed = post.req("POST", f"/strategies/{v1_id}/versions", u,
                     {"definition": BULL["definition"], "parent_version_id": v1_ver})
    assert mixed.status_code == 422 and mixed.json()["detail"]["code"] == "schema_mismatch"
    back = post.req("POST", f"/strategies/{c['strategy_id']}/versions", u,
                    {"definition": v1_definition("eq"), "parent_version_id": c["version_id"]})
    assert back.status_code == 422 and back.json()["detail"]["code"] == "schema_mismatch"


# ── TC-19: caps ──────────────────────────────────────────────────────────────
def test_tc19_strategy_and_version_caps(post, monkeypatch):
    monkeypatch.setattr(store, "MAX_STRATEGIES_PER_USER", 2)
    monkeypatch.setattr(store, "MAX_VERSIONS_PER_STRATEGY", 2)
    u = new_user()
    a = post.create(u)
    post.create(u, COVERED)
    third = post.req("POST", "/strategies", u, BULL)
    assert third.status_code == 409 and third.json()["detail"]["code"] == "strategy_limit"
    clone = post.req("POST", f"/strategies/{a['strategy_id']}/clone", u, {})
    assert clone.status_code == 409 and clone.json()["detail"]["code"] == "strategy_limit"
    v2 = post.req("POST", f"/strategies/{a['strategy_id']}/versions", u,
                  {"definition": changed(BULL["definition"]), "parent_version_id": a["version_id"]})
    assert v2.status_code == 201
    v3 = post.req("POST", f"/strategies/{a['strategy_id']}/versions", u,
                  {"definition": changed(changed(BULL["definition"])), "parent_version_id": v2.json()["version_id"]})
    assert v3.status_code == 409 and v3.json()["detail"]["code"] == "version_limit"


# ── TC-20: the database keeps versions immutable ─────────────────────────────
def test_tc20_the_trigger_refuses_changing_a_version(post):
    c = post.create(new_user())
    vid = uuid.UUID(c["version_id"])
    with pytest.raises(asyncpg.PostgresError) as exc:
        sql(post.url, "UPDATE strategy_versions SET definition = '{}'::jsonb WHERE id = $1", vid, fetch="execute")
    assert "immutable" in str(exc.value)
    for col, val in (("version_no", 9), ("created_by", "x"), ("schema_version", "1")):
        with pytest.raises(asyncpg.PostgresError):
            sql(post.url, f"UPDATE strategy_versions SET {col} = $2 WHERE id = $1", vid, val, fetch="execute")
    sql(post.url, "UPDATE strategy_versions SET is_active = FALSE WHERE id = $1", vid, fetch="execute")   # allowed
    assert sql(post.url, "SELECT is_active FROM strategy_versions WHERE id = $1", vid, fetch="fetchval") is False


# ── TC-21: not yours → 404, never 403 ────────────────────────────────────────
def test_tc21_another_users_strategy_is_not_found(post):
    owner, other = new_user(), new_user()
    c = post.create(owner)
    sid, vid = c["strategy_id"], c["version_id"]
    for method, path, body in (("GET", f"/strategies/{sid}/versions", None),
                               ("GET", f"/strategies/{sid}/versions/{vid}", None),
                               ("POST", f"/strategies/{sid}/versions",
                                {"definition": changed(BULL["definition"]), "parent_version_id": vid}),
                               ("POST", f"/strategies/{sid}/clone", {})):
        r = post.req(method, path, other, body)
        assert r.status_code == 404, (method, path, r.text)
    for bad in ("not-a-uuid", str(uuid.uuid4())):
        assert post.req("GET", f"/strategies/{bad}/versions", owner).status_code == 404
        assert post.req("POST", f"/strategies/{bad}/clone", owner, {}).status_code == 404
    assert post.req("GET", f"/strategies/{sid}/versions/{uuid.uuid4()}", owner).status_code == 404
    assert post.req("GET", f"/strategies/{sid}/versions", None).status_code == 401


# ── TC-22: clone ─────────────────────────────────────────────────────────────
def test_tc22_clone_own_and_a_public_template(post):
    u = new_user()
    c = post.create(u)
    r = post.req("POST", f"/strategies/{c['strategy_id']}/clone", u, {})
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["strategy_id"] != c["strategy_id"] and j["version_no"] == 1 and j["source"] == "clone"
    assert j["cloned_from"] == {"strategy_id": c["strategy_id"], "version_id": c["version_id"], "version_no": 1}
    got = post.req("GET", f"/strategies/{j['strategy_id']}", u).json()
    assert got["name"] == "NIFTY bull call spread (copy)" and got["active_version"]["definition"]["name"] == got["name"]
    named = post.req("POST", f"/strategies/{c['strategy_id']}/clone", u, {"name": "Mine", "version_id": c["version_id"]})
    assert named.status_code == 201
    assert post.req("GET", f"/strategies/{named.json()['strategy_id']}", u).json()["name"] == "Mine"
    assert post.req("POST", f"/strategies/{c['strategy_id']}/clone", u, {"color": "red"}).status_code == 422

    tpl_owner, cloner = new_user(), new_user()
    t = post.req("POST", "/strategies", tpl_owner, {"name": "tpl", "asset_class": "STOCK", "definition": v1_definition("tpl")})
    tid = t.json()["id"]
    sql(post.url, "UPDATE strategies SET is_public_template = TRUE WHERE id = $1", uuid.UUID(tid), fetch="execute")
    k = post.req("POST", f"/strategies/{tid}/clone", cloner, {})
    assert k.status_code == 201, k.text
    row = sql(post.url, "SELECT owner_id, source, cloned_from, asset_class, is_public_template FROM strategies WHERE id = $1",
              uuid.UUID(k.json()["strategy_id"]), fetch="fetchrow")
    assert (row["owner_id"], row["source"], str(row["cloned_from"]), row["asset_class"], row["is_public_template"]) == \
        (cloner, "clone", tid, "STOCK", False)
    assert k.json()["schema_version"] == "1"
    ver = sql(post.url, "SELECT dsl_version, schema_version FROM strategy_versions WHERE id = $1",
              uuid.UUID(k.json()["version_id"]), fetch="fetchrow")
    assert (ver["dsl_version"], ver["schema_version"]) == ("1", "1")


# ── TC-23: unlimited-loss drafts are kept and marked ─────────────────────────
def test_tc23_a_naked_short_call_is_saved_and_blocked_for_backtest_and_paper(post):
    body = copy.deepcopy(BULL)
    body["template_id"] = None
    body["source"] = "user"
    body["definition"]["template_id"] = None
    body["definition"]["legs"] = [body["definition"]["legs"][1]]           # the short call alone
    r = post.req("POST", "/strategies", new_user(), body)
    assert r.status_code == 201, r.text
    blocking = [c for c in r.json()["checks"] if c["severity"] == "blocking"]
    assert [(c["code"], c["blocking_for"]) for c in blocking] == [("unbounded_loss", ["backtest", "paper"])]


# ── TC-24: the list the wizard's Step 1 reads ───────────────────────────────
def _run(url, sid, vid, status, minutes_ago):
    sql(url, "INSERT INTO strategy_runs (strategy_id, version_id, run_type, status, started_at, finished_at, triggered_by) "
             "VALUES ($1, $2, 'BACKTEST', $3, now() - make_interval(mins => $4), now() - make_interval(mins => $4), 'u')",
        uuid.UUID(sid), uuid.UUID(vid), status, minutes_ago, fetch="execute")


def test_tc24_summary_rows(post):
    u = new_user()
    draft = post.create(u)
    current = post.create(u, COVERED)
    _run(post.url, current["strategy_id"], current["version_id"], "OK", 5)
    stale = post.create(u)
    _run(post.url, stale["strategy_id"], stale["version_id"], "OK", 30)
    nv = post.req("POST", f"/strategies/{stale['strategy_id']}/versions", u,
                  {"definition": changed(BULL["definition"]), "parent_version_id": stale["version_id"]})
    assert nv.status_code == 201
    failed = post.create(u)
    _run(post.url, failed["strategy_id"], failed["version_id"], "OK", 60)
    _run(post.url, failed["strategy_id"], failed["version_id"], "FAILED", 1)
    live = post.create(u)
    post.paper[live["strategy_id"]] = 2
    v1 = post.req("POST", "/strategies", u, {"name": "eq", "asset_class": "STOCK", "definition": v1_definition("eq")}).json()

    r = post.req("GET", "/strategies", u, params={"include": "summary"})
    assert r.status_code == 200, r.text
    rows = {row["id"]: row for row in r.json()["strategies"]}
    assert r.json()["count"] == 6 and len(rows) == 6
    d = rows[draft["strategy_id"]]
    assert d["last_backtest"] is None and d["paper_live"] == {"open": 0}
    assert d["latest_version"]["id"] == draft["version_id"] and d["latest_version"]["version_no"] == 1
    assert (d["source"], d["template_id"], d["underlying"], d["asset_class"], d["schema_version"]) == \
        ("template", "bull_call_spread", "NIFTY", "FNO", "2")
    c = rows[current["strategy_id"]]["last_backtest"]
    assert (c["status"], c["is_current_version"], c["version_no"]) == ("OK", True, 1) and c["finished_at"]
    s = rows[stale["strategy_id"]]
    assert (s["last_backtest"]["status"], s["last_backtest"]["is_current_version"], s["last_backtest"]["version_no"]) == \
        ("OK", False, 1)
    assert s["latest_version"]["version_no"] == 2
    assert rows[failed["strategy_id"]]["last_backtest"]["status"] == "FAILED"
    assert rows[live["strategy_id"]]["paper_live"] == {"open": 2}
    e = rows[v1["id"]]
    assert (e["schema_version"], e["source"], e["asset_class"]) == ("1", "user", "STOCK")
    assert "create_idempotency_key" not in e and "create_fingerprint" not in e
    assert post.req("GET", "/strategies", u, params={"include": "everything"}).status_code == 422


# ── TC-25: the legacy list is unchanged ──────────────────────────────────────
def test_tc25_the_legacy_list_shows_only_v1_rows_with_the_old_keys(post):
    u = new_user()
    post.create(u)
    v1 = post.req("POST", "/strategies", u, {"name": "eq", "asset_class": "STOCK", "definition": v1_definition("eq")}).json()
    r = post.req("GET", "/strategies", u)
    assert r.status_code == 200
    assert [s["id"] for s in r.json()["strategies"]] == [v1["id"]] and r.json()["count"] == 1
    assert set(r.json()["strategies"][0]) == LEGACY_LIST_KEYS


# ── TC-26: the old routes refuse v2 rows ─────────────────────────────────────
def test_tc26_patch_and_backtest_refuse_a_v2_strategy(post):
    u = new_user()
    c = post.create(u)
    for definition in (changed(BULL["definition"]), v1_definition("x")):
        r = post.req("PATCH", f"/strategies/{c['strategy_id']}", u, {"definition": definition})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "use_versions_route", r.text
    bt = post.req("POST", f"/strategies/{c['strategy_id']}/backtest", u, {"from_date": "2026-01-01", "to_date": "2026-03-31"})
    assert bt.status_code == 422 and bt.json()["detail"]["code"] == "backtest_not_available", bt.text
    assert sql(post.url, "SELECT count(*) FROM strategy_runs WHERE strategy_id = $1", uuid.UUID(c["strategy_id"]),
               fetch="fetchval") == 0
    assert sql(post.url, "SELECT count(*) FROM strategy_versions WHERE strategy_id = $1", uuid.UUID(c["strategy_id"]),
               fetch="fetchval") == 1


# ── TC-27, TC-28: v1 answers before and after the migration ──────────────────
def _v1_round_trip(h: Harness) -> Dict[str, Any]:
    u = new_user()
    created = h.req("POST", "/strategies", u, {"name": "eq", "asset_class": "STOCK", "definition": v1_definition("eq")})
    assert created.status_code == 200, created.text
    sid = created.json()["id"]
    got = h.req("GET", f"/strategies/{sid}", u)
    patched = h.req("PATCH", f"/strategies/{sid}", u, {"definition": v1_definition("eq2")})
    listed = h.req("GET", "/strategies", u)
    other = h.req("GET", f"/strategies/{sid}", new_user())
    return {"created": created, "got": got, "patched": patched, "listed": listed, "other": other}


def _shape(r):
    def strip(x):
        if isinstance(x, dict):
            return {k: ("<id>" if k in {"id", "strategy_id", "owner_id", "created_by"} else
                        "<ts>" if k.endswith("_at") else strip(v)) for k, v in x.items()}
        if isinstance(x, list):
            return [strip(i) for i in x]
        return x
    return r.status_code, strip(r.json())


def test_tc27_tc28_v1_answers_are_the_same_before_and_after_the_migration(pre, post):
    before = _v1_round_trip(pre)
    after = _v1_round_trip(post)
    for step in before:
        assert _shape(after[step]) == _shape(before[step]), step
    assert set(after["got"].json()) == LEGACY_LIST_KEYS | {"active_version"}
    assert set(after["got"].json()["active_version"]) == LEGACY_VERSION_KEYS
    assert after["other"].status_code == 403                                  # the old route's own rule, unchanged


def test_tc28_before_the_migration_the_new_routes_say_so(pre):
    u = new_user()
    r = pre.req("POST", "/strategies", u, BULL)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "store_not_migrated"
    v1 = pre.req("POST", "/strategies", u, {"name": "eq", "asset_class": "STOCK", "definition": v1_definition("eq")}).json()
    for method, path, body, params in (("GET", "/strategies", None, {"include": "summary"}),
                                       ("GET", f"/strategies/{v1['id']}/versions", None, None),
                                       ("POST", f"/strategies/{v1['id']}/clone", {}, None),
                                       ("POST", f"/strategies/{v1['id']}/versions",
                                        {"definition": BULL["definition"], "parent_version_id": v1["active_version"]["id"]},
                                        None)):
        r = pre.req(method, path, u, body, params=params)
        assert r.status_code == 503 and r.json()["detail"]["code"] == "store_not_migrated", (path, r.text)


# ── TC-29: the migration itself ──────────────────────────────────────────────
def test_tc29_migration_ran_twice_and_the_old_rows_still_read(post, dbs):
    url = dbs["post"]
    checks = sql(url, "SELECT conname, pg_get_constraintdef(oid) AS def FROM pg_constraint "
                      "WHERE conrelid = 'public.strategies'::regclass AND contype = 'c' ORDER BY conname")
    asset = [c for c in checks if "asset_class" in c["def"]]
    assert len(asset) == 1 and all(v in asset[0]["def"] for v in ("STOCK", "MF", "FNO", "MIXED"))
    assert len([c for c in checks if "source" in c["def"]]) == 1
    fks = sql(url, "SELECT count(*) FROM pg_constraint WHERE conrelid = 'public.strategy_versions'::regclass "
                   "AND contype = 'f' AND pg_get_constraintdef(oid) LIKE '%parent_version_id%'", fetch="fetchval")
    assert fks == 1
    trig = sql(url, "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'public.strategy_versions'::regclass "
                    "AND NOT tgisinternal", fetch="fetchval")
    assert trig == 1
    old = sql(url, "SELECT s.id, s.source, v.schema_version FROM strategies s JOIN strategy_versions v ON v.strategy_id = s.id "
                   "WHERE s.owner_id = 'user_staging_shape'")
    assert len(old) == 6 and {(r["source"], r["schema_version"]) for r in old} == {("user", "1")}
    for r in old:
        got = post.req("GET", f"/strategies/{r['id']}", "user_staging_shape")
        assert got.status_code == 200 and set(got.json()) == LEGACY_LIST_KEYS | {"active_version"}
