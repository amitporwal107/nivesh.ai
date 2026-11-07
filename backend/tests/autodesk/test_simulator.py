"""AD-70..AD-77: the simulator, with TEST-DOUBLE agents and crafted market data (tests/autodesk/stubs.py)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from autodesk import contracts as C
from autodesk import store
from autodesk.market.view import FrozenMarketView, LookAheadError
from autodesk.simulator.manager import SimulationManager
from tests.autodesk import stubs
from tests.autodesk.conftest import run

_n = 0


def tenant() -> str:
    global _n
    _n += 1
    return f"t-sim-{_n}"


def cfg(**kw) -> C.SimulationConfig:
    base = dict(name="test", start_date=date(2026, 11, 4), end_date=date(2026, 11, 5), max_proposals_per_session=1)
    base.update(kw)
    return C.SimulationConfig(**base)


def manager(pool, **over):
    return SimulationManager(pool, stubs.orchestrator(pool, **over), stubs.sessions_provider,
                             versions=lambda: {"agents": "stub"})


async def _sim(pool, t, **kw):
    m = manager(pool)
    sim = await m.create(tenant_id=t, cfg=cfg(**kw), user_id="u")
    await m.start(tenant_id=t, sid=sim["simulation_id"], user_id="u")
    return m, sim


def test_ad70_create_and_validation(pg_pool):
    for bad in (dict(start_date=date(2026, 11, 5), end_date=date(2026, 11, 4)),
                dict(mode=C.SimulationMode.LIVE_SHADOW), dict(mode=C.SimulationMode.SCENARIO)):
        with pytest.raises(ValidationError):
            cfg(**bad)

    async def go():
        t = tenant()
        m = manager(pg_pool)
        sim = await m.create(tenant_id=t, cfg=cfg(), user_id="u")
        assert sim["status"] == "CREATED" and sim["config"]["sessions"] == ["2026-11-04", "2026-11-05"]
        async with pg_pool.acquire() as c:
            acc = await store.get_account(c, t, sim["account_id"])
        assert acc["kind"] == "SIMULATION" and acc["simulation_id"] == sim["simulation_id"]
        assert sim["versions"]["policy"]["version"] == 1
        with pytest.raises(ValueError):
            await m.create(tenant_id=t, cfg=cfg(start_date=date(2026, 11, 7), end_date=date(2026, 11, 8)), user_id="u")
    run(go())


def test_ad71_clock_walks_the_schedule(pg_pool):
    async def go():
        t = tenant()
        m, sim = await _sim(pg_pool, t)
        sid = sim["simulation_id"]
        r = await m.step(tenant_id=t, sid=sid, unit="SESSION")
        assert [s["phase"] for s in r["steps"]] == ["PREMARKET", "SCAN", "PROPOSALS", "OPEN", "CLOSE", "EOD"]
        async with pg_pool.acquire() as c:
            ev = await store.list_clock_events(c, t, sid)
        times = [e["sim_time"] for e in ev]
        assert times == sorted(times) and len(set(times)) == len(times)
        assert [e["seq"] for e in ev] == [1, 2, 3, 4, 5, 6]
    run(go())


def test_ad72_no_future_data(pg_pool):
    async def go():
        t = tenant()
        m, sim = await _sim(pg_pool, t)
        sid = sim["simulation_id"]
        await m.step(tenant_id=t, sid=sid, unit="SESSION")      # session 2026-11-04
        async with pg_pool.acquire() as c:
            tasks = await store.list_tasks(c, t, simulation_id=sid)
        reads = [tc for x in tasks for tc in (x["tool_calls"] or [])]
        assert reads, "agents must have read market data"
        for tc in reads:
            for k in ("day",):
                if k in tc["args"]:
                    assert tc["args"][k] <= "2026-11-03", tc       # only data published before 08:30 on 11-04
        # a deliberate read of the session's own day before publication raises
        view = FrozenMarketView(stubs.at(date(2026, 11, 4), "08:45"), stubs.DATA)
        with pytest.raises(LookAheadError):
            await view.day_snapshot(date(2026, 11, 4))
        bars = await view.daily_bars("RELIANCE", sessions=50)
        assert bars[-1].day == date(2026, 11, 3)
    run(go())


def test_ad73_pause_resume_stop(pg_pool):
    async def go():
        t = tenant()
        m, sim = await _sim(pg_pool, t)
        sid = sim["simulation_id"]
        await m.step(tenant_id=t, sid=sid)
        await m.pause(tenant_id=t, sid=sid, user_id="u")
        with pytest.raises(store.Conflict):
            await m.step(tenant_id=t, sid=sid)
        await m.resume(tenant_id=t, sid=sid, user_id="u")
        r = await m.step(tenant_id=t, sid=sid)
        assert r["steps"][0]["phase"] == "SCAN"
        await m.stop(tenant_id=t, sid=sid, user_id="u")
        with pytest.raises(store.Conflict):
            await m.step(tenant_id=t, sid=sid)
        with pytest.raises(store.Conflict):
            await m.resume(tenant_id=t, sid=sid, user_id="u")
    run(go())


def test_ad74_isolation(pg_pool):
    async def go():
        t = tenant()
        m, sim = await _sim(pg_pool, t)
        sid = sim["simulation_id"]
        await m.step(tenant_id=t, sid=sid, unit="SESSION")
        async with pg_pool.acquire() as c:
            assert await store.list_signals(c, t) == []                       # desk list: no simulated rows
            assert len(await store.list_signals(c, t, simulation_id=sid)) == 2
            assert await store.list_plans(c, t) == []
            assert len(await store.list_plans(c, t, simulation_id=sid)) == 1
            assert await store.list_accounts(c, t) == []                      # sim account hidden by default
            with pytest.raises(store.Conflict):
                await store.set_account_mode(c, tenant_id=t, account_id=sim["account_id"],
                                             mode=C.OperatingMode.ASSISTED, actor="u", reason="x")
    run(go())


def _normalised(rows_sig, rows_plan, rows_apr):
    return (sorted((r["session_date"].isoformat(), r["instrument"], r["category"], str(r["signal_score"]), r["status"])
                   for r in rows_sig),
            sorted((r["instrument"], r["strategy_type"], r["status"], r["current_version"]) for r in rows_plan),
            sorted((r["status"], r["plan_version"]) for r in rows_apr))


def test_ad75_deterministic_replay(pg_pool):
    async def go():
        outs = []
        for _ in range(2):
            t = tenant()
            m, sim = await _sim(pg_pool, t)
            await m.run_to_end(tenant_id=t, sid=sim["simulation_id"])
            async with pg_pool.acquire() as c:
                sid = sim["simulation_id"]
                outs.append(_normalised(await store.list_signals(c, t, simulation_id=sid),
                                        await store.list_plans(c, t, simulation_id=sid),
                                        await store.list_approvals(c, t, simulation_id=sid)))
        assert outs[0] == outs[1] and outs[0][0]
    run(go())


def test_ad76_run_to_end_results(pg_pool):
    async def go():
        t = tenant()
        m, sim = await _sim(pg_pool, t)
        sid = sim["simulation_id"]
        r = await m.run_to_end(tenant_id=t, sid=sid)
        assert r["status"] == "COMPLETED" and r["step_seq"] == 12
        async with pg_pool.acquire() as c:
            s = await store.get_simulation(c, t, sid)
        res = s["results"]
        assert res["sessions_total"] == 2 and res["phases_run"] == 12
        assert res["signals"]["total"] == 4 and res["plans"]["total"] == 2
        assert res["agents"]["MIDDLE_OFFICE"]["completed"] == 2 and res["handoffs"] == 6
        assert res["limitations"] and res["versions"]["policy"]["version"] == 1
        with pytest.raises(store.Conflict):
            await m.step(tenant_id=t, sid=sid)
    run(go())


def test_ad77_eod_expires_session_items(pg_pool):
    async def go():
        t = tenant()
        m, sim = await _sim(pg_pool, t, operating_mode=C.OperatingMode.ASSISTED)
        sid = sim["simulation_id"]
        await m.step(tenant_id=t, sid=sid, unit="SESSION")
        async with pg_pool.acquire() as c:
            sig = {r["instrument"]: r["status"] for r in await store.list_signals(c, t, simulation_id=sid)}
            assert sorted(sig.values()) == ["CONSUMED", "EXPIRED"]
            assert await store.list_approvals(c, t, pending_only=True) == []
            [plan] = await store.list_plans(c, t, simulation_id=sid)
            assert plan["status"] == "EXPIRED"
            [wf] = await store.list_workflows(c, t, simulation_id=sid, kind="TRADE_PROPOSAL")
            assert wf["state"] == "COMPLETED" and wf["outcome"]["result"] == "EXPIRED"
            evs = [e["event_type"] for e in await store.list_events(c, t, simulation_id=sid)]
            assert "APPROVAL_EXPIRED" in evs and "SIGNAL_EXPIRED" in evs
    run(go())
