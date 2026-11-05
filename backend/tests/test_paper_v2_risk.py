"""Paper Trading v2 — correlation (services/spt/correlation.py) and the named stress scenarios (services/spt/
stress_named.py on GET /api/v1/risk/stress-test/{id}); TESTCASES PV2-B-18..20.
MOCK — not real data: every symbol, close and position here is made up."""
from __future__ import annotations

import asyncio
import math
import statistics
from datetime import date, timedelta

import pytest

from services import desk_trading as desk
from services.spt import constants as C
from services.spt import correlation, stress_named
from tests.paper_v2_fakes import A, NOW, U1, client, world  # noqa: F401 (fixtures)

LAST = date(2026, 11, 4)                    # the last completed session before NOW (Thu 5 Nov 2026, 10:30 IST)


def sessions(n: int):
    out, d = [], LAST
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return list(reversed(out))


def bars_from_returns(rets, start=100.0):
    """MOCK closes: start, then each return applied; one bar per weekday ending on LAST."""
    days = sessions(len(rets) + 1)
    closes = [start]
    for r in rets:
        closes.append(closes[-1] * (1 + r))
    return [{"date": d, "close": c} for d, c in zip(days, closes)]


X = [0.01 * math.sin(i * 0.7) + 0.002 * ((i * 37) % 7 - 3) for i in range(60)]      # MOCK returns
Y = [0.6 * x + 0.004 * math.cos(i * 1.3) for i, x in enumerate(X)]                  # correlated with X, not exactly


def read(rets_or_bars, error=None):
    bars = rets_or_bars if rets_or_bars and isinstance(rets_or_bars[0], dict) else bars_from_returns(rets_or_bars or [])
    return {"bars": [] if error else bars, "error": error, "source": "MOCK bars"}


# ── PV2-B-18 the math ────────────────────────────────────────────────────────
def test_pv2_b_18_pearson_matches_an_independent_computation():
    rows = [correlation.series("FIXA", read(X), 60, NOW), correlation.series("FIXB", read(Y), 60, NOW),
            correlation.series("FIXN", read([-x for x in X]), 60, NOW)]
    assert all(r["usable"] for r in rows) and rows[0]["observations"] == 60
    m, cells = correlation.matrix(rows, 60)
    # the returns as the series recomputes them from the closes (c1/c0 − 1), against Python's own statistics.correlation
    xa = [rows[0]["returns"][d] for d in sorted(rows[0]["returns"])]
    yb = [rows[1]["returns"][d] for d in sorted(rows[1]["returns"])]
    assert m[0][1] == pytest.approx(statistics.correlation(xa, yb), abs=1e-4)
    assert m[0][2] == pytest.approx(-1.0, abs=1e-4)                                  # an exact mirror
    assert [m[i][i] for i in range(3)] == [1.0, 1.0, 1.0]
    assert m[1][0] == m[0][1] and m[2][0] == m[0][2] and cells == []
    assert correlation.pearson([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]) == pytest.approx(1.0)
    assert correlation.pearson([1.0, 1.0, 1.0], [2.0, 4.0, 6.0]) is None             # no variance → no ρ


# ── PV2-B-19 nulls with reasons ──────────────────────────────────────────────
def test_pv2_b_19_short_jumpy_unreadable_and_stale_series_are_null():
    bonus = list(X)
    bonus[40] = -0.5                                                                # an unadjusted 1:1 bonus
    stale = bars_from_returns(X)
    stale = [{"date": b["date"] - timedelta(days=14), "close": b["close"]} for b in stale]
    rows = [correlation.series("FIXA", read(X), 60, NOW),
            correlation.series("FIXS", read(X[:10]), 60, NOW),
            correlation.series("FIXJ", read(bonus), 60, NOW),
            correlation.series("FIXU", read([], error="MOCK: the data platform did not answer"), 60, NOW),
            correlation.series("FIXT", read(stale), 60, NOW)]
    assert [r["usable"] for r in rows] == [True, False, False, False, False]
    assert "only 10 daily returns" in rows[1]["reason"] and "at least 40" in rows[1]["reason"]
    assert "bonus or split" in rows[2]["reason"] and rows[2]["jump"]["pct"] == -50.0
    assert "did not answer" in rows[3]["reason"]
    assert "stale" in rows[4]["reason"]
    body = correlation.build(rows, 60, left_out=[], with_symbol=None)
    m = body["matrix"]
    assert m[0][0] == 1.0 and all(m[i][i] is None for i in range(1, 5))
    assert all(m[0][j] is None and m[j][0] is None for j in range(1, 5))
    assert {c["b"] for c in body["cells"] if c["a"] == "FIXA"} == {"FIXS", "FIXJ", "FIXU", "FIXT"}
    assert body["threshold"] == 0.7 and body["days"] == 60 and len(body["notes"]) >= 4


def test_pv2_b_19b_a_small_move_is_kept_and_an_18pct_move_is_not():
    ok = list(X)
    ok[30] = -0.17
    jump = list(X)
    jump[30] = 0.25
    assert correlation.series("FIXA", read(ok), 60, NOW)["usable"] is True
    assert correlation.series("FIXB", read(jump), 60, NOW)["usable"] is False


def test_pv2_b_19c_route_symbols_with_and_bad_with(client):
    db = client.world.db
    db[C.POSITIONS].docs.append({"_id": "pa", "user_id": U1, "symbol": "FIXA", "state": C.POS_MONITORING,
                                 "quantity": 10, "avg_entry_price": 500.0})
    db[desk.TRADES].docs.extend([
        {"_id": "d1", "user_id": U1, "status": "open", "symbol": "FIXB", "quantity": 5, "entry_price": 300.0},
        {"_id": "d2", "user_id": U1, "status": "open", "kind": "strategy", "underlying": "FIXC", "symbol": "FIXC",
         "legs": [{"kind": "option", "side": "buy", "lots": 1, "lot_size": 100, "entry_price": 20.0, "strike": 100.0,
                   "option_type": "call", "expiry": "2026-11-24"}]}])
    series = {"FIXA": X, "FIXB": Y, "FIXC": [-x for x in X], "FIXW": X[:5]}

    async def bars(symbol, now):
        return read(series[symbol])
    import services.spt.correlation as mod
    mod_default = mod._default_bars
    try:
        mod._default_bars = bars
        r = client.get(f"/api/v1/risk/correlation/{U1}?with=fixw", headers=A)
    finally:
        mod._default_bars = mod_default
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["symbols"] == ["FIXA", "FIXC", "FIXB", "FIXW"]          # by exposure (5,000 / 2,000 / 1,500), `with` last
    assert b["matrix"][0][1] == pytest.approx(-1.0, abs=1e-4) and b["matrix"][3][3] is None
    assert {"a": "FIXA", "b": "FIXC", "rho": b["matrix"][0][1]} in b["concentrated_pairs"]
    assert set(b) >= {"symbols", "matrix", "days", "threshold", "basis", "notes"}
    r = client.get(f"/api/v1/risk/correlation/{U1}?with=BAD%20SYM", headers=A)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_symbol"
    assert client.get(f"/api/v1/risk/correlation/{U1}?days=5", headers=A).status_code == 422


# ── PV2-B-20 the named stress scenarios ──────────────────────────────────────
def test_pv2_b_20_named_scenarios_hand_checked():
    cash = [{"order_id": "x", "symbol": "FIXX", "sector": "IT", "quantity": 100, "entry": 500.0, "stop": 480.0},
            {"order_id": "y", "symbol": "FIXY", "sector": "Bank", "quantity": 40, "entry": 1000.0, "stop": 950.0},
            {"order_id": "z", "symbol": "FIXZ", "sector": "IT", "quantity": 10, "entry": 200.0, "stop": None}]
    fno = [{"scenarios": [{"name": "und_down_2", "pnl_rs": -1000.0}], "stress": {"iv_up_10_rs": 2500.0}}]
    out = stress_named.named(cash, fno, correlated=["FIXX", "FIXY"])
    s = {x["name"]: x for x in out["scenarios"]}
    assert list(s) == ["index_down", "sector_gap", "correlated_stops", "gap_beyond_stops", "iv_up"]
    assert all(set(x) >= {"name", "label", "loss_rs", "assumption"} and x["assumption"] for x in s.values())
    # shares 50,000 + 40,000 = 90,000 × 2 % = 1,800, plus the F&O structure's −1,000
    assert (s["index_down"]["label"], s["index_down"]["loss_rs"], s["index_down"]["shares_pnl_rs"]) == ("Nifty -2%", 2800.0, -1800.0)
    assert (s["sector_gap"]["label"], s["sector_gap"]["loss_rs"]) == ("IT gap -3%", 1500.0)          # 50,000 × 3 %
    cost = desk.round_trip_cost
    m = desk.COST_MODEL
    exp_stops = 100 * 20 + cost(100, 500.0, 480.0, m) + 40 * 50 + cost(40, 1000.0, 950.0, m)
    assert s["correlated_stops"]["loss_rs"] == pytest.approx(round(exp_stops, 2))
    assert s["correlated_stops"]["symbols"] == ["FIXX", "FIXY"]
    exp_gap = 100 * 20 * 1.25 + cost(100, 500.0, 475.0, m) + 40 * 50 * 1.25 + cost(40, 1000.0, 937.5, m)
    assert (s["gap_beyond_stops"]["label"], s["gap_beyond_stops"]["loss_rs"]) == ("Gap beyond stops +25%", pytest.approx(round(exp_gap, 2)))
    assert (s["iv_up"]["label"], s["iv_up"]["loss_rs"], s["iv_up"]["pnl_rs"]) == ("IV +10 pts (F&O)", 0.0, 2500.0)
    assert out["unpriced"] == ["FIXZ"]


def test_pv2_b_20b_unknown_inputs_are_null_with_a_reason():
    cash = [{"symbol": "FIXX", "sector": "IT", "quantity": 100, "entry": 500.0, "stop": 480.0}]
    out = stress_named.named(cash, None, correlated=None, fno_reason="MOCK chain down", corr_reason="MOCK no bars")
    s = {x["name"]: x for x in out["scenarios"]}
    assert s["index_down"]["loss_rs"] is None and "MOCK chain down" in s["index_down"]["reason"]
    assert s["index_down"]["shares_pnl_rs"] == -1000.0
    assert s["iv_up"]["loss_rs"] is None and s["correlated_stops"]["loss_rs"] is None
    assert s["correlated_stops"]["reason"] == "MOCK no bars"
    assert s["sector_gap"]["loss_rs"] == 1500.0                    # needs neither source
    out = stress_named.named(cash, [], correlated=[])
    s = {x["name"]: x for x in out["scenarios"]}
    assert s["correlated_stops"]["loss_rs"] == 0.0 and "nothing is counted" in s["correlated_stops"]["assumption"]
    assert s["iv_up"]["loss_rs"] == 0.0 and s["index_down"]["loss_rs"] == 1000.0


def test_pv2_b_20c_route_keeps_the_existing_scenarios_and_adds_the_named(client):
    r = client.get(f"/api/v1/risk/stress-test/{U1}", headers=A)
    assert r.status_code == 200, r.text
    names = [s["name"] for s in r.json()["scenarios"]]
    assert names == ["gap_through_stop", "sector_shock", "market_shock", "index_down", "sector_gap", "correlated_stops",
                     "gap_beyond_stops", "iv_up"]
    assert r.json()["named"]["version"] == stress_named.VERSION
