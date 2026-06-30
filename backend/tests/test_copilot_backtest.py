"""Unit tests for the copilot historical "what-if" backtest.

Covers the pure math (lump-sum CAGR, SIP XIRR, trading-day snapping), the
free-text parsing, instrument resolution + weighting, the end-to-end engine with
synthetic price/NAV series (no DB / network), the insufficient-history guard, and
the intent routing that sends these queries to the backtest analyst.

All deterministic and offline — patches DaaS + the resolvers.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from services.copilot_tools import backtest as bt
from services.copilot_tools.symbol_resolver import Resolution
from services.copilot_tools.scheme_resolver import SchemeMatch
from nidp.services.copilot_agent.nodes.intent_patterns import match_agent


AS_OF = date(2026, 6, 30)


# ── pure math ────────────────────────────────────────────────────────────────

def test_lump_sum_doubling_two_years():
    r = bt.lump_sum(
        amount=100_000, entry_value=100.0, latest_value=200.0,
        entry_date=date(2024, 6, 30), latest_date=AS_OF,
    )
    assert r["invested"] == 100_000
    assert r["current_value"] == 200_000
    assert r["abs_return_pct"] == 100.0
    # ~2 years → CAGR ≈ 41.4%
    assert 41.0 <= r["cagr_pct"] <= 42.0


def test_add_months_clamps_leap_day():
    # 1 year before 29 Feb 2024 lands on a valid day in 2023 (no 29 Feb).
    assert bt._add_months(date(2024, 2, 29), -12) == date(2023, 2, 28)
    assert bt._add_months(date(2026, 6, 30), -36) == date(2023, 6, 30)


def test_snap_picks_first_on_or_after():
    series = [(date(2025, 1, 3), 10.0), (date(2025, 1, 6), 11.0), (date(2025, 1, 7), 12.0)]
    # target on a weekend (Jan 4-5 2025) → snaps forward to Jan 6
    assert bt._snap(series, date(2025, 1, 4)) == (date(2025, 1, 6), 11.0)
    # exact hit
    assert bt._snap(series, date(2025, 1, 3)) == (date(2025, 1, 3), 10.0)
    # beyond the series → None
    assert bt._snap(series, date(2025, 2, 1)) is None


def _flat_daily(start: date, end: date, value: float):
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append((d, value))
        d += timedelta(days=1)
    return out


def test_sip_flat_series_zero_return():
    series = _flat_daily(date(2025, 6, 30), AS_OF, 100.0)
    res = bt.sip(120_000, series, date(2025, 6, 30), AS_OF, months=12)
    assert res is not None
    data, flows = res
    assert data["installments"] == 12
    # invested == current when the price never moves → XIRR ≈ 0
    assert data["current_value"] == data["invested"]
    assert abs(data["xirr_pct"]) < 1.0


def test_sip_rising_series_positive_xirr():
    # value climbs from 100 to ~140 over the year
    out, d, v = [], date(2025, 6, 30), 100.0
    while d <= AS_OF:
        if d.weekday() < 5:
            out.append((d, round(v, 4)))
        v *= (1.40) ** (1 / 252)
        d += timedelta(days=1)
    res = bt.sip(120_000, out, date(2025, 6, 30), AS_OF, months=12)
    assert res is not None
    data, _ = res
    assert data["xirr_pct"] is not None and data["xirr_pct"] > 0


# ── parsing ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("invested 10L across X and Y", 10_00_000),
    ("put ₹2cr in stuff", 2_00_00_000),
    ("invest 50k", 50_000),
    ("invested in HDFC 3 years ago", bt.DEFAULT_AMOUNT),  # no amount → default
])
def test_parse_amount(text, expected):
    assert bt.parse_amount(text) == expected


def test_parse_periods():
    assert bt.parse_periods("1 year and 3 years ago") == [1, 3]
    assert bt.parse_periods("no horizon mentioned") == list(bt.DEFAULT_PERIODS)


def test_parse_fragments_strips_amount_and_tail():
    frags = bt.parse_fragments(
        "If I had invested 10L in HDFC Bank, Reliance and Parag Parikh Flexi Cap "
        "3 years ago, what is it worth today?"
    )
    names = [f[0] for f in frags]
    assert names == ["HDFC Bank", "Reliance", "Parag Parikh Flexi Cap"]
    assert all(f[1] is None for f in frags)


def test_parse_fragments_explicit_weights():
    frags = bt.parse_fragments("invest 30% HDFC Bank and 70% Reliance 1 year ago")
    assert frags == [("HDFC Bank", 30.0), ("Reliance", 70.0)]


# ── resolution + weighting ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_instruments_equal_weight():
    def fake_symbol(text):
        t = text.lower()
        if "reliance" in t:
            return Resolution(symbol="RELIANCE", display_name="Reliance", source="name")
        return Resolution()

    async def fake_scheme(text):
        return SchemeMatch(scheme_code="123456", scheme_name="Test Flexi Cap Fund", confidence=0.9)

    with patch("services.copilot_tools.symbol_resolver.resolve_symbol", fake_symbol), \
         patch("services.copilot_tools.scheme_resolver.resolve_scheme", fake_scheme):
        insts, unresolved = await bt.resolve_instruments(
            [("Reliance", None), ("Test Flexi Cap Fund", None)]
        )
    assert unresolved == []
    kinds = {i.ident: i.kind for i in insts}
    assert kinds["RELIANCE"] == "stock"
    assert kinds["123456"] == "mf"
    assert abs(sum(i.weight for i in insts) - 1.0) < 1e-9
    assert all(abs(i.weight - 0.5) < 1e-9 for i in insts)


@pytest.mark.asyncio
async def test_resolve_instruments_explicit_weight_normalised():
    def fake_symbol(text):
        t = text.lower()
        if "reliance" in t:
            return Resolution(symbol="RELIANCE", display_name="Reliance", source="name")
        if "tcs" in t:
            return Resolution(symbol="TCS", display_name="TCS", source="name")
        return Resolution()

    async def fake_scheme(text):
        return None

    with patch("services.copilot_tools.symbol_resolver.resolve_symbol", fake_symbol), \
         patch("services.copilot_tools.scheme_resolver.resolve_scheme", fake_scheme):
        insts, _ = await bt.resolve_instruments([("Reliance", 30.0), ("TCS", 70.0)])
    by = {i.ident: i.weight for i in insts}
    assert abs(by["RELIANCE"] - 0.30) < 1e-9
    assert abs(by["TCS"] - 0.70) < 1e-9


# ── end-to-end engine (synthetic series) ─────────────────────────────────────

def _growing_bulk_rows(start: date, end: date, v0: float, annual: float):
    """Daily bars growing at `annual` CAGR over TRADING days (so the realised
    CAGR over a full year of bars is ~annual)."""
    out, d, v = [], start, v0
    step = (annual) ** (1 / 252)
    while d <= end:
        if d.weekday() < 5:
            out.append({"as_of_date": d.isoformat(), "tret_close": round(v, 4),
                        "adj_close": round(v, 4)})
            v *= step
        d += timedelta(days=1)
    return out


@pytest.mark.asyncio
async def test_engine_end_to_end_stock_and_fund():
    stk = _growing_bulk_rows(date(2023, 1, 2), AS_OF, 100.0, 1.25)
    nav = [{"nav_date": r["as_of_date"], "nav": r["tret_close"]}
           for r in _growing_bulk_rows(date(2022, 1, 3), AS_OF, 200.0, 1.12)]

    async def fake_bulk(symbols, start, end, **kw):
        return {"STK": stk} if "STK" in symbols else {}

    async def fake_nav(code, start=None, end=None, **kw):
        return [r for r in nav
                if (not start or r["nav_date"] >= start) and (not end or r["nav_date"] <= end)]

    def fake_symbol(text):
        return Resolution(symbol="STK", display_name="STK", source="name") if "reliance" in text.lower() else Resolution()

    async def fake_scheme(text):
        return SchemeMatch(scheme_code="123456", scheme_name="Test Flexi Cap Fund", confidence=0.9)

    idx = [{"as_of_date": r["as_of_date"], "close_price": r["tret_close"]}
           for r in _growing_bulk_rows(date(2022, 1, 3), AS_OF, 20000.0, 1.15)]

    async def fake_index(name, start=None, end=None, **kw):
        return [r for r in idx
                if (not start or r["as_of_date"] >= start) and (not end or r["as_of_date"] <= end)]

    with patch("services.copilot_tools.daas_client.get_adjusted_prices_bulk", fake_bulk), \
         patch("services.copilot_tools.daas_client.get_mf_nav_history", fake_nav), \
         patch("services.copilot_tools.daas_client.get_index_eod_history", fake_index), \
         patch("services.copilot_tools.symbol_resolver.resolve_symbol", fake_symbol), \
         patch("services.copilot_tools.scheme_resolver.resolve_scheme", fake_scheme):
        res = await bt.get_historical_backtest(
            "If I had invested 10L in Reliance and Test Flexi Cap Fund "
            "1 year and 3 years ago, what is it worth today?",
            as_of=AS_OF,
        )

    assert res.ok
    assert res.data["amount"] == 10_00_000
    assert res.data["periods"] == [1, 3]
    p1, p3 = res.data["portfolio"]["1"], res.data["portfolio"]["3"]
    assert p1["status"] == "ok" and p3["status"] == "ok"
    assert p1["instruments_covered"] == 2 and p3["instruments_covered"] == 2
    # growth is positive, and 3y compounds more value than 1y
    assert p3["lump_sum"]["current_value"] > p1["lump_sum"]["current_value"]
    assert p1["lump_sum"]["cagr_pct"] > 0 and p1["sip"]["xirr_pct"] is not None
    # one row per instrument × period
    assert len(res.rows) == 4
    # the stock (25% CAGR) should out-CAGR the fund (12% CAGR) at 1y
    stk_1y = next(r for r in res.rows if r["identifier"] == "STK" and r["period_years"] == 1)
    mf_1y = next(r for r in res.rows if r["identifier"] == "123456" and r["period_years"] == 1)
    assert stk_1y["cagr_pct"] > mf_1y["cagr_pct"]
    # benchmark present and computed (~15% CAGR index)
    bench = res.data["benchmark"]
    assert bench["index"] == "Nifty 500"
    assert bench["1"]["status"] == "ok"
    assert 10.0 <= bench["3"]["lump_sum"]["cagr_pct"] <= 20.0


@pytest.mark.asyncio
async def test_benchmark_unavailable_degrades():
    stk = _growing_bulk_rows(date(2023, 1, 2), AS_OF, 100.0, 1.20)

    async def fake_bulk(symbols, start, end, **kw):
        return {"STK": stk} if "STK" in symbols else {}

    async def fake_index(name, start=None, end=None, **kw):
        return []  # index series unavailable

    def fake_symbol(text):
        return Resolution(symbol="STK", display_name="STK", source="name") if "reliance" in text.lower() else Resolution()

    async def fake_scheme(text):
        return None

    with patch("services.copilot_tools.daas_client.get_adjusted_prices_bulk", fake_bulk), \
         patch("services.copilot_tools.daas_client.get_index_eod_history", fake_index), \
         patch("services.copilot_tools.symbol_resolver.resolve_symbol", fake_symbol), \
         patch("services.copilot_tools.scheme_resolver.resolve_scheme", fake_scheme):
        res = await bt.get_historical_backtest("backtest 10L in Reliance 1 year ago", as_of=AS_OF)

    assert res.ok
    assert res.data["benchmark"]["status"] == "unavailable"
    # the backtest itself still succeeds without the benchmark
    assert res.data["portfolio"]["1"]["status"] == "ok"


@pytest.mark.asyncio
async def test_engine_flags_insufficient_history():
    # series only since mid-2025 → 3y lookback (2023-06) is impossible
    young = _growing_bulk_rows(date(2025, 6, 2), AS_OF, 50.0, 1.40)

    async def fake_bulk(symbols, start, end, **kw):
        return {"NEWSTK": young} if "NEWSTK" in symbols else {}

    async def fake_nav(code, start=None, end=None, **kw):
        return []

    def fake_symbol(text):
        return Resolution(symbol="NEWSTK", display_name="NewCo", source="name") if "newco" in text.lower() else Resolution()

    async def fake_scheme(text):
        return None

    with patch("services.copilot_tools.daas_client.get_adjusted_prices_bulk", fake_bulk), \
         patch("services.copilot_tools.daas_client.get_mf_nav_history", fake_nav), \
         patch("services.copilot_tools.symbol_resolver.resolve_symbol", fake_symbol), \
         patch("services.copilot_tools.scheme_resolver.resolve_scheme", fake_scheme):
        res = await bt.get_historical_backtest("backtest 10L in NewCo 3 years ago", as_of=AS_OF)

    assert res.ok
    row = next(r for r in res.rows if r["period_years"] == 3)
    assert row["status"] == "insufficient_history"
    assert row["data_since"] == "2025-06-02"
    assert res.data["portfolio"]["3"]["status"] == "insufficient_history"


@pytest.mark.asyncio
async def test_engine_no_instruments():
    res = await bt.get_historical_backtest("what would my money have done", as_of=AS_OF)
    assert not res.ok
    assert res.error in ("no_instruments", "unresolved")


@pytest.mark.asyncio
async def test_engine_no_price_data_returns_error():
    """Resolves instruments but the data layer returns nothing → explicit
    no_price_data error (so the node says 'couldn't load', not an empty widget)."""
    async def empty_bulk(symbols, start, end, **kw):
        return {}

    async def empty_index(name, start=None, end=None, **kw):
        return []

    def fake_symbol(text):
        return Resolution(symbol="STK", display_name="STK", source="name") if "reliance" in text.lower() else Resolution()

    async def fake_scheme(text):
        return None

    with patch("services.copilot_tools.daas_client.get_adjusted_prices_bulk", empty_bulk), \
         patch("services.copilot_tools.daas_client.get_index_eod_history", empty_index), \
         patch("services.copilot_tools.symbol_resolver.resolve_symbol", fake_symbol), \
         patch("services.copilot_tools.scheme_resolver.resolve_scheme", fake_scheme):
        res = await bt.get_historical_backtest("backtest 10L in Reliance 1 year ago", as_of=AS_OF)

    assert not res.ok
    assert res.error == "no_price_data"


@pytest.mark.asyncio
async def test_engine_data_call_failure_degrades_not_crashes():
    """A failing/slow DaaS call must not propagate — it degrades to no_price_data."""
    async def boom_bulk(symbols, start, end, **kw):
        raise TimeoutError("simulated slow edge")

    async def empty_index(name, start=None, end=None, **kw):
        return []

    def fake_symbol(text):
        return Resolution(symbol="STK", display_name="STK", source="name") if "reliance" in text.lower() else Resolution()

    async def fake_scheme(text):
        return None

    with patch("services.copilot_tools.daas_client.get_adjusted_prices_bulk", boom_bulk), \
         patch("services.copilot_tools.daas_client.get_index_eod_history", empty_index), \
         patch("services.copilot_tools.symbol_resolver.resolve_symbol", fake_symbol), \
         patch("services.copilot_tools.scheme_resolver.resolve_scheme", fake_scheme):
        res = await bt.get_historical_backtest("backtest 10L in Reliance 1 year ago", as_of=AS_OF)

    assert not res.ok
    assert res.error == "no_price_data"


# ── intent routing ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "If I had invested 10L in HDFC Bank and Reliance 3 years ago, what is it worth today?",
    "backtest 5 lakh across Infosys and TCS over 1 year and 3 years",
    "what if I invested in Parag Parikh Flexi Cap 3 years back",
    "how much would 1 lakh have grown to today if I bought TCS 5 years ago",
])
def test_routes_to_backtest(text):
    assert match_agent(text) == "backtest_analyst"


@pytest.mark.parametrize("text", [
    "how is my portfolio doing",
    "my portfolio returns",
    "what is the NAV of HDFC Flexi Cap",
    "show me the top large cap funds",
])
def test_does_not_hijack_other_intents(text):
    assert match_agent(text) != "backtest_analyst"
