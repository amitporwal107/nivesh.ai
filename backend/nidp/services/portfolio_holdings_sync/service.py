"""Portfolio Holdings Sync — GCS landing zone → NIDP TimescaleDB.

Reads the JSONL file written by Nivesh's portfolio_gcs_export service:
  gs://{bucket}/portfolio/holdings/{date}/holdings.jsonl

No Nivesh Postgres connection required.

Data flow
---------
GCS (JSONL written by Nivesh backend)
            │
            │  this service
            ▼
NIDP Postgres (TimescaleDB)
  portfolio.client_master
  portfolio.user_holdings_snapshot
  portfolio.sync_audit_log
            │
            ▼
  portfolio_intelligence_sync  (triggered with --run-intel)

Configuration
-------------
NIDP_GCS_BUCKET   — GCS bucket (default: nidp-raw-niveshdataintelligence)
NIDP_POSTGRES_URL — NIDP TimescaleDB (used by get_pool())
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import date
from typing import Any, Optional

from nidp.shared.storage.pg import get_pool as _get_nidp_pool

logger = logging.getLogger(__name__)

GCS_BUCKET = os.environ.get("NIDP_GCS_BUCKET", "nidp-raw-niveshdataintelligence")
HOLDINGS_PREFIX = "portfolio/holdings"


# ── GCS helpers ─────────────────────────────────────────────────────

def _gcs_client():
    from google.cloud import storage  # lazy import
    return storage.Client()


def _read_gcs(blob_path: str) -> bytes:
    client = _gcs_client()
    return client.bucket(GCS_BUCKET).blob(blob_path).download_as_bytes()


def _gcs_blob_exists(blob_path: str) -> bool:
    client = _gcs_client()
    return client.bucket(GCS_BUCKET).blob(blob_path).exists()


def _resolve_blob_path(target_date: Optional[date]) -> Optional[str]:
    """Return the GCS blob path for target_date, or latest if None."""
    if target_date:
        return f"{HOLDINGS_PREFIX}/{target_date.isoformat()}/holdings.jsonl"

    latest_path = f"{HOLDINGS_PREFIX}/latest.json"
    if not _gcs_blob_exists(latest_path):
        logger.warning("portfolio_holdings_sync: latest.json not found in GCS")
        return None
    meta = json.loads(_read_gcs(latest_path))
    return meta.get("path")


def _load_records(blob_path: str) -> list[dict[str, Any]]:
    raw = _read_gcs(blob_path)
    records = []
    for line in raw.splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


# ── Hashing (change detection) ───────────────────────────────────────

def _holdings_hash(holdings: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        sorted(holdings, key=lambda r: (r.get("isin") or r.get("symbol") or "")),
        sort_keys=True, default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ── NIDP upserts ────────────────────────────────────────────────────

async def _upsert_client_master(conn, external_user_id: str, client_id: str, display_name: Optional[str]) -> None:
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


async def _upsert_holdings(conn, external_user_id: str, snapshot_date: date, holdings: list[dict]) -> int:
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
                quantity         = EXCLUDED.quantity,
                avg_buy_price    = EXCLUDED.avg_buy_price,
                market_value_inr = EXCLUDED.market_value_inr,
                weight_pct       = EXCLUDED.weight_pct,
                instrument_name  = EXCLUDED.instrument_name
            """,
            external_user_id,
            date.fromisoformat(snapshot_date) if isinstance(snapshot_date, str) else snapshot_date,
            h.get("source_system", "nivesh_cas"),
            h.get("asset_class"), h.get("symbol"), h.get("isin"),
            h.get("amfi_scheme_code"), h.get("instrument_name"),
            h.get("quantity"), h.get("avg_buy_price"),
            h.get("market_value_inr"), h.get("weight_pct"),
        )
        count += int(tag.split()[-1])
    return count


async def _write_audit(conn, sync_run_id, external_user_id, snapshot_date, status,
                       holdings_upserted=0, portfolio_hash=None, error_detail=None) -> None:
    await conn.execute(
        """
        INSERT INTO portfolio.sync_audit_log
            (sync_run_id, external_user_id, snapshot_date, status,
             holdings_upserted, portfolio_hash, error_detail)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        sync_run_id, external_user_id,
        date.fromisoformat(snapshot_date) if isinstance(snapshot_date, str) else snapshot_date,
        status, holdings_upserted, portfolio_hash, error_detail,
    )


async def _update_last_sync(conn, external_user_id: str) -> None:
    await conn.execute(
        "UPDATE portfolio.client_master SET last_sync_at = NOW() WHERE external_user_id = $1",
        external_user_id,
    )


# ── Main entry point ────────────────────────────────────────────────

async def run(target_date: Optional[date] = None) -> dict[str, Any]:
    """Read portfolio JSONL from GCS and upsert into NIDP TimescaleDB."""
    sync_run_id = uuid.uuid4()
    nidp = await _get_nidp_pool()
    stats: dict[str, int] = {"synced": 0, "skipped": 0, "errors": 0, "holdings": 0}

    blob_path = _resolve_blob_path(target_date)
    if not blob_path:
        logger.info("portfolio_holdings_sync: no GCS file found for %s", target_date or "latest")
        return {**stats, "sync_run_id": str(sync_run_id)}

    logger.info("portfolio_holdings_sync: reading gs://%s/%s", GCS_BUCKET, blob_path)
    records = _load_records(blob_path)

    if not records:
        logger.info("portfolio_holdings_sync: empty file")
        return {**stats, "sync_run_id": str(sync_run_id)}

    logger.info("portfolio_holdings_sync: %d client records to process", len(records))

    for rec in records:
        email       = rec["external_user_id"]
        snap_date   = rec["snapshot_date"]
        client_id   = rec.get("client_id", "")
        display_name = rec.get("display_name")
        holdings    = rec.get("holdings", [])

        if not holdings:
            async with nidp.acquire() as conn:
                await _write_audit(conn, sync_run_id, email, snap_date,
                                   "SKIPPED", error_detail="no holdings in export file")
            stats["skipped"] += 1
            continue

        phash = _holdings_hash(holdings)

        try:
            async with nidp.acquire() as conn:
                last = await conn.fetchrow(
                    """
                    SELECT portfolio_hash FROM portfolio.sync_audit_log
                     WHERE external_user_id = $1
                       AND snapshot_date    = $2
                       AND status           = 'SUCCESS'
                     ORDER BY synced_at DESC LIMIT 1
                    """,
                    email,
                    date.fromisoformat(snap_date) if isinstance(snap_date, str) else snap_date,
                )

            if last and last["portfolio_hash"] == phash:
                async with nidp.acquire() as conn:
                    await _write_audit(conn, sync_run_id, email, snap_date,
                                       "SKIPPED", portfolio_hash=phash)
                stats["skipped"] += 1
                continue

            async with nidp.acquire() as conn:
                async with conn.transaction():
                    await _upsert_client_master(conn, email, client_id, display_name)
                    n = await _upsert_holdings(conn, email, snap_date, holdings)
                    await _write_audit(conn, sync_run_id, email, snap_date,
                                       "SUCCESS", holdings_upserted=n, portfolio_hash=phash)
                    await _update_last_sync(conn, email)

            stats["synced"]   += 1
            stats["holdings"] += len(holdings)
            logger.info("portfolio_holdings_sync: synced %s / %s — %d holdings",
                        email, snap_date, len(holdings))

        except Exception as exc:  # noqa: BLE001
            logger.warning("portfolio_holdings_sync: error for %s: %s", email, exc, exc_info=True)
            try:
                async with nidp.acquire() as conn:
                    await _write_audit(conn, sync_run_id, email, snap_date,
                                       "ERROR", error_detail=str(exc)[:500])
            except Exception:  # noqa: BLE001
                pass
            stats["errors"] += 1

    return {
        **stats,
        "sync_run_id": str(sync_run_id),
        "target_date": target_date.isoformat() if target_date else "latest",
        "gcs_source":  blob_path,
    }
