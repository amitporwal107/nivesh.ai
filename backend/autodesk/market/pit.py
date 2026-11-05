"""Point-in-time MarketView over the data platform (DaaS API) — the real market data of the desk.

Every read is bounded by the view's `as_of` (cash end-of-day of session d visible from d 18:30 IST, F&O from d 19:30
IST; market/calendar.py decides the sessions) and recorded as a tool call. A failed or non-200 read is DataUnavailable:
an empty answer is never passed off as "no data".

Prices are the RAW bhavcopy (`/prices/eod/{symbol}`), adjusted AS OF the view: the warehouse's adjusted series is
back-adjusted with every corporate action known today, so using it directly would let a later split leak into an
earlier replay. Here each bar is scaled by cumulative_adj_factor(day) / cumulative_adj_factor(latest visible session):
actions after the view's date cancel out, actions inside the window are applied.
"""
from __future__ import annotations

import time
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import quote

from . import calendar
from .view import Bar, BuildupRow, DataUnavailable, FnoContract, LookAheadError, RecordingMixin

Getter = Callable[[str, dict], Awaitable[tuple[int, Any]]]

INDEX_FUTURES = {"NIFTY": "Nifty 50", "BANKNIFTY": "Nifty Bank", "FINNIFTY": "Nifty Financial Services",
                 "MIDCPNIFTY": "Nifty Midcap Select", "NIFTYNXT50": "Nifty Next 50"}
VIX_INDEX = "India VIX"
PAGE = 5000
MAX_PAGES = 6
CACHE_TTL_S = 300
CACHE_MAX = 512
SECTOR_TTL_S = 6 * 3600

_cache: "OrderedDict[tuple, tuple[float, Any]]" = OrderedDict()
_sectors: dict[str, Any] = {"at": 0.0, "map": {}}


async def _daas_get(path: str, params: dict) -> tuple[int, Any]:
    from services.copilot_tools import daas_client
    try:
        return await daas_client.get_raw(path, params, timeout=20.0)
    except daas_client.DaasError as e:
        raise DataUnavailable(f"data API: {e}") from e


def _d(v) -> Optional[Decimal]:
    return None if v is None or v == "" else Decimal(str(v))


def _i(v) -> Optional[int]:
    return None if v is None or v == "" else int(Decimal(str(v)))


def _day(v) -> date:
    return date.fromisoformat(str(v)[:10])


class PitMarketView(RecordingMixin):
    """MarketView over the DaaS API at `as_of` (see the module docstring)."""

    def __init__(self, as_of: datetime, *, getter: Optional[Getter] = None):
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        self.as_of = as_of.astimezone(timezone.utc)
        self._get = getter or _daas_get
        self._memo: dict[tuple, Any] = {}
        self._init_recording()

    # ── plumbing ──────────────────────────────────────────────────────────────────────────────────────────────────

    async def _fetch(self, path: str, params: Optional[dict] = None) -> Any:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        key = (path, tuple(sorted((k, str(v)) for k, v in params.items())))
        if key in self._memo:
            return self._memo[key]
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL_S and self._get is _daas_get:
            self._memo[key] = hit[1]
            return hit[1]
        status, body = await self._get(path, params)
        if status != 200 or not isinstance(body, dict):
            raise DataUnavailable(f"data API {path}: HTTP {status}")
        self._memo[key] = body
        if self._get is _daas_get:
            _cache[key] = (time.monotonic(), body)
            _cache.move_to_end(key)
            while len(_cache) > CACHE_MAX:
                _cache.popitem(last=False)
        return body

    async def _rows(self, path: str, params: dict) -> list[dict]:
        out: list[dict] = []
        for page in range(MAX_PAGES):
            body = await self._fetch(path, {**params, "limit": PAGE, "offset": page * PAGE})
            rows = body.get("data")
            if not isinstance(rows, list):
                raise DataUnavailable(f"data API {path}: no data list")
            out += rows
            if len(rows) < PAGE:
                return out
        raise DataUnavailable(f"data API {path}: more than {PAGE * MAX_PAGES} rows")

    def latest_session(self, kind: str = "cash") -> date:
        return calendar.latest_published(self.as_of, kind)

    def _guard(self, day: Optional[date], kind: str) -> date:
        latest = self.latest_session(kind)
        if day is None:
            return latest
        if day > latest:
            raise LookAheadError(f"{kind} data for {day} is not published at {self.as_of.isoformat()}")
        return day

    def _window_start(self, latest: date, sessions: int) -> date:
        return latest - timedelta(days=int(sessions * 1.6) + 12)

    # ── cash ──────────────────────────────────────────────────────────────────────────────────────────────────────

    async def sessions_between(self, start: date, end: date) -> list[date]:
        t0 = time.monotonic()
        latest = self.latest_session("cash")
        out = [d for d in await calendar.sessions_between(start, min(end, latest))]
        self._record("sessions_between", {"start": start, "end": end}, t0=t0, rows=len(out))
        return out

    async def _factors(self, symbol: str, start: date, latest: date) -> dict[date, Decimal]:
        rows = await self._rows(f"/prices/adjusted/{quote(symbol, safe='')}",
                                {"start": start.isoformat(), "end": latest.isoformat()})
        return {_day(r["as_of_date"]): _d(r.get("cumulative_adj_factor")) or Decimal("1") for r in rows}

    async def daily_bars(self, symbol: str, *, sessions: int) -> list[Bar]:
        t0 = time.monotonic()
        latest = self.latest_session("cash")
        start = self._window_start(latest, sessions)
        path = f"/prices/eod/{quote(symbol, safe='')}"
        try:
            raw = await self._rows(path, {"start": start.isoformat(), "end": latest.isoformat(), "series": "EQ"})
            if not raw:
                raw = await self._rows(path, {"start": start.isoformat(), "end": latest.isoformat(), "series": "BE"})
            factors = await self._factors(symbol, start, latest) if raw else {}
        except DataUnavailable as e:
            self._record("daily_bars", {"symbol": symbol, "sessions": sessions}, t0=t0, ok=False, error=str(e))
            raise
        anchor = factors.get(max(factors)) if factors else Decimal("1")
        bars = []
        for r in sorted(raw, key=lambda r: r["as_of_date"]):
            day = _day(r["as_of_date"])
            if day > latest:
                continue
            f = (factors.get(day) or anchor) / anchor if anchor else Decimal("1")
            adj = lambda v: None if v is None else (Decimal(str(v)) * f)          # noqa: E731
            vol = _i(r.get("volume")) or 0
            bars.append(Bar(day=day, open=adj(r["open_price"]), high=adj(r["high_price"]), low=adj(r["low_price"]),
                            close=adj(r["close_price"]), volume=int(vol / f) if f else vol,
                            turnover_rs=_d(r.get("turnover")), deliv_pct=_d(r.get("deliv_pct")), adj_factor=f))
        bars = bars[-sessions:]
        self._record("daily_bars", {"symbol": symbol, "sessions": sessions}, t0=t0, rows=len(bars))
        return bars

    async def day_snapshot(self, day: date) -> dict[str, Bar]:
        t0 = time.monotonic()
        day = self._guard(day, "cash")
        rows = await self._rows("/prices/eod", {"on": day.isoformat(), "series": "EQ"})
        out = {r["symbol"]: Bar(day=day, open=_d(r["open_price"]), high=_d(r["high_price"]), low=_d(r["low_price"]),
                                close=_d(r["close_price"]), volume=_i(r.get("volume")) or 0,
                                turnover_rs=_d(r.get("turnover")), deliv_pct=_d(r.get("deliv_pct")))
               for r in rows if r.get("close_price") is not None}
        self._record("day_snapshot", {"day": day}, t0=t0, rows=len(out))
        return out

    async def index_bars(self, name: str, *, sessions: int) -> list[Bar]:
        t0 = time.monotonic()
        latest = self.latest_session("cash")
        rows = await self._rows(f"/prices/index/{quote(name, safe='')}",
                                {"start": self._window_start(latest, sessions).isoformat(), "end": latest.isoformat()})
        bars = [Bar(day=_day(r["as_of_date"]), open=_d(r["open_price"]) or _d(r["close_price"]),
                    high=_d(r["high_price"]) or _d(r["close_price"]), low=_d(r["low_price"]) or _d(r["close_price"]),
                    close=_d(r["close_price"]), volume=_i(r.get("volume")) or 0, turnover_rs=_d(r.get("turnover")))
                for r in sorted(rows, key=lambda r: r["as_of_date"]) if r.get("close_price") is not None
                and _day(r["as_of_date"]) <= latest][-sessions:]
        self._record("index_bars", {"name": name, "sessions": sessions}, t0=t0, rows=len(bars))
        return bars

    async def vix(self, day: Optional[date] = None) -> Optional[Decimal]:
        t0 = time.monotonic()
        day = self._guard(day, "cash")
        rows = await self._rows(f"/prices/index/{quote(VIX_INDEX, safe='')}",
                                {"start": day.isoformat(), "end": day.isoformat()})
        v = next((_d(r["close_price"]) for r in rows if _day(r["as_of_date"]) == day), None)
        self._record("vix", {"day": day}, t0=t0, rows=1 if v is not None else 0)
        return v

    async def sector(self, symbol: str) -> Optional[str]:
        """Industry classification (not point-in-time; classifications rarely change). sector_master is sparse, so the
        Nifty 500 constituents' industry fills the gaps."""
        t0 = time.monotonic()
        if time.monotonic() - _sectors["at"] > SECTOR_TTL_S or not _sectors["map"]:
            m: dict[str, str] = {}
            try:                                   # each source on its own: one failing must not empty the other
                for r in await self._rows("/indices/Nifty 500/constituents", {}):
                    if r.get("industry"):
                        m[r["symbol"]] = r["industry"]
            except DataUnavailable:
                pass
            try:
                for r in await self._rows("/symbols", {}):
                    if r.get("symbol") and (r.get("sector") or r.get("industry")) and r["symbol"] not in m:
                        m[r["symbol"]] = r.get("sector") or r.get("industry")
            except DataUnavailable:
                pass
            if m:
                _sectors.update(at=time.monotonic(), map=m)
        v = _sectors["map"].get(symbol)
        self._record("sector", {"symbol": symbol}, t0=t0, rows=1 if v else 0)
        return v

    # ── F&O ───────────────────────────────────────────────────────────────────────────────────────────────────────

    async def _buildup_body(self, day: date) -> dict:
        body = await self._fetch("/desk/fno-buildup", {"date": day.isoformat()})
        if body.get("as_of") not in (None, day.isoformat()):
            raise DataUnavailable(f"build-up for {day} answered for {body.get('as_of')}")
        return body

    async def fno_universe(self, day: Optional[date] = None) -> list[str]:
        t0 = time.monotonic()
        day = self._guard(day, "fno")
        body = await self._buildup_body(day)
        out = sorted({r["symbol"] for r in (body.get("rows") or []) + (body.get("indices") or [])
                      if r.get("symbol") and r.get("close") is not None})
        self._record("fno_universe", {"day": day}, t0=t0, rows=len(out))
        return out

    async def fno_buildup(self, day: Optional[date] = None) -> list[BuildupRow]:
        t0 = time.monotonic()
        day = self._guard(day, "fno")
        body = await self._buildup_body(day)
        out = [BuildupRow(day=day, underlying=r["symbol"], label=r.get("label") or "no_data",
                          price_change_pct=_d(r.get("price_chg_pct")), oi_change_pct=_d(r.get("oi_chg_pct")),
                          fut_close=_d(r.get("close")), open_interest=_i(r.get("oi")), extra=r)
               for r in (body.get("rows") or []) + (body.get("indices") or []) if r.get("symbol")]
        self._record("fno_buildup", {"day": day}, t0=t0, rows=len(out))
        return out

    async def _contracts(self, underlying: str, day: date, kinds: tuple[str, ...], expiry: Optional[date] = None
                         ) -> list[FnoContract]:
        path = f"/fno/{quote(underlying, safe='')}"
        rows: list[dict] = []
        for it in kinds:
            rows = await self._rows(path, {"on": day.isoformat(), "instrument_type": it,
                                           "expiry": expiry.isoformat() if expiry else None})
            if rows:
                break
        out = []
        for r in rows:
            if _day(r["as_of_date"]) != day:
                continue
            ot = r.get("option_type")
            out.append(FnoContract(day=day, underlying=underlying, kind=ot if ot in ("CE", "PE") else "FUT",
                                   expiry=_day(r["expiry_date"]), strike=_d(r.get("strike_price")),
                                   close=_d(r.get("close_price")), settle=_d(r.get("settle_price")),
                                   underlying_price=_d(r.get("underlying_price")),
                                   open_interest=_i(r.get("open_interest")), change_in_oi=_i(r.get("change_in_oi")),
                                   traded_volume=_i(r.get("traded_volume")), lot_size=_i(r.get("new_board_lot_qty")),
                                   traded_value_rs=_d(r.get("traded_value"))))
        return out

    def _kinds(self, underlying: str, fut: bool) -> tuple[str, ...]:
        idx = underlying in INDEX_FUTURES
        if fut:
            return ("IDF", "FUTIDX") if idx else ("STF", "FUTSTK")
        return ("IDO", "OPTIDX") if idx else ("STO", "OPTSTK")

    async def futures(self, underlying: str, day: Optional[date] = None) -> list[FnoContract]:
        t0 = time.monotonic()
        day = self._guard(day, "fno")
        out = sorted(await self._contracts(underlying, day, self._kinds(underlying, True)), key=lambda r: r.expiry)
        self._record("futures", {"underlying": underlying, "day": day}, t0=t0, rows=len(out))
        return out

    async def options(self, underlying: str, expiry: date, day: Optional[date] = None) -> list[FnoContract]:
        t0 = time.monotonic()
        day = self._guard(day, "fno")
        out = [r for r in await self._contracts(underlying, day, self._kinds(underlying, False), expiry)
               if r.kind in ("CE", "PE") and r.expiry == expiry]
        self._record("options", {"underlying": underlying, "expiry": expiry, "day": day}, t0=t0, rows=len(out))
        return out

    async def expiries(self, underlying: str, day: Optional[date] = None) -> list[date]:
        t0 = time.monotonic()
        day = self._guard(day, "fno")
        futs = await self._contracts(underlying, day, self._kinds(underlying, True))
        opts = await self._contracts(underlying, day, self._kinds(underlying, False))
        out = sorted({r.expiry for r in futs + opts if r.expiry >= day})
        self._record("expiries", {"underlying": underlying, "day": day}, t0=t0, rows=len(out))
        return out

    async def lot_size(self, underlying: str, day: Optional[date] = None) -> Optional[int]:
        t0 = time.monotonic()
        day = self._guard(day, "fno")
        sizes = [r.lot_size for r in await self._contracts(underlying, day, self._kinds(underlying, True)) if r.lot_size]
        self._record("lot_size", {"underlying": underlying, "day": day}, t0=t0, rows=len(sizes))
        return sizes[0] if sizes else None
