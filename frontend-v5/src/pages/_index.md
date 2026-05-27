# Screen index

| # | Screen           | Route               | Status   | API source |
|---|------------------|---------------------|----------|------------|
| 1 | Dashboard        | `/dashboard`        | ✅       | composite client-side; real via `usePortfolioSummary`, `usePortfolioNavHistory`, `useV3Portfolio` |
| 2 | Portfolio        | `/portfolio`        | ✅       | `/api/portfolio/holdings`, `/api/portfolio/trend` |
| 3 | Fund Details     | `/funds/:id`        | ✅       | filtered `useHoldings` |
| 4 | Concentration    | `/concentration`    | ✅       | `/api/portfolio/exposure/concentration` + `useDashboard("concentration")` (v4) |
| 5 | Diversification  | `/diversification`  | ✅       | `useDashboard("diversification")` (v4 only — no v3 endpoint) |
| 6 | Risk Analysis    | `/risk`             | ✅       | `useDashboard("risk")` (v4 only — no v3 endpoint) |
| 7 | Recommendations  | `/recommendations`  | ✅       | `/api/plans/active` → mapped to Keep/Reduce/Add |
| 8 | Chat             | `/chat`             | ✅       | `/api/chat` (TODO wire) |
| 9 | Login            | `/login`            | ✅       | `/api/auth/google` (Gmail-only, whitelist) |
| 10| Onboarding       | `/onboarding`       | ✅       | `/api/portfolio/upload`, `/api/gmail/scan`, etc. (3 CAS Parser methods) |
| 11| Settings         | `/settings`         | ✅       | local + `/api/auth/logout` |

## API integration

See **[architecture.md](./integration/architecture.md)** for the full integration layer architecture and **[portfolio.integration.md](./integration/portfolio.integration.md)** for the worked example.

## Mock ↔ real switch

```bash
# in production/.env.local
VITE_USE_MOCK_API=false
VITE_API_BASE_URL=https://staging.niveshcopilot.com
```

Restart Vite. No component changes; the services factory swaps adapters.

## Implemented adapters

| Adapter         | OpenAPI tags                          | Hooks                            |
|-----------------|---------------------------------------|----------------------------------|
| `auth`          | `auth`                                | `useMe`, `useGoogleSignIn`, `useLogout`, `useGoogleClientId` |
| `portfolio`     | `portfolio`, `portfolio_snapshots`    | `usePortfolioSummary`, `usePortfolioNavHistory`, `useHoldings` |
| `plans`         | `plans`                               | `useRecommendations`, `useApplyRecommendation` |
| `goals`         | `goals`                               | `useGoals`, `useGoalsSnapshot`, `useGoalSimulate`, `useGoalWhatIf` |
| `analytics`     | `portfolio_exposure`, partial `analytics` | `useConcentration` |
| `insights`      | `insights`                            | `useV3Portfolio` (ETag-aware), `useInsightsList` |
| `dashboards`    | v4 (Postman) — composite envelope     | `useDashboard(domain, params?)` |

## Still TODO

- **Diversification real adapter** — backend has no `/correlation` or `/fund-overlap`; only the v4 composite. Wire via `useDashboard("diversification")` once that endpoint is live.
- **Risk real adapter** — same; via `useDashboard("risk")`.
- **Advisor adapters** — `/api/advisor/today|aum|underperformers|rebalance` + v4 `/api/advisor/summary|sip-board`.
- **MFD adapters** — `/api/mfd/profiles/*` + v4 `/api/mfd/profiles/:id/needs-attention|call-log|sip-nudge|review-pack`.
- **Chat adapter** — `/api/chat`, `/api/chat/sessions/*`, streaming support.
- **Scenarios adapter** — `/api/scenarios/*` (simulate, rebalance-plan, save).
- **Broker adapter** — `/api/broker/*` for portfolio connect.
- **CAS upload adapter** — `/api/portfolio/upload` (multipart) + polling task status.
