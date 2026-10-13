"""Angel One (SmartAPI) native broker adapter — raw HTTP, read-only.

Sign-in is Angel One's own "publisher login" page. Nivesh never asks for,
receives or stores a client code, PIN, OTP or TOTP:
  1. Browser → `https://smartapi.angelone.in/publisher-login
       ?api_key=<APP_KEY>&redirect_url=<NIVESH_CB>&state=<STATE>`
  2. The user signs in on Angel One's page, which then sends the browser
     (GET) to the app's Redirect URL with `auth_token` (the session JWT),
     `feed_token`, `refresh_token` and `state` in the query string.
  3. There is no code-for-token exchange: `auth_token` already is the
     session. `exchange_code` proves it with one getProfile read, which
     also gives the client code.
  4. Reads send `Authorization: Bearer <auth_token>` plus the X-* headers
     in `_headers`. The session lasts "till 12 midnight"; the user signs in
     again the next day. No refresh token is kept.

Holdings, positions and funds only. Nothing here places, modifies or
cancels an order.

Operator: add an app at https://smartapi.angelone.in (My Profile → My
APIs → Add App) with Nivesh's callback as its Redirect URL, and set
`BROKER_ANGEL_API_KEY`. This flow does not use `BROKER_ANGEL_API_SECRET`.
Optional `BROKER_ANGEL_PUBLIC_IP`: the backend's public IP, sent as
X-ClientPublicIP.

Docs: https://smartapi.angelone.in/docs/User (login flow, session life,
profile, RMS), /docs/Portfolio (holdings, positions), /docs/ResponseStructure
(headers, envelope), /docs/Exceptions (error codes), /docs/RateLimit.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional
from urllib.parse import quote

import httpx

from . import registry
from ._helpers import conf, detect_etf, require
from .base import AccessToken, Funds, Holding, HubPosition, Position

SLUG = "angel"
DISPLAY = "Angel One"
AUTH_STYLE = "oauth"
# Angel One names the session value `auth_token` on the redirect.
CALLBACK_CODE_PARAMS = ("auth_token",)
# Angel's login page appends `?auth_token=…` to the registered URL, so that URL
# must not already carry a query string: Nivesh advertises
# /api/broker/native/callback/angel (routes.broker_native._redirect_uri).
CALLBACK_PATH_STYLE = True
# Also on the redirect. `exchange_code` takes it as a keyword of the same
# name when the callback can pass it; only the Fenix headers need it.
CALLBACK_EXTRA_PARAMS = ("feed_token",)

_LOGIN_URL = "https://smartapi.angelone.in/publisher-login"
_API = "https://apiconnect.angelone.in"

# "The session established via SmartAPI remains active till 12 midnight" —
# the page names no timezone; read as IST, as `sessions._DAILY_EXPIRY_IST`
# does for the other Indian brokers.
_IST = timezone(timedelta(hours=5, minutes=30))

# docs/Exceptions: the error codes that mean the session token is not good.
_TOKEN_ERROR_CODES = {
    "AG8001",  # Invalid Token
    "AG8002",  # Token Expired
    "AG8003",  # Token missing
    "AB1010",  # AMX Session Expired
    "AB1011",  # Client not login
}

# docs/Orders "producttype" → the hub's vocabulary (BO in step with
# `hub_reads._PRODUCT_CODES`). A code that is not listed stays None.
_PRODUCTS = {
    "DELIVERY": "delivery",          # Cash & Carry for equity (CNC)
    "CARRYFORWARD": "carryforward",  # Normal for futures and options (NRML)
    "MARGIN": "margin",              # Margin Delivery
    "INTRADAY": "intraday",          # Margin Intraday Squareoff (MIS)
    "BO": "intraday",                # Bracket Order
}
# Same split as `hub_reads._segment_for`; any other exchange is "equity".
_SEGMENTS = {"NFO": "fno", "BFO": "fno", "MCX": "commodity", "CDS": "currency", "BCD": "currency"}


class AngelError(RuntimeError):
    """Angel One answered without a success status. Carries its error code only."""


class AngelSessionExpired(RuntimeError):
    """Angel One refused the session token (one of `_TOKEN_ERROR_CODES`)."""


class AngelRateLimited(RuntimeError):
    """HTTP 403 for exceeding the rate limit — the session itself is fine."""


class AngelDayPositionsNotSupported(NotImplementedError):
    """getPosition is documented as one list; no day book is derived from it."""


def auth_url(*, state: str, redirect_uri: str) -> str:
    api_key = require("BROKER_ANGEL_API_KEY")
    return (
        f"{_LOGIN_URL}?api_key={quote(api_key, safe='')}"
        f"&redirect_url={quote(redirect_uri, safe='')}&state={quote(state, safe='')}"
    )


def _next_midnight_ist(now: Optional[datetime] = None) -> datetime:
    """The next 00:00 IST after `now`, in UTC."""
    local = (now or datetime.now(timezone.utc)).astimezone(_IST)
    ends = local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return ends.astimezone(timezone.utc)


async def exchange_code(
    *, code: str, state: str, redirect_uri: str, feed_token: Optional[str] = None,
) -> AccessToken:
    """`code` is the `auth_token` from the redirect — already the session
    JWT, so nothing is exchanged. One getProfile read proves Angel One
    accepts it with Nivesh's app key, and gives the client code that
    recognises a reconnect of the same login.
    """
    jwt = (code or "").strip().removeprefix("Bearer ").strip()
    if not jwt:
        raise RuntimeError("Angel One: no auth_token on the redirect")
    profile = await _get(
        "/rest/secure/angelbroking/user/v1/getProfile", AccessToken(token=jwt), "profile",
    )
    client_code = str(profile.get("clientcode") or "").strip() if isinstance(profile, dict) else ""
    if not client_code:
        raise RuntimeError("Angel One: the profile read returned no client code")
    extras = {"user_id": client_code, "expires_at": _next_midnight_ist().isoformat()}
    if (feed_token or "").strip():
        extras["feed_token"] = feed_token.strip()
    return AccessToken(token=jwt, extras=extras)


def _headers(token: AccessToken) -> dict:
    """What every SmartAPI call carries (docs "Header Parameters" and the
    request samples). Key spelling is Fenix's, so `fenix_headers` can reuse
    the dict. The local IP and MAC of a server say nothing about the user,
    so they are fixed placeholders; the docs do not say what a server
    should send.
    """
    return {
        "Content-type": "application/json",
        "X-ClientLocalIP": "127.0.0.1",
        "X-ClientPublicIP": conf("BROKER_ANGEL_PUBLIC_IP") or "127.0.0.1",
        "X-MACAddress": "00:00:00:00:00:00",
        "Accept": "application/json",
        "X-PrivateKey": require("BROKER_ANGEL_API_KEY"),
        "X-UserType": "USER",
        "X-SourceID": "WEB",
        "Authorization": f"Bearer {token.token}",
    }


async def _get(path: str, token: AccessToken, what: str) -> Any:
    """GET one SmartAPI resource and return its `data`.

    A token Angel One refuses raises `AngelSessionExpired` when the reply
    carries one of its token error codes, else `httpx.HTTPStatusError` from
    a bare 401/403. Angel One also answers 403 when a rate limit is hit —
    that is `AngelRateLimited`, so a live session is not ended over it.
    Errors carry the broker's error code only, never a token or a payload.
    """
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{_API}{path}", headers=_headers(token))
    try:
        body = r.json()
    except ValueError:
        body = None
    env = body if isinstance(body, dict) else {}
    code = str(env.get("errorcode") or env.get("errorCode") or "").strip().upper()
    if code in _TOKEN_ERROR_CODES:
        raise AngelSessionExpired(f"Angel One rejected the session token ({code})")
    if r.status_code == 403 and "exceeding" in r.text.lower():
        raise AngelRateLimited(f"Angel One rate limit reached reading {what}")
    if code:
        raise AngelError(f"Angel One {what} read failed (errorcode {code})")
    r.raise_for_status()
    ok = env.get("status", env.get("success"))
    if ok is not True and str(ok).lower() != "true":
        # A reply that is not a success must never read as "nothing held".
        raise AngelError(f"Angel One {what} read failed (no success status)")
    return env.get("data")


async def fetch_holdings(token: AccessToken) -> List[Holding]:
    data = await _get("/rest/secure/angelbroking/portfolio/v1/getAllHolding", token, "holdings")
    out: List[Holding] = []
    for h in (data or {}).get("holdings") or []:
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


async def _position_rows(token: AccessToken) -> List[dict]:
    # One flat list, a row per instrument + product; `data` is null when empty.
    return await _get("/rest/secure/angelbroking/order/v1/getPosition", token, "positions") or []


def _instrument_type(row: dict, symbol: str) -> Optional[str]:
    """FUT / CE / PE from the row's `optiontype` / `instrumenttype`, else
    off the symbol's suffix as in SmartAPI's naming convention
    (BANKNIFTY25JAN2440000PE, BANKNIFTY28AUG24FUT).
    """
    option = (row.get("optiontype") or "").upper()
    if option in ("CE", "PE"):
        return option
    if (row.get("instrumenttype") or "").upper().startswith("FUT"):
        return "FUT"
    for suffix in ("FUT", "CE", "PE"):
        if symbol.endswith(suffix):
            return suffix
    return None


def _iso_date(raw: Any) -> Optional[str]:
    """`expirydate` as an ISO date. SmartAPI writes it 25JAN2024; a value
    in a shape not recognised stays None rather than being passed on."""
    text = str(raw or "").strip()
    for fmt in ("%d%b%Y", "%d%b%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _number(raw: Any) -> Optional[float]:
    """A numeric field that may be absent: None, not 0, when it is."""
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


async def fetch_positions(token: AccessToken) -> List[Position]:
    out: List[Position] = []
    for p in await _position_rows(token):
        out.append(Position(
            symbol=(p.get("tradingsymbol") or "").upper(),
            exchange=(p.get("exchange") or "").upper(),
            quantity=float(p.get("netqty") or 0),
            avg_price=float(p.get("avgnetprice") or p.get("netprice") or 0),
            pnl=float(p.get("pnl") or 0),
            product=p.get("producttype"),
        ))
    return out


async def fetch_hub_positions(token: AccessToken, kind: str) -> List[HubPosition]:
    """The net book in the hub's shape. `last_price` and `pnl` are filled
    only when the row carries `ltp` / `pnl` — the documented row has
    neither. `kind="day"` raises: the docs speak of a day book but document
    one list, and its `buyqty` / `sellqty` beside the `cf*` columns are not
    documented as today's trades, so no day book is derived from them.
    """
    if kind == "day":
        raise AngelDayPositionsNotSupported("Angel One has no day-positions read")
    if kind != "net":
        raise ValueError("kind must be 'net' or 'day'")
    out: List[HubPosition] = []
    for p in await _position_rows(token):
        sym = (p.get("tradingsymbol") or "").upper()
        ex = (p.get("exchange") or "").upper()
        raw = str(p.get("producttype") or "").strip() or None
        product = _PRODUCTS.get(raw.upper()) if raw else None
        segment = _SEGMENTS.get(ex, "equity")
        derivative = segment != "equity"
        strike = _number(p.get("strikeprice")) if derivative else None
        out.append(HubPosition(
            symbol=sym,
            exchange=ex,
            quantity=float(p.get("netqty") or 0),
            avg_price=float(p.get("avgnetprice") or p.get("netprice") or 0),
            # None, not 0.0, when the row has no last price: 0 would read as one.
            last_price=_number(p.get("ltp")),  # type: ignore[arg-type]
            pnl=_number(p.get("pnl")) or 0.0,
            product=product,
            product_raw=raw,
            segment=segment,
            is_intraday=product == "intraday",
            instrument_type=_instrument_type(p, sym) if derivative else None,
            expiry=_iso_date(p.get("expirydate")) if derivative else None,
            # Cash rows carry "-1"; only a real strike is passed on.
            strike=strike if strike and strike > 0 else None,
            kind=kind,
            name=(p.get("symbolname") or "").strip() or None,
        ))
    return out


async def fetch_funds(token: AccessToken) -> Funds:
    d = await _get("/rest/secure/angelbroking/user/v1/getRMS", token, "funds") or {}
    return Funds(
        available_cash=float(d.get("net") or 0),
        used_margin=float(d.get("utiliseddebits") or 0),
        collateral=float(d.get("collateral") or 0),
    )


def fenix_headers(token: AccessToken) -> dict:
    """The header dict Fenix's `AngelOne.authenticate()` builds after its
    own login, rebuilt from the stored session so Fenix can read without
    one. `x-api-key` is Nivesh's app key — what SmartAPI's WebSocket docs
    define that header as — not the literal in Fenix's source.
    `x-client-code` / `x-feed-token` are left out when the session does not
    hold them: the Fenix reader then names the missing key; nothing is
    made up.
    """
    extras = token.extras or {}
    headers = _headers(token)
    headers["x-api-key"] = headers["X-PrivateKey"]
    for key, field in (("x-client-code", "user_id"), ("x-feed-token", "feed_token")):
        value = str(extras.get(field) or "").strip()
        if value:
            headers[key] = value
    return headers


class _Module:
    SLUG = SLUG
    DISPLAY = DISPLAY
    AUTH_STYLE = AUTH_STYLE
    CALLBACK_CODE_PARAMS = CALLBACK_CODE_PARAMS
    CALLBACK_PATH_STYLE = CALLBACK_PATH_STYLE
    CALLBACK_EXTRA_PARAMS = CALLBACK_EXTRA_PARAMS
    # `FENIX_CLASS = "AngelOne"` is deliberately not set, so reads stay on
    # this adapter: Fenix requires an `x-feed-token` header and the callback
    # hands `exchange_code` only `auth_token`. Set it here once `feed_token`
    # is passed through too.
    auth_url = staticmethod(auth_url)
    exchange_code = staticmethod(exchange_code)
    fetch_holdings = staticmethod(fetch_holdings)
    fetch_positions = staticmethod(fetch_positions)
    fetch_hub_positions = staticmethod(fetch_hub_positions)
    fetch_funds = staticmethod(fetch_funds)
    fenix_headers = staticmethod(fenix_headers)


registry.register(_Module())
