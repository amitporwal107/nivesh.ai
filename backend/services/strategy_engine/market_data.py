"""Market-data access for the strategy engine — pluggable backend.

The engine needs four things to screen/backtest: a trading calendar, the
universe's symbols (point-in-time), the per-date matched+ranked candidates,
and adjusted exit bars. Historically it read `nidp.*` via the app's Postgres
pool — fine on a co-located dev box, broken on staging/prod where NIDP is a
separate system reached over the DaaS API.

This module abstracts that behind `MarketDataProvider` with two backends:

  • `SqlMarketDataProvider` — direct SQL (co-located dev + the unit tests).
    Pushes predicates to SQL via `compiler_stock`.
  • `DaasMarketDataProvider` — NIDP DaaS API; fetches raw rows in bulk and
    screens/ranks in the app via `evaluator` (the API can't run arbitrary
    DSL predicates server-side).

`get_provider()` picks the backend from `STRATEGY_MARKET_DATA` (sql|daas),
defaulting to daas when the DaaS client is configured, else sql.

Universes and their survivorship status (recorded as basis["universe_basis"]):
  • market / LIQUID_EQ — `point_in_time`: each date's members are computed from that date's
    prices and the 30 sessions before it (liquid_universe.py, liquid-eq-v1), so stocks later
    delisted are in the universe while they traded. Both backends use the same pure rule.
  • index on DaaS — `latest_snapshot`: the newest constituent snapshot applied to every date
    (survivorship bias); basis["universe_warning"] says so and the UI shows it. No historical
    constituents are invented (docs/ai_research/P4_POINT_IN_TIME_UNIVERSE.md).
  • custom — `custom_universe`: the user's own list, as saved.

Both backends expose the same async surface; R1's semantics (adjusted-price
entries/exits, point-in-time membership) are preserved by both.
"""
from __future__ import annotations

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from datetime import date
from typing import Any, Dict, List, Optional, Set

from .compiler_stock import compile_stock_query, to_asyncpg, _PIT_INDEX_NAME
from . import evaluator as _ev
from . import liquid_universe as _lu
from .backtest_sql import EXIT_BARS_SQL  # shared SQL constant (avoids import cycle)

logger = logging.getLogger(__name__)

SURVIVORSHIP_WARNING = (
    "Survivorship bias: this index universe uses the latest constituent snapshot for every date in the window, so stocks "
    "that left the index (including any later delisted) are missing and past results look better than they were. "
    f"Use \"{_lu.LABEL}\" for a survivorship-free run.")
_EOD_CONCURRENCY = 8      # parallel one-session price reads for the liquid universe (DaaS)
_LOOKBACK_BATCH = 35      # weekdays read per step while looking back for the 29 priced sessions before a window
_LOOKBACK_STEPS = 4       # at most 140 weekdays back (the start of the price history ends the search earlier)


def _market_universe(spec: Dict[str, Any]) -> bool:
    uni = spec.get("universe") or {}
    return uni.get("type") == "market" and str(uni.get("ref", "")).upper() == _lu.REF


def _iso(d: Any) -> str:
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


class MarketDataProvider(ABC):
    """Per-run market-data access. `prepare()` is an optional prefetch hook the
    DaaS backend uses to bulk-load the window; the SQL backend no-ops it."""

    @abstractmethod
    async def prepare(self, spec: Dict[str, Any], from_date: date, to_date: date) -> None: ...

    @abstractmethod
    async def trading_dates(self, from_date: date, to_date: date) -> List[date]: ...

    @abstractmethod
    async def latest_date(self) -> Optional[date]:
        """Most recent date with feature snapshots (for a live, single-date screen)."""

    @abstractmethod
    async def screen(self, spec: Dict[str, Any], as_of: date) -> List[Dict[str, Any]]:
        """Matched + ranked + top-N candidate rows for one date. Each row carries
        at least: symbol, close, adj_close, adj_factor, atr14, accumulation_score."""

    @abstractmethod
    async def exit_bars(self, symbols: List[str], as_of: date) -> Dict[str, Dict[str, Any]]:
        """{symbol: {open, high, low, close}} adjusted, for one date (the open fills a gap through the stop)."""


# ── SQL backend (co-located dev / unit tests) ───────────────────────────────
class SqlMarketDataProvider(MarketDataProvider):
    def __init__(self, pool):
        self._pool = pool
        self._sql_pg: Optional[str] = None
        self._base_args: List[Any] = []
        self._members: Optional[Dict[str, Set[str]]] = None    # market universe: iso date -> members
        self.basis: Dict[str, Any] = {"price_basis": "corp_action_adjusted",
                                      "universe_basis": "unknown"}

    async def _use_point_in_time(self, spec: Dict[str, Any]) -> bool:
        uni = spec.get("universe") or {}
        if uni.get("type") != "index":
            return False
        index_name = _PIT_INDEX_NAME.get(str(uni.get("ref", "")).upper())
        if not index_name:
            return False
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM nidp.index_constituents WHERE index_name = $1 LIMIT 1",
                index_name,
            )
        if not row:
            logger.warning("SqlMarketDataProvider: index_constituents empty for %s — "
                           "legacy present-day membership (survivorship bias)", index_name)
        return bool(row)

    async def _prepare_market(self, from_date: date, to_date: date) -> None:
        async with self._pool.acquire() as conn:
            window = [r["as_of_date"] for r in await conn.fetch(
                "SELECT DISTINCT as_of_date FROM nidp.stock_features_daily WHERE as_of_date BETWEEN $1 AND $2 "
                "ORDER BY as_of_date", from_date, to_date)]
            lookback = [r["as_of_date"] for r in await conn.fetch(
                "SELECT DISTINCT as_of_date FROM nidp.prices_eod WHERE series = 'EQ' AND as_of_date < $1 "
                f"ORDER BY as_of_date DESC LIMIT {_lu.LOOKBACK_SESSIONS}", from_date)]
            read = sorted(lookback) + window
            rows = await conn.fetch(
                "SELECT as_of_date, symbol, series, close_price, volume FROM nidp.prices_eod "
                "WHERE as_of_date = ANY($1::date[]) AND series = 'EQ'", read) if read else []
            # NSE's latest ETF list, as the DaaS backend reads it (an ETF is an ETF for life; see liquid_universe.py)
            etf_rows = await conn.fetch(
                "SELECT symbol FROM nidp.security_reference_daily WHERE is_etf AND as_of_date = "
                "(SELECT MAX(as_of_date) FROM nidp.security_reference_daily)")
        by_day: Dict[date, List[Dict[str, Any]]] = {}
        for r in rows:
            by_day.setdefault(r["as_of_date"], []).append(dict(r))
        etfs = {r["symbol"] for r in etf_rows}
        members, report = _lu.membership(read, by_day, window, etfs)
        report["etf_list"] = {"source": "nidp.security_reference_daily.is_etf", "count": len(etfs)}
        report["lookback_sessions"] = len(lookback)
        self._members = {_iso(d): m for d, m in members.items()}
        self.basis.update(universe_basis="point_in_time", universe_rule=_lu.rule(), universe_report=report)

    async def prepare(self, spec, from_date, to_date) -> None:
        if _market_universe(spec):
            await self._prepare_market(from_date, to_date)
            pit = False
        else:
            pit = await self._use_point_in_time(spec)
            self.basis["universe_basis"] = "point_in_time" if pit else "present_day_fallback"
            if not pit:
                self.basis["universe_warning"] = SURVIVORSHIP_WARNING
        sql, params = compile_stock_query(spec, point_in_time_universe=pit)
        sql_pg, base_args = to_asyncpg(sql, params)
        next_slot = len(base_args) + 1
        sql_pg = sql_pg.replace(":as_of_date", f"${next_slot}")
        if self._members is not None:
            sql_pg = sql_pg.replace(":universe_members", f"${next_slot + 1}")
        self._sql_pg = sql_pg
        self._base_args = base_args

    async def trading_dates(self, from_date, to_date) -> List[date]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT as_of_date FROM nidp.stock_features_daily "
                "WHERE as_of_date BETWEEN $1 AND $2 ORDER BY as_of_date",
                from_date, to_date,
            )
        return [r["as_of_date"] for r in rows]

    async def latest_date(self) -> Optional[date]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT MAX(as_of_date) AS d FROM nidp.stock_features_daily")
        return row["d"] if row and row["d"] else None

    async def screen(self, spec, as_of) -> List[Dict[str, Any]]:
        if self._sql_pg is None:
            await self.prepare(spec, as_of, as_of)
        extra = [] if self._members is None else [sorted(self._members.get(_iso(as_of), set()))]
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(self._sql_pg, *self._base_args, as_of, *extra)
        return [dict(r) for r in rows]

    async def exit_bars(self, symbols, as_of) -> Dict[str, Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(EXIT_BARS_SQL, symbols, as_of)
        return {r["symbol"]: dict(r) for r in rows}


# ── DaaS backend (staging / prod) ───────────────────────────────────────────
class DaasMarketDataProvider(MarketDataProvider):
    _CHUNK = 250  # symbols per bulk call (< NIDP _BULK_MAX_SYMBOLS)

    def __init__(self, app_pool=None):
        self._app_pool = app_pool  # for custom universes (user_universes lives app-side)
        self._feat: Dict[str, Dict[str, Dict[str, Any]]] = {}   # symbol -> {iso_date: row}
        self._adj: Dict[str, Dict[str, Dict[str, Any]]] = {}    # symbol -> {iso_date: row}
        self._snapshots: List[tuple] = []                       # [(snapshot_date, set(symbols))] asc
        self._members: Optional[Dict[str, Set[str]]] = None     # market universe: iso date -> members
        self.basis: Dict[str, Any] = {"price_basis": "corp_action_adjusted",
                                      "universe_basis": "unknown"}

    # -- universe resolution --
    async def _custom_symbols(self, universe_id: str) -> List[str]:
        if self._app_pool is None:
            return []
        async with self._app_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT symbols FROM user_universes WHERE id = $1", universe_id)
        return list(row["symbols"]) if row and row["symbols"] else []

    @staticmethod
    def _membership_sample_dates(from_date: date, to_date: date) -> List[date]:
        """Month-start sample points (+ endpoints) at which to snapshot index
        membership — constituents change ~quarterly, so monthly is ample and
        bounds the calls to <= ~60 for a 5y window."""
        if from_date == to_date:
            return [to_date]
        pts: List[date] = [from_date]
        y, m = from_date.year, from_date.month
        while True:
            m += 1
            if m > 12:
                m = 1; y += 1
            d = date(y, m, 1)
            if d >= to_date:
                break
            pts.append(d)
        pts.append(to_date)
        return pts

    async def prepare(self, spec, from_date, to_date) -> None:
        from ..copilot_tools import daas_client as dc
        uni = spec.get("universe") or {}
        symbols: set = set()

        if uni.get("type") == "index":
            index_name = _PIT_INDEX_NAME.get(str(uni.get("ref", "")).upper())
            if not index_name:
                raise ValueError(f"unknown index ref {uni.get('ref')!r}")
            # Constituent snapshots are periodic, and the DaaS `on` lookup matches
            # an EXACT snapshot date — passing an arbitrary bar/sample date returns
            # nothing. So resolve to the most-recent available snapshot (on=None)
            # and apply it across the window. Honest label: latest_snapshot (true
            # per-bar point-in-time needs snapshot-history the API doesn't expose).
            syms = await dc.get_index_constituents(index_name, on=None)
            self._snapshots.append((from_date, set(syms)))
            symbols.update(syms)
            self.basis["universe_basis"] = "latest_snapshot"
            self.basis["universe_warning"] = SURVIVORSHIP_WARNING
        elif _market_universe(spec):
            symbols.update(await self._prepare_market(dc, from_date, to_date))
        elif uni.get("type") == "custom":
            syms = await self._custom_symbols(str(uni.get("ref", "")))
            self._snapshots.append((from_date, set(syms)))
            symbols.update(syms)
            self.basis["universe_basis"] = "custom_universe"
        else:
            raise ValueError(f"universe type {uni.get('type')!r} not supported")

        self._snapshots.sort(key=lambda t: t[0])
        sym_list = sorted(symbols)
        # Bulk-fetch the window once per symbol-chunk. Range queries are reliable
        # over the internal DaaS endpoint (NIDP_DAAS_INTERNAL_URL); the public
        # edge dropped large/slow responses, which is why that routing exists.
        start_iso, end_iso = _iso(from_date), _iso(to_date)
        for i in range(0, len(sym_list), self._CHUNK):
            chunk = sym_list[i:i + self._CHUNK]
            feats = await dc.get_features_bulk(chunk, start_iso, end_iso)
            for sym, rows in feats.items():
                self._feat[sym] = {_iso(r["as_of_date"]): r for r in rows}
            adj = await dc.get_adjusted_prices_bulk(chunk, start_iso, end_iso)
            for sym, rows in adj.items():
                self._adj[sym] = {_iso(r["as_of_date"]): r for r in rows}

    async def _prepare_market(self, dc, from_date: date, to_date: date) -> Set[str]:
        """The liquid universe's members per window date, from one bhavcopy read per session (the window plus the 29
        sessions before it). Returns the union, the only symbols whose features and bars are then fetched. A failed read
        raises: a backtest never runs on a silently thinner universe."""
        window = [date.fromisoformat(x) for x in await dc.get_trading_calendar(_iso(from_date), _iso(to_date))]
        sem = asyncio.Semaphore(_EOD_CONCURRENCY)

        async def one(d: date):
            async with sem:
                return d, await dc.get_prices_eod_on(_iso(d), series=_lu.SERIES)

        async def read_days(days: List[date]) -> Dict[date, List[Dict[str, Any]]]:
            return dict(await asyncio.gather(*(one(d) for d in days)))
        by_day = await read_days(window)
        # The lookback: the 29 most recent days before the window that have EQ prices (weekdays without any are holidays).
        lookback: List[date] = []
        cursor = from_date
        for _ in range(_LOOKBACK_STEPS):
            cands = _lu.weekdays_before(cursor, _LOOKBACK_BATCH)
            got = await read_days(cands)
            for d in cands:
                if got[d] and len(lookback) < _lu.LOOKBACK_SESSIONS:
                    lookback.append(d)
                    by_day[d] = got[d]
            if len(lookback) >= _lu.LOOKBACK_SESSIONS or not any(got.values()):
                break
            cursor = cands[-1]
        read = sorted(lookback) + window
        etfs, etf_note = await self._etf_list(dc)
        members, report = _lu.membership(read, by_day, window, etfs)
        report["lookback_sessions"] = len(lookback)
        report["etf_list"] = etf_note
        self._members = {_iso(d): m for d, m in members.items()}
        self.basis.update(universe_basis="point_in_time", universe_rule=_lu.rule(), universe_report=report)
        return set().union(*members.values()) if members else set()

    @staticmethod
    async def _etf_list(dc):
        """(NSE's ETF list, a note on where it came from). The data API serves the flag only in the scan snapshot (the
        latest list). If it cannot be read the universe keeps the name rule and the note says so; it is not guessed."""
        try:
            status, body = await dc.get_raw("/features/scan-snapshot", None, timeout=30.0)
        except Exception as e:  # noqa: BLE001 — reported in the run, the name rule still applies
            return set(), {"source": "unavailable", "error": f"{type(e).__name__}: {str(e)[:120]}", "count": 0}
        rows = (body or {}).get("rows") if status == 200 and isinstance(body, dict) else None
        if not isinstance(rows, list):
            return set(), {"source": "unavailable", "error": f"scan snapshot HTTP {status}", "count": 0}
        etfs = {str(r["symbol"]).upper() for r in rows if isinstance(r, dict) and r.get("symbol") and r.get("is_etf")}
        return etfs, {"source": "DaaS /features/scan-snapshot (nidp.security_reference_daily.is_etf, latest list)",
                      "reference_as_of": (body or {}).get("reference_as_of"), "count": len(etfs)}

    def _membership(self, as_of: date) -> set:
        """Symbols in the universe as of `as_of` — the date's own members for a market universe; otherwise the most
        recent snapshot <= as_of. Falls back to the earliest snapshot if as_of precedes all."""
        if self._members is not None:
            return self._members.get(_iso(as_of), set())
        chosen: Optional[set] = None
        for snap_date, syms in self._snapshots:
            if snap_date <= as_of:
                chosen = syms
            else:
                break
        if chosen is None and self._snapshots:
            chosen = self._snapshots[0][1]
        return chosen or set()

    async def trading_dates(self, from_date, to_date) -> List[date]:
        from ..copilot_tools import daas_client as dc
        from datetime import date as _date
        iso = await dc.get_trading_calendar(_iso(from_date), _iso(to_date))
        return [_date.fromisoformat(s) for s in iso]

    async def latest_date(self) -> Optional[date]:
        from ..copilot_tools import daas_client as dc
        from datetime import date as _date
        iso = await dc.get_trading_calendar(None, None)
        return _date.fromisoformat(iso[-1]) if iso else None

    async def screen(self, spec, as_of) -> List[Dict[str, Any]]:
        key = _iso(as_of)
        rows: List[Dict[str, Any]] = []
        for sym in self._membership(as_of):
            fr = self._feat.get(sym, {}).get(key)
            if not fr:
                continue
            ar = self._adj.get(sym, {}).get(key) or {}
            row = dict(fr)
            row["adj_close"] = ar.get("adj_close")
            row["adj_factor"] = ar.get("cumulative_adj_factor")
            rows.append(row)
        return _ev.screen_rows(spec, rows)

    async def exit_bars(self, symbols, as_of) -> Dict[str, Dict[str, Any]]:
        key = _iso(as_of)
        out: Dict[str, Dict[str, Any]] = {}
        for sym in symbols:
            ar = self._adj.get(sym, {}).get(key)
            if not ar:
                continue
            out[sym] = {"symbol": sym, "open": ar.get("adj_open"), "high": ar.get("adj_high"),
                        "low": ar.get("adj_low"), "close": ar.get("adj_close")}
        return out


def get_provider(app_pool=None) -> MarketDataProvider:
    """Pick the backend: `STRATEGY_MARKET_DATA=sql|daas`, else daas when the DaaS
    client is configured (staging/prod), else sql (co-located dev)."""
    mode = (os.environ.get("STRATEGY_MARKET_DATA") or "").strip().lower()
    if not mode:
        try:
            from ..copilot_tools import daas_client as dc
            mode = "daas" if dc.is_configured() else "sql"
        except Exception:
            mode = "sql"
    if mode == "daas":
        return DaasMarketDataProvider(app_pool)
    return SqlMarketDataProvider(app_pool)
