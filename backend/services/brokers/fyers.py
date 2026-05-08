"""Fyers (API v3) native broker adapter.

Standard OAuth — `https://api-t1.fyers.in/api/v3/generate-authcode?
client_id=<APP_KEY>&redirect_uri=<CB>&response_type=code&state=<>`.

App registered at https://myapi.fyers.in/dashboard/.
Secrets: BROKER_FYERS_API_KEY (`<app_id>-<id_suffix>`),
BROKER_FYERS_API_SECRET.
"""
from __future__ import annotations

import logging
from typing import Any, List
from urllib.parse import quote

from . import registry
from ._helpers import conf, detect_etf, require, require_sdk, to_thread
from .base import AccessToken, Funds, Holding, Position

logger = logging.getLogger(__name__)

SLUG = "fyers"
DISPLAY = "Fyers"
AUTH_STYLE = "oauth"

_AUTH_URL_TPL = (
    "https://api-t1.fyers.in/api/v3/generate-authcode"
    "?client_id={key}&redirect_uri={cb}&response_type=code&state={state}"
)


def auth_url(*, state: str, redirect_uri: str) -> str:
    return _AUTH_URL_TPL.format(
        key=quote(require("BROKER_FYERS_API_KEY"), safe=""),
        cb=quote(redirect_uri, safe=""),
        state=quote(state, safe=""),
    )


async def exchange_code(*, code: str, state: str, redirect_uri: str) -> AccessToken:
    """POST /api/v3/validate-authcode with sha256(api_key:api_secret)
    checksum. Direct HTTP keeps deps minimal.
    """
    import hashlib
    import httpx
    api_key = require("BROKER_FYERS_API_KEY")
    api_secret = require("BROKER_FYERS_API_SECRET")
    checksum = hashlib.sha256(f"{api_key}:{api_secret}".encode()).hexdigest()
    payload = {"grant_type": "authorization_code", "appIdHash": checksum, "code": code}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            "https://api-t1.fyers.in/api/v3/validate-authcode",
            json=payload, headers={"Content-Type": "application/json"},
        )
    body = r.json()
    if body.get("s") != "ok" or not body.get("access_token"):
        raise RuntimeError(f"Fyers token exchange failed: {body!r}")
    return AccessToken(
        token=body["access_token"],
        extras={"refresh_token": body.get("refresh_token"), "expires_in": body.get("expires_in")},
    )


async def _get(path: str, api_key: str, token: str) -> Any:
    import httpx
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            f"https://api-t1.fyers.in/api/v3{path}",
            headers={"Authorization": f"{api_key}:{token}"},
        )
    r.raise_for_status()
    return r.json()


async def fetch_holdings(token: AccessToken) -> List[Holding]:
    api_key = require("BROKER_FYERS_API_KEY")
    body = await _get("/holdings", api_key, token.token)
    rows = (body or {}).get("holdings") or []
    out: List[Holding] = []
    for h in rows:
        sym = (h.get("symbol") or "").upper()
        if not sym:
            continue
        ex = sym.split(":", 1)[0] if ":" in sym else None
        clean_sym = sym.split(":", 1)[1].rstrip("-EQ") if ":" in sym else sym
        out.append(Holding(
            isin=(h.get("isin") or "").upper() or None,
            symbol=clean_sym,
            asset_type="etf" if detect_etf(clean_sym) else "equity",
            quantity=float(h.get("quantity") or 0),
            avg_price=float(h.get("costPrice") or 0),
            current_price=float(h.get("ltp") or 0),
            name=clean_sym,
            exchange=ex,
            source_id=sym,
        ))
    return out


async def fetch_positions(token: AccessToken) -> List[Position]:
    api_key = require("BROKER_FYERS_API_KEY")
    body = await _get("/positions", api_key, token.token)
    rows = (body or {}).get("netPositions") or []
    out: List[Position] = []
    for p in rows:
        sym = (p.get("symbol") or "").upper()
        ex = sym.split(":", 1)[0] if ":" in sym else ""
        out.append(Position(
            symbol=sym.split(":", 1)[1] if ":" in sym else sym,
            exchange=ex,
            quantity=float(p.get("netQty") or 0),
            avg_price=float(p.get("netAvg") or 0),
            pnl=float(p.get("pl") or 0),
            product=p.get("productType"),
        ))
    return out


async def fetch_funds(token: AccessToken) -> Funds:
    api_key = require("BROKER_FYERS_API_KEY")
    body = await _get("/funds", api_key, token.token)
    fund_limit = (body or {}).get("fund_limit") or []
    bal = next((x for x in fund_limit if x.get("title") == "Total Balance"), {})
    used = next((x for x in fund_limit if x.get("title") == "Utilized Amount"), {})
    return Funds(
        available_cash=float(bal.get("equityAmount") or 0),
        used_margin=float(used.get("equityAmount") or 0),
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
