"""Broker hub reads — holdings and positions for natively connected accounts.

A native account (`broker_accounts.native == True`, written by
`routes.broker_native`) holds the broker's own session token. This module
is the one read path for such an account:

  * holdings  — fetched on connect, on demand, and once a day while the
                session is live (`daily_sync`); stored in `db.holdings`
                tagged with `broker_account_id`. The broker wins: statement
                copies of what the account holds are then removed
                (`helpers.holdings_reconcile`). Each sync leaves a snapshot
                (`sync_snapshots`) with the result of its duplicate check.
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
import math
import re
import uuid
from dataclasses import asdict
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from helpers import holdings_reconcile
from services import dashboard_cache
from . import fenix_reader, registry, sessions, sync_snapshots
from ._helpers import to_thread
from .base import AccessToken, ContractRef, Holding, HubPosition, Position
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

# The views of a contract chart (`read_contract_chart`): five-minute and
# thirty-minute bars.
CHART_INTERVALS = ("5m", "30m")
_CONTRACT_KINDS = ("FUT", "CE", "PE")
_SYMBOL_RE = re.compile(r"[A-Z0-9][A-Z0-9&._-]{0,39}")
_EXCHANGE_RE = re.compile(r"[A-Z]{2,10}")

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


async def sync_account(db, doc: dict, *, trigger: str = "manual") -> dict:
    """Read one native account's holdings and store them, replacing only that
    account's rows, then keep a snapshot of the sync.

    `trigger` says what started it: "connect", "manual" or "daily". Returns
    `{"count", "holdings", "duplicates", "snapshot_id"}` — `holdings` are the
    summary rows the OpenAlgo sync returns and `snapshot_id` is None when the
    snapshot could not be written. `duplicates` is the duplicate check:

        repeated_in_broker_reply, same_instrument_lines   see `_persist_holdings`
        broker_file_rows_replaced, statement_rows_replaced  see `_apply_broker_wins`
        also_in_other_accounts                             see `_held_in_other_accounts`

    A counter of the last three is None when its check could not run: the
    number is then not known, which is not the same as zero.
    """
    if trigger not in sync_snapshots.TRIGGERS:
        raise ValueError(f"trigger must be one of {sync_snapshots.TRIGGERS}")
    account_id = doc["account_id"]
    user_id = doc["user_id"]
    broker = doc.get("broker") or ""
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

    rows, in_reply = await _persist_holdings(db, user_id, account_id, doc, holdings)
    replaced = await _apply_broker_wins(db, user_id, account_id, broker, rows)
    duplicates = {
        **in_reply,
        "broker_file_rows_replaced": replaced["export_rows_removed"],
        "statement_rows_replaced": replaced["statement_rows_removed"],
        "also_in_other_accounts": await _held_in_other_accounts(db, user_id, account_id, broker, rows),
    }
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
    snapshot_id = await _record_snapshot(
        db, doc, rows, trigger=trigger, duplicates=duplicates, synced_at=now,
    )
    return {
        "count": len(saved),
        "holdings": saved,
        "duplicates": duplicates,
        "snapshot_id": snapshot_id,
    }


def _instrument_key(row: Dict[str, Any]) -> str:
    """What makes two rows the same instrument: the ISIN when the row has
    one, else exchange + trading symbol (`source_id`), else the ticker."""
    for field in ("isin", "source_id", "ticker"):
        value = str(row.get(field) or "").strip().upper()
        if value:
            return value
    return ""


async def _persist_holdings(
    db, user_id: str, account_id: str, account_doc: dict, holdings: List[Holding],
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Replace this account's prior holdings, leave every other row alone
    (CAS / Excel imports, other broker accounts). Mirrors
    `routes.broker_connect._persist_broker_holdings`, which stays the writer
    for OpenAlgo accounts.

    Returns the rows as stored and what the duplicate check found inside the
    broker's reply:
        repeated_in_broker_reply — a line the broker sent again (same
            instrument, quantity and average price): one copy is stored
        same_instrument_lines — a further line for an instrument already in
            the reply, with another quantity or cost (a separate lot): every
            such line is stored, and counted here
    """
    await db.holdings.delete_many(
        {"user_id": user_id, "broker_account_id": account_id},
    )

    stored: List[Dict[str, Any]] = []
    seen_lines: set = set()
    seen_instruments: set = set()
    repeated = same_instrument = 0
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
        key = _instrument_key(holding_doc)
        if key:
            line = (key, holding_doc["quantity"], holding_doc["buy_price"])
            if line in seen_lines:
                repeated += 1
                continue
            if key in seen_instruments:
                same_instrument += 1
            seen_lines.add(line)
            seen_instruments.add(key)
        _fill_from_masterdata(holding_doc)
        await db.holdings.insert_one(holding_doc)
        stored.append(holding_doc)
    return stored, {
        "repeated_in_broker_reply": repeated,
        "same_instrument_lines": same_instrument,
    }


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
) -> Dict[str, Optional[int]]:
    """The broker wins: drop the statement copies of what this account now
    holds, and the rows of an uploaded export of the same broker for the same
    instruments (`helpers.holdings_reconcile`). Returns its counts of removed
    rows. The account's rows are already stored, so a failure here is logged
    and does not fail the sync — the counts are then None (not known)."""
    try:
        return await holdings_reconcile.apply_broker_wins(db, user_id, rows, broker=broker, live=True)
    except Exception:  # noqa: BLE001
        logger.exception(
            "broker sync: reconcile failed account=%s broker=%s — synced rows kept",
            account_id, broker,
        )
        return {"statement_rows_removed": None, "export_rows_removed": None}


async def _held_in_other_accounts(
    db, user_id: str, account_id: str, broker: str, rows: List[Dict[str, Any]],
) -> Optional[int]:
    """How many of the instruments just stored this user also holds in
    another connected account of the same broker. Two logins at one broker
    are two real accounts, so those rows are never removed — the overlap is
    only counted. A failed read is logged and gives None (not known)."""
    mine = {_instrument_key(r) for r in rows} - {""}
    if not mine:
        return 0
    try:
        cursor = db.holdings.find(
            {
                "user_id": user_id,
                "broker": broker,
                "broker_account_id": {"$nin": [None, "", account_id]},
            },
            {"_id": 0, "isin": 1, "source_id": 1, "ticker": 1},
        )
        others = {_instrument_key(r) for r in await cursor.to_list(length=5000)}
    except Exception:  # noqa: BLE001
        logger.exception(
            "broker sync: other-account check failed account=%s broker=%s", account_id, broker,
        )
        return None
    return len(mine & others)


async def _record_snapshot(
    db, doc: dict, rows: List[Dict[str, Any]], *,
    trigger: str, duplicates: Dict[str, Optional[int]], synced_at: str,
) -> Optional[str]:
    """Keep a snapshot of this sync (`sync_snapshots`) and return its id. The
    holdings are already stored, so a failure here is logged and does not
    fail the sync — the id is then None."""
    try:
        return await sync_snapshots.record(
            db, doc, rows, trigger=trigger, duplicates=duplicates, synced_at=synced_at,
            broker_display=display_name(doc.get("broker") or ""),
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "broker sync: snapshot not written account=%s broker=%s",
            doc.get("account_id"), doc.get("broker"),
        )
        return None


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


# ── Contract chart ───────────────────────────────────────────────────────
def parse_contract(symbol: Any, exchange: Any, instrument_type: Any, expiry: Any, strike: Any) -> ContractRef:
    """A futures or options contract named by a client, checked and put in
    one form. The values are those of a position row (`HubPosition`). Raises
    `ValueError` with a plain sentence for anything that cannot name one — the
    values go into a broker request, so nothing is passed on unchecked.
    """
    sym = symbol.strip().upper() if isinstance(symbol, str) else ""
    if not _SYMBOL_RE.fullmatch(sym):
        raise ValueError("symbol must be the position's own symbol")
    exch = exchange.strip().upper() if isinstance(exchange, str) else ""
    if not _EXCHANGE_RE.fullmatch(exch):
        raise ValueError("exchange must be the position's own exchange")
    kind = instrument_type.strip().upper() if isinstance(instrument_type, str) else ""
    if kind not in _CONTRACT_KINDS:
        raise ValueError("instrument_type must be FUT, CE or PE")
    if isinstance(expiry, datetime) or not isinstance(expiry, (str, date)):
        raise ValueError("expiry must be a date (YYYY-MM-DD)")
    try:
        expires = expiry if isinstance(expiry, date) else datetime.strptime(expiry.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("expiry must be a date (YYYY-MM-DD)") from None
    if kind == "FUT":
        return ContractRef(symbol=sym, exchange=exch, instrument_type=kind, expiry=expires.isoformat(), strike=None)
    if isinstance(strike, bool) or not isinstance(strike, (int, float)) or not math.isfinite(strike) or not 0 < strike <= 10_000_000:
        raise ValueError("an option needs its strike price")
    return ContractRef(symbol=sym, exchange=exch, instrument_type=kind, expiry=expires.isoformat(), strike=float(strike))


def supports_contract_chart(slug: str) -> bool:
    """Whether the broker's adapter can read a contract's own price history."""
    try:
        adapter = registry.get(slug)
    except KeyError:
        return False
    return bool(getattr(adapter, "IMPLEMENTED", True)) and callable(getattr(adapter, "fetch_contract_chart", None))


async def read_contract_chart(db, doc: dict, contract: ContractRef, interval: str) -> dict:
    """The price history and latest quote of one futures or options contract,
    read live from the account's broker on every call; nothing is stored.
    Returns `ContractChart` as a dict: `{"candles": [...], "quote": {...} | None}`.

    Raises like `read_account_positions`: a broker that refuses the session
    ends it; a broker with no chart reader is `BrokerNotSupported`.
    """
    if interval not in CHART_INTERVALS:
        raise ValueError(f"interval must be one of {CHART_INTERVALS}")
    try:
        slug = doc.get("broker") or ""
        token = _live_token(doc)
        adapter = _adapter_for(slug, "contract chart")
        fetch = getattr(adapter, "fetch_contract_chart", None)
        if fetch is None:
            raise BrokerNotSupported(f"{adapter.DISPLAY} has no contract chart reader")
        chart = await _adapter_call(adapter, "a contract chart", fetch, token, contract, interval)
        return asdict(chart)
    except BrokerSessionExpired:
        await sessions.end_session(db, doc["account_id"], "broker_rejected")
        raise
    except (sessions.SessionEnded, BrokerNotSupported):
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "broker contract chart read failed account=%s broker=%s interval=%s error=%s",
            doc.get("account_id"), doc.get("broker"), interval, _error_label(exc),
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
                await sync_account(db, doc, trigger="daily")
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
