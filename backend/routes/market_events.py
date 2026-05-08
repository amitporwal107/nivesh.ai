"""Market Events & Intelligence routes.

Read-only endpoints surfacing today's corporate events, AI signals,
and impact scores from the NIDP intelligence pipeline.

  GET /api/market/events            — today's events + AI signals + confirmation
  GET /api/market/events/tomorrow   — D-1 pre-event briefings for tomorrow
  GET /api/market/signals           — high-confidence AI signal feed (last 7 days)

All data is sourced from nidp.* tables via the shared pg_client pool.
Auth: any logged-in user (global market view, not per-portfolio).

Throttling
----------
Server-side: simple TTL cache (dict) keyed by (endpoint, params).  All users
share the same cache so a burst of simultaneous requests hits Postgres once.
TTL is 60 s for today/tomorrow (data changes only when intelligence pipeline
runs) and 120 s for the signals feed (even more stable).

The cache is process-local and intentionally simple — no Redis needed for
this read volume.  An asyncio.Lock per key prevents thundering-herd on the
first request after expiry.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Request

from deps import get_current_user

# ── TTL cache ──────────────────────────────────────────────────────────────
_cache: dict[str, tuple[float, Any]] = {}   # key → (expires_at, payload)
_locks: dict[str, asyncio.Lock] = {}        # key → lock (prevents thundering herd)

_TTL_EVENTS  = 60    # seconds — today / tomorrow endpoints
_TTL_SIGNALS = 120   # seconds — signals feed (slower moving)


def _cache_get(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry and entry[0] > time.monotonic():
        return entry[1]
    return None


def _cache_set(key: str, value: Any, ttl: int) -> None:
    _cache[key] = (time.monotonic() + ttl, value)


def _get_lock(key: str) -> asyncio.Lock:
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/market", tags=["market_events"])


def _safe_json(v) -> dict | list | None:
    """Safely decode a JSONB column that may be a dict, string, or None."""
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except Exception:
        return None


def _serialise(rows: list) -> list[dict]:
    """Convert asyncpg Record list to JSON-safe dicts."""
    out = []
    for r in rows:
        d = dict(r)
        for k, v in d.items():
            if isinstance(v, date):
                d[k] = v.isoformat()
            elif hasattr(v, "isoformat"):
                d[k] = v.isoformat()
            elif isinstance(v, (dict, list)):
                pass  # already safe
            # JSONB columns come back as dicts from asyncpg — leave them
        # Expand signal_json fields to top-level for easier frontend consumption
        sj = _safe_json(d.get("signal_json")) or {}
        d["summary"]         = sj.get("summary", "")
        d["key_factors"]     = sj.get("key_factors", [])
        d["risks"]           = sj.get("risks", [])
        d["trading_note"]    = sj.get("trading_note", "")
        d["beat_scenario"]   = sj.get("beat_scenario", "")
        d["miss_scenario"]   = sj.get("miss_scenario", "")
        d["key_metrics_watch"] = sj.get("key_metrics_to_watch", [])
        # Expand confirmation_json
        cj = _safe_json(d.get("confirmation_json")) or {}
        d["volume_spike_ratio"]   = cj.get("volume_spike_ratio")
        d["delivery_pct"]         = cj.get("delivery_pct_today")
        d["delivery_spike_ratio"] = cj.get("delivery_spike_ratio")
        d["oi_change_pct"]        = cj.get("oi_change_pct")
        d["oi_signal"]            = cj.get("oi_signal")
        d["put_call_ratio"]       = cj.get("put_call_ratio")
        d["pcr_signal"]           = cj.get("pcr_signal")
        d["sector_return_pct"]    = cj.get("sector_return_pct")
        d["sector_index"]         = cj.get("sector_index")
        d["price_breakout"]       = cj.get("price_breakout", False)
        d["gap_up_pct"]           = cj.get("gap_up_pct")
        d["vs_20d_high_pct"]      = cj.get("vs_20d_high_pct")
        d["confirmation_signals"] = cj.get("signals_hit", [])
        # Remove raw JSON blobs from the response to keep payload small
        d.pop("signal_json", None)
        d.pop("confirmation_json", None)
        out.append(d)
    return out


@router.get("/events")
async def market_events_today(request: Request, date_str: Optional[str] = None):
    """Today's corporate events with impact scores, AI signals, and market confirmation.

    Returns all events from event_calendar for the given date (default: today),
    joined with any available AI signals and scoring data from
    corporate_event_signals. Events without signals are included as
    "pending" so the UI can show the full calendar.

    Cached for 60 s (shared across all users).
    """
    await get_current_user(request)
    target = date_str or date.today().isoformat()
    cache_key = f"events:{target}"

    async with _get_lock(cache_key):
        cached = _cache_get(cache_key)
        if cached is not None:
            logger.debug("market_events_today cache hit key=%s", cache_key)
            return cached

        try:
            from services import pg_client
            pool = await pg_client.get_pool()
            if pool is None:
                return {"events": [], "date": target, "_reason": "no pg pool"}

            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    -- Inner query: DISTINCT ON deduplicates any pre-migration duplicate
                    -- calendar rows, picking the row with the richest signal per
                    -- (symbol, event_type).  Outer query re-sorts for the UI.
                    SELECT * FROM (
                        SELECT DISTINCT ON (ec.symbol, ec.event_type)
                            ec.symbol,
                            ec.company_name,
                            ec.event_type,
                            ec.event_date,
                            ec.period,
                            ec.purpose,
                            ec.source                            AS calendar_source,
                            s.id                                 AS signal_id,
                            s.signal_type,
                            s.sentiment,
                            s.confidence,
                            s.impact_score,
                            s.estimated_move_pct_low,
                            s.estimated_move_pct_high,
                            s.breakout_score,
                            s.breakout_confidence,
                            s.alert_sent,
                            s.analysed_at,
                            s.signal_json,
                            s.confirmation_json
                        FROM nidp.event_calendar ec
                        LEFT JOIN nidp.corporate_event_signals s
                               ON s.symbol      = ec.symbol
                              AND s.event_type  = ec.event_type
                              AND s.event_date  = ec.event_date
                              AND s.signal_type = 'post_event'
                              AND (   s.period IS NOT DISTINCT FROM ec.period
                                   OR s.period IS NULL
                                   OR ec.period IS NULL)
                        WHERE ec.event_date = $1::date
                        ORDER BY
                            ec.symbol,
                            ec.event_type,
                            COALESCE(s.impact_score, 0) DESC,
                            (s.id IS NOT NULL)           DESC
                    ) deduped
                    ORDER BY
                        COALESCE(impact_score, 0) DESC,
                        COALESCE(confidence,   0) DESC,
                        symbol
                    """,
                    target,
                )

            result = {
                "events":   _serialise(list(rows)),
                "date":     target,
                "count":    len(rows),
                "cached_until": int(time.time()) + _TTL_EVENTS,
            }
            _cache_set(cache_key, result, _TTL_EVENTS)
            return result
        except Exception as e:
            logger.error("market_events_today failed: %s", e)
            return {"events": [], "date": target, "_error": str(e)}


@router.get("/events/tomorrow")
async def market_events_tomorrow(request: Request):
    """D-1 pre-event briefings for tomorrow's scheduled results.

    Returns events from event_calendar for tomorrow, joined with
    d1_prep signals generated by the evening D-1 preparation service.

    Cached for 60 s (shared across all users).
    """
    await get_current_user(request)
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    cache_key = f"events_tomorrow:{tomorrow}"

    async with _get_lock(cache_key):
        cached = _cache_get(cache_key)
        if cached is not None:
            logger.debug("market_events_tomorrow cache hit key=%s", cache_key)
            return cached

        try:
            from services import pg_client
            pool = await pg_client.get_pool()
            if pool is None:
                return {"briefings": [], "date": tomorrow, "_reason": "no pg pool"}

            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT
                        ec.symbol,
                        ec.company_name,
                        ec.event_type,
                        ec.event_date,
                        ec.period,
                        s.sentiment,
                        s.confidence,
                        s.estimated_move_pct_low,
                        s.estimated_move_pct_high,
                        s.signal_json,
                        s.analysed_at
                    FROM nidp.event_calendar ec
                    LEFT JOIN nidp.corporate_event_signals s
                           ON s.symbol      = ec.symbol
                          AND s.event_type  = ec.event_type
                          AND s.event_date  = ec.event_date
                          AND s.signal_type = 'd1_prep'
                    WHERE ec.event_date = $1::date
                      AND ec.event_type IN ('quarterly_results', 'board_meeting', 'agm')
                    ORDER BY
                        COALESCE(s.confidence, 0) DESC,
                        ec.symbol
                    """,
                    tomorrow,
                )

            result = {
                "briefings":    _serialise(list(rows)),
                "date":         tomorrow,
                "count":        len(rows),
                "cached_until": int(time.time()) + _TTL_EVENTS,
            }
            _cache_set(cache_key, result, _TTL_EVENTS)
            return result
        except Exception as e:
            logger.error("market_events_tomorrow failed: %s", e)
            return {"briefings": [], "date": tomorrow, "_error": str(e)}


@router.get("/signals")
async def market_signals_feed(
    request: Request,
    days: int = 3,
    min_confidence: float = 60.0,
    sentiment: Optional[str] = None,
    event_type: Optional[str] = None,
):
    """High-confidence AI signal feed for the last N days.

    Filters:
      days            — look-back window (default 3, max 14)
      min_confidence  — minimum AI confidence % (default 60)
      sentiment       — filter by sentiment string (e.g. 'bullish')
      event_type      — filter by event type (e.g. 'order_win')

    Returns signals sorted by impact_score DESC, then confidence DESC.
    """
    await get_current_user(request)
    days = min(days, 14)
    since = (date.today() - timedelta(days=days)).isoformat()

    # Normalise / clamp filter inputs used in cache key and query
    sentiment_clean  = sentiment.strip().lower()[:30]  if sentiment   else None
    event_type_clean = event_type.strip().lower()[:50] if event_type  else None
    cache_key = f"signals:{since}:{min_confidence}:{sentiment_clean}:{event_type_clean}"

    async with _get_lock(cache_key):
        cached = _cache_get(cache_key)
        if cached is not None:
            logger.debug("market_signals_feed cache hit key=%s", cache_key)
            return cached

        try:
            from services import pg_client
            pool = await pg_client.get_pool()
            if pool is None:
                return {"signals": [], "_reason": "no pg pool"}

            # Build parameterised query — no string interpolation of user input
            params: list = [since, min_confidence]
            extra_clauses = ""
            if sentiment_clean:
                params.append(f"%{sentiment_clean}%")
                extra_clauses += f" AND s.sentiment ILIKE ${len(params)}"
            if event_type_clean:
                params.append(event_type_clean)
                extra_clauses += f" AND s.event_type = ${len(params)}"

            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    f"""
                    SELECT
                        s.id                         AS signal_id,
                        s.symbol,
                        s.event_type,
                        s.event_date,
                        s.period,
                        s.signal_type,
                        s.sentiment,
                        s.confidence,
                        s.impact_score,
                        s.estimated_move_pct_low,
                        s.estimated_move_pct_high,
                        s.breakout_score,
                        s.breakout_confidence,
                        s.alert_sent,
                        s.analysed_at,
                        s.signal_json,
                        s.confirmation_json,
                        ec.company_name,
                        ec.purpose
                    FROM nidp.corporate_event_signals s
                    LEFT JOIN nidp.event_calendar ec
                           ON ec.symbol     = s.symbol
                          AND ec.event_type = s.event_type
                          AND ec.event_date = s.event_date
                    WHERE s.event_date >= $1::date
                      AND s.confidence  >= $2
                      AND s.signal_type  = 'post_event'
                      {extra_clauses}
                    ORDER BY
                        s.impact_score  DESC NULLS LAST,
                        s.confidence    DESC NULLS LAST,
                        s.event_date    DESC
                    LIMIT 100
                    """,
                    *params,
                )

            result = {
                "signals":      _serialise(list(rows)),
                "since":        since,
                "count":        len(rows),
                "cached_until": int(time.time()) + _TTL_SIGNALS,
            }
            _cache_set(cache_key, result, _TTL_SIGNALS)
            return result
        except Exception as e:
            logger.error("market_signals_feed failed: %s", e)
            return {"signals": [], "_error": str(e)}
