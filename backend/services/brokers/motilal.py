"""Motilal Oswal (MOFSL OpenAPI, "moAPI") native broker adapter — raw HTTP, read-only.

Sign-in is MOFSL's own "Login through Portal" page. Nivesh never asks for,
receives or stores a client code, password, OTP, PAN / date of birth or TOTP:
  1. Browser → `https://invest.motilaloswal.com/OpenAPI/Login.aspx?apikey=<APP_KEY>`
  2. The customer signs in on MOFSL's page, which then sends the browser
     (GET) to the Redirect URL registered for the app with
     `?authtoken=<token>` appended.
  3. POST /rest/login/v1/getaccesstoken (app key + app secret + authtoken)
     → `accesstoken`; POST /rest/login/v5/getprofile → the client code.
  4. Every call sends the authtoken as `Authorization`, plus `accesstoken`,
     `ApiKey`, `apisecretkey`, `vendorinfo` and the headers in `_headers`.
  The session ends "every day morning 6 a.m." and at most 24 hours after
  sign-in. Nothing renews it without the customer.

DP holdings, positions and the margin summary only. Nothing here places,
modifies or cancels an order.

NOT RUN AGAINST A LIVE ACCOUNT, and MOFSL's pages leave these open:
  * Whether ONE app key signs in ANY client. The portal login is described
    as the flow for a "third party vendor" using an "APP Key (provided by
    MOFSL)", and vendors register by e-mail — but the same page says "API
    key has to be create by client itself not anyone else", and the
    go-live mail names one Client ID per API key.
  * No `state` parameter is documented, so none is sent and none is expected
    back: the callback finds the user by their Nivesh session cookie
    (routes.broker_native._find_state).
  * What a vendor's server sends in the device headers (`_DEVICE_HEADERS`).
  * Whether reads need the backend's IP on the app's static-IP whitelist
    (the FAQ says it of order placement in one answer and of "all API
    requests" in another; error MO2035 "Unauthorized IP Address").

Left empty because the API does not return it: a holding's last price,
exchange and trading symbol (`symbol` is MOFSL's scrip name, e.g. "RELAXO
EQ" — the ISIN is the key); a position's instrument name; the P&L of a day
row that also has carried-forward quantity.

Operator: register Nivesh as a vendor with MOFSL (tradingapi@motilaloswal.com,
or "Become a partner" on https://invest.motilaloswal.com/moapi/) with the
Redirect URL `<host>/api/broker/native/callback/motilal`, and set
`BROKER_MOTILAL_API_KEY`, `BROKER_MOTILAL_API_SECRET` and
`BROKER_MOTILAL_VENDOR_INFO` (the vendor short name MOFSL assigns; for a key
a client created for their own use, that client's code). Optional
`BROKER_MOTILAL_PUBLIC_IP`: the backend's public IP, sent as ClientPublicIp.

Docs: https://invest.motilaloswal.com/moapi/APIDocumentation/Introduction
(login, headers, holding, position, margin, error codes), .../FAQ (session
life, vendors, static IP) and MOFSL's SDK https://github.com/motradingapi/PythonSDK
(getaccesstoken call, header names).
"""
from __future__ import annotations

import logging
import platform
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from . import registry
from ._helpers import conf, detect_etf, require
from .base import AccessToken, Funds, Holding, HubPosition, Position

logger = logging.getLogger(__name__)

SLUG = "motilal"
DISPLAY = "Motilal Oswal"
AUTH_STYLE = "oauth"
# MOFSL names the session value `authtoken` on the redirect.
CALLBACK_CODE_PARAMS = ("authtoken",)
# The docs show `?authtoken=…` appended to the registered URL, so that URL
# must not already carry a query string: Nivesh advertises
# /api/broker/native/callback/motilal (routes.broker_native._redirect_uri).
CALLBACK_PATH_STYLE = True

_LOGIN_URL = "https://invest.motilaloswal.com/OpenAPI/Login.aspx"
_API = "https://openapi.motilaloswal.com"

# "Product and Its Version" — the value the docs give and MOFSL's SDK sends.
_USER_AGENT = "MOSL/V.1.1.0"

# The docs list these as mandatory and give sample values only ("1.2.3.4",
# "00:00:00:00:00:00", "Windows 10", "DELL", "Chrome"); they do not say what a
# vendor's server sends, and MOFSL's own SDK sends fixed text for most. These
# describe the Nivesh backend that makes the call. The customer's own device
# is not known here and is not made up.
_DEVICE_HEADERS = {
    "SourceId": "WEB",  # WEB | MOBILE | DESKTOP
    "ClientLocalIp": "127.0.0.1",
    "MacAddress": "00:00:00:00:00:00",
    "osname": platform.system() or "Linux",
    "osversion": platform.release() or "unknown",
    "devicemodel": "server",
    "manufacturer": "unknown",
    "productname": "Nivesh",
    "productversion": "1",
    # "Mandatory for WEB": the web client here is this server's HTTP library.
    "browsername": "httpx",
    "browserversion": httpx.__version__,
}

# No timezone is named for "6 a.m."; read as IST, as
# `sessions._DAILY_EXPIRY_IST` does for the other Indian brokers.
_IST = timezone(timedelta(hours=5, minutes=30))

# "Error Codes And Description": the codes that say the customer's session is
# not good. Every other code (API key, secret key, vendor tag, headers, IP)
# is Nivesh's own setup and must not end a session.
_SESSION_ERROR_CODES = {
    "MO8001",  # Invalid Token
    "MO8002",  # Token Expired
    "MO8003",  # Token missing
    "MO1011",  # Client Not Login
}
# Read as "nothing to list" on their own read only — the docs do not say when
# they are sent.
_NO_HOLDINGS = "MO1015"   # Holding Not Found
_NO_POSITIONS = "MO1016"  # Position Not Found
_ERROR_CODE = re.compile(r"[A-Z]{2,6}\d{1,6}")

# MOFSL exchange names → the hub's; any other name is kept as it is.
_EXCHANGES = {"NSEFO": "NFO", "BSEFO": "BFO", "NSECD": "CDS", "BSECD": "BCD"}
# Same split as `hub_reads._segment_for`, plus NCDEX; any other exchange is "equity".
_SEGMENTS = {
    "NFO": "fno", "BFO": "fno", "MCX": "commodity", "NCDEX": "commodity",
    "CDS": "currency", "BCD": "currency",
}
# FAQ: with Normal "You can carry forward positions to the next trading day",
# and Value Plus "Stands for Margin Intraday Square Off (MIS)". SELLFROMDP
# and BTST are listed without a meaning and stay None.
_PRODUCTS = {"NORMAL": "carryforward", "DELIVERY": "delivery", "VALUEPLUS": "intraday"}


class MotilalError(RuntimeError):
    """A MOFSL call failed. The text carries the HTTP status and MOFSL's
    error code only — never a token, a key or the response body."""


class MotilalSessionExpired(MotilalError):
    """MOFSL refused the session — the customer must sign in again."""


# ── Sign-in ──────────────────────────────────────────────────────────────
def auth_url(*, state: str, redirect_uri: str) -> str:
    """The login page takes only the app key. MOFSL sends the customer back
    to the Redirect URL registered for that key, and documents no `state`
    parameter, so neither argument is sent.
    """
    api_key = require("BROKER_MOTILAL_API_KEY")
    # Needed for every call after the redirect: fail before the customer leaves.
    require("BROKER_MOTILAL_API_SECRET")
    require("BROKER_MOTILAL_VENDOR_INFO")
    return f"{_LOGIN_URL}?apikey={quote(api_key, safe='')}"


def _session_end(now: Optional[datetime] = None) -> datetime:
    """The next 06:00 IST after `now`, in UTC — always inside the 24 hours
    the FAQ gives a token."""
    local = (now or datetime.now(timezone.utc)).astimezone(_IST)
    ends = local.replace(hour=6, minute=0, second=0, microsecond=0)
    if ends <= local:
        ends += timedelta(days=1)
    return ends.astimezone(timezone.utc)


async def exchange_code(*, code: str, state: str, redirect_uri: str) -> AccessToken:
    """`code` is the `authtoken` from the redirect. It becomes a usable
    session with the access token MOFSL issues against Nivesh's app key and
    secret; one profile read then gives the client code that recognises a
    reconnect of the same login.
    """
    auth_token = (code or "").strip()
    if not auth_token:
        raise MotilalError("Motilal Oswal: no authtoken on the redirect")
    session = AccessToken(token=auth_token)
    granted = await _post("/rest/login/v1/getaccesstoken", session, "access token")
    access_token = str(granted.get("accesstoken") or "").strip()
    if not access_token:
        raise MotilalError("Motilal Oswal returned no access token")
    session.extras["access_token"] = access_token
    profile = (await _post("/rest/login/v5/getprofile", session, "profile")).get("data")
    client_code = str(profile.get("clientcode") or "").strip() if isinstance(profile, dict) else ""
    if not client_code:
        raise MotilalError("Motilal Oswal: the profile read returned no client code")
    session.extras["user_id"] = client_code
    session.extras["expires_at"] = _session_end().isoformat()
    return session


# ── Requests ─────────────────────────────────────────────────────────────
def _headers(token: AccessToken) -> Dict[str, str]:
    """The docs' "Header Parameters", mandatory on every call. `accesstoken`
    is empty on the call that fetches it, as in MOFSL's SDK. `installedappid`
    and `imeino` are for DESKTOP / MOBILE and are not sent.
    """
    return {
        "Accept": "application/json",
        "User-Agent": _USER_AGENT,
        "Authorization": token.token,
        "ApiKey": require("BROKER_MOTILAL_API_KEY"),
        "apisecretkey": require("BROKER_MOTILAL_API_SECRET"),
        "accesstoken": str((token.extras or {}).get("access_token") or ""),
        "vendorinfo": require("BROKER_MOTILAL_VENDOR_INFO"),
        "ClientPublicIp": conf("BROKER_MOTILAL_PUBLIC_IP") or "127.0.0.1",
        **_DEVICE_HEADERS,
    }


async def _post(path: str, token: AccessToken, what: str, empty_code: str = "") -> Dict[str, Any]:
    """POST one OpenAPI call and return its JSON envelope.

    Every call made here is documented as a POST, and a client's own read
    needs no request fields (only a dealer names a client). `empty_code` is
    the error code that, for this read, means there is nothing to list; it
    is answered with `{}`.

    A session MOFSL refuses raises `MotilalSessionExpired`. Anything else —
    Nivesh's keys, headers or IP included — raises `MotilalError`, so a
    fault on our side never ends the customer's session. The error and the
    log line carry the HTTP status and MOFSL's error code only.
    """
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{_API}{path}", headers=_headers(token), json={})
    try:
        body = r.json()
    except ValueError:
        body = None
    env = body if isinstance(body, dict) else {}
    if r.status_code < 400 and str(env.get("status") or "").upper() == "SUCCESS":
        return env
    code = str(env.get("errorcode") or "").strip().upper()
    if not _ERROR_CODE.fullmatch(code):
        code = ""  # not shaped like one of MOFSL's codes: none of it is repeated
    if code and code == empty_code:
        return {}
    if code in _SESSION_ERROR_CODES or (not code and r.status_code == 401):
        raise MotilalSessionExpired(
            f"Motilal Oswal rejected the session ({what}, {code or 'HTTP 401'})",
        )
    # The hub logs only the exception class; the code is what tells an
    # operator which key or header MOFSL refused.
    logger.warning("Motilal Oswal %s failed: HTTP %s, errorcode %s", what, r.status_code, code or "none")
    raise MotilalError(
        f"Motilal Oswal {what} failed (HTTP {r.status_code}, errorcode {code or 'none'})",
    )


def _rows(env: Dict[str, Any]) -> List[dict]:
    data = env.get("data")
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def _number(raw: Any) -> Optional[float]:
    """A numeric field that may be absent: None, not 0, when it is."""
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


# ── Holdings ─────────────────────────────────────────────────────────────
async def fetch_holdings(token: AccessToken) -> List[Holding]:
    """DP (demat) holdings. The row has the ISIN, MOFSL's scrip name, the
    total quantity and the average buy price — no last price, exchange or
    trading symbol, so `symbol` is the scrip name as given.
    """
    env = await _post("/rest/report/v3/getdpholding", token, "holdings", _NO_HOLDINGS)
    out: List[Holding] = []
    for h in _rows(env):
        name = str(h.get("scripname") or "").strip()
        isin = str(h.get("scripisinno") or "").strip().upper() or None
        symbol = name.upper() or isin
        if not symbol:
            continue
        out.append(Holding(
            isin=isin,
            symbol=symbol,
            asset_type="etf" if detect_etf(name) else "equity",
            quantity=_number(h.get("dpquantity")) or 0.0,
            avg_price=_number(h.get("buyavgprice")) or 0.0,
            current_price=0.0,  # not in MOFSL's holdings payload
            name=name or None,
            source_id=f"{SLUG}:{isin or symbol}",
        ))
    return out


# ── Positions ────────────────────────────────────────────────────────────
def _iso_date(raw: Any) -> Optional[str]:
    """`expirydate` as an ISO date. The docs write it 29-Aug-2023 (Position
    Detail) and "0" on a cash row; any other shape stays None rather than
    being passed on."""
    try:
        return datetime.strptime(str(raw or "").strip(), "%d-%b-%Y").date().isoformat()
    except ValueError:
        return None


def _hub_position(p: dict, kind: str) -> Optional[HubPosition]:
    """One getposition row as a net or a day row; None when the row has no
    trade of today and the day book is asked for.

    The row carries both books: `day*` is today's trades, `cf*` what was
    carried forward "on actual buy amount", and `buyquantity` /
    `sellquantity` their totals. The average is the bought (or, for a short,
    the sold) amount over its quantity, on actual amounts — the totals'
    own amounts value the carried part at the last close.
    """
    def num(key: str) -> float:
        return _number(p.get(key)) or 0.0

    carried = bool(num("cfbuyquantity") or num("cfsellquantity"))
    if kind == "day":
        bought, sold = num("daybuyquantity"), num("daysellquantity")
        if not (bought or sold):
            return None
        quantity = bought - sold
        buy_amount, sell_amount = num("daybuyamount"), num("daysellamount")
    else:
        bought = num("cfbuyquantity") + num("daybuyquantity")
        sold = num("cfsellquantity") + num("daysellquantity")
        quantity = num("buyquantity") - num("sellquantity")
        buy_amount = num("cfbuyamount") + num("daybuyamount")
        sell_amount = num("cfsellamount") + num("daysellamount")
    if quantity > 0 and bought:
        avg_price = buy_amount / bought
    elif quantity < 0 and sold:
        avg_price = sell_amount / sold
    else:
        avg_price = 0.0
    # P&L on the actual average price. The row has no figure for today's
    # trades alone, so a day row gets one only when nothing was carried.
    pnl = num("actualmarktomarket") + num("actualbookedprofitloss")
    if kind == "day" and carried:
        pnl = 0.0

    raw_exchange = str(p.get("exchange") or "").strip().upper()
    exchange = _EXCHANGES.get(raw_exchange, raw_exchange)
    segment = _SEGMENTS.get(exchange, "equity")
    product_raw = str(p.get("productname") or "").strip() or None
    product = _PRODUCTS.get(product_raw.upper().replace(" ", "")) if product_raw else None
    # `optiontype` is CE / PE on an option and "XX" on the documented cash
    # row. A derivative with an expiry and no option type is a future.
    option = str(p.get("optiontype") or "").strip().upper()
    raw_expiry = str(p.get("expirydate") or "").strip()
    instrument_type = None
    if option in ("CE", "PE"):
        instrument_type = option
    elif segment != "equity" and option in ("", "XX") and raw_expiry not in ("", "0"):
        instrument_type = "FUT"
    strike = _number(p.get("strikeprice")) if instrument_type in ("CE", "PE") else None
    return HubPosition(
        symbol=str(p.get("symbol") or "").strip().upper(),
        exchange=exchange,
        quantity=quantity,
        avg_price=avg_price,
        # None, not 0.0, when the row has no last price: 0 would read as one.
        last_price=_number(p.get("LTP")),
        pnl=pnl,
        product=product,
        product_raw=product_raw,
        segment=segment,
        is_intraday=product == "intraday",
        instrument_type=instrument_type,
        expiry=_iso_date(raw_expiry),
        strike=strike if strike and strike > 0 else None,
        kind=kind,
    )


async def fetch_hub_positions(token: AccessToken, kind: str) -> List[HubPosition]:
    """The net book (carried forward + today) or the day book (today's
    trades), both from the one getposition read."""
    if kind not in ("net", "day"):
        raise ValueError("kind must be 'net' or 'day'")
    env = await _post("/rest/book/v4/getposition", token, "positions", _NO_POSITIONS)
    rows = (_hub_position(p, kind) for p in _rows(env))
    return [row for row in rows if row is not None]


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
    """From the margin summary, a list of numbered lines. MOFSL has no funds
    call (FAQ); the line numbers are the ones in the documented sample.
    """
    env = await _post("/rest/report/v3/getreportmarginsummary", token, "margin summary")
    amount: Dict[int, float] = {}
    for row in _rows(env):
        srno = _number(row.get("srno"))
        if srno is not None:
            amount[int(srno)] = _number(row.get("amount")) or 0.0
    return Funds(
        available_cash=amount.get(102, 0.0),  # Total Available Margin for Cash
        collateral=amount.get(220, 0.0),      # Non cash deposit
        # Margin Usage(B) Cash, FO, Currency, Commodity, Brokerage
        used_margin=sum(amount.get(n, 0.0) for n in (301, 321, 340, 360, 381)),
        pnl_realized=amount.get(700, 0.0),    # Total Profit and Loss(BPL)
        pnl_unrealized=amount.get(600, 0.0),  # Total Profit and Loss(MTM)
    )


class _Module:
    SLUG = SLUG
    DISPLAY = DISPLAY
    AUTH_STYLE = AUTH_STYLE
    CALLBACK_CODE_PARAMS = CALLBACK_CODE_PARAMS
    CALLBACK_PATH_STYLE = CALLBACK_PATH_STYLE
    auth_url = staticmethod(auth_url)
    exchange_code = staticmethod(exchange_code)
    fetch_holdings = staticmethod(fetch_holdings)
    fetch_positions = staticmethod(fetch_positions)
    fetch_hub_positions = staticmethod(fetch_hub_positions)
    fetch_funds = staticmethod(fetch_funds)


registry.register(_Module())
