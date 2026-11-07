"""Real-data verification run of the Autonomous Trading Desk (Phase 1) — AD-14, AD-72, AD-83, AD-85, AD-87.

Runs the REAL agents and the point-in-time market view over the data platform (read-only) through the orchestrator,
the simulator and the HTTP API, against a FRESH database on a THROWAWAY Postgres (AUTODESK_TEST_PG_URL). Nothing shared
is written. The HTTP part fakes the signed-in user (dependency override); real sign-in is checked after deployment.

  usage (inside a container from the staging backend image, worktree mounted read-only):
    python scripts/autodesk_staging_run.py [--sim-start YYYY-MM-DD --sim-end YYYY-MM-DD] [--max-proposals N]
Prints one JSON document (no secrets).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException, Request   # module level: annotations are strings here (postponed evaluation)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "autodesk_staging_run")
os.environ.setdefault("OPENAI_API_KEY", "staging-run-placeholder")   # the shared middleware's import chain needs a value
OUT = os.environ.get("AUTODESK_RUN_OUT")                              # directory for the JSON sections


def emit(out: dict, section: str) -> None:
    """Write a finished section at once (a later failure keeps what was verified)."""
    if OUT:
        with open(os.path.join(OUT, f"{section}.json"), "w") as f:
            json.dump(_j(out.get(section)), f, indent=1, default=str)


def _j(x):
    return json.loads(json.dumps(x, default=str))


async def fresh_db(base: str) -> str:
    import asyncpg
    name = "adrun_" + uuid.uuid4().hex[:10]
    admin = await asyncpg.connect(base)
    await admin.execute(f'CREATE DATABASE "{name}"')
    await admin.close()
    return base.rsplit("/", 1)[0] + "/" + name


async def view_checks(out: dict) -> None:
    """AD-14: the point-in-time view on real data."""
    from autodesk.market.pit import PitMarketView
    now = datetime.now(timezone.utc)
    v = PitMarketView(now)
    r: dict = {"as_of": now, "latest_cash": v.latest_session("cash"), "latest_fno": v.latest_session("fno")}
    bars = await v.daily_bars("RELIANCE", sessions=60)
    r["reliance_bars"] = {"n": len(bars), "first": bars[0].day, "last": bars[-1].day, "last_close": bars[-1].close,
                          "last_turnover_rs": bars[-1].turnover_rs, "close_x_volume": bars[-1].close * bars[-1].volume,
                          "factors": sorted({str(b.adj_factor) for b in bars})}
    uni = await v.fno_universe()
    bu = await v.fno_buildup()
    r["fno_universe"] = {"n": len(uni), "sample": uni[:8], "indices": [u for u in uni if u in
                                                                      ("NIFTY", "BANKNIFTY", "FINNIFTY")]}
    r["buildup"] = {"n": len(bu), "labels": {lab: sum(1 for x in bu if x.label == lab) for lab in
                                             sorted({x.label for x in bu})}}
    futs = await v.futures("RELIANCE")
    r["reliance_futures"] = [{"expiry": f.expiry, "close": f.close, "settle": f.settle, "lot": f.lot_size,
                              "volume": f.traded_volume, "traded_value": f.traded_value_rs,
                              "vol_x_lot_x_close": (f.traded_volume or 0) * (f.lot_size or 0) * (f.close or 0)}
                             for f in futs]
    r["lot_size"] = {s: await v.lot_size(s) for s in ("RELIANCE", "NIFTY", "BANKNIFTY")}
    exps = await v.expiries("NIFTY")
    r["nifty_expiries"] = exps[:6]
    opts = await v.options("NIFTY", exps[1] if len(exps) > 1 else exps[0])
    r["nifty_chain"] = {"expiry": exps[1] if len(exps) > 1 else exps[0], "rows": len(opts),
                        "traded": sum(1 for o in opts if (o.traded_volume or 0) > 0),
                        "spot": next((o.underlying_price for o in opts if o.underlying_price), None)}
    r["vix"] = await v.vix()
    r["nifty50_last"] = (await v.index_bars("Nifty 50", sessions=3))[-1].close
    r["sector"] = {s: await v.sector(s) for s in ("RELIANCE", "INFY", "HDFCBANK")}
    calls = v.tool_calls()
    r["tool_calls"] = {"n": len(calls), "all_as_of": all(c.as_of == v.as_of for c in calls),
                       "failed": [c.model_dump(mode="json") for c in calls if not c.ok]}
    try:
        from autodesk.market.view import LookAheadError
        await v.day_snapshot(r["latest_cash"] + timedelta(days=1))
        r["lookahead_refused"] = False
    except LookAheadError:
        r["lookahead_refused"] = True
    out["AD-14_view"] = r
    emit(out, "AD-14_view")


async def desk_cycle(pool, out: dict, max_proposals: int) -> None:
    """AD-83: a desk session cycle for the coming session with the real agents."""
    from autodesk import contracts as C
    from autodesk import store
    from autodesk.accounts import open_account
    from autodesk.agents.registry import default_agents
    from autodesk.market.calendar import next_session_for
    from autodesk.market.pit import PitMarketView
    from autodesk.orchestrator.engine import Orchestrator

    t = "staging-run"
    async with pool.acquire() as c:
        acc = await open_account(c, tenant_id=t, name="Desk A", kind=C.AccountKind.PAPER,
                                 mode=C.OperatingMode.AUTONOMOUS_PAPER, capital=Decimal("10000000"),
                                 created_by="staging-run")
    orch = Orchestrator(pool, default_agents(), lambda as_of: PitMarketView(as_of), task_deadline_s=60.0)
    await orch.register_agents()
    now = datetime.now(timezone.utc)
    sd = await next_session_for(now)
    t0 = time.monotonic()
    cyc = await orch.run_session_cycle(tenant_id=t, account_id=acc["account_id"], session_date=sd, as_of=now,
                                       max_proposals=max_proposals)
    r: dict = {"session_date": sd, "as_of": now, "seconds": round(time.monotonic() - t0, 1), "state": cyc["state"],
               "premarket": (cyc["outcome"] or {}).get("premarket", {}).get("status"),
               "allowed": (cyc["outcome"] or {}).get("premarket", {}).get("allowed_segments"),
               "proposals": (cyc["outcome"] or {}).get("proposals")}
    async with pool.acquire() as c:
        sigs = await store.list_signals(c, t, limit=500)
        r["signals"] = {"n": len(sigs), "by_category": {}, "top": []}
        for s in sigs:
            r["signals"]["by_category"][s["category"]] = r["signals"]["by_category"].get(s["category"], 0) + 1
        for s in sorted(sigs, key=lambda s: -float(s["signal_score"]))[:8]:
            b = s["body"]
            r["signals"]["top"].append({"instrument": s["instrument"], "category": s["category"],
                                        "direction": b["direction"], "score": b["signal_score"],
                                        "ref": b["reference_price"], "invalidation": b["invalidation_price"],
                                        "levels": b["targets"], "missing": b["missing_inputs"]})
        scan_wf = (await store.list_workflows(c, t, parent_workflow_id=cyc["workflow_id"], kind="MARKET_SCAN"))[0]
        scan_task = (await store.list_tasks(c, t, workflow_id=scan_wf["workflow_id"]))[0]
        r["scan_task"] = {"state": scan_task["state"], "tool_calls": len(scan_task["tool_calls"] or []),
                          "failed_reads": sum(1 for x in scan_task["tool_calls"] or [] if not x.get("ok", True)),
                          "summary": scan_task.get("result_summary"),
                          "universe_size": (scan_task.get("result") or {}).get("universe_size"),
                          "suppressed": len((scan_task.get("result") or {}).get("suppressed") or []),
                          "suppressed_sample": ((scan_task.get("result") or {}).get("suppressed") or [])[:5],
                          "regime": (scan_task.get("result") or {}).get("regime")}
        plans = []
        for wf in await store.list_workflows(c, t, parent_workflow_id=cyc["workflow_id"], kind="TRADE_PROPOSAL"):
            o = wf["outcome"] or {}
            item = {"result": o.get("result"), "reasons": o.get("reasons") or o.get("reason")}
            if o.get("trade_id"):
                p = await store.get_plan(c, t, o["trade_id"])
                b = p["body"]
                risk = await store.latest_risk_assessment(c, t, p["trade_id"], p["current_version"])
                item.update({"instrument": p["instrument"], "strategy": p["strategy_type"], "version": p.get("version"),
                             "legs": [(lg["kind"], lg["side"], lg.get("strike"), lg["lots"], lg["ref_price"],
                                       str(lg.get("expiry"))) for lg in b["legs"]],
                             "max_loss_rs": b["max_loss_rs"], "max_profit_rs": b["max_profit_rs"],
                             "capital_rs": b["capital_required_rs"], "thesis": b["thesis"],
                             "risk": risk and {"verdict": risk["verdict"], "violations": risk["body"]["violations"],
                                               "warnings": risk["body"]["warnings"]},
                             "approvals": [(a["status"], a["decided_by"]) for a in
                                           await store.list_approvals(c, t, trade_id=p["trade_id"])]})
            else:
                tasks = await store.list_tasks(c, t, workflow_id=wf["workflow_id"])
                item["tasks"] = [(x["to_agent"], x["state"], (x.get("error") or "")[:200]) for x in tasks]
            plans.append(item)
        r["plans"] = plans
        r["events"] = await c.fetchval("SELECT count(*) FROM autodesk.events WHERE tenant_id=$1", t)
    out["AD-83_cycle"] = r
    emit(out, "AD-83_cycle")


async def simulation(pool, out: dict, start: date, end: date) -> None:
    """AD-85 + AD-72: a replay of past sessions on real data; every read bounded by the simulated clock."""
    from autodesk import store
    from autodesk.agents.registry import default_agents
    from autodesk.contracts import SimulationConfig
    from autodesk.market.calendar import sessions_between
    from autodesk.market.pit import PitMarketView
    from autodesk.market.view import published_at
    from autodesk.orchestrator.engine import Orchestrator
    from autodesk.simulator.manager import SimulationManager

    t = "staging-sim"
    orch = Orchestrator(pool, default_agents(), lambda as_of: PitMarketView(as_of), task_deadline_s=60.0)
    m = SimulationManager(pool, orch, sessions_between, versions=lambda: {"ai_trader": "autodesk-ait-v1",
                                                                          "risk_engine": "autodesk-risk-v1"})
    sim = await m.create(tenant_id=t, cfg=SimulationConfig(name="staging replay", start_date=start, end_date=end,
                                                           max_proposals_per_session=3,
                                                           starting_capital_rs=Decimal("10000000")),
                       user_id="staging-run")
    sid = sim["simulation_id"]
    await m.start(tenant_id=t, sid=sid, user_id="staging-run")
    t0 = time.monotonic()
    await m.run_to_end(tenant_id=t, sid=sid)
    res = await m.results(tenant_id=t, sid=sid)
    r: dict = {"simulation_id": sid, "seconds": round(time.monotonic() - t0, 1), "results": res}
    # AD-72: no read may reach data published after the task's simulated time
    bad, n = [], 0
    async with pool.acquire() as c:
        rows = await c.fetch("""SELECT task_id, task_type, sim_time, tool_calls FROM autodesk.agent_tasks
                                WHERE tenant_id=$1 AND simulation_id=$2""", t, sid)
    for row in rows:
        for tc in row["tool_calls"] or []:
            n += 1
            asof = datetime.fromisoformat(str(tc.get("as_of")).replace("Z", "+00:00")) if tc.get("as_of") else None
            if row["sim_time"] and asof and asof != row["sim_time"]:
                bad.append({"task": row["task_id"], "why": "tool as_of differs from the task's sim_time"})
            day = (tc.get("args") or {}).get("day")
            if day and asof:
                kind = "fno" if tc["tool"] in ("fno_universe", "fno_buildup", "futures", "options", "expiries",
                                               "lot_size") else "cash"
                if published_at(date.fromisoformat(day), kind) > asof:
                    bad.append({"task": row["task_id"], "tool": tc["tool"], "day": day, "as_of": str(asof)})
            if not tc.get("ok", True) and "LookAhead" in str(tc.get("error")):
                bad.append({"task": row["task_id"], "why": tc.get("error")})
    r["AD-72"] = {"tool_calls_checked": n, "violations": bad[:10], "violation_count": len(bad)}
    async with pool.acquire() as c:
        r["by_session"] = [dict(x) for x in await c.fetch(
            """SELECT session_date, kind, state, outcome->>'result' AS result, count(*) AS n
               FROM autodesk.workflows WHERE tenant_id=$1 AND simulation_id=$2
               GROUP BY 1,2,3,4 ORDER BY 1,2""", t, sid)]
    out["AD-85_simulation"] = r
    emit(out, "AD-85_simulation")


async def api_checks(dsn: str, out: dict) -> None:
    """AD-87 (+ a read of the cycle) through the HTTP API on real data; the signed-in user is faked."""
    from fastapi.testclient import TestClient

    from autodesk.agents.registry import default_agents
    from autodesk.db import create_pool_for
    from autodesk.main import build_state, create_app
    from autodesk.market.calendar import next_session_for, sessions_between
    from autodesk.market.pit import PitMarketView
    from autodesk.routers.api import current_user

    async def factory():
        pool = await create_pool_for(dsn)
        st = build_state(pool, agents=default_agents(), market_factory=lambda a: PitMarketView(a),
                         sessions_provider=sessions_between, next_session=next_session_for)
        await st.orchestrator.register_agents()
        return st

    app = create_app(factory)

    async def fake_user(request: Request):
        if request.headers.get("X-Run-User") != "staging-run":
            raise HTTPException(401, "Not authenticated")
        return {"user_id": "staging-run", "role": "user"}

    app.dependency_overrides[current_user] = fake_user
    h = {"X-Run-User": "staging-run"}
    with TestClient(app) as cl:
        r = {"health": cl.get("/api/v1/health").json(),
             "unauthenticated_status": cl.get("/api/v1/desk/status").status_code}
        st = cl.get("/api/v1/desk/status", headers=h).json()
        r["desk_status"] = {k: st.get(k) for k in ("pending_approvals", "open_workflows", "market_data", "controls",
                                                   "execution")}
        r["desk_status"]["accounts"] = [(a["name"], a["operating_mode"]) for a in st.get("accounts", [])]
        r["desk_status"]["agents"] = [(a["agent_key"], a["version"]) for a in st.get("agents", [])]
        resp = cl.get("/api/v1/trade-plans", headers=h)
        plans = resp.json()
        r["trade_plans"] = {"status": resp.status_code, "n": len(plans) if isinstance(plans, list) else plans}
        if isinstance(plans, list) and plans:
            p = cl.get(f"/api/v1/trade-plans/{plans[0]['trade_id']}", headers=h).json()
            r["first_plan"] = {"trade_id": p["trade_id"], "plan_hash": p["plan_hash"],
                               "verdict": (p.get("latest_risk_assessment") or {}).get("verdict")}
        for name, path in (("signals", "/api/v1/signals"), ("agents_activity_ai_trader", "/api/v1/agents/AI_TRADER/activity"),
                           ("controls", "/api/v1/desk/controls"), ("simulations", "/api/v1/simulations")):
            resp = cl.get(path, headers=h)
            body = resp.json()
            r[name] = {"status": resp.status_code, "n": len(body) if isinstance(body, list) else body}
    out["AD-87_api"] = r
    emit(out, "AD-87_api")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim-start", default=None)
    ap.add_argument("--sim-end", default=None)
    ap.add_argument("--max-proposals", type=int, default=3)
    ap.add_argument("--skip", default="", help="comma list of: view,cycle,sim,api")
    a = ap.parse_args()
    skip = set(filter(None, a.skip.split(",")))

    from autodesk.db import create_pool_for, set_pool
    from autodesk.db.migrate import apply_pending
    from autodesk.market import calendar

    out: dict = {"started": datetime.now(timezone.utc)}
    out["calendar"] = await calendar.load_years([2025, 2026, 2027])
    dsn = await fresh_db(os.environ["AUTODESK_TEST_PG_URL"])
    pool = await create_pool_for(dsn)
    set_pool(pool)
    out["migrations"] = await apply_pending(pool)
    if "view" not in skip:
        await view_checks(out)
    if "cycle" not in skip:
        await desk_cycle(pool, out, a.max_proposals)
    if "sim" not in skip:
        today = datetime.now(timezone.utc).date()
        past = await calendar.sessions_between(today - timedelta(days=14), today - timedelta(days=1))
        start = date.fromisoformat(a.sim_start) if a.sim_start else past[-3]
        end = date.fromisoformat(a.sim_end) if a.sim_end else past[-2]
        await simulation(pool, out, start, end)
    await pool.close()
    if "api" not in skip:
        await api_checks(dsn, out)
    out["finished"] = datetime.now(timezone.utc)
    print(json.dumps(_j(out), indent=1, default=str))


if __name__ == "__main__":
    asyncio.run(main())
