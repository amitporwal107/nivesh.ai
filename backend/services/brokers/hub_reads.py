"""Broker hub reads — holdings and positions for natively connected accounts.

A native account (`broker_accounts.native == True`, written by
`routes.broker_native`) holds the broker's own session token. This module
is the one read path for such an account:

  * holdings  — fetched on connect, on demand, and once a day while the
                session is live (`daily_sync`); stored in `db.holdings`
                tagged with `broker_account_id`. The broker wins: statement
                copies of what the account holds are then removed
                (`helpers.holdings_reconcile`).
  * positions — fetched on demand only; read live and never stored.

Strictly read-only: nothing here places, modifies or cancels an order.

Reader choice is deterministic. When `fenix_reader.supports(slug)` reports
the read, Fenix serves it; otherwise the broker's own adapter from
`registry.get(slug)` does — for positions its `fetch_hub_positions(token,
kind)` when it has one, else `fetch_positions` (the net book only). There
is no fallback from one reader to another on error — the error surfaces.

Errors raised to callers:

    sessions.SessionEnded   the account holds no live session (reconnect)
    BrokerSessionExpired    the broker refused the stored token; the session
                            is ended here before the error is re-raised
    BrokerNotSupported      no reader can serve this read for this broker
    BrokerReadError         any other broker-side failure
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from helpers import holdings_reconcile
from services import dashboard_cache
from . import fenix_reader, registry, sessions
from ._helpers import to_thread
from .base import AccessToken, Holding, HubPosition, Position
from .fenix_reader import BrokerNotSupported, BrokerReadError, BrokerSessionExpired

logger = logging.getLogger(__name__)

# `source` on a holdings row written from a native account. OpenAlgo rows
# keep `source = "openalgo"`; both carry `broker` + `broker_account_id`.
NATIVE_SOURCE = "broker_native"

# How many accounts `daily_sync` reads from brokers at the same time.
DAILY_SYNC_CONCURRENCY = 4

# Error codes shared by the routes and the stored `last_error` text.
CODE_SESSION_EXPIRED = "BROKER_SESSION_EXPIRED"
CODE_NOT_SUPPORTED = "BROKER_READ_NOT_SUPPORTED"
CODE_READ_FAILED = "BROKER_READ_FAILED"

_ASSET_TYPES = ("equity", "mutual_fund", "etf", "bond", "gold", "fd", "other")

# Broker product codes → the hub's product vocabulary. A code that is not
# listed stays None rather than being guessed; `product_raw` keeps the code.
_PRODUCT_CODES: Dict[str, str] = {
    "MIS": "intraday", "I": "intraday", "INTRADAY": "intraday",
    "BO": "intraday", "CO": "intraday",
    "CNC": "delivery", "D": "delivery", "DELIVERY": "delivery",
    "NRML": "carryforward", "CARRYFORWARD": "carryforward",
    "MTF": "margin", "MARGIN": "margin",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def display_name(slug: str) -> str:
    """The broker's display name from the adapter registry (the slug itself
    when no adapter is registered for it)."""
    try:
        return registry.get(slug).DISPLAY
    except KeyError:
        return slug


def describe_failure(exc: BaseException, slug: str, what: str) -> Tuple[str, str]:
    """`(code, message)` for a failed read of `what` ("holdings", "net
    positions", …). The message is built from fixed text and the broker's
    display name — never from the exception — so it cannot carry a token,
    a secret or a raw broker payload.
    """
    name = display_name(slug) or "the broker"
    if isinstance(exc, (sessions.SessionEnded, BrokerSessionExpired)):
        return CODE_SESSION_EXPIRED, f"Your {name} session has ended. Reconnect the account to continue."
    if isinstance(exc, BrokerNotSupported):
        return CODE_NOT_SUPPORTED, f"Reading {what} is not available for {name}."
    return CODE_READ_FAILED, f"Could not read {what} from {name}. Please try again."


# ── Reader selection ─────────────────────────────────────────────────────
def _live_token(doc: dict) -> AccessToken:
    """The account's session token, or raise. Only native rows hold a broker
    session; an OpenAlgo row's stored key is not a broker token and must
    never be sent to a broker as one."""
    if not doc.get("native"):
        raise BrokerNotSupported("Live broker reads need a directly connected account")
    if not sessions.is_live(doc):
        raise sessions.SessionEnded("The broker session has ended")
    return sessions.load_token(doc)


async def _fenix_supports(slug: str) -> Dict[str, bool]:
    """`fenix_reader.supports`, off the event loop: its first call imports
    fenix, which takes a few seconds when cold."""
    return await to_thread(fenix_reader.supports, slug)


def _is_token_rejection(exc: BaseException) -> bool:
    """True when an adapter error means the broker refused the session token.

    The raw-HTTP adapters (Upstox, Fyers, Dhan, AliceBlue) surface it as an
    `httpx.HTTPStatusError` with 401/403 from `raise_for_status()`.
    kiteconnect (Zerodha) and SmartApi (Angel One) each raise their own
    `TokenException`, and an adapter may define its own `…SessionExpired`;
    both are matched by class name so no SDK has to be importable here.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (401, 403)
    return any(
        cls.__name__ == "TokenException" or cls.__name__.endswith("SessionExpired")
        for cls in type(exc).__mro__
    )


def _is_not_supported(exc: BaseException) -> bool:
    """True when an adapter says it cannot serve the read at all: a
    `NotImplementedError`, or its own exception named `…NotSupported`."""
    if isinstance(exc, NotImplementedError):
        return True
    return any(cls.__name__.endswith("NotSupported") for cls in type(exc).__mro__)


def _error_label(exc: BaseException) -> str:
    """Short, payload-free description of an error for messages and logs:
    the HTTP status or the exception class, never its text. For an error
    already mapped onto a hub type, the underlying cause is described."""
    if isinstance(exc, BrokerReadError) and exc.__cause__ is not None:
        exc = exc.__cause__
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__


def _adapter_for(slug: str, what: str):
    """The broker's own adapter, or `BrokerNotSupported` when there is none
    that can read."""
    try:
        adapter = registry.get(slug)
    except KeyError:
        raise BrokerNotSupported(f"No reader is registered for broker '{slug}'") from None
    if not getattr(adapter, "IMPLEMENTED", True):
        # Placeholder adapters from `_stub` only raise.
        raise BrokerNotSupported(f"{adapter.DISPLAY} has no {what} reader yet")
    return adapter


async def _adapter_call(adapter, what: str, fetch, *args) -> list:
    """Run one adapter read, mapping its failures onto the hub's error types."""
    try:
        return await fetch(*args)
    except BrokerReadError:
        raise
    except Exception as exc:  # noqa: BLE001
        if _is_token_rejection(exc):
            raise BrokerSessionExpired(f"{adapter.DISPLAY} rejected the stored session") from exc
        if _is_not_supported(exc):
            raise BrokerNotSupported(f"{adapter.DISPLAY} cannot serve {what}") from exc
        raise BrokerReadError(
            f"{adapter.DISPLAY} {what} read failed ({_error_label(exc)})",
        ) from exc


# ── Holdings ─────────────────────────────────────────────────────────────
async def read_holdings_for(doc: dict) -> list[Holding]:
    """Live holdings for one native account. Reads only — nothing is stored."""
    slug = doc.get("broker") or ""
    token = _live_token(doc)
    if (await _fenix_supports(slug)).get("holdings"):
        return await fenix_reader.read_holdings(slug, token)
    adapter = _adapter_for(slug, "holdings")
    return await _adapter_call(adapter, "holdings", adapter.fetch_holdings, token)


async def sync_account(db, doc: dict) -> dict:
    """Read one native account's holdings and store them, replacing only that
    account's rows. Returns `{"count": n, "holdings": [...]}` — the same
    summary rows the OpenAlgo sync returns.
    """
    account_id = doc["account_id"]
    user_id = doc["user_id"]
    try:
        holdings = await read_holdings_for(doc)
    except BrokerSessionExpired:
        await sessions.end_session(db, account_id, "broker_rejected")
        raise
    except sessions.SessionEnded:
        raise
    except Exception as exc:  # noqa: BLE001
        _, message = describe_failure(exc, doc.get("broker") or "", "holdings")
        logger.warning(
            "broker sync failed account=%s broker=%s error=%s",
            account_id, doc.get("broker"), _error_label(exc),
        )
        # `status` is left alone: for a native row it tracks the session
        # (sessions.STATUS_*), and a failed read does not end the session.
        await db.broker_accounts.update_one(
            {"account_id": account_id},
            {"$set": {"last_error": message, "updated_at": _now_iso()}},
        )
        raise

    rows = await _persist_holdings(db, user_id, account_id, doc, holdings)
    await _apply_broker_wins(db, user_id, account_id, doc.get("broker") or "", rows)
    await _invalidate_user_caches(db, user_id)
    saved = [
        {
            "holding_id": r["holding_id"],
            "name": r["name"],
            "ticker": r["ticker"],
            "asset_type": r["asset_type"],
            "quantity": r["quantity"],
        }
        for r in rows
    ]

    now = _now_iso()
    # Not for a session that was ended (logout / expiry) while the read was
    # in flight — that row must keep saying it needs a reconnect.
    await db.broker_accounts.update_one(
        {"account_id": account_id, "status": {"$ne": sessions.STATUS_EXPIRED}},
        {"$set": {
            "status": sessions.STATUS_ACTIVE,
            "last_sync_at": now,
            "last_sync_count": len(saved),
            "last_error": None,
            "updated_at": now,
        }},
    )
    return {"count": len(saved), "holdings": saved}


async def _persist_holdings(
    db, user_id: str, account_id: str, account_doc: dict, holdings: List[Holding],
) -> List[Dict[str, Any]]:
    """Replace this account's prior holdings, leave every other row alone
    (CAS / Excel imports, other broker accounts), and return the rows as
    stored. Mirrors `routes.broker_connect._persist_broker_holdings`, which
    stays the writer for OpenAlgo accounts.
    """
    await db.holdings.delete_many(
        {"user_id": user_id, "broker_account_id": account_id},
    )

    stored: List[Dict[str, Any]] = []
    now = _now_iso()
    for h in holdings:
        # Brokers also list instruments that were sold out (ICICI's demat list
        # does, with every quantity field at zero): that is not a holding.
        if float(h.quantity or 0) <= 0:
            continue
        asset_type = h.asset_type if h.asset_type in _ASSET_TYPES else "equity"
        holding_doc = {
            "holding_id": f"hold_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "portfolio_id": "",
            "name": h.name or h.symbol or "Unknown",
            "ticker": h.symbol or "",
            "asset_type": asset_type,
            "quantity": float(h.quantity or 0),
            "buy_price": float(h.avg_price or 0),
            "current_price": float(h.current_price or 0),
            "sector": h.sector or "Other",
            "buy_date": None,
            "source": NATIVE_SOURCE,
            "source_id": h.source_id or "",
            "broker": account_doc.get("broker"),
            "broker_account_id": account_id,
            "uploaded_at": now,
            "created_at": now,
        }
        # What `holdings_reconcile` matches on. Left out, not blank, when
        # the broker gave none.
        isin = str(h.isin or "").strip().upper()
        if isin:
            holding_doc["isin"] = isin
        _fill_from_masterdata(holding_doc)
        await db.holdings.insert_one(holding_doc)
        stored.append(holding_doc)
    return stored


def _fill_from_masterdata(row: Dict[str, Any]) -> None:
    """Fill what the broker left blank from an exact ISIN lookup: the company
    name where the broker gave only its own code (ICICI) or a scrip label, a
    price where it gave none (Groww, Motilal Oswal), and the sector. Never
    changes ticker, quantity or cost. A failed lookup leaves the row as the
    broker gave it; it must not fail the sync.
    """
    try:
        from services import masterdata
        from services.equity_sectors import enrich_holdings_with_sectors
        masterdata.enrich_broker_row(row)
        enrich_holdings_with_sectors([row])
    except Exception as exc:  # noqa: BLE001
        logger.warning("broker sync: masterdata fill skipped for one row (%s)", type(exc).__name__)


async def _apply_broker_wins(
    db, user_id: str, account_id: str, broker: str, rows: List[Dict[str, Any]],
) -> None:
    """The broker wins: drop the statement / export copies of what this
    account now holds (`helpers.holdings_reconcile`). The account's rows are
    already stored, so a failure here is logged and does not fail the sync."""
    try:
        await holdings_reconcile.apply_broker_wins(db, user_id, rows, broker=broker, live=True)
    except Exception:  # noqa: BLE001
        logger.exception(
            "broker sync: reconcile failed account=%s broker=%s — synced rows kept",
            account_id, broker,
        )


async def _invalidate_user_caches(db, user_id: str) -> None:
    """Drop what is derived from the user's holdings. Best-effort: the
    holdings are already stored, so a cache failure is logged, not raised."""
    try:
        await db.mfd_profile_signal_cache.delete_one({"user_id": user_id})
    except Exception as exc:  # noqa: BLE001
        logger.warning("broker sync: profile-signal cache not cleared: %s", type(exc).__name__)
    try:
        # Dashboards are built from `db.holdings` and cached per user for
        # 24h; every other holdings writer (upload, manual edit) clears it.
        await dashboard_cache.invalidate(user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("broker sync: dashboard cache not cleared: %s", type(exc).__name__)


# ── Positions ────────────────────────────────────────────────────────────
def _segment_for(exchange: str) -> str:
    ex = (exchange or "").upper()
    if ex in ("NFO", "BFO"):
        return "fno"
    if ex == "MCX":
        return "commodity"
    if ex in ("CDS", "BCD"):
        return "currency"
    return "equity"


def _hub_position(p: Position, kind: str) -> HubPosition:
    """An adapter `Position` in the hub's shape. Fields the adapter does not
    provide (last price, contract details, name) stay None — never invented."""
    raw: Optional[str] = (str(p.product).strip() or None) if p.product is not None else None
    product = _PRODUCT_CODES.get(raw.upper()) if raw else None
    return HubPosition(
        symbol=p.symbol,
        exchange=p.exchange,
        quantity=float(p.quantity or 0),
        avg_price=float(p.avg_price or 0),
        last_price=None,
        pnl=float(p.pnl or 0),
        product=product,
        product_raw=raw,
        segment=_segment_for(p.exchange),
        is_intraday=product == "intraday",
        instrument_type=None,
        expiry=None,
        strike=None,
        kind=kind,
        name=getattr(p, "name", None),
    )


async def _read_positions(doc: dict, kind: str) -> list[dict]:
    slug = doc.get("broker") or ""
    token = _live_token(doc)
    if (await _fenix_supports(slug)).get("positions"):
        rows = await fenix_reader.read_positions(slug, token, kind)
        return [asdict(p) for p in rows]
    adapter = _adapter_for(slug, "positions")
    fetch_hub = getattr(adapter, "fetch_hub_positions", None)
    if fetch_hub is not None:
        # The richer adapter read serves both books itself, and raises its
        # own "not supported" for one it cannot.
        rows = await _adapter_call(adapter, f"{kind} positions", fetch_hub, token, kind)
        return [asdict(p) for p in rows]
    if kind != "net":
        # `fetch_positions` returns the net book only; net rows must not be
        # handed back labelled as the day book.
        raise BrokerNotSupported(f"{adapter.DISPLAY} day positions have no reader")
    rows = await _adapter_call(adapter, "net positions", adapter.fetch_positions, token)
    return [asdict(_hub_position(p, kind)) for p in rows]


async def read_account_positions(db, doc: dict, kind: str = "net") -> list[dict]:
    """Live positions for one native account as `HubPosition` dicts. `kind`
    is "net" (carried forward + today) or "day" (today's trades). Read from
    the broker on every call; nothing is stored.
    """
    if kind not in ("net", "day"):
        raise ValueError("kind must be 'net' or 'day'")
    try:
        return await _read_positions(doc, kind)
    except BrokerSessionExpired:
        await sessions.end_session(db, doc["account_id"], "broker_rejected")
        raise
    except (sessions.SessionEnded, BrokerNotSupported):
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "broker positions read failed account=%s broker=%s kind=%s error=%s",
            doc.get("account_id"), doc.get("broker"), kind, _error_label(exc),
        )
        raise


# ── Daily sync ───────────────────────────────────────────────────────────
async def daily_sync(db) -> dict:
    """Refresh holdings for every native account whose session is live.

    Returns `{"accounts", "synced", "expired", "failed"}`:
        accounts — native accounts looked at
        synced   — holdings refreshed
        expired  — not synced because the session has ended (before this
                   run, in the expiry sweep, or rejected by the broker now)
        failed   — session live but the read or the save failed
    so `accounts == synced + expired + failed`.
    """
    await sessions.expire_due_sessions(db)
    docs = await db.broker_accounts.find({"native": True}, {"_id": 0}).to_list(length=None)

    gate = asyncio.Semaphore(DAILY_SYNC_CONCURRENCY)

    async def _one(doc: dict) -> str:
        if not sessions.is_live(doc):
            return "expired"
        async with gate:
            try:
                await sync_account(db, doc)
                return "synced"
            except (sessions.SessionEnded, BrokerSessionExpired):
                return "expired"
            except Exception as exc:  # noqa: BLE001
                # One account must never stop the rest. `sync_account` has
                # already recorded a read failure on the account row.
                logger.warning(
                    "broker daily sync: account=%s broker=%s failed: %s",
                    doc.get("account_id"), doc.get("broker"), _error_label(exc),
                )
                return "failed"

    outcomes = await asyncio.gather(*(_one(d) for d in docs))
    summary = {
        "accounts": len(docs),
        "synced": outcomes.count("synced"),
        "expired": outcomes.count("expired"),
        "failed": outcomes.count("failed"),
    }
    logger.info(
        "broker daily sync: accounts=%d synced=%d expired=%d failed=%d",
        summary["accounts"], summary["synced"], summary["expired"], summary["failed"],
    )
    return summary
