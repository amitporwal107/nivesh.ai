"""Bridge: read V3 portfolio_ingestion holdings for a V2 user_id.

When a user onboards via the V4 flow (POST /api/cas/sdk-callback on the
portfolio_ingestion service), their holdings land in
portfolio_ingestion.holdings (V3 Postgres) but NOT in V2's MongoDB
db.holdings — the two services are independent.

This module fills that gap for every V2 read path that queries db.holdings.
It talks to the same Postgres instance via the existing V2 pg_client pool.

Usage pattern in V2 services:

    all_holdings = await db.holdings.find(...).to_list(N)
    if not all_holdings:
        from services.pi_bridge import pi_holdings_for_user
        all_holdings = await pi_holdings_for_user(user_id)

The returned dicts are shaped identically to V2 MongoDB holding documents
so no other code changes are needed downstream.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import asyncpg

log = logging.getLogger(__name__)

_pi_pool: "asyncpg.Pool | None" = None


async def _get_pi_pool() -> "asyncpg.Pool | None":
    """Return (and lazily create) an asyncpg pool for V3 Postgres (PI_POSTGRES_URL)."""
    global _pi_pool
    if _pi_pool is not None:
        return _pi_pool
    url = os.environ.get("PI_POSTGRES_URL")
    if not url:
        log.warning("pi_bridge: PI_POSTGRES_URL not set — bridge disabled")
        return None
    try:
        _pi_pool = await asyncpg.create_pool(
            url, min_size=1, max_size=3, command_timeout=10,
            statement_cache_size=0,
        )
        log.info("pi_bridge: V3 Postgres pool opened")
        return _pi_pool
    except Exception as exc:  # noqa: BLE001
        log.warning("pi_bridge: failed to open V3 Postgres pool: %s", exc)
        return None


# V3 asset_class → V2 asset_type
_CLASS_MAP: dict[str, str] = {
    "mutual_fund":         "mutual_fund",
    "equity":              "equity",
    "etf":                 "etf",
    "nps":                 "nps",
    "insurance":           "insurance",
    "corporate_bond":      "debt",
    "government_security": "debt",
    "aif":                 "aif",
}


async def pi_holdings_for_user(user_id: str) -> list[dict[str, Any]]:
    """Return active-snapshot holdings from V3 Postgres shaped like V2 Mongo docs.

    Returns [] on any error so callers can treat absence as a soft fallback.
    """
    pool = await _get_pi_pool()
    if pool is None:
        return []
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT h.asset_class, h.isin, h.amfi_code, h.folio,
                       h.scheme_code, h.amc, h.name,
                       h.quantity::float AS quantity,
                       h.value::float   AS value
                  FROM portfolio_ingestion.holdings h
                  JOIN portfolio_ingestion.snapshots s ON s.id = h.snapshot_id
                  JOIN portfolio_ingestion.users     u ON u.pan_hash = s.pan_hash
                 WHERE u.external_id = $1
                   AND s.is_active   = true
                 ORDER BY h.value DESC
                """,
                user_id,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("pi_bridge: Postgres query failed for user %s: %s", user_id, exc)
        return []

    out: list[dict[str, Any]] = []
    for r in rows:
        qty = r["quantity"] or 0.0
        val = r["value"] or 0.0
        # current_price: V3 stores the total value, not unit price.
        # Reconstruct so V2's `quantity * current_price` math still works.
        current_price = (val / qty) if qty > 0 else 0.0
        out.append({
            "user_id":      user_id,
            "asset_type":   _CLASS_MAP.get(r["asset_class"], r["asset_class"]),
            "name":         r["name"],
            "isin":         r["isin"],
            "folio_number": r["folio"],
            "amc":          r["amc"],
            "scheme_code":  r["scheme_code"],
            "amfi_code":    r["amfi_code"],
            "quantity":     qty,
            "current_price": current_price,
            # instrument_id is not available in V3; V3-scoring path falls back
            # to scheme_name matching which works without this field.
            "instrument_id": None,
        })

    if out:
        log.info(
            "pi_bridge: returned %d holdings from V3 Postgres for user %s",
            len(out), user_id,
        )
    return out
