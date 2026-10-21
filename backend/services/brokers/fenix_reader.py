"""Fenix-backed holdings / positions reader for the broker hub.

Fenix (https://github.com/TheHardeep/fenix, GPL-3.0, pinned `fenix==2.0.2`)
is used here ONLY as the reader. The user has already signed in on the
broker's own page and Nivesh holds the resulting session (`AccessToken`).
This module hands that session to a fresh Fenix broker object with
`use_headers()` and calls three read methods:

    fetch_holdings()   fetch_net_positions()   fetch_day_positions()

Guarantees
----------
  * Read-only. Nothing here calls, wraps or exposes a Fenix method that
    sends or changes anything at the broker, and Fenix's own sign-in flow
    is never run: no password, PIN or TOTP ever reaches Fenix.
  * One Fenix object per call, built and used on a worker thread, never
    shared between users, discarded when the call returns.
  * `fenix` is imported on first use, so the backend boots without it. Then
    `supports()` is all False and the reads raise `BrokerNotSupported`.
  * Exception text and log lines carry the broker slug, the operation, the
    error class, the HTTP status and the broker's short error code. Never a
    token, an app secret, a client id, a URL or a response body.

Public API
----------
    supports(slug)                      -> {"holdings": bool, "positions": bool}
    await read_holdings(slug, token)    -> list[Holding]
    await read_positions(slug, token, kind="net" | "day") -> list[HubPosition]

`kind="day"` is served only where Fenix reads a day book that is separate
from the net book: Zerodha and AliceBlue. For every other Fenix class
`fetch_day_positions()` returns the net snapshot again, so a day read raises
`BrokerNotSupported` instead of handing back net rows labelled "day".
`supports()["positions"]` is about the net book.

    BrokerReadError          the read failed
    BrokerSessionExpired     the broker rejected the stored session
    BrokerNotSupported       no Fenix reader for this slug or read / fenix missing

Built-in header builders: zerodha, upstox, fyers, aliceblue, dhan.

Adapter hook (for brokers whose adapter lives elsewhere, e.g. Angel One, Groww)
-------------------------------------------------------------------------------
A broker gets a Fenix reader without any change to this file when the adapter
returned by `registry.get(slug)` defines:

    FENIX_CLASS = "AngelOne"            # str: the class name inside `fenix`

    def fenix_headers(token: AccessToken) -> dict[str, str]:
        '''The header dict Fenix's own sign-in would have produced.'''

    def fenix_auth_params(token: AccessToken) -> dict:    # optional
        '''Non-header context, passed as `auth_params` to `use_headers()`.'''

Rules for the hook:
  * `fenix_headers` must return every key in the Fenix class's
    `_REQUIRED_AUTH_HEADER_KEYS`. Every key in `_AUTH_CONTEXT_KEYS` must be
    in the headers or in `fenix_auth_params`. Keys and values must be `str`.
    A missing key is reported by name as a `BrokerReadError` before any
    request is made.
  * To report a problem in your own words (a secret that is not configured,
    a stored session with a field missing) raise `BrokerReadError` or a
    subclass; it is passed through unchanged. Any other exception is
    reported by its class name only, so its text cannot leak anything.
  * A built-in builder wins when a slug has both.
  * `supports(slug)` is true for a read only when fenix imports, the class
    exists in fenix as a broker class, and the class has the read method.
  * Day positions follow the rule above: AngelOne and Groww have no separate
    day book in Fenix, so `kind="day"` is refused for them.
  * Rows are mapped by the same code as the built-ins: Fenix's unified keys
    first, then the broker's own row (Fenix's `info`) for what Fenix leaves
    out. Check the result against your broker's payload before relying on it.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from ._helpers import conf, detect_etf, require_sdk, to_thread
from .base import AccessToken, Holding, HubPosition

logger = logging.getLogger(__name__)

__all__ = [
    "BrokerNotSupported",
    "BrokerReadError",
    "BrokerSessionExpired",
    "read_holdings",
    "read_positions",
    "supports",
]


# ── Errors ───────────────────────────────────────────────────────────────
class BrokerReadError(RuntimeError):
    """The read failed."""


class BrokerSessionExpired(BrokerReadError):
    """The broker rejected the stored session; the user must reconnect."""


class BrokerNotSupported(BrokerReadError):
    """No Fenix reader for this slug (or for this read), or fenix is not installed."""


# ── Fenix loading ────────────────────────────────────────────────────────
_INSTALL_HINT = "Add `fenix==2.0.2` to backend/requirements.txt."

# Fenix logs every request and response body at DEBUG on the logger it is
# given. It gets this one, pinned above DEBUG, so a DEBUG root logger can
# never put holdings or request headers into Nivesh's logs.
_FENIX_LOGGER = logging.getLogger(__name__ + ".fenix")
_FENIX_LOGGER.setLevel(logging.WARNING)

_FENIX_CONFIG: Dict[str, Any] = {
    "logger": _FENIX_LOGGER,
    "verbose": False,
    "logSensitive": False,
    "paper_mode": False,
}

_HOLDINGS_METHOD = "fetch_holdings"
_POSITION_METHODS = {"net": "fetch_net_positions", "day": "fetch_day_positions"}

# Fenix classes whose day read is a different book from the net read, checked
# against the fenix 2.0.2 source: Zerodha maps Kite's own `day` list and
# AliceBlue asks the broker for its DAY book. Every other class audited
# (Upstox, Fyers, Dhan, AngelOne, Groww) returns the net snapshot from
# `fetch_day_positions()`; net rows are never handed back labelled "day".
_DAY_BOOK_CLASSES = frozenset({"Zerodha", "AliceBlue"})


def _load_fenix() -> Any:
    """The `fenix` module, imported on first use. None when it cannot be
    imported (not installed, or one of its own imports is missing)."""
    try:
        return require_sdk("fenix", _INSTALL_HINT)
    except Exception as exc:  # noqa: BLE001 - any import failure means "no reader"
        logger.debug("fenix is not importable (%s)", type(exc).__name__)
        return None


def _fenix_class(fx: Any, name: str) -> Optional[type]:
    """`fenix.<name>` when it is a concrete Fenix broker class, else None."""
    base = getattr(fx, "Broker", None)
    cls = getattr(fx, name, None)
    if not isinstance(base, type) or not isinstance(cls, type):
        return None
    if cls is base or not issubclass(cls, base):
        return None
    return cls


# ── Built-in header builders ─────────────────────────────────────────────
# Each returns the dict Fenix's own sign-in builds at the end of
# `authenticate()` for that broker, made from what Nivesh stores.
def _stored(value: Any, what: str, slug: str) -> str:
    """A stored session field as text, or a clean error naming the field."""
    text = str(value).strip() if value is not None else ""
    if not text:
        raise BrokerReadError(f"{slug}: the stored session has no {what}; reconnect the account")
    return text


def _app_key(name: str, slug: str) -> str:
    """One of Nivesh's own app keys, or a clean error naming the secret."""
    value = conf(name)
    if not value:
        raise BrokerReadError(f"{slug}: {name} is not configured")
    return value


def _zerodha_headers(token: AccessToken) -> Dict[str, str]:
    api_key = _app_key("BROKER_ZERODHA_API_KEY", "zerodha")
    access = _stored(token.token, "access token", "zerodha")
    return {
        "X-Kite-Version": "3",
        "User-Agent": "Kiteconnect-python/4.2.0",
        "Authorization": f"token {api_key}:{access}",
        # Fenix requires these three keys too. Kite ignores them; `user_id`
        # is the one Kite returned at sign-in (empty when it was not stored).
        "user_id": str((token.extras or {}).get("user_id") or ""),
        "api_key": api_key,
        "access_token": access,
    }


def _upstox_headers(token: AccessToken) -> Dict[str, str]:
    access = _stored(token.token, "access token", "upstox")
    return {
        "Authorization": f"Bearer {access}",
        "Accept": "application/json",
    }


def _fyers_headers(token: AccessToken) -> Dict[str, str]:
    api_key = _app_key("BROKER_FYERS_API_KEY", "fyers")
    access = _stored(token.token, "access token", "fyers")
    return {"Authorization": f"{api_key}:{access}"}


def _aliceblue_headers(token: AccessToken) -> Dict[str, str]:
    user_id = _stored((token.extras or {}).get("user_id"), "user id", "aliceblue")
    session = _stored(token.token, "session id", "aliceblue")
    inner = hashlib.sha256(session.encode("utf-8")).hexdigest()
    return {
        "ID": user_id,
        "AccessToken": session,
        "Authorization": f"Bearer {user_id} {session}",
        "X-SAS-Version": "2.0",
        "User-Agent": "AliceBlue_V21.0.1",
        "Content-Type": "application/json",
        "susertoken": hashlib.sha256(inner.encode("utf-8")).hexdigest(),
    }


def _dhan_headers(token: AccessToken) -> Dict[str, str]:
    client_id = _stored((token.extras or {}).get("client_id"), "client id", "dhan")
    access = _stored(token.token, "access token", "dhan")
    return {
        "access-token": access,
        "Accept": "application/json",
        # Auth context, not a request header: Fenix keeps it off the wire.
        "user_id": client_id,
    }


@dataclass(frozen=True)
class _Reader:
    fenix_class: str
    headers: Callable[[AccessToken], Mapping[str, str]]
    auth_params: Optional[Callable[[AccessToken], Mapping[str, Any]]] = None


_BUILTIN: Dict[str, _Reader] = {
    "zerodha": _Reader("Zerodha", _zerodha_headers),
    "upstox": _Reader("Upstox", _upstox_headers),
    "fyers": _Reader("Fyers", _fyers_headers),
    "aliceblue": _Reader("AliceBlue", _aliceblue_headers),
    "dhan": _Reader("Dhan", _dhan_headers),
}


def _adapter_reader(slug: str) -> Optional[_Reader]:
    """The adapter hook: `FENIX_CLASS` + `fenix_headers` on the registered
    adapter (see the module docstring)."""
    try:
        from . import registry  # imported here: adapters must stay free to import this module
        adapter = registry.get(slug)
    except Exception:  # noqa: BLE001 - unknown slug, or the registry is unavailable
        return None
    class_name = getattr(adapter, "FENIX_CLASS", None)
    headers = getattr(adapter, "fenix_headers", None)
    if not isinstance(class_name, str) or not class_name.strip() or not callable(headers):
        return None
    auth_params = getattr(adapter, "fenix_auth_params", None)
    return _Reader(class_name.strip(), headers, auth_params if callable(auth_params) else None)


def _slug(slug: Any) -> str:
    return str(slug or "").strip().lower()


def _resolve(slug: str) -> Optional[_Reader]:
    return _BUILTIN.get(slug) or _adapter_reader(slug)


# ── Public: capability ───────────────────────────────────────────────────
def supports(slug: str) -> Dict[str, bool]:
    """Which reads Fenix can serve for `slug`.

    Both False when the slug has no reader, fenix is not importable, or the
    Fenix class is missing. "positions" is the net book; see the module
    docstring for the day book. The first call imports fenix (a few seconds
    when cold); call it from a worker thread if that matters.
    """
    nothing = {"holdings": False, "positions": False}
    reader = _resolve(_slug(slug))
    if reader is None:
        return nothing
    fx = _load_fenix()
    if fx is None:
        return nothing
    cls = _fenix_class(fx, reader.fenix_class)
    if cls is None:
        return nothing
    return {
        "holdings": callable(getattr(cls, _HOLDINGS_METHOD, None)),
        "positions": all(callable(getattr(cls, m, None)) for m in _POSITION_METHODS.values()),
    }


# ── Session → Fenix call ─────────────────────────────────────────────────
def _require(slug: str, method: str) -> Tuple[_Reader, type]:
    """The reader and Fenix class for a read, or `BrokerNotSupported`."""
    reader = _resolve(slug)
    if reader is None:
        raise BrokerNotSupported(f"no Fenix reader for broker {slug[:40]!r}")
    fx = _load_fenix()
    if fx is None:
        raise BrokerNotSupported(f"fenix is not installed. {_INSTALL_HINT}")
    cls = _fenix_class(fx, reader.fenix_class)
    if cls is None or not callable(getattr(cls, method, None)):
        raise BrokerNotSupported(f"{slug}: Fenix has no {method} for this broker")
    return reader, cls


def _session_material(
    slug: str, reader: _Reader, cls: type, token: AccessToken,
) -> Tuple[Dict[str, str], Dict[str, Any]]:
    """Header dict + auth context for `use_headers()`, validated against what
    the Fenix class requires. Raises `BrokerReadError` naming what is missing."""
    failure: Optional[BrokerReadError] = None
    headers: Any = None
    auth_params: Any = None
    try:
        headers = reader.headers(token)
        auth_params = reader.auth_params(token) if reader.auth_params else {}
    except BrokerReadError:
        raise
    except Exception as exc:  # noqa: BLE001 - reported by class name only
        failure = BrokerReadError(
            f"{slug}: could not build the broker session headers ({type(exc).__name__})",
        )
    if failure is not None:
        raise failure

    if not isinstance(headers, Mapping) or not headers:
        raise BrokerReadError(f"{slug}: the header builder returned no headers")
    if auth_params is None:
        auth_params = {}
    if not isinstance(auth_params, Mapping):
        raise BrokerReadError(f"{slug}: fenix_auth_params must return a dict")

    not_text = sorted(
        str(k)[:40] for k, v in headers.items()
        if not isinstance(k, str) or not isinstance(v, str)
    )
    if not_text:
        raise BrokerReadError(
            f"{slug}: session header names and values must be strings (check: {', '.join(not_text)})",
        )

    required = tuple(getattr(cls, "_REQUIRED_AUTH_HEADER_KEYS", ()) or ())
    context = tuple(getattr(cls, "_AUTH_CONTEXT_KEYS", ()) or ())
    missing = [k for k in required if k not in headers]
    missing += [k for k in context if k not in headers and k not in auth_params]
    if missing:
        raise BrokerReadError(
            f"{slug}: the stored session cannot supply what Fenix {cls.__name__} "
            f"requires (missing: {', '.join(missing)})",
        )
    return dict(headers), dict(auth_params)


_SAFE_CODE = re.compile(r"^[A-Za-z0-9_.\-]{1,24}$")


def _safe_code(code: Any, secrets: Iterable[str]) -> Optional[str]:
    """The broker's short error code, only when it is plainly a code and
    shares no text with any session value."""
    if code is None or isinstance(code, bool):
        return None
    text = str(code).strip()
    if not _SAFE_CODE.match(text):
        return None
    for secret in secrets:
        if len(secret) >= 4 and (secret in text or text in secret):
            return None
    return text


def _translate(slug: str, method: str, exc: BaseException, secrets: Iterable[str]) -> BrokerReadError:
    """A Fenix (or any) failure as one of this module's errors. The text is
    built from the error class, HTTP status and short broker code only; the
    original exception is deliberately not chained, because Fenix errors hold
    the response object and, through it, the request headers."""
    kind = type(exc).__name__
    status = getattr(exc, "status_code", None)
    if isinstance(status, bool) or not isinstance(status, int):
        status = None
    parts = [kind]
    if status is not None:
        parts.append(f"HTTP {status}")
    code = _safe_code(getattr(exc, "error_code", None), secrets)
    if code:
        parts.append(f"broker code {code}")
    detail = ", ".join(parts)

    fx = _load_fenix()
    auth_error = getattr(getattr(fx, "errors", None), "AuthenticationError", None)
    rejected = (isinstance(auth_error, type) and isinstance(exc, auth_error)) or status == 401
    if rejected:
        logger.warning("fenix_reader: %s %s: broker rejected the stored session (%s)", slug, method, detail)
        return BrokerSessionExpired(f"{slug}: the broker rejected the stored session ({detail})")
    logger.warning("fenix_reader: %s %s failed (%s)", slug, method, detail)
    return BrokerReadError(f"{slug}: {method} failed ({detail})")


def _close(broker: Any) -> None:
    """Release the HTTP connections of a finished Fenix object."""
    session = getattr(broker, "_session", None)
    close = getattr(session, "close", None)
    if callable(close):
        try:
            close()
        except Exception as exc:  # noqa: BLE001 - nothing to recover; the object is discarded
            logger.debug("fenix_reader: closing the HTTP session failed (%s)", type(exc).__name__)


def _read_sync(
    slug: str, cls: type, headers: Dict[str, str], auth_params: Dict[str, Any], method: str,
) -> Any:
    """Build a fresh Fenix object, restore the session, run one read.
    Synchronous (Fenix uses `requests`): always called on a worker thread."""
    secrets = [v for v in headers.values() if isinstance(v, str)]
    secrets += [v for v in auth_params.values() if isinstance(v, str)]
    broker: Any = None
    result: Any = None
    failure: Optional[BrokerReadError] = None
    try:
        broker = cls(dict(_FENIX_CONFIG))
        if auth_params:
            broker.use_headers(headers, auth_params=auth_params)
        else:
            broker.use_headers(headers)
        result = getattr(broker, method)()
    except Exception as exc:  # noqa: BLE001 - every failure becomes a BrokerReadError
        failure = _translate(slug, method, exc, secrets)
    finally:
        _close(broker)
    if failure is not None:
        raise failure
    return result


async def _read(slug: Any, token: AccessToken, method: str) -> Tuple[str, Any]:
    key = _slug(slug)
    # Resolving imports fenix on first use, so it runs off the event loop too.
    reader, cls = await to_thread(_require, key, method)
    headers, auth_params = _session_material(key, reader, cls, token)
    return key, await to_thread(_read_sync, key, cls, headers, auth_params, method)


# ── Record mapping ───────────────────────────────────────────────────────
# Fenix's unified record keys (fenix.base.constants.Position). Fenix 2.0.2
# does not unify every read: several methods hand back the broker's own rows
# (or its whole response). Each lookup below therefore tries the unified key
# first and then the broker's own key names, in the listed order. For a
# unified record the broker's row is its `info` value.
_INFO = "info"

_EXCHANGES = frozenset({"NSE", "BSE", "NFO", "BFO", "MCX", "CDS", "BCD", "NCO", "BCO", "NCDEX"})
_FNO = frozenset({"NFO", "BFO"})
_COMMODITY = frozenset({"MCX", "NCO", "BCO", "NCDEX"})
_CURRENCY = frozenset({"CDS", "BCD"})

# Exchange spellings Fenix passes through untranslated.
_EXCHANGE_CODES: Dict[str, str] = {
    # Dhan `exchangeSegment`
    "NSE_EQ": "NSE", "BSE_EQ": "BSE", "NSE_FNO": "NFO", "BSE_FNO": "BFO",
    "NSE_CURRENCY": "CDS", "BSE_CURRENCY": "BCD", "MCX_COMM": "MCX",
    # Fyers `exchange` + `segment` (exchange 10 NSE, 11 MCX, 12 BSE; segment
    # 10 cash, 11 equity derivatives, 12 currency, 20 commodity)
    "1010": "NSE", "1011": "NFO", "1012": "CDS", "1020": "NCO",
    "1210": "BSE", "1211": "BFO", "1212": "BCD", "1220": "BCO",
    "1120": "MCX",
}
_RAW_EXCHANGE_KEYS = ("exchange", "Exchange", "exchangeSegment")

_SYMBOL_KEYS = ("symbol", "tradingsymbol", "trading_symbol", "tradingSymbol", "Tsym")
# AliceBlue (legacy ANT) holdings name the symbol per venue.
_VENUE_SYMBOL_KEYS: Dict[str, str] = {"Nsetsym": "NSE", "Bsetsym": "BSE"}
_NOT_A_SYMBOL = ("", "0", "NA", "--")

_NAME_KEYS = ("company_name", "companyname", "symbolname")
_ISIN_KEYS = ("isin", "ISIN", "Isin")

_POSITION_QTY_KEYS = ("netQty", "quantity", "netqty", "Netqty")
_POSITION_AVG_KEYS = ("avgPrice", "average_price", "netAvg", "netprice")
# AliceBlue (legacy ANT) gives one average per side.
_LONG_AVG_KEYS = ("NetBuyavgprc", "Buyavgprc")
_SHORT_AVG_KEYS = ("NetSellavgprc", "Sellavgprc")
_LTP_KEYS = ("ltp", "last_price", "lastTradedPrice", "LTP")
_PNL_KEYS = ("pnl", "pl")
_REALISED_KEYS = ("realised", "realizedProfit", "realized_profit", "realisedprofitloss")
_UNREALISED_KEYS = ("unrealised", "unrealizedProfit", "unrealized_profit", "unrealisedprofitloss")
_RAW_PRODUCT_KEYS = ("product", "productType", "producttype", "Pcode")
_OPTION_TYPE_KEYS = ("optiontype", "Opttype", "drvOptionType")
_INSTRUMENT_KEYS = ("instrumenttype", "Instname")
_EXPIRY_KEYS = ("expirydate", "Expdate", "drvExpiryDate")
_STRIKE_KEYS = ("strikeprice", "Stikeprc", "drvStrikePrice")

_HOLDING_QTY_KEYS = ("netQty", "quantity", "totalQty")
# AliceBlue (legacy ANT) holdings split the quantity over several fields.
_ALICE_QTY_KEYS = ("Holdqty", "HUqty", "SellableQty")
_HOLDING_AVG_KEYS = ("avgPrice", "average_price", "averageprice", "costPrice", "avgCostPrice", "Price")
_HOLDING_LTP_KEYS = _LTP_KEYS + ("LTnse", "LTbse")
# Where a broker wraps its holdings rows when Fenix returns the whole response.
_HOLDING_CONTAINERS = ("holdings", "HoldingVal", "data")

# Broker product code → hub product. "D" (Upstox delivery) and "LONGTERM"
# (AliceBlue) are delivery for cash equity and carry-forward for derivatives.
_PRODUCT_KINDS: Dict[str, str] = {
    "MIS": "intraday", "INTRADAY": "intraday", "I": "intraday",
    "CO": "intraday", "BO": "intraday", "OCO": "intraday",
    "CNC": "delivery", "DELIVERY": "delivery",
    "NRML": "carryforward", "CARRYFORWARD": "carryforward",
    "MARGIN": "margin", "MTF": "margin",
}
_DELIVERY_OR_CARRY = frozenset({"D", "LONGTERM"})

_EXPIRY_FORMATS = ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d%b%Y", "%d-%b-%Y", "%d %b %Y")


def _num(value: Any) -> Optional[float]:
    """A finite float from a broker value ("1,234.50" included), else None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).replace(",", "").strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    return number if math.isfinite(number) else None


def _first(row: Mapping[str, Any], keys: Iterable[str]) -> Any:
    """The first value under `keys` that is neither None nor ""."""
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            return value
    return None


def _views(record: Mapping[str, Any]) -> Tuple[Mapping[str, Any], Mapping[str, Any]]:
    """(record, broker row). The broker row is `info` for a unified record and
    the record itself when Fenix returned the broker's row untouched."""
    info = record.get(_INFO)
    if isinstance(info, Mapping) and info:
        return record, info
    return record, record


def _pick(record: Mapping[str, Any], raw: Mapping[str, Any], keys: Iterable[str]) -> Any:
    keys = tuple(keys)
    value = _first(record, keys)
    if value is None and raw is not record:
        value = _first(raw, keys)
    return value


def _symbol(record: Mapping[str, Any], raw: Mapping[str, Any]) -> Tuple[str, Optional[str]]:
    """(symbol in upper case, venue it implies). The venue comes from a
    Fyers-style "NSE:SBIN-EQ" prefix or an AliceBlue per-venue symbol field."""
    value = _pick(record, raw, _SYMBOL_KEYS)
    venue: Optional[str] = None
    if value is None:
        for key, implied in _VENUE_SYMBOL_KEYS.items():
            candidate = str(raw.get(key) or "").strip()
            if candidate.upper() not in _NOT_A_SYMBOL:
                value, venue = candidate, implied
                break
    text = str(value or "").strip().upper()
    if text in _NOT_A_SYMBOL:
        return "", None
    if ":" in text:
        prefix, rest = text.split(":", 1)
        if prefix in _EXCHANGES and rest:
            return rest, prefix
    return text, venue


def _exchange(
    record: Mapping[str, Any], raw: Mapping[str, Any], venue: Optional[str],
) -> Tuple[Optional[str], str]:
    """(recognised exchange code or None, the broker's own text)."""
    value = _first(record, ("exchange",))
    if value is None:
        value = _first(raw, _RAW_EXCHANGE_KEYS)
    text = str(value).strip().upper() if value is not None else ""
    if len(text) == 2 and text.isdigit():
        segment = str(raw.get("segment") or "").strip()
        if segment.isdigit():
            text = text + segment
    code = _EXCHANGE_CODES.get(text, text)
    if code in _EXCHANGES:
        return code, text
    return (venue if venue in _EXCHANGES else None), text


def _segment(exchange: Optional[str]) -> str:
    if exchange in _FNO:
        return "fno"
    if exchange in _COMMODITY:
        return "commodity"
    if exchange in _CURRENCY:
        return "currency"
    return "equity"


def _product(
    record: Mapping[str, Any], raw: Mapping[str, Any], segment: str,
) -> Tuple[Optional[str], Optional[str]]:
    """(hub product or None, the broker's own code or None)."""
    broker_code = _first(raw, _RAW_PRODUCT_KEYS)
    fenix_code = record.get("product")
    shown = broker_code if broker_code is not None else fenix_code
    product_raw = (str(shown).strip() or None) if shown is not None else None
    for candidate in (broker_code, fenix_code):
        if candidate is None:
            continue
        key = str(candidate).strip().upper()
        if key in _DELIVERY_OR_CARRY:
            return ("delivery" if segment == "equity" else "carryforward"), product_raw
        if key in _PRODUCT_KINDS:
            return _PRODUCT_KINDS[key], product_raw
    return None, product_raw


def _instrument_type(symbol: str, segment: str, raw: Mapping[str, Any]) -> Optional[str]:
    """"CE" | "PE" | "FUT" for a derivative, from the broker's own field when
    it sends one, else from the trading-symbol suffix. None for cash."""
    if segment == "equity":
        return None
    option = str(_first(raw, _OPTION_TYPE_KEYS) or "").strip().upper()
    if option in ("CE", "CALL"):
        return "CE"
    if option in ("PE", "PUT"):
        return "PE"
    if str(_first(raw, _INSTRUMENT_KEYS) or "").strip().upper().startswith("FUT"):
        return "FUT"
    for suffix in ("CE", "PE", "FUT"):
        if symbol.endswith(suffix):
            return suffix
    return None


def _expiry(raw: Mapping[str, Any]) -> Optional[str]:
    """ISO expiry date when the broker's row carries a parseable one."""
    value = _first(raw, _EXPIRY_KEYS)
    if value is None:
        return None
    text = str(value).strip()
    for fmt in _EXPIRY_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        # Brokers send placeholders such as 0001-01-01 for "no expiry".
        return parsed.date().isoformat() if parsed.year >= 2000 else None
    return None


def _pnl(record: Mapping[str, Any], raw: Mapping[str, Any]) -> float:
    """Total P&L. Realised + unrealised when Fenix gives both, else the
    broker's total, else the broker's realised + unrealised, else 0."""
    realised = _num(record.get("realisedPnl"))
    unrealised = _num(record.get("unrealisedPnl"))
    if realised is not None and unrealised is not None:
        return realised + unrealised
    total = _num(_pick(record, raw, _PNL_KEYS))
    if total is not None:
        return total
    realised = _num(_first(raw, _REALISED_KEYS))
    unrealised = _num(_first(raw, _UNREALISED_KEYS))
    if realised is not None and unrealised is not None:
        return realised + unrealised
    return 0.0


def _to_position(record: Any, kind: str) -> Optional[HubPosition]:
    """One Fenix position record as a `HubPosition`; None when the record has
    no symbol or no quantity (it is then counted as unrecognised)."""
    if not isinstance(record, Mapping):
        return None
    record, raw = _views(record)
    symbol, venue = _symbol(record, raw)
    quantity = _num(_pick(record, raw, _POSITION_QTY_KEYS))
    if not symbol or quantity is None:
        return None

    known, text = _exchange(record, raw, venue)
    segment = _segment(known)
    product, product_raw = _product(record, raw, segment)

    avg_price = _num(_pick(record, raw, _POSITION_AVG_KEYS))
    if avg_price is None:
        avg_price = _num(_first(raw, _LONG_AVG_KEYS if quantity >= 0 else _SHORT_AVG_KEYS))

    derivative = segment != "equity"
    strike = _num(_first(raw, _STRIKE_KEYS)) if derivative else None
    name = _first(raw, _NAME_KEYS)
    return HubPosition(
        symbol=symbol,
        exchange=known or text,
        quantity=quantity,
        avg_price=avg_price if avg_price is not None else 0.0,
        # None, not 0.0, when the broker sends no last price: 0 would read as a price.
        last_price=_num(_pick(record, raw, _LTP_KEYS)),  # type: ignore[arg-type]
        pnl=_pnl(record, raw),
        product=product,
        product_raw=product_raw,
        segment=segment,
        is_intraday=product == "intraday",
        instrument_type=_instrument_type(symbol, segment, raw),
        expiry=_expiry(raw) if derivative else None,
        strike=strike if strike is not None and strike > 0 else None,
        kind=kind,
        name=(str(name).strip() or None) if name is not None else None,
    )


def _holding_quantity(record: Mapping[str, Any], raw: Mapping[str, Any]) -> Optional[float]:
    quantity = _num(_pick(record, raw, _HOLDING_QTY_KEYS))
    if quantity is not None:
        return quantity
    # AliceBlue (legacy ANT): the first of its quantity fields that is not zero.
    values = [_num(raw.get(key)) for key in _ALICE_QTY_KEYS if key in raw]
    values = [v for v in values if v is not None]
    if not values:
        return None
    return next((v for v in values if v != 0), 0.0)


def _to_holding(record: Any) -> Optional[Holding]:
    """One Fenix holdings record as a `Holding`; None when the record has no
    symbol or no quantity (it is then counted as unrecognised)."""
    if not isinstance(record, Mapping):
        return None
    record, raw = _views(record)
    broker_symbol, venue = _symbol(record, raw)
    quantity = _holding_quantity(record, raw)
    if not broker_symbol or quantity is None:
        return None

    exchange, _ = _exchange(record, raw, venue)
    # `symbol` is the bare ticker (cash series suffix dropped, as the Fyers
    # adapter does); `source_id` keeps the broker's own symbol.
    ticker = broker_symbol[:-3] if broker_symbol.endswith("-EQ") else broker_symbol
    company = _first(raw, _NAME_KEYS)
    company = str(company).strip() if company is not None else ""
    isin = _first(raw, _ISIN_KEYS)
    isin = str(isin).strip().upper() if isin is not None else ""
    avg_price = _num(_pick(record, raw, _HOLDING_AVG_KEYS))
    current_price = _num(_pick(record, raw, _HOLDING_LTP_KEYS))
    return Holding(
        isin=isin or None,
        symbol=ticker,
        asset_type="etf" if detect_etf(ticker, company) else "equity",
        quantity=quantity,
        avg_price=avg_price if avg_price is not None else 0.0,
        current_price=current_price if current_price is not None else 0.0,
        # The broker's company name when it sends one, else the ticker, as
        # the existing adapters do.
        name=company or ticker,
        sector=None,
        exchange=exchange,
        source_id=f"{exchange}:{broker_symbol}" if exchange else broker_symbol,
    )


def _holding_rows(slug: str, result: Any) -> List[Any]:
    """The holdings rows inside whatever `fetch_holdings()` returned."""
    if result is None:
        return []
    if isinstance(result, (list, tuple)):
        return list(result)
    if isinstance(result, Mapping):
        for key in _HOLDING_CONTAINERS:
            value = result.get(key)
            if isinstance(value, (list, tuple)):
                return list(value)
            if isinstance(value, Mapping) and isinstance(value.get("holdings"), (list, tuple)):
                return list(value["holdings"])
    raise BrokerReadError(f"{slug}: holdings came back in a shape that is not recognised")


def _position_rows(slug: str, result: Any) -> List[Any]:
    if result is None:
        return []
    if isinstance(result, (list, tuple)):
        return list(result)
    raise BrokerReadError(f"{slug}: positions came back in a shape that is not recognised")


def _map_rows(slug: str, what: str, rows: List[Any], mapper: Callable[[Any], Any]) -> List[Any]:
    """Map every row. Rows without a symbol or quantity are skipped and
    counted; if none of the rows could be mapped the read fails, because an
    empty list would say "nothing held" when the truth is "not understood"."""
    mapped = [item for item in (mapper(row) for row in rows) if item is not None]
    skipped = len(rows) - len(mapped)
    if skipped and not mapped:
        raise BrokerReadError(
            f"{slug}: none of the {len(rows)} {what} rows was in a recognised shape",
        )
    if skipped:
        logger.warning(
            "fenix_reader: %s %s: skipped %d of %d rows with no symbol or quantity",
            slug, what, skipped, len(rows),
        )
    return mapped


# ── Public: reads ────────────────────────────────────────────────────────
async def read_holdings(slug: str, token: AccessToken) -> List[Holding]:
    """Live holdings for one stored broker session."""
    key, result = await _read(slug, token, _HOLDINGS_METHOD)
    return _map_rows(key, "holdings", _holding_rows(key, result), _to_holding)


async def read_positions(slug: str, token: AccessToken, kind: str = "net") -> List[HubPosition]:
    """Live positions for one stored broker session. `kind` is "net" (carried
    forward + today) or "day" (the broker's day book, where Fenix reads one)."""
    if kind not in _POSITION_METHODS:
        raise ValueError("kind must be 'net' or 'day'")
    reader = _resolve(_slug(slug))
    if kind == "day" and reader is not None and reader.fenix_class not in _DAY_BOOK_CLASSES:
        raise BrokerNotSupported(
            f"{_slug(slug)}: Fenix has no separate day book for this broker "
            "(its day read returns the net positions)",
        )
    key, result = await _read(slug, token, _POSITION_METHODS[kind])
    return _map_rows(
        key, f"{kind} positions", _position_rows(key, result),
        lambda row: _to_position(row, kind),
    )
