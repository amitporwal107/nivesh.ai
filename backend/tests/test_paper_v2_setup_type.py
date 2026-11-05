"""Paper Trading v2 — `setup_type` on /api/desk/pnl rows from stored fields only (services/paper_pnl/dashboard.setup_fields,
services/paper_pnl/book._spt_setup_types), and the F&O structure id that both screens use (TESTCASES PV2-B-31..33).
MOCK — not real data: every user, symbol, trade, opportunity and price here is made up; test-user ids only."""
from __future__ import annotations

from datetime import datetime, timezone

from services.paper_pnl import book as bk
from services.paper_pnl import dashboard as dash
from services.spt import fno_structures as fs
from tests.test_desk_trading import A, TRADES_URL, api, world  # noqa: F401 (fixtures)
from tests.test_paper_pnl import build, cash_pub, q, spread_pub
from tests.test_paper_pnl import pnl_api  # noqa: F401 (fixture)
from tests.test_paper_pnl_spt import ENTRY, F1, F2, closed_position, fills_of, open_position, run


# ── PV2-B-31 each kind's stored field, never inferred ────────────────────────
def test_pv2_b_31_setup_fields_per_kind():
    scanner = bk.spt_item(open_position(), fills_of(open_position()), setup_type="breakout")
    unknown_scanner = bk.spt_item(open_position(), fills_of(open_position()))
    spread = bk.strategy_item(spread_pub())
    idea = bk.cash_item({**cash_pub("t1", "FIXA", 10, 100.0, stop=90),
                         "source": {"kind": "scanner", "bucket": "Momentum", "signal_date": "2026-11-04"}})
    chart = bk.cash_item({**cash_pub("t2", "FIXB", 10, 100.0, stop=90), "source": {"kind": "chart_analysis",
                                                                                   "bucket": None, "signal_date": None}})
    bare = bk.cash_item(cash_pub("t3", "FIXC", 10, 100.0, stop=90))
    got = [dash.setup_fields(i) for i in (scanner, unknown_scanner, spread, idea, chart, bare)]
    assert got == [{"setup_type": "breakout", "setup_type_source": "spt_opportunities.category"},
                   {"setup_type": None, "setup_type_source": None},
                   {"setup_type": "bull_call_spread", "setup_type_source": "desk_paper_trades.family"},
                   {"setup_type": "Momentum", "setup_type_source": "desk_paper_trades.source.bucket"},
                   {"setup_type": None, "setup_type_source": None},            # a source kind is not a setup type
                   {"setup_type": None, "setup_type_source": None}]


def test_pv2_b_31b_on_open_rows_closed_rows_and_strategy_entries():
    idea = bk.cash_item({**cash_pub("t1", "FIXA", 10, 100.0, stop=90), "source": {"kind": "scanner", "bucket": "Momentum"}})
    spread = bk.strategy_item(spread_pub(marks=(170.0, 95.0)))
    closed_pos, exits = closed_position()
    closed = bk.spt_item(closed_pos, fills_of(closed_pos, exits), setup_type="reversal")
    body = build([idea, spread], [closed], quotes={"t1": q(105.0), "st1:0": q(170.0), "st1:1": q(95.0)})
    rows = {(p["trade_id"], p["leg_index"]): p for p in body["positions"]}
    assert rows[("t1", None)]["setup_type"] == "Momentum"
    assert rows[("st1", 0)]["setup_type"] == rows[("st1", 1)]["setup_type"] == "bull_call_spread"
    assert body["strategies"][0]["setup_type"] == "bull_call_spread"
    [c] = [c for c in body["closed"] if c["source"] == "scanner"]
    assert (c["setup_type"], c["setup_type_source"]) == ("reversal", "spt_opportunities.category")


# ── PV2-B-32 the scanner join: one read per book build, over HTTP ────────────
def test_pv2_b_32_route_reads_the_opportunity_category_once(world, api, pnl_api):
    client, live = pnl_api
    db = world.db
    r = api.post(TRADES_URL, json={"symbol": "FIXA", "quantity": 10, "entry_price": 100.0, "stop_price": 95.0,
                                   "target_price": 110.0, "source": {"kind": "scanner", "bucket": "Breakout"}}, headers=A)
    assert r.status_code == 201, r.text
    desk_id = r.json()["trade"]["id"]
    pos = open_position()
    db.cols["spt_orders"].docs.append({**ENTRY, "fills": [F1, F2], "state": "FILLED"})
    db.cols["spt_positions"].docs.append(pos)
    closed_pos, exits = closed_position()
    # a second (closed) position with its own entry order, whose opportunity is not stored
    db.cols["spt_orders"].docs.append({**ENTRY, "_id": "o-2", "fills": [F1, F2], "state": "FILLED"})
    db.cols["spt_positions"].docs.append({**closed_pos, "_id": "pos-2", "entry_order_id": "o-2",
                                          "opportunity_id": "opp-gone"})
    db.cols["spt_opportunities"].docs.append({"_id": "opp-1", "category": "breakout", "family": "MOCK family"})
    reads = []
    real_find = db.cols["spt_opportunities"].find

    def counting_find(query):
        reads.append(query)
        return real_find(query)
    db.cols["spt_opportunities"].find = counting_find
    live["FIXS"] = 510.0
    body = client.get("/api/desk/pnl", params={"period": "ALL"}, headers=A).json()
    by = {p["trade_id"]: p for p in body["positions"]}
    assert (by["pos-1"]["setup_type"], by["pos-1"]["setup_type_source"]) == ("breakout", "spt_opportunities.category")
    assert (by[desk_id]["setup_type"], by[desk_id]["setup_type_source"]) == ("Breakout", "desk_paper_trades.source.bucket")
    [c] = [c for c in body["closed"] if c["trade_id"] == "pos-2"]
    assert c["setup_type"] is None                       # its opportunity is not stored: null, not guessed
    assert reads == [{"_id": {"$in": ["opp-1", "opp-gone"]}}]           # one batched read for every position


def test_pv2_b_32b_an_unreadable_opportunity_store_leaves_rows_with_null(world, api, pnl_api):
    client, live = pnl_api
    db = world.db
    db.cols["spt_orders"].docs.append({**ENTRY, "fills": [F1, F2], "state": "FILLED"})
    db.cols["spt_positions"].docs.append(open_position())

    def boom(query):
        raise RuntimeError("MOCK: the opportunities store is down")
    db.cols["spt_opportunities"].find = boom
    live["FIXS"] = 510.0
    body = client.get("/api/desk/pnl", params={"period": "ALL"}, headers=A).json()
    [row] = [p for p in body["positions"] if p["source"] == "scanner"]
    assert row["setup_type"] is None and body["scanner_error"] is None       # the position itself is still shown


# ── PV2-B-33 the F&O structure id is the P&L row's strategy_id ───────────────
def test_pv2_b_33_fno_structure_id_equals_pnl_strategy_id():
    pub = spread_pub("st-77", marks=(170.0, 95.0))
    item = bk.strategy_item(pub)
    body = build([item], quotes={"st-77:0": q(170.0), "st-77:1": q(95.0)})
    strategy_ids = {p["strategy_id"] for p in body["positions"]}
    s = fs.structure(item.public, group=None, leg_ltp={"st-77:0": 170.0, "st-77:1": 95.0}, margin=(None, "MOCK"),
                     limit_rs=None, today=datetime(2026, 11, 5, tzinfo=timezone.utc).date())
    assert strategy_ids == {s["id"]} == {body["strategies"][0]["strategy_id"]} == {"st-77"}
