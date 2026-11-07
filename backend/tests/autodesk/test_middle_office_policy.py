"""AD-52 (unit part), AD-53: policy rules. AD-55..AD-59: the Middle Office review (real agent logic, pure)."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from autodesk import contracts as C
from autodesk.agents.middle_office import build_scope, review
from autodesk.control import policy as P
from tests.autodesk import marketdata as md
from tests.autodesk.test_risk_engine import assess, bull_call

ST = C.ApprovalStatus


# ── policy ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_ad52_who_may_loosen():
    base = P.default_policy_body()
    tighter = base.model_copy(update={"per_trade_risk_pct": Decimal("0.3")})
    looser = base.model_copy(update={"per_trade_risk_pct": Decimal("1.0")})
    P.validate_change(base, tighter, is_admin=False)                     # a user may tighten
    with pytest.raises(PermissionError, match="per_trade_risk_pct"):
        P.validate_change(base, looser, is_admin=False)
    P.validate_change(base, looser, is_admin=True)                       # an admin may loosen
    P.validate_change(tighter, base, is_admin=False)                     # back to the default is not looser
    more = base.model_copy(update={"allowed_strategies": list(base.allowed_strategies) + [C.StrategyType.SHORT_FUTURES]})
    assert P.is_looser(base, more) == ["allowed_strategies"]


def test_ad53_most_restrictive_wins():
    tenant = P.default_policy_body().model_copy(update={"source": "tenant"})
    account = tenant.model_copy(update={"per_trade_risk_pct": Decimal("0.3"), "min_reward_risk": Decimal("2"),
                                        "allowed_strategies": [C.StrategyType.LONG_EQUITY,
                                                               C.StrategyType.BULL_CALL_SPREAD], "source": "account"})
    eff = P.effective(tenant, account)
    assert eff.per_trade_risk_pct == Decimal("0.3") and eff.min_reward_risk == Decimal("2")
    assert set(eff.allowed_strategies) == {C.StrategyType.LONG_EQUITY, C.StrategyType.BULL_CALL_SPREAD}
    assert eff.position_pct == tenant.position_pct and eff.source == "effective(tenant, account)"
    assert P.effective(account, tenant).per_trade_risk_pct == Decimal("0.3")     # order does not matter


# ── Middle Office ───────────────────────────────────────────────────────────────────────────────────────────────────

def _review(*, mode="AUTONOMOUS_PAPER", plan=None, assessment="pass", score="75", pol=None, acct=None):
    plan = plan or bull_call()
    a = assess(plan) if assessment == "pass" else assessment
    return review(tenant_id="t-agents", account=acct or md.account(operating_mode=mode), policy=pol or md.policy(),
                  trade_id="TRD-T", plan_version=1, plan=plan, assessment=a,
                  signal_score=Decimal(score) if score else None, simulation_id=None), plan


def test_ad55_research_mode_never_approves():
    d, _ = _review(mode="RESEARCH")
    assert d.status == ST.REJECTED and "research_mode" in d.reasons[0] and d.scope is None


def test_ad56_assisted_needs_a_person():
    d, _ = _review(mode="ASSISTED")
    assert d.status == ST.NEEDS_HUMAN_APPROVAL and d.scope is None


def test_ad57_autonomous_inside_rules_binds_scope():
    d, plan = _review()
    assert d.status == ST.APPROVED and d.decided_by.startswith("MIDDLE_OFFICE@")
    s = d.scope
    assert (s.trade_id, s.plan_version, s.account_id, s.tenant_id) == ("TRD-T", 1, "ACC-T", "t-agents")
    assert s.max_lots == plan.legs[0].lots and s.max_risk_rs == plan.max_loss_rs
    assert s.max_notional_rs == sum(lg.ref_price * lg.quantity for lg in plan.legs).quantize(Decimal("0.01"))
    assert s.execution_mode == "PAPER" and s.plan_hash == C.plan_hash(plan)
    assert d.expires_at == plan.plan_expires_at                          # session close
    sim = review(tenant_id="t-agents", account=md.account(kind="SIMULATION"), policy=md.policy(), trade_id="TRD-T",
                 plan_version=1, plan=plan, assessment=assess(plan), signal_score=Decimal("75"), simulation_id="SIM-1")
    assert sim.scope.execution_mode == "SIMULATION" and sim.simulation_id == "SIM-1"


def test_ad58_outside_autonomy_rules_needs_a_person():
    d, _ = _review(pol=md.policy(autonomy={"auto_approve": True, "max_risk_pct": "0.1", "min_signal_score": 70,
                                           "strategies": ["BULL_CALL_SPREAD"]}))
    assert d.status == ST.NEEDS_HUMAN_APPROVAL and any("above" in r for r in d.reasons)
    d, _ = _review(score="65")
    assert d.status == ST.NEEDS_HUMAN_APPROVAL and any("signal score" in r for r in d.reasons)
    d, _ = _review(pol=md.policy(autonomy={"auto_approve": True, "max_risk_pct": "0.5", "min_signal_score": 70,
                                           "strategies": ["LONG_EQUITY"]}))
    assert d.status == ST.NEEDS_HUMAN_APPROVAL and any("autonomy list" in r for r in d.reasons)


def test_ad59_assessment_problems():
    plan = bull_call()
    d, _ = _review(plan=plan, assessment=None)
    assert d.status == ST.REJECTED
    other = assess(plan).model_copy(update={"plan_version": 2})
    d, _ = _review(plan=plan, assessment=other)
    assert d.status == ST.REJECTED and "another plan version" in d.reasons[0]
    failed = assess(plan, acct=md.account(status="SUSPENDED"))
    d, _ = _review(plan=plan, assessment=failed)
    assert d.status == ST.REJECTED and "account_active" in d.reasons[0]
    from tests.autodesk.test_risk_engine import book
    reduce = assess(plan, bk=book(6_000_000))
    assert reduce.verdict == C.RiskVerdict.REDUCE
    d, _ = _review(plan=plan, assessment=reduce)
    assert d.status == ST.NEEDS_REVISION
    d, _ = _review(acct=md.account(status="SUSPENDED"))
    assert d.status == ST.SUSPENDED


def test_scope_builder_is_shared_with_people():
    plan = bull_call()
    s = build_scope(tenant_id="t", account=md.account(), trade_id="TRD-T", plan_version=3, plan=plan)
    assert s.plan_version == 3 and s.plan_hash == C.plan_hash(plan.model_dump(mode="json"))
    assert plan.plan_expires_at - md.AS_OF < timedelta(hours=8)
