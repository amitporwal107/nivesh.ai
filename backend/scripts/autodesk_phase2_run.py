"""Real-data check of Phase 2 paper execution (AD-P2-95..98). READ-ONLY on the data platform; all writes go to a FRESH
database on a THROWAWAY Postgres (AUTODESK_TEST_PG_URL). Nothing shared is written. Runs the REAL agents over a few past
sessions with the paper execution gateway twice with the same seed and once with another, compares the fingerprints, then
re-reads each fill's exchange row to check the fill against it. Prints one JSON document (no secrets).

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


async def verify_fills(pool, sid: str) -> dict:
    """AD-P2-97: each fill against the exchange row READ AGAIN through a new reader (no shared cache), each charge against the
    cost card, each mark against the last session's close, the cash balance against the fills."""
    from autodesk.execution import costs, orders
    from autodesk.execution.capital import balances
    from autodesk.execution.fill_model import DEFAULT_PARAMS as P
    from autodesk.market.session_bars import PitSessionBars
    bars = PitSessionBars()
    async with pool.acquire() as c:
        rows = await c.fetch(
            """SELECT f.fill_id, f.price, f.quantity, f.side, f.session_date, f.arrival_price, f.value_rs, f.charges_rs, f.fill_kind,
                      o.kind, o.underlying, o.expiry, o.strike, o.lot_size, o.order_type, o.limit_price, o.leg_id,
                      (SELECT count(*) FROM autodesk.trade_fills g WHERE g.order_id=f.order_id AND g.fill_time < f.fill_time) AS earlier
               FROM autodesk.trade_fills f JOIN autodesk.trade_orders o USING (order_id) WHERE f.simulation_id=$1""", sid)
    checked, bad = 0, []
    for r in rows:
        bar = await bars.bar(orders.leg_ref(dict(r)), r["session_date"], clock_session=r["session_date"])
        checked += 1
        if bar is None:
            bad.append({"fill": r["fill_id"], "why": "no exchange row"})
            continue
        passive = r["arrival_price"] == r["limit_price"] and r["price"] == r["limit_price"]
        if passive:                                    # a resting limit: price must have traded THROUGH it
            ok_px = bar.low < r["price"] if r["side"] == "BUY" else bar.high > r["price"]
        else:                                          # at the open: the contract's own open, moved against the order only
            hs = max(r["arrival_price"] * P.half_spread_pct[r["kind"]] / 100, D("0.05") if r["kind"] in ("CE", "PE") else D("0"))
            slip = r["arrival_price"] * P.slippage_bps[r["kind"]] * D(str(P.slippage_factor[1])) / D("10000")
            room = hs + slip + D("0.05")
            ok_px = r["arrival_price"] == bar.open and (
                r["arrival_price"] < r["price"] <= r["arrival_price"] + room if r["side"] == "BUY"
                else r["arrival_price"] - room <= r["price"] < r["arrival_price"])
        cap = int(D(bar.traded_units) * P.participation_pct / 100)
        ok_q = r["quantity"] <= cap and r["quantity"] % r["lot_size"] == 0
        ok_v = r["value_rs"] == (r["price"] * r["quantity"]).quantize(D("0.01"))
        card = costs.charges(r["kind"], r["side"], r["value_rs"], first_fill=r["earlier"] == 0)["total"]
        ok_c = r["charges_rs"] == card and r["fill_kind"] == "SIMULATED"
        ok_t = bar.traded and (bar.lot_size is None or bar.lot_size == r["lot_size"])
        if not (ok_px and ok_q and ok_v and ok_c and ok_t):
            bad.append({"fill": r["fill_id"], "underlying": r["underlying"], "price": str(r["price"]), "open": str(bar.open),
                        "qty": r["quantity"], "cap": cap, "price_ok": ok_px, "qty_ok": ok_q, "value_ok": ok_v, "charges_ok": ok_c,
                        "traded_ok": ok_t})
    async with pool.acquire() as c:
        legs = await c.fetch("SELECT l.kind, l.underlying, l.expiry, l.strike, l.mark_price, l.mark_source, l.mark_stale "
                             "FROM autodesk.trade_position_legs l JOIN autodesk.trade_positions p USING (position_id) "
                             "WHERE p.simulation_id=$1", sid)
        last = await c.fetchval("SELECT max(session_date) FROM autodesk.equity_snapshots WHERE simulation_id=$1", sid)
        acct = await c.fetchrow("SELECT account_id, tenant_id, starting_capital_rs FROM autodesk.accounts WHERE simulation_id=$1", sid)
        v = await balances(c, acct["tenant_id"], acct["account_id"])
        by_fills = await c.fetchrow(
            """SELECT COALESCE(sum(CASE WHEN o.kind='FUT' THEN 0 WHEN f.side='BUY' THEN -f.value_rs ELSE f.value_rs END),0) AS flow,
                      COALESCE(sum(f.charges_rs),0) AS charges, COALESCE(sum(f.value_rs),0) AS value
               FROM autodesk.trade_fills f JOIN autodesk.trade_orders o USING (order_id) WHERE f.simulation_id=$1""", sid)
    marks_ok, stale, marks_bad = 0, 0, []
    for lg in legs:
        bar = await bars.bar(orders.leg_ref(dict(lg)), last, clock_session=last)
        if lg["mark_stale"]:
            stale += 1                                 # flagged: never shown as current
        elif bar is not None and bar.traded and lg["mark_price"] == bar.close:
            marks_ok += 1
        else:
            marks_bad.append({"leg": f"{lg['kind']}:{lg['underlying']}", "mark": str(lg["mark_price"]), "close": str(bar.close) if bar else None})
    cash_expected = acct["starting_capital_rs"] + by_fills["flow"] - by_fills["charges"]
    return {"fills_checked": checked, "fill_mismatches": bad[:10], "mismatch_count": len(bad), "legs_checked": len(legs),
            "marks_equal_last_close": marks_ok, "marks_flagged_stale": stale, "mark_mismatches": marks_bad[:10],
            "cash_from_fills": {"expected_rs": cash_expected, "ledger_rs": v.cash_balance_rs, "difference_rs": cash_expected - v.cash_balance_rs},
            "charges_from_fills": {"fills_rs": by_fills["charges"], "ledger_rs": v.fees_rs},
            "notional_from_fills": {"fills_rs": by_fills["value"], "ledger_rs": v.deployed_notional_rs}}


async def no_look_ahead(pool, tenant: str, sid: str, bars) -> dict:
    """AD-P2-64 and AD-72 on real data: the fill engine read only the clock's session, and no agent read reached data published
    after its task's simulated time. `previous_session` is left out of the published-data rule: it reads the holiday calendar
    only, for the session being prepared (market/pit.py), so its `day` is not market data. It is counted separately."""
    from autodesk.market.view import published_at
    wrong = [r for r in bars.reads if r[1] != r[2]]
    bad, n, calendar_only = [], 0, 0
    async with pool.acquire() as c:
        rows = await c.fetch("SELECT task_id, task_type, sim_time, tool_calls FROM autodesk.agent_tasks WHERE tenant_id=$1 AND simulation_id=$2",
                             tenant, sid)
    for row in rows:
        for tc in row["tool_calls"] or []:
            n += 1
            asof = datetime.fromisoformat(str(tc.get("as_of")).replace("Z", "+00:00")) if tc.get("as_of") else None
            if row["sim_time"] and asof and asof != row["sim_time"]:
                bad.append({"tool": tc["tool"], "why": "as_of differs from the task's sim_time"})
            day = (tc.get("args") or {}).get("day")
            if tc["tool"] == "previous_session":
                calendar_only += 1
            elif day and asof:
                kind = "fno" if tc["tool"] in ("fno_universe", "fno_buildup", "futures", "options", "expiries", "lot_size") else "cash"
                if published_at(date.fromisoformat(day), kind) > asof:
                    bad.append({"tool": tc["tool"], "day": day, "as_of": str(asof)})
            if not tc.get("ok", True) and "LookAhead" in str(tc.get("error")):
                bad.append({"tool": tc["tool"], "why": tc.get("error")})
    return {"fill_engine_reads": len(bars.reads), "reads_outside_the_clock_session": len(wrong),
            "agent_tool_calls_checked": n, "calendar_only_calls": calendar_only, "agent_look_ahead_violations": bad[:10],
            "violation_count": len(bad)}


async def detail(pool, sid: str) -> dict:
    """What happened, plan by plan: for the report. Prices and costs as stored."""
    async with pool.acquire() as c:
        orders_ = await c.fetch(
            """SELECT o.session_date, o.underlying, p.strategy_type, o.leg_id, o.kind, o.strike, o.side, o.quantity, o.lot_size, o.order_type,
                      o.limit_price, o.ref_price, o.state, o.filled_qty, o.avg_fill_price, o.reject_code, o.reject_reason
               FROM autodesk.trade_orders o JOIN autodesk.trade_plans p USING (trade_id) WHERE o.simulation_id=$1
               ORDER BY o.session_date, o.underlying, o.leg_id""", sid)
        res = await c.fetch("""SELECT status, count(*) AS n, sum(amount_rs) AS amount, sum(consumed_rs) AS consumed, sum(released_rs) AS released
                               FROM autodesk.capital_reservations WHERE simulation_id=$1 GROUP BY status""", sid)
        led = await c.fetch("SELECT entry_type, count(*) AS n, sum(cash_delta_rs) AS cash, sum(reserved_delta_rs) AS reserved, sum(margin_delta_rs) AS margin, "
                            "sum(fees_delta_rs) AS fees FROM autodesk.capital_ledger_entries WHERE simulation_id=$1 GROUP BY entry_type ORDER BY entry_type", sid)
        hist = await c.fetch("SELECT e.to_state, count(*) AS n FROM autodesk.trade_order_events e JOIN autodesk.trade_orders o USING (order_id) "
                             "WHERE o.simulation_id=$1 GROUP BY e.to_state ORDER BY e.to_state", sid)
        jour = await c.fetch("SELECT kind, count(*) AS n FROM autodesk.trade_journal_entries WHERE simulation_id=$1 GROUP BY kind ORDER BY kind", sid)
        one = await c.fetchval("SELECT trade_id FROM autodesk.trade_fills WHERE simulation_id=$1 ORDER BY fill_time LIMIT 1", sid)
        chain = await c.fetch("SELECT kind, summary FROM autodesk.trade_journal_entries WHERE trade_id=$1 ORDER BY seq", one) if one else []
        wf = await c.fetch("SELECT session_date, outcome->>'result' AS result, count(*) AS n FROM autodesk.workflows WHERE simulation_id=$1 "
                           "AND kind='TRADE_PROPOSAL' GROUP BY 1,2 ORDER BY 1,2", sid)
        no_trade = await c.fetch("SELECT session_date, outcome->'reasons' AS reasons FROM autodesk.workflows WHERE simulation_id=$1 "
                                 "AND kind='TRADE_PROPOSAL' AND outcome->>'result'='NO_TRADE' ORDER BY session_date LIMIT 8", sid)
    return _j({"orders": [dict(r) for r in orders_], "reservations": [dict(r) for r in res], "ledger": [dict(r) for r in led],
               "order_history": [dict(r) for r in hist], "journal_kinds": [dict(r) for r in jour],
               "journal_chain_of_first_trade": [dict(r) for r in chain], "proposal_results": [dict(r) for r in wf],
               "no_trade_reasons": [dict(r) for r in no_trade]})


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
    for label, seed in (("a", a.seed), ("b", a.seed), ("other-seed", a.seed + 1)):
        r = await one_run(pool, start, end, seed, label)
        es = r["results"].get("execution_summary") or {}
        runs.append({"label": label, "seed": seed, "seconds": r["seconds"], "status": r["results"]["status"],
                     "signals": r["results"]["signals"]["total"], "plans": r["results"]["plans"]["by_status"],
                     "execution_summary": {k: es.get(k) for k in (
                         "trades", "net_pnl_rs", "max_drawdown_rs", "max_drawdown_pct", "seed", "intents", "intents_refused", "orders",
                         "orders_by_state", "reject_codes", "fills", "reservations", "fill_ratio", "rejection_rate", "reconciliation",
                         "fingerprint", "cost_model")},
                     "capital": {k: (es.get("capital") or {}).get(k) for k in (
                         "equity_rs", "cash_balance_rs", "used_margin_rs", "available_cash_rs", "reserved_capital_rs",
                         "available_buying_power_rs", "deployed_notional_rs", "open_risk_rs", "pending_risk_rs",
                         "pending_order_commitment_rs", "realized_gross_rs", "fees_rs", "net_realized_rs", "unrealized_gross_rs", "net_pnl_rs")},
                     "pnl_daily": (es.get("pnl") or {}).get("daily"), "pnl_by_strategy": (es.get("pnl") or {}).get("by_strategy"),
                     "charges_by_component": (es.get("pnl") or {}).get("charges_by_component"),
                     "spread_rs": (es.get("pnl") or {}).get("spread_rs"), "slippage_rs": (es.get("pnl") or {}).get("slippage_rs"),
                     "verify": await verify_fills(pool, r["simulation_id"]),
                     "no_look_ahead": await no_look_ahead(pool, r["tenant"], r["simulation_id"], r["bars"])})
        if label == "a":
            out["detail_run_a"] = await detail(pool, r["simulation_id"])
    out["runs"] = runs
    fa, fb, fo = (r["execution_summary"]["fingerprint"] for r in runs)
    out["AD-P2-96_same_seed"] = {"a": fa, "b": fb, "equal": fa == fb,
                                 "net_pnl_equal": runs[0]["execution_summary"]["net_pnl_rs"] == runs[1]["execution_summary"]["net_pnl_rs"]}
    out["other_seed"] = {"seed": a.seed + 1, "fingerprint": fo, "differs": fo != fa, "net_pnl_rs": runs[2]["execution_summary"]["net_pnl_rs"]}
    await pool.close()
    out["finished"] = datetime.now(timezone.utc)
    print(json.dumps(_j(out), indent=1, default=str))


if __name__ == "__main__":
    asyncio.run(main())
