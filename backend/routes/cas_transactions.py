"""Read APIs for CAS-extracted transactions + detected SIPs.

Powers the "Active SIPs" panel and the per-fund transaction history view.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Query, Request

from deps import db, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["cas-transactions"])


@router.get("/portfolio/transactions")
async def list_transactions(
    request: Request,
    isin: Optional[str] = Query(None, description="Filter by ISIN"),
    folio: Optional[str] = Query(None, description="Filter by folio number"),
    limit: int = Query(500, le=2000),
):
    """List CAS-extracted transactions for the current user.

    Supports optional ISIN / folio filters. Sorted by date desc.
    """
    user = await get_current_user(request)
    q: dict = {"user_id": user["user_id"]}
    if isin:
        q["isin"] = isin
    if folio:
        q["folio"] = folio
    cursor = db.cas_transactions.find(q, {"_id": 0}).sort("date", -1).limit(limit)
    txns = [t async for t in cursor]
    # Aggregate quick totals for the UI
    total_invested = sum(t.get("amount", 0) for t in txns if t["type"] in ("PURCHASE", "SIP_PURCHASE"))
    total_redeemed = sum(t.get("amount", 0) for t in txns if t["type"] == "REDEMPTION")
    return {
        "transactions": txns,
        "count": len(txns),
        "total_invested": round(total_invested, 2),
        "total_redeemed": round(total_redeemed, 2),
    }


@router.get("/portfolio/sips")
async def list_detected_sips(request: Request):
    """List SIPs detected from CAS transaction patterns.

    Each SIP carries cadence (MONTHLY/QUARTERLY), amount, instalment count,
    first/last dates, total invested, and ACTIVE/PAUSED status (PAUSED
    when the most recent instalment is past 2× cadence).
    """
    user = await get_current_user(request)
    cursor = db.detected_sips.find(
        {"user_id": user["user_id"]}, {"_id": 0}
    ).sort([("status", 1), ("amount", -1)])    # ACTIVE first, then by amount desc
    sips = [s async for s in cursor]

    # Augment each SIP with v4 fields (setdefault so existing data wins).
    # Screens served: 17_sip_board.svg (advisor)
    for s in sips:
        s.setdefault("state", s.get("status", "UNKNOWN"))
        s.setdefault("mandate_id", None)
        s.setdefault("mandate_expiry_date", None)
        s.setdefault("last_bounce_reason", None)
        s.setdefault("last_bounce_date", None)
        s.setdefault("cycles_missed", 0)
        s.setdefault("next_debit_date", None)
        s.setdefault("proposed_stepup_pct", None)

    active = [s for s in sips if s.get("status") == "ACTIVE"]
    monthly_outflow = sum(
        s["amount"] for s in active if s.get("cadence") == "MONTHLY"
    ) + sum(
        s["amount"] / 3 for s in active if s.get("cadence") == "QUARTERLY"
    )
    return {
        "sips": sips,
        "count": len(sips),
        "active_count": len(active),
        "monthly_sip_outflow": round(monthly_outflow, 2),
    }
