"""The point-in-time market view every agent reads through (PRD §28.4, architecture §10.5).

A view is bound to an instant `as_of` (UTC). It only shows data that had been PUBLISHED by then:
- cash end-of-day bars for session d become visible at d 19:30 IST (CASH_EOD_PUBLISHED_IST)
- F&O end-of-day rows for session d become visible at d 22:45 IST (FNO_EOD_PUBLISHED_IST)
The two times sit after the real loads on the data platform (cash bhavcopy about 19:00 IST, F&O bhavcopy about 22:15 IST,
nidp.v_feed_status, 4 Nov 2026) with a safety margin, so a desk cycle never reads a day that has not landed.
Asking for a later session raises LookAheadError. This is the replay's no-future-data guarantee, and the same rule
applies to the live desk (as_of = now).

Every read is recorded as a ToolCall so an agent task's evidence shows exactly which data it used.

Implementations:
- autodesk.market.pit.PitMarketView — reads the NIDP warehouse through the data API (services.copilot_tools.daas_client)
- FrozenMarketView (below) — in-memory data; unit tests and, later, scenario overrides. It is NOT real market data:
  anything built on it must say so.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from ..contracts import ToolCall

IST = ZoneInfo("Asia/Kolkata")
CASH_EOD_PUBLISHED_IST = dtime(19, 30)
FNO_EOD_PUBLISHED_IST = dtime(22, 45)


class LookAheadError(RuntimeError):
    """A read asked for data that was not published at the view's as_of."""


class DataUnavailable(RuntimeError):
    """The data source has no data for the request (or could not be reached)."""


class ToolNotAllowed(PermissionError):
    """An agent called a market tool outside its allowlist."""


def ist(dt: datetime) -> datetime:
    return dt.astimezone(IST)


def published_at(day: date, kind: str) -> datetime:
    """UTC instant at which session `day`'s end-of-day data of `kind` ('cash'|'fno') is treated as published."""
    t = CASH_EOD_PUBLISHED_IST if kind == "cash" else FNO_EOD_PUBLISHED_IST
    return datetime.combine(day, t, tzinfo=IST).astimezone(timezone.utc)


@dataclass(frozen=True)
class Bar:
    day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    turnover_rs: Optional[Decimal] = None
    deliv_pct: Optional[Decimal] = None
    adj_factor: Decimal = Decimal("1")   # as-of adjustment applied (1 = none)


@dataclass(frozen=True)
class FnoContract:
    day: date
    underlying: str
    kind: str                     # "FUT" | "CE" | "PE"
    expiry: date
    strike: Optional[Decimal]
    close: Optional[Decimal]
    settle: Optional[Decimal]
    underlying_price: Optional[Decimal]
    open_interest: Optional[int]
    change_in_oi: Optional[int]
    traded_volume: Optional[int]
    lot_size: Optional[int]
    traded_value_rs: Optional[Decimal] = None   # as published by the exchange file (see pit.py for the unit check)


@dataclass(frozen=True)
class BuildupRow:
    day: date
    underlying: str
    label: str                    # long_buildup | short_buildup | short_covering | long_unwinding | neutral
    price_change_pct: Optional[Decimal]
    oi_change_pct: Optional[Decimal]
    fut_close: Optional[Decimal]
    open_interest: Optional[int]
    extra: dict = field(default_factory=dict)


@runtime_checkable
class MarketView(Protocol):
    as_of: datetime

    def latest_session(self, kind: str = "cash") -> date: ...
    async def previous_session(self, day: date) -> date: ...
    async def sessions_between(self, start: date, end: date) -> list[date]: ...
    async def daily_bars(self, symbol: str, *, sessions: int) -> list[Bar]: ...
    async def day_snapshot(self, day: date) -> dict[str, Bar]: ...
    async def index_bars(self, name: str, *, sessions: int) -> list[Bar]: ...
    async def fno_universe(self, day: Optional[date] = None) -> list[str]: ...
    async def fno_buildup(self, day: Optional[date] = None) -> list[BuildupRow]: ...
    async def futures(self, underlying: str, day: Optional[date] = None) -> list[FnoContract]: ...
    async def options(self, underlying: str, expiry: date, day: Optional[date] = None) -> list[FnoContract]: ...
    async def expiries(self, underlying: str, day: Optional[date] = None) -> list[date]: ...
    async def lot_size(self, underlying: str, day: Optional[date] = None) -> Optional[int]: ...
    async def vix(self, day: Optional[date] = None) -> Optional[Decimal]: ...
    async def sector(self, symbol: str) -> Optional[str]: ...
    def tool_calls(self) -> list[ToolCall]: ...


def chain_snapshot(rows: list[FnoContract], *, spot: Optional[Decimal], require_traded: bool = True) -> dict[str, Any]:
    """Shape option rows for services.strategy_plan.templates (the chain dict they expect). A strike side whose
    contract did not trade that session gets close=None: the bhavcopy carries the previous close forward for untraded
    contracts, and a template refuses a missing premium rather than guessing one."""
    by_strike: dict[Decimal, dict[str, Any]] = {}
    day: Optional[date] = None
    for r in rows:
        if r.kind not in ("CE", "PE") or r.strike is None:
            continue
        day = day or r.day
        side = "call" if r.kind == "CE" else "put"
        traded = (r.traded_volume or 0) > 0
        close = r.close if (traded or not require_traded) else None
        by_strike.setdefault(r.strike, {"strike": float(r.strike), "call": None, "put": None})[side] = {
            "close": float(close) if close is not None and close > 0 else None,
            "oi": r.open_interest, "volume": r.traded_volume}
    return {"as_of": day.isoformat() if day else None,
            "strikes": [by_strike[k] for k in sorted(by_strike)],
            "spot": float(spot) if spot is not None else None,
            "source": f"NSE F&O bhavcopy close, {day.isoformat() if day else 'n/a'}",
            "spot_source": f"NSE F&O bhavcopy underlying price, {day.isoformat() if day else 'n/a'}"}


class RecordingMixin:
    """Shared call recording for view implementations."""

    def _init_recording(self) -> None:
        self._calls: list[ToolCall] = []

    def _record(self, tool: str, args: dict, *, t0: float, rows: Optional[int] = None, ok: bool = True,
                error: Optional[str] = None) -> None:
        self._calls.append(ToolCall(tool=tool, args={k: (v.isoformat() if isinstance(v, (date, datetime)) else v)
                                                     for k, v in args.items()},
                                    as_of=self.as_of, ok=ok, rows=rows, error=error,
                                    ms=int((time.monotonic() - t0) * 1000)))

    def tool_calls(self) -> list[ToolCall]:
        return list(self._calls)


class RestrictedView:
    """Wraps a MarketView and allows only the listed methods (agent tool permissions, PRD §29.5)."""

    def __init__(self, inner: MarketView, allowed: set[str], agent: str):
        self._inner, self._allowed, self._agent = inner, set(allowed), agent

    @property
    def as_of(self) -> datetime:
        return self._inner.as_of

    def tool_calls(self) -> list[ToolCall]:
        return self._inner.tool_calls()

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in self._allowed:
            raise ToolNotAllowed(f"{self._agent} may not use market.{name}")
        return getattr(self._inner, name)


class FrozenMarketView(RecordingMixin):
    """In-memory MarketView over fixed data. FOR TESTS / SCENARIOS — not real market data.

    data keys: "bars" {symbol: [Bar]}, "index" {name: [Bar]}, "fno" {underlying: [FnoContract]},
    "buildup" {day: [BuildupRow]}, "vix" {day: Decimal}, "sector" {symbol: str}, "sessions": [date]
    Session days come from data["sessions"] (sorted); the publication rule is the same as the real view.
    """

    def __init__(self, as_of: datetime, data: dict[str, Any]):
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        self.as_of = as_of.astimezone(timezone.utc)
        self._d = data
        self._sessions: list[date] = sorted(data.get("sessions") or [])
        self._init_recording()

    def latest_session(self, kind: str = "cash") -> date:
        vis = [d for d in self._sessions if published_at(d, kind) <= self.as_of]
        if not vis:
            raise DataUnavailable(f"no {kind} session published by {self.as_of.isoformat()}")
        return vis[-1]

    def _guard(self, day: Optional[date], kind: str) -> date:
        latest = self.latest_session(kind)
        if day is None:
            return latest
        if day > latest:
            raise LookAheadError(f"{kind} data for {day} is not published at {self.as_of.isoformat()}")
        return day

    async def previous_session(self, day: date) -> date:
        t0 = time.monotonic()
        prior = [d for d in self._sessions if d < day]
        if not prior:
            self._record("previous_session", {"day": day}, t0=t0, rows=0, ok=False, error="no earlier session")
            raise DataUnavailable(f"no session before {day} in the session list")
        self._record("previous_session", {"day": day}, t0=t0, rows=1)
        return prior[-1]

    async def sessions_between(self, start: date, end: date) -> list[date]:
        t0 = time.monotonic()
        out = [d for d in self._sessions if start <= d <= end]
        self._record("sessions_between", {"start": start, "end": end}, t0=t0, rows=len(out))
        return out

    async def daily_bars(self, symbol: str, *, sessions: int) -> list[Bar]:
        t0 = time.monotonic()
        latest = self.latest_session("cash")
        bars = [b for b in self._d.get("bars", {}).get(symbol, []) if b.day <= latest][-sessions:]
        self._record("daily_bars", {"symbol": symbol, "sessions": sessions}, t0=t0, rows=len(bars))
        return bars

    async def day_snapshot(self, day: date) -> dict[str, Bar]:
        t0 = time.monotonic()
        day = self._guard(day, "cash")
        out = {s: b for s, bars in self._d.get("bars", {}).items() for b in bars if b.day == day}
        self._record("day_snapshot", {"day": day}, t0=t0, rows=len(out))
        return out

    async def index_bars(self, name: str, *, sessions: int) -> list[Bar]:
        t0 = time.monotonic()
        latest = self.latest_session("cash")
        bars = [b for b in self._d.get("index", {}).get(name, []) if b.day <= latest][-sessions:]
        self._record("index_bars", {"name": name, "sessions": sessions}, t0=t0, rows=len(bars))
        return bars

    async def fno_universe(self, day: Optional[date] = None) -> list[str]:
        t0 = time.monotonic()
        day = self._guard(day, "fno")
        out = sorted({r.underlying for rows in self._d.get("fno", {}).values() for r in rows
                      if r.day == day and r.kind == "FUT"})
        self._record("fno_universe", {"day": day}, t0=t0, rows=len(out))
        return out

    async def fno_buildup(self, day: Optional[date] = None) -> list[BuildupRow]:
        t0 = time.monotonic()
        day = self._guard(day, "fno")
        out = list(self._d.get("buildup", {}).get(day, []))
        self._record("fno_buildup", {"day": day}, t0=t0, rows=len(out))
        return out

    async def futures(self, underlying: str, day: Optional[date] = None) -> list[FnoContract]:
        t0 = time.monotonic()
        day = self._guard(day, "fno")
        out = [r for r in self._d.get("fno", {}).get(underlying, []) if r.day == day and r.kind == "FUT"]
        self._record("futures", {"underlying": underlying, "day": day}, t0=t0, rows=len(out))
        return sorted(out, key=lambda r: r.expiry)

    async def options(self, underlying: str, expiry: date, day: Optional[date] = None) -> list[FnoContract]:
        t0 = time.monotonic()
        day = self._guard(day, "fno")
        out = [r for r in self._d.get("fno", {}).get(underlying, [])
               if r.day == day and r.kind in ("CE", "PE") and r.expiry == expiry]
        self._record("options", {"underlying": underlying, "expiry": expiry, "day": day}, t0=t0, rows=len(out))
        return out

    async def expiries(self, underlying: str, day: Optional[date] = None) -> list[date]:
        t0 = time.monotonic()
        day = self._guard(day, "fno")
        out = sorted({r.expiry for r in self._d.get("fno", {}).get(underlying, []) if r.day == day})
        self._record("expiries", {"underlying": underlying, "day": day}, t0=t0, rows=len(out))
        return out

    async def lot_size(self, underlying: str, day: Optional[date] = None) -> Optional[int]:
        t0 = time.monotonic()
        day = self._guard(day, "fno")
        sizes = [r.lot_size for r in self._d.get("fno", {}).get(underlying, []) if r.day == day and r.lot_size]
        self._record("lot_size", {"underlying": underlying, "day": day}, t0=t0, rows=len(sizes))
        return sizes[0] if sizes else None

    async def vix(self, day: Optional[date] = None) -> Optional[Decimal]:
        t0 = time.monotonic()
        day = self._guard(day, "cash")
        v = self._d.get("vix", {}).get(day)
        self._record("vix", {"day": day}, t0=t0, rows=1 if v is not None else 0)
        return v

    async def sector(self, symbol: str) -> Optional[str]:
        t0 = time.monotonic()
        v = self._d.get("sector", {}).get(symbol)
        self._record("sector", {"symbol": symbol}, t0=t0, rows=1 if v else 0)
        return v
