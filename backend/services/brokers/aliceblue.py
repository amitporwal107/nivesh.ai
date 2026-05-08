"""AliceBlue (Ant API) native broker adapter.

OAuth-style: redirect to login URL with `appcode`, callback returns
`authCode`. Exchange via `getApiAccessToken(userid, authCode)`.

Operator: register at https://ant.aliceblueonline.com/.
Secrets: BROKER_ALICEBLUE_API_KEY (= app code/key),
         BROKER_ALICEBLUE_API_SECRET.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, List
from urllib.parse import quote

from . import registry
from ._helpers import detect_etf, require, to_thread
from .base import AccessToken, Funds, Holding, Position

logger = logging.getLogger(__name__)

SLUG = "aliceblue"
DISPLAY = "AliceBlue"
AUTH_STYLE = "oauth"


def auth_url(*, state: str, redirect_uri: str) -> str:
    return (
        f"https://ant.aliceblueonline.com/?appcode={quote(require('BROKER_ALICEBLUE_API_KEY'), safe='')}"
        f"&state={quote(state, safe='')}"
    )


async def exchange_code(*, code: str, state: str, redirect_uri: str) -> AccessToken:
    """AliceBlue's auth flow:
      1. After OAuth, the callback URL has `?userId=<X>&authCode=<Y>`.
      2. POST to /vendor/getUserDetails with sha256(userId+authCode+secret).
    `code` here is a JSON `{userId, authCode}` from the form/query.
    """
    import httpx
    import json
    api_key = require("BROKER_ALICEBLUE_API_KEY")
    api_secret = require("BROKER_ALICEBLUE_API_SECRET")
    try:
        creds = json.loads(code) if code.startswith("{") else {"authCode": code}
    except Exception:  # noqa: BLE001
        creds = {"authCode": code}
    user_id = creds.get("userId") or ""
    auth_code = creds.get("authCode") or ""
    if not (user_id and auth_code):
        raise RuntimeError("AliceBlue: userId + authCode required")
    checksum = hashlib.sha256(f"{user_id}{auth_code}{api_secret}".encode()).hexdigest()
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            "https://ant.aliceblueonline.com/rest/AliceBlueAPIService/api/customer/getUserSID",
            json={"userId": user_id, "userData": checksum},
        )
    body = r.json()
    if body.get("stat") != "Ok":
        raise RuntimeError(f"AliceBlue exchange failed: {body!r}")
    return AccessToken(
        token=body.get("userSessionID") or "",
        extras={"user_id": user_id},
    )


async def _get(path: str, user_id: str, token: str) -> Any:
    import httpx
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            f"https://ant.aliceblueonline.com/rest/AliceBlueAPIService/api{path}",
            headers={"Authorization": f"Bearer {user_id} {token}"},
        )
    r.raise_for_status()
    return r.json()


async def fetch_holdings(token: AccessToken) -> List[Holding]:
    body = await _get("/positionAndHoldings/holdings", token.extras.get("user_id", ""), token.token)
    rows = (body or {}).get("HoldingVal") or []
    out: List[Holding] = []
    for h in rows:
        sym = (h.get("TradingSymbol") or "").upper()
        if not sym:
            continue
        ex = (h.get("Exchange") or "").upper() or None
        out.append(Holding(
            isin=(h.get("Isin") or "").upper() or None,
            symbol=sym,
            asset_type="etf" if detect_etf(sym) else "equity",
            quantity=float(h.get("HUqty") or 0),
            avg_price=float(h.get("AvgPrice") or 0),
            current_price=float(h.get("LTP") or 0),
            name=sym,
            exchange=ex,
            source_id=f"{ex}:{sym}" if ex else sym,
        ))
    return out


async def fetch_positions(token: AccessToken) -> List[Position]:
    body = await _get("/positionAndHoldings/positionBook", token.extras.get("user_id", ""), token.token)
    rows = body if isinstance(body, list) else []
    out: List[Position] = []
    for p in rows:
        out.append(Position(
            symbol=(p.get("Tsym") or "").upper(),
            exchange=(p.get("Exchange") or "").upper(),
            quantity=float(p.get("Netqty") or 0),
            avg_price=float(p.get("NetAvgPrice") or 0),
            pnl=float(p.get("realisedprofitloss") or 0),
        ))
    return out


async def fetch_funds(token: AccessToken) -> Funds:
    body = await _get("/limits/getRmsLimits", token.extras.get("user_id", ""), token.token)
    rows = body if isinstance(body, list) else []
    eq = next((x for x in rows if x.get("segment") == "ALL"), {})
    return Funds(
        available_cash=float(eq.get("net") or 0),
        used_margin=float(eq.get("debits") or 0),
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
