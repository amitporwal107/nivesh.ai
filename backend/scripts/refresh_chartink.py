#!/usr/bin/env python3
"""refresh_chartink.py — the scheduled refresh of every user's Chartink scans (Smart Trading Desk).

Runs the same code as POST /api/desk/chartink/refresh (services/chartink_desk/refresh.py) for ALL users who connected a dashboard: each user's enabled,
supported stock scans are run against Chartink's public screener endpoint, politely (2 at a time, at least 1 s between scans, 30 s each, 25 scans at
most per user, users one after another) and today's (IST) hits are stored, replacing the same scan and day, so a rerun is idempotent. A scan that fails
never fails the others; the hits of a failed scan are not refreshed. The per-user manual cooldown is not applied here (cron runs hours apart).
Notification is in-app only. Nothing here places an order or talks to a broker; no Chartink credential exists or is stored.

Usage:
    docker exec nivesh-staging-app-backend python -m scripts.refresh_chartink
    docker exec nivesh-staging-app-backend python -m scripts.refresh_chartink --dry-run   # list what would run, fetch nothing, write nothing

Exit codes (like scripts/check_desk_alerts.py):
  0 — ran (individual scans may have failed; each is counted and the error codes are logged)
  1 — fatal: the database could not be read, or every scan of every user failed
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

log = logging.getLogger("refresh_chartink")


async def run(db=None, *, dry_run: bool = False, scan_fn=None) -> Dict[str, Any]:
    """Refresh every user's scans. Returns the counts that are logged; `ok` is False only when scans were attempted and none succeeded."""
    from services.chartink_desk import refresh as refresh_mod  # noqa: E402

    if db is None:
        from deps import db  # noqa: E402
    kw = {"scan_fn": scan_fn} if scan_fn is not None else {}
    out = await refresh_mod.refresh_all(db, dry_run=dry_run, **kw)
    out["ok"] = dry_run or not (out["scans_failed"] and not out["scans_ok"])
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    p = argparse.ArgumentParser(description="Refresh every user's Chartink scans and store today's hits")
    p.add_argument("--dry-run", action="store_true", help="Report what would run; fetch nothing, write nothing")
    args = p.parse_args()
    try:
        result = asyncio.run(run(dry_run=args.dry_run))
    except Exception as exc:  # noqa: BLE001 — the database (or something under it) failed; cron needs a non-zero exit
        log.exception("chartink refresh failed: %r", exc)
        return 1
    log.info("chartink refresh%s: users=%d scans_ok=%d scans_failed=%d", " (dry run)" if result["dry_run"] else "", result["users"], result["scans_ok"], result["scans_failed"])
    for u in result["per_user"]:
        log.info("  user %s: %s", u["user_id_hash"], {k: v for k, v in u.items() if k != "user_id_hash"})
    if not result["ok"]:
        log.error("every scan failed; no Chartink hits were refreshed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
