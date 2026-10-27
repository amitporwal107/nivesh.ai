"""AI scanner watchlist — B-1 … B-10 of test_reports/ai_scanner_watchlist_TESTCASES.md.

The system caller (deps.system_caller), the shaping of a day (services/ai_watchlist_build), the job's exits
(scripts/build_ai_watchlist), the store's write-once rule and run of days (services/ai_watchlist_store) and the read route
(routes/ai_watchlist). No database, NSE, DaaS or Kite: every outside call is stubbed.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

import deps
from routes import ai_watchlist as route
from scripts import build_ai_watchlist as job
from services import ai_watchlist_build as build
from services import ai_watchlist_store as store
from services import strategy_levels

SYS = build.SYSTEM_USER


def bare_request(headers=None):
    return Request({"type": "http", "method": "GET", "path": "/x", "query_string": b"", "headers": headers or []})


# ── B-1 … B-3: the system caller ──────────────────────────────────────────

def test_inside_the_system_caller_the_user_is_the_system_user_without_any_session():
    async def go():
        with deps.system_caller(SYS):
            return await deps.get_current_user(bare_request())
    u = asyncio.run(go())
    assert u["user_id"] == "system:ai-watchlist" and u["_system"] is True and u["_active_profile_id"] is None


def test_outside_it_the_normal_check_applies():
    with pytest.raises(HTTPException) as e:
        asyncio.run(deps.get_current_user(bare_request()))
    assert e.value.status_code == 401


def test_a_task_started_outside_never_sees_it_and_tasks_started_inside_do():
    async def who():
        try:
            return (await deps.get_current_user(bare_request()))["user_id"]
        except HTTPException as e:
            return e.status_code

    async def go():
        outside = asyncio.ensure_future(who())          # created before the block: its own context
        with deps.system_caller(SYS):
            inside = await asyncio.gather(who(), who())
            seen_outside = await outside
        after = await who()
        return inside, seen_outside, after

    inside, seen_outside, after = asyncio.run(go())
    assert inside == ["system:ai-watchlist", "system:ai-watchlist"]
    assert seen_outside == 401 and after == 401


def test_the_system_caller_is_never_an_admin():
    async def go():
        with deps.system_caller(SYS):
            await deps.require_admin(bare_request())
    with pytest.raises(HTTPException) as e:
        asyncio.run(go())
    assert e.value.status_code == 403
    with pytest.raises(ValueError):
        with deps.system_caller({"user_id": "x", "is_admin": True}):
            pass
    with pytest.raises(ValueError):
        with deps.system_caller({"name": "no id"}):
            pass


def test_no_header_or_cookie_can_turn_it_on():
    req = bare_request([(b"cookie", b"system_caller=1"), (b"x-system-caller", b"system:ai-watchlist")])
    with pytest.raises(HTTPException) as e:
        asyncio.run(deps.get_current_user(req))
    assert e.value.status_code == 401


# ── B-7: shaping a day ────────────────────────────────────────────────────

def idea(sym, preferred=None, strategies=(), plan_status="plan"):
    return {"symbol": sym, "name": f"{sym} Ltd", "direction": "bullish", "fno_eligible": True, "source": "ai_scanner",
            "scanner": {"bucket": "pre_breakout", "status": "awaiting", "score": 84, "close": 100.0, "close_date": "2026-10-26",
                        "entry": 101.0, "stop": 95.0, "target": 115.0, "sector": "Banks", "reasons": ["MOCK"]},
            "plan_status": plan_status, "status_reasons": [{"code": "c", "message": "a reason"}], "plan_inputs": {"underlying": sym},
            "preferred": preferred, "strategies": list(strategies)}


def opt(u, fit, rr, structure="bear_put_spread"):
    return {"underlying": u, "structure": structure, "name": f"{structure} on {u}", "fit": {"score": fit, "because": []},
            "reward_risk": rr, "legs": [{"kind": "option"}], "alternatives": [{"underlying": u}]}


def test_a_cash_entry_keeps_the_scanner_view_the_plan_status_and_the_strategy_that_fits():
    cash = {"id": "cash:x", "segment": "cash", "label": "Buy shares", "status": "candidate", "sizing": {"quantity": 208}}
    pref = {"id": "options:y", "segment": "options", "label": "Bull call spread", "status": "candidate", "legs_text": "Buy … sell …",
            "max_loss": -7000, "reward_risk_net": 2.4}
    e = build.cash_entry(idea("ICICIBANK", "options:y", [cash, pref]), 1)
    assert e["rank"] == 1 and e["scanner"]["entry"] == 101.0 and e["sector"] == "Banks"
    assert e["preferred"]["label"] == "Bull call spread" and e["sized_shares"] == 208
    assert e["status_reasons"] == ["a reason"] and e["plan_inputs"] == {"underlying": "ICICIBANK"}
    assert build.cash_entry(idea("CRISIL", None, [], "no_trade"), 2)["preferred"] is None


def test_fno_merges_both_classes_by_fit_then_reward_risk_and_drops_alternatives():
    top = {"classes": {"index_options": {"ideas": [opt("BANKNIFTY", 100.0, 1.5), opt("NIFTY", 92.5, 1.0)]},
                       "stock_fno": {"ideas": [opt("INDUSTOWER", 100.0, 2.0), opt("PETRONET", 92.5, None), opt("DRREDDY", 92.5, 1.2)]}}}
    rows = build.fno_entries(top)
    assert [(r["underlying"], r["kind"], r["rank"]) for r in rows] == [
        ("INDUSTOWER", "stock", 1), ("BANKNIFTY", "index", 2), ("DRREDDY", "stock", 3), ("NIFTY", "index", 4), ("PETRONET", "stock", 5)]
    assert all("alternatives" not in r for r in rows)
    assert len(build.fno_entries(top, limit=2)) == 2


def test_a_day_carries_the_notes_and_never_claims_a_broker_send():
    ideas = {"ideas": [idea(f"S{i}") for i in range(12)], "ranking_note": "by score", "caveats": ["c"], "data_as_of": {"price": "2026-10-26"}}
    top = {"classes": {"index_options": {"ideas": [opt("NIFTY", 90.0, 1.0)], "as_of": "2026-10-26"},
                       "stock_fno": {"ideas": [], "universe": {"skipped": [{"underlying": "PREMEXPLN"}]}, "unavailable": [{"underlying": "X"}]}},
           "ranking_note": "fit", "gaps": ["g"], "staleness_note": "older regime", "regime": {"available": True, "label": "Bearish", "as_of": "2026-10-23"}}
    d = build.shape_day("2026-10-26", ideas, top, datetime(2026, 10, 26, 14, 45, tzinfo=timezone.utc))
    assert len(d["cash"]) == 10 and len(d["fno"]) == 1 and d["sent_to_broker"] is False
    n = d["notes"]
    assert (n["fno_staleness"], n["fno_chain_as_of"], n["regime"]["as_of"]) == ("older regime", "2026-10-26", "2026-10-23")
    assert n["fno_skipped"] == [{"underlying": "PREMEXPLN"}] and n["fno_unavailable"] == [{"underlying": "X"}]


# ── stored levels (test_reports/fno_idea_paper_trade_TESTCASES.md B-7, B-8) ──

# The REAL staging capture of POST /api/desk/strategy/top (2026-10-21) the browser specs use; see also
# tests/test_fno_idea_paper_trade_contract.py, which pins the browser's levels request for its BANKNIFTY idea.
CAPTURED_TOP = Path(__file__).resolve().parents[2] / "frontend-v5" / "e2e" / "fixtures" / "desk-strategy-top.json"
LIST_NOW = datetime(2026, 10, 21, 14, 45, tzinfo=timezone.utc)


def captured_top():
    assert CAPTURED_TOP.exists(), f"{CAPTURED_TOP} (the real board capture) must be present"
    return json.loads(CAPTURED_TOP.read_text(encoding="utf-8"))


def test_each_fno_entry_stores_the_levels_engines_answer_for_that_idea_on_the_list_day():
    top = captured_top()
    d = build.shape_day("2026-10-21", {"ideas": []}, top, LIST_NOW)
    assert [e["underlying"] for e in d["fno"]] == ["MPHASIS", "ICICIBANK", "BANKNIFTY", "NIFTY"]
    for e in d["fno"]:
        refs = build.levels_refs_for(top, e["underlying"])
        want = strategy_levels.compute(build.payoff_request_for(e), refs, date(2026, 10, 21))
        assert e["strategy_levels"] == {"as_of": "2026-10-21", "computed_at": LIST_NOW.isoformat(), "refs": refs, "result": want, "error": None}
        assert want["valid"] is True and want["sent_to_broker"] is False
        assert refs["expected_move"] is not None and refs["put_wall"] is None and refs["call_wall"] is None
    assert d["sent_to_broker"] is False


def test_an_idea_that_cannot_be_priced_or_an_engine_failure_keeps_the_day_and_says_why(monkeypatch, caplog):
    unpriced = {"classes": {"index_options": {"ideas": [opt("NIFTY", 90.0, 1.0)]}}}          # no reference price
    lv = build.shape_day("2026-10-26", {"ideas": []}, unpriced, LIST_NOW)["fno"][0]["strategy_levels"]
    assert lv["result"] is None and lv["error"].startswith("The idea has no reference price")

    def boom(*a, **k):
        raise ZeroDivisionError("MOCK engine failure")
    monkeypatch.setattr(strategy_levels, "compute", boom)
    with caplog.at_level("WARNING"):
        d = build.shape_day("2026-10-21", {"ideas": []}, captured_top(), LIST_NOW)
    assert len(d["fno"]) == 4
    assert all(e["strategy_levels"]["result"] is None and "ZeroDivisionError" in e["strategy_levels"]["error"] for e in d["fno"])
    assert "levels for BANKNIFTY failed: ZeroDivisionError" in caplog.text


def test_the_dry_run_summary_names_each_entrys_levels_or_why_there_are_none():
    top = captured_top()
    d = build.shape_day("2026-10-21", {"ideas": []}, top, LIST_NOW)
    bank = next(e for e in d["fno"] if e["underlying"] == "BANKNIFTY")
    assert job.levels_text(bank) == "levels bearish: stop 55271.88 / target 54641.63"
    assert job.levels_text({"strategy_levels": {"error": "no prices"}}) == "levels: no prices"
    assert job.levels_text({"strategy_levels": {"result": {"valid": False, "problems": [{"message": "bad"}]}}}) == "levels: not valid (bad)"
    assert job.levels_text({}) == "levels: none stored"


# ── B-4 … B-6: the job ────────────────────────────────────────────────────

@pytest.fixture
def job_env(monkeypatch):
    seen = {"built": 0, "inserted": []}
    state = {"signals": 666, "has": False, "insert_ok": True}

    async def signals_on(d):
        return state["signals"]

    async def has_day(d):
        return state["has"]

    async def build_day(d):
        seen["built"] += 1
        # The board read the list date's chain: a day on another day's chain (or none) is refused (exit 4,
        # tests/test_watchlist_fno_chain_expiry.py).
        top = {"classes": {"index_options": {"as_of": d, "ideas": []}}}
        return build.shape_day(d, {"ideas": [idea("A")]}, top, datetime(2026, 10, 26, tzinfo=timezone.utc))

    async def insert_day(doc):
        seen["inserted"].append(doc["list_date"])
        return state["insert_ok"]

    import scripts.run_positional_engine as rpe
    monkeypatch.setattr(rpe, "signals_on", signals_on)
    monkeypatch.setattr(store, "has_day", has_day)
    monkeypatch.setattr(store, "insert_day", insert_day)
    monkeypatch.setattr(build, "build_day", build_day)
    return seen, state


def test_no_scan_for_the_date_writes_nothing_and_exits_2(job_env):
    seen, state = job_env
    state["signals"] = 0
    assert asyncio.run(job.run("2026-10-26", skip_if_done=False, dry_run=False)) == 2
    assert seen == {"built": 0, "inserted": []}


def test_skip_if_done_with_the_day_stored_builds_nothing(job_env):
    seen, state = job_env
    state["has"] = True
    assert asyncio.run(job.run("2026-10-26", skip_if_done=True, dry_run=False)) == 0
    assert seen == {"built": 0, "inserted": []}


def test_dry_run_builds_and_writes_nothing(job_env):
    seen, _ = job_env
    assert asyncio.run(job.run("2026-10-26", skip_if_done=True, dry_run=True)) == 0
    assert seen == {"built": 1, "inserted": []}


def test_a_build_is_stored_and_a_race_is_reported(job_env):
    seen, state = job_env
    assert asyncio.run(job.run("2026-10-26", skip_if_done=True, dry_run=False)) == 0
    assert seen["inserted"] == ["2026-10-26"]
    state["insert_ok"] = False
    assert asyncio.run(job.run("2026-10-26", skip_if_done=False, dry_run=False)) == 3


# ── B-8, B-10: the store ──────────────────────────────────────────────────

def test_a_day_is_written_once(monkeypatch):
    from pymongo.errors import DuplicateKeyError

    class Coll:
        def __init__(self):
            self.ids = set()

        async def insert_one(self, doc):
            if doc["_id"] in self.ids:
                raise DuplicateKeyError("dup")
            self.ids.add(doc["_id"])

    c = Coll()
    monkeypatch.setattr(store, "db", {store.COL: c})
    assert asyncio.run(store.insert_day({"list_date": "2026-10-26"})) is True
    assert asyncio.run(store.insert_day({"list_date": "2026-10-26", "cash": ["changed"]})) is False


@pytest.mark.parametrize("earlier, stored, want", [
    ([], ["2026-10-23", "2026-10-26"], 1),                                       # new today
    (["2026-10-23"], ["2026-10-23", "2026-10-26"], 2),                          # yesterday's list too
    (["2026-10-21"], ["2026-10-21", "2026-10-23", "2026-10-26"], 1),            # missed the 23rd: the run is broken
    (["2026-10-21", "2026-10-23"], ["2026-10-21", "2026-10-23", "2026-10-26"], 3),
])
def test_days_on_list_counts_stored_days_in_a_row(earlier, stored, want):
    assert store.run_of_days("2026-10-26", earlier, stored) == want


# ── B-9, B-10: the route ──────────────────────────────────────────────────

DAY = {"list_date": "2026-10-26", "built_at": "x", "rules": {}, "notes": {}, "sent_to_broker": False,
       "cash": [{"rank": 1, "symbol": "ICICIBANK"}, {"rank": 2, "symbol": "CRISIL"}],
       "fno": [{"rank": 1, "underlying": "BANKNIFTY"}]}


@pytest.fixture
def api(monkeypatch):
    days = [{"list_date": "2026-10-26", "cash": 2, "fno": 1}, {"list_date": "2026-10-23", "cash": 10, "fno": 10}]

    async def user(request):
        if request.headers.get("x-anon"):
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": "u1"}

    async def dateline(limit=120):
        return [dict(d) for d in days]

    async def get_day(d=None):
        import copy
        return copy.deepcopy(DAY) if d in (None, "2026-10-26") else None

    async def earlier(d, lookback_days=30):
        return {"cash": {"ICICIBANK": ["2026-10-23"]}, "fno": {}}

    monkeypatch.setattr(route, "get_current_user", user)
    monkeypatch.setattr(store, "dateline", dateline)
    monkeypatch.setattr(store, "get_day", get_day)
    monkeypatch.setattr(store, "earlier_appearances", earlier)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app), days


def test_route_newest_day_by_default_with_dateline_and_runs(api):
    c, _ = api
    b = c.get("/api/desk/ai-watchlist").json()
    assert b["list_date"] == "2026-10-26" and [d["list_date"] for d in b["available_dates"]] == ["2026-10-26", "2026-10-23"]
    icici, crisil = b["cash"]
    assert (icici["earlier_list_dates"], icici["days_on_list"]) == (["2026-10-23"], 2)
    assert (crisil["earlier_list_dates"], crisil["days_on_list"]) == ([], 1)
    assert b["fno"][0]["days_on_list"] == 1 and b["read_only"] is True


def test_route_a_date_unknown_malformed_and_signed_out(api):
    c, _ = api
    assert c.get("/api/desk/ai-watchlist", params={"date": "2026-10-26"}).json()["list_date"] == "2026-10-26"
    r = c.get("/api/desk/ai-watchlist", params={"date": "2026-10-01"})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "not_stored"
    assert c.get("/api/desk/ai-watchlist", params={"date": "26-10-2026"}).status_code == 422
    assert c.get("/api/desk/ai-watchlist", headers={"x-anon": "1"}).status_code == 401


def test_route_with_nothing_stored_yet_says_when_the_job_runs(api):
    c, days = api
    days.clear()
    b = c.get("/api/desk/ai-watchlist").json()
    assert b["available_dates"] == [] and b["cash"] == [] and "22:45 IST" in b["empty_reason"]
