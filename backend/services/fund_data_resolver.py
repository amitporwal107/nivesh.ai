"""Fund data resolver — Redis → Mongo cache → Groww scrape, with off-hours gating.

Phase 1 uses MongoDB as the cache layer until POSTGRES_URL + REDIS_URL are configured
via the admin Secrets panel. When those become available, swap the cache backends.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Any

from deps import db
from services import groww_client
from helpers import secrets as _secrets

logger = logging.getLogger(__name__)

# TTL for cached fund data (15 days per user spec)
CACHE_TTL_DAYS = 15

# Off-hours = NOT (Mon-Fri 09:00-16:00 IST)
# IST = UTC + 5:30
def _is_off_hours(now_utc: Optional[datetime] = None) -> bool:
    n = now_utc or datetime.now(timezone.utc)
    ist = n + timedelta(hours=5, minutes=30)
    # weekend
    if ist.weekday() >= 5:
        return True
    # before 09:00 or after 16:00 IST
    h = ist.hour
    return h < 9 or h >= 16


async def _get_cached(instrument_key: str) -> Optional[Dict[str, Any]]:
    """Look up cached fund data. Returns None if missing or stale."""
    doc = await db.fund_holdings_cache.find_one(
        {"instrument_key": instrument_key}, {"_id": 0}
    )
    if not doc:
        return None
    fetched = doc.get("fetched_at")
    if fetched:
        try:
            f = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - f).days
            doc["_age_days"] = age_days
            doc["_stale"] = age_days > CACHE_TTL_DAYS
        except Exception:
            doc["_age_days"] = 999
            doc["_stale"] = True
    return doc


async def _persist(instrument_key: str, data: Dict[str, Any]) -> None:
    await db.fund_holdings_cache.update_one(
        {"instrument_key": instrument_key},
        {"$set": {**data, "instrument_key": instrument_key}},
        upsert=True,
    )


async def _queue_scrape(instrument_key: str, scheme_name: str, slug: Optional[str]) -> None:
    """Record a pending scrape for the next off-hours run."""
    await db.scrape_queue.update_one(
        {"instrument_key": instrument_key},
        {
            "$set": {
                "instrument_key": instrument_key,
                "scheme_name": scheme_name,
                "slug": slug,
                "status": "queued",
                "queued_at": datetime.now(timezone.utc).isoformat(),
            }
        },
        upsert=True,
    )


async def get_fund_data(
    instrument_key: str,
    scheme_name: str,
    explicit_slug: Optional[str] = None,
    force_refresh: bool = False,
    allow_scrape: Optional[bool] = None,
) -> Dict[str, Any]:
    """Return fund holdings/sector/split. Strategy:

    1. Fresh cache hit → return
    2. Stale cache + off-hours → refresh, else return stale
    3. No cache + off-hours → scrape inline
    4. No cache + market hours → queue; return {available: False}

    `allow_scrape=True` forces a scrape regardless of off-hours (admin override).
    """
    off_hours = _is_off_hours()
    should_scrape_now = allow_scrape if allow_scrape is not None else off_hours

    cached = None if force_refresh else await _get_cached(instrument_key)

    # Fresh cache hit
    if cached and not cached.get("_stale") and cached.get("valid"):
        return {**cached, "available": True, "source": "cache"}

    # Can we scrape right now?
    if not should_scrape_now:
        if cached and cached.get("valid"):
            # Stale but usable
            return {**cached, "available": True, "source": "stale-cache", "queued_refresh": True}
        await _queue_scrape(instrument_key, scheme_name, explicit_slug)
        return {"available": False, "reason": "scrape scheduled for off-hours", "queued": True}

    # Scrape inline
    fresh = await groww_client.fetch_fund(scheme_name, explicit_slug)
    if not fresh:
        # Scrape failed — return stale if we have it
        if cached and cached.get("valid"):
            return {**cached, "available": True, "source": "stale-cache", "last_fetch_failed": True}
        return {"available": False, "reason": "groww fetch failed", "scheme_name": scheme_name}

    await _persist(instrument_key, fresh)
    # Clear from queue if it was queued
    await db.scrape_queue.update_one(
        {"instrument_key": instrument_key},
        {"$set": {"status": "done", "done_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {**fresh, "available": True, "source": "fresh"}


async def drain_queue(max_items: int = 20, delay_between_s: float = 3.0) -> Dict[str, Any]:
    """Process pending scrape queue. Should be invoked by a scheduler in off-hours.

    Polite pacing: `delay_between_s` between requests.
    Returns summary.
    """
    import asyncio
    if not _is_off_hours():
        return {"skipped": True, "reason": "not off-hours"}

    pending = await db.scrape_queue.find(
        {"status": "queued"}, {"_id": 0}
    ).sort("queued_at", 1).limit(max_items).to_list(max_items)

    ok, failed = 0, 0
    for item in pending:
        try:
            fresh = await groww_client.fetch_fund(
                item["scheme_name"], item.get("slug")
            )
            if fresh:
                await _persist(item["instrument_key"], fresh)
                await db.scrape_queue.update_one(
                    {"instrument_key": item["instrument_key"]},
                    {"$set": {"status": "done", "done_at": datetime.now(timezone.utc).isoformat()}},
                )
                ok += 1
            else:
                await db.scrape_queue.update_one(
                    {"instrument_key": item["instrument_key"]},
                    {"$set": {"status": "failed", "failed_at": datetime.now(timezone.utc).isoformat()}},
                )
                failed += 1
        except Exception as e:
            logger.warning(f"drain: {item.get('instrument_key')} error: {e}")
            failed += 1
        await asyncio.sleep(delay_between_s)

    return {"processed": ok + failed, "ok": ok, "failed": failed, "skipped": False}
