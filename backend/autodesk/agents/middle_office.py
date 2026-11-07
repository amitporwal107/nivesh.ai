"""Middle Office Supervisor — Independent Controller (PRD §6.4). Applies the approval policy to a plan version and its
risk assessment. Deterministic. It cannot alter fills, bypass the gateway or change limits.

  RESEARCH mode                                   → REJECTED (research accounts never approve)
  no assessment / another version / verdict FAIL  → REJECTED
  verdict REDUCE                                  → NEEDS_REVISION
  ASSISTED                                        → NEEDS_HUMAN_APPROVAL
  AUTONOMOUS_PAPER within policy.autonomy         → APPROVED, scope bound to the exact version, size and mode
  AUTONOMOUS_PAPER outside it                     → NEEDS_HUMAN_APPROVAL
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from ..contracts import (AgentDescriptor, AgentKey, AgentResult, ApprovalDecision, ApprovalScope, ApprovalStatus,
                         OperatingMode, PolicyBody, RiskAssessment, RiskVerdict, TaskSpec, TaskType, TradePlanBody,
                         plan_hash)
from .base import Agent, AgentContext

VERSION = "autodesk-mo-v1"
DECIDED_BY = f"MIDDLE_OFFICE@{VERSION}"
ALLOWED_ACTIONS = ["ENTER", "EXIT_AT_INVALIDATION", "EXIT_AT_TARGET", "TRAIL_TIGHTEN", "TIME_EXIT"]
EXEC_MODE = {"SIMULATION": "SIMULATION", "PAPER": "PAPER", "SHADOW": "SHADOW"}

DESCRIPTOR = AgentDescriptor(agent_key=AgentKey.MIDDLE_OFFICE, version=VERSION, kind="DETERMINISTIC",
                             task_types=[TaskType.REVIEW_FOR_APPROVAL], tools=[],
                             prohibited=["alter fills", "bypass the gateway", "change risk limits"])


def build_scope(*, tenant_id: str, account: dict, trade_id: str, plan_version: int,
                plan: TradePlanBody) -> ApprovalScope:
    """The exact authority an approval grants (PRD §10.3). Used for agent and human approvals alike."""
    notional = sum((lg.ref_price * lg.quantity for lg in plan.legs), Decimal("0"))
    return ApprovalScope(tenant_id=tenant_id, account_id=account["account_id"], trade_id=trade_id,
                         plan_version=plan_version, instrument=plan.instrument, strategy_type=plan.strategy_type,
                         max_lots=max(lg.lots for lg in plan.legs), max_notional_rs=notional.quantize(Decimal("0.01")),
                         max_risk_rs=plan.max_loss_rs, execution_mode=EXEC_MODE[account["kind"]],
                         allowed_actions=list(ALLOWED_ACTIONS), plan_hash=plan_hash(plan))


def review(*, tenant_id: str, account: dict, policy: dict, trade_id: str, plan_version: int, plan: TradePlanBody,
           assessment: Optional[RiskAssessment], signal_score: Optional[Decimal],
           simulation_id: Optional[str]) -> ApprovalDecision:
    pol = PolicyBody.model_validate(policy["body"])
    base = dict(trade_id=trade_id, plan_version=plan_version, account_id=account["account_id"],
                simulation_id=simulation_id, decided_by=DECIDED_BY, policy_id=policy["policy_id"],
                policy_version=int(policy["version"]), expires_at=plan.plan_expires_at)

    def no(status: ApprovalStatus, *reasons: str) -> ApprovalDecision:
        return ApprovalDecision(**base, status=status, reasons=list(reasons),
                                risk_assessment_id=assessment.assessment_id if assessment else None)

    if account.get("operating_mode") == OperatingMode.RESEARCH.value:
        return no(ApprovalStatus.REJECTED, "research_mode: research accounts never approve")
    if account.get("status") != "ACTIVE":
        return no(ApprovalStatus.SUSPENDED, f"account is {account.get('status')}")
    if assessment is None:
        return no(ApprovalStatus.REJECTED, "no risk assessment for this plan version")
    if assessment.trade_id != trade_id or assessment.plan_version != plan_version:
        return no(ApprovalStatus.REJECTED, "the risk assessment is for another plan version")
    if assessment.verdict == RiskVerdict.FAIL:
        return no(ApprovalStatus.REJECTED, "risk checks failed: " + ", ".join(assessment.violations))
    if assessment.verdict == RiskVerdict.REDUCE:
        return no(ApprovalStatus.NEEDS_REVISION, f"passes only at {assessment.sizing.get('allowed_size')} "
                                                 f"{assessment.sizing.get('unit')}")
    if account.get("operating_mode") == OperatingMode.ASSISTED.value:
        return no(ApprovalStatus.NEEDS_HUMAN_APPROVAL, "assisted mode: a person approves every plan")
    a = pol.autonomy
    equity = Decimal(str(account["starting_capital_rs"]))
    risk_pct = (plan.max_loss_rs / equity * 100) if equity > 0 else Decimal("100")
    outside = []
    if not a.auto_approve:
        outside.append("the policy does not allow automatic approval")
    if risk_pct > a.max_risk_pct:
        outside.append(f"risk {risk_pct.quantize(Decimal('0.01'))}% of equity is above {a.max_risk_pct}%")
    if signal_score is None or signal_score < a.min_signal_score:
        outside.append(f"signal score {signal_score} is below {a.min_signal_score}")
    if plan.strategy_type not in a.strategies:
        outside.append(f"{plan.strategy_type.value} is not in the autonomy list")
    if outside:
        return no(ApprovalStatus.NEEDS_HUMAN_APPROVAL, *outside)
    return ApprovalDecision(**base, status=ApprovalStatus.APPROVED, risk_assessment_id=assessment.assessment_id,
                            reasons=["within the autonomy rules of the policy",
                                     f"risk {risk_pct.quantize(Decimal('0.01'))}% of equity"],
                            scope=build_scope(tenant_id=tenant_id, account=account, trade_id=trade_id,
                                              plan_version=plan_version, plan=plan))


class MiddleOffice(Agent):
    descriptor = DESCRIPTOR

    async def run(self, task: TaskSpec, ctx: AgentContext) -> AgentResult:
        p = ctx.inputs["plan"]
        a = ctx.inputs.get("assessment")
        sig = ctx.inputs.get("signal") or {}
        d = review(tenant_id=ctx.tenant_id, account=ctx.account, policy=ctx.policy, trade_id=p["trade_id"],
                   plan_version=int(p["version"]), plan=TradePlanBody.model_validate(p["body"]),
                   assessment=RiskAssessment.model_validate(a) if a else None,
                   signal_score=Decimal(str(sig["signal_score"])) if sig.get("signal_score") is not None else None,
                   simulation_id=ctx.simulation_id)
        return AgentResult(output_schema="approval-decision-v1", output=d.model_dump(mode="json"),
                           summary=f"{d.status.value}: {'; '.join(d.reasons)}",
                           evidence_refs=[f"plan://{p['trade_id']}@{p['version']}"] +
                           ([f"assessment://{a['assessment_id']}"] if a else []))
