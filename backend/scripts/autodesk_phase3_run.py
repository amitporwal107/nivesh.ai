"""Real-data check of Phase 3A (AD-P3-90..94). READ-ONLY on the data platform; every write goes to a FRESH database on a
THROWAWAY Postgres (AUTODESK_TEST_PG_URL). Runs the REAL agents over N past sessions with paper execution AND the lifecycle
manager, twice with the same seed and once with another, then checks: every reconciliation run 0.00, fingerprints, the fill
engine's read log, the agents' reads, and EVERY closing against the exchange row READ AGAIN through a new reader. Prints one
JSON document (no secrets).

  usage (container from the staging backend image, worktree mounted read-only, data API env passed in, network autodesk-test):
    python scripts/autodesk_phase3_run.py --start 2026-10-05 --end 2026-11-06 [--seed 42]
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import sys
import time
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "autodesk_phase3_run")
os.environ.setdefault("OPENAI_API_KEY", "phase3-run-placeholder")
D = Decimal

_spec = importlib.util.spec_from_file_location("p2run", os.path.join(os.path.dirname(os.path.abspath(__file__)), "autodesk_phase2_run.py"))
p2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(p2)


def _j(x):
    return json.loads(json.dumps(x, default=str))


async def one_run(pool, start: date, end: date, seed: int, label: str) -> dict:
    from autodesk.agents.registry import default_agents
    from autodesk.contracts import SimulationConfig
    from autodesk.execution import adapters as ad
    from autodesk.execution.fill_model import DEFAULT_PARAMS
    from autodesk.execution.gateway import ExecutionGateway
    from autodesk.lifecycle.manager import LifecycleManager, pit_history
    from autodesk.market.calendar import sessions_between
    from autodesk.market.pit import PitMarketView
    from autodesk.market.session_bars import PitSessionBars
    from autodesk.orchestrator.engine import Orchestrator
    from autodesk.simulator.manager import SimulationManager

    factory = lambda as_of: PitMarketView(as_of)                                                   # noqa: E731
    lc = LifecycleManager(pool, params=DEFAULT_PARAMS, history=pit_history(factory))
    gw = ExecutionGateway(pool, sim=ad.SimulationPaperAdapter(PitSessionBars(), DEFAULT_PARAMS), params=DEFAULT_PARAMS, lifecycle=lc)
    orch = Orchestrator(pool, default_agents(), factory, task_deadline_s=60.0, execution=gw)
    m = SimulationManager(pool, orch, sessions_between, versions=lambda: {"run": label}, execution=gw)
    t = f"p3-run-{label}"
    sim = await m.create(tenant_id=t, cfg=SimulationConfig(name=f"phase3 {label}", start_date=start, end_date=end, seed=seed,
                                                           max_proposals_per_session=5, starting_capital_rs=D("10000000")),
                         user_id="phase3-run")
    sid = sim["simulation_id"]
    await m.start(tenant_id=t, sid=sid, user_id="phase3-run")
    t0 = time.monotonic()
    await m.run_to_end(tenant_id=t, sid=sid)
    res = await m.results(tenant_id=t, sid=sid)
    return {"tenant": t, "simulation_id": sid, "seconds": round(time.monotonic() - t0, 1), "results": res, "bars": gw.sim.bars,
            "history_reads": lc.history_reads}


async def verify_closings(pool, sid: str) -> dict:
    """Every closing fill and settlement against the exchange row read again (new reader, no shared cache)."""
    from autodesk.execution import costs
    from autodesk.execution.fill_model import DEFAULT_PARAMS as P
    from autodesk.market.session_bars import LegRef, PitSessionBars
    bars = PitSessionBars()
    async with pool.acquire() as c:
        fills = await c.fetch(
            """SELECT f.fill_id, f.price, f.quantity, f.side, f.session_date, f.arrival_price, f.value_rs, f.charges_rs, f.fill_kind,
                      o.kind, o.underlying, o.expiry, o.strike, o.lot_size, o.leg_id, o.trade_id, o.close_reason,
                      r.how, r.level, r.trigger_price, p.instrument,
                      (SELECT count(*) FROM autodesk.trade_fills g WHERE g.order_id=f.order_id AND g.fill_time < f.fill_time) AS earlier
               FROM autodesk.trade_fills f JOIN autodesk.trade_orders o USING (order_id)
               JOIN autodesk.trade_exit_records r ON r.intent_id = f.intent_id
               JOIN autodesk.trade_positions p ON p.trade_id = o.trade_id
               WHERE f.simulation_id=$1 AND o.purpose='CLOSE' ORDER BY f.session_date, o.trade_id, o.leg_id""", sid)
        settles = await c.fetch("""SELECT r.*, p.instrument FROM autodesk.trade_exit_records r JOIN autodesk.trade_positions p
                                   USING (position_id) WHERE r.simulation_id=$1 AND r.how='settlement'""", sid)
    bad, checked, examples = [], 0, []
    for r in fills:
        ref = LegRef(kind=r["kind"], underlying=r["underlying"], expiry=r["expiry"], strike=r["strike"])
        b = await bars.bar(ref, r["session_date"], clock_session=r["session_date"])
        checked += 1
        if b is None:
            bad.append({"fill": r["fill_id"], "why": "no exchange row"})
            continue
        how = r["how"]
        arrival_ok = {"open": r["arrival_price"] == b.open, "close": r["arrival_price"] == b.close,
                      "level": r["level"] is not None and r["arrival_price"] == min(max(r["level"], b.low), b.high),
                      "objective": r["level"] is not None and r["price"] >= r["level"] and (b.high > r["price"] if r["side"] == "SELL" else b.low < r["price"])
                      }.get(how, False)
        inside = b.low <= r["price"] <= b.high
        adverse = r["price"] <= r["arrival_price"] if r["side"] == "SELL" else r["price"] >= r["arrival_price"]
        cap = int(D(b.traded_units) * P.participation_pct / 100)
        q_ok = r["quantity"] <= cap and r["quantity"] % r["lot_size"] == 0
        v_ok = r["value_rs"] == (r["price"] * r["quantity"]).quantize(D("0.01"))
        card = costs.charges(r["kind"], r["side"], r["value_rs"], first_fill=r["earlier"] == 0)["total"]
        c_ok = r["charges_rs"] == card and r["fill_kind"] == "SIMULATED"
        row = {"fill": r["fill_id"], "session": r["session_date"], "instrument": r["instrument"], "leg": f"{r['kind']} {r['strike'] or ''}".strip(),
               "reason": r["close_reason"], "how": how, "level": r["level"], "side": r["side"], "qty": r["quantity"], "price": r["price"],
               "arrival": r["arrival_price"], "row": {"open": b.open, "high": b.high, "low": b.low, "close": b.close, "units": b.traded_units},
               "value_rs": r["value_rs"], "charges_rs": r["charges_rs"], "card_charges_rs": card}
        if not (arrival_ok and inside and adverse and q_ok and v_ok and c_ok and b.traded):
            bad.append({**row, "arrival_ok": arrival_ok, "inside": inside, "adverse": adverse, "qty_ok": q_ok, "value_ok": v_ok,
                        "charges_ok": c_ok, "traded": b.traded})
        elif len(examples) < 12:
            examples.append(row)
    s_bad = []
    for s in settles:
        for lg in s["legs"]:
            if lg["kind"] == "FUT":
                fb = await bars.bar(LegRef("FUT", s["instrument"], s["session_date"]), s["session_date"], clock_session=s["session_date"])
                ok = fb is not None and fb.settle == D(lg["price"])
            else:
                ub = await bars.bar(LegRef("EQ", s["instrument"]), s["session_date"], clock_session=s["session_date"])
                ok = ub is not None and ub.close is not None
            if not ok:
                s_bad.append({"record": s["record_id"], "leg": lg})
    return {"closing_fills_checked": checked, "closing_mismatches": bad[:10], "mismatch_count": len(bad), "examples": examples,
            "settlements": len(settles), "settlement_mismatches": s_bad}


async def books(pool, tenant: str, sid: str) -> dict:
    from autodesk.lifecycle import recon
    async with pool.acquire() as c:
        acct = await c.fetchrow("SELECT account_id FROM autodesk.accounts WHERE simulation_id=$1", sid)
        now = await recon.account_checks(c, tenant, acct["account_id"])
        runs = await c.fetchrow("""SELECT count(*) AS runs, count(*) FILTER (WHERE NOT ok) AS failed,
                                          max((SELECT max(abs((x->>'difference_rs')::numeric)) FROM jsonb_array_elements(checks) x)) AS worst
                                   FROM autodesk.reconciliation_runs WHERE simulation_id=$1""", sid)
        states = await c.fetch("SELECT lifecycle_state, status, count(*) AS n FROM autodesk.trade_positions WHERE simulation_id=$1 GROUP BY 1,2", sid)
        flags = await c.fetch("SELECT trade_id, instrument, flags FROM autodesk.trade_positions WHERE simulation_id=$1 AND flags <> '[]'::jsonb", sid)
        closed = await c.fetch(
            """SELECT p.instrument, p.strategy_type, p.close_reason, p.opened_at, p.closed_at, p.realized_gross_rs, p.closing_charges_rs,
                      (SELECT sum(charges_rs) FROM autodesk.trade_position_legs l WHERE l.position_id=p.position_id) AS opening_charges,
                      (x.state->>'sessions_held')::int AS held
               FROM autodesk.trade_positions p LEFT JOIN autodesk.trade_exit_state x USING (trade_id)
               WHERE p.simulation_id=$1 AND p.status='CLOSED' ORDER BY p.closed_at, p.instrument""", sid)
        moves = await c.fetchval("SELECT count(*) FROM autodesk.trade_lifecycle_events WHERE simulation_id=$1", sid)
        levels = await c.fetchval("SELECT count(*) FROM autodesk.events WHERE simulation_id=$1 AND event_type='LEVEL_TIGHTENED'", sid)
        lim = await c.fetch("SELECT payload FROM autodesk.events WHERE simulation_id=$1 AND event_type='LIMIT_BREACHED'", sid)
    return _j({"checks_now": now, "all_zero_now": all(k["ok"] for k in now), "reconciliation_runs": dict(runs),
               "states": [dict(r) for r in states], "flags": [dict(r) for r in flags][:20], "closed": [dict(r) for r in closed],
               "lifecycle_moves": moves, "trail_moves": levels, "limit_breaches": [r["payload"] for r in lim]})


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-10-05")
    ap.add_argument("--end", default="2026-11-06")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--runs", default="a,b,other-seed")
    a = ap.parse_args()
    from autodesk.db import create_pool_for, set_pool
    from autodesk.db.migrate import apply_pending
    from autodesk.market import calendar

    out: dict = {"started": datetime.now(timezone.utc)}
    out["calendar"] = await calendar.load_years([2025, 2026, 2027])
    dsn = await p2.fresh_db(os.environ["AUTODESK_TEST_PG_URL"])
    pool = await create_pool_for(dsn)
    set_pool(pool)
    out["migrations"] = await apply_pending(pool)
    start, end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    sessions = await calendar.sessions_between(start, end)
    out["sessions"] = [str(s) for s in sessions]
    out["session_count"] = len(sessions)
    runs = []
    plan = [(x, a.seed + (1 if x == "other-seed" else 0)) for x in a.runs.split(",")]
    for label, seed in plan:
        r = await one_run(pool, start, end, seed, label)
        es = r["results"].get("execution_summary") or {}
        item = {"label": label, "seed": seed, "seconds": r["seconds"], "status": r["results"]["status"],
                "signals": r["results"]["signals"]["total"], "plans": r["results"]["plans"]["by_status"],
                "execution_summary": {k: es.get(k) for k in (
                    "trades", "closed_trades", "open_positions", "win_rate", "net_pnl_rs", "realized_gross_rs", "realized_net_rs",
                    "max_drawdown_rs", "max_drawdown_pct", "exits_by_reason", "lifecycle", "reconciliation_runs", "intents",
                    "intents_refused", "orders", "orders_by_state", "reject_codes", "fills", "reconciliation", "fingerprint")},
                "history_reads": {"count": len(r["history_reads"]), "symbols": len({x[0] for x in r["history_reads"]})},
                "no_look_ahead": await p2.no_look_ahead(pool, r["tenant"], r["simulation_id"], r["bars"]),
                "books": await books(pool, r["tenant"], r["simulation_id"])}
        if label == "a":
            item["verify_closings"] = await verify_closings(pool, r["simulation_id"])
            item["limitations"] = r["results"].get("limitations")
        runs.append(item)
        print(json.dumps({"progress": label, "seconds": r["seconds"], "status": item["status"],
                          "closed": item["execution_summary"].get("closed_trades")}, default=str), file=sys.stderr, flush=True)
    out["runs"] = runs
    fps = {r["label"]: r["execution_summary"]["fingerprint"] for r in runs}
    if "a" in fps and "b" in fps:
        out["AD-P3-92_same_seed"] = {"a": fps["a"], "b": fps["b"], "equal": fps["a"] == fps["b"]}
    if "a" in fps and "other-seed" in fps:
        out["AD-P3-92_other_seed"] = {"fingerprint": fps["other-seed"], "differs": fps["other-seed"] != fps["a"]}
    await pool.close()
    out["finished"] = datetime.now(timezone.utc)
    print(json.dumps(_j(out), indent=1, default=str))


if __name__ == "__main__":
    asyncio.run(main())
