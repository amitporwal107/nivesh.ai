"""Strategy Builder API.

Public (auth-required):
  GET    /api/strategy-builder/templates                — list builtin templates
  GET    /api/strategy-builder/universes                — list user + public universes
  POST   /api/strategy-builder/universes                — create user universe
  POST   /api/strategy-builder/strategies               — create + version a strategy
  GET    /api/strategy-builder/strategies               — list current user's strategies
  GET    /api/strategy-builder/strategies/{id}          — fetch active version
  PATCH  /api/strategy-builder/strategies/{id}          — save new version
  DELETE /api/strategy-builder/strategies/{id}          — archive
  GET    /api/strategy-builder/config-schema            — JSON Schema for the Bot-details built-ins
  GET    /api/strategy-builder/strategies/{id}/config   — stored Bot-details config (or the defaults)
  PUT    /api/strategy-builder/strategies/{id}/config   — save Bot-details config (owner only)
  POST   /api/strategy-builder/screen                   — run entry rules vs latest snapshot → ranked list
  POST   /api/strategy-builder/strategies/{id}/backtest — run backtest, returns run_id
  GET    /api/strategy-builder/runs/{run_id}            — fetch backtest result + trades
  POST   /api/strategy-builder/validate                 — validate a DSL doc (no save)

The shared strategy store, v2 (Strategy Copilot Phase 1.1; services/strategy_store.py; needs migration 026, else 503
store_not_migrated). A v2 document is told apart by `definition.schema_version == "2"`; v1 answers are unchanged:
  POST   /api/strategy-builder/strategies               — with a v2 definition: 201 {strategy_id, version_id, …}
                                                          (Idempotency-Key; a replay answers the first create)
  GET    /api/strategy-builder/strategies?include=summary — every own strategy with source, latest_version,
                                                          last_backtest and paper_live (the legacy list, without
                                                          `include`, keeps to STOCK/MF rows and its old keys)
  POST   /api/strategy-builder/strategies/{id}/versions — save a new version from parent_version_id (409 stale_parent)
  GET    /api/strategy-builder/strategies/{id}/versions — the version list, newest first
  GET    /api/strategy-builder/strategies/{id}/versions/{version_id} — one version with its definition
  POST   /api/strategy-builder/strategies/{id}/clone    — copy your own strategy or a public template
  PATCH on a v2 strategy is 422 use_versions_route; a v2 backtest is 422 backtest_not_available (Phase 2).

Admin:
  POST   /api/strategy-builder/strategies/{id}/promote   — mark as public template
  POST   /api/strategy-builder/snapshot-features         — kick off feature snapshotter
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import asyncpg
from fastapi import APIRouter, Body, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from deps import get_current_user, require_admin
from services import pg_client
from services import strategy_store as store
from services.ai_trader import config as ai_config
from services.ai_trader.config import ConfigValidationError
from services.strategy_engine import dsl as dsl_mod
from services.strategy_engine import backtest as bt
from services.strategy_engine import liquid_universe
from services.strategy_engine.compiler_stock import compile_stock_query, to_asyncpg, CompileError
from services.strategy_engine.market_data import get_provider
from services.strategy_engine.evaluator import EvalError
from services.strategy_engine.screen_bridge import build_definition_from_screen, ScreenBridgeError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/strategy-builder", tags=["strategy-builder"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "services" / "strategy_engine" / "templates"

# Concurrent open positions a backtest may hold. Unlike the four Bot-details built-ins this
# has no home in NiveshConfig — spec §8b.7 names that gap — so the router keeps owning its
# default, and it stays the fallback when a caller doesn't pass one.
DEFAULT_MAX_POSITIONS = 10


# ── Pydantic request bodies ─────────────────────────────────────────
class StrategyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    asset_class: str = Field(..., pattern="^(STOCK|MF)$")
    definition: Dict[str, Any]


class StrategyUpdate(BaseModel):
    definition: Dict[str, Any]


class VersionCreate(BaseModel):
    """POST /strategies/{id}/versions (v2 only)."""
    model_config = ConfigDict(extra="forbid")
    definition: Dict[str, Any]
    parent_version_id: str = Field(..., min_length=1, max_length=64)
    change_summary: Optional[str] = Field(None, max_length=store.CHANGE_SUMMARY_MAX)


class CloneRequest(BaseModel):
    """POST /strategies/{id}/clone. Without a version_id the active version is copied."""
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(None, min_length=1, max_length=store.NAME_MAX)
    version_id: Optional[str] = Field(None, max_length=64)


# The fields a v2 create body may carry; anything else is refused (the v1 body ignores extras, as it always did).
V2_CREATE_FIELDS = ("name", "description", "asset_class", "source", "template_id", "definition")
# The columns the legacy reads return: they keep their old keys after migration 026 adds columns.
STRATEGY_COLUMNS = ("id, owner_id, name, description, asset_class, is_public_template, is_archived, "
                    "created_at, updated_at")
VERSION_COLUMNS = "id, strategy_id, version_no, definition, dsl_version, is_active, created_at, created_by"


class UniverseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    asset_class: str = Field(..., pattern="^(STOCK|MF)$")
    symbols: List[str] = Field(default_factory=list)


class BacktestRequest(BaseModel):
    from_date: str   # ISO YYYY-MM-DD
    to_date: str
    # Both optional: omitted means "use the strategy's stored config, else the platform
    # default". An explicit value still wins, so existing callers are unaffected.
    starting_capital: Optional[float] = None
    max_positions: Optional[int] = None


class StrategyConfigUpdate(BaseModel):
    """Bot-details built-ins (spec §2). All optional — a PUT merges onto the stored row
    (or onto config.AI_DEFAULTS when there is none), so a partial save is a patch, not a
    reset. `symbols` is absent on purpose: it comes from the strategy's universe and is
    read-only here. A field sent as null counts as "not supplied"."""
    model_config = ConfigDict(extra="forbid")
    initial_capital: Optional[float] = None
    commission_pct: Optional[float] = None
    pyramiding: Optional[int] = None
    short_margin_pct: Optional[float] = None

    # Pydantic's lax mode coerces True -> 1 and "500000" -> 500000.0, so a bool or a numeric string
    # would reach the row as a number and NiveshConfig.validate()'s own type check would never see it.
    # The class accepts exactly FIELD_RANGES[field]["py_types"] and the served schema says
    # `"type": "number"` / `"integer"`, and this endpoint must reject the same inputs both do
    # (spec §4.4) — so the type is checked here, on the raw value, before any coercion.
    @field_validator("initial_capital", "commission_pct", "pyramiding", "short_margin_pct",
                     mode="before")
    @classmethod
    def _strict_type(cls, v, info):
        if v is None:                       # a field sent as null counts as "not supplied"
            return v
        rng = ai_config.FIELD_RANGES[info.field_name]
        # bool first: it is a subclass of int, so isinstance(True, (int, float)) is True.
        if isinstance(v, bool) or not isinstance(v, rng["py_types"]):
            raise ValueError(rng["type_message"])
        return v


class ScreenRequest(BaseModel):
    definition: Dict[str, Any]
    as_of_date: Optional[str] = None   # ISO YYYY-MM-DD; default = latest snapshot


class FromScreenRequest(BaseModel):
    """Create a strategy from the copilot-chat stock-screener widget state."""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    # widget filters: {"<primitiveKey>_min"|"_max": number}
    filters: Dict[str, Any] = Field(default_factory=dict)
    sector: Optional[List[str]] = None
    universe: Optional[Dict[str, Any]] = None


# ── Helpers ─────────────────────────────────────────────────────────
def _parse_iso_date(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"invalid date {s!r} — expected YYYY-MM-DD")


def _user_id(user) -> str:
    """Resolve a stable user id from the auth payload. Mongo users use
    `id`; some flows expose `_id` or `user_id`."""
    for key in ("id", "_id", "user_id"):
        v = (user or {}).get(key) if isinstance(user, dict) else None
        if v:
            return str(v)
    raise HTTPException(status_code=401, detail="user has no id")


def _definition(raw: Any) -> Any:
    """A jsonb column as Python (asyncpg hands jsonb back as text unless a codec is set)."""
    return json.loads(raw) if isinstance(raw, str) else raw


def _uuid_or_404(value: str, what: str = "strategy") -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail=f"{what} not found") from None


def _store_error(exc: "store.StoreInputError") -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.detail())


def _store_refusal(status: int, code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, **extra})


async def _store_v2_ready(conn) -> bool:
    """Whether migration 026 is applied: its last column exists (the migration is one transaction)."""
    return bool(await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = to_regclass('public.strategy_versions') "
        "AND attname = 'request_fingerprint' AND NOT attisdropped)"))


async def _require_store_v2(conn) -> None:
    if not await _store_v2_ready(conn):
        logger.error("strategy store v2 called before backend/migrations/026_strategy_store_v2.sql was applied")
        raise _store_refusal(503, "store_not_migrated",
                             "The strategy store is not upgraded on this server yet (migration 026); nothing was saved.")


async def _lock_owner(conn, uid: str) -> None:
    """Serialise one user's creates and clones (the 200-strategy cap and Idempotency-Key replays) in this transaction."""
    await conn.execute("SELECT pg_advisory_xact_lock(hashtext('strategy_store:' || $1))", uid)


async def _readable_strategy(conn, sid: uuid.UUID, uid: str, *, owner_only: bool, for_update: bool = False):
    """The store's ownership rule (PR #390's): not yours, archived or unknown are all the same 404, never 403. Reads also
    allow a public template; writes never do."""
    row = await conn.fetchrow(
        "SELECT id, owner_id, name, description, asset_class, is_public_template, is_archived, source, template_id, "
        "underlying FROM strategies WHERE id = $1" + (" FOR UPDATE" if for_update else ""), sid)
    if row is None or row["is_archived"] or (
            str(row["owner_id"]) != uid and (owner_only or not row["is_public_template"])):
        raise HTTPException(status_code=404, detail="strategy not found")
    return row


def _idempotency_key(request: Request) -> Optional[str]:
    try:
        return store.clean_idempotency_key(request.headers.get("Idempotency-Key"))
    except store.StoreInputError as exc:
        raise _store_error(exc)


async def _record_failed_run(pool, strategy_id, version_id, from_date, to_date, uid, exc: BaseException) -> Optional[str]:
    """Store a backtest that raised as a FAILED strategy_runs row and return its id (PRD Appendix A). If that write
    fails too, log it and return None: the caller still answers with the original error, which must not be masked."""
    try:
        return await bt.persist_failed_run(
            pool, strategy_id=strategy_id, version_id=version_id, from_date=from_date, to_date=to_date,
            triggered_by=uid, error_message=f"{type(exc).__name__}: {exc}",
        )
    except Exception:  # noqa: BLE001 — logged at error level, then the original error is raised by the caller
        logger.exception("could not record the FAILED backtest run of strategy %s", strategy_id)
        return None


# ── Templates ───────────────────────────────────────────────────────
@router.get("/templates")
async def list_templates(request: Request):
    await get_current_user(request)
    out: List[Dict[str, Any]] = []
    if TEMPLATES_DIR.is_dir():
        for p in sorted(TEMPLATES_DIR.glob("*.json")):
            try:
                with p.open() as f:
                    spec = json.load(f)
            except Exception as e:   # noqa: BLE001
                logger.warning("template %s unreadable: %s", p.name, e)
                continue
            out.append({
                "key": p.stem,
                "name": spec.get("name", p.stem),
                "description": spec.get("description"),
                "asset_class": spec.get("asset_class"),
                "definition": spec,
            })
    return {"templates": out, "count": len(out)}


# ── Validation ──────────────────────────────────────────────────────
@router.post("/validate")
async def validate(request: Request, body: Dict[str, Any]):
    await get_current_user(request)
    errs = dsl_mod.validate_strategy(body)
    return {
        "valid": not errs,
        "errors": dsl_mod.errors_as_strings(errs),
    }


# ── Universes ───────────────────────────────────────────────────────
@router.get("/universes")
async def list_universes(request: Request, asset_class: Optional[str] = None):
    user = await get_current_user(request)
    uid = _user_id(user)
    pool = await pg_client.get_pool()
    where = ["(owner_id = $1 OR is_public)"]
    params: List[Any] = [uid]
    if asset_class:
        where.append("asset_class = $2")
        params.append(asset_class)
    sql = ("SELECT id, owner_id, name, description, asset_class, symbols, is_public, "
           "       created_at, updated_at "
           "  FROM user_universes "
           " WHERE " + " AND ".join(where) + " "
           " ORDER BY (owner_id = $1) DESC, name ASC")
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return {
        "universes": [_serialise(r) for r in rows],
        "count": len(rows),
    }


@router.post("/universes")
async def create_universe(request: Request, body: UniverseCreate):
    user = await get_current_user(request)
    uid = _user_id(user)
    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO user_universes
                   (owner_id, name, description, asset_class, symbols)
               VALUES ($1, $2, $3, $4, $5)
               RETURNING id, owner_id, name, description, asset_class, symbols,
                         is_public, created_at, updated_at""",
            uid, body.name, body.description, body.asset_class, body.symbols,
        )
    return _serialise(row)


# ── Universe catalog (curated public baskets + index presets + real metrics) ──
# Index presets are static — the only refs the compiler's INDEX_REFS accepts. Public
# sector / index-theme baskets are seeded by migration 117 (real membership from
# nidp.sector_master / index_constituents). Per-universe 3M return = median
# return_60d_pct of constituents; trend = 1M-vs-3M momentum. Both are real, populated
# columns (verified on staging). No number is fabricated — a basket with no metric
# shows null. Result cached per snapshot date (values change once/day).
# The whole-market, point-in-time universe (liquid-eq-v1): the default for an "all stocks" universe. A backtest on it
# has no survivorship bias; the index presets below are applied with their LATEST constituents to every past date.
_MARKET_PRESETS = [
    {"ref": liquid_universe.REF, "name": liquid_universe.LABEL, "description": liquid_universe.DESCRIPTION,
     "survivorship": "point_in_time"},
]
_INDEX_PRESETS = [
    {"ref": "NIFTY50",  "name": "Nifty 50",  "description": "Largest 50 by free-float — most liquid."},
    {"ref": "NIFTY100", "name": "Nifty 100", "description": "Top 100 by free-float market cap."},
    {"ref": "NIFTY200", "name": "Nifty 200", "description": "Large + midcap breadth."},
    {"ref": "NIFTY500", "name": "Nifty 500", "description": "Full breadth — small / mid / large."},
]
_CATALOG_CACHE: Dict[str, Dict[str, Any]] = {}


def _median(vals: List[Any]) -> Optional[float]:
    v = sorted(float(x) for x in vals if isinstance(x, (int, float)))
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def _trend_label(m20: Optional[float], m60: Optional[float]) -> tuple:
    """Trend from acceleration of median 1M (return_20d_pct) vs 3M (return_60d_pct)
    pace — both real, materialised, populated columns. Deliberately does NOT use
    momentum_score (not a materialised column → would be null/fabricated)."""
    if m20 is None or m60 is None:
        return (None, None)
    monthly_from_3m = m60 / 3.0
    if m60 > 0 and m20 > monthly_from_3m:
        return ("warming", "Accelerating")
    if m20 < 0:
        return ("cooling", "Cooling")
    return ("steady", "Steady")


def _catalog_probe_spec(universe: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "version": dsl_mod.DSL_VERSION, "asset_class": "STOCK", "name": "catalog",
        "universe": universe,
        "entry": {"all_of": [{"feature": "close", "op": ">=", "value": 0}]},
        "exit": {"stoploss_pct": 8.0, "target_rr": 2.0, "max_hold_days": 20},
        "ranking": {"by": "market_cap_cr", "limit": 100, "order": "desc"},
        "rebalance": "daily",
    }


async def _universe_metrics(pool, universe: Dict[str, Any], asof) -> Dict[str, Any]:
    """Real median 3M return + trend for one universe. Fresh provider per call —
    a provider instance accumulates per-universe state, so it must not be shared."""
    try:
        provider = get_provider(pool)
        spec = _catalog_probe_spec(universe)
        await provider.prepare(spec, asof, asof)
        rows = await provider.screen(spec, asof)
        r60 = _median([r.get("return_60d_pct") for r in rows])
        r20 = _median([r.get("return_20d_pct") for r in rows])
        trend, label = _trend_label(r20, r60)
        return {
            "return_3m_pct": round(r60, 2) if r60 is not None else None,
            "trend": trend, "trend_label": label, "sampled": len(rows),
        }
    except Exception as e:   # noqa: BLE001
        logger.warning("catalog metrics failed for %s: %s", universe, e)
        return {"return_3m_pct": None, "trend": None, "trend_label": None, "sampled": 0}


@router.get("/universe-catalog")
async def universe_catalog(request: Request):
    """Curated universe catalog: index presets + public sector / index-theme baskets,
    each with a REAL median 3M return (return_60d_pct) and a momentum trend."""
    await get_current_user(request)
    pool = await pg_client.get_pool()
    provider = get_provider(pool)
    asof = await provider.latest_date()
    if asof is None:
        raise HTTPException(status_code=503, detail="no feature snapshots available")
    # Fetch the public system baskets first so the cache key can include their
    # count — seeding new baskets (a migration) then invalidates the cache
    # automatically instead of serving a stale pre-seed catalog for the rest of the day.
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            r"SELECT id, owner_id, name, description, symbols FROM user_universes "
            r"WHERE is_public AND asset_class = 'STOCK' AND owner_id LIKE '\_\_system%' "
            r"ORDER BY cardinality(symbols) DESC, name ASC"
        )
    ckey = f"{asof.isoformat()}:{len(rows)}"
    if ckey in _CATALOG_CACHE:
        return _CATALOG_CACHE[ckey]

    catalog: List[Dict[str, Any]] = [
        {"kind": "broad", "category": "Broad Market", "ref": p["ref"], "id": None,
         "name": p["name"], "description": p["description"], "symbol_count": None,
         "universe": {"type": "market", "ref": p["ref"]}, "survivorship": p["survivorship"], "default": True,
         "_universe": {"type": "market", "ref": p["ref"]}}
        for p in _MARKET_PRESETS
    ] + [
        {"kind": "broad", "category": "Broad Market", "ref": p["ref"], "id": None,
         "name": p["name"], "description": p["description"], "symbol_count": None,
         "universe": {"type": "index", "ref": p["ref"]}, "survivorship": "latest_snapshot",
         "_universe": {"type": "index", "ref": p["ref"]}}
        for p in _INDEX_PRESETS
    ]
    for r in rows:
        is_sector = str(r["owner_id"]).startswith("__system_sector")
        catalog.append({
            "kind": "sector" if is_sector else "index-theme",
            "category": "Sector" if is_sector else "Index Theme",
            "ref": None, "id": str(r["id"]), "name": r["name"],
            "description": r["description"], "symbol_count": len(r["symbols"] or []),
            "universe": {"type": "custom", "ref": str(r["id"])}, "survivorship": "custom_universe",
            "_universe": {"type": "custom", "ref": str(r["id"])},
        })

    # Bounded concurrency — each metric is a fresh DaaS fetch; don't stampede DaaS.
    sem = asyncio.Semaphore(6)

    async def _bounded(u):
        async with sem:
            return await _universe_metrics(pool, u, asof)

    metrics = await asyncio.gather(*[_bounded(c["_universe"]) for c in catalog])
    out: List[Dict[str, Any]] = []
    for c, m in zip(catalog, metrics):
        c.pop("_universe", None)
        c["return_3m_pct"] = m["return_3m_pct"]
        c["trend"] = m["trend"]
        c["trend_label"] = m["trend_label"]
        out.append(c)

    result = {"as_of_date": ckey, "return_window": "3M", "count": len(out), "universes": out}
    _CATALOG_CACHE[ckey] = result
    return result


# ── Strategies ──────────────────────────────────────────────────────
@router.post("/strategies")
async def create_strategy(request: Request, response: Response, body: Any = Body(...)):
    """v1 (the equity DSL): exactly as before, including how FastAPI refused a bad body. v2 (`definition.schema_version
    == "2"`): the shared strategy store."""
    definition = body.get("definition") if isinstance(body, dict) else None
    if store.is_v2(definition):
        return await _create_strategy_v2(request, response, body)
    try:
        parsed = StrategyCreate.model_validate(body, from_attributes=True)   # FastAPI's own mode for a body model
    except ValidationError as exc:
        # The error FastAPI raised for the old `body: StrategyCreate` signature, before the handler ran (so before auth).
        raise RequestValidationError([{**e, "loc": ("body", *e["loc"])} for e in exc.errors()], body=body) from None
    return await _create_strategy_v1(request, parsed)


async def _create_strategy_v1(request: Request, body: StrategyCreate):
    user = await get_current_user(request)
    uid = _user_id(user)
    errs = dsl_mod.validate_strategy(body.definition)
    if errs:
        raise HTTPException(status_code=400, detail={
            "message": "invalid strategy spec",
            "errors": dsl_mod.errors_as_strings(errs),
        })

    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            srow = await conn.fetchrow(
                """INSERT INTO strategies
                       (owner_id, name, description, asset_class)
                   VALUES ($1, $2, $3, $4)
                   RETURNING id, owner_id, name, description, asset_class,
                             is_public_template, is_archived, created_at, updated_at""",
                uid, body.name, body.description, body.asset_class,
            )
            sid = srow["id"]
            vrow = await conn.fetchrow(
                """INSERT INTO strategy_versions
                       (strategy_id, version_no, definition, dsl_version, is_active, created_by)
                   VALUES ($1, 1, $2::jsonb, $3, TRUE, $4)
                   RETURNING id, version_no, created_at""",
                sid, json.dumps(body.definition), dsl_mod.DSL_VERSION, uid,
            )
            await conn.execute(
                """INSERT INTO strategy_audit
                       (strategy_id, actor_id, action, new_definition, note)
                   VALUES ($1, $2, 'CREATE', $3::jsonb, NULL)""",
                sid, uid, json.dumps(body.definition),
            )
    return {
        **_serialise(srow),
        "active_version": _serialise(vrow),
    }


def _v2_create_problems(body: Dict[str, Any]) -> List[Dict[str, str]]:
    """Every problem with a v2 create body: unknown fields, the document, and body fields that disagree with it."""
    problems = [{"field": str(k), "code": "unknown_field", "message": f"{k} is not a field of a strategy create."}
                for k in body if k not in V2_CREATE_FIELDS]
    definition = body["definition"]
    doc_problems = store.validate_definition(definition)
    problems += store.problems_with_prefix(doc_problems, "definition")
    source = body.get("source", "user")
    if source not in store.CREATE_SOURCES:
        problems.append({"field": "source", "code": "invalid_source",
                         "message": f"source must be one of {', '.join(store.CREATE_SOURCES)} (a clone is made with /clone)."})
    desc = body.get("description")
    if desc is not None and (not isinstance(desc, str) or len(desc) > store.DESCRIPTION_MAX):
        problems.append({"field": "description", "code": "invalid_text",
                         "message": f"description must be text of at most {store.DESCRIPTION_MAX} characters."})
    if not doc_problems:
        derived = store.asset_class_of(definition)
        if "asset_class" in body and body["asset_class"] != derived:
            problems.append({"field": "asset_class", "code": "asset_class_mismatch",
                             "message": f"The legs make this a {derived} strategy, not {body['asset_class']}."})
        if "name" in body and body["name"] != definition["name"]:
            problems.append({"field": "name", "code": "name_mismatch", "message": "name must equal definition.name."})
        if "template_id" in body and body["template_id"] != definition.get("template_id"):
            problems.append({"field": "template_id", "code": "template_mismatch",
                             "message": "template_id must equal definition.template_id."})
        if source == "template" and not definition.get("template_id"):
            problems.append({"field": "template_id", "code": "template_required",
                             "message": "A strategy whose source is a template names it in definition.template_id."})
    return problems


async def _create_strategy_v2(request: Request, response: Response, body: Dict[str, Any]):
    user = await get_current_user(request)
    uid = _user_id(user)
    key = _idempotency_key(request)
    problems = _v2_create_problems(body)
    if problems:
        code = "invalid_definition" if any(p["field"].startswith("definition") for p in problems) else "invalid_body"
        raise _store_refusal(422, code, "The strategy cannot be saved: " + problems[0]["message"], problems=problems)
    definition = body["definition"]
    asset_class = store.asset_class_of(definition)
    source = body.get("source", "user")
    fp = store.fingerprint(body)

    def answer(sid, vid, replayed: bool) -> Dict[str, Any]:
        return {"strategy_id": str(sid), "version_id": str(vid), "version_no": 1, "schema_version": store.SCHEMA_V2,
                "asset_class": asset_class, "source": source, "checks": store.checks(definition), "replayed": replayed}

    async def replay(conn) -> Optional[Dict[str, Any]]:
        prior = await conn.fetchrow(
            "SELECT s.id, s.create_fingerprint, v.id AS version_id FROM strategies s "
            "JOIN strategy_versions v ON v.strategy_id = s.id AND v.version_no = 1 "
            "WHERE s.owner_id = $1 AND s.create_idempotency_key = $2", uid, key)
        if prior is None:
            return None
        if prior["create_fingerprint"] != fp:
            raise _store_refusal(409, "idempotency_conflict",
                                 "This Idempotency-Key was already used to create a different strategy; nothing new was saved.",
                                 existing_strategy_id=str(prior["id"]))
        response.status_code = 200
        return answer(prior["id"], prior["version_id"], True)

    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        await _require_store_v2(conn)
        try:
            async with conn.transaction():
                await _lock_owner(conn, uid)
                if key is not None:
                    prior = await replay(conn)
                    if prior is not None:
                        return prior
                n = await conn.fetchval("SELECT count(*) FROM strategies WHERE owner_id = $1 AND NOT is_archived", uid)
                if n >= store.MAX_STRATEGIES_PER_USER:
                    raise _store_refusal(409, "strategy_limit",
                                         f"You have {store.MAX_STRATEGIES_PER_USER} strategies; archive one to save another.")
                sid = await conn.fetchval(
                    """INSERT INTO strategies (owner_id, name, description, asset_class, source, template_id, underlying,
                                               create_idempotency_key, create_fingerprint)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING id""",
                    uid, definition["name"], body.get("description"), asset_class, source, definition.get("template_id"),
                    definition["underlying"]["symbol"], key, fp if key is not None else None)
                vid = await conn.fetchval(
                    """INSERT INTO strategy_versions (strategy_id, version_no, definition, dsl_version, is_active, created_by,
                                                      schema_version, request_fingerprint)
                       VALUES ($1, 1, $2::jsonb, $3, TRUE, $4, $3, $5) RETURNING id""",
                    sid, json.dumps(definition), store.SCHEMA_V2, uid, fp)
                await conn.execute(
                    """INSERT INTO strategy_audit (strategy_id, actor_id, action, new_definition, note)
                       VALUES ($1, $2, 'CREATE', $3::jsonb, $4)""",
                    sid, uid, json.dumps(definition), f"strategy store v2, source {source}")
        except asyncpg.UniqueViolationError:
            # The same key raced in from another request between the lookup and the insert: answer the one that won.
            async with conn.transaction():
                prior = await replay(conn) if key is not None else None
            if prior is None:
                raise
            return prior
    response.status_code = 201
    return answer(sid, vid, False)


@router.post("/from-screen")
async def create_strategy_from_screen(request: Request, body: FromScreenRequest):
    """Turn the copilot-chat stock screener's current filters into a saved
    STOCK strategy. Maps each screener primitive to its stock_features_daily
    column (feature.* predicate), applies default exit/ranking/rebalance, then
    validates + persists exactly like POST /strategies. Unmappable filters are
    returned in `dropped_filters` (never silently ignored)."""
    user = await get_current_user(request)
    uid = _user_id(user)
    try:
        definition, dropped = build_definition_from_screen(
            name=body.name, filters=body.filters, sector=body.sector,
            universe=body.universe, description=body.description,
        )
    except ScreenBridgeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    errs = dsl_mod.validate_strategy(definition)
    if errs:
        raise HTTPException(status_code=400, detail={
            "message": "could not build a valid strategy from this screen",
            "errors": dsl_mod.errors_as_strings(errs),
        })

    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            srow = await conn.fetchrow(
                """INSERT INTO strategies
                       (owner_id, name, description, asset_class)
                   VALUES ($1, $2, $3, 'STOCK')
                   RETURNING id, owner_id, name, description, asset_class,
                             is_public_template, is_archived, created_at, updated_at""",
                uid, body.name, definition.get("description"),
            )
            sid = srow["id"]
            vrow = await conn.fetchrow(
                """INSERT INTO strategy_versions
                       (strategy_id, version_no, definition, dsl_version, is_active, created_by)
                   VALUES ($1, 1, $2::jsonb, $3, TRUE, $4)
                   RETURNING id, version_no, created_at""",
                sid, json.dumps(definition), dsl_mod.DSL_VERSION, uid,
            )
            await conn.execute(
                """INSERT INTO strategy_audit
                       (strategy_id, actor_id, action, new_definition, note)
                   VALUES ($1, $2, 'CREATE', $3::jsonb, 'from stock screener')""",
                sid, uid, json.dumps(definition),
            )
    return {
        **_serialise(srow),
        "active_version": _serialise(vrow),
        "definition": definition,
        "dropped_filters": dropped,
    }


@router.get("/strategies")
async def list_strategies(request: Request, include_templates: bool = False,
                          include: Optional[str] = Query(None, pattern="^summary$")):
    user = await get_current_user(request)
    uid = _user_id(user)
    if include == "summary":
        return await _list_summary(uid, include_templates)
    pool = await pg_client.get_pool()
    # The legacy list keeps to what it always listed: the equity/MF strategies the old screens can open and backtest.
    where = ["NOT is_archived", "asset_class IN ('STOCK', 'MF')", "(owner_id = $1"]
    params: List[Any] = [uid]
    if include_templates:
        where[-1] += " OR is_public_template"
    where[-1] += ")"
    sql = ("SELECT id, owner_id, name, description, asset_class, is_public_template, "
           "       is_archived, created_at, updated_at "
           "  FROM strategies "
           " WHERE " + " AND ".join(where) + " "
           " ORDER BY updated_at DESC")
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return {"strategies": [_serialise(r) for r in rows], "count": len(rows)}


async def _list_summary(uid: str, include_templates: bool) -> Dict[str, Any]:
    """Strategy Lab's "Existing strategies" list: every own strategy (v1 and v2), with what the status word is derived
    from (frontend instance-store.ts storeStatus: PAPER LIVE, BACKTEST FAILED, BACKTESTED, STALE, DRAFT)."""
    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        await _require_store_v2(conn)
        rows = await conn.fetch(
            f"""SELECT {', '.join('s.' + c.strip() for c in STRATEGY_COLUMNS.split(','))},
                       s.source, s.template_id, s.underlying, s.cloned_from,
                       v.id AS version_id, v.version_no, v.created_at AS version_created_at, v.schema_version,
                       r.id AS run_id, r.status AS run_status, r.finished_at AS run_finished_at,
                       r.version_id AS run_version_id, rv.version_no AS run_version_no
                  FROM strategies s
                  LEFT JOIN strategy_versions v ON v.strategy_id = s.id AND v.is_active
                  LEFT JOIN LATERAL (
                        SELECT id, status, finished_at, version_id FROM strategy_runs
                         WHERE strategy_id = s.id AND run_type = 'BACKTEST' AND status IN ('OK', 'FAILED')
                         ORDER BY started_at DESC, id DESC LIMIT 1) r ON TRUE
                  LEFT JOIN strategy_versions rv ON rv.id = r.version_id
                 WHERE NOT s.is_archived AND (s.owner_id = $1 {"OR s.is_public_template" if include_templates else ""})
                 ORDER BY s.updated_at DESC""", uid)
    own = [str(r["id"]) for r in rows if str(r["owner_id"]) == uid]
    paper_error = None
    try:
        paper = await store.count_open_paper_trades(uid, own)
    except Exception:  # noqa: BLE001 — logged; the list still answers and says the count is unknown
        logger.exception("strategy store: could not count open desk paper trades for the summary")
        paper, paper_error = {}, "The desk's paper trades could not be read; PAPER LIVE is unknown."
    out = []
    for r in rows:
        sid = str(r["id"])
        row = _serialise({k: r[k] for k in ("id", "owner_id", "name", "description", "asset_class", "is_public_template",
                                            "is_archived", "created_at", "updated_at", "source", "template_id",
                                            "underlying", "cloned_from")})
        row["schema_version"] = r["schema_version"]
        row["latest_version"] = None if r["version_id"] is None else {
            "id": str(r["version_id"]), "version_no": r["version_no"],
            "created_at": r["version_created_at"].isoformat() if r["version_created_at"] else None}
        row["last_backtest"] = None if r["run_id"] is None else {
            "run_id": str(r["run_id"]), "status": r["run_status"],
            "finished_at": r["run_finished_at"].isoformat() if r["run_finished_at"] else None,
            "version_no": r["run_version_no"], "is_current_version": r["run_version_id"] == r["version_id"]}
        if paper_error:
            row["paper_live"] = {"open": None, "error": paper_error}
        else:
            row["paper_live"] = {"open": paper.get(sid, 0) if sid in own else 0}
        out.append(row)
    return {"strategies": out, "count": len(out)}


@router.get("/strategies/{strategy_id}")
async def get_strategy(request: Request, strategy_id: str):
    user = await get_current_user(request)
    uid = _user_id(user)
    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        # Named columns, not *: migration 026 adds columns (some internal, like the Idempotency-Key) that this answer
        # never had.
        s = await conn.fetchrow(
            f"SELECT {STRATEGY_COLUMNS} FROM strategies WHERE id = $1", strategy_id,
        )
        if not s:
            raise HTTPException(status_code=404, detail="strategy not found")
        if str(s["owner_id"]) != uid and not s["is_public_template"]:
            raise HTTPException(status_code=403, detail="not authorised")
        v = await conn.fetchrow(
            f"SELECT {VERSION_COLUMNS} FROM strategy_versions WHERE strategy_id = $1 AND is_active",
            strategy_id,
        )
        definition = _definition(v["definition"]) if v else None
        extra: Dict[str, Any] = {}
        if store.is_v2(definition):                      # a v2 row exists only after migration 026
            meta = await conn.fetchrow(
                "SELECT source, template_id, underlying, cloned_from FROM strategies WHERE id = $1", strategy_id)
            extra = {**_serialise(meta), "schema_version": store.SCHEMA_V2, "checks": store.checks(definition)}
    return {
        **_serialise(s),
        "active_version": _serialise(v) if v else None,
        **extra,
    }


@router.patch("/strategies/{strategy_id}")
async def update_strategy(request: Request, strategy_id: str, body: StrategyUpdate):
    user = await get_current_user(request)
    uid = _user_id(user)
    if store.is_v2(body.definition):
        raise _use_versions_route()
    errs = dsl_mod.validate_strategy(body.definition)
    if errs:
        raise HTTPException(status_code=400, detail={
            "message": "invalid strategy spec",
            "errors": dsl_mod.errors_as_strings(errs),
        })
    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            s = await conn.fetchrow(
                "SELECT * FROM strategies WHERE id = $1 FOR UPDATE", strategy_id,
            )
            if not s:
                raise HTTPException(status_code=404, detail="strategy not found")
            if str(s["owner_id"]) != uid:
                raise HTTPException(status_code=403, detail="not the owner")
            prev = await conn.fetchrow(
                "SELECT * FROM strategy_versions WHERE strategy_id = $1 AND is_active",
                strategy_id,
            )
            if prev and store.is_v2(_definition(prev["definition"])):
                raise _use_versions_route()
            await conn.execute(
                "UPDATE strategy_versions SET is_active = FALSE WHERE strategy_id = $1 AND is_active",
                strategy_id,
            )
            new_no = (prev["version_no"] if prev else 0) + 1
            v = await conn.fetchrow(
                """INSERT INTO strategy_versions
                       (strategy_id, version_no, definition, dsl_version, is_active, created_by)
                   VALUES ($1, $2, $3::jsonb, $4, TRUE, $5)
                   RETURNING id, version_no, created_at""",
                strategy_id, new_no, json.dumps(body.definition), dsl_mod.DSL_VERSION, uid,
            )
            await conn.execute(
                "UPDATE strategies SET updated_at = NOW() WHERE id = $1", strategy_id,
            )
            await conn.execute(
                """INSERT INTO strategy_audit
                       (strategy_id, actor_id, action, prev_definition, new_definition)
                   VALUES ($1, $2, 'UPDATE', $3::jsonb, $4::jsonb)""",
                strategy_id, uid,
                json.dumps(prev["definition"]) if prev else None,
                json.dumps(body.definition),
            )
    return {"version": _serialise(v)}


def _use_versions_route() -> HTTPException:
    return _store_refusal(422, "use_versions_route",
                          "A v2 (legs) strategy is saved with POST /api/strategy-builder/strategies/{id}/versions, which "
                          "checks the parent version and answers with the diff.")


@router.delete("/strategies/{strategy_id}")
async def archive_strategy(request: Request, strategy_id: str):
    user = await get_current_user(request)
    uid = _user_id(user)
    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        s = await conn.fetchrow("SELECT owner_id FROM strategies WHERE id = $1", strategy_id)
        if not s:
            raise HTTPException(status_code=404, detail="strategy not found")
        if str(s["owner_id"]) != uid:
            raise HTTPException(status_code=403, detail="not the owner")
        await conn.execute(
            "UPDATE strategies SET is_archived = TRUE, updated_at = NOW() WHERE id = $1",
            strategy_id,
        )
        await conn.execute(
            "INSERT INTO strategy_audit (strategy_id, actor_id, action) VALUES ($1, $2, 'ARCHIVE')",
            strategy_id, uid,
        )
    return {"ok": True, "id": strategy_id, "archived": True}


# ── The shared strategy store, v2: versions and clones ──────────────
def _version_row(row, *, with_definition: bool = False) -> Dict[str, Any]:
    out = {"version_id": str(row["id"]), "strategy_id": str(row["strategy_id"]), "version_no": row["version_no"],
           "created_at": row["created_at"].isoformat() if row["created_at"] else None,
           "change_summary": row["change_summary"],
           "parent_version_id": str(row["parent_version_id"]) if row["parent_version_id"] else None,
           "schema_version": row["schema_version"], "is_active": row["is_active"]}
    if with_definition:
        definition = _definition(row["definition"])
        out["definition"] = definition
        if store.is_v2(definition):
            out["checks"] = store.checks(definition)
    return out


_VERSION_META = ("id, strategy_id, version_no, created_at, change_summary, parent_version_id, schema_version, is_active")


@router.post("/strategies/{strategy_id}/versions")
async def create_version(request: Request, response: Response, strategy_id: str, body: VersionCreate):
    """Save a new version of a v2 strategy, from the version the client loaded (`parent_version_id`). Another save in
    between makes this one 409 stale_parent (two tabs); the answer carries the server's field-by-field diff."""
    user = await get_current_user(request)
    uid = _user_id(user)
    key = _idempotency_key(request)
    sid = _uuid_or_404(strategy_id)
    if not store.is_v2(body.definition):
        raise _store_refusal(422, "schema_mismatch", "This route saves v2 (legs) documents; a v1 strategy is saved with PATCH.")
    problems = store.validate_definition(body.definition)
    if problems:
        raise _store_refusal(422, "invalid_definition", "The version cannot be saved: " + problems[0]["message"],
                             problems=store.problems_with_prefix(problems, "definition"))
    fp = store.fingerprint(body.model_dump())
    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        await _require_store_v2(conn)
        async with conn.transaction():
            await _readable_strategy(conn, sid, uid, owner_only=True, for_update=True)
            if key is not None:
                prior = await conn.fetchrow(
                    "SELECT v.id, v.version_no, v.parent_version_id, v.request_fingerprint, v.definition, "
                    "p.definition AS parent_definition FROM strategy_versions v "
                    "LEFT JOIN strategy_versions p ON p.id = v.parent_version_id "
                    "WHERE v.strategy_id = $1 AND v.idempotency_key = $2", sid, key)
                if prior is not None:
                    if prior["request_fingerprint"] != fp:
                        raise _store_refusal(409, "idempotency_conflict",
                                             "This Idempotency-Key was already used for a different version; nothing new was saved.",
                                             existing_version_id=str(prior["id"]))
                    response.status_code = 200
                    saved = _definition(prior["definition"])
                    return {"version_id": str(prior["id"]), "version_no": prior["version_no"],
                            "parent_version_id": str(prior["parent_version_id"]) if prior["parent_version_id"] else None,
                            "diff": store.diff(_definition(prior["parent_definition"]) or {}, saved),
                            "checks": store.checks(saved), "replayed": True}
            active = await conn.fetchrow(
                "SELECT id, version_no, definition, schema_version FROM strategy_versions "
                "WHERE strategy_id = $1 AND is_active", sid)
            if active is None or active["schema_version"] != store.SCHEMA_V2:
                raise _store_refusal(422, "schema_mismatch",
                                     "This strategy is a v1 (equity DSL) strategy; save its versions with PATCH.")
            if str(active["id"]) != body.parent_version_id:
                raise _store_refusal(409, "stale_parent",
                                     f"Version {active['version_no']} was saved after the one you edited; reload it and "
                                     "apply your change again.",
                                     active_version_id=str(active["id"]), active_version_no=active["version_no"])
            count, top = await conn.fetchrow(
                "SELECT count(*), max(version_no) FROM strategy_versions WHERE strategy_id = $1", sid)
            if count >= store.MAX_VERSIONS_PER_STRATEGY:
                raise _store_refusal(409, "version_limit",
                                     f"A strategy holds at most {store.MAX_VERSIONS_PER_STRATEGY} versions; clone it to go on.")
            before = _definition(active["definition"])
            changes = store.diff(before, body.definition)
            if not changes:
                raise _store_refusal(422, "no_change", f"Nothing changed since version {active['version_no']}.")
            await conn.execute("UPDATE strategy_versions SET is_active = FALSE WHERE strategy_id = $1 AND is_active", sid)
            vid, version_no = await conn.fetchrow(
                """INSERT INTO strategy_versions (strategy_id, version_no, definition, dsl_version, is_active, created_by,
                                                  schema_version, parent_version_id, change_summary, idempotency_key,
                                                  request_fingerprint)
                   VALUES ($1, $2, $3::jsonb, $4, TRUE, $5, $4, $6, $7, $8, $9) RETURNING id, version_no""",
                sid, top + 1, json.dumps(body.definition), store.SCHEMA_V2, uid, active["id"], body.change_summary,
                key, fp)
            await conn.execute(
                "UPDATE strategies SET updated_at = NOW(), name = $2, template_id = $3, underlying = $4, asset_class = $5 "
                "WHERE id = $1",
                sid, body.definition["name"], body.definition.get("template_id"), body.definition["underlying"]["symbol"],
                store.asset_class_of(body.definition))
            await conn.execute(
                """INSERT INTO strategy_audit (strategy_id, actor_id, action, prev_definition, new_definition, note)
                   VALUES ($1, $2, 'UPDATE', $3::jsonb, $4::jsonb, $5)""",
                sid, uid, json.dumps(before), json.dumps(body.definition), body.change_summary)
    response.status_code = 201
    return {"version_id": str(vid), "version_no": version_no, "parent_version_id": str(active["id"]), "diff": changes,
            "checks": store.checks(body.definition), "replayed": False}


@router.get("/strategies/{strategy_id}/versions")
async def list_versions(request: Request, strategy_id: str):
    user = await get_current_user(request)
    uid = _user_id(user)
    sid = _uuid_or_404(strategy_id)
    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        await _require_store_v2(conn)
        await _readable_strategy(conn, sid, uid, owner_only=False)
        rows = await conn.fetch(
            f"SELECT {_VERSION_META} FROM strategy_versions WHERE strategy_id = $1 ORDER BY version_no DESC", sid)
    return {"strategy_id": str(sid), "versions": [_version_row(r) for r in rows], "count": len(rows)}


@router.get("/strategies/{strategy_id}/versions/{version_id}")
async def get_version(request: Request, strategy_id: str, version_id: str):
    user = await get_current_user(request)
    uid = _user_id(user)
    sid = _uuid_or_404(strategy_id)
    vid = _uuid_or_404(version_id, "version")
    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        await _require_store_v2(conn)
        await _readable_strategy(conn, sid, uid, owner_only=False)
        row = await conn.fetchrow(
            f"SELECT {_VERSION_META}, definition FROM strategy_versions WHERE id = $1 AND strategy_id = $2", vid, sid)
    if row is None:
        raise HTTPException(status_code=404, detail="version not found")
    return _version_row(row, with_definition=True)


@router.post("/strategies/{strategy_id}/clone")
async def clone_strategy(request: Request, response: Response, strategy_id: str,
                         body: Optional[CloneRequest] = Body(None)):
    """Copy one version (default: the active one) of your own strategy, or of a public template, into a new strategy
    you own: version 1, `source: "clone"`, `cloned_from` set. v1 and v2 strategies alike."""
    user = await get_current_user(request)
    uid = _user_id(user)
    body = body or CloneRequest()
    sid = _uuid_or_404(strategy_id)
    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        await _require_store_v2(conn)
        async with conn.transaction():
            await _lock_owner(conn, uid)
            src = await _readable_strategy(conn, sid, uid, owner_only=False)
            if body.version_id is not None:
                v = await conn.fetchrow(
                    "SELECT id, version_no, definition, dsl_version, schema_version FROM strategy_versions "
                    "WHERE id = $1 AND strategy_id = $2", _uuid_or_404(body.version_id, "version"), sid)
            else:
                v = await conn.fetchrow(
                    "SELECT id, version_no, definition, dsl_version, schema_version FROM strategy_versions "
                    "WHERE strategy_id = $1 AND is_active", sid)
            if v is None:
                raise HTTPException(status_code=404, detail="version not found")
            n = await conn.fetchval("SELECT count(*) FROM strategies WHERE owner_id = $1 AND NOT is_archived", uid)
            if n >= store.MAX_STRATEGIES_PER_USER:
                raise _store_refusal(409, "strategy_limit",
                                     f"You have {store.MAX_STRATEGIES_PER_USER} strategies; archive one to save another.")
            name = body.name or f"{src['name']} (copy)"[:store.NAME_MAX]
            definition = _definition(v["definition"])
            if isinstance(definition, dict) and "name" in definition:
                definition = {**definition, "name": name}
            new_sid = await conn.fetchval(
                """INSERT INTO strategies (owner_id, name, description, asset_class, source, template_id, underlying,
                                           cloned_from, cloned_from_version)
                   VALUES ($1, $2, $3, $4, 'clone', $5, $6, $7, $8) RETURNING id""",
                uid, name, src["description"], src["asset_class"], src["template_id"], src["underlying"], sid, v["id"])
            new_vid = await conn.fetchval(
                """INSERT INTO strategy_versions (strategy_id, version_no, definition, dsl_version, is_active, created_by,
                                                  schema_version)
                   VALUES ($1, 1, $2::jsonb, $3, TRUE, $4, $5) RETURNING id""",
                new_sid, json.dumps(definition), v["dsl_version"], uid, v["schema_version"])
            await conn.execute(
                """INSERT INTO strategy_audit (strategy_id, actor_id, action, new_definition, note)
                   VALUES ($1, $2, 'CLONE', $3::jsonb, $4)""",
                new_sid, uid, json.dumps(definition), f"clone of {sid} version {v['version_no']}")
    response.status_code = 201
    out = {"strategy_id": str(new_sid), "version_id": str(new_vid), "version_no": 1, "schema_version": v["schema_version"],
           "source": "clone", "cloned_from": {"strategy_id": str(sid), "version_id": str(v["id"]),
                                              "version_no": v["version_no"]}}
    if store.is_v2(definition):
        out["checks"] = store.checks(definition)
    return out


# ── Config (Bot details) ────────────────────────────────────────────
# The stored form of NiveshConfig, in strategy_config (migration 024). Every range,
# default and ownership rule below is read out of services.ai_trader.config, so the class,
# the DB CHECK constraints and the JSON Schema the UI validates against cannot drift
# (spec §4.4: one schema shared by frontend and backend).
_CONFIG_FIELDS = tuple(ai_config.FIELD_RANGES)   # initial_capital, commission_pct, pyramiding, short_margin_pct

# Stored faithfully, but the engine cannot honour them yet: the DSL backtester is long-only
# and counts no same-direction entries, so pyramiding and short margin change nothing about a
# run today. Said out loud in every response rather than left for the UI to imply otherwise.
_CONFIG_NOT_ENFORCED = ("pyramiding", "short_margin_pct")

# FIELD_RANGES bound → JSON Schema keyword (config.py uses `<` vs `<=` via the exclusive_* keys).
_BOUND_KEYWORDS = {"minimum": "minimum", "maximum": "maximum",
                   "exclusive_minimum": "exclusiveMinimum", "exclusive_maximum": "exclusiveMaximum"}


def _config_field_owner(field: str) -> str:
    """Ownership badge of spec §8b.1, derived from config.py's constants rather than restated."""
    if field == "symbols":
        return "platform"
    if field in ai_config.CODE_WRITABLE:
        return "code"            # `strategy_info` may assign it; the field is the fallback
    return "bot_details"


async def _stored_config(conn, strategy_id: str) -> Optional[Dict[str, Any]]:
    """The stored row as plain JSON numbers — asyncpg returns NUMERIC as Decimal, which
    would serialise as a string. None when the strategy has no row yet."""
    row = await conn.fetchrow(
        """SELECT schema_version, initial_capital, commission_pct, pyramiding,
                  short_margin_pct, updated_at
             FROM strategy_config WHERE strategy_id = $1""",
        strategy_id,
    )
    if not row:
        return None
    return {
        "schema_version": int(row["schema_version"]),
        "initial_capital": float(row["initial_capital"]),
        "commission_pct": float(row["commission_pct"]),
        "pyramiding": int(row["pyramiding"]),
        "short_margin_pct": float(row["short_margin_pct"]),
        "updated_at": row["updated_at"],
    }


async def _display_symbols(conn, uid: str, definition: Any) -> tuple:
    """The read-only symbol list for the Bot details tab, and where it came from.

    A `custom` universe keeps its symbols in user_universes.symbols, so that list is exact
    and one cheap read (guarded owner-or-public, like /screen does). An `index` universe is
    a membership *predicate* the compiler expands inside the screening SQL
    (compiler_stock.INDEX_REFS) — there is no stored list to read and enumerating it would
    need a provider round-trip per request. Rather than guess a universe, return nothing and
    label it `unavailable`.
    """
    uni = (definition or {}).get("universe") or {} if isinstance(definition, dict) else {}
    if uni.get("type") != "custom":
        return [], "unavailable"
    try:
        ref = uuid.UUID(str(uni.get("ref")))
    except (TypeError, ValueError):
        return [], "unavailable"
    row = await conn.fetchrow(
        "SELECT symbols FROM user_universes WHERE id = $1 AND (owner_id = $2 OR is_public)",
        ref, uid,
    )
    if not row:
        return [], "unavailable"
    return list(row["symbols"] or []), "custom_universe"


def _config_payload(strategy_id: str, stored: Optional[Dict[str, Any]],
                    symbols: List[str], symbols_source: str) -> Dict[str, Any]:
    """One shape for GET and PUT. No row → the AI defaults with `stored: false`."""
    values = stored or {**ai_config.AI_DEFAULTS,
                        "schema_version": ai_config.SCHEMA_VERSION, "updated_at": None}
    updated_at = values["updated_at"]
    return {
        "strategy_id": str(strategy_id),
        "stored": stored is not None,
        "schema_version": values["schema_version"],
        **{f: values[f] for f in _CONFIG_FIELDS},
        "symbols": symbols,
        "symbols_source": symbols_source,      # "custom_universe" | "unavailable"
        "updated_at": updated_at.isoformat() if updated_at else None,
        "not_enforced_by_engine": list(_CONFIG_NOT_ENFORCED),
    }


def _offending_config_field(message: str) -> Optional[str]:
    """Which field a ConfigValidationError is about — its messages start with the field name."""
    return next((f for f in _CONFIG_FIELDS if message.startswith(f)), None)


def _offending_db_field(error: Exception) -> Optional[str]:
    """Which config column postgres (or asyncpg) refused the value of.

    An unnamed CHECK gets the column into its generated constraint name
    (`strategy_config_pyramiding_check`), and asyncpg names the query argument it could not encode
    (`invalid input for query argument $5: 40000 (value out of int16 range)`).
    """
    text = f"{getattr(error, 'constraint_name', '') or ''} {error}"
    for field in _CONFIG_FIELDS:
        if field in text:
            return field
    m = re.search(r"query argument \$(\d+)", str(error))
    if m:
        i = int(m.group(1)) - 3          # $1 strategy_id, $2 schema_version, $3… the four fields
        if 0 <= i < len(_CONFIG_FIELDS):
            return _CONFIG_FIELDS[i]
    return None


async def _load_strategy_for_config(conn, strategy_id: str, uid: str, *, owner_only: bool):
    """Shared 404 / 403 gate: reads also allow a public template, writes never do."""
    s = await conn.fetchrow("SELECT * FROM strategies WHERE id = $1", strategy_id)
    if not s:
        raise HTTPException(status_code=404, detail="strategy not found")
    if str(s["owner_id"]) != uid and (owner_only or not s["is_public_template"]):
        raise HTTPException(status_code=403, detail="not the owner" if owner_only else "not authorised")
    return s


@router.get("/config-schema")
async def config_schema(request: Request):
    """JSON Schema for the Bot-details built-ins, derived from services.ai_trader.config.

    Spec §4.4 requires the frontend and the backend to reject exactly the same inputs; this
    is the one document both validate against, so a range changes in config.py only.
    """
    await get_current_user(request)
    # `properties` describes the PUT BODY and nothing else, so it holds only the four writable
    # built-ins: with `additionalProperties: false` a client that validates its body against this
    # document must reach the same verdict the endpoint does, and JSON Schema's `readOnly` is an
    # annotation that constrains no input — a `symbols` property here would have the UI accept a
    # body the server then refuses with `unknown_ui_config_field` (spec §4.4). `symbols` is still
    # worth showing, so it is described below under `read_only`, out of the body's schema.
    properties: Dict[str, Any] = {}
    for field, rng in ai_config.FIELD_RANGES.items():
        prop: Dict[str, Any] = {
            "type": rng["json_type"],
            "default": ai_config.AI_DEFAULTS[field],
            "owner": _config_field_owner(field),
            "writable_in_code": field in ai_config.CODE_WRITABLE,
            # Honesty (CONTEXT §1): the UI must not promise an effect the engine has not got.
            "enforced_by_engine": field not in _CONFIG_NOT_ENFORCED,
            "error_message": rng["range_message"],
        }
        for bound, keyword in _BOUND_KEYWORDS.items():
            if bound in rng:
                prop[keyword] = rng[bound]
        if "scale" in rng:
            # The value is stored in NUMERIC(_, scale) and postgres would ROUND anything finer into
            # it, so the UI must refuse the extra decimals exactly as NiveshConfig.validate() does.
            prop["multipleOf"] = 10.0 ** -rng["scale"]
        properties[field] = prop
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Strategy config (Bot details)",
        "schema_version": ai_config.SCHEMA_VERSION,
        "type": "object",
        "additionalProperties": False,          # an unknown field is refused, never dropped
        "required": [],                         # PUT merges onto the stored row, so nothing is mandatory
        "properties": properties,
        "writable": list(_CONFIG_FIELDS),
        "not_enforced_by_engine": list(_CONFIG_NOT_ENFORCED),
        # Displayed, never submitted: not part of the body's schema above (see the comment there).
        "read_only": {
            "symbols": {
                "type": "array", "items": {"type": "string"}, "minItems": 1,
                "readOnly": True, "owner": _config_field_owner("symbols"),
                "description": "Derived from the strategy's universe. Never written through this API.",
            },
        },
    }


@router.get("/strategies/{strategy_id}/config")
async def get_strategy_config(request: Request, strategy_id: str):
    user = await get_current_user(request)
    uid = _user_id(user)
    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        await _load_strategy_for_config(conn, strategy_id, uid, owner_only=False)
        v = await conn.fetchrow(
            "SELECT definition FROM strategy_versions WHERE strategy_id = $1 AND is_active",
            strategy_id,
        )
        stored = await _stored_config(conn, strategy_id)
        definition = v["definition"] if v else None
        if isinstance(definition, str):
            definition = json.loads(definition)
        symbols, source = await _display_symbols(conn, uid, definition)
    return _config_payload(strategy_id, stored, symbols, source)


@router.put("/strategies/{strategy_id}/config")
async def put_strategy_config(request: Request, strategy_id: str, body: Dict[str, Any]):
    """Save the Bot-details built-ins. Owner only — a public template you don't own is 403.

    The body is taken raw so an unknown key can be refused *by name* (FastAPI's own
    extra=forbid 422 names it only in `loc`); it is then parsed by StrategyConfigUpdate and
    validated by building a real NiveshConfig, so the accepted ranges are the class's.
    """
    user = await get_current_user(request)
    uid = _user_id(user)
    unknown = sorted(k for k in body if k not in StrategyConfigUpdate.model_fields)
    if unknown:
        raise HTTPException(status_code=422, detail={
            "message": "unknown_ui_config_field",
            "fields": unknown,
            "settable": list(_CONFIG_FIELDS),
        })
    try:
        patch = StrategyConfigUpdate(**body)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail={
            "message": "invalid_config_value",
            "fields": sorted({str(err["loc"][0]) for err in e.errors() if err.get("loc")}),
            "errors": [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()],
        })
    supplied = {f: v for f, v in patch.model_dump().items() if v is not None}

    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _load_strategy_for_config(conn, strategy_id, uid, owner_only=True)
            stored = await _stored_config(conn, strategy_id)
            before = {f: (stored or ai_config.AI_DEFAULTS)[f] for f in _CONFIG_FIELDS}
            merged = {**before, **supplied}

            v = await conn.fetchrow(
                "SELECT definition FROM strategy_versions WHERE strategy_id = $1 AND is_active",
                strategy_id,
            )
            definition = v["definition"] if v else None
            if isinstance(definition, str):
                definition = json.loads(definition)
            symbols, source = await _display_symbols(conn, uid, definition)

            # NiveshConfig.validate() refuses an empty universe, but a DSL strategy's universe
            # lives in its definition and is never written to strategy_config.symbols (see
            # migration 024). Only the four numbers are being validated here, so when the
            # universe can't be enumerated pass an obvious placeholder: it satisfies the
            # non-empty rule, is never persisted and never returned.
            try:
                cfg = ai_config.resolve(symbols or [f"dsl:{strategy_id}"], ui=merged)
            except ConfigValidationError as e:
                msg = str(e)
                raise HTTPException(status_code=422, detail={
                    "message": msg, "field": _offending_config_field(msg),
                })

            changed = [f"{f} {before[f]} → {merged[f]}" for f in _CONFIG_FIELDS if before[f] != merged[f]]
            note = "Bot details config: " + ("; ".join(changed) if changed else "no field changed")
            try:
                await conn.execute(
                    """INSERT INTO strategy_config
                           (strategy_id, schema_version, initial_capital, commission_pct,
                            pyramiding, short_margin_pct, updated_at)
                       VALUES ($1, $2, $3, $4, $5, $6, NOW())
                       ON CONFLICT (strategy_id) DO UPDATE
                          SET schema_version   = EXCLUDED.schema_version,
                              initial_capital  = EXCLUDED.initial_capital,
                              commission_pct   = EXCLUDED.commission_pct,
                              pyramiding       = EXCLUDED.pyramiding,
                              short_margin_pct = EXCLUDED.short_margin_pct,
                              updated_at       = NOW()""",
                    strategy_id, ai_config.SCHEMA_VERSION, cfg.initial_capital, cfg.commission_pct,
                    cfg.pyramiding, cfg.short_margin_pct,
                )
            except (asyncpg.exceptions.CheckViolationError, asyncpg.exceptions.DataError) as e:
                # Belt and braces. NiveshConfig.validate() above already refuses every value the
                # columns of migration 024 cannot hold (range AND decimal scale AND the SMALLINT
                # domain), so this is unreachable today. If the class and the columns ever drift
                # again the caller still gets the 422 this contract promises, naming the field,
                # instead of a 500 — a domain mismatch is a bad request, not a server fault.
                logger.warning("strategy_config write refused by the database (%s): %s",
                               type(e).__name__, e)
                raise HTTPException(status_code=422, detail={
                    "message": "invalid_config_value",
                    "field": _offending_db_field(e),
                    "error": str(e).splitlines()[0],
                })
            # Not a DSL edit, so prev_definition / new_definition stay NULL — the `note` is the record.
            await conn.execute(
                """INSERT INTO strategy_audit (strategy_id, actor_id, action, note)
                   VALUES ($1, $2, 'CONFIG_UPDATE', $3)""",
                strategy_id, uid, note,
            )
            saved = await _stored_config(conn, strategy_id)
    return _config_payload(strategy_id, saved, symbols, source)


# ── Screen (live ranked candidate list) ─────────────────────────────
@router.post("/screen")
async def screen_strategy(request: Request, body: ScreenRequest):
    """Run a strategy's entry rules against the latest feature snapshot and
    return the ranked candidate list — the Phase-1 "Screen" step.

    Unlike /backtest this evaluates a *single* as_of_date (the latest
    snapshot by default) and does not simulate trades. It reuses the same
    compiler as the backtest, so the candidate set is exactly what a
    backtest would enter on that date — keeping Screen and Backtest
    consistent for a given spec + as_of_date.
    """
    user = await get_current_user(request)
    uid = _user_id(user)

    spec = body.definition
    errs = dsl_mod.validate_strategy(spec)
    if errs:
        raise HTTPException(status_code=400, detail={
            "message": "invalid strategy spec",
            "errors": dsl_mod.errors_as_strings(errs),
        })

    pool = await pg_client.get_pool()

    # Custom universes: compile_stock_query expands `type:custom` to a
    # subselect on user_universes WITHOUT an owner check — its documented
    # contract leaves that to the route layer. Enforce owner-or-public here
    # so a caller can't screen another user's private universe by guessing
    # its UUID.
    uni = spec.get("universe") or {}
    if uni.get("type") == "custom":
        async with pool.acquire() as conn:
            owns = await conn.fetchrow(
                "SELECT 1 FROM user_universes WHERE id = $1 AND (owner_id = $2 OR is_public)",
                uni.get("ref"), uid,
            )
        if not owns:
            raise HTTPException(status_code=403, detail="universe not found or not authorised")

    # Screen via the market-data provider (direct SQL on co-located dev; NIDP
    # DaaS API on staging/prod). Same compiler/evaluator semantics as the
    # backtest, so Screen and Backtest stay consistent for a spec + as_of_date.
    provider = get_provider(pool)
    try:
        asof = _parse_iso_date(body.as_of_date) if body.as_of_date else await provider.latest_date()
        if asof is None:
            raise HTTPException(status_code=503, detail="no feature snapshots available")
        await provider.prepare(spec, asof, asof)
        rows = await provider.screen(spec, asof)
    except (CompileError, EvalError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    ranked_by = spec["ranking"]["by"]
    # Honesty (CONTEXT §1): `score`/`composite_score` are Phase-1 proxies that
    # the compiler maps to accumulation_score. Surface the real basis so the
    # UI can label the score column truthfully rather than implying a
    # fundamentals composite that doesn't exist yet.
    score_basis = "accumulation_score" if ranked_by in {"score", "composite_score"} else ranked_by

    return {
        "candidates": [_serialise(r) for r in rows],
        "count": len(rows),
        "as_of_date": asof.isoformat(),
        "ranked_by": ranked_by,
        "score_basis": score_basis,
    }


# ── Backtest ────────────────────────────────────────────────────────
@router.post("/strategies/{strategy_id}/backtest")
async def run_backtest_endpoint(request: Request, strategy_id: str, body: BacktestRequest):
    user = await get_current_user(request)
    uid = _user_id(user)
    fd = _parse_iso_date(body.from_date)
    td = _parse_iso_date(body.to_date)
    if fd > td:
        raise HTTPException(status_code=400, detail="from_date must be ≤ to_date")
    if (td - fd).days > 365 * 5:
        raise HTTPException(status_code=400, detail="backtest window must be ≤ 5 years")

    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        s = await conn.fetchrow("SELECT * FROM strategies WHERE id = $1", strategy_id)
        if not s:
            raise HTTPException(status_code=404, detail="strategy not found")
        if str(s["owner_id"]) != uid and not s["is_public_template"]:
            raise HTTPException(status_code=403, detail="not authorised")
        v = await conn.fetchrow(
            "SELECT * FROM strategy_versions WHERE strategy_id = $1 AND is_active",
            strategy_id,
        )
        if not v:
            raise HTTPException(status_code=400, detail="strategy has no active version")
        if store.is_v2(_definition(v["definition"])):
            # Not a run: the equity engine cannot read a legs document, and nothing is recorded for a request it refuses.
            raise _store_refusal(422, "backtest_not_available",
                                 "Backtests of saved F&O and multi-leg structures arrive with the options engine "
                                 "(Strategy Copilot Phase 2). Nothing was run or recorded.")
        try:
            stored = await _stored_config(conn, strategy_id)
        except asyncpg.UndefinedTableError:
            # migration 024 not applied on this database yet. Run on the platform defaults
            # rather than failing a backtest that worked before this endpoint learned about
            # stored config — and say so loudly so it gets applied.
            logger.error("strategy_config missing — apply backend/migrations/024_strategy_config.sql")
            stored = None

    # Resolution order (spec §4.2): explicit request value → the strategy's stored config →
    # the platform default. An existing caller that passes starting_capital still wins.
    cfg = {**ai_config.AI_DEFAULTS, **(stored or {})}
    starting_capital = (body.starting_capital if body.starting_capital is not None
                        else float(cfg["initial_capital"]))
    # max_positions has no home in NiveshConfig — spec §8b.7 names that gap — so its
    # fallback stays this router's own default rather than a config value that doesn't exist.
    max_positions = body.max_positions if body.max_positions is not None else DEFAULT_MAX_POSITIONS
    # commission_pct is a per-side PERCENT; the backtester's per-side cost is slippage_pct as a
    # FRACTION (bt.DEFAULT_SLIPPAGE_PCT = 0.0005 = 5 bps). Same conversion, and the same
    # reasoning, as services/ai_trader/strategy.py's resolved-config run: charge it there
    # instead of a second time of our own.
    slippage_pct = float(cfg["commission_pct"]) / 100.0

    spec = v["definition"]
    if isinstance(spec, str):
        spec = json.loads(spec)
    try:
        result = await bt.run_backtest(
            pool, spec,
            from_date=fd, to_date=td,
            starting_capital=starting_capital,
            max_positions=max_positions,
            slippage_pct=slippage_pct,
        )
    except (CompileError, ValueError) as e:
        await _record_failed_run(pool, strategy_id, v["id"], fd, td, uid, e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001 — recorded as FAILED, logged, and re-raised as a 500
        failed_id = await _record_failed_run(pool, strategy_id, v["id"], fd, td, uid, e)
        logger.exception("backtest of strategy %s failed; run %s recorded as FAILED", strategy_id, failed_id)
        raise HTTPException(status_code=500, detail=(f"backtest failed; recorded as FAILED run {failed_id}"
                                                     if failed_id else "backtest failed"))

    run_id = await bt.persist_run(
        pool, strategy_id=strategy_id, version_id=v["id"],
        spec=spec, result=result, from_date=fd, to_date=td, triggered_by=uid,
    )
    status, error_message = bt.run_status(result)
    return {
        "run_id": run_id,
        # OK, or FAILED for a window with no data (metrics.reason stays "no_data", which the screens already read).
        "status": status,
        "error": error_message,
        "metrics": result.metrics,
        # What reproduces this run (data watermark, code, rule and cost-model versions, universe): the same
        # block GET /runs/{run_id} returns for any stored run (backtest.run_provenance).
        "provenance": bt.run_provenance({"metrics": result.metrics, "version_id": v["id"]}),
        "equity_curve": result.equity_curve,
        "trade_count": len(result.trades),
        # What the run actually used, and where each number came from — the caller should not
        # have to guess whether its own value, the stored config or a default won.
        "resolved_config": {
            "starting_capital": starting_capital,
            "starting_capital_source": ("request" if body.starting_capital is not None
                                        else "strategy_config" if stored else "default"),
            "max_positions": max_positions,
            "max_positions_source": "request" if body.max_positions is not None else "default",
            "commission_pct": float(cfg["commission_pct"]),
            "slippage_pct": slippage_pct,
            "config_stored": stored is not None,
            "not_enforced_by_engine": list(_CONFIG_NOT_ENFORCED),
        },
    }


def _can_read_run(run, uid: str) -> bool:
    """Who may read a stored run and its trade ledger (PRD §15, §19.2: no cross-user access).

    - The user who triggered the run.
    - The owner of a private strategy, for every run of it (only the owner can run a private strategy), and the owner
      of any strategy for a run nobody triggered (a system run, `triggered_by` NULL).
    - Nobody else. In particular, a public template's runs belong to the users who ran them, not to every user, and
      not to the template's owner either."""
    triggered_by = str(run.get("triggered_by")) if run.get("triggered_by") else None
    if triggered_by == uid:
        return True
    if str(run["strategy_owner"]) != uid:
        return False
    return (not run["is_public_template"]) or triggered_by is None


async def _audit_run_denied(request: Request, uid: str, run_id: str, reason: str) -> None:
    """Record a refused run read in audit_log (PRD Appendix A: deny and log). audit.record never raises."""
    from services import audit
    await audit.record(
        user_id=uid, action="strategy_run_view", resource=f"strategy_run:{run_id}"[:120],
        ip=request.client.host if request.client else None, ua=request.headers.get("user-agent"),
        outcome="denied", details={"reason": reason},
    )


@router.get("/runs/{run_id}")
async def get_run(request: Request, run_id: str):
    user = await get_current_user(request)
    uid = _user_id(user)
    # One answer for "no such run" and "not yours", so a caller cannot learn that someone else's run exists.
    not_found = HTTPException(status_code=404, detail="run not found")
    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        try:
            run = await conn.fetchrow(
                """SELECT r.*, s.owner_id AS strategy_owner, s.is_public_template
                     FROM strategy_runs r
                     JOIN strategies s ON s.id = r.strategy_id
                    WHERE r.id = $1""",
                run_id,
            )
        except asyncpg.DataError:
            # asyncpg refuses an id that is not a UUID before it reaches postgres ("invalid input for query
            # argument $1"). No run can have that id: answer 404, not a 500.
            raise not_found
        if not run:
            raise not_found
        if not _can_read_run(run, uid):
            await _audit_run_denied(request, uid, run_id, "not the run's trigger or the private strategy's owner")
            raise not_found
        trades = await conn.fetch(
            "SELECT * FROM strategy_trades WHERE run_id = $1 ORDER BY entry_date",
            run_id,
        )
        version = await conn.fetchrow("SELECT definition FROM strategy_versions WHERE id = $1", run["version_id"])
    return {
        "run": _serialise(run),
        # Every run, older ones included, is read through one normaliser: a field the run never recorded is null
        # and named in provenance.not_recorded (runs before provenance-v1 lack the code version, the spec hash is
        # derived from the immutable strategy version, and so on). Nothing is guessed.
        "provenance": bt.run_provenance(dict(run), version["definition"] if version else None),
        "trades": [_serialise(t) for t in trades],
    }


# ── Admin ───────────────────────────────────────────────────────────
@router.post("/strategies/{strategy_id}/promote")
async def promote_template(request: Request, strategy_id: str):
    await require_admin(request)
    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE strategies SET is_public_template = TRUE WHERE id = $1",
            strategy_id,
        )
    return {"ok": True, "strategy_id": strategy_id, "is_public_template": True}


@router.post("/snapshot-features")
async def admin_snapshot_features(request: Request,
                                   target_date: Optional[str] = Query(None),
                                   universe: str = "nifty500"):
    await require_admin(request)
    from nidp.services.feature_snapshotter import snapshot_features_for_date
    pool = await pg_client.get_pool()
    d = _parse_iso_date(target_date) if target_date else date.today()
    report = await snapshot_features_for_date(pool, d, universe_filter=universe)
    return {"ok": True, "report": report.as_dict()}


# ── Serialisation ───────────────────────────────────────────────────
def _serialise(row) -> Dict[str, Any]:
    """Convert asyncpg Record / dict to a JSON-friendly dict."""
    if row is None:
        return {}
    if hasattr(row, "_asdict"):
        d = dict(row)
    elif isinstance(row, dict):
        d = dict(row)
    else:
        d = dict(row)
    out: Dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, (datetime, date)):
            out[k] = v.isoformat()
        elif isinstance(v, uuid.UUID):
            out[k] = str(v)
        elif isinstance(v, str) and k in {"definition", "metrics", "equity_curve", "reasons", "metadata"}:
            try:
                out[k] = json.loads(v)
            except Exception:   # noqa: BLE001
                out[k] = v
        else:
            out[k] = v
    return out
