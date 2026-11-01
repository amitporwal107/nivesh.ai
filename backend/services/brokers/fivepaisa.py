"""5paisa native broker adapter.

SIGN-IN IS NOT OFFERED. The py5paisa SDK's session call
(`get_totp_session(client_code, totp, pin)`) needs the user's 5paisa
password/PIN and a one-time code typed into Nivesh, and Nivesh never accepts
broker credentials: an account is connected only by signing in on the
broker's own page (see services/brokers/sessions.py). `exchange_code`
therefore refuses every request, and `AUTH_STYLE = "form"` keeps the broker
off the connectable list (`registry.list_supported`). The read helpers stay
for the day 5paisa offers a redirect sign-in.

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


CREDENTIALS_REFUSED = (
    "5paisa sign-in is not offered: it needs your 5paisa password and a one-time code, "
    "and Nivesh never accepts broker credentials."
)


async def exchange_code(*, code: str, state: str, redirect_uri: str) -> AccessToken:
    """Refuse. The only 5paisa session the SDK offers is built from the user's
    password/PIN and TOTP, which Nivesh must not receive. `code` is never
    parsed, logged or passed on."""
    raise RuntimeError(CREDENTIALS_REFUSED)


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
