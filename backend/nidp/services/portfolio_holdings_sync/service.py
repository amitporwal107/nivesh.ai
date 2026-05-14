"""Portfolio Holdings Sync — Nivesh Postgres → NIDP Postgres.

Pulls the client portfolio holdings that were written by
cas_snapshot_engine._persist_pg_snapshot() (and optionally by the EOD
snapshot job) from Nivesh's relational store and upserts them into
NIDP's portfolio.user_holdings_snapshot so the intelligence pipeline
has fresh data to work with.

Data flow
---------
Nivesh Postgres
  portfolio_snapshot_master   (client_id, snapshot_date, total_value)
  portfolio_snapshot_holdings (snapshot_id, instrument_id, units, current_value, weight_pct)
  instrument_master           (instrument_id, symbol, isin, instrument_type, instrument_name)
  client_user_map             (client_id → email)                    [migration 020]
            │
            │  this service (two asyncpg pools)
            ▼
NIDP Postgres
  portfolio.client_master         [migration 046]
  portfolio.user_holdings_snapshot [migration 042]
  portfolio.sync_audit_log         [migration 046]
            │
            │  triggered automatically after sync
            ▼
  portfolio_intelligence_sync  (maps → features → user_intelligence_snapshot)

Incremental strategy
--------------------
By default the service syncs the LATEST snapshot for each client (the
row with the highest snapshot_date).  Pass target_date to force a
specific date — useful for backfill runs.

A SHA-256 hash of the holdings payload is stored in sync_audit_log so
re-runs that produce no change are marked SKIPPED without touching the
NIDP tables.

Configuration
-------------
NIVESH_POSTGRES_URL  — connection string for Nivesh Postgres (new env var)
NIDP_POSTGRES_URL    — NIDP Postgres (existing env var, used by get_pool())
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import date
from typing import Any, Optional

import asyncpg

from nidp.shared.storage.pg import get_pool as _get_nidp_pool

logger = logging.getLogger(__name__)

# ── Asset-class normalisation ─────────────────────────────────────
_ASSET_CLASS: dict[str, str] = {
    "EQUITY":      "EQUITY",
    "MUTUAL_FUND": "MF",
    "SGB":         "GOLD",
    "ETF":         "ETF",
    "DEBT":        "DEBT",
    "CASH":        "CASH",
}


def _asset_class(instrument_type: str) -> str:
    return _ASSET_CLASS.get((instrument_type or "").upper(), "OTHER")


# ── Nivesh pool (separate from NIDP pool) ─────────────────────────
_nivesh_pool: Optional[asyncpg.Pool] = None


async def _get_nivesh_pool() -> asyncpg.Pool:
    global _nivesh_pool
    if _nivesh_pool is not None:
        return _nivesh_pool
    url = (
        os.environ.get("NIVESH_POSTGRES_URL")
        or os.environ.get("POSTGRES_URL")
        or "postgresql://postgres:postgres@localhost:5432/nivesh"
    )
    _nivesh_pool = await asyncpg.create_pool(
        url,
        min_size=1,
        max_size=4,
        command_timeout=30,
        statement_cache_size=0,
    )
    logger.info("Nivesh pg pool initialized for portfolio sync")
    return _nivesh_pool


async def _close_nivesh_pool() -> None:
    global _nivesh_pool
    if _nivesh_pool is not None:
        await _nivesh_pool.close()
        _nivesh_pool = None


def _holdings_hash(rows: list[dict[str, Any]]) -> str:
    """Stable SHA-256 over sorted holding rows — detects no-op re-runs."""
    payload = json.dumps(
        sorted(rows, key=lambda r: (r.get("isin") or r.get("symbol") or "")),
        sort_keys=True, default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


async def _fetch_nivesh_snapshots(
    conn: asyncpg.Connection,
    target_date: Optional[date],
) -> list[asyncpg.Record]:
    """Return one row per (client_id, email, snapshot_date) to sync.

    When target_date is given, restrict to that date.
    Otherwise pick the MAX(snapshot_date) per client so we always
    bring in the freshest snapshot.
    """
    if target_date:
        return await conn.fetch(
            """
            SELECT
                psm.client_id,
                cum.email           AS external_user_id,
                cum.display_name,
                psm.snapshot_date,
                psm.total_value,
                psm.total_invested,
                psm.id              AS snapshot_id
            FROM portfolio_snapshot_master psm
            JOIN client_user_map cum ON cum.client_id = psm.client_id
            WHERE psm.snapshot_date = $1
            ORDER BY cum.email
            """,
            target_date,
        )
    else:
        return await conn.fetch(
            """
            SELECT DISTINCT ON (psm.client_id)
                psm.client_id,
                cum.email           AS external_user_id,
                cum.display_name,
                psm.snapshot_date,
                psm.total_value,
                psm.total_invested,
                psm.id              AS snapshot_id
            FROM portfolio_snapshot_master psm
            JOIN client_user_map cum ON cum.client_id = psm.client_id
            ORDER BY psm.client_id, psm.snapshot_date DESC
            """,
        )


async def _fetch_holdings(
    conn: asyncpg.Connection,
    snapshot_id: str,
    total_value: float,
) -> list[dict[str, Any]]:
    """Return normalised holding dicts ready for NIDP upsert."""
    rows = await conn.fetch(
        """
        SELECT
            im.instrument_type,
            im.symbol,
            im.isin,
            im.instrument_name,
            psh.units       AS quantity,
            psh.current_value AS market_value_inr,
            psh.weight_pct
        FROM portfolio_snapshot_holdings psh
        JOIN instrument_master im ON im.instrument_id = psh.instrument_id::uuid
        WHERE psh.snapshot_id = $1
        """,
        snapshot_id,
    )
    tv = float(total_value or 0)
    out: list[dict[str, Any]] = []
    for r in rows:
        itype = (r["instrument_type"] or "").upper()
        mv = float(r["market_value_inr"] or 0)
        out.append({
            "asset_class":       _asset_class(itype),
            "symbol":            r["symbol"] if itype == "EQUITY" else None,
            "isin":              r["isin"],
            "amfi_scheme_code":  r["symbol"] if itype == "MUTUAL_FUND" else None,
            "instrument_name":   r["instrument_name"],
            "quantity":          float(r["quantity"] or 0),
            "avg_buy_price":     None,       # not stored at Nivesh PG level
            "market_value_inr":  mv,
            "weight_pct":        float(r["weight_pct"] or 0) or (
                round(mv / tv * 100, 6) if tv > 0 else 0.0
            ),
            "source_system":     "nivesh_cas",
        })
    return out


async def _upsert_client_master(
    conn: asyncpg.Connection,
    external_user_id: str,
    client_id: str,
    display_name: Optional[str],
) -> None:
    await conn.execute(
        """
        INSERT INTO portfolio.client_master
            (external_user_id, client_id, display_name, updated_at)
        VALUES ($1, $2, $3, NOW())
        ON CONFLICT (external_user_id) DO UPDATE SET
            client_id    = EXCLUDED.client_id,
            display_name = EXCLUDED.display_name,
            updated_at   = NOW()
        """,
        external_user_id, client_id, display_name,
    )


async def _upsert_holdings(
    conn: asyncpg.Connection,
    external_user_id: str,
    snapshot_date: date,
    holdings: list[dict[str, Any]],
) -> int:
    """Upsert all holdings for (external_user_id, snapshot_date).
    Returns count of rows actually inserted/updated."""
    count = 0
    for h in holdings:
        tag = await conn.execute(
            """
            INSERT INTO portfolio.user_holdings_snapshot (
                external_user_id, snapshot_date, source_system,
                asset_class, symbol, isin, amfi_scheme_code,
                instrument_name, quantity, avg_buy_price,
                market_value_inr, weight_pct
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12
            )
            ON CONFLICT (
                external_user_id, snapshot_date,
                COALESCE(isin, ''),
                COALESCE(symbol, ''),
                COALESCE(amfi_scheme_code, ''),
                source_system
            ) DO UPDATE SET
                quantity          = EXCLUDED.quantity,
                avg_buy_price     = EXCLUDED.avg_buy_price,
                market_value_inr  = EXCLUDED.market_value_inr,
                weight_pct        = EXCLUDED.weight_pct,
                instrument_name   = EXCLUDED.instrument_name
            """,
            external_user_id, snapshot_date, h["source_system"],
            h["asset_class"], h["symbol"], h["isin"], h["amfi_scheme_code"],
            h["instrument_name"], h["quantity"], h["avg_buy_price"],
            h["market_value_inr"], h["weight_pct"],
        )
        count += int(tag.split()[-1])
    return count


async def _write_audit(
    conn: asyncpg.Connection,
    sync_run_id: uuid.UUID,
    external_user_id: str,
    snapshot_date: date,
    status: str,
    holdings_upserted: int = 0,
    portfolio_hash: Optional[str] = None,
    error_detail: Optional[str] = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO portfolio.sync_audit_log
            (sync_run_id, external_user_id, snapshot_date, status,
             holdings_upserted, portfolio_hash, error_detail)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        sync_run_id, external_user_id, snapshot_date, status,
        holdings_upserted, portfolio_hash, error_detail,
    )


async def _update_last_sync(conn: asyncpg.Connection, external_user_id: str) -> None:
    await conn.execute(
        "UPDATE portfolio.client_master SET last_sync_at = NOW() WHERE external_user_id = $1",
        external_user_id,
    )


async def run(target_date: Optional[date] = None) -> dict[str, Any]:
    """Execute one portfolio holdings sync pass.

    Returns a summary dict suitable for run_with_job_log reporting.
    """
    sync_run_id = uuid.uuid4()
    nivesh = await _get_nivesh_pool()
    nidp   = await _get_nidp_pool()

    stats: dict[str, int] = {"synced": 0, "skipped": 0, "errors": 0, "holdings": 0}

    async with nivesh.acquire() as n_conn:
        snapshots = await _fetch_nivesh_snapshots(n_conn, target_date)

        if not snapshots:
            logger.info("portfolio_holdings_sync: no snapshots found for %s", target_date or "latest")
            return {**stats, "sync_run_id": str(sync_run_id)}

        logger.info("portfolio_holdings_sync: %d clients to process", len(snapshots))

        for snap in snapshots:
            email       = snap["external_user_id"]
            client_id   = snap["client_id"]
            snap_date   = snap["snapshot_date"]
            snap_id     = snap["snapshot_id"]
            total_value = float(snap["total_value"] or 0)

            try:
                holdings = await _fetch_holdings(n_conn, str(snap_id), total_value)

                if not holdings:
                    async with nidp.acquire() as d_conn:
                        await _write_audit(
                            d_conn, sync_run_id, email, snap_date,
                            "SKIPPED", error_detail="no resolvable holdings in Nivesh",
                        )
                    stats["skipped"] += 1
                    continue

                phash = _holdings_hash(holdings)

                # Check if this exact payload was already synced (skip no-ops).
                async with nidp.acquire() as d_conn:
                    last = await d_conn.fetchrow(
                        """
                        SELECT portfolio_hash FROM portfolio.sync_audit_log
                         WHERE external_user_id = $1
                           AND snapshot_date    = $2
                           AND status           = 'SUCCESS'
                         ORDER BY synced_at DESC
                         LIMIT 1
                        """,
                        email, snap_date,
                    )

                if last and last["portfolio_hash"] == phash:
                    async with nidp.acquire() as d_conn:
                        await _write_audit(
                            d_conn, sync_run_id, email, snap_date,
                            "SKIPPED", portfolio_hash=phash,
                        )
                    stats["skipped"] += 1
                    continue

                # Upsert into NIDP
                async with nidp.acquire() as d_conn:
                    async with d_conn.transaction():
                        await _upsert_client_master(
                            d_conn, email, client_id, snap["display_name"],
                        )
                        n = await _upsert_holdings(d_conn, email, snap_date, holdings)
                        await _write_audit(
                            d_conn, sync_run_id, email, snap_date,
                            "SUCCESS", holdings_upserted=n, portfolio_hash=phash,
                        )
                        await _update_last_sync(d_conn, email)

                stats["synced"]   += 1
                stats["holdings"] += len(holdings)
                logger.info(
                    "portfolio_holdings_sync: synced %s / %s — %d holdings",
                    email, snap_date, len(holdings),
                )

            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "portfolio_holdings_sync: error for %s / %s: %s",
                    email, snap_date, exc, exc_info=True,
                )
                try:
                    async with nidp.acquire() as d_conn:
                        await _write_audit(
                            d_conn, sync_run_id, email, snap_date,
                            "ERROR", error_detail=str(exc)[:500],
                        )
                except Exception:  # noqa: BLE001
                    pass
                stats["errors"] += 1

    return {
        **stats,
        "sync_run_id": str(sync_run_id),
        "target_date": target_date.isoformat() if target_date else "latest",
    }
