"""Pure feed-health classification for the NIDP Console "Feeds Live" tab.

Framework-free on purpose (no fastapi / no DB): the admin route imports
`classify_feed` / `feed_dt` from here, and unit tests import them directly
without needing the whole route module (which pulls in fastapi).

The input is one feed row as returned by the NIDP Query API `/feeds`
endpoint (backend/nidp/services/query_api/routers/feeds.py). Notable:
`last_run_status` on that payload comes from `source_registry`, which is
only updated on job *finalize* — so it never holds 'RUNNING' mid-flight.
The authoritative "running now" signal lives in `nidp.job_log` and is
read per-feed via `/jobs/{ingester}/runs`; this classifier only settles
each feed's terminal health for the rollup summary.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Cadences expected to produce a successful run every trading day; only
# these get a "stale" (missed the last trading day) verdict. Monthly /
# quarterly / event / manual feeds are never flagged stale (too noisy).
DAILY_CADENCES = {"daily", "high-freq"}


def feed_dt(iso: Optional[str]) -> Optional[datetime]:
    """Parse an ISO timestamp into a tz-aware datetime; None-safe.
    Naive timestamps are assumed UTC so downstream arithmetic never raises."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def classify_feed(feed: Dict[str, Any], last_trading_day) -> str:
    """Classify one feed row worst-first:

        running | never_run | failing | stale | healthy

    `last_trading_day` is a `date` (the most recent weekday, IST). A
    daily-cadence feed that has not succeeded on/after that day is stale.
    """
    status = (feed.get("last_run_status") or "").upper()
    if status == "RUNNING":
        return "running"
    if not feed.get("last_run_at"):
        return "never_run"
    if (feed.get("consecutive_failures") or 0) > 0 or status == "FAILED":
        return "failing"
    freq = (feed.get("expected_freq") or "").lower()
    if freq in DAILY_CADENCES:
        succ_dt = feed_dt(feed.get("last_success_at"))
        if succ_dt is None or succ_dt.date() < last_trading_day:
            return "stale"
    return "healthy"
