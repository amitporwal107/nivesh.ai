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


@dataclass
class HubPosition:
    """Broker-hub position shape (one row of a net or day position book).

    Richer than `Position`: carries the normalised product, the segment and
    the derivative contract details the hub screens need. Produced by
    `fenix_reader.read_positions` and by `hub_reads` for adapter reads. A
    field the broker does not give is left at its default (or None) — never
    filled with a guess.
    """
    symbol: str                      # broker trading symbol, upper-case
    exchange: str                    # NSE | BSE | NFO | BFO | MCX | CDS ...
    quantity: float                  # signed net quantity (negative = short)
    avg_price: float
    last_price: Optional[float] = None  # None when the broker sends no price
    pnl: float = 0.0
    product: Optional[str] = None      # normalised: "intraday" | "delivery" | "carryforward" | "margin"; None if unknown
    product_raw: Optional[str] = None  # the broker's own code (MIS, CNC, NRML, ...)
    segment: str = "equity"            # "equity" | "fno" | "commodity" | "currency"
    is_intraday: bool = False
    instrument_type: Optional[str] = None  # "FUT" | "CE" | "PE"; None for cash
    expiry: Optional[str] = None       # ISO date, when the broker gives it
    strike: Optional[float] = None
    kind: str = "net"                  # "net" | "day"
    name: Optional[str] = None         # broker's instrument / company name, when given


@dataclass(frozen=True)
class ContractRef:
    """One futures or options contract, in the terms a `HubPosition` row
    carries it: the row's own `symbol` and `exchange`, plus its contract
    details."""
    symbol: str                      # as the broker's position row gives it
    exchange: str                    # NFO | BFO | MCX | CDS ...
    instrument_type: str             # "FUT" | "CE" | "PE"
    expiry: str                      # ISO date
    strike: Optional[float] = None   # None for a future


@dataclass
class Candle:
    """One bar of a contract's own price. `time` is the bar's start as an ISO
    timestamp with the exchange's UTC offset."""
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None
    open_interest: Optional[float] = None


@dataclass
class ContractQuote:
    """The latest quote of a contract. Every field is None when the broker
    did not send it — never a guess."""
    last_price: Optional[float] = None
    last_traded_at: Optional[str] = None   # ISO timestamp with offset
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    previous_close: Optional[float] = None
    change_pct: Optional[float] = None
    spot_price: Optional[float] = None     # the underlying's price, when given
    volume: Optional[float] = None


@dataclass
class ContractChart:
    """A contract's price history (oldest bar first) and its latest quote.
    Returned by an adapter's optional `fetch_contract_chart(token, contract,
    interval)`; `interval` is one of `hub_reads.CHART_INTERVALS`."""
    candles: List[Candle] = field(default_factory=list)
    quote: Optional[ContractQuote] = None
