"""Live quotes from the platform-level Kite feed (services/kite_live_feed). Read only.

GET /api/live/status    state of the feed (mode, source, instrument count, last tick age)
GET /api/live/quotes    ?symbols=RELIANCE,NIFTY 50   batch of quotes from the latest snapshot
GET /api/live/snapshot  ?universe=indices|nifty500|fno|all   a whole set
GET /api/live/stream    SSE, one `snapshot` event per cadence with the same body as /quotes or /snapshot

Every body carries as_of / data_at / age_seconds / stale / mode. A symbol with no price is absent from `quotes` and listed
in `missing` (null, never 0). The API never calls Kite: it serves what the leader process published.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from deps import get_current_user
from services.kite_live_feed import config as cfg
from services.kite_live_feed import gateway as gw
from services.kite_live_feed.feed import aware, get_feed

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/live", tags=["live-quotes"])

MAX_SYMBOLS = 600
UNIVERSES = ("indices", "nifty500", "fno", "all")
STREAM_MAX_SECONDS = 30 * 60            # the client reconnects (EventSource does so by itself)


def _age(ts: Any, now: datetime) -> Optional[float]:
    d = aware(ts) if isinstance(ts, datetime) else None
    if d is None and ts:
        try:
            d = aware(datetime.fromisoformat(str(ts)))
        except ValueError:
            d = None
    return round((now - d).total_seconds(), 1) if d else None


def mode_of(status: Optional[dict], age: Optional[float]) -> str:
    """live | delayed | closed | expired | not_connected | disabled -- what the shell's chip shows."""
    if not status:
        return "disabled" if not cfg.enabled() else "not_connected"
    st, session = status.get("state"), status.get("session")
    if st in ("expired", "not_connected"):
        return st
    if session == "open":
        if st == "live" and age is not None and age <= cfg.STALE_AFTER_SECONDS:
            return "live"
        return "delayed"
    return "closed"


def build_payload(snapshot: Optional[dict], status: Optional[dict], wanted: Optional[List[str]], now: datetime) -> Dict[str, Any]:
    snap = snapshot or {}
    by_sym = {q["symbol"]: q for q in snap.get("quotes", [])}
    data_age = _age(snap.get("data_at"), now)
    mode = mode_of(status, data_age)
    syms = list(by_sym) if wanted is None else wanted
    quotes = {s: {k: v for k, v in by_sym[s].items() if k != "symbol"} for s in syms if s in by_sym}
    stale = snapshot is None or mode in ("delayed", "expired", "not_connected", "disabled")
    return {"as_of": snap.get("as_of"), "data_at": snap.get("data_at"), "age_seconds": data_age, "stale": stale,
            "stale_after_seconds": cfg.STALE_AFTER_SECONDS, "mode": mode, "session": (status or {}).get("session") or snap.get("session"),
            "source": snap.get("source"), "final": bool(snap.get("final")), "count": len(quotes),
            "missing": [s for s in syms if s not in by_sym] if wanted is not None else [], "quotes": quotes,
            "note": "Prices are null/absent when Kite gave none. `stale` is true when the market is open and the newest data is older than "
                    f"{cfg.STALE_AFTER_SECONDS}s, or the feed is not connected.", "read_only": True}


def _symbols(raw: str) -> List[str]:
    out, seen = [], set()
    for part in raw.split(","):
        s = gw.canon(part)
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    if not out:
        raise HTTPException(status_code=400, detail="symbols is empty")
    if len(out) > MAX_SYMBOLS:
        raise HTTPException(status_code=400, detail=f"at most {MAX_SYMBOLS} symbols; use /snapshot?universe= for a whole set")
    return out


async def _universe_symbols(name: str) -> Optional[List[str]]:
    if name == "all":
        return None
    sets = await get_feed().read_universe()
    return list(sets.get(name, []))


async def _body(symbols: Optional[List[str]], universe: Optional[str]) -> Dict[str, Any]:
    feed = get_feed()
    now = datetime.now(timezone.utc)
    wanted = symbols
    if symbols:
        await feed.request_symbols(symbols)
    elif universe:
        wanted = await _universe_symbols(universe)
    return build_payload(await feed.read_snapshot(), await feed.read_status(), wanted, now)


@router.get("/status")
async def status(request: Request) -> Dict[str, Any]:
    await get_current_user(request)
    feed = get_feed()
    st = await feed.read_status()
    snap = await feed.read_snapshot()
    now = datetime.now(timezone.utc)
    age = _age((st or {}).get("data_at") or (snap or {}).get("data_at"), now)
    out = dict(st or {})
    out.pop("holder", None)
    out.pop("updated_at", None)
    return {"enabled": cfg.enabled(), "mode": mode_of(st, age), "state": (st or {}).get("state", "disabled" if not cfg.enabled() else "unknown"),
            "last_tick_age_seconds": age, "as_of": (snap or {}).get("as_of"), "source": out.get("source"),
            "instrument_count": out.get("instrument_count", 0), "unresolved_count": out.get("unresolved_count", 0),
            "session": out.get("session"), "reason": out.get("reason"), "message": out.get("message", ""),
            "cadence_seconds": out.get("cadence_seconds", cfg.cadence_seconds()), "universe": out.get("universe", {}),
            "holiday_checked": out.get("holiday_checked"), "read_only": True}


@router.get("/quotes")
async def quotes(request: Request, symbols: str = Query(..., max_length=12000)) -> Dict[str, Any]:
    await get_current_user(request)
    return await _body(_symbols(symbols), None)


@router.get("/snapshot")
async def snapshot(request: Request, universe: str = Query("indices"), symbols: Optional[str] = Query(None, max_length=12000)) -> Dict[str, Any]:
    await get_current_user(request)
    if universe not in UNIVERSES:
        raise HTTPException(status_code=400, detail=f"universe must be one of {', '.join(UNIVERSES)}")
    return await _body(_symbols(symbols) if symbols else None, universe)


@router.get("/stream")
async def stream(request: Request, symbols: Optional[str] = Query(None, max_length=12000), universe: Optional[str] = Query(None)):
    """Server-sent events: an immediate `snapshot` event, then one per cadence. Comments (": ping") keep proxies open."""
    await get_current_user(request)
    if universe is not None and universe not in UNIVERSES:
        raise HTTPException(status_code=400, detail=f"universe must be one of {', '.join(UNIVERSES)}")
    syms = _symbols(symbols) if symbols else None
    if syms is None and universe is None:
        universe = "indices"
    cadence = get_feed().cadence

    async def gen():
        loop = asyncio.get_event_loop()
        started = loop.time()
        yield f"retry: {cadence * 1000}\n\n"
        while loop.time() - started < STREAM_MAX_SECONDS:
            if await request.is_disconnected():
                return
            try:
                body = await _body(syms, universe)
                yield f"event: snapshot\ndata: {json.dumps(body, separators=(',', ':'))}\n\n"
            except Exception as e:  # noqa: BLE001 — tell the client, keep the stream
                logger.warning("live stream pass failed: %s", type(e).__name__)
                yield f"event: error\ndata: {json.dumps({'error': 'snapshot_unavailable'})}\n\n"
            await asyncio.sleep(cadence)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})
