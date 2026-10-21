"""GET /api/markets/symbol-lookup: type-ahead search and "did you mean" over the NSE symbol universe. Signed in, read only, nothing stored.

    ?q=<text>          a symbol, a company-name fragment ("pc jew") or an ISIN, up to 40 characters; empty = popular + recent
    &limit=8           1 to 20
    &fno_only=true     only stocks in the NSE F&O master (the Options & futures lab)
    &recent=A,B,...    symbols the client remembers (up to 8); returned as they are if they exist in the universe. Never stored here.

Response: {query, exact, results:[{symbol, name, isin, sector, industry, fno_eligible, in_scanner, last_price_date, has_prices, match,
matched_on, highlight:{symbol:[[s,e]], name:[[s,e]]}, score}], count, reason, source, as_of} and, for an empty q, `popular` (the
scanner's top setups today, with `popular_source`) and `recent`. Rules and sources: services/symbol_lookup.py.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query, Request

from deps import get_current_user
from services import symbol_lookup as sl

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/markets", tags=["markets"])

POPULAR_LIMIT = 8
_SYM = re.compile(r"^[A-Za-z0-9&-]{1,20}$")


async def _popular(request: Request, u: sl.Universe) -> Dict[str, Any]:
    try:
        from services.strategy_plan.selection import select_opportunities
        sel = await select_opportunities(request, POPULAR_LIMIT)
    except Exception as e:  # noqa: BLE001 — popular is a convenience; an unreadable scanner shows none
        logger.warning("symbol lookup: scanner unavailable for popular: %s", e)
        return {"popular": [], "popular_source": None, "popular_reason": "The scanner could not be read."}
    out: List[Dict[str, Any]] = []
    for s in sel.get("setups") or []:
        e = u.entries.get(str(s.get("symbol") or "").upper())
        if e is not None:
            out.append(sl.entry_view(e, "popular", "symbol"))
    return {"popular": out, "popular_source": sel.get("source"), "popular_reason": None if out else (sel.get("empty_reason") or "The scanner has no setups today.")}


@router.get("/symbol-lookup")
async def symbol_lookup(request: Request, q: str = Query("", max_length=200), limit: int = Query(sl.DEFAULT_LIMIT, ge=1, le=sl.MAX_LIMIT),
                        fno_only: bool = False, recent: str = Query("", max_length=400)) -> Dict[str, Any]:
    await get_current_user(request)
    try:
        text = sl.normalise(q)
    except sl.BadQuery as e:
        raise HTTPException(status_code=422, detail={"code": "invalid_query", "message": str(e)})
    try:
        body = await sl.lookup(text, limit, fno_only)
    except RuntimeError as e:
        logger.warning("symbol lookup unavailable: %s", e)
        raise HTTPException(status_code=502, detail="lookup_unavailable")
    if not text:
        u = await sl.get_universe()
        wanted = [x.upper() for x in recent.split(",") if _SYM.match(x.strip())][:sl.MAX_RECENT]
        body["recent"] = [sl.entry_view(u.entries[s], "recent") for s in dict.fromkeys(wanted) if s in u.entries and (not fno_only or u.entries[s]["fno_eligible"])]
        pop = await _popular(request, u)
        if fno_only:
            pop["popular"] = [p for p in pop["popular"] if p["fno_eligible"]]
        body.update(pop)
    return body
