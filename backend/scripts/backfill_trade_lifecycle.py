"""Backfill the lifecycle (Phase 2.2) of paper trades and AI Trader tickets stored before it existed.

    python -m scripts.backfill_trade_lifecycle            # DRY RUN (the default): reads, prints the counts, writes nothing
    python -m scripts.backfill_trade_lifecycle --apply    # writes; needs the owner's go-ahead (gap study §9.2)

For every `desk_paper_trades` and `ai_trader_tickets` document WITHOUT a `state`, the events are rebuilt from its stored
fields exactly as services/trade_lifecycle.derive_history / derive_ticket_history do (each flagged `derived: true`,
source `derived_from_stored_fields`), replayed to check the chain, and — only with --apply — written with
{_id, state: null} in the filter, so a document that gained a state meanwhile (a close, a newer write) is never
touched and a second run writes nothing. Documents that already have a state are counted and left alone.

Output: JSON with counts per collection and derived state, the number of events, any chain problems, and up to three
example ids per state (ids only: no user ids, symbols or amounts are printed). Exit 0 on success, 1 on a problem.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services import trade_lifecycle as lc  # noqa: E402

log = logging.getLogger("backfill_trade_lifecycle")
TRADES, TICKETS = "desk_paper_trades", "ai_trader_tickets"
PROJECTION_NOTE = "ids only; no user ids, symbols or amounts"


def derive(collection: str, doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    return lc.derive_ticket_history(doc) if collection == TICKETS else lc.derive_history(doc)


def summarise(collection: str, docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """{collection, total, already, to_backfill, by_state, events, problems, examples} plus the planned writes."""
    out: Dict[str, Any] = {"collection": collection, "total": len(docs), "already_have_state": 0, "to_backfill": 0,
                           "by_state": Counter(), "by_status": Counter(), "events": 0, "problems": [], "examples": {}, "writes": []}
    for d in docs:
        if d.get("state"):
            out["already_have_state"] += 1
            continue
        try:
            events = derive(collection, d)
        except lc.InvalidTransition as exc:
            out["problems"].append({"id": d.get("_id"), "problem": str(exc)})
            continue
        state, problems = lc.replay(events)
        if problems:
            out["problems"].append({"id": d.get("_id"), "problem": "; ".join(problems)})
            continue
        out["to_backfill"] += 1
        out["by_state"][state] += 1
        out["by_status"][f"{d.get('kind') or 'cash'}:{d.get('status')}:{d.get('exit_reason') or d.get('rejected_by') or '-'}"] += 1
        out["events"] += len(events)
        out["examples"].setdefault(state, [])
        if len(out["examples"][state]) < 3:
            out["examples"][state].append(d.get("_id"))
        out["writes"].append((d["_id"], state, events))
    out["by_state"], out["by_status"] = dict(out["by_state"]), dict(out["by_status"])
    return out


async def run(db, *, apply: bool) -> Dict[str, Any]:
    report: Dict[str, Any] = {"mode": "apply" if apply else "dry-run", "lifecycle_version": lc.LIFECYCLE_VERSION,
                              "printed": PROJECTION_NOTE, "collections": []}
    for col in (TRADES, TICKETS):
        docs = await db[col].find({}).to_list(None)
        s = summarise(col, docs)
        written = 0
        if apply:
            for _id, state, events in s["writes"]:
                res = await db[col].update_one({"_id": _id, "state": None},
                                               {"$set": {"state": state, "lifecycle_backfilled_at": datetime.now(timezone.utc).isoformat()},
                                                "$push": {"transitions": {"$each": events}}})
                written += res.matched_count
        s["written"] = written
        s.pop("writes")
        report["collections"].append(s)
    return report


async def main_async(apply: bool) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=10000)
    try:
        report = await run(client[os.environ["DB_NAME"]], apply=apply)
    finally:
        client.close()
    print(json.dumps(report, indent=1, default=str))
    return 1 if any(c["problems"] for c in report["collections"]) else 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = p.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", default=True, help="read and report only (the default)")
    g.add_argument("--apply", action="store_true", help="write the derived events (needs the owner's go-ahead)")
    args = p.parse_args()
    log.info("lifecycle backfill: %s", "APPLY" if args.apply else "dry run, nothing is written")
    return asyncio.run(main_async(apply=bool(args.apply)))


if __name__ == "__main__":
    sys.exit(main())
