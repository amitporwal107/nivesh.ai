"""Early signals, alerts and trading plans of the Scan dashboard (docs/scan_builder/DESIGN.md §10).

A SIGNAL is a stock entering one of the dashboard's stock lists during the session: recorded once per (day, widget, stock)
with the time first seen and the live price then, only from a list whose every condition was applied (a list still waiting
for its intraday candles shows daily-only survivors and would raise false alerts). Each signal carries a PLAN (rules
`scan-plan-v1`, frozen at the moment of the signal) in the words the owner chose for this screen on 3 Nov 2026: Entry,
Stop loss, Target 1, Target 2. Rule-based levels, not advice; no accuracy is claimed.

Plan (rules `scan-plan-v2`, owner 3 Nov ~20:50 IST, from the early-signals study's typical move after a flag — a median further
rise of ~1.0–1.5 % and a dip of ~0.6 %): long — Entry = the live price when first seen; Stop loss = Entry − 1 %; Target 1 =
Entry + 1.5 %; Target 2 = Entry + 3 % (reward : risk 1.5 and 3.0). A falling F&O stock in the two "Open interest" lists gets
the short mirror (Stop loss + 1 %, targets −1.5 % / −3 %). Every signal with a live price gets a plan.

Storage (Redis, shared by the 4 workers; first writer wins):
    nivesh:sb:signals:<day>:s:<widget>:<SYMBOL>   the signal (JSON), SET NX, TTL 3 days
    nivesh:sb:signals:<day>:index                 RPUSH of the keys in the order recorded
    nivesh:sb:signals:leader                      the worker that computes the dashboard every LOOP_S in the session
Without Redis each worker keeps its own list (tests, local runs).

Early even with nobody watching: start() runs a loop on every worker; the one holding the leader lock calls
market_dashboard.get_dashboard every LOOP_S from 09:15 to 15:30 IST, which records signals. On by default where
APP_ENV=staging; SCAN_SIGNALS_ENABLED=0 turns it off, =1 turns it on elsewhere.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Set

import numpy as np

from services.kite_live_feed import config as cfg

from . import engine
from . import spec as S

logger = logging.getLogger(__name__)

PLAN_RULES = "scan-plan-v2"
RULES_TEXT = ("Entry = the live price when the stock entered the list; Stop loss = Entry − 1 %; Target 1 = Entry + 1.5 %; "
              "Target 2 = Entry + 3 % (reward : risk 1.5 and 3.0). Falling F&O stocks in the Open interest lists: the short "
              "mirror. Levels sized from the 3 Nov early-signals study's typical move after a flag.")
CAVEAT = ("Rule-based levels from fixed settings (scan-plan-v2), frozen when the signal was recorded. Not investment advice; no "
          "accuracy or hit rate is claimed. A stop loss is a level, not an executable price: an order can fill worse in a gap.")
STOP_PCT, T1_PCT, T2_PCT = 1.0, 1.5, 3.0
ATR_N = 14
SWING_N = 20
AT_OPEN_UNTIL = (9, 20)                 # first seen by 09:20 IST = "at open"
SHORT_WIDGETS = {"open_interest", "oi_7"}   # F&O-only lists whose conditions also pass falling stocks
TTL_S = 3 * 86400
MAX_LISTED = 300
LOOP_S = 15.0
LEADER_TTL_S = 45
PREFIX = "nivesh:sb:signals:"
IST = cfg.IST


# ── the plan ────────────────────────────────────────────────────────────────────────────────────────────────────────

def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _r(v: Optional[float]) -> Optional[float]:
    return None if v is None else round(v, 2)


def make_plan(direction: str, entry: Any, day_low: Any = None, day_high: Any = None, atr: Any = None,
              swing_high: Any = None, swing_low: Any = None) -> Dict[str, Any]:
    """The plan of one signal (scan-plan-v2, above). The other inputs are kept for the record of the stock's day; the levels
    use the Entry only. Never raises; without a live price plan_ok is False with a plan_note."""
    e = _f(entry)
    out: Dict[str, Any] = {"direction": direction, "entry": _r(e), "stop_loss": None, "target_1": None, "target_2": None,
                           "risk_per_share": None, "rr_1": None, "rr_2": None, "stop_basis": None, "target_1_basis": None,
                           "plan_ok": False, "plan_note": None, "day_low": _r(_f(day_low)), "day_high": _r(_f(day_high)),
                           "atr": _r(_f(atr))}
    if e is None or e <= 0:
        out["plan_note"] = "No live price when the signal was recorded, so no plan."
        return out
    sign = 1 if direction == "long" else -1
    stop = e * (1 - sign * STOP_PCT / 100)
    t1, t2 = e * (1 + sign * T1_PCT / 100), e * (1 + sign * T2_PCT / 100)
    risk = abs(e - stop)
    out.update(stop_loss=_r(stop), target_1=_r(t1), target_2=_r(t2), risk_per_share=_r(risk),
               rr_1=round(T1_PCT / STOP_PCT, 2), rr_2=round(T2_PCT / STOP_PCT, 2),
               stop_basis=f"Entry {'−' if sign > 0 else '+'} {STOP_PCT:g} %",
               target_1_basis=f"Entry {'+' if sign > 0 else '−'} {T1_PCT:g} %", plan_ok=True)
    return out


def _plan_spec(limit: int) -> Dict[str, Any]:
    m, x = S.measure, S.expr
    col = lambda cid, e: {"id": cid, "alias": cid, "enabled": True, "format": "number", "expr": e}
    return S.validate({"version": 1, "name": "plan inputs", "description": "", "filters": S.group("root", [], universe="cash"),
                       "columns": [col("c_close", x(m("close"))), col("c_low", x(m("low"))), col("c_high", x(m("high"))),
                                   col("c_atr", x(m("atr", 1, period=ATR_N))),
                                   col("c_hi", x(m("max", 1, source="high", period=SWING_N))),
                                   col("c_lo", x(m("min", 1, source="low", period=SWING_N))),
                                   col("c_chg", x(m("close"), "-", m("close", 1), "/", m("close", 1), "*", S.number(100)))],
                       "sort": {"column": "c_close", "dir": "desc"}, "limit": limit})


def plan_inputs(panel: engine.Panel, symbols: Sequence[str]) -> Dict[str, Dict[str, Optional[float]]]:
    """{symbol: close, low, high, atr, swing_high, swing_low, chg} for `symbols`, from the engine on the dashboard's panel."""
    pos = {s: i for i, s in enumerate(panel.symbols)}
    want = [s for s in dict.fromkeys(symbols) if s in pos]
    out: Dict[str, Dict[str, Optional[float]]] = {}
    keys = ("close", "low", "high", "atr", "swing_high", "swing_low", "chg")
    for i in range(0, len(want), 500):
        chunk = want[i:i + 500]
        elig = np.zeros(len(panel.symbols), dtype=bool)
        for s in chunk:
            elig[pos[s]] = True
        res = engine.evaluate(_plan_spec(len(chunk)), panel, eligible=elig,
                              universes={"cash": np.ones(len(panel.symbols), dtype=bool)}, fundamentals={})
        for j, vals in zip(res["order"], res["values"]):
            out[panel.symbols[j]] = dict(zip(keys, vals))
    return out


# ── storage ─────────────────────────────────────────────────────────────────────────────────────────────────────────

class LocalSignalStore:
    """One process's store (tests, no Redis)."""

    def __init__(self) -> None:
        self.kv: Dict[str, str] = {}
        self.lists: Dict[str, List[str]] = {}
        self.leader: Optional[str] = None
        self.leader_until = 0.0

    async def add(self, key: str, index: str, value: str, ttl: int) -> bool:
        if key in self.kv:
            return False
        self.kv[key] = value
        self.lists.setdefault(index, []).append(key)
        return True

    async def read(self, index: str, last: int) -> List[str]:
        keys = self.lists.get(index, [])[-last:]
        return [self.kv[k] for k in keys if k in self.kv]

    async def lead(self, key: str, me: str, ttl: int, now: float) -> bool:
        if self.leader in (None, me) or now >= self.leader_until:
            self.leader, self.leader_until = me, now + ttl
            return True
        return False


class RedisSignalStore:
    """The shared store (the live quote cache's Redis). A failed Redis call is logged and treated as 'not stored'."""

    def __init__(self, getter: Optional[Callable[[], Awaitable[Any]]] = None) -> None:
        if getter is None:
            from .intraday import _redis_client as getter
        self._getter = getter

    async def add(self, key: str, index: str, value: str, ttl: int) -> bool:
        try:
            c = await asyncio.wait_for(self._getter(), 4.0)
            if not await asyncio.wait_for(c.set(key, value, nx=True, ex=ttl), 2.0):
                return False
            await asyncio.wait_for(c.rpush(index, key), 2.0)
            await asyncio.wait_for(c.expire(index, ttl), 2.0)
            return True
        except Exception as e:  # noqa: BLE001 — a signal not stored this run is tried again on the next one
            logger.warning("scan signals: redis write failed (%s)", type(e).__name__)
            return False

    async def read(self, index: str, last: int) -> List[str]:
        try:
            c = await asyncio.wait_for(self._getter(), 4.0)
            keys = await asyncio.wait_for(c.lrange(index, -last, -1), 2.0)
            if not keys:
                return []
            vals = await asyncio.wait_for(c.mget(keys), 2.0)
            return [v.decode() if isinstance(v, bytes) else v for v in vals if v]
        except Exception as e:  # noqa: BLE001 — the dashboard answers without the feed and says so
            logger.warning("scan signals: redis read failed (%s)", type(e).__name__)
            raise

    async def lead(self, key: str, me: str, ttl: int, now: float) -> bool:
        try:
            c = await asyncio.wait_for(self._getter(), 4.0)
            if await asyncio.wait_for(c.set(key, me, nx=True, ex=ttl), 2.0):
                return True
            holder = await asyncio.wait_for(c.get(key), 2.0)
            holder = holder.decode() if isinstance(holder, bytes) else holder
            if holder == me:
                await asyncio.wait_for(c.expire(key, ttl), 2.0)
                return True
            return False
        except Exception as e:  # noqa: BLE001 — no leader this round; the next round tries again
            logger.warning("scan signals: leader check failed (%s)", type(e).__name__)
            return False


_store: Any = None


def get_store() -> Any:
    global _store
    if _store is None:
        _store = RedisSignalStore()
    return _store


# ── recording and reading ───────────────────────────────────────────────────────────────────────────────────────────

_seen: Dict[str, Set[str]] = {}            # this process: day -> widget:symbol already handled


def _day_keys(day: str):
    return f"{PREFIX}{day}:index", f"{PREFIX}{day}:s:"


def recordable(widget: Dict[str, Any]) -> bool:
    """A stock list whose every condition was applied: its rows passed everything (a Partial list still waiting for its
    candles shows daily-only survivors and is not used; one that only left out stocks without candles is)."""
    return (widget.get("row_kind") == "symbol" and widget.get("status") in ("ok", "partial")
            and bool(widget.get("rows")) and all(c.get("applied", True) for c in widget.get("criteria") or []))


async def record(widgets: Sequence[Dict[str, Any]], inputs_for: Callable[[Sequence[str]], Dict[str, Dict[str, Any]]],
                 now: datetime, *, store: Any = None) -> List[Dict[str, Any]]:
    """Record the stocks newly in a recordable list. `inputs_for(symbols)` gives plan_inputs. Returns the signals this call
    stored (another worker may have stored the rest first)."""
    store = store or get_store()
    ist = now.astimezone(IST)
    day = ist.date().isoformat()
    seen = _seen.setdefault(day, set())
    for d in list(_seen):
        if d != day:
            del _seen[d]
    fresh = [(w, r[0]) for w in widgets if recordable(w) for r in w["rows"]
             if isinstance(r[0], str) and f"{w['id']}:{r[0]}" not in seen]
    if not fresh:
        return []
    inputs = await asyncio.to_thread(inputs_for, [s for _, s in fresh])
    index, kp = _day_keys(day)
    at_open = (ist.hour, ist.minute) <= AT_OPEN_UNTIL
    stored = []
    for w, sym in fresh:
        sid = f"{w['id']}:{sym}"
        inp = inputs.get(sym) or {}
        direction = "short" if w["id"] in SHORT_WIDGETS and (_f(inp.get("chg")) or 0.0) < 0 else "long"
        sig = {"id": sid, "widget_id": w["id"], "widget_title": w.get("title"), "symbol": sym,
               "first_seen": ist.isoformat(timespec="seconds"), "at_open": at_open, "rules": PLAN_RULES,
               **make_plan(direction, inp.get("close"), inp.get("low"), inp.get("high"), inp.get("atr"),
                           inp.get("swing_high"), inp.get("swing_low"))}
        if await store.add(kp + sid, index, json.dumps(sig), TTL_S):
            stored.append(sig)
        seen.add(sid)
    return stored


async def today(now: datetime, prices: Dict[str, float], *, store: Any = None) -> Dict[str, Any]:
    """{signals (newest first, with price_now and move_since_pct from `prices`), error} for the IST day of `now`."""
    store = store or get_store()
    day = now.astimezone(IST).date().isoformat()
    index, _ = _day_keys(day)
    try:
        raw = await store.read(index, MAX_LISTED)
    except Exception:  # noqa: BLE001 — logged by the store
        return {"signals": [], "error": "The signal list could not be read just now."}
    out = []
    for v in raw:
        try:
            sig = json.loads(v)
        except ValueError:
            logger.warning("scan signals: an unreadable signal was skipped")
            continue
        p, e = _f(prices.get(sig.get("symbol"))), _f(sig.get("entry"))
        sig["price_now"] = _r(p)
        sig["move_since_pct"] = _r(((p - e) / e * 100) if p is not None and e else None)   # the price's move, either direction
        out.append(sig)
    out.sort(key=lambda s: s.get("first_seen") or "", reverse=True)
    return {"signals": out, "error": None}


# ── the loop that keeps signals early ───────────────────────────────────────────────────────────────────────────────

_task: Optional[asyncio.Task] = None
_ME = f"{os.getpid()}:{uuid.uuid4().hex[:8]}"


def enabled(env: Optional[Dict[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    flag = (env.get("SCAN_SIGNALS_ENABLED") or "").strip()
    if flag == "0":
        return False
    return flag == "1" or (env.get("APP_ENV") or "").strip().lower() == "staging"


def in_session(now: datetime) -> bool:
    ist = now.astimezone(IST)
    return ist.weekday() < 5 and (9, 15) <= (ist.hour, ist.minute) < (15, 31)


async def loop_once(now: datetime, *, store: Any = None, run: Optional[Callable[[], Awaitable[Any]]] = None,
                    me: str = _ME) -> bool:
    """One round: in the session and holding the leader lock → compute the dashboard (which records signals). True if it ran."""
    if not in_session(now):
        return False
    store = store or get_store()
    if not await store.lead(PREFIX + "leader", me, LEADER_TTL_S, time.time()):
        return False
    if run is None:
        from . import market_dashboard
        from .data import get_data

        async def run() -> None:                                    # every tab: each one's lists raise signals
            for key in market_dashboard.DASHBOARDS:
                await market_dashboard.get_dashboard(get_data(), dashboard=key)
    await run()
    return True


async def _loop() -> None:
    while True:
        try:
            ran = await loop_once(datetime.now(timezone.utc))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — one failed round never stops the loop; logged with its trace
            logger.exception("scan signals: a round failed")
            ran = False
        await asyncio.sleep(LOOP_S if ran or in_session(datetime.now(timezone.utc)) else 60.0)


def start() -> bool:
    """Start the loop on this worker when enabled (server startup). True if started."""
    global _task
    if not enabled() or (_task is not None and not _task.done()):
        return False
    _task = asyncio.get_running_loop().create_task(_loop())
    logger.info("scan signals: loop started (every %.0f s in the session, one leader across workers)", LOOP_S)
    return True


def stop() -> None:
    if _task is not None and not _task.done():
        _task.cancel()
