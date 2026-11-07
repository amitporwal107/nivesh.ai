"""Paper Trading v2 — open risk by allocation bucket (services/spt/allocation.open_risk_rows / risk_by, used by
GET /api/v1/risk/account utilisation.buckets[k].risk_rs and by the overview's concentration; TESTCASES PV2-B-29, 30).
MOCK — not real data: every user, symbol, reservation and figure here is made up; test-user ids only."""
from __future__ import annotations

import asyncio

from services import paper_account as acct
from services.spt import allocation, overview
from services.spt import constants as C
from tests.paper_v2_fakes import A, NOW, U1, client, world  # noqa: F401 (fixtures)

CAPS = {"open_risk_cap_rs": 1e9, "exposure_cap_rs": 1e9, "sector_cap_rs": 1e9, "max_positions": 50}


def run(coro):
    return asyncio.run(coro)


# ── PV2-B-29 the rows and their buckets (pure) ───────────────────────────────
def test_pv2_b_29_open_risk_rows_by_bucket_and_sector():
    book = {"reservations": [
                {"trade_id": "o-1", "store": C.ORDERS, "kind": "cash", "symbol": "FIXA", "sector": "IT", "risk_rs": 2000.0},
                {"trade_id": "o-2", "store": C.ORDERS, "kind": "cash", "symbol": "FIXB", "sector": "IT", "risk_rs": 500.0},
                {"trade_id": "d-1", "store": "desk_paper_trades", "kind": "cash", "symbol": "FIXC", "sector": "Bank",
                 "risk_rs": 1000.0},
                {"trade_id": "d-2", "store": "desk_paper_trades", "kind": "structure", "symbol": "NIFTY", "sector": None,
                 "risk_rs": 3000.0}],
            "positions": [
                {"trade_id": "d-1", "reserved": True, "kind": "cash", "risk_rs": 1000.0},          # already a reservation
                {"trade_id": "d-3", "reserved": False, "kind": "strategy", "store": "desk_paper_trades", "symbol": "BANKNIFTY",
                 "sector": None, "risk_rs": 700.0},
                {"trade_id": "j-1", "reserved": False, "kind": "journal", "store": "trade_journal", "symbol": "FIXD",
                 "sector": "IT", "risk_rs": None}]}
    rows = allocation.open_risk_rows(book, {"o-1": "equity_positional", "o-2": "equity_intraday"})
    assert [(r["trade_id"], r["bucket"]) for r in rows] == [
        ("o-1", "equity_positional"), ("o-2", "equity_intraday"), ("d-1", "equity_positional"), ("d-2", "fno"),
        ("d-3", "fno"), ("j-1", "equity_positional")]
    assert allocation.risk_by(rows, "bucket") == {"equity_positional": 3000.0, "equity_intraday": 500.0, "fno": 3700.0}
    assert allocation.risk_by(rows, "sector") == {"IT": 2500.0, "Bank": 1000.0, "unclassified": 3700.0}


# ── PV2-B-30 over the route, and the overview reads the same rows ────────────
def test_pv2_b_30_risk_account_buckets_sum_to_open_risk(client):
    db = client.world.db
    run(acct.reserve_entry(db, U1, {"id": "res-1", "trade_id": "o-1", "store": C.ORDERS, "path": "spt_entry", "kind": "cash",
                                    "symbol": "FIXS", "sector": "IT", "funding_rs": 50_000.0, "risk_rs": 2_500.0,
                                    "exposure_rs": 50_000.0, "positions": 1, "held": True}, CAPS))
    run(acct.reserve_entry(db, U1, {"id": "res-2", "trade_id": "d-9", "store": "desk_paper_trades", "path": "desk",
                                    "kind": "structure", "symbol": "NIFTY", "sector": None, "funding_rs": 6_000.0,
                                    "risk_rs": 6_200.0, "exposure_rs": 6_000.0, "positions": 1, "held": False}, CAPS))
    db[C.ORDERS].docs.append({"_id": "o-1", "user_id": U1, "purpose": "ENTRY", "state": C.ORD_PENDING, "quantity": 100,
                              "filled_qty": 0})
    db[C.PROPOSALS].docs.append({"_id": "p-1", "user_id": U1, "order_id": "o-1", "horizon": "positional",
                                 "instrument": "cash", "symbol": "FIXS"})
    r = client.get(f"/api/v1/risk/account/{U1}", headers=A)
    assert r.status_code == 200, r.text
    b = r.json()
    buckets = b["utilisation"]["buckets"]
    assert {k: v["risk_rs"] for k, v in buckets.items()} == {"equity_positional": 2500.0, "equity_intraday": 0.0,
                                                              "fno": 6200.0}
    assert sum(v["risk_rs"] for v in buckets.values()) == b["open_risk"]["rs"] == 8700.0
    # the capital column is unchanged: it counts the SPT reservation only (said in bucket_risk_basis)
    assert {k: v["used_rs"] for k, v in buckets.items()} == {"equity_positional": 50000.0, "equity_intraday": 0.0, "fno": 0.0}
    assert b["utilisation"]["bucket_risk_unknown"] == [] and "SPT reservations only" in b["utilisation"]["bucket_risk_basis"]

    state = run(allocation.account_state(db, U1, now=NOW))
    assert state["bucket_risk_rs"] == {"equity_positional": 2500.0, "equity_intraday": 0.0, "fno": 6200.0}
    state["profile"] = {**state["profile"], "limits": {**state["profile"]["limits"], "max_sector_pct": 5.0}}
    wc = overview.concentration(state)                    # IT ₹50,000 of a ₹50,000 cap; ₹2,500 of ₹8,700 open risk
    assert wc["name"] == "IT" and wc["pct_of_open_risk"] == round(2500 / 8700 * 100, 2)


def test_pv2_b_30b_an_unreadable_book_leaves_bucket_risk_null(client, monkeypatch):
    from services import risk_book

    async def boom(*a, **kw):
        raise RuntimeError("MOCK: the book store is down")
    monkeypatch.setattr(risk_book, "read", boom)
    b = client.get(f"/api/v1/risk/account/{U1}", headers=A).json()
    assert all(v["risk_rs"] is None for v in b["utilisation"]["buckets"].values())
