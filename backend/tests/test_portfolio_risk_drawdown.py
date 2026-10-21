"""GET /api/portfolio/risk-analytics — the 1-year drawdown of the stocks held (backend addition B14, PRD §8.4).

The PRA results table (pra.portfolio_risk_results) is empty on staging (read-only check 2026-10-14: 0 rows), so the
drawdown comes from each stock's own `max_drawdown_1y_pct` in nidp.stock_features_daily, read through the same DaaS
v3-primitives call the route already makes, value-weighted over the stocks that have it. It is labelled as the
stocks' drawdown, not the portfolio's own (which needs a value series; see GET /api/portfolio/holding-risk).

No Mongo, no network: `db.holdings` and the DaaS bulk calls are fakes. MOCK — not real data.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.portfolio_risk_analytics as route


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, n):
        return list(self._docs)


class _Holdings:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query, projection=None):
        return _Cursor([d for d in self.docs if d["user_id"] == query["user_id"]])


class _Db:
    def __init__(self, docs):
        self.holdings = _Holdings(docs)


def _client(monkeypatch, holdings: List[Dict[str, Any]], stocks: Dict[str, Dict[str, Any]]):
    async def user(request: Request):
        return {"user_id": "u1"}

    async def stock_bulk(symbols, timeout=15.0):
        return {s: stocks[s] for s in symbols if s in stocks}

    async def mf_bulk(isins, timeout=15.0):
        return {}

    monkeypatch.setattr(route, "db", _Db(holdings))
    monkeypatch.setattr(route, "get_current_user", user)
    monkeypatch.setattr(route._daas, "get_v3_stock_primitives_bulk", stock_bulk)
    monkeypatch.setattr(route._daas, "get_v3_mf_primitives_bulk", mf_bulk)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app)


def _h(ticker, qty, price, asset_type="equity", user="u1"):
    return {"user_id": user, "name": ticker, "ticker": ticker, "asset_type": asset_type, "quantity": qty, "current_price": price}


HOLDINGS = [
    _h("FIXA", 100, 300),          # ₹30,000
    _h("FIXB", 50, 200),           # ₹10,000
    _h("FIXC", 10, 100),           # ₹1,000, no drawdown on record
    _h("FUND1", 1000, 60, asset_type="mutual_fund"),   # ₹60,000: a fund is not a stock
    _h("OTHER", 1, 1_000_000, user="u2"),
]
STOCKS = {
    "FIXA": {"beta_1y": 1.1, "volatility_1y_pct": 22.0, "max_drawdown_1y_pct": -30.0, "as_of_date": "2026-10-12"},
    "FIXB": {"beta_1y": 0.9, "volatility_1y_pct": 18.0, "max_drawdown_1y_pct": -10.0, "as_of_date": "2026-10-12"},
    "FIXC": {"beta_1y": 1.0, "volatility_1y_pct": 25.0, "max_drawdown_1y_pct": None, "as_of_date": "2026-10-11"},
}


def test_drawdown_is_the_value_weighted_one_year_drawdown_of_the_stocks(monkeypatch):
    d = _client(monkeypatch, HOLDINGS, STOCKS).get("/api/portfolio/risk-analytics").json()
    # (−30 × 30,000 + −10 × 10,000) / 40,000 = −25.0
    assert d["holdings_drawdown_1y_pct"] == -25.0
    # 40,000 of the 1,01,000 the route valued (stocks 41,000 + fund 60,000) has a figure → 39.6%
    assert d["drawdown_coverage_pct"] == round(40000 / 101000 * 100, 1) == 39.6
    assert d["worst_drawdown_holding"] == {"name": "FIXA", "ticker": "FIXA", "max_drawdown_1y_pct": -30.0}
    assert d["drawdown_as_of"] == "2026-10-12"
    assert "not the portfolio" in d["drawdown_method"] and "max_drawdown_1y_pct" in d["drawdown_source"]
    # The portfolio's own drawdown is not computed here: still null, never 0.
    assert d["max_drawdown_pct"] is None
    rows = {r["ticker"]: r for r in d["stock_breakdown"]}
    assert rows["FIXA"]["max_drawdown_1y_pct"] == -30.0 and rows["FIXC"]["max_drawdown_1y_pct"] is None


def test_no_drawdown_on_record_is_null_not_zero(monkeypatch):
    stocks = {k: {**v, "max_drawdown_1y_pct": None} for k, v in STOCKS.items()}
    d = _client(monkeypatch, HOLDINGS, stocks).get("/api/portfolio/risk-analytics").json()
    assert d["holdings_drawdown_1y_pct"] is None and d["worst_drawdown_holding"] is None
    assert d["drawdown_coverage_pct"] == 0.0


def test_another_users_holdings_never_count(monkeypatch):
    d = _client(monkeypatch, HOLDINGS, STOCKS).get("/api/portfolio/risk-analytics").json()
    assert d["total_value"] == 101000.0
