"""Angel One (SmartAPI) native broker adapter.

Angel uses **API-key + client-id + TOTP** auth, not OAuth — the user
provides credentials directly. So `auth_url` returns Nivesh's own
form URL (the form posts to `/api/broker/native/callback?broker=angel`
with user-entered fields, which the callback dispatches to
`exchange_code` here).

For now `auth_url` returns the form URL; the form itself is rendered
by Nivesh's frontend (TODO — out of scope for this turn).

App credentials (`BROKER_ANGEL_API_KEY` + `BROKER_ANGEL_API_SECRET`)
are registered at https://smartapi.angelbroking.com/.
"""
from __future__ import annotations

import logging
from typing import Any, List

from . import registry
from ._helpers import conf, detect_etf, require, require_sdk, to_thread
from .base import AccessToken, Funds, Holding, Position

logger = logging.getLogger(__name__)

SLUG = "angel"
DISPLAY = "Angel One"
AUTH_STYLE = "form"  # NOT OAuth — Angel needs client_id + password + TOTP


def auth_url(*, state: str, redirect_uri: str) -> str:
    """Form-based brokers don't have an external OAuth URL. We send the
    user to a Nivesh-rendered credential form keyed by `state`. The form
    POSTs the entered fields back to /api/broker/native/callback with
    `broker=angel`, `state=<...>`, and the credentials in the body.
    """
    return f"/broker-credentials/angel?state={state}"


async def exchange_code(*, code: str, state: str, redirect_uri: str) -> AccessToken:
    """`code` here is a JSON-encoded blob `{client_code, password, totp}`
    posted by the Nivesh-rendered form. We use SmartAPI's
    `generateSession` to mint a session token.
    """
    import json
    sa = require_sdk("SmartApi", "Add `smartapi-python` to requirements.txt.")
    api_key = require("BROKER_ANGEL_API_KEY")
    try:
        creds = json.loads(code)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Angel: malformed credentials body — {e}")
    client_code = creds.get("client_code")
    password = creds.get("password")
    totp = creds.get("totp")
    if not (client_code and password and totp):
        raise RuntimeError("Angel: client_code, password, totp all required")

    obj = sa.SmartConnect(api_key=api_key)
    data = await to_thread(obj.generateSession, client_code, password, totp)
    if not data or not data.get("status"):
        raise RuntimeError(f"Angel session failed: {data}")
    payload = data.get("data") or {}
    return AccessToken(
        token=payload.get("jwtToken") or "",
        extras={
            "client_code": client_code,
            "refreshToken": payload.get("refreshToken"),
            "feedToken": payload.get("feedToken"),
        },
    )


def _client(token: AccessToken):
    sa = require_sdk("SmartApi", "Add `smartapi-python` to requirements.txt.")
    api_key = require("BROKER_ANGEL_API_KEY")
    obj = sa.SmartConnect(api_key=api_key)
    obj.setAccessToken(token.token)
    obj.setRefreshToken(token.extras.get("refreshToken"))
    obj.setFeedToken(token.extras.get("feedToken"))
    return obj


async def fetch_holdings(token: AccessToken) -> List[Holding]:
    obj = _client(token)
    data = await to_thread(obj.holding)
    rows = (data or {}).get("data") or []
    out: List[Holding] = []
    for h in rows:
        sym = (h.get("tradingsymbol") or "").upper()
        if not sym:
            continue
        ex = (h.get("exchange") or "").upper() or None
        out.append(Holding(
            isin=(h.get("isin") or "").upper() or None,
            symbol=sym,
            asset_type="etf" if detect_etf(sym) else "equity",
            quantity=float(h.get("quantity") or 0),
            avg_price=float(h.get("averageprice") or 0),
            current_price=float(h.get("ltp") or 0),
            name=sym,
            exchange=ex,
            source_id=f"{ex}:{sym}" if ex else sym,
        ))
    return out


async def fetch_positions(token: AccessToken) -> List[Position]:
    obj = _client(token)
    data = await to_thread(obj.position)
    rows = (data or {}).get("data") or []
    out: List[Position] = []
    for p in rows:
        out.append(Position(
            symbol=(p.get("tradingsymbol") or "").upper(),
            exchange=(p.get("exchange") or "").upper(),
            quantity=float(p.get("netqty") or 0),
            avg_price=float(p.get("avgnetprice") or 0),
            pnl=float(p.get("pnl") or 0),
            product=p.get("producttype"),
        ))
    return out


async def fetch_funds(token: AccessToken) -> Funds:
    obj = _client(token)
    data = await to_thread(obj.rmsLimit)
    d = (data or {}).get("data") or {}
    return Funds(
        available_cash=float(d.get("net") or 0),
        used_margin=float(d.get("utiliseddebits") or 0),
        collateral=float(d.get("collateral") or 0),
    )


class _Module:
    SLUG = SLUG
    DISPLAY = DISPLAY
    AUTH_STYLE = AUTH_STYLE
    auth_url = staticmethod(auth_url)
    exchange_code = staticmethod(exchange_code)
    fetch_holdings = staticmethod(fetch_holdings)
    fetch_positions = staticmethod(fetch_positions)
    fetch_funds = staticmethod(fetch_funds)


registry.register(_Module())
