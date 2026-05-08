"""Zerodha (Kite Connect) native broker adapter.

Uses Zerodha's official `kiteconnect` Python SDK. Read-only flow only —
we never call `place_order` / `modify_order` / `cancel_order`.

Auth model (Kite Connect v3):
  1. User clicks Connect Zerodha → browser redirected to
     `https://kite.trade/connect/login?api_key=<APP_KEY>&v=3`.
  2. Zerodha → user logs in → redirects back to Nivesh's callback with
     a `request_token` query param.
  3. Nivesh exchanges `(api_key, request_token, api_secret)` → SHA-256
     checksum → POST `/session/token` → receives an `access_token`.
  4. Access token is stored encrypted; expires at ~3 AM IST daily, so
     re-auth is needed each trading day (Kite's fixed policy).

App credentials (`BROKER_ZERODHA_API_KEY`, `BROKER_ZERODHA_API_SECRET`)
are admin secrets registered once with Zerodha's Kite Connect partner
portal — NOT per-user.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from .base import AccessToken, Broker, Funds, Holding, Position
from . import registry

logger = logging.getLogger(__name__)

SLUG = "zerodha"
DISPLAY = "Zerodha"
AUTH_STYLE = "oauth"


# ── App credentials ──────────────────────────────────────────────────────
def _conf(key: str) -> str:
    """Read a Nivesh secret with env fallback. Empty when unset."""
    try:
        from helpers import secrets as _s
        v = (_s.get(key) or "").strip()
        if v:
            return v
    except Exception:  # noqa: BLE001
        pass
    return (os.environ.get(key) or "").strip()


def _api_key() -> str:
    return _conf("BROKER_ZERODHA_API_KEY")


def _api_secret() -> str:
    return _conf("BROKER_ZERODHA_API_SECRET")


def _kite(access_token: str = ""):
    """Build a `kiteconnect.KiteConnect` client. Imported lazily so the
    backend boots even before kiteconnect is installed."""
    try:
        from kiteconnect import KiteConnect
    except ImportError as e:  # noqa: BLE001
        raise RuntimeError(
            "kiteconnect SDK not installed. Add `kiteconnect` to backend/requirements.txt.",
        ) from e
    api_key = _api_key()
    if not api_key:
        raise RuntimeError(
            "BROKER_ZERODHA_API_KEY is not configured — operator must register a Kite Connect app.",
        )
    kc = KiteConnect(api_key=api_key)
    if access_token:
        kc.set_access_token(access_token)
    return kc


# ── Protocol implementation ──────────────────────────────────────────────
def auth_url(*, state: str, redirect_uri: str) -> str:
    """Kite Connect's login URL embeds the app's API key. The redirect
    URI was registered with Zerodha at app-creation time and isn't
    parameterised here — Zerodha redirects to whatever's on file plus
    appends `?request_token=...&action=login&status=success`. We pass
    `state` via Kite's `redirect_params` mechanism so we can correlate
    the callback with the originating Nivesh session.

    `redirect_uri` is currently ignored at Zerodha's side (their app
    config controls it), but kept in the signature for protocol parity
    with OAuth-style brokers.
    """
    kc = _kite()
    return f"{kc.login_url()}&redirect_params=state%3D{state}"


async def exchange_code(*, code: str, state: str, redirect_uri: str) -> AccessToken:
    """Kite calls our callback with `request_token=<code>`. We exchange
    it for an `access_token` via `generate_session(request_token, api_secret)`.
    Returns an `AccessToken` whose `extras` holds Kite's `user_id` (used
    by some endpoints) and the issuance timestamp.
    """
    api_secret = _api_secret()
    if not api_secret:
        raise RuntimeError("BROKER_ZERODHA_API_SECRET missing")
    kc = _kite()
    # `generate_session` is sync — Kite's SDK isn't async. Run on
    # the default executor so we don't block the event loop.
    import asyncio
    data = await asyncio.get_event_loop().run_in_executor(
        None, lambda: kc.generate_session(code, api_secret),
    )
    token = data.get("access_token") or ""
    if not token:
        raise RuntimeError(f"Kite generate_session returned no access_token: {data!r}")
    return AccessToken(
        token=token,
        extras={
            "user_id": data.get("user_id"),
            "user_shortname": data.get("user_shortname"),
            "user_type": data.get("user_type"),
            "broker": data.get("broker"),
            "login_time": data.get("login_time"),
        },
    )


async def fetch_holdings(token: AccessToken) -> List[Holding]:
    """Kite's `/portfolio/holdings` returns a list of dicts — already in
    a clean, well-documented shape. Map to Nivesh's canonical `Holding`.
    """
    kc = _kite(token.token)
    import asyncio
    raw: List[Dict[str, Any]] = await asyncio.get_event_loop().run_in_executor(
        None, kc.holdings,
    )
    out: List[Holding] = []
    for h in raw or []:
        sym = (h.get("tradingsymbol") or "").strip().upper()
        if not sym:
            continue
        # Kite's `instrument_token` is internal; we prefer ISIN if present.
        isin = (h.get("isin") or "").strip().upper() or None
        ex = (h.get("exchange") or "").strip().upper() or None
        # ETFs have product=CNC + tradingsymbol containing "BEES"/"ETF" —
        # use a name-based override.
        name = sym  # Kite holdings don't include a long name field
        is_etf = any(tag in sym for tag in ("BEES", "ETF", "GOLDM"))
        out.append(Holding(
            isin=isin,
            symbol=sym,
            asset_type="etf" if is_etf else "equity",
            quantity=float(h.get("quantity") or 0),
            avg_price=float(h.get("average_price") or 0),
            current_price=float(h.get("last_price") or 0),
            name=name,
            sector=None,
            exchange=ex,
            source_id=f"{ex}:{sym}" if ex else sym,
        ))
    return out


async def fetch_positions(token: AccessToken) -> List[Position]:
    kc = _kite(token.token)
    import asyncio
    raw: Dict[str, Any] = await asyncio.get_event_loop().run_in_executor(
        None, kc.positions,
    )
    nets = (raw or {}).get("net") or []
    out: List[Position] = []
    for p in nets:
        out.append(Position(
            symbol=str(p.get("tradingsymbol") or "").upper(),
            exchange=str(p.get("exchange") or "").upper(),
            quantity=float(p.get("quantity") or 0),
            avg_price=float(p.get("average_price") or 0),
            pnl=float(p.get("pnl") or 0),
            product=str(p.get("product") or "") or None,
        ))
    return out


async def fetch_funds(token: AccessToken) -> Funds:
    kc = _kite(token.token)
    import asyncio
    raw: Dict[str, Any] = await asyncio.get_event_loop().run_in_executor(
        None, kc.margins,
    )
    eq = (raw or {}).get("equity") or {}
    avail = eq.get("available") or {}
    util = eq.get("utilised") or {}
    return Funds(
        available_cash=float(eq.get("net") or 0),
        collateral=float(avail.get("collateral") or 0),
        used_margin=float(util.get("debits") or 0),
        pnl_realized=float(util.get("m2m_realised") or 0),
        pnl_unrealized=float(util.get("m2m_unrealised") or 0),
    )


# ── Self-registration ────────────────────────────────────────────────────
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
