"""The paper P&L dashboard with Scanner-to-Paper Trading (SPT) positions (services/paper_pnl/{book,dashboard,timeseries}.py,
routes/desk_pnl.py; 5 Nov 2026).

The SPT position documents here are built by slice C's OWN functions (services/spt/paper/positions.new_position,
entry_fill_fields, exit_fill_fields) from fills priced by C's cost card (execution.fill_costs), so every figure the
dashboard shows is checked against C's own arithmetic (its realised P&L and its display mark), not against numbers
re-derived here.

MOCK — not real data: every symbol, price, quantity, user and id is made up.
"""
from __future__ import annotations

import asyncio
import copy
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

from services import desk_cost_card as cost_card
from services import paper_account as acct
from services import paper_reconcile
from services.paper_pnl import book as bk
from services.paper_pnl import dashboard as dash
from services.paper_pnl import timeseries
from services.paper_pnl.prices import LIVE, Quote
from services.spt.paper import execution as spt_exec
from services.spt.paper import positions as spt_pos
from tests.test_desk_trading import A, TRADES_URL, api, world  # noqa: F401  (fixtures)
from tests.test_paper_pnl import pnl_api  # noqa: F401  (fixture)

NOW = datetime(2026, 11, 5, 5, 0, tzinfo=timezone.utc)            # Thursday 10:30 IST
TODAY = "2026-11-05"
CARD = spt_exec.card_snapshot()
USER = "user_a"
MARKET_OPEN = {"session": "open", "feed": "live", "day": TODAY}
LIMITS = {"max_open_risk_pct": 3.0, "daily_loss_pct": 2.0}


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def fill(order_id: str, seq: int, qty: int, price: float, side: str, at: datetime) -> Dict[str, Any]:
    """MOCK — one fill as slice C records it on its order (orders.record_fills)."""
    value = cost_card.paisa(qty * price)
    return {"fill_id": f"{order_id}:{seq}", "seq": seq, "quantity": qty, "price": price, "value_rs": value,
            "costs": spt_exec.fill_costs(side, value, first_fill=(seq == 1), model=CARD), "slippage_rs": 0.0,
            "at": at.isoformat()}


ENTRY = {"_id": "o-1", "user_id": USER, "purpose": "ENTRY", "side": "BUY", "symbol": "FIXS", "quantity": 100,
         "proposal_id": "prop-1", "opportunity_id": "opp-1", "correlation_id": "prop-1", "planned_entry_price": 502.0,
         "exit_plan": {"stop_loss": 480.0, "target_1": 545.0, "target_2": 590.0, "t1_exit_fraction": 0.5},
         "risk": {"reservation_id": "res-1"}, "cost_model": CARD}
OPENED = NOW - timedelta(days=1, hours=1)                       # Wednesday 09:30 IST
F1 = fill("o-1", 1, 60, 502.25, "BUY", OPENED)
F2 = fill("o-1", 2, 40, 502.30, "BUY", OPENED + timedelta(seconds=15))


def open_position() -> Dict[str, Any]:
    """MOCK — the position after the entry order's two fills, built by slice C's own code."""
    pos = spt_pos.new_position(ENTRY, F1, OPENED)
    pos.update(spt_pos.entry_fill_fields(pos, F2))
    pos["fill_ids"].append(F2["fill_id"])
    pos.update(_id="pos-1", state="MONITORING", version=3, updated_at=OPENED.isoformat())
    return pos


def exit_order(oid: str, fills: List[Dict[str, Any]], reason: str) -> Dict[str, Any]:
    return {"_id": oid, "user_id": USER, "purpose": "EXIT", "position_id": "pos-1", "side": "SELL", "reason": reason,
            "gap": False, "fills": fills}


X1 = fill("x-1", 1, 50, 545.0, "SELL", NOW - timedelta(minutes=20))          # T1 today
X2 = fill("x-2", 1, 50, 571.1234, "SELL", NOW - timedelta(minutes=5))        # T2 today (a 4-decimal fill price)


def after_exit(pos: Dict[str, Any], rec: Dict[str, Any], order: Dict[str, Any], *, closable: bool, **extra) -> Dict[str, Any]:
    out = copy.deepcopy(pos)
    out.update(spt_pos.exit_fill_fields(out, rec, order, closable=closable, now=NOW))
    out["fill_ids"].append(rec["fill_id"])
    out.update(extra)
    return out


def partial_position():
    order = exit_order("x-1", [X1], "target_1")
    pos = after_exit(open_position(), X1, order, closable=False, t1_done=True, stop_loss=502.27, version=5)
    return pos, [order]


def closed_position():
    p, orders = partial_position()
    o2 = exit_order("x-2", [X2], "target_2")
    return after_exit(p, X2, o2, closable=True, version=7), orders + [o2]


def fills_of(pos, exits=()):
    out = [(dict(f), 1) for f in (F1, F2)]
    for o in exits:
        out += [(dict(f), -1) for f in o["fills"]]
    return out


def q(ltp: float) -> Quote:
    return Quote(ltp=ltp, prev_close=500.0, status=LIVE, source="test", at=None, age_seconds=1.0, day=TODAY)


def build(open_items=(), closed_items=(), quotes=None, account=None, spt_error=None):
    book = bk.Book(open=list(open_items), closed=list(closed_items), spt_error=spt_error)
    filters = dash.make_filters("ALL", "ALL", None, None, date(2026, 11, 5))
    acc = account or {"starting_capital_rs": 1_000_000.0, "cash_rs": 1_000_000.0, "blocked_rs": 50_227.0}
    return dash.build(book, quotes or {}, MARKET_OPEN, acc, LIMITS, filters, now=NOW)


# ── P-01 an open scanner position ────────────────────────────────────────────
def test_spt_pnl_01_an_open_scanner_position_is_a_cash_row_tagged_scanner():
    pos = open_position()
    item = bk.spt_item(pos, fills_of(pos))
    assert (item.kind, item.source, item.status, item.entered) == ("cash", "scanner", "open", True)
    body = build([item], quotes={"pos-1": q(510.0)})
    [r] = body["positions"]
    assert (r["source"], r["opportunity_id"], r["proposal_id"], r["order_id"], r["spt_state"]) == \
        ("scanner", "opp-1", "prop-1", "o-1", "MONITORING")
    assert (r["mode"], r["segment"], r["side"], r["net_quantity"], r["account_id"]) == ("PAPER", "EQUITY", "LONG", 100, "paper")
    assert r["avg_price"] == 502.27 and r["unrealized_pnl"] == 773.0 and r["realized_pnl"] == 0.0     # (510 − 502.27) × 100
    est = spt_exec.exit_costs_per_share(510.0, 100, CARD) * 100
    assert r["charges_estimated"] == round(pos["entry_costs_rs"] + est, 2)
    mark = spt_pos.mark_fields(pos, {"bid": 510.0, "ltp": 510.0}, NOW)                # slice C's own display mark
    assert r["net_pnl"] == pytest.approx(mark["unrealized_net_rs"], abs=0.01)
    assert (r["stop_loss"], r["target"], r["status"]) == (480.0, 545.0, "ACTIVE")
    assert r["editable_levels"] is False and r["pending_levels"] is None and "spt-exec-v1" in r["executions_note"]
    assert [(e["execution_id"], e["side"], e["quantity"]) for e in r["executions"]] == [("o-1:1", "BUY", 60), ("o-1:2", "BUY", 40)]
    s = body["summary"]
    assert s["open_positions_by_source"] == {"desk": 0, "scanner": 1, "broker": 0} and s["unrealized_pnl"] == 773.0
    assert body["risk"]["open_risk_rs"] == round((480.0 - 510.0) * 100, 2)            # the stop risk is counted
    assert "scanner" in body["notes"]


def test_spt_pnl_01b_stop_alert_says_the_monitor_exits_it():
    pos = open_position()
    body = build([bk.spt_item(pos, fills_of(pos))], quotes={"pos-1": q(479.0)})
    [a] = [a for a in body["risk"]["alerts"] if a["type"] == "STOP_LOSS_HIT"]
    assert "paper monitor" in a["message"] and "evening check" not in a["message"]


# ── P-02 a partial exit (T1) ─────────────────────────────────────────────────
def test_spt_pnl_02_a_partly_exited_position_carries_its_realised_part_and_all_its_charges():
    pos, exits = partial_position()
    item = bk.spt_item(pos, fills_of(pos, exits))
    body = build([item], quotes={"pos-1": q(560.0)})
    [r] = body["positions"]
    assert r["net_quantity"] == 50 and r["realized_pnl"] == pos["realized_gross_rs"] == 2136.5      # (545 − 502.27) × 50
    assert r["target"] == 590.0 and r["stop_loss"] == 502.27                                      # T2 after T1, breakeven
    mark = spt_pos.mark_fields(pos, {"bid": 560.0, "ltp": 560.0}, NOW)
    assert r["net_pnl"] == pytest.approx(pos["realized_net_rs"] + mark["unrealized_net_rs"], abs=0.02)
    assert r["charges_estimated"] == round(pos["entry_costs_rs"] + pos["exit_costs_rs"]
                                           + spt_exec.exit_costs_per_share(560.0, 50, CARD) * 50, 2)


# ── P-03 a closed scanner trade, and the reconciliation ──────────────────────
def test_spt_pnl_03_a_closed_scanner_trade_reconciles_with_no_false_mismatch():
    pos, exits = closed_position()
    assert pos["state"] == "CLOSED" and pos["quantity"] == 0
    item = bk.spt_item(pos, fills_of(pos, exits))
    body = build(closed_items=[item])
    [c] = body["closed"]
    assert (c["source"], c["order_id"], c["kind"], c["segment"]) == ("scanner", "o-1", "cash", "EQUITY")
    assert c["realized_pnl"] == pos["realized_gross_rs"] and c["net_pnl"] == pos["realized_net_rs"]
    assert c["charges"] == round(pos["entry_costs_rs"] + pos["exit_costs_rs"], 2)
    assert c["exit_session"] == TODAY and c["exit_reason"] == "target_2"
    rec = body["reconciliation"]
    assert rec["checked"] == 1 and rec["mismatches"] == []
    assert not [a for a in body["risk"]["alerts"] if a["type"] == "RECONCILIATION_MISMATCH"]
    tampered = copy.deepcopy(pos)
    tampered["realized_gross_rs"] = round(pos["realized_gross_rs"] + 5.0, 2)
    body = build(closed_items=[bk.spt_item(tampered, fills_of(tampered, exits))])
    [m] = body["reconciliation"]["mismatches"]
    assert m["source"] == "scanner" and m["difference"] == -5.0


# ── P-04 capital: blocked by source; a desk-only account is unchanged ────────
def test_spt_pnl_04_blocked_capital_is_split_and_a_desk_only_account_is_unchanged():
    pos = open_position()
    acc = {"starting_capital_rs": 1_000_000.0, "cash_rs": 1_000_000.0, "blocked_rs": 60_227.0,
           "spt_reserved_rs": 50_227.0, "spt_reservations": 1}
    body = build([bk.spt_item(pos, fills_of(pos))], quotes={"pos-1": q(510.0)}, account=acc)
    split = body["risk"]["capital"]["blocked_by_source"]
    assert (split["scanner"], split["desk"]) == (50_227.0, 10_000.0)
    assert body["reconciliation"]["scanner_reserved_rs"] == 50_227.0 and body["reconciliation"]["scanner_reservations"] == 1
    assert body["positions"][0]["invested_value"] == 50_227.0                          # the scanner funding, position by position
    desk_only = build(account={"starting_capital_rs": 1e6, "cash_rs": 1e6, "blocked_rs": 10_000.0})
    assert desk_only["risk"]["capital"]["blocked_by_source"] is None                    # no split read: nothing invented
    assert desk_only["summary"]["open_positions_by_source"] == {"desk": 0, "scanner": 0, "broker": 0}
    assert desk_only["scanner_error"] is None and desk_only["reconciliation"]["mismatches"] == []


def test_spt_pnl_05_unreadable_scanner_book_and_missing_fills_are_said_not_hidden():
    body = build(spt_error="the scanner paper positions could not be read (RuntimeError)")
    assert body["scanner_error"].startswith("the scanner") and [a["type"] for a in body["risk"]["alerts"]] == ["SCANNER_BOOK"]
    pos = open_position()
    item = bk.spt_item(pos, [])                                                      # its fills could not be matched
    assert item.public["fills_missing"] is True
    body = build([item], quotes={"pos-1": q(510.0)})
    assert body["positions"] == [] and [a["type"] for a in body["risk"]["alerts"]] == ["SCANNER_FILLS_MISSING"]


# ── P-06 the curve ───────────────────────────────────────────────────────────
def test_spt_pnl_06_the_curve_holds_scanner_positions_and_their_partial_exits_today():
    pos, exits = partial_position()
    item = bk.spt_item(pos, fills_of(pos, exits))
    book = bk.Book(open=[item])
    [line] = timeseries.paper_lines(book, {"pos-1": q(560.0)})
    assert (line["key"], line["net_quantity"], line["avg_price"]) == ("pos-1", 50, pytest.approx(502.27))
    assert timeseries.partial_realized(item, TODAY) == 2136.5 and timeseries.partial_realized(item, "2026-11-04") == 0.0
    assert "scanner" in timeseries.BASIS


# ── P-07 the route, end to end, with the paper account and the reconciliation invariants ──
CAPS = {"open_risk_cap_rs": 1e9, "exposure_cap_rs": 1e9, "sector_cap_rs": 1e9, "max_positions": 50}


def test_spt_pnl_07_route_desk_and_scanner_together_and_the_account_reconciles(world, api, pnl_api):
    client, live = pnl_api
    r = api.post(TRADES_URL, json={"symbol": "FIXA", "quantity": 10, "entry_price": 100.0, "stop_price": 95.0,
                                   "target_price": 110.0}, headers=A)
    assert r.status_code == 201, r.text
    desk_id = r.json()["trade"]["id"]
    db = world.db
    pos = open_position()
    # MOCK: the reservation slice B takes for the entry order (store spt_orders, trade_id = the order id) …
    run(acct.reserve_entry(db, USER, {"id": "res-1", "trade_id": "o-1", "store": "spt_orders", "path": "spt_entry",
                                      "kind": "cash", "symbol": "FIXS", "sector": "MOCK Sector", "funding_rs": 50_227.0,
                                      "risk_rs": 2_500.0, "exposure_rs": 50_227.0, "positions": 1, "held": True}, CAPS))
    # … and slice C's order and position
    db.cols["spt_orders"].docs.append({**ENTRY, "fills": [F1, F2], "state": "FILLED"})
    db.cols["spt_positions"].docs.append(pos)
    live["FIXS"] = 510.0
    body = client.get("/api/desk/pnl", params={"period": "ALL"}, headers=A).json()
    by = {p["trade_id"]: p for p in body["positions"]}
    assert by[desk_id]["source"] == "desk" and by["pos-1"]["source"] == "scanner"
    assert by["pos-1"]["unrealized_pnl"] == 773.0 and by["pos-1"]["order_id"] == "o-1"
    assert body["summary"]["open_positions_by_source"] == {"desk": 1, "scanner": 1, "broker": 0}
    account = next(a for a in db.cols["paper_accounts"].docs if a["user_id"] == USER)
    split = body["risk"]["capital"]["blocked_by_source"]
    assert split["scanner"] == 50_227.0 and split["desk"] == round(account["blocked_rs"] - 50_227.0, 2)
    assert split["desk"] == round(by[desk_id]["invested_value"], 2)                     # the desk trade's own funding
    assert body["reconciliation"]["mismatches"] == [] and body["scanner_error"] is None
    rows = [x for x in db.cols[acct.LEDGER].docs if x["user_id"] == USER]
    trades = [t for t in db.cols["desk_paper_trades"].docs if t["user_id"] == USER]
    inv = paper_reconcile.invariants(account, rows, trades)
    assert inv["I1_ok"] and inv["I2_ok"] and inv["I3_ok"] and inv["I3_spt_reserved"] == 50_227.0, inv

    # slice C closes it (both targets) and releases the reservation once, with the net P&L
    closed, exits = closed_position()
    db.cols["spt_positions"].docs[:] = [closed]
    db.cols["spt_orders"].docs.extend({**o, "state": "FILLED"} for o in exits)
    run(acct.release(db, USER, 50_227.0, net_pnl=closed["realized_net_rs"], trade_id="o-1", symbol="FIXS"))
    body = client.get("/api/desk/pnl", params={"period": "ALL"}, headers=A).json()
    assert [p["source"] for p in body["positions"]] == ["desk"]
    [c] = [c for c in body["closed"] if c["source"] == "scanner"]
    assert c["realized_pnl"] == closed["realized_gross_rs"] and c["net_pnl"] == closed["realized_net_rs"]
    assert body["reconciliation"]["checked"] >= 1 and body["reconciliation"]["mismatches"] == []
    assert body["risk"]["capital"]["blocked_by_source"]["scanner"] == 0.0
    account = next(a for a in db.cols["paper_accounts"].docs if a["user_id"] == USER)
    rows = [x for x in db.cols[acct.LEDGER].docs if x["user_id"] == USER]
    inv = paper_reconcile.invariants(account, rows, trades)
    assert inv["I1_ok"] and inv["I2_ok"] and inv["I3_ok"], inv
    assert body["modes"]["PAPER"]["realized_pnl"] == closed["realized_gross_rs"]


def test_spt_pnl_08_an_unreadable_scanner_store_leaves_the_desk_intact(world, api, pnl_api, monkeypatch):
    client, live = pnl_api
    api.post(TRADES_URL, json={"symbol": "FIXA", "quantity": 10, "entry_price": 100.0, "stop_price": 95.0,
                               "target_price": 110.0}, headers=A)

    async def boom(db, uid):
        raise RuntimeError("MOCK store down")
    monkeypatch.setattr(bk, "_spt_docs", boom)
    body = client.get("/api/desk/pnl", params={"period": "ALL"}, headers=A).json()
    assert [p["source"] for p in body["positions"]] == ["desk"]
    assert body["scanner_error"] == "the scanner paper positions could not be read (RuntimeError)"
    assert "SCANNER_BOOK" in [a["type"] for a in body["risk"]["alerts"]]
