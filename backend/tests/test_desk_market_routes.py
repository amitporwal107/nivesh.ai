"""Trading desk market reads on the app side:

    GET /api/markets/sector-returns, GET /api/markets/deals   routes/markets_desk.py → DaaS /v1/desk/sector-returns, /desk/deals
    GET /api/fno/scan/buildup                                  routes/fno.py          → DaaS /v1/desk/fno-buildup
    breadth.universe_kind on GET /api/markets/home             routes/markets.py::_breadth
    exchange on GET /api/filings/feed rows                     routes/filings.py::_exchange

No network and no Mongo: `daas_client.get_raw` is replaced by a recorder that answers with fixture bodies
(MOCK — not real data) in the shape the data platform sends, so each route's own work runs for real: auth,
parameter validation, what is forwarded, the pass-through and the error mapping. The DaaS router's figures are
tested in nidp/tests/services/test_daas_desk_market.py; real figures come from the staging data test.
"""
from __future__ import annotations

import copy
from typing import Any, List, Optional, Tuple

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from routes import filings, markets
from routes import fno as fno_route
from routes import markets_desk as desk_route
from services.copilot_tools import daas_client

Calls = List[Tuple[str, Optional[dict]]]

SECTORS = {"as_of": "2026-10-13", "source": "NSE index close (nidp.index_eod)", "sessions": {"1d": 1, "1w": 5, "1m": 21},
           "sectors": [{"index": "Nifty IT", "sector": "IT", "date": "2026-10-13", "close": 29830.1,
                        "ret_1d_pct": 5.22, "ret_1w_pct": 6.02, "ret_1m_pct": 3.25}]}
DEALS = {"as_of": "2026-10-13", "from": "2026-10-09", "days": 5, "kind": "all", "symbol": None,
         "source": "NSE bulk and block deals (nidp.bulk_deals, nidp.block_deals)", "count": 1, "total": 1,
         "rows": [{"date": "2026-10-13", "kind": "bulk", "symbol": "CMLL", "client_name": "MICROCURVES TRADING PRIVATE LIMITED",
                   "side": "SELL", "quantity": 2099164, "avg_price": 633.54, "value_cr": 132.99}]}
BUILDUP = {"as_of": "2026-10-13", "source": "NSE F&O bhavcopy (nidp.fno_bhavcopy), stock futures", "universe": 1,
           "counts": {"long_buildup": 1, "short_buildup": 0, "short_covering": 0, "long_unwinding": 0, "neutral": 0, "no_data": 0},
           "rows": [{"symbol": "UJJIVANSFB", "near_expiry": "2026-10-27", "close": 65.46, "prev_close": 62.56, "price_chg_pct": 4.64,
                     "oi": 37184000, "oi_chg": 5736000, "oi_chg_pct": 18.24, "expiries": 3, "label": "long_buildup"}]}


def _client(monkeypatch, module, reply: Any, *, signed_in: bool = True, configured: bool = True) -> Tuple[TestClient, Calls]:
    calls: Calls = []

    async def get_raw(path: str, params: Optional[dict] = None, timeout: float = 10.0):
        calls.append((path, params))
        r = reply(path) if callable(reply) else reply
        if isinstance(r, Exception):
            raise r
        return copy.deepcopy(r)

    monkeypatch.setattr(daas_client, "get_raw", get_raw)
    monkeypatch.setattr(daas_client, "is_configured", lambda: configured)
    if signed_in:
        async def fake_user(request: Request):
            return {"user_id": "u1", "email": "u1@example.com"}
        monkeypatch.setattr(module, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(module.router)
    return TestClient(app), calls


# ── /api/markets/sector-returns and /api/markets/deals ───────────────────────

def test_sector_returns_is_passed_through_unchanged(monkeypatch):
    c, calls = _client(monkeypatch, desk_route, (200, SECTORS))
    r = c.get("/api/markets/sector-returns")
    assert r.status_code == 200 and r.json() == SECTORS
    assert calls == [("/desk/sector-returns", None)]


def test_deals_forwards_defaults_and_upper_cases_the_symbol(monkeypatch):
    c, calls = _client(monkeypatch, desk_route, (200, DEALS))
    assert c.get("/api/markets/deals").json() == DEALS
    assert c.get("/api/markets/deals?days=30&kind=block&symbol=jublpharma&limit=20").status_code == 200
    assert calls == [("/desk/deals", {"days": 5, "kind": "all", "limit": 500}),
                     ("/desk/deals", {"days": 30, "kind": "block", "limit": 20, "symbol": "JUBLPHARMA"})]


@pytest.mark.parametrize("qs", ["days=0", "days=31", "kind=insider", "symbol=AB%20C", "symbol=" + "A" * 21, "limit=0", "limit=2001"])
def test_deals_rejects_bad_parameters_before_calling_the_data_platform(monkeypatch, qs):
    c, calls = _client(monkeypatch, desk_route, (200, DEALS))
    assert c.get(f"/api/markets/deals?{qs}").status_code == 422
    assert calls == []


FAILURES = [
    pytest.param((503, {"detail": "down"}), id="http-503"),
    pytest.param((404, {"detail": "Not Found"}), id="route-not-deployed"),
    pytest.param((200, {"as_of": "2026-10-13"}), id="200-without-the-list"),
    pytest.param((200, None), id="200-not-json"),
    pytest.param(daas_client.DaasError("timed out"), id="unreachable"),
]


@pytest.mark.parametrize("reply", FAILURES)
@pytest.mark.parametrize("path", ["/api/markets/sector-returns", "/api/markets/deals"])
def test_a_failing_data_platform_is_502_never_an_empty_list(monkeypatch, reply, path):
    c, _ = _client(monkeypatch, desk_route, reply)
    r = c.get(path)
    assert (r.status_code, r.json()) == (502, {"detail": "upstream_unavailable"})


@pytest.mark.parametrize("path", ["/api/markets/sector-returns", "/api/markets/deals"])
def test_an_unconfigured_data_platform_is_502_and_is_not_called(monkeypatch, path):
    c, calls = _client(monkeypatch, desk_route, (200, DEALS), configured=False)
    assert c.get(path).status_code == 502 and calls == []


def test_empty_deals_are_200_with_the_as_of_date(monkeypatch):
    empty = {**DEALS, "count": 0, "total": 0, "rows": []}
    c, _ = _client(monkeypatch, desk_route, (200, empty))
    r = c.get("/api/markets/deals?kind=block&days=1")
    assert r.status_code == 200 and r.json()["rows"] == [] and r.json()["as_of"] == "2026-10-13"


@pytest.mark.parametrize("path", ["/api/markets/sector-returns", "/api/markets/deals"])
def test_desk_market_routes_need_a_signed_in_user(monkeypatch, path):
    c, calls = _client(monkeypatch, desk_route, (200, DEALS), signed_in=False)   # the real deps.get_current_user
    r = c.get(path)
    assert (r.status_code, r.json()) == (401, {"detail": "Not authenticated"})
    assert calls == []


# ── /api/fno/scan/buildup ────────────────────────────────────────────────────

def test_buildup_scan_forwards_the_day_and_passes_the_answer_through(monkeypatch):
    c, calls = _client(monkeypatch, fno_route, (200, BUILDUP))
    assert c.get("/api/fno/scan/buildup").json() == BUILDUP
    assert c.get("/api/fno/scan/buildup?date=2026-10-12").status_code == 200
    assert calls == [("/desk/fno-buildup", None), ("/desk/fno-buildup", {"date": "2026-10-12"})]


def test_buildup_scan_is_not_caught_by_the_symbol_routes(monkeypatch):
    c, calls = _client(monkeypatch, fno_route, (200, BUILDUP))
    c.get("/api/fno/scan/buildup")
    assert [p for p, _ in calls] == ["/desk/fno-buildup"]       # never /fno/SCAN/...


def test_buildup_scan_rejects_a_bad_date(monkeypatch):
    c, calls = _client(monkeypatch, fno_route, (200, BUILDUP))
    assert c.get("/api/fno/scan/buildup?date=13-10-2026").status_code == 422
    assert calls == []


@pytest.mark.parametrize("reply", FAILURES)
def test_buildup_scan_failure_is_502(monkeypatch, reply):
    c, _ = _client(monkeypatch, fno_route, reply)
    r = c.get("/api/fno/scan/buildup")
    assert (r.status_code, r.json()) == (502, {"detail": "upstream_unavailable"})


def test_buildup_scan_with_no_rows_is_200(monkeypatch):
    empty = {**BUILDUP, "as_of": "2026-10-02", "universe": 0, "rows": [],
             "counts": {k: 0 for k in BUILDUP["counts"]}}
    c, _ = _client(monkeypatch, fno_route, (200, empty))
    r = c.get("/api/fno/scan/buildup?date=2026-10-02")
    assert r.status_code == 200 and r.json()["rows"] == [] and r.json()["as_of"] == "2026-10-02"


def test_buildup_scan_needs_a_signed_in_user(monkeypatch):
    c, calls = _client(monkeypatch, fno_route, (200, BUILDUP), signed_in=False)
    r = c.get("/api/fno/scan/buildup")
    assert (r.status_code, r.json()) == (401, {"detail": "Not authenticated"}) and calls == []


# ── /api/markets/home breadth ────────────────────────────────────────────────

EOD = {"advances": 1200, "declines": 900, "universe_size": 2193, "pct_above_20ema": 41.5, "pct_above_50ema": 38.0,
       "new_52w_highs": 12, "new_52w_lows": 30}
LIVE = {"advances": 30, "declines": 18, "unchanged": 2, "universe": 50}


def test_breadth_names_the_end_of_day_bhavcopy_universe():
    b = markets._breadth(EOD, LIVE)
    assert b["universe"] == 2193 and b["universe_kind"] == "bhavcopy"
    assert (b["advances"], b["declines"], b["unchanged"]) == (1200, 900, 93)
    assert b["pct_above_20ema"] == 41.5 and b["new_52w_lows"] == 30 and b["tone"] == "POSITIVE"


def test_breadth_names_the_live_nifty50_fallback():
    b = markets._breadth({}, LIVE)
    assert b["universe"] == 50 and b["universe_kind"] == "nifty50_live"
    assert (b["advances"], b["declines"], b["unchanged"]) == (30, 18, 2)
    assert b["pct_above_20ema"] is None


def test_breadth_without_either_source_names_no_universe():
    b = markets._breadth({}, {})
    assert b["universe"] is None and b["universe_kind"] is None and b["advances"] is None and b["tone"] == "NEUTRAL"


def test_breadth_universe_stays_a_bare_count_for_the_existing_screens():
    # frontend-v5 MarketBreadthC parses `universe` as z.number().nullable(); an object there fails /markets/home
    assert isinstance(markets._breadth(EOD, LIVE)["universe"], int)


# ── /api/filings/feed exchange ───────────────────────────────────────────────

@pytest.mark.parametrize("source,exchange", [("NSE_ANN", "NSE"), ("BSE_ANN", "BSE"), ("bse_ann", "BSE"),
                                             ("SEBI", None), ("RBI", None), (None, None), ("", None)])
def test_exchange_comes_from_the_stored_source(source, exchange):
    assert filings._exchange(source) == exchange


def test_exchange_is_not_guessed_from_the_url():
    row = filings._row({"id": "a1", "symbol": "ABC", "source": None, "url": "https://www.bseindia.com/xml-data/corpfiling/x.pdf"})
    assert row["exchange"] is None


def test_feed_rows_carry_the_exchange(monkeypatch):
    articles = [{"id": "n1", "symbol": "INFY", "company": "Infosys", "when": "2026-10-13T10:00:00+05:30", "source": "NSE_ANN",
                 "title": "Press Release", "url": "https://nsearchives.nseindia.com/a.pdf"},
                {"id": "b1", "symbol": "TCS", "company": "TCS", "when": "2026-10-13T09:00:00+05:30", "source": "BSE_ANN",
                 "title": "Outcome", "url": "https://www.bseindia.com/b.pdf"}]

    async def fake_feed(*a, **k):
        return {"articles": articles, "total": 2, "categories": {}}

    async def no_insights(ids):
        return {}

    async def fake_user(request: Request):
        return {"user_id": "u1"}
    monkeypatch.setattr(filings, "_feed", fake_feed)
    monkeypatch.setattr(filings, "_insights_for", no_insights)
    monkeypatch.setattr(filings, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(filings.router)
    r = TestClient(app).get("/api/filings/feed?days=7")
    assert r.status_code == 200
    assert [(x["id"], x["exchange"]) for x in r.json()["rows"]] == [("n1", "NSE"), ("b1", "BSE")]
