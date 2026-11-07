"""AD-P2-03, 20..29, 33, 60, 61: intents, controls, and a simulation from approval to fill. TEST DATA, not real market data."""
from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest

from autodesk import contracts as C
from autodesk import store
from autodesk.execution import capital, settle
from tests.autodesk import p2_harness as H
from tests.autodesk.conftest import run

D = Decimal


async def setup(pool, *, shares=100, px="1000", rows=None, policy=None, capital_rs="1000000", **body_kw):
    t = H.tenant()
    sim, acc, pol = await H.make_simulation(pool, t, capital=capital_rs, policy=policy)
    body = H.eq_body(acc["account_id"], shares=shares, px=px, **body_kw)
    plan = await H.make_approved_plan(pool, t, acc, pol, body)
    gw = H.sim_gateway(pool, rows if rows is not None else {H.key_eq(): H.bar(px, units=1_000_000)})
    return t, sim, acc, pol, body, plan, gw


async def intent_of(pool, t, tid):
    async with pool.acquire() as c:
        return dict(await c.fetchrow("SELECT * FROM autodesk.execution_intents WHERE tenant_id=$1 AND trade_id=$2 "
                                     "ORDER BY created_at LIMIT 1", t, tid))


def test_adp2_20_intent_validated_with_controls_orders_and_reservation(pg_pool):
    async def go():
        t, sim, acc, pol, body, plan, gw = await setup(pg_pool)
        it = await gw.create_intent(tenant_id=t, trade_id=plan["trade_id"], plan_version=1, as_of=H.AT_0900,
                                    approval_id=plan["approval_id"])
        assert it["status"] == "VALIDATED" and it["adapter"] == "PAPER_SIM" and it["execution_mode"] == "SIMULATION"
        assert it["plan_hash"] == C.plan_hash(body) and it["approval_id"] == plan["approval_id"]
        names = {k["name"] for k in it["controls"]}
        assert {"account_active", "approval_exists", "plan_hash", "scope", "entries_not_stopped", "funds_and_limits"} <= names
        assert all(k["outcome"] == "PASS" for k in it["controls"])
        async with pg_pool.acquire() as c:
            os_ = [dict(r) for r in await c.fetch("SELECT * FROM autodesk.trade_orders WHERE intent_id=$1", it["intent_id"])]
            res = await capital.get_reservation(c, t, it["reservation_id"])
            v = await capital.balances(c, t, acc["account_id"])
            st = (await store.get_plan(c, t, plan["trade_id"]))["status"]
        assert len(os_) == 1 and os_[0]["state"] == "VALIDATED" and os_[0]["order_type"] == "LIMIT"
        assert res["status"] == "ACTIVE" and v.reserved_capital_rs == res["amount_rs"] > D("100000") and st == "EXECUTING"
        # same key again: the same intent, no second reservation or order
        again = await gw.create_intent(tenant_id=t, trade_id=plan["trade_id"], plan_version=1, as_of=H.AT_0900)
        assert again["intent_id"] == it["intent_id"]
    run(go())


def test_adp2_21_five_concurrent_calls_one_intent(pg_pool):
    async def go():
        t, sim, acc, pol, body, plan, gw = await setup(pg_pool)
        res = await asyncio.gather(*[gw.create_intent(tenant_id=t, trade_id=plan["trade_id"], plan_version=1, as_of=H.AT_0900,
                                                      approval_id=plan["approval_id"]) for _ in range(5)])
        assert len({r["intent_id"] for r in res}) == 1
        async with pg_pool.acquire() as c:
            n_res = await c.fetchval("SELECT count(*) FROM autodesk.capital_reservations WHERE trade_id=$1", plan["trade_id"])
            n_ord = await c.fetchval("SELECT count(*) FROM autodesk.trade_orders WHERE trade_id=$1", plan["trade_id"])
        assert n_res == 1 and n_ord == 1
    run(go())


@pytest.mark.parametrize("case,code", [
    ("hash", "PLAN_HASH_MISMATCH"), ("no_approval", "NO_APPROVAL"), ("expired", "APPROVAL_EXPIRED"),
    ("no_pass", "NO_PASS_ASSESSMENT"), ("suspended", "ACCOUNT_NOT_ACTIVE"), ("research", "MODE_NOT_ALLOWED"),
    ("policy", "POLICY_CHANGED"), ("after_open", "SESSION_PHASE_PASSED"), ("short_fut", "STRATEGY_NOT_ALLOWED"),
])
def test_adp2_22_to_29_every_refusal_keeps_its_row(pg_pool, case, code):
    async def go():
        t = H.tenant()
        sim, acc, pol = await H.make_simulation(pg_pool, t)
        body = H.eq_body(acc["account_id"])
        kw, call = {}, {}
        if case == "no_approval":
            kw["approved"] = False
        if case == "expired":
            kw["approval_expires"] = H.AT_0900 - timedelta(minutes=1)
        if case == "no_pass":
            kw["verdict"] = "FAIL"
        if case == "policy":
            kw["policy_version"] = 7
        plan = await H.make_approved_plan(pg_pool, t, acc, pol, body, **kw)
        if case == "hash":
            call["caller_plan_hash"] = "0" * 64
        if case == "suspended":
            async with pg_pool.acquire() as c:
                await c.execute("UPDATE autodesk.accounts SET status='SUSPENDED' WHERE account_id=$1", acc["account_id"])
        if case == "research":
            async with pg_pool.acquire() as c:
                await c.execute("UPDATE autodesk.accounts SET operating_mode='RESEARCH' WHERE account_id=$1", acc["account_id"])
        if case == "short_fut":
            fut = C.PlanLeg(leg_id="L1", kind=C.InstrumentKind.FUT, underlying="ACME", expiry=H.EXP, side=C.LegSide.SHORT,
                            lots=1, lot_size=500, quantity=500, ref_price=D("1000"), ref_price_source="TEST DATA")
            body2 = body.model_copy(update={"legs": [fut], "segment": C.Segment.FUTURES,
                                            "strategy_type": C.StrategyType.LONG_FUTURES})
            plan = await H.make_approved_plan(pg_pool, t, acc, pol, body2)
        gw = H.sim_gateway(pg_pool, {H.key_eq(): H.bar("1000")})
        at = H.AT_0915 + timedelta(minutes=1) if case == "after_open" else H.AT_0900
        it = await gw.create_intent(tenant_id=t, trade_id=plan["trade_id"], plan_version=1, as_of=at,
                                    approval_id=plan["approval_id"], **call)
        assert it["status"] == "REFUSED" and code in it["refusal_codes"], it["refusal_codes"]
        async with pg_pool.acquire() as c:
            n_ord = await c.fetchval("SELECT count(*) FROM autodesk.trade_orders WHERE intent_id=$1", it["intent_id"])
            n_res = await c.fetchval("SELECT count(*) FROM autodesk.capital_reservations WHERE trade_id=$1", plan["trade_id"])
            st = (await store.get_plan(c, t, plan["trade_id"]))["status"]
            ev = await c.fetchval("SELECT count(*) FROM autodesk.events WHERE correlation_id=$1 AND event_type="
                                  "'EXECUTION_INTENT_REFUSED'", plan["trade_id"])
        assert n_ord == 0 and n_res == 0 and st == "EXECUTION_REFUSED" and ev == 1
    run(go())


def test_adp2_23_newer_plan_version_is_stale(pg_pool):
    async def go():
        t, sim, acc, pol, body, plan, gw = await setup(pg_pool)
        async with pg_pool.acquire() as c:
            async with c.transaction():
                await c.execute("UPDATE autodesk.trade_plans SET status='AWAITING_APPROVAL' WHERE trade_id=$1", plan["trade_id"])
                await store.revise_plan(c, tenant_id=t, trade_id=plan["trade_id"], body=body.model_copy(update={"thesis": "v2"}),
                                        created_by="test", reason="revised")
        it = await gw.create_intent(tenant_id=t, trade_id=plan["trade_id"], plan_version=1, as_of=H.AT_0900)
        assert it["status"] == "REFUSED" and "PLAN_VERSION_STALE" in it["refusal_codes"]
    run(go())


def test_adp2_27_stop_new_entries_on_the_desk_not_in_simulations(pg_pool):
    async def go():
        t, sim, acc, pol, body, plan, gw = await setup(pg_pool)
        async with pg_pool.acquire() as c:
            async with c.transaction():
                await store.set_desk_control(c, tenant_id=t, control=C.DeskControl.STOP_NEW_ENTRIES, active=True,
                                             reason="test", actor="u")
        it = await gw.create_intent(tenant_id=t, trade_id=plan["trade_id"], plan_version=1, as_of=H.AT_0900)
        assert it["status"] == "VALIDATED"                       # a simulation of a past session is not affected
    run(go())


def test_adp2_03_60_simulation_from_approval_to_fill(pg_pool):
    async def go():
        t, sim, acc, pol, body, plan, gw = await setup(pg_pool, rows={H.key_eq(): H.bar("1000", "1012", "995", "1008")})
        it = await gw.create_intent(tenant_id=t, trade_id=plan["trade_id"], plan_version=1, as_of=H.AT_0900,
                                    approval_id=plan["approval_id"])
        assert it["status"] == "VALIDATED"
        out = await settle.run_open(gw, tenant_id=t, simulation_id=sim["simulation_id"], session=H.SD, as_of=H.AT_0915)
        assert out["submitted"] == 1 and out["filled_orders"] == 1
        async with pg_pool.acquire() as c:
            o = dict(await c.fetchrow("SELECT * FROM autodesk.trade_orders WHERE trade_id=$1", plan["trade_id"]))
            f = dict(await c.fetchrow("SELECT * FROM autodesk.trade_fills WHERE trade_id=$1", plan["trade_id"]))
            pos = dict(await c.fetchrow("SELECT * FROM autodesk.trade_positions WHERE trade_id=$1", plan["trade_id"]))
            v = await capital.balances(c, t, acc["account_id"])
            hist = [r["to_state"] for r in await c.fetch("SELECT to_state FROM autodesk.trade_order_events WHERE order_id=$1 "
                                                         "ORDER BY seq", o["order_id"])]
            st = (await store.get_plan(c, t, plan["trade_id"]))["status"]
            intent = dict(await c.fetchrow("SELECT * FROM autodesk.execution_intents WHERE intent_id=$1", it["intent_id"]))
        assert o["state"] == "FILLED" and o["filled_qty"] == 100 and f["fill_kind"] == "SIMULATED"
        assert f["price"] >= D("1000") and f["price"] <= D("1002")        # open + half spread + slippage, on the tick
        assert hist == ["CREATED", "VALIDATED", "SUBMITTED", "ACKNOWLEDGED", "OPEN", "FILLED"]
        assert pos["status"] == "OPEN" and pos["open_risk_rs"] == D("4000.00") and st == "EXECUTED"
        assert intent["status"] == "COMPLETED" and intent["result"] == "FILLED"
        value = f["price"] * 100
        assert v.cash_balance_rs == D("1000000") - value - f["charges_rs"]
        assert v.deployed_notional_rs == value and v.used_margin_rs == 0 and v.reserved_capital_rs == 0
        assert v.open_risk_rs == D("4000.00") and v.pending_risk_rs == 0 and v.fees_rs == f["charges_rs"]
        assert v.reconciliation()["difference_rs"] == 0
    run(go())


def test_adp2_61_limit_never_reached_expires_and_releases(pg_pool):
    async def go():
        # session trades 1010..1020: the 1000 plan's limit (≤ zone_high 1001) is not reached
        t, sim, acc, pol, body, plan, gw = await setup(pg_pool, rows={H.key_eq(): H.bar("1010", "1020", "1008", "1015")},
                                                       zone_high="1001")
        it = await gw.create_intent(tenant_id=t, trade_id=plan["trade_id"], plan_version=1, as_of=H.AT_0900)
        assert it["status"] == "VALIDATED"
        out = await settle.run_open(gw, tenant_id=t, simulation_id=sim["simulation_id"], session=H.SD, as_of=H.AT_0915)
        assert out["resting"] == 1 and out["filled_orders"] == 0
        out = await settle.run_close(gw, tenant_id=t, simulation_id=sim["simulation_id"], session=H.SD, as_of=H.AT_1530)
        assert out["expired_orders"] == 1
        async with pg_pool.acquire() as c:
            o = dict(await c.fetchrow("SELECT * FROM autodesk.trade_orders WHERE trade_id=$1", plan["trade_id"]))
            res = await capital.get_reservation(c, t, it["reservation_id"])
            v = await capital.balances(c, t, acc["account_id"])
            st = (await store.get_plan(c, t, plan["trade_id"]))["status"]
        assert o["state"] == "EXPIRED" and o["attempts"] >= 1 and "LIMIT_NOT_REACHED" in (o["last_no_fill_reason"] or "")
        assert res["status"] == "EXPIRED" and v.available_buying_power_rs == D("1000000.00") and st == "EXPIRED"
    run(go())
