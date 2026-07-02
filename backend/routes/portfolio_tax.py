"""V4 Tax dashboard endpoint — GET /api/portfolio/tax-summary.

Promotes the existing /api/copilot/widgets/tax_harvest data shape into a
dashboard-grade GET endpoint per docs/api-changes.md New Endpoint B.12.

Also fixes the stale ₹1L LTCG limit hardcoded in copilot_widgets.py
(gap-analysis Finding C.8) — updated to ₹1,25,000 per the Jul-2024
Indian tax law amendment.

Backward compat: the chat widget POST /api/copilot/widgets/tax_harvest
remains unchanged. Dashboard reads use this lighter GET instead.

Serves screens: 10 Tax dashboard (mobile + web).
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, Query, Request

from deps import db, get_current_user

router = APIRouter(prefix="/api/portfolio")
logger = logging.getLogger(__name__)

# Post-Jul-2024 Indian tax law: LTCG exemption raised from ₹1L to ₹1.25L.
LTCG_LIMIT_RS = 125_000.0


def _days_to_fy_end(today: Optional[date] = None) -> int:
    """Days remaining until 31 March of the current Indian FY."""
    today = today or date.today()
    fy_end_year = today.year if today.month < 4 else today.year + 1
    fy_end = date(fy_end_year, 3, 31)
    return max(0, (fy_end - today).days)


def _current_fy_label(today: Optional[date] = None) -> str:
    today = today or date.today()
    if today.month < 4:
        return f"FY {today.year - 1}-{str(today.year)[2:]}"
    return f"FY {today.year}-{str(today.year + 1)[2:]}"


def _fy_bounds(fy: Optional[str], today: Optional[date] = None) -> tuple[date, date, str]:
    """(start, end, label) for an Indian FY. Accepts 'FY 2025-26' / '2025-26' /
    '2025'; defaults to the current FY (Apr 1 – Mar 31)."""
    import re
    today = today or date.today()
    start_year = today.year if today.month >= 4 else today.year - 1
    if fy:
        m = re.search(r"(20\d{2})", fy)
        if m:
            start_year = int(m.group(1))
    return date(start_year, 4, 1), date(start_year + 1, 3, 31), f"FY {start_year}-{str(start_year + 1)[2:]}"


@router.get("/capital-gains-statement")
async def capital_gains_statement(request: Request, fy: Optional[str] = Query(None)) -> dict[str, Any]:
    """Scheme-wise realised capital-gains statement (FIFO) in the broker/depository
    layout — Sections A (STCG Sec-111A) / B (LTCG Sec-112A) / C summary. Epic 0.12."""
    user = await get_current_user(request)
    user_id = user.get("user_id") or str(user.get("_id") or "")
    start, end, fy_label = _fy_bounds(fy)

    from dataclasses import asdict
    from services import tax_engine_fifo, cg_statement
    events: list[dict[str, Any]] = []
    try:
        state = await tax_engine_fifo.build_user_tax_state(user_id)
        for e in state.calculator.events:
            d = asdict(e)
            sd = d.get("sell_date")
            sdate = sd.date() if isinstance(sd, datetime) else sd
            if sdate is None or (start <= sdate <= end):
                events.append(d)
    except Exception as exc:  # noqa: BLE001 — no realised events / no CAS is a valid empty statement
        logger.warning("CG statement: FIFO build failed for %s: %s", user_id, exc)

    return cg_statement.build_statement(
        events, fy_label=fy_label,
        holder=user.get("name") or user.get("full_name"),
        pan=user.get("pan") or user.get("pan_number"),
        period=f"{start.strftime('%d-%b-%Y')} to {end.strftime('%d-%b-%Y')}",
        generated_on=date.today().isoformat(),
    )


@router.get("/tax-summary")
async def get_tax_summary(request: Request, fy: Optional[str] = Query(None)) -> dict[str, Any]:
    """LTCG harvest candidates + tax structuring opportunities.

    Returns a dashboard-grade payload matching docs/api-changes.md B.12.

    Query params:
        fy — optional FY label (e.g. "FY 2025-26"). Defaults to current FY.
    """
    user = await get_current_user(request)
    user_id = user.get("user_id") or str(user.get("_id") or "")

    # Load holdings — Mongo holdings first, then V3 Postgres bridge for V4 users.
    raw: list[dict] = []
    async for h in db.holdings.find({"user_id": user_id}, {"_id": 0}):
        raw.append(h)
    if not raw:
        async for h in db.portfolio_holdings.find({"user_id": user_id}, {"_id": 0}):
            raw.append(h)

    cg_doc = await db.capital_gains_summary.find_one({"user_id": user_id}) or {}
    ltcg_used = float(cg_doc.get("ltcg_booked_rs") or 0)
    ltcg_remaining = max(0.0, LTCG_LIMIT_RS - ltcg_used)

    candidates: list[dict[str, Any]] = []
    total_harvestable = 0.0

    for h in raw:
        gain = float(h.get("unrealised_gain") or h.get("gain") or 0)
        days = int(h.get("days_held") or h.get("holding_days") or 0)
        cost = float(h.get("invested_value") or h.get("cost_basis") or 0)
        curr = float(h.get("current_value") or h.get("value") or 0)
        name = h.get("fund_name") or h.get("scheme_name") or h.get("name") or "Unknown"
        instrument_id = h.get("instrument_id") or h.get("ticker") or h.get("isin")

        if gain <= 0 or days < 365:
            continue

        eligible = gain <= ltcg_remaining
        if eligible:
            total_harvestable += gain

        candidates.append({
            "instrument_id": instrument_id,
            "fund_name": name,
            "current_value_rs": round(curr, 2) if curr else None,
            "cost_basis_rs": round(cost, 2) if cost else None,
            "gain_rs": round(gain, 2),
            "gain_type": "LTCG",
            "days_held": days or None,
            "eligible": eligible,
            "eligible_after_date": None,   # per-lot future enhancement
            "wash_sale_risk": False,
        })

    candidates.sort(key=lambda c: c["gain_rs"])  # safest harvest first

    warning = (
        "Repurchasing within 30 days may trigger wash-sale considerations."
        if candidates else None
    )

    return {
        "fy": fy or _current_fy_label(),
        "ltcg_limit_rs": LTCG_LIMIT_RS,
        "ltcg_used_rs": round(ltcg_used, 2),
        "ltcg_remaining_rs": round(ltcg_remaining, 2),
        "total_harvestable_rs": round(total_harvestable, 2) if total_harvestable else 0.0,
        "days_to_fy_end": _days_to_fy_end(),
        "candidates": candidates[:8],
        "warning": warning,
        "empty": len(raw) == 0,
    }
