"""Daily ATM IV history: services/fno_iv_history, routes/fno.py (read_session, session_iv, GET /{symbol}/iv-history) and
scripts/record_iv_history.py. Test cases: test_reports/iv_history_TESTCASES.md (IV-n below).

No network and no Mongo: the data platform is a fake `daas_client.get_raw` answering with fixture rows (MOCK — not real
data) in the shape DaaS /v1/fno/{symbol}?on=<day> sends (nidp/services/daas_api/routers/fno.py), and Mongo is an
in-memory fake collection. The route, the recorder and the IV model run for real.

The worked example (the same one tests/test_fno_routes.py works by hand for the chain): session 12 Oct 2026, near-month
expiry 27 Oct 2026 (15 calendar days, T = 15/365), r = 5.75%. The 27 Oct future settles at 110.00, so the forward is
110.00 ("future"). The spot is 108, so the ATM strike is 110; its call and put both settle at 1.7749, the price a
volatility of 20% gives (d1 = 0.0202721, price = DF × 110 × (2 N(d1) − 1) = 1.77491) → call iv 20.00, put iv 20.00,
ATM IV (20.00 + 20.00) / 2 = 20.00.

IV rank and IV percentile, worked by hand (services/fno_iv_history's docstring), window 10, 30, 12, 14, 11, 13:
    rank        (13 − 10) / (30 − 10) × 100 = 15.0
    percentile  earlier sessions below 13: 10, 12, 11 → 3 of 5 → 60.0
"""
from __future__ import annotations

import asyncio
import copy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from routes import fno as route
from services import fno_iv_history as store
from services.copilot_tools import daas_client

DAY = "2026-10-12"
NEAR = "2026-10-27"
NEXT = "2026-11-24"
FAR = "2026-12-29"
SPOT = 108.0


# ── fixtures (MOCK — not real data) ──────────────────────────────────────────

def _future(expiry: str, settle: Optional[float], day: str = DAY) -> Dict[str, Any]:
    """One futures row as DaaS /v1/fno/{symbol} sends it (current exchange format: STF, option_type FUT)."""
    return {"as_of_date": day, "ticker_symbol": "TESTCO", "instrument_type": "STF", "expiry_date": expiry,
            "strike_price": -1.0, "option_type": "FUT", "close_price": settle, "settle_price": settle,
            "underlying_price": SPOT, "open_interest": 5000, "change_in_oi": 120, "traded_volume": 2500}


def _option(expiry: str, strike: float, side: str, close: float, settle: float, oi: int, volume: int,
            day: str = DAY) -> Dict[str, Any]:
    return {"as_of_date": day, "ticker_symbol": "TESTCO", "instrument_type": "STO", "expiry_date": expiry,
            "strike_price": strike, "option_type": side, "close_price": close, "settle_price": settle,
            "underlying_price": SPOT, "open_interest": oi, "change_in_oi": 0, "traded_volume": volume, "traded_value": 1000.0}


def _near_options(day: str = DAY) -> List[Dict[str, Any]]:
    """The near-month chain of the worked example (tests/test_fno_routes.py MODEL_CHAIN)."""
    return [
        _option(NEAR, 100.0, "CE", 9.9, 9.9, 10, 7, day), _option(NEAR, 100.0, "PE", 0.05, 0.05, 40, 9, day),
        _option(NEAR, 110.0, "CE", 1.7, 1.7749, 20, 30, day), _option(NEAR, 110.0, "PE", 1.8, 1.7749, 30, 25, day),
        _option(NEAR, 120.0, "CE", 0.05, 0.05, 0, 0, day), _option(NEAR, 120.0, "PE", 10.4, 10.4, 5, 2, day),
    ]


def _next_options(day: str = DAY) -> List[Dict[str, Any]]:
    """Next month: nobody traded or holds the ATM contracts, so their prices are not market prices."""
    return [_option(NEXT, 110.0, "CE", 3.0, 3.0, 0, 0, day), _option(NEXT, 110.0, "PE", 3.4, 3.4, 0, 0, day)]


SESSION = {
    "futures": [_future(NEAR, 110.0), _future(NEXT, 110.5), _future(FAR, 111.0)],
    "options": {NEAR: _near_options(), NEXT: _next_options()},
}

Reply = Any


def _envelope(rows: List[Dict[str, Any]], as_of: Optional[str], next_offset: Optional[int] = None) -> Dict[str, Any]:
    return {"data": rows, "count": len(rows), "pagination": {"limit": 5000, "offset": 0, "total": None, "next_offset": next_offset},
            "symbol": "TESTCO", "as_of": as_of}


def _platform(sessions: Dict[str, Dict[str, Any]], *, fail: Optional[Dict[str, Reply]] = None,
              answer_day: Optional[Dict[str, str]] = None) -> Callable[[str, Optional[dict]], Reply]:
    """A fake data platform. `sessions` maps a day to its futures and option rows; a day not in it has no rows (the
    data platform then answers 200 with no rows for that day). `fail` maps a day to the reply every read of it gets
    (an exception or a status), `answer_day` maps a day to the day the platform claims to answer for."""
    def replies(path: str, params: Optional[dict]) -> Reply:
        params = params or {}
        day = params.get("on")
        if fail and day in fail:
            return fail[day]
        s = sessions.get(day, {"futures": [], "options": {}})
        as_of = (answer_day or {}).get(day, day)
        if "instrument_type" in params:
            rows = [r for r in s["futures"] if r["instrument_type"] == params["instrument_type"]]
        else:
            e = params["expiry"]
            rows = [r for r in s["futures"] if r["expiry_date"] == e] + list(s["options"].get(e, []))
        return 200, _envelope(copy.deepcopy(rows), as_of)
    return replies


def _wire(monkeypatch, replies: Callable[[str, Optional[dict]], Reply]) -> List[Tuple[str, dict]]:
    calls: List[Tuple[str, dict]] = []

    async def get_raw(path: str, params: Optional[dict] = None, timeout: float = 10.0):
        calls.append((path, dict(params or {})))
        reply = replies(path, params)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(daas_client, "get_raw", get_raw)
    monkeypatch.setattr(daas_client, "is_configured", lambda: True)
    return calls


class _Cursor:
    def __init__(self, docs: List[Dict[str, Any]]): self.docs = docs
    def sort(self, key: str, direction: int):
        self.docs = sorted(self.docs, key=lambda d: d.get(key), reverse=direction == -1)
        return self
    def limit(self, n: int):
        self.docs = self.docs[:n]
        return self
    def __aiter__(self):
        async def gen():
            for d in self.docs:
                yield d
        return gen()


class _Col:
    """An in-memory Mongo collection: update_one with $set / $setOnInsert and upsert, find with equality filters."""
    def __init__(self): self.docs: Dict[str, Dict[str, Any]] = {}; self.fail = False; self.reads = 0; self.indexes = []

    async def update_one(self, q, upd, upsert=False):
        # Mongo refuses an update that sets _id or names one field in both operators: so does the fake.
        assert "_id" not in upd["$set"] and not set(upd["$set"]) & set(upd.get("$setOnInsert", {}))
        _id = q["_id"]
        fresh = _id not in self.docs
        doc = self.docs.setdefault(_id, {"_id": _id})
        if fresh:
            doc.update(copy.deepcopy(upd.get("$setOnInsert", {})))
        doc.update(copy.deepcopy(upd["$set"]))
        return type("R", (), {"upserted_id": _id if fresh else None})()

    def find(self, flt=None, proj=None):
        self.reads += 1
        if self.fail:
            raise RuntimeError("mongo down")
        docs = [copy.deepcopy(d) for d in self.docs.values() if all(d.get(k) == v for k, v in (flt or {}).items())]
        if proj and proj.get("_id") == 0:
            for d in docs:
                d.pop("_id", None)
        return _Cursor(docs)

    async def create_index(self, keys, **_k):
        self.indexes.append(keys)
        return "ix"


class _Db(dict):
    def __getitem__(self, k): return self.setdefault(k, _Col())


def _weekdays(n: int, start: str = "2025-06-02") -> List[str]:
    d, out = date.fromisoformat(start), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _doc(day: str, iv: Optional[float], sym: str = "TESTCO", method: str = "recorded", version: str = store.CALC_VERSION,
         reason: Optional[str] = None) -> Dict[str, Any]:
    """A stored document as the recorder leaves it (MOCK — not real data)."""
    near = {k: None for k in route.IV_BUCKET_FIELDS}
    near.update(expiry=NEAR, atm_iv=iv, reason=reason if iv is None else None, spot=SPOT, forward=110.0, forward_basis="future")
    doc = store.build_doc(sym, day, {"near_month": near, "next_month": {"atm_iv": None, "reason": "no rows"}}, 5.75)
    doc.update(calc_version=version, method=method, recorded_at=datetime(2026, 10, 26, tzinfo=timezone.utc))
    doc.pop("_id")
    return doc


# ── IV rank and IV percentile (IV-1, IV-2) ───────────────────────────────────

def test_iv1_rank_and_percentile_worked_by_hand():
    """Window 10, 30, 12, 14, 11, 13 (current 13):
        rank        (13 − 10) / (30 − 10) × 100 = 3 / 20 × 100 = 15.0
        percentile  earlier 10 30 12 14 11; below 13: 10, 12, 11 = 3 of 5 → 60.0"""
    window = [10.0, 30.0, 12.0, 14.0, 11.0, 13.0]
    assert store.iv_rank(window) == 15.0
    assert store.iv_percentile(window) == 60.0
    # the same through the route's answer, with the session minimum set to the window's length
    days = _weekdays(6)
    body = store.history_answer("TESTCO", [_doc(d, v) for d, v in zip(days, window)], "near_month", 252, min_sessions=6)
    assert (body["iv_rank"], body["iv_percentile"], body["reason"]) == (15.0, 60.0, None)
    assert body["window"] == {"sessions": 6, "from": days[0], "to": days[-1], "min": 10.0, "max": 30.0,
                              "calendar_days": (date.fromisoformat(days[-1]) - date.fromisoformat(days[0])).days}


def test_iv2_flat_window_has_no_rank_and_a_reason_but_a_percentile():
    assert store.iv_rank([15.0, 15.0, 15.0]) is None
    assert store.iv_percentile([15.0, 15.0, 15.0]) == 0.0           # none of the earlier sessions is strictly below
    assert store.iv_rank([]) is None and store.iv_percentile([15.0]) is None
    days = _weekdays(3)
    body = store.history_answer("TESTCO", [_doc(d, 15.0) for d in days], "near_month", 10, min_sessions=3)
    assert body["iv_rank"] is None and body["iv_percentile"] == 0.0 and "did not change" in body["reason"]


# ── the 252-session rule (IV-3 .. IV-7) ──────────────────────────────────────

def test_iv3_under_252_sessions_rank_and_percentile_are_null_with_the_count():
    days = _weekdays(251)
    body = store.history_answer("TESTCO", [_doc(d, 10.0 + i % 7) for i, d in enumerate(days)], "near_month", 30)
    assert body["sessions"] == 251 and body["iv_rank"] is None and body["iv_percentile"] is None and body["window"] is None
    assert "251 sessions" in body["reason"] and "need 252" in body["reason"]
    assert len(body["series"]) == 30 and body["series"][-1]["date"] == days[-1] and body["current"]["date"] == days[-1]


def test_iv4_exactly_252_sessions_gives_rank_and_percentile():
    days = _weekdays(252)
    values = [10.0 + (i % 11) for i in range(251)] + [15.0]          # lows 10, highs 20, current 15
    body = store.history_answer("TESTCO", [_doc(d, v) for d, v in zip(days, values)], "near_month", 252)
    below = sum(1 for v in values[:-1] if v < 15.0)
    assert body["sessions"] == 252 and body["reason"] is None
    assert body["iv_rank"] == 50.0 and body["iv_percentile"] == round(below / 251 * 100, 1)
    assert (body["window"]["sessions"], body["window"]["from"], body["window"]["to"]) == (252, days[0], days[-1])


def test_iv5_only_the_latest_252_sessions_form_the_window():
    days = _weekdays(300)
    # 48 older sessions at 90 (outside the window), then 251 alternating 10 / 20, then the current 15
    values = [90.0] * 48 + [10.0 if i % 2 == 0 else 20.0 for i in range(251)] + [15.0]
    body = store.history_answer("TESTCO", [_doc(d, v) for d, v in zip(days, values)], "near_month", 5)
    assert body["sessions"] == 300 and body["window"]["from"] == days[48] and body["window"]["max"] == 20.0
    assert body["iv_rank"] == 50.0                                     # (15 − 10) / (20 − 10); with the 90s it would be 6.2
    assert body["iv_percentile"] == round(126 / 251 * 100, 1)           # 126 tens among the 251 earlier sessions
    assert [p["date"] for p in body["series"]] == days[-5:]


def test_iv6_sessions_without_an_iv_are_listed_with_their_reason_and_never_counted():
    days = _weekdays(6)
    docs = [_doc(d, 10.0 + i) for i, d in enumerate(days)]
    docs[2] = _doc(days[2], None, reason="neither the ATM call nor the ATM put has an implied volatility")
    body = store.history_answer("TESTCO", docs, "near_month", 10, min_sessions=6)
    assert body["sessions"] == 5 and body["sessions_without_iv"] == 1 and body["iv_rank"] is None
    assert "5 sessions" in body["reason"]
    gap = body["series"][2]
    assert gap["atm_iv"] is None and "ATM call" in gap["reason"] and len(body["series"]) == 6
    # with the minimum met by the sessions that have an IV, the gap is not a value in the window
    body = store.history_answer("TESTCO", docs, "near_month", 10, min_sessions=5)
    assert body["window"]["sessions"] == 5 and body["window"]["min"] == 10.0 and body["iv_rank"] == 100.0


def test_iv7_latest_session_without_an_iv_is_current_and_no_older_iv_stands_in():
    days = _weekdays(7)
    docs = [_doc(d, 10.0 + i) for i, d in enumerate(days[:-1])] + [_doc(days[-1], None, reason="no forward")]
    body = store.history_answer("TESTCO", docs, "near_month", 10, min_sessions=3)
    assert body["current"]["date"] == days[-1] and body["current"]["atm_iv"] is None
    assert body["iv_rank"] is None and body["iv_percentile"] is None and days[-1] in body["reason"] and "no forward" in body["reason"]


def test_a_row_of_another_calculation_version_is_not_mixed_into_the_window():
    days = _weekdays(4)
    docs = [_doc(days[0], 50.0, version="fno-atm-iv-v0")] + [_doc(d, 10.0 + i) for i, d in enumerate(days[1:])]
    body = store.history_answer("TESTCO", docs, "near_month", 10, min_sessions=3)
    assert body["sessions"] == 3 and body["sessions_other_version"] == 1 and body["window"]["max"] == 12.0


# ── the IV is the chain route's own (IV-8, IV-9) ─────────────────────────────

def test_iv8_session_atm_iv_is_the_chain_routes_atm_iv_on_the_same_rows(monkeypatch):
    near = route.expiry_atm_iv(DAY, NEAR, SESSION["futures"], SESSION["options"][NEAR])
    assert near["atm_iv"] == 20.0 and (near["call_iv"], near["put_iv"]) == (20.0, 20.0)
    assert (near["call_iv_price"], near["put_iv_price"]) == ("settle", "settle")
    assert (near["days_to_expiry"], near["atm_strike"], near["spot"]) == (15, 110, SPOT)
    assert (near["forward"], near["forward_basis"], near["future_settle"], near["reason"]) == (110.0, "future", 110.0, None)

    # the chain route on the same rows (its /chain body regroups the same option rows by strike)
    def replies(path: str, params: Optional[dict]) -> Reply:
        if path.endswith("/chain"):
            strikes: Dict[float, Dict[str, Any]] = {}
            for r in SESSION["options"][NEAR]:
                strikes.setdefault(r["strike_price"], {"strike": r["strike_price"], "CE": None, "PE": None})[r["option_type"]] = r
            return 200, {"symbol": "TESTCO", "as_of": DAY, "expiry": NEAR, "strikes": [strikes[k] for k in sorted(strikes)]}
        return 200, _envelope([r for r in SESSION["futures"] if r["instrument_type"] == params["instrument_type"]], DAY)

    _wire(monkeypatch, replies)

    async def fake_user(request: Request):
        return {"user_id": "u1"}
    monkeypatch.setattr(route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(route.router)
    s = TestClient(app).get(f"/api/fno/TESTCO/chain?expiry={NEAR}").json()["summary"]
    assert (s["atm_iv"], s["forward"], s["forward_basis"], s["atm_strike"], s["rate_pct"]) == (
        near["atm_iv"], near["forward"], near["forward_basis"], near["atm_strike"], 5.75)


def test_iv9_buckets_are_the_first_and_second_futures_expiries_after_the_session():
    futures = [_future(DAY, 108.1), _future(NEAR, 110.0), _future(NEXT, 110.5), _future(FAR, 111.0),
               _future("2026-09-29", 100.0, day="2026-09-29")]       # another day's row is not the session's
    assert route.session_expiries(DAY, futures) == [NEAR, NEXT, FAR]
    buckets = route.session_iv(DAY, futures, {NEAR: _near_options(), NEXT: _next_options()})
    assert buckets["near_month"]["expiry"] == NEAR and buckets["near_month"]["atm_iv"] == 20.0
    nxt = buckets["next_month"]
    assert nxt["expiry"] == NEXT and nxt["atm_iv"] is None and "neither the ATM call nor the ATM put" in nxt["reason"]
    assert nxt["forward"] == 110.5 and nxt["forward_basis"] == "future"
    # a session listing a single futures expiry has no next month, and says so
    one = route.session_iv(DAY, [_future(NEAR, 110.0)], {NEAR: _near_options()})
    assert one["next_month"]["atm_iv"] is None and one["next_month"]["expiry"] is None and "fewer than 2" in one["next_month"]["reason"]


# ── reading one session from the data platform ───────────────────────────────

def test_read_session_asks_for_that_day_and_the_bucket_expiries_only(monkeypatch):
    calls = _wire(monkeypatch, _platform({DAY: SESSION}))
    got = asyncio.run(route.read_session("TESTCO", DAY))
    assert sorted(got["expiries"]) == [NEAR, NEXT] and len(got["futures"]) == 3
    assert all(p["on"] == DAY for _, p in calls)
    assert sorted(p.get("instrument_type", "") for _, p in calls if "instrument_type" in p) == ["FUTIDX", "FUTSTK", "IDF", "STF"]
    assert sorted(p["expiry"] for _, p in calls if "expiry" in p) == [NEAR, NEXT]          # never the far month


def test_read_session_reads_every_page_of_an_expiry(monkeypatch):
    first, second = _near_options()[:3], _near_options()[3:]

    def replies(path, params):
        if "instrument_type" in params:
            return 200, _envelope([r for r in SESSION["futures"] if r["instrument_type"] == params["instrument_type"]], DAY)
        if params["expiry"] != NEAR:
            return 200, _envelope([], DAY)
        if params["offset"] == 0:
            return 200, _envelope(first, DAY, next_offset=3)
        return 200, _envelope(second, DAY)

    _wire(monkeypatch, replies)
    got = asyncio.run(route.read_session("TESTCO", DAY))
    assert len(got["expiries"][NEAR]) == 6
    assert route.session_iv(DAY, got["futures"], got["expiries"])["near_month"]["atm_iv"] == 20.0


def test_an_expiry_that_never_stops_paging_is_refused_not_truncated(monkeypatch):
    def replies(path, params):
        if "instrument_type" in params:
            return 200, _envelope([r for r in SESSION["futures"] if r["instrument_type"] == params["instrument_type"]], DAY)
        return 200, _envelope(_near_options()[:1], DAY, next_offset=params["offset"] + 1)

    _wire(monkeypatch, replies)
    with pytest.raises(route.HTTPException) as e:
        asyncio.run(route.read_session("TESTCO", DAY))
    assert e.value.status_code == 502


# ── the recorder (IV-10 .. IV-13, IV-18) ─────────────────────────────────────

def _recorder():
    from scripts import record_iv_history as rec
    return rec


def test_iv18_recorded_row_carries_source_rate_as_of_version_method_and_inputs(monkeypatch):
    _wire(monkeypatch, _platform({DAY: SESSION}))
    db = _Db()
    assert asyncio.run(_recorder().record_one(db, "TESTCO", DAY, "recorded", dry=False)) == "written"
    doc = db[store.COLLECTION].docs[f"TESTCO:{DAY}"]
    assert (doc["underlying"], doc["date"], doc["as_of"], doc["calc_version"], doc["rate_pct"], doc["method"]) == (
        "TESTCO", DAY, DAY, store.CALC_VERSION, 5.75, "recorded")
    assert "nidp.fno_bhavcopy" in doc["source"] and "Black-76" in doc["source"]
    near = doc["buckets"]["near_month"]
    assert set(near) == set(route.IV_BUCKET_FIELDS)
    assert (near["spot"], near["future_settle"], near["forward"], near["forward_basis"], near["atm_iv"]) == (SPOT, 110.0, 110.0, "future", 20.0)
    assert isinstance(doc["recorded_at"], datetime) and isinstance(doc["computed_at"], datetime)


def test_iv10_upserting_a_session_twice_leaves_one_document_and_keeps_the_first_write(monkeypatch):
    first, later = datetime(2026, 10, 12, 17, 30, tzinfo=timezone.utc), datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)
    db = _Db()
    buckets = route.session_iv(DAY, SESSION["futures"], SESSION["options"])
    doc = store.build_doc("TESTCO", DAY, buckets, 5.75)
    assert asyncio.run(store.upsert(db, doc, "backfill", now=first)) is True
    assert asyncio.run(store.upsert(db, copy.deepcopy(doc), "recorded", now=later)) is False
    col = db[store.COLLECTION]
    assert list(col.docs) == [f"TESTCO:{DAY}"]
    stored = col.docs[f"TESTCO:{DAY}"]
    assert stored["buckets"] == doc["buckets"] and stored["buckets"]["near_month"]["atm_iv"] == 20.0
    assert (stored["method"], stored["recorded_at"], stored["computed_at"]) == ("backfill", first, later)
    with pytest.raises(ValueError):
        asyncio.run(store.upsert(db, doc, "guessed"))
    # the recorder twice over the same session: still one document
    _wire(monkeypatch, _platform({DAY: SESSION}))
    rec = _recorder()
    db2 = _Db()
    assert asyncio.run(rec.record_one(db2, "TESTCO", DAY, "recorded", dry=False)) == "written"
    assert asyncio.run(rec.record_one(db2, "TESTCO", DAY, "recorded", dry=False)) == "updated"
    assert len(db2[store.COLLECTION].docs) == 1


@pytest.mark.parametrize("reply", [
    daas_client.DaasError("DAAS connectivity error"),
    (502, {"detail": "bad gateway"}),
    (500, None),
    (404, {"detail": "Not Found"}),                    # a missing route says nothing about the underlying
])
def test_iv11_a_failed_read_writes_nothing_and_is_counted_as_failed_never_zero(monkeypatch, reply):
    _wire(monkeypatch, _platform({DAY: SESSION}, fail={DAY: reply}))
    db = _Db()
    assert asyncio.run(_recorder().record_one(db, "TESTCO", DAY, "recorded", dry=False)) == "failed"
    assert db[store.COLLECTION].docs == {}


def test_iv11_an_expiry_read_failing_after_the_futures_read_writes_nothing(monkeypatch):
    ok = _platform({DAY: SESSION})
    _wire(monkeypatch, lambda path, params: daas_client.DaasError("timed out") if "expiry" in (params or {}) else ok(path, params))
    db = _Db()
    assert asyncio.run(_recorder().record_one(db, "TESTCO", DAY, "recorded", dry=False)) == "failed"
    assert db[store.COLLECTION].docs == {}


def test_iv12_an_answer_for_another_day_is_refused(monkeypatch):
    _wire(monkeypatch, _platform({DAY: SESSION}, answer_day={DAY: "2026-10-23"}))
    db = _Db()
    assert asyncio.run(_recorder().record_one(db, "TESTCO", DAY, "backfill", dry=False)) == "failed"
    assert db[store.COLLECTION].docs == {}
    # rows of another day inside an answer that claims the right day are refused too
    stale = {"futures": [_future(NEAR, 110.0, day="2026-10-23")], "options": {}}
    _wire(monkeypatch, _platform({DAY: stale}))
    assert asyncio.run(_recorder().record_one(db, "TESTCO", DAY, "backfill", dry=False)) == "failed"
    assert db[store.COLLECTION].docs == {}


def test_iv13_a_weekday_without_rows_is_skipped_and_counted_never_filled(monkeypatch):
    _wire(monkeypatch, _platform({}))
    db = _Db()
    assert asyncio.run(_recorder().record_one(db, "TESTCO", "2026-10-02", "backfill", dry=False)) == "no_rows"
    assert db[store.COLLECTION].docs == {}


def test_backfill_run_counts_each_outcome_and_skips_stored_sessions(monkeypatch):
    rec = _recorder()
    days = ["2026-10-09", DAY, "2026-10-13", "2026-10-14"]            # Fri (holiday here), Mon ok, Tue fails, Wed ok
    later = {"futures": [_future(NEAR, 110.0, "2026-10-14"), _future(NEXT, 110.5, "2026-10-14")],
             "options": {NEAR: _near_options("2026-10-14"), NEXT: _next_options("2026-10-14")}}
    _wire(monkeypatch, _platform({DAY: SESSION, "2026-10-14": later}, fail={"2026-10-13": daas_client.DaasError("down")}))
    db = _Db()
    counts = asyncio.run(rec.run(db, ["TESTCO"], days, "backfill", dry=False, skip_existing=True))
    assert dict(counts) == {"no_rows": 1, "written": 2, "failed": 1}
    assert sorted(db[store.COLLECTION].docs) == [f"TESTCO:{DAY}", "TESTCO:2026-10-14"]
    again = asyncio.run(rec.run(db, ["TESTCO"], days, "backfill", dry=False, skip_existing=True))
    assert dict(again) == {"skipped_existing": 2, "no_rows": 1, "failed": 1}
    dry = asyncio.run(rec.run(_Db(), ["TESTCO"], [DAY], "recorded", dry=True, skip_existing=False))
    assert dict(dry) == {"dry": 1}


def test_recorder_weekdays_and_backfill_window():
    rec = _recorder()
    assert rec.weekdays(date(2026, 10, 9), date(2026, 10, 13)) == ["2026-10-09", "2026-10-12", "2026-10-13"]
    assert rec.backfill_start(date(2026, 10, 13), 3) == date(2026, 10, 9)
    assert rec.scan_universe({"indices": [{"symbol": "nifty"}], "rows": [{"symbol": "RELIANCE"}, {"x": 1}]}) == ["NIFTY", "RELIANCE"]


def test_the_documented_schedule_runs_after_the_last_fno_bhavcopy_retry():
    """The cron line is documented in the script (not installed). It must run after the NIDP F&O bhavcopy ingest's last
    retry (deploy/cloudpe/nidp/nidp-staging.cron), or it would record a partly loaded session."""
    root = Path(__file__).resolve().parents[2]
    doc = (root / "backend" / "scripts" / "record_iv_history.py").read_text()
    assert "CRON_TZ=Asia/Kolkata" in doc
    [line] = [l.strip() for l in doc.splitlines() if "python -m scripts.record_iv_history >>" in l]
    minute, hour = line.split()[:2]
    retries = [l.split()[:2] for l in (root / "deploy" / "cloudpe" / "nidp" / "nidp-staging.cron").read_text().splitlines()
               if l and not l.startswith("#") and l.rstrip().endswith("run_service.sh fno_bhavcopy")]
    assert retries and max((int(h), int(m)) for m, h in retries) < (int(hour), int(minute))
    assert line.split()[4] == "1-5" and "--dry-run" not in line


# ── the route (IV-14 .. IV-17, IV-19) ────────────────────────────────────────

def _route_client(monkeypatch, docs: List[Dict[str, Any]], *, signed_in: bool = True, fail: bool = False) -> Tuple[TestClient, _Col]:
    import deps
    db = _Db()
    col = db[store.COLLECTION]
    for d in docs:
        col.docs[store.doc_id(d["underlying"], d["date"])] = {"_id": store.doc_id(d["underlying"], d["date"]), **d}
    col.fail = fail
    monkeypatch.setattr(deps, "db", db)
    if signed_in:
        async def fake_user(request: Request):
            return {"user_id": "u1"}
        monkeypatch.setattr(route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app), col


def test_route_returns_the_series_sessions_and_current(monkeypatch):
    days = _weekdays(4)
    docs = [_doc(d, 18.0 + i) for i, d in enumerate(days)] + [_doc(days[0], 99.0, sym="OTHER")]
    c, _ = _route_client(monkeypatch, docs)
    body = c.get("/api/fno/testco/iv-history?days=3").json()
    assert body["symbol"] == "TESTCO" and body["bucket"] == "near_month" and body["sessions"] == 4
    assert [p["date"] for p in body["series"]] == days[1:] and [p["atm_iv"] for p in body["series"]] == [19.0, 20.0, 21.0]
    assert body["current"]["date"] == days[-1] and body["current"]["atm_iv"] == 21.0 and body["current"]["rate_pct"] == 5.75
    assert body["iv_rank"] is None and body["iv_percentile"] is None and "4 sessions" in body["reason"] and "252" in body["reason"]
    assert body["methods"] == {"recorded": 4, "backfill": 0} and body["read_only"] is True
    nxt = c.get("/api/fno/TESTCO/iv-history?bucket=next_month").json()
    assert nxt["bucket"] == "next_month" and nxt["sessions"] == 0 and nxt["series"][-1]["reason"] == "no rows"


def test_iv14_unauthenticated_is_401_and_the_store_is_not_read(monkeypatch):
    c, col = _route_client(monkeypatch, [_doc(DAY, 20.0)], signed_in=False)      # the real deps.get_current_user
    r = c.get("/api/fno/TESTCO/iv-history")
    assert (r.status_code, r.json()) == (401, {"detail": "Not authenticated"})
    assert col.reads == 0


def test_iv15_nothing_recorded_is_200_with_zero_sessions_and_a_reason(monkeypatch):
    c, _ = _route_client(monkeypatch, [])
    body = c.get("/api/fno/NIFTY/iv-history").json()
    assert (body["sessions"], body["current"], body["series"], body["iv_rank"], body["iv_percentile"]) == (0, None, [], None, None)
    assert "No IV history is recorded for NIFTY" in body["reason"]


def test_iv16_a_store_that_cannot_be_read_is_502_never_an_empty_history(monkeypatch):
    c, _ = _route_client(monkeypatch, [_doc(DAY, 20.0)], fail=True)
    r = c.get("/api/fno/TESTCO/iv-history")
    assert (r.status_code, r.json()) == (502, {"detail": "upstream_unavailable"})


@pytest.mark.parametrize("path", [
    "/api/fno/TEST$CO/iv-history",
    "/api/fno/TESTCO/iv-history?days=0",
    f"/api/fno/TESTCO/iv-history?days={store.MAX_DAYS + 1}",
    "/api/fno/TESTCO/iv-history?bucket=weekly",
])
def test_iv17_bad_input_is_422_before_the_store_is_read(monkeypatch, path):
    c, col = _route_client(monkeypatch, [_doc(DAY, 20.0)])
    assert c.get(path).status_code == 422
    assert col.reads == 0
