"""Phase 3 decision cards, backend: BE-1 … BE-7 of test_reports/p3_decision_cards_TESTCASES.md.

What the card renders must come from the TradePlan (nothing is computed in the browser), so the plan carries its
evidence, warnings and gap risk (BE-1 … BE-3); the plan route lists only the versions the caller can open, so a card can
switch to the newest (BE-4); the AI watchlist keeps the scan's basis (BE-5) and says since when an idea has been carried
(BE-6); the admin job-health route answers for the AI scanner's own run records (BE-7).

Plans are built by the real plan builder from the MOCK sources of tests/test_strategy_plan.py, and the F&O board idea is
the REAL 2026-10-21 staging capture (frontend-v5/e2e/fixtures/desk-strategy-top.json). Mongo is the in-memory stand-in
of tests/test_desk_trading.py. No network.
"""
from __future__ import annotations

import asyncio
import copy
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

import routes.desk_trading as desk_route
import deps
import routes.risk_controls as risk_route
from routes import ai_watchlist as aiw_route
from services import ai_watchlist_build as awb
from services import ai_watchlist_store as store
from services import job_runs
from services.strategy_plan import regime_fit
from services.strategy_plan import trade_plan as tpm
from tests.test_desk_trading import FakeDb
from tests.test_strategy_plan import build, world

REPO = Path(__file__).resolve().parents[2]
TOP = json.loads((REPO / "frontend-v5" / "e2e" / "fixtures" / "desk-strategy-top.json").read_text())
KEYS = ["regime", "trend", "relative_strength", "momentum", "volume", "structure"]
WARN = ["event", "liquidity", "concentration", "correlation"]


def cash_tp(plan):
    return next(c for c in plan["candidates"] if c["segment"] == "cash")["trade_plan"]


def board_plans():
    top = copy.deepcopy(TOP)
    regime_fit.attach_trade_plans(top)
    return top


# ── BE-1: a cash plan carries its evidence and warnings ────────────────────
def test_be1_a_cash_plan_carries_six_evidence_lines_and_four_warnings_from_the_ledger():
    plan = build(instrument="cash")
    tp = cash_tp(plan)
    ev = tp["evidence"]["items"]
    assert [e["key"] for e in ev] == KEYS
    ledger = {i["key"]: i for i in plan["evidence"]}
    for row, lk in zip(ev, ("desk_regime", "trend_structure", "relative_strength", "momentum", "volume", "levels")):
        want = ledger[lk]
        assert row["status"] == ("unavailable" if want["direction"] == "unavailable" else "ok")
        assert row["text"].startswith(want["interpretation"]) and row["as_of"] == want["source_as_of"]
    # the MOCK world's confirmed bull flag joins the price-structure line
    assert "Bull flag" in ev[-1]["text"]
    w = {x["key"]: x for x in tp["warnings"]}
    assert list(w) == WARN
    assert w["event"]["status"] in ("clear", "flagged") and w["event"]["text"]
    assert w["liquidity"]["status"] == "clear" and "Eligible for the scanner universe" in w["liquidity"]["text"]
    assert w["concentration"]["status"] == "at_entry" and w["correlation"]["status"] == "unavailable"
    # the plan is the same for every user: no portfolio value is stored on it
    assert "value_rs" not in json.dumps(tp["evidence"]) + json.dumps(tp["warnings"])
    assert tp["rules_version"] == tpm.RULES_VERSION and tpm.validate(tp) == []


def test_be1b_an_unreadable_source_is_unavailable_with_its_reason_and_an_event_in_the_horizon_is_flagged():
    snaps = world()
    snaps["indicators"] = {"ok": False, "data": None, "error": "MOCK: indicators not read", "source": "MOCK", "as_of": None, "version": None}
    ev = tpm.ledger_evidence(build(snaps=snaps, instrument="cash")["evidence"])
    trend = next(e for e in ev["items"] if e["key"] == "trend")
    assert trend["status"] == "unavailable" and "MOCK: indicators not read" in trend["text"] and trend["direction"] is None
    # results inside the horizon: the event warning is flagged with the ledger's own words
    ledger = [{"key": "results_and_events", "direction": "conflicts", "interpretation": "Quarterly results are scheduled on 2026-10-24, inside the 10-day horizon: gap risk."},
              {"key": "corporate_actions", "direction": "neutral", "interpretation": "No ex-date inside the horizon."}]
    w = {x["key"]: x for x in tpm.ledger_warnings(ledger, {"segment": "cash"})}
    assert w["event"]["status"] == "flagged" and "Quarterly results are scheduled" in w["event"]["text"]
    assert w["liquidity"]["status"] == "unavailable"


# ── BE-2: an F&O board idea ────────────────────────────────────────────────
def test_be2_a_board_idea_takes_the_regime_and_trend_from_the_board_and_says_the_rest_is_not_computed():
    top = board_plans()
    tp = top["classes"]["index_options"]["ideas"][0]["trade_plan"]
    ev = {e["key"]: e for e in tp["evidence"]["items"]}
    assert list(ev) == KEYS
    assert ev["regime"]["status"] == "ok" and "Desk regime Bearish" in ev["regime"]["text"] and ev["regime"]["as_of"] == TOP["regime"]["as_of"]
    assert ev["trend"]["status"] == "ok" and ev["trend"]["text"].startswith("The measured trend is down")
    for k in ("relative_strength", "momentum", "volume", "structure"):
        assert ev[k]["status"] == "unavailable" and "F&O board" in ev[k]["text"]
    w = {x["key"]: x for x in tp["warnings"]}
    assert w["event"]["status"] == "unavailable" and w["liquidity"]["status"] == "clear"
    assert w["concentration"]["status"] == "at_entry" and w["correlation"]["status"] == "unavailable"
    assert tpm.validate(tp) == []


def test_be2b_without_a_measured_regime_the_regime_line_is_unavailable_with_the_reason():
    idea = copy.deepcopy(TOP["classes"]["index_options"]["ideas"][0])
    ev = tpm.board_evidence(idea, {"available": False, "reason": "MOCK: macro engine down"})
    assert ev["items"][0]["status"] == "unavailable" and "MOCK: macro engine down" in ev["items"][0]["text"]


# ── BE-3: gap and slippage risk ────────────────────────────────────────────
def test_be3_cash_and_options_plans_say_their_gap_and_slippage_risk():
    cash = cash_tp(build(instrument="cash"))
    assert "fill" in cash["costs"]["gap_risk"] and "% a side" in cash["costs"]["gap_risk"]
    opt = board_plans()["classes"]["index_options"]["ideas"][0]["trade_plan"]
    assert "end-of-day closes" in opt["costs"]["gap_risk"]


# ── BE-4: the versions a caller can open ───────────────────────────────────
@pytest.fixture
def plan_api(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(desk_route, "db", db)

    async def fake_user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": uid}
    monkeypatch.setattr(desk_route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(desk_route.router)
    c = TestClient(app)
    c.db = db
    return c


def test_be4_versions_list_only_the_plans_the_caller_can_open(plan_api):
    v1 = cash_tp(build(instrument="cash"))
    asyncio.run(tpm.store(plan_api.db, copy.deepcopy(v1), "system:ai-watchlist"))
    other = copy.deepcopy(v1)
    other["stop"]["price"] = 1161.0
    other = tpm.finalize({k: v for k, v in other.items() if k not in tpm.NOT_HASHED} | {"eligibility": v1["eligibility"]})
    asyncio.run(tpm.store(plan_api.db, copy.deepcopy(other), "user_b"))      # user B's newer version, same lineage
    mine = copy.deepcopy(v1)
    mine["stop"]["price"] = 1162.0
    mine = tpm.finalize({k: v for k, v in mine.items() if k not in tpm.NOT_HASHED} | {"eligibility": v1["eligibility"]})
    asyncio.run(tpm.store(plan_api.db, copy.deepcopy(mine), "user_a"))
    got = plan_api.get(f"/api/desk/trade-plans/{v1['plan_id']}", headers={"X-Test-User": "user_a"}).json()
    ids = [v["plan_id"] for v in got["versions"]]
    assert ids == [v1["plan_id"], mine["plan_id"]] and other["plan_id"] not in ids
    assert [v["version"] for v in got["versions"]] == [1, 3]
    # user B sees the system plan and their own, not user A's
    b = plan_api.get(f"/api/desk/trade-plans/{v1['plan_id']}", headers={"X-Test-User": "user_b"}).json()
    assert [v["plan_id"] for v in b["versions"]] == [v1["plan_id"], other["plan_id"]]
    assert plan_api.get(f"/api/desk/trade-plans/{other['plan_id']}", headers={"X-Test-User": "user_a"}).status_code == 404


# ── BE-5: the scan basis travels with the stored day ───────────────────────
SCAN_BASIS = {"date": "2026-10-26", "engine_versions": ["v1.1"], "price_basis": "corp_action_adjusted",
              "price_basis_rows": {"corp_action_adjusted": 2210, "raw_no_factors": 0, "raw_before_v1_1": 0},
              "exceptions": {"raw_prices": [], "truncated": [], "not_scored_after_truncation": []}, "exceptions_note": None,
              "data_quality": {"status": "clean", "warnings": 0, "problems": [], "checked_at": "2026-10-26T14:15:25+00:00"}}


def test_be5_a_day_stores_the_scan_basis_the_ideas_route_answered_and_a_day_without_it_reads_null():
    now = datetime(2026, 10, 26, 17, 15, tzinfo=timezone.utc)
    day = awb.shape_day("2026-10-26", {"ideas": [], "selection": {"scan_basis": SCAN_BASIS}}, {"classes": {}}, now)
    assert day["notes"]["scan_basis"] == SCAN_BASIS
    assert awb.shape_day("2026-10-26", {"ideas": []}, {"classes": {}}, now)["notes"]["scan_basis"] is None


# ── BE-6: carried from an earlier list ─────────────────────────────────────
def plan_entry(sym, entry, stop, target, pid):
    return {"symbol": sym, "trade_plan_id": pid, "trade_plan": {"plan_id": pid, "entry": {"price": entry}, "stop": {"price": stop},
            "targets": [{"name": "conservative", "price": target - 10, "primary": False}, {"name": "base", "price": target, "primary": True}]}}


DAYS = ["2026-10-27", "2026-10-23", "2026-10-22", "2026-10-21"]       # 24-26 Oct stored no list (weekend, holiday)
FIRST = {"list_date": "2026-10-22",
         "cash": [plan_entry("ICICIBANK", 1200.0, 1160.0, 1280.0, "tp_first")],
         "fno": [{"underlying": "BANKNIFTY", "net_premium": -8769.0,
                  "strategy_levels": {"result": {"underlying": {"stop": 55271.88, "target": 54641.63}}}}]}
TODAY = {"list_date": "2026-10-27", "built_at": "x", "rules": {}, "notes": {}, "sent_to_broker": False,
         "cash": [{**plan_entry("ICICIBANK", 1210.0, 1172.0, 1286.0, "tp_today"), "rank": 1}, {"rank": 2, "symbol": "CRISIL"}],
         "fno": [{"rank": 1, "underlying": "BANKNIFTY", "trade_plan_id": "tp_fno",
                  "trade_plan": {"entry": {"net_premium_rs": -9012.0}, "stop": {"price": 55300.0},
                                 "targets": [{"name": "t1", "price": 54600.0, "primary": True}]}}]}


@pytest.fixture
def carry_api(monkeypatch):
    asked = []

    async def user(request):
        return {"user_id": "u1"}

    async def dateline(limit=120):
        return [{"list_date": d, "cash": 1, "fno": 1} for d in DAYS]

    async def get_day(d=None):
        return copy.deepcopy(TODAY) if d in (None, "2026-10-27") else None

    async def earlier(d, lookback_days=30):
        return {"cash": {"ICICIBANK": ["2026-10-23", "2026-10-22"]}, "fno": {"BANKNIFTY": ["2026-10-23", "2026-10-22"]}}

    async def first_days(dates):
        asked.append(sorted(dates))
        return {"2026-10-22": copy.deepcopy(FIRST)} if "2026-10-22" in dates else {}

    monkeypatch.setattr(aiw_route, "get_current_user", user)
    monkeypatch.setattr(store, "dateline", dateline)
    monkeypatch.setattr(store, "get_day", get_day)
    monkeypatch.setattr(store, "earlier_appearances", earlier)
    monkeypatch.setattr(store, "days_for_levels", first_days)
    app = FastAPI()
    app.include_router(aiw_route.router)
    return TestClient(app), asked


def test_be6_an_idea_on_three_list_days_in_a_row_says_since_when_with_the_first_and_todays_levels(carry_api):
    c, asked = carry_api
    b = c.get("/api/desk/ai-watchlist").json()
    icici, crisil = b["cash"]
    assert icici["days_on_list"] == 3
    assert icici["carried"] == {
        "sessions": 3, "from": "2026-10-22",
        "first": {"list_date": "2026-10-22", "entry": 1200.0, "entry_kind": "price", "stop": 1160.0, "target": 1280.0,
                  "plan_id": "tp_first", "basis": "trade_plan"},
        "today": {"list_date": "2026-10-27", "entry": 1210.0, "entry_kind": "price", "stop": 1172.0, "target": 1286.0,
                  "plan_id": "tp_today", "basis": "trade_plan"}}
    assert "carried" not in crisil
    assert icici["levels_on_list"] == icici["carried"]["today"]
    assert crisil["levels_on_list"] == {"list_date": "2026-10-27", "entry": None, "entry_kind": "price", "stop": None, "target": None,
                                        "plan_id": None, "basis": "scanner"}
    bank = b["fno"][0]["carried"]
    assert bank["first"] == {"list_date": "2026-10-22", "entry": -8769.0, "entry_kind": "net_premium", "stop": 55271.88,
                             "target": 54641.63, "plan_id": None, "basis": "strategy_levels"}
    assert bank["today"]["entry"] == -9012.0 and bank["today"]["stop"] == 55300.0 and bank["today"]["basis"] == "trade_plan"
    assert asked == [["2026-10-22", "2026-10-22"]]             # one read for both segments' first day


@pytest.mark.parametrize("earlier,stored,want", [
    ([], ["2026-10-27", "2026-10-23"], "2026-10-27"),
    (["2026-10-23"], ["2026-10-27", "2026-10-23", "2026-10-22"], "2026-10-23"),
    (["2026-10-23", "2026-10-21"], ["2026-10-27", "2026-10-23", "2026-10-22", "2026-10-21"], "2026-10-23"),
])
def test_be6b_the_run_starts_where_run_of_days_stops_counting(earlier, stored, want):
    assert store.run_start("2026-10-27", earlier, stored) == want


def test_be6c_a_cash_entry_stored_before_plans_falls_back_to_the_scanners_levels():
    got = store.entry_levels({"symbol": "X", "scanner": {"entry": 100.0, "stop": 95.0, "target": 110.0}}, "cash", "2026-10-21")
    assert (got["entry"], got["stop"], got["target"], got["basis"], got["plan_id"]) == (100.0, 95.0, 110.0, "scanner", None)


# ── BE-7: the AI scanner's job health ──────────────────────────────────────
JOB = "positional_engine"


@pytest.fixture
def jobs_api(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(risk_route, "db", db)
    who = {"user": {"user_id": "a1", "role": "admin"}}

    async def fake_user(request):
        return who["user"]
    monkeypatch.setattr(deps, "get_current_user", fake_user)          # require_role("admin") reads it from deps
    monkeypatch.setattr(job_runs, "utcnow", lambda: datetime(2026, 10, 27, 17, 0, tzinfo=timezone.utc))   # Tue 22:30 IST
    app = FastAPI()
    app.include_router(risk_route.admin_router)
    c = TestClient(app)
    c.db, c.who = db, who
    return c


def scanner_run(db, status, *, at=datetime(2026, 10, 27, 14, 15, tzinfo=timezone.utc), error=None):
    db["job_runs"].docs.append({"_id": f"r{len(db['job_runs'].docs)}", "job": JOB, "started_at": at.isoformat(),
                                "finished_at": (at + timedelta(seconds=25)).isoformat(), "status": status, "exit_code": 0,
                                "session": "2026-10-27", "counts": {"engine_version": "v1.1"}, "error": error, "dry_run": False,
                                "calendar_ready": True})


@pytest.mark.parametrize("status,state,healthy", [
    ("ok", "ok", True), ("skipped_done", "ok", True), ("calendar_not_ready", "calendar_not_ready", False),
    ("refused_calendar_unavailable", "refused", False), ("refused_dirty_bars", "refused", False),
    ("skipped_no_bars", "no_data", False), ("failed", "failed", False), ("skipped_no_session", "skipped", True),
])
def test_be7_the_admin_route_reads_the_scanners_own_records(jobs_api, status, state, healthy):
    assert jobs_api.get(f"/api/admin/risk/jobs/{JOB}").json()["state"] == "never_run"
    scanner_run(jobs_api.db, status, error="MOCK reason" if status != "ok" else None)
    r = jobs_api.get(f"/api/admin/risk/jobs/{JOB}")
    body = r.json()
    assert r.status_code == 200 and (body["state"], body["healthy"]) == (state, healthy), body
    assert body["schedule"] == "Mon–Fri 19:45 IST, retry 21:45 IST" and body["last_run"]["counts"] == {"engine_version": "v1.1"}
    assert "calendar_ready" not in body["last_run"]                     # the read path's allow-list still holds


def test_be7b_no_run_since_the_21_45_slot_is_missed_and_non_admins_are_refused(jobs_api):
    scanner_run(jobs_api.db, "ok", at=datetime(2026, 10, 26, 14, 15, tzinfo=timezone.utc))      # Monday's run only
    assert jobs_api.get(f"/api/admin/risk/jobs/{JOB}").json()["state"] == "missed"
    jobs_api.who["user"] = {"user_id": "u1", "role": "user"}
    assert jobs_api.get(f"/api/admin/risk/jobs/{JOB}").status_code == 403


def test_be7c_the_scanner_cron_lines_match_its_schedule():
    sched = job_runs.SCHEDULES[JOB]
    text = (REPO / sched["cron_file"]).read_text()
    assert "CRON_TZ=Asia/Kolkata" in text
    lines = [l for l in text.splitlines() if l and not l.startswith("#") and re.match(r"^\d", l)]
    assert [(int(l.split()[1]), int(l.split()[0])) for l in lines] == [(t.hour, t.minute) for t in sched["slots"]]
    assert all(l.split()[4] == "1-5" and "python -m scripts.run_positional_engine" in l for l in lines)
    assert sched["weekdays"] == (0, 1, 2, 3, 4)
