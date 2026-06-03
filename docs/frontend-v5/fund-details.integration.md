# Fund Details — API integration

## Endpoints

| Hook | Endpoint |
|---|---|
| `useHoldings()` (filtered to `holding.fundId === :id`) | `GET /api/portfolio/holdings` |
| `useV3FundScores` (optional drill-down) | `GET /api/insights/v3-portfolio` |
| `useV3FundScore(instrumentId)` *(intelligence)* | `GET /api/intelligence/v3-score/{instrument_id}` |

## Response → ViewModel mapping

The page consumes the existing domain `Holding` model (mapped via `services/mappers/portfolio.mapper.ts`). Returns shown are placeholders (`{ m1: 0, … }`) until the backend exposes per-fund returns at the base `/holdings` endpoint — `/holdings-enriched` already provides `xirr_pct`, `gain_pct`, `current_value_rs`. To upgrade Fund Details, swap the hook to consume `useEnrichedHoldings` and read those fields directly.

For full V3 breakdown (38 primitives across 6 composites: returns · risk · cost · consistency · portfolio_fit · esg_proxy), call `intelligenceService.v3Score(instrumentId)` in a side panel.

## States

- `holdings.isPending` → card skeleton
- holding not found in list → `EmptyState` → `/portfolio`
- holding present but V3 fetch fails → render base data, hide V3 panel
