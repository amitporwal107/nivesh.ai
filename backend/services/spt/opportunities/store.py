"""The `spt_opportunities` collection (DESIGN.md §3, §4, §5).

One market-wide document per consolidated opportunity: `_id` uuid4, `consolidation_key` unique among open opportunities
(a partial unique index on `is_open: true`). Every state change is ONE conditional update whose filter carries the state and
the `version` read just before (DESIGN.md D7: no multi-document transactions), so two writers can never both move it.

Read interface for slice B (DESIGN.md §4; B writes nothing here except through `transition`, and only to EXPIRED):

    async get(db, opp_id) -> dict | None
    async list_by_state(db, states, *, day=None, limit=500) -> list          oldest first_seen_at first
    async transition(db, opp_id, *, expect_states, to_state, reason, extra=None) -> dict | None

`transition` answers None (and writes nothing) when the opportunity is missing, is not in one of `expect_states`, the move
is not in the state machine (ALLOWED), or another writer changed it between the read and the write. It appends
{from, to, reason, at, version} to `state_history` and emits OPPORTUNITY_QUALIFIED / _REJECTED / _EXPIRED for those states.

Evidence bookkeeping: `evidence_version` rises on every attached signal and every conflict; a validation records the
`evidence_version` it judged as `validated_evidence_version`, so new evidence is never lost to a race with a validation.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .. import constants as C
from .. import events

logger = logging.getLogger(__name__)

COLL = C.OPPORTUNITIES
SOURCE = "spt-opportunity-engine"
MAX_LIMIT = 500

ALLOWED: Dict[str, tuple] = {
    C.OPP_CREATED: (C.OPP_VALIDATING, C.OPP_EXPIRED),
    C.OPP_VALIDATING: (C.OPP_QUALIFIED, C.OPP_CONDITIONAL, C.OPP_WATCHLIST, C.OPP_REJECTED, C.OPP_DATA_INSUFFICIENT,
                       C.OPP_EXPIRED),
    C.OPP_CONDITIONAL: (C.OPP_VALIDATING, C.OPP_EXPIRED),
    C.OPP_WATCHLIST: (C.OPP_VALIDATING, C.OPP_EXPIRED),
    C.OPP_DATA_INSUFFICIENT: (C.OPP_VALIDATING, C.OPP_EXPIRED),
    C.OPP_QUALIFIED: (C.OPP_EXPIRED,),
    C.OPP_REJECTED: (),
    C.OPP_EXPIRED: (),
}
STATE_EVENTS = {C.OPP_QUALIFIED: "OPPORTUNITY_QUALIFIED", C.OPP_REJECTED: "OPPORTUNITY_REJECTED",
                C.OPP_EXPIRED: "OPPORTUNITY_EXPIRED"}
PROTECTED = {"_id", "state", "version", "state_history", "is_open", "consolidation_key"}

_indexed = False


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def ensure_indexes(db) -> None:
    global _indexed
    if _indexed:
        return
    c = db[COLL]
    await c.create_index([("consolidation_key", 1)], unique=True, partialFilterExpression={"is_open": True},
                         name="consolidation_key_open_unique")
    await c.create_index([("symbol", 1), ("direction", 1), ("horizon", 1), ("state", 1)])
    await c.create_index([("state", 1), ("first_seen_at", 1)])
    await c.create_index([("day", 1), ("state", 1)])
    await c.create_index([("signals.signal_id", 1)])
    _indexed = True


async def get(db, opp_id: str) -> Optional[Dict[str, Any]]:
    return await db[COLL].find_one({"_id": opp_id})


async def list_by_state(db, states: Sequence[str], *, day: Optional[str] = None, limit: int = MAX_LIMIT) -> List[Dict[str, Any]]:
    """Opportunities in any of `states` (and of IST `day`, the first signal's day, when given), oldest first."""
    q: Dict[str, Any] = {"state": {"$in": list(states)}}
    if day:
        q["day"] = day
    lim = max(1, min(int(limit or MAX_LIMIT), MAX_LIMIT))
    return await db[COLL].find(q).sort("first_seen_at", 1).limit(lim).to_list(length=None)


async def transition(db, opp_id: str, *, expect_states: Iterable[str], to_state: str, reason: str,
                     extra: Optional[Dict[str, Any]] = None, now: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Move one opportunity to `to_state` if it is in `expect_states` (see the module docstring). `extra` = more fields to
    set in the same write (never _id, state, version, state_history, is_open, consolidation_key). ValueError for an
    unknown state (a programming error)."""
    if to_state not in C.OPP_STATES:
        raise ValueError(f"unknown opportunity state {to_state!r}")
    expect = list(expect_states)
    cur = await get(db, opp_id)
    if cur is None or cur.get("state") not in expect:
        return None
    if to_state not in ALLOWED.get(cur["state"], ()):
        logger.warning("spt opportunities: %s → %s is not in the state machine (%s)", cur["state"], to_state, opp_id)
        return None
    at = now or now_iso()
    version = int(cur.get("version") or 0)
    fields = {k: v for k, v in (extra or {}).items() if k not in PROTECTED}
    fields.update(state=to_state, state_reason=reason, is_open=to_state in C.OPP_OPEN_STATES, updated_at=at)
    res = await db[COLL].update_one(
        {"_id": opp_id, "state": cur["state"], "version": version},
        {"$set": fields, "$inc": {"version": 1},
         "$push": {"state_history": {"from": cur["state"], "to": to_state, "reason": reason, "at": at,
                                     "version": version + 1}}})
    if getattr(res, "matched_count", 0) != 1:
        return None
    doc = await get(db, opp_id)
    ev = STATE_EVENTS.get(to_state)
    if ev and doc is not None:
        await events.emit(db, ev, idempotency_key=f"opp:{opp_id}:{to_state.lower()}", source_service=SOURCE, occurred_at=at,
                          correlation_id=opp_id, instrument_id=doc.get("symbol"),
                          payload={"opportunity_id": opp_id, "symbol": doc.get("symbol"), "direction": doc.get("direction"),
                                   "horizon": doc.get("horizon"), "from": cur["state"], "to": to_state, "reason": reason,
                                   "version": version + 1,
                                   "opportunity_score": doc.get("opportunity_score")})
    return doc


# ── slice A's own writes (consolidate.py) ─────────────────────────────────────────────────────────────────────────────

async def insert_new(db, doc: Dict[str, Any]) -> bool:
    """True when stored; False when an open opportunity with the same consolidation_key exists (the unique index)."""
    await ensure_indexes(db)
    try:
        await db[COLL].insert_one(doc)
        return True
    except Exception as e:  # noqa: BLE001 — only a duplicate key is expected; anything else is re-raised
        if type(e).__name__ == "DuplicateKeyError" or "duplicate key" in str(e).lower():
            return False
        raise


async def candidates(db, symbol: str, *, direction: Optional[str] = None, horizon: Optional[str] = None,
                     states: Sequence[str] = C.OPP_OPEN_STATES) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"symbol": symbol, "state": {"$in": list(states)}}
    if direction:
        q["direction"] = direction
    if horizon:
        q["horizon"] = horizon
    return await db[COLL].find(q).sort("first_seen_at", 1).to_list(length=None)


async def attached_ids(db, signal_ids: Sequence[str]) -> set:
    """The ids of `signal_ids` already in some opportunity's `signals`."""
    want = set(signal_ids)
    out: set = set()
    ids = list(want)
    for i in range(0, len(ids), 500):
        docs = await db[COLL].find({"signals.signal_id": {"$in": ids[i:i + 500]}}).to_list(length=None)
        for d in docs:
            out.update(s.get("signal_id") for s in d.get("signals") or [] if s.get("signal_id") in want)
    return out
