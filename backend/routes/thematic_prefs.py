"""Per-user thematic research preferences — query history + favourites.

Server-backed (Mongo `thematic_prefs`, one doc per user) so the Research page's
history/favourites follow the user across devices. Mirrors the client hook's shape:
{ history: [str], favorites: [str] }. History is newest-first, deduped, capped.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from pydantic import BaseModel

from deps import db, get_current_user

router = APIRouter(prefix="/api")

_CAP = 40
_indexed = False


async def _ensure_index() -> None:
    global _indexed
    if _indexed:
        return
    try:
        await db.thematic_prefs.create_index("user_id", unique=True)
    except Exception:  # noqa: BLE001 — index is best-effort
        pass
    _indexed = True


class QueryBody(BaseModel):
    query: str | None = None
    clear: bool | None = False


async def _load(uid: str) -> dict:
    doc = await db.thematic_prefs.find_one(
        {"user_id": uid}, {"_id": 0, "history": 1, "favorites": 1})
    return {
        "history": (doc or {}).get("history") or [],
        "favorites": (doc or {}).get("favorites") or [],
    }


async def _save(uid: str, patch: dict) -> None:
    patch = {**patch, "updated_at": datetime.now(timezone.utc)}
    await db.thematic_prefs.update_one({"user_id": uid}, {"$set": patch}, upsert=True)


@router.get("/thematic/prefs")
async def get_prefs(request: Request):
    await _ensure_index()
    user = await get_current_user(request)
    return await _load(user["user_id"])


@router.post("/thematic/history")
async def add_history(request: Request, body: QueryBody):
    await _ensure_index()
    user = await get_current_user(request)
    uid = user["user_id"]
    cur = await _load(uid)
    q = (body.query or "").strip()
    if q:
        hist = ([q] + [x for x in cur["history"] if x != q])[:_CAP]
        await _save(uid, {"history": hist})
        cur["history"] = hist
    return cur


@router.post("/thematic/history/remove")
async def remove_history(request: Request, body: QueryBody):
    await _ensure_index()
    user = await get_current_user(request)
    uid = user["user_id"]
    cur = await _load(uid)
    if body.clear:
        hist: list = []
    else:
        q = (body.query or "").strip()
        hist = [x for x in cur["history"] if x != q]
    await _save(uid, {"history": hist})
    cur["history"] = hist
    return cur


@router.post("/thematic/favorites/toggle")
async def toggle_favorite(request: Request, body: QueryBody):
    await _ensure_index()
    user = await get_current_user(request)
    uid = user["user_id"]
    cur = await _load(uid)
    q = (body.query or "").strip()
    if q:
        favs = [x for x in cur["favorites"] if x != q] if q in cur["favorites"] else [q] + cur["favorites"]
        await _save(uid, {"favorites": favs})
        cur["favorites"] = favs
    return cur
