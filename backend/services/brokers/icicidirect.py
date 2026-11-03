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

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import httpx

from . import registry
from ._helpers import detect_etf, require
from .base import (
    AccessToken, BrokerTrade, Candle, ContractChart, ContractQuote, ContractRef, Funds, Holding, HubPosition, Position,
)

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
        failure = IciciDirectError(
            f"ICICI Direct {what} failed (HTTP {r.status_code}, API status {status!r})",
        )
        failure.http_status = r.status_code   # a caller may treat a 503 as "try again"
        raise failure
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


# ── Trade book ───────────────────────────────────────────────────────────
# Breeze's `GET /trades` (the SDK's get_trade_list): a JSON body with `exchange_code` (always), and from_date / to_date /
# product_type / action / stock_code when given. One call per exchange. The brokers send the current day only for a day range of
# one day. NOT SEEN LIVE: the field names below are the ones ICICI's trade-list documentation lists; the first real read must be
# compared with the broker's own screen (test_reports/OVERRIDE_copilot_broker_book.md).
_TRADE_EXCHANGES = ("NSE", "NFO")


def _trade_time(row: Dict[str, Any]) -> Optional[str]:
    raw = str(row.get("trade_date") or row.get("order_datetime") or "").strip()
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=_IST).isoformat()
        except ValueError:
            continue
    return raw or None


def _breeze_trade(row: Dict[str, Any], exchange: str) -> Optional[BrokerTrade]:
    action = str(row.get("action") or "").strip().lower()
    code = str(row.get("stock_code") or "").strip().upper()
    qty = _number(row.get("quantity"))
    px = _number(row.get("average_price") if row.get("average_price") not in (None, "") else row.get("trade_price"))
    if action not in ("buy", "sell") or not code or not qty or qty <= 0 or not px or px <= 0:
        return None
    product = str(row.get("product_type") or "").strip()
    right = str(row.get("right") or "").strip().lower()
    itype = {"call": "CE", "put": "PE"}.get(right) if "option" in product.lower() else ("FUT" if "future" in product.lower() else None)
    return BrokerTrade(
        symbol=code, exchange=str(row.get("exchange_code") or exchange).strip().upper(), side=action, quantity=qty, price=px,
        traded_at=_trade_time(row), trade_id=str(row.get("exchange_trade_id") or row.get("trade_id") or "") or None,
        order_id=str(row.get("order_id") or row.get("exchange_order_id") or "") or None, product_raw=product or None,
        instrument_type=itype, expiry=_iso_date(row.get("expiry_date")),
        strike=_number(row.get("strike_price")) if itype in ("CE", "PE") else None)


async def fetch_trades(token: AccessToken) -> List[BrokerTrade]:
    """Today's fills in NSE cash and NFO. Read-only (a GET)."""
    day = datetime.now(_IST).date().isoformat()
    out: List[BrokerTrade] = []
    for exchange in _TRADE_EXCHANGES:
        rows = await _signed_get("trades", {"exchange_code": exchange, "from_date": f"{day}T00:00:00.000Z",
                                            "to_date": f"{day}T23:59:59.000Z"}, token, f"{exchange} trades") or []
        for r in rows if isinstance(rows, list) else []:
            t = _breeze_trade(r, exchange) if isinstance(r, dict) else None
            if t is not None:
                out.append(t)
    return out


# ── Contract chart ───────────────────────────────────────────────────────
# The hub's view → Breeze's own interval name and how many days one read
# covers. There is no daily view. Seen live on 2026-10-14 for an NFO stock
# option and its future: "1day" (the documented name) and "1minute" answer
# API status 500, and the rows "day" returns are not candles — their `close`
# is the PREVIOUS day's close (13 Oct: close 35.15 while that day's last
# trade and the quote's ltp were 21.85) — so they would draw wrong bars.
_CHART_VIEWS: Dict[str, tuple] = {"5m": ("5minute", 7), "30m": ("30minute", 45)}
_RIGHTS = {"CE": "call", "PE": "put"}
# `/quotes` answers HTTP 503 when calls come in a burst (seen live: two in a
# row answered, the next three did not). It is tried once more after this.
_QUOTE_RETRY_AFTER_S = 0.5


def _number(raw: Any) -> Optional[float]:
    """Breeze sends a number as a number in a quote and as text in a candle.
    None for anything that is not one — a missing price is not a zero."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        text = str(raw).strip()
        return float(text) if text else None
    except ValueError:
        return None


def _ist_iso(raw: Any, fmt: str) -> Optional[str]:
    """Breeze's exchange-local time (no offset) as an ISO timestamp in IST."""
    try:
        return datetime.strptime(str(raw).strip(), fmt).replace(tzinfo=_IST).isoformat()
    except ValueError:
        return None


def _contract_payload(contract: ContractRef) -> Dict[str, str]:
    """A future or an option in Breeze's words. Refuses anything else, an
    option with no strike, and an expiry that is not an ISO date."""
    kind = (contract.instrument_type or "").upper()
    option = kind in _RIGHTS
    if not option and kind != "FUT":
        raise IciciDirectNotSupported("ICICI Direct charts are read for futures and options only")
    if option and not contract.strike:
        raise IciciDirectNotSupported("An option's chart needs its strike price")
    try:
        expiry = datetime.strptime(contract.expiry, "%Y-%m-%d").date().isoformat()
    except (TypeError, ValueError):
        raise IciciDirectNotSupported("A contract's chart needs its expiry date") from None
    return {
        "stock_code": contract.symbol,
        "exchange_code": contract.exchange,
        "product_type": "options" if option else "futures",
        # Breeze's samples send every expiry at 06:00 UTC.
        "expiry_date": f"{expiry}T06:00:00.000Z",
        "right": _RIGHTS.get(kind, "others"),
        "strike_price": f"{contract.strike:g}" if option else "0",
    }


def _candle(row: Any) -> Optional[Candle]:
    """One `/historicalcharts` row, or None when it has no time or lacks one
    of its four prices — a bar is not drawn from a guess."""
    if not isinstance(row, dict):
        return None
    when = _ist_iso(row.get("datetime"), "%Y-%m-%d %H:%M:%S")
    prices = [_number(row.get(k)) for k in ("open", "high", "low", "close")]
    if when is None or any(p is None for p in prices):
        return None
    return Candle(
        time=when, open=prices[0], high=prices[1], low=prices[2], close=prices[3],
        volume=_number(row.get("volume")), open_interest=_number(row.get("open_interest")),
    )


def _quote(rows: Any) -> Optional[ContractQuote]:
    row = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None
    if row is None:
        return None
    return ContractQuote(
        last_price=_number(row.get("ltp")),
        last_traded_at=_ist_iso(row.get("ltt"), "%d-%b-%Y %H:%M:%S"),
        open=_number(row.get("open")),
        high=_number(row.get("high")),
        low=_number(row.get("low")),
        previous_close=_number(row.get("previous_close")),
        change_pct=_number(row.get("ltp_percent_change")),
        spot_price=_number(row.get("spot_price")),
        volume=_number(row.get("total_quantity_traded")),
    )


async def fetch_contract_chart(token: AccessToken, contract: ContractRef, interval: str) -> ContractChart:
    """The price history of one future or option and its latest quote — the
    contract's own price, not the underlying share's. Two reads
    (`/historicalcharts`, `/quotes`); nothing is stored and nothing is ordered.

    `contract.symbol` is ICICI's stock code, as `fetch_hub_positions` gives
    it. `interval` is "5m" or "30m". The candles are the chart: if they
    cannot be read the call fails. The quote is an extra: a 503 is tried once
    more, and if it still fails the chart comes back with `quote=None` —
    unless ICICI refused the session, which always raises.
    """
    view = _CHART_VIEWS.get(interval)
    if view is None:
        raise IciciDirectNotSupported(f"ICICI Direct has no {interval!r} chart view")
    breeze_interval, days = view
    which = _contract_payload(contract)
    end = datetime.now(timezone.utc).replace(microsecond=0)
    window = {
        "interval": breeze_interval,
        "from_date": _timestamp(end - timedelta(days=days)),
        "to_date": _timestamp(end),
    }
    rows = await _signed_get("historicalcharts", {**window, **which}, token, "chart")
    bars = (_candle(r) for r in (rows if isinstance(rows, list) else []))
    candles = sorted((c for c in bars if c is not None), key=lambda c: c.time)
    return ContractChart(candles=candles, quote=await _read_quote(which, token))


async def _read_quote(which: Dict[str, str], token: AccessToken) -> Optional[ContractQuote]:
    """One `/quotes` read: a 503 is tried once more; any other failure, or a
    second 503, is None. A refused session always raises."""
    for attempt in (1, 2):
        try:
            return _quote(await _signed_get("quotes", which, token, "quote"))
        except IciciDirectSessionExpired:
            raise
        except IciciDirectError as failure:
            if attempt == 2 or getattr(failure, "http_status", None) != 503:
                return None
            await asyncio.sleep(_QUOTE_RETRY_AFTER_S)
    return None


async def fetch_contract_quote(token: AccessToken, contract: ContractRef) -> Optional[ContractQuote]:
    """The latest quote of one future or option, on its own — one read of
    `/quotes`. None when ICICI returns no quote or it cannot be read; a
    refused session raises. Nothing is stored and nothing is ordered."""
    return await _read_quote(_contract_payload(contract), token)


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
    fetch_trades = staticmethod(fetch_trades)
    fetch_contract_chart = staticmethod(fetch_contract_chart)
    fetch_contract_quote = staticmethod(fetch_contract_quote)


registry.register(_Module())
