"""Export Nivesh portfolio holdings to GCS for NIDP consumption.

Reads from MongoDB (the canonical holdings store) — no Postgres dependency.

Landing zone layout:
  gs://{bucket}/portfolio/holdings/{YYYY-MM-DD}/holdings.jsonl  — one JSON line per user
  gs://{bucket}/portfolio/holdings/latest.json                  — pointer to newest file

NIDP's portfolio_holdings_sync reads these files.

Env vars:
  NIDP_GCS_BUCKET — GCS bucket (default: nidp-raw-niveshdataintelligence)
  MONGO_URL       — MongoDB connection string
  DB_NAME         — database name
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

GCS_BUCKET = os.environ.get("NIDP_GCS_BUCKET", "nidp-raw-niveshdataintelligence")
HOLDINGS_PREFIX = "portfolio/holdings"

_ASSET_CLASS: dict[str, str] = {
    "equity":      "EQUITY",
    "mutual_fund": "MF",
    "etf":         "ETF",
    "gold":        "GOLD",
    "debt":        "DEBT",
    "cash":        "CASH",
    "sgb":         "GOLD",
}


def _to_asset_class(asset_type: str) -> str:
    return _ASSET_CLASS.get((asset_type or "").lower(), "OTHER")


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
    db,
    target_date: Optional[date] = None,
) -> dict[str, Any]:
    """
    Read holdings from MongoDB and write one JSONL file to GCS per export run.

    Args:
        db: Motor AsyncIOMotorDatabase instance
        target_date: snapshot date label to embed in the file path (default: today)

    Returns summary dict.
    """
    export_date = target_date or date.today()
    date_str = export_date.isoformat()

    # Load all users with email for the user_id → email mapping
    user_cursor = db.users.find({}, {"user_id": 1, "email": 1, "name": 1, "_id": 0})
    user_map: dict[str, dict] = {}
    async for u in user_cursor:
        if u.get("user_id") and u.get("email"):
            user_map[u["user_id"]] = {"email": u["email"], "name": u.get("name", "")}

    if not user_map:
        logger.info("portfolio_gcs_export: no users found")
        return {"exported": 0, "skipped": 0, "date": date_str}

    # Load all holdings grouped by user_id
    holdings_by_user: dict[str, list] = {}
    async for h in db.holdings.find({}):
        uid = h.get("user_id")
        if uid:
            holdings_by_user.setdefault(uid, []).append(h)

    lines: list[bytes] = []
    exported = skipped = 0

    for user_id, user_info in user_map.items():
        raw_holdings = holdings_by_user.get(user_id, [])
        if not raw_holdings:
            skipped += 1
            continue

        total_value = sum(
            float(h.get("current_price") or 0) * float(h.get("quantity") or 0)
            for h in raw_holdings
        )

        holdings: list[dict] = []
        for h in raw_holdings:
            qty = float(h.get("quantity") or 0)
            price = float(h.get("current_price") or 0)
            mv = qty * price
            asset_type = (h.get("asset_type") or "").lower()
            is_equity = asset_type == "equity"
            isin = h.get("isin") or h.get("ticker")
            holdings.append({
                "asset_class":      _to_asset_class(asset_type),
                "symbol":           h.get("nse_symbol") if is_equity else None,
                "isin":             isin,
                "amfi_scheme_code": None,
                "instrument_name":  h.get("name"),
                "quantity":         qty,
                "avg_buy_price":    float(h.get("buy_price") or 0) or None,
                "market_value_inr": mv,
                "weight_pct":       round(mv / total_value * 100, 6) if total_value > 0 else 0.0,
                "source_system":    "nivesh_cas",
            })

        record = {
            "schema_version":   "1",
            "exported_at":      datetime.now(timezone.utc).isoformat(),
            "external_user_id": user_info["email"],
            "client_id":        user_id,
            "display_name":     user_info["name"],
            "snapshot_date":    date_str,
            "total_value":      total_value,
            "total_invested":   None,
            "holdings":         holdings,
        }
        lines.append(json.dumps(record, default=str).encode())
        exported += 1
        logger.info("portfolio_gcs_export: queued %s — %d holdings", user_info["email"], len(holdings))

    if not lines:
        return {"exported": 0, "skipped": skipped, "date": date_str}

    blob_path = f"{HOLDINGS_PREFIX}/{date_str}/holdings.jsonl"
    payload = b"\n".join(lines)
    _upload_to_gcs(blob_path, payload, content_type="application/x-ndjson")

    latest = json.dumps({
        "date":        date_str,
        "path":        blob_path,
        "records":     exported,
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }).encode()
    _upload_to_gcs(f"{HOLDINGS_PREFIX}/latest.json", latest)

    return {"exported": exported, "skipped": skipped, "date": date_str, "gcs_path": blob_path}
