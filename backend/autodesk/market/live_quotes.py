"""Live quotes for paper fills on the desk's real-time accounts (PHASE2_DESIGN §7). Read only.

Source: the platform feed's Redis cache first (no Kite call, no token in this process), then the read-only REST quote for
what the socket does not carry, above all stock options and next-month futures. `ReadOnlyKite` exposes no order method, so
nothing here can place anything. A failure answers "no quote, because …". Nothing ever falls back to an older price.

Freshness is decided in one place, `check_quote`. Age is measured from `received_at`: the feed's `exchange_ts` is the
container's UTC clock labelled +05:30 (found 4 Nov), so it is not used for age.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timezone
from decimal import Decimal
from typing import Any, Awaitable, Callable, Iterable, Optional, Protocol

from .session_bars import LegRef
from .view import IST

log = logging.getLogger(__name__)

MAX_QUOTE_AGE_S = 120.0        # the same age the existing paper engine accepts
MAX_REST_KEYS = 40             # one bounded REST call per tick
REST_BACKOFF_S = 60.0          # after a refused REST call (no login, Kite down)


@dataclass(frozen=True)
class LiveQuote:
    key: str                              # LegRef.key
    symbol: str                           # exchange symbol, e.g. RELIANCE, RELIANCE26NOVFUT
    ltp: Optional[Decimal]
    bid: Optional[Decimal]
    ask: Optional[Decimal]
    bid_qty: Optional[int]
    ask_qty: Optional[int]
    volume: Optional[int]
    received_at: Optional[datetime]       # when this process's source received it
    last_trade_at: Optional[datetime]     # REST only; the socket's rows carry no reliable stamp
    lot_size: Optional[int]
    source: str                           # "feed-cache" | "kite-rest" | a test's label

    @property
    def ref(self) -> str:
        return f"{self.source}:{self.symbol}@{self.received_at.isoformat() if self.received_at else 'n/a'}"


class QuoteSource(Protocol):
    async def quotes(self, legs: Iterable[LegRef], now: datetime) -> "QuoteAnswer": ...


@dataclass
class QuoteAnswer:
    quotes: dict[str, LiveQuote] = field(default_factory=dict)   # by LegRef.key
    problems: dict[str, str] = field(default_factory=dict)       # key or "*" → why there is no quote


def check_quote(q: Optional[LiveQuote], now: datetime, *, max_age_s: float = MAX_QUOTE_AGE_S) -> Optional[str]:
    """None when this quote may price a fill at `now`; otherwise the reason code. The owner's no-stale-data rule."""
    if q is None:
        return "QUOTE_MISSING"
    if q.ltp is None or q.ltp <= 0:
        return "QUOTE_NO_PRICE"
    if q.received_at is None:
        return "QUOTE_STALE"
    if q.received_at.astimezone(IST).date() != now.astimezone(IST).date():
        return "QUOTE_NOT_TODAY"
    if abs((now - q.received_at).total_seconds()) > max_age_s:
        return "QUOTE_STALE"
    if q.last_trade_at is not None and q.last_trade_at.astimezone(IST).date() != now.astimezone(IST).date():
        return "QUOTE_NOT_TRADED_TODAY"       # Kite answers a price for contracts that have not traded for days
    if not (q.volume or 0) > 0:
        return "QUOTE_NOT_TRADED_TODAY"
    return None


def _dec(v: Any) -> Optional[Decimal]:
    if v is None or v == "":
        return None
    try:
        d = Decimal(str(v))
    except ArithmeticError:
        return None
    return d if d > 0 else None


def _int(v: Any) -> Optional[int]:
    d = _dec(v)
    return int(d) if d is not None else None


def _when(v: Any) -> Optional[datetime]:
    """A stamp from Redis (ISO) or Kite (a naive datetime in IST)."""
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=IST)
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def from_cache_row(key: str, row: dict) -> LiveQuote:
    """A row of services/kite_live_feed/quote_cache. Its `exchange_ts` is not trusted for age (module docstring)."""
    return LiveQuote(key=key, symbol=str(row.get("symbol")), ltp=_dec(row.get("ltp")), bid=_dec(row.get("bid")),
                     ask=_dec(row.get("ask")), bid_qty=_int(row.get("bid_qty")), ask_qty=_int(row.get("ask_qty")),
                     volume=_int(row.get("volume")), received_at=_when(row.get("received_at")), last_trade_at=None,
                     lot_size=_int(row.get("lot_size")), source="feed-cache")


def from_rest_row(key: str, symbol: str, row: dict, now: datetime, lot_size: Optional[int]) -> LiveQuote:
    """A row of Kite's quote(): best bid and ask from its depth, `received_at` = the moment of this read."""
    depth = row.get("depth") if isinstance(row.get("depth"), dict) else {}
    top = lambda side: (depth.get(side) or [{}])[0] if isinstance(depth.get(side), list) else {}   # noqa: E731
    return LiveQuote(key=key, symbol=symbol, ltp=_dec(row.get("last_price")), bid=_dec(top("buy").get("price")),
                     ask=_dec(top("sell").get("price")), bid_qty=_int(top("buy").get("quantity")),
                     ask_qty=_int(top("sell").get("quantity")), volume=_int(row.get("volume")), received_at=now,
                     last_trade_at=_when(row.get("last_trade_time")), lot_size=lot_size, source="kite-rest")


class KiteQuoteSource:
    """Redis first, then the read-only REST quote (PHASE2_DESIGN §7). `read_cache` and `kite_factory` are injectable: the
    tests pass fakes. Nothing here writes."""

    def __init__(self, *, read_cache: Optional[Callable[[list[str]], Awaitable[Optional[dict]]]] = None,
                 kite_factory: Optional[Callable[[], Awaitable[Any]]] = None, clock=time.monotonic):
        self._read_cache = read_cache or _feed_cache_read
        self._kite_factory = kite_factory or _platform_kite
        self._clock = clock
        self._nfo: dict[tuple, dict] = {}
        self._nfo_day: Optional[date] = None
        self._rest_down_until = 0.0
        self._rest_reason = ""

    async def _contracts(self, kite: Any, now: datetime) -> dict[tuple, dict]:
        """Kite's NFO instrument list keyed by contract, read once per IST day. A symbol is never assembled by hand: weekly
        and monthly option symbols follow different patterns."""
        today = now.astimezone(IST).date()
        if self._nfo_day != today or not self._nfo:
            rows = await asyncio.to_thread(kite.instruments, "NFO")
            out: dict[tuple, dict] = {}
            for r in rows or []:
                if not isinstance(r, dict) or str(r.get("instrument_type") or "").upper() not in ("FUT", "CE", "PE"):
                    continue
                kind = str(r["instrument_type"]).upper()
                strike = None if kind == "FUT" else Decimal(str(r.get("strike"))).normalize()
                out[(str(r.get("name") or "").upper(), str(r.get("expiry"))[:10], strike, kind)] = r
            self._nfo, self._nfo_day = out, today
        return self._nfo

    async def quotes(self, legs: Iterable[LegRef], now: datetime) -> QuoteAnswer:
        legs = list({lg.key: lg for lg in legs}.values())
        ans = QuoteAnswer()
        if not legs:
            return ans
        kite: Any = None
        contract_of: dict[str, dict] = {}
        fno = [lg for lg in legs if lg.kind != "EQ"]
        if fno:      # the contract's exchange symbol comes from Kite's own list, which needs the day's login
            kite = await self._kite_or_none(ans)
            if kite is not None:
                try:
                    contracts = await self._contracts(kite, now)
                except Exception as e:  # noqa: BLE001 — reported as a reason; no price is guessed
                    self._down(ans, f"the contract list could not be read ({type(e).__name__})")
                    contracts = {}
                for lg in fno:
                    strike = None if lg.kind == "FUT" else Decimal(str(lg.strike)).normalize()
                    r = contracts.get((lg.underlying.upper(), str(lg.expiry), strike, lg.kind))
                    if r:
                        contract_of[lg.key] = r
                    elif contracts:
                        ans.problems[lg.key] = "no listed contract"
        symbol = {lg.key: (lg.underlying if lg.kind == "EQ" else contract_of.get(lg.key, {}).get("tradingsymbol"))
                  for lg in legs}
        wanted = [s for s in symbol.values() if s]
        cached = await self._read_cache(wanted) if wanted else {}
        if cached is None:
            ans.problems.setdefault("*cache", "the feed's quote cache is not available")
            cached = {}
        missing: list[LegRef] = []
        for lg in legs:
            sym = symbol.get(lg.key)
            row = cached.get(sym) if sym else None
            q = from_cache_row(lg.key, row) if row else None
            if q is not None and check_quote(q, now) is None:
                ans.quotes[lg.key] = q
            else:
                if q is not None:
                    ans.quotes[lg.key] = q     # kept so check_quote can name the reason if REST cannot do better
                missing.append(lg)
        if missing:
            await self._rest(missing, symbol, contract_of, kite, now, ans)
        return ans

    def _down(self, ans: QuoteAnswer, reason: str) -> None:
        self._rest_down_until = self._clock() + REST_BACKOFF_S
        self._rest_reason = reason
        ans.problems["*"] = reason

    async def _kite_or_none(self, ans: QuoteAnswer) -> Any:
        if self._clock() < self._rest_down_until:
            ans.problems["*"] = self._rest_reason
            return None
        try:
            return await self._kite_factory()
        except Exception as e:  # noqa: BLE001
            self._down(ans, f"no Kite session ({e if isinstance(e, NoKiteSession) else type(e).__name__})")
            return None

    async def _rest(self, missing: list[LegRef], symbol: dict, contract_of: dict, kite: Any, now: datetime,
                    ans: QuoteAnswer) -> None:
        kite = kite or await self._kite_or_none(ans)
        if kite is None:
            return
        keys: dict[str, LegRef] = {}
        for lg in missing[:MAX_REST_KEYS]:
            sym = symbol.get(lg.key)
            if sym:
                keys[f"{'NSE' if lg.kind == 'EQ' else 'NFO'}:{sym}"] = lg
        if not keys:
            return
        try:
            answer = await asyncio.to_thread(kite.quote, sorted(keys))
        except Exception as e:  # noqa: BLE001 — a token or network error is a reason, never a price
            self._down(ans, f"the quote request failed ({type(e).__name__})")
            return
        for k, lg in keys.items():
            row = (answer or {}).get(k)
            if isinstance(row, dict):
                lot = contract_of.get(lg.key, {}).get("lot_size")
                ans.quotes[lg.key] = from_rest_row(lg.key, k.split(":", 1)[1], row, now, _int(lot))


class NoKiteSession(RuntimeError):
    pass


async def _feed_cache_read(symbols: list[str]) -> Optional[dict]:
    from services.kite_live_feed import quote_cache
    return await quote_cache.read_quotes(symbols)


async def _platform_kite() -> Any:
    """The read-only client on the platform's daily login. A process that is not the feed's leader refreshes the token from
    Mongo first (else it holds yesterday's). Reads only; the login itself is an admin's, once a day."""
    from deps import db
    from services.kite_live_feed import config as feed_cfg
    from services.kite_live_feed import gateway, platform_token
    await platform_token.refresh_cache(db)
    key, token = feed_cfg.get_api_key(), feed_cfg.get_token()
    if not key or not token:
        raise NoKiteSession("the day's Kite login is not valid")
    return gateway.default_kite_factory(key, token)


def session_open(d: date) -> datetime:
    return datetime.combine(d, dtime(9, 15), tzinfo=IST).astimezone(timezone.utc)


def in_fill_window(kind: str, now: datetime) -> bool:
    """Whether an order of this kind can be priced now. F&O stocks' continuous cash trading ends at 15:15 since 3 Aug 2026
    (closing auction session), so a share order stops there; contracts go on to the desk's 15:30 close."""
    t = now.astimezone(IST).time()
    return dtime(9, 15) <= t < (dtime(15, 15) if kind == "EQ" else dtime(15, 30))


def age_seconds(at: Optional[datetime], now: datetime) -> Optional[float]:
    return None if at is None else (now - at).total_seconds()

