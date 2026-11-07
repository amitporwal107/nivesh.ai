"""AD-P2-04, 05, 06, 47, 50, 51, 52: what each product does to the ledger, baskets, marks. TEST DATA, not real market data."""
from __future__ import annotations

from decimal import Decimal

from autodesk import contracts as C
from autodesk import store
from autodesk.execution import capital, settle
from tests.autodesk import p2_harness as H
from tests.autodesk.conftest import run

D = Decimal
CE, PE, BUY, SELL = "CE", "PE", "LONG", "SHORT"


async def go_sim(pool, body_fn, rows, *, capital_rs="1000000"):
    t = H.tenant()
    sim, acc, pol = await H.make_simulation(pool, t, capital=capital_rs)
    body = body_fn(acc["account_id"])
    plan = await H.make_approved_plan(pool, t, acc, pol, body)
    gw = H.sim_gateway(pool, rows)
    it = await gw.create_intent(tenant_id=t, trade_id=plan["trade_id"], plan_version=1, as_of=H.AT_0900, approval_id=plan["approval_id"])
    return t, sim, acc, plan, gw, it


async def fills_of(pool, tid):
    async with pool.acquire() as c:
        return [dict(r) for r in await c.fetch("SELECT * FROM autodesk.trade_fills WHERE trade_id=$1 ORDER BY leg_id", tid)]


async def opened(pool, t, sim, acc, plan, gw):
    out = await settle.run_open(gw, tenant_id=t, simulation_id=sim["simulation_id"], session=H.SD, as_of=H.AT_0915)
    async with pool.acquire() as c:
        v = await capital.balances(c, t, acc["account_id"])
    return out, v, await fills_of(pool, plan["trade_id"])


def fut_body(aid):
    leg = C.PlanLeg(leg_id="L1", kind=C.InstrumentKind.FUT, underlying="ACME", expiry=H.EXP, side=C.LegSide.LONG, lots=1,
                    lot_size=500, quantity=500, ref_price=D("1000"), ref_price_source="TEST DATA")
    return C.TradePlanBody(
        thesis="t", rationale=["t"], signal_id=None, market_context={"sector": "IT"}, account_id=aid, instrument="ACME",
        segment=C.Segment.FUTURES, strategy_type=C.StrategyType.LONG_FUTURES, legs=[leg],
        entry={"order_type": "LIMIT", "max_slippage_pct": "0.5", "reference_price": "1000"}, invalidation={}, targets=[],
        max_loss_rs=D("20000"), max_profit_rs=None, loss_defined=False, breakevens=[], expected_payoff={},
        capital_required_rs=D("75000"), margin_estimate={"amount_rs": "75000", "fno": True}, liquidity={}, holding={},
        exit_rules={}, risk_warnings=[], provenance={}, plan_expires_at=H.AT_1530)


def test_adp2_04_futures_margin_notional_and_loss_are_three_numbers(pg_pool):
    async def go():
        t, sim, acc, plan, gw, it = await go_sim(pg_pool, fut_body, {H.key_fut(): H.bar("1000", units=500_000, lot=500)})
        assert it["status"] == "VALIDATED", it["refusal_codes"]
        out, v, fills = await opened(pg_pool, t, sim, acc, plan, gw)
        f = fills[0]
        notional = f["price"] * 500
        assert out["filled_orders"] == 1
        assert v.used_margin_rs == (notional * D("0.15")).quantize(D("0.01"))
        assert v.deployed_notional_rs == notional and v.open_risk_rs == D("20000.00")
        assert v.cash_balance_rs == D("1000000") - f["charges_rs"]                    # a future costs no cash, only fees
        assert len({v.used_margin_rs, v.deployed_notional_rs, v.open_risk_rs}) == 3
        assert v.available_cash_rs == v.cash_balance_rs - v.used_margin_rs
    run(go())


def debit_spread(aid):
    legs = [H.opt_leg("L1", CE, BUY, 1400, "32.10"), H.opt_leg("L2", CE, SELL, 1440, "17.20")]
    return H.spread_body(aid, legs, C.StrategyType.BULL_CALL_SPREAD, max_loss=15200, capital=14900)


def credit_spread(aid):
    legs = [H.opt_leg("L1", PE, SELL, 1400, "30.00", lots=1), H.opt_leg("L2", PE, BUY, 1360, "12.00", lots=1)]
    return H.spread_body(aid, legs, C.StrategyType.BULL_PUT_SPREAD, max_loss=11200, capital=20000)


def condor(aid):
    legs = [H.opt_leg("L1", PE, SELL, 1400, "20.00", lots=1), H.opt_leg("L2", PE, BUY, 1360, "8.00", lots=1),
            H.opt_leg("L3", CE, SELL, 1600, "22.00", lots=1), H.opt_leg("L4", CE, BUY, 1640, "9.00", lots=1)]
    return H.spread_body(aid, legs, C.StrategyType.IRON_CONDOR, max_loss=12000, capital=20000)


def rows_for(*specs, units=1_000_000):
    return {H.key_opt(k, s): H.bar(o, units=units, lot=500) for k, s, o in specs}


def test_adp2_05_52_debit_spread_cash_out_margin_zero_one_position_two_legs(pg_pool):
    async def go():
        rows = rows_for((CE, 1400, "32.10"), (CE, 1440, "17.20"))
        t, sim, acc, plan, gw, it = await go_sim(pg_pool, debit_spread, rows)
        assert it["status"] == "VALIDATED", it["refusal_codes"]
        out, v, fills = await opened(pg_pool, t, sim, acc, plan, gw)
        assert len(fills) == 2 and out["filled_orders"] == 2
        buy = next(f for f in fills if f["side"] == "BUY")
        sell = next(f for f in fills if f["side"] == "SELL")
        net = buy["price"] * 1000 - sell["price"] * 1000
        fees = buy["charges_rs"] + sell["charges_rs"]
        assert v.cash_balance_rs == D("1000000") - net - fees and v.used_margin_rs == 0
        async with pg_pool.acquire() as c:
            legs = await c.fetch("SELECT * FROM autodesk.trade_position_legs WHERE position_id=(SELECT position_id FROM "
                                 "autodesk.trade_positions WHERE trade_id=$1)", plan["trade_id"])
            npos = await c.fetchval("SELECT count(*) FROM autodesk.trade_positions WHERE trade_id=$1", plan["trade_id"])
        assert npos == 1 and {lg["side"] for lg in legs} == {"LONG", "SHORT"} and len(legs) == 2
        assert buy["charges_rs"] > 0 and sell["charges_rs"] > 0                    # each leg its own charges
    run(go())


def test_adp2_05_credit_spread_cash_in_margin_is_the_width(pg_pool):
    async def go():
        rows = rows_for((PE, 1400, "30.00"), (PE, 1360, "12.00"))
        t, sim, acc, plan, gw, it = await go_sim(pg_pool, credit_spread, rows)
        assert it["status"] == "VALIDATED", it["refusal_codes"]
        out, v, fills = await opened(pg_pool, t, sim, acc, plan, gw)
        assert len(fills) == 2
        sell = next(f for f in fills if f["side"] == "SELL")
        buy = next(f for f in fills if f["side"] == "BUY")
        credit = sell["price"] * 500 - buy["price"] * 500
        fees = sum(f["charges_rs"] for f in fills)
        assert v.used_margin_rs == D("20000.00")                                    # (1400 − 1360) × 500
        assert v.cash_balance_rs == D("1000000") + credit - fees
        assert D("1000000") - v.available_buying_power_rs == D("20000") - credit + fees    # falls by width − credit + fees
    run(go())


def test_adp2_52_iron_condor_four_legs_one_position(pg_pool):
    async def go():
        rows = rows_for((PE, 1400, "20.00"), (PE, 1360, "8.00"), (CE, 1600, "22.00"), (CE, 1640, "9.00"))
        t, sim, acc, plan, gw, it = await go_sim(pg_pool, condor, rows)
        assert it["status"] == "VALIDATED", it["refusal_codes"]
        out, v, fills = await opened(pg_pool, t, sim, acc, plan, gw)
        assert len(fills) == 4 and out["filled_orders"] == 4
        async with pg_pool.acquire() as c:
            n = await c.fetchval("SELECT count(*) FROM autodesk.trade_position_legs WHERE position_id=(SELECT position_id FROM "
                                 "autodesk.trade_positions WHERE trade_id=$1)", plan["trade_id"])
        assert n == 4 and v.used_margin_rs == D("20000.00") and v.open_risk_rs == D("12000.00")
    run(go())


def test_adp2_50_one_untraded_leg_rejects_every_leg_and_releases(pg_pool):
    async def go():
        rows = rows_for((CE, 1400, "32.10"))
        rows[H.key_opt(CE, 1440)] = H.bar("17.20", units=0, lot=500, traded=False)
        t, sim, acc, plan, gw, it = await go_sim(pg_pool, debit_spread, rows)
        out = await settle.run_open(gw, tenant_id=t, simulation_id=sim["simulation_id"], session=H.SD, as_of=H.AT_0915)
        async with pg_pool.acquire() as c:
            os_ = [dict(r) for r in await c.fetch("SELECT * FROM autodesk.trade_orders WHERE trade_id=$1", plan["trade_id"])]
            res = await capital.get_reservation(c, t, it["reservation_id"])
            npos = await c.fetchval("SELECT count(*) FROM autodesk.trade_positions WHERE trade_id=$1", plan["trade_id"])
            st = (await store.get_plan(c, t, plan["trade_id"]))["status"]
            v = await capital.balances(c, t, acc["account_id"])
        assert out["rejected"] == 1 and {o["state"] for o in os_} == {"REJECTED"}
        assert all("all-or-none" in (o["reject_reason"] or "") or "together" in (o["reject_reason"] or "") for o in os_)
        assert "L2" in os_[0]["reject_reason"] and res["status"] == "RELEASED" and npos == 0 and st == "EXECUTION_REFUSED"
        assert v.reserved_capital_rs == 0 and v.cash_balance_rs == D("1000000.00")
    run(go())


def test_adp2_51_net_cost_above_net_limit_rejects_all_legs(pg_pool):
    async def go():
        # the long leg opens 40 % above its plan premium: the net passes the net limit (+15 %)
        rows = rows_for((CE, 1400, "45.00"), (CE, 1440, "17.20"))
        t, sim, acc, plan, gw, it = await go_sim(pg_pool, debit_spread, rows)
        await settle.run_open(gw, tenant_id=t, simulation_id=sim["simulation_id"], session=H.SD, as_of=H.AT_0915)
        async with pg_pool.acquire() as c:
            os_ = [dict(r) for r in await c.fetch("SELECT * FROM autodesk.trade_orders WHERE trade_id=$1", plan["trade_id"])]
        assert {o["state"] for o in os_} == {"REJECTED"} and "BASKET_NET_LIMIT" in os_[0]["reject_code"]
    run(go())


def test_adp2_06_marks_reconcile_and_unrealized_is_signed(pg_pool):
    async def go():
        rows = rows_for((CE, 1400, "32.10"), (CE, 1440, "17.20"))
        rows[H.key_opt(CE, 1400)] = H.bar("32.10", "36", "31", "35.00", units=1_000_000, lot=500)
        rows[H.key_opt(CE, 1440)] = H.bar("17.20", "20", "16", "19.00", units=1_000_000, lot=500)
        t, sim, acc, plan, gw, it = await go_sim(pg_pool, debit_spread, rows)
        await settle.run_open(gw, tenant_id=t, simulation_id=sim["simulation_id"], session=H.SD, as_of=H.AT_0915)
        out = await settle.run_close(gw, tenant_id=t, simulation_id=sim["simulation_id"], session=H.SD, as_of=H.AT_1530)
        assert out["marked_legs"] == 2
        async with pg_pool.acquire() as c:
            v = await capital.balances(c, t, acc["account_id"])
            legs = {r["leg_id"]: dict(r) for r in await c.fetch("SELECT * FROM autodesk.trade_position_legs")}
            snap = await c.fetchrow("SELECT * FROM autodesk.equity_snapshots WHERE account_id=$1", acc["account_id"])
        long_leg = next(x for x in legs.values() if x["side"] == "LONG" and x["mark_price"] == D("35.0000"))
        short_leg = next(x for x in legs.values() if x["side"] == "SHORT" and x["mark_price"] == D("19.0000"))
        assert long_leg["unrealized_rs"] == (D("35") * 1000 - long_leg["cost_value_rs"]).quantize(D("0.01"))
        assert short_leg["unrealized_rs"] == (short_leg["cost_value_rs"] - D("19") * 1000).quantize(D("0.01"))
        assert v.unrealized_gross_rs == long_leg["unrealized_rs"] + short_leg["unrealized_rs"]
        assert v.reconciliation()["difference_rs"] == 0 and snap["equity_rs"] == v.equity_rs
    run(go())


def test_adp2_47_option_leg_is_priced_from_its_own_contract_row(pg_pool):
    async def go():
        rows = rows_for((CE, 1400, "32.10"), (CE, 1440, "17.20"))
        rows[H.key_eq()] = H.bar("1000")                          # the underlying: must not matter
        t, sim, acc, plan, gw, it = await go_sim(pg_pool, debit_spread, rows)
        _out, _v, fills = await opened(pg_pool, t, sim, acc, plan, gw)
        buy = next(f for f in fills if f["side"] == "BUY")
        assert D("32.10") <= buy["price"] <= D("33.00") and buy["arrival_price"] == D("32.1000")
        assert "TEST DATA" in buy["price_source"]
        assert all(k.startswith(("CE:", "PE:")) for k, *_ in gw.sim.bars.reads)       # no read of the underlying
    run(go())
