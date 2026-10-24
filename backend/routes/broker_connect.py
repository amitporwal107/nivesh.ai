"""Broker Connect routes — Nivesh Secure Portfolio Connect.

Read-only. Accounts are connected by signing in on the broker's own page
(`routes.broker_native`); this module lists, syncs, reads and disconnects
them. The OpenAlgo connect, provisioning and reverse-proxy paths were
removed (2026-10-24): live execution will go through Kite Connect, and
OpenAlgo had no caller in the app. A legacy OpenAlgo row can still be
listed and disconnected; it cannot be synced or read.

Routes (all under /api/broker, all authenticated):

    GET    /api/broker/supported              — list of brokers we accept
    GET    /api/broker/accounts               — current user's connections
    POST   /api/broker/accounts/{id}/sync     — fetch holdings through the
                                                broker session of a native
                                                account (an OpenAlgo row is
                                                refused as not supported)
    GET    /api/broker/accounts/{id}/holdings — live holdings, one native
                                                account (never stored)
    GET    /api/broker/holdings               — live holdings, every account
                                                of the user (an OpenAlgo one
                                                is listed as not readable)
    GET    /api/broker/accounts/{id}/positions — live positions, one native
                                                account (never stored)
    GET    /api/broker/positions              — live positions, every account
                                                of the user (as /holdings)
    GET    /api/broker/funds                  — live cash and margin, every
                                                account of the user (as
                                                /holdings); read-only, never
                                                stored
    GET    /api/broker/accounts/{id}/snapshots — history of an account's
                                                holdings syncs
    GET    /api/broker/snapshots/{id}         — one sync snapshot, with the
                                                holdings as they were stored
    DELETE /api/broker/accounts/{id}          — disconnect (delete + audit)

The sync endpoint imports holdings into the same `db.holdings` collection
as CAS / Excel imports, tagged with `broker_account_id = "<account>"` so a
re-sync replaces *only that account's* prior rows and concurrent CAS
imports stay intact. Rows an OpenAlgo sync wrote earlier keep
`source = "openalgo"` until the account is disconnected.

Accounts connected on the broker's own page (`native: True`, written by
`routes.broker_native`) are read through `services.brokers.hub_reads`;
their holdings rows carry `source = "broker_native"`. Syncing such an
account and the live holdings and positions routes need the `broker_hub`
feature flag; nothing else here does.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from core.exceptions import (
    BusinessException,
    IntegrationException,
    NiveshException,
    ValidationException,
)
from deps import db, get_current_user
from feature_gate import require_feature
from services import audit as _audit
from services.brokers import hub_reads as _hub
from services.brokers import sessions as _sessions
from services.brokers import sync_snapshots as _snapshots
# Display names only, for GET /supported and for naming a legacy OpenAlgo row.
from services.openalgo_client import SUPPORTED_BROKERS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/broker")


# ── Helpers ──────────────────────────────────────────────────────────────
def _public_account(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Strip encrypted secrets before returning to the client."""
    hosted = bool(doc.get("openalgo_hosted"))
    broker = doc.get("broker")
    broker_display = _broker_display(doc)
    return {
        # Session state (native, needs_reconnect, expiry, …). Spread first
        # so it can never displace one of the keys below.
        **_sessions.public_fields(doc),
        "account_id": doc["account_id"],
        "broker": broker,
        "broker_display": broker_display,
        "label": doc.get("label"),
        # Don't leak the internal URL when it's the Nivesh-managed
        # instance — users only need to know it's hosted by Nivesh.
        "openalgo_url": "" if hosted else doc.get("openalgo_url"),
        "openalgo_hosted": hosted,
        "api_key_masked": doc.get("api_key_masked"),
        "status": doc.get("status"),
        "last_sync_at": doc.get("last_sync_at"),
        "last_sync_count": doc.get("last_sync_count"),
        "last_error": doc.get("last_error"),
        "created_at": doc.get("created_at"),
    }


def _broker_display(doc: Dict[str, Any]) -> Optional[str]:
    broker = doc.get("broker")
    if doc.get("native"):
        # Native rows use adapter slugs — the registry names them, the
        # OpenAlgo map does not cover them all.
        return _hub.display_name(broker or "") or broker
    return SUPPORTED_BROKERS.get(broker or "", broker)


async def _get_owned_account(user_id: str, account_id: str) -> Dict[str, Any]:
    doc = await db.broker_accounts.find_one(
        {"account_id": account_id, "user_id": user_id}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Broker account not found")
    return doc


# ── Routes ───────────────────────────────────────────────────────────────
@router.get("/supported")
async def list_supported_brokers(request: Request):
    """Public-ish — still requires auth so we can attribute usage."""
    await get_current_user(request)
    return {
        "brokers": [{"slug": k, "name": v} for k, v in SUPPORTED_BROKERS.items()],
    }


@router.get("/accounts")
async def list_accounts(request: Request):
    user = await get_current_user(request)
    # Mark sessions whose broker expiry has passed before listing, so an
    # expired connection is reported as needing a reconnect.
    await _sessions.expire_due_sessions(db, user_id=user["user_id"])
    cursor = db.broker_accounts.find(
        {"user_id": user["user_id"]}, {"_id": 0},
    ).sort("created_at", -1)
    docs = await cursor.to_list(length=50)
    return {"accounts": [_public_account(d) for d in docs]}


@router.post("/accounts/{account_id}/sync")
async def sync_broker_account(request: Request, account_id: str):
    user = await get_current_user(request)
    user_id = user["user_id"]
    doc = await _get_owned_account(user_id, account_id)

    if not doc.get("native"):
        # A legacy OpenAlgo row: the OpenAlgo client path is gone, so it is
        # refused before the flag is consulted and nothing is written.
        raise _not_native(doc, _NOT_NATIVE_SYNC)
    # Connected on the broker's own page: the stored broker session reads
    # the holdings. Only this branch depends on the `broker_hub` flag.
    await _hub_user(request)
    return await _sync_native_account(request, user_id, doc)


# ── Native (broker-session) reads ────────────────────────────────────────
# Off stops holdings sync and position reads for redirect-connected accounts
# (feature_flags.KNOWN_FEATURES). Listing and disconnecting do not depend on it.
FLAG = "broker_hub"


async def _hub_user(request: Request) -> dict:
    """The signed-in user, refused with 403 when `broker_hub` is off for them."""
    return await require_feature(
        FLAG, resolve_user=lambda r: get_current_user(r), get_db=lambda: db,
    )(request)


class BrokerSessionExpiredException(BusinessException):
    """The broker session behind the account has ended — reconnect needed."""
    error_code = _hub.CODE_SESSION_EXPIRED
    http_status = 409


# Read failure code → the domain exception the global handler turns into the
# standard error envelope (409 / 400 / 502).
_READ_ERRORS = {
    _hub.CODE_SESSION_EXPIRED: BrokerSessionExpiredException,
    _hub.CODE_NOT_SUPPORTED: ValidationException,
    _hub.CODE_READ_FAILED: IntegrationException,
}


def _account_details(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{"broker": doc.get("broker"), "account_id": doc["account_id"]}]


def _read_error(exc: Exception, doc: Dict[str, Any], what: str) -> NiveshException:
    """The error for a failed native read: a stable `code`, a fixed-text
    message (`hub_reads.describe_failure`, never the broker's own error) and
    the broker + account in `details`. The broker's exception is not passed
    as `cause` — the handler logs a cause with its text — and callers raise
    this `from None` for the same reason."""
    code, message = _hub.describe_failure(exc, doc.get("broker") or "", what)
    return _READ_ERRORS[code](message, code=code, details=_account_details(doc))


async def _sync_native_account(
    request: Request, user_id: str, doc: Dict[str, Any],
) -> Dict[str, Any]:
    account_id = doc["account_id"]
    try:
        result = await _hub.sync_account(db, doc, trigger="manual")
    except Exception as e:  # noqa: BLE001
        err = _read_error(e, doc, "holdings")
        await _audit.record(
            user_id=user_id, action="broker_sync", resource=account_id,
            outcome="error",
            ip=request.client.host if request.client else "",
            ua=request.headers.get("user-agent", ""),
            details={
                "broker": doc.get("broker"), "native": True,
                "code": err.code, "reason": err.message,
            },
        )
        raise err from None

    await _audit.record(
        user_id=user_id, action="broker_sync", resource=account_id,
        outcome="success",
        ip=request.client.host if request.client else "",
        ua=request.headers.get("user-agent", ""),
        details={"broker": doc.get("broker"), "native": True, "count": result["count"]},
    )
    return {
        "ok": True,
        "count": result["count"],
        "holdings": result["holdings"],
        # The snapshot kept of this sync (null if it could not be written)
        # and what the duplicate check found.
        "snapshot_id": result["snapshot_id"],
        "duplicates": result["duplicates"],
    }


# Why an OpenAlgo account has no live read: its stored key is an OpenAlgo API
# key, not a broker session (`hub_reads._live_token`).
_NOT_NATIVE_SYNC = (
    "Syncing holdings is available only for accounts connected by signing in on the broker's own page."
)
_NOT_NATIVE_HOLDINGS = (
    "Live holdings are available only for accounts connected by signing in on the broker's own page."
)
_NOT_NATIVE_POSITIONS = (
    "Live positions are available only for accounts connected by signing in on the broker's own page."
)


def _not_native(doc: Dict[str, Any], message: str) -> ValidationException:
    return ValidationException(message, code=_hub.CODE_NOT_SUPPORTED, details=_account_details(doc))


async def _user_accounts(user_id: str) -> List[Dict[str, Any]]:
    """Every broker account of the user, newest first (as GET /accounts)."""
    cursor = db.broker_accounts.find({"user_id": user_id}, {"_id": 0}).sort("created_at", -1)
    return await cursor.to_list(length=50)


def _account_entry(doc: Dict[str, Any]) -> Dict[str, Any]:
    """The fields that name an account in an all-accounts live read."""
    return {
        "account_id": doc["account_id"],
        "broker": doc.get("broker"),
        "broker_display": _broker_display(doc),
        "label": doc.get("label"),
    }


_NO_HOLDINGS_TOTALS: Dict[str, Optional[float]] = {
    "invested_rs": None, "value_rs": None, "pnl_rs": None, "pnl_pct": None,
}


@router.get("/accounts/{account_id}/holdings")
async def get_account_holdings(request: Request, account_id: str):
    """Current holdings of one natively connected account, read live from
    the broker on every call and never stored (the rows the last sync stored
    are not touched). Each row carries its value, cost and P&L, null when
    the broker gave no price or average; `totals` are null when any row
    lacks the figure.
    """
    user = await _hub_user(request)
    doc = await _get_owned_account(user["user_id"], account_id)
    if not doc.get("native"):
        raise _not_native(doc, _NOT_NATIVE_HOLDINGS)
    try:
        rows = await _hub.read_account_holdings(db, doc)
    except Exception as e:  # noqa: BLE001
        raise _read_error(e, doc, "holdings") from None
    return {
        **_account_entry(doc),
        "as_of": _now_iso(),
        "holdings": rows,
        "counts": {"total": len(rows)},
        "totals": _hub.holdings_totals(rows),
    }


@router.get("/holdings")
async def get_all_holdings(request: Request):
    """Current holdings across every broker account of the user, read live.
    Each account is read on its own, a few at a time: one failing — or
    needing a reconnect — is reported in its entry (`ok: false`, `error`)
    and never fails the others. An OpenAlgo account is listed with the
    not-supported error and is not read. Nothing is stored.
    """
    user = await _hub_user(request)
    docs = await _user_accounts(user["user_id"])
    gate = asyncio.Semaphore(_hub.LIVE_READ_CONCURRENCY)

    async def _read_one(doc: Dict[str, Any]) -> Dict[str, Any]:
        entry: Dict[str, Any] = {
            **_account_entry(doc),
            "ok": False,
            "error": None,
            "as_of": None,
            "holdings": [],
            # Not read: how many there are is not known.
            "counts": {"total": None},
            "totals": dict(_NO_HOLDINGS_TOTALS),
        }
        if not doc.get("native"):
            entry["error"] = {"code": _hub.CODE_NOT_SUPPORTED, "message": _NOT_NATIVE_HOLDINGS}
        else:
            try:
                async with gate:
                    rows = await _hub.read_account_holdings(db, doc)
            except Exception as e:  # noqa: BLE001
                code, message = _hub.describe_failure(e, doc.get("broker") or "", "holdings")
                entry["error"] = {"code": code, "message": message}
            else:
                entry.update(
                    ok=True, holdings=rows, counts={"total": len(rows)},
                    totals=_hub.holdings_totals(rows),
                )
        entry["as_of"] = _now_iso()
        return entry

    accounts = await asyncio.gather(*(_read_one(d) for d in docs))
    return {"as_of": _now_iso(), "accounts": list(accounts)}


_NOT_NATIVE_FUNDS = (
    "Live funds are available only for accounts connected by signing in on the broker's own page."
)


@router.get("/funds")
async def get_all_funds(request: Request):
    """Cash and margin across every broker account of the user, read live
    through each broker's read-only funds call and never stored. Each account
    is read on its own, a few at a time: one failing — or needing a
    reconnect — is reported in its entry (`ok: false`, `error`) and never
    fails the others. An OpenAlgo account is listed as not supported and not
    read. Nothing here moves money or places an order.
    """
    user = await _hub_user(request)
    docs = await _user_accounts(user["user_id"])
    gate = asyncio.Semaphore(_hub.LIVE_READ_CONCURRENCY)

    async def _read_one(doc: Dict[str, Any]) -> Dict[str, Any]:
        entry: Dict[str, Any] = {**_account_entry(doc), "ok": False, "error": None, "as_of": None, "funds": None}
        if not doc.get("native"):
            entry["error"] = {"code": _hub.CODE_NOT_SUPPORTED, "message": _NOT_NATIVE_FUNDS}
        else:
            try:
                async with gate:
                    funds = await _hub.read_account_funds(db, doc)
            except Exception as e:  # noqa: BLE001
                code, message = _hub.describe_failure(e, doc.get("broker") or "", "funds")
                entry["error"] = {"code": code, "message": message}
            else:
                entry.update(ok=True, funds=funds)
        entry["as_of"] = _now_iso()
        return entry

    accounts = await asyncio.gather(*(_read_one(d) for d in docs))
    return {
        "as_of": _now_iso(),
        "source": "broker",
        "basis": "As each broker reports it, read live from its funds call; never stored.",
        "accounts": list(accounts),
    }


def _position_counts(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    return {
        "total": len(rows),
        "fno": sum(1 for r in rows if r.get("segment") == "fno"),
        "intraday": sum(1 for r in rows if r.get("is_intraday")),
    }


def _filter_positions(rows: List[Dict[str, Any]], segment: str) -> List[Dict[str, Any]]:
    if segment == "fno":
        return [r for r in rows if r.get("segment") == "fno"]
    if segment == "intraday":
        return [r for r in rows if r.get("is_intraday")]
    return rows


@router.get("/accounts/{account_id}/positions")
async def get_account_positions(
    request: Request,
    account_id: str,
    kind: Literal["net", "day"] = "net",
    segment: Literal["all", "fno", "intraday"] = "all",
):
    """Current positions of one natively connected account, read live from
    the broker on every call and never stored. `counts` describe the whole
    read; `segment` only narrows `positions`.
    """
    user = await _hub_user(request)
    doc = await _get_owned_account(user["user_id"], account_id)
    if not doc.get("native"):
        raise _not_native(doc, _NOT_NATIVE_POSITIONS)
    try:
        rows = await _hub.read_account_positions(db, doc, kind)
    except Exception as e:  # noqa: BLE001
        raise _read_error(e, doc, f"{kind} positions") from None
    return {
        "account_id": account_id,
        "broker": doc.get("broker"),
        "kind": kind,
        "segment": segment,
        "as_of": _now_iso(),
        "positions": _filter_positions(rows, segment),
        "counts": _position_counts(rows),
    }


@router.get("/accounts/{account_id}/contract-chart")
async def get_contract_chart(
    request: Request,
    account_id: str,
    symbol: str = Query(..., min_length=1, max_length=40),
    exchange: str = Query(..., min_length=2, max_length=10),
    instrument_type: Literal["FUT", "CE", "PE"] = Query(...),
    expiry: str = Query(..., min_length=10, max_length=10),
    strike: Optional[float] = Query(None),
    interval: Literal["5m", "30m"] = "5m",
):
    """The price history and latest quote of one futures or options contract
    the account holds — the contract's own price, not the underlying share's —
    read live from the broker on every call and never stored. The contract is
    named by the values of its position row.
    """
    user = await _hub_user(request)
    doc = await _get_owned_account(user["user_id"], account_id)
    if not doc.get("native"):
        raise ValidationException(
            "A contract chart is available only for accounts connected by signing in on the broker's own page.",
            code=_hub.CODE_NOT_SUPPORTED,
            details=_account_details(doc),
        )
    try:
        contract = _hub.parse_contract(symbol, exchange, instrument_type, expiry, strike)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    try:
        chart = await _hub.read_contract_chart(db, doc, contract, interval)
    except Exception as e:  # noqa: BLE001
        raise _read_error(e, doc, "a contract chart") from None
    return {
        "account_id": account_id,
        "broker": doc.get("broker"),
        "broker_display": _hub.display_name(doc.get("broker") or ""),
        "contract": {
            "symbol": contract.symbol, "exchange": contract.exchange,
            "instrument_type": contract.instrument_type,
            "expiry": contract.expiry, "strike": contract.strike,
        },
        "interval": interval,
        "as_of": _now_iso(),
        "candles": chart["candles"],
        "quote": chart["quote"],
    }


@router.get("/positions")
async def get_all_positions(
    request: Request,
    kind: Literal["net", "day"] = "net",
    segment: Literal["all", "fno", "intraday"] = "all",
):
    """Current positions across every broker account of the user. Each
    account is read on its own, a few at a time: one failing — or needing a
    reconnect — is reported in its entry and never fails the others. An
    OpenAlgo account is listed with the not-supported error and is not read.
    """
    user = await _hub_user(request)
    docs = await _user_accounts(user["user_id"])
    gate = asyncio.Semaphore(_hub.LIVE_READ_CONCURRENCY)

    async def _read_one(doc: Dict[str, Any]) -> Dict[str, Any]:
        entry: Dict[str, Any] = {
            **_account_entry(doc),
            "ok": False,
            "error": None,
            "as_of": None,
            "positions": [],
            "counts": _position_counts([]),
        }
        if not doc.get("native"):
            entry["error"] = {"code": _hub.CODE_NOT_SUPPORTED, "message": _NOT_NATIVE_POSITIONS}
            entry["as_of"] = _now_iso()
            return entry
        try:
            async with gate:
                rows = await _hub.read_account_positions(db, doc, kind)
        except Exception as e:  # noqa: BLE001
            code, message = _hub.describe_failure(
                e, doc.get("broker") or "", f"{kind} positions",
            )
            entry["error"] = {"code": code, "message": message}
        else:
            entry["ok"] = True
            entry["positions"] = _filter_positions(rows, segment)
            entry["counts"] = _position_counts(rows)
        entry["as_of"] = _now_iso()
        return entry

    accounts = await asyncio.gather(*(_read_one(d) for d in docs))
    return {
        "as_of": _now_iso(),
        "kind": kind,
        "segment": segment,
        "accounts": list(accounts),
    }


# ── Sync snapshots ───────────────────────────────────────────────────────
# Reading one's own sync history needs a signed-in user but not the
# `broker_hub` flag: it must survive the flag being switched off.
@router.get("/accounts/{account_id}/snapshots")
async def list_account_snapshots(
    request: Request,
    account_id: str,
    limit: int = Query(30, ge=1, le=_snapshots.MAX_PER_ACCOUNT),
):
    """The holdings syncs of one of the user's accounts, newest first, each
    without its holdings rows (`GET /snapshots/{id}` has those)."""
    user = await get_current_user(request)
    doc = await _get_owned_account(user["user_id"], account_id)
    return {
        "account_id": account_id,
        "broker": doc.get("broker"),
        "snapshots": await _snapshots.list_for_account(db, user["user_id"], account_id, limit),
    }


@router.get("/snapshots/{snapshot_id}")
async def get_snapshot(request: Request, snapshot_id: str):
    """One sync snapshot with the holdings as they were stored, for the user
    it belongs to."""
    user = await get_current_user(request)
    snapshot = await _snapshots.get_for_owner(db, user["user_id"], snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Broker sync snapshot not found")
    return snapshot


@router.delete("/accounts/{account_id}")
async def disconnect_broker(request: Request, account_id: str):
    user = await get_current_user(request)
    user_id = user["user_id"]
    doc = await _get_owned_account(user_id, account_id)

    # Remove the account-scoped holdings so the dashboard reflects the
    # disconnect immediately. CAS / Excel rows for the same user stay.
    await db.holdings.delete_many(
        {"user_id": user_id, "broker_account_id": account_id},
    )
    # The sync snapshots are copies of those holdings: they go with them.
    await _snapshots.delete_for_account(db, user_id, account_id)
    await db.broker_accounts.delete_one({"account_id": account_id})

    await _audit.record(
        user_id=user_id, action="broker_disconnect", resource=account_id,
        outcome="success",
        ip=request.client.host if request.client else "",
        ua=request.headers.get("user-agent", ""),
        details={"broker": doc.get("broker")},
    )
    return {"ok": True}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
