"""AD-01..AD-08: schema, append-only rows, task transitions, tenant isolation, dedupe, approval binding, account kinds."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import asyncpg
import pytest
from pydantic import ValidationError

from autodesk import contracts as C
from autodesk import store
from autodesk.db.migrate import apply_pending, MIGRATIONS_DIR, MigrationDrift
from tests.autodesk.conftest import run

T1, T2 = "tenant-one", "tenant-two"


async def _account(c, tenant=T1, kind=C.AccountKind.PAPER, sim=None):
    pol = await store.create_policy(c, tenant_id=tenant, name="default", body=C.PolicyBody().model_dump(mode="json"),
                                    created_by="test")
    return await store.create_account(c, tenant_id=tenant, name="desk", kind=kind,
                                      operating_mode=C.OperatingMode.AUTONOMOUS_PAPER,
                                      starting_capital_rs=Decimal("1000000"), policy_id=pol["policy_id"],
                                      created_by="test", simulation_id=sim)


def _signal(account_id, **kw):
    now = datetime(2026, 11, 4, 3, 15, tzinfo=timezone.utc)
    base = dict(tenant_id=T1, account_id=account_id, instrument="RELIANCE", segment=C.Segment.CASH,
                direction=C.Direction.BULLISH, category=C.SignalCategory.BREAKOUT, signal_score=Decimal("72"),
                data_as_of=now, session_date=date(2026, 11, 4), model_version="m1", rule_version="r1",
                expires_at=now + timedelta(hours=7))
    base.update(kw)
    return C.Signal(**base)


def test_ad01_migrations_idempotent_and_drift(pg_pool, tmp_path, monkeypatch):
    assert run(apply_pending(pg_pool)) == []          # fixture already applied 001
    n = run(pg_pool.fetchval("SELECT count(*) FROM autodesk.schema_migrations"))
    assert n == len(list(MIGRATIONS_DIR.glob("*.sql")))
    # drift: same name, different content
    fake = tmp_path / "migrations"
    fake.mkdir()
    for f in MIGRATIONS_DIR.glob("*.sql"):
        (fake / f.name).write_text(f.read_text() + "\n-- edited\n")
    import autodesk.db.migrate as m
    monkeypatch.setattr(m, "MIGRATIONS_DIR", fake)
    with pytest.raises(MigrationDrift):
        run(m.apply_pending(pg_pool))


def test_ad02_append_only(pg_pool):
    async def go():
        async with pg_pool.acquire() as c:
            acc = await _account(c)                                   # event + policy version
            plan = await store.create_plan(c, tenant_id=T1, body=_plan_body(acc["account_id"]), created_by="test",
                                           simulation_id=None, workflow_id=None)
            a = C.RiskAssessment(trade_id=plan["trade_id"], plan_version=1, account_id=acc["account_id"],
                                 verdict=C.RiskVerdict.PASS, checks=[], sizing={}, inputs_snapshot={},
                                 policy_id=acc["policy_id"], policy_version=1, engine_version="t")
            await store.insert_risk_assessment(c, tenant_id=T1, a=a, producer="test", workflow_id=None)
            d = C.ApprovalDecision(trade_id=plan["trade_id"], plan_version=1, account_id=acc["account_id"],
                                   status=C.ApprovalStatus.REJECTED, decided_by="t", reasons=["x"])
            await store.insert_approval(c, tenant_id=T1, d=d, producer="test", workflow_id=None)
            for table, col in (("events", "producer"), ("policy_versions", "reason"),
                               ("trade_plan_versions", "change_reason"), ("risk_assessments", "engine_version"),
                               ("approvals", "decided_by")):
                assert await c.fetchval(f"SELECT count(*) FROM autodesk.{table}") > 0, table
                for sql in (f"UPDATE autodesk.{table} SET {col}='changed'", f"DELETE FROM autodesk.{table}"):
                    with pytest.raises(asyncpg.exceptions.RestrictViolationError):
                        async with c.transaction():
                            await c.execute(sql)
    run(go())


def test_ad03_task_transitions(pg_pool):
    async def go():
        async with pg_pool.acquire() as c:
            acc = await _account(c)
            wf, _ = await store.create_workflow(c, tenant_id=T1, account_id=acc["account_id"],
                                                kind=C.WorkflowKind.TRADE_PROPOSAL, producer="test")
            spec = C.TaskSpec(workflow_id=wf["workflow_id"], tenant_id=T1, account_id=acc["account_id"],
                              to_agent=C.AgentKey.RISK_OPS, task_type=C.TaskType.ASSESS_RISK,
                              required_output_schema="risk-assessment-v1")
            t, created = await store.create_task(c, spec)
            assert created and t["state"] == "CREATED"
            for s in (C.TaskState.ASSIGNED, C.TaskState.ACCEPTED, C.TaskState.RUNNING, C.TaskState.RESULT_READY,
                      C.TaskState.VALIDATED, C.TaskState.COMPLETED):
                t = await store.transition_task(c, tenant_id=T1, task_id=spec.task_id, to=s, producer="test")
            assert t["state"] == "COMPLETED" and t["completed_at"] is not None and t["latency_ms"] is not None
            evs = await store.list_events(c, T1, workflow_id=wf["workflow_id"])
            assert [e["payload"]["to"] for e in evs if e["event_type"] == "TASK_STATE_CHANGED"] == [
                "ASSIGNED", "ACCEPTED", "RUNNING", "RESULT_READY", "VALIDATED", "COMPLETED"]
            spec2 = C.TaskSpec(workflow_id=wf["workflow_id"], tenant_id=T1, to_agent=C.AgentKey.RISK_OPS,
                               task_type=C.TaskType.ASSESS_RISK, required_output_schema="risk-assessment-v1")
            await store.create_task(c, spec2)
            with pytest.raises(store.IllegalTransition):
                await store.transition_task(c, tenant_id=T1, task_id=spec2.task_id, to=C.TaskState.COMPLETED,
                                            producer="test")
    run(go())


def test_ad04_task_owner_enforced():
    with pytest.raises(ValidationError):
        C.TaskSpec(workflow_id="WF-x", tenant_id=T1, to_agent=C.AgentKey.RISK_OPS,
                   task_type=C.TaskType.GENERATE_STRATEGY, required_output_schema="strategy-proposal-v1")


def test_ad05_tenant_isolation(pg_pool):
    async def go():
        async with pg_pool.acquire() as c:
            acc = await _account(c)
            wf, _ = await store.create_workflow(c, tenant_id=T1, account_id=acc["account_id"],
                                                kind=C.WorkflowKind.SESSION_CYCLE, producer="test")
            sig, _ = await store.insert_signal(c, _signal(acc["account_id"], instrument="TCS"), workflow_id=None,
                                               task_id=None, producer="test")
            for fn, arg in ((store.get_account, acc["account_id"]), (store.get_workflow, wf["workflow_id"]),
                            (store.get_signal, sig["signal_id"])):
                assert await fn(c, T1, arg)
                with pytest.raises(store.NotFound):
                    await fn(c, T2, arg)
            assert await store.list_accounts(c, T2) == []
    run(go())


def test_ad06_signal_dedupe(pg_pool):
    async def go():
        async with pg_pool.acquire() as c:
            acc = await _account(c)
            a, created_a = await store.insert_signal(c, _signal(acc["account_id"], instrument="INFY"),
                                                     workflow_id=None, task_id=None, producer="test")
            b, created_b = await store.insert_signal(c, _signal(acc["account_id"], instrument="INFY",
                                                                signal_score=Decimal("90")),
                                                     workflow_id=None, task_id=None, producer="test")
            assert created_a and not created_b and a["signal_id"] == b["signal_id"]
    run(go())


def test_ad07_approval_binding_and_single_answer(pg_pool):
    scope = C.ApprovalScope(tenant_id=T1, account_id="ACC-1", trade_id="TRD-1", plan_version=2, instrument="X",
                            strategy_type=C.StrategyType.LONG_EQUITY, max_lots=1, max_notional_rs=Decimal("1"),
                            max_risk_rs=Decimal("1"), execution_mode="PAPER", allowed_actions=["ENTER"])
    with pytest.raises(ValidationError):
        C.ApprovalDecision(trade_id="TRD-1", plan_version=2, account_id="ACC-1", status=C.ApprovalStatus.APPROVED,
                           decided_by="x", reasons=[])                       # no scope
    with pytest.raises(ValidationError):
        C.ApprovalDecision(trade_id="TRD-1", plan_version=3, account_id="ACC-1", status=C.ApprovalStatus.APPROVED,
                           decided_by="x", reasons=[], scope=scope,
                           expires_at=datetime.now(timezone.utc))            # scope for version 2

    async def go():
        async with pg_pool.acquire() as c:
            acc = await _account(c)
            body = _plan_body(acc["account_id"])
            plan = await store.create_plan(c, tenant_id=T1, body=body, created_by="test", simulation_id=None,
                                           workflow_id=None)
            req = C.ApprovalDecision(trade_id=plan["trade_id"], plan_version=1, account_id=acc["account_id"],
                                     status=C.ApprovalStatus.NEEDS_HUMAN_APPROVAL, decided_by="MIDDLE_OFFICE@t",
                                     reasons=["assisted mode"])
            r = await store.insert_approval(c, tenant_id=T1, d=req, producer="test", workflow_id=None)
            ans = C.ApprovalDecision(trade_id=plan["trade_id"], plan_version=1, account_id=acc["account_id"],
                                     status=C.ApprovalStatus.REJECTED, decided_by="user:u", reasons=["no"])
            await store.insert_approval(c, tenant_id=T1, d=ans, producer="test", workflow_id=None,
                                        supersedes_id=r["approval_id"])
            ans2 = C.ApprovalDecision(trade_id=plan["trade_id"], plan_version=1, account_id=acc["account_id"],
                                      status=C.ApprovalStatus.REJECTED, decided_by="user:u", reasons=["again"])
            with pytest.raises(store.Conflict):
                async with c.transaction():
                    await store.insert_approval(c, tenant_id=T1, d=ans2, producer="test", workflow_id=None,
                                                supersedes_id=r["approval_id"])
            assert await store.list_approvals(c, T1, pending_only=True) == []
    run(go())


def test_ad08_account_kind_constraints(pg_pool):
    async def go():
        async with pg_pool.acquire() as c:
            with pytest.raises(asyncpg.CheckViolationError):
                async with c.transaction():
                    await _account(c, kind=C.AccountKind.SIMULATION, sim=None)
            with pytest.raises(asyncpg.CheckViolationError):
                await c.execute("""INSERT INTO autodesk.accounts (account_id, tenant_id, name, kind, operating_mode,
                                   starting_capital_rs, policy_id, created_by)
                                   VALUES ('A','t','n','LIVE','RESEARCH',1,'p','x')""")
    run(go())


def _plan_body(account_id):
    leg = C.PlanLeg(leg_id="L1", kind=C.InstrumentKind.EQ, underlying="RELIANCE", side=C.LegSide.LONG, lots=10,
                    lot_size=1, quantity=10, ref_price=Decimal("1500"), ref_price_source="test fixture")
    return C.TradePlanBody(
        thesis="test", rationale=["test"], signal_id=None, market_context={}, account_id=account_id,
        instrument="RELIANCE", segment=C.Segment.CASH, strategy_type=C.StrategyType.LONG_EQUITY, legs=[leg],
        entry={"order_type": "LIMIT"}, invalidation={"underlying_level": "1460"}, targets=[],
        max_loss_rs=Decimal("420"), max_profit_rs=None, loss_defined=False, breakevens=[], expected_payoff={},
        capital_required_rs=Decimal("15000"), margin_estimate={}, liquidity={}, holding={}, exit_rules={},
        risk_warnings=[], plan_expires_at=datetime.now(timezone.utc) + timedelta(hours=6), provenance={})
