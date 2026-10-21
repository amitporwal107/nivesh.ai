"""Groww native broker adapter (Groww Trading API v1, raw HTTP).

Read-only: holdings, positions, margin. Nothing here places, modifies or
cancels an order.

Groww's Trading API documents no redirect / OAuth sign-in. A Bearer access
token comes from one of three places:
  1. Access Token — the user generates it on Groww (Profile → Settings →
     Trading APIs → Generate API keys → Access Token). "Expires daily at
     6:00 AM".
  2. API key + secret → POST /v1/token/api/access, after a daily approval
     on Groww.
  3. TOTP token + TOTP secret → the same endpoint.
(2) and (3) would leave Nivesh holding a long-lived credential that can
mint trading tokens, so only (1) is taken: the user pastes the day's token.
We surface this as `auth_style="apikey"`, the way Dhan is, and check the
token with one profile read before accepting it.

No operator configuration: Nivesh registers no app with Groww and reads no
BROKER_GROWW_* secret — the user brings the token, and needs an active
Trading API plan on Groww for it to work.

Left empty because the API does not return it: a holding's last price,
exchange and name; a position's last price, unrealised P&L, expiry and
strike. There is one positions snapshot (the net book) and no day book.

Reads go straight to Groww's REST API and not through Fenix, although Fenix
has a Groww class: Fenix sends headers that present the caller as Groww's own
Python SDK, and its day-positions call returns the net book.

Docs: https://groww.in/trade-api/docs/curl (auth, headers, errors, rate
limits) and its /portfolio, /margin, /user and /annexures pages.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import httpx

from . import registry
from ._helpers import detect_etf
from .base import AccessToken, Funds, Holding, HubPosition, Position

SLUG = "groww"
DISPLAY = "Groww"
AUTH_STYLE = "apikey"

_API = "https://api.groww.in/v1"

# "Expires daily at 6:00 AM" — the page names no timezone; read as IST, as
# `sessions._DAILY_EXPIRY_IST` does for the other Indian brokers.
_IST = timezone(timedelta(hours=5, minutes=30))

# Annexure "Product" lists CNC, MIS and NRML; MTF is kept in step with
# `hub_reads._PRODUCT_CODES`. A code that is not listed stays None.
_PRODUCTS = {"CNC": "delivery", "MIS": "intraday", "NRML": "carryforward", "MTF": "margin"}
# Only CASH and FNO are served by the API today.
_SEGMENTS = {"CASH": "equity", "FNO": "fno", "COMMODITY": "commodity", "CURRENCY": "currency"}
# Groww says NSE / BSE for derivatives too; the hub's codes split them out.
_FNO_EXCHANGES = {"NSE": "NFO", "BSE": "BFO"}


class GrowwError(RuntimeError):
    """Groww answered without `status: SUCCESS`. Carries its error code only."""


class GrowwTokenRejected(RuntimeError):
    """Sign-in: Groww refused the pasted access token."""


class GrowwDayPositionsNotSupported(NotImplementedError):
    """Groww has one positions snapshot (net); there is no day book to read."""


def auth_url(*, state: str, redirect_uri: str) -> str:
    return f"/broker-credentials/groww?state={state}"


def _pasted_token(code: str) -> str:
    """The token out of `code`: bare, or a JSON blob `{access_token}` from
    the form. Errors never echo what was pasted."""
    raw = (code or "").strip()
    if raw.startswith("{"):
        try:
            creds = json.loads(raw)
        except ValueError:
            raise RuntimeError("Groww: malformed credentials body") from None
        raw = str(creds.get("access_token") or "").strip()
    return raw.removeprefix("Bearer ").strip()


def _next_expiry(now: Optional[datetime] = None) -> datetime:
    """The next 06:00 IST after `now`, in UTC."""
    local = (now or datetime.now(timezone.utc)).astimezone(_IST)
    ends = local.replace(hour=6, minute=0, second=0, microsecond=0)
    if ends <= local:
        ends += timedelta(days=1)
    return ends.astimezone(timezone.utc)


async def exchange_code(*, code: str, state: str, redirect_uri: str) -> AccessToken:
    """`code` is the access token the user generated on Groww. One profile
    read (GET /user/detail) proves Groww accepts it before it is stored,
    and gives the client code that recognises a reconnect of the same login.
    """
    tok = _pasted_token(code)
    if not tok:
        raise RuntimeError("Groww: access_token required")
    try:
        profile = await _get("/user/detail", tok)
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        if status in (401, 403):
            raise GrowwTokenRejected(
                f"Groww did not accept the access token (HTTP {status}). Tokens expire "
                "daily at 6:00 AM — generate a new one on Groww and check that the "
                "Trading API plan is active.",
            ) from None
        raise
    extras = {"expires_at": _next_expiry().isoformat()}
    user_id = str(profile.get("ucc") or profile.get("vendor_user_id") or "").strip()
    if user_id:
        extras["user_id"] = user_id
    return AccessToken(token=tok, extras=extras)


async def _get(path: str, token: str) -> dict:
    """GET one resource and return its `payload`. A token Groww refuses
    surfaces as `httpx.HTTPStatusError` (401/403) from `raise_for_status()`.
    """
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            f"{_API}{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "X-API-VERSION": "1.0",
            },
        )
    r.raise_for_status()
    body = r.json()
    if not isinstance(body, dict) or body.get("status") != "SUCCESS":
        # A body that is not a success must never read as "no holdings".
        err = body.get("error") if isinstance(body, dict) else None
        code = err.get("code") if isinstance(err, dict) else None
        raise GrowwError(f"Groww API did not return SUCCESS (code={code})")
    return body.get("payload") or {}


async def fetch_holdings(token: AccessToken) -> List[Holding]:
    payload = await _get("/holdings/user", token.token)
    out: List[Holding] = []
    for h in payload.get("holdings") or []:
        sym = (h.get("trading_symbol") or "").upper()
        if not sym:
            continue
        out.append(Holding(
            isin=(h.get("isin") or "").upper() or None,
            symbol=sym,
            asset_type="etf" if detect_etf(sym) else "equity",
            quantity=float(h.get("quantity") or 0),
            avg_price=float(h.get("average_price") or 0),
            current_price=0.0,  # not in Groww's holdings payload
            name=sym,
            source_id=sym,
        ))
    return out


async def _position_rows(token: AccessToken) -> List[dict]:
    # No `segment` filter: one call returns CASH and FNO rows together.
    payload = await _get("/positions/user", token.token)
    return payload.get("positions") or []


def _exchange(row: dict) -> str:
    ex = (row.get("exchange") or "").upper()
    if (row.get("segment") or "").upper() == "FNO":
        return _FNO_EXCHANGES.get(ex, ex)
    return ex


def _instrument_type(symbol: str) -> Optional[str]:
    """FUT / CE / PE read off an F&O trading symbol's suffix, as in Groww's
    instrument master (BANKNIFTY25DEC27000PE, ASIANPAINT25FEBFUT). The
    positions row has no instrument-type, expiry or strike field.
    """
    for suffix in ("FUT", "CE", "PE"):
        if symbol.endswith(suffix):
            return suffix
    return None


async def fetch_positions(token: AccessToken) -> List[Position]:
    out: List[Position] = []
    for p in await _position_rows(token):
        out.append(Position(
            symbol=(p.get("trading_symbol") or "").upper(),
            exchange=_exchange(p),
            quantity=float(p.get("quantity") or 0),
            avg_price=float(p.get("net_price") or 0),
            pnl=float(p.get("realised_pnl") or 0),
            product=p.get("product"),
        ))
    return out


async def fetch_hub_positions(token: AccessToken, kind: str) -> List[HubPosition]:
    """The net book in the hub's shape. `pnl` is Groww's `realised_pnl` —
    the only P&L it returns. `kind="day"` raises: the payload's credit /
    debit legs are not documented as today's trades, so no day book is
    derived from them.
    """
    if kind == "day":
        raise GrowwDayPositionsNotSupported("Groww has no day-positions read")
    if kind != "net":
        raise ValueError("kind must be 'net' or 'day'")
    out: List[HubPosition] = []
    for p in await _position_rows(token):
        sym = (p.get("trading_symbol") or "").upper()
        raw = str(p.get("product") or "").strip() or None
        seg = (p.get("segment") or "").upper()
        out.append(HubPosition(
            symbol=sym,
            exchange=_exchange(p),
            quantity=float(p.get("quantity") or 0),
            avg_price=float(p.get("net_price") or 0),
            # None, not 0.0: Groww sends no last price and 0 would read as one.
            last_price=None,  # type: ignore[arg-type]
            pnl=float(p.get("realised_pnl") or 0),
            product=_PRODUCTS.get(raw.upper()) if raw else None,
            product_raw=raw,
            segment=_SEGMENTS.get(seg, "equity"),
            is_intraday=bool(raw) and raw.upper() == "MIS",
            instrument_type=_instrument_type(sym) if seg == "FNO" else None,
            expiry=None,
            strike=None,
            kind=kind,
            name=None,
        ))
    return out


async def fetch_funds(token: AccessToken) -> Funds:
    m = await _get("/margins/detail/user", token.token)
    return Funds(
        available_cash=float(m.get("clear_cash") or 0),
        collateral=float(m.get("collateral_available") or 0),
        used_margin=float(m.get("net_margin_used") or 0),
    )


class _Module:
    SLUG = SLUG
    DISPLAY = DISPLAY
    AUTH_STYLE = AUTH_STYLE
    auth_url = staticmethod(auth_url)
    exchange_code = staticmethod(exchange_code)
    fetch_holdings = staticmethod(fetch_holdings)
    fetch_positions = staticmethod(fetch_positions)
    fetch_hub_positions = staticmethod(fetch_hub_positions)
    fetch_funds = staticmethod(fetch_funds)


registry.register(_Module())
