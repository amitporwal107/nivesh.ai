"""Admin steps for the suggestion engine. Run from backend/ (nothing here is scheduled):

    python -m services.suggestions.admin seed                 write the catalog into suggestion_rules / query_templates
    python -m services.suggestions.admin pass --days 14       pre-open / post-close pass for users active in N days
    python -m services.suggestions.admin pass --dry-run       list how many users the pass would evaluate, write nothing

The pass is meant for the two daily slots (pre-open, after the evening data jobs); installing a cron is an owner
decision and is not done here.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import List


async def active_users(db, days: int) -> List[str]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    ids = set(await db.chat_sessions.distinct("user_id", {"updated_at": {"$gte": since}}))
    ids |= set(await db.desk_paper_trades.distinct("user_id", {"status": "open"}))
    return sorted(i for i in ids if i)


async def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="services.suggestions.admin")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed")
    p = sub.add_parser("pass")
    p.add_argument("--days", type=int, default=14)
    p.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    from deps import db
    from . import engine, store
    if args.cmd == "seed":
        print(json.dumps(await store.seed(db)))
        return 0
    users = await active_users(db, args.days)
    if args.dry_run:
        print(json.dumps({"users": len(users), "dry_run": True}))
        return 0
    print(json.dumps(await engine.scheduled_pass(db, user_ids=users)))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
