"""Market Desk › Scan Builder: stock scans the user builds, run on our own data (docs/scan_builder/DESIGN.md §4).

Endpoints (signed-in user, behind the `scan_builder` feature flag; every saved scan is scoped to its owner):
    GET    /api/scan-builder/catalog          measures, fundamentals, operators, universes (with sizes), timeframes, templates,
                                              limits, default_spec, refresh_seconds; also starts warming the price panel
    POST   /api/scan-builder/run    {spec}    -> RunResult; at most one run per user per RUN_GAP_S in this worker (429)
    GET    /api/scan-builder/scans            -> {scans: [{id, name, description, created_at, updated_at}]}
    POST   /api/scan-builder/scans  {spec}    -> {scan}
    GET    /api/scan-builder/scans/{id}       -> {scan}
    PUT    /api/scan-builder/scans/{id} {spec} -> {scan}
    POST   /api/scan-builder/scans/{id}/copy  -> {scan}
    DELETE /api/scan-builder/scans/{id}       -> {ok: true}
    GET    /api/scan-builder/market-dashboard -> the realtime scan dashboard (DESIGN.md §8): the 17 widgets of Chartink
                                              dashboard 247498 on our data, each with its criteria; one computation per
                                              market_dashboard.CACHE_S per worker, shared by every viewer

Typed errors: {"detail": {"code", "message", ...}} plus status/error/code/message at the top level (the desk client reads
detail): invalid_spec (422, with `path`), run_too_soon (429, retry_after_s), data_unavailable (503), scan_not_found (404),
too_many_scans (409). The flag dependency answers 403 when the feature is off for the user. Reads market data only; no order
is ever placed. Writes pass the app's CSRF middleware like every other write.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from deps import db, get_current_user
from feature_gate import require_feature
from services.scan_builder import market_dashboard, service, spec as specmod, store
from services.scan_builder.data import DataUnavailable, get_data

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/scan-builder", tags=["scan-builder"], dependencies=[Depends(require_feature("scan_builder"))])

RUN_GAP_S = 4.0
_last_run: Dict[str, float] = {}
_indexes_ready = False


def _answer(status: int, code: str, message: str, **extra: Any) -> JSONResponse:
    detail = {"code": code, "message": message, **extra}
    return JSONResponse(status_code=status, content={"detail": detail, "status": status, "error": code, "code": code,
                                                     "message": message})


async def _user_id(request: Request) -> str:
    user = await get_current_user(request)
    return str(user.get("user_id"))


async def _ensure_indexes() -> None:
    global _indexes_ready
    if not _indexes_ready:
        await store.ensure_indexes(db)
        _indexes_ready = True


async def _body_spec(request: Request):
    try:
        body = await request.json()
    except ValueError:
        return None, _answer(422, "invalid_spec", "The request body is not JSON.", path="")
    if not isinstance(body, dict) or "spec" not in body:
        return None, _answer(422, "invalid_spec", "The body must be {\"spec\": {...}}.", path="spec")
    try:
        return specmod.validate(body["spec"]), None
    except specmod.SpecError as e:
        return None, _answer(422, "invalid_spec", e.message, path=e.path)


@router.get("/catalog")
async def catalog(request: Request):
    await _user_id(request)
    data = get_data()
    out = specmod.catalog()
    sizes: Dict[str, Any] = {}
    try:
        ref = await data.reference()
        sizes = service.universe_sizes(data.loaded_panel, ref)
    except DataUnavailable as e:
        logger.warning("scan builder catalog: universe sizes unavailable: %s", e.message)
    out["universes"] = [{**u, "size": sizes.get(u["key"])} for u in out["universes"]]
    out["refresh_seconds"] = service.REFRESH_SECONDS
    data.warm()
    return out


@router.post("/run")
async def run(request: Request):
    uid = await _user_id(request)
    spec, err = await _body_spec(request)
    if err is not None:
        return err
    now = time.monotonic()
    last = _last_run.get(uid)
    if last is not None and now - last < RUN_GAP_S:
        wait = round(RUN_GAP_S - (now - last), 1)
        return _answer(429, "run_too_soon", f"One run every {RUN_GAP_S:g} seconds; try again in {wait:g} s.", retry_after_s=wait)
    _last_run[uid] = now
    try:
        return await service.run(spec, get_data())
    except DataUnavailable as e:
        return _answer(503, "data_unavailable", e.message)


@router.get("/market-dashboard")
async def market_dashboard_view(request: Request):
    uid = await _user_id(request)
    try:
        dash = await market_dashboard.get_dashboard(get_data())
    except DataUnavailable as e:
        return _answer(503, "data_unavailable", e.message)
    return await market_dashboard.attach_ideas(dash, uid)


@router.get("/scans")
async def list_scans(request: Request):
    uid = await _user_id(request)
    await _ensure_indexes()
    return {"scans": await store.list_scans(db, uid)}


@router.post("/scans")
async def create_scan(request: Request):
    uid = await _user_id(request)
    spec, err = await _body_spec(request)
    if err is not None:
        return err
    await _ensure_indexes()
    try:
        return {"scan": await store.create_scan(db, uid, spec)}
    except store.StoreError as e:
        return _answer(e.status, e.code, e.message)


@router.get("/scans/{scan_id}")
async def get_scan(scan_id: str, request: Request):
    uid = await _user_id(request)
    try:
        return {"scan": await store.get_scan(db, uid, scan_id)}
    except store.StoreError as e:
        return _answer(e.status, e.code, e.message)


@router.put("/scans/{scan_id}")
async def update_scan(scan_id: str, request: Request):
    uid = await _user_id(request)
    spec, err = await _body_spec(request)
    if err is not None:
        return err
    try:
        return {"scan": await store.update_scan(db, uid, scan_id, spec)}
    except store.StoreError as e:
        return _answer(e.status, e.code, e.message)


@router.post("/scans/{scan_id}/copy")
async def copy_scan(scan_id: str, request: Request):
    uid = await _user_id(request)
    await _ensure_indexes()
    try:
        return {"scan": await store.copy_scan(db, uid, scan_id)}
    except store.StoreError as e:
        return _answer(e.status, e.code, e.message)


@router.delete("/scans/{scan_id}")
async def delete_scan(scan_id: str, request: Request):
    uid = await _user_id(request)
    try:
        await store.delete_scan(db, uid, scan_id)
    except store.StoreError as e:
        return _answer(e.status, e.code, e.message)
    return {"ok": True}
