"""Daily feed health check.

Queries nidp.job_log for the last 24h and reports any feed that has NO
COMPLETED (status='OK') run. Emits a structured JSON summary to stdout
which Cloud Logging picks up. Exits 1 if any expected feed is missing
so Cloud Run flags the job FAILED — which surfaces in monitoring.

EXPECTED_FEEDS list below mirrors the daily-run feeds. Update when you
add/remove a feed. Weekly/monthly feeds get longer windows.

Environment:
    NIDP_HEALTH_LOOKBACK_HOURS  (default 30)  — how far back to look
    NIDP_HEALTH_FAIL_ON_GAPS    (default 1)   — exit 1 if gaps found

Usage:
    python -m nidp.services.feed_health_check
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)

# Feeds expected to land at least once per WINDOW_HOURS.
# (ingester_name, max_age_hours, severity)
# severity: ERROR = page on miss; WARN = log only.
EXPECTED_FEEDS: list[tuple[str, int, str]] = [
    # Daily NSE feeds (run every weekday)
    ("bhavcopy",                  30, "ERROR"),
    ("delivery",                  30, "ERROR"),
    ("index_close",               30, "ERROR"),
    ("fno_bhavcopy",              30, "ERROR"),
    ("fii_dii",                   30, "ERROR"),
    ("bulk_deals",                30, "WARN"),
    ("block_deals",               30, "WARN"),
    ("corporate_actions",         30, "WARN"),
    # Daily AMFI feeds
    ("amfi_nav",                  30, "ERROR"),
    ("amfi_nav_history",          30, "WARN"),
    # Macro / weekly
    ("rbi_yields",                72, "WARN"),
    ("fred_macro",                30, "WARN"),
    # Master refresh (less frequent)
    ("nse_calendar",             168, "WARN"),
    ("nse_equity_master",        168, "WARN"),
    ("index_constituents",       168, "WARN"),
    # Derivatives
    ("price_adjuster",            30, "ERROR"),
]


async def check() -> dict:
    fail_on_gaps = os.environ.get("NIDP_HEALTH_FAIL_ON_GAPS", "1") == "1"

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Latest OK run per ingester
        rows = await conn.fetch(
            """
            SELECT ingester,
                   MAX(finished_at) AS last_ok
              FROM nidp.job_log
             WHERE status = 'OK'
               AND finished_at > NOW() - INTERVAL '14 days'
             GROUP BY ingester
            """
        )
        last_ok = {r["ingester"]: r["last_ok"] for r in rows}

        # Recent FAILED rows for context
        failed_rows = await conn.fetch(
            """
            SELECT ingester, target_date, started_at, error_message
              FROM nidp.job_log
             WHERE status = 'FAILED'
               AND started_at > NOW() - INTERVAL '36 hours'
             ORDER BY started_at DESC
             LIMIT 100
            """
        )

    now = datetime.now(timezone.utc)
    gaps: list[dict] = []
    healthy: list[dict] = []
    for ing, max_age_h, severity in EXPECTED_FEEDS:
        ok_ts = last_ok.get(ing)
        if ok_ts is None:
            gaps.append({
                "ingester": ing,
                "severity": severity,
                "reason":   f"no OK run in last 14 days",
                "last_ok":  None,
            })
            continue
        age_h = (now - ok_ts).total_seconds() / 3600
        if age_h > max_age_h:
            gaps.append({
                "ingester": ing,
                "severity": severity,
                "reason":   f"stale by {age_h:.1f}h (limit {max_age_h}h)",
                "last_ok":  ok_ts.isoformat(),
            })
        else:
            healthy.append({
                "ingester": ing,
                "last_ok":  ok_ts.isoformat(),
                "age_h":    round(age_h, 1),
            })

    error_gaps = [g for g in gaps if g["severity"] == "ERROR"]
    warn_gaps  = [g for g in gaps if g["severity"] == "WARN"]

    summary = {
        "checked_at":         now.isoformat(),
        "expected_feeds":     len(EXPECTED_FEEDS),
        "healthy":            len(healthy),
        "gaps_total":         len(gaps),
        "gaps_error":         len(error_gaps),
        "gaps_warn":          len(warn_gaps),
        "gap_details":        gaps,
        "recent_failures":    [
            {
                "ingester":      r["ingester"],
                "target_date":   r["target_date"].isoformat() if r["target_date"] else None,
                "started_at":    r["started_at"].isoformat(),
                "error_message": (r["error_message"] or "")[:200],
            }
            for r in failed_rows
        ],
    }

    # Single-line JSON for Cloud Logging structured output
    print(json.dumps(summary, default=str))

    if error_gaps:
        logger.error("FEED HEALTH: %d ERROR-level gaps", len(error_gaps))
        for g in error_gaps:
            logger.error("  GAP %s severity=%s reason=%s last_ok=%s",
                         g["ingester"], g["severity"], g["reason"],
                         g["last_ok"])
    elif warn_gaps:
        logger.warning("FEED HEALTH: %d WARN-level gaps", len(warn_gaps))
    else:
        logger.info("FEED HEALTH: all %d feeds healthy", len(healthy))

    if fail_on_gaps and error_gaps:
        sys.exit(1)

    return summary


def main() -> None:
    setup_logging(service="feed_health_check")
    asyncio.run(check())


if __name__ == "__main__":
    main()
