"""Scheduled-job runs: a heartbeat per run, a lease so two runs cannot overlap, and a health reading.

WHY THIS EXISTS
The evening desk check (scripts/check_desk_alerts.py) closes paper trades at their stop or target. When it does not
run, or runs and fails, nothing says so: the cron log is on the VM and nobody reads it, so the first sign is a trade
left open past its stop. A run that is recorded can be checked; a run that is missing can be noticed.

Store (MongoDB):
    job_runs    one document per run (not per dry run): {_id: run_id, job, started_at, finished_at, status,
                exit_code, session, counts, error}. Written as "running" when the run starts and finished when it
                ends, also when it fails. Never deleted by this module.
    job_locks   one document per job: {_id: job, run_id, acquired_at, expires_at}. A run takes the lease by
                inserting it, or by taking over an EXPIRED lease with a compare-and-set on the previous run id; it
                lets go by expiring it. The lease expires on its own, so a run that died does not block the next.

Health. A job is MISSED when no run has been recorded since its latest scheduled slot, once that slot is more than
`grace` old. The slot comes from the schedule below, kept in step with the cron file (a test compares them), so a
weekend or a public holiday is not a miss: the cron still runs on a weekday holiday and records "skipped_no_session".
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

RUNS = "job_runs"
LOCKS = "job_locks"

IST = timezone(timedelta(hours=5, minutes=30))

#: job → its schedule. KEEP IN STEP with the cron file named here (tests/test_desk_exit_job.py parses it).
SCHEDULES: Dict[str, Dict[str, Any]] = {
    "check_desk_alerts": {
        "cron_file": "deploy/nivesh-staging/desk-alerts.cron",
        "weekdays": (0, 1, 2, 3, 4),                 # Mon–Fri
        "slots": (time(20, 45), time(22, 45)),       # IST; the second is the retry
        "grace": timedelta(minutes=60),
        "lease": timedelta(minutes=60),
        "text": "Mon–Fri 20:45 IST, retry 22:45 IST",
    },
    # The AI scanner (scripts/run_positional_engine.py) writes its own records under this job name since #355
    # (services/positional_engine/scan_meta.py: status, session, counts with the engine version, price basis and
    # data-quality summary). A run takes about half a minute; the 21:45 run is the retry for a late bhavcopy.
    "positional_engine": {
        "cron_file": "deploy/nivesh-staging/positional-engine.cron",
        "weekdays": (0, 1, 2, 3, 4),
        "slots": (time(19, 45), time(21, 45)),
        "grace": timedelta(minutes=60),
        "lease": timedelta(minutes=60),
        "text": "Mon–Fri 19:45 IST, retry 21:45 IST",
    },
}

# Final statuses a run can record. "running" is the only non-final one.
OK, PARTIAL, FAILED = "ok", "partial", "failed"
SKIPPED_NO_BARS, SKIPPED_NO_SESSION, SKIPPED_LOCKED, SKIPPED_DONE = (
    "skipped_no_bars", "skipped_no_session", "skipped_locked", "skipped_done")
RUNNING = "running"
# The scanner's own outcomes (services/positional_engine/scan_meta.py): scored but next year's NSE holiday list is not
# loaded (an alert), and a refusal to score (the calendar or the factors could not be read, or the bars are dirty).
CALENDAR_NOT_READY = "calendar_not_ready"
REFUSED_PREFIX = "refused_"

#: What the read path returns of a run: an allow-list, so nothing else stored on the document leaks out.
PUBLIC_FIELDS = ("_id", "job", "started_at", "finished_at", "status", "exit_code", "session", "counts", "error",
                 "dry_run")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _parse(stamp: Any) -> Optional[datetime]:
    if not stamp:
        return None
    try:
        moment = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


# ── the lease ────────────────────────────────────────────────────────────────
async def acquire(db, job: str, run_id: str, *, now: datetime, lease: timedelta) -> bool:
    """Take the job's lease for `run_id`. False when another run holds an unexpired lease.

    Two runs racing for a FREE lease: both insert `_id: job`, Mongo's unique `_id` lets one through. Two runs racing
    for an EXPIRED lease: both read it, both update with the old run id in the filter, one matches."""
    from pymongo.errors import DuplicateKeyError

    doc = {"_id": job, "run_id": run_id, "acquired_at": _iso(now), "expires_at": _iso(now + lease)}
    try:
        await db[LOCKS].insert_one(doc)
        return True
    except DuplicateKeyError:
        pass
    held = await db[LOCKS].find_one({"_id": job})
    if held is None:                 # removed by hand between the two calls: treat as contended, the next run retries
        logger.warning("job_runs: the %s lease vanished while it was being taken; not running", job)
        return False
    expires = _parse(held.get("expires_at"))
    if expires is not None and expires > now:
        logger.info("job_runs: %s is held by run %s until %s", job, held.get("run_id"), held.get("expires_at"))
        return False
    res = await db[LOCKS].update_one({"_id": job, "run_id": held.get("run_id")},
                                     {"$set": {"run_id": run_id, "acquired_at": doc["acquired_at"],
                                               "expires_at": doc["expires_at"]}})
    return bool(res.matched_count)


async def release(db, job: str, run_id: str, *, now: datetime) -> None:
    """Let go of the lease by expiring it (only if this run still holds it). The document stays."""
    await db[LOCKS].update_one({"_id": job, "run_id": run_id},
                               {"$set": {"expires_at": _iso(now), "released_at": _iso(now)}})


# ── the heartbeat ────────────────────────────────────────────────────────────
async def start(db, job: str, run_id: str, *, now: datetime, **fields: Any) -> None:
    await db[RUNS].insert_one({"_id": run_id, "job": job, "started_at": _iso(now), "finished_at": None,
                               "status": RUNNING, "exit_code": None, "error": None, **fields})


async def finish(db, run_id: str, *, now: datetime, status: str, exit_code: int,
                 counts: Optional[Dict[str, Any]] = None, error: Optional[str] = None, **fields: Any) -> None:
    await db[RUNS].update_one({"_id": run_id}, {"$set": {"finished_at": _iso(now), "status": status,
                                                          "exit_code": exit_code, "counts": counts, "error": error,
                                                          **fields}})


async def latest(db, job: str, **match: Any) -> Optional[Dict[str, Any]]:
    """The newest run of `job` (optionally also matching equality fields), or None."""
    rows = await db[RUNS].find({"job": job, **match}).sort("started_at", -1).to_list(1)
    return rows[0] if rows else None


def public(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if doc is None:
        return None
    out = {k: doc.get(k) for k in PUBLIC_FIELDS if k in doc}
    out["run_id"] = out.pop("_id", None)
    return out


# ── health ───────────────────────────────────────────────────────────────────
def last_slot(job: str, now: datetime) -> datetime:
    """The latest scheduled slot of `job` that is at least `grace` old at `now` (UTC-aware)."""
    sched = SCHEDULES[job]
    local = now.astimezone(IST)
    for back in range(0, 15):
        day = local.date() - timedelta(days=back)
        if day.weekday() not in sched["weekdays"]:
            continue
        for at in sorted(sched["slots"], reverse=True):
            slot = datetime.combine(day, at, tzinfo=IST)
            if slot + sched["grace"] <= local:
                return slot.astimezone(timezone.utc)
    raise ValueError(f"{job}: no scheduled slot in the last two weeks")    # a schedule with no weekdays


def health(job: str, last: Optional[Dict[str, Any]], last_ok: Optional[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    """{state, healthy, reason, expected_since, age_hours} from the newest run and the newest successful run.

    state: never_run | running | failed | partial | no_data | missed | ok | skipped | calendar_not_ready | refused
      failed    the newest run failed, or is still "running" after its lease (it died without finishing)
      partial   it ran, but some prices or sources could not be read: those trades / alerts were not checked
      no_data   it ran but the session's bars were not in the data platform, so nothing was checked
      missed    nothing was recorded since the latest scheduled slot (older than the grace period)
      calendar_not_ready  (the scanner) it scored, but next year's NSE holiday list is not loaded: an alert
      refused   (the scanner) it refused to score: the calendar or the adjustment factors could not be read, or the
                bars failed the integrity check (fail-closed, owner decision 2026-10-27)
    """
    sched = SCHEDULES[job]
    since = last_slot(job, now)
    base = {"schedule": sched["text"], "expected_since": _iso(since), "grace_minutes": int(sched["grace"].total_seconds() // 60),
            "last_success_at": (last_ok or {}).get("started_at")}
    if last is None:
        return {**base, "state": "never_run", "healthy": False, "reason": "No run of this job has been recorded.",
                "age_hours": None}
    started = _parse(last.get("started_at"))
    age = round((now - started).total_seconds() / 3600, 2) if started else None
    base["age_hours"] = age
    status = last.get("status")
    if status == RUNNING:
        if started is not None and now - started <= sched["lease"]:
            return {**base, "state": "running", "healthy": True, "reason": "A run is in progress."}
        return {**base, "state": "failed", "healthy": False,
                "reason": "The newest run started but never recorded a finish: it died or was killed."}
    if started is None or started < since - timedelta(minutes=5):
        return {**base, "state": "missed", "healthy": False,
                "reason": f"No run recorded since the {since.astimezone(IST).strftime('%a %d %b %H:%M')} IST slot."}
    if status == FAILED:
        return {**base, "state": "failed", "healthy": False, "reason": last.get("error") or "The newest run failed."}
    if status == PARTIAL:
        return {**base, "state": "partial", "healthy": False,
                "reason": "The newest run could not read some prices or sources; those trades or alerts were not checked."}
    if status == SKIPPED_NO_BARS:
        return {**base, "state": "no_data", "healthy": False,
                "reason": f"The {last.get('session')} session's bars were not in the data platform; nothing was checked."}
    if status == OK or status == SKIPPED_DONE:
        return {**base, "state": "ok", "healthy": True, "reason": None}
    if status == CALENDAR_NOT_READY:
        return {**base, "state": "calendar_not_ready", "healthy": False,
                "reason": last.get("error") or "The run scored, but next year's NSE holiday calendar is not loaded."}
    if isinstance(status, str) and status.startswith(REFUSED_PREFIX):
        return {**base, "state": "refused", "healthy": False,
                "reason": last.get("error") or f"The newest run refused to score ({status})."}
    return {**base, "state": "skipped", "healthy": status in (SKIPPED_NO_SESSION, SKIPPED_LOCKED),
            "reason": f"The newest run was skipped ({status})."}


async def read_health(db, job: str, now: datetime) -> Dict[str, Any]:
    last = await latest(db, job)
    last_ok = await latest(db, job, status=OK)
    return {"job": job, **health(job, last, last_ok, now), "last_run": public(last), "last_success": public(last_ok)}
