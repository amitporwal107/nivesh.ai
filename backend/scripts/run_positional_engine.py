#!/usr/bin/env python3
"""run_positional_engine.py — end-to-end positional engine runner for cron.

Mirrors POST /api/positional/run-full but skips the FastAPI/admin-auth
layer so it can be invoked from cron without a session cookie.

Pipeline (each step is best-effort, partial failure is logged but
doesn't abort the run):
  1. NSE bhavcopy ingest    → stock_ohlcv
  2. Chartink scans run     → chartink_scan_hits
  3. Score + rank universe  → stock_technical_features + positional_signals

Usage:
    docker exec nivesh-backend python -m scripts.run_positional_engine
    docker exec nivesh-backend python -m scripts.run_positional_engine --date 2026-05-19
    docker exec nivesh-backend python -m scripts.run_positional_engine --skip-bhavcopy
    # the scheduled evening run (deploy/cloudpe/app/positional-engine.cron):
    docker exec nivesh-staging-app-backend python -m scripts.run_positional_engine --require-bars --skip-if-done

Always: a date the NSE calendar (holiday list, segment CM) says is not a session is refused before anything is fetched
or scored, and so is a date the calendar cannot vouch for. The bhavcopy step refuses a file whose own trade date
(DATE1) is not the run date: NSE answers a holiday URL with the previous session's file.

--require-bars: after the bhavcopy step, stop unless stock_ohlcv holds bars for the date. Without them the Chartink hits
                still make a universe and the scorer would date the previous session's bars as today's.
--skip-if-done: do nothing when positional_signals already holds the date (a retry after a run that worked).
--backfill-missing: before the day's bhavcopy, ingest every warehouse session of the last --backfill-days calendar days
                that stock_ohlcv lacks (a day the job missed). Idempotent: a rerun finds nothing missing.
Data quality (report only, on by default; --skip-quality-check turns it off): services/positional_engine/bar_quality
over the feature window. Its status is recorded with the results and shown on the desk (scan_basis).
--require-clean: also refuse to score when it finds missing sessions, non-session dates, copied sessions or invalid
                OHLC (or cannot run). Owner decision 2026-10-27: not in the cron until the staging evidence is reviewed.
--quality-check: accepted for compatibility; the check is on by default.

Calendar readiness (owner decision 2026-10-27): from --calendar-lead (MM-DD, default SCANNER_CALENDAR_LEAD or 12-01)
next year's NSE CM holiday list must be loaded too. When it is not, the run logs an ERROR, still scores the day, and
exits 6; the run record says calendar_ready=false and the missing year.

Run record: every run that gets past argument parsing writes one document to Mongo `job_runs` (job
"positional_engine", services/positional_engine/scan_meta.py): status, exit code, session, counts (engine version,
price basis, exceptions, data quality, calendar), error. A record that cannot be written is logged as an ERROR.

Exit codes:
  0 — pipeline ran (even if a sub-step had issues; see log for partial errors), or skipped as already scored
  1 — fatal error reaching DB/secrets
  2 — skipped: no bars for the date yet (--require-bars)
  3 — refused: the date is not an NSE session (weekend or holiday)
  4 — refused: the NSE calendar could not be read or does not cover the date
  5 — refused: the bar store failed the data-quality check (--require-clean)
  6 — scored, but next year's NSE holiday list is not loaded (ALERT: load it before 1 Jan)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

log = logging.getLogger("positional_runner")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


async def _count_on(sql: str, run_date: date) -> Optional[int]:
    """count(*) for the day, or None when the database cannot be reached."""
    from services import pg_client  # noqa: E402

    pool = await pg_client.get_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        return int(await conn.fetchval(sql, run_date) or 0)


async def bars_on(run_date: date) -> Optional[int]:
    return await _count_on("SELECT count(*) FROM stock_ohlcv WHERE bar_date = $1", run_date)


async def signals_on(run_date: date) -> Optional[int]:
    return await _count_on("SELECT count(*) FROM positional_signals WHERE signal_date = $1", run_date)


EXIT_CODES = {"no_bars": 2, "not_a_session": 3, "calendar_unavailable": 4, "dirty_bars": 5}
EXIT_CALENDAR_NOT_READY = 6
RECORD_TIMEOUT_S = 10.0         # a Mongo hiccup must not hold the evening run
QUALITY_WINDOW_DAYS = 400       # the pipeline's 260-bar feature window


async def quality(run_date: date) -> dict:
    """bar_quality over the feature window, against the warehouse sessions before the run date (the warehouse may not
    hold the run date yet at 19:45; the calendar already vouched for it)."""
    from services import pg_client  # noqa: E402
    from services.positional_engine import bar_quality, session_calendar  # noqa: E402

    start = run_date - timedelta(days=QUALITY_WINDOW_DAYS)
    pool = await pg_client.get_pool()
    if pool is None:
        return {"ok": False, "error": "no_pg_pool"}
    try:
        sessions = await session_calendar.warehouse_sessions(start, run_date - timedelta(days=1))
    except session_calendar.CalendarUnavailable as e:
        return {"ok": False, "error": "warehouse_sessions_unavailable", "reason": str(e)}
    report = await bar_quality.check_store(pool, start, run_date, sessions | {run_date})
    clean, problems = bar_quality.is_clean(report)
    return {"ok": True, "clean": clean, "problems": problems, "report": report}


async def run(run_date: date, *, fetch_bhavcopy: bool, fetch_scans: bool,
              require_bars: bool = False, skip_if_done: bool = False,
              backfill_missing: bool = False, backfill_days: int = 14,
              quality_check: bool = True, require_clean: bool = False,
              calendar_lead: Tuple[int, int] = (12, 1)) -> dict:
    from services.positional_engine import (  # noqa: E402
        bhavcopy_ingester,
        chartink_api,
        chartink_loader,
        pipeline,
        scan_config,
        session_calendar,
    )
    from deps import db  # noqa: E402

    out: dict = {"date": str(run_date), "steps": {}}

    # A weekend, a holiday, or a date the calendar cannot vouch for is never fetched or scored.
    try:
        is_session, why = await session_calendar.check_session(run_date)
    except session_calendar.CalendarUnavailable as e:
        log.error("refused %s: the NSE calendar is unavailable (%s)", run_date, e)
        out.update(ok=False, skipped="calendar_unavailable", reason=str(e),
                   calendar={"ready": False, "missing_year": run_date.year, "checked_years": [run_date.year],
                             "reason": str(e)})
        return out
    if not is_session:
        log.warning("refused %s: not an NSE session (%s)", run_date, why)
        out.update(ok=False, skipped="not_a_session", reason=why)
        return out

    # A retry after a run that already scored the day does nothing.
    if skip_if_done and (await signals_on(run_date) or 0) > 0:
        log.info("already scored %s: nothing to do", run_date)
        out.update(ok=True, skipped="already_scored")
        return out

    # Next year's holidays must be loaded before the first session that needs them: an alert, not a refusal.
    ready = await session_calendar.readiness(run_date, calendar_lead)
    out["calendar"] = ready
    if not ready["ready"]:
        log.error("ALERT calendar not ready: the NSE CM holiday list for %s is not loaded (%s). The run continues; "
                  "load it before the first session of %s.", ready["missing_year"], ready["reason"], ready["missing_year"])

    if backfill_missing:
        try:
            bf = await bhavcopy_ingester.backfill_missing(run_date - timedelta(days=backfill_days),
                                                          run_date - timedelta(days=1))
            out["steps"]["backfill"] = bf
            log.info("backfill: missing=%s ok=%s", bf.get("missing"), bf.get("ok"))
        except Exception as e:  # noqa: BLE001
            out["steps"]["backfill"] = {"ok": False, "error": str(e)[:200]}
            log.warning("backfill failed: %s", e)

    if fetch_bhavcopy:
        try:
            res = await bhavcopy_ingester.ingest(run_date)
            out["steps"]["bhavcopy"] = {"ok": res["status"] == "written", **res}
            log.info("bhavcopy: %s, %d rows%s", res["status"], res["rows_written"],
                     f" ({res['reason']})" if res.get("reason") else "")
        except Exception as e:  # noqa: BLE001
            out["steps"]["bhavcopy"] = {"ok": False, "error": str(e)[:200]}
            log.warning("bhavcopy failed: %s", e)

    # Without the day's bars the Chartink hits would still make a universe, and the scorer would date the previous
    # session's bars as today's. A scheduled run stops here instead and is retried later.
    if require_bars and not await bars_on(run_date):
        log.warning("no stock_ohlcv bars for %s (bhavcopy not published or not ingested yet): not scoring", run_date)
        out.update(ok=False, skipped="no_bars")
        return out

    if quality_check or require_clean:
        try:
            q = await quality(run_date)
        except Exception as e:  # noqa: BLE001
            q = {"ok": False, "error": str(e)[:200]}
        out["steps"]["quality"] = q
        if q.get("ok"):
            log.info("bar quality: clean=%s problems=%s", q["clean"], q["problems"])
        else:
            log.warning("bar quality check could not run: %s", q.get("reason") or q.get("error"))
        if require_clean and not (q.get("ok") and q.get("clean")):
            log.warning("refused %s: the bar store is not clean (%s): not scoring", run_date,
                        q.get("problems") or q.get("error"))
            out.update(ok=False, skipped="dirty_bars")
            return out

    if fetch_scans:
        try:
            scans = await scan_config.load(db)
            if not scans:
                out["steps"]["chartink"] = {"ok": False, "error": "no_scans_configured"}
                log.warning("chartink: no scans configured")
            else:
                results = await chartink_api.run_scans(scans)
                written = {}
                for name, rows in results.items():
                    if name == "_errors":
                        continue
                    n = await chartink_loader.upsert_scan_hits(run_date, name, rows)
                    written[name] = n
                out["steps"]["chartink"] = {
                    "ok": True,
                    "rows_written": written,
                    "errors": results.get("_errors", {}),
                }
                log.info("chartink: %d scans → %s rows", len(written), sum(written.values()))
        except Exception as e:  # noqa: BLE001
            out["steps"]["chartink"] = {"ok": False, "error": str(e)[:200]}
            log.warning("chartink failed: %s", e)

    try:
        summary = await pipeline.run_for_date(run_date)
        out["steps"]["pipeline"] = summary
        log.info(
            "pipeline: scored=%s actionable=%s ok=%s price_basis=%s break_truncated=%s",
            summary.get("scored"), summary.get("actionable"), summary.get("ok"),
            summary.get("price_basis"), summary.get("break_truncated"),
        )
        if not summary.get("ok"):
            log.error("pipeline did not score %s: %s %s", run_date, summary.get("error"), summary.get("reason") or "")
    except Exception as e:  # noqa: BLE001
        out["steps"]["pipeline"] = {"ok": False, "error": str(e)[:200]}
        log.error("pipeline failed: %s", e)

    out["ok"] = out["steps"].get("pipeline", {}).get("ok", False)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Positional engine end-to-end runner")
    p.add_argument("--date", help="YYYY-MM-DD; defaults to today (UTC)")
    p.add_argument("--skip-bhavcopy", action="store_true",
                    help="Skip NSE bhavcopy ingest (use existing OHLCV rows)")
    p.add_argument("--skip-scans", action="store_true",
                    help="Skip Chartink scan fetch (use existing scan hits)")
    p.add_argument("--require-bars", action="store_true",
                    help="Stop before the scans and scoring unless stock_ohlcv holds bars for the date (exit 2)")
    p.add_argument("--skip-if-done", action="store_true",
                    help="Do nothing when positional_signals already holds the date")
    p.add_argument("--backfill-missing", action="store_true",
                    help="First ingest warehouse sessions of the last --backfill-days days that stock_ohlcv lacks")
    p.add_argument("--backfill-days", type=int, default=14,
                    help="Calendar days before the run date that --backfill-missing looks at (default 14)")
    p.add_argument("--quality-check", action="store_true",
                    help="Accepted for compatibility: the data-quality check runs by default")
    p.add_argument("--skip-quality-check", action="store_true",
                    help="Do not run the bar-store data-quality check (its status is then 'not checked')")
    p.add_argument("--require-clean", action="store_true",
                    help="Refuse to score when the data-quality check finds a market-wide problem (exit 5)")
    p.add_argument("--calendar-lead", default="",
                    help="MM-DD from which next year's NSE holiday list must be loaded (default SCANNER_CALENDAR_LEAD or 12-01)")
    args = p.parse_args()

    run_date: date
    if args.date:
        try:
            run_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            log.error("Invalid --date %r (expected YYYY-MM-DD)", args.date)
            return 1
    else:
        run_date = datetime.utcnow().date()

    from services.positional_engine import session_calendar  # noqa: E402
    try:
        lead = session_calendar.parse_lead(args.calendar_lead)
    except ValueError:
        log.error("Invalid --calendar-lead / SCANNER_CALENDAR_LEAD %r (expected MM-DD)", args.calendar_lead)
        return 1

    log.info(
        "positional engine: date=%s bhavcopy=%s scans=%s",
        run_date, not args.skip_bhavcopy, not args.skip_scans,
    )
    result, code = asyncio.run(recorded(run_date, dict(
        fetch_bhavcopy=not args.skip_bhavcopy,
        fetch_scans=not args.skip_scans,
        require_bars=args.require_bars,
        skip_if_done=args.skip_if_done,
        backfill_missing=args.backfill_missing,
        backfill_days=args.backfill_days,
        quality_check=not args.skip_quality_check,
        require_clean=args.require_clean,
        calendar_lead=lead,
    )))
    log.info("done: ok=%s skipped=%s exit=%s steps=%s", result.get("ok"), result.get("skipped"), code,
             list(result.get("steps", {})))
    return code


def exit_code(result: dict) -> int:
    if result.get("skipped"):
        return EXIT_CODES.get(result["skipped"], 0)
    if not (result.get("calendar") or {}).get("ready", True):
        return EXIT_CALENDAR_NOT_READY
    return 0


def record_of(result: dict, code: int) -> Tuple[str, dict, Optional[str], dict]:
    """(status, counts, error, top-level fields) of the run record for `result`."""
    from services.positional_engine import ENGINE_VERSION, scan_meta  # noqa: E402

    pipe = result.get("steps", {}).get("pipeline") or {}
    q = result.get("steps", {}).get("quality") or {}
    cal = result.get("calendar") or {}
    report = q.get("report") or {}
    counts = {
        "date": result.get("date"), "engine_version": ENGINE_VERSION,
        "scored": pipe.get("scored"), "actionable": pipe.get("actionable"),
        "price_basis": pipe.get("price_basis"), "exceptions": pipe.get("exceptions"),
        "quality": ({"ok": q.get("ok"), "clean": q.get("clean"), "problems": q.get("problems"),
                     "counts": {k: (v or {}).get("count") for k, v in report.items() if isinstance(v, dict)},
                     "error": q.get("error"), "reason": q.get("reason")} if q else None),
        "calendar": cal or None,
        "bhavcopy": (result.get("steps", {}).get("bhavcopy") or {}).get("status"),
        "backfill_missing": (result.get("steps", {}).get("backfill") or {}).get("missing"),
    }
    fields = {"calendar_ready": cal.get("ready") if cal else None, "calendar_missing_year": cal.get("missing_year") if cal else None}
    skipped = result.get("skipped")
    if skipped:
        return scan_meta.SKIPPED.get(skipped, f"skipped_{skipped}"), counts, result.get("reason"), fields
    if pipe and not pipe.get("ok"):
        return scan_meta.FAILED, counts, f"{pipe.get('error')}: {pipe.get('reason') or ''}".strip(": "), fields
    if code == EXIT_CALENDAR_NOT_READY:
        return (scan_meta.CALENDAR_NOT_READY, counts,
                f"the NSE CM holiday list for {cal.get('missing_year')} is not loaded ({cal.get('reason')})", fields)
    return scan_meta.OK, counts, None, fields


async def recorded(run_date: date, kwargs: dict) -> Tuple[dict, int]:
    """run() with its run record in Mongo `job_runs`: written as running first, finished with the outcome after."""
    from services.positional_engine import scan_meta  # noqa: E402
    db = None
    run_id = uuid.uuid4().hex
    try:
        from deps import db as _db  # noqa: E402
        await asyncio.wait_for(scan_meta.start(_db, run_id, session=run_date.isoformat(), now=scan_meta.utcnow()),
                               RECORD_TIMEOUT_S)
        db = _db
    except Exception as e:  # noqa: BLE001 — the run still happens; the missing record is an ERROR in the log
        log.error("run record not started (%s): this run will not appear in job_runs", type(e).__name__)
    try:
        result = await run(run_date, **kwargs)
    except Exception as e:  # a crash is recorded as failed, then raised as before
        if db is not None:
            try:
                await asyncio.wait_for(scan_meta.finish(db, run_id, now=scan_meta.utcnow(), status=scan_meta.FAILED,
                                                        exit_code=1, counts={"date": run_date.isoformat()},
                                                        error=f"{type(e).__name__}: {str(e)[:300]}"), RECORD_TIMEOUT_S)
            except Exception as rec_err:  # noqa: BLE001
                log.error("run record %s not finished after a crash (%s)", run_id, type(rec_err).__name__)
        raise
    code = exit_code(result)
    if db is not None:
        status, counts, error, fields = record_of(result, code)
        try:
            await asyncio.wait_for(scan_meta.finish(db, run_id, now=scan_meta.utcnow(), status=status, exit_code=code,
                                                    counts=counts, error=error, **fields), RECORD_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001
            log.error("run record %s not finished (%s): job_runs shows it as running", run_id, type(e).__name__)
    return result, code


if __name__ == "__main__":
    sys.exit(main())
