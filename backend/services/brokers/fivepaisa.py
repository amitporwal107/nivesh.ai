"""5paisa native broker adapter.

5paisa uses an OAuth-like flow with `RequestToken` + `Encrypt(api_key,
api_secret, request_token)`. No browser-based redirect — user runs the
5paisa trader login, retrieves a request_token via the partner portal,
pastes it into Nivesh. We surface this as form-style for now.

Operator: register at https://www.5paisa.com/developerapi/.
Secrets: BROKER_FIVEPAISA_API_KEY, BROKER_FIVEPAISA_API_SECRET,
         BROKER_FIVEPAISA_USER_KEY, BROKER_FIVEPAISA_USER_ID
"""
from __future__ import annotations

import logging
from typing import Any, List

from . import registry
from ._helpers import detect_etf, require, require_sdk, to_thread
from .base import AccessToken, Funds, Holding, Position

logger = logging.getLogger(__name__)

SLUG = "fivepaisa"
DISPLAY = "5paisa"
AUTH_STYLE = "form"


def auth_url(*, state: str, redirect_uri: str) -> str:
    return f"/broker-credentials/fivepaisa?state={state}"


async def exchange_code(*, code: str, state: str, redirect_uri: str) -> AccessToken:
    """`code` is JSON `{client_code, password, totp}` from form."""
    import json
    sdk = require_sdk("py5paisa", "Add `py5paisa` to requirements.txt.")
    try:
        creds = json.loads(code)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"5paisa malformed creds: {e}")
    cred = {
        "APP_NAME": require("BROKER_FIVEPAISA_API_KEY"),
        "APP_SOURCE": require("BROKER_FIVEPAISA_API_SECRET"),
        "USER_ID": require("BROKER_FIVEPAISA_USER_ID"),
        "PASSWORD": require("BROKER_FIVEPAISA_USER_KEY"),
        "USER_KEY": require("BROKER_FIVEPAISA_USER_KEY"),
        "ENCRYPTION_KEY": require("BROKER_FIVEPAISA_USER_KEY"),
    }
    cl = sdk.FivePaisaClient(cred=cred)
    await to_thread(
        cl.get_totp_session, creds.get("client_code"), creds.get("totp"), creds.get("password"),
    )
    if not getattr(cl, "Login_check", False):
        raise RuntimeError("5paisa login failed")
    return AccessToken(
        token=cl.client_code,
        extras={
            "jwt": getattr(cl, "Jwt_token", None),
            "client_code": cl.client_code,
        },
    )


def _client(token: AccessToken):
    sdk = require_sdk("py5paisa", "Add `py5paisa` to requirements.txt.")
    cred = {
        "APP_NAME": require("BROKER_FIVEPAISA_API_KEY"),
        "APP_SOURCE": require("BROKER_FIVEPAISA_API_SECRET"),
        "USER_ID": require("BROKER_FIVEPAISA_USER_ID"),
        "PASSWORD": require("BROKER_FIVEPAISA_USER_KEY"),
        "USER_KEY": require("BROKER_FIVEPAISA_USER_KEY"),
        "ENCRYPTION_KEY": require("BROKER_FIVEPAISA_USER_KEY"),
    }
    cl = sdk.FivePaisaClient(cred=cred)
    cl.client_code = token.token
    return cl


async def fetch_holdings(token: AccessToken) -> List[Holding]:
    cl = _client(token)
    rows = await to_thread(cl.holdings) or []
    out: List[Holding] = []
    for h in rows:
        sym = (h.get("Symbol") or "").upper()
        if not sym:
            continue
        ex = (h.get("Exch") or "").upper() or None
        out.append(Holding(
            isin=(h.get("ISIN") or "").upper() or None,
            symbol=sym,
            asset_type="etf" if detect_etf(sym) else "equity",
            quantity=float(h.get("Quantity") or 0),
            avg_price=float(h.get("AveragePrice") or 0),
            current_price=float(h.get("CurrentPrice") or 0),
            name=h.get("FullName") or sym,
            exchange=ex,
            source_id=f"{ex}:{sym}" if ex else sym,
        ))
    return out


async def fetch_positions(token: AccessToken) -> List[Position]:
    cl = _client(token)
    rows = await to_thread(cl.positions) or []
    out: List[Position] = []
    for p in rows:
        out.append(Position(
            symbol=(p.get("ScripName") or "").upper(),
            exchange=(p.get("Exch") or "").upper(),
            quantity=float(p.get("NetQty") or 0),
            avg_price=float(p.get("AvgRate") or 0),
            pnl=float(p.get("BookedPL") or 0) + float(p.get("MTOM") or 0),
        ))
    return out


async def fetch_funds(token: AccessToken) -> Funds:
    cl = _client(token)
    margin = await to_thread(cl.margin) or [{}]
    m = margin[0] if isinstance(margin, list) and margin else {}
    return Funds(
        available_cash=float(m.get("AvailableMargin") or 0),
        used_margin=float(m.get("MarginUtilized") or 0),
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
