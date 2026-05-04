"""Chartink scan-definition storage (Mongo `system_config.chartink_scans`).

A single Mongo doc holds the full scan list, mirrored after the V3
weights pattern (services/v3_weights.py). One source of truth means
updating the dashboard's screener set is just one PUT.

Doc shape:
    {
      "_id": "chartink_scans",
      "scans": [
        {"name": "atlas.trend_up", "clause": "( {cash} ... )", "enabled": True},
        ...
      ],
      "updated_at": ISO,
    }
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List

logger = logging.getLogger(__name__)

CONFIG_DOC_ID = "chartink_scans"


def _normalise(scan: dict) -> dict:
    """Trim + coerce one scan definition. Drops anything not in the schema."""
    return {
        "name":   str(scan.get("name") or "").strip(),
        "clause": str(scan.get("clause") or "").strip(),
        "enabled": bool(scan.get("enabled", True)),
    }


def validate(scans: list) -> List[dict]:
    out: List[dict] = []
    seen: set = set()
    for s in scans or []:
        if not isinstance(s, dict):
            continue
        n = _normalise(s)
        if not n["name"] or not n["clause"]:
            continue
        if n["name"] in seen:
            continue
        seen.add(n["name"])
        out.append(n)
    return out


async def load(db) -> List[dict]:
    try:
        doc = await db["system_config"].find_one({"_id": CONFIG_DOC_ID})
    except Exception as e:  # noqa: BLE001
        logger.warning("scan_config load failed: %s", e)
        return []
    if not doc:
        return []
    return validate(doc.get("scans") or [])


async def save(db, scans: list) -> List[dict]:
    cleaned = validate(scans)
    await db["system_config"].update_one(
        {"_id": CONFIG_DOC_ID},
        {"$set": {
            "scans": cleaned,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    return cleaned


# ── Webhook token (per-tenant shared secret for Chartink alerts) ─────────
async def ensure_webhook_token(db) -> str:
    """Return the current webhook token, generating one on first call.
    Used to authenticate Chartink alert POSTs without a full HMAC scheme
    (Chartink doesn't sign payloads, so a URL token is the standard
    authentication pattern for their webhooks)."""
    doc = await db["system_config"].find_one({"_id": CONFIG_DOC_ID})
    token = (doc or {}).get("webhook_token")
    if token:
        return token
    import secrets
    token = secrets.token_urlsafe(32)
    await db["system_config"].update_one(
        {"_id": CONFIG_DOC_ID},
        {"$set": {"webhook_token": token,
                   "webhook_token_created_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return token


async def get_webhook_token(db):
    doc = await db["system_config"].find_one({"_id": CONFIG_DOC_ID})
    return (doc or {}).get("webhook_token")


async def rotate_webhook_token(db) -> str:
    """Force a new token. Existing Chartink alerts pointing at the old
    URL will start failing after rotation — admin must re-paste."""
    import secrets
    token = secrets.token_urlsafe(32)
    await db["system_config"].update_one(
        {"_id": CONFIG_DOC_ID},
        {"$set": {"webhook_token": token,
                   "webhook_token_rotated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return token


def match_scan_name(saved_scans: List[dict], chartink_scan_name: str):
    """Map Chartink's free-text scan_name to one of our saved scans.
    Strategy: lowercase + normalise spaces/dashes to underscores, then
    look for exact or substring match in the saved scan names. Returns
    the internal name or None if no match."""
    if not chartink_scan_name:
        return None
    norm = chartink_scan_name.lower().strip().replace(" ", "_").replace("-", "_")
    for s in saved_scans:
        if s["name"].lower() == norm:
            return s["name"]
    for s in saved_scans:
        # Allow tail match: "TODAYS TOP BUY" → "atlas.todays_top_buy"
        if s["name"].lower().endswith("." + norm) or norm in s["name"].lower():
            return s["name"]
    return None
