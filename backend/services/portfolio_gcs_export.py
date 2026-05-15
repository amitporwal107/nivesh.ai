"""Export Nivesh portfolio holdings to GCS for NIDP consumption.

Landing zone layout:
  gs://{bucket}/portfolio/holdings/{YYYY-MM-DD}/holdings.jsonl  — one JSON line per client
  gs://{bucket}/portfolio/holdings/latest.json                   — pointer to newest date

NIDP's portfolio_holdings_sync reads these files; no Postgres-to-Postgres
bridge is needed.

Env vars (both are already required by the main backend):
  NIDP_GCS_BUCKET   — GCS bucket name (defaults to nidp-raw-niveshdataintelligence)
  POSTGRES_URL      — Nivesh Postgres connection string
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from typing import Any, Optional

import asyncpg

logger = logging.getLogger(__name__)

GCS_BUCKET = os.environ.get("NIDP_GCS_BUCKET", "nidp-raw-niveshdataintelligence")
HOLDINGS_PREFIX = "portfolio/holdings"

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


async def _fetch_all_snapshots(
    conn: asyncpg.Connection,
    target_date: Optional[date],
) -> list[asyncpg.Record]:
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
    rows = await conn.fetch(
        """
        SELECT
            im.instrument_type,
            im.symbol,
            im.isin,
            im.instrument_name,
            psh.units          AS quantity,
            psh.current_value  AS market_value_inr,
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
            "asset_class":      _asset_class(itype),
            "symbol":           r["symbol"] if itype == "EQUITY" else None,
            "isin":             r["isin"],
            "amfi_scheme_code": r["symbol"] if itype == "MUTUAL_FUND" else None,
            "instrument_name":  r["instrument_name"],
            "quantity":         float(r["quantity"] or 0),
            "avg_buy_price":    None,
            "market_value_inr": mv,
            "weight_pct":       float(r["weight_pct"] or 0) or (
                round(mv / tv * 100, 6) if tv > 0 else 0.0
            ),
            "source_system": "nivesh_cas",
        })
    return out


def _gcs_client():
    from google.cloud import storage  # lazy import
    return storage.Client()


def _upload_to_gcs(blob_path: str, data: bytes, content_type: str = "application/json") -> None:
    client = _gcs_client()
    bucket = client.bucket(GCS_BUCKET)
    blob = bucket.blob(blob_path)
    blob.upload_from_string(data, content_type=content_type)
    logger.info("uploaded gs://%s/%s (%d bytes)", GCS_BUCKET, blob_path, len(data))


async def export_portfolio_to_gcs(
    db_pool: asyncpg.Pool,
    target_date: Optional[date] = None,
) -> dict[str, Any]:
    """
    Query Nivesh Postgres and write one JSONL file to GCS.

    Args:
        db_pool: existing asyncpg pool connected to Nivesh Postgres
        target_date: snapshot date to export; None = latest per client

    Returns summary dict.
    """
    async with db_pool.acquire() as conn:
        snapshots = await _fetch_all_snapshots(conn, target_date)

        if not snapshots:
            logger.info("portfolio_gcs_export: no snapshots found for %s", target_date or "latest")
            return {"exported": 0, "skipped": 0, "date": str(target_date or "latest")}

        logger.info("portfolio_gcs_export: %d clients to export", len(snapshots))

        lines: list[bytes] = []
        exported = skipped = 0
        export_date = target_date or date.today()

        for snap in snapshots:
            email     = snap["external_user_id"]
            snap_date = snap["snapshot_date"]
            snap_id   = snap["snapshot_id"]
            tv        = float(snap["total_value"] or 0)

            try:
                holdings = await _fetch_holdings(conn, str(snap_id), tv)
                if not holdings:
                    skipped += 1
                    continue

                record = {
                    "schema_version":   "1",
                    "exported_at":      datetime.now(timezone.utc).isoformat(),
                    "external_user_id": email,
                    "client_id":        str(snap["client_id"]),
                    "display_name":     snap["display_name"],
                    "snapshot_date":    snap_date.isoformat(),
                    "total_value":      tv,
                    "total_invested":   float(snap["total_invested"] or 0),
                    "holdings":         holdings,
                }
                lines.append(json.dumps(record, default=str).encode())
                export_date = snap_date
                exported += 1

            except Exception as exc:  # noqa: BLE001
                logger.warning("portfolio_gcs_export: error for %s: %s", email, exc)
                skipped += 1

    if not lines:
        return {"exported": 0, "skipped": skipped, "date": str(target_date or "latest")}

    date_str = export_date.isoformat()
    blob_path = f"{HOLDINGS_PREFIX}/{date_str}/holdings.jsonl"
    payload = b"\n".join(lines)
    _upload_to_gcs(blob_path, payload, content_type="application/x-ndjson")

    latest = json.dumps({
        "date":      date_str,
        "path":      blob_path,
        "records":   exported,
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }).encode()
    _upload_to_gcs(f"{HOLDINGS_PREFIX}/latest.json", latest)

    return {"exported": exported, "skipped": skipped, "date": date_str, "gcs_path": blob_path}
