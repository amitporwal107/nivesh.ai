"""Buyer- and seller-initiated prints of cash stocks, counted live from Kite WebSocket ticks (the feed leader only).

Why: the scan dashboard's "10x volume first 5 min" widget needs "buyer initiated trades / seller initiated trades > 1".
Its first source is TrueData tick history (services/scan_builder/tick_flow.py); when TrueData is unavailable the dashboard reads
these counts from the live quote cache instead. Kite keeps no tick history, so the counts start at the first tick this feed
saw for the stock today (`sides_since`).

Each EQ tick in 'full' mode carries the last price, the day's cumulative volume and the order book. A tick counts as ONE
print when the cumulative volume rose since the previous tick; its size is that rise. Kite sends snapshots (about one a
second per instrument), so one print can hold several exchange trades: the counts are tick-level, not exchange trades.

Side (Lee–Ready, the same rule as tick_flow.classify), against the PREVIOUS tick's best bid/ask (the quote before the trade):
  * price >= previous ask → ask (buyer-initiated); <= previous bid → bid (seller-initiated);
  * strictly inside the spread: above the mid → ask, below → bid, at the mid → the tick test;
  * no usable previous bid/ask (missing, zero or crossed) → the tick test;
  * tick test: against the previous tick's price — up → ask, down → bid, unchanged → the last counted print's side; no side
    yet → not counted (in neither count).
Only the continuous session counts (after 09:15:00 up to 15:30:00 IST): a tick at or before 09:15:00 only sets the baseline,
so the opening call auction is never classified; the first tick after a pre-open baseline is a baseline too (the auction
volume may arrive in it). After 15:30:00 the counts stay as they are. A new IST day starts from zero. `rebase()` (after a
WebSocket reconnect) makes every stock's next tick a baseline, so volume traded while the socket was down is never put on one
side; such volume is simply not counted, which is visible as (ask_volume + bid_volume) < the day's volume.

Switch: KITE_FEED_TRADE_SIDES=1 on, =0 off; unset → on only when APP_ENV=staging (it puts the cash stocks in 'full' mode).
Thread-safe: ticks arrive on the KiteTicker thread, REST quotes read `counts` on the event loop.
"""
from __future__ import annotations

import math
import os
import threading
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Mapping, Optional

from .config import CLOSE, IST, OPEN

ENV = "KITE_FEED_TRADE_SIDES"
FIELDS = ("ask_trades", "bid_trades", "ask_volume", "bid_volume", "sides_since")


def enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    flag = (env.get(ENV) or "").strip()
    if flag == "0":
        return False
    return flag == "1" or (env.get("APP_ENV") or "").strip().lower() == "staging"


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def classify(ltp: float, bid: Optional[float], ask: Optional[float], prev_ltp: Optional[float], prev_side: int) -> int:
    """+1 ask (buyer-initiated), -1 bid (seller-initiated), 0 unknown. bid/ask are the PREVIOUS tick's."""
    if bid is not None and ask is not None and bid > 0 and ask > 0 and ask >= bid:
        if ltp >= ask:
            return 1
        if ltp <= bid:
            return -1
        mid = (bid + ask) / 2.0
        if ltp > mid:
            return 1
        if ltp < mid:
            return -1
    if prev_ltp is None:
        return 0
    if ltp > prev_ltp:
        return 1
    if ltp < prev_ltp:
        return -1
    return prev_side


@dataclass
class _State:
    day: date
    since: str                          # receive time (IST ISO) of the first baseline today
    ask_trades: int = 0
    bid_trades: int = 0
    ask_volume: float = 0.0
    bid_volume: float = 0.0
    volume: Optional[float] = None      # cumulative volume at the previous tick (None = next tick is a baseline)
    bid: Optional[float] = None         # the previous tick's best bid / ask
    ask: Optional[float] = None
    ltp: Optional[float] = None         # the previous tick's price (tick test)
    side: int = 0                       # the last counted print's side
    pre_open: bool = False              # the baseline was taken at or before 09:15:00

    def out(self) -> Dict[str, Any]:
        return {"ask_trades": self.ask_trades, "bid_trades": self.bid_trades, "ask_volume": int(self.ask_volume),
                "bid_volume": int(self.bid_volume), "sides_since": self.since}


def _phase(at: datetime) -> int:
    """-1 at or before 09:15:00 IST, 0 in the continuous session, 1 after 15:30:00."""
    t = at.astimezone(IST).time()
    if t <= OPEN:
        return -1
    return 0 if t <= CLOSE else 1


class TradeSides:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._s: Dict[str, _State] = {}

    def on_tick(self, sym: str, day: date, ltp: Any, volume: Any, bid: Any, ask: Any, at: datetime) -> Dict[str, Any]:
        """Count this tick into `sym`'s day and return the day's running counts (see the module docstring)."""
        price, vol, b, a = _num(ltp), _num(volume), _num(bid), _num(ask)
        phase = _phase(at)
        with self._lock:
            s = self._s.get(sym)
            if s is None or s.day != day:
                s = self._s[sym] = _State(day=day, since=at.astimezone(IST).isoformat(timespec="seconds"))
            if phase > 0:
                return s.out()
            if s.volume is None or (s.pre_open and phase == 0) or phase < 0:
                s.volume, s.bid, s.ask, s.ltp, s.pre_open = vol, b, a, price, phase < 0
                if not (s.ask_trades or s.bid_trades):
                    s.since = at.astimezone(IST).isoformat(timespec="seconds")     # counting starts after this tick
                return s.out()
            if vol is not None and price is not None and price > 0:
                if vol < s.volume:
                    return s.out()          # an out-of-order tick: neither counted nor a new baseline
                delta = vol - s.volume
                if delta > 0:
                    side = classify(price, s.bid, s.ask, s.ltp, s.side)
                    if side > 0:
                        s.ask_trades += 1
                        s.ask_volume += delta
                    elif side < 0:
                        s.bid_trades += 1
                        s.bid_volume += delta
                    s.side = side
                s.volume = vol
            if price is not None and price > 0:
                s.ltp = price
            s.bid, s.ask = b, a
            return s.out()

    def counts(self, sym: str, day: date) -> Optional[Dict[str, Any]]:
        """The day's counts so far without a tick (None when this stock has none today)."""
        with self._lock:
            s = self._s.get(sym)
            return s.out() if s is not None and s.day == day else None

    def rebase(self) -> None:
        """Every stock's next tick becomes a baseline (after a reconnect); the counts so far are kept."""
        with self._lock:
            for s in self._s.values():
                s.volume = None
