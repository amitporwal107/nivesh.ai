"""The scan loop's hand-off to SPT ingest, and the day catch-up (Workflow §4.2 steps 8–9, §20.3).

`after_store(day, kind, records, store)` is called by services/scan_builder/signals.record / record_strong right after they
stored NEW marks in Redis. It never blocks and never raises into the scan loop: it only schedules `ingest` as an asyncio task
whose failure is logged (with its type) by the task's done-callback. The day's scores doc is read from the same signal store
for the list marks' scanner_score (ingest._score_from_doc).

`catch_up(db, day)` reads the day's whole list index and strong index from the signal store and ingests every mark not yet
stored (idempotent: a stored mark is a no-op). The SPT loop runs it every round, so a hook that did not run (another
worker, a restart, the flag off on that worker, Redis briefly unreadable) loses nothing while Redis keeps the day (3 days).

A list mark's ingest waits SPT_INGEST_DELAY_S (default 20 s) first: the scan round that recorded the mark saves the day's
scores (with this stock, computed at the detection time) only after recording, so reading them at once would store a null
score for every stock new to the lists. A strong signal carries its own frozen score and is ingested at once.

Flag SPT_INGEST_ENABLED: on where APP_ENV=staging; "0" turns it off; "1" turns it on elsewhere.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set

from . import ingest, store as sig_store

logger = logging.getLogger(__name__)

DEFAULT_DELAY_S = 20.0
_tasks: Set["asyncio.Task[Any]"] = set()
_known: Dict[str, Set[str]] = {}            # this process: day -> signal ids known to be stored (catch-up skips them)


def enabled(env: Optional[Dict[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    flag = (env.get("SPT_INGEST_ENABLED") or "").strip()
    if flag == "0":
        return False
    return flag == "1" or (env.get("APP_ENV") or "").strip().lower() == "staging"


def delay_s(env: Optional[Dict[str, str]] = None) -> float:
    raw = (os.environ if env is None else env).get("SPT_INGEST_DELAY_S")
    try:
        v = float(raw) if raw not in (None, "") else DEFAULT_DELAY_S
    except ValueError:
        return DEFAULT_DELAY_S
    return min(max(v, 0.0), 120.0)


def _db():
    from deps import db                      # imported late: tests and scripts give their own db
    return db


def _done(task: "asyncio.Task[Any]") -> None:
    _tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("spt ingest: a scheduled ingest failed (%s)", type(exc).__name__)


async def _run(day: str, kind: str, records: List[Dict[str, Any]], scan_store: Any, db: Any,
               delay: float) -> Dict[str, Any]:
    from services.scan_builder import signals as SIG
    scores_doc = None
    if kind == "list":
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            scores_doc = await SIG.load_scores(day, store=scan_store)
        except Exception as e:  # noqa: BLE001 — the marks are stored without a score (null + note), never with a guess
            logger.warning("spt ingest: the day's scores could not be read (%s)", type(e).__name__)
    db = db if db is not None else _db()
    counts = await ingest.ingest(db, day=day, marks=records if kind == "list" else (),
                                 strong=records if kind == "strong" else (), scores_doc=scores_doc, via="hook")
    return counts


def after_store(day: str, kind: str, records: Sequence[Dict[str, Any]], scan_store: Any = None, *, db: Any = None,
                env: Optional[Dict[str, str]] = None) -> Optional["asyncio.Task[Any]"]:
    """Schedule the ingest of `records` (kind "list" or "strong") stored for IST `day`. Returns the task, or None when the
    flag is off, there is nothing to ingest or there is no running loop. Never raises."""
    try:
        if not records or not enabled(env):
            return None
        loop = asyncio.get_running_loop()
        task = loop.create_task(_run(day, kind, [dict(r) for r in records], scan_store, db, delay_s(env)))
        _tasks.add(task)
        task.add_done_callback(_done)
        return task
    except Exception as e:  # noqa: BLE001 — the scan loop must never fail because of SPT; the catch-up ingests it later
        logger.warning("spt ingest: not scheduled (%s)", type(e).__name__)
        return None


def _parse(raw: Sequence[Any], what: str) -> List[Dict[str, Any]]:
    out = []
    for v in raw:
        try:
            rec = json.loads(v) if isinstance(v, (str, bytes)) else v
        except ValueError:
            logger.warning("spt catch-up: an unreadable %s was skipped", what)
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


async def read_day(day: str, *, scan_store: Any = None) -> Dict[str, Any]:
    """{marks, strong, scores_doc} of IST `day` from the signal store. Raises when the list index cannot be read."""
    from services.scan_builder import signals as SIG
    s = scan_store or SIG.get_store()
    marks = await SIG.day_marks(day, store=s)
    strong_index, _ = SIG._strong_keys(day)          # the strong index key (signals.py's own helper)
    strong = _parse(await s.read(strong_index, SIG.MAX_STRONG), "strong signal")
    try:
        scores_doc = await SIG.load_scores(day, store=s)
    except Exception as e:  # noqa: BLE001 — marks go in without a score
        logger.warning("spt catch-up: the day's scores could not be read (%s)", type(e).__name__)
        scores_doc = None
    return {"marks": marks, "strong": strong, "scores_doc": scores_doc}


async def catch_up(db, day: str, *, scan_store: Any = None, now: Optional[datetime] = None,
                   via: str = "catch_up") -> Dict[str, Any]:
    """Ingest every mark and strong signal of `day` not yet stored. Returns ingest counts plus {"read": n}."""
    now = now or datetime.now(timezone.utc)
    got = await read_day(day, scan_store=scan_store)
    ids = ([ingest.list_signal_id(day, str(m.get("widget_id")), str(m.get("symbol"))) for m in got["marks"]]
           + [ingest.strong_signal_id(day, str(r.get("symbol"))) for r in got["strong"]])
    known = _known.setdefault(day, set())
    for d in list(_known):
        if d < day and len(_known) > 4:
            del _known[d]
    unknown = [i for i in ids if i not in known]
    if unknown:
        known.update(await sig_store.existing_ids(db, unknown))
    counts = await ingest.ingest(db, day=day, marks=got["marks"], strong=got["strong"], scores_doc=got["scores_doc"],
                                 now=now, via=via, skip_ids=known)
    known.update(ids)          # stored now, or a duplicate, or counted as an error (retried after a restart)
    if counts["errors"]:
        _known[day] = known - set(ids)          # retry the whole day's unknowns next round rather than lose one
    counts["read"] = len(ids)
    return counts
