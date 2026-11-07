"""AD-40..AD-51: the deterministic risk engine on plans from the real Trading Assistant and on hand-built legs
(market data: tests/autodesk/marketdata.py — TEST DATA)."""
from __future__ import annotations

from decimal import Decimal

from autodesk import contracts as C
from autodesk.control import risk_engine
from autodesk.control.book import Book, Commitment
from tests.autodesk import marketdata as md
from tests.autodesk.test_trading_assistant import generate

S, SEG, DIR, K, SIDE = C.StrategyType, C.Segment, C.Direction, C.InstrumentKind, C.LegSide
FACTS = {"data_age_sessions": 0, "adv_rs": Decimal("2000000000"), "lot_size": 500, "sector": "Capital Goods",
         "latest_session": md.FNO_DAY.isoformat()}


def bull_call(capital=md.CAPITAL) -> C.TradePlanBody:
    sig = md.signal("ACME", SEG.FUTURES, DIR.BULLISH, ref="1000", inv="960", targets=["1080", "1120"],
                    sector="Capital Goods")
    return generate(sig, acct=md.account(starting_capital_rs=capital)).plan


def book(equity=md.CAPITAL, pending=()) -> Book:
    return Book(account_id="ACC-T", equity_rs=Decimal(equity), starting_capital_rs=Decimal(equity),
                pending=list(pending))


def assess(plan, *, bk=None, acct=None, pol=None, facts=None) -> C.RiskAssessment:
    return risk_engine.assess(trade_id="TRD-T", plan_version=1, plan=plan, account=acct or md.account(),
                              policy=pol or md.policy(), book=bk or book(), as_of=md.AS_OF, session_date=md.SD,
                              facts={**FACTS, **(facts or {})})


def check(a: C.RiskAssessment, name: str) -> C.RiskCheck:
    return next(c for c in a.checks if c.name == name)


def opt(leg_id, kind, side, strike, premium, lots=2, oi=50_000):
    return C.PlanLeg(leg_id=leg_id, kind=kind, underlying="ACME", expiry=md.EXP, strike=Decimal(strike), side=side,
                     lots=lots, lot_size=500, quantity=lots * 500, ref_price=Decimal(premium),
                     ref_price_source="test", open_interest=oi)


def with_legs(plan: C.TradePlanBody, legs, strategy, **over) -> C.TradePlanBody:
    return plan.model_copy(update={"legs": legs, "strategy_type": strategy, **over})


def test_baseline_pass():
    a = assess(bull_call())
    assert a.verdict == C.RiskVerdict.PASS, [(c.name, c.outcome, c.detail) for c in a.checks]
    assert a.violations == [] and a.engine_version == "autodesk-risk-v1"


def test_ad40_reduce_then_fail_per_trade_risk():
    plan = bull_call()                                    # sized for ₹1 Cr: 4 lots, loss ≈ ₹45,000
    lots = plan.legs[0].lots
    a = assess(plan, bk=book(6_000_000))                  # budget ₹30,000
    assert a.verdict == C.RiskVerdict.REDUCE and a.violations == ["per_trade_risk"]
    allowed = a.sizing["allowed_size"]
    assert 1 <= allowed < lots and a.sizing["unit"] == "lots per leg"
    a2 = assess(plan, bk=book(1_500_000))                 # budget ₹7,500 < one lot
    assert a2.verdict == C.RiskVerdict.FAIL and "per_trade_risk" in a2.violations and a2.sizing["allowed_size"] == 0


def test_ad41_credit_terms():
    base = bull_call()
    thin = [opt("L1", K.PE, SIDE.SHORT, "960", "6.68"), opt("L2", K.PE, SIDE.LONG, "940", "3.28")]
    a = assess(with_legs(base, thin, S.BULL_PUT_SPREAD))
    assert check(a, "credit_terms").outcome == C.CheckOutcome.FAIL and a.verdict == C.RiskVerdict.FAIL
    assert check(a, "reward_risk").outcome == C.CheckOutcome.SKIPPED
    rich = [opt("L1", K.PE, SIDE.SHORT, "960", "10.00"), opt("L2", K.PE, SIDE.LONG, "940", "2.00")]
    a = assess(with_legs(base, rich, S.BULL_PUT_SPREAD))
    assert check(a, "credit_terms").outcome == C.CheckOutcome.PASS, check(a, "credit_terms").detail
    assert a.verdict == C.RiskVerdict.PASS, a.violations


def test_ad42_reward_risk_below_minimum():
    sig = md.signal("ACME", SEG.FUTURES, DIR.BULLISH, ref="1000", inv="960", targets=["1080"])
    p = generate(sig, pol=md.policy(allowed_strategies=["LONG_FUTURES"], min_reward_risk="1.2"))
    assert p.decision == "PLAN" and p.plan.strategy_type == S.LONG_FUTURES       # rr ≈ 1.3 passes a 1.2 policy
    a = assess(p.plan)                                                            # the default policy needs 1.5
    assert check(a, "reward_risk").outcome == C.CheckOutcome.FAIL and "reward_risk" in a.violations


def test_ad43_naked_short_option():
    a = assess(with_legs(bull_call(), [opt("L1", K.PE, SIDE.SHORT, "960", "6.68")], S.BULL_PUT_SPREAD))
    assert check(a, "defined_risk").outcome == C.CheckOutcome.FAIL and a.verdict == C.RiskVerdict.FAIL


def test_ad44_stale_inputs():
    a = assess(bull_call(), facts={"data_age_sessions": 2})
    assert "inputs_fresh" in a.violations and a.verdict == C.RiskVerdict.FAIL
    a = assess(bull_call(), facts={"data_age_sessions": None})
    assert "inputs_fresh" in a.violations


def test_ad45_short_futures_not_allowed():
    fut = C.PlanLeg(leg_id="L1", kind=K.FUT, underlying="ACME", expiry=md.EXP, side=SIDE.SHORT, lots=1, lot_size=500,
                    quantity=500, ref_price=Decimal("1005"), ref_price_source="test", open_interest=1_000_000)
    a = assess(with_legs(bull_call(), [fut], S.SHORT_FUTURES))
    assert "strategy_allowed" in a.violations and a.verdict == C.RiskVerdict.FAIL


def _commit(loss, capital, sector="Capital Goods", fno=True):
    return Commitment(trade_id="TRD-P", plan_version=1, instrument="OTHER", sector=sector,
                      strategy_type="BULL_CALL_SPREAD", max_loss_rs=Decimal(loss), capital_rs=Decimal(capital),
                      fno=fno)


def test_ad46_open_risk():
    plan = bull_call()                                    # ≈ 0.45% of ₹1 Cr
    a = assess(plan, bk=book(pending=[_commit(280_000, 0, sector="Other")]))      # 2.8% already committed
    assert a.verdict == C.RiskVerdict.REDUCE and a.violations == ["open_risk"] and a.sizing["allowed_size"] >= 1
    a = assess(plan, bk=book(pending=[_commit(299_500, 0, sector="Other")]))      # no lot fits
    assert a.verdict == C.RiskVerdict.FAIL and "open_risk" in a.violations


def test_ad47_sector_limit():
    a = assess(bull_call(), bk=book(pending=[_commit(0, 2_499_500, fno=False)]))   # 25% of ₹1 Cr = ₹25 L
    assert "sector" in a.violations and a.verdict == C.RiskVerdict.FAIL


def test_ad48_margin_utilisation():
    a = assess(bull_call(), bk=book(pending=[_commit(0, 2_499_500, sector="Other", fno=True)]))
    assert "margin_utilization" in a.violations and a.verdict == C.RiskVerdict.FAIL


def test_ad49_suspended_account():
    a = assess(bull_call(), acct=md.account(status="SUSPENDED"))
    assert "account_active" in a.violations and a.verdict == C.RiskVerdict.FAIL


def test_ad50_deterministic():
    plan = bull_call()
    a, b = assess(plan), assess(plan)
    strip = lambda x: x.model_dump(mode="json", exclude={"assessment_id", "created_at"})   # noqa: E731
    assert strip(a) == strip(b)


def test_ad51_loss_limits_skipped_in_phase1():
    a = assess(bull_call())
    for name in ("daily_loss", "weekly_loss", "drawdown"):
        c = check(a, name)
        assert c.outcome == C.CheckOutcome.SKIPPED and "Phase 2" in c.detail


def test_engine_uses_its_own_loss():
    plan = bull_call()
    a = assess(plan.model_copy(update={"max_loss_rs": Decimal("1000")}))
    assert any("engine computes" in w for w in a.warnings) and a.verdict == C.RiskVerdict.PASS
    assert Decimal(a.sizing["loss_rs"]) > Decimal("1000")


def test_wrong_lot_size_and_untraded_leg():
    a = assess(bull_call(), facts={"lot_size": 400})
    assert "legs_valid" in a.violations
    legs = [opt("L1", K.CE, SIDE.LONG, "1000", "25.32", oi=0), opt("L2", K.CE, SIDE.SHORT, "1080", "2.92")]
    a = assess(with_legs(bull_call(), legs, S.BULL_CALL_SPREAD))
    assert "liquidity" in a.violations
