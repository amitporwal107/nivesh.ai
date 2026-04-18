"""Fund data resolver — 3-tier cache with Postgres as durable fallback.

Read chain:  Redis → MongoDB → Postgres aggregate → live Groww scrape
Write chain: Groww scrape → (Redis + Mongo + Postgres tables) atomically

Off-hours gate = NOT (Mon-Fri 09:00-16:00 IST). During market hours, misses
are enqueued in db.scrape_queue for the off-hours drain job (see
routes/mf_data.py admin_drain_queue and Phase 2 APScheduler).
"""
from __future__ import annotations
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Any

from deps import db
from services import groww_client, pg_client, pg_writer, redis_client

logger = logging.getLogger(__name__)

CACHE_TTL_DAYS = 15


# ── Off-hours ────────────────────────────────────────────────────────────
def _is_off_hours(now_utc: Optional[datetime] = None) -> bool:
    n = now_utc or datetime.now(timezone.utc)
    ist = n + timedelta(hours=5, minutes=30)
    if ist.weekday() >= 5:
        return True
    return ist.hour < 9 or ist.hour >= 16


# ── Canonical instrument key ─────────────────────────────────────────────
async def resolve_instrument(
    scheme_name: str,
    scheme_code: Optional[str] = None,
    isin: Optional[str] = None,
) -> Dict[str, Any]:
    master: Optional[Dict[str, Any]] = None
    if isin:
        master = await pg_client.lookup_instrument(isin=isin, instrument_type="MUTUAL_FUND")
    if master is None and scheme_code:
        master = await pg_client.lookup_instrument(symbol=scheme_code, instrument_type="MUTUAL_FUND")
    if master is None and scheme_name:
        hits = await pg_client.search_mf_by_name(scheme_name, limit=1)
        master = hits[0] if hits else None

    canonical_name = (master or {}).get("instrument_name") or scheme_name
    if master and master.get("isin"):
        key = f"ISIN:{master['isin']}"
    elif master and master.get("symbol"):
        key = f"SCHEME:{master['symbol']}"
    elif scheme_code:
        key = f"SCHEME:{scheme_code}"
    else:
        key = f"NAME:{(scheme_name or '').lower().strip()}"

    out: Dict[str, Any] = {"instrument_key": key, "scheme_name": canonical_name}
    if master:
        out["instrument_id"] = str(master["instrument_id"]) if master.get("instrument_id") else None
        out["symbol"] = master.get("symbol")
        out["isin"] = master.get("isin")
    return out


# ── Cache layer ──────────────────────────────────────────────────────────
async def _get_cached(instrument_key: str) -> Optional[Dict[str, Any]]:
    doc = await redis_client.get_holdings(instrument_key)
    if doc is None:
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


async def _persist_all(instrument_key: str, data: Dict[str, Any]) -> None:
    """Write-through to Redis + Mongo + Postgres."""
    payload = {**data, "instrument_key": instrument_key}
    await redis_client.set_holdings(instrument_key, payload)
    await db.fund_holdings_cache.update_one(
        {"instrument_key": instrument_key},
        {"$set": payload},
        upsert=True,
    )
    try:
        await pg_writer.persist_scrape(payload)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"pg_writer.persist_scrape failed for {instrument_key}: {e}")


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
    t0 = time.time()
    resolved = await resolve_instrument(scheme_name, scheme_code, isin)
    key = resolved["instrument_key"]
    canonical_name = resolved["scheme_name"]

    off_hours = _is_off_hours()
    should_scrape_now = allow_scrape if allow_scrape is not None else off_hours

    cached = None if force_refresh else await _get_cached(key)
    if cached and not cached.get("_stale") and cached.get("valid"):
        return {**cached, **resolved, "available": True, "source": "cache"}

    # If we cannot scrape right now, enqueue + serve whatever we have (stale cache or PG)
    if not should_scrape_now:
        if cached and cached.get("valid"):
            await _queue_scrape(key, canonical_name, explicit_slug)
            return {**cached, **resolved, "available": True,
                    "source": "stale-cache", "queued_refresh": True}
        pg_doc = await pg_writer.load_fund_from_pg(
            isin=isin, scheme_code=scheme_code, scheme_name=canonical_name
        )
        if pg_doc and pg_doc.get("valid"):
            await _queue_scrape(key, canonical_name, explicit_slug)
            return {**pg_doc, **resolved, "available": True,
                    "source": "pg-fallback", "queued_refresh": True}
        await _queue_scrape(key, canonical_name, explicit_slug)
        return {**resolved, "available": False,
                "reason": "scrape scheduled for off-hours", "queued": True}

    # Scrape inline
    slug = explicit_slug or await redis_client.get_slug(key)
    fresh = await groww_client.fetch_fund(canonical_name, slug)
    duration_ms = int((time.time() - t0) * 1000)

    if not fresh:
        await pg_writer.log_scrape_attempt(
            instrument_id=None, instrument_name=canonical_name, slug=slug,
            status="failed", duration_ms=duration_ms,
        )
        if cached and cached.get("valid"):
            return {**cached, **resolved, "available": True,
                    "source": "stale-cache", "last_fetch_failed": True}
        pg_doc = await pg_writer.load_fund_from_pg(
            isin=isin, scheme_code=scheme_code, scheme_name=canonical_name
        )
        if pg_doc and pg_doc.get("valid"):
            return {**pg_doc, **resolved, "available": True,
                    "source": "pg-fallback", "last_fetch_failed": True}
        return {**resolved, "available": False, "reason": "groww fetch failed"}

    # Persist the scrape first (creates the PG instrument row)
    await pg_writer.persist_scrape(fresh)
    # Re-resolve so cache + response include fresh instrument_id / isin
    resolved2 = await resolve_instrument(
        fresh.get("scheme_name") or canonical_name,
        fresh.get("metadata", {}).get("scheme_code") or scheme_code,
        fresh.get("metadata", {}).get("isin") or isin,
    )
    enriched = {**fresh, **resolved2}
    await redis_client.set_holdings(key, {**enriched, "instrument_key": key})
    await db.fund_holdings_cache.update_one(
        {"instrument_key": key},
        {"$set": {**enriched, "instrument_key": key}},
        upsert=True,
    )
    if fresh.get("slug"):
        await redis_client.set_slug(key, fresh["slug"])
    await db.scrape_queue.update_one(
        {"instrument_key": key},
        {"$set": {"status": "done", "done_at": datetime.now(timezone.utc).isoformat()}},
    )
    import uuid as _uuid
    iid = resolved2.get("instrument_id")
    try:
        iid_uuid = _uuid.UUID(iid) if iid else None
    except (TypeError, ValueError):
        iid_uuid = None
    await pg_writer.log_scrape_attempt(
        instrument_id=iid_uuid,
        instrument_name=canonical_name,
        slug=fresh.get("slug"),
        status="ok" if fresh.get("valid") else "partial",
        holdings_count=len(fresh.get("holdings") or []),
        validation_issues=", ".join(fresh.get("validation_issues") or []) or None,
        source="fresh",
        duration_ms=duration_ms,
    )
    return {**enriched, "available": True, "source": "fresh"}


# ── Off-hours drain (Phase 2) ────────────────────────────────────────────
async def drain_queue(max_items: int = 20, delay_between_s: float = 3.0,
                      force: bool = False) -> Dict[str, Any]:
    import asyncio
    if not force and not _is_off_hours():
        return {"skipped": True, "reason": "not off-hours"}

    pending = await db.scrape_queue.find(
        {"status": "queued"}, {"_id": 0}
    ).sort("queued_at", 1).limit(max_items).to_list(max_items)

    ok, failed = 0, 0
    for item in pending:
        t0 = time.time()
        try:
            fresh = await groww_client.fetch_fund(
                item["scheme_name"], item.get("slug")
            )
            dur = int((time.time() - t0) * 1000)
            if fresh:
                # PG first, then resolve for instrument_id, then cache the enriched
                await pg_writer.persist_scrape(fresh)
                meta = fresh.get("metadata") or {}
                resolved2 = await resolve_instrument(
                    fresh.get("scheme_name") or item["scheme_name"],
                    meta.get("scheme_code"), meta.get("isin"),
                )
                enriched = {**fresh, **resolved2}
                await redis_client.set_holdings(
                    item["instrument_key"], {**enriched, "instrument_key": item["instrument_key"]}
                )
                await db.fund_holdings_cache.update_one(
                    {"instrument_key": item["instrument_key"]},
                    {"$set": {**enriched, "instrument_key": item["instrument_key"]}},
                    upsert=True,
                )
                if fresh.get("slug"):
                    await redis_client.set_slug(item["instrument_key"], fresh["slug"])
                await db.scrape_queue.update_one(
                    {"instrument_key": item["instrument_key"]},
                    {"$set": {"status": "done",
                              "done_at": datetime.now(timezone.utc).isoformat()}},
                )
                import uuid as _uuid
                iid = resolved2.get("instrument_id")
                try:
                    iid_uuid = _uuid.UUID(iid) if iid else None
                except (TypeError, ValueError):
                    iid_uuid = None
                await pg_writer.log_scrape_attempt(
                    instrument_id=iid_uuid,
                    instrument_name=item["scheme_name"],
                    slug=fresh.get("slug"),
                    status="ok" if fresh.get("valid") else "partial",
                    holdings_count=len(fresh.get("holdings") or []),
                    validation_issues=", ".join(fresh.get("validation_issues") or []) or None,
                    source="drain",
                    duration_ms=dur,
                )
                ok += 1
            else:
                await db.scrape_queue.update_one(
                    {"instrument_key": item["instrument_key"]},
                    {"$set": {"status": "failed",
                              "failed_at": datetime.now(timezone.utc).isoformat()}},
                )
                await pg_writer.log_scrape_attempt(
                    instrument_id=None,
                    instrument_name=item["scheme_name"],
                    slug=item.get("slug"),
                    status="failed",
                    source="drain",
                    duration_ms=dur,
                )
                failed += 1
        except Exception as e:  # noqa: BLE001
            logger.warning(f"drain: {item.get('instrument_key')} error: {e}")
            failed += 1
        await asyncio.sleep(delay_between_s)

    return {"processed": ok + failed, "ok": ok, "failed": failed, "skipped": False}


async def seed_portfolio_queue(user_id: Optional[str] = None) -> Dict[str, Any]:
    """Bulk-enqueue all MF schemes from users' portfolios for off-hours scraping.

    If `user_id` is None, enqueues across ALL users.
    """
    query: Dict[str, Any] = {"instrument_type": "MUTUAL_FUND"}
    if user_id:
        query["user_id"] = user_id
    # Dedupe by (scheme_name, scheme_code)
    pipeline = [
        {"$match": query},
        {"$group": {
            "_id": {"scheme_name": "$scheme_name", "scheme_code": "$scheme_code"},
        }},
    ]
    queued = 0
    async for row in db.holdings.aggregate(pipeline):
        sn = (row["_id"] or {}).get("scheme_name")
        sc = (row["_id"] or {}).get("scheme_code")
        if not sn:
            continue
        resolved = await resolve_instrument(sn, sc, None)
        await _queue_scrape(resolved["instrument_key"], resolved["scheme_name"], None)
        queued += 1
    return {"queued": queued}
