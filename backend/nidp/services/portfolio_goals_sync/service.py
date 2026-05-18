"""Portfolio Goals Sync — GCS landing zone → NIDP TimescaleDB.

JSONL line shape (one per goal, NOT per user):
  {
    "schema_version":      "1",
    "exported_at":         "...",
    "external_user_id":    "<email>",
    "client_id":           "<user uuid>",
    "goal_id":             "<uuid>",
    "goal_type":           "retirement|education|home|wealth|custom",
    "goal_name":           "...",
    "target_amount_rs":    1500000.0,
    "horizon_years":       12.5,
    "priority":            "high|medium|low",
    "inflation_pct":       6.0,
    "expected_return_pct": 10.5,
    "current_corpus_rs":   250000.0,
    "monthly_sip_rs":      15000.0,
    "allocation":          {"equity": 60, "debt": 30, "hybrid": 10},
    "selected_funds":      {...},
    "manual_fund_override": false,
    "status":              "active|achieved|abandoned|paused",
    "on_track_pct":        72.5,
    "last_simulated_at":   "...",
    "last_simulation":     {...},
    "upstream_created_at": "...",
    "upstream_updated_at": "..."
  }

The primary key is the upstream `goal_id` UUID so this is naturally
idempotent.
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
GOALS_PREFIX = "portfolio/goals"
_DATASET = "goals"


def _gcs_client():
    from google.cloud import storage  # lazy import
    return storage.Client()


def _read_gcs(blob_path: str) -> bytes:
    return _gcs_client().bucket(GCS_BUCKET).blob(blob_path).download_as_bytes()


def _gcs_blob_exists(blob_path: str) -> bool:
    return _gcs_client().bucket(GCS_BUCKET).blob(blob_path).exists()


def _resolve_blob_path(target_date: Optional[date]) -> Optional[str]:
    if target_date:
        return f"{GOALS_PREFIX}/{target_date.isoformat()}/goals.jsonl"
    latest_path = f"{GOALS_PREFIX}/latest.json"
    if not _gcs_blob_exists(latest_path):
        logger.warning("portfolio_goals_sync: latest.json missing in GCS")
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

async def _upsert_goal(conn, rec: dict[str, Any]) -> int:
    """Returns 1 if inserted, 0 if updated. Uses upstream goal_id as PK."""
    tag = await conn.execute(
        """
        INSERT INTO portfolio.user_goals (
            goal_id, external_user_id, source_system,
            goal_type, goal_name, target_amount_rs, horizon_years,
            priority, inflation_pct, expected_return_pct,
            current_corpus_rs, monthly_sip_rs,
            allocation, selected_funds, manual_fund_override,
            status, on_track_pct, last_simulated_at, last_simulation,
            upstream_created_at, upstream_updated_at, synced_at
        ) VALUES (
            $1::uuid, $2, $3,
            $4, $5, $6, $7,
            $8, $9, $10,
            $11, $12,
            $13::jsonb, $14::jsonb, $15,
            $16, $17, $18::timestamptz, $19::jsonb,
            $20::timestamptz, $21::timestamptz, NOW()
        )
        ON CONFLICT (goal_id) DO UPDATE SET
            external_user_id     = EXCLUDED.external_user_id,
            goal_type            = EXCLUDED.goal_type,
            goal_name            = EXCLUDED.goal_name,
            target_amount_rs     = EXCLUDED.target_amount_rs,
            horizon_years        = EXCLUDED.horizon_years,
            priority             = EXCLUDED.priority,
            inflation_pct        = EXCLUDED.inflation_pct,
            expected_return_pct  = EXCLUDED.expected_return_pct,
            current_corpus_rs    = EXCLUDED.current_corpus_rs,
            monthly_sip_rs       = EXCLUDED.monthly_sip_rs,
            allocation           = EXCLUDED.allocation,
            selected_funds       = EXCLUDED.selected_funds,
            manual_fund_override = EXCLUDED.manual_fund_override,
            status               = EXCLUDED.status,
            on_track_pct         = EXCLUDED.on_track_pct,
            last_simulated_at    = EXCLUDED.last_simulated_at,
            last_simulation      = EXCLUDED.last_simulation,
            upstream_updated_at  = EXCLUDED.upstream_updated_at,
            synced_at            = NOW()
        """,
        rec["goal_id"],
        rec["external_user_id"],
        rec.get("source_system", "nivesh_pg"),
        rec.get("goal_type", "custom"),
        rec.get("goal_name", "Untitled goal"),
        rec.get("target_amount_rs", 0),
        rec.get("horizon_years", 0),
        rec.get("priority", "medium"),
        rec.get("inflation_pct"),
        rec.get("expected_return_pct"),
        rec.get("current_corpus_rs", 0),
        rec.get("monthly_sip_rs", 0),
        json.dumps(rec.get("allocation") or {}),
        json.dumps(rec.get("selected_funds") or {}),
        bool(rec.get("manual_fund_override") or False),
        rec.get("status", "active"),
        rec.get("on_track_pct"),
        rec.get("last_simulated_at"),
        json.dumps(rec.get("last_simulation") or {}),
        rec.get("upstream_created_at"),
        rec.get("upstream_updated_at"),
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
    stats = {"users": 0, "goals_seen": 0, "goals_upserted": 0, "errors": 0}

    blob_path = _resolve_blob_path(target_date)
    if not blob_path:
        logger.info("portfolio_goals_sync: no GCS file (target=%s)", target_date or "latest")
        return {**stats, "sync_run_id": str(sync_run_id)}

    logger.info("portfolio_goals_sync: reading gs://%s/%s", GCS_BUCKET, blob_path)
    records = _load_records(blob_path)
    if not records:
        logger.info("portfolio_goals_sync: empty file")
        return {**stats, "sync_run_id": str(sync_run_id)}

    by_user: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        uid = r.get("external_user_id")
        gid = r.get("goal_id")
        if not uid or not gid:
            stats["errors"] += 1
            continue
        by_user.setdefault(uid, []).append(r)

    stats["goals_seen"] = sum(len(v) for v in by_user.values())
    today = target_date or date.today()

    for email, goals in by_user.items():
        upserted = 0
        try:
            async with nidp.acquire() as conn:
                async with conn.transaction():
                    for rec in goals:
                        upserted += await _upsert_goal(conn, rec)
                    await _write_audit(
                        conn, sync_run_id, email, today,
                        "SUCCESS", rows_upserted=upserted,
                    )
            stats["users"]          += 1
            stats["goals_upserted"] += upserted
            logger.info("  %s — %d goals upserted", email, upserted)
        except Exception as exc:  # noqa: BLE001
            stats["errors"] += 1
            logger.warning("portfolio_goals_sync: %s failed: %s", email, exc)
            async with nidp.acquire() as conn:
                await _write_audit(
                    conn, sync_run_id, email, today,
                    "ERROR", rows_upserted=upserted, error_detail=str(exc)[:500],
                )

    return {**stats, "sync_run_id": str(sync_run_id), "gcs_path": blob_path}
