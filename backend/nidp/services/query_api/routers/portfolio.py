"""Portfolio ingest — the app pushes user portfolio data to NIDP over HTTP.

Endpoints (bearer auth, same token as the rest of the Query API):
  POST /portfolio/ingest-holdings      — holdings, one record per holding
  POST /portfolio/ingest-transactions  — transactions, one record per transaction
  POST /portfolio/ingest-goals         — goals, one record per goal

These replace the GCS landing zone: the app used to write JSONL files that the
portfolio_*_sync cron jobs read back. The app and NIDP now share neither a
bucket nor a database, so the records arrive in the request body and go through
the SAME upsert code the sync jobs use (``ingest_records`` in each service) —
identical change detection, upserts and audit rows, whatever the transport.

Request body: ``{"records": [...], "snapshot_date": "YYYY-MM-DD"}``.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException

from nidp.services.query_api.auth import require_bearer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/portfolio", tags=["portfolio"], dependencies=[Depends(require_bearer)])

# A full push of every user's holdings or transactions fits well inside this;
# it exists so a malformed client cannot post an unbounded body.
MAX_RECORDS = 200_000

# Fields a holding carries; anything else in a pushed record is ignored.
_HOLDING_FIELDS = (
    "source_system", "asset_class", "symbol", "isin", "amfi_scheme_code",
    "instrument_name", "quantity", "avg_buy_price", "market_value_inr", "weight_pct",
)


def _records(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    records = payload.get("records")
    if not isinstance(records, list):
        raise HTTPException(status_code=422, detail="'records' must be a list")
    if len(records) > MAX_RECORDS:
        raise HTTPException(status_code=413, detail=f"too many records (max {MAX_RECORDS})")
    if any(not isinstance(r, dict) for r in records):
        raise HTTPException(status_code=422, detail="every record must be an object")
    return records


def _snapshot_date(payload: Dict[str, Any]) -> Optional[date]:
    raw = payload.get("snapshot_date")
    if raw in (None, ""):
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        raise HTTPException(status_code=422, detail="'snapshot_date' must be YYYY-MM-DD") from None


def _group_holdings(records: List[Dict[str, Any]], default_date: Optional[date]) -> List[Dict[str, Any]]:
    """Flat per-holding records → one record per (user, snapshot date), the
    shape portfolio_holdings_sync works on."""
    grouped: Dict[tuple, Dict[str, Any]] = {}
    for r in records:
        user = r.get("external_user_id")
        snap = r.get("snapshot_date") or (default_date.isoformat() if default_date else None)
        if not user or not snap:
            raise HTTPException(
                status_code=422,
                detail="every holding needs 'external_user_id' and a snapshot date",
            )
        try:
            date.fromisoformat(str(snap)[:10])
        except ValueError:
            raise HTTPException(status_code=422, detail=f"bad snapshot_date {snap!r}") from None
        client = grouped.setdefault((user, str(snap)[:10]), {
            "external_user_id": user,
            "snapshot_date":    str(snap)[:10],
            "client_id":        r.get("client_id") or "",
            "display_name":     r.get("display_name"),
            "holdings":         [],
        })
        client["holdings"].append({k: r.get(k) for k in _HOLDING_FIELDS if r.get(k) is not None})
    return list(grouped.values())


@router.post("/ingest-holdings", summary="Upsert user holdings pushed by the app")
async def ingest_holdings(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    from nidp.services.portfolio_holdings_sync import service as holdings_sync

    clients = _group_holdings(_records(payload), _snapshot_date(payload))
    if not clients:
        return {"ok": True, "upserted": 0, "users": 0, "synced": 0, "skipped": 0, "errors": 0}
    result = await holdings_sync.ingest_records(clients)
    logger.info("portfolio ingest-holdings: %s", result)
    return {
        "ok":          result["errors"] == 0,
        "upserted":    result["holdings"],
        "users":       len(clients),
        "synced":      result["synced"],
        "skipped":     result["skipped"],     # unchanged since the last successful sync
        "errors":      result["errors"],
        "sync_run_id": result["sync_run_id"],
    }


@router.post("/ingest-transactions", summary="Upsert user transactions pushed by the app")
async def ingest_transactions(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    from nidp.services.portfolio_transactions_sync import service as txn_sync

    records = _records(payload)
    _snapshot_date(payload)                     # validated for a consistent contract
    if not records:
        return {"ok": True, "upserted": 0, "users": 0, "seen": 0, "errors": 0}
    result = await txn_sync.ingest_records(records)
    logger.info("portfolio ingest-transactions: %s", result)
    return {
        "ok":          result["errors"] == 0,
        "upserted":    result["txns_upserted"],
        "users":       result["users"],
        "seen":        result["txns_seen"],
        "errors":      result["errors"],
        "sync_run_id": result["sync_run_id"],
    }


@router.post("/ingest-goals", summary="Upsert user goals pushed by the app")
async def ingest_goals(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    from nidp.services.portfolio_goals_sync import service as goals_sync

    records = _records(payload)
    target = _snapshot_date(payload)
    if not records:
        return {"ok": True, "upserted": 0, "users": 0, "seen": 0, "errors": 0}
    result = await goals_sync.ingest_records(records, target_date=target)
    logger.info("portfolio ingest-goals: %s", result)
    return {
        "ok":          result["errors"] == 0,
        "upserted":    result["goals_upserted"],
        "users":       result["users"],
        "seen":        result["goals_seen"],
        "errors":      result["errors"],
        "sync_run_id": result["sync_run_id"],
    }
