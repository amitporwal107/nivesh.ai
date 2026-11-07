"""AD-P2-24..31, 76: the remaining controls and the live basket. TEST DATA / TEST DOUBLES, not real market data."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from autodesk import contracts as C
from autodesk import store
from autodesk.execution import adapters as ad
from autodesk.execution import capital, orders, settle
from autodesk.execution import fill_model as fm
from autodesk.execution.gateway import ExecutionGateway
from autodesk.market.live_quotes import QuoteAnswer
from tests.autodesk import p2_harness as H
from tests.autodesk.conftest import run
from tests.autodesk.test_p2_live import KEY, T1030, fresh
from tests.autodesk.test_p2_products import debit_spread

D = Decimal


async def sim_intent(pool, *, body_over=None, **plan_kw):
    t = H.tenant()
    sim, acc, pol = await H.make_simulation(pool, t)
    body = H.eq_body(acc["account_id"])
    scope_body = body_over(body) if body_over else None
    plan = await H.make_approved_plan(pool, t, acc, pol, body, scope_body=scope_body, **plan_kw)
    gw = H.sim_gateway(pool, {H.key_eq(): H.bar("1000")})
    return t, sim, acc, pol, body, plan, gw


def test_adp2_24_approval_of_another_version_is_no_approval(pg_pool):
    async def go():
        t, sim, acc, pol, body, plan, gw = await sim_intent(pg_pool)
        async with pg_pool.acquire() as c:
            async with c.transaction():
                await c.execute("UPDATE autodesk.trade_plans SET status='AWAITING_APPROVAL' WHERE trade_id=$1", plan["trade_id"])
                await store.revise_plan(c, tenant_id=t, trade_id=plan["trade_id"], body=body.model_copy(update={"thesis": "v2"}),
                                        created_by="test", reason="revised")
                await store.set_plan_status(c, tenant_id=t, trade_id=plan["trade_id"], status=C.PlanStatus.APPROVED)
        it = await gw.create_intent(tenant_id=t, trade_id=plan["trade_id"], plan_version=2, as_of=H.AT_0900)
        assert it["status"] == "REFUSED" and "NO_APPROVAL" in it["refusal_codes"]
    run(go())


def test_adp2_25_plan_outside_the_approved_scope(pg_pool):
    async def go():
        small = lambda b: b.model_copy(update={"legs": [b.legs[0].model_copy(update={"lots": 10, "quantity": 10})]})
        t, sim, acc, pol, body, plan, gw = await sim_intent(pg_pool, body_over=small)
        it = await gw.create_intent(tenant_id=t, trade_id=plan["trade_id"], plan_version=1, as_of=H.AT_0900)
        scope = next(k for k in it["controls"] if k["name"] == "scope")
        assert it["status"] == "REFUSED" and "SCOPE_EXCEEDED" in it["refusal_codes"] and "lots" in scope["detail"] and "notional" in scope["detail"]
    run(go())


def test_adp2_26_account_mode_changed_since_the_plan_began(pg_pool):
    async def go():
        t, sim, acc, pol, body, plan, gw = await sim_intent(pg_pool, began_mode="ASSISTED")
        it = await gw.create_intent(tenant_id=t, trade_id=plan["trade_id"], plan_version=1, as_of=H.AT_0900)
        assert it["status"] == "REFUSED" and "ACCOUNT_MODE_CHANGED" in it["refusal_codes"]
    run(go())


def test_adp2_28_same_plan_version_under_another_key_is_a_duplicate(pg_pool):
    async def go():
        t, sim, acc, pol, body, plan, gw = await sim_intent(pg_pool)
        async with pg_pool.acquire() as c:
            await c.execute("""INSERT INTO autodesk.execution_intents (intent_id, tenant_id, account_id, simulation_id, trade_id, plan_version,
                                   execution_mode, adapter, action, session_date, status, idempotency_key)
                               VALUES ('INT-other', $1, $2, $3, $4, 1, 'SIMULATION', 'PAPER_SIM', 'ENTER', $5, 'VALIDATED', 'another-key')""",
                            t, acc["account_id"], sim["simulation_id"], plan["trade_id"], H.SD)
        it = await gw.create_intent(tenant_id=t, trade_id=plan["trade_id"], plan_version=1, as_of=H.AT_0900)
        assert it["status"] == "REFUSED" and "DUPLICATE_INTENT" in it["refusal_codes"]
    run(go())


def test_adp2_30_policy_changed_between_intent_and_open(pg_pool):
    async def go():
        t, sim, acc, pol, body, plan, gw = await sim_intent(pg_pool)
        it = await gw.create_intent(tenant_id=t, trade_id=plan["trade_id"], plan_version=1, as_of=H.AT_0900)
        assert it["status"] == "VALIDATED"
        async with pg_pool.acquire() as c:
            async with c.transaction():
                await store.add_policy_version(c, tenant_id=t, policy_id=pol["policy_id"], body=H.wide_policy().model_dump(mode="json"),
                                               created_by="test", reason="tightened")
        out = await settle.run_open(gw, tenant_id=t, simulation_id=sim["simulation_id"], session=H.SD, as_of=H.AT_0915)
        async with pg_pool.acquire() as c:
            o = dict(await c.fetchrow("SELECT * FROM autodesk.trade_orders WHERE trade_id=$1", plan["trade_id"]))
            res = await capital.get_reservation(c, t, it["reservation_id"])
            row = dict(await c.fetchrow("SELECT * FROM autodesk.execution_intents WHERE intent_id=$1", it["intent_id"]))
            nf = await c.fetchval("SELECT count(*) FROM autodesk.trade_fills WHERE trade_id=$1", plan["trade_id"])
        assert out["rejected"] == 1 and o["state"] == "REJECTED" and o["reject_code"] == "POLICY_CHANGED" and nf == 0
        assert res["status"] == "RELEASED" and row["status"] == "REFUSED"
    run(go())


def test_adp2_27_desk_stop_new_entries_at_intent_and_between_intent_and_submission(pg_pool):
    async def go():
        t = H.tenant()
        acc, pol = await H.make_desk_account(pg_pool, t)
        fq = H.FakeQuotes()
        gw = ExecutionGateway(pg_pool, live=ad.LivePaperAdapter(fq, fm.DEFAULT_PARAMS))
        p1 = await H.make_approved_plan(pg_pool, t, acc, pol, H.eq_body(acc["account_id"]))
        p2 = await H.make_approved_plan(pg_pool, t, acc, pol, H.eq_body(acc["account_id"]))
        it1 = await gw.create_intent(tenant_id=t, trade_id=p1["trade_id"], plan_version=1, as_of=T1030)
        assert it1["status"] == "VALIDATED"
        async with pg_pool.acquire() as c:
            async with c.transaction():
                await store.set_desk_control(c, tenant_id=t, control=C.DeskControl.STOP_NEW_ENTRIES, active=True, reason="halt", actor="u")
        # activated between intent and submission: refused at submission, the reservation is released
        sub = await gw.submit(tenant_id=t, intent_id=it1["intent_id"], as_of=T1030)
        assert sub["status"] == "REFUSED" and "ENTRIES_STOPPED" in sub["refusal_codes"]
        async with pg_pool.acquire() as c:
            res = await capital.get_reservation(c, t, it1["reservation_id"])
            o = dict(await c.fetchrow("SELECT * FROM autodesk.trade_orders WHERE intent_id=$1", it1["intent_id"]))
        assert res["status"] == "RELEASED" and o["state"] == "REJECTED"
        # active at intent time
        it2 = await gw.create_intent(tenant_id=t, trade_id=p2["trade_id"], plan_version=1, as_of=T1030)
        assert it2["status"] == "REFUSED" and "ENTRIES_STOPPED" in it2["refusal_codes"]
    run(go())


def test_adp2_31_tick_and_collar_are_checked_on_the_order_spec():
    spec = {"legs": [{"leg_id": "L1", "quantity": 100, "lot_size": 1, "limit_price": "1000.03", "ref_price": "1000", "kind": "EQ"},
                     {"leg_id": "L2", "quantity": 500, "lot_size": 500, "limit_price": "1100.00", "ref_price": "1000", "kind": "FUT"},
                     {"leg_id": "L3", "quantity": 501, "lot_size": 500, "limit_price": None, "ref_price": "30", "kind": "CE"}]}
    codes = [c for c, _ in orders.spec_problems(spec, fm.DEFAULT_PARAMS)]
    assert set(codes) == {"TICK_SIZE", "COLLAR", "LOT_SIZE"} and len(codes) == 3, codes


def test_adp2_76_live_basket_all_legs_fresh_or_nothing_fills(pg_pool):
    async def go():
        t = H.tenant()
        acc, pol = await H.make_desk_account(pg_pool, t)
        fq = H.FakeQuotes()
        gw = ExecutionGateway(pg_pool, live=ad.LivePaperAdapter(fq, fm.DEFAULT_PARAMS))
        plan = await H.make_approved_plan(pg_pool, t, acc, pol, debit_spread(acc["account_id"]))
        it = await gw.create_intent(tenant_id=t, trade_id=plan["trade_id"], plan_version=1, as_of=T1030)
        assert it["status"] == "VALIDATED", it["refusal_codes"]
        k1, k2 = H.key_opt("CE", 1400), H.key_opt("CE", 1440)
        mk = lambda key, sym, ltp, bid, ask, at: H.quote(key, sym, ltp, bid=bid, ask=ask, at=at, bid_qty=5000, ask_qty=5000, lot=500)
        stale = T1030 - timedelta(minutes=10)
        fq.answer = QuoteAnswer(quotes={k1: mk(k1, "ACME26NOV1400CE", "32.1", "32.0", "32.2", T1030 - timedelta(seconds=3)),
                                        k2: mk(k2, "ACME26NOV1440CE", "17.2", "17.1", "17.3", stale)})
        await settle.live_tick(gw, tenant_id=t, now=T1030)
        async with pg_pool.acquire() as c:
            filled = await c.fetchval("SELECT sum(filled_qty) FROM autodesk.trade_orders WHERE trade_id=$1", plan["trade_id"])
        assert filled == 0                                                       # one leg stale: nothing fills
        later = T1030 + timedelta(seconds=10)
        fq.answer = QuoteAnswer(quotes={k1: mk(k1, "ACME26NOV1400CE", "32.1", "32.0", "32.2", later - timedelta(seconds=2)),
                                        k2: mk(k2, "ACME26NOV1440CE", "17.2", "17.1", "17.3", later - timedelta(seconds=2))})
        await settle.live_tick(gw, tenant_id=t, now=later)
        async with pg_pool.acquire() as c:
            states = {r["state"] for r in await c.fetch("SELECT state FROM autodesk.trade_orders WHERE trade_id=$1", plan["trade_id"])}
            npos = await c.fetchval("SELECT count(*) FROM autodesk.trade_positions WHERE trade_id=$1", plan["trade_id"])
        assert states == {"FILLED"} and npos == 1
    run(go())
