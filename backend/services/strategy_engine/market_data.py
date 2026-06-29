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

Both backends expose the same async surface; R1's semantics (adjusted-price
entries/exits, point-in-time membership) are preserved by both.
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from datetime import date
from typing import Any, Dict, List, Optional

from .compiler_stock import compile_stock_query, to_asyncpg, _PIT_INDEX_NAME
from . import evaluator as _ev
from .backtest_sql import EXIT_BARS_SQL  # shared SQL constant (avoids import cycle)

logger = logging.getLogger(__name__)


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
        """{symbol: {high, low, close}} adjusted, for one date."""


# ── SQL backend (co-located dev / unit tests) ───────────────────────────────
class SqlMarketDataProvider(MarketDataProvider):
    def __init__(self, pool):
        self._pool = pool
        self._sql_pg: Optional[str] = None
        self._base_args: List[Any] = []
        self.basis: Dict[str, str] = {"price_basis": "corp_action_adjusted",
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

    async def prepare(self, spec, from_date, to_date) -> None:
        pit = await self._use_point_in_time(spec)
        self.basis["universe_basis"] = "point_in_time" if pit else "present_day_fallback"
        sql, params = compile_stock_query(spec, point_in_time_universe=pit)
        sql_pg, base_args = to_asyncpg(sql, params)
        next_slot = len(base_args) + 1
        self._sql_pg = sql_pg.replace(":as_of_date", f"${next_slot}")
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
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(self._sql_pg, *self._base_args, as_of)
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
        self.basis: Dict[str, str] = {"price_basis": "corp_action_adjusted",
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

    def _membership(self, as_of: date) -> set:
        """Symbols in the universe as of `as_of` — most recent snapshot <= as_of
        (point-in-time). Falls back to the earliest snapshot if as_of precedes all."""
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
            out[sym] = {"symbol": sym, "high": ar.get("adj_high"),
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
