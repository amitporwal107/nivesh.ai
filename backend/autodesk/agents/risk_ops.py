"""Risk & Operations — Risk Guardian (PRD §6.3). Gathers the market facts a check needs through its own restricted
market view, then runs the deterministic risk engine. It cannot weaken a policy, approve or execute."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from ..contracts import AgentDescriptor, AgentKey, AgentResult, TaskSpec, TaskType, TradePlanBody
from ..control import risk_engine
from ..control.book import Book
from ..market.view import DataUnavailable, ist
from .base import Agent, AgentContext

DESCRIPTOR = AgentDescriptor(
    agent_key=AgentKey.RISK_OPS, version="autodesk-risk-ops-v1", kind="DETERMINISTIC",
    task_types=[TaskType.ASSESS_RISK],
    tools=["market.daily_bars", "market.lot_size", "market.sector", "market.sessions_between"],
    prohibited=["weaken hard policies", "approve", "execute"])


class RiskOps(Agent):
    descriptor = DESCRIPTOR

    async def facts(self, plan: TradePlanBody, ctx: AgentContext) -> dict:
        m = ctx.market
        f: dict = {"latest_session": None, "data_age_sessions": None, "adv_rs": None, "lot_size": None, "sector": None}
        latest = m.latest_session("cash")
        f["latest_session"] = latest.isoformat()
        built = (plan.provenance or {}).get("data_as_of")
        if built:
            built_day = ist(_dt(built)).date()
            sessions = await m.sessions_between(built_day, latest)
            f["data_age_sessions"] = max(len([d for d in sessions if d > built_day]), 0)
        try:
            bars = await m.daily_bars(plan.instrument, sessions=20)
            vals = [b.turnover_rs if b.turnover_rs is not None else b.close * b.volume for b in bars]
            if len(vals) >= 10:
                f["adv_rs"] = (sum(vals) / len(vals)).quantize(Decimal("1"))
        except DataUnavailable:
            pass
        if any(lg.kind.value != "EQ" for lg in plan.legs):
            f["lot_size"] = await m.lot_size(plan.instrument)
        f["sector"] = await m.sector(plan.instrument) or (plan.market_context or {}).get("sector")
        return f

    async def run(self, task: TaskSpec, ctx: AgentContext) -> AgentResult:
        p = ctx.inputs["plan"]
        plan = TradePlanBody.model_validate(p["body"])
        book = Book.from_json(ctx.inputs["book"])
        facts = await self.facts(plan, ctx)
        a = risk_engine.assess(trade_id=p["trade_id"], plan_version=int(p["version"]), plan=plan, account=ctx.account,
                               policy=ctx.policy, book=book, as_of=ctx.as_of,
                               session_date=date.fromisoformat(ctx.inputs["session_date"]), facts=facts,
                               simulation_id=ctx.simulation_id)
        failed = ", ".join(a.violations) or "none"
        summary = f"{a.verdict.value}: failed checks {failed}"
        if a.verdict.value == "REDUCE":
            summary += f"; passes at {a.sizing['allowed_size']} {a.sizing['unit']}"
        return AgentResult(output_schema="risk-assessment-v1", output=a.model_dump(mode="json"), summary=summary,
                           evidence_refs=[f"plan://{p['trade_id']}@{p['version']}", f"book://{book.account_id}"])


def _dt(v):
    from datetime import datetime
    return v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace("Z", "+00:00"))
