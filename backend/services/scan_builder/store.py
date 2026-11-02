"""Saved scans, per user, in MongoDB collection `scan_builder_scans`.

A document: {id, user_id, name, description, spec, created_at, updated_at}. Every read and write is scoped to its owner, so
another user's id answers "not found" (never "forbidden", which would confirm it exists). The spec is stored as validated.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

COLLECTION = "scan_builder_scans"
MAX_SCANS_PER_USER = 100
_PUBLIC = {"_id": 0, "user_id": 0}


class StoreError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def ensure_indexes(db) -> None:
    await db[COLLECTION].create_index([("user_id", 1), ("updated_at", -1)])
    await db[COLLECTION].create_index([("id", 1)], unique=True)


async def list_scans(db, user_id: str) -> List[Dict[str, Any]]:
    cur = db[COLLECTION].find({"user_id": user_id}, {"_id": 0, "id": 1, "name": 1, "description": 1, "created_at": 1,
                                                      "updated_at": 1}).sort("updated_at", -1)
    return [d async for d in cur]


async def get_scan(db, user_id: str, scan_id: str) -> Dict[str, Any]:
    doc = await db[COLLECTION].find_one({"id": scan_id, "user_id": user_id}, _PUBLIC)
    if not doc:
        raise StoreError("scan_not_found", "No saved scan with that id.", 404)
    return doc


async def create_scan(db, user_id: str, spec: Dict[str, Any], *, name: Optional[str] = None) -> Dict[str, Any]:
    if await db[COLLECTION].count_documents({"user_id": user_id}) >= MAX_SCANS_PER_USER:
        raise StoreError("too_many_scans", f"You can keep at most {MAX_SCANS_PER_USER} saved scans; delete one first.", 409)
    now = _now()
    spec = {**spec, "name": name or spec["name"]}
    doc = {"id": uuid.uuid4().hex, "user_id": user_id, "name": spec["name"], "description": spec.get("description", ""),
           "spec": spec, "created_at": now, "updated_at": now}
    await db[COLLECTION].insert_one(dict(doc))
    return {k: v for k, v in doc.items() if k != "user_id"}


async def update_scan(db, user_id: str, scan_id: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    now = _now()
    res = await db[COLLECTION].update_one({"id": scan_id, "user_id": user_id},
                                          {"$set": {"spec": spec, "name": spec["name"],
                                                    "description": spec.get("description", ""), "updated_at": now}})
    if not res.matched_count:
        raise StoreError("scan_not_found", "No saved scan with that id.", 404)
    return await get_scan(db, user_id, scan_id)


async def copy_scan(db, user_id: str, scan_id: str) -> Dict[str, Any]:
    src = await get_scan(db, user_id, scan_id)
    name = f"Copy of {src['name']}"[:80]
    return await create_scan(db, user_id, src["spec"], name=name)


async def delete_scan(db, user_id: str, scan_id: str) -> None:
    res = await db[COLLECTION].delete_one({"id": scan_id, "user_id": user_id})
    if not res.deleted_count:
        raise StoreError("scan_not_found", "No saved scan with that id.", 404)
