"""The market agent's data tool must call DaaS paths that exist.

daas_client._get prepends /v1 to every path. market_research passed paths that
already began with /v1, so it requested /v1/v1/... , got a 404 (returned as
None) and the market agent answered every question with "snapshot unavailable".
"""
import asyncio

from services.copilot_tools import daas_client, market_research


def test_market_tool_requests_unprefixed_daas_paths(monkeypatch):
    seen = []

    async def fake_get(path, params=None, **kw):
        seen.append(path)
        return None
    monkeypatch.setattr(daas_client, "_get", fake_get)
    monkeypatch.setattr(daas_client, "is_configured", lambda: True)
    asyncio.run(market_research.get_market_research())
    assert seen, "the tool made no DaaS request"
    assert all(not p.startswith("/v1/") for p in seen), seen
    assert "/snapshots/market" in seen
