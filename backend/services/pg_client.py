"""Postgres client — lazy pool initialized from admin-managed secret POSTGRES_URL.

Expected schema (see /tmp/nivesh-ingestion/scripts/create_schema.sql):

    instrument_master (
        instrument_id SERIAL PK, symbol TEXT, instrument_name TEXT,
        instrument_type TEXT CHECK IN ('EQUITY','MUTUAL_FUND','SGB'),
        isin TEXT, exchange TEXT, currency TEXT, is_active BOOL
    )

For mutual funds: `symbol` = AMFI scheme_code, `isin` = isin_growth.
For equities:     `symbol` = NSE symbol.

All queries return plain dicts. If POSTGRES_URL is not configured, every
function returns None / [] so callers can gracefully degrade.
"""
from __future__ import annotations
import logging
from typing import Dict, List, Optional, Any

import asyncpg

from helpers import secrets as _secrets

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None
_last_url: Optional[str] = None


async def get_pool() -> Optional[asyncpg.Pool]:
    """Return an asyncpg pool bound to the current POSTGRES_URL secret.

    If the URL changed (admin updated secret), the pool is rebuilt.
    Returns None if URL is not configured or connection fails.

    Falls back to a local-postgres default so V2 keeps working when the
    admin secret hasn't been hydrated yet (container cold-start / fork).
    """
    global _pool, _last_url
    import os
    url = _secrets.get("POSTGRES_URL") or os.environ.get("POSTGRES_URL")
    if not url:
        # Local default — matches the auto-recovery script's bootstrapped DB.
        url = "postgresql://postgres:postgres@localhost:5432/nivesh"
        logger.warning("POSTGRES_URL secret/env missing — falling back to local default")
    if _pool is not None and _last_url == url:
        return _pool
    # Tear down old pool
    if _pool is not None:
        try:
            await _pool.close()
        except Exception:  # noqa: BLE001
            pass
        _pool = None
    try:
        _pool = await asyncpg.create_pool(
            url, min_size=1, max_size=5, command_timeout=10
        )
        _last_url = url
        logger.info("Postgres pool initialized")
        return _pool
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Postgres pool init failed: {e}")
        _pool = None
        _last_url = None
        return None


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        try:
            await _pool.close()
        finally:
            _pool = None


async def ping() -> Dict[str, Any]:
    """Health check for admin panel."""
    pool = await get_pool()
    if pool is None:
        return {"ok": False, "reason": "POSTGRES_URL not configured"}
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT 1 AS ok, version() AS version")
            return {"ok": True, "version": row["version"]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": str(e)}


async def lookup_instrument(
    *,
    symbol: Optional[str] = None,
    isin: Optional[str] = None,
    instrument_type: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Find one instrument by symbol and/or ISIN. Returns dict or None."""
    pool = await get_pool()
    if pool is None:
        return None
    clauses: List[str] = []
    args: List[Any] = []
    if symbol:
        args.append(symbol)
        clauses.append(f"symbol = ${len(args)}")
    if isin:
        args.append(isin)
        clauses.append(f"isin = ${len(args)}")
    if instrument_type:
        args.append(instrument_type)
        clauses.append(f"instrument_type = ${len(args)}")
    if not clauses:
        return None
    where = " AND ".join(clauses)
    sql = (
        "SELECT instrument_id, symbol, instrument_name, instrument_type, isin, "
        "exchange, currency, is_active "
        f"FROM instrument_master WHERE {where} LIMIT 1"
    )
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, *args)
            return dict(row) if row else None
    except Exception as e:  # noqa: BLE001
        logger.warning(f"pg lookup_instrument failed: {e}")
        return None


async def search_mf_by_name(name_query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Fuzzy MF lookup using ILIKE on instrument_name. Lightweight, no trigram."""
    pool = await get_pool()
    if pool is None or not name_query:
        return []
    pattern = f"%{name_query.strip()}%"
    sql = (
        "SELECT instrument_id, symbol, instrument_name, isin FROM instrument_master "
        "WHERE instrument_type = 'MUTUAL_FUND' AND instrument_name ILIKE $1 "
        "ORDER BY char_length(instrument_name) ASC LIMIT $2"
    )
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, pattern, limit)
            return [dict(r) for r in rows]
    except Exception as e:  # noqa: BLE001
        logger.warning(f"pg search_mf_by_name failed: {e}")
        return []


async def latest_nav(instrument_id: int) -> Optional[Dict[str, Any]]:
    """Most recent NAV for a given MF instrument_id (legacy integer PK)."""
    pool = await get_pool()
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT nav, nav_date FROM mutual_fund_nav "
                "WHERE instrument_id = $1 ORDER BY nav_date DESC LIMIT 1",
                instrument_id,
            )
            if not row:
                return None
            return {"nav": float(row["nav"]), "nav_date": row["nav_date"].isoformat()}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"pg latest_nav failed: {e}")
        return None


async def latest_nav_by_uuid(instrument_id) -> Optional[Dict[str, Any]]:
    """Most recent NAV using new schema: mutual_fund_metadata.nav/nav_date."""
    pool = await get_pool()
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT nav, nav_date FROM mutual_fund_metadata "
                "WHERE instrument_id = $1",
                instrument_id,
            )
            if not row or row["nav"] is None:
                return None
            return {
                "nav": float(row["nav"]),
                "nav_date": row["nav_date"].isoformat() if row["nav_date"] else None,
            }
    except Exception as e:  # noqa: BLE001
        logger.warning(f"pg latest_nav_by_uuid failed: {e}")
        return None
