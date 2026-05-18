"""Portfolio Transactions Sync — GCS landing zone → NIDP TimescaleDB.

Reads the JSONL written by the Nivesh-side ``export_cas_transactions_to_gcs``
exporter and upserts into ``portfolio.user_transactions``.

JSONL line shape (one per CAS transaction, NOT per user):
  {
    "schema_version":   "1",
    "exported_at":      "...",
    "external_user_id": "<email>",
    "client_id":        "<user uuid>",
    "txn_date":         "YYYY-MM-DD",
    "txn_type":         "PURCHASE | SIP_PURCHASE | REDEMPTION | ...",
    "folio":            "...",
    "isin":             "...",
    "amfi_scheme_code": "...",
    "symbol":           "...",
    "instrument_name":  "...",
    "asset_class":      "EQUITY | MF | ETF | DEBT | CASH | OTHER",
    "units":             123.456,
    "amount_inr":       12345.67,
    "nav_or_price":     97.45,
    "cas_file_id":      "..."
  }

Idempotency: the natural key on ``portfolio.user_transactions``
(external_user_id, txn_date, txn_type, folio, isin, units, amount_inr,
source_system) means re-runs are safe; CONFLICT DO UPDATE refreshes
metadata only.

Env vars:
  NIDP_GCS_BUCKET   — default 'nidp-raw-niveshdataintelligence'
  NIDP_POSTGRES_URL — TimescaleDB used by ``get_pool()``
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import date
from typing import Any, Optional

from nidp.shared.storage.pg import get_pool as _get_nidp_pool

logger = logging.getLogger(__name__)

GCS_BUCKET = os.environ.get("NIDP_GCS_BUCKET", "nidp-raw-niveshdataintelligence")
TXN_PREFIX = "portfolio/transactions"

_DATASET = "transactions"

# Keep in lock-step with services/portfolio_gcs_export.py
_VALID_TXN_TYPES = {
    "PURCHASE", "SIP_PURCHASE", "REDEMPTION",
    "DIVIDEND", "BONUS", "SWITCH_IN", "SWITCH_OUT", "OTHER",
}


# ── GCS helpers ──────────────────────────────────────────────────────

def _gcs_client():
    from google.cloud import storage  # lazy import
    return storage.Client()


def _read_gcs(blob_path: str) -> bytes:
    return _gcs_client().bucket(GCS_BUCKET).blob(blob_path).download_as_bytes()


def _gcs_blob_exists(blob_path: str) -> bool:
    return _gcs_client().bucket(GCS_BUCKET).blob(blob_path).exists()


def _resolve_blob_path(target_date: Optional[date]) -> Optional[str]:
    if target_date:
        return f"{TXN_PREFIX}/{target_date.isoformat()}/transactions.jsonl"
    latest_path = f"{TXN_PREFIX}/latest.json"
    if not _gcs_blob_exists(latest_path):
        logger.warning("portfolio_transactions_sync: latest.json missing in GCS")
        return None
    meta = json.loads(_read_gcs(latest_path))
    return meta.get("path")


def _load_records(blob_path: str) -> list[dict[str, Any]]:
    raw = _read_gcs(blob_path)
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


# ── Upserts ──────────────────────────────────────────────────────────

async def _upsert_transaction(conn, rec: dict[str, Any]) -> int:
    """Returns 1 if a row was inserted, 0 if updated (or unchanged)."""
    txn_type = (rec.get("txn_type") or "").upper().strip()
    if txn_type not in _VALID_TXN_TYPES:
        txn_type = "OTHER"

    tag = await conn.execute(
        """
        INSERT INTO portfolio.user_transactions (
            external_user_id, source_system, txn_date, txn_type,
            folio, isin, amfi_scheme_code, symbol, instrument_name,
            asset_class, units, amount_inr, nav_or_price,
            cas_file_id, metadata_json
        ) VALUES (
            $1, $2, $3::date, $4,
            $5, $6, $7, $8, $9,
            $10, $11, $12, $13,
            $14, $15::jsonb
        )
        ON CONFLICT (
            external_user_id, txn_date, txn_type,
            COALESCE(folio, ''), COALESCE(isin, ''),
            COALESCE(units, 0), COALESCE(amount_inr, 0),
            source_system
        ) DO UPDATE SET
            amfi_scheme_code = EXCLUDED.amfi_scheme_code,
            symbol           = EXCLUDED.symbol,
            instrument_name  = EXCLUDED.instrument_name,
            asset_class      = EXCLUDED.asset_class,
            nav_or_price     = EXCLUDED.nav_or_price,
            cas_file_id      = EXCLUDED.cas_file_id,
            metadata_json    = EXCLUDED.metadata_json
        """,
        rec["external_user_id"],
        rec.get("source_system", "nivesh_cas"),
        rec["txn_date"],
        txn_type,
        rec.get("folio"),
        rec.get("isin"),
        rec.get("amfi_scheme_code"),
        rec.get("symbol"),
        rec.get("instrument_name"),
        rec.get("asset_class", "OTHER"),
        rec.get("units"),
        rec.get("amount_inr"),
        rec.get("nav_or_price"),
        rec.get("cas_file_id"),
        json.dumps(rec.get("metadata") or {}),
    )
    return int(tag.split()[-1] or 0)


async def _write_audit(
    conn, sync_run_id: uuid.UUID, external_user_id: str,
    snapshot_date: date, status: str,
    rows_upserted: int = 0, error_detail: Optional[str] = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO portfolio.sync_audit_log
            (sync_run_id, external_user_id, snapshot_date, status,
             holdings_upserted, dataset, rows_upserted, error_detail)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        sync_run_id, external_user_id, snapshot_date,
        status, rows_upserted, _DATASET, rows_upserted, error_detail,
    )


# ── Main entry point ─────────────────────────────────────────────────

async def run(target_date: Optional[date] = None) -> dict[str, Any]:
    sync_run_id = uuid.uuid4()
    nidp = await _get_nidp_pool()
    stats = {"users": 0, "txns_seen": 0, "txns_upserted": 0, "errors": 0}

    blob_path = _resolve_blob_path(target_date)
    if not blob_path:
        logger.info("portfolio_transactions_sync: no GCS file (target=%s)", target_date or "latest")
        return {**stats, "sync_run_id": str(sync_run_id)}

    logger.info("portfolio_transactions_sync: reading gs://%s/%s", GCS_BUCKET, blob_path)
    records = _load_records(blob_path)
    if not records:
        logger.info("portfolio_transactions_sync: empty file")
        return {**stats, "sync_run_id": str(sync_run_id)}

    # Bucket by (user, max-txn-date) so the audit log writes one row per user.
    by_user: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        uid = r.get("external_user_id")
        if not uid or not r.get("txn_date"):
            stats["errors"] += 1
            continue
        by_user.setdefault(uid, []).append(r)

    stats["txns_seen"] = sum(len(v) for v in by_user.values())

    for email, txns in by_user.items():
        latest_txn_date = max(date.fromisoformat(t["txn_date"]) for t in txns)
        upserted = 0
        try:
            async with nidp.acquire() as conn:
                async with conn.transaction():
                    for rec in txns:
                        upserted += await _upsert_transaction(conn, rec)
                    await _write_audit(
                        conn, sync_run_id, email, latest_txn_date,
                        "SUCCESS", rows_upserted=upserted,
                    )
            stats["users"]         += 1
            stats["txns_upserted"] += upserted
            logger.info("  %s — %d txns upserted (through %s)", email, upserted, latest_txn_date)
        except Exception as exc:  # noqa: BLE001
            stats["errors"] += 1
            logger.warning("portfolio_transactions_sync: %s failed: %s", email, exc)
            async with nidp.acquire() as conn:
                await _write_audit(
                    conn, sync_run_id, email, latest_txn_date,
                    "ERROR", rows_upserted=upserted, error_detail=str(exc)[:500],
                )

    return {**stats, "sync_run_id": str(sync_run_id), "gcs_path": blob_path}
