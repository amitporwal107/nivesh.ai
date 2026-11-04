"""Exit watch (docs/paper_pnl_dashboard/EXIT_WATCH.md; test cases test_reports/exit_watch_TESTCASES.md EW-01..EW-28, EW-31).

Covers services/exit_watch (rules, book, view, store, runner, service) and the two routes on routes/desk_pnl.py.

No network and no real database. What is replaced, and by what:
    Mongo             an in-memory stand-in (tests/test_desk_trading.FakeCollection, plus update_many)
    the broker book   paper_pnl.live.read_broker_book returns a fixed BrokerBook
    prices            the runner's / service's bar and quote readers are injected
    the user          the route's get_current_user reads the X-Test-User header

MOCK — not real data: every symbol, quantity, price, bar and level below is made up (no user's real positions), except the
public HDFCAMC 1:1 bonus close pair (5,336.5 → 2,679.0, ex-date 2025-11-26) used for the series-break cases. Broker codes are
ICICI Direct's own (TATSTE = TATASTEEL, DLFLIM = DLF). Each expected figure is worked out by hand in the test.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from routes import desk_pnl as pnl_route
from services.exit_watch import book as book_mod
from services.exit_watch import rules, runner, service, store, view
from services.paper_pnl import live
from services.scan_builder.signals import LocalSignalStore
from tests import mongo_ops
from tests.test_desk_trading import FakeCollection, _Result

IST = timezone(timedelta(hours=5, minutes=30))
TODAY = date(2026, 11, 4)                                         # a Wednesday
IN_SESSION = datetime(2026, 11, 5, 4, 30, tzinfo=timezone.utc)    # Thu 10:00 IST
EVENING = datetime(2026, 11, 4, 14, 0, tzinfo=timezone.utc)       # Wed 19:30 IST
READ_AT = "2026-11-05T04:29:00+00:00"
UID, OTHER = "user_a", "user_b"
ICICI, ZERODHA = "acc-icici-1", "acc-zerodha-1"


# ── fakes ────────────────────────────────────────────────────────────────────────────────────────────────────────────
class Coll(FakeCollection):
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

    @property
    def writes(self) -> int:
        return sum(c.writes for c in self.c.values())


def run(coro):
    return asyncio.run(coro)


def weekdays(n: int, end: date = TODAY) -> List[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def bars_from(closes: List[float], *, rng: float = 2.0, end: date = TODAY) -> List[Dict[str, Any]]:
    """MOCK bars: high = close + rng/2, low = close − rng/2, so a flat series has TR = rng."""
    return [{"date": d, "open": c, "high": c + rng / 2, "low": c - rng / 2, "close": c, "volume": 1000.0}
            for d, c in zip(weekdays(len(closes), end), closes)]


def row(symbol: str, qty: float, avg: float, *, account: str = ICICI, broker: str = "icicidirect", display: str = "ICICI Direct",
        segment: str = "cash", itype: Optional[str] = None, expiry: Optional[str] = None, strike: Optional[float] = None,
        last: Optional[float] = None) -> Dict[str, Any]:
    """A broker NET position row with the positions workspace's private keys. MOCK."""
    return {"symbol": symbol, "exchange": "NSE" if segment == "cash" else "NFO", "quantity": qty, "avg_price": avg,
            "last_price": last, "segment": segment, "instrument_type": itype, "expiry": expiry, "strike": strike,
            "product_raw": "X", "_account_id": account, "_broker": broker, "_broker_display": display, "_read_at": READ_AT}


def hedge_pair(fut_qty: float = 300, put_qty: float = 300) -> List[Dict[str, Any]]:
    return [row("DLFLIM", fut_qty, 1000.0, segment="fno", itype="FUT", expiry="2026-11-23", last=1010.0),
            row("DLFLIM", put_qty, 20.0, segment="fno", itype="PE", expiry="2026-11-23", strike=980.0, last=18.0)]


# ── EW-01..EW-08: the rule ───────────────────────────────────────────────────────────────────────────────────────────
def test_ew01_wilder_atr_hand_worked():
    flat = bars_from([100.0] * 15)                     # TR 2 on bars 1..14 → first ATR = 2
    assert rules.atr(flat) == pytest.approx(2.0)
    b = flat + [{"date": date(2026, 11, 5), "open": 101, "high": 106.0, "low": 100.0, "close": 103.0}]
    # TR = max(106 − 100, |106 − 100|, |100 − 100|) = 6 → ATR = (2 × 13 + 6) / 14 = 2.2857
    assert rules.atr(b) == pytest.approx(32 / 14, abs=0.01)
    assert rules.atr(flat[:14]) is None                # 14 bars: only 13 TRs


def test_ew02_candidate_both_sides():
    assert rules.candidate(100.0, 2.0, "long") == 96.0
    assert rules.candidate(100.0, 2.0, "short") == 104.0
    assert rules.candidate(179.65, 9.47, "long") == 160.71


def test_ew03_first_stop():
    adv = rules.advance_level(None, bars_from([100.0] * 20), "long")
    assert adv["first"] and adv["stop"] == 96.0 and adv["day"] == "2026-11-04"
    assert len(adv["history"]) == 1 and adv["history"][0]["reason"] == "first stop"


def test_ew04_trail_long_never_loosens():
    base = bars_from([100.0] * 20, end=date(2026, 10, 30))
    up = {"date": date(2026, 11, 2), "open": 103, "high": 105.0, "low": 103.0, "close": 104.0}
    down = {"date": date(2026, 11, 3), "open": 101, "high": 102.0, "low": 100.0, "close": 101.0}
    stored = {"stop": 96.0, "day": "2026-10-30", "history": []}
    a1 = (2 * 13 + 5) / 14                              # TR = max(2, |105 − 100|, |103 − 100|) = 5
    c1 = round(104.0 - 2 * a1, 2)                       # 99.57
    a2 = (a1 * 13 + 4) / 14                             # TR = max(2, |102 − 104|, |100 − 104|) = 4
    c2 = round(101.0 - 2 * a2, 2)                       # 96.32, below the raised stop
    adv = rules.advance_level(stored, base + [up, down], "long")
    assert c1 == 99.57 and c2 == 96.32
    assert adv["stop"] == 99.57 and adv["moved"] is True and adv["day"] == "2026-11-03"
    assert [h["moved"] for h in adv["history"]] == [True, False]
    assert [h["candidate"] for h in adv["history"]] == [c1, c2]


def test_ew05_trail_short_mirrored():
    base = bars_from([100.0] * 20, end=date(2026, 10, 30))
    dn = {"date": date(2026, 11, 2), "open": 96, "high": 97.0, "low": 95.0, "close": 96.0}
    adv = rules.advance_level({"stop": 104.0, "day": "2026-10-30", "history": []}, base + [dn], "short")
    assert adv["stop"] == round(96.0 + 2 * (31 / 14), 2) == 100.43 and adv["moved"] is True
    up = {"date": date(2026, 11, 3), "open": 99, "high": 100.0, "low": 98.0, "close": 99.0}
    adv2 = rules.advance_level({"stop": 100.43, "day": "2026-11-02", "history": []}, base + [dn, up], "short")
    assert adv2["stop"] == 100.43 and adv2["moved"] is False          # a higher candidate never loosens a short's stop


def test_ew06_same_day_changes_nothing():
    stored = {"stop": 95.5, "day": "2026-11-04", "history": [{"day": "2026-11-04"}]}
    adv = rules.advance_level(stored, bars_from([100.0] * 20), "long")
    assert adv["stop"] == 95.5 and adv["moved"] is False and adv["history"] == stored["history"]


def test_ew07_bonus_break_uses_post_break_bars_and_resets():
    pre = bars_from([5336.5] * 40, rng=10.0, end=date(2025, 11, 25))
    post = bars_from([2679.0] * 20, rng=10.0, end=date(2025, 12, 23))
    bars = pre + post
    ev = rules.evaluate(bars, "long")
    assert ev["break_day"] == "2025-11-26" and len(ev["bars"]) == 20
    assert ev["atr"] == 10.0 and ev["candidate"] == 2659.0             # the 2,657-point gap is not a true range
    adv = rules.advance_level({"stop": 5100.0, "day": "2025-11-20", "history": []}, bars, "long")
    assert adv["reset"] is True and adv["stop"] == 2659.0
    assert adv["history"][-1]["reason"] == "price series break (bonus or split)"


def test_ew08_too_few_bars():
    pre = bars_from([5336.5] * 40, rng=10.0, end=date(2025, 11, 25))
    post = bars_from([2679.0] * 10, rng=10.0, end=date(2025, 12, 9))
    ev = rules.evaluate(pre + post, "long")
    assert ev["available"] is False and "after the price series break" in ev["why"] and "10 available" in ev["why"]
    adv = rules.advance_level({"stop": 5100.0, "day": "2025-11-20", "history": []}, pre + post, "long")
    assert adv["stop"] is None and adv["reset"] is True
    assert rules.advance_level(None, bars_from([100.0] * 12), "long")["stop"] is None
    assert "needs 15 sessions" in rules.evaluate(bars_from([100.0] * 12), "long")["why"]


# ── EW-09/10: your own stop ──────────────────────────────────────────────────────────────────────────────────────────
def watched_shares(qty: float = 500, avg: float = 200.0) -> book_mod.Watched:
    return book_mod.group([row("TATSTE", qty, avg)])[0][0]


def test_ew09_your_stop_wins():
    w = watched_shares()
    assert view.stop_in_force(w, 160.71, {"stop": 170.0}, 179.65) == (170.0, "yours")
    lvl = rules.advance_level(None, bars_from([179.65] * 20), "long")
    v = view.position_view(w, lvl, {"stop": 170.0}, price=179.65, source="eod", as_of="2026-11-04", stored=False)
    assert v["method"] == "yours" and v["stop"] == 170.0 and v["rule_stop"] == lvl["stop"]
    # the stored levels go back to the screen whole, so changing the stop keeps a target / trail the user set elsewhere
    assert v["own"] == {"stop": 170.0, "target": None, "trail_pct": None}
    v2 = view.position_view(w, lvl, {"target": 300.0}, price=179.65, source="eod", as_of="2026-11-04", stored=False)
    assert v2["method"] == "atr_trail" and v2["own"] == {"stop": None, "target": 300.0, "trail_pct": None}
    assert view.position_view(w, lvl, None, price=179.65, source="eod", as_of="2026-11-04", stored=False)["own"] is None


def test_ew10_your_trail_from_the_peak_never_below_a_fixed_stop():
    w = watched_shares()
    assert view.stop_in_force(w, 160.0, {"stop": 170.0, "trail_pct": 5.0, "peak": 200.0}, 185.0) == (190.0, "yours")
    assert view.stop_in_force(w, 160.0, {"stop": 195.0, "trail_pct": 5.0, "peak": 200.0}, 196.0) == (195.0, "yours")


# ── EW-11..EW-16: the book ───────────────────────────────────────────────────────────────────────────────────────────
def test_ew11_shares_long():
    ws, skipped = book_mod.group([row("TATSTE", 500, 200.0)])
    assert skipped == [] and len(ws) == 1
    w = ws[0]
    assert (w.key, w.kind, w.side, w.underlying, w.method) == (f"{ICICI}|TATASTEEL|long", "shares", "long", "TATASTEEL", "atr_trail")
    assert w.label == "TATASTEEL shares"


def test_ew12_future_with_covering_put_is_hedged_floor_loss():
    w = book_mod.group(hedge_pair())[0][0]
    assert w.kind == "hedged" and w.method == "put_floor" and w.hedge["strike"] == 980.0
    d1 = [{"type": l.type, "quantity": l.quantity, "avg": l.avg, "price": l.price} for l in w.delta_one]
    loss, basis = rules.loss_at_stop("hedged", "long", d1, 980.0, spot=1005.0, hedge=w.hedge)
    assert loss == 12000.0                                             # (1000 − 980) × 300 + 20 × 300
    assert "Floor loss at expiry" in basis
    v = view.position_view(w, rules.advance_level(None, bars_from([1005.0] * 20), "long"), None, price=1005.0,
                           source="eod", as_of="2026-11-04", stored=False)
    assert v["stop"] == 980.0 and v["method"] == "put_floor" and v["loss_at_stop"] == 12000.0
    assert v["label"] == "DLF future + 980 PE"


def test_ew12b_two_puts_binding_strike():
    rows = [row("DLFLIM", 300, 1000.0, segment="fno", itype="FUT", expiry="2026-11-23"),
            row("DLFLIM", 150, 25.0, segment="fno", itype="PE", expiry="2026-11-23", strike=990.0),
            row("DLFLIM", 150, 12.0, segment="fno", itype="PE", expiry="2026-11-23", strike=950.0)]
    w = book_mod.group(rows)[0][0]
    assert w.kind == "hedged" and w.hedge["strike"] == 950.0                  # 300 covered only from 950 down
    d1 = [{"type": "FUT", "quantity": 300.0, "avg": 1000.0, "price": None}]
    loss, _ = rules.loss_at_stop("hedged", "long", d1, 950.0, hedge=w.hedge)
    # at 950: future −50 × 300 = −15,000 · 990 put worth 40 × 150 = 6,000 · premiums 25 × 150 + 12 × 150 = 5,550
    assert loss == round(50 * 300 - 6000 + 5550, 2) == 14550.0


def test_ew13_short_future_with_long_call_is_capped():
    rows = [row("COALINDIA26NOVFUT", -150, 400.0, account=ZERODHA, broker="zerodha", display="Zerodha", segment="fno"),
            row("COALINDIA26NOV420CE", 150, 6.0, account=ZERODHA, broker="zerodha", display="Zerodha", segment="fno")]
    w = book_mod.group(rows)[0][0]
    assert (w.kind, w.side, w.method, w.hedge["strike"]) == ("hedged", "short", "call_cap", 420.0)
    d1 = [{"type": "FUT", "quantity": -150.0, "avg": 400.0, "price": None}]
    loss, _ = rules.loss_at_stop("hedged", "short", d1, 420.0, hedge=w.hedge)
    assert loss == 3900.0                                              # (420 − 400) × 150 + 6 × 150


def test_ew14_partly_hedged_uses_the_trail():
    w = book_mod.group(hedge_pair(fut_qty=600, put_qty=300))[0][0]
    assert w.kind == "future" and w.method == "atr_trail" and w.note == "partly hedged (300 of 600)"


def test_ew15_not_watched_reasons():
    rows = [row("DLFLIM", 300, 20.0, segment="fno", itype="PE", expiry="2026-11-23", strike=980.0),
            row("TATSTE", 100, 250.0), row("TATSTE", -50, 180.0, segment="fno", itype="FUT", expiry="2026-11-23"),
            row("ZZSGB1", -3, 6000.0, segment="cash")]
    ws, skipped = book_mod.group(rows)
    assert ws == []
    whys = {s["label"]: s["why"] for s in skipped}
    assert whys["DLF options (ICICI Direct)"].startswith("options only")
    assert whys["TATASTEEL (ICICI Direct)"] == "shares or futures on both sides (long and short)"
    assert "ZZSGB1" in whys["ZZSGB1 (ICICI Direct)"] and "security master" in whys["ZZSGB1 (ICICI Direct)"]


def test_ew16_two_accounts_two_positions():
    rows = [row("TATSTE", 100, 250.0), row("TATASTEEL", 50, 240.0, account=ZERODHA, broker="zerodha", display="Zerodha")]
    ws, _ = book_mod.group(rows)
    assert sorted(w.key for w in ws) == sorted([f"{ICICI}|TATASTEEL|long", f"{ZERODHA}|TATASTEEL|long"])


# ── EW-17..EW-19: status and loss ────────────────────────────────────────────────────────────────────────────────────
def test_ew17_status_hit_near_ok():
    assert rules.status_of("long", 95.0, 96.0, 2.0, "atr_trail", near=0.5)[0] == "HIT"
    st, pct, in_atr = rules.status_of("long", 96.9, 96.0, 2.0, "atr_trail", near=0.5)
    assert st == "NEAR" and in_atr == 0.45 and pct == round(0.9 / 96.9 * 100, 2)
    assert rules.status_of("long", 100.0, 96.0, 2.0, "atr_trail", near=0.5) == ("OK", 4.0, 2.0)
    assert rules.status_of("short", 104.5, 104.0, 2.0, "atr_trail", near=0.5)[0] == "HIT"
    assert rules.status_of("long", 100.0, None, 2.0, "none")[0] == "NO_STOP"


def test_ew18_hedged_through_strike_is_floor():
    assert rules.status_of("long", 975.0, 980.0, 20.0, "put_floor")[0] == "FLOOR"


def test_ew19_loss_at_stop():
    shares = [{"type": "EQ", "quantity": 500.0, "avg": 200.0, "price": None}]
    assert rules.loss_at_stop("shares", "long", shares, 150.0)[0] == 25000.0
    fut = [{"type": "FUT", "quantity": 300.0, "avg": 1000.0, "price": 1010.0}]
    loss, basis = rules.loss_at_stop("future", "long", fut, 950.0, spot=1005.0)
    assert loss == 13500.0 and "basis" in basis                        # exit 950 + 5.00 basis → (1000 − 955) × 300
    gain = [{"type": "EQ", "quantity": 100.0, "avg": 90.0, "price": None}]
    assert rules.loss_at_stop("shares", "long", gain, 95.0)[0] == -500.0


# ── the watcher's harness ────────────────────────────────────────────────────────────────────────────────────────────
class Harness:
    def __init__(self):
        self.db = DB()
        self.rows: Dict[str, List[Dict[str, Any]]] = {UID: [row("TATSTE", 500, 200.0)]}
        self.bars: Dict[str, List[Dict[str, Any]]] = {"TATASTEEL": bars_from([180.0] * 30)}
        self.quote: Dict[str, Any] = {}
        self.feed: Dict[str, Any] = {"source": "kite_live", "why": None}
        self.own: Dict[str, Dict[str, Any]] = {}
        self.events: Dict[str, List[Dict[str, Any]]] = {}
        self.bar_reads = 0

    def deps(self) -> runner.Deps:
        async def books(db, now):
            return {u: (rs, READ_AT) for u, rs in self.rows.items()}

        async def bars(sym, start):
            self.bar_reads += 1
            return self.bars.get(sym, [])

        async def quotes(syms, now):
            return {**self.feed, "quotes": {s: self.quote[s] for s in syms if s in self.quote}}

        async def own(db, uid):
            return self.own

        async def events(sym, today):
            return self.events.get(sym, [])

        return runner.Deps(db=self.db, books=books, bars=bars, quotes=quotes, own_levels=own, events=events)

    def live_quote(self, sym: str, px: float, *, age_s: float = 5.0, now: datetime = IN_SESSION) -> None:
        self.quote[sym] = {"ltp": px, "received_at": (now - timedelta(seconds=age_s)).astimezone(IST).isoformat()}

    def alerts(self, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        return [d for d in self.db[store.ALERTS].docs if kind is None or d["kind"] == kind]


@pytest.fixture
def h(monkeypatch):
    monkeypatch.setattr(store, "_indexed", False)
    return Harness()


# ── EW-20..EW-26: alerts and the loop ────────────────────────────────────────────────────────────────────────────────
def test_ew20_stop_hit_fires_once_per_stop_value(h):
    h.live_quote("TATASTEEL", 175.0)                                      # stop = 180 − 2 × 2 = 176
    run(runner.live_round(IN_SESSION, h.deps()))
    run(runner.live_round(IN_SESSION, h.deps()))
    hits = h.alerts("STOP_HIT")
    assert len(hits) == 1 and hits[0]["level"] == 176.0 and hits[0]["severity"] == "CRITICAL"
    assert "through its stop loss ₹176.00" in hits[0]["text"] and "read-only" in hits[0]["text"]
    lv = h.db[store.LEVELS].docs[0]
    assert lv["stop"] == 176.0 and lv["user_id"] == UID and lv["method"] == "atr_trail"
    lv["stop"] = 175.5                                                 # the trail raised it; hit again later
    run(runner.live_round(IN_SESSION, h.deps()))
    assert [a["level"] for a in h.alerts("STOP_HIT")] == [176.0, 175.5]


def test_ew20b_near_stop_once_per_day(h):
    h.live_quote("TATASTEEL", 176.8)                                      # 0.8 above, within 0.5 × ATR 2 = 1.0
    run(runner.live_round(IN_SESSION, h.deps()))
    run(runner.live_round(IN_SESSION, h.deps()))
    assert len(h.alerts("NEAR_STOP")) == 1 and h.alerts("STOP_HIT") == []


def test_ew21_no_fire_on_stale_data(h):
    h.feed = {"source": None, "why": "feed_not_live"}
    h.live_quote("TATASTEEL", 170.0)
    out = run(runner.live_round(IN_SESSION, h.deps()))
    assert h.alerts() == [] and out["feed_why"] == "feed_not_live"
    assert h.db[store.STATE].docs[0]["feed_why"] == "feed_not_live"
    h.feed = {"source": "kite_live", "why": None}
    h.live_quote("TATASTEEL", 170.0, age_s=600)                           # a quote received 10 minutes ago
    run(runner.live_round(IN_SESSION, h.deps()))
    assert h.alerts() == []


def test_ew21b_bonus_day_price_fires_nothing(h):
    h.live_quote("TATASTEEL", 90.0)                                       # half the stored close: a split not in EOD yet
    run(runner.live_round(IN_SESSION, h.deps()))
    assert h.alerts() == []


def evening_series() -> List[Dict[str, Any]]:
    closes = [230.0 - i for i in range(58)] + [195.0, 165.0]           # a fall, a bounce yesterday, a drop today
    return bars_from(closes)


def test_ew22_evening_signals_once_per_day(h):
    h.bars["TATASTEEL"] = evening_series()
    closes = [b["close"] for b in h.bars["TATASTEEL"]]
    f, s = rules.ema_series(closes, 20), rules.ema_series(closes, 50)
    assert closes[-1] < f[-1] < s[-1] and not (closes[-2] < f[-2] < s[-2])          # the series is what the test says
    h.db[store.LEVELS].docs.append({"_id": store.level_id(UID, f"{ICICI}|TATASTEEL|long"), "user_id": UID,
                                    "key": f"{ICICI}|TATASTEEL|long", "stop": 170.0, "day": "2026-11-03", "history": [],
                                    "method": "atr_trail", "kind": "shares", "active": True, "close": 195.0})
    out = run(runner.evening_round(EVENING, h.deps()))
    assert out["ran"] and out["pending"] == []
    kinds = sorted(a["kind"] for a in h.alerts())
    assert kinds == ["CLOSE_THROUGH_STOP", "SUPPORT_BREAK", "TREND_TURN"]
    sup = min(b["low"] for b in h.bars["TATASTEEL"][-21:-1])
    assert next(a for a in h.alerts() if a["kind"] == "SUPPORT_BREAK")["level"] == sup
    assert all(a["source"] == "eod" and a["day"] == "2026-11-04" for a in h.alerts())
    assert run(runner.evening_round(EVENING, h.deps()))["why"] == "done for the day"
    h.db[store.STATE].docs.clear()                                      # even a forced second pass fires nothing new
    run(runner.evening_round(EVENING, h.deps()))
    assert len(h.alerts()) == 3


def test_ew22b_stop_raised(h):
    h.bars["TATASTEEL"] = bars_from([180.0] * 29 + [186.0])
    h.db[store.LEVELS].docs.append({"_id": store.level_id(UID, f"{ICICI}|TATASTEEL|long"), "user_id": UID,
                                    "key": f"{ICICI}|TATASTEEL|long", "stop": 176.0, "day": "2026-11-03", "history": [],
                                    "method": "atr_trail", "kind": "shares", "active": True})
    run(runner.evening_round(EVENING, h.deps()))
    raised = h.alerts("STOP_RAISED")
    a = (2 * 13 + 7) / 14                                               # TR = max(2, |187 − 180|, |185 − 180|) = 7
    assert len(raised) == 1 and raised[0]["level"] == round(186.0 - 2 * a, 2) and raised[0]["severity"] == "INFO"
    assert h.db[store.LEVELS].docs[0]["stop"] == round(186.0 - 2 * a, 2)


def test_ew23_evening_waits_for_todays_bar(h):
    h.bars["TATASTEEL"] = bars_from([180.0] * 30, end=date(2026, 11, 3))
    out = run(runner.evening_round(EVENING, h.deps()))
    assert out["pending"] == ["TATASTEEL"] and h.alerts() == [] and h.db[store.LEVELS].docs == []
    st = h.db[store.STATE].docs[0]
    assert st["_id"] == "eod" and "day" not in st and st["pending"] == ["TATASTEEL"]


def test_ew24_hedge_removed(h):
    h.rows = {UID: hedge_pair()}
    h.bars["DLF"] = bars_from([1005.0] * 30)
    h.live_quote("DLF", 1005.0)
    run(runner.live_round(IN_SESSION, h.deps()))
    assert h.db[store.LEVELS].docs[0]["method"] == "put_floor" and h.alerts() == []
    h.rows = {UID: hedge_pair()[:1]}                                    # the put is gone, the future stays
    run(runner.live_round(IN_SESSION, h.deps()))
    gone = h.alerts("HEDGE_REMOVED")
    assert len(gone) == 1 and gone[0]["severity"] == "CRITICAL" and "no longer capped" in gone[0]["text"]
    assert h.db[store.LEVELS].docs[0]["method"] == "atr_trail"
    run(runner.live_round(IN_SESSION, h.deps()))
    assert len(h.alerts("HEDGE_REMOVED")) == 1


def test_ew25_results_soon_once_per_event(h):
    h.events["TATASTEEL"] = [{"event_date": "2026-11-06", "event_type": "quarterly_results", "purpose": "results"},
                          {"event_date": "2026-11-20", "event_type": "quarterly_results", "purpose": "too far"},
                          {"event_date": "2026-11-05", "event_type": "agm", "purpose": "not results"}]
    run(runner.evening_round(EVENING, h.deps()))
    soon = h.alerts("RESULTS_SOON")
    assert len(soon) == 1 and "Fri 06 Nov" in soon[0]["text"]
    h.bars["TATASTEEL"] = bars_from([180.0] * 31, end=date(2026, 11, 5))
    run(runner.evening_round(datetime(2026, 11, 5, 14, 0, tzinfo=timezone.utc), h.deps()))
    assert len(h.alerts("RESULTS_SOON")) == 1


def test_ew26_loop_gating(monkeypatch, h):
    sunday = datetime(2026, 11, 8, 5, 0, tzinfo=timezone.utc)
    assert run(runner.loop_once(sunday, h.deps())) == "idle"
    other = LocalSignalStore()
    run(other.lead(runner.LEADER_KEY, "someone-else", 90, __import__("time").time()))
    assert run(runner.loop_once(IN_SESSION, h.deps(), leader_store=other, me="me")) == "not_leader"
    mine = LocalSignalStore()
    h.live_quote("TATASTEEL", 181.0)
    assert run(runner.loop_once(IN_SESSION, h.deps(), leader_store=mine, me="me")) == "live"
    monkeypatch.setattr(runner, "_last_evening", float("-inf"))
    assert run(runner.loop_once(EVENING, h.deps(), leader_store=mine, me="me", clock=lambda: 1000.0)) == "evening"
    assert run(runner.loop_once(EVENING, h.deps(), leader_store=mine, me="me", clock=lambda: 1300.0)) == "waiting"
    assert runner.enabled({"APP_ENV": "staging"}) is True
    assert runner.enabled({"APP_ENV": "staging", "EXIT_WATCH_ENABLED": "0"}) is False
    assert runner.enabled({"EXIT_WATCH_ENABLED": "1"}) is True and runner.enabled({}) is False
    monkeypatch.setenv("EXIT_WATCH_ENABLED", "0")

    async def try_start():
        return runner.start()
    assert run(try_start()) is False


def test_snapshot_books_latest_per_account_in_window():
    db = DB()
    snaps = db[runner.SNAPSHOTS]
    snaps.docs += [
        {"_id": "s1", "user_id": UID, "account_id": ICICI, "broker": "icicidirect", "read_at": "2026-11-04T10:00:00+00:00",
         "last_seen_at": "2026-11-04T13:00:00+00:00", "rows": [{"symbol": "TATSTE", "quantity": 500, "avg_price": 200.0},
                                                                 {"symbol": "INOWIN", "quantity": 0, "avg_price": 60.0}]},
        {"_id": "s0", "user_id": UID, "account_id": ICICI, "broker": "icicidirect", "read_at": "2026-11-03T10:00:00+00:00",
         "last_seen_at": "2026-11-03T13:00:00+00:00", "rows": [{"symbol": "OLD", "quantity": 5, "avg_price": 1.0}]},
        {"_id": "z0", "user_id": UID, "account_id": ZERODHA, "broker": "zerodha", "read_at": "2026-10-20T10:00:00+00:00",
         "last_seen_at": "2026-10-20T10:00:00+00:00", "rows": [{"symbol": "STALE", "quantity": 1, "avg_price": 1.0}]},
    ]
    out = run(runner.snapshot_books(db, IN_SESSION))
    rows, as_of = out[UID]
    assert [r["symbol"] for r in rows] == ["TATSTE"] and as_of == "2026-11-04T13:00:00+00:00"
    assert rows[0]["_account_id"] == ICICI and rows[0]["_broker_display"] == "ICICI Direct"


# ── EW-27/28/31: the routes ──────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def api(monkeypatch):
    db = DB()
    monkeypatch.setattr(pnl_route, "db", db)
    monkeypatch.setattr(store, "_indexed", False)

    async def fake_user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": uid}

    monkeypatch.setattr(pnl_route, "get_current_user", fake_user)
    entries = [{"source": "broker", "account_id": ICICI, "broker": "icicidirect", "broker_display": "ICICI Direct", "ok": True,
                "error": None, "read_at": datetime.now(timezone.utc).isoformat(), "rows": 3}]
    book = live.BrokerBook(entries=entries, rows=[row("TATSTE", 500, 200.0), *hedge_pair(), row("ZZSGB1", -3, 6000.0)],
                           read_mono=0.0)

    async def fake_book(request, db_, uid, **kw):
        return book

    monkeypatch.setattr(live, "read_broker_book", fake_book)

    async def fake_bars(sym, start):
        return {"TATASTEEL": bars_from([179.65] * 30), "DLF": bars_from([1005.0] * 30, rng=20.0)}.get(sym, [])

    async def fake_quotes(syms, now):
        return {"source": "kite_close", "day": "2026-11-03", "as_of": "2026-11-03T15:31:00+05:30",
                "quotes": {"TATASTEEL": {"ltp": 178.0}}}

    async def fake_own(db_, uid):
        return {}

    monkeypatch.setattr(service, "cached_bars", fake_bars)
    monkeypatch.setattr(service, "read_quotes", fake_quotes)
    monkeypatch.setattr(service, "read_own_levels", fake_own)
    app = FastAPI()
    app.include_router(pnl_route.router)
    return TestClient(app), db


def test_ew27_needs_a_session(api):
    client, _ = api
    assert client.get("/api/desk/pnl/exits").status_code == 401
    assert client.post("/api/desk/pnl/exits/seen", json={}).status_code == 401


def test_ew28_invalid_account(api):
    client, _ = api
    for bad in ("acc-not-mine", "bad account!"):
        r = client.get("/api/desk/pnl/exits", params={"account": bad}, headers={"X-Test-User": UID})
        assert r.status_code == 422 and r.json()["detail"] == "invalid_account"


def test_ew28b_body_shape_and_reads_write_nothing(api):
    client, db = api
    before = db.writes
    r = client.get("/api/desk/pnl/exits", headers={"X-Test-User": UID})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"as_of", "session", "rule", "watcher", "positions", "not_watched", "alerts", "unseen", "accounts"}
    assert body["rule"]["id"] == "exit-atr-trail-v1"
    by = {p["underlying"]: p for p in body["positions"]}
    sw, hd = by["TATASTEEL"], by["DLF"]
    assert set(sw) == {"key", "account_id", "account", "underlying", "label", "kind", "side", "legs", "price", "price_source",
                       "price_as_of", "stop", "method", "stop_day", "stored", "rule_stop", "atr", "atr_pct", "distance_pct",
                       "distance_atr", "status", "why", "loss_at_stop", "loss_basis", "support", "note", "history", "own"}
    # the saved Kite close is for 3 Nov while NSE's 4 Nov bar is in: the exchange close wins
    assert sw["price"] == 179.65 and sw["price_source"] == "eod" and sw["stored"] is False
    assert sw["stop"] == round(179.65 - 4.0, 2) and sw["method"] == "atr_trail" and sw["status"] == "OK"
    assert hd["method"] == "put_floor" and hd["stop"] == 980.0 and hd["loss_at_stop"] == 12000.0
    assert body["not_watched"][0]["label"].startswith("ZZSGB1")
    assert body["accounts"] == [{"account_id": ICICI, "name": "ICICI Direct", "state": "OK"}]
    assert db.writes == before                                          # a read writes nothing


def test_ew31_mark_seen_only_mine(api):
    client, db = api
    for uid, key in ((UID, "k1"), (UID, "k2"), (OTHER, "k3")):
        run(store.fire(db, uid, key, "STOP_HIT", "1", {"day": "2026-11-05", "text": "MOCK"}))
    ids = [d["_id"] for d in db[store.ALERTS].docs]
    r = client.post("/api/desk/pnl/exits/seen", json={"ids": [ids[0]]}, headers={"X-Test-User": UID})
    assert r.json() == {"marked": 1}
    r = client.post("/api/desk/pnl/exits/seen", json={"ids": [ids[2]]}, headers={"X-Test-User": UID})
    assert r.json() == {"marked": 0}                                    # another user's alert is not mine to mark
    r = client.post("/api/desk/pnl/exits/seen", json={}, headers={"X-Test-User": UID})
    assert r.json() == {"marked": 1}
    assert [d["seen"] for d in db[store.ALERTS].docs] == [True, True, False]
    for bad in ({"ids": "x"}, {"foo": 1}, {"ids": [1]}):
        r = client.post("/api/desk/pnl/exits/seen", json=bad, headers={"X-Test-User": UID})
        assert r.status_code == 422 and r.json()["detail"] == "invalid_body"
    r = client.post("/api/desk/pnl/exits/seen", content=b"{not json", headers={"X-Test-User": UID})
    assert r.status_code == 422
    body = client.get("/api/desk/pnl/exits", headers={"X-Test-User": UID}).json()
    assert body["unseen"] == 0 and len(body["alerts"]) == 2 and all(a["seen"] for a in body["alerts"])
