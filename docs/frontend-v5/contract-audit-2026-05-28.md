# Contract audit — 2026-05-28 (Pass 3 — final)

All 6 user-requested specs audited. Equity-scoring and mf-scoring deferred
(small, mostly read-only fund-level endpoints that no current screen consumes).

## Pass 3 changes

### Portfolio (portfolio.yaml)
- `asset_type` enum is **lowercase**: `equity`, `mutual_fund`, `etf`, `bond`, `gold`, `fd`, `other` (was UPPERCASE).
- `/api/portfolio/trend` returns `{ days, series: [{ date, value_rs }], start_value_rs, end_value_rs, gain_pct }` — NOT `{ points: [{ date, value }] }`.
- New `EnrichedHoldingsRes` contract; `getSummary()` now composes from `/holdings-enriched` (totals) + `/insights/analysis` (health).
- New adapter methods: `listHoldingsEnriched`, `searchInstruments`, `listSips`.

### Goals (goals.yaml)
- `Goal` carries `priority`, `current_corpus_rs`, `inflation_pct`, `selected_funds`, `manual_fund_override`, `projected_corpus_rs`, `sip_gap_rs` at top level.
- `GoalsListRes` is `{ total, on_track, at_risk, goals: [...] }` — NOT a bare array.
- `/simulate` returns rich `MonteCarloRes` with `corpus_projections`, `sip_recommendations`, `year_by_year`.
- `/what-if` is its own response shape (`WhatIfRes` with `delta_on_track_pct`, `persisted: false`).
- `on_track_pct` is **0..100** (percentage), not 0..1 (ratio). Mapper updated.
- New `useGoals` returns `{ goals, totals }` — components need to read `.goals` array.

### Advisor (advisor.yaml)
- `/api/advisor/today` returns bucketed `{ high_priority, medium_priority, low_priority, summary }` — NOT a flat list.
- `/api/advisor/aum` returns `{ total_aum_rs, mom_change_pct, clients }` with per-client `aum_mom_change_rs/pct`.
- `/api/advisor/underperformers` and `/rebalance` have richer shapes.
- New: `/api/mfd/workspace` (mode INDIVIDUAL/ADVISORY + firm metadata).
- Activate/deactivate flow confirmed. Notes / tax-summary / portfolio-trend adapter methods added.

### Intelligence (intelligence.yaml)
- `/api/intelligence/portfolio` returns `{ look_through, sector_allocation, overlap_matrix, concentration_flags, narrative }` — richer than my earlier passthrough.
- `/api/intelligence/simulate` body is `{ remove_mf_ids: [string] }` — confirmed.
- `/api/intelligence/v3-score/{id}` returns 38-primitive breakdown grouped into 6 composites (returns, risk, cost, consistency, portfolio_fit, esg_proxy).
- New: `/api/intelligence/sector-peers/{symbol}` for stock-level peer ranking.

### Login & Onboarding (login-onboarding.yaml) — **major flow change**
- `UserProfile`: confirmed match.
- `/api/auth/google` request is `{ credential }`; cookie set in `Set-Cookie` — confirmed.
- `/api/auth/google-client-id` confirmed.
- New: `/api/user/journey`, `/api/user/risk-profile`, `/api/user/quick-setup`, `/api/user/complete-onboarding`.
- **CAS PDF flow changed**:
  - `POST /api/portfolio/upload` is now **CSV/Excel only**. PDF returns 410 Gone.
  - PDF goes through CAS Connect SDK: `/api/casparser/access-token` → widget → `/api/portfolio/import-connect`.
  - Onboarding upload UI needs rework to call `getConnectToken()` + mount the widget instead of multipart file upload.
- New: DPDP Act compliance endpoints (`/api/compliance/consent|export|delete`).

## Deferred

- `equity-scoring.yaml` (17 KB) — `/api/portfolio/stock-scores`, `/portfolio/analytics`, `/portfolio/deep-analytics`. Stock-level V3 ratings.
- `mf-scoring.yaml` (16 KB) — `/api/insights/v3-portfolio` (already audited in Pass 1), `/portfolio/fund-performance`, `/api/mf-data/*`, `/api/nav/refresh`.

Both are read-only analytics endpoints that no current screen consumes. The
intelligence + insights adapters cover the same data through composite calls.
Add dedicated adapters when a screen needs them.

## Production-readiness blockers remaining

1. **CAS Connect widget integration** — Onboarding upload UI calls the wrong adapter. Frontend needs to either:
   (a) embed `@cas-parser/connect` widget React wrapper, or
   (b) provide CSV-only fallback for now.
2. **`npm run build`** — never executed; TypeScript errors are unknown.
3. **`RequireAuth` not wired** into the router yet (the component exists, the route guard isn't applied).
4. **CORS / cookie attributes on staging** — confirm `SameSite` and credentials allow cross-origin (frontend dev origin vs `staging.niveshcopilot.com`).
