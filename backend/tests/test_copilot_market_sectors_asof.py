"""Copilot market answers: sector returns and as-of dates reach the model.

All DaaS bodies below are MOCK — not real data; expected values are computed from the payload.
"""
import asyncio
from types import SimpleNamespace

from services.copilot_tools import daas_client, market_research as mr

# MOCK — not real data
SNAP = {"as_of_date": "2026-10-19", "nifty50_close": 22889.0, "nifty50_pct_change": -1.11,
        "india_vix": 14.77, "advances_count": 665, "declines_count": 2608, "unchanged_count": 50,
        "fii_cash_net_cr": -1148.64, "dii_cash_net_cr": 900.0, "rbi_10y_yield": 7.37,
        "index_as_of": "2026-10-19", "prices_as_of": "2026-10-19",
        "fii_dii_as_of": "2026-10-19", "yields_as_of": "2026-10-16"}
SECTORS = {"as_of": "2026-10-19", "source": "NSE index close (nidp.index_eod)", "sectors": [  # MOCK
    {"index": "Nifty IT", "sector": "IT", "date": "2026-10-19", "close": 30000.0,
     "ret_1d_pct": -2.0, "ret_1w_pct": 1.0, "ret_1m_pct": 3.0},
    {"index": "Nifty FMCG", "sector": "FMCG", "date": "2026-10-19", "close": 55000.0,
     "ret_1d_pct": 0.4, "ret_1w_pct": None, "ret_1m_pct": 0.5},
    {"index": "Nifty Bank", "sector": "Banks", "date": "2026-10-19", "close": 55488.0,
     "ret_1d_pct": -0.5, "ret_1w_pct": -1.0, "ret_1m_pct": 2.0}]}


def _run(monkeypatch, routes):
    async def fake_get(path, params=None, **kw):
        v = routes.get(path)
        if isinstance(v, Exception):
            raise v
        return v
    monkeypatch.setattr(daas_client, "_get", fake_get)
    return asyncio.run(mr.get_market_research())


def test_sectors_ranked_with_asof_and_source(monkeypatch):
    res = _run(monkeypatch, {"/snapshots/market": {"data": SNAP}, "/desk/sector-returns": SECTORS})
    ranked = res.widget["sectors"]["ranked"]
    assert [r["sector"] for r in ranked] == ["FMCG", "Banks", "IT"]
    assert res.widget["sectors"]["as_of"] == SECTORS["as_of"]
    assert res.widget["sectors"]["source"] == SECTORS["source"]
    assert "FMCG 55,000 (1d +0.40%, 1w n/a, 1m +0.50%)" in res.summary
    assert SECTORS["source"] in res.summary


def test_every_block_has_mode_and_its_own_date(monkeypatch):
    res = _run(monkeypatch, {"/snapshots/market": {"data": SNAP}, "/desk/sector-returns": SECTORS})
    s = res.summary
    assert "India VIX 14.77 (normal) [end of day, as of 2026-10-19]" in s
    assert "breadth 665 adv / 2608 decl [end of day, as of 2026-10-19]" in s
    assert "FII ₹-1,149cr, DII ₹900cr [end of day, as of 2026-10-19]" in s
    assert "10Y G-Sec 7.37% [end of day, as of 2026-10-16]" in s  # the yields' own (older) date


def test_missing_source_date_is_named_not_invented(monkeypatch):
    snap = {k: v for k, v in SNAP.items() if k != "yields_as_of"}
    res = _run(monkeypatch, {"/snapshots/market": {"data": snap}, "/desk/sector-returns": SECTORS})
    assert "10Y G-Sec 7.37% [end of day, date not provided by source]" in res.summary


def test_failing_sector_call_is_explicit(monkeypatch):
    err = daas_client.DaasError("DAAS /desk/sector-returns returned HTTP 500")
    res = _run(monkeypatch, {"/snapshots/market": {"data": SNAP}, "/desk/sector-returns": err})
    assert res.ok
    assert "sector data unavailable: DAAS /desk/sector-returns returned HTTP 500" in res.summary
    assert res.widget["sectors"]["unavailable"]


def test_empty_sector_rows_is_explicit(monkeypatch):
    res = _run(monkeypatch, {"/snapshots/market": {"data": SNAP},
                             "/desk/sector-returns": {"as_of": None, "sectors": []}})
    assert "sector data unavailable: the sector-returns route returned no sector rows" in res.summary


def test_prompt_contains_asof_strings(monkeypatch):
    from nidp.services.copilot_agent.nodes import market as node
    from nidp.services.copilot_agent import _stream
    captured = {}

    class FakeLLM:
        async def ainvoke(self, msgs):
            captured["system"] = msgs[0]["content"]
            return SimpleNamespace(content="ok")

    async def fake_get(path, params=None, **kw):
        return {"/snapshots/market": {"data": SNAP}, "/desk/sector-returns": SECTORS}.get(path)

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(daas_client, "_get", fake_get)
    monkeypatch.setattr(node, "make_chat_llm", lambda t: FakeLLM())
    monkeypatch.setattr(_stream, "emit_widget", noop)
    state = SimpleNamespace(messages=[SimpleNamespace(type="human", content="Which sectors lead?")],
                            persona=None, desk_persona="trader")
    asyncio.run(node.market_node(state))
    sp = captured["system"]
    assert "[end of day, as of 2026-10-19]" in sp
    assert "[end of day, as of 2026-10-16]" in sp
    assert "sectors ranked by 1-day return" in sp
