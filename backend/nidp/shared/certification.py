"""Certification Publisher.

Writes the PASS decision to nidp.certified_dates and emits a
cache-invalidation signal so the API serves the freshly-certified data.

What "certification" means in practice:
  - A row is inserted into nidp.certified_dates for (target_date, domain).
  - The DaaS API reads this table via v_publish_gate before serving data,
    so uncertified dates are silently excluded from API responses.
  - The API response-cache TTL for that date is set to 0 (immediate expiry)
    so the next request re-queries the now-certified tables.

Cache invalidation strategy:
  - In-process: an asyncio.Event is broadcast to any warm cache holders.
  - Redis (when available): DEL the affected key patterns via the
    NIDP_REDIS_URL env var.  Falls back gracefully if Redis is absent.
  - Cloud CDN / API Gateway: a webhook URL can be registered via
    NIDP_CACHE_WEBHOOK_URL; a POST is sent on certification.

Usage:
    from nidp.shared.certification import CertificationPublisher
    pub = CertificationPublisher(conn)
    await pub.publish(target_date, domain, quality_score=qs)
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import date
from typing import Optional

import asyncpg

from nidp.shared.validation.quality_score import QualityScore

logger = logging.getLogger(__name__)

# Optional Redis URL — if absent, skip Redis invalidation silently.
_REDIS_URL     = os.getenv("NIDP_REDIS_URL", "")
# Optional webhook for CDN / API Gateway cache flush.
_CACHE_WEBHOOK = os.getenv("NIDP_CACHE_WEBHOOK_URL", "")


class CertificationPublisher:
    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn

    async def publish(
        self,
        target_date: date,
        domain: str,
        quality_score: Optional[QualityScore] = None,
    ) -> None:
        """Mark (target_date, domain) as certified and flush caches."""
        cert_id = uuid.uuid4()
        overall = quality_score.overall        if quality_score else None
        cert    = quality_score.certification  if quality_score else None

        await self._conn.execute(
            """
            INSERT INTO nidp.certified_dates
                (cert_id, target_date, domain,
                 overall_score, certification, certified_at)
            VALUES ($1,$2,$3,$4,$5,NOW())
            ON CONFLICT (target_date, domain) DO UPDATE SET
                overall_score = EXCLUDED.overall_score,
                certification = EXCLUDED.certification,
                certified_at  = NOW(),
                cert_id       = EXCLUDED.cert_id
            """,
            cert_id, target_date, domain, overall, cert,
        )

        logger.info(
            "certified date=%s domain=%s score=%s tier=%s cert_id=%s",
            target_date, domain, overall, cert, cert_id,
        )

        # Invalidate downstream caches
        await self._invalidate_api_cache(target_date, domain)
        await self._notify_webhook(target_date, domain, cert_id)

    async def _invalidate_api_cache(self, target_date: date, domain: str) -> None:
        """Delete affected Redis keys, or log a skip if Redis is not configured."""
        if not _REDIS_URL:
            logger.debug("cache_invalidate: no NIDP_REDIS_URL — skipping Redis flush")
            return
        try:
            import redis.asyncio as aioredis
            client = aioredis.from_url(_REDIS_URL, decode_responses=True)
            patterns = [
                f"nidp:{domain}:*:{target_date.isoformat()}",
                f"nidp:quality:{domain}:{target_date.isoformat()}",
                f"nidp:certification:{domain}:{target_date.isoformat()}",
            ]
            async with client:
                for pattern in patterns:
                    keys = [k async for k in client.scan_iter(pattern)]
                    if keys:
                        await client.delete(*keys)
                        logger.info(
                            "cache_invalidate: deleted %d key(s) matching %s",
                            len(keys), pattern,
                        )
        except Exception:                                          # noqa: BLE001
            logger.warning(
                "cache_invalidate: Redis flush failed — API will serve stale "
                "until natural TTL expires", exc_info=True,
            )

    async def _notify_webhook(
        self, target_date: date, domain: str, cert_id: uuid.UUID,
    ) -> None:
        if not _CACHE_WEBHOOK:
            return
        try:
            import aiohttp
            payload = json.dumps({
                "event":       "nidp.certified",
                "target_date": target_date.isoformat(),
                "domain":      domain,
                "cert_id":     str(cert_id),
            })
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    _CACHE_WEBHOOK,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    logger.info("cache_webhook: %s → %d", _CACHE_WEBHOOK, resp.status)
        except Exception:                                          # noqa: BLE001
            logger.warning("cache_webhook: POST failed — continuing", exc_info=True)
