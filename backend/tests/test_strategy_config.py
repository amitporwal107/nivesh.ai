"""Strategy config — the stored "Bot details" built-ins (docs/STRATEGY_BUILDER_CONFIG_SPEC.md §2/§4.2/§4.3/§5/§8b).

Covers TC-4 … TC-23 of test_reports/strategy_config_TESTCASES.md: the migration's columns and CHECKs
(TC-4), the served JSON Schema (TC-5), GET/PUT on
`/api/strategy-builder/strategies/{id}/config` (TC-6 … TC-19) and the backtest's config resolution
(TC-20 … TC-23). TC-1/TC-2/TC-3 need a real postgres and TC-24 … TC-30 are the UI; neither belongs here.

No network, no database, no clock. Replaced, and by what:
  * `route.get_current_user`   reads the test's `X-Test-User` header; no header → 401, like the real
                               dependency. MOCK — the real one needs Mongo.
  * `pg_client.get_pool`       a fake pool whose connection answers this router's six statements out of
                               Python dicts. MOCK — not a database: it has no CHECK constraints and no
                               types, so it can store what postgres would refuse. That is deliberate —
                               the assertions below are about what the *application* accepts, and TC-4
                               checks the constraints by reading the migration's own text.
                               NUMERIC columns come back as `Decimal`, as asyncpg returns them.
  * `bt.run_backtest`          records the keyword arguments the router passed and returns an empty, real
                               `BacktestResult`. MOCK — no bars, no run; only the resolution is under test.
  * `bt.persist_run`           returns a fixed run id instead of writing `strategy_runs`.

Everything else runs for real: `NiveshConfig.resolve()` does the validating, the router does the merging,
the ownership gate, the audit write and the percent→fraction conversion, and the ranges asserted below are
imported from `services.ai_trader.config` rather than restated, so editing a bound in one place without the
other fails TC-4 and TC-5.

MOCK — not real data: every strategy id, owner id, universe and symbol here is invented.

Worked examples
  TC-22  commission is a per-side PERCENT; the backtester's per-side cost is a FRACTION. 0.05 % / 100
         = 0.0005 = 5 bps, which is exactly `bt.DEFAULT_SLIPPAGE_PCT`.
  TC-13  the bound is `0 < initial_capital <= 1e10`, so 1e10 is accepted and 1e10 + 1 = 10,000,000,001
         is refused; 0 is refused because the minimum is exclusive.
  TC-14  `0 <= commission_pct <= 5` is inclusive at both ends: 5.0 saves, 5.01 is refused.
  TC-15  `0 < short_margin_pct <= 100`: 100 saves, 0 is refused.

Pydantic's lax mode would coerce `True` → `1` and `"3"` → `3`, which would let the endpoint store values
`NiveshConfig.validate()` rejects and the served schema calls ill-typed. `StrategyConfigUpdate`'s
`_strict_type` validator closes that: it reads the raw body value, refuses a bool first (bool is a subclass
of int) and then anything outside `FIELD_RANGES[field]["py_types"]`. `test_pyramiding_rejects_a_bool` and
`test_numeric_strings_are_refused_on_every_field` pin both halves; both pass.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import asyncpg
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from routes import strategy_builder as route
from services import pg_client
from services.ai_trader import config as ai_config
from services.strategy_engine import backtest as bt

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "024_strategy_config.sql"

# MOCK — not real data.
OWNER = "user_owner"
OTHER = "user_other"
S_OWN = "11111111-1111-4111-8111-111111111111"          # OWNER's private strategy
S_TEMPLATE = "22222222-2222-4222-8222-222222222222"     # OTHER's public template
S_OTHER = "33333333-3333-4333-8333-333333333333"        # OTHER's private strategy
UNIVERSE = "44444444-4444-4444-8444-444444444444"       # a custom universe owned by OWNER
NOW = datetime(2026, 10, 21, 6, 30, tzinfo=timezone.utc)

AS_OWNER = {"X-Test-User": OWNER}
AS_OTHER = {"X-Test-User": OTHER}


def cfg_url(strategy_id: str) -> str:
    return f"/api/strategy-builder/strategies/{strategy_id}/config"


# ═════════════════════════════════════════════════════════════════════════════
# Fake database (MOCK — a dict, not postgres; see the module docstring)
# ═════════════════════════════════════════════════════════════════════════════
def _stored_row(initial_capital, commission_pct, pyramiding, short_margin_pct,
                schema_version=ai_config.SCHEMA_VERSION, updated_at=NOW) -> Dict[str, Any]:
    """A strategy_config row the way asyncpg hands it back: NUMERIC → Decimal, SMALLINT → int."""
    return {"schema_version": int(schema_version),
            "initial_capital": Decimal(str(initial_capital)),
            "commission_pct": Decimal(str(commission_pct)),
            "pyramiding": int(pyramiding),
            "short_margin_pct": Decimal(str(short_margin_pct)),
            "updated_at": updated_at}


class Db:
    def __init__(self):
        self.strategies: Dict[str, Dict[str, Any]] = {
            S_OWN: {"id": S_OWN, "owner_id": OWNER, "is_public_template": False},
            S_TEMPLATE: {"id": S_TEMPLATE, "owner_id": OTHER, "is_public_template": True},
            S_OTHER: {"id": S_OTHER, "owner_id": OTHER, "is_public_template": False},
        }
        # An index universe is a membership predicate with no stored symbol list, which is the
        # common case; S_OWN gets a custom one so the symbols path is exercised too. jsonb comes
        # back from asyncpg as text here, as the router's `isinstance(definition, str)` expects.
        self.strategy_versions: Dict[str, Dict[str, Any]] = {
            S_OWN: {"id": "v-own", "strategy_id": S_OWN, "is_active": True,
                    "definition": json.dumps({"universe": {"type": "custom", "ref": UNIVERSE}})},
            S_TEMPLATE: {"id": "v-tpl", "strategy_id": S_TEMPLATE, "is_active": True,
                         "definition": {"universe": {"type": "index", "ref": "NIFTY100"}}},
            S_OTHER: {"id": "v-oth", "strategy_id": S_OTHER, "is_active": True,
                      "definition": {"universe": {"type": "index", "ref": "NIFTY50"}}},
        }
        self.user_universes: Dict[str, Dict[str, Any]] = {
            UNIVERSE: {"id": UNIVERSE, "owner_id": OWNER, "is_public": False,
                       "symbols": ["MOCKCO", "OTHERCO"]},          # MOCK — not NSE symbols
        }
        self.strategy_config: Dict[str, Dict[str, Any]] = {}
        self.strategy_audit: List[Dict[str, Any]] = []
        self.config_writes = 0                                     # every INSERT … ON CONFLICT, upsert or not
        # Set to an exception to make the config INSERT fail the way postgres/asyncpg would. The
        # fake pool has no constraints and no types of its own (see the module docstring), so this
        # is the only way to exercise the router's defensive 422 on a refused write.
        self.insert_error: Optional[BaseException] = None


class _Tx:
    """Stand-in for `conn.transaction()`. It does not roll anything back — no test here depends on a
    rollback, and swallowing the router's HTTPException would hide a failure."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class Conn:
    def __init__(self, db: Db):
        self.db = db

    def transaction(self):
        return _Tx()

    async def fetchrow(self, q: str, *args):
        if "FROM strategy_config" in q:
            return self.db.strategy_config.get(str(args[0]))
        if "FROM strategy_versions" in q:
            row = self.db.strategy_versions.get(str(args[0]))
            return row if row and row["is_active"] else None
        if "FROM user_universes" in q:
            row = self.db.user_universes.get(str(args[0]))
            if row and (str(row["owner_id"]) == str(args[1]) or row["is_public"]):
                return row
            return None
        if "FROM strategies" in q:
            return self.db.strategies.get(str(args[0]))
        raise AssertionError(f"unexpected fetchrow: {q}")

    async def execute(self, q: str, *args):
        if "INSERT INTO strategy_config" in q:
            assert "ON CONFLICT (strategy_id) DO UPDATE" in q, "config write must be an upsert (TC-12)"
            if self.db.insert_error is not None:
                raise self.db.insert_error
            self.db.config_writes += 1
            self.db.strategy_config[str(args[0])] = _stored_row(args[2], args[3], args[4], args[5],
                                                                schema_version=args[1])
            return "INSERT 0 1"
        if "INSERT INTO strategy_audit" in q:
            # `action` is a literal in the SQL, not a parameter, so read it out of the statement.
            action = re.search(r"VALUES\s*\([^)]*'([A-Z_]+)'", q)
            self.db.strategy_audit.append({"strategy_id": str(args[0]), "actor_id": args[1],
                                           "action": action.group(1) if action else None,
                                           "note": args[2]})
            return "INSERT 0 1"
        raise AssertionError(f"unexpected execute: {q}")


class Pool:
    def __init__(self, db: Db):
        self.db = db

    def acquire(self):
        conn = Conn(self.db)

        class _CM:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, *exc):
                return False
        return _CM()


@pytest.fixture
def db(monkeypatch) -> Db:
    d = Db()

    async def fake_user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": uid}

    monkeypatch.setattr(route, "get_current_user", fake_user)

    async def get_pool():
        return Pool(d)

    monkeypatch.setattr(pg_client, "get_pool", get_pool)
    return d


@pytest.fixture
def api(db) -> TestClient:
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app)


@pytest.fixture
def engine(monkeypatch) -> Dict[str, Any]:
    """Records what the router handed `bt.run_backtest`; no bars are read and no run is written."""
    seen: Dict[str, Any] = {}

    async def fake_run_backtest(pool, spec, *, from_date, to_date, starting_capital,
                                max_positions, slippage_pct):
        seen.update(spec=spec, from_date=from_date, to_date=to_date,
                    starting_capital=starting_capital, max_positions=max_positions,
                    slippage_pct=slippage_pct)
        return bt.BacktestResult(trades=[], equity_curve=[], metrics={"total_return_pct": 0.0})

    async def fake_persist_run(pool, **kw):
        seen["persisted"] = kw
        return "run-0001"

    monkeypatch.setattr(bt, "run_backtest", fake_run_backtest)
    monkeypatch.setattr(bt, "persist_run", fake_persist_run)
    return seen


def backtest(api, strategy_id=S_OWN, who=None, status=200, **body):
    body = {"from_date": "2026-01-01", "to_date": "2026-03-31", **body}
    r = api.post(f"/api/strategy-builder/strategies/{strategy_id}/backtest",
                 json=body, headers=who or AS_OWNER)
    assert r.status_code == status, r.text
    return r.json()


# ═════════════════════════════════════════════════════════════════════════════
# TC-4  the migration's columns and CHECKs
# ═════════════════════════════════════════════════════════════════════════════
def _ddl() -> str:
    """The migration with its `--` comments stripped, so a field named in prose can't be mistaken
    for a column or a constraint."""
    return "\n".join(re.sub(r"--.*$", "", line) for line in MIGRATION.read_text().splitlines())


def _column(name: str) -> str:
    m = re.search(rf"^\s*{name}\s+(.+)$", _ddl(), re.M)
    assert m, f"migration declares no column {name}"
    return re.sub(r"\s+", " ", m.group(1).strip().rstrip(",").strip())


def _checks() -> Dict[str, set]:
    """{field: {(operator, bound), …}} as the migration's CHECK clauses state it."""
    out: Dict[str, set] = {}
    for expr in re.findall(r"CHECK\s*\(([^()]*)\)", _ddl()):
        for field, op, value in re.findall(r"(\w+)\s*(<=|>=|<|>)\s*([0-9.eE+-]+)", expr):
            out.setdefault(field, set()).add((op, float(value)))
    return out


def test_migration_columns_and_checks_match_the_spec():
    """TC-4 — column types/ranges in 024_strategy_config.sql match the spec §4.3 and the ranges in
    services.ai_trader.config, which is where they are derived from rather than restated."""
    assert _column("strategy_id") == "UUID PRIMARY KEY REFERENCES public.strategies(id) ON DELETE CASCADE"
    assert _column("schema_version") == "SMALLINT NOT NULL DEFAULT 1"
    assert _column("symbols") == "TEXT[]"                    # reserved, nullable: never written today
    assert _column("initial_capital") == "NUMERIC(18,2) NOT NULL"
    assert _column("commission_pct") == "NUMERIC(6,4) NOT NULL"
    assert _column("pyramiding") == "SMALLINT NOT NULL"
    assert _column("short_margin_pct") == "NUMERIC(5,2) NOT NULL"
    assert _column("updated_at") == "TIMESTAMPTZ NOT NULL DEFAULT NOW()"

    # Every CHECK the migration carries, expressed as config.py's FIELD_RANGES expresses it. Change a
    # bound in config.py without changing the migration (or the reverse) and this fails.
    expected = {}
    for field, rng in ai_config.FIELD_RANGES.items():
        bounds = set()
        for key, op in (("minimum", ">="), ("exclusive_minimum", ">"),
                        ("maximum", "<="), ("exclusive_maximum", "<")):
            if key in rng:
                bounds.add((op, float(rng[key])))
        expected[field] = bounds
    assert _checks() == expected

    # The declared precisions must actually hold the range's own extremes: NUMERIC(p,s) tops out at
    # p-s integer digits, so a maximum that doesn't fit would be rejected by postgres, not clamped.
    for field, precision, scale in (("initial_capital", 18, 2), ("commission_pct", 6, 4),
                                    ("short_margin_pct", 5, 2)):
        maximum = ai_config.FIELD_RANGES[field]["maximum"]
        assert maximum < 10 ** (precision - scale), f"{field} max {maximum} overflows NUMERIC({precision},{scale})"
    # `pyramiding` is SMALLINT, which tops out at 32767, so config.py carries that exact ceiling:
    # anything above it is refused by the class instead of blowing up inside asyncpg's int16 encoder.
    assert ai_config.FIELD_RANGES["pyramiding"]["minimum"] == 0
    assert ai_config.FIELD_RANGES["pyramiding"]["maximum"] == 32767

    # And every NUMERIC column's declared scale is the one config.py enforces, so a value the class
    # accepts cannot be ROUNDED by postgres into a CHECK violation (0.004 → 0.00 breaks `> 0`).
    for field, scale in (("initial_capital", 2), ("commission_pct", 4), ("short_margin_pct", 2)):
        declared = re.search(r"NUMERIC\(\d+,(\d+)\)", _column(field))
        assert declared and int(declared.group(1)) == scale
        assert ai_config.FIELD_RANGES[field]["scale"] == scale
    assert "scale" not in ai_config.FIELD_RANGES["pyramiding"]      # SMALLINT has no decimals


def test_migration_is_safe_on_a_pooled_connection_and_names_its_prerequisite():
    """TC-4 — this file runs on a connection borrowed from the app's pool (post_deploy_migrate), so
    it must not leave a session setting behind, and it must fail by name when the table its FK needs
    has not been created by the other runner (backend/nidp/migrations/020_strategy_builder_core.sql)."""
    ddl = _ddl()
    # A plain SET outlives the transaction and leaks onto every later borrower of that connection.
    assert not re.search(r"\bSET\s+search_path\b", ddl, re.I)
    # Which means every object has to be schema-qualified instead.
    assert "CREATE TABLE IF NOT EXISTS public.strategy_config" in ddl
    assert "REFERENCES public.strategies(id)" in ddl

    # The guard: a descriptive, diagnosable failure instead of a bare missing-relation error, and
    # never a silent skip.
    assert "to_regclass('public.strategies') IS NULL" in ddl
    assert "RAISE EXCEPTION" in ddl
    message = re.search(r"RAISE EXCEPTION\s*'([^']*)'", ddl, re.S)
    assert message, "the guard must carry a message"
    assert "public.strategies" in message.group(1)
    assert "020_strategy_builder_core.sql" in message.group(1)
    # post_deploy_migrate swallows (and marks applied) anything whose text looks like a duplicate
    # object; this message must not be mistaken for one.
    assert not any(tok in message.group(1).lower()
                   for tok in ("already exists", "duplicate column", "duplicate key"))


# ═════════════════════════════════════════════════════════════════════════════
# TC-5  the served JSON Schema is derived from config.py, not duplicated
# ═════════════════════════════════════════════════════════════════════════════
def test_config_schema_ranges_equal_the_config_constants(api):
    """TC-5 — GET /config-schema's bounds, types and defaults are config.py's own constants."""
    r = api.get("/api/strategy-builder/config-schema", headers=AS_OWNER)
    assert r.status_code == 200, r.text
    schema = r.json()
    assert schema["schema_version"] == ai_config.SCHEMA_VERSION
    assert schema["additionalProperties"] is False                  # unknown keys refused, not dropped
    assert schema["writable"] == list(ai_config.FIELD_RANGES)

    keyword = {"minimum": "minimum", "maximum": "maximum",
               "exclusive_minimum": "exclusiveMinimum", "exclusive_maximum": "exclusiveMaximum"}
    for field, rng in ai_config.FIELD_RANGES.items():
        prop = schema["properties"][field]
        assert prop["type"] == rng["json_type"]
        assert prop["default"] == ai_config.AI_DEFAULTS[field]
        assert prop["error_message"] == rng["range_message"]
        assert prop["writable_in_code"] is (field in ai_config.CODE_WRITABLE)
        # Exactly the bounds config.py states — no extra bound invented, none dropped.
        served = {k: prop[k] for k in keyword.values() if k in prop}
        assert served == {keyword[k]: rng[k] for k in keyword if k in rng}
        # The stored column's decimal scale, as the JSON Schema keyword for it, so a client
        # validating against this document refuses the same extra digits validate() does.
        if "scale" in rng:
            assert prop["multipleOf"] == 10.0 ** -rng["scale"]
        else:
            assert "multipleOf" not in prop

    # `properties` describes the PUT BODY, so it holds the writable fields and nothing else:
    # `additionalProperties: false` plus a `symbols` property would have a client accept a body the
    # server refuses with `unknown_ui_config_field` (JSON Schema's `readOnly` constrains no input).
    assert set(schema["properties"]) == set(ai_config.FIELD_RANGES)
    assert "symbols" not in schema["properties"]
    # It is still described, out of the body's schema, because the tab displays it.
    assert schema["read_only"]["symbols"]["readOnly"] is True
    assert set(schema["read_only"]) | set(schema["properties"]) == ai_config.BUILTINS
    # Honesty: the two fields the engine cannot act on yet are named as such.
    assert set(schema["not_enforced_by_engine"]) == {"pyramiding", "short_margin_pct"}
    for field in ai_config.FIELD_RANGES:
        enforced = schema["properties"][field]["enforced_by_engine"]
        assert enforced is (field not in schema["not_enforced_by_engine"])


def test_config_schema_requires_auth(api):
    """TC-5/TC-10 — the schema is behind auth like every other route in this router."""
    assert api.get("/api/strategy-builder/config-schema").status_code == 401


# ═════════════════════════════════════════════════════════════════════════════
# TC-6 … TC-10  GET
# ═════════════════════════════════════════════════════════════════════════════
def test_get_with_no_stored_row_returns_the_ai_defaults(api, db):
    """TC-6 — no strategy_config row → AI_DEFAULTS, `stored: false`, and nothing written."""
    r = api.get(cfg_url(S_OWN), headers=AS_OWNER)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stored"] is False
    assert {f: body[f] for f in ai_config.AI_DEFAULTS} == ai_config.AI_DEFAULTS
    assert body["schema_version"] == ai_config.SCHEMA_VERSION
    assert body["updated_at"] is None
    # S_OWN's universe is custom, so the read-only symbol list is the stored one.
    assert body["symbols"] == ["MOCKCO", "OTHERCO"]
    assert body["symbols_source"] == "custom_universe"
    assert db.strategy_config == {} and db.config_writes == 0


def test_get_with_a_stored_row_returns_the_stored_values(api, db):
    """TC-7 — a stored row is returned as plain JSON numbers with `stored: true`."""
    db.strategy_config[S_OWN] = _stored_row(250_000, 0.12, 3, 60)
    r = api.get(cfg_url(S_OWN), headers=AS_OWNER)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stored"] is True
    assert body["initial_capital"] == 250_000.0
    assert body["commission_pct"] == 0.12
    assert body["pyramiding"] == 3
    assert body["short_margin_pct"] == 60.0
    assert body["updated_at"] == NOW.isoformat()
    # Decimal would have serialised as a string; these must be real JSON numbers.
    for field in ai_config.FIELD_RANGES:
        assert isinstance(body[field], (int, float)) and not isinstance(body[field], bool)


def test_get_unknown_strategy_is_404(api):
    """TC-8 — an id with no strategies row is 404, not 403 and not an empty default config."""
    r = api.get(cfg_url("55555555-5555-4555-8555-555555555555"), headers=AS_OWNER)
    assert r.status_code == 404, r.text
    assert "not found" in json.dumps(r.json())


def test_get_another_users_private_strategy_is_403(api):
    """TC-9 — a strategy you don't own and that is not a public template is 403."""
    r = api.get(cfg_url(S_OTHER), headers=AS_OWNER)
    assert r.status_code == 403, r.text


def test_get_a_public_template_you_do_not_own_is_readable(api):
    """TC-9 — the counterpart: reads do allow a public template (writes don't; see TC-18)."""
    r = api.get(cfg_url(S_TEMPLATE), headers=AS_OWNER)
    assert r.status_code == 200, r.text
    # An index universe is a predicate, not a stored list, so there is nothing to show.
    assert r.json()["symbols"] == [] and r.json()["symbols_source"] == "unavailable"


def test_get_without_auth_is_401(api):
    """TC-10 — no credentials → 401 before any ownership check or read."""
    assert api.get(cfg_url(S_OWN)).status_code == 401


# ═════════════════════════════════════════════════════════════════════════════
# TC-11 … TC-19  PUT
# ═════════════════════════════════════════════════════════════════════════════
def put(api, body, strategy_id=S_OWN, who=None, status=200):
    r = api.put(cfg_url(strategy_id), json=body, headers=who or AS_OWNER)
    assert r.status_code == status, r.text
    return r.json()


def test_put_persists_and_echoes_the_stored_row(api, db):
    """TC-11 — a valid body is written and the response is the stored row, not the request."""
    body = put(api, {"initial_capital": 500_000, "commission_pct": 0.03,
                     "pyramiding": 2, "short_margin_pct": 75})
    assert body["stored"] is True
    assert (body["initial_capital"], body["commission_pct"],
            body["pyramiding"], body["short_margin_pct"]) == (500_000.0, 0.03, 2, 75.0)
    assert body["schema_version"] == ai_config.SCHEMA_VERSION
    assert body["updated_at"] is not None
    assert list(db.strategy_config) == [S_OWN]
    assert float(db.strategy_config[S_OWN]["initial_capital"]) == 500_000.0
    # The engine still can't act on two of the four; the response says so rather than implying it can.
    assert set(body["not_enforced_by_engine"]) == {"pyramiding", "short_margin_pct"}


def test_put_is_a_patch_onto_the_defaults(api):
    """TC-11 — a partial body merges onto AI_DEFAULTS instead of resetting the omitted fields."""
    body = put(api, {"commission_pct": 1.5})
    assert body["commission_pct"] == 1.5
    assert body["initial_capital"] == ai_config.AI_DEFAULTS["initial_capital"]
    assert body["pyramiding"] == ai_config.AI_DEFAULTS["pyramiding"]
    assert body["short_margin_pct"] == ai_config.AI_DEFAULTS["short_margin_pct"]


def test_put_twice_updates_one_row_in_place(api, db):
    """TC-12 — the second PUT upserts: one row per strategy, the later values win."""
    put(api, {"initial_capital": 400_000})
    put(api, {"initial_capital": 900_000, "pyramiding": 1})
    assert list(db.strategy_config) == [S_OWN]
    assert db.config_writes == 2                               # two writes, still one row
    row = db.strategy_config[S_OWN]
    assert float(row["initial_capital"]) == 900_000.0 and int(row["pyramiding"]) == 1
    assert put(api, {})["initial_capital"] == 900_000.0        # and the read-back agrees


@pytest.mark.parametrize("value", [0, -1, 1e10 + 1])
def test_initial_capital_out_of_range_is_422_naming_the_field(api, db, value):
    """TC-13 — 0, negative and above 1e10 are refused, and the error names initial_capital."""
    detail = put(api, {"initial_capital": value}, status=422)["detail"]
    assert detail["field"] == "initial_capital"
    assert "initial_capital" in detail["message"]
    assert db.strategy_config == {}


def test_initial_capital_accepts_its_inclusive_maximum(api):
    """TC-13 — the upper bound is inclusive, so exactly 1e10 saves."""
    assert put(api, {"initial_capital": 1e10})["initial_capital"] == 1e10


@pytest.mark.parametrize("value,status", [(5.0, 200), (0.0, 200), (5.01, 422)])
def test_commission_pct_boundary(api, value, status):
    """TC-14 — `0 <= commission_pct <= 5`: 0 and 5.0 save, 5.01 is 422 naming the field."""
    body = put(api, {"commission_pct": value}, status=status)
    if status == 200:
        assert body["commission_pct"] == value
    else:
        assert body["detail"]["field"] == "commission_pct"
        assert "commission_pct" in body["detail"]["message"]


@pytest.mark.parametrize("value,status", [(100, 200), (0, 422)])
def test_short_margin_pct_boundary(api, value, status):
    """TC-15 — `0 < short_margin_pct <= 100`: 100 saves, 0 is 422 (the minimum is exclusive)."""
    body = put(api, {"short_margin_pct": value}, status=status)
    if status == 200:
        assert body["short_margin_pct"] == 100.0
    else:
        assert body["detail"]["field"] == "short_margin_pct"


def test_pyramiding_zero_is_accepted_and_negative_is_422(api):
    """TC-16 — 0 is the default and valid; -1 is refused with pyramiding named."""
    assert put(api, {"pyramiding": 0})["pyramiding"] == 0
    detail = put(api, {"pyramiding": -1}, status=422)["detail"]
    assert detail["field"] == "pyramiding"
    assert "pyramiding" in detail["message"]


def test_pyramiding_rejects_a_bool(api, db):
    """TC-16 — `true` is not a count of extra entries and is refused, not read as 1.

    Pydantic would coerce `True` → `1`; `StrategyConfigUpdate._strict_type` rejects the bool on the
    raw body value first, so the endpoint refuses exactly what `NiveshConfig.validate()` refuses.
    """
    body = put(api, {"pyramiding": True}, status=422)
    assert "pyramiding" in json.dumps(body["detail"])
    assert db.strategy_config == {}


@pytest.mark.parametrize("field,value", [("initial_capital", "500000"), ("commission_pct", "0.1"),
                                         ("pyramiding", "3"), ("short_margin_pct", "50")])
def test_numeric_strings_are_refused_on_every_field(api, db, field, value):
    """TC-16 — a numeric STRING is the same hole as the bool: pydantic's lax mode would coerce it,
    while FIELD_RANGES[*]["py_types"] excludes str and the served schema says "number"/"integer".
    422 naming the field, and nothing stored."""
    detail = put(api, {field: value}, status=422)["detail"]
    assert detail["message"] == "invalid_config_value"
    assert detail["fields"] == [field]
    assert any(field in err for err in detail["errors"])
    assert db.strategy_config == {} and db.config_writes == 0


def test_pyramiding_rejects_a_float_that_the_column_cannot_hold(api, db):
    """TC-16 — `pyramiding` is an integer field (SMALLINT column, "type": "integer" in the schema),
    so 2.5 is refused by name rather than silently truncated to 2."""
    detail = put(api, {"pyramiding": 2.5}, status=422)["detail"]
    assert detail["fields"] == ["pyramiding"]
    assert db.strategy_config == {}


def test_pyramiding_above_the_smallint_ceiling_is_422_not_a_500(api, db):
    """TC-16 — the column is SMALLINT, so 40000 is out of range, not a server error: asyncpg would
    refuse to encode it ("value out of int16 range") and the client would see a 500."""
    detail = put(api, {"pyramiding": 40000}, status=422)["detail"]
    assert detail["field"] == "pyramiding"
    assert "pyramiding" in detail["message"]
    assert db.strategy_config == {} and db.config_writes == 0
    # The ceiling itself is the SMALLINT maximum and still saves.
    assert put(api, {"pyramiding": 32767})["pyramiding"] == 32767


@pytest.mark.parametrize("field,value", [("initial_capital", 0.004), ("short_margin_pct", 0.004),
                                         ("commission_pct", 0.00004)])
def test_a_value_finer_than_its_column_is_422_not_a_500(api, db, field, value):
    """TC-13/TC-14/TC-15 — these are all inside their range, but NUMERIC(_, scale) cannot hold them:
    postgres would ROUND 0.004 to 0.00 and the column's own CHECK (`> 0`) would then fire, so the
    caller got a 500 where the contract promises a 422. The class refuses the extra digits itself."""
    detail = put(api, {field: value}, status=422)["detail"]
    assert detail["field"] == field
    assert "decimal places" in detail["message"] and field in detail["message"]
    assert db.strategy_config == {} and db.config_writes == 0


def test_the_coarsest_value_each_column_can_hold_still_saves(api):
    """TC-13/TC-14 — the scale rule refuses only what the column would round: one unit of the last
    decimal place it does keep is accepted."""
    assert put(api, {"initial_capital": 0.01})["initial_capital"] == 0.01
    assert put(api, {"commission_pct": 0.0001})["commission_pct"] == 0.0001


@pytest.mark.parametrize("error,expected_field", [
    (asyncpg.exceptions.CheckViolationError(
        'new row for relation "strategy_config" violates check constraint '
        '"strategy_config_initial_capital_check"'), "initial_capital"),
    (asyncpg.exceptions.DataError(
        "invalid input for query argument $5: 40000 (value out of int16 range)"), "pyramiding"),
])
def test_a_write_the_database_refuses_is_422_naming_the_field(api, db, error, expected_field):
    """TC-13/TC-16 — second layer of the same guarantee: even if NiveshConfig and the columns of
    migration 024 ever drift apart again, a refused write is reported as a bad request naming the
    field, never as a 500. The valid body below is refused only by the injected database error."""
    db.insert_error = error
    detail = put(api, {"initial_capital": 500_000}, status=422)["detail"]
    assert detail["message"] == "invalid_config_value"
    assert detail["field"] == expected_field
    assert db.strategy_config == {} and db.config_writes == 0


def test_every_schema_property_is_a_key_put_accepts(api):
    """TC-5/TC-17 — spec §4.4: the keys the served schema advertises for the body and the keys PUT
    accepts are the same set. `symbols` is not one of them, and is not advertised as one."""
    schema = api.get("/api/strategy-builder/config-schema", headers=AS_OWNER).json()
    assert set(schema["properties"]) == set(ai_config.FIELD_RANGES)
    for field in schema["properties"]:
        assert put(api, {field: ai_config.AI_DEFAULTS[field]})[field] == ai_config.AI_DEFAULTS[field]
    assert "symbols" not in schema["properties"]
    assert put(api, {"symbols": ["MOCKCO"]}, status=422)["detail"]["message"] == "unknown_ui_config_field"


def test_unknown_field_is_refused_by_name_and_nothing_is_stored(api, db):
    """TC-17 — an unknown key is 422 `unknown_ui_config_field` naming it; it is never dropped."""
    detail = put(api, {"initial_capital": 700_000, "max_positions": 5, "risk_pct": 1}, status=422)["detail"]
    assert detail["message"] == "unknown_ui_config_field"
    assert detail["fields"] == ["max_positions", "risk_pct"]
    assert detail["settable"] == list(ai_config.FIELD_RANGES)
    # The valid field in the same body must not have been written either.
    assert db.strategy_config == {} and db.config_writes == 0 and db.strategy_audit == []


def test_symbols_is_not_settable_through_this_endpoint(api):
    """TC-17 — `symbols` is a built-in but comes from the universe, so it is an unknown key here."""
    detail = put(api, {"symbols": ["MOCKCO"]}, status=422)["detail"]
    assert detail["message"] == "unknown_ui_config_field"
    assert detail["fields"] == ["symbols"]


def test_put_by_a_non_owner_on_a_public_template_is_403(api, db):
    """TC-18 — a public template is readable by anyone but writable only by its owner."""
    put(api, {"initial_capital": 123_456}, strategy_id=S_TEMPLATE, status=403)
    put(api, {"initial_capital": 123_456}, strategy_id=S_OTHER, status=403)
    assert db.strategy_config == {} and db.strategy_audit == []
    # The owner of the template can still write it.
    assert put(api, {"initial_capital": 123_456}, strategy_id=S_TEMPLATE,
               who=AS_OTHER)["initial_capital"] == 123_456.0


def test_put_writes_exactly_one_audit_row(api, db):
    """TC-19 — one strategy_audit row per PUT, action CONFIG_UPDATE, actor = the caller."""
    put(api, {"initial_capital": 300_000, "pyramiding": 4})
    assert len(db.strategy_audit) == 1
    row = db.strategy_audit[0]
    assert row["action"] == "CONFIG_UPDATE"
    assert row["strategy_id"] == S_OWN and row["actor_id"] == OWNER
    # The note is the record of the change (a config PUT is not a DSL edit, so no definitions).
    assert "initial_capital" in row["note"] and "300000" in row["note"].replace(".0", "")
    put(api, {"commission_pct": 0.2})
    assert len(db.strategy_audit) == 2 and db.strategy_audit[1]["action"] == "CONFIG_UPDATE"


# ═════════════════════════════════════════════════════════════════════════════
# TC-20 … TC-23  the backtest's config resolution
# ═════════════════════════════════════════════════════════════════════════════
def test_backtest_uses_the_stored_capital_when_the_body_omits_it(api, db, engine):
    """TC-20 — no starting_capital in the body → the strategy's stored initial_capital reaches the engine."""
    db.strategy_config[S_OWN] = _stored_row(2_500_000, 0.05, 0, 100)
    body = backtest(api)
    assert engine["starting_capital"] == 2_500_000.0
    assert body["resolved_config"]["starting_capital"] == 2_500_000.0
    assert body["resolved_config"]["starting_capital_source"] == "strategy_config"
    assert body["resolved_config"]["config_stored"] is True
    # max_positions has no home in NiveshConfig (spec §8b.7), so it stays the router's default.
    assert engine["max_positions"] == route.DEFAULT_MAX_POSITIONS
    assert body["resolved_config"]["max_positions_source"] == "default"


def test_backtest_body_capital_beats_the_stored_config(api, db, engine):
    """TC-21 — an explicit starting_capital wins over the stored row (back-compat for old callers)."""
    db.strategy_config[S_OWN] = _stored_row(2_500_000, 0.05, 0, 100)
    body = backtest(api, starting_capital=750_000, max_positions=3)
    assert engine["starting_capital"] == 750_000.0 and engine["max_positions"] == 3
    assert body["resolved_config"]["starting_capital_source"] == "request"
    assert body["resolved_config"]["max_positions_source"] == "request"


def test_backtest_converts_commission_percent_to_a_slippage_fraction(api, db, engine):
    """TC-22 — commission_pct 0.05 (a percent) reaches the engine as slippage_pct 0.0005 (a fraction)."""
    db.strategy_config[S_OWN] = _stored_row(1_000_000, 0.05, 0, 100)
    body = backtest(api)
    assert engine["slippage_pct"] == 0.0005
    assert engine["slippage_pct"] == bt.DEFAULT_SLIPPAGE_PCT        # 0.05 % per side IS the engine's 5 bps
    assert body["resolved_config"]["commission_pct"] == 0.05
    assert body["resolved_config"]["slippage_pct"] == 0.0005


def test_backtest_commission_conversion_is_not_the_identity(api, db, engine):
    """TC-22 — a second value, so the /100 is pinned as a conversion rather than a coincidence."""
    db.strategy_config[S_OWN] = _stored_row(1_000_000, 0.5, 0, 100)
    backtest(api)
    assert engine["slippage_pct"] == 0.005


def test_backtest_with_no_stored_config_falls_back_to_the_ai_defaults(api, db, engine):
    """TC-23 — no strategy_config row → AI_DEFAULTS are used and the run still succeeds."""
    assert db.strategy_config == {}
    body = backtest(api)
    assert body["run_id"] == "run-0001"
    assert engine["starting_capital"] == ai_config.AI_DEFAULTS["initial_capital"] == 1_000_000.0
    assert engine["slippage_pct"] == ai_config.AI_DEFAULTS["commission_pct"] / 100.0
    assert body["resolved_config"]["starting_capital_source"] == "default"
    assert body["resolved_config"]["config_stored"] is False
    assert set(body["resolved_config"]["not_enforced_by_engine"]) == {"pyramiding", "short_margin_pct"}
