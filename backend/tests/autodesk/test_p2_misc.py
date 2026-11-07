"""AD-P2-34, 35, 68, 78, 90, 91: adapter failure, withdrawal, the risk book from the ledger, the Kite quote source, wording.
TEST DATA / TEST DOUBLES, not real market data."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from autodesk import contracts as C
from autodesk import store
from autodesk.control.book import load_book
from autodesk.execution import adapters as ad
from autodesk.execution import capital, orders, settle
from autodesk.market.live_quotes import KiteQuoteSource, LegRef, NoKiteSession
from tests.autodesk import p2_harness as H
from tests.autodesk.conftest import run
from tests.autodesk.test_safety import ADVICE

D = Decimal


async def one_plan(pool, *, shares=100, px="1000", rows=None, **kw):
    t = H.tenant()
    sim, acc, pol = await H.make_simulation(pool, t)
    body = H.eq_body(acc["account_id"], shares=shares, px=px, **kw)
    plan = await H.make_approved_plan(pool, t, acc, pol, body)
    gw = H.sim_gateway(pool, rows if rows is not None else {H.key_eq(): H.bar(px)})
    it = await gw.create_intent(tenant_id=t, trade_id=plan["trade_id"], plan_version=1, as_of=H.AT_0900, approval_id=plan["approval_id"])
    assert it["status"] == "VALIDATED", it["refusal_codes"]
    return t, sim, acc, plan, gw, it


def test_adp2_34_adapter_failure_leaves_unknown_not_retried_released_at_the_close(pg_pool):
    async def go():
        t, sim, acc, plan, gw, it = await one_plan(pg_pool)

        async def boom(order, key):
            raise RuntimeError("the adapter is down")
        gw.sim.submit = boom
        row = await gw.submit(tenant_id=t, intent_id=it["intent_id"], as_of=H.AT_0915)
        async with pg_pool.acquire() as c:
            o = dict(await c.fetchrow("SELECT * FROM autodesk.trade_orders WHERE trade_id=$1", plan["trade_id"]))
            n_intents = await c.fetchval("SELECT count(*) FROM autodesk.execution_intents WHERE trade_id=$1", plan["trade_id"])
        assert o["state"] == "UNKNOWN" and n_intents == 1 and row["status"] == "SUBMITTED"
        out = await settle.run_open(gw, tenant_id=t, simulation_id=sim["simulation_id"], session=H.SD, as_of=H.AT_0915)
        assert out["filled_orders"] == 0                                   # an UNKNOWN order is never priced or retried
        async with pg_pool.acquire() as c:
            res = await capital.get_reservation(c, t, it["reservation_id"])
        assert res["status"] == "ACTIVE"                                   # held while the order is unresolved
        await settle.run_close(gw, tenant_id=t, simulation_id=sim["simulation_id"], session=H.SD, as_of=H.AT_1530)
        async with pg_pool.acquire() as c:
            o = dict(await c.fetchrow("SELECT * FROM autodesk.trade_orders WHERE trade_id=$1", plan["trade_id"]))
            res = await capital.get_reservation(c, t, it["reservation_id"])
        assert o["state"] == "EXPIRED" and res["status"] == "EXPIRED"
    run(go())


def test_adp2_35_withdraw_open_order_filled_order_and_amend(pg_pool):
    async def go():
        # a limit that does not reach the open: the order rests, then is withdrawn
        t, sim, acc, plan, gw, it = await one_plan(pg_pool, rows={H.key_eq(): H.bar("1010", "1020", "1008", "1015")}, zone_high="1001")
        await settle.run_open(gw, tenant_id=t, simulation_id=sim["simulation_id"], session=H.SD, as_of=H.AT_0915)
        async with pg_pool.acquire() as c:
            oid = await c.fetchval("SELECT order_id FROM autodesk.trade_orders WHERE trade_id=$1", plan["trade_id"])
        await gw.withdraw(tenant_id=t, order_id=oid, as_of=H.AT_0915 + timedelta(minutes=5))
        async with pg_pool.acquire() as c:
            hist = [r["to_state"] for r in await c.fetch("SELECT to_state FROM autodesk.trade_order_events WHERE order_id=$1 ORDER BY seq", oid)]
            res = await capital.get_reservation(c, t, it["reservation_id"])
            st = (await store.get_plan(c, t, plan["trade_id"]))["status"]
            v = await capital.balances(c, t, acc["account_id"])
        assert hist[-2:] == ["CANCEL_PENDING", "CANCELLED"] and res["status"] == "RELEASED" and st == "EXPIRED"
        assert v.reserved_capital_rs == 0
        with pytest.raises(store.Conflict):
            await gw.withdraw(tenant_id=t, order_id=oid)
        with pytest.raises(store.Conflict, match="AMEND_NOT_ALLOWED"):     # Phase 3: amend exists, never on an ended order
            await gw.amend(tenant_id=t, order_id=oid, changes={"limit_price": "1"})
        # a filled order cannot be withdrawn
        t2, sim2, acc2, plan2, gw2, it2 = await one_plan(pg_pool)
        await settle.run_open(gw2, tenant_id=t2, simulation_id=sim2["simulation_id"], session=H.SD, as_of=H.AT_0915)
        async with pg_pool.acquire() as c:
            oid2 = await c.fetchval("SELECT order_id FROM autodesk.trade_orders WHERE trade_id=$1", plan2["trade_id"])
        with pytest.raises(store.Conflict):
            await gw2.withdraw(tenant_id=t2, order_id=oid2)
    run(go())


def test_adp2_68_book_counts_reservations_and_filled_positions(pg_pool):
    async def go():
        t, sim, acc, plan, gw, it = await one_plan(pg_pool)
        async with pg_pool.acquire() as c:
            b = await load_book(c, t, acc["account_id"], H.AT_0900)
        mine = [x for x in b.pending if x.trade_id == plan["trade_id"]]
        assert len(mine) == 1 and mine[0].max_loss_rs == D("4000.00") and b.pending_risk_rs == D("4000.00")   # the reservation
        await settle.run_open(gw, tenant_id=t, simulation_id=sim["simulation_id"], session=H.SD, as_of=H.AT_0915)
        async with pg_pool.acquire() as c:
            await c.execute("UPDATE autodesk.trade_plans SET status='EXPIRED' WHERE trade_id=$1", plan["trade_id"])   # plan row expiry
            b = await load_book(c, t, acc["account_id"], H.AT_1530)
            v = await capital.balances(c, t, acc["account_id"])
        mine = [x for x in b.pending if x.trade_id == plan["trade_id"]]
        assert len(mine) == 1 and mine[0].max_loss_rs == D("4000.00")      # the open position stays counted
        assert b.equity_rs == v.equity_rs < D("1000000")                   # equity from the ledger (fees paid)
    run(go())


# ── AD-P2-78 the Kite quote source, with fakes ───────────────────────────────────────────────────────

class FakeKite:
    def __init__(self):
        self.calls = []

    def instruments(self, ex):
        self.calls.append(("instruments", ex))
        return [{"instrument_type": "CE", "name": "ACME", "expiry": "2026-11-26", "strike": 1400, "tradingsymbol": "ACME26NOV1400CE",
                 "lot_size": 500}]

    def quote(self, keys):
        self.calls.append(("quote", tuple(keys)))
        now = datetime.now(timezone.utc).isoformat()
        return {k: {"last_price": 32.1, "volume": 1000, "last_trade_time": now,
                    "depth": {"buy": [{"price": 32.0, "quantity": 500}], "sell": [{"price": 32.2, "quantity": 500}]}} for k in keys}


def test_adp2_78_redis_first_rest_for_the_rest_and_a_token_failure_gives_a_reason_not_a_price():
    async def go():
        now = datetime(2026, 11, 5, 5, 0, tzinfo=timezone.utc)
        eq, opt = LegRef("EQ", "ACME"), LegRef("CE", "ACME", H.EXP.replace(day=26).replace(month=11), D("1400"))
        row = {"symbol": "ACME", "ltp": "1000", "bid": "999.9", "ask": "1000.1", "bid_qty": 10, "ask_qty": 10, "volume": 500,
               "received_at": (now - timedelta(seconds=3)).isoformat()}

        async def cache(symbols):
            return {"ACME": row}
        kite = FakeKite()

        async def kf():
            return kite
        src = KiteQuoteSource(read_cache=cache, kite_factory=kf)
        ans = await src.quotes([eq], now)
        assert ans.quotes[eq.key].source == "feed-cache" and kite.calls == []            # Redis answered; Kite untouched
        ans = await src.quotes([eq, opt], now)
        assert ans.quotes[eq.key].source == "feed-cache" and ans.quotes[opt.key].source == "kite-rest"
        assert [c[0] for c in kite.calls] == ["instruments", "quote"] and kite.calls[1][1] == ("NFO:ACME26NOV1400CE",)

        async def nokite():
            raise NoKiteSession("the day's Kite login is not valid")
        down = KiteQuoteSource(read_cache=lambda s: _none(), kite_factory=nokite)
        ans = await down.quotes([opt], now)
        assert ans.quotes == {} and "login" in ans.problems["*"]                         # a reason, no price
        ans2 = await down.quotes([opt], now)                                              # backed off: no second attempt
        assert ans2.quotes == {} and "login" in ans2.problems["*"]
    run(go())


async def _none():
    return None


def test_adp2_78_source_file_calls_only_instruments_and_quote():
    src = Path(__file__).resolve().parents[2] / "autodesk" / "market" / "live_quotes.py"
    used = set(re.findall(r"\bkite\.(\w+)", src.read_text()))
    assert used <= {"instruments", "quote"}, used


# ── AD-P2-90 / 91 ───────────────────────────────────────────────────────────────────────────────────

def test_adp2_90_adapters_are_paper_and_shadow_only():
    assert ad.LIVE_EXECUTION_AVAILABLE is False
    assert set(ad.known_adapters()) == {"PAPER_SIM", "PAPER_LIVE", "SHADOW"}
    assert ad.route_name({"kind": "PAPER"}) == "PAPER_LIVE" and ad.route_name({"kind": "SIMULATION"}) == "PAPER_SIM"
    import inspect
    assert "client" not in inspect.signature(ad.route_name).parameters


def test_adp2_91_generated_text_avoids_the_advice_words(pg_pool):
    async def go():
        t, sim, acc, plan, gw, it = await one_plan(pg_pool, rows={H.key_eq(): H.bar("1010", "1020", "1008", "1015")}, zone_high="1001")
        await settle.run_open(gw, tenant_id=t, simulation_id=sim["simulation_id"], session=H.SD, as_of=H.AT_0915)
        await settle.run_close(gw, tenant_id=t, simulation_id=sim["simulation_id"], session=H.SD, as_of=H.AT_1530)
        t2, sim2, acc2, plan2, gw2, it2 = await one_plan(pg_pool)
        await settle.run_open(gw2, tenant_id=t2, simulation_id=sim2["simulation_id"], session=H.SD, as_of=H.AT_0915)
        async with pg_pool.acquire() as c:
            texts = []
            for q in ("SELECT reason AS x FROM autodesk.trade_order_events", "SELECT reject_reason AS x FROM autodesk.trade_orders",
                      "SELECT last_no_fill_reason AS x FROM autodesk.trade_orders", "SELECT summary AS x FROM autodesk.trade_journal_entries",
                      "SELECT memo AS x FROM autodesk.capital_ledger_entries", "SELECT price_source AS x FROM autodesk.trade_fills"):
                texts += [r["x"] for r in await c.fetch(q) if r["x"]]
            for r in await c.fetch("SELECT controls FROM autodesk.execution_intents"):
                texts += [k["detail"] for k in r["controls"]]
        from autodesk.simulator.manager import PHASE2_LIMITATIONS
        from autodesk.execution import fill_model as fm
        texts += PHASE2_LIMITATIONS + [fm.ALL_OR_NONE]
        bad = [(x, ADVICE.search(x).group(0)) for x in texts if ADVICE.search(x)]
        assert texts and bad == [], bad
    run(go())


def test_adp2_01_migration_gives_an_existing_account_its_opening_row(pg_pool):
    """An account that existed before migration 003 (its ledger row removed to simulate that) gets one when the migration's INSERT … SELECT runs."""
    async def go():
        from autodesk.db.migrate import MIGRATIONS_DIR
        t = H.tenant()
        acc, pol = await H.make_desk_account(pg_pool, t)
        sql = next(p for p in sorted(MIGRATIONS_DIR.glob("003_*.sql"))).read_text()
        insert = sql[sql.index("INSERT INTO autodesk.capital_ledger_entries"):sql.index("-- ── Reservations")]
        async with pg_pool.acquire() as c:
            await c.execute("ALTER TABLE autodesk.capital_ledger_entries DISABLE TRIGGER capital_ledger_append_only")
            try:
                await c.execute("DELETE FROM autodesk.capital_ledger_entries WHERE account_id=$1", acc["account_id"])
            finally:
                await c.execute("ALTER TABLE autodesk.capital_ledger_entries ENABLE TRIGGER capital_ledger_append_only")
            assert await c.fetchval("SELECT count(*) FROM autodesk.capital_ledger_entries WHERE account_id=$1", acc["account_id"]) == 0
            await c.execute(insert)
            await c.execute(insert)                                              # idempotent
            v = await capital.balances(c, t, acc["account_id"])
            n = await c.fetchval("SELECT count(*) FROM autodesk.capital_ledger_entries WHERE account_id=$1", acc["account_id"])
        assert n == 1 and v.equity_rs == v.cash_balance_rs == v.available_buying_power_rs == D("1000000.00")
    run(go())


def test_adp2_02_append_only_tables_refuse_changes_to_real_rows(pg_pool):
    async def go():
        import asyncpg
        t, sim, acc, plan, gw, it = await one_plan(pg_pool)
        await settle.run_open(gw, tenant_id=t, simulation_id=sim["simulation_id"], session=H.SD, as_of=H.AT_0915)
        async with pg_pool.acquire() as c:
            for sql in ("UPDATE autodesk.trade_fills SET price=1 WHERE trade_id=$1", "DELETE FROM autodesk.trade_fills WHERE trade_id=$1",
                        "UPDATE autodesk.trade_journal_entries SET summary='x' WHERE trade_id=$1",
                        "DELETE FROM autodesk.trade_journal_entries WHERE trade_id=$1",
                        "UPDATE autodesk.trade_order_events SET reason='x' WHERE order_id=(SELECT order_id FROM autodesk.trade_orders WHERE trade_id=$1)",
                        "DELETE FROM autodesk.trade_order_events WHERE order_id=(SELECT order_id FROM autodesk.trade_orders WHERE trade_id=$1)"):
                with pytest.raises(asyncpg.PostgresError):
                    await c.execute(sql, plan["trade_id"])
            with pytest.raises(asyncpg.CheckViolationError):                     # a fill can only ever be simulated
                await c.execute("INSERT INTO autodesk.trade_fills (fill_id, order_id, intent_id, tenant_id, account_id, trade_id, leg_id, side, "
                                "quantity, price, arrival_price, value_rs, charges, charges_rs, cost_model, price_source, fill_model, fill_kind, "
                                "fill_time, session_date) SELECT 'F-x', order_id, intent_id, tenant_id, account_id, trade_id, leg_id, side, 1, 1, 1, 1, "
                                "'{}'::jsonb, 0, 'x', 'x', 'x', 'BROKER_CONFIRMED', now(), session_date FROM autodesk.trade_orders WHERE trade_id=$1",
                                plan["trade_id"])
    run(go())
