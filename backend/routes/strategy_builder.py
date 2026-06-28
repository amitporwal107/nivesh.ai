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
  POST   /api/strategy-builder/screen                   — run entry rules vs latest snapshot → ranked list
  POST   /api/strategy-builder/strategies/{id}/backtest — run backtest, returns run_id
  GET    /api/strategy-builder/runs/{run_id}            — fetch backtest result + trades
  POST   /api/strategy-builder/validate                 — validate a DSL doc (no save)

Admin:
  POST   /api/strategy-builder/strategies/{id}/promote   — mark as public template
  POST   /api/strategy-builder/snapshot-features         — kick off feature snapshotter
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from deps import get_current_user, require_admin
from services import pg_client
from services.strategy_engine import dsl as dsl_mod
from services.strategy_engine import backtest as bt
from services.strategy_engine.compiler_stock import compile_stock_query, to_asyncpg, CompileError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/strategy-builder", tags=["strategy-builder"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "services" / "strategy_engine" / "templates"


# ── Pydantic request bodies ─────────────────────────────────────────
class StrategyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    asset_class: str = Field(..., pattern="^(STOCK|MF)$")
    definition: Dict[str, Any]


class StrategyUpdate(BaseModel):
    definition: Dict[str, Any]


class UniverseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    asset_class: str = Field(..., pattern="^(STOCK|MF)$")
    symbols: List[str] = Field(default_factory=list)


class BacktestRequest(BaseModel):
    from_date: str   # ISO YYYY-MM-DD
    to_date: str
    starting_capital: float = 1_000_000.0
    max_positions: int = 10


class ScreenRequest(BaseModel):
    definition: Dict[str, Any]
    as_of_date: Optional[str] = None   # ISO YYYY-MM-DD; default = latest snapshot


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


# ── Strategies ──────────────────────────────────────────────────────
@router.post("/strategies")
async def create_strategy(request: Request, body: StrategyCreate):
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


@router.get("/strategies")
async def list_strategies(request: Request, include_templates: bool = False):
    user = await get_current_user(request)
    uid = _user_id(user)
    pool = await pg_client.get_pool()
    where = ["NOT is_archived", "(owner_id = $1"]
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


@router.get("/strategies/{strategy_id}")
async def get_strategy(request: Request, strategy_id: str):
    user = await get_current_user(request)
    uid = _user_id(user)
    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        s = await conn.fetchrow(
            "SELECT * FROM strategies WHERE id = $1", strategy_id,
        )
        if not s:
            raise HTTPException(status_code=404, detail="strategy not found")
        if str(s["owner_id"]) != uid and not s["is_public_template"]:
            raise HTTPException(status_code=403, detail="not authorised")
        v = await conn.fetchrow(
            "SELECT * FROM strategy_versions WHERE strategy_id = $1 AND is_active",
            strategy_id,
        )
    return {
        **_serialise(s),
        "active_version": _serialise(v) if v else None,
    }


@router.patch("/strategies/{strategy_id}")
async def update_strategy(request: Request, strategy_id: str, body: StrategyUpdate):
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

    # Compile once; bind as_of_date into the trailing positional slot exactly
    # as the backtest runner does (compiler emits ":as_of_date", not a pN).
    try:
        sql, params = compile_stock_query(spec)
    except CompileError as e:
        raise HTTPException(status_code=400, detail=str(e))
    sql_pg, base_args = to_asyncpg(sql, params)
    next_slot = len(base_args) + 1
    sql_pg = sql_pg.replace(":as_of_date", f"${next_slot}")

    async with pool.acquire() as conn:
        if body.as_of_date:
            asof = _parse_iso_date(body.as_of_date)
        else:
            row = await conn.fetchrow(
                "SELECT MAX(as_of_date) AS d FROM nidp.stock_features_daily"
            )
            asof = row["d"] if row and row["d"] else None
            if asof is None:
                raise HTTPException(status_code=503, detail="no feature snapshots available")
        rows = await conn.fetch(sql_pg, *(list(base_args) + [asof]))

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

    spec = v["definition"]
    if isinstance(spec, str):
        spec = json.loads(spec)
    try:
        result = await bt.run_backtest(
            pool, spec,
            from_date=fd, to_date=td,
            starting_capital=body.starting_capital,
            max_positions=body.max_positions,
        )
    except (CompileError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    run_id = await bt.persist_run(
        pool, strategy_id=strategy_id, version_id=v["id"],
        spec=spec, result=result, from_date=fd, to_date=td, triggered_by=uid,
    )
    return {
        "run_id": run_id,
        "metrics": result.metrics,
        "equity_curve": result.equity_curve,
        "trade_count": len(result.trades),
    }


@router.get("/runs/{run_id}")
async def get_run(request: Request, run_id: str):
    user = await get_current_user(request)
    uid = _user_id(user)
    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        run = await conn.fetchrow(
            """SELECT r.*, s.owner_id AS strategy_owner, s.is_public_template
                 FROM strategy_runs r
                 JOIN strategies s ON s.id = r.strategy_id
                WHERE r.id = $1""",
            run_id,
        )
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        if str(run["strategy_owner"]) != uid and not run["is_public_template"]:
            raise HTTPException(status_code=403, detail="not authorised")
        trades = await conn.fetch(
            "SELECT * FROM strategy_trades WHERE run_id = $1 ORDER BY entry_date",
            run_id,
        )
    return {
        "run": _serialise(run),
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
