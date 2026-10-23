"""Read-only doors to Kite: a client that can only read, and a WebSocket ticker wrapper.

`ReadOnlyKite` exposes exactly instruments(), quote(), historical_data() and profile(); there is no order, GTT, margin or
session method on it, so nothing built on it can place, modify or cancel an order.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

# Kite's own list of tradingsymbols for the broad market indices lives in the NSE instrument master (segment INDICES).
_ALIASES = {
    "NIFTY FINANCIAL SERVICES": "NIFTY FIN SERVICE", "NIFTY CONSUMER DURABLES": "NIFTY CONSR DURBL",
    "NIFTY SERVICES SECTOR": "NIFTY SERV SECTOR", "NIFTY PRIVATE BANK": "NIFTY PVT BANK",
    "NIFTY MIDCAP SELECT": "NIFTY MID SELECT", "NIFTY OIL & GAS": "NIFTY OIL AND GAS",
    "NIFTY NEXT50": "NIFTY NEXT 50", "NIFTY MEDIA": "NIFTY MEDIA",
}


def canon(symbol: str) -> str:
    """'NSE:Nifty  Bank' -> 'NIFTY BANK': the key every cache and response uses."""
    s = str(symbol or "").strip()
    if ":" in s:
        s = s.split(":", 1)[1]
    s = " ".join(s.upper().split())
    return _ALIASES.get(s, s)


class ReadOnlyKite:
    """The only Kite surface this package uses. Wraps a KiteConnect client without re-exporting the rest of it."""

    def __init__(self, kc: Any):
        self._kc = kc

    def instruments(self, exchange: str) -> List[dict]:
        return self._kc.instruments(exchange)

    def quote(self, keys: List[str]) -> Dict[str, dict]:
        return self._kc.quote(keys)

    def profile(self) -> dict:
        return self._kc.profile()

    def historical_data(self, instrument_token: int, from_date, to_date, interval: str) -> List[dict]:
        """Candles for one instrument (market data; Kite allows ~3 requests/second)."""
        return self._kc.historical_data(instrument_token, from_date, to_date, interval, continuous=False, oi=False)


def default_kite_factory(api_key: str, token: str) -> ReadOnlyKite:
    try:
        from kiteconnect import KiteConnect
    except ImportError as e:
        raise RuntimeError("kiteconnect SDK not installed") from e
    kc = KiteConnect(api_key=api_key)
    kc.set_access_token(token)
    return ReadOnlyKite(kc)


def default_ticker_factory(api_key: str, token: str):
    from kiteconnect import KiteTicker
    return KiteTicker(api_key, token)


class TickerSource:
    """KiteTicker in 'quote' mode (ltp, ohlc, volume) on its own thread; the tokens in `full_tokens` (the futures) are in
    'full' mode, the only one that carries open interest. Ticks go to `on_tick(token, tick)`.

    `healthy()` is true while connected and a tick (or the connect) happened in the last `stale_after` seconds.
    A close with a token/permission error sets `auth_failed`; the feed then reports 'expired' and re-reads the token.
    """
    MODE = "quote"

    def __init__(self, api_key: str, token: str, on_tick: Callable[[int, dict], None],
                 factory: Callable[[str, str], Any] = default_ticker_factory, stale_after: float = 20.0):
        self._on_tick, self._stale_after = on_tick, stale_after
        self._kws = factory(api_key, token)
        self._tokens: List[int] = []
        self.full_tokens: set = set()
        self._lock = threading.Lock()
        self.connected = False
        self.auth_failed = False
        self.last_event = 0.0
        self.last_tick = 0.0
        self.last_error = ""
        k = self._kws
        k.on_connect, k.on_ticks, k.on_close, k.on_error = self._connect, self._ticks, self._close, self._error
        k.on_reconnect = lambda ws, n: setattr(self, "last_event", time.monotonic())
        k.on_noreconnect = lambda ws: setattr(self, "connected", False)

    def start(self, tokens: Iterable[int]) -> None:
        with self._lock:
            self._tokens = list(tokens)
        self.last_event = time.monotonic()
        self._kws.connect(threaded=True)

    def set_tokens(self, tokens: Iterable[int]) -> None:
        new = list(tokens)
        with self._lock:
            old = set(self._tokens)
            self._tokens = new
        if self.connected:
            add = [t for t in new if t not in old]
            drop = [t for t in old if t not in set(new)]
            if drop:
                self._kws.unsubscribe(drop)
            if add:
                self._sub(add)

    def _sub(self, tokens: List[int]) -> None:
        for i in range(0, len(tokens), 500):
            chunk = tokens[i:i + 500]
            self._kws.subscribe(chunk)
            full = [t for t in chunk if t in self.full_tokens]
            rest = [t for t in chunk if t not in self.full_tokens]
            if rest:
                self._kws.set_mode(self.MODE, rest)
            if full:
                self._kws.set_mode("full", full)

    def stop(self) -> None:
        try:
            self._kws.close()
        except Exception as e:  # noqa: BLE001
            logger.debug("kite ticker close: %s", type(e).__name__)
        self.connected = False

    def healthy(self) -> bool:
        if not self.connected or self.auth_failed:
            return False
        return (time.monotonic() - max(self.last_tick, self.last_event)) <= self._stale_after

    # KiteTicker callbacks (called on the ticker thread)
    def _connect(self, ws, response=None) -> None:
        self.connected, self.last_event = True, time.monotonic()
        with self._lock:
            toks = list(self._tokens)
        self._sub(toks)

    def _ticks(self, ws, ticks) -> None:
        self.last_tick = time.monotonic()
        for t in ticks or []:
            try:
                self._on_tick(int(t["instrument_token"]), t)
            except Exception as e:  # noqa: BLE001 — one bad tick must not kill the ticker thread
                logger.debug("kite tick dropped: %s", type(e).__name__)

    def _close(self, ws, code=None, reason=None) -> None:
        self.connected = False
        self.last_error = f"closed:{code}"
        if code in (403, 1006) and "token" in str(reason).lower():
            self.auth_failed = True

    def _error(self, ws, code=None, reason=None) -> None:
        self.last_error = f"error:{code}"
        if code == 403 or "token" in str(reason).lower() or "403" in str(reason):
            self.auth_failed = True
