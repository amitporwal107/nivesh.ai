"""The paper fill engine's only historical data: one session's exchange row per instrument (PHASE2_DESIGN §6.1).

The fill engine plays the market, so it may read the session it is simulating. The agents cannot: they read through the
point-in-time view (market/view.py), which still refuses that session until it is published. This reader is never given
to an agent. It refuses every session except the one the simulated clock is in, and logs each read so a test can prove it.

Rows are the RAW bhavcopy: `/prices/eod/{symbol}` for shares, `/fno/{underlying}` for contracts. An option leg is priced
from its own contract's row. `traded_volume` in the F&O file is in CONTRACTS (RELIANCE 5 Nov: 29,890 × 500 × ₹1,317 =
the file's ₹19.69 bn traded value); `traded_units` here is always shares or contract units. A contract that did not trade
carries an old close: `traded` is False and it can never price a fill.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional
from urllib.parse import quote

from .pit import INDEX_FUTURES, MAX_PAGES, PAGE, Getter, _d, _daas_get, _day, _i
from .view import DataUnavailable, LookAheadError


@dataclass(frozen=True)
class LegRef:
    """One instrument, as a plan leg names it."""
    kind: str                       # EQ | FUT | CE | PE
    underlying: str
    expiry: Optional[date] = None
    strike: Optional[Decimal] = None

    @property
    def key(self) -> str:
        if self.kind == "EQ":
            return f"EQ:{self.underlying}"
        if self.kind == "FUT":
            return f"FUT:{self.underlying}:{self.expiry}"
        return f"{self.kind}:{self.underlying}:{self.expiry}:{Decimal(str(self.strike)).normalize():f}"


@dataclass(frozen=True)
class SessionBar:
    day: date
    open: Optional[Decimal]
    high: Optional[Decimal]
    low: Optional[Decimal]
    close: Optional[Decimal]
    settle: Optional[Decimal]
    prev_close: Optional[Decimal]
    traded_units: int               # shares, or contracts × lot size
    lot_size: Optional[int]         # the exchange's lot that session (None for shares)
    traded: bool
    source: str


class SessionBarSource:
    """Guard and read log. Subclasses implement `_read`."""

    def __init__(self) -> None:
        self.reads: deque[tuple[str, date, date]] = deque(maxlen=20000)   # (instrument key, session read, session of the clock)

    async def bar(self, leg: LegRef, session: date, *, clock_session: date) -> Optional[SessionBar]:
        """The row of `leg` for `session`, or None if the exchange has none. Only the clock's session can be read."""
        if session != clock_session:
            raise LookAheadError(f"the fill engine may read only the session the clock is in ({clock_session}), "
                                 f"not {session}")
        self.reads.append((leg.key, session, clock_session))
        return await self._read(leg, session)

    async def _read(self, leg: LegRef, session: date) -> Optional[SessionBar]:
        raise NotImplementedError


class PitSessionBars(SessionBarSource):
    """Over the data API. A failed read raises DataUnavailable: an unreachable source is never "no trade"."""

    def __init__(self, getter: Optional[Getter] = None):
        super().__init__()
        self._get = getter or _daas_get
        self._rows: dict[tuple, list[dict]] = {}

    async def _pages(self, path: str, params: dict) -> list[dict]:
        out: list[dict] = []
        for page in range(MAX_PAGES):
            status, body = await self._get(path, {**params, "limit": PAGE, "offset": page * PAGE})
            if status != 200 or not isinstance(body, dict) or not isinstance(body.get("data"), list):
                raise DataUnavailable(f"data API {path}: HTTP {status}")
            out += body["data"]
            if len(body["data"]) < PAGE:
                return out
        raise DataUnavailable(f"data API {path}: more than {PAGE * MAX_PAGES} rows")

    async def _cached(self, key: tuple, path: str, params: dict) -> list[dict]:
        if key not in self._rows:
            rows = await self._pages(path, params)
            if not rows:                   # not cached: the session's file may not have landed yet
                return rows
            if len(self._rows) > 256:      # one simulation walks forward: older sessions are never read again
                self._rows.clear()
            self._rows[key] = rows
        return self._rows[key]

    async def _read(self, leg: LegRef, session: date) -> Optional[SessionBar]:
        return await (self._cash(leg, session) if leg.kind == "EQ" else self._contract(leg, session))

    async def _cash(self, leg: LegRef, session: date) -> Optional[SessionBar]:
        sym = quote(leg.underlying, safe="")
        day = session.isoformat()
        for series in ("EQ", "BE"):
            rows = await self._cached(("cash", leg.underlying, series, session), f"/prices/eod/{sym}",
                                      {"start": day, "end": day, "series": series})
            r = next((x for x in rows if _day(x["as_of_date"]) == session), None)
            if r is not None:
                vol = _i(r.get("volume")) or 0
                return SessionBar(day=session, open=_d(r.get("open_price")), high=_d(r.get("high_price")),
                                  low=_d(r.get("low_price")), close=_d(r.get("close_price")), settle=None,
                                  prev_close=_d(r.get("prev_close")), traded_units=vol, lot_size=None, traded=vol > 0,
                                  source=f"NSE bhavcopy {series} {day}")
        return None

    async def _contract(self, leg: LegRef, session: date) -> Optional[SessionBar]:
        idx = leg.underlying in INDEX_FUTURES
        fut = leg.kind == "FUT"
        kinds = (("IDF", "FUTIDX") if idx else ("STF", "FUTSTK")) if fut else (("IDO", "OPTIDX") if idx else ("STO", "OPTSTK"))
        path = f"/fno/{quote(leg.underlying, safe='')}"
        rows: list[dict] = []
        for it in kinds:
            rows = await self._cached(("fno", leg.underlying, it, leg.expiry, session), path,
                                      {"on": session.isoformat(), "instrument_type": it, "expiry": leg.expiry.isoformat()})
            if rows:
                break
        r = next((x for x in rows if self._is(x, leg, session)), None)
        if r is None:
            return None
        lot = _i(r.get("new_board_lot_qty"))
        contracts = _i(r.get("traded_volume")) or 0
        return SessionBar(day=session, open=_d(r.get("open_price")), high=_d(r.get("high_price")),
                          low=_d(r.get("low_price")), close=_d(r.get("close_price")), settle=_d(r.get("settle_price")),
                          prev_close=_d(r.get("prev_close_price")), traded_units=contracts * (lot or 0), lot_size=lot,
                          traded=contracts > 0, source=f"NSE F&O bhavcopy {session.isoformat()}")

    @staticmethod
    def _is(r: dict, leg: LegRef, session: date) -> bool:
        if _day(r["as_of_date"]) != session or _day(r["expiry_date"]) != leg.expiry:
            return False
        ot = r.get("option_type")
        if leg.kind == "FUT":
            return ot not in ("CE", "PE")
        return ot == leg.kind and _d(r.get("strike_price")) == Decimal(str(leg.strike))
