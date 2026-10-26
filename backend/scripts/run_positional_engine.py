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

--require-bars: after the bhavcopy step, stop unless stock_ohlcv holds bars for the date. Without them the Chartink hits
                still make a universe and the scorer would date the previous session's bars as today's.
--skip-if-done: do nothing when positional_signals already holds the date (a retry after a run that worked).

Exit codes:
  0 — pipeline ran (even if a sub-step had issues; see log for partial errors), or skipped as already scored
  1 — fatal error reaching DB/secrets
  2 — skipped: no bars for the date yet (--require-bars)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date, datetime
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


async def run(run_date: date, *, fetch_bhavcopy: bool, fetch_scans: bool,
              require_bars: bool = False, skip_if_done: bool = False) -> dict:
    from services.positional_engine import (  # noqa: E402
        bhavcopy_ingester,
        chartink_api,
        chartink_loader,
        pipeline,
        scan_config,
    )
    from deps import db  # noqa: E402

    out: dict = {"date": str(run_date), "steps": {}}

    # A retry after a run that already scored the day does nothing.
    if skip_if_done and (await signals_on(run_date) or 0) > 0:
        log.info("already scored %s: nothing to do", run_date)
        out.update(ok=True, skipped="already_scored")
        return out

    if fetch_bhavcopy:
        try:
            n = await bhavcopy_ingester.ingest_for_date(run_date)
            out["steps"]["bhavcopy"] = {"ok": n > 0, "rows_written": n}
            log.info("bhavcopy: %d rows", n)
        except Exception as e:  # noqa: BLE001
            out["steps"]["bhavcopy"] = {"ok": False, "error": str(e)[:200]}
            log.warning("bhavcopy failed: %s", e)

    # Without the day's bars the Chartink hits would still make a universe, and the scorer would date the previous
    # session's bars as today's. A scheduled run stops here instead and is retried later.
    if require_bars and not await bars_on(run_date):
        log.warning("no stock_ohlcv bars for %s (bhavcopy not published or not ingested yet): not scoring", run_date)
        out.update(ok=False, skipped="no_bars")
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
            "pipeline: scored=%s actionable=%s ok=%s",
            summary.get("scored"), summary.get("actionable"), summary.get("ok"),
        )
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
    ))
    log.info("done: ok=%s skipped=%s steps=%s", result.get("ok"), result.get("skipped"), list(result.get("steps", {})))
    return 2 if result.get("skipped") == "no_bars" else 0


if __name__ == "__main__":
    sys.exit(main())
