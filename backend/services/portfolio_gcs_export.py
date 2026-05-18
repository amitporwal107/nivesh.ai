"""Export Nivesh portfolio holdings, raw CAS transactions and user goals
to GCS for NIDP consumption.

Reads:
  * MongoDB — db.holdings, db.cas_transactions (canonical user state)
  * Nivesh Postgres — user_goals (goal definitions)

Landing zone layout (one JSONL file per dataset per date + a latest.json pointer):
  gs://{bucket}/portfolio/holdings/{date}/holdings.jsonl
  gs://{bucket}/portfolio/holdings/latest.json
  gs://{bucket}/portfolio/transactions/{date}/transactions.jsonl
  gs://{bucket}/portfolio/transactions/latest.json
  gs://{bucket}/portfolio/goals/{date}/goals.jsonl
  gs://{bucket}/portfolio/goals/latest.json

NIDP's portfolio_holdings_sync / portfolio_transactions_sync /
portfolio_goals_sync read these files.

Env vars:
  NIDP_GCS_BUCKET — GCS bucket (default: nidp-raw-niveshdataintelligence)
  MONGO_URL       — MongoDB connection string
  DB_NAME         — database name
  POSTGRES_URL    — Nivesh Postgres (for user_goals export)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

GCS_BUCKET         = os.environ.get("NIDP_GCS_BUCKET", "nidp-raw-niveshdataintelligence")
HOLDINGS_PREFIX    = "portfolio/holdings"
TRANSACTIONS_PREFIX = "portfolio/transactions"
GOALS_PREFIX       = "portfolio/goals"


# CAS transaction-type values written by the parser → canonical NIDP types.
# Anything else falls through to OTHER (the sync writes that out unchanged).
_TXN_TYPE_MAP: dict[str, str] = {
    "PURCHASE":         "PURCHASE",
    "SIP_PURCHASE":     "SIP_PURCHASE",
    "BUY":              "PURCHASE",
    "REDEMPTION":       "REDEMPTION",
    "SELL":             "REDEMPTION",
    "SWITCH_IN":        "SWITCH_IN",
    "SWITCH_OUT":       "SWITCH_OUT",
    "DIVIDEND":         "DIVIDEND",
    "DIVIDEND_PAYOUT":  "DIVIDEND",
    "DIVIDEND_REINVEST": "DIVIDEND",
    "BONUS":            "BONUS",
}


def _normalise_txn_type(raw: Optional[str]) -> str:
    return _TXN_TYPE_MAP.get((raw or "").upper().strip(), "OTHER")

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


# ── CAS transactions export ──────────────────────────────────────────

async def export_cas_transactions_to_gcs(
    db,
    target_date: Optional[date] = None,
) -> dict[str, Any]:
    """Stream Mongo `cas_transactions` → JSONL → GCS for NIDP consumption.

    Emits one JSONL line per CAS transaction (not per user). The line shape
    is consumed by `nidp.services.portfolio_transactions_sync`.

    Transactions are unbounded in volume — this exporter does NOT load
    them all into memory; it streams the cursor straight to the upload
    payload buffer.
    """
    export_date = target_date or date.today()
    date_str = export_date.isoformat()

    user_cursor = db.users.find({}, {"user_id": 1, "email": 1, "name": 1, "_id": 0})
    user_map: dict[str, dict] = {}
    async for u in user_cursor:
        if u.get("user_id") and u.get("email"):
            user_map[u["user_id"]] = {"email": u["email"], "name": u.get("name", "")}

    if not user_map:
        logger.info("export_cas_transactions_to_gcs: no users found")
        return {"exported": 0, "users": 0, "date": date_str}

    exported_at_iso = datetime.now(timezone.utc).isoformat()
    lines: list[bytes] = []
    users_with_txns = 0

    for user_id, user_info in user_map.items():
        cursor = db.cas_transactions.find(
            {"user_id": user_id},
            {
                "_id": 0,
                "folio": 1, "folio_number": 1, "isin": 1,
                "amfi_scheme_code": 1, "symbol": 1, "name": 1, "scheme_name": 1,
                "asset_type": 1, "date": 1, "type": 1,
                "units": 1, "amount": 1, "nav": 1, "price": 1,
                "cas_file_id": 1,
            },
        )
        user_count = 0
        async for t in cursor:
            txn_date = t.get("date")
            if not txn_date:
                continue
            units = t.get("units")
            amount = t.get("amount")
            nav = t.get("nav") or t.get("price")
            if nav in (None, 0) and units and amount:
                try:
                    nav = float(amount) / float(units)
                except (TypeError, ZeroDivisionError):
                    nav = None

            name = t.get("name") or t.get("scheme_name")
            asset_type = (t.get("asset_type") or "").lower()
            asset_class = _to_asset_class(asset_type) if asset_type else "MF"

            record = {
                "schema_version":   "1",
                "exported_at":      exported_at_iso,
                "external_user_id": user_info["email"],
                "client_id":        user_id,
                "txn_date":         str(txn_date)[:10],
                "txn_type":         _normalise_txn_type(t.get("type")),
                "folio":            t.get("folio") or t.get("folio_number"),
                "isin":             t.get("isin"),
                "amfi_scheme_code": t.get("amfi_scheme_code"),
                "symbol":           t.get("symbol"),
                "instrument_name":  name,
                "asset_class":      asset_class,
                "units":            float(units) if units is not None else None,
                "amount_inr":       float(amount) if amount is not None else None,
                "nav_or_price":     float(nav) if nav is not None else None,
                "cas_file_id":      t.get("cas_file_id"),
                "source_system":    "nivesh_cas",
            }
            lines.append(json.dumps(record, default=str).encode())
            user_count += 1
        if user_count > 0:
            users_with_txns += 1

    if not lines:
        logger.info("export_cas_transactions_to_gcs: no transactions to export")
        return {"exported": 0, "users": 0, "date": date_str}

    blob_path = f"{TRANSACTIONS_PREFIX}/{date_str}/transactions.jsonl"
    payload = b"\n".join(lines)
    _upload_to_gcs(blob_path, payload, content_type="application/x-ndjson")

    latest = json.dumps({
        "date":        date_str,
        "path":        blob_path,
        "records":     len(lines),
        "users":       users_with_txns,
        "exported_at": exported_at_iso,
    }).encode()
    _upload_to_gcs(f"{TRANSACTIONS_PREFIX}/latest.json", latest)

    return {
        "exported": len(lines), "users": users_with_txns,
        "date": date_str, "gcs_path": blob_path,
    }


# ── Goals export (Postgres source) ───────────────────────────────────

async def export_user_goals_to_gcs(
    db,
    target_date: Optional[date] = None,
) -> dict[str, Any]:
    """Export PG `user_goals` rows → JSONL → GCS for NIDP consumption.

    Joins to MongoDB `users` to translate the upstream UUID `user_id`
    into an email `external_user_id`, which is NIDP's canonical user key.
    Goals belonging to users without an email are skipped.

    Reads PG via `services.pg_client.get_pool()`. If PG is not
    configured the function returns a no-op result rather than raising,
    so it can be wired into pipelines safely.
    """
    export_date = target_date or date.today()
    date_str = export_date.isoformat()

    try:
        from services import pg_client as _pg
        pool = await _pg.get_pool()
    except Exception as exc:  # noqa: BLE001
        logger.warning("export_user_goals_to_gcs: PG unavailable: %s", exc)
        return {"exported": 0, "users": 0, "date": date_str, "skipped_reason": "pg_unavailable"}
    if pool is None:
        logger.info("export_user_goals_to_gcs: PG not configured")
        return {"exported": 0, "users": 0, "date": date_str, "skipped_reason": "pg_not_configured"}

    # uuid → email map from Mongo
    uid_to_email: dict[str, str] = {}
    async for u in db.users.find({}, {"user_id": 1, "email": 1, "_id": 0}):
        if u.get("user_id") and u.get("email"):
            uid_to_email[str(u["user_id"])] = u["email"]

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT goal_id, user_id, goal_type, goal_name,
                   target_amount_rs, horizon_years, priority,
                   inflation_pct, expected_return_pct,
                   current_corpus_rs, monthly_sip_rs,
                   allocation, selected_funds, manual_fund_override,
                   status, on_track_pct, last_simulated_at, last_simulation,
                   created_at, updated_at
              FROM user_goals
            """
        )

    exported_at_iso = datetime.now(timezone.utc).isoformat()
    lines: list[bytes] = []
    seen_users: set[str] = set()
    skipped_no_email = 0

    for r in rows:
        uid = str(r["user_id"])
        email = uid_to_email.get(uid)
        if not email:
            skipped_no_email += 1
            continue
        seen_users.add(email)
        record = {
            "schema_version":      "1",
            "exported_at":         exported_at_iso,
            "external_user_id":    email,
            "client_id":           uid,
            "source_system":       "nivesh_pg",
            "goal_id":             str(r["goal_id"]),
            "goal_type":           r["goal_type"],
            "goal_name":           r["goal_name"],
            "target_amount_rs":    float(r["target_amount_rs"]) if r["target_amount_rs"] is not None else 0.0,
            "horizon_years":       float(r["horizon_years"]) if r["horizon_years"] is not None else 0.0,
            "priority":            r["priority"],
            "inflation_pct":       float(r["inflation_pct"]) if r["inflation_pct"] is not None else None,
            "expected_return_pct": float(r["expected_return_pct"]) if r["expected_return_pct"] is not None else None,
            "current_corpus_rs":   float(r["current_corpus_rs"]) if r["current_corpus_rs"] is not None else 0.0,
            "monthly_sip_rs":      float(r["monthly_sip_rs"]) if r["monthly_sip_rs"] is not None else 0.0,
            "allocation":          r["allocation"],
            "selected_funds":      r["selected_funds"],
            "manual_fund_override": bool(r["manual_fund_override"]),
            "status":              r["status"],
            "on_track_pct":        float(r["on_track_pct"]) if r["on_track_pct"] is not None else None,
            "last_simulated_at":   r["last_simulated_at"].isoformat() if r["last_simulated_at"] else None,
            "last_simulation":     r["last_simulation"],
            "upstream_created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "upstream_updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        lines.append(json.dumps(record, default=str).encode())

    if not lines:
        logger.info(
            "export_user_goals_to_gcs: no goals to export (skipped_no_email=%d)",
            skipped_no_email,
        )
        return {"exported": 0, "users": 0, "date": date_str,
                "skipped_no_email": skipped_no_email}

    blob_path = f"{GOALS_PREFIX}/{date_str}/goals.jsonl"
    _upload_to_gcs(blob_path, b"\n".join(lines), content_type="application/x-ndjson")

    latest = json.dumps({
        "date":             date_str,
        "path":             blob_path,
        "records":          len(lines),
        "users":            len(seen_users),
        "exported_at":      exported_at_iso,
        "skipped_no_email": skipped_no_email,
    }).encode()
    _upload_to_gcs(f"{GOALS_PREFIX}/latest.json", latest)

    return {
        "exported": len(lines), "users": len(seen_users),
        "skipped_no_email": skipped_no_email,
        "date": date_str, "gcs_path": blob_path,
    }
