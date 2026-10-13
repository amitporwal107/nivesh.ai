"""ICICI Direct native broker adapter (Breeze API v1).

Read-only: demat / portfolio holdings, positions, funds. Raw HTTP — the
Breeze SDK is not a dependency, and nothing here places, modifies or
cancels an order.

Auth model (https://api.icicidirect.com/breezeapi/documents/index.html):
  1. Browser → `https://api.icicidirect.com/apiuser/login?api_key=<APP_KEY>`;
     the customer signs in on ICICI Direct's page. The URL takes nothing
     else — no redirect parameter and no `state`.
  2. ICICI returns the browser to the redirect URL registered with the app
     by a cross-site form POST: form field `API_Session`, the same one-time
     session key also appended to the URL as `?apisession=`. Because ICICI
     appends its own `?…`, the registered URL must carry no query string
     (`CALLBACK_PATH_STYLE`): `<host>/api/broker/native/callback/icicidirect`.
     `routes.broker_native` answers that POST with a 303 to the same URL as
     a GET and finishes the sign-in there, where the user's cookie is sent.
       https://www.icicidirect.com/ilearn/stocks/articles/how-to-generate-session-key-and-install-sdk-for-breeze-api
  3. GET `/customerdetails` {SessionToken: <session key>, AppKey} →
     `session_token` + `idirect_userid`.
  4. Every later call: GET with a JSON body and the headers `X-AppKey`,
     `X-SessionToken`, `X-Timestamp` and
     `X-Checksum: token sha256(timestamp + body + secret_key)`.
  The session key "is valid for 24hrs or before midnight, whichever is
  earlier" and cannot be renewed without the customer.

What ICICI Direct's own pages say about Breeze apps (sign-in is on by
product decision; these stand as facts):
  * An app is registered by one ICICI Direct customer under their own login,
    one API key per client, tied to that client's static IP, "for individual
    and personal trading purposes. Any integration with any third-party
    applications for trading is strictly prohibited."
      https://www.icicidirect.com/faqs/fno/how-can-i-use-a-third-party-platform-to-trade-via-breeze-api
      https://www.icicidirect.com/faqs/fno/can-i-create-multiple-api-keys
  * NOT TESTED LIVE: whether ICICI accepts a login made with Nivesh's app
    key by a customer other than the one who registered the app. Nothing
    official says it does.

Operator: register the app at https://api.icicidirect.com/apiuser/home with
the redirect URL above and the backend's egress IP as the static IP.
Secrets: BROKER_ICICIDIRECT_API_KEY, BROKER_ICICIDIRECT_API_SECRET.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import httpx

from . import registry
from ._helpers import detect_etf, require
from .base import AccessToken, Funds, Holding, HubPosition, Position

SLUG = "icicidirect"
DISPLAY = "ICICI Direct"
AUTH_STYLE = "oauth"

# The one switch for sign-in. Off, `auth_url` / `exchange_code` refuse with
# CONNECT_BLOCKED_REASON and the registry lists the broker as not built.
CONNECTABLE = True
CONNECT_BLOCKED_REASON = "ICICI Direct sign-in is switched off in Nivesh."

# How the session key comes back (see step 2 above): the registered URL has
# no query string, the key is in the query as `apisession`, and the same
# value is POSTed as the form field `API_Session`.
CALLBACK_PATH_STYLE = True
CALLBACK_CODE_PARAMS = ("apisession",)
CALLBACK_FORM_FIELDS = ("API_Session",)
# ICICI's app form limits the Redirect URL's length, so the URL to register
# is the short one: <host>/api/b/icici (routes.broker_native.short_router).
CALLBACK_ALIAS = "icici"

_LOGIN_URL = "https://api.icicidirect.com/apiuser/login?api_key="
_API = "https://api.icicidirect.com/breezeapi/api/v1"

# `Error` texts Breeze answers with. The first was observed on the live API
# for an app key it does not know; the second is the invalid-session text
# ICICI's own SDK checks for; the third is from ICICI's FAQ ("Request
# Denied: The IP address used does not match with the static IP declared
# when this API key was created"). The first and third are Nivesh's own
# setup, not the customer's session, and must not end it.
_ERR_APP_KEY = "Public Key does not exist."
_ERR_SESSION = "Invalid session."
_ERR_STATIC_IP = "static IP"

_IST = timezone(timedelta(hours=5, minutes=30))

# ICICI product → hub product. Only the two ICICI itself defines: "Cash"
# settles by delivery, "Margin" is its intraday product. Every other
# product stays None and keeps its name in `product_raw`.
#   https://www.icicidirect.com/faqs/stocks/how-is-intraday-trading-different-from-trading-in-cash-segment-delivery
_PRODUCTS: Dict[str, str] = {"cash": "delivery", "margin": "intraday"}
_SEGMENTS = ("equity", "fno", "commodity", "currency")


class IciciDirectError(RuntimeError):
    """A Breeze call failed. The text never carries a token, a key or the
    broker's response body."""


class IciciDirectSessionExpired(IciciDirectError):
    """ICICI Direct refused the session token — the customer must sign in again."""


class IciciDirectNotSupported(IciciDirectError):
    """Something this adapter cannot serve: sign-in, or the day positions book."""


def _require_connectable() -> None:
    if not CONNECTABLE:
        raise IciciDirectNotSupported(CONNECT_BLOCKED_REASON)


# ── Request signing ──────────────────────────────────────────────────────
def _timestamp(now: Optional[datetime] = None) -> str:
    """ISO-8601 UTC with zero milliseconds, e.g. `2024-06-01T10:23:56.000Z`.
    Breeze honours a request only within 60 seconds of this."""
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _checksum(timestamp: str, body: str, secret: str) -> str:
    return hashlib.sha256((timestamp + body + secret).encode("utf-8")).hexdigest()


def _unwrap(r: httpx.Response, what: str) -> Any:
    """The `Success` part of a Breeze answer, or raise.

    Breeze wraps every answer as `{"Success", "Status", "Error"}` and does
    not always use the HTTP status for a failure (an unknown app key is
    HTTP 200 on `/customerdetails` and HTTP 401 on a signed read).
    """
    try:
        body = r.json()
    except ValueError:
        body = None
    envelope = body if isinstance(body, dict) else {}
    error = envelope.get("Error")
    if error == _ERR_APP_KEY:
        raise IciciDirectError(
            "ICICI Direct did not recognise Nivesh's app key (BROKER_ICICIDIRECT_API_KEY)",
        )
    if isinstance(error, str) and _ERR_STATIC_IP in error:
        raise IciciDirectError(
            "ICICI Direct refused this server's IP — it is not the static IP registered with the app key",
        )
    if r.status_code in (401, 403) or error == _ERR_SESSION:
        raise IciciDirectSessionExpired(f"ICICI Direct rejected the session ({what})")
    status = envelope.get("Status")
    if r.status_code != 200 or error or str(status) != "200":
        raise IciciDirectError(
            f"ICICI Direct {what} failed (HTTP {r.status_code}, API status {status!r})",
        )
    return envelope.get("Success")


async def _signed_get(path: str, payload: Dict[str, Any], token: AccessToken, what: str) -> Any:
    """Breeze reads are GET requests that carry a JSON body; the checksum
    covers exactly the bytes sent."""
    api_key = require("BROKER_ICICIDIRECT_API_KEY")
    api_secret = require("BROKER_ICICIDIRECT_API_SECRET")
    body = json.dumps(payload, separators=(",", ":"))
    timestamp = _timestamp()
    headers = {
        "Content-Type": "application/json",
        "X-Checksum": "token " + _checksum(timestamp, body, api_secret),
        "X-Timestamp": timestamp,
        "X-AppKey": api_key,
        "X-SessionToken": token.token,
    }
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.request("GET", f"{_API}/{path}", content=body, headers=headers)
    return _unwrap(r, what)


# ── Sign-in ──────────────────────────────────────────────────────────────
def _login_url(api_key: str) -> str:
    return _LOGIN_URL + quote_plus(api_key)


def _session_expiry(now: Optional[datetime] = None) -> datetime:
    """When a session started at `now` ends: "24hrs or before midnight,
    whichever is earlier" — the next midnight, never more than 24h away.
    ICICI's pages name no timezone; midnight is read as IST.
    """
    local = (now or datetime.now(timezone.utc)).astimezone(_IST)
    midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc)


def auth_url(*, state: str, redirect_uri: str) -> str:
    """Breeze's login URL takes only the app key. The redirect URL is the
    one registered with the app, and there is no documented `state`
    parameter, so neither argument is sent.
    """
    _require_connectable()
    return _login_url(require("BROKER_ICICIDIRECT_API_KEY"))


async def exchange_code(*, code: str, state: str, redirect_uri: str) -> AccessToken:
    """`code` is the one-time session key (`apisession`). GET
    /customerdetails turns it into the session token; that call is the
    only one that needs no signing headers.
    """
    _require_connectable()
    api_key = require("BROKER_ICICIDIRECT_API_KEY")
    require("BROKER_ICICIDIRECT_API_SECRET")  # every read after this needs it
    body = json.dumps({"SessionToken": code, "AppKey": api_key}, separators=(",", ":"))
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.request(
            "GET", f"{_API}/customerdetails",
            content=body, headers={"Content-Type": "application/json"},
        )
    details = _unwrap(r, "session exchange")
    token = details.get("session_token") if isinstance(details, dict) else None
    if not token:
        raise IciciDirectError("ICICI Direct session exchange returned no session token")
    return AccessToken(
        token=token,
        extras={
            "user_id": details.get("idirect_userid"),
            "expires_at": _session_expiry().isoformat(),
        },
    )


# ── Holdings ─────────────────────────────────────────────────────────────
async def fetch_holdings(token: AccessToken) -> List[Holding]:
    """Demat holdings, priced from the NSE equity portfolio.

    `/dematholdings` is the list: ICICI stock code, ISIN, quantity — no
    prices. `/portfolioholdings` (NSE) adds average and market price by
    stock code. `symbol` is ICICI's own stock code (e.g. `UNITEC`), not
    the NSE ticker — the API returns no exchange symbol, so the ISIN is
    the key to enrich on. A portfolio row with no demat row is left out:
    it has no ISIN to identify it.
    """
    demat = await _signed_get("dematholdings", {}, token, "demat holdings") or []
    portfolio = await _signed_get(
        "portfolioholdings",
        {"exchange_code": "NSE", "from_date": "", "to_date": "", "stock_code": "", "portfolio_type": ""},
        token, "portfolio holdings",
    ) or []
    priced: Dict[str, Dict[str, Any]] = {}
    for p in portfolio:
        priced.setdefault(str(p.get("stock_code") or "").strip().upper(), p)
    out: List[Holding] = []
    for h in demat:
        code = str(h.get("stock_code") or "").strip().upper()
        if not code:
            continue
        p = priced.get(code) or {}
        out.append(Holding(
            isin=str(h.get("stock_ISIN") or "").strip().upper() or None,
            symbol=code,
            asset_type="etf" if detect_etf(code) else "equity",
            quantity=float(h.get("quantity") or 0),
            avg_price=float(p.get("average_price") or 0),
            current_price=float(p.get("current_market_price") or 0),
            source_id=f"{SLUG}:{code}",
        ))
    return out


# ── Positions ────────────────────────────────────────────────────────────
def _iso_date(value: Any) -> Optional[str]:
    """Breeze's `27-Feb-2025` → `2025-02-27`; None for anything else."""
    try:
        return datetime.strptime(str(value).strip(), "%d-%b-%Y").date().isoformat()
    except ValueError:
        return None


def _hub_position(p: Dict[str, Any]) -> HubPosition:
    """One `/portfoliopositions` row in the hub's shape. Only what the row
    carries is filled; `symbol` is ICICI's stock code and the contract is
    described by `instrument_type` / `expiry` / `strike`.
    """
    exchange = str(p.get("exchange_code") or "").strip().upper()
    product_raw = str(p.get("product_type") or "").strip() or None
    product_key = (product_raw or "").lower()
    product = _PRODUCTS.get(product_key)
    is_option = "option" in product_key
    instrument_type = None
    if is_option:
        right = str(p.get("right") or "").strip().lower()
        instrument_type = {"call": "CE", "put": "PE"}.get(right)
    elif "future" in product_key:
        instrument_type = "FUT"
    segment = str(p.get("segment") or "").strip().lower()
    if segment not in _SEGMENTS:
        segment = "fno" if exchange in ("NFO", "BFO") else "equity"
    # `action` gives the side of the position; quantity becomes signed.
    quantity = float(p.get("quantity") or 0)
    action = str(p.get("action") or "").strip().lower()
    if action in ("buy", "sell"):
        quantity = abs(quantity) if action == "buy" else -abs(quantity)
    return HubPosition(
        symbol=str(p.get("stock_code") or "").strip().upper(),
        exchange=exchange,
        quantity=quantity,
        avg_price=float(p.get("average_price") or 0),
        last_price=float(p.get("ltp") or 0),
        pnl=float(p.get("pnl") or 0),
        product=product,
        product_raw=product_raw,
        segment=segment,
        is_intraday=product == "intraday",
        instrument_type=instrument_type,
        expiry=_iso_date(p.get("expiry_date")),
        strike=float(p.get("strike_price") or 0) if is_option else None,
        kind="net",
    )


async def fetch_hub_positions(token: AccessToken, kind: str) -> List[HubPosition]:
    """Breeze has one positions book and no parameter that separates the
    day's trades from it. It is served as `net`; `day` is refused rather
    than handing the same rows back under another label.
    """
    if kind != "net":
        raise IciciDirectNotSupported(
            f"ICICI Direct has no separate {kind!r} positions book — only net positions",
        )
    rows = await _signed_get("portfoliopositions", {}, token, "positions") or []
    return [_hub_position(p) for p in rows]


async def fetch_positions(token: AccessToken) -> List[Position]:
    out: List[Position] = []
    for p in await fetch_hub_positions(token, "net"):
        out.append(Position(
            symbol=p.symbol,
            exchange=p.exchange,
            quantity=p.quantity,
            avg_price=p.avg_price,
            pnl=p.pnl,
            product=p.product_raw,
        ))
    return out


async def fetch_funds(token: AccessToken) -> Funds:
    """`/funds` reports, per segment, what the customer has allocated for
    trading and what trades have blocked. The linked bank balance it also
    returns is not broker funds and is not read.
    """
    f = await _signed_get("funds", {}, token, "funds") or {}
    allocated = sum(float(f.get(f"allocated_{s}") or 0) for s in _SEGMENTS)
    blocked = sum(float(f.get(f"block_by_trade_{s}") or 0) for s in _SEGMENTS)
    return Funds(available_cash=allocated - blocked, used_margin=blocked)


class _Module:
    SLUG = SLUG
    DISPLAY = DISPLAY
    AUTH_STYLE = AUTH_STYLE
    IMPLEMENTED = CONNECTABLE  # the registry lists it as not built when sign-in is off
    CONNECTABLE = CONNECTABLE
    CONNECT_BLOCKED_REASON = CONNECT_BLOCKED_REASON
    CALLBACK_PATH_STYLE = CALLBACK_PATH_STYLE
    CALLBACK_CODE_PARAMS = CALLBACK_CODE_PARAMS
    CALLBACK_FORM_FIELDS = CALLBACK_FORM_FIELDS
    CALLBACK_ALIAS = CALLBACK_ALIAS
    auth_url = staticmethod(auth_url)
    exchange_code = staticmethod(exchange_code)
    fetch_holdings = staticmethod(fetch_holdings)
    fetch_positions = staticmethod(fetch_positions)
    fetch_hub_positions = staticmethod(fetch_hub_positions)
    fetch_funds = staticmethod(fetch_funds)


registry.register(_Module())
