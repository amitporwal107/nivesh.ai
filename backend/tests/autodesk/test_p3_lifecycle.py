"""AD-P3-*: Phase 3A lifecycle, from a confirmed (simulated) fill to a reconciled closure. TEST DATA — NOT REAL MARKET DATA: rows,
plans and quotes are crafted; FakeQuotes is a TEST DOUBLE. See docs/autodesk/testcases_phase3a.md."""
from __future__ import annotations

import ast
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from autodesk import contracts as C
from autodesk import store
from autodesk.execution import adapters as ad
from autodesk.execution import capital, reports, settle
from autodesk.execution.fill_model import DEFAULT_PARAMS, TICK
from autodesk.execution.gateway import ExecutionGateway
from autodesk.lifecycle import controls, limits, recon
from autodesk.lifecycle import rules as RL
from autodesk.lifecycle.manager import LifecycleManager, _pre_expiry_session
from autodesk.market import calendar
from autodesk.market.live_quotes import QuoteAnswer
from services import exit_rules as XR
from tests.autodesk import p2_harness as H
from tests.autodesk.conftest import run
from tests.autodesk.test_safety import ADVICE

D = Decimal
IST = H.IST
S1, S2, S3, S4 = date(2026, 11, 5), date(2026, 11, 6), date(2026, 11, 9), date(2026, 11, 10)


def at(d: date, hh: int, mm: int) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=IST).astimezone(timezone.utc)


def lc_gateway(pool, rows, *, seed_params=DEFAULT_PARAMS, lifecycle=True, adapter=None):
    lc = LifecycleManager(pool, params=seed_params) if lifecycle else None
    sim = adapter or ad.SimulationPaperAdapter(H.FrozenSessionBars(rows), seed_params)
    return ExecutionGateway(pool, sim=sim, params=seed_params, lifecycle=lc)


def eq_plan(aid, *, shares=100, px="1000", inv="960", targets=(), hold=None, trail=None, sd=S1, sector="IT", zone_high=None):
    b = H.eq_body(aid, shares=shares, px=px, inv=inv, sector=sector, sd=sd, zone_high=zone_high)
    return b.model_copy(update={
        "targets": [C.TargetLevel(level=D(l), exit_fraction=D(f)) for l, f in targets],
        "holding": {"max_holding_days": hold} if hold else {},
        "exit_rules": {"trailing": trail} if trail else {},
        "market_context": {"sector": sector, "direction": "BULLISH"}})


def by_session(**rows):
    """{key: {session: bar}}"""
    return rows


async def one_sim(pool, body_fn, rows, *, seed=42, capital_="1000000", policy=None, lifecycle=True, adapter=None):
    t = H.tenant()
    sim, acc, pol = await H.make_simulation(pool, t, capital=capital_, seed=seed, policy=policy)
    body = body_fn(acc["account_id"])
    plan = await H.make_approved_plan(pool, t, acc, pol, body)
    gw = lc_gateway(pool, rows, lifecycle=lifecycle, adapter=adapter)
    it = await gw.create_intent(tenant_id=t, trade_id=plan["trade_id"], plan_version=1, as_of=H.AT_0900,
                                approval_id=plan["approval_id"])
    assert it["status"] == "VALIDATED", it["refusal_codes"]
    return t, sim, acc, plan, gw


async def sessions(gw, t, sid, days):
    out = []
    for d in days:
        o = await settle.run_open(gw, tenant_id=t, simulation_id=sid, session=d, as_of=at(d, 9, 15))
        cl = await settle.run_close(gw, tenant_id=t, simulation_id=sid, session=d, as_of=at(d, 15, 30))
        out.append((o, cl))
    return out


async def facts(pool, trade_id):
    async with pool.acquire() as c:
        pos = dict(await c.fetchrow("SELECT * FROM autodesk.trade_positions WHERE trade_id=$1", trade_id))
        legs = [dict(r) for r in await c.fetch("SELECT * FROM autodesk.trade_position_legs WHERE position_id=$1 ORDER BY leg_id",
                                               pos["position_id"])]
        recs = [dict(r) for r in await c.fetch("SELECT * FROM autodesk.trade_exit_records WHERE trade_id=$1 ORDER BY created_at",
                                               trade_id)]
        fills = [dict(r) for r in await c.fetch(
            "SELECT f.*, o.purpose FROM autodesk.trade_fills f JOIN autodesk.trade_orders o USING (order_id) "
            "WHERE f.trade_id=$1 ORDER BY f.fill_time", trade_id)]
        moves = [r["to_state"] for r in await c.fetch("SELECT to_state FROM autodesk.trade_lifecycle_events WHERE trade_id=$1 ORDER BY seq",
                                                      trade_id)]
        jour = [(r["kind"], r["summary"]) for r in await c.fetch(
            "SELECT kind, summary FROM autodesk.trade_journal_entries WHERE trade_id=$1 ORDER BY seq", trade_id)]
        led = {r["entry_type"]: dict(r) for r in await c.fetch(
            """SELECT entry_type, sum(cash_delta_rs) AS cash, sum(realized_gross_delta_rs) AS realized, sum(margin_delta_rs) AS margin,
                      sum(open_risk_delta_rs) AS risk, sum(notional_delta_rs) AS notional, sum(fees_delta_rs) AS fees
               FROM autodesk.capital_ledger_entries WHERE trade_id=$1 GROUP BY entry_type""", trade_id)}
        v = await capital.balances(c, pos["tenant_id"], pos["account_id"])
        checks = await recon.account_checks(c, pos["tenant_id"], pos["account_id"])
    return {"pos": pos, "legs": legs, "recs": recs, "fills": fills, "moves": moves, "journal": jour, "ledger": led, "v": v,
            "checks": checks}


def all_zero(checks):
    return all(k["ok"] and k["difference_rs"] == "0.00" for k in checks), [k for k in checks if not k["ok"]]


# ── A. rules from the plan (pure) ────────────────────────────────────────────────────────────────────────────────

def test_adp3_01_share_rules_from_the_plan_and_the_actual_fill():
    body = eq_plan("ACC", targets=[("1060", "0.5"), ("1100", "1")], hold=10, trail="trail-atr-v1 (2 × ATR14), tighten only")
    s = RL.setup(body.model_dump(mode="json"), [{"kind": "EQ", "underlying": "ACME", "side": "LONG", "avg_price": D("1003.50")}])
    r = RL.make_rules(s, 0)
    st = RL.start_state(s, r, session=S1, warmup=[])
    assert (s.trigger_key, s.side, s.level, s.max_hold, s.trail) == ("EQ:ACME", "long", D("960.00"), 10, (2.0, 14))
    assert r.target == 1060.0 and r.max_hold_sessions == 10 and r.trail_atr_mult == 2.0 and r.atr_period == 14
    assert st.entry_price == 1003.5 and st.stop == 960.0 and st.stop_version == 1
    assert [o["fraction"] for o in s.objectives] == ["0.5", "1"]


def test_adp3_02_03_04_05_trigger_series_by_structure():
    fut = H.eq_body("A").model_dump(mode="json")
    s = RL.setup(fut, [{"kind": "FUT", "underlying": "ACME", "side": "LONG", "avg_price": D("1012"), "expiry": H.EXP}],
                 fut_prev_close=D("1010"), und_prev_close=D("1000"))
    assert (s.trigger_key, s.trigger_basis, s.ratio, s.level) == (f"FUT:ACME:{H.EXP}", "FUTURE_ROW_TRANSLATED", D("1.01000000"),
                                                                   D("969.60"))
    opt = {**fut, "market_context": {"direction": "BEARISH"}}
    s = RL.setup(opt, [{"kind": "PE", "underlying": "ACME", "side": "LONG", "avg_price": D("20"), "expiry": H.EXP}], und_open=D("990"))
    assert (s.trigger_key, s.side, s.structure, s.entry_trigger_price) == ("EQ:ACME", "short", True, D("990"))
    neu = {**fut, "market_context": {"direction": "NEUTRAL"}}
    s = RL.setup(neu, [{"kind": "CE", "underlying": "ACME", "side": "SHORT", "avg_price": D("5"), "expiry": H.EXP}])
    assert s.trigger_key is None and s.level is None and "neutral" in s.notes[0]
    assert RL.parse_trail("trail-atr-v1 (2 × ATR14), tighten only") == (2.0, 14) and RL.parse_trail("none") is None
    assert RL.parse_trend("trend-ema-v1 (EMA 20)") == 20 and RL.parse_trend(None) is None


def test_adp3_06_pre_expiry_session():
    saved = calendar._HOLIDAYS.get(2026)
    try:
        calendar.set_holidays(2026, {})
        d, basis = run(_pre_expiry_session(date(2026, 11, 26), date(2026, 11, 16), 2))
        assert d == date(2026, 11, 24) and basis == "exchange sessions"
    finally:
        if saved is not None:
            calendar.set_holidays(2026, saved)
        else:
            calendar._HOLIDAYS.pop(2026, None)


# ── B. decisions and the clock (pure) ────────────────────────────────────────────────────────────────────────────

def _eq_setup(**kw):
    body = eq_plan("ACC", **kw).model_dump(mode="json")
    return RL.setup(body, [{"kind": "EQ", "underlying": "ACME", "side": "LONG", "avg_price": D("1000")}])


def test_adp3_10_11_open_sees_only_the_open_and_changes_nothing_else():
    s = _eq_setup(trail="trail-atr-v1 (2 × ATR3)")
    st = RL.start_state(s, RL.make_rules(s, 0), session=S1, warmup=[])
    assert RL.at_open(s, st, 0, D("1005"), S2) is None                     # nothing decided: state not stepped (no ATR, no mark)
    d = RL.at_open(s, st, 0, D("950"), S2)
    assert (d.reason, d.how, d.gapped, d.trigger_price) == (C.CloseReason.STOP, C.PriceHow.OPEN, True, D("950"))


def test_adp3_12_13_14_15_close_decisions():
    s = _eq_setup(targets=[("1060", "0.5"), ("1100", "1")])
    st = RL.start_state(s, RL.make_rules(s, 0), session=S1, warmup=[])
    b = lambda o, h, l, c: H.bar(o, h, l, c, session=S2)                   # noqa: E731
    x = RL.at_close(s, st, 0, b(1004, 1010, 955, 958), S2)
    assert (x.decision.reason, x.decision.how, x.decision.level) == (C.CloseReason.STOP, C.PriceHow.LEVEL, D("960.00"))
    x = RL.at_close(s, st, 0, b(1004, 1070, 955, 1000), S2)
    assert x.decision.reason == C.CloseReason.STOP and x.decision.both_in_range       # the adverse level wins
    x = RL.at_close(s, st, 0, b(1004, 1060, 1001, 1050), S2)
    assert x.decision is None and x.state.sessions_held == 1 and x.events[-1]["code"] == "objective_touched"
    x = RL.at_close(s, st, 0, b(1004, 1061, 1001, 1050), S2)
    assert (x.decision.reason, x.decision.how, x.decision.fraction, x.decision.objective_index) == \
        (C.CloseReason.TARGET, C.PriceHow.OBJECTIVE, D("0.5"), 0)
    assert not x.state.closed                                                 # the rest goes on


def test_adp3_16_lots():
    assert RL.lots_to_close(100, 1, D("0.5")) == 50 and RL.lots_to_close(500, 500, D("0.5")) == 500
    assert RL.lots_to_close(1500, 500, D("0.5")) == 500 and RL.lots_to_close(7, 1, D("1")) == 7


def test_adp3_17_19_holding_period_and_no_second_engine():
    s = _eq_setup(hold=3, trail="trail-atr-v1 (1.5 × ATR2)")
    rules = RL.make_rules(s, 0)
    st0 = RL.start_state(s, rules, session=S1, warmup=[])
    rows = [H.bar(1000 + i, 1010 + 3 * i, 995 + 2 * i, 1005 + 2 * i, session=S1 + timedelta(days=i)) for i in range(3)]
    st, ref = st0, st0
    for i, r in enumerate(rows):
        x = RL.at_close(s, st, 0, r, r.day)
        ref, ex = XR.step(ref, {"date": r.day, "open": float(r.open), "high": float(r.high), "low": float(r.low),
                                "close": float(r.close)}, rules)
        assert (x.decision is None) == (ex is None)
        st = x.state
        assert st.stop == ref.stop and st.sessions_held == ref.sessions_held     # the manager adds no rule of its own
    assert x.decision.reason == C.CloseReason.TIME and x.decision.how == C.PriceHow.CLOSE


# ── D. closure and the books (integration) ───────────────────────────────────────────────────────────────────────

def test_adp3_35_41_42_share_closed_at_the_level_books_and_reconciles(pg_pool):
    async def go():
        k = H.key_eq()
        rows = {k: {S1: H.bar(1000, 1010, 995, 1005, session=S1), S2: H.bar(1004, 1006, 955, 958, prev=1005, session=S2)}}
        t, sim, acc, plan, gw = await one_sim(pg_pool, lambda a: eq_plan(a), rows)
        await sessions(gw, t, sim["simulation_id"], [S1, S2])
        f = await facts(pg_pool, plan["trade_id"])
        p, rec = f["pos"], f["recs"][0]
        assert p["status"] == "CLOSED" and p["lifecycle_state"] == "SETTLED" and p["close_reason"] == "stop"
        assert f["moves"] == ["ACTIVE_POSITION", "EXIT_PENDING", "CLOSED", "SETTLED"]
        assert (rec["reason"], rec["how"]) == ("stop", "level")
        close_fill = [x for x in f["fills"] if x["purpose"] == "CLOSE"][0]
        open_fill = [x for x in f["fills"] if x["purpose"] == "OPEN"][0]
        px = close_fill["price"]
        assert D("955") <= px <= D("960") - D("0.48") and (px / TICK) == (px / TICK).to_integral_value()
        assert close_fill["value_rs"] == px * 100 and close_fill["side"] == "SELL"
        gross = close_fill["value_rs"] - open_fill["value_rs"]
        assert rec["realized_gross_rs"] == gross == p["realized_gross_rs"] == f["ledger"]["REALIZED_PNL"]["realized"]
        assert f["ledger"]["MARGIN_RELEASED"]["risk"] == -D("4000.00")            # the plan's loss at the level, released
        v = f["v"]
        assert v.open_risk_rs == 0 and v.deployed_notional_rs == 0 and v.reserved_capital_rs == 0
        assert v.cash_balance_rs == D("1000000") + gross - open_fill["charges_rs"] - close_fill["charges_rs"]
        assert v.net_realized_rs == gross - open_fill["charges_rs"] - close_fill["charges_rs"] and v.unrealized_gross_rs == 0
        ok, bad = all_zero(f["checks"])
        assert ok, bad
        kinds = [k for k, _ in f["journal"]]
        assert kinds.index("FILL") < kinds.index("LIFECYCLE") < kinds.index("CLOSING_DECISION") < kinds.index("CLOSING_FILL") \
            < kinds.index("CLOSURE") < kinds.index("RECONCILIATION")
        assert not [s for _k, s in f["journal"] if ADVICE.search(s)]
    run(go())


def test_adp3_36_15_partial_objective_then_the_level_and_no_duplicate(pg_pool):
    async def go():
        k = H.key_eq()
        rows = {k: {S1: H.bar(1000, 1010, 995, 1005, session=S1), S2: H.bar(1010, 1061, 1001, 1050, session=S2),
                    S3: H.bar(1040, 1045, 955, 960, session=S3)}}
        t, sim, acc, plan, gw = await one_sim(pg_pool, lambda a: eq_plan(a, targets=[("1060", "0.5"), ("1100", "1")]), rows)
        await sessions(gw, t, sim["simulation_id"], [S1, S2])
        f = await facts(pg_pool, plan["trade_id"])
        assert f["pos"]["status"] == "OPEN" and f["pos"]["lifecycle_state"] == "PARTIAL_EXIT"
        assert f["legs"][0]["quantity"] == 50 and f["legs"][0]["closed_qty"] == 50 and f["legs"][0]["opened_qty"] == 100
        cf = [x for x in f["fills"] if x["purpose"] == "CLOSE"]
        assert len(cf) == 1 and cf[0]["price"] == D("1060") and cf[0]["spread_rs"] == 0 and cf[0]["slippage_rs"] == 0
        assert f["pos"]["open_risk_rs"] == D("2000.00")                            # risk recalculated: half left
        assert all_zero(f["checks"])[0]
        # the same session again: no second closing
        await settle.run_close(gw, tenant_id=t, simulation_id=sim["simulation_id"], session=S2, as_of=at(S2, 15, 30))
        assert len([x for x in (await facts(pg_pool, plan["trade_id"]))["fills"] if x["purpose"] == "CLOSE"]) == 1
        await sessions(gw, t, sim["simulation_id"], [S3])
        f = await facts(pg_pool, plan["trade_id"])
        assert f["pos"]["lifecycle_state"] == "SETTLED" and [r["reason"] for r in f["recs"]] == ["target", "stop"]
        assert f["pos"]["realized_gross_rs"] == sum((r["realized_gross_rs"] for r in f["recs"]), D("0"))
        assert f["moves"] == ["ACTIVE_POSITION", "EXIT_PENDING", "PARTIAL_EXIT", "EXIT_PENDING", "CLOSED", "SETTLED"]
        assert all_zero(f["checks"])[0]
    run(go())


def test_adp3_14_a_touch_of_the_objective_does_not_fill(pg_pool):
    async def go():
        k = H.key_eq()
        rows = {k: {S1: H.bar(1000, 1010, 995, 1005, session=S1), S2: H.bar(1010, 1060, 1001, 1050, session=S2)}}
        t, sim, acc, plan, gw = await one_sim(pg_pool, lambda a: eq_plan(a, targets=[("1060", "1")]), rows)
        await sessions(gw, t, sim["simulation_id"], [S1, S2])
        f = await facts(pg_pool, plan["trade_id"])
        assert f["pos"]["status"] == "OPEN" and not [x for x in f["fills"] if x["purpose"] == "CLOSE"]
    run(go())


def test_adp3_10_gap_through_the_level_fills_at_the_real_open(pg_pool):
    async def go():
        k = H.key_eq()
        rows = {k: {S1: H.bar(1000, 1010, 995, 1005, session=S1), S2: H.bar(950, 970, 940, 965, prev=1005, session=S2)}}
        t, sim, acc, plan, gw = await one_sim(pg_pool, lambda a: eq_plan(a), rows)
        await sessions(gw, t, sim["simulation_id"], [S1, S2])
        f = await facts(pg_pool, plan["trade_id"])
        rec = f["recs"][0]
        cf = [x for x in f["fills"] if x["purpose"] == "CLOSE"][0]
        assert (rec["how"], rec["gapped"], rec["trigger_price"]) == ("open", True, D("950"))
        assert cf["arrival_price"] == D("950") and D("940") <= cf["price"] < D("950")       # never at 960
        assert cf["sim_time"] == at(S2, 9, 15) and all_zero(f["checks"])[0]
    run(go())


def test_adp3_17_holding_period_closes_at_the_close(pg_pool):
    async def go():
        k = H.key_eq()
        rows = {k: {S1: H.bar(1000, 1010, 995, 1005, session=S1), S2: H.bar(1006, 1012, 1001, 1008, session=S2)}}
        t, sim, acc, plan, gw = await one_sim(pg_pool, lambda a: eq_plan(a, hold=2), rows)
        await sessions(gw, t, sim["simulation_id"], [S1, S2])
        f = await facts(pg_pool, plan["trade_id"])
        rec = f["recs"][0]
        cf = [x for x in f["fills"] if x["purpose"] == "CLOSE"][0]
        assert (rec["reason"], rec["how"]) == ("time", "close") and cf["arrival_price"] == D("1008")
        assert D("1001") <= cf["price"] < D("1008")
    run(go())


def test_adp3_29_40_volume_capped_closing_carries_to_the_next_open(pg_pool):
    async def go():
        k = H.key_eq()
        rows = {k: {S1: H.bar(1000, 1010, 995, 1005, session=S1), S2: H.bar(1004, 1006, 955, 958, units=500, session=S2),
                    S3: H.bar(957, 966, 950, 962, session=S3)}}
        t, sim, acc, plan, gw = await one_sim(pg_pool, lambda a: eq_plan(a), rows)
        await sessions(gw, t, sim["simulation_id"], [S1, S2])
        f = await facts(pg_pool, plan["trade_id"])
        assert f["legs"][0]["quantity"] == 50 and f["pos"]["lifecycle_state"] == "PARTIAL_EXIT"
        async with pg_pool.acquire() as c:
            pend = await c.fetchval("SELECT pending FROM autodesk.trade_exit_state WHERE trade_id=$1", plan["trade_id"])
        assert pend["qty"] == {"L1": 50} and pend["reason"] == "stop"
        await sessions(gw, t, sim["simulation_id"], [S3])
        f = await facts(pg_pool, plan["trade_id"])
        assert f["pos"]["lifecycle_state"] == "SETTLED" and [r["how"] for r in f["recs"]] == ["level", "open"]
        assert all_zero(f["checks"])[0]
    run(go())


def _fut_body(aid, *, inv="960", lots=1, lot=500, px="1010", sd=S1):
    leg = C.PlanLeg(leg_id="L1", kind=C.InstrumentKind.FUT, underlying="ACME", expiry=H.EXP, side=C.LegSide.LONG, lots=lots,
                    lot_size=lot, quantity=lots * lot, ref_price=D(px), ref_price_source="TEST DATA")
    b = H.eq_body(aid, sd=sd)
    return b.model_copy(update={"legs": [leg], "segment": C.Segment.FUTURES, "strategy_type": C.StrategyType.LONG_FUTURES,
                                "max_loss_rs": D("25000"), "capital_required_rs": D("75750"),
                                "margin_estimate": {"amount_rs": "75750", "fno": True},
                                "invalidation": {"underlying_level": inv}, "entry": {"order_type": "MARKET"},
                                "market_context": {"sector": "IT", "direction": "BULLISH"}})


def test_adp3_37_futures_closed_at_the_translated_level(pg_pool):
    async def go():
        ke, kf = H.key_eq(), H.key_fut()
        rows = {ke: {S1: H.bar(1000, 1005, 995, 1001, prev=1000, session=S1), S2: H.bar(1000, 1002, 950, 955, prev=1001, session=S2)},
                kf: {S1: H.bar(1010, 1015, 1005, 1011, prev=1010, lot=500, units=5_000_000, session=S1),
                     S2: H.bar(1010, 1012, 962, 966, prev=1011, lot=500, units=5_000_000, session=S2)}}
        t, sim, acc, plan, gw = await one_sim(pg_pool, _fut_body, rows)
        await sessions(gw, t, sim["simulation_id"], [S1, S2])
        f = await facts(pg_pool, plan["trade_id"])
        async with pg_pool.acquire() as c:
            xs = await c.fetchrow("SELECT trigger_key, trigger_basis, level_ratio, objectives FROM autodesk.trade_exit_state WHERE trade_id=$1",
                                  plan["trade_id"])
        assert xs["trigger_basis"] == "FUTURE_ROW_TRANSLATED" and xs["level_ratio"] == D("1.01")
        rec = f["recs"][0]
        assert rec["level"] == D("969.60") and rec["how"] == "level"
        cf = [x for x in f["fills"] if x["purpose"] == "CLOSE"][0]
        of = [x for x in f["fills"] if x["purpose"] == "OPEN"][0]
        gross = cf["value_rs"] - of["value_rs"]
        assert rec["realized_gross_rs"] == gross and f["ledger"]["REALIZED_PNL"]["cash"] == gross    # futures: cash by the result
        v = f["v"]
        assert v.used_margin_rs == 0 and v.deployed_notional_rs == 0
        assert v.cash_balance_rs == D("1000000") + gross - of["charges_rs"] - cf["charges_rs"]
        assert all_zero(f["checks"])[0]
    run(go())


def _spread_body(aid, *, direction="BULLISH", inv="960"):
    legs = [H.opt_leg("L1", "CE", "LONG", 1000, "30"), H.opt_leg("L2", "CE", "SHORT", 1100, "8")]
    b = H.spread_body(aid, legs, C.StrategyType.BULL_CALL_SPREAD, max_loss=23000, capital=23000)
    return b.model_copy(update={"invalidation": {"underlying_level": inv}, "targets": [C.TargetLevel(level=D("1080"))],
                                "market_context": {"sector": "IT", "direction": direction},
                                "entry": {"order_type": "LIMIT", "reference_price": "1000"}})


def _spread_rows(s2_und, s2_l1, s2_l2, extra=None):
    k1, k2, ke = H.key_opt("CE", 1000), H.key_opt("CE", 1100), H.key_eq()
    rows = {ke: {S1: H.bar(1000, 1005, 995, 1001, session=S1), S2: s2_und},
            k1: {S1: H.bar(30, 31, 29, 30.5, lot=500, units=2_000_000, session=S1), S2: s2_l1},
            k2: {S1: H.bar(8, 8.5, 7.5, 8.2, lot=500, units=2_000_000, session=S1), S2: s2_l2}}
    for k, v in (extra or {}).items():
        rows[k].update(v)
    return rows


def test_adp3_38_spread_closes_as_one_unit_at_its_legs_closes(pg_pool):
    async def go():
        rows = _spread_rows(H.bar(1000, 1001, 955, 958, session=S2), H.bar(29, 29, 12, 13, lot=500, units=2_000_000, session=S2),
                            H.bar(8, 8, 2, 2.5, lot=500, units=2_000_000, session=S2))
        t, sim, acc, plan, gw = await one_sim(pg_pool, _spread_body, rows)
        await sessions(gw, t, sim["simulation_id"], [S1, S2])
        f = await facts(pg_pool, plan["trade_id"])
        rec = f["recs"][0]
        assert rec["how"] == "close" and rec["reason"] == "stop" and len(rec["legs"]) == 2
        cf = {x["leg_id"]: x for x in f["fills"] if x["purpose"] == "CLOSE"}
        assert cf["L1"]["side"] == "SELL" and cf["L1"]["arrival_price"] == D("13") and cf["L1"]["price"] < D("13")
        assert cf["L2"]["side"] == "BUY" and cf["L2"]["arrival_price"] == D("2.5") and cf["L2"]["price"] > D("2.5")
        assert f["pos"]["lifecycle_state"] == "SETTLED" and all_zero(f["checks"])[0]
    run(go())


def test_adp3_38_one_leg_without_a_row_nothing_closes_and_it_waits(pg_pool):
    async def go():
        rows = _spread_rows(H.bar(1000, 1001, 955, 958, session=S2), H.bar(29, 29, 12, 13, lot=500, units=2_000_000, session=S2),
                            H.bar(8, 8, 2, 2.5, lot=500, units=2_000_000, traded=False, session=S2))
        t, sim, acc, plan, gw = await one_sim(pg_pool, _spread_body, rows)
        await sessions(gw, t, sim["simulation_id"], [S1, S2])
        f = await facts(pg_pool, plan["trade_id"])
        assert f["pos"]["status"] == "OPEN" and not [x for x in f["fills"] if x["purpose"] == "CLOSE"]
        assert any(fl["code"] == "CLOSE_BLOCKED_NO_DATA" for fl in f["pos"]["flags"])
        async with pg_pool.acquire() as c:
            assert (await c.fetchval("SELECT pending FROM autodesk.trade_exit_state WHERE trade_id=$1", plan["trade_id"]))["reason"] == "stop"
        assert all_zero(f["checks"])[0]
    run(go())


# ── E. expiry settlement ─────────────────────────────────────────────────────────────────────────────────────────

def _call_body(aid):
    leg = H.opt_leg("L1", "CE", "LONG", 1000, "30", lots=1)
    b = H.spread_body(aid, [leg], C.StrategyType.LONG_CALL, max_loss=15100, capital=15100)
    return b.model_copy(update={"market_context": {"sector": "IT", "direction": "NEUTRAL"}})


def test_adp3_45_48_settlement_at_expiry_and_missing_data(pg_pool):
    async def go():
        ke, k1 = H.key_eq(), H.key_opt("CE", 1000)
        E = H.EXP
        rows = {ke: {S1: H.bar(1000, 1005, 995, 1001, session=S1)},
                k1: {S1: H.bar(30, 31, 29, 30.5, lot=500, units=2_000_000, session=S1)}}
        t, sim, acc, plan, gw = await one_sim(pg_pool, _call_body, rows)
        await sessions(gw, t, sim["simulation_id"], [S1])
        # expiry day: no underlying row yet -> nothing assumed
        await settle.run_close(gw, tenant_id=t, simulation_id=sim["simulation_id"], session=E, as_of=at(E, 15, 30))
        f = await facts(pg_pool, plan["trade_id"])
        assert f["pos"]["status"] == "OPEN" and f["pos"]["lifecycle_state"] == "RECONCILIATION_REQUIRED"
        assert any(fl["code"] == "SETTLEMENT_DATA_MISSING" for fl in f["pos"]["flags"]) and not f["recs"]
        # the row lands: settled at intrinsic against the close
        rows[ke][E] = H.bar(1035, 1045, 1030, 1040, session=E)
        rows[k1][E] = H.bar(36, 46, 30, 40.2, lot=500, units=2_000_000, session=E)
        await settle.run_close(gw, tenant_id=t, simulation_id=sim["simulation_id"], session=E, as_of=at(E, 15, 31))
        f = await facts(pg_pool, plan["trade_id"])
        rec = f["recs"][0]
        assert (rec["reason"], rec["how"]) == ("expiry", "settlement") and rec["legs"][0]["price"] == "40.0000"
        assert rec["value_rs"] == D("20000.00") and not [x for x in f["fills"] if x["purpose"] == "CLOSE"]
        assert f["pos"]["lifecycle_state"] == "SETTLED" and all_zero(f["checks"])[0]
    run(go())


def test_adp3_46_worthless_leg_settles_at_zero_and_pays_its_closing_charges(pg_pool):
    async def go():
        ke, k1 = H.key_eq(), H.key_opt("CE", 1000)
        E = H.EXP
        rows = {ke: {S1: H.bar(1000, 1005, 995, 1001, session=S1), E: H.bar(990, 995, 980, 985, session=E)},
                k1: {S1: H.bar(30, 31, 29, 30.5, lot=500, units=2_000_000, session=S1)}}
        t, sim, acc, plan, gw = await one_sim(pg_pool, _call_body, rows)
        await sessions(gw, t, sim["simulation_id"], [S1])
        await settle.run_close(gw, tenant_id=t, simulation_id=sim["simulation_id"], session=E, as_of=at(E, 15, 30))
        f = await facts(pg_pool, plan["trade_id"])
        rec = f["recs"][0]
        assert rec["value_rs"] == 0 and rec["charges_rs"] > 0 and f["pos"]["lifecycle_state"] == "SETTLED"
        assert all_zero(f["checks"])[0]
    run(go())


# ── F. limits ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_adp3_50_52_53_daily_loss_and_drawdown_act_on_pnl(pg_pool):
    async def go():
        k = H.key_eq()
        rows = {k: {S1: H.bar(1000, 1001, 935, 940, session=S1), S2: H.bar(941, 950, 930, 945, session=S2)}}
        pol = H.wide_policy(max_drawdown_pct=D("2"))
        t, sim, acc, plan, gw = await one_sim(pg_pool, lambda a: eq_plan(a, shares=40, inv="900"), rows, capital_="100000",
                                              policy=pol)
        await sessions(gw, t, sim["simulation_id"], [S1])
        async with pg_pool.acquire() as c:
            cur = await limits.current(c, tenant_id=t, account_id=acc["account_id"], session=S2)
            ev = [r["payload"] for r in await c.fetch("SELECT payload FROM autodesk.events WHERE account_id=$1 AND event_type='LIMIT_BREACHED'",
                                                     acc["account_id"])]
            ctl = await c.fetchrow("SELECT * FROM autodesk.lifecycle_controls WHERE scope=$1", acc["account_id"])
        assert {e["limit"] for e in ev} == {"daily", "drawdown"} and ctl["control"] == "SUSPEND_ACCOUNT" and ctl["active"]
        codes = {b["code"] for b in cur["blocks"]}
        assert "DAILY_LOSS_LIMIT" in codes
        # a new plan the next session is refused; the open position still follows its rules
        body2 = H.eq_body(acc["account_id"], sym="ACME", shares=10, sd=S2)
        async with pg_pool.acquire() as c:
            pol_row = await store.get_policy(c, t, acc["policy_id"])
        plan2 = await H.make_approved_plan(pg_pool, t, acc, pol_row, body2)
        it = await gw.create_intent(tenant_id=t, trade_id=plan2["trade_id"], plan_version=1, as_of=at(S2, 9, 0),
                                    approval_id=plan2["approval_id"])
        assert it["status"] == "REFUSED" and {"DAILY_LOSS_LIMIT", "ACCOUNT_SUSPENDED"} <= set(it["refusal_codes"])
        # the risk engine judges the same numbers (no longer SKIPPED)
        from autodesk.control.book import load_book
        async with pg_pool.acquire() as c:
            book = await load_book(c, t, acc["account_id"], at(S2, 9, 0))
        assert book.loss_limits["daily_loss"] and book.loss_limits["drawdown"]
    run(go())


# ── G. amend, controls, close requests, UNKNOWN ──────────────────────────────────────────────────────────────────

def test_adp3_55_56_amend_only_towards_less_risk(pg_pool):
    async def go():
        k = H.key_eq()
        rows = {k: {S1: H.bar(1010, 1020, 1008, 1015, session=S1)}}
        t, sim, acc, plan, gw = await one_sim(pg_pool, lambda a: eq_plan(a, zone_high="1001"), rows)
        await settle.run_open(gw, tenant_id=t, simulation_id=sim["simulation_id"], session=S1, as_of=at(S1, 9, 15))
        async with pg_pool.acquire() as c:
            oid = await c.fetchval("SELECT order_id FROM autodesk.trade_orders WHERE trade_id=$1", plan["trade_id"])
        for bad in ({"lots": 101}, {"limit_price": "1002"}):
            with pytest.raises(store.Conflict, match="AMEND_RAISES_RISK"):
                await gw.amend(tenant_id=t, order_id=oid, changes=bad, as_of=at(S1, 9, 20))
        o = await gw.amend(tenant_id=t, order_id=oid, changes={"lots": 60, "limit_price": "999.50"}, as_of=at(S1, 9, 20))
        assert (o["state"], o["quantity"], o["limit_price"]) == ("OPEN", 60, D("999.50"))
        async with pg_pool.acquire() as c:
            hist = [r["to_state"] for r in await c.fetch("SELECT to_state FROM autodesk.trade_order_events WHERE order_id=$1 ORDER BY seq", oid)]
        assert hist[-2:] == ["MODIFY_PENDING", "OPEN"]
    run(go())


def test_adp3_59_reduce_only_closes_at_the_next_open_and_refuses_new_intents(pg_pool):
    async def go():
        k = H.key_eq()
        rows = {k: {S1: H.bar(1000, 1010, 995, 1005, session=S1), S2: H.bar(1006, 1012, 1001, 1008, session=S2)}}
        t, sim, acc, plan, gw = await one_sim(pg_pool, lambda a: eq_plan(a), rows)
        await sessions(gw, t, sim["simulation_id"], [S1])
        async with pg_pool.acquire() as c:
            async with c.transaction():
                r = await controls.set_control(c, tenant_id=t, control=C.LifecycleControl.REDUCE_ONLY, scope=acc["account_id"],
                                               active=True, reason="test", actor="test")
                again = await controls.set_control(c, tenant_id=t, control=C.LifecycleControl.REDUCE_ONLY,
                                                   scope=acc["account_id"], active=True, reason="test", actor="test")
        assert r["changed"] and not again["changed"]
        await sessions(gw, t, sim["simulation_id"], [S2])
        f = await facts(pg_pool, plan["trade_id"])
        assert f["recs"][0]["reason"] == "risk_control" and f["recs"][0]["how"] == "open" and f["pos"]["lifecycle_state"] == "SETTLED"
    run(go())


def test_adp3_57_suspended_modifications_freeze_the_trail_not_the_level():
    s = _eq_setup(trail="trail-atr-v1 (1 × ATR2)")
    st = RL.start_state(s, RL.make_rules(s, 0), session=S1, warmup=[{"high": 1010, "low": 990, "close": 1000},
                                                                       {"high": 1012, "low": 992, "close": 1005}])
    up = H.bar(1010, 1100, 1008, 1095, session=S2)
    assert RL.at_close(s, st, 0, up, S2).state.stop > 960                 # the trail raises the level
    frozen = RL.at_close(s, st, 0, up, S2, freeze_trail=True)
    assert frozen.state.stop == 960.0                                      # frozen: the level in force stays
    assert RL.at_close(s, st, 0, H.bar(1000, 1001, 955, 958, session=S2), S2, freeze_trail=True).decision.reason == C.CloseReason.STOP


class _BrokenAdapter(ad.SimulationPaperAdapter):
    """TEST DOUBLE: raises on submit, so the order is left UNKNOWN."""
    async def submit(self, order, idempotency_key):
        raise RuntimeError("paper venue unreachable (test)")


def test_adp3_62_unknown_order_reconciled_never_resubmitted(pg_pool):
    async def go():
        k = H.key_eq()
        rows = {k: {S1: H.bar(1000, 1010, 995, 1005, session=S1)}}
        adapter = _BrokenAdapter(H.FrozenSessionBars(rows), DEFAULT_PARAMS)
        t, sim, acc, plan, gw = await one_sim(pg_pool, lambda a: eq_plan(a), rows, adapter=adapter)
        await gw.submit(tenant_id=t, intent_id=(await _intent(pg_pool, plan["trade_id"]))["intent_id"], as_of=at(S1, 9, 15))
        async with pg_pool.acquire() as c:
            assert await c.fetchval("SELECT state FROM autodesk.trade_orders WHERE trade_id=$1", plan["trade_id"]) == "UNKNOWN"
        await settle.run_open(gw, tenant_id=t, simulation_id=sim["simulation_id"], session=S1, as_of=at(S1, 9, 15))
        async with pg_pool.acquire() as c:
            o = await c.fetchrow("SELECT state, order_id FROM autodesk.trade_orders WHERE trade_id=$1", plan["trade_id"])
            reason = await c.fetchval("SELECT reason FROM autodesk.trade_order_events WHERE order_id=$1 ORDER BY seq DESC LIMIT 1",
                                      o["order_id"])
            it = await _intent(pg_pool, plan["trade_id"])
            res = await c.fetchrow("SELECT status FROM autodesk.capital_reservations WHERE trade_id=$1", plan["trade_id"])
            v = await capital.balances(c, t, acc["account_id"])
        assert o["state"] == "EXPIRED" and "never worked" in reason and it["status"] == "COMPLETED"
        assert res["status"] in ("RELEASED", "EXPIRED") and v.reserved_capital_rs == 0
    run(go())


async def _intent(pool, trade_id):
    async with pool.acquire() as c:
        return dict(await c.fetchrow("SELECT * FROM autodesk.execution_intents WHERE trade_id=$1 AND action='ENTER'", trade_id))


# ── H. live path (FakeQuotes: TEST DOUBLE) ───────────────────────────────────────────────────────────────────────

@pytest.fixture()
def cal2026():
    saved = calendar._HOLIDAYS.get(2026)
    calendar.set_holidays(2026, {})
    yield
    if saved is not None:
        calendar.set_holidays(2026, saved)
    else:
        calendar._HOLIDAYS.pop(2026, None)


def test_adp3_65_66_live_closing_only_from_a_fresh_quote(pg_pool, cal2026):
    async def go():
        T = datetime(2026, 11, 5, 10, 30, tzinfo=IST).astimezone(timezone.utc)
        t = H.tenant()
        acc, pol = await H.make_desk_account(pg_pool, t)
        plan = await H.make_approved_plan(pg_pool, t, acc, pol, eq_plan(acc["account_id"]))
        fq = H.FakeQuotes()
        gw = ExecutionGateway(pg_pool, live=ad.LivePaperAdapter(fq, DEFAULT_PARAMS), lifecycle=LifecycleManager(pg_pool))
        await gw.create_intent(tenant_id=t, trade_id=plan["trade_id"], plan_version=1, as_of=T, approval_id=plan["approval_id"])
        k = H.key_eq()
        fq.answer = QuoteAnswer(quotes={k: H.quote(k, "ACME", "1000", bid=999.9, ask=1000.1, at=T - timedelta(seconds=5))})
        await settle.live_tick(gw, tenant_id=t, now=T)                      # opens
        T2 = T + timedelta(seconds=5)
        fq.answer = QuoteAnswer(quotes={k: H.quote(k, "ACME", "1000", bid=999.9, ask=1000.1, at=T2)})
        await settle.live_tick(gw, tenant_id=t, now=T2)                     # activates (managed from the next session)
        # a stale quote below the level: no closing
        T3 = T + timedelta(minutes=10)
        fq.answer = QuoteAnswer(quotes={k: H.quote(k, "ACME", "955", bid=954.9, ask=955.1, at=T3 - timedelta(minutes=5))})
        await settle.live_tick(gw, tenant_id=t, now=T3)
        f = await facts(pg_pool, plan["trade_id"])
        assert f["pos"]["status"] == "OPEN" and not f["recs"]
        # a fresh one: closed from the quote's bid
        T4 = T3 + timedelta(seconds=5)
        fq.answer = QuoteAnswer(quotes={k: H.quote(k, "ACME", "955", bid=954.9, ask=955.1, at=T4)})
        await settle.live_tick(gw, tenant_id=t, now=T4)
        f = await facts(pg_pool, plan["trade_id"])
        rec = f["recs"][0]
        assert (rec["reason"], rec["how"]) == ("stop", "quote") and f["pos"]["lifecycle_state"] == "SETTLED"
        cf = [x for x in f["fills"] if x["purpose"] == "CLOSE"][0]
        assert cf["price"] <= D("954.9") and "live quote" in cf["price_source"] and all_zero(f["checks"])[0]
    run(go())


# ── I. determinism, results ──────────────────────────────────────────────────────────────────────────────────────

def test_adp3_79_30_same_seed_same_fingerprint_other_seed_differs(pg_pool):
    async def go():
        k = H.key_eq()
        rows = {k: {S1: H.bar(1000, 1010, 995, 1005, session=S1), S2: H.bar(1004, 1006, 955, 958, session=S2)}}
        fps, prices = [], []
        for seed in (7, 7, 8):
            t, sim, acc, plan, gw = await one_sim(pg_pool, lambda a: eq_plan(a), rows, seed=seed)
            await sessions(gw, t, sim["simulation_id"], [S1, S2])
            async with pg_pool.acquire() as c:
                es = await reports.execution_summary(c, t, sim["simulation_id"])
            fps.append(es["fingerprint"])
            prices.append((await facts(pg_pool, plan["trade_id"]))["recs"][0]["legs"][0]["price"])
            assert es["closed_trades"] == 1 and es["exits_by_reason"] == {"stop": 1} and es["reconciliation_runs"]["failed"] == 0
        assert fps[0] == fps[1] and fps[0] != fps[2] and prices[0] == prices[1]
    run(go())


def test_adp3_78_no_lifecycle_is_phase_2(pg_pool):
    async def go():
        k = H.key_eq()
        rows = {k: {S1: H.bar(1000, 1010, 995, 1005, session=S1), S2: H.bar(1004, 1006, 955, 958, session=S2)}}
        t, sim, acc, plan, gw = await one_sim(pg_pool, lambda a: eq_plan(a), rows, lifecycle=False)
        await sessions(gw, t, sim["simulation_id"], [S1, S2])
        f = await facts(pg_pool, plan["trade_id"])
        assert f["pos"]["status"] == "OPEN" and not f["recs"]
    run(go())


# ── J. guards ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_adp3_85_no_literal_in_the_lifecycle_code_uses_an_advice_word():
    pkg = Path(__file__).resolve().parents[2] / "autodesk"
    hits = []
    for f in sorted((pkg / "lifecycle").glob("*.py")) + [pkg / "routers" / "lifecycle.py"]:
        tree = ast.parse(f.read_text())
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs \
                    and n.value not in ("BUY", "SELL", "buy", "sell") and not n.value.startswith("/"):
                m = ADVICE.search(n.value)
                if m:
                    hits.append(f"{f.name}:{n.lineno}: {m.group(0)!r} in {n.value!r}")
    assert hits == [], hits


def test_adp3_88_results_text_says_positions_close():
    from autodesk.simulator.manager import PHASE3_LIMITATIONS
    text = " ".join(PHASE3_LIMITATIONS)
    assert "positions stay open" not in text and "not enforced" not in text and "managed from their fills to closure" in text
