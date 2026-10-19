"""GET /api/portfolio/holding-risk (routes/portfolio_desk.py; backend addition B15, PRD §8.4).

Per stock held: average traded value and the days to sell the position at a share of the average daily volume
(liquidity and liquidation difficulty), overnight gaps (gap risk), the stock's own volatility; for today's stocks held
together: the drawdown and the 1-month volatility of their value series. Every level comes with the rule that set it.
Missing or stale prices are listed, never filled in.

Harness from test_portfolio_desk.py: the holdings builder and `daas_client.get_raw` are fakes. MOCK — not real data:
every series below is made up; expected figures are worked out by hand in the comments.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import pytest

import routes.portfolio_desk as route
from tests.test_portfolio_desk import _client, _h


def _days(n: int, start: date = date(2026, 6, 1)) -> List[str]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


# ── pure maths ───────────────────────────────────────────────────────────────
def test_gap_stats_hand_worked():
    cal = ["d0", "d1", "d2", "d3", "d4"]
    opens = {"d1": 103.0, "d2": 104.0, "d3": 95.0, "d4": 96.5}
    closes = {"d0": 100.0, "d1": 104.0, "d2": 100.0, "d3": 96.0, "d4": 97.0}
    g = route.gap_stats(opens, closes, cal, gap_pct=2.0)
    # gaps: d1 103/100 = +3.0%, d2 104/104 = 0, d3 95/100 = −5.0%, d4 96.5/96 = +0.52% → 2 of 4 at 2% or more
    assert (g["sessions"], g["gap_sessions"], g["rate_pct"]) == (4, 2, 50.0)
    assert (g["largest_down_pct"], g["largest_down_date"], g["largest_up_pct"]) == (-5.0, "d3", 3.0)


def test_gap_stats_need_both_closes_and_an_open():
    g = route.gap_stats({"d2": 99.0}, {"d0": 100.0, "d2": 100.0}, ["d0", "d1", "d2"], gap_pct=2.0)
    assert g["sessions"] == 0 and g["rate_pct"] is None and g["largest_down_pct"] is None


@pytest.mark.parametrize("close, volume, qty, adv_cr, days, level", [
    # ₹100 × 50,000 = ₹50 lakh a day = ₹0.5 Cr (< ₹10 Cr); 10% of 50,000 = 5,000 a day → 10,000 shares = 2 days
    (100.0, 50_000, 10_000, 0.5, 2.0, "medium"),
    (100.0, 50_000, 30_000, 0.5, 6.0, "high"),          # > 5 days
    (100.0, 50_000, 1_000, 0.5, 0.2, "medium"),          # quick to sell, but the stock trades under ₹10 Cr a day
    (1000.0, 200_000, 1_000, 20.0, 0.05, "low"),         # ₹20 Cr a day, 0.05 days
])
def test_liquidity_rule(close, volume, qty, adv_cr, days, level):
    rows = [{"raw_close": close, "raw_volume": volume} for _ in range(25)]
    out = route.liquidity_of(rows, qty)
    assert out["adv_cr"] == adv_cr and out["days_to_exit"] == days and out["level"] == level
    assert out["below_threshold"] is (adv_cr < route.LIQUIDITY_RULE["min_adv_cr"])


def test_liquidity_without_volume_is_unknown_not_zero():
    out = route.liquidity_of([{"raw_close": 100.0, "raw_volume": None}] * 25, 10)
    assert out == {"adv_rs": None, "adv_cr": None, "avg_volume": None, "days_to_exit": None, "below_threshold": None,
                   "level": None, "sessions": 0}


def test_drawdown_hand_worked():
    d = route.drawdown_of([100.0, 120.0, 90.0, 110.0], ["d0", "d1", "d2", "d3"])
    assert d == {"max_pct": -25.0, "peak_date": "d1", "trough_date": "d2", "current_pct": round((110 / 120 - 1) * 100, 2)}


def test_value_series_uses_todays_values_on_common_dates():
    closes = {"A": {"d0": 10.0, "d1": 11.0, "d2": 12.0}, "B": {"d0": 20.0, "d1": 20.0, "d2": 18.0}}
    dates, values = route.value_series(closes, {"A": 1200.0, "B": 1800.0}, ["d0", "d1", "d2"])
    # A: 1,200 / 12 = 100 shares; B: 1,800 / 18 = 100 shares → 3,000, 3,100, 3,000
    assert dates == ["d0", "d1", "d2"] and values == pytest.approx([3000.0, 3100.0, 3000.0])


def test_levels_follow_their_rules():
    assert route.level_for("volatility", 9.9) == "low" and route.level_for("volatility", 18.0) == "high"
    assert route.level_for("volatility", 30.0) == "very_high"
    assert route.level_for("drawdown", -9.0) == "low" and route.level_for("drawdown", -15.0) == "medium"
    assert route.level_for("drawdown", -25.0) == "high"
    assert route.level_for("gap", 4.0) == "low" and route.level_for("gap", 10.0) == "medium" and route.level_for("gap", 20.0) == "high"
    assert route.level_for("gap", None) is None


# ── the route ────────────────────────────────────────────────────────────────
DAYS = _days(90)


def _series() -> Dict[str, List[Dict[str, Any]]]:
    """LIQ: ₹1,000, rising 0.1% a day, opens at the previous close, 2,00,000 shares a day (₹20 Cr).
    THIN: ₹100 flat, every 4th session opens 3% below the previous close then recovers by the close, 50,000 shares a
    day (₹0.5 Cr). OLDBAR: like LIQ but its last bar is three sessions old (stale)."""
    out: Dict[str, List[Dict[str, Any]]] = {"LIQ": [], "THIN": [], "OLDBAR": []}
    c = 1000.0
    for i, d in enumerate(DAYS):
        prev = c
        c = round(c * 1.001, 4)
        out["LIQ"].append({"as_of_date": d, "adj_open": prev, "adj_close": c, "raw_close": c, "raw_volume": 200_000})
        out["OLDBAR"].append({"as_of_date": d, "adj_open": prev, "adj_close": c, "raw_close": c, "raw_volume": 200_000})
        gap = i > 0 and i % 4 == 0
        out["THIN"].append({"as_of_date": d, "adj_open": 97.0 if gap else 100.0, "adj_close": 100.0, "raw_close": 100.0,
                            "raw_volume": 50_000})
    out["OLDBAR"] = out["OLDBAR"][:-3]
    return out


SERIES = _series()


def _reply(path: str, params: Optional[dict]):
    if path.startswith("/prices/adjusted/"):
        sym = path.rsplit("/", 1)[1]
        rows = sorted(SERIES.get(sym, []), key=lambda r: r["as_of_date"], reverse=True)[: params["limit"]]
        return 200, {"data": rows, "symbol": sym}
    raise AssertionError(path)


HOLDINGS = [
    {**_h("LIQ", 100_000.0, 10.0, isin="INE000A01011"), "quantity": 100.0},
    {**_h("THIN", 600_000.0, 60.0, isin="INE000B01011"), "quantity": 6_000.0},
    {**_h("OLDBAR", 50_000.0, 5.0, isin="INE000C01011"), "quantity": 50.0},
    _h(None, 5_000.0, 0.5, isin="INE111X01011", name="Unlisted Co"),
    _h(None, 245_000.0, 24.5, asset_type="mutual_fund", name="A Fund"),
]


def test_route_end_to_end(monkeypatch):
    c, calls, _ = _client(monkeypatch, holdings=HOLDINGS, reply=_reply)
    r = c.get("/api/portfolio/holding-risk", params={"sessions": 60})
    assert r.status_code == 200, r.text
    d = r.json()
    assert sorted(p for p, _ in calls) == ["/prices/adjusted/LIQ", "/prices/adjusted/OLDBAR", "/prices/adjusted/THIN"]
    assert all(params == {"limit": 61} for _, params in calls)
    assert d["as_of"] == DAYS[-1] and d["sessions"] == 60 and d["source"] == route.CORR_SOURCE
    assert d["rules"]["liquidity"]["min_adv_cr"] == 10.0 and d["rules"]["gap"]["gap_pct"] == 2.0
    assert all(isinstance(d["rules"][k]["text"], str) and d["rules"][k]["text"] for k in ("liquidity", "gap", "volatility", "drawdown"))

    rows = {h["symbol"]: h for h in d["holdings"]}
    liq, thin = rows["LIQ"], rows["THIN"]
    # LIQ: closes ₹1,07x–₹1,09x over its last 20 sessions × 2,00,000 shares → about ₹21.6 Cr a day; 100 shares → 0.005 days
    assert 21.0 < liq["adv_cr"] < 22.0 and liq["days_to_exit"] == 0.01 and liq["liquidity_level"] == "low"
    # THIN: 6,000 shares ÷ (10% of 50,000) = 1.2 days; ₹0.5 Cr a day is under ₹10 Cr → medium
    assert (thin["adv_cr"], thin["days_to_exit"], thin["below_threshold"], thin["liquidity_level"]) == (0.5, 1.2, True, "medium")
    # THIN gaps: every 4th of the 60 sessions → 15 of 60 = 25.0%, each −3.0%
    assert (thin["gap_sessions"], thin["gap_rate_pct"], thin["largest_gap_down_pct"]) == (15, 25.0, -3.0)
    assert liq["gap_sessions"] == 0 and liq["gap_rate_pct"] == 0.0
    assert rows["OLDBAR"]["stale"] is True and rows["OLDBAR"]["last_session"] == DAYS[-4]

    p = d["portfolio"]
    # Liquidity: THIN is under ₹10 Cr → medium; 6,00,000 of the 7,50,000 in stocks with prices = 80.0%
    assert p["liquidity"]["level"] == "medium" and p["liquidity"]["below_threshold_value_pct"] == 80.0
    assert p["liquidity"]["slowest"] == {"symbol": "THIN", "days_to_exit": 1.2}
    # Gap rate, value-weighted over LIQ, THIN and OLDBAR: (0 × 1,00,000 + 25 × 6,00,000 + 0 × 50,000) / 7,50,000 = 20.0 → high
    assert p["gap"]["rate_pct"] == 20.0 and p["gap"]["level"] == "high"
    assert p["gap"]["largest"]["symbol"] == "THIN" and p["gap"]["largest"]["pct"] == -3.0
    # Today's stocks held together (OLDBAR left out as stale): LIQ rises every day and THIN closes flat → no drawdown
    s = p["series"]
    assert s["symbols"] == ["LIQ", "THIN"] and s["excluded"] == [{"symbol": "OLDBAR", "reason": f"price is stale (last {DAYS[-4]})"}]
    # Coverage is of every direct stock's value, the unlisted one included: 7,00,000 of 7,55,000
    assert s["coverage_pct"] == round(700_000 / 755_000 * 100, 1) == 92.7
    assert p["drawdown"]["max_pct"] == 0.0 and p["drawdown"]["level"] == "low"
    assert p["volatility_1m"]["pct"] is not None and p["volatility_1m"]["level"] == "low"

    m = d["missing"]
    assert m["no_symbol"] == ["INE111X01011"] and m["stale"] == [{"symbol": "OLDBAR", "last_session": DAYS[-4]}]
    assert m["no_prices"] == [] and m["latest_session"] == DAYS[-1]


def test_route_with_no_stocks_makes_no_daas_call(monkeypatch):
    c, calls, _ = _client(monkeypatch, holdings=[_h(None, 1000.0, 100.0, asset_type="mutual_fund", name="F")], reply=_reply)
    d = c.get("/api/portfolio/holding-risk").json()
    assert calls == [] and d["holdings"] == [] and d["portfolio"]["liquidity"]["level"] is None
    assert d["portfolio"]["drawdown"]["max_pct"] is None


def test_route_failures(monkeypatch):
    from services.copilot_tools.daas_client import DaasError
    c, _, _ = _client(monkeypatch, holdings=HOLDINGS, reply=lambda p, q: DaasError("down"))
    r = c.get("/api/portfolio/holding-risk")
    assert (r.status_code, r.json()["detail"]) == (502, "upstream_unavailable")
    c, _, _ = _client(monkeypatch, holdings=RuntimeError("mongo"), reply=_reply)
    assert c.get("/api/portfolio/holding-risk").status_code == 503
    c, _, _ = _client(monkeypatch, holdings=HOLDINGS, reply=_reply)
    assert c.get("/api/portfolio/holding-risk", params={"sessions": 20}).status_code == 422


def test_a_stock_without_prices_is_listed_as_missing(monkeypatch):
    def reply(path, params):
        if path.endswith("/THIN"):
            return 200, {"data": [], "symbol": "THIN"}
        return _reply(path, params)
    c, _, _ = _client(monkeypatch, holdings=HOLDINGS, reply=reply)
    d = c.get("/api/portfolio/holding-risk", params={"sessions": 60}).json()
    assert d["missing"]["no_prices"] == ["THIN"]
    assert "THIN" not in {h["symbol"] for h in d["holdings"] if h["adv_cr"] is not None}
