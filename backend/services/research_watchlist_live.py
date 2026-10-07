"""Live price overlay for the Research Watchlist (`/watchlist`) — yfinance,
cached 30s during NSE market hours / 5min after-hours. Same reasoning and
shape as `positional_engine/nse_live.py`'s index snapshot: NSE blocks the
cloud IP block we're hosted on, so yfinance (proxying through Yahoo's CDN)
is the reliable no-auth source. Request-time cache, not a background writer —
the cache is only ever populated by an actual page view, so an unvisited
page costs nothing and a visited one is at most 30s stale.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

_CACHE: Dict[str, Any] = {"ts": 0.0, "data": {}}


def _is_market_open_ist() -> bool:
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    minute = now.hour * 60 + now.minute
    return 9 * 60 + 15 <= minute <= 15 * 60 + 30


def _ttl() -> float:
    return 30.0 if _is_market_open_ist() else 300.0


def _fetch_yf_batch(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Synchronous yfinance call. Returns {symbol: {price, prev_close,
    day_change, day_change_pct}}. period='2d' so we always have current +
    previous trading day's close even right after a fresh open."""
    import yfinance as yf

    tickers = [f"{s}.NS" for s in symbols]
    out: Dict[str, Dict[str, Any]] = {}
    try:
        data = yf.download(" ".join(tickers), period="2d", interval="1d", progress=False, threads=True)
        if data.empty or "Close" not in data.columns:
            return out
        for ticker, sym in zip(tickers, symbols):
            try:
                col = data["Close"][ticker] if len(tickers) > 1 else data["Close"]
                series = col.dropna()
                if len(series) >= 2:
                    cur, prev = float(series.iloc[-1]), float(series.iloc[-2])
                    out[sym] = {
                        "price": round(cur, 2),
                        "prev_close": round(prev, 2),
                        "day_change": round(cur - prev, 2),
                        "day_change_pct": round((cur - prev) / prev * 100, 2) if prev else None,
                    }
                elif len(series) == 1:
                    out[sym] = {
                        "price": round(float(series.iloc[-1]), 2),
                        "prev_close": None, "day_change": None, "day_change_pct": None,
                    }
            except (KeyError, IndexError, ValueError):
                continue
    except Exception as e:  # noqa: BLE001
        logger.warning("research_watchlist_live: yfinance batch failed: %s", e)
    return out


async def get_live_quotes(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Cached live quotes for `symbols`. On a cold cache or Yahoo failure,
    returns whatever's cached (possibly {}) rather than raising — callers
    fall back to the last stored price, never block or 500 on a Yahoo blip."""
    now = time.time()
    if _CACHE["data"] and (now - _CACHE["ts"]) < _ttl():
        return _CACHE["data"]
    fetched = await asyncio.to_thread(_fetch_yf_batch, symbols)
    if not fetched:
        return _CACHE["data"]
    _CACHE["data"] = fetched
    _CACHE["ts"] = now
    return fetched
