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

Exit codes:
  0 — pipeline ran (even if a sub-step had issues; see log for partial errors)
  1 — fatal error reaching DB/secrets
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

log = logging.getLogger("positional_runner")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


async def run(run_date: date, *, fetch_bhavcopy: bool, fetch_scans: bool) -> dict:
    from services.positional_engine import (  # noqa: E402
        bhavcopy_ingester,
        chartink_api,
        chartink_loader,
        pipeline,
        scan_config,
    )
    from deps import db  # noqa: E402

    out: dict = {"date": str(run_date), "steps": {}}

    if fetch_bhavcopy:
        try:
            n = await bhavcopy_ingester.ingest_for_date(run_date)
            out["steps"]["bhavcopy"] = {"ok": n > 0, "rows_written": n}
            log.info("bhavcopy: %d rows", n)
        except Exception as e:  # noqa: BLE001
            out["steps"]["bhavcopy"] = {"ok": False, "error": str(e)[:200]}
            log.warning("bhavcopy failed: %s", e)

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
    ))
    log.info("done: ok=%s steps=%s", result.get("ok"), list(result.get("steps", {})))
    return 0


if __name__ == "__main__":
    sys.exit(main())
