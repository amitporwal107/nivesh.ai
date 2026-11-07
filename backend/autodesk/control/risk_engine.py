"""Deterministic risk engine of the desk (DESIGN §6.2). Pure: plan + account + policy + book + facts → RiskAssessment.

The engine never trusts the plan's own loss figure: it recomputes loss, reward, credit and capital with
control/sizing.py (services/risk_gate/estimate.py underneath) and records both when they differ.

Verdict
  PASS    every hard check passes
  REDUCE  only size-related checks fail (per_trade_risk, position, open_risk, sector, margin_utilization) and a
          smaller size passes all of them: sizing.allowed_lots carries that size
  FAIL    any other hard check fails, or no size passes
A hard FAIL cannot be overridden by any agent (PRD §6.3 guardrail hierarchy).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Optional

from ..contracts import (CheckOutcome, Direction, InstrumentKind, PolicyBody, RiskAssessment, RiskCheck, RiskVerdict,
                         Segment, StrategyType, TradePlanBody)
from . import sizing
from .book import Book

ENGINE_VERSION = "autodesk-risk-v1"

LEG_SEGMENT = {InstrumentKind.EQ: Segment.CASH, InstrumentKind.FUT: Segment.FUTURES,
               InstrumentKind.CE: Segment.OPTIONS, InstrumentKind.PE: Segment.OPTIONS}
LOSS_LIMITS_SKIP = "daily and weekly loss and drawdown limits act on P&L from Phase 3 (with the trade lifecycle)"


def _pct(value: Decimal, equity: Decimal) -> Decimal:
    return (value / equity * 100).quantize(Decimal("0.001")) if equity > 0 else Decimal("0")


def _chk(name, ok: Optional[bool], detail: str, value=None, limit=None, hard=True, warn=False) -> RiskCheck:
    if ok is None:
        outcome = CheckOutcome.SKIPPED
    elif ok:
        outcome = CheckOutcome.WARN if warn else CheckOutcome.PASS
    else:
        outcome = CheckOutcome.FAIL
    return RiskCheck(name=name, outcome=outcome, detail=detail, hard=hard,
                     value=None if value is None else sizing.rs(value) if not isinstance(value, int) else Decimal(value),
                     limit=None if limit is None else sizing.rs(limit) if not isinstance(limit, int) else Decimal(limit))


def _invalidation(plan: TradePlanBody) -> Optional[Decimal]:
    v = (plan.invalidation or {}).get("underlying_level")
    return Decimal(str(v)) if v not in (None, "") else None


def _target(plan: TradePlanBody) -> Optional[Decimal]:
    for t in plan.targets:
        if t.basis == "UNDERLYING":
            return t.level
    return None


def _direction(plan: TradePlanBody) -> Direction:
    d = (plan.market_context or {}).get("direction")
    return Direction(d) if d in Direction.__members__ else Direction.BULLISH


def _size_checks(legs, *, plan: TradePlanBody, policy: PolicyBody, book: Book, sector: str) -> tuple[list[RiskCheck], dict]:
    """The size-dependent checks for `legs`. Returns (checks, numbers)."""
    eq = book.equity_rs
    inv = _invalidation(plan)
    est, why = sizing.loss(legs, strategy=plan.strategy_type, direction=_direction(plan), invalidation=inv)
    loss = sizing.rs(est["total"]) if est else None
    cap = sizing.capital_used(legs, strategy=plan.strategy_type, futures_margin_pct=policy.futures_margin_pct,
                              max_loss_rs=loss)
    capital = cap["amount_rs"]
    out = []
    if loss is None:
        out.append(_chk("per_trade_risk", False, f"loss cannot be estimated: {why}"))
    else:
        lim = eq * policy.per_trade_risk_pct / 100
        out.append(_chk("per_trade_risk", loss <= lim, f"loss {loss} ({_pct(loss, eq)}% of equity) vs limit "
                        f"{policy.per_trade_risk_pct}%", loss, lim))
    lim_pos = eq * policy.position_pct / 100
    out.append(_chk("position", capital <= lim_pos, f"capital used {capital} ({cap['method']}) vs "
                    f"{policy.position_pct}% of equity", capital, lim_pos))
    if loss is not None:
        tot = book.pending_risk_rs + loss
        lim = eq * policy.open_risk_pct / 100
        out.append(_chk("open_risk", tot <= lim, f"open risk incl. {len(book.pending)} approved plans "
                        f"{tot} ({_pct(tot, eq)}%) vs {policy.open_risk_pct}%", tot, lim))
    else:
        out.append(_chk("open_risk", False, "loss unknown"))
    sec_tot = book.sector_capital_rs(sector) + capital
    lim = eq * policy.sector_pct / 100
    out.append(_chk("sector", sec_tot <= lim, f"sector {sector}: capital incl. approved plans {sec_tot} vs "
                    f"{policy.sector_pct}% of equity", sec_tot, lim, warn=sector == "UNCLASSIFIED"))
    if cap["fno"]:
        tot = book.pending_fno_capital_rs + capital
        lim = eq * policy.max_margin_utilization_pct / 100
        out.append(_chk("margin_utilization", tot <= lim, f"F&O capital incl. approved plans {tot} "
                        f"({_pct(tot, eq)}%) vs {policy.max_margin_utilization_pct}% (estimate, not SPAN)", tot, lim))
    else:
        out.append(_chk("margin_utilization", None, "no F&O legs"))
    return out, {"loss": est, "loss_rs": loss, "capital": cap}


def assess(*, trade_id: str, plan_version: int, plan: TradePlanBody, account: dict, policy: dict, book: Book,
           as_of: datetime, session_date: date, facts: dict[str, Any],
           simulation_id: Optional[str] = None) -> RiskAssessment:
    """facts: {"data_age_sessions": int|None, "adv_rs": Decimal|None, "lot_size": int|None, "sector": str|None,
    "latest_session": iso date|None}. Missing facts never pass a check."""
    pol = PolicyBody.model_validate(policy["body"])
    checks: list[RiskCheck] = []
    warnings: list[str] = []
    legs = plan.legs
    fno = any(lg.kind != InstrumentKind.EQ for lg in legs)

    age = facts.get("data_age_sessions")
    checks.append(_chk("inputs_fresh", None if age is None else age <= pol.max_data_age_sessions,
                       "data age unknown" if age is None else f"plan built on data {age} session(s) old vs max "
                       f"{pol.max_data_age_sessions}", age, pol.max_data_age_sessions))
    if age is None:
        checks[-1] = _chk("inputs_fresh", False, "data age unknown: never treated as fresh")
    checks.append(_chk("account_active", account.get("status") == "ACTIVE", f"account is {account.get('status')}"))
    checks.append(_chk("strategy_allowed", plan.strategy_type in pol.allowed_strategies,
                       f"{plan.strategy_type.value} {'is' if plan.strategy_type in pol.allowed_strategies else 'is not'}"
                       " in the policy's allowed strategies"))
    segs = {LEG_SEGMENT[lg.kind] for lg in legs}
    bad = [s.value for s in segs if s not in pol.allowed_segments]
    checks.append(_chk("segment_allowed", not bad, "all leg segments allowed" if not bad else f"not allowed now: {bad}"))

    # legs
    raw = sizing.raw_legs(legs)
    from services.risk_gate import gate
    clean, failures = gate.clean_legs(raw)
    problems = [m for _c, m in failures]
    if len(legs) > pol.max_legs:
        problems.append(f"{len(legs)} legs > {pol.max_legs}")
    problems += [f"{lg.leg_id}: {lg.lots} lots > {pol.max_lots_per_leg}" for lg in legs
                 if lg.kind != InstrumentKind.EQ and lg.lots > pol.max_lots_per_leg]
    lot_fact = facts.get("lot_size")
    lot_warn = False
    for lg in legs:
        if lg.kind != InstrumentKind.EQ:
            if lot_fact is None:
                lot_warn = True
            elif lg.lot_size != lot_fact:
                problems.append(f"{lg.leg_id}: lot size {lg.lot_size} != exchange lot {lot_fact}")
    checks.append(_chk("legs_valid", not problems, "; ".join(problems) or
                       ("legs valid" + (" (exchange lot size not available to confirm)" if lot_warn else "")),
                       warn=lot_warn))

    # defined risk
    inv = _invalidation(plan)
    if not fno:
        checks.append(_chk("defined_risk", inv is not None, "shares: the loss is bounded by closing at the "
                           "invalidation level" if inv is not None else "a share plan needs an invalidation level"))
    elif all(lg.kind == InstrumentKind.FUT for lg in legs):
        checks.append(_chk("defined_risk", inv is not None, "futures: the loss is bounded only by closing at the "
                           "invalidation level (a synthetic level; a gap can go through it)" if inv is not None
                           else "a futures plan needs an invalidation level", warn=True))
    else:
        f = [m for c, m in gate.defined_risk_failures(clean)] if clean else ["legs invalid"]
        checks.append(_chk("defined_risk", not f, "defined risk" if not f else "; ".join(f)))

    # expiry
    exp_issues = []
    expiries = sorted({lg.expiry for lg in legs if lg.expiry})
    for e in expiries:
        dte = (e - session_date).days
        if e <= session_date:
            exp_issues.append(f"{e} expires on or before the session")
        elif dte < pol.min_days_to_expiry:
            exp_issues.append(f"{e} is {dte} days away (< {pol.min_days_to_expiry})")
    if len(expiries) > 1:
        exp_issues.append("more than one expiry (calendar / diagonal structures are not supported yet)")
    checks.append(_chk("expiry", None if not expiries else not exp_issues,
                       "no derivative legs" if not expiries else "; ".join(exp_issues) or "expiry ok"))

    # liquidity
    adv = facts.get("adv_rs")
    liq = []
    if adv is None:
        liq.append("average traded value unknown")
    elif Decimal(str(adv)) < pol.min_adv_rs:
        liq.append(f"20-session average traded value {sizing.rs(adv)} < {pol.min_adv_rs}")
    if pol.require_traded_legs:
        liq += [f"{lg.leg_id}: no open interest" for lg in legs
                if lg.kind in (InstrumentKind.CE, InstrumentKind.PE) and not (lg.open_interest or 0) > 0]
    checks.append(_chk("liquidity", not liq, "; ".join(liq) or "liquid", adv, pol.min_adv_rs))

    # size-dependent checks
    sector = facts.get("sector") or (plan.market_context or {}).get("sector") or "UNCLASSIFIED"
    size_checks, nums = _size_checks(legs, plan=plan, policy=pol, book=book, sector=sector)
    loss = nums["loss_rs"]
    if loss is not None and abs(loss - plan.max_loss_rs) > max(Decimal("1"), loss * Decimal("0.02")):
        warnings.append(f"the plan states a loss of {plan.max_loss_rs}; the engine computes {loss} and uses its own")

    # reward : risk and credit terms
    credit = sizing.credit(legs)
    if credit is not None:
        costs = Decimal(str(nums["loss"]["costs"])) if nums["loss"] else Decimal("0")
        net = Decimal(str(credit["net_credit_rs"])) - costs
        need = Decimal(str(credit["width_rs"])) * pol.credit_min_width_fraction
        checks.append(_chk("credit_terms", net >= need, f"net credit after costs {sizing.rs(net)} vs width "
                           f"{credit['width_rs']} × {pol.credit_min_width_fraction}", net, need))
        checks.append(_chk("reward_risk", None, "credit structure: judged by credit_terms (owner rule 28 Oct)"))
    else:
        checks.append(_chk("credit_terms", None, "not a credit structure"))
        rew = sizing.reward(legs, direction=_direction(plan), target=_target(plan))
        if rew is None and fno and not any(lg.kind == InstrumentKind.FUT for lg in legs) and \
                sizing.size_of(legs) is not None and _target(plan) is not None:
            checks.append(_chk("reward_risk", True, "unbounded gain (net long calls)"))
        elif rew is None or loss is None or loss <= 0:
            checks.append(_chk("reward_risk", False, "no reward level or loss to compare"))
        else:
            rr = (Decimal(str(rew)) / loss).quantize(Decimal("0.01"))
            checks.append(_chk("reward_risk", rr >= pol.min_reward_risk, f"reward {sizing.rs(rew)} : loss {loss} = "
                               f"{rr} vs {pol.min_reward_risk}", rr, pol.min_reward_risk))

    checks += size_checks
    for name in ("daily_loss", "weekly_loss", "drawdown"):
        checks.append(_chk(name, None, LOSS_LIMITS_SKIP))

    hard_fail = [c.name for c in checks if c.hard and c.outcome == CheckOutcome.FAIL]
    size_only = bool(hard_fail) and set(hard_fail) <= set(sizing.SIZE_CHECKS)
    current = sizing.size_of(legs)
    allowed = None
    if size_only and current and current > 1:
        allowed = _largest_passing(current, lambda m: all(
            c.outcome != CheckOutcome.FAIL for c in
            _size_checks(sizing.scale(legs, m), plan=plan, policy=pol, book=book, sector=sector)[0]))
    if not hard_fail:
        verdict = RiskVerdict.PASS
    elif size_only and allowed:
        verdict = RiskVerdict.REDUCE
    else:
        verdict = RiskVerdict.FAIL
    budget = book.equity_rs * pol.per_trade_risk_pct / 100
    return RiskAssessment(
        trade_id=trade_id, plan_version=plan_version, account_id=account["account_id"], simulation_id=simulation_id,
        verdict=verdict, checks=checks, violations=hard_fail,
        sizing={"proposed_size": current, "allowed_size": allowed if verdict == RiskVerdict.REDUCE else current
                if verdict == RiskVerdict.PASS else 0, "unit": "shares" if not fno else "lots per leg",
                "budget_rs": str(sizing.rs(budget)), "loss_rs": None if loss is None else str(loss),
                "capital_rs": str(nums["capital"]["amount_rs"]), "capital_method": nums["capital"]["method"],
                "method": "fixed risk per trade (policy per_trade_risk_pct of equity)"},
        inputs_snapshot={"equity_rs": str(book.equity_rs), "pending_commitments": len(book.pending),
                         "pending_risk_rs": str(book.pending_risk_rs),
                         "pending_fno_capital_rs": str(book.pending_fno_capital_rs), "sector": sector,
                         "facts": {k: (str(v) if isinstance(v, Decimal) else v) for k, v in facts.items()},
                         "loss_estimate": nums["loss"], "credit_terms": credit, "as_of": as_of.isoformat(),
                         "session_date": session_date.isoformat(), "book_basis": book.basis},
        policy_id=policy["policy_id"], policy_version=int(policy["version"]), engine_version=ENGINE_VERSION,
        warnings=warnings)


def _largest_passing(upper: int, ok: Callable[[int], bool]) -> Optional[int]:
    """Largest m in [1, upper) with ok(m), assuming ok is monotone (smaller is never worse). None if none."""
    lo, hi = 0, upper - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if ok(mid):
            lo = mid
        else:
            hi = mid - 1
    return lo if lo >= 1 and ok(lo) else None
