"""Read side of Phase 2 (PHASE2_DESIGN §9): the capital view, P&L, a simulation's execution summary, the determinism
fingerprint. Money is returned as strings; nothing here writes."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time as dtime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from .. import store
from ..market.view import IST
from . import costs
from . import fill_model as fm
from .capital import CapitalView, balances, rs

ZERO = Decimal("0")
MARK_MAX_AGE_S = 120.0       # during a live session a mark older than this is shown as stale


def _s(v: Any) -> Any:
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _s(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_s(x) for x in v]
    return v


def view_json(v: CapitalView) -> dict:
    d = v.to_dict()
    d["reconciliation"] = v.reconciliation()
    d["marks"] = {"as_of": v.marks_as_of, "stale_legs": v.stale_legs}
    d.pop("stale_legs", None)
    d.pop("marks_as_of", None)
    return _s(d)


def in_market_hours(now: datetime) -> bool:
    t = now.astimezone(IST)
    return t.weekday() < 5 and dtime(9, 15) <= t.time() <= dtime(15, 30)


async def capital_view(c, tenant_id: str, account_id: str, now: Optional[datetime] = None) -> dict:
    """The §9.2 measures. On the live desk, while the market is open, a mark older than MARK_MAX_AGE_S is listed as stale."""
    now = now or datetime.now(timezone.utc)
    v = await balances(c, tenant_id, account_id)
    acc = await store.get_account(c, tenant_id, account_id)
    if acc["simulation_id"] is None and in_market_hours(now):
        listed = {(x["trade_id"], x["leg_id"]) for x in v.stale_legs}
        for lg in await c.fetch(
                """SELECT p.trade_id, l.leg_id, l.underlying, l.marked_at FROM autodesk.trade_position_legs l
                   JOIN autodesk.trade_positions p USING (position_id)
                   WHERE p.account_id=$1 AND p.tenant_id=$2 AND p.status='OPEN' AND l.marked_at < $3""",
                account_id, tenant_id, now - timedelta(seconds=MARK_MAX_AGE_S)):
            if (lg["trade_id"], lg["leg_id"]) not in listed:
                v.stale_legs.append(dict(lg))
    return view_json(v)


async def charges_by_component(c, tenant_id: str, account_id: str) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for r in await c.fetch("SELECT charges FROM autodesk.trade_fills WHERE tenant_id=$1 AND account_id=$2", tenant_id, account_id):
        for k, v in (r["charges"] or {}).items():
            if k != "total":
                out[k] = out.get(k, ZERO) + Decimal(str(v))
    return out


async def drawdown(c, account_id: str, start: Decimal) -> tuple[Decimal, Decimal, list[dict]]:
    """Maximum drawdown from the opening capital and the session snapshots; daily and cumulative P&L per session."""
    peak, worst, worst_pct, prev = start, ZERO, ZERO, start
    daily: list[dict] = []
    for r in await c.fetch("SELECT session_date, equity_rs, net_pnl_rs FROM autodesk.equity_snapshots WHERE account_id=$1 "
                           "ORDER BY session_date", account_id):
        eq = r["equity_rs"]
        peak = max(peak, eq)
        dd = eq - peak
        if dd < worst:
            worst, worst_pct = dd, (dd / peak * 100) if peak else ZERO
        daily.append({"session_date": r["session_date"], "equity_rs": eq, "day_pnl_rs": eq - prev, "cumulative_pnl_rs": eq - start})
        prev = eq
    return worst, worst_pct.quantize(Decimal("0.01")), daily


async def pnl(c, tenant_id: str, account_id: str) -> dict:
    acc = await store.get_account(c, tenant_id, account_id)
    v = await balances(c, tenant_id, account_id)
    start = Decimal(str(acc["starting_capital_rs"]))
    slip = await c.fetchrow("SELECT COALESCE(sum(slippage_rs),0) AS slip, COALESCE(sum(spread_rs),0) AS spread "
                            "FROM autodesk.trade_fills WHERE tenant_id=$1 AND account_id=$2", tenant_id, account_id)
    by_strategy: dict[str, Decimal] = {}
    for r in await c.fetch(
            """SELECT p.strategy_type, COALESCE(sum(l.unrealized_rs - l.charges_rs),0) AS net
               FROM autodesk.trade_positions p JOIN autodesk.trade_position_legs l USING (position_id)
               WHERE p.tenant_id=$1 AND p.account_id=$2 GROUP BY p.strategy_type""", tenant_id, account_id):
        by_strategy[r["strategy_type"]] = r["net"]
    worst, worst_pct, daily = await drawdown(c, account_id, start)
    return _s({"account_id": account_id, "gross_realized_rs": v.realized_gross_rs, "gross_unrealized_rs": v.unrealized_gross_rs,
               "charges_rs": v.fees_rs, "charges_by_component": await charges_by_component(c, tenant_id, account_id),
               "slippage_rs": slip["slip"], "spread_rs": slip["spread"], "net_realized_rs": v.net_realized_rs,
               "net_unrealized_rs": v.unrealized_gross_rs, "net_pnl_rs": v.net_pnl_rs, "by_strategy": by_strategy,
               "daily": daily, "max_drawdown_rs": -worst if worst else ZERO, "max_drawdown_pct": -worst_pct if worst_pct else ZERO,
               "note": "realized P&L arrives with position closing in Phase 3; unrealized is marked at the session close or the live quote"})


async def fingerprint(c, simulation_id: str) -> str:
    """sha256 of the id-free canonical rows of every order, fill, position leg and session snapshot: the same seed gives the
    same value, so equal fingerprints mean equal prices, quantities, costs, marks and P&L."""
    orders = await c.fetch("SELECT session_date, kind, underlying, expiry, strike, side, leg_id, quantity, order_type, limit_price, "
                           "state, filled_qty, avg_fill_price, reject_code FROM autodesk.trade_orders WHERE simulation_id=$1", simulation_id)
    fills = await c.fetch(
        """SELECT f.session_date, o.kind, o.underlying, o.expiry, o.strike, f.side, f.leg_id, f.quantity, f.price,
                  f.arrival_price, f.charges_rs, f.spread_rs, f.slippage_rs, f.latency_ms, f.fill_time
           FROM autodesk.trade_fills f JOIN autodesk.trade_orders o USING (order_id) WHERE f.simulation_id=$1""", simulation_id)
    legs = await c.fetch(
        """SELECT p.instrument, p.strategy_type, p.open_risk_rs, p.capital_rs, p.margin_rs, l.leg_id, l.kind, l.side, l.quantity,
                  l.avg_price, l.cost_value_rs, l.charges_rs, l.mark_price, l.mark_stale, l.unrealized_rs
           FROM autodesk.trade_position_legs l JOIN autodesk.trade_positions p USING (position_id)
           WHERE p.simulation_id=$1""", simulation_id)
    snaps = await c.fetch("""SELECT session_date, equity_rs, cash_balance_rs, used_margin_rs, reserved_rs, notional_rs, open_risk_rs,
                                    fees_rs, unrealized_gross_rs, net_pnl_rs, stale_legs
                             FROM autodesk.equity_snapshots WHERE simulation_id=$1""", simulation_id)

    def canon(rows):
        return sorted(json.dumps([_s(x) for x in r.values()], sort_keys=True) for r in rows)
    return hashlib.sha256(json.dumps({"orders": canon(orders), "fills": canon(fills), "legs": canon(legs),
                                      "snapshots": canon(snaps)}).encode()).hexdigest()


async def execution_summary(c, tenant_id: str, simulation_id: str, params: Optional[fm.FillParams] = None) -> dict:
    acct = await c.fetchrow("SELECT account_id FROM autodesk.accounts WHERE tenant_id=$1 AND simulation_id=$2", tenant_id, simulation_id)
    if acct is None:
        return {}
    aid = acct["account_id"]
    n = lambda sql: c.fetchval(sql, simulation_id)                                                    # noqa: E731
    orders_total = await n("SELECT count(*) FROM autodesk.trade_orders WHERE simulation_id=$1")
    orders_filled = await n("SELECT count(*) FROM autodesk.trade_orders WHERE simulation_id=$1 AND state='FILLED'")
    orders_rejected = await n("SELECT count(*) FROM autodesk.trade_orders WHERE simulation_id=$1 AND state='REJECTED'")
    by_state = {r["state"]: r["n"] for r in await c.fetch(
        "SELECT state, count(*) AS n FROM autodesk.trade_orders WHERE simulation_id=$1 GROUP BY state", simulation_id)}
    v = await balances(c, tenant_id, aid)
    p = await pnl(c, tenant_id, aid)
    trades = await n("SELECT count(*) FROM autodesk.trade_positions WHERE simulation_id=$1")
    return _s({
        "trades": trades, "net_pnl_rs": v.net_pnl_rs, "max_drawdown_rs": p["max_drawdown_rs"], "max_drawdown_pct": p["max_drawdown_pct"],
        "seed": await c.fetchval("SELECT (config->>'seed')::int FROM autodesk.simulations WHERE simulation_id=$1", simulation_id),
        "reject_codes": {r["reject_code"]: r["n"] for r in await c.fetch(
            "SELECT reject_code, count(*) AS n FROM autodesk.trade_orders WHERE simulation_id=$1 AND reject_code IS NOT NULL "
            "GROUP BY reject_code", simulation_id)},
        "intents": await n("SELECT count(*) FROM autodesk.execution_intents WHERE simulation_id=$1"),
        "intents_refused": await n("SELECT count(*) FROM autodesk.execution_intents WHERE simulation_id=$1 AND status='REFUSED'"),
        "orders": orders_total, "orders_by_state": by_state,
        "fills": await n("SELECT count(*) FROM autodesk.trade_fills WHERE simulation_id=$1"),
        "reservations": await n("SELECT count(*) FROM autodesk.capital_reservations WHERE simulation_id=$1"),
        "positions": trades, "capital": view_json(v), "pnl": p,
        "fill_ratio": str((Decimal(orders_filled) / orders_total).quantize(Decimal("0.0001"))) if orders_total else None,
        "rejection_rate": str((Decimal(orders_rejected) / orders_total).quantize(Decimal("0.0001"))) if orders_total else None,
        "fill_model": (params or fm.DEFAULT_PARAMS).describe(), "cost_model": costs.COST_MODEL,
        "reconciliation": v.reconciliation(), "fingerprint": await fingerprint(c, simulation_id),
        "labels": "every fill is simulated; none is broker-confirmed",
    })


def mark_age(leg: dict, now: Optional[datetime] = None, *, live: bool = False) -> dict:
    """Age of a mark. While the market is open an old mark on the live desk is flagged, not presented as current."""
    now = now or datetime.now(timezone.utc)
    at = leg.get("marked_at")
    age = (now - at).total_seconds() if at else None
    old = live and in_market_hours(now) and age is not None and age > MARK_MAX_AGE_S
    return {"mark_age_s": age, "mark_stale": bool(leg.get("mark_stale")) or old}
