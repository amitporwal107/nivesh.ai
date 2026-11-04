"""In-memory stand-ins and builders shared by the SPT slice-A suites (tests/test_spt_a_*.py).

MOCK — not real data, except where a test says it copied a record from the 4 Nov 2026 Redis dump
(/home/deploy/nivesh-signal-archive/redis_dump_20261105.jsonl: market-wide scanner output, no user data).

    Coll / DB      tests/test_desk_trading.FakeCollection (Mongo filter/update semantics from tests/mongo_ops.py) plus
                   update_many, a projection argument on find, and string index keys (events.py indexes "idempotency_key")
    Inputs         a MarketInputs whose bars and regime come from dicts (no data platform)
    mark / strong  list marks and strong records shaped exactly like services/scan_builder/signals.record / record_strong
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from services.spt import events as spt_events
from services.spt.opportunities import consolidate as cons
from services.spt.opportunities import inputs as inputs_mod
from services.spt.opportunities import store as opp_store
from services.spt.signals import hook
from services.spt.signals import store as sig_store
from tests import mongo_ops
from tests.test_desk_trading import FakeCollection, _Result

IST = timezone(timedelta(hours=5, minutes=30))
DAY = "2026-11-04"                                                    # a Wednesday
D = date(2026, 11, 4)


def ist(h: int, m: int, s: int = 0, day: date = D) -> datetime:
    return datetime(day.year, day.month, day.day, h, m, s, tzinfo=IST)


class Coll(FakeCollection):
    async def create_index(self, keys, **kw):
        if isinstance(keys, str):
            keys = [(keys, 1)]
        return await super().create_index(keys, **kw)

    def find(self, query, projection=None):
        return super().find(query)

    async def update_many(self, query, update):
        n = 0
        for d in self.docs:
            if mongo_ops.match(d, query):
                mongo_ops.apply(d, update)
                n += 1
        self.writes += n
        return _Result(matched=n)


class DB:
    def __init__(self):
        self.c: Dict[str, Coll] = {}

    def __getitem__(self, name: str) -> Coll:
        return self.c.setdefault(name, Coll())

    def __getattr__(self, name: str) -> Coll:
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]

    @property
    def writes(self) -> int:
        return sum(c.writes for c in self.c.values())


def reset_module_state() -> None:
    """Module-level caches that would leak between tests."""
    spt_events._indexed = False
    sig_store._indexed = False
    opp_store._indexed = False
    hook._known.clear()
    cons._handled.clear()


def events_of(db: DB, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
    return [e for e in db["spt_events"].docs if event_type is None or e["event_type"] == event_type]


# ── scanner records, shaped like services/scan_builder/signals.py stores them (MOCK) ─────────────────────────────────

def mark(widget: str, sym: str, at: datetime, price: Any = 100.0, *, direction: str = "long",
         title: Optional[str] = None) -> Dict[str, Any]:
    return {"id": f"{widget}:{sym}", "widget_id": widget, "widget_title": title or widget, "symbol": sym,
            "first_seen": at.astimezone(IST).isoformat(timespec="seconds"), "at_open": False, "rules": "scan-list-mark",
            "direction": direction, "entry": price, "stop_loss": None, "target_1": None, "target_2": None,
            "risk_per_share": None, "rr_1": None, "rr_2": None, "stop_basis": None, "target_1_basis": None,
            "plan_ok": False, "plan_note": "Plans go to strong signals only (score ≥ 70).", "day_low": None,
            "day_high": None, "atr": 2.0}


def strong(sym: str, at: datetime, entry: float = 100.0, atr: float = 2.0, *, score: int = 75,
           lists: Optional[List[str]] = None, plan_ok: bool = True) -> Dict[str, Any]:
    risk = 2 * atr
    return {"symbol": sym, "name": f"{sym} Ltd", "score_at": score,
            "parts_at": {"quality": 25, "trend": 20, "reason": 14, "size": 10, "participation": 6, "penalty": 0},
            "reasons_at": ["made-up reason"], "penalties_at": [],
            "lists_at": [{"id": w, "title": w} for w in (lists or ["dt_52w_high"])],
            "rules": "scan-plan-v3", "entry": entry, "stop_loss": round(entry - risk, 2) if plan_ok else None,
            "target_1": round(entry + 2 * risk, 2) if plan_ok else None,
            "target_2": round(entry + 4 * risk, 2) if plan_ok else None,
            "risk_per_share": risk if plan_ok else None, "rr_1": 2.0, "rr_2": 4.0, "atr": atr, "sma20": entry - 3,
            "trend_exit": "A daily close below the 20-day average", "plan_ok": plan_ok,
            "plan_note": None if plan_ok else "No ATR(14) for this stock (too little history), so no plan.",
            "id": f"strong:{sym}", "first_strong": at.astimezone(IST).isoformat(timespec="seconds")}


# ── market data (MOCK) ───────────────────────────────────────────────────────────────────────────────────────────────

def weekdays(n: int, end: date) -> List[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def bars_from(closes: List[float], *, end: date, volume: float = 1_000_000.0, rng: float = 1.0,
              volumes: Optional[List[float]] = None) -> List[Dict[str, Any]]:
    days = weekdays(len(closes), end)
    return [{"date": d, "open": c, "high": c + rng, "low": c - rng, "close": c,
             "volume": (volumes[i] if volumes else volume), "series": "EQ"} for i, (d, c) in enumerate(zip(days, closes))]


def rising(n: int = 260, start: float = 50.0, step: float = 0.2, **kw) -> List[Dict[str, Any]]:
    return bars_from([round(start + i * step, 2) for i in range(n)], **kw)


REGIME_BULL = {"available": True, "key": "bullish", "label": "Bullish", "as_of": "2026-11-03", "trend": "up",
               "india_vix": 13.0, "breadth": "up", "rule_version": "desk-regime-v1", "source": "MOCK regime"}


class Inputs(inputs_mod.MarketInputs):
    """MarketInputs over dicts. `bars_by` symbol -> bars, or an Exception instance to raise; `regime` a dict or Exception."""

    def __init__(self, bars_by: Dict[str, Any], regime: Any = None):
        self.bars_by = bars_by
        self.regime_value = REGIME_BULL if regime is None else regime
        self.bar_calls: List[str] = []

        async def fetch(symbol, start):
            self.bar_calls.append(symbol)
            v = self.bars_by.get(symbol, [])
            if isinstance(v, Exception):
                raise v
            return [b for b in v if b["date"] >= start]

        async def reg():
            if isinstance(self.regime_value, Exception):
                raise self.regime_value
            return dict(self.regime_value)

        super().__init__(fetch_bars=fetch, read_regime=reg)
