#!/usr/bin/env python3
"""build_ai_watchlist.py — store the day's AI scanner watchlist (Top 10 cash + Top 10 F&O ideas) for cron.

Runs after the AI scanner (scripts/run_positional_engine.py, 19:45 IST): needs that day's scan in positional_signals,
builds both lists with services/ai_watchlist_build.build_day (as the system caller) and stores them in
ai_watchlist_days (services/ai_watchlist_store). A stored day is never rewritten.

Usage:
    docker exec nivesh-staging-app-backend python -m scripts.build_ai_watchlist                  # today (IST)
    docker exec nivesh-staging-app-backend python -m scripts.build_ai_watchlist --skip-if-done   # the cron's form
    docker exec nivesh-staging-app-backend python -m scripts.build_ai_watchlist --dry-run        # build and print, write nothing
    docker exec nivesh-staging-app-backend python -m scripts.build_ai_watchlist --date 2026-10-26

Exit codes:
  0 — stored, or nothing to do (--skip-if-done and the day is stored; --dry-run)
  1 — the build failed
  2 — no AI scanner run for the date yet (nothing written)
  3 — the day was stored by another run meanwhile (nothing written)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

log = logging.getLogger("ai_watchlist")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

IST = timezone(timedelta(hours=5, minutes=30))


def levels_text(e: Dict[str, Any]) -> str:
    """One F&O entry's stored levels in a few words: the underlying stop / target 1, or why there are none."""
    lv = e.get("strategy_levels") or {}
    res = lv.get("result") or {}
    if not lv:
        return "levels: none stored"
    if lv.get("error"):
        return f"levels: {lv['error']}"
    if not res.get("valid"):
        return f"levels: not valid ({((res.get('problems') or [{}])[0]).get('message') or 'no reason given'})"
    u = res.get("underlying") or {}
    return f"levels {u.get('view')}: stop {u.get('stop')} / target {u.get('target')}"


def summary(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "list_date": doc["list_date"],
        "cash": [f"{e['rank']:02d} {e['symbol']} · {e.get('plan_status')} · {(e.get('preferred') or {}).get('label') or '-'}" for e in doc["cash"]],
        "fno": [f"{e['rank']:02d} {e['underlying']} ({e['kind']}) · {e.get('name')} · fit {e.get('fit', {}).get('score')} · {levels_text(e)}" for e in doc["fno"]],
        "regime": doc["notes"].get("regime"),
        "fno_staleness": doc["notes"].get("fno_staleness"),
        "fno_unavailable": len(doc["notes"].get("fno_unavailable") or []),
    }


async def run(list_date: str, *, skip_if_done: bool, dry_run: bool) -> int:
    from scripts.run_positional_engine import signals_on
    from services import ai_watchlist_store as store
    from services.ai_watchlist_build import build_day

    if skip_if_done and not dry_run and await store.has_day(list_date):
        log.info("%s is already stored: nothing to do", list_date)
        return 0
    scanned = await signals_on(date.fromisoformat(list_date))
    if not scanned:
        log.warning("no AI scanner run for %s (positional_signals empty for the date): nothing built", list_date)
        return 2
    try:
        doc = await build_day(list_date)
    except Exception as e:  # noqa: BLE001
        log.error("build failed: %s: %s", type(e).__name__, str(e)[:200])
        return 1
    log.info("built %s: %d cash, %d F&O", list_date, len(doc["cash"]), len(doc["fno"]))
    print(json.dumps(summary(doc), indent=1, default=str))
    if dry_run:
        log.info("dry run: nothing written")
        return 0
    if not await store.insert_day(doc):
        log.warning("%s was stored by another run meanwhile: nothing written", list_date)
        return 3
    log.info("stored %s", list_date)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Store the day's AI scanner watchlist")
    p.add_argument("--date", help="YYYY-MM-DD; defaults to today (IST)")
    p.add_argument("--skip-if-done", action="store_true", help="Do nothing when the day is already stored")
    p.add_argument("--dry-run", action="store_true", help="Build and print, write nothing")
    args = p.parse_args()
    if args.date:
        try:
            list_date = date.fromisoformat(args.date).isoformat()
        except ValueError:
            log.error("Invalid --date %r (expected YYYY-MM-DD)", args.date)
            return 1
    else:
        list_date = datetime.now(IST).date().isoformat()
    log.info("ai watchlist: date=%s skip_if_done=%s dry_run=%s", list_date, args.skip_if_done, args.dry_run)
    return asyncio.run(run(list_date, skip_if_done=args.skip_if_done, dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
