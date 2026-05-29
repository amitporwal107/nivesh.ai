# Dashboard — API integration

## Endpoints

| Hook | Endpoint | Purpose |
|---|---|---|
| `usePortfolioSummary` | composes `/api/portfolio/holdings-enriched` + `/api/insights/analysis` | totalValue · pnl · healthScore |
| `usePortfolioNavHistory("1y")` | `GET /api/portfolio/trend?days=365` | sparkline series |
| `useV3Portfolio` *(alias of `useHealthAnalysis`)* | `GET /api/insights/analysis` | canonical Health Score for the score ring |
| `useInsightsList` (optional) | `GET /api/insights` | top insights to render under hero |

## Request shape

All GETs; bearer cookie `session` attached by `credentials: "include"`. Correlation id on every request.

## Response → ViewModel mapping

`getSummary()` composes:

| Wire (rupees) | Domain (paise) |
|---|---|
| `total_value_rs` | `totalValue` (× 100) |
| `total_invested_rs` | derived → `costBasis` total |
| derived | `yearChange.{abs, pct}` |
| `portfolio_health.score` | `healthScore` |

`portfolio_health.breakdown` (return_quality · diversification · risk_adjusted · cost_efficiency · goal_alignment · overlap_penalty) is available for the "Why this score?" drawer (not wired yet).

## Fallback behaviour

- `/insights/analysis` 4xx/5xx → `healthScore = 0`; rest of the dashboard still renders.
- `/portfolio/trend` empty → sparkline shows zero baseline; hero card still resolves.
- 401 on either → router redirects to `/login` via `RequireAuth`.

## Empty / loading / error states

- Loading: `LoadingSkeleton variant="dashboard"` — matches the final layout exactly so no shift on arrival.
- Empty: when `totalValue === 0`, `EmptyState` directs to `/onboarding`.
- Error: page-level `ErrorState` retries both queries together.

## Open contract questions

- The composite endpoint (one shot summary) doesn't exist in OpenAPI yet. When it ships, swap `getSummary()` to call it directly; UI unchanged.
- ETag-aware caching on `/insights/analysis` — header not documented; if the backend emits one, our http client passes through (`If-None-Match` on refetch already supported).
