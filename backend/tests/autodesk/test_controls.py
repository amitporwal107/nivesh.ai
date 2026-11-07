"""AD-93..AD-98: additions from the owner's screen designs (5 Nov) — STOP_NEW_ENTRIES and the plan-hash approval
binding. TEST-DOUBLE agents and crafted market data (tests/autodesk/stubs.py)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from autodesk import contracts as C
from autodesk import store
from autodesk.accounts import open_account
from autodesk.simulator.manager import SimulationManager
from tests.autodesk import stubs
from tests.autodesk.conftest import run

D = date(2026, 11, 5)
AS_OF = stubs.at(D, "09:00")
STOP = C.DeskControl.STOP_NEW_ENTRIES
_n = 0


def tenant() -> str:
    global _n
    _n += 1
    return f"t-ctl-{_n}"


async def _acct(pool, t, mode=C.OperatingMode.AUTONOMOUS_PAPER):
    async with pool.acquire() as c:
        return await open_account(c, tenant_id=t, name="desk", kind=C.AccountKind.PAPER, mode=mode,
                                  capital=Decimal("1000000"), created_by="test")


async def _set(pool, t, active, reason="drill"):
    async with pool.acquire() as c:
        return await store.set_desk_control(c, tenant_id=t, control=STOP, active=active, reason=reason, actor="user:u")


async def _events(pool, t, kind):
    async with pool.acquire() as c:
        return [e for e in await store.list_events(c, t) if e["event_type"] == kind]


def test_ad93_cycle_holds_back_proposals(pg_pool):
    async def go():
        t = tenant()
        acc = await _acct(pg_pool, t)
        await _set(pg_pool, t, True)
        orch = stubs.orchestrator(pg_pool)
        cyc = await orch.run_session_cycle(tenant_id=t, account_id=acc["account_id"], session_date=D, as_of=AS_OF,
                                           max_proposals=2)
        assert cyc["state"] == "COMPLETED", cyc
        prop = cyc["outcome"]["proposals"]
        assert prop["proposed"] == 0 and prop["candidates"] >= 1 and "STOP_NEW_ENTRIES" in prop["held_back"]
        async with pg_pool.acquire() as c:
            assert await store.list_workflows(c, t, parent_workflow_id=cyc["workflow_id"], kind="TRADE_PROPOSAL") == []
            sigs = await store.list_signals(c, t, status="DETECTED")
        assert len(sigs) >= 1                                   # the scanner still shows what it found
        [ev] = await _events(pg_pool, t, "ENTRIES_STOPPED")
        assert ev["payload"]["stage"] == "proposals"
    run(go())


def test_ad94_single_proposal_refused(pg_pool):
    async def go():
        t = tenant()
        acc = await _acct(pg_pool, t)
        await _set(pg_pool, t, True)
        orch = stubs.orchestrator(pg_pool)
        cyc = await orch.run_session_cycle(tenant_id=t, account_id=acc["account_id"], session_date=D, as_of=AS_OF)
        async with pg_pool.acquire() as c:
            [sig, *_] = await store.list_signals(c, t, status="DETECTED")
        with pytest.raises(store.Conflict):
            await orch.run_trade_proposal(tenant_id=t, cycle=cyc, signal=sig, as_of=AS_OF)
        async with pg_pool.acquire() as c:
            assert (await store.get_signal(c, t, sig["signal_id"]))["status"] == "DETECTED"
    run(go())


def test_ad95_no_human_approval_while_stopped(pg_pool):
    async def go():
        t = tenant()
        acc = await _acct(pg_pool, t, mode=C.OperatingMode.ASSISTED)
        orch = stubs.orchestrator(pg_pool)
        await orch.run_session_cycle(tenant_id=t, account_id=acc["account_id"], session_date=D, as_of=AS_OF,
                                     max_proposals=2)
        async with pg_pool.acquire() as c:
            a1, a2 = await store.list_approvals(c, t, pending_only=True)
        await _set(pg_pool, t, True)
        with pytest.raises(store.Conflict, match="stopped"):
            await orch.decide(tenant_id=t, approval_id=a1["approval_id"], decision="APPROVE", reason="",
                              user_id="u", now=stubs.at(D, "10:00"))
        r = await orch.decide(tenant_id=t, approval_id=a2["approval_id"], decision="REJECT", reason="no",
                              user_id="u", now=stubs.at(D, "10:01"))
        assert r["status"] == "REJECTED"
        await _set(pg_pool, t, False)
        r = await orch.decide(tenant_id=t, approval_id=a1["approval_id"], decision="APPROVE", reason="ok",
                              user_id="u", now=stubs.at(D, "10:02"))
        assert r["status"] == "APPROVED"
    run(go())


def test_ad95b_stop_during_a_proposal_holds_it_back(pg_pool):
    """The control is activated while Risk & Operations works: the plan never reaches the Middle Office."""
    async def go():
        t = tenant()
        acc = await _acct(pg_pool, t)

        class StopperRO(stubs.StubRO):
            async def run(self, task, ctx):
                await _set(pg_pool, t, True, reason="pressed mid-flight")
                return await super().run(task, ctx)

        orch = stubs.orchestrator(pg_pool, **{C.AgentKey.RISK_OPS: StopperRO()})
        cyc = await orch.run_session_cycle(tenant_id=t, account_id=acc["account_id"], session_date=D, as_of=AS_OF,
                                           max_proposals=1)
        async with pg_pool.acquire() as c:
            [wf] = await store.list_workflows(c, t, parent_workflow_id=cyc["workflow_id"], kind="TRADE_PROPOSAL")
            assert wf["outcome"]["result"] == "ENTRIES_STOPPED"
            assert (await store.get_plan(c, t, wf["outcome"]["trade_id"]))["status"] == "REJECTED"
            assert await store.list_approvals(c, t, trade_id=wf["outcome"]["trade_id"]) == []
            tasks = await store.list_tasks(c, t, workflow_id=wf["workflow_id"])
        assert "MIDDLE_OFFICE" not in {x["to_agent"] for x in tasks}
    run(go())


def test_ad96_simulations_not_affected(pg_pool):
    async def go():
        t = tenant()
        await _set(pg_pool, t, True)
        m = SimulationManager(pg_pool, stubs.orchestrator(pg_pool), stubs.sessions_provider,
                              versions=lambda: {"agents": "stub"})
        sim = await m.create(tenant_id=t, cfg=C.SimulationConfig(name="t", start_date=date(2026, 11, 4),
                                                                   end_date=date(2026, 11, 4),
                                                                   max_proposals_per_session=1), user_id="u")
        sid = sim["simulation_id"]
        await m.start(tenant_id=t, sid=sid, user_id="u")
        await m.step(tenant_id=t, sid=sid, unit="SESSION")
        async with pg_pool.acquire() as c:
            wfs = await store.list_workflows(c, t, simulation_id=sid, kind="TRADE_PROPOSAL")
        assert len(wfs) == 1 and wfs[0]["outcome"]["result"] == "APPROVED_NO_EXECUTION"
        assert await _events(pg_pool, t, "ENTRIES_STOPPED") == []
    run(go())


def test_ad97_activate_twice_lift_once(pg_pool):
    async def go():
        t = tenant()
        r1 = await _set(pg_pool, t, True, "first")
        r2 = await _set(pg_pool, t, True, "second")
        r3 = await _set(pg_pool, t, False, "all clear")
        assert (r1["changed"], r2["changed"], r3["changed"]) == (True, False, True)
        assert len(await _events(pg_pool, t, "DESK_CONTROL_ACTIVATED")) == 1
        [lift] = await _events(pg_pool, t, "DESK_CONTROL_LIFTED")
        assert lift["payload"] == {"control": "STOP_NEW_ENTRIES", "reason": "all clear"}
        async with pg_pool.acquire() as c:
            [row] = await store.list_desk_controls(c, t)
            assert row["active"] is False and row["reason"] == "all clear"
            assert await store.entries_stopped(c, t) is None
    run(go())


def test_ad98_plan_hash_binding(pg_pool):
    async def go():
        # an automatic approval carries the hash of the exact plan version
        t = tenant()
        acc = await _acct(pg_pool, t)
        orch = stubs.orchestrator(pg_pool)
        cyc = await orch.run_session_cycle(tenant_id=t, account_id=acc["account_id"], session_date=D, as_of=AS_OF,
                                           max_proposals=1)
        async with pg_pool.acquire() as c:
            [wf] = await store.list_workflows(c, t, parent_workflow_id=cyc["workflow_id"], kind="TRADE_PROPOSAL")
            plan = await store.get_plan(c, t, wf["outcome"]["trade_id"])
            [apr] = await store.list_approvals(c, t, trade_id=plan["trade_id"])
        h = C.plan_hash(plan["body"])
        assert len(h) == 64 and apr["body"]["scope"]["plan_hash"] == h
        assert C.plan_hash(C.TradePlanBody.model_validate(plan["body"])) == h      # dict and model agree
        # a person's decision is bound to the version they reviewed
        t2 = tenant()
        acc2 = await _acct(pg_pool, t2, mode=C.OperatingMode.ASSISTED)
        await orch.run_session_cycle(tenant_id=t2, account_id=acc2["account_id"], session_date=D, as_of=AS_OF,
                                     max_proposals=1)
        async with pg_pool.acquire() as c:
            [req] = await store.list_approvals(c, t2, pending_only=True)
            p2 = await store.get_plan(c, t2, req["trade_id"])
        with pytest.raises(store.Conflict, match="plan hash"):
            await orch.decide(tenant_id=t2, approval_id=req["approval_id"], decision="APPROVE", reason="",
                              user_id="u", now=stubs.at(D, "10:00"), plan_hash="f" * 64)
        r = await orch.decide(tenant_id=t2, approval_id=req["approval_id"], decision="APPROVE", reason="",
                              user_id="u", now=stubs.at(D, "10:01"), plan_hash=C.plan_hash(p2["body"]))
        assert r["status"] == "APPROVED" and r["body"]["scope"]["plan_hash"] == C.plan_hash(p2["body"])
    run(go())
