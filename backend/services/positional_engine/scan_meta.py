"""The AI scanner's run record, and the basis it publishes with its results.

Run record (owner decision 2026-10-27: failures visible and alertable). One document per scanner run in Mongo
`job_runs`, in the shape of the scheduled-job heartbeat of services/job_runs.py, which reads these records by job name
(job_runs.SCHEDULES["positional_engine"]; admin route GET /api/admin/risk/jobs/positional_engine):

    {_id: run_id, job: "positional_engine", started_at, finished_at, status, exit_code, session, counts, error,
     dry_run, calendar_ready, calendar_missing_year}

`counts` carries what the results are published with: engine version, price-basis counts, the exceptions (symbols on
raw prices, symbols not scored after a history cut), the data-quality summary and the calendar readiness. Calendar
readiness is also inside `counts` and `error`, because the heartbeat's read path only returns its allow-listed fields.

Basis (`scan_basis` on GET /api/positional/picks and /watchlist): for the date served, the engine version and price
basis of the stored rows themselves, and the exceptions and data-quality status of the newest run record for that date.
A row without a recorded price basis was computed before engine v1.1, on raw prices, and is reported as raw.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

JOB = "positional_engine"
RUNS = "job_runs"

# Final statuses of a scanner run (the heartbeat's vocabulary where it has one).
OK, FAILED = "ok", "failed"
CALENDAR_NOT_READY = "calendar_not_ready"           # scored, but next year's NSE holiday list is not loaded: ALERT
SKIPPED = {"not_a_session": "skipped_no_session", "no_bars": "skipped_no_bars", "already_scored": "skipped_done",
           "calendar_unavailable": "refused_calendar_unavailable", "dirty_bars": "refused_dirty_bars"}
PUBLISHED = (OK, CALENDAR_NOT_READY)                 # runs whose counts describe the stored results

ADJUSTED, RAW = "corp_action_adjusted", "raw"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def start(db, run_id: str, *, session: str, now: datetime) -> None:
    await db[RUNS].insert_one({"_id": run_id, "job": JOB, "started_at": now.isoformat(), "finished_at": None,
                               "status": "running", "exit_code": None, "session": session, "counts": None,
                               "error": None, "dry_run": False})


async def finish(db, run_id: str, *, now: datetime, status: str, exit_code: int, counts: Dict[str, Any],
                 error: Optional[str], **fields: Any) -> None:
    await db[RUNS].update_one({"_id": run_id}, {"$set": {"finished_at": now.isoformat(), "status": status,
                                                          "exit_code": exit_code, "counts": counts, "error": error,
                                                          **fields}})


async def latest_for_session(db, session: str) -> Optional[Dict[str, Any]]:
    """The newest finished run that scored `session` (ISO date), or None."""
    rows = await db[RUNS].find({"job": JOB, "session": session, "status": {"$in": list(PUBLISHED)}},
                               {"counts": 1, "finished_at": 1, "status": 1}).sort("finished_at", -1).to_list(1)
    return rows[0] if rows else None


def price_basis_label(adjusted: int, legacy: int) -> str:
    """corp_action_adjusted when the day's rows were scored on adjusted bars (v1.1), raw when none were."""
    if adjusted and not legacy:
        return ADJUSTED
    return RAW if not adjusted else "mixed"


def data_quality(record: Optional[Dict[str, Any]], unreadable: Optional[str]) -> Dict[str, Any]:
    q = ((record or {}).get("counts") or {}).get("quality") or {}
    if q.get("ok"):
        return {"status": "clean" if q.get("clean") else "warnings", "warnings": len(q.get("problems") or []),
                "problems": q.get("problems") or [], "checked_at": record.get("finished_at")}
    if unreadable:
        return {"status": "not_checked", "warnings": None, "problems": [], "reason": f"run record unreadable ({unreadable})"}
    if q:
        return {"status": "not_checked", "warnings": None, "problems": [], "reason": q.get("reason") or q.get("error")}
    return {"status": "not_checked", "warnings": None, "problems": [],
            "reason": "no data-quality check is recorded for this date"}


async def basis_for_date(pool, db, d: date) -> Dict[str, Any]:
    """What the results of `d` were computed on. Reads only."""
    async with pool.acquire() as conn:
        groups = await conn.fetch(
            "SELECT engine_version v, components->'price_adjustment'->>'price_basis' b, count(*) n"
            " FROM stock_technical_features WHERE as_of_date = $1 GROUP BY 1, 2", d)
        raw_rows = await conn.fetch(
            "SELECT nse_symbol FROM stock_technical_features WHERE as_of_date = $1"
            " AND components->'price_adjustment'->>'price_basis' = 'raw_no_factors' ORDER BY 1", d)
        cut_rows = await conn.fetch(
            "SELECT nse_symbol, components->'price_adjustment'->>'break_truncated_at' b FROM stock_technical_features"
            " WHERE as_of_date = $1 AND components->'price_adjustment'->>'break_truncated_at' IS NOT NULL ORDER BY 1", d)
    by_basis: Counter = Counter()
    versions = set()
    for g in groups:
        by_basis[g["b"] or "none"] += g["n"]
        if g["v"]:
            versions.add(g["v"])
    adjusted = by_basis["warehouse_adjusted"]
    legacy = by_basis["none"]
    record, unreadable = None, None
    try:
        record = await latest_for_session(db, d.isoformat())
    except Exception as e:  # noqa: BLE001 — reported in the payload and the log, never as "clean"
        unreadable = type(e).__name__
        logger.warning("scan basis %s: run record unreadable: %s", d, e)
    exc = ((record or {}).get("counts") or {}).get("exceptions") or {}
    return {
        "date": d.isoformat(),
        "engine_versions": sorted(versions),
        "price_basis": price_basis_label(adjusted, legacy),
        "price_basis_rows": {"corp_action_adjusted": adjusted, "raw_no_factors": by_basis["raw_no_factors"],
                             "raw_before_v1_1": legacy},
        "exceptions": {
            "raw_prices": [{"symbol": r["nse_symbol"], "reason": "no split/bonus factors in the warehouse: scored on "
                                                                 "raw NSE prices"} for r in raw_rows],
            "truncated": [{"symbol": r["nse_symbol"], "break_date": r["b"]} for r in cut_rows],
            "not_scored_after_truncation": exc.get("not_scored_after_truncation") if record else None,
        },
        "exceptions_note": None if record else "no run record for this date: symbols not scored are not known",
        "data_quality": data_quality(record, unreadable),
    }
