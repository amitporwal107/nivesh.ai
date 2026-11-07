"""Shared pieces of the Phase 2 tests. TEST DATA — NOT REAL MARKET DATA: crafted session rows and plans.

A simulation account with a plan that is approved and assessed PASS, a frozen session-bar source, and a fake quote source.
"""
from __future__ import annotations

import itertools
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from autodesk import contracts as C
from autodesk import store
from autodesk.accounts import open_account
from autodesk.agents.middle_office import build_scope
from autodesk.execution import adapters as ad
from autodesk.execution.gateway import ExecutionGateway
from autodesk.market.live_quotes import LiveQuote, QuoteAnswer
from autodesk.market.session_bars import LegRef, SessionBar, SessionBarSource

D = Decimal
SD = date(2026, 11, 5)
IST = timezone(timedelta(hours=5, minutes=30))
AT_0900 = datetime(2026, 11, 5, 9, 0, tzinfo=IST).astimezone(timezone.utc)      # PROPOSALS phase
AT_0915 = datetime(2026, 11, 5, 9, 15, tzinfo=IST).astimezone(timezone.utc)      # OPEN
AT_1530 = datetime(2026, 11, 5, 15, 30, tzinfo=IST).astimezone(timezone.utc)     # CLOSE
EXP = date(2026, 11, 26)
_n = itertools.count(1)


def tenant() -> str:
    return f"t-p2-{next(_n)}"


def wide_policy(**over) -> C.PolicyBody:
    base = dict(per_trade_risk_pct=D("5"), open_risk_pct=D("50"), position_pct=D("50"), sector_pct=D("100"),
                max_margin_utilization_pct=D("100"), min_days_to_expiry=1)
    base.update(over)
    return C.PolicyBody(**base)


class FrozenSessionBars(SessionBarSource):
    """Rows keyed by (leg key, session). `rows[key]` may be a SessionBar (same for any session) or a dict by session."""

    def __init__(self, rows: dict):
        super().__init__()
        self.rows = rows

    async def _read(self, leg: LegRef, session: date) -> Optional[SessionBar]:
        if callable(self.rows):
            return self.rows(leg, session)
        r = self.rows.get(leg.key)
        return r.get(session) if isinstance(r, dict) else r


def bar(open_, high=None, low=None, close=None, *, units=1_000_000, lot=None, prev=None, traded=True, session=SD) -> SessionBar:
    o = D(str(open_))
    return SessionBar(day=session, open=o, high=D(str(high)) if high is not None else o * D("1.01"),
                      low=D(str(low)) if low is not None else o * D("0.99"), close=D(str(close)) if close is not None else o,
                      settle=None, prev_close=D(str(prev)) if prev is not None else o, traded_units=units, lot_size=lot,
                      traded=traded, source="TEST DATA session row")


def key_eq(sym="ACME") -> str:
    return LegRef("EQ", sym).key


def key_opt(kind, strike, sym="ACME", expiry=EXP) -> str:
    return LegRef(kind, sym, expiry, D(str(strike))).key


def key_fut(sym="ACME", expiry=EXP) -> str:
    return LegRef("FUT", sym, expiry).key


def eq_body(account_id: str, *, sym="ACME", shares=100, px="1000", inv="960", sector="IT", order_type="LIMIT",
            zone_high=None, sd=SD) -> C.TradePlanBody:
    p = D(px)
    leg = C.PlanLeg(leg_id="L1", kind=C.InstrumentKind.EQ, underlying=sym, side=C.LegSide.LONG, lots=shares, lot_size=1,
                    quantity=shares, ref_price=p, ref_price_source="TEST DATA")
    entry = {"order_type": order_type, "max_slippage_pct": "0.5", "reference_price": px}
    if zone_high:
        entry["zone_high"] = zone_high
    return C.TradePlanBody(
        thesis="test plan", rationale=["test"], signal_id=None, market_context={"sector": sector}, account_id=account_id,
        instrument=sym, segment=C.Segment.CASH, strategy_type=C.StrategyType.LONG_EQUITY, legs=[leg], entry=entry,
        invalidation={"underlying_level": inv}, targets=[], max_loss_rs=(p - D(inv)) * shares, max_profit_rs=None,
        loss_defined=False, breakevens=[p], expected_payoff={}, capital_required_rs=p * shares, margin_estimate={},
        liquidity={}, holding={}, exit_rules={}, risk_warnings=[], provenance={"agent": "test"},
        plan_expires_at=datetime(sd.year, sd.month, sd.day, 15, 30, tzinfo=IST).astimezone(timezone.utc))


def opt_leg(leg_id, kind, side, strike, premium, lots=2, lot=500, sym="ACME") -> C.PlanLeg:
    return C.PlanLeg(leg_id=leg_id, kind=C.InstrumentKind(kind), underlying=sym, expiry=EXP, strike=D(str(strike)),
                     side=C.LegSide(side), lots=lots, lot_size=lot, quantity=lots * lot, ref_price=D(str(premium)),
                     ref_price_source="TEST DATA", open_interest=50_000)


def spread_body(account_id: str, legs, strategy, *, max_loss, capital, sym="ACME", sector="IT") -> C.TradePlanBody:
    return C.TradePlanBody(
        thesis="test spread", rationale=["test"], signal_id=None, market_context={"sector": sector}, account_id=account_id,
        instrument=sym, segment=C.Segment.OPTIONS, strategy_type=strategy, legs=legs, entry={"order_type": "LIMIT"},
        invalidation={}, targets=[], max_loss_rs=D(str(max_loss)), max_profit_rs=None, loss_defined=True, breakevens=[],
        expected_payoff={}, capital_required_rs=D(str(capital)), margin_estimate={"amount_rs": str(capital), "fno": True},
        liquidity={}, holding={}, exit_rules={}, risk_warnings=[], provenance={"agent": "test"},
        plan_expires_at=datetime(2026, 11, 5, 15, 30, tzinfo=IST).astimezone(timezone.utc))


async def make_simulation(pool, t: str, *, capital="1000000", policy: Optional[C.PolicyBody] = None, seed=42) -> tuple[dict, dict, dict]:
    """(simulation row, its account, its policy row)."""
    cfg = C.SimulationConfig(name="p2", start_date=SD, end_date=SD, seed=seed, starting_capital_rs=D(capital))
    async with pool.acquire() as c:
        async with c.transaction():
            sim = await store.create_simulation(c, tenant_id=t, cfg=cfg, created_by="test", versions={})
            pol = await store.create_policy(c, tenant_id=t, name="p", body=(policy or wide_policy()).model_dump(mode="json"),
                                            created_by="test")
            acc = await open_account(c, tenant_id=t, name="sim", kind=C.AccountKind.SIMULATION,
                                     mode=C.OperatingMode.AUTONOMOUS_PAPER, capital=D(capital), created_by="test",
                                     policy_id=pol["policy_id"], simulation_id=sim["simulation_id"])
    return sim, acc, pol


async def make_desk_account(pool, t: str, *, capital="1000000", policy: Optional[C.PolicyBody] = None,
                            mode=C.OperatingMode.AUTONOMOUS_PAPER) -> tuple[dict, dict]:
    async with pool.acquire() as c:
        async with c.transaction():
            pol = await store.create_policy(c, tenant_id=t, name="p", body=(policy or wide_policy()).model_dump(mode="json"),
                                            created_by="test")
            acc = await open_account(c, tenant_id=t, name="desk", kind=C.AccountKind.PAPER, mode=mode, capital=D(capital),
                                     created_by="test", policy_id=pol["policy_id"])
    return acc, pol


async def make_approved_plan(pool, t: str, acc: dict, pol: dict, body: C.TradePlanBody, *, verdict="PASS", approved=True,
                             approval_expires: Optional[datetime] = None, policy_version: Optional[int] = None,
                             scope_body: Optional[C.TradePlanBody] = None, began_mode: Optional[str] = None) -> dict:
    """A plan row (status APPROVED) with a risk assessment and an APPROVED decision bound to its hash. -> {trade_id, approval_id, ...}"""
    sim_id = acc["simulation_id"]
    async with pool.acquire() as c:
        async with c.transaction():
            wid = None
            if began_mode:                       # a workflow that began while the account was in `began_mode`
                wf, _ = await store.create_workflow(c, tenant_id=t, account_id=acc["account_id"], kind=C.WorkflowKind.TRADE_PROPOSAL,
                                                    producer="test", simulation_id=sim_id, session_date=SD, sim_time=None,
                                                    idempotency_key=f"wf-{next(_n)}", input={"operating_mode": began_mode})
                wid = wf["workflow_id"]
            plan = await store.create_plan(c, tenant_id=t, body=body, created_by="test", simulation_id=sim_id, workflow_id=wid)
            tid = plan["trade_id"]
            a = C.RiskAssessment(trade_id=tid, plan_version=1, account_id=acc["account_id"], simulation_id=sim_id,
                                 verdict=C.RiskVerdict(verdict), checks=[], sizing={}, inputs_snapshot={},
                                 policy_id=pol["policy_id"], policy_version=policy_version or pol["version"], engine_version="test")
            await store.insert_risk_assessment(c, tenant_id=t, a=a, producer="test", workflow_id=None)
            out = {"trade_id": tid, "assessment_id": a.assessment_id, "approval_id": None}
            if approved:
                d = C.ApprovalDecision(trade_id=tid, plan_version=1, account_id=acc["account_id"], simulation_id=sim_id,
                                       status=C.ApprovalStatus.APPROVED, decided_by="MIDDLE_OFFICE@test", reasons=["test"],
                                       scope=build_scope(tenant_id=t, account=acc, trade_id=tid, plan_version=1, plan=scope_body or body),
                                       risk_assessment_id=a.assessment_id,
                                       expires_at=approval_expires or body.plan_expires_at)
                await store.insert_approval(c, tenant_id=t, d=d, producer="test", workflow_id=None)
                out["approval_id"] = d.approval_id
                await store.set_plan_status(c, tenant_id=t, trade_id=tid, status=C.PlanStatus.APPROVED)
    return out


def sim_gateway(pool, rows: dict, **kw) -> ExecutionGateway:
    from autodesk.execution.fill_model import DEFAULT_PARAMS
    params = kw.pop("params", DEFAULT_PARAMS)
    return ExecutionGateway(pool, sim=ad.SimulationPaperAdapter(FrozenSessionBars(rows), params), params=params, **kw)


class FakeQuotes:
    """TEST DOUBLE — not real market data. Returns what the test sets."""

    def __init__(self):
        self.answer = QuoteAnswer()
        self.calls = 0

    async def quotes(self, legs, now):
        self.calls += 1
        legs = list(legs)
        return QuoteAnswer(quotes={k: v for k, v in self.answer.quotes.items() if any(l.key == k for l in legs)},
                           problems=dict(self.answer.problems))


def quote(key, symbol, ltp, *, bid=None, ask=None, bid_qty=10_000, ask_qty=10_000, volume=500_000, at: datetime,
          lot=None, source="test-feed") -> LiveQuote:
    return LiveQuote(key=key, symbol=symbol, ltp=D(str(ltp)), bid=D(str(bid)) if bid is not None else None,
                     ask=D(str(ask)) if ask is not None else None, bid_qty=bid_qty, ask_qty=ask_qty, volume=volume,
                     received_at=at, last_trade_at=at, lot_size=lot, source=source)
