"""Market data a validation reads (Workflow §6.2), cached per process. Every reader answers what it read with its source and
an `error` instead of raising, so a data-provider outage becomes DATA_INSUFFICIENT with a reason, never a guess (Workflow §20).

    bars(symbol)   NSE end-of-day bars (services/desk_trading.fetch_bars: nidp.prices_eod through the data platform, raw
                   traded prices, NOT adjusted for bonuses or splits; validate.py cuts at exit_watch.rules.series_break)
                   for BARS_LOOKBACK_DAYS calendar days (≈ 290 sessions: enough for EMA200), cached BARS_TTL_S per symbol,
                   at most BARS_CACHE_MAX symbols (least recently used dropped first: ~290 bars a symbol)
    regime()       the desk regime (macro_engine.classify_desk_regime through strategy_plan.regime_fit.read_regime), cached
                   REGIME_TTL_S

Reads run at most FETCH_CONCURRENCY at a time. Tests pass their own `fetch_bars` / `read_regime`.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ..signals import clock

logger = logging.getLogger(__name__)

BARS_LOOKBACK_DAYS = 420
BARS_TTL_S = 1800.0
BARS_CACHE_MAX = 200
REGIME_TTL_S = 300.0
FETCH_CONCURRENCY = 6
BARS_SOURCE = "NSE end-of-day bhavcopy, raw traded prices (nidp.prices_eod via the data platform, desk_trading.fetch_bars)"
REGIME_SOURCE = "macro_engine.classify_desk_regime (strategy_plan.regime_fit.read_regime)"


async def _default_fetch_bars(symbol: str, start: date) -> List[Dict[str, Any]]:
    from services import desk_trading
    return await desk_trading.fetch_bars(symbol, start)


async def _default_read_regime() -> Dict[str, Any]:
    from services.strategy_plan import regime_fit
    return await regime_fit.read_regime()


class MarketInputs:
    def __init__(self, fetch_bars: Optional[Callable[[str, date], Awaitable[List[Dict[str, Any]]]]] = None,
                 read_regime: Optional[Callable[[], Awaitable[Dict[str, Any]]]] = None,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        self._fetch = fetch_bars or _default_fetch_bars
        self._regime = read_regime or _default_read_regime
        self._mono = monotonic
        self._bars: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._reg: Dict[str, Any] = {"at": float("-inf"), "value": None}
        self._gate = asyncio.Semaphore(FETCH_CONCURRENCY)

    async def bars(self, symbol: str, now: Optional[datetime] = None) -> Dict[str, Any]:
        """{bars, error, source, read_at}. A read error is cached for a minute only."""
        hit = self._bars.get(symbol)
        if hit is not None and self._mono() - hit["at"] < hit["ttl"]:
            self._bars.move_to_end(symbol)
            return hit["value"]
        now = now or datetime.now(timezone.utc)
        start = clock.ist_day(now) - timedelta(days=BARS_LOOKBACK_DAYS)
        out: Dict[str, Any] = {"bars": [], "error": None, "source": BARS_SOURCE, "read_at": clock.utc_iso(now)}
        try:
            async with self._gate:
                out["bars"] = list(await self._fetch(symbol, start) or [])
        except Exception as e:  # noqa: BLE001 — reported as unreadable; the validation says DATA_INSUFFICIENT
            logger.warning("spt validate: bars for %s unreadable (%s)", symbol, type(e).__name__)
            out["error"] = f"the end-of-day bars could not be read ({type(e).__name__})"
        self._bars[symbol] = {"at": self._mono(), "ttl": 60.0 if out["error"] else BARS_TTL_S, "value": out}
        self._bars.move_to_end(symbol)
        while len(self._bars) > BARS_CACHE_MAX:
            self._bars.popitem(last=False)
        return out

    async def regime(self) -> Dict[str, Any]:
        if self._reg["value"] is not None and self._mono() - self._reg["at"] < REGIME_TTL_S:
            return self._reg["value"]
        try:
            reg = dict(await self._regime() or {})
        except Exception as e:  # noqa: BLE001 — reported as unavailable
            logger.warning("spt validate: regime unreadable (%s)", type(e).__name__)
            reg = {"available": False, "reason": f"unreadable ({type(e).__name__})"}
        reg.setdefault("source", REGIME_SOURCE)
        self._reg = {"at": self._mono() if reg.get("available") else float("-inf"), "value": reg}
        return reg

    def forget(self) -> None:
        self._bars.clear()
        self._reg = {"at": float("-inf"), "value": None}


_default: Optional[MarketInputs] = None


def get_inputs() -> MarketInputs:
    global _default
    if _default is None:
        _default = MarketInputs()
    return _default
