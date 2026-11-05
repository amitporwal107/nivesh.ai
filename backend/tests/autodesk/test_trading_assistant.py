"""AD-30..AD-35: the Trading Assistant (real agent) on crafted market data (tests/autodesk/marketdata.py — TEST DATA)."""
from __future__ import annotations

from decimal import Decimal

from services.risk_gate import estimate as est

from autodesk import contracts as C
from autodesk.agents.trading_assistant import TradingAssistant
from autodesk.control import sizing
from tests.autodesk import marketdata as md
from tests.autodesk.conftest import run

S, SEG, DIR = C.StrategyType, C.Segment, C.Direction
MANDATORY = ["thesis", "rationale", "signal_id", "market_context", "account_id", "instrument", "segment",
             "strategy_type", "legs", "entry", "invalidation", "targets", "max_loss_rs", "loss_defined", "breakevens",
             "expected_payoff", "capital_required_rs", "margin_estimate", "liquidity", "holding", "exit_rules",
             "risk_warnings", "plan_expires_at", "provenance"]


def generate(sig: C.Signal, market=None, **kw) -> C.StrategyProposal:
    agent = TradingAssistant()
    ctx = md.ctx(market or md.view(), {"session_date": md.SD.isoformat(), "signal": sig.model_dump(mode="json")}, **kw)
    res = run(agent.run(md.task(C.TaskType.GENERATE_STRATEGY), ctx))
    assert res.output_schema == "strategy-proposal-v1"
    return C.StrategyProposal.model_validate(res.output)


def alts(p: C.StrategyProposal) -> dict[str, dict]:
    return {a["strategy"]: a for a in p.alternatives}


def test_ad30_cash_only_signal_long_shares():
    sig = md.signal("PLAINCO", SEG.CASH, DIR.BULLISH, ref="500", inv="480", targets=["550", "570"])
    p = generate(sig)
    assert p.decision == "PLAN", (p.reasons, p.alternatives)
    plan = p.plan
    assert plan.strategy_type == S.LONG_EQUITY and plan.segment == SEG.CASH
    dumped = plan.model_dump()
    for f in MANDATORY:
        assert dumped.get(f) not in (None, "", [], {}), f
    [leg] = plan.legs
    q = leg.quantity
    loss = est.cash_risk(q, 500.0, 480.0)
    assert plan.max_loss_rs == sizing.rs(loss["total"])                     # loss at invalidation + costs + gap
    assert plan.max_loss_rs < Decimal(q) * 500                              # never "price to zero"
    budget = md.CAPITAL * Decimal("0.005")
    assert plan.max_loss_rs <= budget and q * 500 <= md.CAPITAL * Decimal("0.10")      # budget and position cap
    assert est.cash_risk(q + 1, 500.0, 480.0)["total"] > float(budget) or (q + 1) * 500 > md.CAPITAL * Decimal("0.10")
    assert plan.capital_required_rs == Decimal(q) * 500
    # derivative alternatives were considered and skipped because PLAINCO has no F&O contracts
    a = alts(p)
    assert "no F&O contracts" in (a["BULL_CALL_SPREAD"]["skip"] or "")
    assert plan.provenance["rule_version"] == "ta-rules-v1" and plan.provenance["data_as_of"]


def test_ad31_fno_signal_alternatives_from_the_chain():
    sig = md.signal("ACME", SEG.FUTURES, DIR.BULLISH, ref="1000", inv="960", targets=["1080", "1120"],
                    category=C.SignalCategory.LONG_BUILDUP, sector="Capital Goods")
    p = generate(sig)
    assert p.decision == "PLAN", (p.reasons, p.alternatives)
    a = alts(p)
    assert {"LONG_FUTURES", "BULL_CALL_SPREAD", "BULL_PUT_SPREAD"} <= set(a)
    plan = p.plan
    assert plan.strategy_type == S.BULL_CALL_SPREAD, a          # derivative structures first for a derivatives signal
    chain = {(r.strike, r.kind): r.close for r in md.acme_fno() if r.expiry == md.EXP and r.strike is not None}
    for lg in plan.legs:
        assert lg.lot_size == 500 and lg.expiry == md.EXP                    # 4-day expiry refused (min 7 days)
        assert lg.ref_price == chain[(lg.strike, lg.kind.value)]             # premium = the bhavcopy close
        assert lg.greeks is not None and lg.greeks.iv and "model" in lg.greeks.model
    assert plan.loss_defined and plan.max_profit_rs and plan.max_loss_rs <= md.CAPITAL * Decimal("0.005")
    lots = plan.legs[0].lots
    assert lots >= 1 and all(lg.lots == lots for lg in plan.legs)
    # alternatives that miss their own rule carry the reason and are not offered
    assert a["BULL_PUT_SPREAD"]["meets_rule"] is False and "width" in a["BULL_PUT_SPREAD"]["rule_note"]


def test_ad32_untraded_strike_is_never_priced():
    # the at-the-money call did not trade: it is not used at a carried-forward price
    m = md.view(md.data(acme=md.acme_fno(untraded=[(1000, "CE")])))
    sig = md.signal("ACME", SEG.FUTURES, DIR.BULLISH, ref="1000", inv="960", targets=["1080"])
    p = generate(sig, market=m)
    assert p.decision == "PLAN"
    assert all(not (lg.strike == 1000 and lg.kind == C.InstrumentKind.CE) for lg in p.plan.legs)
    # no call traded at all: every call structure is skipped, none is priced
    calls = [(k, "CE") for k in range(840, 1180, 20)]
    m = md.view(md.data(acme=md.acme_fno(untraded=calls)))
    p = generate(sig, market=m)
    a = alts(p)
    for s in ("BULL_CALL_SPREAD", "LONG_CALL"):
        assert a[s]["skip"] == "no suitable traded strikes in the chain", a[s]
    if p.decision == "PLAN":
        assert all(lg.kind != C.InstrumentKind.CE for lg in p.plan.legs)


def test_ad33_neutral_index_iron_condor():
    sig = md.signal("IDX", SEG.INDEX, DIR.NEUTRAL, ref="24000", inv=None, category=C.SignalCategory.RANGE_BOUND)
    p = generate(sig)
    assert p.decision == "PLAN", (p.reasons, p.alternatives)
    plan = p.plan
    assert plan.strategy_type == S.IRON_CONDOR and len(plan.legs) == 4 and plan.loss_defined
    kinds = sorted((lg.kind.value, lg.side.value) for lg in plan.legs)
    assert kinds == [("CE", "LONG"), ("CE", "SHORT"), ("PE", "LONG"), ("PE", "SHORT")]
    cr = sizing.credit(plan.legs)
    loss, _ = sizing.loss(plan.legs, strategy=S.IRON_CONDOR, direction=DIR.NEUTRAL, invalidation=None)
    assert Decimal(str(cr["net_credit_rs"])) - Decimal(str(loss["costs"])) >= \
        Decimal(str(cr["width_rs"])) * Decimal("0.3333")                       # meets the credit rule
    shorts = sorted(lg.strike for lg in plan.legs if lg.side == C.LegSide.SHORT)
    assert shorts[0] < 24000 < shorts[1]


def test_ad34_nothing_viable_no_trade():
    # bearish view, but the policy allows only shares: no bearish share plan exists
    sig = md.signal("ACME", SEG.FUTURES, DIR.BEARISH, ref="1000", inv="1040", targets=["920"],
                    category=C.SignalCategory.SHORT_BUILDUP)
    p = generate(sig, pol=md.policy(allowed_strategies=["LONG_EQUITY"]))
    assert p.decision == "NO_TRADE" and p.plan is None and p.reasons
    # and a budget too small for one lot of anything
    sig = md.signal("ACME", SEG.FUTURES, DIR.BULLISH, ref="1000", inv="960", targets=["1080"])
    p = generate(sig, acct=md.account(starting_capital_rs=Decimal("100000")))
    assert p.decision == "NO_TRADE"
    assert any("above the per-trade budget" in r for r in p.reasons), p.reasons


def test_ad35_revise_size_then_next_alternative():
    sig = md.signal("ACME", SEG.FUTURES, DIR.BULLISH, ref="1000", inv="960", targets=["1080", "1120"])
    first = generate(sig).plan
    lots = first.legs[0].lots
    assert lots >= 2
    agent = TradingAssistant()

    def revise(violations, allowed):
        a = C.RiskAssessment(trade_id="TRD-T", plan_version=1, account_id="ACC-T", verdict=C.RiskVerdict.REDUCE
                             if allowed else C.RiskVerdict.FAIL, checks=[], violations=violations,
                             sizing={"allowed_size": allowed, "unit": "lots per leg"}, inputs_snapshot={},
                             policy_id="POL-T", policy_version=1, engine_version="t")
        ctx = md.ctx(md.view(), {"session_date": md.SD.isoformat(), "signal": sig.model_dump(mode="json"),
                                 "plan": {"trade_id": "TRD-T", "version": 1, "body": first.model_dump(mode="json")},
                                 "assessment": a.model_dump(mode="json"), "revision": 1})
        res = run(agent.run(md.task(C.TaskType.REVISE_STRATEGY), ctx))
        return C.StrategyProposal.model_validate(res.output)

    smaller = revise(["per_trade_risk"], lots - 1)
    assert smaller.decision == "PLAN" and smaller.plan.strategy_type == first.strategy_type
    assert all(lg.lots == lots - 1 for lg in smaller.plan.legs) and smaller.plan.max_loss_rs < first.max_loss_rs
    assert smaller.plan.max_profit_rs < first.max_profit_rs
    other = revise(["liquidity"], None)
    assert other.decision == "PLAN" and other.plan.strategy_type != first.strategy_type
    assert first.strategy_type.value in other.plan.provenance["tried"]


def test_loss_rises_with_size():
    """sizing.loss must grow with the size: the bisection that sizes plans relies on it (the shared estimate's
    worst-point tie made a 9-lot iron condor dearer than a 10-lot one; see sizing._options_loss)."""
    sig = md.signal("IDX", SEG.INDEX, DIR.NEUTRAL, ref="24000", inv=None, category=C.SignalCategory.RANGE_BOUND)
    plan = generate(sig).plan
    losses = []
    for m in range(1, 11):
        e, _ = sizing.loss(sizing.scale(plan.legs, m), strategy=S.IRON_CONDOR, direction=DIR.NEUTRAL, invalidation=None)
        losses.append(e["total"])
    assert all(b > a for a, b in zip(losses, losses[1:])), losses
    assert plan.legs[0].lots == 10 or losses[plan.legs[0].lots] > 50000      # sized to the budget or the lot cap
    assert "invalidation level at None" not in plan.thesis
    assert not any("gap through the invalidation" in w for w in plan.risk_warnings)
