# Concentration — API integration

## Endpoint

`GET /api/portfolio/exposure/concentration` → `ConcentrationBreakdownC` (loose passthrough; backend schema not formally declared in `portfolio.yaml` paths).

## Hook

`useConcentration()` → returns `ConcentrationSnapshot` (camelCase domain).

## Response → ViewModel mapping (best-effort)

The backend returns an opaque object with `amc`, `sector`, `company` breakdowns. The mapper currently expects `sector.breakdown[]` of `{ name, pct, cap_pct }`. If the real shape differs, the mapper logs a contract-drift warning and renders an empty sectors list — UI degrades gracefully.

| Domain field | Source |
|---|---|
| `sectors[]` | `sector.breakdown[]` |
| `topStockName/Pct` | `sector.top_stock` |
| `sectorOverCount` | `sector.sectors_over_cap` |
| `herfindahl` | `sector.herfindahl` |

## Drill-down

Each sector tile on the treemap is intended to expand into stock-level look-through. The data lives at `GET /api/intelligence/portfolio` → `look_through.top_holdings[]`. Wire when the sector→stock filter UX lands.

## States

- Empty (no holdings yet) → redirect to `/onboarding`
- Backend returns malformed sector array → `ErrorState` with correlation id; user can still navigate elsewhere
