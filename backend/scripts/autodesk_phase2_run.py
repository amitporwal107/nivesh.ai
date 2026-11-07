"""Real-data check of Phase 2 paper execution (AD-P2-95..98). READ-ONLY on the data platform; all writes go to a FRESH
database on a THROWAWAY Postgres (AUTODESK_TEST_PG_URL). Nothing shared is written. Runs the REAL agents over a few past
sessions with the paper execution gateway twice with the same seed, compares the fingerprints, then re-reads each fill's
exchange row to check the fill against it. Prints one JSON document (no secrets).

  usage (container from the staging backend image, worktree mounted read-only, DaaS env passed in, network autodesk-test):
    python scripts/autodesk_phase2_run.py [--sessions 3] [--seed 42]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "autodesk_phase2_run")
os.environ.setdefault("OPENAI_API_KEY", "phase2-run-placeholder")
D = Decimal


def _j(x):
    return json.loads(json.dumps(x, default=str))


async def fresh_db(base: str) -> str:
    import asyncpg
    name = "adp2_" + uuid.uuid4().hex[:10]
    admin = await asyncpg.connect(base)
    await admin.execute(f'CREATE DATABASE "{name}"')
    await admin.close()
    return base.rsplit("/", 1)[0] + "/" + name


async def one_run(pool, start: date, end: date, seed: int, label: str) -> dict:
    from autodesk.agents.registry import default_agents
    from autodesk.contracts import SimulationConfig
    from autodesk.execution import adapters as ad
    from autodesk.execution.fill_model import DEFAULT_PARAMS
    from autodesk.execution.gateway import ExecutionGateway
    from autodesk.market.calendar import sessions_between
    from autodesk.market.pit import PitMarketView
    from autodesk.market.session_bars import PitSessionBars
    from autodesk.orchestrator.engine import Orchestrator
    from autodesk.simulator.manager import SimulationManager

    gw = ExecutionGateway(pool, sim=ad.SimulationPaperAdapter(PitSessionBars(), DEFAULT_PARAMS), params=DEFAULT_PARAMS)
    orch = Orchestrator(pool, default_agents(), lambda as_of: PitMarketView(as_of), task_deadline_s=60.0, execution=gw)
    m = SimulationManager(pool, orch, sessions_between, versions=lambda: {"run": label}, execution=gw)
    t = f"p2-run-{label}"
    sim = await m.create(tenant_id=t, cfg=SimulationConfig(name=f"phase2 {label}", start_date=start, end_date=end, seed=seed,
                                                           max_proposals_per_session=5, starting_capital_rs=D("10000000")),
                         user_id="phase2-run")
    sid = sim["simulation_id"]
    await m.start(tenant_id=t, sid=sid, user_id="phase2-run")
    t0 = time.monotonic()
    await m.run_to_end(tenant_id=t, sid=sid)
    res = await m.results(tenant_id=t, sid=sid)
    return {"tenant": t, "simulation_id": sid, "seconds": round(time.monotonic() - t0, 1), "results": res, "bars": gw.sim.bars}


async def verify_fills(pool, tenant: str, sid: str, bars) -> dict:
    """AD-P2-97: each fill against the exchange row read again."""
    from autodesk.execution import orders
    from autodesk.execution.fill_model import DEFAULT_PARAMS as P
    async with pool.acquire() as c:
        rows = await c.fetch(
            """SELECT f.fill_id, f.price, f.quantity, f.side, f.session_date, f.arrival_price, o.kind, o.underlying, o.expiry,
                      o.strike, o.lot_size, o.order_type, o.limit_price
               FROM autodesk.trade_fills f JOIN autodesk.trade_orders o USING (order_id) WHERE f.simulation_id=$1""", sid)
    checked, bad = 0, []
    for r in rows:
        ref = orders.leg_ref(dict(r))
        bar = await bars.bar(ref, r["session_date"], clock_session=r["session_date"])
        checked += 1
        if bar is None:
            bad.append({"fill": r["fill_id"], "why": "no exchange row"}); continue
        at_close = r["order_type"] == "LIMIT" and r["price"] == r["limit_price"] and r["arrival_price"] == r["limit_price"]
        if at_close:
            ok_px = bar.low is not None and bar.high is not None and bar.low <= r["price"] <= bar.high
        else:
            hs = r["arrival_price"] * P.half_spread_pct[r["kind"]] / 100
            hi = r["arrival_price"] + max(hs, D("0.05")) + r["arrival_price"] * P.slippage_bps[r["kind"]] * D(str(P.slippage_factor[1])) / D("10000") + D("0.10")
            ok_px = r["arrival_price"] == bar.open and (r["arrival_price"] <= r["price"] <= hi if r["side"] == "BUY" else r["price"] <= r["arrival_price"])
        cap = int(D(bar.traded_units) * P.participation_pct / 100)
        ok_q = r["quantity"] <= max(cap, r["lot_size"]) or at_close
        if not (ok_px and ok_q):
            bad.append({"fill": r["fill_id"], "price": str(r["price"]), "open": str(bar.open), "qty": r["quantity"], "cap": cap, "ok_px": ok_px, "ok_q": ok_q})
    async with pool.acquire() as c:
        legs = await c.fetch("SELECT l.kind, l.underlying, l.expiry, l.strike, l.mark_price, l.mark_source, l.marked_at, p.simulation_id "
                             "FROM autodesk.trade_position_legs l JOIN autodesk.trade_positions p USING (position_id) WHERE p.simulation_id=$1", sid)
        last = await c.fetchval("SELECT max(session_date) FROM autodesk.equity_snapshots WHERE simulation_id=$1", sid)
    marks_ok, marks_bad = 0, []
    for lg in legs:
        bar = await bars.bar(orders.leg_ref(dict(lg)), last, clock_session=last) if last else None
        if bar is not None and bar.close is not None and lg["mark_price"] == bar.close:
            marks_ok += 1
        elif lg["mark_source"] and "last mark kept" in lg["mark_source"]:
            marks_ok += 1                                                      # flagged stale, never shown as current
        else:
            marks_bad.append({"leg": f"{lg['kind']}:{lg['underlying']}", "mark": str(lg["mark_price"]), "close": str(bar.close) if bar else None})
    return {"fills_checked": checked, "fill_mismatches": bad[:10], "mismatch_count": len(bad), "legs_checked": len(legs),
            "marks_equal_closes": marks_ok, "mark_mismatches": marks_bad[:10]}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    from autodesk.db import create_pool_for, set_pool
    from autodesk.db.migrate import apply_pending
    from autodesk.market import calendar

    out: dict = {"started": datetime.now(timezone.utc)}
    out["calendar"] = await calendar.load_years([2025, 2026, 2027])
    dsn = await fresh_db(os.environ["AUTODESK_TEST_PG_URL"])
    pool = await create_pool_for(dsn)
    set_pool(pool)
    out["migrations"] = await apply_pending(pool)
    today = datetime.now(timezone.utc).date()
    past = await calendar.sessions_between(today - timedelta(days=20), today - timedelta(days=1))
    sessions = past[-(a.sessions + 1):-1]
    start, end = sessions[0], sessions[-1]
    out["sessions"] = [str(s) for s in sessions]
    runs = []
    for label in ("a", "b"):
        r = await one_run(pool, start, end, a.seed, label)
        es = r["results"].get("execution_summary") or {}
        runs.append({"label": label, "seconds": r["seconds"], "status": "COMPLETED", "signals": r["results"]["signals"]["total"],
                     "plans": r["results"]["plans"]["by_status"], "execution_summary": {k: es.get(k) for k in (
                         "trades", "net_pnl_rs", "max_drawdown_rs", "intents", "intents_refused", "orders", "orders_by_state", "fills",
                         "reservations", "fill_ratio", "rejection_rate", "reconciliation", "fingerprint")},
                     "capital": {k: (es.get("capital") or {}).get(k) for k in ("equity_rs", "cash_balance_rs", "used_margin_rs", "reserved_capital_rs",
                                                                              "deployed_notional_rs", "open_risk_rs", "fees_rs", "unrealized_gross_rs")},
                     "verify": await verify_fills(pool, r["tenant"], r["simulation_id"], r["bars"])})
        if label == "a":
            async with pool.acquire() as c:
                out["sample_fills"] = [_j(dict(x)) for x in await c.fetch(
                    """SELECT o.underlying, o.kind, o.side, o.order_type, o.limit_price, f.quantity, f.price, f.arrival_price, f.charges_rs, f.price_source, f.session_date
                       FROM autodesk.trade_fills f JOIN autodesk.trade_orders o USING (order_id) WHERE f.simulation_id=$1 ORDER BY f.fill_time LIMIT 6""",
                    r["simulation_id"])]
                out["intent_refusals"] = [_j(dict(x)) for x in await c.fetch(
                    "SELECT refusal_codes, count(*) AS n FROM autodesk.execution_intents WHERE simulation_id=$1 AND status='REFUSED' GROUP BY 1",
                    r["simulation_id"])]
    out["runs"] = runs
    fa, fb = (r["execution_summary"]["fingerprint"] for r in runs)
    out["AD-P2-96_same_seed_same_fingerprint"] = {"a": fa, "b": fb, "equal": fa == fb,
                                                  "net_pnl_equal": runs[0]["execution_summary"]["net_pnl_rs"] == runs[1]["execution_summary"]["net_pnl_rs"]}
    await pool.close()
    out["finished"] = datetime.now(timezone.utc)
    print(json.dumps(_j(out), indent=1, default=str))


if __name__ == "__main__":
    asyncio.run(main())
