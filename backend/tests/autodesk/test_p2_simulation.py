"""AD-P2-60, 62, 63, 64, 65, 66, 67, 69: a simulation from scan to fills, through the real manager and orchestrator with
test-double agents (stubs.py) and a frozen session-bar source. TEST DATA, not real market data."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from autodesk import contracts as C
from autodesk import store
from autodesk.execution import adapters as ad
from autodesk.execution import capital, reports
from autodesk.execution.fill_model import DEFAULT_PARAMS
from autodesk.execution.gateway import ExecutionGateway
from autodesk.simulator.manager import SimulationManager
from tests.autodesk import p2_harness as H
from tests.autodesk import stubs
from tests.autodesk.conftest import run
from tests.autodesk.test_simulator import cfg, tenant

D = Decimal


def session_rows(*, shift=Decimal("0")):
    """Each share opens at the previous session's close (what the stub plans were priced on) plus `shift`."""
    def fn(leg, session):
        if leg.kind != "EQ":
            return None
        bars = [b for b in stubs.DATA["bars"][leg.underlying] if b.day < session]
        if not bars:
            return None
        px = bars[-1].close + shift
        return H.bar(px, px + 8, px - 8, px + 3, units=1_000_000, prev=bars[-1].close)
    return fn


def build(pool, rows=None, *, with_gateway=True):
    orch = stubs.orchestrator(pool)
    gw = None
    if with_gateway:
        gw = ExecutionGateway(pool, sim=ad.SimulationPaperAdapter(H.FrozenSessionBars(rows or session_rows()), DEFAULT_PARAMS))
        orch.execution = gw
    return SimulationManager(pool, orch, stubs.sessions_provider, versions=lambda: {"agents": "stub"}, execution=gw), gw


async def start(pool, t, m, **kw):
    sim = await m.create(tenant_id=t, cfg=cfg(**kw), user_id="u")
    await m.start(tenant_id=t, sid=sim["simulation_id"], user_id="u")
    return sim


def test_adp2_60_step_phase_by_phase(pg_pool):
    async def go():
        t = tenant()
        m, gw = build(pg_pool)
        sim = await start(pg_pool, t, m)
        sid = sim["simulation_id"]
        seen = {}
        for _ in range(6):                                                  # one session: 08:30 .. 18:00
            r = await m.step(tenant_id=t, sid=sid, unit="PHASE", user_id="u")
            st = r["steps"][0]["phase"]
            async with pg_pool.acquire() as c:
                seen[st] = {
                    "res": await c.fetchval("SELECT string_agg(status, ',') FROM autodesk.capital_reservations WHERE simulation_id=$1", sid),
                    "ord": await c.fetchval("SELECT string_agg(state, ',') FROM autodesk.trade_orders WHERE simulation_id=$1", sid),
                    "pos": await c.fetchval("SELECT count(*) FROM autodesk.trade_positions WHERE simulation_id=$1", sid),
                    "snap": await c.fetchval("SELECT count(*) FROM autodesk.equity_snapshots WHERE simulation_id=$1", sid)}
        assert seen["PROPOSALS"]["res"] == "ACTIVE" and seen["PROPOSALS"]["ord"] == "VALIDATED" and seen["PROPOSALS"]["pos"] == 0
        assert seen["OPEN"]["ord"] == "FILLED" and seen["OPEN"]["pos"] == 1 and seen["OPEN"]["res"] == "CONSUMED"
        assert seen["CLOSE"]["snap"] == 1 and seen["EOD"]["pos"] == 1
        async with pg_pool.acquire() as c:
            kinds = {r["event_type"] for r in await c.fetch("SELECT event_type FROM autodesk.events WHERE simulation_id=$1", sid)}
            res = await m.results(tenant_id=t, sid=sid)
        assert {"CAPITAL_RESERVED", "EXECUTION_INTENT_VALIDATED", "ORDER_STATE_CHANGED", "ORDER_FILLED", "POSITION_OPENED"} <= kinds
        es = res["execution_summary"]
        assert es["trades"] == 1 and es["orders"] == 1 and es["fills"] == 1 and es["reconciliation"]["difference_rs"] == "0.00"
    run(go())


def test_adp2_62_63_66_two_sessions_marks_drawdown_and_determinism(pg_pool):
    async def go():
        outs = []
        for seed in (42, 42, 7):
            t = tenant()
            m, gw = build(pg_pool)
            sim = await start(pg_pool, t, m, seed=seed, start_date=date(2026, 10, 28), end_date=date(2026, 10, 29))
            await m.run_to_end(tenant_id=t, sid=sim["simulation_id"])
            async with pg_pool.acquire() as c:
                s = await store.get_simulation(c, t, sim["simulation_id"])
                snaps = await c.fetch("SELECT * FROM autodesk.equity_snapshots WHERE simulation_id=$1 ORDER BY session_date",
                                      sim["simulation_id"])
            outs.append((s["results"]["execution_summary"], snaps))
        a, b, other = outs
        assert a[0]["fingerprint"] == b[0]["fingerprint"] and a[0]["net_pnl_rs"] == b[0]["net_pnl_rs"]
        assert a[0]["fingerprint"] != other[0]["fingerprint"]                     # another seed: other slippage and latency
        es, snaps = a
        assert es["trades"] == 2 and len(snaps) == 2 and es["fills"] == 2
        assert es["reconciliation"]["difference_rs"] == "0.00" and es["fill_model"]["version"] == "autodesk-fill-v1"
        for k in ("max_drawdown_rs", "max_drawdown_pct", "intents", "orders", "reservations", "positions", "capital", "pnl",
                  "fill_ratio", "rejection_rate", "cost_model", "labels"):
            assert k in es, k
        assert es["pnl"]["daily"][1]["cumulative_pnl_rs"] == es["net_pnl_rs"]
        assert snaps[1]["net_pnl_rs"] == D(es["net_pnl_rs"])
    run(go())


def test_adp2_64_no_look_ahead_in_fills(pg_pool):
    async def go():
        t = tenant()
        m, gw = build(pg_pool)
        sim = await start(pg_pool, t, m, start_date=date(2026, 10, 28), end_date=date(2026, 10, 29))
        await m.run_to_end(tenant_id=t, sid=sim["simulation_id"])
        reads = gw.sim.bars.reads
        assert reads and all(session == clock for _k, session, clock in reads)       # only the clock's own session
        import pytest
        from autodesk.market.view import LookAheadError
        with pytest.raises(LookAheadError):
            await gw.sim.bars.bar(H.LegRef("EQ", "RELIANCE"), date(2026, 10, 29), clock_session=date(2026, 10, 28))
        # changing a LATER session's rows changes nothing before it
        base = [dict(r) for r in await _fills(pg_pool, sim["simulation_id"])]
        m2, gw2 = build(pg_pool, rows=lambda leg, ses: (session_rows(shift=D("50"))(leg, ses) if ses == date(2026, 10, 29)
                                                         else session_rows()(leg, ses)))
        t2 = tenant()
        sim2 = await start(pg_pool, t2, m2, start_date=date(2026, 10, 28), end_date=date(2026, 10, 29))
        await m2.run_to_end(tenant_id=t2, sid=sim2["simulation_id"])
        again = [dict(r) for r in await _fills(pg_pool, sim2["simulation_id"])]
        assert base[0]["price"] == again[0]["price"] and base[0]["session_date"] == again[0]["session_date"]
    run(go())


async def _fills(pool, sid):
    async with pool.acquire() as c:
        return await c.fetch("SELECT session_date, price FROM autodesk.trade_fills WHERE simulation_id=$1 ORDER BY session_date", sid)


def test_adp2_65_isolation(pg_pool):
    async def go():
        t = tenant()
        m, gw = build(pg_pool)
        s1 = await start(pg_pool, t, m)
        s2 = await start(pg_pool, t, m)
        await m.run_to_end(tenant_id=t, sid=s1["simulation_id"])
        async with pg_pool.acquire() as c:
            a1 = await c.fetchval("SELECT account_id FROM autodesk.accounts WHERE simulation_id=$1", s1["simulation_id"])
            a2 = await c.fetchval("SELECT account_id FROM autodesk.accounts WHERE simulation_id=$1", s2["simulation_id"])
            v2 = await capital.balances(c, t, a2)
            desk_rows = await c.fetchval("SELECT count(*) FROM autodesk.trade_orders WHERE simulation_id IS NULL AND tenant_id=$1", t)
        assert a1 != a2 and v2.cash_balance_rs == D("1000000.00") and v2.reserved_capital_rs == 0 and desk_rows == 0
        # the live adapter refuses a simulated order; the simulation adapter refuses a desk order
        import pytest
        with pytest.raises(ad.AdapterRefused):
            await ad.LivePaperAdapter(None, DEFAULT_PARAMS).submit({"order_id": "x", "simulation_id": "SIM-1"}, "k")
        with pytest.raises(ad.AdapterRefused):
            await ad.SimulationPaperAdapter(None, DEFAULT_PARAMS).submit({"order_id": "x", "simulation_id": None}, "k")
        with pytest.raises(ad.AdapterRefused):
            await ad.ShadowAdapter().submit({"order_id": "x"}, "k")
        assert ad.LIVE_EXECUTION_AVAILABLE is False
    run(go())


def test_adp2_69_no_gateway_is_phase_1_behaviour(pg_pool):
    async def go():
        t = tenant()
        m, gw = build(pg_pool, with_gateway=False)
        sim = await start(pg_pool, t, m)
        await m.run_to_end(tenant_id=t, sid=sim["simulation_id"])
        async with pg_pool.acquire() as c:
            wfs = await c.fetch("SELECT outcome FROM autodesk.workflows WHERE simulation_id=$1 AND kind='TRADE_PROPOSAL'", sim["simulation_id"])
            n = {tbl: await c.fetchval(f"SELECT count(*) FROM autodesk.{tbl} WHERE simulation_id=$1", sim["simulation_id"])
                 for tbl in ("trade_orders", "trade_fills", "execution_intents", "capital_reservations", "trade_positions")}
            ledger = await c.fetchval("SELECT count(*) FROM autodesk.capital_ledger_entries WHERE simulation_id=$1", sim["simulation_id"])
            res = (await store.get_simulation(c, t, sim["simulation_id"]))["results"]
        assert {w["outcome"]["result"] for w in wfs} == {"APPROVED_NO_EXECUTION"} and not any(n.values()) and ledger == 1
        assert "execution_summary" not in res and "approved plans are not filled" in " ".join(res["limitations"])
    run(go())


def test_adp2_67_person_approves_before_and_after_open(pg_pool):
    async def go():
        t = tenant()
        m, gw = build(pg_pool)
        sim = await start(pg_pool, t, m, operating_mode=C.OperatingMode.ASSISTED)    # the stub Middle Office asks a person
        sid = sim["simulation_id"]
        for _ in range(3):                                                     # PREMARKET, SCAN, PROPOSALS
            await m.step(tenant_id=t, sid=sid, unit="PHASE", user_id="u")
        async with pg_pool.acquire() as c:
            pending = await store.list_approvals(c, t, pending_only=True, simulation_id=sid)
        assert pending, "the stub Middle Office did not ask for a person"
        row = await m.orch.decide(tenant_id=t, approval_id=pending[0]["approval_id"], decision="APPROVE", reason="ok", user_id="u")
        async with pg_pool.acquire() as c:
            it = dict(await c.fetchrow("SELECT * FROM autodesk.execution_intents WHERE simulation_id=$1", sid))
        assert it["status"] == "VALIDATED"
        await m.step(tenant_id=t, sid=sid, unit="PHASE", user_id="u")          # OPEN
        async with pg_pool.acquire() as c:
            fills = await c.fetchval("SELECT count(*) FROM autodesk.trade_fills WHERE simulation_id=$1", sid)
        assert fills == 1
    run(go())
