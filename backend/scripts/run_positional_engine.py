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
--quality-check: run services/positional_engine/bar_quality over the feature window and log/return its counts.
--require-clean: as --quality-check, and refuse to score when it finds missing sessions, non-session dates, copied
                sessions or invalid OHLC (or cannot run). Turn it on only after the bar store is repaired
                (scripts/repair_scanner_bars.py), or it refuses every run.

Exit codes:
  0 — pipeline ran (even if a sub-step had issues; see log for partial errors), or skipped as already scored
  1 — fatal error reaching DB/secrets
  2 — skipped: no bars for the date yet (--require-bars)
  3 — refused: the date is not an NSE session (weekend or holiday)
  4 — refused: the NSE calendar could not be read or does not cover the date
  5 — refused: the bar store failed the data-quality check (--require-clean)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

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
              quality_check: bool = False, require_clean: bool = False) -> dict:
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
        log.warning("refused %s: the NSE calendar is unavailable (%s)", run_date, e)
        out.update(ok=False, skipped="calendar_unavailable", reason=str(e))
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
                    help="Run the bar-store data-quality check and log its counts")
    p.add_argument("--require-clean", action="store_true",
                    help="As --quality-check, and refuse to score when the store is not clean (exit 5)")
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

    log.info(
        "positional engine: date=%s bhavcopy=%s scans=%s",
        run_date, not args.skip_bhavcopy, not args.skip_scans,
    )
    result = asyncio.run(run(
        run_date,
        fetch_bhavcopy=not args.skip_bhavcopy,
        fetch_scans=not args.skip_scans,
        require_bars=args.require_bars,
        skip_if_done=args.skip_if_done,
        backfill_missing=args.backfill_missing,
        backfill_days=args.backfill_days,
        quality_check=args.quality_check,
        require_clean=args.require_clean,
    ))
    log.info("done: ok=%s skipped=%s steps=%s", result.get("ok"), result.get("skipped"), list(result.get("steps", {})))
    return EXIT_CODES.get(result.get("skipped"), 0)


if __name__ == "__main__":
    sys.exit(main())
