"""Desk audit wave 1 (2026-10-28), B3 and the backend half of F1 (test_reports/desk_audit_wave1_TESTCASES.md B3-1 … B3-7).

  B3-1/2  GET /api/markets/home: a live snapshot with a value but no day change (Yahoo's 2-day window held one bar)
          replaced the tape's end-of-day change, and the desk showed "— (—)" for NIFTY and BANK NIFTY. A live value
          now replaces the tape only together with its change.
  B3-3/4/7 POST /api/desk/strategy/ideas: the "strategy that fits" (the preferred strategy) carries `account_size`, the
          risk service's own sizing of ITS TradePlan for the signed-in account (plan_sizing.size_for), so a card no
          longer shows "Size 34 shares" beside a one-lot "Buy 700 shares…". The AI-watchlist job passes no sizer and
          its stored lists keep their shape.
  B3-5    Each strategy row says whether its shown reward : risk reaches the plan's minimum (1.5 by default), so a
          0.19 : 1 strategy is never "viable" on a card.
  B3-6    The sizing basis and the kill-switch scope are plain words: no file path, no function name.

No network and no real database: MOCK — not real data. The ideas route runs on the fixture world of
tests/test_strategy_ideas.py (real plan builder and payoff engine); the risk service's sizing is a stub.
"""
from __future__ import annotations

import asyncio
import inspect
from typing import Any, Dict, List

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from routes import markets
from services.positional_engine import nse_live
from services.strategy_plan import ideas as ideas_mod
from tests.test_strategy_ideas import A, IDEAS_BODY, client  # noqa: F401 — `client` is the ideas route fixture

PATH_WORDS = ("services/", ".py", ".decide", "routes/", "GET /api")


# ── B3-1 / B3-2: the index tiles of GET /api/markets/home ────────────────────

def _home(monkeypatch, live: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    from services.positional_engine import market_dashboard as md

    async def build():
        return {"as_of_date": "2026-10-27", "breadth": {}}

    async def live_snapshot():
        return live

    async def nothing():
        return {}

    async def tape():
        return [
            {"name": "Nifty 50", "value": 22753.2, "change_pct": 0.68, "is_vix": False, "trend": None, "spark": [22600.0, 22753.2], "as_of": "2026-10-27"},
            {"name": "Nifty Bank", "value": 54366.7, "change_pct": 0.15, "is_vix": False, "trend": None, "spark": [54287.35, 54366.7], "as_of": "2026-10-27"},
            {"name": "India VIX", "value": 17.16, "change_pct": 1.78, "is_vix": True, "trend": None, "spark": [16.86, 17.16], "as_of": "2026-10-27"},
        ]

    async def movers():
        return {"as_of": None, "gainers": [], "losers": []}

    async def none():
        return None

    async def no_news():
        return []

    async def fake_user(request: Request):
        return {"user_id": "u1"}

    monkeypatch.setattr(md, "build", build)
    monkeypatch.setattr(nse_live, "get_live_snapshot", live_snapshot)
    monkeypatch.setattr(nse_live, "get_global_snapshot", nothing)
    monkeypatch.setattr(nse_live, "get_index_tape", tape)
    monkeypatch.setattr(markets, "_top_movers", movers)
    monkeypatch.setattr(markets, "_fii_dii", none)
    monkeypatch.setattr(markets, "_news", no_news)
    monkeypatch.setattr(markets, "get_current_user", fake_user)
    markets._CACHE.update({"ts": 0.0, "data": None})
    app = FastAPI()
    app.include_router(markets.router)
    d = TestClient(app).get("/api/markets/home").json()
    markets._CACHE.update({"ts": 0.0, "data": None})
    return {i["name"]: i for i in d["indices"]}


def test_b3_1_a_live_value_without_its_change_keeps_the_tapes_end_of_day_tile(monkeypatch):
    # What staging's snapshot held on 28 Oct before the open (read-only probe): closes, every change_pct None.
    by = _home(monkeypatch, {"nifty50": {"close": 22753.2, "change_pct": None}, "vix": {"value": 17.16, "change_pct": None},
                             "sectors": [{"sector": "Bank", "close": 54366.7, "change_pct": None}]})
    for name, pct in (("Nifty 50", 0.68), ("Nifty Bank", 0.15), ("India VIX", 1.78)):
        t = by[name]
        assert t["change_pct"] == pct and t["change"] is not None, t       # never a value with a null change
        assert t["as_of"] == "2026-10-27"                                  # the tape's own bar day, not "live"
    assert by["Nifty 50"]["change"] == round(22753.2 - 22753.2 / 1.0068, 2)


def test_b3_2_a_live_value_with_its_change_still_replaces_the_tape(monkeypatch):
    by = _home(monkeypatch, {"nifty50": {"close": 22900.0, "change_pct": 0.64}, "vix": {}, "sectors": []})
    assert by["Nifty 50"]["value"] == 22900.0 and by["Nifty 50"]["change_pct"] == 0.64 and by["Nifty 50"]["as_of"] is None
    assert by["Nifty Bank"]["value"] == 54366.7 and by["Nifty Bank"]["change_pct"] == 0.15     # no live value: the tape


# ── B3-3 / B3-7: the strategy that fits is sized for the account ─────────────

def _stub_sizing(monkeypatch, answer=None, fail: bool = False) -> List[Dict[str, Any]]:
    from services.risk_gate import plan_sizing
    seen: List[Dict[str, Any]] = []

    async def size_for(db, tp, user_id, *, now=None):
        seen.append({"plan_id": tp.get("plan_id"), "segment": (tp.get("strategy") or {}).get("segment"), "user": user_id})
        if fail:
            raise RuntimeError("MOCK: the risk snapshot could not be read")
        return answer or {"status": "not_sizable", "quantity": None, "lots": None, "unit": "lots per leg",
                          "blocking": [{"code": "per_trade_risk_exceeded", "check": "per_trade", "severity": "block",
                                        "message": "MOCK: one lot's loss is above your per-trade budget"}]}
    monkeypatch.setattr(plan_sizing, "size_for", size_for)
    return seen


def test_b3_3_the_preferred_strategy_carries_the_risk_services_size_of_its_own_trade_plan(client, monkeypatch):  # noqa: F811
    seen = _stub_sizing(monkeypatch)
    r = client.post("/api/desk/strategy/ideas", json=IDEAS_BODY, headers=A)
    assert r.status_code == 200
    ideas = r.json()["ideas"]
    with_pref = [i for i in ideas if i["preferred"]]
    assert with_pref, "the fixture world must give at least one preferred strategy"
    assert len(seen) == len(with_pref) and {s["user"] for s in seen} == {"user_a"}       # B3-7: the signed-in account
    for i in ideas:
        sized = [s for s in i["strategies"] if "account_size" in s]
        if not i["preferred"]:
            assert sized == []
            continue
        assert [s["id"] for s in sized] == [i["preferred"]]                              # only the strategy that fits
        row = sized[0]
        assert row["account_size"]["status"] == "not_sizable"
        assert row["trade_plan_id"] in {s["plan_id"] for s in seen}                       # ITS TradePlan, not the cash one
        if row["segment"] != "cash":
            assert row["trade_plan_id"] != i["trade_plan_id"]


def test_b3_3b_a_sizing_failure_is_unavailable_and_the_ideas_still_answer(client, monkeypatch):  # noqa: F811
    _stub_sizing(monkeypatch, fail=True)
    r = client.post("/api/desk/strategy/ideas", json=IDEAS_BODY, headers=A)
    assert r.status_code == 200
    rows = [s for i in r.json()["ideas"] for s in i["strategies"] if "account_size" in s]
    assert rows and all(s["account_size"]["status"] == "unavailable" and "RuntimeError" in s["account_size"]["reason"] for s in rows)


def test_b3_3c_no_preferred_strategy_or_no_trade_plan(monkeypatch):
    calls: List[Any] = []

    async def sizer(tp):
        calls.append(tp)
        return {"status": "sized", "quantity": 34}

    idea = {"symbol": "X", "preferred": None, "strategies": [{"id": "cash:a"}]}
    asyncio.run(ideas_mod.size_fit(idea, {"preferred": None, "candidates": []}, sizer))
    assert calls == [] and "account_size" not in idea["strategies"][0]
    idea = {"symbol": "X", "preferred": "combination:covered_call", "strategies": [{"id": "combination:covered_call"}]}
    asyncio.run(ideas_mod.size_fit(idea, {"preferred": "combination:covered_call", "candidates": [{"id": "combination:covered_call", "trade_plan": None}]}, sizer))
    assert calls == [] and idea["strategies"][0]["account_size"]["status"] == "unavailable"
    tp = {"plan_id": "tp_cc"}
    idea = {"symbol": "X", "preferred": "cash:a", "strategies": [{"id": "cash:a"}, {"id": "combination:covered_call"}]}
    plan = {"preferred": "cash:a", "candidates": [{"id": "combination:covered_call", "trade_plan": {"plan_id": "tp_other"}}, {"id": "cash:a", "trade_plan": tp}]}
    asyncio.run(ideas_mod.size_fit(idea, plan, sizer))
    assert calls == [tp] and idea["strategies"][0]["account_size"] == {"status": "sized", "quantity": 34}
    assert "account_size" not in idea["strategies"][1]


def test_b3_4_without_a_sizer_nothing_is_attached():
    idea = {"symbol": "X", "preferred": "cash:a", "strategies": [{"id": "cash:a"}]}
    asyncio.run(ideas_mod.size_fit(idea, {"preferred": "cash:a", "candidates": [{"id": "cash:a", "trade_plan": {"plan_id": "tp"}}]}, None))
    assert idea == {"symbol": "X", "preferred": "cash:a", "strategies": [{"id": "cash:a"}]}
    assert inspect.signature(ideas_mod.build_ideas).parameters["sizer"].default is None   # the AI-watchlist job's call is unchanged


# ── B3-5: the minimum reward : risk on each strategy row ─────────────────────

def test_b3_5_meets_min_reward_risk():
    f = ideas_mod.meets_min_reward_risk
    assert f("candidate", 0.19, 2.4, 1.5) is False          # the library's 0.19 : 1 "viable" (audit 2026-10-28)
    assert f("candidate", 1.64, None, 1.5) is True
    assert f("candidate", 1.5, None, 1.5) is True           # at the minimum is enough
    assert f("candidate", None, 2.0, 1.5) is True           # no net figure: the gross ratio
    assert f("candidate", None, None, 1.5) is None
    assert f("no_trade", 0.2, None, 1.5) is None            # not viable: nothing to compare
    assert f("candidate", 0.19, None, None) is None


def test_b3_5b_strategies_of_carries_the_plans_minimum(client, monkeypatch):  # noqa: F811
    _stub_sizing(monkeypatch)
    b = client.post("/api/desk/strategy/ideas", json={**IDEAS_BODY, "min_reward_risk": 1.5}, headers=A).json()
    rows = [s for i in b["ideas"] for s in i["strategies"]]
    assert rows and all(s["min_reward_risk"] == 1.5 for s in rows)
    for s in rows:
        want = ideas_mod.meets_min_reward_risk(s["status"], s["reward_risk_net"], s["reward_risk_gross"], 1.5)
        assert s["meets_min_reward_risk"] is want, s["id"]


# ── B3-6: plain words, no file paths ─────────────────────────────────────────

def test_b3_6_the_sizing_basis_and_the_kill_switch_scope_name_no_file_or_function():
    from routes import risk_controls
    from services.risk_gate import plan_sizing
    assert not any(w in plan_sizing.BASIS for w in PATH_WORDS), plan_sizing.BASIS
    src = inspect.getsource(risk_controls.status)
    scope = src[src.index('"scope"'):src.index('"not_in_scope"')]
    assert "universal risk service" in scope and not any(w in scope for w in PATH_WORDS), scope
