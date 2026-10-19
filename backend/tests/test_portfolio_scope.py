"""GET /api/portfolio/composition/scope (routes/portfolio_composition.py) — PRD §8.3: every total names the accounts
and instrument types it includes, with data freshness and reconciliation status.

No Mongo: `db.holdings` and `db.broker_accounts` are in-memory fakes. MOCK — not real data.
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.portfolio_composition as route
from helpers import holdings_reconcile

INFY, HDFC = "INE009A01021", "INE040A01034"


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, n):
        return list(self._docs)


class _Col:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query, projection=None):
        return _Cursor([dict(d) for d in self.docs if all(d.get(k) == v for k, v in query.items())])


class _Db:
    def __init__(self, holdings, accounts):
        self.holdings = _Col(holdings)
        self.broker_accounts = _Col(accounts)


def _row(name, *, qty, bp, cp, source, user="u1", **over) -> Dict[str, Any]:
    r = {"user_id": user, "holding_id": f"h_{name}", "name": name, "ticker": name, "asset_type": "equity",
         "quantity": qty, "buy_price": bp, "current_price": cp, "source": source,
         "uploaded_at": "2026-10-10T09:00:00+00:00", "created_at": "2026-10-10T09:00:00+00:00"}
    r.update(over)
    return r


HOLDINGS: List[Dict[str, Any]] = [
    # A connected Zerodha account: two stocks, read at its last sync
    _row("INFY", qty=10, bp=1400, cp=1500, source="broker_native", broker="zerodha", broker_account_id="ba_z",
         isin=INFY, uploaded_at="2026-10-13T10:12:00+00:00"),
    _row("TCS", qty=2, bp=3000, cp=3100, source="broker_native", broker="zerodha", broker_account_id="ba_z",
         uploaded_at="2026-10-13T10:12:00+00:00"),
    # A CAS statement: a fund and Infosys again (the same ISIN as the Zerodha row)
    _row("Some Flexi Cap Fund", qty=100, bp=50, cp=60, source="cas", asset_type="mutual_fund", ticker="INF204KB17I5"),
    _row("Infosys Ltd", qty=3, bp=1300, cp=1500, source="cas", ticker=INFY, uploaded_at="2026-09-30T09:00:00+00:00",
         created_at="2026-09-30T09:00:00+00:00"),
    # A plain sheet: no average cost, and a row with no price
    _row("HDFC Bank", qty=5, bp=0, cp=1650, source="manual", ticker="HDFCBANK"),
    _row("Unpriced Co", qty=4, bp=10, cp=0, source="manual", ticker="UNPRICED"),
    # Another user's row is never read
    _row("OTHER", qty=1, bp=1, cp=1_000_000, source="manual", user="u2"),
]
ACCOUNTS = [{"user_id": "u1", "account_id": "ba_z", "broker": "zerodha", "label": "Zerodha", "native": True,
             "last_sync_at": "2026-10-13T10:12:00+00:00"}]


def _client(monkeypatch, holdings=HOLDINGS, accounts=ACCOUNTS):
    async def user(request: Request):
        return {"user_id": "u1"}

    monkeypatch.setattr(route, "db", _Db(holdings, accounts))
    monkeypatch.setattr(route, "get_current_user", user)
    monkeypatch.setattr(holdings_reconcile, "_symbol_index", {"INFY": INFY, "HDFCBANK": HDFC})
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app)


def test_scope_names_every_account_and_instrument_type(monkeypatch):
    r = _client(monkeypatch).get("/api/portfolio/composition/scope")
    assert r.status_code == 200, r.text
    d = r.json()
    seg = {s["key"]: s for s in d["accounts"]}
    assert set(seg) == {"account:ba_z", "statement", "manual"}
    z = seg["account:ba_z"]
    # 10 × 1,500 + 2 × 3,100 = 21,200; invested 14,000 + 6,000 = 20,000
    assert (z["kind"], z["name"], z["holdings"], z["value_rs"], z["invested_rs"]) == ("broker_account", "Zerodha", 2, 21200.0, 20000.0)
    assert z["instrument_types"] == {"equity": 2} and z["last_updated"] == "2026-10-13T10:12:00+00:00"
    assert z["last_sync_at"] == "2026-10-13T10:12:00+00:00"
    assert sorted((l["symbol"], l["quantity"]) for l in z["lines"]) == [("INFY", 10.0), ("TCS", 2.0)]
    st = seg["statement"]
    # 100 × 60 + 3 × 1,500 = 10,500
    assert (st["name"], st["holdings"], st["value_rs"], st["instrument_types"]) == ("CAS statement", 2, 10500.0, {"equity": 1, "mutual_fund": 1})
    m = seg["manual"]
    # 5 × 1,650 + 4 × 0 = 8,250; invested only where a cost is on record: 4 × 10 = 40
    assert (m["value_rs"], m["invested_rs"], m["unpriced"], m["no_cost"]) == (8250.0, 40.0, 1, 1)

    t = d["totals"]
    assert t["holdings"] == 6 and t["value_rs"] == 21200.0 + 10500.0 + 8250.0
    assert t["invested_rs"] == 20000.0 + 5000.0 + 3900.0 + 40.0
    assert (t["unpriced_rows"], t["no_cost_rows"]) == (1, 1)
    assert d["instrument_types"] == {"equity": 5, "mutual_fund": 1}
    alloc = {a["asset_class"]: a for a in d["asset_allocation"]}
    assert alloc["Equity"]["value_rs"] == 21200.0 + 4500.0 + 8250.0 + 6000.0      # an equity fund counts as equity
    # The weights add up to 100 (to the rounding)
    assert abs(sum(a["weight_pct"] for a in d["asset_allocation"]) - 100.0) < 0.05

    rec = d["reconciliation"]
    [dup] = rec["duplicates"]
    assert dup["isin"] == INFY and sorted(dup["sources"]) == ["CAS statement", "Zerodha"] and dup["rows"] == 2
    assert "broker" in rec["rule"].lower()
    assert d["last_updated"] == "2026-10-13T10:12:00+00:00" and d["oldest_updated"] == "2026-09-30T09:00:00+00:00"


def test_an_empty_portfolio_has_no_accounts_and_null_totals(monkeypatch):
    d = _client(monkeypatch, holdings=[], accounts=[]).get("/api/portfolio/composition/scope").json()
    assert d["accounts"] == [] and d["totals"]["value_rs"] is None and d["totals"]["holdings"] == 0
    assert d["reconciliation"]["duplicates"] == []
