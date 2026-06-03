# V2 route → component → endpoint map (for V4 reuse)

> Source: live walk of `https://staging.niveshcopilot.com/v2/app` + `/app/frontend/src/` code audit. V2 is the working app and the reference truth for the 9-screen V4 P0 build. The discarded `/v3/` is not in scope.

## V2 shell

- Mounted at `/v2/app`. Single-page app, tab-driven via state in `frontend/src/pages/NiveshV2.jsx` (625 lines).
- Sidebar nav switches `activeScreen` state — not React Router sub-routes. Each "screen" is a child component.
- All `/api/*` calls go through `fetch()` directly or via small wrapper hooks. No central API client.
- Auth via `frontend/src/context/AuthContext.js` (`useAuth()` hook).
- Number formatting via `frontend/src/context/NumberFormatContext.js` (`useNumberFormat()` hook).

---

## 1. AI Copilot Landing  ↔ V4 `s-landing`

- **Sidebar**: "Nivesh Copilot"
- **Top-level component**: `frontend/src/components/ChatView.js:19`
- **Key endpoints** (load):
  - `GET /api/copilot/agents`
  - `GET /api/copilot/models/picker`
  - `GET /api/chat/sessions`
  - `GET /api/copilot/suggested-prompts`
  - `GET /api/insights/analysis` (cached narrative)
- **Key endpoints** (interaction):
  - `POST /api/chat/stream` (SSE; the main chat send)
  - `POST /api/copilot/agents/oneshot` (alternative one-shot)
  - `POST /api/copilot/feedback` (thumbs)
- **Sub-components**: Hero score card (Compute Score CTA), quick-action chips (Portfolio health check / Simulate rebalance / Optimise tax / Generate report), slash-command composer (`/fundcard /market /compare /sip /rebalance /tax /stress /sectors /overlap`).
- **V4 visual delta**: V2 has a richer composer with slash-commands + model picker (`Auto-route` / `GPT-4o`). V4 mockup is simpler — single text box + suggested-prompt chips. **V4 should keep slash-commands** because they're already wired and high-leverage.

## 2. Portfolio Dashboard  ↔ V4 NEW (no direct mockup screen)

- **Sidebar**: "Dashboard" (the cockpit) AND "Portfolio" (the holdings/builder).
- **Top-level component**: `frontend/src/components/v2app/screens/V2HomeScreen.jsx:47` (the cockpit Dashboard).
- **Key endpoints** (Dashboard load):
  - `GET /api/user/profile`
  - `GET /api/portfolio/holdings`
  - `GET /api/portfolio/analytics`
  - `GET /api/insights`
  - `GET /api/portfolios`
  - `GET /api/intelligence/portfolio?narrate=true`
  - `GET /api/portfolio/holdings-enriched`
  - `GET /api/portfolio/cas-snapshots?limit=1`
  - `GET /api/user/persona`
  - `GET /api/goals`
- **Sub-components**: `PersonaHero` (Retail Investor banner), `HealthScoreHero`, `AIAdvisorSummary`, `Top3Actions`, Goals widget, Intelligence Feed.
- The Portfolio sub-page is a separate component triggered from the "Portfolio" sidebar item — holdings table + AI Portfolio Builder (Build proposed portfolio CTA).
- **V4 visual delta**: V4 mockup has no equivalent "Dashboard" cockpit — it's a chat-first landing. **Recommendation**: keep the Dashboard cockpit as the Portfolio Dashboard (the user's #2 P0 screen), serve V4 mockup's `s-landing` chat-first surface from the "AI Copilot" button. Two complementary surfaces, not one.

## 3. Concentration Dashboard  ↔ V4 `s-d_conc`

- **Sidebar**: "Insights" → tab "Diversification & Consolidation" → sub-tabs: **AMC exposure**, **Sector exposure**, **Company exposure**, **Group exposure**.
- **Top-level component**: `frontend/src/components/insights/ConcentrationAnalyticsTab.jsx:1` rendered inside `InsightsView.js`.
- **Key endpoint**: `GET /api/portfolio/exposure/concentration` — returns `{total_value, amc:{items[], hhi, effective_n, largest_pct, hero_insight}, sector:{...}, company:{...}, group:{...}}`. All 4 lenses come from ONE endpoint.
- **V4 visual delta**: V4 mockup wants Concentration as a **standalone screen** with the 4 lens chips at the top, not buried as a sub-sub-tab inside Insights. V4 mockup also wants a 5th "Stocks" lens, but in V2 single-stock concentration lives under `company.items[]` so the chip is just a relabel.

## 4. Diversification Dashboard  ↔ V4 `s-d_div`

- **Sidebar**: "Insights" → tab "Diversification & Consolidation" (the same tab as concentration; "fund_overlap_insights" sub-section).
- **Top-level component**: `frontend/src/components/InsightsView.js:257` — overlap matrix sub-section.
- **Key endpoint**: `GET /api/portfolio/deep-analytics` — returns `{overexposure, performance_cards, duplication}`. **Note**: `deep-analytics` does NOT carry beta/sharpe/drawdown (the API_INVENTORY claim is wrong — see [WIDGET_API_MAP.md](WIDGET_API_MAP.md)).
- Also draws from `GET /api/portfolio/exposure/fund-overlap/matrix` for the pairwise overlap.
- **V4 visual delta**: V4 wants Diversification as a standalone screen with a pairwise overlap chart + caution line at 60%. The data is all there; just unbundle the sub-section.

## 5. Action Plan Dashboard  ↔ V4 `s-plan`

- **Sidebar**: "Plan Board"
- **Top-level component**: `frontend/src/components/v2/PlanBoardView.js:21`
- **Key endpoints**:
  - `GET /api/plans/history?limit=20`
  - `GET /api/plans/active`
  - `POST /api/plans/generate` (Generate New Plan CTA)
  - `PATCH /api/plans/{plan_id}/actions/{action_id}` (state transitions)
- **Notable**: listens to custom DOM event `nivesh:plan-saved` so Copilot-side plan saves push back into the Plan Board live.
- **V4 visual delta**: V4 wants action rows grouped by source-domain (Concentration / Risk / Performance / Goals / Tax / Diversification). V2 today shows a flat plan list without `source_domain`. Maps to GAP-A2 in the additive backlog — but V4 can ship with the V2 flat list if needed.

## 6. Risk Dashboard  ↔ V4 `s-d_risk`

- **Sidebar**: "Insights" → tab "Risk"
- **Top-level component**: `frontend/src/components/InsightsView.js:259` — "risk" sub-tab.
- **Key endpoints** (all POST widgets returning `{type, title, data, actions}` envelopes):
  - `POST /api/copilot/widgets/risk_suitability` — Equity %, Small/Mid %, Profile label
  - `POST /api/copilot/widgets/portfolio_var` — 1-day VaR, 10-day VaR, annual vol
  - `POST /api/copilot/widgets/stress_test` — COVID 2020, GFC 2008 scenarios
- Also draws beta / sharpe / vol from `GET /api/portfolio/risk-analytics`.
- **V4 visual delta**: V4 mockup shows VaR donut + 4-stat grid (Beta / Volatility / Max DD / Sharpe). **Max DD is not exposed** anywhere (GAP-R2). Otherwise straight reskin.

## 7. Homepage (public marketing) ↔ V4 `s-home`

- **Path**: `/` (above auth wall)
- **Top-level component**: `frontend/src/pages/Landing.js:14`
- **Endpoints**: none (only `GET /api/auth/google-client-id` for the OAuth button via `AuthContext`).
- **Sub-components**: hero + 3 CTA buttons ("Analyze My Portfolio", "Try Demo", "Nivesh Classic", "AI Copilot 2.0 β"), 3 feature tiles, "Get started in 3 steps", trust strapline. Version selector stores choice in localStorage (V1 Classic vs V2 vs V2 β).
- **V4 visual delta**: V4 mockup is heavier on serif type + 3 feature tiles + sample-score teaser. Pure reskin — no data changes needed.

## 8. Goals  ↔ V4 `s-d_goals`

- **Sidebar**: "Goals"
- **Top-level component**: `frontend/src/components/goals/GoalsView.jsx:1`
- **Key endpoints**:
  - `GET /api/goals` (list)
  - `GET /api/goals/snapshot` (summary stats — `user_financial_snapshots` row, NOT per-goal projections; per-goal projections are on `goals[].on_track_pct` + `goals[].last_simulation.{required_sip_rs, shortfall_rs}`)
  - `POST /api/goals/{goal_id}/simulate` (Monte Carlo)
  - `POST /api/goals/{goal_id}/what-if`
- **Constraints**: V2 enforces max 4 active goals in the UI. "Set up your snapshot" gate appears if user has no `user_financial_snapshots` row.
- **V4 visual delta**: V4 wants per-goal funding-% chart with caution line at 85%. The data is all there (`on_track_pct`). Recommendation matrix on V4 needs goal-engine actions to flow into `/api/plans/active` (GAP-A4) — without it, recommendations remain on the Goals view only.

## 9. Onboarding — CAS Ingestion Pipeline  ↔ V4 `s-onboard`

- **Gate**: `OnboardingCopilotWrapped` shown as full-page wizard if `userProfile.onboarding_completed === false`.
- **Top-level component**: `frontend/src/components/OnboardingCopilotWrapped.jsx:1`
- **Key endpoints**:
  - `POST /api/onboarding/pan` (PAN capture)
  - `POST /api/portfolio/upload` (CAS PDF/CSV multipart) → poll `GET /api/portfolio/upload-status/{task_id}`
  - `POST /api/onboarding/gmail/auto-import` + Gmail OAuth at `GET /api/gmail/connect`
  - `POST /api/casparser/access-token` + the `@cas-parser/connect` SDK for hosted CAS flow
  - `POST /api/user/complete-onboarding` (mark done)
- **Supported import sources today**: CAS PDF upload · CAS Connect SDK · Gmail auto-import. **Broker connect is not implemented** (no `/api/broker/native/start/*` routes).
- **V4 visual delta**: V4 mockup wants 3 import cards (Gmail / Upload / Broker). Drop the broker card or substitute with OpenAlgo hosted (`POST /api/broker/connect-hosted` exists). Manual entry fallback (`POST /api/portfolio/holdings`) stays.

---

## Reusable hooks (V4 inherits verbatim)

| Hook | File | Used by |
|---|---|---|
| `useAuth()` | `frontend/src/context/AuthContext.js` | All screens |
| `useNumberFormat()` | `frontend/src/context/NumberFormatContext.js` | InsightsView, V2HomeScreen, GoalsView |
| Parallel-fetch `useCallback` template | `frontend/src/pages/NiveshV2.jsx`, `V2HomeScreen.jsx`, `PlanBoardView.js` | Standard pattern: `Promise.all([fetch(holdings), fetch(analytics), fetch(insights), fetch(portfolios)])` on mount |

---

## V4 architecture deltas (vs V2)

| Concern | V2 today | V4 recommendation |
|---|---|---|
| **Routing** | State-driven (`activeScreen` switch in `NiveshV2.jsx:625`) — no shareable URLs, no back-button | Use React Router with `/v4/landing`, `/v4/concentration`, etc. so each screen has a real URL |
| **Concentration vs Diversification** | Both inside one Insights tab | Split into 2 standalone screens; share the same data fetch (one call to `/exposure/concentration` + one to `/exposure/fund-overlap/matrix`) |
| **Risk Dashboard** | Sub-tab of Insights | Standalone screen; same 3 widget POSTs as V2 |
| **Action Plan** | Flat list | Group by `source_domain` once GAP-A2 lands; until then, V2-style flat |
| **Onboarding** | Full-page gate blocking dashboard render | Could also work as a post-login modal in V4; the gate behaviour is fine but tab the steps |
| **API client** | Scattered `fetch()` calls per component | Single V4 API client at `frontend/src/v4/api/client.ts` with adapter functions per V4 screen |
| **Capacitor** | Used for native iOS/Android wrap | Drop for V4 — separate mobile pages, web-only build (per user direction) |

---

## Bottom line for V4 build

- **Every endpoint V4 needs already fires today in V2.** The HAR capture from the live walk confirms it.
- The work is almost entirely **frontend** — extract 3 sub-tabs from `InsightsView.js` into standalone screens, reskin against the V4 mockup, swap state-driven routing for React Router, introduce a single API client + adapter layer.
- No backend changes are required to scaffold V4 launch. The GAP-A1/A2/A3/A4/S1 P0 bundle remains a nice-to-have for the live-projection UX and Plan Board grouping, but V4 can ship without it using V2-style fallbacks (plan-level projection, flat action list, quality+health meters relabeled as fundamentals+technicals).
- Estimated V4 build size: ~2–3 weeks of frontend work for a 1-2 dev team, assuming the V4 mockup HTML translates cleanly to React components.
