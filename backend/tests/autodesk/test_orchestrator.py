"""AD-60..AD-68 (+ tool permission): the orchestrator and task runtime, with TEST-DOUBLE agents (tests/autodesk/stubs.py)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from autodesk import contracts as C
from autodesk import store
from autodesk.accounts import open_account
from tests.autodesk import stubs
from tests.autodesk.conftest import run

D = date(2026, 11, 5)
AS_OF = stubs.at(D, "09:00")
_n = 0


def tenant() -> str:
    global _n
    _n += 1
    return f"t-orch-{_n}"


async def _acct(pool, t, mode=C.OperatingMode.AUTONOMOUS_PAPER):
    async with pool.acquire() as c:
        return await open_account(c, tenant_id=t, name="desk", kind=C.AccountKind.PAPER, mode=mode,
                                  capital=Decimal("1000000"), created_by="test")


async def _cycle(pool, orch, t, acc, **kw):
    return await orch.run_session_cycle(tenant_id=t, account_id=acc["account_id"], session_date=D, as_of=AS_OF,
                                        max_proposals=kw.pop("max_proposals", 1), **kw)


async def _children(pool, t, cycle_id, kind="TRADE_PROPOSAL"):
    async with pool.acquire() as c:
        return await store.list_workflows(c, t, parent_workflow_id=cycle_id, kind=kind)


def test_ad60_happy_path(pg_pool):
    async def go():
        t = tenant()
        acc = await _acct(pg_pool, t)
        orch = stubs.orchestrator(pg_pool)
        cyc = await _cycle(pg_pool, orch, t, acc)
        assert cyc["state"] == "COMPLETED", cyc
        [wf] = await _children(pg_pool, t, cyc["workflow_id"])
        assert wf["state"] == "COMPLETED" and wf["outcome"]["result"] == "APPROVED_NO_EXECUTION"
        async with pg_pool.acquire() as c:
            tasks = sorted(await store.list_tasks(c, t, workflow_id=wf["workflow_id"]), key=lambda r: r["created_at"])
            assert [x["to_agent"] for x in tasks] == ["TRADING_ASSISTANT", "RISK_OPS", "MIDDLE_OFFICE"]
            assert all(x["state"] == "COMPLETED" for x in tasks)
            hand = await store.list_handoffs(c, t, workflow_id=wf["workflow_id"])
            assert [(h["from_agent"], h["to_agent"]) for h in hand] == [
                ("AI_TRADER", "TRADING_ASSISTANT"), ("TRADING_ASSISTANT", "RISK_OPS"), ("RISK_OPS", "MIDDLE_OFFICE")]
            plan = await store.get_plan(c, t, wf["outcome"]["trade_id"])
            assert plan["status"] == "APPROVED"
            [apr] = await store.list_approvals(c, t, trade_id=plan["trade_id"])
            assert apr["status"] == "APPROVED" and apr["body"]["scope"]["plan_version"] == plan["current_version"]
            evs = [e["event_type"] for e in await store.list_events(c, t, workflow_id=wf["workflow_id"])]
            assert evs.index("TRADE_PLAN_CREATED") < evs.index("RISK_ASSESSMENT_COMPLETED") \
                < evs.index("APPROVAL_REQUESTED") < evs.index("APPROVAL_GRANTED")
            # every task was persisted (TASK_CREATED) before it was assigned
            for x in tasks:
                kinds = [(e["event_type"], e["payload"].get("to")) for e in await store.list_events(c, t, workflow_id=wf["workflow_id"])
                         if e["payload"].get("task_id") == x["task_id"]]
                assert kinds[0][0] == "TASK_CREATED" and kinds[1] == ("TASK_STATE_CHANGED", "ASSIGNED")
    run(go())


def test_ad61_revision_then_pass_and_unresolved(pg_pool):
    async def go():
        t = tenant()
        acc = await _acct(pg_pool, t)
        ro = stubs.StubRO(); ro.verdicts = ["FAIL", "PASS"]
        cyc = await _cycle(pg_pool, stubs.orchestrator(pg_pool, **{C.AgentKey.RISK_OPS: ro}), t, acc)
        [wf] = await _children(pg_pool, t, cyc["workflow_id"])
        assert wf["outcome"]["result"] == "APPROVED_NO_EXECUTION" and wf["outcome"]["plan_version"] == 2
        async with pg_pool.acquire() as c:
            vers = await store.list_plan_versions(c, t, wf["outcome"]["trade_id"])
            assert [v["version"] for v in vers] == [1, 2] and vers[1]["supersedes_version"] == 1

        t2 = tenant()
        acc2 = await _acct(pg_pool, t2)
        ro2 = stubs.StubRO(); ro2.verdicts = ["FAIL"]
        cyc2 = await _cycle(pg_pool, stubs.orchestrator(pg_pool, **{C.AgentKey.RISK_OPS: ro2}), t2, acc2)
        [wf2] = await _children(pg_pool, t2, cyc2["workflow_id"])
        assert wf2["outcome"]["result"] == "NO_TRADE" and wf2["outcome"]["stage"] == "risk"
        async with pg_pool.acquire() as c:
            p = await store.get_plan(c, t2, wf2["outcome"]["trade_id"])
            assert p["status"] == "REJECTED" and p["current_version"] == 3
            assert await store.list_approvals(c, t2, trade_id=p["trade_id"]) == []
    run(go())


def test_ad62_timeout_retry_and_escalation(pg_pool):
    async def go():
        t = tenant()
        acc = await _acct(pg_pool, t)
        slow = stubs.SlowTA(); slow.slow_attempts = 1
        cyc = await _cycle(pg_pool, stubs.orchestrator(pg_pool, **{C.AgentKey.TRADING_ASSISTANT: slow}), t, acc)
        [wf] = await _children(pg_pool, t, cyc["workflow_id"])
        assert wf["outcome"]["result"] == "APPROVED_NO_EXECUTION"
        async with pg_pool.acquire() as c:
            ta = [x for x in await store.list_tasks(c, t, workflow_id=wf["workflow_id"]) if x["to_agent"] == "TRADING_ASSISTANT"][0]
            assert ta["attempt"] == 2 and ta["state"] == "COMPLETED"

        t2 = tenant()
        acc2 = await _acct(pg_pool, t2)
        slow2 = stubs.SlowTA(); slow2.slow_attempts = 99
        orch2 = stubs.orchestrator(pg_pool, **{C.AgentKey.TRADING_ASSISTANT: slow2})
        await orch2.register_agents()            # registry rows, so the status written after the run can be read
        cyc2 = await _cycle(pg_pool, orch2, t2, acc2)
        [wf2] = await _children(pg_pool, t2, cyc2["workflow_id"])
        assert wf2["state"] == "FAILED"
        async with pg_pool.acquire() as c:
            [ta2] = [x for x in await store.list_tasks(c, t2, workflow_id=wf2["workflow_id"])]
            assert ta2["state"] == "ESCALATED" and "deadline" in ta2["error"]
            assert await store.list_approvals(c, t2) == []
            # The escalation leaves the agent DEGRADED in the registry (it used to be reset to IDLE straight away).
            reg = {(a["agent_key"], a["version"]): a["status"] for a in await store.list_agents(c)}
            assert reg[("TRADING_ASSISTANT", slow2.descriptor.version)] == "DEGRADED"

        # Its next run that completes brings it back to IDLE.
        slow3 = stubs.SlowTA(); slow3.slow_attempts = 0
        t3 = tenant()
        orch3 = stubs.orchestrator(pg_pool, **{C.AgentKey.TRADING_ASSISTANT: slow3})
        await orch3.register_agents()
        await _cycle(pg_pool, orch3, t3, await _acct(pg_pool, t3))
        async with pg_pool.acquire() as c:
            reg = {(a["agent_key"], a["version"]): a["status"] for a in await store.list_agents(c)}
            assert reg[("TRADING_ASSISTANT", slow3.descriptor.version)] == "IDLE"
    run(go())


def test_ad63_invalid_output_never_used(pg_pool):
    async def go():
        t = tenant()
        acc = await _acct(pg_pool, t)
        bad = stubs.BadTA(); bad.bad_attempts = 99
        cyc = await _cycle(pg_pool, stubs.orchestrator(pg_pool, **{C.AgentKey.TRADING_ASSISTANT: bad}), t, acc)
        [wf] = await _children(pg_pool, t, cyc["workflow_id"])
        assert wf["state"] == "FAILED"
        async with pg_pool.acquire() as c:
            [ta] = await store.list_tasks(c, t, workflow_id=wf["workflow_id"])
            assert ta["state"] == "FAILED" and ta["validation"]["schema_ok"] is False
            assert await store.list_plans(c, t) == []          # nothing built from the invalid output
    run(go())


def test_ad64_premarket_blocked_stops_cycle(pg_pool):
    async def go():
        t = tenant()
        acc = await _acct(pg_pool, t)
        ts = stubs.StubTS(); ts.status = C.HealthStatus.BLOCKED
        cyc = await _cycle(pg_pool, stubs.orchestrator(pg_pool, **{C.AgentKey.TECH_SUPPORT: ts}), t, acc)
        assert cyc["state"] == "BLOCKED" and cyc["outcome"]["result"] == "BLOCKED_NO_NEW_RISK"
        assert await _children(pg_pool, t, cyc["workflow_id"], kind="MARKET_SCAN") == []
        async with pg_pool.acquire() as c:
            assert await store.list_signals(c, t) == []
            evs = [e["event_type"] for e in await store.list_events(c, t)]
            assert "PREMARKET_BLOCKED" in evs
    run(go())


def test_ad65_idempotent_cycle(pg_pool):
    async def go():
        t = tenant()
        acc = await _acct(pg_pool, t)
        orch = stubs.orchestrator(pg_pool)
        a = await _cycle(pg_pool, orch, t, acc)
        b = await _cycle(pg_pool, orch, t, acc)
        assert a["workflow_id"] == b["workflow_id"]
        async with pg_pool.acquire() as c:
            assert len(await store.list_workflows(c, t, kind="SESSION_CYCLE")) == 1
            assert len(await store.list_workflows(c, t, kind="TRADE_PROPOSAL")) == 1
    run(go())


def test_ad66_human_decisions(pg_pool):
    async def go():
        t = tenant()
        acc = await _acct(pg_pool, t, mode=C.OperatingMode.ASSISTED)
        orch = stubs.orchestrator(pg_pool)
        cyc = await _cycle(pg_pool, orch, t, acc, max_proposals=2)
        wfs = await _children(pg_pool, t, cyc["workflow_id"])
        assert [w["state"] for w in wfs] == ["WAITING_HUMAN", "WAITING_HUMAN"]
        async with pg_pool.acquire() as c:
            pending = await store.list_approvals(c, t, pending_only=True)
        assert len(pending) == 2
        a1, a2 = pending
        row = await orch.decide(tenant_id=t, approval_id=a1["approval_id"], decision="APPROVE", reason="ok",
                                user_id="u1", now=stubs.at(D, "10:00"))
        assert row["status"] == "APPROVED" and row["decided_by"] == "user:u1" and row["supersedes_id"] == a1["approval_id"]
        with pytest.raises(store.Conflict):
            await orch.decide(tenant_id=t, approval_id=a1["approval_id"], decision="REJECT", reason="", user_id="u1",
                              now=stubs.at(D, "10:01"))
        await orch.decide(tenant_id=t, approval_id=a2["approval_id"], decision="REJECT", reason="no", user_id="u1",
                          now=stubs.at(D, "10:02"))
        async with pg_pool.acquire() as c:
            st = {p["trade_id"]: p["status"] for p in await store.list_plans(c, t)}
            assert sorted(st.values()) == ["APPROVED", "REJECTED"]
            assert await store.list_approvals(c, t, pending_only=True) == []
        # a request answered after the window closed
        t2 = tenant()
        acc2 = await _acct(pg_pool, t2, mode=C.OperatingMode.ASSISTED)
        cyc2 = await _cycle(pg_pool, orch, t2, acc2)
        async with pg_pool.acquire() as c:
            [p2] = await store.list_approvals(c, t2, pending_only=True)
        with pytest.raises(store.Conflict):
            await orch.decide(tenant_id=t2, approval_id=p2["approval_id"], decision="APPROVE", reason="", user_id="u",
                              now=stubs.at(D, "16:00"))
    run(go())


def test_ad67_rogue_middle_office_cannot_approve(pg_pool):
    async def go():
        t = tenant()
        acc = await _acct(pg_pool, t, mode=C.OperatingMode.ASSISTED)
        mo = stubs.StubMO(); mo.rogue = True
        cyc = await _cycle(pg_pool, stubs.orchestrator(pg_pool, **{C.AgentKey.MIDDLE_OFFICE: mo}), t, acc)
        [wf] = await _children(pg_pool, t, cyc["workflow_id"])
        assert wf["state"] == "FAILED"
        async with pg_pool.acquire() as c:
            assert await store.list_approvals(c, t) == []
            [p] = await store.list_plans(c, t)
            assert p["status"] == "REJECTED"
            mo_task = [x for x in await store.list_tasks(c, t, workflow_id=wf["workflow_id"]) if x["to_agent"] == "MIDDLE_OFFICE"][0]
            assert mo_task["state"] == "FAILED" and "PASS assessment" in mo_task["error"]
    run(go())


def test_ad68_recovery_fails_closed(pg_pool):
    async def go():
        from autodesk.orchestrator.runtime import recover_interrupted
        t = tenant()
        acc = await _acct(pg_pool, t)
        async with pg_pool.acquire() as c:
            async with c.transaction():
                wf, _ = await store.create_workflow(c, tenant_id=t, account_id=acc["account_id"],
                                                    kind=C.WorkflowKind.TRADE_PROPOSAL, producer="test")
                wf = await store.set_workflow_state(c, tenant_id=t, workflow_id=wf["workflow_id"],
                                                    state=C.WorkflowState.RUNNING, producer="test")
                spec = C.TaskSpec(workflow_id=wf["workflow_id"], tenant_id=t, account_id=acc["account_id"],
                                  to_agent=C.AgentKey.RISK_OPS, task_type=C.TaskType.ASSESS_RISK,
                                  required_output_schema="risk-assessment-v1")
                await store.create_task(c, spec)
                for s in (C.TaskState.ASSIGNED, C.TaskState.ACCEPTED, C.TaskState.RUNNING):
                    await store.transition_task(c, tenant_id=t, task_id=spec.task_id, to=s, producer="test")
        touched = await recover_interrupted(pg_pool)
        assert spec.task_id in touched
        async with pg_pool.acquire() as c:
            task = await store.get_task(c, t, spec.task_id)
            assert task["state"] == "ESCALATED" and task["error"] == "interrupted by restart"
            assert (await store.get_workflow(c, t, wf["workflow_id"]))["state"] == "FAILED"
    run(go())


def test_tool_permission_violation_fails_task(pg_pool):
    async def go():
        t = tenant()
        acc = await _acct(pg_pool, t)
        cyc = await _cycle(pg_pool, stubs.orchestrator(pg_pool, **{C.AgentKey.TRADING_ASSISTANT: stubs.SnoopTA()}), t, acc)
        [wf] = await _children(pg_pool, t, cyc["workflow_id"])
        async with pg_pool.acquire() as c:
            [ta] = await store.list_tasks(c, t, workflow_id=wf["workflow_id"])
        assert ta["state"] == "FAILED" and "ToolNotAllowed" in ta["error"] and ta["attempt"] == 1
    run(go())


def test_research_mode_never_reaches_approval(pg_pool):
    async def go():
        t = tenant()
        acc = await _acct(pg_pool, t, mode=C.OperatingMode.RESEARCH)
        cyc = await _cycle(pg_pool, stubs.orchestrator(pg_pool), t, acc)
        [wf] = await _children(pg_pool, t, cyc["workflow_id"])
        assert wf["outcome"]["result"] == "RESEARCH_ONLY"
        async with pg_pool.acquire() as c:
            assert [x["to_agent"] for x in await store.list_tasks(c, t, workflow_id=wf["workflow_id"])].count("MIDDLE_OFFICE") == 0
            assert await store.list_approvals(c, t) == []
    run(go())
