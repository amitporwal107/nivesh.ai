#!/usr/bin/env python3
"""check_nidp_feed_health.py — quick stale/failing NIDP feed audit.

Calls the NIDP Query API's `/feeds` endpoint (same data the admin NIDP
page renders) and prints a punch-list of feeds that look broken:

  • never run                            → feed registered but no job_log row
  • last_run_status = FAILED              → most recent run errored
  • stale (no success in N days)          → expected cadence vs reality

Designed to answer the operator question:
    "Are all the NIDP daily jobs actually running, or is something
    silently broken?"
in one command, without scrolling Grafana or 35 feed-detail panels.

Requires NIDP_QUERY_API_URL + NIDP_QUERY_API_TOKEN (already configured
on the nivesh-backend container — same secrets the admin NIDP page uses).

Usage:
    docker exec nivesh-backend python -m scripts.check_nidp_feed_health
    docker exec nivesh-backend python -m scripts.check_nidp_feed_health --json
    docker exec nivesh-backend python -m scripts.check_nidp_feed_health --stale-days 2

Exit codes:
  0 — all feeds healthy
  2 — at least one feed flagged (stale / failed / never-run)
  1 — fatal error reaching the NIDP Query API
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

log = logging.getLogger("nidp_health")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


# Default per-cadence staleness thresholds. A feed is "stale" if it
# hasn't succeeded in more than this many days. Tuned to be slightly
# more forgiving than the cadence — daily feeds can lag 1 day, weekly
# can lag 8, etc., before they're considered broken.
STALE_THRESHOLD_BY_CADENCE = {
    "daily":     1,
    "weekly":    8,
    "monthly":   32,
    "quarterly": 95,
    "high-freq": 1,
    "event":     None,    # event-driven feeds aren't expected to fire daily
    "manual":    None,
}


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # NIDP serialises timestamps with trailing 'Z' or +00:00; both fine.
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


async def main(stale_days_override: int | None, as_json: bool) -> int:
    from services import nidp_query_client as nq  # noqa: E402

    if not nq.is_configured():
        log.error(
            "NIDP_QUERY_API_URL / NIDP_QUERY_API_TOKEN not configured — "
            "check Admin → Secrets, or run inside the nivesh-backend container.",
        )
        return 1

    try:
        payload = await nq.get_feeds()
    except nq.NidpQueryClientError as e:
        log.error("NIDP Query API call failed: %s", e.detail)
        return 1
    except Exception as e:  # noqa: BLE001
        log.error("Unexpected error reaching NIDP Query API: %s", e)
        return 1

    rows = payload.get("feeds") or []
    if not rows:
        log.error("NIDP Query API returned no feeds — has migration 022 been applied?")
        return 1

    now = datetime.now(timezone.utc)
    flagged: list[dict] = []
    healthy: list[str] = []
    skipped: list[str] = []   # cadence=event/manual, no staleness check

    for r in rows:
        ingester = r.get("ingester") or "?"
        cadence = (r.get("expected_freq") or "").lower() or "daily"
        threshold = (stale_days_override
                     if stale_days_override is not None
                     else STALE_THRESHOLD_BY_CADENCE.get(cadence))
        last_success_at = _parse_iso(r.get("last_success_at"))
        last_run_status = r.get("last_run_status")
        consec_fail = r.get("consecutive_failures") or 0
        stale_days = (now - last_success_at).days if last_success_at else None

        issues: list[str] = []
        if last_success_at is None and (r.get("success_count") or 0) == 0:
            issues.append("never-succeeded")
        if last_run_status == "FAILED":
            issues.append("last_run_failed")
        if consec_fail >= 3:
            issues.append(f"consec_fail={consec_fail}")
        if threshold is not None and stale_days is not None and stale_days > threshold:
            issues.append(f"stale ({stale_days}d > {threshold}d)")

        if issues:
            flagged.append({
                "ingester":        ingester,
                "cadence":         cadence,
                "issues":          issues,
                "last_run_status": last_run_status,
                "last_run_at":     r.get("last_run_at"),
                "last_success_at": r.get("last_success_at"),
                "consec_failures": consec_fail,
                "last_error":      (r.get("last_error_message") or "")[:200],
            })
        elif threshold is None:
            skipped.append(ingester)
        else:
            healthy.append(ingester)

    if as_json:
        print(json.dumps({
            "checked_at": now.isoformat(),
            "total":      len(rows),
            "healthy":    healthy,
            "skipped":    skipped,
            "flagged":    flagged,
        }, indent=2, default=str))
        return 0 if not flagged else 2

    # Human-readable summary
    print()
    print(f"NIDP feed health — checked {now.isoformat(timespec='seconds')}")
    print(f"  total registered : {len(rows)}")
    print(f"  healthy          : {len(healthy)}")
    print(f"  event/manual     : {len(skipped)}  (cadence not time-based)")
    print(f"  flagged          : {len(flagged)}")
    print()
    if not flagged:
        print("  ✓ All time-based feeds are running on schedule.")
        return 0

    print("  Flagged feeds (need attention):")
    print(f"    {'INGESTER':<32} {'CADENCE':<10} {'LAST_OK':<22} {'STATUS':<8} ISSUES")
    print(f"    {'-' * 32} {'-' * 10} {'-' * 22} {'-' * 8} ------")
    for f in flagged:
        last_ok = f["last_success_at"] or "—"
        print(
            f"    {f['ingester']:<32} "
            f"{f['cadence']:<10} "
            f"{last_ok[:22]:<22} "
            f"{(f['last_run_status'] or '—'):<8} "
            f"{', '.join(f['issues'])}"
        )
        if f["last_error"]:
            print(f"        ↳ last error: {f['last_error']}")
    print()
    print("  Investigate further:")
    print("    Admin UI: https://niveshcopilot.com/admin#nidp")
    print("    Logs:     bash /opt/nidp/repo/backend/nidp/deploy/gcp/fetch_logs.sh <job-name> 24h")
    return 2


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="NIDP feed health audit")
    p.add_argument("--json", action="store_true", help="Emit JSON instead of human-readable table")
    p.add_argument("--stale-days", type=int, default=None,
                    help="Override the per-cadence stale threshold (days)")
    args = p.parse_args()
    sys.exit(asyncio.run(main(args.stale_days, args.json)))
