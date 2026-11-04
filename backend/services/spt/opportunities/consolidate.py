"""Consolidation `spt-consolidate-v1` (constants.CONSOLIDATION_VERSION): normalized scanner events → market-wide
opportunities (PRD §6.3–§6.4; Workflow §5.2 steps 5–9, §5.4; DESIGN.md §4).

Rules:
    key          consolidation_key = SYMBOL|direction|horizon|<window start day>. The window starts at the opportunity's
                 first signal: intraday = that IST day (until its close); positional = SPT_POSITIONAL_WINDOW_SESSIONS
                 (default 5) weekday sessions after it (clock.window_until).
    attach       a normalized event joins the opportunity of the same symbol, direction and horizon whose window covers it:
                 its IST day is at most N sessions before the opportunity's first day (an out-of-order arrival) and its
                 detection time is not after window_until. Candidates are the open states plus REJECTED (a rejected
                 opportunity keeps the signals of its own window, so an illiquid stock does not open a new opportunity on
                 every list mark); EXPIRED never takes a signal. Otherwise a new opportunity is created (state CREATED).
    attribution  every attached signal keeps signal_id, scanner_id, scanner_name, detected_at, detected_price,
                 scanner_score, score_version, category and family (PRD §6.4: the original ids and timestamps are
                 preserved; different families stay identifiable). Scores are NEVER added together (Workflow §5.3).
    strong       a strong signal attaches its frozen scan-plan-v3 plan as `strong` (the first one in the window; a later
                 strong signal is attached as a signal and does not replace the plan the opportunity was judged on).
    conflicts    an event whose symbol has an open opportunity in the OTHER direction (any horizon) is evidence against it:
                 each side's opportunity gets the other side's signals in `conflicts` [{signal_id, scanner_id, direction,
                 detected_at, opportunity_id}], and SIGNAL_CONFLICT_DETECTED is emitted once per event (Workflow §5.4:
                 opposing signals are retained, never discarded).
    idempotent   an event already in an opportunity is skipped; attaching uses `signals.signal_id $ne` in the filter, so a
                 replay or a second pass never doubles a signal; creating relies on the open-key unique index, and a lost
                 race attaches to the winner.
    late         an event whose expiry_at has passed is not consolidated (it would only open an expired opportunity).

Events: OPPORTUNITY_CREATED (`opp:<id>:created`), OPPORTUNITY_UPDATED per attached signal (`opp:<id>:signal:<signal_id>`),
SIGNAL_CONFLICT_DETECTED (`conflict:<signal_id>`).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set

from .. import constants as C
from .. import events
from ..signals import clock, normalize
from ..signals import store as sig_store
from . import store

logger = logging.getLogger(__name__)

SOURCE = "spt-opportunity-engine"
ATTACH_STATES = tuple(C.OPP_OPEN_STATES) + (C.OPP_REJECTED,)
SIGNAL_FIELDS = ("signal_id", "scanner_id", "scanner_name", "detected_at", "detected_price", "scanner_score", "score_version",
                 "category", "family", "kind", "timeframe")
PLAN_FIELDS = ("rules", "entry", "stop_loss", "target_1", "target_2", "risk_per_share", "rr_1", "rr_2", "atr", "sma20",
               "trend_exit", "plan_ok", "plan_note")
MAX_RETRIES = 4

_handled: Dict[str, Set[str]] = {}       # this process: day -> signal ids placed (or late) already: not read again


def consolidation_key(symbol: str, direction: str, horizon: str, window_day: str) -> str:
    return f"{symbol}|{direction}|{horizon}|{window_day}"


def signal_entry(ev: Dict[str, Any], at: str) -> Dict[str, Any]:
    return {**{k: ev.get(k) for k in SIGNAL_FIELDS}, "attached_at": at}


def strong_block(ev: Dict[str, Any]) -> Dict[str, Any]:
    raw = ev.get("supporting_metrics") or {}
    return {"signal_id": ev["signal_id"], "first_strong": raw.get("first_strong"), "detected_at": ev.get("detected_at"),
            "score_at": raw.get("score_at"), "parts_at": raw.get("parts_at"), "reasons_at": raw.get("reasons_at"),
            "penalties_at": raw.get("penalties_at"), "lists_at": raw.get("lists_at"),
            "plan": {k: raw.get(k) for k in PLAN_FIELDS}}


def _covers(opp: Dict[str, Any], ev: Dict[str, Any], sessions: int) -> bool:
    det = clock.parse_ts(ev.get("detected_at"))
    until = clock.parse_ts(opp.get("window_until"))
    if det is None or until is None or det > until:
        return False
    first_day = datetime.fromisoformat(opp["day"]).date()
    ev_day = datetime.fromisoformat(ev["day"]).date()
    if opp.get("horizon") == normalize.INTRADAY:
        return ev_day == first_day
    return clock.sessions_between(ev_day, first_day) <= sessions


def new_doc(ev: Dict[str, Any], *, sessions: int, at: str) -> Dict[str, Any]:
    day = ev["day"]
    until = clock.utc_iso(clock.window_until(datetime.fromisoformat(day).date(), ev["horizon"], sessions))
    is_strong = ev.get("kind") == "strong"
    oid = str(uuid.uuid4())
    return {
        "_id": oid, "opportunity_id": oid,
        "consolidation_key": consolidation_key(ev["symbol"], ev["direction"], ev["horizon"], day),
        "symbol": ev["symbol"], "exchange": "NSE", "direction": ev["direction"], "bias": ev.get("bias"),
        "family": ev.get("family"), "category": ev.get("category"), "horizon": ev["horizon"], "day": day,
        "first_seen_at": ev["detected_at"], "last_signal_at": ev["detected_at"], "window_until": until, "expires_at": until,
        "window_sessions": sessions if ev["horizon"] == normalize.POSITIONAL else 0,
        "state": C.OPP_CREATED, "state_reason": "first_signal", "is_open": True, "version": 1,
        "signals": [signal_entry(ev, at)], "signal_count": 1,
        "families": [ev.get("family")] if ev.get("family") else [],
        "categories": [ev.get("category")] if ev.get("category") else [],
        "conflicts": [], "strong": strong_block(ev) if is_strong else None,
        "validation": None, "opportunity_score": None, "evidence_version": 1, "validated_evidence_version": 0,
        "revalidate_at": None,
        "state_history": [{"from": None, "to": C.OPP_CREATED, "reason": "first_signal", "at": at, "version": 1}],
        "consolidation_version": C.CONSOLIDATION_VERSION, "created_at": at, "updated_at": at,
    }


async def _attach(db, opp: Dict[str, Any], ev: Dict[str, Any], at: str) -> bool:
    """Add `ev` to `opp` (idempotent). True when this call attached it."""
    upd: Dict[str, Any] = {
        "$push": {"signals": signal_entry(ev, at)},
        "$inc": {"signal_count": 1, "evidence_version": 1, "version": 1},
        "$set": {"updated_at": at},
        "$max": {"last_signal_at": ev["detected_at"]},
    }
    add: Dict[str, Any] = {}
    if ev.get("family"):
        add["families"] = ev["family"]
    if ev.get("category"):
        add["categories"] = ev["category"]
    if add:
        upd["$addToSet"] = add
    if ev.get("kind") == "strong" and not opp.get("strong"):
        upd["$set"]["strong"] = strong_block(ev)
    res = await db[store.COLL].update_one(
        {"_id": opp["_id"], "version": opp.get("version"), "signals.signal_id": {"$ne": ev["signal_id"]}}, upd)
    if getattr(res, "matched_count", 0) != 1:
        return False
    await events.emit(db, "OPPORTUNITY_UPDATED", idempotency_key=f"opp:{opp['_id']}:signal:{ev['signal_id']}",
                      source_service=SOURCE, occurred_at=at, correlation_id=opp["_id"], instrument_id=opp["symbol"],
                      payload={"opportunity_id": opp["_id"], "change": "signal_attached", "signal_id": ev["signal_id"],
                               "scanner_id": ev.get("scanner_id"), "family": ev.get("family"),
                               "strong_attached": "strong" in upd["$set"]})
    return True


async def _conflicts(db, opp_id: str, ev: Dict[str, Any], at: str) -> List[str]:
    """Record the conflict between `ev` (now in `opp_id`) and the open opportunities of the other direction. Returns their ids."""
    other = normalize.SHORT if ev["direction"] == normalize.LONG else normalize.LONG
    opps = await store.candidates(db, ev["symbol"], direction=other)
    if not opps:
        return []
    mine = {"signal_id": ev["signal_id"], "scanner_id": ev.get("scanner_id"), "direction": ev["direction"],
            "detected_at": ev.get("detected_at"), "opportunity_id": opp_id}
    theirs: List[Dict[str, Any]] = []
    for o in opps:
        await db[store.COLL].update_one(
            {"_id": o["_id"], "conflicts.signal_id": {"$ne": ev["signal_id"]}},
            {"$push": {"conflicts": mine}, "$inc": {"evidence_version": 1}, "$set": {"updated_at": at}})
        theirs.extend({"signal_id": s.get("signal_id"), "scanner_id": s.get("scanner_id"), "direction": other,
                       "detected_at": s.get("detected_at"), "opportunity_id": o["_id"]} for s in o.get("signals") or [])
    target = await store.get(db, opp_id)
    have = {c.get("signal_id") for c in (target or {}).get("conflicts") or []}
    new = [c for c in theirs if c["signal_id"] not in have]
    if new:
        await db[store.COLL].update_one({"_id": opp_id},
                                        {"$push": {"conflicts": {"$each": new}}, "$inc": {"evidence_version": 1},
                                         "$set": {"updated_at": at}})
    ids = [o["_id"] for o in opps]
    await events.emit(db, "SIGNAL_CONFLICT_DETECTED", idempotency_key=f"conflict:{ev['signal_id']}", source_service=SOURCE,
                      occurred_at=at, correlation_id=opp_id, instrument_id=ev["symbol"],
                      payload={"signal_id": ev["signal_id"], "symbol": ev["symbol"], "direction": ev["direction"],
                               "opportunity_id": opp_id, "against_opportunities": ids,
                               "against_signals": [c["signal_id"] for c in theirs]})
    return ids


async def place(db, ev: Dict[str, Any], *, now: Optional[datetime] = None,
                sessions: Optional[int] = None) -> Dict[str, Any]:
    """Attach one normalized event to its opportunity, or create one. Returns {action, opportunity_id, conflicts}:
    action ∈ attached | created | already | late | skipped | failed."""
    now = now or datetime.now(timezone.utc)
    sessions = sessions or clock.window_sessions()
    at = clock.utc_iso(now)
    if ev.get("status") != "normalized":
        return {"action": "skipped", "opportunity_id": None, "conflicts": []}
    exp = clock.parse_ts(ev.get("expiry_at"))
    if exp is not None and now > exp:
        return {"action": "late", "opportunity_id": None, "conflicts": []}
    for _ in range(MAX_RETRIES):
        cands = [o for o in await store.candidates(db, ev["symbol"], direction=ev["direction"], horizon=ev["horizon"],
                                                   states=ATTACH_STATES) if _covers(o, ev, sessions)]
        for o in cands:
            if any(s.get("signal_id") == ev["signal_id"] for s in o.get("signals") or []):
                return {"action": "already", "opportunity_id": o["_id"], "conflicts": []}
        if cands:
            target = max(cands, key=lambda o: o.get("first_seen_at") or "")
            if await _attach(db, target, ev, at):
                return {"action": "attached", "opportunity_id": target["_id"],
                        "conflicts": await _conflicts(db, target["_id"], ev, at)}
            continue                                   # changed under us (version): read again
        doc = new_doc(ev, sessions=sessions, at=at)
        if await store.insert_new(db, doc):
            await events.emit(db, "OPPORTUNITY_CREATED", idempotency_key=f"opp:{doc['_id']}:created", source_service=SOURCE,
                              occurred_at=at, correlation_id=doc["_id"], instrument_id=doc["symbol"],
                              payload={"opportunity_id": doc["_id"], "consolidation_key": doc["consolidation_key"],
                                       "symbol": doc["symbol"], "direction": doc["direction"], "horizon": doc["horizon"],
                                       "first_signal_id": ev["signal_id"], "window_until": doc["window_until"],
                                       "consolidation_version": C.CONSOLIDATION_VERSION})
            return {"action": "created", "opportunity_id": doc["_id"], "conflicts": await _conflicts(db, doc["_id"], ev, at)}
        # an open opportunity with this key appeared since the read (another writer): attach to it on the next pass
    logger.warning("spt consolidate: %s could not be placed after %d tries", ev.get("signal_id"), MAX_RETRIES)
    return {"action": "failed", "opportunity_id": None, "conflicts": []}


async def consolidate(db, *, days: Sequence[str], now: Optional[datetime] = None, sessions: Optional[int] = None,
                      received_since: Optional[str] = None) -> Dict[str, int]:
    """Place every normalized event of IST `days` that is in no opportunity yet, oldest detection first. Returns counts.
    `received_since` (UTC ISO): read only events received from then on (the loop's incremental pass; None = all)."""
    now = now or datetime.now(timezone.utc)
    counts = {"events": 0, "created": 0, "attached": 0, "already": 0, "late": 0, "skipped": 0, "failed": 0,
              "conflicts": 0}
    evs = await sig_store.list_signals(db, days=list(days), status="normalized", limit=0, newest_first=False,
                                       received_since=received_since)
    counts["events"] = len(evs)
    for d in list(_handled):
        if d not in days:
            del _handled[d]
    todo = [e for e in evs if e["signal_id"] not in _handled.get(e["day"], set())]
    if todo:
        known = await store.attached_ids(db, [e["signal_id"] for e in todo])
        for e in todo:
            if e["signal_id"] in known:
                _handled.setdefault(e["day"], set()).add(e["signal_id"])
        todo = [e for e in todo if e["signal_id"] not in known]
    counts["already"] = len(evs) - len(todo)
    for ev in todo:
        try:
            r = await place(db, ev, now=now, sessions=sessions)
        except Exception as e:  # noqa: BLE001 — one event failing never stops the rest; the next round retries it
            logger.warning("spt consolidate: %s failed (%s)", ev.get("signal_id"), type(e).__name__)
            counts["failed"] += 1
            continue
        counts[r["action"]] += 1
        counts["conflicts"] += 1 if r["conflicts"] else 0
        if r["action"] in ("attached", "created", "already", "late"):
            _handled.setdefault(ev["day"], set()).add(ev["signal_id"])
    return counts
