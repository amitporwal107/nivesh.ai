"""Fund data resolver — ISIN-aware lookups with Redis + Mongo tiered cache.

Flow:
  1. Resolve instrument in Postgres `instrument_master` (by ISIN, scheme_code,
     or fuzzy name). Canonical cache key = ISIN if available, else scheme_code,
     else normalised scheme_name.
  2. Check Redis cache (primary) -> Mongo cache (fallback) for holdings.
  3. If fresh hit → return.
  4. If off-hours or admin override → scrape Groww inline, persist to both caches.
  5. If market hours → enqueue in db.scrape_queue, return {available: False}.

Cache TTL = 15 days. Off-hours = outside Mon-Fri 09:00-16:00 IST.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Any

from deps import db
from services import groww_client, pg_client, redis_client

logger = logging.getLogger(__name__)

CACHE_TTL_DAYS = 15


# ── Off-hours gate ───────────────────────────────────────────────────────
def _is_off_hours(now_utc: Optional[datetime] = None) -> bool:
    n = now_utc or datetime.now(timezone.utc)
    ist = n + timedelta(hours=5, minutes=30)
    if ist.weekday() >= 5:          # Sat/Sun
        return True
    return ist.hour < 9 or ist.hour >= 16


# ── Instrument resolution ────────────────────────────────────────────────
async def resolve_instrument(
    scheme_name: str,
    scheme_code: Optional[str] = None,
    isin: Optional[str] = None,
) -> Dict[str, Any]:
    """Look up a mutual fund in Postgres. Returns dict with canonical key.

    Keys always present: `instrument_key`, `scheme_name`.
    Keys present only on pg hit: `instrument_id`, `symbol`, `isin`.
    """
    master: Optional[Dict[str, Any]] = None
    # Prefer ISIN → scheme_code → fuzzy name
    if isin:
        master = await pg_client.lookup_instrument(isin=isin, instrument_type="MUTUAL_FUND")
    if master is None and scheme_code:
        master = await pg_client.lookup_instrument(symbol=scheme_code, instrument_type="MUTUAL_FUND")
    if master is None and scheme_name:
        hits = await pg_client.search_mf_by_name(scheme_name, limit=1)
        if hits:
            master = hits[0]

    canonical_name = (master or {}).get("instrument_name") or scheme_name

    if master and master.get("isin"):
        key = f"ISIN:{master['isin']}"
    elif master and master.get("symbol"):
        key = f"SCHEME:{master['symbol']}"
    elif scheme_code:
        key = f"SCHEME:{scheme_code}"
    else:
        key = f"NAME:{(scheme_name or '').lower().strip()}"

    return {
        "instrument_key": key,
        "scheme_name": canonical_name,
        **({"instrument_id": master["instrument_id"],
            "symbol": master.get("symbol"),
            "isin": master.get("isin")} if master else {}),
    }


# ── Cache layer (Redis primary, Mongo fallback) ──────────────────────────
async def _get_cached(instrument_key: str) -> Optional[Dict[str, Any]]:
    # 1. Redis
    doc = await redis_client.get_holdings(instrument_key)
    if doc is None:
        # 2. Mongo
        doc = await db.fund_holdings_cache.find_one(
            {"instrument_key": instrument_key}, {"_id": 0}
        )
    if not doc:
        return None
    fetched = doc.get("fetched_at")
    age_days = 999
    if fetched:
        try:
            f = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - f).days
        except Exception:  # noqa: BLE001
            pass
    doc["_age_days"] = age_days
    doc["_stale"] = age_days > CACHE_TTL_DAYS
    return doc


async def _persist(instrument_key: str, data: Dict[str, Any]) -> None:
    """Write to both Redis (primary, with TTL) and Mongo (durable fallback)."""
    payload = {**data, "instrument_key": instrument_key}
    await redis_client.set_holdings(instrument_key, payload)
    await db.fund_holdings_cache.update_one(
        {"instrument_key": instrument_key},
        {"$set": payload},
        upsert=True,
    )


async def _queue_scrape(instrument_key: str, scheme_name: str, slug: Optional[str]) -> None:
    await db.scrape_queue.update_one(
        {"instrument_key": instrument_key},
        {"$set": {
            "instrument_key": instrument_key,
            "scheme_name": scheme_name,
            "slug": slug,
            "status": "queued",
            "queued_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )


# ── Public API ───────────────────────────────────────────────────────────
async def get_fund_data(
    scheme_name: str,
    scheme_code: Optional[str] = None,
    isin: Optional[str] = None,
    explicit_slug: Optional[str] = None,
    force_refresh: bool = False,
    allow_scrape: Optional[bool] = None,
) -> Dict[str, Any]:
    """Resolve → cache-check → scrape (if permitted) → persist."""
    resolved = await resolve_instrument(scheme_name, scheme_code, isin)
    key = resolved["instrument_key"]
    canonical_name = resolved["scheme_name"]

    off_hours = _is_off_hours()
    should_scrape_now = allow_scrape if allow_scrape is not None else off_hours

    cached = None if force_refresh else await _get_cached(key)
    if cached and not cached.get("_stale") and cached.get("valid"):
        return {**cached, **resolved, "available": True, "source": "cache"}

    if not should_scrape_now:
        if cached and cached.get("valid"):
            await _queue_scrape(key, canonical_name, explicit_slug)
            return {**cached, **resolved, "available": True,
                    "source": "stale-cache", "queued_refresh": True}
        await _queue_scrape(key, canonical_name, explicit_slug)
        return {**resolved, "available": False,
                "reason": "scrape scheduled for off-hours", "queued": True}

    # Scrape inline — honour cached slug if we've resolved it before
    slug = explicit_slug or await redis_client.get_slug(key)
    fresh = await groww_client.fetch_fund(canonical_name, slug)
    if not fresh:
        if cached and cached.get("valid"):
            return {**cached, **resolved, "available": True,
                    "source": "stale-cache", "last_fetch_failed": True}
        return {**resolved, "available": False,
                "reason": "groww fetch failed"}

    await _persist(key, fresh)
    if fresh.get("slug"):
        await redis_client.set_slug(key, fresh["slug"])
    await db.scrape_queue.update_one(
        {"instrument_key": key},
        {"$set": {"status": "done", "done_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {**fresh, **resolved, "available": True, "source": "fresh"}


# ── Off-hours queue drain ─────────────────────────────────────────────────
async def drain_queue(max_items: int = 20, delay_between_s: float = 3.0) -> Dict[str, Any]:
    """Process pending scrape queue during off-hours (APScheduler target)."""
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
                if fresh.get("slug"):
                    await redis_client.set_slug(item["instrument_key"], fresh["slug"])
                await db.scrape_queue.update_one(
                    {"instrument_key": item["instrument_key"]},
                    {"$set": {"status": "done",
                              "done_at": datetime.now(timezone.utc).isoformat()}},
                )
                ok += 1
            else:
                await db.scrape_queue.update_one(
                    {"instrument_key": item["instrument_key"]},
                    {"$set": {"status": "failed",
                              "failed_at": datetime.now(timezone.utc).isoformat()}},
                )
                failed += 1
        except Exception as e:  # noqa: BLE001
            logger.warning(f"drain: {item.get('instrument_key')} error: {e}")
            failed += 1
        await asyncio.sleep(delay_between_s)

    return {"processed": ok + failed, "ok": ok, "failed": failed, "skipped": False}
