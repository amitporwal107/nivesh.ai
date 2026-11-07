#!/usr/bin/env python3
"""spt_backfill_signals.py — load a day's Scan dashboard signals into SPT (spt_signal_events, then spt_opportunities).

Sources:
    --source archive:<path>   a JSON-lines dump of the Redis signal keys ({key, type, ttl_s, value} per line, as
                              /home/deploy/nivesh-signal-archive/redis_dump_20261105.jsonl): the list marks (`:s:`), the
                              strong signals (`:g:`) and the day's scores doc (`:scores`). --day picks one day of the dump
                              (default: every day in it).
    --source redis --day D    the live signal store (services/scan_builder/signals.py; Redis keeps three days)

Modes:
    --dry-run (default)       build every event exactly as the ingest would and print the counts: normalized /
                              quarantined (by reason), by category and horizon, and how many opportunities the normalized
                              events would group into (distinct symbol × direction × horizon of the day, before any open
                              opportunity they would join). Writes nothing.
    --write                   ingest (idempotent: an event already stored is a no-op) and consolidate the day's events.
                              A second run writes nothing new. Validation is left to the SPT loop.

Every event is judged at the time the script runs: an intraday mark of an earlier day is past its window and is stored
as quarantined `stale` (an expired signal received late); a positional mark inside its window is normalized.

Usage:
    docker exec nivesh-staging-app-backend python -m scripts.spt_backfill_signals --source archive:/tmp/dump.jsonl
    docker exec nivesh-staging-app-backend python -m scripts.spt_backfill_signals --source redis --day 2026-11-05 --write

Exit codes: 0 done · 1 the source or the database could not be read or written · 2 bad arguments.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.spt.opportunities import consolidate as cons  # noqa: E402
from services.spt.signals import hook, ingest  # noqa: E402

logger = logging.getLogger("spt_backfill_signals")
PREFIX = "nivesh:sb:signals:"


def parse_archive(path: str, day: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """{day: {marks, strong, scores_doc}} from a JSON-lines Redis dump. Unreadable lines are counted, not guessed."""
    out: Dict[str, Dict[str, Any]] = {}
    bad = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                key = rec["key"]
            except (ValueError, KeyError, TypeError):
                bad += 1
                continue
            if not isinstance(key, str) or not key.startswith(PREFIX):
                continue
            parts = key[len(PREFIX):].split(":")
            if len(parts) < 2:
                continue
            d, kind = parts[0], parts[1]
            if day and d != day:
                continue
            slot = out.setdefault(d, {"marks": [], "strong": [], "scores_doc": None, "unreadable": 0})
            if kind not in ("s", "g", "scores"):
                continue
            try:
                value = json.loads(rec["value"]) if isinstance(rec.get("value"), str) else rec.get("value")
            except ValueError:
                slot["unreadable"] += 1
                continue
            if not isinstance(value, dict):
                slot["unreadable"] += 1
            elif kind == "s":
                slot["marks"].append(value)
            elif kind == "g":
                slot["strong"].append(value)
            else:
                slot["scores_doc"] = value
    if bad:
        logger.warning("%d unreadable line(s) in %s", bad, path)
    return out


def dry_run(day: str, got: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    docs = ([ingest.list_event(m, day=day, scores_doc=got.get("scores_doc"), now=now, via="backfill")
             for m in got["marks"]]
            + [ingest.strong_event(r, day=day, now=now, via="backfill") for r in got["strong"]])
    ok = [d for d in docs if d["status"] == "normalized"]
    reasons: Counter = Counter(r for d in docs for r in d["quarantine_reasons"])
    return {"day": day, "events": len(docs), "list_marks": len(got["marks"]), "strong": len(got["strong"]),
            "normalized": len(ok), "quarantined": len(docs) - len(ok), "quarantine_reasons": dict(reasons),
            "by_category": dict(Counter(d["category"] for d in ok)), "by_horizon": dict(Counter(d["horizon"] for d in ok)),
            "with_scanner_score": sum(1 for d in docs if d["scanner_score"] is not None),
            "opportunity_groups": len({(d["symbol"], d["direction"], d["horizon"]) for d in ok}),
            "unreadable": got.get("unreadable", 0)}


async def write(db, day: str, got: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    ing = await ingest.ingest(db, day=day, marks=got["marks"], strong=got["strong"], scores_doc=got.get("scores_doc"),
                              now=now, via="backfill")
    con = await cons.consolidate(db, days=[day], now=now)
    return {"day": day, "ingest": ing, "consolidate": con}


async def main(argv: Optional[List[str]] = None, *, db: Any = None, out: Callable[[str], None] = print,
               now: Optional[datetime] = None) -> int:
    ap = argparse.ArgumentParser(description="Load Scan dashboard signals into SPT.")
    ap.add_argument("--source", required=True, help="archive:<path> or redis")
    ap.add_argument("--day", help="YYYY-MM-DD (required with --source redis)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True)
    mode.add_argument("--write", action="store_true")
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return 2
    if args.day:
        try:
            date.fromisoformat(args.day)
        except ValueError:
            out("bad --day (YYYY-MM-DD)")
            return 2
    now = now or datetime.now(timezone.utc)
    try:
        if args.source.startswith("archive:"):
            days = parse_archive(args.source[len("archive:"):], args.day)
        elif args.source == "redis":
            if not args.day:
                out("--source redis needs --day")
                return 2
            days = {args.day: await hook.read_day(args.day)}
        else:
            out("--source must be archive:<path> or redis")
            return 2
    except Exception as e:  # noqa: BLE001 — reported with its type; nothing was written
        out(f"the source could not be read ({type(e).__name__}: {e})")
        return 1
    if not days:
        out("no signals found for that source / day")
        return 0
    for day in sorted(days):
        got = days[day]
        if not args.write:
            out(json.dumps({"mode": "dry-run", **dry_run(day, got, now)}, sort_keys=True))
            continue
        if db is None:
            from deps import db as real_db
            db = real_db
        try:
            res = await write(db, day, got, now)
        except Exception as e:  # noqa: BLE001 — a rerun is safe (idempotent)
            out(f"{day}: the write failed ({type(e).__name__}); a rerun is safe")
            return 1
        out(json.dumps({"mode": "write", **res}, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    sys.exit(asyncio.run(main()))
