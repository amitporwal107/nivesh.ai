"""routes/markets.py home-page helpers read NIDP data through the DaaS client.

The DaaS client is stubbed here; nothing in this file touches a database or
the network. All symbols and figures are made up.
"""
import asyncio

import pytest

from routes import markets
from services.copilot_tools import daas_client


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def daas(monkeypatch):
    """Stub the DaaS client; tests set the canned responses on the returned dict."""
    canned = {"fii_dii": None, "articles": None, "movers": {}}
    calls = []

    async def fii_dii(days=90):
        calls.append(("fii_dii", days))
        return canned["fii_dii"]

    async def articles(**kw):
        calls.append(("articles", kw))
        return canned["articles"]

    async def movers(cap="large"):
        calls.append(("movers", cap))
        return canned["movers"].get(cap)

    monkeypatch.setattr(daas_client, "is_configured", lambda: True)
    monkeypatch.setattr(daas_client, "get_market_pulse_fii_dii", fii_dii)
    monkeypatch.setattr(daas_client, "get_market_pulse_articles", articles)
    monkeypatch.setattr(daas_client, "get_market_pulse_movers", movers)
    canned["calls"] = calls
    return canned


def test_fii_dii_takes_the_newest_day(daas):
    daas["fii_dii"] = {"as_of": "2026-01-09", "daily": [
        {"date": "2026-01-09", "fii_net": -3568.9, "dii_net": 4743.256},
        {"date": "2026-01-08", "fii_net": 100.0, "dii_net": -50.0},
    ]}
    assert _run(markets._fii_dii()) == {"as_of": "2026-01-09", "fii_net_cr": -3568.9, "dii_net_cr": 4743.26}


@pytest.mark.parametrize("payload", [None, {}, {"daily": []}, {"daily": [{"date": "2026-01-09", "fii_net": None, "dii_net": None}]}])
def test_fii_dii_is_none_when_there_is_no_data(daas, payload):
    daas["fii_dii"] = payload
    assert _run(markets._fii_dii()) is None


def test_news_keeps_high_and_medium_impact_and_puts_high_first(daas):
    daas["articles"] = {"articles": [
        {"company": "Alpha Ltd", "symbol": "ALPHA", "title": "Order win", "category": "Markets", "impact": "medium", "sentiment": "positive", "when": "2026-01-09T10:00:00+00:00"},
        {"company": "Beta Ltd", "symbol": "BETA", "title": "Trading window", "category": "Regulatory", "impact": "high", "sentiment": None, "when": "2026-01-09T09:00:00+00:00"},
        {"company": "Gamma Ltd", "symbol": "GAMMA", "title": "Results", "category": "Earnings", "impact": "high", "sentiment": "negative", "when": "2026-01-09T08:00:00+00:00"},
        {"company": "Delta Ltd", "symbol": "DELTA", "title": "Newspaper ad", "category": "Markets", "impact": None, "sentiment": None, "when": "2026-01-09T07:00:00+00:00"},
        {"company": "Epsilon Ltd", "symbol": "EPS", "title": "Misc", "category": "Other", "impact": "medium", "sentiment": None, "when": "2026-01-09T06:00:00+00:00"},
    ]}
    news = _run(markets._news(limit=5))
    assert [n["symbol"] for n in news] == ["GAMMA", "ALPHA"]
    assert news[0] == {"title": "Gamma Ltd — Results", "category": "Earnings",
                       "when": "2026-01-09T08:00:00+00:00", "symbol": "GAMMA", "sentiment": "negative"}


def test_news_respects_the_limit(daas):
    daas["articles"] = {"articles": [
        {"company": f"Co {i}", "symbol": f"S{i}", "title": "t", "category": "Markets", "impact": "high", "when": None}
        for i in range(9)
    ]}
    assert len(_run(markets._news(limit=4))) == 4


def test_top_movers_merges_cap_segments_and_reranks(daas):
    daas["movers"] = {
        "large": {"as_of": "2026-01-09", "gainers": [{"symbol": "L1", "name": "Large One", "price": 100.0, "change_pct": 2.0}],
                  "losers": [{"symbol": "L2", "name": "Large Two", "price": 50.0, "change_pct": -1.0}]},
        "mid":   {"as_of": "2026-01-09", "gainers": [{"symbol": "M1", "name": "Mid One", "price": 10.0, "change_pct": 9.5}],
                  "losers": [{"symbol": "M2", "name": None, "price": 5.0, "change_pct": -7.25}]},
        "small": None,                       # one segment unavailable must not empty the panel
    }
    out = _run(markets._top_movers(limit=4))
    assert out["as_of"] == "2026-01-09"
    assert [g["symbol"] for g in out["gainers"]] == ["M1", "L1"]
    assert [l["symbol"] for l in out["losers"]] == ["M2", "L2"]
    assert out["losers"][0] == {"symbol": "M2", "name": "M2", "price": 5.0, "change_pct": -7.25}
    assert [c for c in daas["calls"] if c[0] == "movers"] == [("movers", "large"), ("movers", "mid"), ("movers", "small")]


def test_helpers_return_empty_without_touching_anything_when_daas_is_unconfigured(daas, monkeypatch):
    monkeypatch.setattr(daas_client, "is_configured", lambda: False)
    assert _run(markets._fii_dii()) is None
    assert _run(markets._news()) == []
    assert _run(markets._top_movers()) == {"as_of": None, "gainers": [], "losers": []}
    assert daas["calls"] == []


def test_home_helpers_no_longer_reference_nidp_tables_in_sql():
    import inspect
    src = "".join(inspect.getsource(f) for f in (markets._top_movers, markets._fii_dii, markets._news))
    assert "pool" not in src and "conn.fetch" not in src
    for relation in ("analytics.mv_top_momentum", "nidp.fii_dii_flows", "nidp.corporate_announcements"):
        assert relation not in src
