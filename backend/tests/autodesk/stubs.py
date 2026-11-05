"""TEST DOUBLES for orchestrator / simulator / API tests — not real agents and not real market data.

Each stub honours the real contracts (task types, output schemas, input contract in agents/base.py) so the core can be
tested before and independently of the real agents. Market data here is a FrozenMarketView over crafted bars.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from autodesk import contracts as C
from autodesk.agents.base import Agent, AgentContext
from autodesk.market.view import Bar, FrozenMarketView, IST, published_at

SESSIONS = [date(2026, 10, 27), date(2026, 10, 28), date(2026, 10, 29), date(2026, 10, 30),
            date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5)]


def crafted_bars(symbol: str, base: Decimal) -> list[Bar]:
    out = []
    for i, d in enumerate(SESSIONS):
        px = base + Decimal(i * 5)
        out.append(Bar(day=d, open=px, high=px + 10, low=px - 10, close=px + 5, volume=100000 + i * 1000))
    return out


DATA = {"sessions": SESSIONS,
        "bars": {"RELIANCE": crafted_bars("RELIANCE", Decimal("1450")), "INFY": crafted_bars("INFY", Decimal("1500"))},
        "sector": {"RELIANCE": "Oil Gas & Consumable Fuels", "INFY": "Information Technology"}}


def market_factory(as_of: datetime) -> FrozenMarketView:
    return FrozenMarketView(as_of, DATA)


async def sessions_provider(start: date, end: date) -> list[date]:
    return [d for d in SESSIONS if start <= d <= end]


def _desc(key, tasks, tools=()):
    return C.AgentDescriptor(agent_key=key, version=f"stub-{key.value.lower()}", kind="DETERMINISTIC",
                             task_types=list(tasks), tools=list(tools), prohibited=["test double"])


class StubTS(Agent):
    descriptor = _desc(C.AgentKey.TECH_SUPPORT, [C.TaskType.PREMARKET_HEALTH_CHECK], ["market.day_snapshot"])
    status = C.HealthStatus.READY

    async def run(self, task, ctx: AgentContext):
        latest = ctx.market.latest_session("cash")
        snap = await ctx.market.day_snapshot(latest)
        allowed = {C.HealthStatus.READY: ["CASH", "FUTURES", "OPTIONS"], C.HealthStatus.DEGRADED: ["CASH"],
                   C.HealthStatus.BLOCKED: []}[self.status]
        rep = C.PremarketReport(status=self.status, session_date=date.fromisoformat(ctx.inputs["session_date"]),
                                checks=[C.HealthCheck(name="cash_eod", status=self.status, detail=f"{len(snap)} rows",
                                                      as_of=latest.isoformat())],
                                data_as_of={"cash_eod": latest.isoformat()}, allowed_segments=allowed)
        return C.AgentResult(output_schema="premarket-report-v1", output=rep.model_dump(mode="json"),
                             summary=f"pre-market {self.status.value}")


class StubAIT(Agent):
    descriptor = _desc(C.AgentKey.AI_TRADER, [C.TaskType.SCAN_MARKET], ["market.daily_bars"])

    async def run(self, task, ctx: AgentContext):
        sd = date.fromisoformat(ctx.inputs["session_date"])
        latest = ctx.market.latest_session("cash")
        sigs = []
        for sym, score in (("RELIANCE", "80"), ("INFY", "75")):
            bars = await ctx.market.daily_bars(sym, sessions=5)
            close = bars[-1].close
            sigs.append(C.Signal(tenant_id=ctx.tenant_id, account_id=ctx.account["account_id"],
                                 simulation_id=ctx.simulation_id, instrument=sym, segment=C.Segment.CASH,
                                 direction=C.Direction.BULLISH, category=C.SignalCategory.BREAKOUT,
                                 signal_score=Decimal(score), reference_price=close,
                                 entry_zone={"low": close, "high": close + 5}, invalidation_price=close - 30,
                                 targets=[close + 60, close + 120], data_as_of=published_at(latest, "cash"),
                                 session_date=sd, model_version="stub", rule_version="stub-rule",
                                 expires_at=datetime(sd.year, sd.month, sd.day, 15, 30, tzinfo=IST).astimezone(timezone.utc),
                                 sector=DATA["sector"][sym]))
        rep = C.ScanReport(session_date=sd, universe="STUB", universe_size=2, scanned=2, signals=sigs,
                           data_as_of=published_at(latest, "cash"), rule_version="stub-rule")
        return C.AgentResult(output_schema="scan-report-v1", output=rep.model_dump(mode="json"),
                             summary=f"{len(sigs)} signals")


def plan_body(ctx: AgentContext, signal: dict, shares: int) -> C.TradePlanBody:
    px = Decimal(str(signal["reference_price"]))
    inv = Decimal(str(signal["invalidation_price"]))
    sd = date.fromisoformat(ctx.inputs["session_date"])
    leg = C.PlanLeg(leg_id="L1", kind=C.InstrumentKind.EQ, underlying=signal["instrument"], side=C.LegSide.LONG,
                    lots=shares, lot_size=1, quantity=shares, ref_price=px, ref_price_source="stub")
    return C.TradePlanBody(
        thesis="stub plan", rationale=["test double"], signal_id=signal["signal_id"], market_context={},
        account_id=ctx.account["account_id"], instrument=signal["instrument"], segment=C.Segment.CASH,
        strategy_type=C.StrategyType.LONG_EQUITY, legs=[leg], entry={"order_type": "LIMIT"},
        invalidation={"underlying_level": str(inv)}, targets=[], max_loss_rs=(px - inv) * shares,
        max_profit_rs=None, loss_defined=False, breakevens=[px], expected_payoff={},
        capital_required_rs=px * shares, margin_estimate={}, liquidity={}, holding={}, exit_rules={},
        risk_warnings=[], provenance={"agent": "stub"},
        plan_expires_at=datetime(sd.year, sd.month, sd.day, 15, 30, tzinfo=IST).astimezone(timezone.utc))


class StubTA(Agent):
    descriptor = _desc(C.AgentKey.TRADING_ASSISTANT, [C.TaskType.GENERATE_STRATEGY, C.TaskType.REVISE_STRATEGY])
    no_trade = False

    async def run(self, task, ctx: AgentContext):
        if self.no_trade:
            out = C.StrategyProposal(decision="NO_TRADE", reasons=["nothing viable (stub)"])
        elif task.task_type == C.TaskType.GENERATE_STRATEGY:
            out = C.StrategyProposal(decision="PLAN", plan=plan_body(ctx, ctx.inputs["signal"], 40))
        else:
            prev = ctx.inputs["plan"]["body"]["legs"][0]["lots"]
            out = C.StrategyProposal(decision="PLAN", plan=plan_body(ctx, ctx.inputs["signal"], max(1, prev // 2)))
        return C.AgentResult(output_schema="strategy-proposal-v1", output=out.model_dump(mode="json"),
                             summary=out.decision)


class StubRO(Agent):
    descriptor = _desc(C.AgentKey.RISK_OPS, [C.TaskType.ASSESS_RISK])
    verdicts: list[str] = ["PASS"]    # consumed in order; the last one repeats

    def __init__(self):
        self.calls = 0

    async def run(self, task, ctx: AgentContext):
        v = self.verdicts[min(self.calls, len(self.verdicts) - 1)]
        self.calls += 1
        p = ctx.inputs["plan"]
        failed = v == "FAIL"
        a = C.RiskAssessment(trade_id=p["trade_id"], plan_version=p["version"], account_id=ctx.account["account_id"],
                             simulation_id=ctx.simulation_id, verdict=C.RiskVerdict(v),
                             checks=[C.RiskCheck(name="per_trade_risk",
                                                 outcome=C.CheckOutcome.FAIL if failed else C.CheckOutcome.PASS)],
                             violations=["per_trade_risk"] if failed else [], sizing={}, inputs_snapshot={},
                             policy_id=ctx.policy["policy_id"], policy_version=ctx.policy["version"],
                             engine_version="stub")
        return C.AgentResult(output_schema="risk-assessment-v1", output=a.model_dump(mode="json"), summary=v)


def stub_scope(*, tenant_id, account, trade_id, plan_version, plan: C.TradePlanBody) -> C.ApprovalScope:
    return C.ApprovalScope(tenant_id=tenant_id, account_id=account["account_id"], trade_id=trade_id,
                           plan_version=plan_version, instrument=plan.instrument, strategy_type=plan.strategy_type,
                           max_lots=max(l.lots for l in plan.legs), max_notional_rs=plan.capital_required_rs,
                           max_risk_rs=plan.max_loss_rs,
                           execution_mode="SIMULATION" if account["kind"] == "SIMULATION" else "PAPER",
                           allowed_actions=["ENTER"], plan_hash=C.plan_hash(plan))


class StubMO(Agent):
    descriptor = _desc(C.AgentKey.MIDDLE_OFFICE, [C.TaskType.REVIEW_FOR_APPROVAL])
    rogue = False   # approve regardless (tests the orchestrator's defence in depth)

    async def run(self, task, ctx: AgentContext):
        p = ctx.inputs["plan"]
        a = ctx.inputs["assessment"]
        body = C.TradePlanBody.model_validate(p["body"])
        mode = ctx.account["operating_mode"]
        common = dict(trade_id=p["trade_id"], plan_version=p["version"], account_id=ctx.account["account_id"],
                      simulation_id=ctx.simulation_id, decided_by="MIDDLE_OFFICE@stub")
        if self.rogue or mode == "AUTONOMOUS_PAPER":
            d = C.ApprovalDecision(**common, status=C.ApprovalStatus.APPROVED, reasons=["stub"],
                                   scope=stub_scope(tenant_id=ctx.tenant_id, account=ctx.account,
                                                    trade_id=p["trade_id"], plan_version=p["version"], plan=body),
                                   risk_assessment_id="RSK-forged" if self.rogue else a["assessment_id"],
                                   expires_at=body.plan_expires_at)
        else:
            d = C.ApprovalDecision(**common, status=C.ApprovalStatus.NEEDS_HUMAN_APPROVAL, reasons=["assisted"],
                                   risk_assessment_id=a["assessment_id"], expires_at=body.plan_expires_at)
        return C.AgentResult(output_schema="approval-decision-v1", output=d.model_dump(mode="json"),
                             summary=d.status.value)


class SlowTA(StubTA):
    """Sleeps past the deadline on the first `slow_attempts` calls."""
    slow_attempts = 1

    def __init__(self):
        self.n = 0

    async def run(self, task, ctx):
        self.n += 1
        if self.n <= self.slow_attempts:
            await asyncio.sleep(5)
        return await super().run(task, ctx)


class BadTA(StubTA):
    """Returns output that fails the schema on the first `bad_attempts` calls."""
    bad_attempts = 1

    def __init__(self):
        self.n = 0

    async def run(self, task, ctx):
        self.n += 1
        if self.n <= self.bad_attempts:
            return C.AgentResult(output_schema="strategy-proposal-v1", output={"decision": "PLAN"}, summary="bad")
        return await super().run(task, ctx)


class SnoopTA(StubTA):
    """Calls a market tool outside its allowlist (it has none)."""

    async def run(self, task, ctx):
        await ctx.market.daily_bars("RELIANCE", sessions=5)
        return await super().run(task, ctx)


class Book:
    def __init__(self, equity):
        self.equity = equity

    def to_json(self):
        return {"equity_rs": str(self.equity), "pending": []}


async def stub_load_book(c, tenant_id, account_id, as_of):
    return Book(Decimal("1000000"))


def agents(**over) -> dict:
    base = {C.AgentKey.TECH_SUPPORT: StubTS(), C.AgentKey.AI_TRADER: StubAIT(), C.AgentKey.TRADING_ASSISTANT: StubTA(),
            C.AgentKey.RISK_OPS: StubRO(), C.AgentKey.MIDDLE_OFFICE: StubMO()}
    base.update(over)
    return base


def orchestrator(pool, **over):
    from autodesk.orchestrator.engine import Orchestrator
    return Orchestrator(pool, agents(**over), market_factory, load_book=stub_load_book, scope_builder=stub_scope,
                        task_deadline_s=1.0)


def at(day: date, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=IST).astimezone(timezone.utc)
