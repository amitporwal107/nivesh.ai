"""AD-P2-01..14 — capital ledger and atomic reservation (docs/autodesk/PHASE2_DESIGN.md §3, §4). Throwaway Postgres, no market data."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import asyncpg
import pytest

from autodesk import contracts as C
from autodesk import store
from autodesk.execution import capital
from autodesk.execution.capital import ReservationRefused, ReserveRequest
from tests.autodesk.conftest import run

T = "t-p2-capital"
NOW = datetime(2026, 11, 5, 3, 45, tzinfo=timezone.utc)          # 09:15 IST
D = Decimal


def wide_policy(**over) -> C.PolicyBody:
    base = dict(per_trade_risk_pct=D("5"), open_risk_pct=D("100"), position_pct=D("100"), sector_pct=D("100"),
                max_margin_utilization_pct=D("100"))
    base.update(over)
    return C.PolicyBody(**base)


async def new_account(c, tenant=T, capital_rs="1000000", sim=None) -> dict:
    pol = await store.create_policy(c, tenant_id=tenant, name="p", body=wide_policy().model_dump(mode="json"), created_by="t")
    return await store.create_account(c, tenant_id=tenant, name="a", kind=C.AccountKind.PAPER,
                                      operating_mode=C.OperatingMode.AUTONOMOUS_PAPER, starting_capital_rs=D(capital_rs),
                                      policy_id=pol["policy_id"], created_by="t", simulation_id=sim)


def req(acc, key, *, amount="150000", risk="1000", capital_rs=None, sector="IT", fno=False, expires=None, policy=None,
        trade=None) -> ReserveRequest:
    return ReserveRequest(tenant_id=acc["tenant_id"], account_id=acc["account_id"], simulation_id=acc["simulation_id"],
                          trade_id=trade or f"TRD-{key}", plan_version=1, idempotency_key=key, amount_rs=D(amount),
                          risk_rs=D(risk), commitment_rs=D(amount), capital_rs=D(capital_rs or amount), instrument="ACME",
                          sector=sector, fno=fno, expires_at=expires or NOW + timedelta(hours=6), as_of=NOW,
                          policy=policy or wide_policy())


async def reserve(pool, r):
    async with pool.acquire() as c:
        async with c.transaction():
            return await capital.reserve(c, r)


def test_adp2_01_opening_row(pg_pool):
    async def go():
        async with pg_pool.acquire() as c:
            acc = await new_account(c)
            v = await capital.balances(c, T, acc["account_id"])
            n = await c.fetchval("SELECT count(*) FROM autodesk.capital_ledger_entries WHERE account_id=$1", acc["account_id"])
        assert n == 1
        for f in ("equity_rs", "cash_balance_rs", "available_cash_rs", "available_buying_power_rs"):
            assert getattr(v, f) == D("1000000.00"), f
        for f in ("used_margin_rs", "reserved_capital_rs", "deployed_notional_rs", "open_risk_rs", "pending_risk_rs",
                  "pending_order_commitment_rs", "realized_gross_rs", "fees_rs", "unrealized_gross_rs", "net_pnl_rs"):
            assert getattr(v, f) == 0, f
    run(go())


def test_adp2_02_append_only(pg_pool):
    async def go():
        async with pg_pool.acquire() as c:
            acc = await new_account(c)
            for sql in ("UPDATE autodesk.capital_ledger_entries SET memo='x' WHERE account_id=$1",
                        "DELETE FROM autodesk.capital_ledger_entries WHERE account_id=$1"):
                with pytest.raises(asyncpg.PostgresError):
                    await c.execute(sql, acc["account_id"])
            # the other append-only tables carry the same row trigger (their rows are exercised by the gateway tests)
            for tbl in ("trade_order_events", "trade_fills", "trade_journal_entries"):
                trg = await c.fetchval("SELECT count(*) FROM pg_trigger WHERE tgrelid = ('autodesk.' || $1)::regclass "
                                       "AND NOT tgisinternal AND (tgtype & 8 = 8 OR tgtype & 16 = 16)", tbl)
                assert trg >= 1, tbl
            col = await c.fetchval("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'autodesk.trade_fills'::regclass "
                                   "AND pg_get_constraintdef(oid) LIKE '%fill_kind%'")
            assert "SIMULATED" in col
    run(go())


def test_adp2_10_ten_concurrent_reservations(pg_pool):
    async def go():
        async with pg_pool.acquire() as c:
            acc = await new_account(c)
        res = await asyncio.gather(*[reserve(pg_pool, req(acc, f"k10-{i}")) for i in range(10)], return_exceptions=True)
        ok = [r for r in res if isinstance(r, dict)]
        refused = [r for r in res if isinstance(r, ReservationRefused)]
        assert len(ok) == 6 and len(refused) == 4 and {r.code for r in refused} == {"INSUFFICIENT_FUNDS"}
        async with pg_pool.acquire() as c:
            v = await capital.balances(c, T, acc["account_id"])
            assert v.reserved_capital_rs == D("900000.00") and v.available_buying_power_rs == D("100000.00")
            assert v.pending_risk_rs == D("6000.00") and v.pending_order_commitment_rs == D("900000.00")
            n = await c.fetchval("SELECT count(*) FROM autodesk.capital_reservations WHERE account_id=$1", acc["account_id"])
            s = await c.fetchval("SELECT sum(amount_rs) FROM autodesk.capital_reservations WHERE account_id=$1 AND status='ACTIVE'",
                                 acc["account_id"])
        assert n == 6 and s == D("900000.00")
    run(go())


def test_adp2_11_idempotent_reserve(pg_pool):
    async def go():
        async with pg_pool.acquire() as c:
            acc = await new_account(c)
        a = await reserve(pg_pool, req(acc, "k11"))
        b = await reserve(pg_pool, req(acc, "k11"))
        many = await asyncio.gather(*[reserve(pg_pool, req(acc, "k11b")) for _ in range(5)])
        assert a["reservation_id"] == b["reservation_id"] and len({m["reservation_id"] for m in many}) == 1
        async with pg_pool.acquire() as c:
            rows = await c.fetchval("SELECT count(*) FROM autodesk.capital_ledger_entries WHERE account_id=$1 "
                                    "AND entry_type='CAPITAL_RESERVED'", acc["account_id"])
        assert rows == 2                                   # one per distinct key
    run(go())


def test_adp2_12_expiry_is_released_by_the_next_reserve(pg_pool):
    async def go():
        async with pg_pool.acquire() as c:
            acc = await new_account(c)
        first = await reserve(pg_pool, req(acc, "k12a", amount="900000", expires=NOW - timedelta(minutes=1)))
        # NOW is past its expiry, so the funds are free again for the next reservation of the account
        second = await reserve(pg_pool, req(acc, "k12b", amount="900000"))
        async with pg_pool.acquire() as c:
            old = await capital.get_reservation(c, T, first["reservation_id"])
            v = await capital.balances(c, T, acc["account_id"])
            rel = await c.fetchval("SELECT count(*) FROM autodesk.capital_ledger_entries WHERE account_id=$1 "
                                   "AND entry_type='CAPITAL_RESERVATION_RELEASED'", acc["account_id"])
        assert old["status"] == "EXPIRED" and old["released_rs"] == D("900000.00") and rel == 1
        assert second["status"] == "ACTIVE" and v.reserved_capital_rs == D("900000.00")
    run(go())


def test_adp2_13_partly_consumed_then_closed(pg_pool):
    async def go():
        async with pg_pool.acquire() as c:
            acc = await new_account(c)
        r = await reserve(pg_pool, req(acc, "k13", amount="200000", risk="1000"))
        async with pg_pool.acquire() as c:
            async with c.transaction():
                r = await capital.consume(c, r, used_rs=D("120000"), risk_moved_rs=D("600"), commitment_done_rs=D("120000"),
                                          ref_id="FILL-x", sim_time=None)
                assert r["consumed_rs"] == D("120000.00") and r["status"] == "ACTIVE"
                r = await capital.close_reservation(c, r, status=C.ReservationStatus.EXPIRED, reason="order ended", sim_time=None)
            v = await capital.balances(c, T, acc["account_id"])
        assert r["status"] == "CONSUMED" and r["consumed_rs"] + r["released_rs"] == r["amount_rs"] == D("200000.00")
        assert v.reserved_capital_rs == 0 and v.open_risk_rs == D("600.00") and v.pending_risk_rs == 0
        assert v.pending_order_commitment_rs == 0
    run(go())


@pytest.mark.parametrize("case,over,code", [
    ("funds", dict(amount="1000001"), "INSUFFICIENT_FUNDS"),
    ("per-trade risk", dict(risk="50001"), "PER_TRADE_RISK"),
    ("position", dict(capital_rs="300000", policy=wide_policy(position_pct=D("20"))), "POSITION_LIMIT"),
    ("sector", dict(capital_rs="300000", sector="Banks", policy=wide_policy(sector_pct=D("20"))), "SECTOR_LIMIT"),
    ("margin", dict(capital_rs="300000", fno=True, policy=wide_policy(max_margin_utilization_pct=D("20"))), "MARGIN_LIMIT"),
    ("open risk", dict(risk="40000", policy=wide_policy(open_risk_pct=D("3"))), "OPEN_RISK_LIMIT"),
])
def test_adp2_14_each_limit_has_its_code(pg_pool, case, over, code):
    async def go():
        async with pg_pool.acquire() as c:
            acc = await new_account(c)
            before = await c.fetchval("SELECT count(*) FROM autodesk.capital_ledger_entries WHERE account_id=$1", acc["account_id"])
        kw = {"amount": "10000", "risk": "100", **over}
        with pytest.raises(ReservationRefused) as e:
            await reserve(pg_pool, req(acc, f"k14-{case}", **kw))
        assert e.value.code == code
        async with pg_pool.acquire() as c:
            n = await c.fetchval("SELECT count(*) FROM autodesk.capital_reservations WHERE account_id=$1", acc["account_id"])
            after = await c.fetchval("SELECT count(*) FROM autodesk.capital_ledger_entries WHERE account_id=$1", acc["account_id"])
        assert n == 0 and after == before
    run(go())
