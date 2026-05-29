# Portfolio — API integration

## Endpoints consumed

| Screen                | Hook                     | Endpoint(s) |
|-----------------------|--------------------------|-------------|
| Dashboard             | `usePortfolioSummary`    | `GET /api/portfolio/holdings`, `GET /api/insights/v3-portfolio` (composed client-side) |
| Dashboard             | `usePortfolioNavHistory` | `GET /api/portfolio/trend?days=365` |
| Portfolio             | `useHoldings`            | `GET /api/portfolio/holdings?portfolio_id&asset_type` |
| Fund Details          | `useHoldings` (filtered) | same |

## Request shape

All endpoints take query params; bodies only on POST/PUT.

```http
GET /api/portfolio/holdings?asset_type=MUTUAL_FUND HTTP/1.1
Cookie: session=…              ← auto-attached by `credentials: include`
X-Correlation-Id: <uuid>
X-Client-Version: 0.1.0
```

## Response → ViewModel mapping

### Holding

| Wire (snake_case)   | Domain (camelCase)         | Notes |
|---------------------|----------------------------|-------|
| `holding_id`        | `id`, `fundId`             | dedup key |
| `quantity`          | `units`                    | |
| `buy_price` × `qty` | `costBasis`                | × 100 → paise |
| `current_price`×qty | `marketValue`              | × 100 → paise |
| _derived_           | `unrealizedPnl`, `unrealizedPnlPct` | mapper computes |
| `asset_type`        | `fund.category`            | EQUITY/ETF → large-cap, etc. |

V3 scores, expense ratio, NAV history per fund are NOT in the base `/holdings` response — they live on `/portfolio/holdings-enriched` and `/intelligence/v3-score/{id}` (follow-on adapters).

### PortfolioSummary (composite)

The OpenAPI doesn't expose a single summary endpoint. The adapter composes:

```
listHoldings()              → totalValue, totalCost, yearChange
+
insights/v3-portfolio       → healthScore, grade
=
PortfolioSummary
```

`dayChange`, `weekChange`, `allocation`, `topInsights` default to empty values until the corresponding adapters (`/portfolio/exposure/concentration`, `/insights`) land. Screens render partial data gracefully (req #14).

## Fallback behaviour

| Failure                                  | UX                                                |
|------------------------------------------|---------------------------------------------------|
| Network error                            | React Query retries once; ErrorState on second fail |
| 401                                      | `ApiError.kind = "auth"` → router redirects to `/login` (TODO) |
| 422 / contract drift                     | `ApiError.kind = "contract_drift"` — caught in ErrorState; correlation ID surfaced |
| `/insights/v3-portfolio` unavailable     | health score = 0, screens render with empty score state |

## Dependency graph

```
Dashboard
  └─ usePortfolioSummary ─┬─ portfolio.listHoldings  →  /api/portfolio/holdings
                          └─ portfolio.getHealthScore → /api/insights/v3-portfolio (ETag-aware)

  └─ usePortfolioNavHistory → /api/portfolio/trend

Portfolio / FundDetails
  └─ useHoldings → /api/portfolio/holdings
```

## Switching to real APIs

```bash
# .env.local
VITE_USE_MOCK_API=false
VITE_API_BASE_URL=https://staging.niveshcopilot.com
```

Restart Vite; hooks now hit staging. Cookie `session` flows automatically because `credentials: "include"` is set in `services/api/http.ts`.

## Contract drift

Zod parses every response; mismatches throw `ApiError.kind = "contract_drift"` with a message like:

```
portfolio.listHoldings: Expected number, received string at .0.quantity
```

In dev this surfaces in `ErrorState` with the correlation ID. Recommended: pipe these to Sentry via `setObserver()` so production drift fires alerts.
