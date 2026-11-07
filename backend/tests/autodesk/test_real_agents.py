"""The proposal chain with the REAL Trading Assistant, Risk & Operations and Middle Office, the real book loader and
scope builder, through the orchestrator and Postgres. Only the scanner and the pre-market check are test doubles, and
the market data is crafted (tests/autodesk/marketdata.py — TEST DATA)."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from autodesk import contracts as C
from autodesk import store
from autodesk.accounts import open_account
from autodesk.agents.base import Agent, AgentContext
from autodesk.agents.middle_office import MiddleOffice
from autodesk.agents.risk_ops import RiskOps
from autodesk.agents.trading_assistant import TradingAssistant
from autodesk.market.view import IST, published_at
from autodesk.orchestrator.engine import Orchestrator
from tests.autodesk import marketdata as md
from tests.autodesk import stubs
from tests.autodesk.conftest import run


class TwoSignalScanner(Agent):
    """TEST DOUBLE scanner: one bullish F&O stock signal and one neutral index signal."""
    descriptor = stubs._desc(C.AgentKey.AI_TRADER, [C.TaskType.SCAN_MARKET], ["market.daily_bars"])

    async def run(self, task, ctx: AgentContext):
        latest = ctx.market.latest_session("cash")
        common = dict(tenant_id=ctx.tenant_id, account_id=ctx.account["account_id"], simulation_id=ctx.simulation_id,
                      data_as_of=published_at(latest, "cash"), session_date=md.SD, model_version="test-scan",
                      rule_version="test-scan",
                      expires_at=datetime(2026, 11, 6, 15, 30, tzinfo=IST).astimezone(timezone.utc))
        sigs = [C.Signal(instrument="ACME", segment=C.Segment.FUTURES, direction=C.Direction.BULLISH,
                         category=C.SignalCategory.LONG_BUILDUP, signal_score=Decimal("80"),
                         reference_price=Decimal("1000"), invalidation_price=Decimal("960"),
                         targets=[Decimal("1080"), Decimal("1120")], fno_eligible=True, sector="Capital Goods",
                         **common),
                C.Signal(instrument="IDX", segment=C.Segment.INDEX, direction=C.Direction.NEUTRAL,
                         category=C.SignalCategory.RANGE_BOUND, signal_score=Decimal("78"),
                         reference_price=Decimal("24000"), fno_eligible=True, **common)]
        rep = C.ScanReport(session_date=md.SD, universe="TEST", universe_size=2, scanned=2, signals=sigs,
                           data_as_of=published_at(latest, "cash"), rule_version="test-scan")
        return C.AgentResult(output_schema="scan-report-v1", output=rep.model_dump(mode="json"), summary="2 signals")


def test_real_proposal_chain(pg_pool):
    async def go():
        t = "t-real-agents"
        async with pg_pool.acquire() as c:
            acc = await open_account(c, tenant_id=t, name="desk A", kind=C.AccountKind.PAPER,
                                     mode=C.OperatingMode.AUTONOMOUS_PAPER, capital=md.CAPITAL, created_by="test")
        agents = stubs.agents(**{C.AgentKey.AI_TRADER: TwoSignalScanner(), C.AgentKey.TRADING_ASSISTANT: TradingAssistant(),
                                 C.AgentKey.RISK_OPS: RiskOps(), C.AgentKey.MIDDLE_OFFICE: MiddleOffice()})
        orch = Orchestrator(pg_pool, agents, lambda as_of: md.view(as_of=as_of), task_deadline_s=10.0)
        await orch.register_agents()
        cyc = await orch.run_session_cycle(tenant_id=t, account_id=acc["account_id"], session_date=md.SD,
                                           as_of=md.AS_OF, max_proposals=2)
        assert cyc["state"] == "COMPLETED", cyc
        async with pg_pool.acquire() as c:
            wfs = await store.list_workflows(c, t, parent_workflow_id=cyc["workflow_id"], kind="TRADE_PROPOSAL")
            by = {}
            for wf in wfs:
                plan = await store.get_plan(c, t, wf["outcome"]["trade_id"])
                risk = await store.latest_risk_assessment(c, t, plan["trade_id"], plan["current_version"])
                aprs = await store.list_approvals(c, t, trade_id=plan["trade_id"])
                tasks = await store.list_tasks(c, t, workflow_id=wf["workflow_id"])
                by[plan["instrument"]] = (wf, plan, risk, aprs, tasks)
        assert set(by) == {"ACME", "IDX"}
        for sym, strategy in (("ACME", "BULL_CALL_SPREAD"), ("IDX", "IRON_CONDOR")):
            wf, plan, risk, aprs, tasks = by[sym]
            assert wf["outcome"]["result"] == "APPROVED_NO_EXECUTION", (sym, wf["outcome"], risk and risk["body"])
            assert plan["strategy_type"] == strategy and plan["status"] == "APPROVED"
            assert risk["verdict"] == "PASS" and risk["body"]["engine_version"] == "autodesk-risk-v1"
            [apr] = aprs
            assert apr["body"]["scope"]["plan_hash"] == C.plan_hash(plan["body"])
            assert apr["body"]["decided_by"].startswith("MIDDLE_OFFICE@autodesk-mo-v1")
            assert [x["to_agent"] for x in sorted(tasks, key=lambda r: r["created_at"])] == \
                ["TRADING_ASSISTANT", "RISK_OPS", "MIDDLE_OFFICE"]
        # the index plan's liquidity came from futures traded value, and that is recorded
        idx_risk = by["IDX"][2]["body"]
        assert "futures traded value" in idx_risk["inputs_snapshot"]["facts"]["adv_basis"]
        ro_task = next(x for x in by["IDX"][4] if x["to_agent"] == "RISK_OPS")
        assert any(tc["tool"] == "futures" for tc in ro_task["tool_calls"]), ro_task["tool_calls"]
        # the second plan was checked against the first one's commitment
        assert Decimal(by["IDX"][2]["body"]["inputs_snapshot"]["pending_risk_rs"]) > 0 or \
            Decimal(by["ACME"][2]["body"]["inputs_snapshot"]["pending_risk_rs"]) > 0
    run(go())
