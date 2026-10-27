#!/usr/bin/env python3
"""build_results_week.py — store the day's "Results week" snapshot (docs/EARNINGS_SURPRISE_TRACKER.md §5) for cron.

Builds the GET /api/desk/results-week answer for the date (services/results_week/build.build_day, snapshot mode: the
OI build-up must be the date's own, never an earlier day's) and stores it in Mongo results_week_days (`_id` = date,
insert-once: a stored day is never rewritten), so the validation study reads what was known that night. The per-user
Chartink column is not stored: the route joins the signed-in user's hits at read time.

Before building, it refreshes each imported desk Chartink dashboard once (services/chartink_desk/refresh.refresh_all,
the same code as POST /api/desk/chartink/refresh, per-user pacing; confirmation only, never scored). The build calls
no route-level code and checks no user, so it needs no deps.system_caller.

Point-in-time: only the date itself can be stored (DaaS answers the results calendar as of now, so a past date rebuilt
later would carry later knowledge). Any --date may be dry-run.

Usage:
    docker exec nivesh-staging-app-backend python -m scripts.build_results_week                  # today (IST)
    docker exec nivesh-staging-app-backend python -m scripts.build_results_week --skip-if-done   # the cron's form
    docker exec nivesh-staging-app-backend python -m scripts.build_results_week --dry-run        # build and print, write nothing
    docker exec nivesh-staging-app-backend python -m scripts.build_results_week --dry-run --date 2026-10-27 --symbols MANKIND,SONACOMS

Exit codes:
  0 — stored, or nothing to do (--skip-if-done and the day is stored), or a --dry-run whose real run would store
  1 — the build failed, the date is invalid, or a date other than today without --dry-run (nothing written)
  2 — the date is not an NSE session (nothing written)
  3 — the day was stored by another run meanwhile (nothing written)
  4 — the date's F&O build-up or stock prices are not loaded yet (nothing written; a later run builds the day).
      --dry-run returns 4 too when a real run would refuse, after printing what it built.
  5 — the results calendar (DaaS expectations) could not be read at all (nothing written)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

log = logging.getLogger("results_week")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)       # one line per DaaS read (~900 a build) drowns the summary

IST = timezone(timedelta(hours=5, minutes=30))
TOP_SHOWN = 10


def summary(body: Dict[str, Any]) -> Dict[str, Any]:
    from services.results_week import scoring as sc

    rated: Dict[str, Dict[str, int]] = {k: {} for k in sc.METRICS}
    declared = [r for r in body["results"] if r["status"] == "declared"]
    for r in declared:
        for k in sc.METRICS:
            m = r["components"]["surprise"]["metrics"][k]
            why = "rated" if m.get("z") is not None else (m.get("reason") or "?").replace("not rated: ", "")
            rated[k][why] = rated[k].get(why, 0) + 1
    scored = [r["score"]["value"] for r in declared if r["score"]["value"] is not None]
    return {
        "date": body["date"], "week": body["week"], "mode": body["mode"], "counts": body["counts"],
        "counts_partial": body["counts_partial"],
        "week_windows": [{k: w.get(k) for k in ("from", "to", "ok", "as_of", "counts", "count")}
                         for w in body["sources"]["expectations"]["week_windows"]],
        "extra_windows": [{k: w.get(k) for k in ("from", "to", "ok", "count")} for w in body["sources"]["expectations"]["extra_windows"]],
        "declared_metrics": rated,
        "earnings_score": {"n": len(scored), "bands": {b: sum(1 for r in declared if r["score"]["band"] == b) for b in ("above", "in_line", "below")}},
        "sources": {k: ({x: v.get(x) for x in ("ok", "as_of", "rows", "read", "failed", "stocks", "stocks_analysed", "latest") if x in v}
                        if isinstance(v, dict) else v) for k, v in body["sources"].items()},
        "ideas_fno": [f"{i['rank']:02d} {i['symbol']} [{i['phase']}] {i['signal']} · {i['why']}" for i in body["ideas"]["fno"][:TOP_SHOWN]],
        "ideas_all": [f"{i['rank']:02d} {i['symbol']} [{i['phase']}] {i['signal']} · {i['why']}" for i in body["ideas"]["all"][:TOP_SHOWN]],
        "ideas_sizes": {"fno": len(body["ideas"]["fno"]), "all": len(body["ideas"]["all"]), "left_out": body["ideas"]["left_out"]},
        "gaps": body["gaps"],
        "wording_check_forbidden_terms_found": sc.forbidden_terms(body),
        "body_kb": round(len(json.dumps(body, default=str)) / 1024, 1),
    }


async def refusal(body: Dict[str, Any], day: date) -> Optional[str]:
    """Why a real run must not store this build yet, or None."""
    from services.results_week import loaders

    fb = body["sources"]["fno_buildup"]
    if fb.get("as_of") != day.isoformat() or not fb.get("rows"):
        return f"the F&O build-up for {day.isoformat()} is not loaded (it has {fb.get('as_of')}, {fb.get('rows')} rows)"
    loaded = await loaders.prices_loaded(day)
    if not loaded:
        return f"stock prices (stock_ohlcv) for {day.isoformat()} are {'not loaded' if loaded is False else 'unreadable'}"
    return None


async def refresh_chartink(dry_run: bool) -> None:
    """Each imported desk Chartink dashboard, once (confirmation only). A failure is logged, never fatal."""
    from deps import db
    from services.chartink_desk import refresh as refresh_mod

    try:
        r = await refresh_mod.refresh_all(db, dry_run=dry_run)
    except Exception as e:  # noqa: BLE001
        log.warning("chartink refresh failed (%s): the results week is built without fresh Chartink hits", type(e).__name__)
        return
    log.info("chartink refresh%s: users=%d scans_ok=%d scans_failed=%d per_user=%s", " (dry run: nothing fetched, nothing written)" if dry_run else "",
             r["users"], r["scans_ok"], r["scans_failed"], r["per_user"])


async def run(day: date, *, skip_if_done: bool, dry_run: bool, show: List[str], today: Optional[date] = None,
              live: bool = False) -> int:
    from services.positional_engine import session_calendar
    from services.results_week import build as rw_build
    from services.results_week import loaders, store

    today = today or datetime.now(IST).date()
    key = day.isoformat()
    if skip_if_done and not dry_run and await store.has_day(key):
        log.info("%s is already stored: nothing to do", key)
        return 0
    if day != today and not dry_run:
        log.error("%s is not today (%s): only the date itself is stored point-in-time; use --dry-run for another date", key, today)
        return 1
    try:
        ok, why = await session_calendar.check_session(day)
    except session_calendar.CalendarUnavailable as e:
        log.error("NSE session calendar unavailable: %s", e)
        return 1
    if not ok:
        log.warning("%s is not an NSE session (%s): nothing built", key, why)
        return 2
    if day == today:
        await refresh_chartink(dry_run)
    t0 = time.monotonic()
    try:
        body = await rw_build.build_day(day, now=datetime.now(timezone.utc), live=live)
    except loaders.SourceUnavailable as e:
        log.error("the results calendar could not be read: %s. Nothing written", e)
        return 5
    except Exception as e:  # noqa: BLE001
        log.error("build failed: %s: %s", type(e).__name__, str(e)[:200])
        return 1
    log.info("built %s in %.1f s", key, time.monotonic() - t0)
    print(json.dumps(summary(body), indent=1, default=str))
    for sym in show:
        rows = [r for r in body["results"] if r["symbol"] == sym.upper()]
        print(json.dumps(rows or {"symbol": sym, "note": "not in this week's results"}, indent=1, default=str))
    why = await refusal(body, day)
    if why:
        log.error("%s %s: %s. Nothing written; a later run builds the day", key, "would be refused" if dry_run else "refused", why)
        return 4
    if dry_run:
        log.info("dry run: nothing written")
        return 0
    if not await store.insert_day(rw_build.strip_chartink(body)):
        log.warning("%s was stored by another run meanwhile: nothing written", key)
        return 3
    log.info("stored %s: %d results, %d + %d ideas", key, len(body["results"]), len(body["ideas"]["fno"]), len(body["ideas"]["all"]))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Store the day's results-week snapshot")
    p.add_argument("--date", help="YYYY-MM-DD; defaults to today (IST)")
    p.add_argument("--skip-if-done", action="store_true", help="Do nothing when the day is already stored")
    p.add_argument("--dry-run", action="store_true", help="Build and print, write nothing (no Chartink fetch either)")
    p.add_argument("--symbols", default="", help="Comma-separated symbols whose full rows are printed")
    p.add_argument("--live", action="store_true", help="With --dry-run: build as the live route does (the OI build-up may "
                                                         "fall back to the newest loaded day, labelled)")
    p.add_argument("--signals", action="store_true",
                   help="Also print the AI scanner's results signal (§4d) as of now: strong / weak symbols with reasons (reads only)")
    args = p.parse_args(argv)
    if args.date:
        try:
            day = date.fromisoformat(args.date)
        except ValueError:
            log.error("Invalid --date %r (expected YYYY-MM-DD)", args.date)
            return 1
    else:
        day = datetime.now(IST).date()
    show = [s.strip() for s in args.symbols.split(",") if s.strip()]
    log.info("results week: date=%s skip_if_done=%s dry_run=%s", day, args.skip_if_done, args.dry_run)
    if args.live and not args.dry_run:
        log.error("--live is for --dry-run only: a stored day is always built from its own F&O day")
        return 1

    async def both() -> int:                # one event loop: the Mongo client is bound to the loop that first used it
        if args.signals:
            await print_signals()
        return await run(day, skip_if_done=args.skip_if_done, dry_run=args.dry_run, show=show, live=args.live)
    return asyncio.run(both())


async def print_signals(now: Optional[datetime] = None) -> None:
    """The results signal the scanner routes would apply now (services/results_week/signal.compute). Reads only."""
    from services.results_week import signal as rs

    now = now or datetime.now(timezone.utc)
    t0 = time.monotonic()
    try:
        sigs, gaps = await rs.compute(now)
    except Exception as e:  # noqa: BLE001
        log.error("results signal unavailable: %s: %s", type(e).__name__, e)
        return
    rows = sorted(sigs.items(), key=lambda kv: (-kv[1]["points"], kv[0]))

    def line(k: str, v: Dict[str, Any]) -> str:
        filed = datetime.fromisoformat(v["filed_at"]).astimezone(IST).strftime("%d %b %H:%M IST")
        return f"{k} {v['points']:+.1f} [{v['basis']}, filed {filed}, session {v['sessions_since']}] · {' · '.join(v['reasons'])}"
    print(json.dumps({"results_signal_as_of": now.isoformat(), "seconds": round(time.monotonic() - t0, 1), "rule": rs.RULE_TEXT, "gaps": gaps,
                      "strong": [line(k, v) for k, v in rows if v["strength"] == "strong"],
                      "weak": [line(k, v) for k, v in rows if v["strength"] == "weak"]},
                     indent=1, default=str))


if __name__ == "__main__":
    sys.exit(main())
