"""Phase 2 review, 7 Nov (Account 1 on the takeover branch). Each test here failed, or could not pass, before its fix:
AD-P2-101.. in docs/autodesk/TESTCASES.md. FakeQuotes, frozen session rows and crafted plans are TEST DATA, not real market data."""
from __future__ import annotations

import ast
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from autodesk import contracts as C
from autodesk import store
from autodesk.execution import adapters as ad
from autodesk.execution import capital, reports, settle
from autodesk.market import calendar
from autodesk.market.live_quotes import QuoteAnswer
from autodesk.market.view import DataUnavailable
from tests.autodesk import p2_harness as H
from tests.autodesk.conftest import run
from tests.autodesk.test_p2_live import KEY, T1030, desk_setup, fresh, live_gw, order_of
from tests.autodesk.test_p2_misc import one_plan
from tests.autodesk.test_p2_products import CE, BUY, PE, SELL, go_sim, opened
from tests.autodesk.test_p2_simulation import build, start, tenant
from tests.autodesk.test_safety import ADVICE

D = Decimal
IST = H.IST
SAT = datetime(2026, 11, 7, 10, 30, tzinfo=IST).astimezone(timezone.utc)


@pytest.fixture
def sessions_known(monkeypatch):
    """The holiday list of 2026 as the desk would have loaded it (crafted: one holiday on Wed 11 Nov)."""
    monkeypatch.setitem(calendar._HOLIDAYS, 2026, {date(2026, 11, 11): "TEST holiday"})


def test_adp2_101_a_persons_approval_leaves_the_workflow_outcome_an_object(pg_pool):
    async def go():
        t = tenant()
        m, gw = build(pg_pool)
        sim = await start(pg_pool, t, m, operating_mode=C.OperatingMode.ASSISTED)
        sid = sim["simulation_id"]
        for _ in range(3):
            await m.step(tenant_id=t, sid=sid, unit="PHASE", user_id="u")
        async with pg_pool.acquire() as c:
            pending = await store.list_approvals(c, t, pending_only=True, simulation_id=sid)
        await m.orch.decide(tenant_id=t, approval_id=pending[0]["approval_id"], decision="APPROVE", reason="ok", user_id="u")
        async with pg_pool.acquire() as c:
            plan = await store.get_plan(c, t, pending[0]["trade_id"])
            wf = await store.get_workflow(c, t, plan["workflow_id"])
        out = wf["outcome"]
        assert isinstance(out, dict), out
        assert out["result"] == "APPROVED" and out["execution"]["status"] == "VALIDATED" and out["trade_id"] == plan["trade_id"]
    run(go())


def test_adp2_102_an_execution_failure_ends_the_workflow_and_says_so(pg_pool):
    async def go():
        t = tenant()
        m, gw = build(pg_pool)

        async def boom(**kw):
            raise RuntimeError("test failure")
        gw.create_intent = boom
        sim = await start(pg_pool, t, m)
        sid = sim["simulation_id"]
        for _ in range(3):
            await m.step(tenant_id=t, sid=sid, unit="PHASE", user_id="u")
        async with pg_pool.acquire() as c:
            wfs = await store.list_workflows(c, t, simulation_id=sid, kind="TRADE_PROPOSAL")
        assert wfs and all(w["state"] == "COMPLETED" for w in wfs)
        assert wfs[0]["outcome"]["execution"] == {"status": "ERROR", "error": "RuntimeError: test failure"}
    run(go())


def test_adp2_103_one_tick_marks_every_tenant_not_the_last_ones_only(pg_pool, sessions_known):
    async def go():
        t1, acc1, plan1, fq, gw, _ = await desk_setup(pg_pool)
        fq.answer = QuoteAnswer(quotes={KEY: fresh(T1030)})
        await settle.live_tick(gw, tenant_id=t1, now=T1030)
        assert (await order_of(pg_pool, plan1["trade_id"]))["state"] == "FILLED"
        t2 = H.tenant()                                 # another tenant with a working order, so the tick's loop ends on it
        acc2, pol2 = await H.make_desk_account(pg_pool, t2)
        plan2 = await H.make_approved_plan(pg_pool, t2, acc2, pol2, H.eq_body(acc2["account_id"]))
        await gw.create_intent(tenant_id=t2, trade_id=plan2["trade_id"], plan_version=1, as_of=T1030, approval_id=plan2["approval_id"])
        later = T1030 + timedelta(minutes=10)
        fq.answer = QuoteAnswer(quotes={KEY: H.quote(KEY, "ACME", "1010", bid=1009.9, ask=1010.1, at=later)})
        await settle.live_tick(gw, now=later)                                         # the production call: no tenant
        async with pg_pool.acquire() as c:
            leg = await c.fetchrow("SELECT l.mark_price FROM autodesk.trade_position_legs l JOIN autodesk.trade_positions p "
                                   "USING (position_id) WHERE p.trade_id=$1", plan1["trade_id"])
        assert leg["mark_price"] == D("1010")
    run(go())


def test_adp2_104_open_positions_read_no_quote_when_the_market_is_shut(pg_pool, sessions_known):
    async def go():
        t, acc, plan, fq, gw, _ = await desk_setup(pg_pool)
        fq.answer = QuoteAnswer(quotes={KEY: fresh(T1030)})
        await settle.live_tick(gw, tenant_id=t, now=T1030)
        calls = fq.calls
        holiday = datetime(2026, 11, 11, 10, 30, tzinfo=IST).astimezone(timezone.utc)
        evening = datetime(2026, 11, 6, 19, 0, tzinfo=IST).astimezone(timezone.utc)
        for now in (SAT, holiday, evening):
            await settle.live_tick(gw, tenant_id=t, now=now)
        assert fq.calls == calls                        # a position alone does not wake the quote source
        monday = datetime(2026, 11, 9, 10, 30, tzinfo=IST).astimezone(timezone.utc)
        fq.answer = QuoteAnswer(quotes={KEY: fresh(monday)})
        assert (await settle.live_tick(gw, tenant_id=t, now=monday))["marked"] == 1
    run(go())


def test_adp2_105_one_quote_read_per_tick_with_no_row_locked_during_it(pg_pool, sessions_known):
    async def go():
        t, acc, plan, fq, gw, _ = await desk_setup(pg_pool)
        for sym in ("BETA", "GAMMA"):
            pol = await _policy_of(pg_pool, t, acc)
            p = await H.make_approved_plan(pg_pool, t, acc, pol, H.eq_body(acc["account_id"], sym=sym))
            await gw.create_intent(tenant_id=t, trade_id=p["trade_id"], plan_version=1, as_of=T1030, approval_id=p["approval_id"])
        before = fq.calls
        real = fq.quotes
        locked: list[int] = []

        async def spying(legs, now):
            async with pg_pool.acquire() as c:        # a transaction holding a row lock would show here
                locked.append(await c.fetchval("SELECT count(*) FROM pg_locks l JOIN pg_class k ON k.oid=l.relation "
                                               "WHERE l.mode='RowShareLock' AND k.relname='execution_intents'"))
            return await real(legs, now)
        fq.quotes = spying
        fq.answer = QuoteAnswer(problems={"*": "no quote in this test"})
        await settle.live_tick(gw, tenant_id=t, now=T1030)
        assert fq.calls == before + 1 and locked == [0]
    run(go())


async def _policy_of(pool, t, acc):
    async with pool.acquire() as c:
        return await store.get_policy(c, t, acc["policy_id"])


def test_adp2_106_a_fill_that_funds_cannot_cover_is_rejected(pg_pool):
    async def go():
        t, sim, acc, plan, gw, it = await one_plan(pg_pool)
        async with pg_pool.acquire() as c:
            v = await capital.balances(c, t, acc["account_id"])
            await capital.post(c, tenant_id=t, account_id=acc["account_id"], simulation_id=sim["simulation_id"],
                               entry_type=C.LedgerEntry.MANUAL_ADJUSTMENT, ref_type="ACCOUNT", ref_id=acc["account_id"],
                               memo="test: funds taken away", cash=-(v.available_buying_power_rs + D("500000")))
        await settle.run_open(gw, tenant_id=t, simulation_id=sim["simulation_id"], session=H.SD, as_of=H.AT_0915)
        o = await order_of(pg_pool, plan["trade_id"])
        assert o["state"] == "REJECTED" and o["reject_code"] == "INSUFFICIENT_FUNDS" and o["filled_qty"] == 0
        async with pg_pool.acquire() as c:
            assert await c.fetchval("SELECT count(*) FROM autodesk.trade_fills WHERE trade_id=$1", plan["trade_id"]) == 0
    run(go())


def _debit(aid):
    return H.spread_body(aid, [H.opt_leg("L1", CE, BUY, 1000, 30), H.opt_leg("L2", CE, SELL, 1100, 12)],
                         C.StrategyType.BULL_CALL_SPREAD, max_loss="18200", capital="18000")


def _condor(aid):
    return H.spread_body(aid, [H.opt_leg("L1", PE, BUY, 860, 5), H.opt_leg("L2", PE, SELL, 900, 12),
                               H.opt_leg("L3", CE, SELL, 1100, 12), H.opt_leg("L4", CE, BUY, 1140, 5)],
                         C.StrategyType.IRON_CONDOR, max_loss="26000", capital="26000")


def _rows(px):
    def fn(leg, session):
        return H.bar(px[(leg.kind, int(leg.strike))], lot=500)
    return fn


@pytest.mark.parametrize("body_fn,px,margin", [
    (_debit, {("CE", 1000): "30", ("CE", 1100): "12"}, "0"),
    (_condor, {("PE", 860): "5", ("PE", 900): "12", ("CE", 1100): "12", ("CE", 1140): "5"}, "40000"),
])
def test_adp2_107_a_basket_converts_its_reservation_once_on_the_net(pg_pool, body_fn, px, margin):
    async def go():
        t, sim, acc, plan, gw, it = await go_sim(pg_pool, body_fn, _rows(px))
        assert it["status"] == "VALIDATED", it["refusal_codes"]
        before_cash = D("1000000")
        out, v, fills = await opened(pg_pool, t, sim, acc, plan, gw)
        assert all(f["fill_kind"] == "SIMULATED" for f in fills)
        async with pg_pool.acquire() as c:
            res = dict(await c.fetchrow("SELECT * FROM autodesk.capital_reservations WHERE trade_id=$1", plan["trade_id"]))
            pos = dict(await c.fetchrow("SELECT * FROM autodesk.trade_positions WHERE trade_id=$1", plan["trade_id"]))
        used = (before_cash - v.cash_balance_rs) + v.used_margin_rs       # what the fills took from buying power
        assert v.used_margin_rs == D(margin)
        assert res["status"] == "CONSUMED" and res["consumed_rs"] == used
        assert res["consumed_rs"] + res["released_rs"] == res["amount_rs"]
        assert v.reserved_capital_rs == 0 and v.pending_risk_rs == 0 and v.pending_order_commitment_rs == 0
        assert pos["open_risk_rs"] == res["risk_rs"] == v.open_risk_rs and pos["capital_rs"] == res["capital_rs"]
        assert pos["margin_rs"] == D(margin)
    run(go())


def test_adp2_108_an_intent_left_created_goes_on_or_is_refused_at_start_up(pg_pool):
    async def go():
        t = H.tenant()
        sim, acc, pol = await H.make_simulation(pg_pool, t)
        plan = await H.make_approved_plan(pg_pool, t, acc, pol, H.eq_body(acc["account_id"]))
        gw = H.sim_gateway(pg_pool, {H.key_eq(): H.bar("1000")})
        real = gw._controls

        async def boom(*a, **kw):
            raise RuntimeError("stopped here")
        gw._controls = boom
        with pytest.raises(RuntimeError):
            await gw.create_intent(tenant_id=t, trade_id=plan["trade_id"], plan_version=1, as_of=H.AT_0900)
        async with pg_pool.acquire() as c:                # persisted before the controls ran (AD-P2-20), in its own commit
            st = await c.fetchval("SELECT status FROM autodesk.execution_intents WHERE trade_id=$1", plan["trade_id"])
        assert st == "CREATED"
        gw._controls = real
        it = await gw.create_intent(tenant_id=t, trade_id=plan["trade_id"], plan_version=1, as_of=H.AT_0900)
        assert it["status"] == "VALIDATED"

        plan2 = await H.make_approved_plan(pg_pool, t, acc, pol, H.eq_body(acc["account_id"], sym="BETA"))
        gw._controls = boom
        with pytest.raises(RuntimeError):
            await gw.create_intent(tenant_id=t, trade_id=plan2["trade_id"], plan_version=1, as_of=H.AT_0900)
        gw._controls = real
        assert await gw.recover() >= 1
        async with pg_pool.acquire() as c:
            r = dict(await c.fetchrow("SELECT * FROM autodesk.execution_intents WHERE trade_id=$1", plan2["trade_id"]))
            head = await store.get_plan(c, t, plan2["trade_id"])
        assert r["status"] == "REFUSED" and r["refusal_codes"] == ["INTERRUPTED"] and head["status"] == "EXECUTION_REFUSED"
    run(go())


def test_adp2_109_a_duplicate_does_not_end_the_plan_the_first_intent_is_working_on(pg_pool):
    async def go():
        t, sim, acc, plan, gw, it = await one_plan(pg_pool)
        dup = await gw.create_intent(tenant_id=t, trade_id=plan["trade_id"], plan_version=1, as_of=H.AT_0900, idempotency_key="another-key")
        assert dup["status"] == "REFUSED" and "DUPLICATE_INTENT" in dup["refusal_codes"]
        async with pg_pool.acquire() as c:
            assert (await store.get_plan(c, t, plan["trade_id"]))["status"] == "EXECUTING"
        await settle.run_open(gw, tenant_id=t, simulation_id=sim["simulation_id"], session=H.SD, as_of=H.AT_0915)
        assert (await order_of(pg_pool, plan["trade_id"]))["state"] == "FILLED"
    run(go())


def test_adp2_110_no_snapshot_on_a_day_without_a_session(pg_pool, sessions_known):
    async def go():
        t, acc, plan, fq, gw, _ = await desk_setup(pg_pool)
        fq.answer = QuoteAnswer(quotes={KEY: fresh(T1030)})
        await settle.live_tick(gw, tenant_id=t, now=T1030)
        assert await settle.live_close(gw, now=SAT + timedelta(hours=6)) == 0
        fri = datetime(2026, 11, 6, 15, 40, tzinfo=IST).astimezone(timezone.utc)
        assert await settle.live_close(gw, now=fri) >= 1
        async with pg_pool.acquire() as c:
            days = [r["session_date"] for r in await c.fetch("SELECT session_date FROM autodesk.equity_snapshots WHERE account_id=$1",
                                                             acc["account_id"])]
        assert days == [date(2026, 11, 6)]
    run(go())


@pytest.mark.parametrize("change,code", [("suspend", "ACCOUNT_NOT_ACTIVE"), ("mode", "MODE_NOT_ALLOWED"), ("policy", "POLICY_CHANGED")])
def test_adp2_111_a_working_order_is_held_when_its_binding_no_longer_holds(pg_pool, change, code):
    async def go():
        t, acc, plan, fq, gw, _ = await desk_setup(pg_pool)
        fq.answer = QuoteAnswer(quotes={KEY: fresh(T1030)})
        before = datetime(2026, 11, 5, 9, 0, tzinfo=IST).astimezone(timezone.utc)
        await settle.live_tick(gw, tenant_id=t, now=before)
        assert (await order_of(pg_pool, plan["trade_id"]))["state"] == "OPEN"
        async with pg_pool.acquire() as c:
            if change == "suspend":
                await c.execute("UPDATE autodesk.accounts SET status='SUSPENDED' WHERE account_id=$1", acc["account_id"])
            elif change == "mode":
                await c.execute("UPDATE autodesk.accounts SET operating_mode='RESEARCH' WHERE account_id=$1", acc["account_id"])
            else:
                pol = await store.get_policy(c, t, acc["policy_id"])
                await store.add_policy_version(c, tenant_id=t, policy_id=pol["policy_id"], body=pol["body"], created_by="test", reason="changed")
        out = await settle.live_tick(gw, tenant_id=t, now=T1030)
        o = await order_of(pg_pool, plan["trade_id"])
        assert out["fills"] == 0 and o["state"] == "OPEN" and o["filled_qty"] == 0 and o["last_no_fill_reason"].startswith(code)
    run(go())


def test_adp2_112_withdrawing_an_unknown_order_is_a_conflict(pg_pool):
    async def go():
        t, sim, acc, plan, gw, it = await one_plan(pg_pool)

        async def fail(order, key):
            raise RuntimeError("adapter down")
        gw.sim.submit = fail
        await gw.submit(tenant_id=t, intent_id=it["intent_id"], as_of=H.AT_0915)
        o = await order_of(pg_pool, plan["trade_id"])
        assert o["state"] == "UNKNOWN"
        with pytest.raises(store.Conflict):
            await gw.withdraw(tenant_id=t, order_id=o["order_id"], as_of=H.AT_0915)
    run(go())


def test_adp2_113_the_fingerprint_covers_marks_and_pnl(pg_pool):
    async def go():
        t, sim, acc, plan, gw, it = await one_plan(pg_pool, rows={H.key_eq(): H.bar("1000", close="1010")})
        sid = sim["simulation_id"]
        await settle.run_open(gw, tenant_id=t, simulation_id=sid, session=H.SD, as_of=H.AT_0915)
        await settle.run_close(gw, tenant_id=t, simulation_id=sid, session=H.SD, as_of=H.AT_1530)
        async with pg_pool.acquire() as c:
            a = await reports.fingerprint(c, sid)
            await c.execute("UPDATE autodesk.trade_position_legs SET mark_price=1011, unrealized_rs=unrealized_rs+100 WHERE position_id="
                            "(SELECT position_id FROM autodesk.trade_positions WHERE trade_id=$1)", plan["trade_id"])
            b = await reports.fingerprint(c, sid)
            s = await reports.execution_summary(c, t, sid)
        assert a != b and s["seed"] == 42 and s["reject_codes"] == {}
    run(go())


def test_adp2_114_a_failed_read_at_the_close_flags_the_mark_stale_and_the_run_goes_on(pg_pool):
    async def go():
        t, sim, acc, plan, gw, it = await one_plan(pg_pool, rows={H.key_eq(): H.bar("1000", close="1010")})
        sid = sim["simulation_id"]
        await settle.run_open(gw, tenant_id=t, simulation_id=sid, session=H.SD, as_of=H.AT_0915)

        async def down(leg, session):
            raise DataUnavailable("data API /prices/eod: HTTP 503")
        gw.sim.bars._read = down
        out = await settle.run_close(gw, tenant_id=t, simulation_id=sid, session=H.SD, as_of=H.AT_1530)
        assert out["stale_legs"] == 1 and out["marked_legs"] == 0
        async with pg_pool.acquire() as c:
            v = await capital.balances(c, t, acc["account_id"])
        assert [x["trade_id"] for x in v.stale_legs] == [plan["trade_id"]]
    run(go())


def test_adp2_115_capital_lists_old_marks_only_while_the_market_is_open(pg_pool, sessions_known):
    async def go():
        t, acc, plan, fq, gw, _ = await desk_setup(pg_pool)
        fq.answer = QuoteAnswer(quotes={KEY: fresh(T1030)})
        await settle.live_tick(gw, tenant_id=t, now=T1030)
        async with pg_pool.acquire() as c:
            fresh_view = await reports.capital_view(c, t, acc["account_id"], now=T1030 + timedelta(seconds=30))
            old_view = await reports.capital_view(c, t, acc["account_id"], now=T1030 + timedelta(minutes=5))
            shut_view = await reports.capital_view(c, t, acc["account_id"], now=SAT)
        assert fresh_view["marks"]["stale_legs"] == []
        assert [x["trade_id"] for x in old_view["marks"]["stale_legs"]] == [plan["trade_id"]]
        assert shut_view["marks"]["stale_legs"] == []
        assert reports.mark_age({"marked_at": T1030}, T1030 + timedelta(minutes=5), live=True)["mark_stale"] is True
        assert reports.mark_age({"marked_at": T1030}, SAT, live=True)["mark_stale"] is False
    run(go())


def test_adp2_116_no_literal_in_the_execution_code_uses_an_advice_word():
    """AD-92 over the source, so a reason no test happens to trigger is covered too. Docstrings are prose for engineers;
    BUY and SELL are API field values, buy and sell are the field names of Kite's depth (standard words are allowed there)."""
    pkg = Path(__file__).resolve().parents[2] / "autodesk"
    files = sorted((pkg / "execution").glob("*.py")) + [pkg / "market" / "session_bars.py", pkg / "market" / "live_quotes.py"]
    hits = []
    for f in files:
        tree = ast.parse(f.read_text())
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs and n.value not in ("BUY", "SELL", "buy", "sell"):
                m = ADVICE.search(n.value)
                if m:
                    hits.append(f"{f.name}:{n.lineno}: {m.group(0)!r} in {n.value!r}")
    assert hits == [], hits


def test_adp2_117_routes_say_paper_only_when_execution_is_wired(pg_pool):
    from types import SimpleNamespace
    from autodesk.routers.api import _execution_text
    assert _execution_text(SimpleNamespace(execution=object())) == "paper only: simulated fills, no broker orders"
    assert _execution_text(SimpleNamespace(execution=None)) == "none (Phase 1: no orders, fills or positions)"
    assert ad.LIVE_EXECUTION_AVAILABLE is False
