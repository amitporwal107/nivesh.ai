"""Early signals, alerts and trading plans of the Scan dashboard (docs/scan_builder/DESIGN.md §10, §11).

A SIGNAL is a stock entering one of the dashboard's stock lists during the session: recorded once per (day, widget, stock)
with the time first seen and the live price then, only from a list whose every condition was applied (a list still waiting
for its intraday candles shows daily-only survivors and would raise false alerts). Plan words (Entry, Stop loss, Target 1,
Target 2) are the owner's choice for this screen (3 Nov 2026). Rule-based levels, not advice; no accuracy is claimed.

Since 4 Nov 2026 (owner: positional, not intraday; only signals with strength above 70 — DESIGN.md §11) a list entry
carries NO plan: it records the stock, the list, the time and the live price then (for "move since"). The stock's strength
(signal_strength.py) is recomputed on every refresh; the first time a long stock's score reaches 70 it becomes a STRONG
SIGNAL, recorded once per (day, stock) with the score, its parts and reasons, and the positional plan (scan-plan-v3) frozen
at the live price then. Only strong signals alert. The intraday plan v2 (Entry − 1 % …) is retired.

Storage (Redis, shared by the 4 workers; first writer wins):
    nivesh:sb:signals:<day>:s:<widget>:<SYMBOL>   the signal (JSON), SET NX, TTL 3 days
    nivesh:sb:signals:<day>:index                 RPUSH of the keys in the order recorded
    nivesh:sb:signals:<day>:g:<SYMBOL>            a strong signal (JSON), SET NX, TTL 3 days
    nivesh:sb:signals:<day>:strong                RPUSH of the strong-signal keys in the order recorded
    nivesh:sb:signals:<day>:scores                the day's scores (JSON {as_of, scores}), rewritten by the leader, TTL 3 days
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
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

from services.kite_live_feed import config as cfg

from . import engine
from . import spec as S

logger = logging.getLogger(__name__)

LIST_RULES = "scan-list-mark"
RULES_TEXT = ("A list mark = a stock joining one of the lists in the session, with the live price then. Plans go only to "
              "strong signals (score ≥ 70); see the score rules.")
NO_PLAN_NOTE = "Plans go to strong signals only (score ≥ 70)."
ATR_N = 14
SWING_N = 20
AT_OPEN_UNTIL = (9, 20)                 # first seen by 09:20 IST = "at open"
SHORT_WIDGETS = {"open_interest", "oi_7"}   # F&O-only lists whose conditions also pass falling stocks
TTL_S = 3 * 86400
MAX_LISTED = 300
MAX_STRONG = 200
MAX_DAY = 5000                          # list marks read for a whole day (4 Nov 2026: 2,111 by 14:35)
LOOP_S = 15.0
LEADER_TTL_S = 45
PREFIX = "nivesh:sb:signals:"
STRONG_THRESHOLD = 70                   # = signal_strength.THRESHOLD (kept here so this module does not import it)
IST = cfg.IST


# ── the list entry ──────────────────────────────────────────────────────────────────────────────────────────────────

def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _r(v: Optional[float]) -> Optional[float]:
    return None if v is None else round(v, 2)


def list_entry(direction: str, price: Any, day_low: Any = None, day_high: Any = None, atr: Any = None) -> Dict[str, Any]:
    """A list entry's fields: the live price when first seen (kept as `entry` for "move since") and the stock's day; no plan
    (plan fields null, plan_ok False with NO_PLAN_NOTE)."""
    return {"direction": direction, "entry": _r(_f(price)), "stop_loss": None, "target_1": None, "target_2": None,
            "risk_per_share": None, "rr_1": None, "rr_2": None, "stop_basis": None, "target_1_basis": None,
            "plan_ok": False, "plan_note": NO_PLAN_NOTE, "day_low": _r(_f(day_low)), "day_high": _r(_f(day_high)),
            "atr": _r(_f(atr))}


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

    async def put(self, key: str, value: str, ttl: int) -> bool:
        self.kv[key] = value
        return True

    async def get(self, key: str) -> Optional[str]:
        return self.kv.get(key)

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

    async def put(self, key: str, value: str, ttl: int) -> bool:
        try:
            c = await asyncio.wait_for(self._getter(), 4.0)
            await asyncio.wait_for(c.set(key, value, ex=ttl), 2.0)
            return True
        except Exception as e:  # noqa: BLE001 — the next round writes again
            logger.warning("scan signals: redis write failed (%s)", type(e).__name__)
            return False

    async def get(self, key: str) -> Optional[str]:
        try:
            c = await asyncio.wait_for(self._getter(), 4.0)
            v = await asyncio.wait_for(c.get(key), 2.0)
            return v.decode() if isinstance(v, bytes) else v
        except Exception as e:  # noqa: BLE001
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

def _to_spt(day: str, kind: str, stored: List[Dict[str, Any]], store: Any) -> None:
    """Hand the marks this call stored to SPT ingest (services/spt/signals/hook.py): scheduled as a task, never awaited here,
    never raises (its own catch-up ingests anything missed). Off unless SPT_INGEST_ENABLED / APP_ENV=staging."""
    if not stored:
        return
    try:
        from services.spt.signals import hook
        hook.after_store(day, kind, stored, store)
    except Exception as e:  # noqa: BLE001 — the scan loop never fails because of SPT
        logger.warning("scan signals: SPT hand-off failed (%s)", type(e).__name__)


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
               "first_seen": ist.isoformat(timespec="seconds"), "at_open": at_open, "rules": LIST_RULES,
               **list_entry(direction, inp.get("close"), inp.get("low"), inp.get("high"), inp.get("atr"))}
        if await store.add(kp + sid, index, json.dumps(sig), TTL_S):
            stored.append(sig)
        seen.add(sid)
    _to_spt(day, "list", stored, store)
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


# ── strong signals (score ≥ 70, DESIGN.md §11) ──────────────────────────────────────────────────────────────────────

def _strong_keys(day: str):
    return f"{PREFIX}{day}:strong", f"{PREFIX}{day}:g:"


_seen_strong: Dict[str, Set[str]] = {}


async def record_strong(candidates: Sequence[Dict[str, Any]], now: datetime, *, store: Any = None) -> List[Dict[str, Any]]:
    """Record each candidate stock as today's strong signal unless one exists (first writer wins across workers). A candidate
    is the frozen record (symbol, score_at, parts_at, reasons_at, lists_at and the scan-plan-v3 fields). Returns those stored
    by this call."""
    store = store or get_store()
    ist = now.astimezone(IST)
    day = ist.date().isoformat()
    seen = _seen_strong.setdefault(day, set())
    for d in list(_seen_strong):
        if d != day:
            del _seen_strong[d]
    index, kp = _strong_keys(day)
    stored = []
    for c in candidates:
        sym = c.get("symbol")
        if not sym or sym in seen:
            continue
        rec = {**c, "id": f"strong:{sym}", "first_strong": ist.isoformat(timespec="seconds")}
        if await store.add(kp + sym, index, json.dumps(rec), TTL_S):
            stored.append(rec)
        seen.add(sym)
    _to_spt(day, "strong", stored, store)
    return stored


async def strong_today(now: datetime, prices: Dict[str, float], scores: Dict[str, Dict[str, Any]], *,
                       store: Any = None) -> Dict[str, Any]:
    """{strong (newest first, with price_now, move_since_pct, score_now, parts_now), error} for the IST day of `now`."""
    store = store or get_store()
    day = now.astimezone(IST).date().isoformat()
    index, _ = _strong_keys(day)
    try:
        raw = await store.read(index, MAX_STRONG)
    except Exception:  # noqa: BLE001 — logged by the store
        return {"strong": [], "error": "The strong-signal list could not be read just now."}
    out = []
    for v in raw:
        try:
            rec = json.loads(v)
        except ValueError:
            logger.warning("scan signals: an unreadable strong signal was skipped")
            continue
        sym = rec.get("symbol")
        p, e = _f(prices.get(sym)), _f(rec.get("entry"))
        now_s = scores.get(sym) or {}
        rec.update(price_now=_r(p), move_since_pct=_r(((p - e) / e * 100) if p is not None and e else None),
                   score_now=now_s.get("score"), parts_now=now_s.get("parts"))
        out.append(rec)
    out.sort(key=lambda r: r.get("first_strong") or "", reverse=True)
    return {"strong": out, "error": None}


# ── a whole day, grouped by company (DESIGN.md §11.1) ──────────────────────────────────────────────────────────────

def _parse(raw: Sequence[str], what: str) -> List[Dict[str, Any]]:
    out = []
    for v in raw:
        try:
            out.append(json.loads(v))
        except ValueError:
            logger.warning("scan signals: an unreadable %s was skipped", what)
    return out


async def day_marks(day: str, *, store: Any = None) -> List[Dict[str, Any]]:
    """Every list mark of `day` (ISO), oldest first. Raises when the store cannot be read."""
    store = store or get_store()
    index, _ = _day_keys(day)
    marks = _parse(await store.read(index, MAX_DAY), "signal")
    marks.sort(key=lambda m: m.get("first_seen") or "")
    return marks


def _scores_key(day: str) -> str:
    return f"{PREFIX}{day}:scores"


async def save_scores(day: str, scores: Dict[str, Dict[str, Any]], now: datetime, *, store: Any = None) -> bool:
    """Store the day's scores (as they stand at `now`) for the day view; each stock keeps what the view shows."""
    store = store or get_store()
    keep = ("name", "score", "parts", "reasons", "penalties", "note")
    doc = {"as_of": now.astimezone(IST).isoformat(timespec="seconds"),
           "scores": {sym: {k: (r.get(k)[:3] if k == "reasons" and r.get(k) else r.get(k)) for k in keep}
                      for sym, r in scores.items()}}
    return await store.put(_scores_key(day), json.dumps(doc), TTL_S)


async def load_scores(day: str, *, store: Any = None) -> Dict[str, Any]:
    store = store or get_store()
    raw = await store.get(_scores_key(day))
    if not raw:
        return {"as_of": None, "scores": {}}
    try:
        return json.loads(raw)
    except ValueError:
        logger.warning("scan signals: the stored scores were unreadable")
        return {"as_of": None, "scores": {}}


def group_day(marks: Sequence[Dict[str, Any]], strong: Sequence[Dict[str, Any]], scores: Dict[str, Dict[str, Any]]
              ) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """Companies (newest activity first) with their marks oldest first, score and strong record; and {widget_id: title}."""
    lists: Dict[str, str] = {}
    by: Dict[str, Dict[str, Any]] = {}
    strong_by = {r.get("symbol"): r for r in strong if r.get("symbol")}
    plan_keys = ("first_strong", "score_at", "entry", "stop_loss", "target_1", "target_2", "risk_per_share", "rr_1", "rr_2",
                 "atr", "sma20", "trend_exit", "plan_ok", "plan_note", "rules")
    for m in sorted(marks, key=lambda x: x.get("first_seen") or ""):
        sym, wid, when = m.get("symbol"), m.get("widget_id"), m.get("first_seen") or ""
        if not sym or not wid:
            continue
        lists.setdefault(wid, m.get("widget_title") or wid)
        sc = scores.get(sym) or {}
        c = by.get(sym)
        if c is None:
            st = strong_by.get(sym)
            c = by[sym] = {"symbol": sym, "name": sc.get("name") or (st or {}).get("name") or "",
                           "score": sc.get("score"), "parts": sc.get("parts"), "reasons": (sc.get("reasons") or [])[:3],
                           "penalties": sc.get("penalties") or [], "note": sc.get("note"),
                           "strong": {k: st.get(k) for k in plan_keys} if st else None,
                           "first_seen": when, "last_seen": when, "n": 0, "marks": []}
        c["marks"].append({"time": when[11:19], "list": wid, "price": m.get("entry"), "direction": m.get("direction")})
        c["n"] += 1
        c["last_seen"] = max(c["last_seen"], when)
    companies = sorted(by.values(), key=lambda c: c["last_seen"], reverse=True)
    return companies, lists


async def day_view(day: str, *, store: Any = None) -> Dict[str, Any]:
    """The answer of GET /signals/day: every list mark of `day` grouped by company. A store that cannot be read gives an empty
    day and a warning, never an exception."""
    store = store or get_store()
    warnings: List[str] = []
    try:
        marks = await day_marks(day, store=store)
    except Exception:  # noqa: BLE001 — logged by the store
        return {"ok": True, "day": day, "count": 0, "companies_count": 0, "threshold": STRONG_THRESHOLD, "scores_as_of": None,
                "lists": {}, "companies": [], "warnings": ["The day's signals could not be read just now."]}
    try:
        strong_index, _ = _strong_keys(day)
        strong = _parse(await store.read(strong_index, MAX_STRONG), "strong signal")
    except Exception:  # noqa: BLE001
        strong = []
        warnings.append("The day's strong signals could not be read just now.")
    try:
        doc = await load_scores(day, store=store)
    except Exception:  # noqa: BLE001
        doc = {"as_of": None, "scores": {}}
        warnings.append("The day's scores could not be read just now.")
    if marks and not doc.get("scores"):
        warnings.append("Scores for this day are not stored yet; they appear after the next dashboard refresh.")
    companies, lists = group_day(marks, strong, doc.get("scores") or {})
    return {"ok": True, "day": day, "count": len(marks), "companies_count": len(companies), "threshold": STRONG_THRESHOLD,
            "scores_as_of": doc.get("as_of"), "lists": lists, "companies": companies, "warnings": warnings}


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
