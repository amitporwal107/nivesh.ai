"""GET /api/portfolio/correlation and /api/portfolio/market-cap-split (routes/portfolio_desk.py).

No network, no Mongo: the holdings builder (services.portfolio_enrichment.build_enriched_portfolio) and
`daas_client.get_raw` are replaced with fixtures — MOCK, not real data — in the shapes the real code returns
(enriched holding rows; DaaS /prices/adjusted rows newest first; DaaS /indices/{name}/constituents envelopes).
The route's own work runs for real: equity filter, merging one stock held in two accounts, the session calendar,
log returns, Pearson, skip reasons, bucket placement and error mapping. The correlation maths is checked against
numpy on the same series. Real figures come from the data test in the report (staging warehouse, read-only).
"""
from __future__ import annotations

import asyncio
import copy
import math
import random
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.portfolio_desk as route

# ── fixtures (MOCK — not real data) ──────────────────────────────────────────


def _days(n: int, start: date = date(2026, 3, 2)) -> List[str]:
    """n weekdays from `start`, oldest first."""
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _series(n: int = 140, seed: int = 7) -> Dict[str, Dict[str, float]]:
    """Adjusted closes for four stocks driven by one common factor: HDFCBANK and ICICIBANK move together,
    TCS loosely, INFY against them. NEWLIST has only the last 40 sessions."""
    rnd = random.Random(seed)
    days = _days(n)
    loads = {"HDFCBANK": (1.0, 0.004), "ICICIBANK": (1.0, 0.006), "TCS": (0.4, 0.012), "INFY": (-0.6, 0.01)}
    closes: Dict[str, Dict[str, float]] = {s: {days[0]: 100.0} for s in loads}
    for prev, d in zip(days, days[1:]):
        m = rnd.gauss(0, 0.01)
        for s, (beta, noise) in loads.items():
            closes[s][d] = closes[s][prev] * math.exp(beta * m + rnd.gauss(0, noise))
    closes["NEWLIST"] = {d: 50.0 + i * 0.1 + (i % 3) * 0.05 for i, d in enumerate(days[-40:])}
    return closes


SERIES = _series()


def _price_rows(sym: str, limit: int) -> List[Dict[str, Any]]:
    """What DaaS /prices/adjusted/{sym}?limit= answers: newest first, at most `limit` rows."""
    s = SERIES.get(sym, {})
    days = sorted(s, reverse=True)[:limit]
    return [{"symbol": sym, "as_of_date": d, "adj_close": s[d], "adj_open": s[d]} for d in days]


def _h(sym: Optional[str], value: float, weight: Optional[float], asset_type: str = "equity",
       isin: Optional[str] = None, name: Optional[str] = None) -> Dict[str, Any]:
    return {"holding_id": f"h_{sym or name}_{value}", "name": name or sym, "isin": isin, "nse_symbol": sym,
            "asset_type": asset_type, "value_rs": value, "weight_pct": weight}


HOLDINGS = [
    _h("HDFCBANK", 50000.0, 10.0, isin="INE040A01034"),
    _h("HDFCBANK", 25000.0, 5.0, isin="INE040A01034"),          # same stock, second demat account
    _h("ICICIBANK", 40000.0, 8.0, isin="INE090A01021"),
    _h("TCS", 30000.0, 6.0, asset_type="stock", isin="INE467B01029"),
    _h("INFY", 20000.0, 4.0, isin="INE009A01021"),
    _h("NEWLIST", 10000.0, 2.0, isin="INE999Z01011"),
    _h(None, 5000.0, 1.0, isin="INE111X01011", name="Unlisted Co"),
    _h(None, 300000.0, 60.0, asset_type="mutual_fund", name="Some Flexi Cap Fund"),
    _h(None, 20000.0, 4.0, asset_type="sgb", name="SGB 2031"),
]


def _client(monkeypatch, *, holdings: Any = None, reply=None, configured: bool = True):
    """reply(path, params) → (status, body) | Exception. Records every DaaS call."""
    calls: List[tuple] = []
    state = {"in_flight": 0, "max_in_flight": 0}

    async def build(user_id: str, use_cache: bool = True):
        assert user_id == "u1"
        if isinstance(holdings, Exception):
            raise holdings
        return {"holdings": copy.deepcopy(HOLDINGS if holdings is None else holdings), "totals": {}}

    async def get_raw(path: str, params: Optional[dict] = None, timeout: float = 10.0):
        calls.append((path, params))
        state["in_flight"] += 1
        state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
        await asyncio.sleep(0.001)
        state["in_flight"] -= 1
        r = (reply or _default_reply)(path, params)
        if isinstance(r, Exception):
            raise r
        return copy.deepcopy(r)

    async def fake_user(request: Request):
        return {"user_id": "u1", "email": "u1@example.com"}

    monkeypatch.setattr(route._pe, "build_enriched_portfolio", build)
    monkeypatch.setattr(route.daas_client, "get_raw", get_raw)
    monkeypatch.setattr(route.daas_client, "is_configured", lambda: configured)
    monkeypatch.setattr(route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app), calls, state


def _default_reply(path: str, params: Optional[dict]):
    if path.startswith("/prices/adjusted/"):
        sym = path.rsplit("/", 1)[1]
        return 200, {"data": _price_rows(sym, params["limit"]), "symbol": sym}
    raise AssertionError(f"unexpected DaaS path {path}")


def _np_corr(a: str, b: str, sessions: int) -> float:
    """Independent check: numpy on the last sessions+1 closes (both series have every day in the window)."""
    days = sorted(SERIES[a])[-(sessions + 1):]
    ra = np.diff(np.log([SERIES[a][d] for d in days]))
    rb = np.diff(np.log([SERIES[b][d] for d in days]))
    return float(np.corrcoef(ra, rb)[0, 1])


# ── pure maths ───────────────────────────────────────────────────────────────

def test_pearson_hand_worked_and_undefined_cases():
    # x = 1,2,3  y = 2,4,7: means 2, 13/3; sxy = (-1)(-7/3) + 0 + (1)(8/3) = 5; sxx = 2; syy = 49/9+1/9+64/9 = 114/9
    assert route.pearson([1, 2, 3], [2, 4, 7]) == pytest.approx(5 / math.sqrt(2 * 114 / 9))
    assert route.pearson([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert route.pearson([1, 1, 1], [1, 2, 3]) is None          # no variance → undefined, not 0
    assert route.pearson([1.0], [2.0]) is None


def test_log_returns_leave_a_gap_where_a_session_is_missing():
    cal = ["2026-10-07", "2026-10-08", "2026-10-09", "2026-10-12"]
    r = route.log_returns({"2026-10-07": 100.0, "2026-10-08": 110.0, "2026-10-12": 99.0}, cal)
    # 10-09 is missing: no return on 10-09 (no close) nor on 10-12 (no previous-session close) — never 10-08→10-12
    assert r == {"2026-10-08": pytest.approx(math.log(1.1))}


def test_correlate_matches_numpy_and_sorts_desc():
    sessions = 120
    closes = {s: SERIES[s] for s in ("HDFCBANK", "ICICIBANK", "TCS", "INFY")}
    out = route.correlate(closes, sessions)
    assert out["used"] == ["HDFCBANK", "ICICIBANK", "INFY", "TCS"] and out["skipped"] == []
    assert out["as_of"] == max(SERIES["HDFCBANK"])
    assert len(out["pairs"]) == 6 and out["pairs_excluded"] == 0
    for p in out["pairs"]:
        assert p["corr"] == pytest.approx(_np_corr(p["a"], p["b"], sessions), abs=1e-12)
        assert -1.0 <= p["corr"] <= 1.0 and p["common_sessions"] == sessions
    corrs = [p["corr"] for p in out["pairs"]]
    assert corrs == sorted(corrs, reverse=True)
    assert (out["pairs"][0]["a"], out["pairs"][0]["b"]) == ("HDFCBANK", "ICICIBANK")
    assert out["pairs"][-1]["corr"] < 0                          # INFY moves against the banks


def test_correlate_skips_a_short_history_with_its_reason():
    out = route.correlate({"HDFCBANK": SERIES["HDFCBANK"], "NEWLIST": SERIES["NEWLIST"], "GONE": {}}, 120)
    assert out["used"] == ["HDFCBANK"] and out["pairs"] == []
    assert out["skipped"] == [
        {"symbol": "GONE", "reason": "no adjusted prices at the data platform"},
        {"symbol": "NEWLIST", "reason": "fewer than 60 sessions of prices (39 in the last 120)"},
    ]


# ── GET /api/portfolio/correlation ───────────────────────────────────────────

def test_correlation_route_end_to_end(monkeypatch):
    c, calls, state = _client(monkeypatch)
    r = c.get("/api/portfolio/correlation", params={"sessions": 120, "limit": 10})
    assert r.status_code == 200, r.text
    d = r.json()
    # equity only (equity + stock), merged by symbol; the fund and the SGB are never priced
    assert sorted(p for p, _ in calls) == sorted(f"/prices/adjusted/{s}" for s in
                                                ("HDFCBANK", "ICICIBANK", "INFY", "NEWLIST", "TCS"))
    assert all(params == {"limit": 121} for _, params in calls)
    assert state["max_in_flight"] <= route.PRICE_READS_AT_ONCE
    assert d["as_of"] == max(SERIES["HDFCBANK"]) and d["sessions"] == 120
    assert d["method"] == route.CORR_METHOD and d["source"] == "nidp.prices_eod_adjusted via DaaS"
    assert d["holdings_used"] == 4
    assert d["holdings_skipped"] == [
        {"symbol": "INE111X01011", "reason": "no NSE symbol on record"},
        {"symbol": "NEWLIST", "reason": "fewer than 60 sessions of prices (39 in the last 120)"},
    ]
    assert d["pairs_total"] == 6 and len(d["pairs"]) == 6 and d["high_threshold"] == 0.7
    top = d["pairs"][0]
    assert (top["a"], top["b"]) == ("HDFCBANK", "ICICIBANK")
    assert top["weight_a_pct"] == 15.0 and top["weight_b_pct"] == 8.0     # 10 + 5 across two accounts
    for p in d["pairs"]:
        assert p["corr"] == round(_np_corr(p["a"], p["b"], 120), 2)
    exact = [_np_corr(p["a"], p["b"], 120) for p in d["pairs"]]
    assert d["avg_corr"] == round(sum(exact) / 6, 2)
    assert d["high_pairs"] == sum(1 for x in exact if x >= 0.7)


def test_correlation_limit_cuts_the_list_not_the_average(monkeypatch):
    c, _, _ = _client(monkeypatch)
    d = c.get("/api/portfolio/correlation", params={"limit": 2}).json()
    assert len(d["pairs"]) == 2 and d["pairs_total"] == 6
    full = c.get("/api/portfolio/correlation").json()
    assert d["avg_corr"] == full["avg_corr"]


def test_correlation_bounds(monkeypatch):
    c, _, _ = _client(monkeypatch)
    assert c.get("/api/portfolio/correlation", params={"sessions": 59}).status_code == 422
    assert c.get("/api/portfolio/correlation", params={"sessions": 251}).status_code == 422
    assert c.get("/api/portfolio/correlation", params={"limit": 0}).status_code == 422


def test_correlation_price_reads_are_bounded(monkeypatch):
    many = [_h(f"SYM{i}", 1.0, 1.0) for i in range(14)]
    c, calls, state = _client(monkeypatch, holdings=many)
    d = c.get("/api/portfolio/correlation").json()
    assert len(calls) == 14 and state["max_in_flight"] == route.PRICE_READS_AT_ONCE
    assert d["holdings_skipped"][0] == {"symbol": "SYM0", "reason": "no adjusted prices at the data platform"}
    assert d["pairs"] == [] and d["as_of"] is None


def test_correlation_fewer_than_two_usable_holdings(monkeypatch):
    c, _, _ = _client(monkeypatch, holdings=[_h("HDFCBANK", 1.0, 1.0), _h("NEWLIST", 1.0, 1.0)])
    d = c.get("/api/portfolio/correlation").json()
    assert d["pairs"] == [] and d["avg_corr"] is None and d["holdings_used"] == 1
    assert d["holdings_skipped"][0]["symbol"] == "NEWLIST"


def test_correlation_no_stocks_makes_no_daas_call(monkeypatch):
    c, calls, _ = _client(monkeypatch, holdings=[_h(None, 1000.0, 100.0, asset_type="mutual_fund", name="F")])
    d = c.get("/api/portfolio/correlation").json()
    assert calls == [] and d["pairs"] == [] and d["as_of"] is None and d["holdings_used"] == 0


def test_correlation_one_failed_read_is_skipped_with_its_reason(monkeypatch):
    from services.copilot_tools.daas_client import DaasError

    def reply(path, params):
        return DaasError("boom") if path.endswith("/TCS") else _default_reply(path, params)
    c, _, _ = _client(monkeypatch, reply=reply)
    d = c.get("/api/portfolio/correlation").json()
    assert {"symbol": "TCS", "reason": "price read failed at the data platform"} in d["holdings_skipped"]
    assert d["holdings_used"] == 3 and d["pairs_total"] == 3


@pytest.mark.parametrize("failure", ["error", "http500", "not_configured"])
def test_correlation_daas_down_is_502_never_an_empty_answer(monkeypatch, failure):
    from services.copilot_tools.daas_client import DaasError
    reply = (lambda p, q: DaasError("down")) if failure == "error" else (lambda p, q: (500, {"detail": "x"}))
    c, _, _ = _client(monkeypatch, reply=reply, configured=failure != "not_configured")
    r = c.get("/api/portfolio/correlation")
    assert r.status_code == 502 and r.json()["detail"] == "upstream_unavailable"


@pytest.mark.parametrize("path", ["/api/portfolio/correlation", "/api/portfolio/market-cap-split"])
def test_holdings_failure_is_503(monkeypatch, path):
    c, calls, _ = _client(monkeypatch, holdings=RuntimeError("mongo down"))
    r = c.get(path)
    assert r.status_code == 503 and r.json()["detail"] == "holdings_unavailable" and calls == []


# ── GET /api/portfolio/market-cap-split ──────────────────────────────────────

def _list(*members) -> List[Dict[str, Any]]:
    return [{"symbol": s, "isin": i, "company_name": s} for s, i in members]


LARGE = _list(("HDFCBANK", "INE040A01034"), ("ICICIBANK", "INE090A01021"), ("LTM", "INE214T01019"))
MID = _list(("TCS", "INE467B01029"))
SMALL = _list(("NEWLIST", "INE999Z01011"))
TOTAL = LARGE + MID + SMALL + _list(("INFY", "INE009A01021"))

CAP_HOLDINGS = [
    _h("HDFCBANK", 50000.0, 10.0, isin="INE040A01034"),
    _h("HDFCBANK", 25000.0, 5.0, isin="INE040A01034"),
    _h("ICICIBANK", 40000.0, 8.0, isin="INE090A01021"),
    _h("LTIM", 15000.0, 3.0, isin="INE214T01019"),               # renamed on NSE: matches LTM by ISIN
    _h("TCS", 30000.0, 6.0, asset_type="stock", isin="INE467B01029"),
    _h("NEWLIST", 10000.0, 2.0, isin="INE999Z01011"),
    _h("INFY", 20000.0, 4.0, isin="INE009A01021"),                # pretend micro for the test
    _h("SMEX", 5000.0, 1.0, isin="INE555S01011"),                 # in no list
    _h(None, 5000.0, 1.0, isin="INE111X01011", name="Unlisted Co"),
    _h(None, 300000.0, 60.0, asset_type="mutual_fund", name="Some Flexi Cap Fund"),
    _h(None, 20000.0, 4.0, asset_type="sgb", name="SGB 2031"),
]
EQUITY_TOTAL = 50000 + 25000 + 40000 + 15000 + 30000 + 10000 + 20000 + 5000 + 5000


def _cap_reply(lists: Dict[str, Optional[List[Dict[str, Any]]]]):
    def reply(path, params):
        from urllib.parse import unquote
        assert path.startswith("/indices/") and path.endswith("/constituents") and params == {"limit": 1000}
        name = unquote(path[len("/indices/"):-len("/constituents")])
        rows = lists.get(name)
        if rows is None:   # the real DaaS answer when the warehouse has no list for the index
            return 200, {"data": [], "count": 0, "index_name": name, "as_of": None}
        return 200, {"data": rows, "count": len(rows), "index_name": name, "as_of": "2026-10-13"}
    return reply


def _bucket(d, name):
    return next(b for b in d["buckets"] if b["bucket"] == name)


def test_market_cap_split_all_lists_present(monkeypatch):
    reply = _cap_reply({"Nifty 100": LARGE, "Nifty Midcap 150": MID, "Nifty Smallcap 250": SMALL,
                        "Nifty Total Market": TOTAL})
    c, calls, _ = _client(monkeypatch, holdings=CAP_HOLDINGS, reply=reply)
    r = c.get("/api/portfolio/market-cap-split")
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(calls) == 4 and d["available"] is True and d["reason"] is None and d["unsplit"] is None
    assert d["as_of"] == "2026-10-13" and d["method"] == route.CAP_METHOD and "index_constituents" in d["source"]
    assert d["total_value_rs"] == EQUITY_TOTAL
    large, mid, small, micro, uncl = (_bucket(d, b) for b in ("large", "mid", "small", "micro", "unclassified"))
    assert large["symbols"] == ["HDFCBANK", "ICICIBANK", "LTIM"] and large["value_rs"] == 130000.0
    assert (mid["symbols"], small["symbols"], micro["symbols"]) == (["TCS"], ["NEWLIST"], ["INFY"])
    assert uncl["symbols"] == ["SMEX", "INE111X01011"] and uncl["count"] == 2
    assert sum(b["value_rs"] for b in d["buckets"]) == EQUITY_TOTAL
    assert sum(b["weight_pct"] for b in d["buckets"]) == pytest.approx(100.0, abs=0.05)
    assert large["weight_pct"] == round(130000 / EQUITY_TOTAL * 100, 2)
    assert d["excluded"]["funds_value_rs"] == 320000.0 and d["excluded"]["holdings"] == 2


def test_market_cap_split_without_midcap_and_smallcap_lists(monkeypatch):
    """Today's warehouse: Nifty 100 and Total Market exist, Midcap 150 and Smallcap 250 do not."""
    reply = _cap_reply({"Nifty 100": LARGE, "Nifty Total Market": TOTAL})
    c, _, _ = _client(monkeypatch, holdings=CAP_HOLDINGS, reply=reply)
    d = c.get("/api/portfolio/market-cap-split").json()
    assert d["available"] is False
    assert d["reason"].startswith("Nifty Midcap 150, Nifty Smallcap 250 constituents are not in the warehouse yet")
    large = _bucket(d, "large")
    assert large["available"] is True and large["value_rs"] == 130000.0 and large["count"] == 3
    for name in ("mid", "small", "micro", "unclassified"):
        b = _bucket(d, name)
        assert b["available"] is False and b["value_rs"] is None and b["count"] is None and b["symbols"] is None
    assert _bucket(d, "mid")["reason"] == "Nifty Midcap 150 constituents are not in the warehouse yet"
    assert _bucket(d, "micro")["reason"] == ("Nifty Midcap 150, Nifty Smallcap 250 constituents are not in the "
                                             "warehouse yet")
    u = d["unsplit"]
    assert u["count"] == 5 and u["symbols"] == ["TCS", "INFY", "NEWLIST", "SMEX", "INE111X01011"]
    assert large["value_rs"] + u["value_rs"] == d["total_value_rs"] == EQUITY_TOTAL
    assert "cannot be placed in a bucket" in u["reason"]
    assert [i["available"] for i in d["indices"]] == [True, False, False, True]
    assert [i["members"] for i in d["indices"]] == [3, None, None, 6]


def test_market_cap_split_daas_down_is_502(monkeypatch):
    from services.copilot_tools.daas_client import DaasError
    c, _, _ = _client(monkeypatch, holdings=CAP_HOLDINGS, reply=lambda p, q: DaasError("down"))
    r = c.get("/api/portfolio/market-cap-split")
    assert r.status_code == 502 and r.json()["detail"] == "upstream_unavailable"
    c, _, _ = _client(monkeypatch, holdings=CAP_HOLDINGS, reply=lambda p, q: (503, None))
    assert c.get("/api/portfolio/market-cap-split").status_code == 502
    c, _, _ = _client(monkeypatch, holdings=CAP_HOLDINGS, configured=False)
    assert c.get("/api/portfolio/market-cap-split").status_code == 502


def test_market_cap_split_no_equity(monkeypatch):
    reply = _cap_reply({"Nifty 100": LARGE, "Nifty Midcap 150": MID, "Nifty Smallcap 250": SMALL,
                        "Nifty Total Market": TOTAL})
    c, _, _ = _client(monkeypatch, holdings=[_h(None, 1000.0, 100.0, asset_type="mutual_fund", name="F")],
                      reply=reply)
    d = c.get("/api/portfolio/market-cap-split").json()
    assert d["total_value_rs"] == 0 and all(b["count"] == 0 and b["weight_pct"] is None for b in d["buckets"])
    assert d["excluded"]["funds_value_rs"] == 1000.0
