"""CAS Time-Machine API — historical snapshot queries for Client 360.

All reads delegate to `services.cas_snapshot_engine` which stores one
immutable snapshot per CAS PDF upload keyed by `statement_period_end`.

Endpoints (all under /api/portfolio/):
  GET  /cas-snapshots                      list of all CAS snapshots (no holdings payload)
  GET  /cas-snapshot?date=YYYY-MM-DD       single snapshot (latest when date omitted)
  GET  /cas-performance?from=&to=          value + health line-chart series
  GET  /cas-sip-summary?from=&to=          monthly SIP bar-chart aggregates
  GET  /cas-sip-breakdown?month=YYYY-MM    per-fund SIP drill-down for one month
  GET  /cas-top-transactions?from=&to=&n=  top-N transactions by amount
  POST /cas-snapshot/{snapshot_date}/activate  load an older snapshot into live holdings view
"""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, HTTPException, Request

from deps import get_current_user
from services import cas_snapshot_engine as _eng

router = APIRouter(prefix="/api/portfolio", tags=["cas-snapshots"])


def _uid(user: dict) -> str:
    return user.get("_session_user_id") or user["user_id"]


@router.get("/cas-snapshots")
async def list_cas_snapshots(request: Request, limit: int = 60):
    """Lightweight list of all CAS snapshots — no holdings payload.
    Returns newest-first so the timeline UI can render tiles immediately."""
    user = await get_current_user(request)
    snaps = await _eng.list_snapshots(_uid(user), limit=limit)
    state = await _eng.get_view_state(_uid(user))
    return {
        "count": len(snaps),
        "snapshots": snaps,
        "current_snapshot_date": state.get("current_snapshot_date"),
        "is_default_latest": state.get("is_default_latest", True),
    }


@router.get("/cas-snapshot")
async def get_cas_snapshot(request: Request, date: Optional[str] = None):
    """Return full snapshot (including holdings). When `date` is omitted,
    returns the latest snapshot. Passing `include_holdings=false` as a
    query param skips the heavy holdings array."""
    user = await get_current_user(request)
    uid = _uid(user)
    include_holdings_param = request.query_params.get("include_holdings", "true").lower()
    include_holdings = include_holdings_param != "false"

    if date:
        snap = await _eng.get_snapshot(uid, date, include_holdings=include_holdings)
    else:
        # Latest = first in descending-date list
        snaps = await _eng.list_snapshots(uid, limit=1)
        if not snaps:
            raise HTTPException(404, "No CAS snapshots yet — upload a CAS PDF to get started")
        snap = await _eng.get_snapshot(uid, snaps[0]["snapshot_date"], include_holdings=include_holdings)

    if not snap:
        raise HTTPException(404, f"No snapshot found for date={date!r}")
    return snap


@router.get("/cas-performance")
async def cas_performance(
    request: Request,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
):
    """Return chronological series of {snapshot_date, total_value,
    total_invested, return_pct, health_score, allocation} for the
    given date range. Used to render the portfolio-value line chart.

    Query params: `from` and `to` (YYYY-MM-DD). Both optional."""
    user = await get_current_user(request)
    uid = _uid(user)
    # FastAPI doesn't like Python keyword `from` as a query param name
    raw_from = request.query_params.get("from") or from_date
    raw_to = request.query_params.get("to") or to_date
    series = await _eng.performance_series(uid, from_date=raw_from, to_date=raw_to)
    return {"count": len(series), "series": series, "from": raw_from, "to": raw_to}


@router.get("/cas-sip-summary")
async def cas_sip_summary(
    request: Request,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
):
    """Monthly SIP / purchase aggregates for the bar chart.

    Returns: {months: [{month: YYYY-MM, total: ₹, count: n}], total_invested}"""
    user = await get_current_user(request)
    uid = _uid(user)
    raw_from = request.query_params.get("from") or from_date
    raw_to = request.query_params.get("to") or to_date
    result = await _eng.sip_monthly_summary(uid, from_date=raw_from, to_date=raw_to)
    return result


@router.get("/cas-sip-breakdown")
async def cas_sip_breakdown(request: Request, month: str):
    """Per-fund and per-AMC SIP drill-down for a single YYYY-MM month.
    Used when the user clicks a bar in the SIP bar chart."""
    user = await get_current_user(request)
    uid = _uid(user)
    if not month or len(month) != 7 or month[4] != "-":
        raise HTTPException(400, "month must be YYYY-MM (e.g. 2026-01)")
    result = await _eng.sip_breakdown_for_month(uid, month)
    return result


@router.get("/cas-top-transactions")
async def cas_top_transactions(
    request: Request,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    n: int = 10,
):
    """Top N transactions by absolute ₹ amount within the date range.
    Returns: [{date, scheme_name, amc, type, amount, units, nav, folio}]"""
    user = await get_current_user(request)
    uid = _uid(user)
    raw_from = request.query_params.get("from") or from_date
    raw_to = request.query_params.get("to") or to_date
    limit = min(max(n, 1), 50)
    txns = await _eng.top_transactions(uid, from_date=raw_from, to_date=raw_to, limit=limit)
    return {"count": len(txns), "transactions": txns, "from": raw_from, "to": raw_to}


@router.post("/cas-snapshot/{snapshot_date}/activate")
async def activate_cas_snapshot(snapshot_date: str, request: Request):
    """MFD clicks an older snapshot tile → load that snapshot's holdings
    into the live holdings table so Client 360 reflects that month.

    The live holdings are replaced atomically; all historical snapshots
    remain intact in `portfolio_snapshots`."""
    user = await get_current_user(request)
    uid = _uid(user)
    try:
        snap = await _eng.load_snapshot_into_holdings(uid, snapshot_date)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return {
        "activated": snapshot_date,
        "holdings_loaded": len(snap.get("holdings") or []),
        "total_value": snap.get("total_value"),
        "is_latest": snap.get("snapshot_date") == snapshot_date,
    }
