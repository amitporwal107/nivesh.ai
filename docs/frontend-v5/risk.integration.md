# Risk Analysis — API integration

## Current state

No dedicated `/api/risk/*` endpoint exists in the 11 OpenAPI files. The Risk screen currently reads `useRisk()` which routes to the **legacy mock service** (`services/analytics.service.ts`).

The closest real-data sources are:

| Need | Real endpoint | Status |
|---|---|---|
| Portfolio beta | `intelligence.portfolio().look_through` (computed from underlying) | partial; not surfaced as a discrete field today |
| Sharpe / Sortino / max drawdown | per-fund: `intelligence/v3-score/{id}.composites.risk.primitives` | per-fund only, not portfolio-aggregated |
| VaR · stress scenarios | none | mock-only |
| Volatility | `insights/analysis.summary` (sometimes carries `volatility_pct`) | not consistent |

## Recommended wiring (when backend adds endpoints)

1. Add `risk.contract.ts` with the real response shape.
2. Drop in `realAnalyticsAdapter.risk()`.
3. Update `useRisk()` to point at `analyticsService.risk()` (already imported via the factory).

Until then the page deliberately runs on mocks so designers / PMs can exercise the UX. The mock looks plausible (₹3.07L VaR, 14.6% σ, 2008-style -32% stress) but is not derived from your actual portfolio.

## States

- Loading: dashboard skeleton.
- Error: ErrorState with retry.
- Empty: cannot happen with mock; with real adapter, when no holdings, redirect to `/onboarding`.
