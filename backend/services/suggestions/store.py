"""The suggestion engine's five Mongo stores. Written by this code only.

    suggestion_rules      rules as data, `_id` = rule id; a stored rule overrides catalog.RULES field by field
    query_templates       `_id` = template id; label, query, the visual-answer intent it resolves to, tab, audience
    suggestion_events     one per (user, event dedupe key): what was detected, when, from which inputs (insert once)
    suggestion_instances  one per (user, dedupe key), `_id` = sg_<hash>: what the card says, its class and tab, the
                          inputs with their as-of dates, state (active | dismissed | completed), expires_at (TTL)
    suggestion_feedback   every dismissed / useful / not_relevant / completed, with the rule and the dedupe key

`seed()` writes the catalog idempotently (an admin step: scripts/seed_suggestions.py). Nothing needs the seed to run:
the engine reads the catalog defaults merged with whatever is stored.
"""
from __future__ import annotations

import copy
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import catalog

RULES = "suggestion_rules"
EVENTS = "suggestion_events"
INSTANCES = "suggestion_instances"
FEEDBACK = "suggestion_feedback"
TEMPLATES = "query_templates"
COLLECTIONS = (RULES, EVENTS, INSTANCES, FEEDBACK, TEMPLATES)

ACTIONS = ("dismissed", "useful", "not_relevant", "completed")
STATES = ("active", "dismissed", "completed")

_indexes_ready = False


def instance_id(user_id: str, dedupe_key: str) -> str:
    return "sg_" + hashlib.sha256(f"{user_id}|{dedupe_key}".encode()).hexdigest()[:16]


def event_id(user_id: str, dedupe_key: str) -> str:
    return "se_" + hashlib.sha256(f"{user_id}|{dedupe_key}".encode()).hexdigest()[:16]


async def ensure_indexes(db: Any) -> None:
    global _indexes_ready
    if _indexes_ready:
        return
    await db[INSTANCES].create_index([("user_id", 1), ("tab", 1), ("state", 1)])
    await db[INSTANCES].create_index([("user_id", 1), ("dedupe_key", 1)], unique=True)
    await db[INSTANCES].create_index("expires_at", expireAfterSeconds=0)
    await db[EVENTS].create_index([("user_id", 1), ("dedupe_key", 1)], unique=True)
    await db[EVENTS].create_index([("user_id", 1), ("detected_at", -1)])
    await db[FEEDBACK].create_index([("user_id", 1), ("dedupe_key", 1), ("at", -1)])
    await db[FEEDBACK].create_index([("user_id", 1), ("rule_id", 1), ("at", -1)])
    await db[RULES].create_index([("tab", 1), ("enabled", 1)])
    await db[TEMPLATES].create_index([("tab", 1)])
    _indexes_ready = True


async def seed(db: Any, *, now: Optional[datetime] = None) -> Dict[str, int]:
    """Write the catalog's rules and templates. Idempotent: a stored document keeps the fields an admin changed
    ($setOnInsert only), so re-running the seed never undoes a tuning."""
    at = (now or datetime.now(timezone.utc)).isoformat()
    added = {"rules": 0, "templates": 0}
    for coll, rows, key in ((RULES, catalog.RULES, "rules"), (TEMPLATES, catalog.QUERY_TEMPLATES, "templates")):
        for row in rows:
            doc = {k: v for k, v in copy.deepcopy(row).items() if k != "_id"}
            res = await db[coll].update_one({"_id": row["_id"]}, {"$setOnInsert": {**doc, "seeded_at": at}}, upsert=True)
            added[key] += 1 if getattr(res, "upserted_id", None) is not None else 0
    await ensure_indexes(db)
    return added


async def _stored(db: Any, coll: str) -> Dict[str, Dict[str, Any]]:
    try:
        docs = await db[coll].find({}).to_list(500)
    except Exception:  # noqa: BLE001 — the catalog defaults still serve
        return {}
    return {d["_id"]: d for d in docs if d.get("_id")}


async def rules(db: Any) -> List[Dict[str, Any]]:
    """Catalog rules with any stored overrides; stored rules not in the catalog are left out (an evaluator must exist)."""
    stored = await _stored(db, RULES)
    out = []
    for r in catalog.RULES:
        merged = {**copy.deepcopy(r), **{k: v for k, v in stored.get(r["_id"], {}).items() if k not in ("_id", "seeded_at")}}
        out.append(merged)
    return out


async def templates(db: Any) -> Dict[str, Dict[str, Any]]:
    stored = await _stored(db, TEMPLATES)
    return {t["_id"]: {**copy.deepcopy(t), **{k: v for k, v in stored.get(t["_id"], {}).items() if k not in ("_id", "seeded_at")}}
            for t in catalog.QUERY_TEMPLATES}


async def latest_feedback(db: Any, user_id: str) -> List[Dict[str, Any]]:
    """The user's newest 500 feedback rows, newest first (the engine keeps the last 30 days)."""
    return await db[FEEDBACK].find({"user_id": user_id}, {"_id": 0}).sort("at", -1).to_list(500)


async def record_event(db: Any, user_id: str, *, dedupe_key: str, rule_id: str, facts: Dict[str, Any],
                       inputs: List[Dict[str, Any]], now: datetime) -> str:
    eid = event_id(user_id, dedupe_key)
    await db[EVENTS].update_one({"_id": eid}, {"$setOnInsert": {
        "user_id": user_id, "dedupe_key": dedupe_key, "rule_id": rule_id, "facts": facts, "inputs": inputs,
        "detected_at": now.isoformat()}}, upsert=True)
    return eid


async def upsert_instance(db: Any, doc: Dict[str, Any], *, now: datetime) -> None:
    """Write what the card says now (it is shown, so it is active: a dismissal whose cooldown has run out ends here);
    keep its first-seen time."""
    fields = {k: v for k, v in doc.items() if k not in ("_id", "created_at")}
    fields.update(state="active", updated_at=now.isoformat())
    await db[INSTANCES].update_one({"_id": doc["_id"]}, {"$set": fields, "$setOnInsert": {"created_at": now.isoformat()}},
                                   upsert=True)


async def get_instance(db: Any, user_id: str, sid: str) -> Optional[Dict[str, Any]]:
    return await db[INSTANCES].find_one({"_id": sid, "user_id": user_id})


async def add_feedback(db: Any, inst: Dict[str, Any], action: str, *, now: datetime) -> Dict[str, Any]:
    row = {"user_id": inst["user_id"], "suggestion_id": inst["_id"], "dedupe_key": inst["dedupe_key"],
           "rule_id": inst["rule_id"], "class": inst.get("class"), "tab": inst.get("tab"), "action": action,
           "at": now.isoformat()}
    await db[FEEDBACK].insert_one(dict(row))
    state = {"dismissed": "dismissed", "not_relevant": "dismissed", "completed": "completed"}.get(action)
    if state:
        await db[INSTANCES].update_one({"_id": inst["_id"]}, {"$set": {"state": state, "state_at": now.isoformat()}})
    return {**row, "state": state or inst.get("state") or "active"}
