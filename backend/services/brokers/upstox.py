"""Upstox native broker adapter (Upstox API v2).

Uses the official `upstox-python-sdk`. Read-only flow: auth → access_token
→ holdings/positions/funds.

Auth model (Upstox v2):
  1. Browser → `https://api.upstox.com/v2/login/authorization/dialog?
       response_type=code&client_id=<APP_KEY>&redirect_uri=<NIVESH_CB>`
  2. User authenticates → Upstox redirects back with `?code=...`
  3. POST `/v2/login/authorization/token` exchanges code → access_token.
  4. Token used as `Authorization: Bearer <token>`.

Operator must register app at https://account.upstox.com/developer/apps
and set `BROKER_UPSTOX_API_KEY` + `BROKER_UPSTOX_API_SECRET`.
"""
from __future__ import annotations

import logging
from typing import Any, List
from urllib.parse import quote

from . import registry
from ._helpers import conf, detect_etf, require, require_sdk, to_thread
from .base import AccessToken, Funds, Holding, Position

logger = logging.getLogger(__name__)

SLUG = "upstox"
DISPLAY = "Upstox"
AUTH_STYLE = "oauth"

_AUTH_URL_TPL = (
    "https://api.upstox.com/v2/login/authorization/dialog"
    "?response_type=code&client_id={key}&redirect_uri={cb}&state={state}"
)


def auth_url(*, state: str, redirect_uri: str) -> str:
    api_key = require("BROKER_UPSTOX_API_KEY")
    return _AUTH_URL_TPL.format(
        key=quote(api_key, safe=""),
        cb=quote(redirect_uri, safe=""),
        state=quote(state, safe=""),
    )


async def exchange_code(*, code: str, state: str, redirect_uri: str) -> AccessToken:
    """POST /v2/login/authorization/token directly — Upstox's SDK uses
    the same request, but raw HTTP keeps the dependency surface smaller.
    """
    import httpx
    api_key = require("BROKER_UPSTOX_API_KEY")
    api_secret = require("BROKER_UPSTOX_API_SECRET")
    payload = {
        "code": code,
        "client_id": api_key,
        "client_secret": api_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    headers = {"accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            "https://api.upstox.com/v2/login/authorization/token",
            data=payload, headers=headers,
        )
    body = r.json()
    token = body.get("access_token")
    if not token:
        raise RuntimeError(f"Upstox token exchange failed: {body!r}")
    return AccessToken(
        token=token,
        extras={
            "user_id": body.get("user_id"),
            "user_name": body.get("user_name"),
            "broker": body.get("broker"),
            "expires_in": body.get("expires_in"),
        },
    )


async def _get(path: str, token: str) -> Any:
    import httpx
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            f"https://api.upstox.com{path}",
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        )
    r.raise_for_status()
    return r.json()


async def fetch_holdings(token: AccessToken) -> List[Holding]:
    body = await _get("/v2/portfolio/long-term-holdings", token.token)
    rows = (body or {}).get("data") or []
    out: List[Holding] = []
    for h in rows:
        sym = (h.get("trading_symbol") or h.get("tradingsymbol") or "").upper()
        if not sym:
            continue
        ex = (h.get("exchange") or "").upper() or None
        out.append(Holding(
            isin=(h.get("isin") or "").upper() or None,
            symbol=sym,
            asset_type="etf" if detect_etf(sym) else "equity",
            quantity=float(h.get("quantity") or 0),
            avg_price=float(h.get("average_price") or 0),
            current_price=float(h.get("last_price") or 0),
            name=h.get("company_name") or sym,
            exchange=ex,
            source_id=f"{ex}:{sym}" if ex else sym,
        ))
    return out


async def fetch_positions(token: AccessToken) -> List[Position]:
    body = await _get("/v2/portfolio/short-term-positions", token.token)
    rows = (body or {}).get("data") or []
    out: List[Position] = []
    for p in rows:
        out.append(Position(
            symbol=(p.get("trading_symbol") or "").upper(),
            exchange=(p.get("exchange") or "").upper(),
            quantity=float(p.get("quantity") or 0),
            avg_price=float(p.get("average_price") or 0),
            pnl=float(p.get("pnl") or 0),
            product=p.get("product"),
        ))
    return out


async def fetch_funds(token: AccessToken) -> Funds:
    body = await _get("/v2/user/get-funds-and-margin", token.token)
    eq = ((body or {}).get("data") or {}).get("equity") or {}
    return Funds(
        available_cash=float(eq.get("available_margin") or 0),
        used_margin=float(eq.get("used_margin") or 0),
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
