"""Personal watchlists — lists of stocks a user names, adds to and removes from.

Per-user, in MongoDB, scoped to the signed-in user on every route (a list that
is not yours answers 404, the same as one that does not exist).

Endpoints (all under /api):
    GET    /watchlists                         — the user's lists, oldest first
    POST   /watchlists                         — make a list            {name}
    POST   /watchlists/starter                 — make the example list, once per user
    GET    /watchlists/{id}                    — one list with its stocks and a quote for each
    PATCH  /watchlists/{id}                    — rename                 {name}
    DELETE /watchlists/{id}                    — delete the list
    POST   /watchlists/{id}/symbols            — add a stock            {symbol}
    DELETE /watchlists/{id}/symbols/{symbol}   — remove a stock

Store:
    user_watchlists        one document per list: watchlist_id, user_id, name,
                           name_key (the name case-folded; unique per user),
                           symbols [{symbol, company_name, added_at}],
                           is_starter, seeded_from, created_at, updated_at
    user_watchlist_state   one document per user (_id = user_id), written the first
                           time that user has a list. It is never removed, so
                           deleting the example list does not bring it back.

The example ("starter") list is real data: a copy of the symbols of the newest
published research watchlist (services/research_watchlist_store), marked
is_starter with the date it was copied from. Nothing here is sample data, and a
research list is not a recommendation.

Quotes, per stock, in this order:
    1. live  — the research watchlist's live-quote service (Yahoo Finance,
               services/research_watchlist_live). That service caches ONE batch
               for all of its callers, so it is always asked for the research
               watchlist's symbols, exactly as the research page asks. Asking it
               for one user's list would replace the batch that page reads.
    2. stored — the data platform's latest end-of-day bar for the symbol
               (GET /v1/prices/latest/{symbol}, nidp.prices_eod): the close, its
               change against the previous close, and the bar's date.
    3. none  — `quote` is null. A missing price is never sent as 0.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from deps import db, get_current_user
from services import research_watchlist_live as live
from services import research_watchlist_store as research_store
from services.copilot_tools import daas_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

MAX_LISTS = 20
MAX_SYMBOLS = 100
NAME_MAX = 60
STARTER_NAME = "Multibagger"

# NSE symbols: letters and digits, with "&", "-" and "." inside (M&M, BAJAJ-AUTO).
_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9&.\-]{0,23}$")

# How long a list read waits for the live-quote service before falling back to
# stored prices. The fetch itself carries on and fills the service's cache.
_LIVE_WAIT_S = 8.0
# End-of-day bars change once a day; one look-up per symbol is kept this long.
_STORED_TTL_S = 600.0
_STORED: Dict[str, Tuple[float, Optional[Dict[str, Any]]]] = {}
_STORED_CONCURRENCY = 8

_indexes_ready = False


class NameBody(BaseModel):
    name: str = Field(max_length=400)


class SymbolBody(BaseModel):
    symbol: str = Field(max_length=80)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _ensure_indexes() -> None:
    """One list per watchlist_id, and one name per user whatever its case."""
    global _indexes_ready
    if _indexes_ready:
        return
    try:
        await db.user_watchlists.create_index("watchlist_id", unique=True)
        await db.user_watchlists.create_index([("user_id", 1), ("name_key", 1)], unique=True)
        _indexes_ready = True
    except Exception as exc:  # noqa: BLE001
        # The routes still check names themselves; the index only closes the race
        # between two writes. Asked for again on the next write.
        logger.warning("watchlists: the indexes could not be created: %r", exc)


def _clean_name(raw: str) -> str:
    name = " ".join(raw.split())
    if not 1 <= len(name) <= NAME_MAX:
        raise HTTPException(status_code=422, detail=f"A list name needs 1 to {NAME_MAX} characters.")
    return name


def _clean_symbol(raw: str) -> str:
    symbol = raw.strip().upper()
    if not _SYMBOL_RE.match(symbol):
        raise HTTPException(status_code=422, detail="That is not a stock symbol.")
    return symbol


def _name_taken(name: str) -> HTTPException:
    return HTTPException(status_code=409, detail=f"You already have a list called “{name}”.")


def _list_full() -> HTTPException:
    return HTTPException(status_code=409, detail=f"A list holds up to {MAX_SYMBOLS} stocks. Remove one to add another.")


def _summary(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "watchlist_id": doc["watchlist_id"],
        "name": doc["name"],
        "symbol_count": len(doc.get("symbols") or []),
        "is_starter": bool(doc.get("is_starter")),
        "seeded_from": doc.get("seeded_from"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def _entry(doc: Dict[str, Any], symbol: str) -> Optional[Dict[str, Any]]:
    return next((e for e in doc.get("symbols") or [] if e.get("symbol") == symbol), None)


def _new_list(user_id: str, name: str, *, symbols: Optional[List[Dict[str, Any]]] = None,
              is_starter: bool = False, seeded_from: Optional[str] = None) -> Dict[str, Any]:
    now = _now()
    return {
        "watchlist_id": f"wl_{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "name": name,
        "name_key": name.casefold(),
        "symbols": symbols or [],
        "is_starter": is_starter,
        "seeded_from": seeded_from,
        "created_at": now,
        "updated_at": now,
    }


async def _owned(user_id: str, watchlist_id: str) -> Dict[str, Any]:
    doc = await db.user_watchlists.find_one({"watchlist_id": watchlist_id, "user_id": user_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="List not found")
    return doc


# ── the never-again marker ───────────────────────────────────────────────────
async def _has_had_a_list(user_id: str) -> bool:
    return await db.user_watchlist_state.find_one({"_id": user_id}) is not None


async def _record_first_list(user_id: str, via: str, seeded_from: Optional[str] = None) -> bool:
    """Record that this user has had a list. True only for the request that
    recorded it: the document's _id is the user, so two requests cannot both."""
    try:
        res = await db.user_watchlist_state.update_one(
            {"_id": user_id},
            {"$setOnInsert": {"user_id": user_id, "first_list_at": _now(), "first_list_via": via, "starter_seeded_from": seeded_from}},
            upsert=True,
        )
    except DuplicateKeyError:
        return False        # two upserts raced; the other one recorded it
    return res.matched_count == 0


# ── the instrument master ────────────────────────────────────────────────────
async def _research_name(symbol: str) -> Tuple[bool, Optional[str]]:
    """(the research watchlist publishes this symbol, its company name there)."""
    for row in await research_store.list_dates():
        pick = await research_store.get_pick(row["list_date"], symbol)
        if pick:
            return True, (str(pick.get("company_name") or "").strip() or None)
    return False, None


async def _company_name(symbol: str) -> Optional[str]:
    """The company name for a symbol the app knows; raises when it does not.

    The symbol master (nidp.sector_master, through the data platform's
    /v1/symbols/search, which puts an exact symbol first) is the authority. A
    stock in a published research list is also accepted, since the app already
    shows it. When the master does not answer, a symbol that is not such a stock
    is refused with 503 rather than guessed at.
    """
    try:
        found = await daas_client.search_symbols(symbol, limit=5)       # None when the platform did not answer
    except Exception as exc:  # noqa: BLE001
        logger.warning("watchlists: the symbol master look-up failed for %s: %r", symbol, exc)
        found = None
    if found is not None and not isinstance(found, dict):
        found = None
    for row in (found or {}).get("data") or []:
        if str(row.get("symbol") or "").strip().upper() == symbol:
            return str(row.get("company_name") or "").strip() or None
    published, name = await _research_name(symbol)
    if published:
        return name
    if found is None:
        logger.warning("watchlists: the symbol master did not answer for %s", symbol)
        raise HTTPException(
            status_code=503,
            detail="The instrument list could not be checked just now, so nothing was added. Please try again.",
        )
    raise HTTPException(status_code=422, detail=f"“{symbol}” is not a stock in the instrument list.")


# ── quotes ───────────────────────────────────────────────────────────────────
def _number(value: Any) -> Optional[float]:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _price(value: Any) -> Optional[float]:
    """A price is a positive number. Zero is what a missing price looks like."""
    number = _number(value)
    return number if number is not None and number > 0 else None


def _log_abandoned(task: "asyncio.Future[Any]") -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.warning("watchlists: the live-quote fetch failed after the wait: %r", task.exception())


async def _live_batch() -> Tuple[Dict[str, Dict[str, Any]], Optional[str]]:
    """(the live-quote service's batch, when the service fetched it)."""
    try:
        symbols = await research_store.all_symbols()
        if not symbols:
            return {}, None
        fetch = asyncio.ensure_future(live.get_live_quotes(symbols))
        try:
            quotes = await asyncio.wait_for(asyncio.shield(fetch), timeout=_LIVE_WAIT_S)
        except asyncio.TimeoutError:
            fetch.add_done_callback(_log_abandoned)
            logger.warning("watchlists: live quotes took over %.0fs; showing stored prices this time", _LIVE_WAIT_S)
            return {}, None
    except Exception as exc:  # noqa: BLE001
        logger.warning("watchlists: live quotes are unavailable: %r", exc)
        return {}, None
    # The service keeps the time it filled its batch; that is the quotes' "as of".
    stamp = _number(getattr(live, "_CACHE", {}).get("ts"))
    fetched_at = datetime.fromtimestamp(stamp, timezone.utc).isoformat() if stamp and stamp > 0 else None
    return (quotes if isinstance(quotes, dict) else {}), fetched_at


def _stored_quote(row: Any) -> Optional[Dict[str, Any]]:
    """A quote from one end-of-day bar; None when the bar has no real close."""
    if not isinstance(row, dict):
        return None
    close = _price(row.get("close_price"))
    if close is None:
        return None
    previous = _price(row.get("prev_close"))
    as_of = row.get("as_of_date")
    return {
        "price": round(close, 2),
        "day_change": round(close - previous, 2) if previous else None,
        "day_change_pct": round((close - previous) / previous * 100, 2) if previous else None,
        "as_of": str(as_of) if as_of else None,
        "is_live": False,
    }


async def _stored_quotes(symbols: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
    gate = asyncio.Semaphore(_STORED_CONCURRENCY)

    async def one(symbol: str) -> Optional[Dict[str, Any]]:
        kept = _STORED.get(symbol)
        if kept and time.time() - kept[0] < _STORED_TTL_S:
            return kept[1]
        try:
            async with gate:
                row = await daas_client.get_stock_price_latest(symbol)
        except Exception as exc:  # noqa: BLE001
            # Not kept: a failed look-up is not "this stock has no price".
            logger.warning("watchlists: no stored price for %s: %r", symbol, exc)
            return None
        quote = _stored_quote(row)
        _STORED[symbol] = (time.time(), quote)
        return quote

    return dict(zip(symbols, await asyncio.gather(*(one(s) for s in symbols))))


async def _quotes_for(symbols: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
    if not symbols:
        return {}
    batch, fetched_at = await _live_batch()
    out: Dict[str, Optional[Dict[str, Any]]] = {}
    for symbol in symbols:
        quote = batch.get(symbol) or {}
        price = _price(quote.get("price"))
        if price is not None:
            out[symbol] = {
                "price": price,
                "day_change": _number(quote.get("day_change")),
                "day_change_pct": _number(quote.get("day_change_pct")),
                "as_of": fetched_at,
                "is_live": True,
            }
    out.update(await _stored_quotes([s for s in symbols if s not in out]))
    return out


# ── routes ───────────────────────────────────────────────────────────────────
@router.get("/watchlists")
async def list_watchlists(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = user["user_id"]
    docs = await db.user_watchlists.find({"user_id": uid}, {"_id": 0}).sort("created_at", 1).to_list(MAX_LISTS + 10)
    # True when this user has never had a list: the screen then asks for the
    # example list once. Never while an advisor is looking at a client's account.
    pending = not docs and not user.get("_active_profile_id") and not await _has_had_a_list(uid)
    return {
        "lists": [_summary(d) for d in docs],
        "limits": {"max_lists": MAX_LISTS, "max_symbols": MAX_SYMBOLS},
        "starter_pending": pending,
    }


@router.post("/watchlists")
async def create_watchlist(request: Request, payload: NameBody) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = user["user_id"]
    name = _clean_name(payload.name)
    await _ensure_indexes()
    if await db.user_watchlists.count_documents({"user_id": uid}) >= MAX_LISTS:
        raise HTTPException(status_code=409, detail=f"You can keep up to {MAX_LISTS} lists. Delete one to make another.")
    clash = await db.user_watchlists.find_one({"user_id": uid, "name_key": name.casefold()}, {"_id": 0, "name": 1})
    if clash:
        raise _name_taken(clash.get("name") or name)
    doc = _new_list(uid, name)
    try:
        await db.user_watchlists.insert_one(doc)
    except DuplicateKeyError:
        raise _name_taken(name)
    await _record_first_list(uid, "own_list")
    return _summary(doc)


def _no_starter(reason: str) -> Dict[str, Any]:
    return {"created": False, "reason": reason, "watchlist": None}


@router.post("/watchlists/starter")
async def create_starter(request: Request) -> Dict[str, Any]:
    """Make the example list for a user who has never had a list. Safe to call
    again: it answers `created: false` and changes nothing."""
    user = await get_current_user(request)
    uid = user["user_id"]
    if user.get("_active_profile_id"):
        # An advisor looking at a client: this would write into the client's account unasked.
        return _no_starter("viewing_a_client")
    await _ensure_indexes()
    if await _has_had_a_list(uid) or await db.user_watchlists.count_documents({"user_id": uid}) > 0:
        return _no_starter("already_had_a_list")

    dates = await research_store.list_dates()
    list_date = dates[0]["list_date"] if dates else None
    picks = await research_store.list_picks(list_date) if list_date else []
    now = _now()
    symbols: List[Dict[str, Any]] = []
    for pick in picks:
        symbol = str(pick.get("symbol") or "").strip().upper()
        if not symbol or any(s["symbol"] == symbol for s in symbols):
            continue
        symbols.append({"symbol": symbol, "company_name": str(pick.get("company_name") or "").strip() or None, "added_at": now})
        if len(symbols) == MAX_SYMBOLS:
            break
    if not symbols:
        # Nothing is recorded, so the list is made on a later visit, once research publishes one.
        return _no_starter("no_research_list")

    if not await _record_first_list(uid, "starter", list_date):
        return _no_starter("already_had_a_list")
    doc = _new_list(uid, STARTER_NAME, symbols=symbols, is_starter=True, seeded_from=list_date)
    try:
        await db.user_watchlists.insert_one(doc)
    except Exception:
        # The list was not stored: take the marker back so the next visit can try again.
        await db.user_watchlist_state.delete_one({"_id": uid})
        raise
    return {"created": True, "reason": None, "watchlist": _summary(doc)}


@router.get("/watchlists/{watchlist_id}")
async def get_watchlist(request: Request, watchlist_id: str) -> Dict[str, Any]:
    user = await get_current_user(request)
    doc = await _owned(user["user_id"], watchlist_id)
    entries = doc.get("symbols") or []
    quotes = await _quotes_for([e["symbol"] for e in entries])
    stocks = [
        {"symbol": e["symbol"], "company_name": e.get("company_name"), "added_at": e.get("added_at"), "quote": quotes.get(e["symbol"])}
        for e in entries
    ]
    live_count = sum(1 for s in stocks if s["quote"] and s["quote"]["is_live"])
    stored_count = sum(1 for s in stocks if s["quote"] and not s["quote"]["is_live"])
    return {
        **_summary(doc),
        "stocks": stocks,
        "quotes": {
            "live": live_count,
            "stored": stored_count,
            "none": len(stocks) - live_count - stored_count,
            "live_source": "yahoo_finance",
            "stored_source": "nidp.prices_eod",
        },
    }


@router.patch("/watchlists/{watchlist_id}")
async def rename_watchlist(request: Request, watchlist_id: str, payload: NameBody) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = user["user_id"]
    name = _clean_name(payload.name)
    await _owned(uid, watchlist_id)
    await _ensure_indexes()
    clash = await db.user_watchlists.find_one(
        {"user_id": uid, "name_key": name.casefold(), "watchlist_id": {"$ne": watchlist_id}}, {"_id": 0, "name": 1},
    )
    if clash:
        raise _name_taken(clash.get("name") or name)
    try:
        await db.user_watchlists.update_one(
            {"watchlist_id": watchlist_id, "user_id": uid},
            {"$set": {"name": name, "name_key": name.casefold(), "updated_at": _now()}},
        )
    except DuplicateKeyError:
        raise _name_taken(name)
    return _summary(await _owned(uid, watchlist_id))


@router.delete("/watchlists/{watchlist_id}")
async def delete_watchlist(request: Request, watchlist_id: str) -> Dict[str, str]:
    user = await get_current_user(request)
    res = await db.user_watchlists.delete_one({"watchlist_id": watchlist_id, "user_id": user["user_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="List not found")
    return {"status": "deleted", "watchlist_id": watchlist_id}


@router.post("/watchlists/{watchlist_id}/symbols")
async def add_symbol(request: Request, watchlist_id: str, payload: SymbolBody) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = user["user_id"]
    symbol = _clean_symbol(payload.symbol)
    doc = await _owned(uid, watchlist_id)

    def already(current: Dict[str, Any], entry: Dict[str, Any]) -> Dict[str, Any]:
        return {"added": False, "reason": "already_in_list", "stock": entry, "watchlist": _summary(current)}

    existing = _entry(doc, symbol)
    if existing:
        return already(doc, existing)
    if len(doc.get("symbols") or []) >= MAX_SYMBOLS:
        raise _list_full()

    entry = {"symbol": symbol, "company_name": await _company_name(symbol), "added_at": _now()}
    # The write carries its own guards (not already there, room left), so two
    # requests that both read the list before writing cannot break either rule.
    res = await db.user_watchlists.update_one(
        {
            "watchlist_id": watchlist_id,
            "user_id": uid,
            "symbols.symbol": {"$ne": symbol},
            f"symbols.{MAX_SYMBOLS - 1}": {"$exists": False},
        },
        {"$push": {"symbols": entry}, "$set": {"updated_at": entry["added_at"]}},
    )
    doc = await _owned(uid, watchlist_id)
    if res.matched_count == 0:
        existing = _entry(doc, symbol)
        if existing:
            return already(doc, existing)
        raise _list_full()
    return {"added": True, "reason": None, "stock": entry, "watchlist": _summary(doc)}


@router.delete("/watchlists/{watchlist_id}/symbols/{symbol}")
async def remove_symbol(request: Request, watchlist_id: str, symbol: str) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = user["user_id"]
    symbol = _clean_symbol(symbol)
    doc = await _owned(uid, watchlist_id)
    if not _entry(doc, symbol):
        return {"removed": False, "symbol": symbol, "watchlist": _summary(doc)}
    await db.user_watchlists.update_one(
        {"watchlist_id": watchlist_id, "user_id": uid},
        {"$pull": {"symbols": {"symbol": symbol}}, "$set": {"updated_at": _now()}},
    )
    return {"removed": True, "symbol": symbol, "watchlist": _summary(await _owned(uid, watchlist_id))}
