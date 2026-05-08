"""Broker adapter protocol.

Every Nivesh-supported broker implements this. The runtime selects
adapters by slug via `registry.get(slug)`; routes call the protocol
methods without caring whether the underlying impl is an official SDK
or a vendored OpenAlgo plugin.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Protocol


AuthStyle = Literal["oauth", "apikey", "form"]


@dataclass
class AccessToken:
    """Opaque per-user, per-broker session token + sidecar metadata.

    `token` is the value the broker's API requires on each authenticated
    request. `extras` carries broker-specific bits (refresh tokens, user
    IDs, expiry timestamps) that the adapter alone interprets — Nivesh
    persists the whole struct encrypted and never inspects `extras`.
    """
    token: str
    extras: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Holding:
    """Canonical Nivesh holding shape — matches what `helpers.parsing.
    save_holdings` writes into the `holdings` collection.
    """
    isin: Optional[str]
    symbol: str
    asset_type: str  # equity | etf | mutual_fund | bond | gold | fd | other
    quantity: float
    avg_price: float
    current_price: float
    name: Optional[str] = None
    sector: Optional[str] = None
    exchange: Optional[str] = None
    source_id: Optional[str] = None  # e.g. f"{exchange}:{symbol}"


@dataclass
class Position:
    symbol: str
    exchange: str
    quantity: float
    avg_price: float
    pnl: float = 0.0
    product: Optional[str] = None


@dataclass
class Funds:
    available_cash: float = 0.0
    collateral: float = 0.0
    used_margin: float = 0.0
    pnl_realized: float = 0.0
    pnl_unrealized: float = 0.0


class Broker(Protocol):
    """Static adapter contract.

    Adapters are typically modules with module-level constants
    (`SLUG`, `DISPLAY`, `AUTH_STYLE`) and async free functions matching
    this protocol. Use `registry.get(slug)` to fetch one.
    """

    SLUG: str
    DISPLAY: str
    AUTH_STYLE: AuthStyle

    def auth_url(self, *, state: str, redirect_uri: str) -> str:
        """Return the URL the browser should be redirected to so the user
        can authenticate at the broker. For OAuth-style brokers this is
        an external URL on the broker's domain. For API-key / form-style
        brokers, this returns Nivesh's own credential-capture form URL.
        """
        ...

    async def exchange_code(
        self, *, code: str, state: str, redirect_uri: str,
    ) -> AccessToken:
        """Exchange the OAuth code (or form-submitted credentials) for a
        per-user access token. Called from Nivesh's `/oauth-callback`.
        """
        ...

    async def fetch_holdings(self, token: AccessToken) -> List[Holding]:
        """Read-only holdings fetch. Should be idempotent."""
        ...

    async def fetch_positions(self, token: AccessToken) -> List[Position]:
        ...

    async def fetch_funds(self, token: AccessToken) -> Funds:
        ...
