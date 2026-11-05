"""Trading Assistant — Strategist (PRD §6.2). Deterministic in Phase 1.

GENERATE_STRATEGY: turn a signal into alternatives — shares, futures and defined-risk option structures built with
the existing templates (services/strategy_plan/templates.py) on the PREVIOUS session's bhavcopy chain — size each to
the per-trade risk budget, order them, and return the first that meets its own rule as a full plan (all 19 PRD fields),
or NO_TRADE with the reasons. A premium is never guessed: a strike side that did not trade is skipped.

Order of preference (rule ta-rules-v1): only alternatives that meet their own rule are offered (directional
reward:risk ≥ policy minimum; credit after costs ≥ width × fraction), in CANDIDATES order for the signal's direction and
segment, then by reward:risk. Losses use control/sizing.py, the same calculator the risk engine checks with.

REVISE_STRATEGY: size-only violations with an allowed size → the same structure at that size; otherwise the next
alternative not yet tried; nothing left → NO_TRADE.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timezone
from decimal import ROUND_DOWN, Decimal
from typing import Any, Optional

from services import option_pricing as op
from services.risk_gate import estimate as est
from services.strategy_plan import templates as tp

from ..contracts import (AgentDescriptor, AgentKey, AgentResult, Direction, Greeks, InstrumentKind, LegSide, PlanLeg,
                         PolicyBody, RiskAssessment, Segment, Signal, StrategyProposal, StrategyType, TargetLevel,
                         TaskSpec, TaskType, Timeframe, TradePlanBody)
from ..control import sizing
from ..market.view import IST, DataUnavailable, chain_snapshot, published_at
from .base import Agent, AgentContext

VERSION = "autodesk-ta-v1"
RULE_VERSION = "ta-rules-v1"
DESCRIPTOR = AgentDescriptor(
    agent_key=AgentKey.TRADING_ASSISTANT, version=VERSION, kind="DETERMINISTIC",
    task_types=[TaskType.GENERATE_STRATEGY, TaskType.REVISE_STRATEGY],
    tools=["market.daily_bars", "market.futures", "market.options", "market.expiries", "market.lot_size",
           "market.vix", "market.sector"],
    prohibited=["approve own proposal", "execute"])

S = StrategyType
CANDIDATES = {
    # shares first for a cash signal; derivative structures first for a derivatives signal
    ("BULLISH", "CASH"): [S.LONG_EQUITY, S.BULL_CALL_SPREAD, S.BULL_PUT_SPREAD, S.LONG_FUTURES, S.LONG_CALL],
    ("BULLISH", "FNO"): [S.BULL_CALL_SPREAD, S.BULL_PUT_SPREAD, S.LONG_FUTURES, S.LONG_EQUITY, S.LONG_CALL],
    ("BEARISH", "CASH"): [S.BEAR_PUT_SPREAD, S.BEAR_CALL_SPREAD, S.SHORT_FUTURES, S.LONG_PUT],
    ("BEARISH", "FNO"): [S.BEAR_PUT_SPREAD, S.BEAR_CALL_SPREAD, S.SHORT_FUTURES, S.LONG_PUT],
    ("NEUTRAL", "CASH"): [S.IRON_CONDOR],
    ("NEUTRAL", "FNO"): [S.IRON_CONDOR],
}
WORDS = {S.LONG_EQUITY: "long shares", S.LONG_FUTURES: "long futures", S.SHORT_FUTURES: "short futures",
         S.LONG_CALL: "long call", S.LONG_PUT: "long put", S.BULL_CALL_SPREAD: "bull call spread",
         S.BEAR_PUT_SPREAD: "bear put spread", S.BULL_PUT_SPREAD: "bull put spread (credit)",
         S.BEAR_CALL_SPREAD: "bear call spread (credit)", S.IRON_CONDOR: "iron condor (credit)"}
SIZE_VIOLATIONS = set(sizing.SIZE_CHECKS)
TICK = Decimal("0.05")


@dataclass
class Alt:
    strategy: StrategyType
    legs: list[PlanLeg] = field(default_factory=list)
    skip: Optional[str] = None
    loss: Optional[dict] = None
    loss_rs: Optional[Decimal] = None
    reward_rs: Optional[Decimal] = None
    rr: Optional[Decimal] = None
    credit: Optional[dict] = None
    meets_rule: bool = False
    max_profit_rs: Optional[Decimal] = None
    breakevens: list[Decimal] = field(default_factory=list)
    loss_defined: bool = False
    chain_as_of: Optional[str] = None
    atm_iv: Optional[float] = None
    order: int = 0
    rule_note: Optional[str] = None             # why it does not meet its own rule
    max_profit_unit: Optional[Decimal] = None   # maximum profit for one lot (None = unbounded / not defined)

    def summary(self) -> dict:
        return {"strategy": self.strategy.value, "skip": self.skip,
                "size": sizing.size_of(self.legs) if self.legs else None,
                "loss_rs": str(self.loss_rs) if self.loss_rs is not None else None,
                "reward_rs": str(self.reward_rs) if self.reward_rs is not None else None,
                "reward_risk": str(self.rr) if self.rr is not None else None,
                "net_credit_rs": (self.credit or {}).get("net_credit_rs"), "meets_rule": self.meets_rule,
                "rule_note": self.rule_note}


def _d(x) -> Optional[Decimal]:
    return None if x is None else Decimal(str(x))


def _tick(x: Decimal) -> Decimal:
    return (x / TICK).quantize(Decimal("1"), rounding=ROUND_DOWN) * TICK


def session_close(d: date) -> datetime:
    return datetime.combine(d, dtime(15, 30), tzinfo=IST).astimezone(timezone.utc)


class _Ctx:
    """What one build needs, read once."""

    def __init__(self, sig: Signal, ctx: AgentContext):
        self.sig, self.ctx = sig, ctx
        self.pol = PolicyBody.model_validate(ctx.policy["body"])
        self.sd = date.fromisoformat(ctx.inputs["session_date"])
        self.equity = Decimal(str(ctx.account["starting_capital_rs"]))
        self.budget = self.equity * self.pol.per_trade_risk_pct / 100
        self.inv = sig.invalidation_price
        self.t1 = sig.targets[0] if sig.targets else None
        self.lot: Optional[int] = None
        self.expiry: Optional[date] = None
        self.fut: Optional[Any] = None
        self.chain: Optional[dict] = None
        self.spot: Optional[Decimal] = sig.reference_price
        self.fno_day: Optional[date] = None
        self.fno_reason: Optional[str] = None
        self.vix: Optional[Decimal] = None
        self.sector: Optional[str] = sig.sector


async def _load_fno(c: _Ctx) -> None:
    m = c.ctx.market
    try:
        c.fno_day = m.latest_session("fno")
        c.lot = await m.lot_size(c.sig.instrument)
        if not c.lot:
            c.fno_reason = "no F&O contracts for this instrument on the latest F&O session"
            return
        exps = [e for e in await m.expiries(c.sig.instrument)
                if e > c.sd and (e - c.sd).days >= c.pol.min_days_to_expiry]
        if not exps:
            c.fno_reason = f"no expiry at least {c.pol.min_days_to_expiry} days after {c.sd}"
            return
        c.expiry = exps[0]
        futs = [f for f in await m.futures(c.sig.instrument) if f.expiry == c.expiry]
        c.fut = futs[0] if futs else None
        rows = await m.options(c.sig.instrument, c.expiry)
        und = next((r.underlying_price for r in rows if r.underlying_price), None)
        c.spot = und or (c.fut.underlying_price if c.fut else None) or c.spot
        c.chain = chain_snapshot(rows, spot=c.spot, require_traded=c.pol.require_traded_legs)
    except DataUnavailable as e:
        c.fno_reason = f"F&O data unavailable: {e}"


def _strikes(chain: dict, side: str) -> list[float]:
    return [r["strike"] for r in chain["strikes"] if (r.get(side) or {}).get("close")]


def _oi(chain: dict, strike: float, side: str) -> Optional[int]:
    for r in chain["strikes"]:
        if r["strike"] == strike:
            return (r.get(side) or {}).get("oi")
    return None


def _iv_greeks(c: _Ctx, kind: str, strike: float, premium: float) -> tuple[Optional[float], Optional[Greeks]]:
    if not c.fno_day or not c.expiry:
        return None, None
    t = op.year_fraction(op.days_between(c.fno_day, c.expiry))
    fwd = op.choose_forward(float(c.fut.settle or c.fut.close) if c.fut and (c.fut.settle or c.fut.close) else None,
                            float(c.spot) if c.spot else None, t)
    if not fwd:
        return None, None
    iv = op.implied_vol(kind, premium, fwd[0], strike, t)
    g = op.greeks(kind, fwd[0], strike, t, iv) if iv else None
    if g is None:
        return iv, None
    q = lambda v: Decimal(str(v)).quantize(Decimal("0.0001"))   # noqa: E731
    return iv, Greeks(delta=q(g.delta), gamma=q(g.gamma), theta=q(g.theta), vega=q(g.vega), iv=q(iv),
                      model=f"Black-76 implied from the bhavcopy close, forward by {fwd[1]} (model)")


def _template_legs(c: _Ctx, res: dict) -> list[PlanLeg]:
    out = []
    for i, lg in enumerate(res["legs"], start=1):
        side = LegSide.LONG if lg["side"] == "buy" else LegSide.SHORT
        if lg["kind"] == "option":
            kind = InstrumentKind.CE if lg["option_type"] == "call" else InstrumentKind.PE
            _iv, g = _iv_greeks(c, kind.value, lg["strike"], lg["entry_price"])
            out.append(PlanLeg(leg_id=f"L{i}", kind=kind, underlying=c.sig.instrument, expiry=c.expiry,
                               strike=_d(lg["strike"]), side=side, lots=lg["quantity"], lot_size=lg["lot_size"],
                               quantity=lg["quantity"] * lg["lot_size"], ref_price=_d(lg["entry_price"]),
                               ref_price_source=lg.get("price_source") or "bhavcopy",
                               open_interest=_oi(c.chain, lg["strike"], "call" if kind == InstrumentKind.CE else "put"),
                               greeks=g))
        elif lg["kind"] == "future":
            out.append(PlanLeg(leg_id=f"L{i}", kind=InstrumentKind.FUT, underlying=c.sig.instrument, expiry=c.expiry,
                               side=side, lots=lg["quantity"], lot_size=lg["lot_size"],
                               quantity=lg["quantity"] * lg["lot_size"], ref_price=_d(lg["entry_price"]),
                               ref_price_source=lg.get("price_source") or "bhavcopy",
                               open_interest=c.fut.open_interest if c.fut else None))
    return out


def _measure(c: _Ctx, a: Alt) -> Alt:
    """Loss, credit, reward and whether the alternative meets its own rule, at its current size."""
    direction = c.sig.direction
    a.loss, why = sizing.loss(a.legs, strategy=a.strategy, direction=direction, invalidation=c.inv)
    if a.loss is None:
        a.skip = f"loss cannot be estimated: {why}"
        return a
    a.loss_rs = sizing.rs(a.loss["total"])
    a.credit = sizing.credit(a.legs)
    a.rr, a.reward_rs, a.meets_rule, a.rule_note = None, None, False, None
    if a.credit is not None:
        net = Decimal(str(a.credit["net_credit_rs"])) - Decimal(str(a.loss["costs"]))
        need = Decimal(str(a.credit["width_rs"])) * c.pol.credit_min_width_fraction
        a.reward_rs = sizing.rs(net)
        a.meets_rule = net >= need
        if not a.meets_rule:
            a.rule_note = (f"net credit after costs {sizing.rs(net)} is below width {a.credit['width_rs']} × "
                           f"{c.pol.credit_min_width_fraction}")
    else:
        r = sizing.reward(a.legs, direction=direction, target=c.t1)
        if r is None and a.strategy in (S.LONG_CALL, S.LONG_PUT):
            a.meets_rule = True        # unbounded gain
        elif r is None:
            a.rule_note = "no level to measure the reward against"
        elif a.loss_rs > 0:
            a.reward_rs = sizing.rs(r)
            a.rr = (Decimal(str(r)) / a.loss_rs).quantize(Decimal("0.01"))
            a.meets_rule = a.rr >= c.pol.min_reward_risk
            if not a.meets_rule:
                a.rule_note = f"reward to loss {a.rr} is below {c.pol.min_reward_risk}"
    if a.rr is None and a.reward_rs is not None and a.loss_rs:
        a.rr = (a.reward_rs / a.loss_rs).quantize(Decimal("0.01"))
    a.max_profit_rs = None if a.max_profit_unit is None else sizing.rs(a.max_profit_unit * (sizing.size_of(a.legs) or 1))
    return a


def _evaluate(c: _Ctx, a: Alt) -> Alt:
    """Size to the per-trade budget (largest size whose loss fits), then measure."""
    direction = c.sig.direction
    unit = sizing.size_of(a.legs) or 1

    def loss_at(m: int) -> tuple[Optional[Decimal], Optional[str]]:
        e, why = sizing.loss(sizing.scale(a.legs, m), strategy=a.strategy, direction=direction, invalidation=c.inv)
        return (sizing.rs(e["total"]) if e else None), why

    one, why = loss_at(1)
    if one is None:
        a.skip = f"loss cannot be estimated: {why}"
        return a
    if one > c.budget:
        a.skip = f"one {'share' if a.strategy == S.LONG_EQUITY else 'lot'} loses {one}, above the per-trade budget " \
                 f"{sizing.rs(c.budget)}"
        return a
    upper = unit if a.strategy == S.LONG_EQUITY else c.pol.max_lots_per_leg
    lo, hi = 1, max(1, upper)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        m_loss, _ = loss_at(mid)
        if m_loss is not None and m_loss <= c.budget:
            lo = mid
        else:
            hi = mid - 1
    a.legs = sizing.scale(a.legs, lo)
    return _measure(c, a)


def _build(c: _Ctx, s: StrategyType, order: int) -> Alt:
    a = Alt(strategy=s, order=order)
    sym, sd = c.sig.instrument, c.sd
    if s == S.LONG_EQUITY:
        if c.sig.segment == Segment.INDEX:
            a.skip = "an index has no shares"
            return a
        px = c.sig.reference_price
        if px is None or c.inv is None or c.inv >= px:
            a.skip = "needs a reference price above the invalidation level"
            return a
        upper = int((c.equity * c.pol.position_pct / 100) / px)
        q = est.max_cash_qty(float(c.budget), float(px), float(c.inv), max(upper, 0))
        if q < 1:
            a.skip = "no whole number of shares fits the per-trade budget and the position cap"
            return a
        a.legs = [PlanLeg(leg_id="L1", kind=InstrumentKind.EQ, underlying=sym, side=LegSide.LONG, lots=q, lot_size=1,
                          quantity=q, ref_price=px, ref_price_source=f"close {c.sig.data_as_of.astimezone(IST).date()}")]
        a.breakevens = [_tick(px + Decimal(str(est.cash_risk(q, float(px), float(px))["costs"])) / q)]
        return _evaluate(c, a)
    if c.fno_reason or not c.lot or not c.expiry:
        a.skip = c.fno_reason or "no F&O data"
        return a
    exp = c.expiry.isoformat()
    spot = float(c.spot) if c.spot else None
    if s in (S.LONG_FUTURES, S.SHORT_FUTURES):
        if not c.fut or not (c.fut.close or c.fut.settle):
            a.skip = "no futures price for the chosen expiry"
            return a
        if c.pol.require_traded_legs and not (c.fut.traded_volume or 0) > 0:
            a.skip = "the futures contract did not trade on the latest session"
            return a
        fn = tp.long_future if s == S.LONG_FUTURES else tp.short_future
        try:
            res = fn(spot or float(c.fut.close), c.lot, exp, float(c.fut.settle or c.fut.close), lots=1,
                     underlying=sym, today=sd, as_of=c.fno_day.isoformat(),
                     source=f"NSE F&O bhavcopy settle, {c.fno_day}")
        except tp.TemplateError as e:
            a.skip = f"{e.code}: {e.message}"
            return a
        a.legs = _template_legs(c, res)
        return _evaluate(c, a)
    if not c.chain or not spot:
        a.skip = "no option chain for the chosen expiry"
        return a
    calls, puts = _strikes(c.chain, "call"), _strikes(c.chain, "put")
    nearest = lambda xs, x: min(xs, key=lambda k: (abs(k - x), k)) if xs else None   # noqa: E731
    t1 = float(c.t1) if c.t1 else None
    inv = float(c.inv) if c.inv else None
    try:
        if s == S.LONG_CALL:
            k = nearest(calls, spot)
            res = tp.long_call(c.chain, spot, c.lot, exp, k, underlying=sym, today=sd) if k else None
        elif s == S.LONG_PUT:
            k = nearest(puts, spot)
            res = tp.long_put(c.chain, spot, c.lot, exp, k, underlying=sym, today=sd) if k else None
        elif s == S.BULL_CALL_SPREAD:
            lk = nearest(calls, spot)
            highs = [k for k in calls if lk and k > lk]
            sk = nearest(highs, t1) if t1 and highs else (highs[0] if highs else None)
            res = tp.bull_call_spread(c.chain, spot, c.lot, exp, lk, sk, underlying=sym, today=sd) if lk and sk else None
        elif s == S.BEAR_PUT_SPREAD:
            lk = nearest(puts, spot)
            lows = [k for k in puts if lk and k < lk]
            sk = nearest(lows, t1) if t1 and lows else (lows[-1] if lows else None)
            res = tp.bear_put_spread(c.chain, spot, c.lot, exp, lk, sk, underlying=sym, today=sd) if lk and sk else None
        elif s in (S.BULL_PUT_SPREAD, S.BEAR_CALL_SPREAD):
            res = _credit_vertical(c, s, calls, puts, spot, inv, exp)
        elif s == S.IRON_CONDOR:
            res = _iron_condor(c, calls, puts, spot, exp)
        else:
            a.skip = "template not available in Phase 1"
            return a
    except tp.TemplateError as e:
        a.skip = f"{e.code}: {e.message}"
        return a
    if res is None:
        a.skip = "no suitable traded strikes in the chain"
        return a
    a.legs = _template_legs(c, res)
    a.chain_as_of = c.chain.get("as_of")
    a.max_profit_unit = None if res.get("profit_unbounded") else _d(res.get("max_profit"))
    a.breakevens = [_d(b) for b in res.get("breakevens") or []]
    a.loss_defined = not res.get("loss_unbounded")
    return _evaluate(c, a)


def _credit_vertical(c: _Ctx, s, calls, puts, spot, inv, exp) -> Optional[dict]:
    """Short strike just beyond the invalidation side (below spot for a bull put, above for a bear call); the long
    strike 1..4 strikes further out — the first width whose credit after costs meets the policy fraction."""
    best = None
    if s == S.BULL_PUT_SPREAD:
        ref = min(inv, spot) if inv else spot
        shorts = [k for k in puts if k <= ref and k < spot]
        if not shorts:
            return None
        sk = max(shorts)
        longs = sorted([k for k in puts if k < sk], reverse=True)[:4]
        build = lambda lk: tp.bull_put_spread(c.chain, spot, c.lot, exp, lk, sk, underlying=c.sig.instrument, today=c.sd)  # noqa: E731
    else:
        ref = max(inv, spot) if inv else spot
        shorts = [k for k in calls if k >= ref and k > spot]
        if not shorts:
            return None
        sk = min(shorts)
        longs = sorted([k for k in calls if k > sk])[:4]
        build = lambda lk: tp.bear_call_spread(c.chain, spot, c.lot, exp, sk, lk, underlying=c.sig.instrument, today=c.sd)  # noqa: E731
    for lk in longs:
        try:
            res = build(lk)
        except tp.TemplateError:
            continue
        legs = _template_legs(c, res)
        cr = sizing.credit(legs)
        e, _ = sizing.loss(legs, strategy=s, direction=c.sig.direction, invalidation=c.inv)
        if not cr or not e:
            continue
        ratio = (Decimal(str(cr["net_credit_rs"])) - Decimal(str(e["costs"]))) / Decimal(str(cr["width_rs"]))
        if best is None or ratio > best[0]:
            best = (ratio, res)
        if ratio >= c.pol.credit_min_width_fraction:
            return res
    return best[1] if best else None


def _iron_condor(c: _Ctx, calls, puts, spot, exp) -> Optional[dict]:
    """Short strikes as far from the spot as possible, but no further than one expected move (ATM implied volatility ×
    √T), whose credit after costs still meets the policy fraction of the width; wings 1–2 strikes out. With flat
    volatility, shorts at a full expected move rarely collect a third of the width, so the search walks inward.
    No pair meets the rule → the 1-expected-move condor is returned and fails its rule (it is then not offered)."""
    atm = min(calls, key=lambda k: abs(k - spot)) if calls else None
    if atm is None:
        return None
    prem = next((r["call"]["close"] for r in c.chain["strikes"] if r["strike"] == atm and r.get("call")), None)
    iv, _ = _iv_greeks(c, "CE", atm, prem) if prem else (None, None)
    if not iv:
        return None
    t = op.year_fraction(op.days_between(c.fno_day, c.expiry))
    em = spot * iv * math.sqrt(t)
    shorts_p = sorted([k for k in puts if spot - em <= k < spot], reverse=True)    # nearest first
    shorts_c = sorted([k for k in calls if spot < k <= spot + em])
    pairs = list(zip(shorts_p, shorts_c))
    fallback = None
    for spk, sck in reversed(pairs):                                             # farthest first
        for w in (1, 2):
            lps = sorted([k for k in puts if k < spk], reverse=True)
            lcs = sorted([k for k in calls if k > sck])
            if len(lps) < w or len(lcs) < w:
                break
            try:
                res = tp.iron_condor(c.chain, spot, c.lot, exp, lps[w - 1], spk, sck, lcs[w - 1],
                                     underlying=c.sig.instrument, today=c.sd)
            except tp.TemplateError:
                continue
            fallback = fallback or res
            legs = _template_legs(c, res)
            cr = sizing.credit(legs)
            e, _ = sizing.loss(legs, strategy=S.IRON_CONDOR, direction=c.sig.direction, invalidation=None)
            if cr and e and (Decimal(str(cr["net_credit_rs"])) - Decimal(str(e["costs"]))) >= \
                    Decimal(str(cr["width_rs"])) * c.pol.credit_min_width_fraction:
                return res
    return fallback


def _candidates(c: _Ctx) -> list[StrategyType]:
    seg = "CASH" if c.sig.segment == Segment.CASH else "FNO"
    order = CANDIDATES[(c.sig.direction.value, seg)]
    allowed_seg = set(c.pol.allowed_segments)
    out = []
    for s in order:
        if s not in c.pol.allowed_strategies:
            continue
        need = {Segment.CASH} if s == S.LONG_EQUITY else (
            {Segment.FUTURES} if s in (S.LONG_FUTURES, S.SHORT_FUTURES) else {Segment.OPTIONS})
        if need <= allowed_seg:
            out.append(s)
    return out


def _rank(alts: list[Alt]) -> list[Alt]:
    """The alternatives that can be offered: built, sized, and meeting their own rule."""
    ok = [a for a in alts if not a.skip and a.meets_rule]
    return sorted(ok, key=lambda a: (a.order, -(a.rr or Decimal("0"))))


def _plan(c: _Ctx, a: Alt, alts: list[Alt], tried: list[str]) -> TradePlanBody:
    sig = c.sig
    pol = c.pol
    cap = sizing.capital_used(a.legs, strategy=a.strategy, futures_margin_pct=pol.futures_margin_pct,
                              max_loss_rs=a.loss_rs)
    expires = session_close(c.sd)
    words = WORDS.get(a.strategy, a.strategy.value.lower())
    data_day = sig.data_as_of.astimezone(IST).date()
    hold_days = 10 if a.strategy == S.LONG_EQUITY else max(1, (c.expiry - c.sd).days - 2) if c.expiry else 10
    greeks = None
    gl = [lg for lg in a.legs if lg.greeks]
    if gl:
        def tot(f):
            vals = [getattr(lg.greeks, f) for lg in gl]
            if any(v is None for v in vals):
                return None
            return sum((v * lg.quantity * (1 if lg.side == LegSide.LONG else -1) for v, lg in zip(vals, gl)),
                       Decimal("0")).quantize(Decimal("0.01"))
        greeks = Greeks(delta=tot("delta"), gamma=tot("gamma"), theta=tot("theta"), vega=tot("vega"),
                        model="sum of leg Black-76 Greeks × signed quantity (model)")
    warnings = ["built on the previous session's closing prices; the next session can open at different prices"]
    if any(lg.kind in (InstrumentKind.EQ, InstrumentKind.FUT) for lg in a.legs):
        warnings.append("a gap through the invalidation level can lose more than the stated figure")
    if any(lg.kind == InstrumentKind.FUT for lg in a.legs):
        warnings.append("futures: the loss is not capped by the structure, only by closing at the invalidation level")
    if cap["estimate"]:
        warnings.append("capital tied up is an estimate, not the exchange margin")
    if sig.missing_inputs:
        warnings.append("the signal had missing inputs: " + ", ".join(sig.missing_inputs))
    targets = [TargetLevel(level=t, exit_fraction=Decimal("0.5") if i == 0 and len(sig.targets) > 1 else Decimal("1"))
               for i, t in enumerate(sig.targets[:2])]
    rationale = [f"signal {sig.category.value.replace('_', ' ').lower()} scored {sig.signal_score} on "
                 f"{data_day} data", f"{words}: {a.summary()['reward_risk'] or 'n/a'} reward to loss"
                 + (f", net credit {a.credit['net_credit_rs']} on width {a.credit['width_rs']}" if a.credit else ""),
                 f"sized to the per-trade budget {sizing.rs(c.budget)} ({pol.per_trade_risk_pct}% of equity)"]
    return TradePlanBody(
        thesis=f"{sig.instrument}: {sig.direction.value.lower()} view from a "
               f"{sig.category.value.replace('_', ' ').lower()} signal; expressed as {words}"
               + (f" with an invalidation level at {sig.invalidation_price}." if sig.invalidation_price is not None
                  else "; the structure's maximum loss bounds the risk."),
        rationale=rationale, signal_id=sig.signal_id,
        market_context={"direction": sig.direction.value, "category": sig.category.value,
                        "signal_score": str(sig.signal_score), "sector": c.sector, "vix": str(c.vix) if c.vix else None,
                        "data_as_of": sig.data_as_of.isoformat(), "fno_session": c.fno_day.isoformat() if c.fno_day
                        else None},
        account_id=c.ctx.account["account_id"], instrument=sig.instrument,
        segment=Segment.CASH if a.strategy == S.LONG_EQUITY else (
            Segment.FUTURES if a.strategy in (S.LONG_FUTURES, S.SHORT_FUTURES) else Segment.OPTIONS),
        strategy_type=a.strategy, legs=a.legs,
        entry={"order_type": "LIMIT", "reference_price": str(sig.reference_price) if sig.reference_price else None,
               "zone_low": str(sig.entry_zone["low"]) if sig.entry_zone else None,
               "zone_high": str(sig.entry_zone["high"]) if sig.entry_zone else None,
               "valid_until": expires.isoformat(), "max_slippage_pct": "0.5"},
        invalidation={"underlying_level": str(sig.invalidation_price) if sig.invalidation_price else None,
                      "rule": "close the position when the underlying closes beyond the invalidation level",
                      "max_loss_rs": str(a.loss_rs)},
        targets=targets, max_loss_rs=a.loss_rs, max_profit_rs=a.max_profit_rs, loss_defined=a.loss_defined,
        breakevens=a.breakevens,
        expected_payoff={"reward_risk": str(a.rr) if a.rr is not None else None,
                         "reward_rs": str(a.reward_rs) if a.reward_rs is not None else None,
                         "assumptions": ["prices are the previous session's closes (bhavcopy for F&O)",
                                         "costs from the desk cost card desk-cost-v2",
                                         "a calculation at the prices shown, not a forecast"]},
        capital_required_rs=cap["amount_rs"], margin_estimate=cap, net_greeks=greeks,
        volatility={"iv_source": "Black-76 implied from bhavcopy closes (model)", "vix": str(c.vix) if c.vix else None},
        liquidity={"min_leg_open_interest": min((lg.open_interest for lg in a.legs if lg.open_interest is not None),
                                                default=None),
                   "note": "the risk engine checks 20-session average traded value"},
        holding={"timeframe": Timeframe.POSITIONAL.value, "max_holding_days": hold_days,
                 "expiry": c.expiry.isoformat() if c.expiry and a.strategy != S.LONG_EQUITY else None,
                 "close_days_before_expiry": 2},
        exit_rules={"trailing": "trail-atr-v1 (2 × ATR14), tighten only", "time": f"after {hold_days} sessions",
                    "emergency": "close every leg together if any leg cannot be managed"},
        risk_warnings=warnings, plan_expires_at=expires,
        provenance={"agent": AgentKey.TRADING_ASSISTANT.value, "agent_version": VERSION, "rule_version": RULE_VERSION,
                    "data_as_of": sig.data_as_of.isoformat(), "chain_as_of": a.chain_as_of,
                    "inputs": [f"signal://{sig.signal_id}"], "tried": tried + [a.strategy.value]},
        costs_estimate={k: a.loss.get(k) for k in ("costs", "gap_stress", "gross", "total", "basis")} if a.loss else {},
        alternatives_considered=[x.summary() for x in alts])


class TradingAssistant(Agent):
    descriptor = DESCRIPTOR

    async def _alternatives(self, c: _Ctx) -> list[Alt]:
        try:
            c.vix = await c.ctx.market.vix()
        except DataUnavailable:
            c.vix = None
        if not c.sector:
            c.sector = await c.ctx.market.sector(c.sig.instrument)
        cands = _candidates(c)
        if any(s != S.LONG_EQUITY for s in cands):
            await _load_fno(c)
        return [_build(c, s, i) for i, s in enumerate(cands)]

    async def run(self, task: TaskSpec, ctx: AgentContext) -> AgentResult:
        sig = Signal.model_validate(ctx.inputs["signal"])
        c = _Ctx(sig, ctx)
        alts = await self._alternatives(c)
        tried: list[str] = []
        chosen: Optional[Alt] = None
        if task.task_type == TaskType.REVISE_STRATEGY:
            prev = TradePlanBody.model_validate(ctx.inputs["plan"]["body"])
            a = RiskAssessment.model_validate(ctx.inputs["assessment"])
            tried = list((prev.provenance or {}).get("tried") or [prev.strategy_type.value])
            allowed = (a.sizing or {}).get("allowed_size")
            same = next((x for x in alts if x.strategy == prev.strategy_type and not x.skip), None)
            if set(a.violations) <= SIZE_VIOLATIONS and allowed and same is not None:
                same.legs = sizing.scale(same.legs, int(allowed))
                same = _measure(c, same)
                if not same.skip and same.meets_rule:
                    chosen = same
                    tried = tried[:-1] if tried and tried[-1] == same.strategy.value else tried
            if chosen is None:
                rest = [x for x in _rank(alts) if x.strategy.value not in tried]
                chosen = rest[0] if rest else None
        else:
            ranked = _rank(alts)
            chosen = ranked[0] if ranked else None
        if chosen is None:
            reasons = [f"{x.strategy.value}: {x.skip or x.rule_note}" for x in alts
                       if x.skip or not x.meets_rule] or ["no alternative left to try"]
            if task.task_type == TaskType.REVISE_STRATEGY:
                reasons.insert(0, "every alternative was tried or cannot be built")
            out = StrategyProposal(decision="NO_TRADE", reasons=reasons, alternatives=[x.summary() for x in alts])
            return AgentResult(output_schema="strategy-proposal-v1", output=out.model_dump(mode="json"),
                               summary=f"no plan for {sig.instrument}: {reasons[0]}",
                               evidence_refs=[f"signal://{sig.signal_id}"])
        body = _plan(c, chosen, alts, tried)
        out = StrategyProposal(decision="PLAN", plan=body, alternatives=[x.summary() for x in alts])
        return AgentResult(output_schema="strategy-proposal-v1", output=out.model_dump(mode="json"),
                           summary=f"{WORDS.get(chosen.strategy, chosen.strategy.value)} on {sig.instrument}, "
                                   f"size {sizing.size_of(chosen.legs)}, loss {chosen.loss_rs}",
                           evidence_refs=[f"signal://{sig.signal_id}"])
