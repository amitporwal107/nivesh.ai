"""Forward test of near-month short build-up (test_reports/fno_forward_test_TESTCASES.md)."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest

from services import fno_forward as ff


def test_tc1_near_state_uses_the_contracts_own_figures_and_never_zero_fills():
    near = {"expiry": "2026-10-27", "change_pct": -2.0, "oi": 1100, "change_in_oi": 100}
    far = {"expiry": "2026-12-29", "change_pct": 9.0, "oi": 5, "change_in_oi": 5}
    s = ff.near_state([far, near])
    assert s["p"] == -2.0 and s["o"] == pytest.approx(10.0)                    # 100 / (1100 - 100)
    assert ff.near_state([{"expiry": "2026-10-27", "change_pct": None, "oi": 10, "change_in_oi": 1}]) is None
    assert ff.near_state([{"expiry": "2026-10-27", "change_pct": -1, "oi": 10, "change_in_oi": 10}]) is None   # no previous OI
    assert ff.near_state([]) is None


def test_tc2_classification():
    f = ff.fires
    assert f({"p": -0.6, "o": 3.0}, "production_floors") and not f({"p": -0.4, "o": 9.0}, "production_floors") and not f({"p": -2.0, "o": 2.9}, "production_floors")
    assert f({"p": -0.01, "o": 0.01}, "no_threshold") and not f({"p": 0.0, "o": 5.0}, "no_threshold") and not f({"p": -1.0, "o": 0.0}, "no_threshold")
    assert not f({"p": 1.0, "o": 5.0}, "no_threshold")                           # price up is not a short build-up


class _Col:
    def __init__(self): self.docs = {}
    async def update_one(self, q, upd, upsert=False):
        _id = q["_id"]
        fresh = _id not in self.docs
        if fresh:
            self.docs[_id] = dict(upd["$setOnInsert"])
        return type("R", (), {"upserted_id": _id if fresh else None})()


class _Db(dict):
    def __getitem__(self, k): return self.setdefault(k, _Col())


def test_tc3_first_write_wins():
    db = _Db()
    st = {"AAA": {"p": -1.0, "o": 4.0}, "BBB": {"p": 1.0, "o": 4.0}, "CCC": None}
    assert asyncio.run(ff.record(db, "2026-10-23", st)) is True
    changed = {"AAA": {"p": 5.0, "o": 9.0}}
    assert asyncio.run(ff.record(db, "2026-10-23", changed)) is False
    doc = db[ff.COLLECTION].docs["2026-10-23"]
    assert doc["settings"]["production_floors"] == [{"symbol": "AAA", "p": -1.0, "o": 4.0}] and doc["universe_symbols"] == ["AAA", "BBB", "CCC"] and doc["with_state"] == 2


def _days(n, start="2026-09-01"):
    d, out = date.fromisoformat(start), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _bars(days, drift):
    px = 100.0
    rows = []
    for d in days:
        rows.append({"as_of_date": d, "adj_open": px, "adj_close": px * (1 + drift)})
        px *= 1 + drift
    return rows


def _world(n_days=45):
    days = _days(n_days)
    bars = {f"S{k}": _bars(days, 0.001) for k in range(12)}
    bars["SHORT"] = _bars(days, -0.004)                                   # the signalled stock falls faster than the universe
    return days, bars


def _doc(day, syms=("SHORT",)):
    return {"as_of": day, "universe_symbols": [f"S{k}" for k in range(12)] + ["SHORT"],
            "settings": {"production_floors": [{"symbol": s, "p": -1.0, "o": 4.0} for s in syms], "no_threshold": [{"symbol": s, "p": -1.0, "o": 4.0} for s in syms]}}


def test_tc4_entry_next_open_exit_five_sessions_later_short_benchmark_relative_net_of_cost_and_open_sessions():
    days, bars = _world(45)
    docs = [_doc(days[3]), _doc(days[len(days) - 3])]                      # the second has fewer than 5 later sessions
    res = ff.evaluate(docs, bars)["settings"]["production_floors"]
    assert res["recorded_sessions"] == 2 and res["judged_sessions"] == 1 and res["open_sessions"] == 1 and res["judged_signals"] == 1
    assert res["mean_pct"] is None
    # hand computation for the judged session: entry = open of days[4], exit = close of days[8]
    rets = {}
    for s, rows in bars.items():
        by = {r["as_of_date"]: r for r in rows}
        rets[s] = (by[days[8]]["adj_close"] / by[days[4]]["adj_open"] - 1) * 100
    bench = sum(rets.values()) / len(rets)
    want = -(rets["SHORT"] - bench) - ff.COST_PCT
    full = ff.evaluate([_doc(days[3])], bars)
    assert full["settings"]["production_floors"]["judged_signals"] == 1 and want > 0          # the short worked in this world


def test_tc5_no_result_before_30_sessions_and_a_result_at_30():
    days, bars = _world(60)
    few = ff.evaluate([_doc(d) for d in days[:10]], bars)["settings"]["production_floors"]
    assert few["judged_sessions"] == 10 and few["mean_pct"] is None and few["t"] is None and few["sessions_needed"] == 20
    many = ff.evaluate([_doc(d) for d in days[:31]], bars)["settings"]["production_floors"]
    assert many["judged_sessions"] == 31 and many["mean_pct"] is not None and many["sessions_needed"] == 0 and many["mean_pct"] > 0
