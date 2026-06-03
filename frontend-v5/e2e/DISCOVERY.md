# DISCOVERY.md — Nivesh V5 E2E Test Discovery

> Generated 2026-05-28 against `https://staging.niveshcopilot.com/v5/`
> Prototype reference: `https://staging.niveshcopilot.com/v5/prototype/Nivesh%20prototype.html`

---

## 1. Route Map

| # | Production Route | Prototype Screen | Sidebar Group | Auth Required |
|---|-----------------|------------------|---------------|--------------|
| 1 | `/v5/` | 01 Homepage | — (full-bleed) | No |
| 2 | `/v5/login` | 02 Sign in | — (full-bleed) | No |
| 3 | `/v5/onboarding` | 03 Onboarding | — (full-bleed) | No (but post-login) |
| 4 | `/v5/dashboard` | (no exact match — chat is closest) | Dashboards › Overview | Yes |
| 5 | `/v5/portfolio` | (not in prototype) | Workspace › Portfolio builder | Yes |
| 6 | `/v5/concentration` | 05 Concentration | Dashboards › Concentration | Yes |
| 7 | `/v5/diversification` | 06 Diversification | Dashboards › Diversification | Yes |
| 8 | `/v5/risk` | 07 Risk | Dashboards › Risk | Yes |
| 9 | `/v5/performance` | 08 Performance | Dashboards › Performance | Yes |
| 10 | `/v5/goals` | 09 Goals | Dashboards › Goals | Yes |
| 11 | `/v5/tax` | 10 Tax | Dashboards › Tax | Yes |
| 12 | `/v5/plan` | 11 Plan board | Workspace › Plan board | Yes |
| 13 | `/v5/recommendations` | 13 Recommendations | Workspace › Recommendations | Yes |
| 14 | `/v5/chat` | 04 Chat copilot | Workspace › Chat copilot | Yes |
| 15 | `/v5/settings` | — (no prototype) | — (sidebar link) | Yes |
| 16 | `/v5/funds/:id` | — (no prototype) | — (from portfolio row) | Yes |

**Prototype-only screens (no production route yet):**
- 12 Builder (Portfolio builder with allocation sliders + projection)
- 14 Instrument flow (Sankey diagram: vehicles → asset class → exposure)

**Production-only screens (no prototype):**
- `/v5/settings`
- `/v5/portfolio`
- `/v5/funds/:id`

---

## 2. Auth / Session Mechanism

- **Cookie name:** `session_token`
- **Domain:** `staging.niveshcopilot.com` (no port qualifier)
- **Attributes:** Secure, Lax, HttpOnly
- **Session injection for tests:** `GET /api/auth/dev-set-cookie?token={TOKEN}`
- **Auth check:** `GET /api/auth/me` → 200 with user profile or 401
- **localStorage key:** `nivesh.ui` (stores `{state: {theme, persona, sidebarCollapsed}, version}`)
- **Google OAuth:** GIS SDK loaded dynamically; `GET /api/auth/google-client-id` → `{client_id: "728147509901-…"}`
- **Post-login routing:** `onboarding_completed === true` → `/dashboard`, `false` → `/onboarding`
- **No active route guard** — protected pages don't redirect to `/login`; they just show API errors if 401

**User profile shape (from /api/auth/me):**
```json
{
  "user_id": "user_ed05fb1daa45",
  "email": "aporwal107@gmail.com",
  "name": "Amit Porwal",
  "is_admin": true,
  "onboarding_completed": false,
  "picture": "https://lh3.googleusercontent.com/a/..."
}
```

---

## 3. Per-Route API Endpoints

| Route | Primary API Endpoints | Common (all auth pages) |
|-------|----------------------|------------------------|
| `/` (homepage) | `GET /api/auth/google-client-id` (unauthenticated) | — |
| `/login` | `GET /api/auth/google-client-id`, `GET /api/auth/me`, `GET /api/insights/analysis` | — |
| `/onboarding` | `POST /api/casparser/access-token`, `POST /api/cas/sdk-callback`, `POST /api/portfolio/upload` | — |
| `/dashboard` | `GET /api/portfolio/holdings-enriched?fresh=false`, `GET /api/portfolio/trend?days=365`, `GET /api/insights/analysis` | `GET /api/auth/me` |
| `/portfolio` | `GET /api/portfolio/holdings` | `GET /api/auth/me`, `GET /api/portfolio/holdings-enriched`, `GET /api/insights/analysis` |
| `/concentration` | `GET /api/portfolio/exposure/concentration` | same |
| `/diversification` | `GET /api/intelligence/portfolio?narrate=true`, `GET /api/portfolio/exposure/concentration` | same |
| `/risk` | (no dedicated endpoint — uses mock/stub data) | same |
| `/performance` | `GET /api/dashboards/performance?period=1y` | same |
| `/goals` | `GET /api/dashboards/goals`, `GET /api/goals` | same |
| `/tax` | `GET /api/dashboards/tax` | same |
| `/plan` | `GET /api/plans/active` | same |
| `/recommendations` | `GET /api/plans/active` (reuses plan) | same |
| `/chat` | `GET /api/copilot/suggested-prompts`, `POST /api/chat/sessions`, `POST /api/chat` | same |
| `/settings` | (no dedicated endpoint — uses `useMe()` + localStorage) | same |

**Rate limiting observed:** `GET /api/auth/me` returns 429 on rapid successive calls.

---

## 4. Key Selectors (confirmed in production)

| Selector | Present | Usage |
|----------|---------|-------|
| `.nv-frame` | ✅ | Homepage wrapper (radial gradient bg) |
| `.nv-card` | ✅ | Card component (surface-1 bg, border, shadow) |
| `.nv-pill` | ✅ | Status badges (mint/amber/indigo/danger) |
| `.nv-pill-mint` | ✅ | Green status pill |
| `.nv-mark` | ✅ | Logo "न" mark (mint gradient) |
| `.nv-mono` | ✅ | JetBrains Mono labels |
| `.nv-serif` | ✅ | Instrument Serif headings |
| `.nv-btn` | ✅ | Button base class |
| `.nv-btn-primary` | ✅ | Primary CTA (mint bg) |
| `[data-theme="dark"]` | ✅ | On `<html>`, default dark theme |
| `[data-theme="light"]` | ✅ | Light theme toggle (Settings) |
| `aside` with `nav[aria-label="Primary"]` | ✅ | Sidebar navigation |
| `.nv-card-2` | ✅ | Secondary card (bg-2) |

---

## 5. Prototype vs Production — Key Text & UI Deltas

### Headlines (expected copy from prototype → production)

| Screen | Prototype Headline | Production Headline | Match? |
|--------|-------------------|---------------------|--------|
| Homepage | "Your portfolio, finally legible." | "Your portfolio, finally legible." | ✅ |
| Login | "Welcome back, Aarav." | "Your portfolio, finally legible." (no user context) | ⚠️ Dynamic — shows user name if logged in |
| Onboarding | "Bring your investments in." | "Bring your investments in." | ✅ |
| Chat | (serif headline in AI response) | "Ask anything about your portfolio." | ✅ Different — prototype shows a conversation state |
| Concentration | "One in three rupees sits in financials." | (dynamic from API) | ✅ |
| Diversification | "Three pairs are nearly the same trade." | (dynamic from API) | ✅ |
| Risk | "One bad quarter could cost ₹3.07 L." | "One bad quarter could cost ₹0." | ⚠️ Shows ₹0 — stub data, no real risk endpoint |
| Performance | "You beat the benchmark by 2.1 points." | (dynamic from API) | ✅ |
| Goals | "Two on track, one ₹1.4 Cr short." | (dynamic from API) | ✅ |
| Tax | "₹11,520 in your hands if you act by March 31." | (dynamic from API) | ✅ |
| Plan | "Your plan, end-to-end." | "Your plan, end-to-end." | ✅ |
| Recommendations | "Six moves to take you from 86 to 94." | (dynamic from API) | ✅ |
| Settings | — | "Make it yours." | N/A |

### Structural Deltas

| Feature | Prototype | Production | Gap |
|---------|-----------|------------|-----|
| **Sidebar nav items** | 7 dashboards + 3 workspace | 7 dashboards + 4 workspace | ✅ Production adds Recommendations |
| **Sidebar user section** | "₹ 24.8 L · NIDP ✓" | Dynamic from API | ✅ |
| **Google Sign-In** | Custom button | `renderButton()` (latest code) or custom button (deployed) | ⚠️ Deploy pending |
| **Health preview card (homepage)** | Score 86, filled bars, 3 insights | Score 0/GRADE D, empty bars, "Sign in to see" | ✅ Correct — no auth = no data |
| **Dashboard** | Chat-style with score ring + actions | Error state (contract drift on navHistory) | ❌ **BUG** — Zod schema mismatch |
| **Concentration treemap** | Full treemap SVG | Renders but appears blank in screenshot | ⚠️ Needs investigation |
| **Risk** | Fan chart + stress table | KPI cards + stress table (no fan chart) | ⚠️ No backend endpoint |
| **Performance** | Attribution waterfall + monthly grid | KPI cards + waterfall (from dashboards API) | ✅ |
| **Plan board** | 4-col kanban (Backlog/Week/Flight/Done) | 4-col kanban | ✅ |
| **Portfolio Builder** | Allocation sliders + donut + projection | Not implemented | ❌ Missing page |
| **Instrument Allocation** | Sankey flow diagram | Not implemented | ❌ Missing page |
| **Login greeting** | "Welcome back, Aarav" + 3 KPI cards | Dynamic — shows name if logged in, generic otherwise | ✅ |
| **Footer security text** | "ENCRYPTED · NEVER STORED · ARN-128459" | "ENCRYPTED · NEVER STORED · ARN-128459" | ✅ |

### Frontend–Backend Mismatches (found by live contract layer)

#### P1 — Dashboard/summary crashes

| # | Endpoint | Frontend expects | Backend returns | UI impact |
|---|----------|-----------------|-----------------|-----------|
| M1 | `GET /api/portfolio/trend` | `series[].date`, `series[].value_rs` | `series[].snapshot_date`, `series[].total_value` + extra `health_score`, `allocation`, `scores` | **Dashboard crashes** — Zod parse fails |
| M2 | `GET /api/insights/analysis` | `portfolio_health.score` (number) | `portfolio_health.health_score` (number) — no `score` field exists | **Health score ring crashes** |

#### P2 — Holdings/enriched response shape differs

| # | Endpoint | Frontend expects | Backend returns | UI impact |
|---|----------|-----------------|-----------------|-----------|
| M3 | `GET /api/portfolio/holdings-enriched` | `action_badge: string \| null` enum | `action_badge: {action, emoji, reason, tone}` (object) | Badges render as `[object Object]` |
| M4 | `GET /api/portfolio/holdings-enriched` | `current_value_rs`, `gain_rs`, `gain_pct`, `weight_pct` (per-holding) | `value_rs`, `invested_rs`, `pnl_rs`, `pnl_pct` (different names) | Fields accessed by wrong name → undefined |
| M5 | `GET /api/portfolio/holdings-enriched` | `v3_grade: "A"\|"B"\|...\|"F"` (per-holding) | No `v3_grade` field on individual holdings | Grade badges always empty |
| M6 | `GET /api/portfolio/holdings-enriched` | Top-level: `portfolio_id`, `total_value_rs`, `total_invested_rs`, `total_gain_pct` | Top-level: `totals.value_rs`, `totals.invested_rs`, `totals.pnl_pct`, no `portfolio_id` | Summary KPIs read wrong path |
| M7 | `GET /api/portfolio/holdings-enriched` | No `alerts` expected | Backend sends `alerts[]` with severity/title/detail | Not displayed (data loss) |
| M8 | `GET /api/portfolio/holdings-enriched` | No `health` expected | Backend sends `health.health_score`, `health.components`, `health.risk_drivers` | Not displayed (data loss — duplicate of insights/analysis) |

#### P2 — Intelligence/overlap field renames

| # | Endpoint | Frontend expects | Backend returns | UI impact |
|---|----------|-----------------|-----------------|-----------|
| M9 | `GET /api/intelligence/portfolio` | `overlap_matrix[].fund_a`, `fund_b`, `overlap_pct` | `pairwise_overlap[].a_name`, `b_name`, `overlap_pct` + top-level key is `pairwise_overlap` not `overlap_matrix` | Diversification page reads wrong keys |

#### P2 — Concentration sector shape differs

| # | Endpoint | Frontend expects | Backend returns | UI impact |
|---|----------|-----------------|-----------------|-----------|
| M10 | `GET /api/portfolio/exposure/concentration` | `sector.breakdown[].{name, pct, cap_pct}`, `sector.top_stock`, `sector.herfindahl` | `sector.items[].{name, pct}`, `sector.hhi_x10000`, `sector.hero_insight`, `sector.effective_n` | Concentration treemap reads wrong structure |

#### P2 — Dashboard envelope field types

| # | Endpoint | Frontend expects | Backend returns | UI impact |
|---|----------|-----------------|-----------------|-----------|
| M11 | `GET /api/dashboards/*` | `badge: string` (e.g. "HEALTHY") | `badge: {label, tone}` (object) | Badge pill text shows `[object Object]` |
| M12 | `GET /api/dashboards/*` | `insight: string` (headline sentence) | `insight: {headline, subtext, hero}` (object) | Page headline shows `[object Object]` |

#### P2 — Plans response wrapper

| # | Endpoint | Frontend expects | Backend returns | UI impact |
|---|----------|-----------------|-----------------|-----------|
| M13 | `GET /api/plans/active` | Direct `PlanC` object (or null) | `{plan: PlanC}` wrapper with `has_plan` | Plan kanban may crash or show empty |
| M14 | `GET /api/plans/active` | `actions[].action_type: "sell"\|"buy"\|"switch"\|...` (lowercase) | `actions[].action_type: "TRIM"\|"EXIT"\|"SWITCH"` (uppercase, different verbs) | Action type badges show wrong labels |
| M15 | `GET /api/plans/active` | `actions[].holding_name` | `actions[].asset_name` | Card title reads wrong field → shows "Action" |
| M16 | `GET /api/plans/active` | `actions[].status: "pending"\|"done"\|"skipped"` | `actions[].status: "PENDING"` (uppercase) | Kanban column matching fails |

#### P2 — Goals response shape

| # | Endpoint | Frontend expects | Backend returns | UI impact |
|---|----------|-----------------|-----------------|-----------|
| M17 | `GET /api/goals` | `GoalsListRes: {total, on_track, at_risk, goals[]}` | `{goals: []}` only — no totals | Goals KPI strip empty, onTrack/atRisk logic fails |

#### P2 — Chat/prompts field name

| # | Endpoint | Frontend expects | Backend returns | UI impact |
|---|----------|-----------------|-----------------|-----------|
| M18 | `GET /api/copilot/suggested-prompts` | `prompts[].text` (string) or bare string array | `prompts[].label` (not `.text`), also has `query`, `icon`, `color`, `score` | Prompt buttons show empty text |

#### P3 — Plan action field renames (6 more)

| # | Endpoint | Frontend expects | Backend returns | UI impact |
|---|----------|-----------------|-----------------|-----------|
| M19 | `GET /api/plans/active` | `plan.actions_total` | `plan.total_actions` | Summary strip "Total actions" count wrong |
| M20 | `GET /api/plans/active` | `plan.actions_done` | `plan.completed_actions` | "done" count wrong |
| M21 | `GET /api/plans/active` | `plan.actions_pending` | `plan.pending_actions` | "pending" count wrong |
| M22 | `GET /api/plans/active` | `actions[].rationale` | `actions[].reason_text` | Card rationale text missing |
| M23 | `GET /api/plans/active` | `actions[].estimated_impact` | No such field; has `amount_rs` + `impact` (string) | Savings per action not shown |
| M24 | `GET /api/plans/active` | `actions[].suggested_alternative` | Not present | Switch target not shown |

#### P3 — Auth / CAS minor

| # | Endpoint | Frontend expects | Backend returns | UI impact |
|---|----------|-----------------|-----------------|-----------|
| M25 | `GET /api/auth/me` | `copilot_enabled: boolean` (required in Zod) | Field not present in response | Zod parse may fail if strict mode |
| M26 | `POST /api/casparser/access-token` | Already reads `access_token` correctly in adapter | ✅ No mismatch (adapter already handles this) | N/A |

### Summary

**39 field-level mismatches** found across **9 endpoints** between frontend Zod contracts and live backend responses. Grouped:

| Endpoint | Mismatch count | Severity |
|----------|---------------|----------|
| `/api/portfolio/holdings-enriched` | 8 (top-level keys, per-holding names, badge type) | P1-P2 |
| `/api/portfolio/trend` | 2 (date/value field names) | P1 |
| `/api/insights/analysis` | 1 (score → health_score) | P1 |
| `/api/portfolio/exposure/concentration` | 3 (sector shape: items vs breakdown, hhi vs herfindahl) | P2 |
| `/api/intelligence/portfolio` | 3 (pairwise_overlap vs overlap_matrix, a_name vs fund_a) | P2 |
| `/api/dashboards/*` | 6 (badge/insight are objects not strings, ×3 endpoints) | P2 |
| `/api/plans/active` | 10 (wrapper, uppercase enums, field renames ×6) | P2 |
| `/api/goals` | 4 (missing totals wrapper) | P2 |
| `/api/copilot/suggested-prompts` | 1 (label vs text) | P2 |
| `/api/auth/me` | 1 (missing copilot_enabled) | P3 |

### Known Bugs Found During Discovery

1. **Dashboard contract drift** — `portfolio.getNavHistory` Zod parse fails. **Root cause found**: OpenAPI spec says `series[].date` + `series[].value_rs`, but actual API returns `series[].snapshot_date` + `series[].total_value`. Also includes extra fields: `allocation`, `health_score`, `return_pct`, `scores`. Fix: update `TrendPointC` in `portfolio.contract.ts` to use `snapshot_date` + `total_value`, or remap in the adapter.
2. **Auth rate limiting** — `GET /api/auth/me` returns 429 on rapid calls (sidebar + multiple hooks call it simultaneously).
3. **Google Sign-In** — `renderButton()` fix committed but not deployed. Current deployed code uses `prompt()` which silently fails when third-party cookies blocked.
4. **Concentration page** — renders but treemap appears blank/very small in headless screenshots.
5. **Portfolio/Concentration** — sidebar not visible in some screenshots (missing `aside` element in snapshot).

---

## 6. Advisor App

Prototype includes 3 advisor screens (Book, Client 360, SIP board) accessed via "Advisor" toggle. **Production does NOT ship advisor routes.** The sidebar shows "client" persona only. Skip advisor tests; note in coverage.

---

## 7. Test Environment Variables

```env
BASE_URL=https://staging.niveshcopilot.com
SESSION_TOKEN=<from dev-set-cookie>
# Optional:
TEST_EMAIL=aporwal107@gmail.com
TEST_USER_NAME=Amit Porwal
```

---

## 8. Fixtures Needed

| Fixture | Source | Used By |
|---------|--------|---------|
| `user-profile.json` | `GET /api/auth/me` | All authenticated pages |
| `user-profile-not-onboarded.json` | Same, `onboarding_completed: false` | Login routing test |
| `holdings-enriched.json` | `GET /api/portfolio/holdings-enriched` | Dashboard, sidebar AUM |
| `holdings.json` | `GET /api/portfolio/holdings` | Portfolio page |
| `portfolio-trend.json` | `GET /api/portfolio/trend?days=365` | Dashboard sparkline |
| `insights-analysis.json` | `GET /api/insights/analysis` | Dashboard health score |
| `concentration.json` | `GET /api/portfolio/exposure/concentration` | Concentration page |
| `intelligence-portfolio.json` | `GET /api/intelligence/portfolio?narrate=true` | Diversification page |
| `dashboards-performance.json` | `GET /api/dashboards/performance?period=1y` | Performance page |
| `dashboards-goals.json` | `GET /api/dashboards/goals` | Goals page |
| `goals.json` | `GET /api/goals` | Goals page |
| `dashboards-tax.json` | `GET /api/dashboards/tax` | Tax page |
| `plans-active.json` | `GET /api/plans/active` | Plan + Recommendations |
| `suggested-prompts.json` | `GET /api/copilot/suggested-prompts` | Chat page |
| `google-client-id.json` | `GET /api/auth/google-client-id` | Login page |
| `empty-portfolio.json` | Holdings with 0 items | Empty state tests |
| `401-response.json` | `{detail: "Not authenticated"}` | Unauthenticated tests |
