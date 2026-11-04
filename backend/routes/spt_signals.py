"""SPT slice A routes: scanner signals and market-wide opportunities (PRD §17.2; DESIGN.md D8, §4).

Endpoints (prefix /api/v1; every one needs a session: 401 without one). Market-wide data: the same for every user.
    GET  /scanner/signals                    ?day=YYYY-MM-DD &symbol= &scanner_id= &category= &status=normalized|quarantined
                                             &limit=1..500 (default 100)  newest detection first
    GET  /scanner/signals/{signal_id}        one event, with the opportunities it is in
    GET  /opportunities                      ?state= &day= &symbol= &horizon=positional|intraday &direction=long|short
                                             &limit=1..500 (default 100)  oldest first signal first
    GET  /opportunities/{opportunity_id}     one opportunity (signals, conflicts, strong plan, latest validation)
    POST /opportunities/{opportunity_id}/validate   revalidate now (CREATED / CONDITIONAL / WATCHLIST / DATA_INSUFFICIENT);
                                             returns the validation record. The only write on this router.

Errors (`detail` codes are stable): 422 invalid_day | invalid_symbol | invalid_limit | invalid_state | invalid_status |
invalid_category | invalid_horizon | invalid_direction | invalid_scanner_id | invalid_kind | invalid_range; 404 signal_not_found | opportunity_not_found;
409 opportunity_not_revalidatable | validation_in_progress | state_changed.

    GET  /analytics/scanners                 ?from=YYYY-MM-DD &to=YYYY-MM-DD (default: the 30 days to today, at most 92)
                                             &kind=list|strong  signal outcomes per scanner / category / score band, with
                                             sample sizes (services/spt/outcomes/analytics.py); read-only
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from deps import db, get_current_user
from services.spt import constants as C
from services.spt.opportunities import store as opp_store
from services.spt.opportunities import validate as opp_validate
from services.spt.outcomes import analytics
from services.spt.signals import clock
from services.spt.signals import normalize
from services.spt.signals import store as sig_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["spt-signals"])

DEFAULT_LIMIT = 100
SYMBOL_RE = re.compile(r"^[A-Z0-9&-]{1,20}$")
ID_RE = re.compile(r"^[A-Za-z0-9_:&.\-]{1,120}$")
STATUSES = ("normalized", "quarantined")


def _day(v: Optional[str]) -> Optional[str]:
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_day")


def _symbol(v: Optional[str]) -> Optional[str]:
    if v in (None, ""):
        return None
    s = v.strip().upper()
    if not SYMBOL_RE.match(s):
        raise HTTPException(status_code=422, detail="invalid_symbol")
    return s


def _limit(v: Optional[int]) -> int:
    if v is None:
        return DEFAULT_LIMIT
    if not 1 <= v <= sig_store.MAX_LIMIT:
        raise HTTPException(status_code=422, detail="invalid_limit")
    return v


def _one_of(v: Optional[str], allowed, code: str) -> Optional[str]:
    if v in (None, ""):
        return None
    if v not in allowed:
        raise HTTPException(status_code=422, detail=code)
    return v


@router.get("/scanner/signals")
async def list_signals(request: Request, day: Optional[str] = None, symbol: Optional[str] = None,
                       scanner_id: Optional[str] = None, category: Optional[str] = None, status: Optional[str] = None,
                       limit: Optional[int] = Query(None)) -> Dict[str, Any]:
    await get_current_user(request)
    d, sym, lim = _day(day), _symbol(symbol), _limit(limit)
    if scanner_id not in (None, "") and not ID_RE.match(scanner_id):
        raise HTTPException(status_code=422, detail="invalid_scanner_id")
    cat = _one_of(category, normalize.CATEGORIES, "invalid_category")
    st = _one_of(status, STATUSES, "invalid_status")
    rows = await sig_store.list_signals(db, day=d, symbol=sym, scanner_id=scanner_id or None, category=cat, status=st,
                                        limit=lim)
    return {"ok": True, "count": len(rows), "limit": lim, "signals": rows,
            "note": "Scanner observations as recorded; scanner_score is the scanner's own score, not a probability."}


@router.get("/scanner/signals/{signal_id}")
async def get_signal(signal_id: str, request: Request) -> Dict[str, Any]:
    await get_current_user(request)
    if not ID_RE.match(signal_id):
        raise HTTPException(status_code=404, detail="signal_not_found")
    doc = await sig_store.get(db, signal_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="signal_not_found")
    opps = await db[opp_store.COLL].find({"signals.signal_id": signal_id}).to_list(length=None)
    return {"ok": True, "signal": doc,
            "opportunities": [{"opportunity_id": o["_id"], "state": o.get("state"), "consolidation_key": o.get("consolidation_key")}
                              for o in opps]}


@router.get("/opportunities")
async def list_opportunities(request: Request, state: Optional[str] = None, day: Optional[str] = None,
                             symbol: Optional[str] = None, horizon: Optional[str] = None, direction: Optional[str] = None,
                             limit: Optional[int] = Query(None)) -> Dict[str, Any]:
    await get_current_user(request)
    st = _one_of(state, C.OPP_STATES, "invalid_state")
    d, sym, lim = _day(day), _symbol(symbol), _limit(limit)
    hz = _one_of(horizon, normalize.HORIZONS, "invalid_horizon")
    dr = _one_of(direction, normalize.DIRECTIONS, "invalid_direction")
    q: Dict[str, Any] = {}
    if st:
        q["state"] = st
    if d:
        q["day"] = d
    if sym:
        q["symbol"] = sym
    if hz:
        q["horizon"] = hz
    if dr:
        q["direction"] = dr
    rows = await db[opp_store.COLL].find(q).sort("first_seen_at", 1).limit(lim).to_list(length=None)
    return {"ok": True, "count": len(rows), "limit": lim, "opportunities": rows,
            "score_label": opp_validate.SCORE_LABEL}


@router.get("/opportunities/{opportunity_id}")
async def get_opportunity(opportunity_id: str, request: Request) -> Dict[str, Any]:
    await get_current_user(request)
    doc = await opp_store.get(db, opportunity_id) if ID_RE.match(opportunity_id) else None
    if doc is None:
        raise HTTPException(status_code=404, detail="opportunity_not_found")
    return {"ok": True, "opportunity": doc, "score_label": opp_validate.SCORE_LABEL}


@router.post("/opportunities/{opportunity_id}/validate")
async def revalidate(opportunity_id: str, request: Request) -> Dict[str, Any]:
    await get_current_user(request)
    if not ID_RE.match(opportunity_id):
        raise HTTPException(status_code=404, detail="opportunity_not_found")
    r = await opp_validate.validate(db, opportunity_id)
    if not r.get("ok"):
        err = r.get("error") or "state_changed"
        raise HTTPException(status_code=404 if err == "opportunity_not_found" else 409, detail=err)
    return {"ok": True, "opportunity_id": opportunity_id, "state": r["state"], "validation": r["validation"]}


@router.get("/analytics/scanners")
async def scanner_analytics(request: Request, day_from: Optional[str] = Query(None, alias="from"),
                            day_to: Optional[str] = Query(None, alias="to"), kind: Optional[str] = None) -> Dict[str, Any]:
    await get_current_user(request)
    to = _day(day_to) or clock.ist_day(datetime.now(timezone.utc)).isoformat()
    frm = _day(day_from) or (date.fromisoformat(to) - timedelta(days=30)).isoformat()
    if frm > to or (date.fromisoformat(to) - date.fromisoformat(frm)).days > analytics.MAX_DAYS:
        raise HTTPException(status_code=422, detail="invalid_range")
    k = _one_of(kind, ("list", "strong"), "invalid_kind")
    return await analytics.scanners(db, day_from=frm, day_to=to, kind=k)
