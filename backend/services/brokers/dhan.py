"""Dhan (Dhan API v2) native broker adapter.

Dhan uses a *long-lived* access token issued from their
[trader portal](https://web.dhan.co/) under My Profile → DhanHQ Trading
APIs → Generate Token. There's no OAuth — user pastes the token.
We surface this as `auth_style="apikey"` and the form takes a single
`access_token` field. `client_id` is also required and stored as extras.

Configure: BROKER_DHAN_API_KEY = client_id (Dhan's trader ID, optional —
can be left blank because per-user tokens are paired with the user's
client_id during entry).
"""
from __future__ import annotations

import logging
from typing import Any, List

from . import registry
from ._helpers import conf, detect_etf, require, to_thread
from .base import AccessToken, Funds, Holding, Position

logger = logging.getLogger(__name__)

SLUG = "dhan"
DISPLAY = "Dhan"
AUTH_STYLE = "apikey"


def auth_url(*, state: str, redirect_uri: str) -> str:
    return f"/broker-credentials/dhan?state={state}"


async def exchange_code(*, code: str, state: str, redirect_uri: str) -> AccessToken:
    """`code` is a JSON blob `{access_token, client_id}` from the form."""
    import json
    try:
        creds = json.loads(code)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Dhan: malformed credentials body — {e}")
    tok = (creds.get("access_token") or "").strip()
    cid = (creds.get("client_id") or "").strip()
    if not (tok and cid):
        raise RuntimeError("Dhan: access_token and client_id required")
    return AccessToken(token=tok, extras={"client_id": cid})


async def _get(path: str, token: str, client_id: str) -> Any:
    import httpx
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            f"https://api.dhan.co/v2{path}",
            headers={
                "access-token": token,
                "client-id": client_id,
                "accept": "application/json",
            },
        )
    r.raise_for_status()
    return r.json()


async def fetch_holdings(token: AccessToken) -> List[Holding]:
    cid = token.extras.get("client_id") or ""
    body = await _get("/holdings", token.token, cid)
    rows = body if isinstance(body, list) else (body or {}).get("data") or []
    out: List[Holding] = []
    for h in rows:
        sym = (h.get("tradingSymbol") or "").upper()
        if not sym:
            continue
        ex = (h.get("exchange") or "").upper() or None
        out.append(Holding(
            isin=(h.get("isin") or "").upper() or None,
            symbol=sym,
            asset_type="etf" if detect_etf(sym) else "equity",
            quantity=float(h.get("totalQty") or h.get("availableQty") or 0),
            avg_price=float(h.get("avgCostPrice") or 0),
            current_price=float(h.get("lastTradedPrice") or 0),
            name=sym,
            exchange=ex,
            source_id=f"{ex}:{sym}" if ex else sym,
        ))
    return out


async def fetch_positions(token: AccessToken) -> List[Position]:
    cid = token.extras.get("client_id") or ""
    body = await _get("/positions", token.token, cid)
    rows = body if isinstance(body, list) else (body or {}).get("data") or []
    out: List[Position] = []
    for p in rows:
        out.append(Position(
            symbol=(p.get("tradingSymbol") or "").upper(),
            exchange=(p.get("exchange") or "").upper(),
            quantity=float(p.get("netQty") or 0),
            avg_price=float(p.get("buyAvg") or 0),
            pnl=float(p.get("realizedProfit") or 0) + float(p.get("unrealizedProfit") or 0),
            product=p.get("productType"),
        ))
    return out


async def fetch_funds(token: AccessToken) -> Funds:
    cid = token.extras.get("client_id") or ""
    body = await _get("/fundlimit", token.token, cid)
    return Funds(
        available_cash=float(body.get("availabelBalance") or body.get("availableBalance") or 0),
        used_margin=float(body.get("utilizedAmount") or 0),
        collateral=float(body.get("collateralAmount") or 0),
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
