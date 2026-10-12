"""Market-data provider adapters (docs/charting.md §32, Phase A).

    contract.py           the normalized ProviderResult / ProviderError every adapter speaks (§32.4)
    kite_adapter.py       KiteMarketDataAdapter   — instrument master + historical candles
    trendlyne_adapter.py  TrendlyneResearchAdapter — MCP client: entities, parameters, events, documents
    request_log.py        secret-free request/response log (provider_requests / provider_responses)

Research/data-service only: nothing here places, modifies or cancels an order (§32.13).
"""
