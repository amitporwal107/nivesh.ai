"""POST /api/screeners/run — run a rule list against the day's stock feature rows.

No network, no Mongo: `nidp_stock_screener` (the data-platform read) is replaced
by a recorder that returns fixture rows, so the route's own work runs for real —
rule translation, matching, coverage, the cut at `limit`, and the unreachable
path. The widget is shaped by the real `build_stock_screener_widget`.

Fixture rows use the raw column names GET /v1/stocks/screener returns
(nidp/services/daas_api/routers/stock_scores.py `_PRIMITIVE_COLS`).
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from routes import screeners as route
from services.copilot_tools import stock_intelligence

URL = "/api/screeners/run"


def _row(symbol: str, **cols: Any) -> Dict[str, Any]:
    return {"symbol": symbol, **cols}


# Six stocks. ROCE is empty for every one of them (the staging situation the
# route has to explain); ROE is empty for two.
DAY: List[Dict[str, Any]] = [
    _row("ALPHA", sector="IT", market_cap_bucket="LARGE_CAP", market_cap_cr=900000, pe_ttm=30.0, roe_pct=25.0, debt_to_equity=0.1, rsi14=55.0),
    _row("BRAVO", sector="IT Services", market_cap_bucket="LARGE_CAP", market_cap_cr=400000, pe_ttm=12.0, roe_pct=18.0, debt_to_equity=0.0, rsi14=40.0),
    _row("CHARLIE", sector="Banks", market_cap_bucket="MID_CAP", market_cap_cr=30000, pe_ttm=15.0, roe_pct=17.99, debt_to_equity=None, rsi14=70.0),
    _row("DELTA", sector=None, market_cap_bucket="SMALL_CAP", market_cap_cr=4000, pe_ttm=None, roe_pct=40.0, debt_to_equity=2.5, rsi14=20.0),
    _row("ECHO", sector="Pharma", market_cap_bucket=None, market_cap_cr=None, pe_ttm=8.0, roe_pct=None, debt_to_equity=0.4, rsi14=50.0),
    _row("FOXTROT", sector=None, market_cap_bucket=None, market_cap_cr=None, pe_ttm=9.0, roe_pct=None, debt_to_equity=0.2, rsi14=45.0),
]


class _NoDb:
    """Any use of the database in a run is a failure: the route is read-only
    and reads market data only."""

    def __getattr__(self, name: str):
        raise AssertionError(f"POST /screeners/run touched db.{name}")


def _client(monkeypatch, rows: Optional[List[Dict[str, Any]]] = None, *, ok: bool = True,
            as_of: Optional[str] = "2026-10-12", raises: Optional[Exception] = None, signed_in: bool = True):
    calls: List[Dict[str, Any]] = []

    async def fake_screener(**kwargs):
        calls.append(kwargs)
        if raises is not None:
            raise raises
        if not ok:
            return {"rows": [], "as_of_date": None, "ok": False}
        return {"rows": copy.deepcopy(DAY if rows is None else rows), "as_of_date": as_of, "ok": True}

    monkeypatch.setattr(stock_intelligence, "nidp_stock_screener", fake_screener)
    monkeypatch.setattr(route, "db", _NoDb())
    if signed_in:
        async def fake_user(request: Request):
            return {"user_id": "u1", "email": "u1@example.com"}
        monkeypatch.setattr(route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app), calls


def _tickers(body: Dict[str, Any]) -> List[str]:
    return [r["ticker"] for r in body["widget"]["universe"]]


# ── TC-1: rules → widget filters; the read is the whole day, unfiltered ──────
def test_rules_become_widget_filters_and_the_whole_day_is_read(monkeypatch):
    c, calls = _client(monkeypatch)
    r = c.post(URL, json={"conditions": [
        {"key": "roe", "op": "over", "value": "18"},      # value as a string — the saved-screen shape
        {"key": "pe", "op": "under", "value": 15},        # value as a number
        {"key": "mcap", "op": "over", "value": "100"},
        {"key": "mcap", "op": "under", "value": "500000"},
    ]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["widget"]["filters"] == {"roe_min": 18.0, "pe_max": 15.0, "mcap_min": 100.0, "mcap_max": 500000.0}
    # One read, of the whole day: no threshold, sector or size is sent to the data
    # platform, so coverage and the match count describe every stock.
    assert calls == [{"sort_by": "market_cap_cr", "limit": 5000}]
    assert body["ok"] is True and body["as_of_date"] == "2026-10-12" and body["universe_complete"] is True
    assert _tickers(body) == ["BRAVO"] and body["matched"] == 1


def test_default_op_is_over_as_in_the_saved_shape(monkeypatch):
    c, _ = _client(monkeypatch)
    body = c.post(URL, json={"conditions": [{"key": "rsi", "value": "60"}]}).json()
    assert body["widget"]["filters"] == {"rsi_min": 60.0} and _tickers(body) == ["CHARLIE"]


def test_two_rules_on_one_side_of_a_metric_keep_the_stricter_bound(monkeypatch):
    c, _ = _client(monkeypatch)
    body = c.post(URL, json={"conditions": [
        {"key": "roe", "op": "over", "value": "10"}, {"key": "roe", "op": "over", "value": "20"},
        {"key": "pe", "op": "under", "value": "40"}, {"key": "pe", "op": "under", "value": "35"},
    ]}).json()
    assert body["widget"]["filters"] == {"roe_min": 20.0, "pe_max": 35.0}
    assert _tickers(body) == ["ALPHA"]


# ── TC-2: matching follows the widget's rule (inclusive bounds, empty fails) ──
def test_bounds_are_inclusive_and_a_stock_without_the_value_fails(monkeypatch):
    c, _ = _client(monkeypatch)
    over = c.post(URL, json={"conditions": [{"key": "roe", "op": "over", "value": "18"}]}).json()
    # 18.0 passes "over 18" (the data platform's own filter is roe_pct >= 18); 17.99 does
    # not; ECHO and FOXTROT have no ROE and fail.
    assert _tickers(over) == ["ALPHA", "BRAVO", "DELTA"] and over["matched"] == 3
    under = c.post(URL, json={"conditions": [{"key": "pe", "op": "under", "value": "12"}]}).json()
    # 12.0 passes "under 12"; DELTA has no P/E and fails rather than counting as zero.
    # ECHO and FOXTROT have no market cap, so they come last, in ticker order.
    assert _tickers(under) == ["BRAVO", "ECHO", "FOXTROT"]
    zero_is_a_value = c.post(URL, json={"conditions": [{"key": "de", "op": "under", "value": "0"}]}).json()
    assert _tickers(zero_is_a_value) == ["BRAVO"]


def test_rows_are_shaped_by_the_chat_widget_builder(monkeypatch):
    c, _ = _client(monkeypatch)
    body = c.post(URL, json={"conditions": [{"key": "roe", "op": "over", "value": "20"}]}).json()
    built = stock_intelligence.build_stock_screener_widget(
        [DAY[0], DAY[3]], initial_filters={"roe_min": 20.0}, as_of_date="2026-10-12")
    assert body["widget"] == built
    assert body["widget"]["universe"][0]["roe"] == 25.0 and body["widget"]["universe"][0]["name"] == "ALPHA"


# ── TC-3 / TC-4: coverage says which metric has no data ──────────────────────
def test_coverage_counts_filled_values_over_the_whole_day_not_over_the_matches(monkeypatch):
    c, _ = _client(monkeypatch)
    body = c.post(URL, json={"conditions": [
        {"key": "roe", "op": "over", "value": "18"}, {"key": "rsi", "op": "under", "value": "60"}]}).json()
    assert body["matched"] == 3
    cov = body["coverage"]
    assert cov["roe"] == {"filled": 4, "total": 6}          # a rule metric
    assert cov["rsi"] == {"filled": 6, "total": 6}          # a rule metric that is not a table column
    assert cov["pe"] == {"filled": 5, "total": 6}           # a default table column
    assert cov["sector"] == {"filled": 4, "total": 6}
    assert cov["mcap"] == {"filled": 4, "total": 6}
    assert cov["roce"] == {"filled": 0, "total": 6}
    # every default table column is reported, plus the rule metrics; nothing else
    columns = [col["key"] for col in body["widget"]["columns"]]
    assert set(cov) == set(columns) | {"roe", "rsi"}


def test_a_rule_on_a_metric_with_no_data_matches_nothing_and_coverage_says_why(monkeypatch):
    c, _ = _client(monkeypatch)
    body = c.post(URL, json={"conditions": [
        {"key": "roce", "op": "over", "value": "1"}, {"key": "pe", "op": "under", "value": "50"}]}).json()
    assert body["ok"] is True and body["matched"] == 0 and body["widget"]["universe"] == []
    assert body["coverage"]["roce"] == {"filled": 0, "total": 6}     # no data: the reason
    assert body["coverage"]["pe"] == {"filled": 5, "total": 6}       # has data: not the reason
    assert body["widget"]["filters"] == {"roce_min": 1.0, "pe_max": 50.0}


def test_no_match_with_data_present_is_distinguishable_from_no_data(monkeypatch):
    c, _ = _client(monkeypatch)
    body = c.post(URL, json={"conditions": [{"key": "roe", "op": "over", "value": "95"}]}).json()
    assert body["matched"] == 0 and body["coverage"]["roe"] == {"filled": 4, "total": 6}


def test_an_empty_day_is_reported_as_nothing_to_screen(monkeypatch):
    c, _ = _client(monkeypatch, rows=[])
    body = c.post(URL, json={"conditions": [{"key": "roe", "op": "over", "value": "1"}]}).json()
    assert body["ok"] is True and body["matched"] == 0 and body["coverage"]["roe"] == {"filled": 0, "total": 0}


# ── TC-5 / TC-6: size bucket and sector ──────────────────────────────────────
def test_size_bucket_keeps_that_bucket_and_reports_label_coverage(monkeypatch):
    c, calls = _client(monkeypatch)
    body = c.post(URL, json={"conditions": [], "bucket": "large"}).json()
    assert _tickers(body) == ["ALPHA", "BRAVO"] and body["matched"] == 2
    assert body["coverage"]["bucket"] == {"filled": 4, "total": 6}
    assert calls == [{"sort_by": "market_cap_cr", "limit": 5000}]
    mid = c.post(URL, json={"conditions": [{"key": "pe", "op": "under", "value": "20"}], "bucket": "mid"}).json()
    assert _tickers(mid) == ["CHARLIE"]
    assert _tickers(c.post(URL, json={"bucket": "small"}).json()) == ["DELTA"]
    # no bucket asked → no bucket entry
    assert "bucket" not in c.post(URL, json={"conditions": [{"key": "pe", "op": "under", "value": "20"}], "bucket": ""}).json()["coverage"]


def test_size_bucket_with_no_labels_in_the_data_matches_nothing_and_says_so(monkeypatch):
    unlabelled = [{**r, "market_cap_bucket": None} for r in DAY]
    c, _ = _client(monkeypatch, rows=unlabelled)
    body = c.post(URL, json={"conditions": [{"key": "pe", "op": "under", "value": "50"}], "bucket": "large"}).json()
    assert body["matched"] == 0 and body["coverage"]["bucket"] == {"filled": 0, "total": 6}
    assert body["coverage"]["pe"] == {"filled": 5, "total": 6}


def test_sector_is_a_case_insensitive_contains_like_the_data_platform(monkeypatch):
    c, _ = _client(monkeypatch)
    assert _tickers(c.post(URL, json={"sector": "it"}).json()) == ["ALPHA", "BRAVO"]
    assert _tickers(c.post(URL, json={"sector": " Services "}).json()) == ["BRAVO"]
    both = c.post(URL, json={"sector": "bank", "conditions": [{"key": "roe", "op": "over", "value": "10"}]}).json()
    assert _tickers(both) == ["CHARLIE"] and both["coverage"]["sector"] == {"filled": 4, "total": 6}


# ── TC-7: the cut at `limit` ─────────────────────────────────────────────────
def test_limit_cuts_the_rows_sent_but_not_the_match_count(monkeypatch):
    c, _ = _client(monkeypatch)
    rule = {"conditions": [{"key": "rsi", "op": "over", "value": "0"}]}
    body = c.post(URL, json={**rule, "limit": 2}).json()
    assert body["matched"] == 6 and _tickers(body) == ["ALPHA", "BRAVO"] and body["widget"]["count"] == 2
    # default is large enough for this day
    assert _tickers(c.post(URL, json=rule).json()) == ["ALPHA", "BRAVO", "CHARLIE", "DELTA", "ECHO", "FOXTROT"]


def test_a_read_that_fills_the_data_platform_page_is_flagged_incomplete(monkeypatch):
    full_page = [_row(f"S{i:04d}", rsi14=50.0) for i in range(5000)]
    c, _ = _client(monkeypatch, rows=full_page)
    body = c.post(URL, json={"conditions": [{"key": "rsi", "op": "over", "value": "10"}], "limit": 1}).json()
    assert body["universe_complete"] is False and body["matched"] == 5000 and _tickers(body) == ["S0000"]


# ── TC-9: the data platform does not answer ──────────────────────────────────
def test_unreachable_source_is_ok_false_with_an_empty_widget(monkeypatch):
    c, calls = _client(monkeypatch, ok=False)
    r = c.post(URL, json={"conditions": [{"key": "roe", "op": "over", "value": "18"}]})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and body["as_of_date"] is None and body["matched"] is None
    assert body["coverage"] == {} and body["universe_complete"] is False
    assert body["widget"]["universe"] == [] and body["widget"]["rows"] == [] and body["widget"]["count"] == 0
    assert body["widget"]["filters"] == {"roe_min": 18.0}
    assert len(calls) == 1


def test_a_failing_read_is_reported_the_same_way_not_as_a_500(monkeypatch):
    c, _ = _client(monkeypatch, raises=RuntimeError("connect refused"))
    r = c.post(URL, json={"conditions": [{"key": "roe", "op": "over", "value": "18"}]})
    assert r.status_code == 200 and r.json()["ok"] is False and r.json()["matched"] is None


# ── TC-10: bad input ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("payload", [
    {"conditions": [{"key": "piotroski", "op": "over", "value": "5"}]},       # not a screening metric
    {"conditions": [{"key": "large", "op": "over", "value": "1"}]},           # a size bucket is not a metric
    {"conditions": [{"key": "roe", "op": "equals", "value": "5"}]},           # unknown comparison
    {"conditions": [{"key": "roe", "op": "over", "value": "high"}]},          # not a number
    {"conditions": [{"key": "roe", "op": "over", "value": ""}]},              # a rule with no value
    {"conditions": [{"key": "roe", "op": "over", "value": "nan"}]},
    {"conditions": [{"key": "roe", "op": "over", "value": "inf"}]},
    {"conditions": [{"key": "roe", "op": "over"}]},                           # value missing
    {"conditions": [{"op": "over", "value": "5"}]},                           # key missing
    {"conditions": "roe over 5"},                                              # not a list
    {"conditions": [{"key": "roe", "op": "over", "value": "5"}], "bucket": "micro"},
    {"conditions": [{"key": "roe", "op": "over", "value": "5"}], "limit": 0},
    {"conditions": [{"key": "roe", "op": "over", "value": "5"}], "limit": 501},
    {"conditions": [{"key": "roe", "op": "over", "value": "5"}], "sector": "x" * 61},
    {"conditions": [{"key": "roe", "op": "over", "value": "5"}] * 51},        # too many rules
    {"conditions": []},                                                        # nothing to screen on
    {"conditions": [], "bucket": "", "sector": "  "},
    {},
])
def test_bad_input_is_rejected_before_any_read(monkeypatch, payload):
    c, calls = _client(monkeypatch)
    r = c.post(URL, json=payload)
    assert r.status_code == 422, (payload, r.status_code, r.text)
    assert calls == []


def test_an_unknown_metric_is_named_in_the_error(monkeypatch):
    c, _ = _client(monkeypatch)
    r = c.post(URL, json={"conditions": [{"key": "roe", "op": "over", "value": "5"}, {"key": "piotroski", "op": "over", "value": "5"}]})
    assert r.status_code == 422 and "piotroski" in r.json()["detail"] and "roe" not in r.json()["detail"]


def test_the_same_rules_give_the_widget_the_same_filters_as_the_chat_parser(monkeypatch):
    """Chat and screen must not drift: for every preset screen the chat widget
    offers, the chat's parser and this route hand the widget one filter dict."""
    from nidp.services.copilot_agent.nodes.recommendation import _parse_screen_filters

    c, _ = _client(monkeypatch)
    presets = stock_intelligence.build_stock_screener_widget([])["presets"]
    assert len(presets) == 9
    for preset in presets:
        chat_filters = _parse_screen_filters(preset["query"])["client_filters"]
        assert chat_filters, preset
        conditions = [
            {"key": fk[:-4], "op": "over" if fk.endswith("_min") else "under", "value": str(bound)}
            for fk, bound in chat_filters.items()
        ]
        body = c.post(URL, json={"conditions": conditions}).json()
        assert body["widget"]["filters"] == chat_filters, preset["name"]


def test_every_metric_the_chat_widget_labels_is_accepted(monkeypatch):
    c, _ = _client(monkeypatch)
    keys = list(stock_intelligence.build_stock_screener_widget([])["filter_labels"])
    assert len(keys) == 33
    body = c.post(URL, json={"conditions": [{"key": k, "op": "over", "value": "1"} for k in keys]})
    assert body.status_code == 200, body.text
    assert set(body.json()["widget"]["filters"]) == {f"{k}_min" for k in keys}


# ── TC-11: signed-out ────────────────────────────────────────────────────────
def test_signed_out_is_401_and_nothing_is_read(monkeypatch):
    # The real get_current_user: no session cookie and no bearer token.
    c, calls = _client(monkeypatch, signed_in=False)
    r = c.post(URL, json={"conditions": [{"key": "roe", "op": "over", "value": "18"}]})
    assert r.status_code == 401 and r.json()["detail"] == "Not authenticated"
    assert calls == []


# ── TC-16: the saved-screen routes are where they were ───────────────────────
def test_run_does_not_shadow_the_saved_screen_routes(monkeypatch):
    c, calls = _client(monkeypatch)
    inserted: List[Dict[str, Any]] = []

    class _Saved:
        async def insert_one(self, doc):
            inserted.append(dict(doc))

        async def find_one(self, query, projection=None):
            return None

    class _Db:
        saved_screeners = _Saved()

    monkeypatch.setattr(route, "db", _Db())
    made = c.post("/api/screeners", json={"name": "Quality", "query": "Screen stocks where ROE over 20",
                                          "conditions": [{"key": "roe", "op": "over", "value": "20"}], "bucket": ""})
    assert made.status_code == 200 and made.json()["name"] == "Quality" and made.json()["screener_id"].startswith("scr_")
    assert inserted[0]["conditions"] == [{"key": "roe", "op": "over", "value": "20"}] and calls == []
    # "run" is only a POST; as a GET it is an id that does not exist
    assert c.get("/api/screeners/run").status_code == 404
    paths = sorted((sorted(r.methods), r.path) for r in route.router.routes)
    assert paths == [
        (["DELETE"], "/api/screeners/{screener_id}"), (["GET"], "/api/screeners"), (["GET"], "/api/screeners/{screener_id}"),
        (["POST"], "/api/screeners"), (["POST"], "/api/screeners/run"), (["PUT"], "/api/screeners/{screener_id}"),
    ]


# ── P/E vs sector arrives under the data platform's alias ────────────────────
# GET /v1/stocks/screener selects `f.pe_vs_sector_pct AS pe_overvaluation_pct`,
# so the row key is the alias. The widget must still fill `peVsSector` from it.

def test_pe_vs_sector_is_read_from_the_platform_alias():
    from services.copilot_tools import stock_intelligence as si

    rows = [
        {"symbol": "ALIASED", "pe_overvaluation_pct": -12.5},
        {"symbol": "OWNNAME", "pe_vs_sector_pct": 8.0, "pe_overvaluation_pct": 99.0},
        {"symbol": "NEITHER"},
    ]
    universe = si.build_stock_screener_widget(rows)["universe"]
    assert [u["peVsSector"] for u in universe] == [-12.5, 8.0, None]

