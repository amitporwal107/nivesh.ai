"""AD-P2-71..77, 79: the live desk prices paper orders from FRESH live quotes only. FakeQuotes is a TEST DOUBLE, not real market data."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from autodesk import contracts as C
from autodesk import store
from autodesk.execution import adapters as ad
from autodesk.execution import capital, settle
from autodesk.execution.gateway import ExecutionGateway
from autodesk.market.live_quotes import QuoteAnswer
from tests.autodesk import p2_harness as H
from tests.autodesk.conftest import run

D = Decimal
IST = H.IST
T1030 = datetime(2026, 11, 5, 10, 30, tzinfo=IST).astimezone(timezone.utc)
KEY = H.key_eq()


def live_gw(pool, fq):
    return ExecutionGateway(pool, live=ad.LivePaperAdapter(fq, H.DEFAULT_PARAMS if hasattr(H, "DEFAULT_PARAMS") else __import__(
        "autodesk.execution.fill_model", fromlist=["DEFAULT_PARAMS"]).DEFAULT_PARAMS))


async def desk_setup(pool, body_fn=None, **kw):
    t = H.tenant()
    acc, pol = await H.make_desk_account(pool, t)
    body = (body_fn or (lambda aid: H.eq_body(aid, shares=kw.get("shares", 100))))(acc["account_id"])
    plan = await H.make_approved_plan(pool, t, acc, pol, body)
    fq = H.FakeQuotes()
    gw = live_gw(pool, fq)
    it = await gw.create_intent(tenant_id=t, trade_id=plan["trade_id"], plan_version=1, as_of=T1030, approval_id=plan["approval_id"])
    assert it["status"] == "VALIDATED", it["refusal_codes"]
    return t, acc, plan, fq, gw, it


def fresh(now, ask="1000.10", bid="999.90", **kw):
    return H.quote(KEY, "ACME", "1000", bid=bid, ask=ask, at=now - timedelta(seconds=5), **kw)


async def order_of(pool, tid):
    async with pool.acquire() as c:
        return dict(await c.fetchrow("SELECT * FROM autodesk.trade_orders WHERE trade_id=$1", tid))


def test_adp2_71_fresh_quote_in_hours_fills_at_the_ask_plus_slippage(pg_pool):
    async def go():
        t, acc, plan, fq, gw, it = await desk_setup(pg_pool)
        fq.answer = QuoteAnswer(quotes={KEY: fresh(T1030)})
        out = await settle.live_tick(gw, tenant_id=t, now=T1030)
        assert out["fills"] == 1
        o = await order_of(pg_pool, plan["trade_id"])
        async with pg_pool.acquire() as c:
            f = dict(await c.fetchrow("SELECT * FROM autodesk.trade_fills WHERE trade_id=$1", plan["trade_id"]))
            npos = await c.fetchval("SELECT count(*) FROM autodesk.trade_positions WHERE trade_id=$1", plan["trade_id"])
        assert o["state"] == "FILLED" and f["fill_kind"] == "SIMULATED" and npos == 1
        assert D("1000.10") < f["price"] <= D("1005") and "live quote" in f["price_source"] and "test-feed:ACME" in f["price_source"]
    run(go())


def test_adp2_72_stale_then_missing_then_fresh_never_fills_at_the_old_price(pg_pool):
    async def go():
        t, acc, plan, fq, gw, it = await desk_setup(pg_pool)
        fq.answer = QuoteAnswer(quotes={KEY: H.quote(KEY, "ACME", "900", bid=899, ask=900, at=T1030 - timedelta(minutes=10))})
        await settle.live_tick(gw, tenant_id=t, now=T1030)
        fq.answer = QuoteAnswer(problems={"*": "the day's Kite login is not valid"})
        await settle.live_tick(gw, tenant_id=t, now=T1030 + timedelta(seconds=5))
        o = await order_of(pg_pool, plan["trade_id"])
        assert o["state"] == "OPEN" and o["attempts"] == 2 and o["filled_qty"] == 0 and o["last_no_fill_reason"]
        later = T1030 + timedelta(seconds=10)
        fq.answer = QuoteAnswer(quotes={KEY: fresh(later, ask="1001.00", bid="1000.80")})
        await settle.live_tick(gw, tenant_id=t, now=later)
        o = await order_of(pg_pool, plan["trade_id"])
        assert o["state"] == "FILLED" and o["avg_fill_price"] >= D("1001.00")                 # the fresh price, not 900
    run(go())


def test_adp2_73_closed_market_reads_no_quote_and_waits(pg_pool):
    async def go():
        from datetime import date
        t, acc, plan, fq, gw, it = await desk_setup(pg_pool, lambda aid: H.eq_body(aid, sd=date(2026, 11, 9)))   # approved for Monday
        fq.answer = QuoteAnswer(quotes={KEY: fresh(T1030)})
        async with pg_pool.acquire() as c:
            await c.execute("UPDATE autodesk.execution_intents SET session_date='2026-11-09' WHERE intent_id=$1", it["intent_id"])
        sat = datetime(2026, 11, 7, 10, 30, tzinfo=IST).astimezone(timezone.utc)
        before_open = datetime(2026, 11, 9, 9, 10, tzinfo=IST).astimezone(timezone.utc)
        for now in (sat, before_open):
            out = await settle.live_tick(gw, tenant_id=t, now=now)
            assert out["fills"] == 0 and fq.calls == 0
        after_cash = datetime(2026, 11, 9, 15, 16, tzinfo=IST).astimezone(timezone.utc)
        out = await settle.live_tick(gw, tenant_id=t, now=after_cash)
        assert out["fills"] == 0 and fq.calls == 0                                   # cash stops at 15:15
        monday = datetime(2026, 11, 9, 10, 30, tzinfo=IST).astimezone(timezone.utc)
        fq.answer = QuoteAnswer(quotes={KEY: fresh(monday)})
        out = await settle.live_tick(gw, tenant_id=t, now=monday)
        assert out["fills"] == 1 and fq.calls >= 1
    run(go())


def test_adp2_74_past_the_close_expires_and_releases(pg_pool):
    async def go():
        t, acc, plan, fq, gw, it = await desk_setup(pg_pool)
        close = datetime(2026, 11, 5, 15, 31, tzinfo=IST).astimezone(timezone.utc)
        fq.answer = QuoteAnswer(quotes={KEY: fresh(close)})
        out = await settle.live_tick(gw, tenant_id=t, now=close)
        o = await order_of(pg_pool, plan["trade_id"])
        async with pg_pool.acquire() as c:
            res = await capital.get_reservation(c, t, it["reservation_id"])
            st = (await store.get_plan(c, t, plan["trade_id"]))["status"]
        assert out["expired"] == 1 and o["state"] == "EXPIRED" and res["status"] == "EXPIRED" and st == "EXPIRED" and fq.calls == 0
    run(go())


def test_adp2_75_quantity_and_one_quote_one_fill(pg_pool):
    async def go():
        t, acc, plan, fq, gw, it = await desk_setup(pg_pool, shares=100)
        q = fresh(T1030, ask_qty=40)
        fq.answer = QuoteAnswer(quotes={KEY: q})
        await settle.live_tick(gw, tenant_id=t, now=T1030)
        o = await order_of(pg_pool, plan["trade_id"])
        assert o["state"] == "PARTIALLY_FILLED" and o["filled_qty"] == 40
        await settle.live_tick(gw, tenant_id=t, now=T1030)                                         # the same quote again
        assert (await order_of(pg_pool, plan["trade_id"]))["filled_qty"] == 40
        nxt = T1030 + timedelta(seconds=5)
        fq.answer = QuoteAnswer(quotes={KEY: fresh(nxt, ask_qty=1000)})
        await settle.live_tick(gw, tenant_id=t, now=nxt)
        assert (await order_of(pg_pool, plan["trade_id"]))["state"] == "FILLED"
    run(go())


def test_adp2_75_no_displayed_quantity_takes_a_quarter_per_tick(pg_pool):
    async def go():
        t, acc, plan, fq, gw, it = await desk_setup(pg_pool, shares=100)
        fq.answer = QuoteAnswer(quotes={KEY: fresh(T1030, ask_qty=None)})
        await settle.live_tick(gw, tenant_id=t, now=T1030)
        assert (await order_of(pg_pool, plan["trade_id"]))["filled_qty"] == 25
    run(go())


def test_adp2_75_limit_past_the_ask_does_not_fill(pg_pool):
    async def go():
        t, acc, plan, fq, gw, it = await desk_setup(pg_pool)
        fq.answer = QuoteAnswer(quotes={KEY: fresh(T1030, ask="1010.00", bid="1009.50")})
        await settle.live_tick(gw, tenant_id=t, now=T1030)
        o = await order_of(pg_pool, plan["trade_id"])
        assert o["state"] == "OPEN" and "LIMIT_NOT_REACHED" in o["last_no_fill_reason"]
    run(go())


def test_adp2_77_stop_new_entries_after_submission_blocks_the_fill(pg_pool):
    async def go():
        t, acc, plan, fq, gw, it = await desk_setup(pg_pool)
        fq.answer = QuoteAnswer(quotes={KEY: fresh(T1030)})
        before_open = datetime(2026, 11, 5, 9, 0, tzinfo=IST).astimezone(timezone.utc)
        await settle.live_tick(gw, tenant_id=t, now=before_open)                      # submitted; waits for the session
        assert (await order_of(pg_pool, plan["trade_id"]))["state"] == "OPEN" and fq.calls == 0
        async with pg_pool.acquire() as c:
            async with c.transaction():
                await store.set_desk_control(c, tenant_id=t, control=C.DeskControl.STOP_NEW_ENTRIES, active=True,
                                             reason="halt", actor="u")
        await settle.live_tick(gw, tenant_id=t, now=T1030)
        o = await order_of(pg_pool, plan["trade_id"])
        assert o["state"] == "OPEN" and o["filled_qty"] == 0 and "ENTRIES_STOPPED" in o["last_no_fill_reason"]
        async with pg_pool.acquire() as c:
            async with c.transaction():
                await store.set_desk_control(c, tenant_id=t, control=C.DeskControl.STOP_NEW_ENTRIES, active=False,
                                             reason="lifted", actor="u")
        fq.answer = QuoteAnswer(quotes={KEY: fresh(T1030 + timedelta(seconds=5))})
        await settle.live_tick(gw, tenant_id=t, now=T1030 + timedelta(seconds=5))
        assert (await order_of(pg_pool, plan["trade_id"]))["state"] == "FILLED"       # lifted: it fills
    run(go())


def test_adp2_79_marks_from_fresh_quotes_and_stale_flag(pg_pool):
    async def go():
        t, acc, plan, fq, gw, it = await desk_setup(pg_pool)
        fq.answer = QuoteAnswer(quotes={KEY: fresh(T1030)})
        await settle.live_tick(gw, tenant_id=t, now=T1030)
        later = T1030 + timedelta(minutes=30)
        fq.answer = QuoteAnswer(quotes={KEY: H.quote(KEY, "ACME", "1010", bid=1009.9, ask=1010.1, at=later - timedelta(seconds=3))})
        out = await settle.live_tick(gw, tenant_id=t, now=later)
        assert out["marked"] == 1
        async with pg_pool.acquire() as c:
            leg = dict(await c.fetchrow("SELECT l.* FROM autodesk.trade_position_legs l JOIN autodesk.trade_positions p USING (position_id) WHERE p.trade_id=$1", plan["trade_id"]))
        assert leg["mark_price"] == D("1010.0000") and leg["marked_at"] == later and leg["unrealized_rs"] > 0
    run(go())
