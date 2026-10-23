"""Live quotes from the platform-level Kite feed (services/kite_live_feed). Read only.

GET /api/live/status    state of the feed (mode, source, instrument count, last tick age)
GET /api/live/quotes    ?symbols=RELIANCE,NIFTY 50   batch of quotes from the latest snapshot
GET /api/live/snapshot  ?universe=indices|nifty500|fno|futures|all   a whole set (futures: the near-month contract of each F&O underlying, with OI)
GET /api/live/close     ?date=YYYY-MM-DD&symbols=  the saved closing quotes of a trading day (newest when omitted)
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

from deps import get_current_user, require_admin
from services.kite_live_feed import config as cfg
from services.kite_live_feed import fno_quotes as fq
from services.kite_live_feed import gateway as gw
from services.kite_live_feed import platform_token as pt
from services.kite_live_feed.feed import aware, get_feed

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/live", tags=["live-quotes"])

MAX_SYMBOLS = 600
UNIVERSES = ("indices", "nifty500", "fno", "futures", "all")
STREAM_MAX_SECONDS = 30 * 60            # the client reconnects (EventSource does so by itself)


def _age(ts: Any, now: datetime) -> Optional[float]:
    d = aware(ts) if isinstance(ts, datetime) else None
    if d is None and ts:
        try:
            d = aware(datetime.fromisoformat(str(ts)))
        except ValueError:
            d = None
    return round((now - d).total_seconds(), 1) if d else None


def _cadence(status: Optional[dict]) -> int:
    try:
        return int((status or {}).get("cadence_seconds") or cfg.cadence_seconds())
    except (TypeError, ValueError):
        return cfg.cadence_seconds()


def mode_of(status: Optional[dict], age: Optional[float]) -> str:
    """live | delayed | closed | expired | not_connected | disabled -- what the shell's chip shows."""
    if not status:
        return "disabled" if not cfg.enabled() else "not_connected"
    st, session = status.get("state"), status.get("session")
    if st in ("expired", "not_connected"):
        return st
    if session == "open":
        if st == "live" and age is not None and age <= cfg.stale_after_seconds(_cadence(status)):
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
            "stale_after_seconds": cfg.stale_after_seconds(_cadence(status)), "cadence_seconds": _cadence(status), "mode": mode, "session": (status or {}).get("session") or snap.get("session"),
            "source": snap.get("source"), "final": bool(snap.get("final")), "count": len(quotes),
            "missing": [s for s in syms if s not in by_sym] if wanted is not None else [], "quotes": quotes,
            "note": "Prices are null/absent when Kite gave none. `stale` is true when the market is open and the newest data is older than "
                    f"{cfg.stale_after_seconds(_cadence(status)):g}s (2.5 cadences), or the feed is not connected.", "read_only": True}


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
            "holiday_checked": out.get("holiday_checked"), "read_only": True,
            "token_alert": out.get("token_alert") or {"state": None},
            "alert_state": (out.get("token_alert") or {}).get("state"),
            "platform_token": await pt.token_status(feed.db)}


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


@router.get("/close")
async def saved_close(request: Request, date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
                symbols: Optional[str] = Query(None, max_length=12000)) -> Dict[str, Any]:
    """The saved Kite closing quotes of one trading day (the newest saved day when `date` is omitted), in the same body as
    /quotes and /snapshot with mode "closed" and final true. Written once after each close; 404 when no close is saved."""
    await get_current_user(request)
    doc = await get_feed().read_close(date)
    if not doc:
        raise HTTPException(status_code=404, detail="no_saved_close")
    body = build_payload(doc, {"state": "market_closed", "session": "closed"}, _symbols(symbols) if symbols else None, datetime.now(timezone.utc))
    body.update({"mode": "closed", "session": "closed", "final": True, "stale": False, "date": doc.get("date")})
    return body


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



@router.post("/fno-quotes")
async def fno_quotes(request: Request) -> Dict[str, Any]:
    """Live premiums for a handful of NAMED F&O contracts (the legs a screen is showing).

    Not the websocket: the platform feed subscribes cash and indices only, and an index option chain
    runs to thousands of strikes against Kite's instrument cap. This asks Kite's REST quote() for the
    handful of contracts actually on screen.

    Always answers 200. When the feed is off, no token is stored, or Kite refuses, it returns
    `available: false` with the reason and NO prices, so the caller keeps the end-of-day figures it
    already had rather than showing a stale number as live.
    """
    await get_current_user(request)
    body = await request.json() if await request.body() else {}
    legs = body.get("legs") if isinstance(body, dict) else None
    if not isinstance(legs, list) or not legs:
        raise HTTPException(status_code=422, detail="legs must be a non-empty list")
    if len(legs) > fq.MAX_LEGS:
        raise HTTPException(status_code=422, detail=f"at most {fq.MAX_LEGS} legs per request")

    def off(reason: str) -> Dict[str, Any]:
        return {"available": False, "reason": reason, "quotes": {}, "unresolved": [], "source": None,
                "read_only": True}

    if not cfg.enabled():
        return off("the live feed is disabled")
    feed = get_feed()
    token = await pt.token_status(feed.db)
    if not token.get("stored") or token.get("expired"):
        return off("no Kite access token is stored for the platform feed")
    key, access = cfg.get_api_key(), cfg.get_token()
    if not key or not access:
        return off("the Kite API key or access token is not configured")
    try:
        # Same read-only wrapper the feed uses (gw.ReadOnlyKite): instruments/quote/historical/profile
        # and nothing else, so no order, GTT, margin or session call is reachable from here.
        kite = gw.default_kite_factory(key, access)
        nfo = await asyncio.to_thread(kite.instruments, "NFO")
    except Exception as e:  # noqa: BLE001 — an unreachable upstream is reported, never guessed around
        logger.warning("fno-quotes: instruments unavailable (%s)", type(e).__name__)
        return off(f"the contract list could not be read ({type(e).__name__})")

    keys, unresolved = fq.resolve(legs, fq.index_instruments(nfo))
    if not keys:
        return {"available": False, "reason": "none of the legs named a listed contract",
                "quotes": {}, "unresolved": unresolved, "source": "kite", "read_only": True}
    try:
        answer = await asyncio.to_thread(kite.quote, sorted(set(keys.values())))
    except Exception as e:  # noqa: BLE001
        logger.warning("fno-quotes: quote() failed (%s)", type(e).__name__)
        return off(f"the quote request failed ({type(e).__name__})")

    priced = fq.prices_from(answer, keys)
    return {
        "available": bool(priced),
        "reason": None if priced else "Kite returned no price for these contracts",
        "quotes": {str(i): v for i, v in priced.items()},
        "unresolved": unresolved,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "source": "kite REST quote (live when the market is open; the last traded price otherwise)",
        "read_only": True,
    }

@router.post("/kite/login-url")
async def kite_login_url(request: Request) -> Dict[str, Any]:
    """Admin only. A fresh single-use login link for the platform Kite session. Opening it is the one human step of the day
    (Zerodha 2FA); nothing here logs in on anyone's behalf. The link carries the API key (public) and a signed state, never a secret."""
    user = await require_admin(request)
    key = cfg.get_api_key()
    if not key:
        raise HTTPException(status_code=503, detail="kite_api_key_missing")
    if not pt.platform_user_id():
        raise HTTPException(status_code=503, detail="platform_user_not_configured")
    made = await pt.create_login_state(get_feed().db, str(user.get("user_id") or "admin"))
    return {"login_url": pt.login_url(key, made["state"]), "expires_at": made["expires_at"].isoformat(),
            "note": "Single use. Zerodha redirects to /api/broker/native/callback?broker=zerodha, which stores the day's token."}
