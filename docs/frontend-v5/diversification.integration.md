# Diversification — API integration

## Endpoints

Two sources combine for this screen:

| Hook | Endpoint | What it gives |
|---|---|---|
| `useCorrelation()` *(legacy mock)* | none yet | stock-level ρ matrix (still on mock data) |
| `useOverlap()` *(legacy mock)* | none yet | fund-pair overlap % (still on mock data) |
| `useIntelligencePortfolio()` | `GET /api/intelligence/portfolio?narrate=true` | look-through · `overlap_matrix` · narrative |

The correlation matrix isn't a documented endpoint in any of the 11 OpenAPI files. The closest backend source is `intelligence_portfolio.overlap_matrix`, which gives fund-to-fund overlap percentages (closer to "shared top-10 holdings" than to ρ).

## Migration path

When backend ships a `/api/diversification/correlation` (or equivalent):

1. Add `correlation` Zod schema + adapter method.
2. Replace `legacyAnalytics.correlation()` in `useCorrelation()` with the real adapter.
3. The screen consumes `CorrelationMatrix` domain shape unchanged.

Until then, the screen renders **real fund-overlap data** from `intelligence/portfolio` and **mock correlation data** for the heatmap. The mix is deliberate — UI won't lie about which is which (overlap pairs come from `overlap_matrix[].overlap_pct`).

## States

- Loading: dashboard skeleton.
- Error on either resource: ErrorState with retry that refetches both.
- Empty: rare — only when portfolio has < 2 holdings.
