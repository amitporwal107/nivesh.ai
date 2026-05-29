# PRD — V5 Frontend Improvements

**Product:** Nivesh.ai New Design V5
**Component:** Frontend (`/app/frontend-v5/`)
**Status:** In progress
**Owner:** _TBD_

---

## 1. Summary

The V5 frontend is a full redesign of the Nivesh.ai user-facing product, built on React 18 + Vite + TanStack Query + Zod. This PRD tracks the improvement backlog for V5 — features that need to ship next (P1), are planned for near-term iterations (P2), and nice-to-have quality improvements (P3). Items move to Done when shipped to staging or production.

---

## 2. Scope and assumptions

**In scope:** V5 frontend pages, components, routing, and the backend API changes directly supporting the V5 UX. All items reference existing APIs unless explicitly noted.

**Out of scope:** NIDP data pipeline changes, scoring model changes, new data feeds — these are prerequisites, not V5 items.

**Key files:** `frontend-v5/src/pages/`, `frontend-v5/src/components/`, `frontend-v5/src/adapters/`

---

## 3. Status legend

| Priority | Meaning |
|----------|---------|
| P1 | Blocking / critical — ship next |
| P2 | High value, planned for near-term iteration |
| P3 | Nice-to-have, no urgent pressure |
| Deferred | Agreed to park until a dependency ships |
| Done | Shipped to staging or production |

---

## 4. P1 — Must ship next

### [V5-P1-001] Multi-step profile completion wizard (Risk → Goals → Snapshot)

**Source:** 2026-05-29 session feedback

After CAS import users have no goal-setting step. The PersonaCard CTA only opens the risk questionnaire. Need a multi-step wizard:
- Step 1 — Risk Profile (6-question questionnaire — already built)
- Step 2 — Goals (add at least 1 goal: type, target ₹, horizon, current corpus, SIP)
- Step 3 — Financial Snapshot (age, income, expenses — optional, unlocks better recommendations)

Progress banner on the Overview dashboard ("Profile 1/3 complete") until all three steps are done.

**APIs available:** `POST /api/goals`, `PUT /api/goals/snapshot`, `POST /api/user/risk-profile` — all exist.  
**Files to touch:** `PersonaCard.tsx`, `RiskProfileModal.tsx`, new `GoalSetupStep.tsx`

---

### [V5-P1-002] User Profile section in Settings

**Source:** 2026-05-29 session feedback

`/settings` page currently has no financial profile management. Users cannot update their risk profile or manage goals after onboarding.

Add a "Financial profile" section with:
- Risk profile card (current category + score + "Retake" button)
- Goals list with add/edit/delete
- Financial snapshot editor

**Files to touch:** `frontend-v5/src/pages/Settings/`

---

### [V5-P1-003] Gate Action Matrix until profile is complete

**Source:** 2026-05-29 design doc feedback

Per the risk-goal design document: *"No recommendation is generated until both risk profile and goals exist."*

When `has_risk_profile = false` OR no active goals, the Action Matrix shows a CTA card ("Complete your profile to unlock personalised actions") instead of empty buckets. Triggering profile completion regenerates the plan.

**Files to touch:** `Dashboard.tsx` ActionMatrix section, `index.tsx` data orchestration

---

## 5. P2 — Planned

### [V5-P2-001] Portfolio & Performance page — V2 parity

**Source:** 2026-05-29 user request with screenshots

Replicate the V2 Performance dashboard in V5:
- Performance Snapshot hero: health score gauge + 4 KPI tiles (Positive Returns, Outperforming Benchmark, Need Review, Total Gain ₹)
- Risk vs Return bubble chart (X=return%, Y=weight%, bubble size=invested ₹, color=return tier)
- Top Contributors & Detractors: horizontal bar chart (top 6 winners, top 4 losers)
- Benchmark Comparison: donut (Outperforming/Meeting/Underperforming) + Best & Worst Performers list (1Y return)
- Tab structure: AI Overview | Performance & Benchmark | Diversification & Consolidation | Tax | Risk

**API:** `/api/portfolio/analytics`, `/api/insights/analysis`, `/api/insights/v3-portfolio`  
**Files to touch:** `frontend-v5/src/pages/Performance/`

---

### [V5-P2-002] Overview dashboard: Risk + Goal alignment insights

**Source:** 2026-05-29 session feedback

Once user has risk profile + goals, `IntelligenceFeed` should surface:
1. Allocation drift per asset class vs risk profile target (not just equity)
2. Goal-at-risk alert (goal on_track_pct < 60%)
3. Horizon-volatility mismatch (goal horizon < 5y but > 40% small/mid-cap)
4. Regular → Direct fund opportunity (cost leakage)
5. Over-equity vs risk profile (equity_pct > target + 15pp)

**Source data:** `/api/goals`, `/api/onboarding/state`, `/api/insights`  
**Files to touch:** `IntelligenceFeed.tsx`, `Dashboard/index.tsx`

---

### [V5-P2-003] Goal-based rebalancing in recommendations engine

**Source:** 2026-05-29 design doc

Recommendation actions should carry goal context: *"Reduce small-cap by 8%. Your retirement goal is 5 years away and the portfolio volatility exceeds the acceptable level for that horizon."*

Backend: extend `generate_plan()` to run goal-alignment checks and attach `goal_id`/`goal_name` to actions.  
Frontend: action cards show "for [goal name]" context tag.

---

### [V5-P2-004] Gmail sync consent + source priority

**Source:** 2026-05-29 user message

On Gmail import, show a consent dialog: "Allow Nivesh to sync your Gmail for new CAS statements automatically?"
- Toggle to enable/disable auto-sync (stored as `auto_import_enabled` — backend field already exists)
- Source priority rule: NSDL eCAS > CDSL eCAS > CAMS > KFintech
- If NSDL eCAS was synced previously, do NOT re-import the same statement (dedup by statement_period + source combination)
- Settings toggle under Settings → Connected Accounts → Gmail Sync

**Backend:** `auto_import_enabled` in `gmail_tokens` collection already exists. Need dedup check in Gmail import route.

---

## 6. P3 — Nice to have

### [V5-P3-001] What-if goal simulator

**Source:** 2026-05-29 analysis

Each GoalCard gets a "Simulate" panel with sliders: monthly SIP, target amount, horizon years. Shows updated success probability + funding gap in real-time using existing `POST /api/goals/{id}/what-if` endpoint. "Accept changes" saves via PATCH.

---

### [V5-P3-002] Risk capacity vs tolerance divergence

**Source:** 2026-05-29 design doc (§3)

Add 3 capacity questions to the risk questionnaire (loan obligations, dependents, savings rate). Compute separate `capacity_score` and `tolerance_score`. Flag when they diverge >20 points. Anchor recommendations to the lower score.

---

### [V5-P3-003] Goal de-risk trigger (>90% funded)

**Source:** 2026-05-29 design doc (§6)

When a goal crosses 90% funded, auto-suggest shifting that goal's allocation from equity to debt/liquid. Show goal card banner: "Goal nearly achieved — de-risk to lock it in." Backend can auto-generate a `TRIM` action for that goal.

---

### [V5-P3-004] Onboarding: CAS source priority dedup

**Source:** 2026-05-29 user message

If user previously synced an NSDL eCAS statement for Apr/2026, a subsequent sync should not re-import the same period from CAMS or KFintech. Apply source priority: NSDL > CDSL > CAMS > KFintech, and skip if same `(statement_period, source_type)` already imported.

---

### [V5-P3-005] Remove ErrorBoundary debug overlay for production

**Source:** 2026-05-29 internal

The `ErrorBoundary` added in `main.tsx` currently shows a raw red error dump. For production, replace with a friendly "Something went wrong — try refreshing" screen. Keep the console logging, remove the raw stack display from the UI.

---

### [V5-P3-006] Fix Docker build context for frontend-v5

**Source:** 2026-05-29 internal — build was using stale Docker layer cache

`docker compose build --no-cache app-frontend-v5` was not rebuilding correctly because the staging VM had untracked `.js` files that shadowed `.tsx` sources. Mitigations added:
- `noEmit: true` in tsconfig.json
- `find src -name '*.js' -delete` in build script

Permanent fix: update `redeploy-staging.sh` to run `sudo find repo/frontend-v5/src -name '*.js' -delete` before docker compose build, so a fresh VM never accumulates stale files again.

---

## 7. Done

### [V5-DONE-001] Monthly portfolio values chart (SparkArea)
**Shipped:** 2026-05-29  
Fixed three root causes of flat-line chart:
1. `import-connect` route now saves `cas_statement_period`, `cas_statement_date`, `cas_portfolio_value_rs` from casparser JSON
2. `cas_statement_date` format "DD-MMM-YYYY" converted to ISO "YYYY-MM-DD" in adapter
3. `<XAxis dataKey="date">` always rendered (hidden when showAxis=false) so tooltip label is the date string, not the array index

---

### [V5-DONE-002] Action matrix empty after CAS import
**Shipped:** 2026-05-29  
`import-connect` and Gmail sync were calling `generate_plan(user_id)` (wrong signature, creates preview) instead of `refresh_plan(user_id)` (fetches data itself, saves as `active`). Fixed both routes.

---

### [V5-DONE-003] Vision API monthly values not persisting
**Shipped:** 2026-05-29  
Vision API model changed to `gpt-5` which was not available. Added fallback to `gpt-4o-mini` and detailed logging for each step.

---

### [V5-DONE-004] Persona-based Overview dashboard
**Shipped:** 2026-05-29  
- `PersonaCard` — detected persona + confidence + "Complete risk & goal profile" CTA
- `RiskProfileModal` — 6-question wizard → saves risk profile + shows target allocation
- `HealthScoreCard` — 4 sub-score bars (Diversification, Risk, Cost Efficiency, Performance)
- `IntelligenceFeed` — top 4 insights with severity badges
- `QuickActions` — 4 persona-aware cards
- V2-style `ActionMatrix` — domain buckets with ₹ amounts

---

### [V5-DONE-005] Post-onboarding routing fix
**Shipped:** 2026-05-29  
`/onboarding` page now redirects to `/dashboard` if `onboarding_completed = true`. Risk profile CTA lives on the Dashboard PersonaCard.

---

### [V5-DONE-006] Fix 137 stale .js shadow files breaking Vite build
**Shipped:** 2026-05-29  
Deleted all stale `.js` files, added `"noEmit": true` to tsconfig, and added `find src -name '*.js' -delete` as a prebuild step.

---

### [V5-DONE-007] Runtime crash: persona dict not unpacked
**Shipped:** 2026-05-29  
`persona` was stored in MongoDB as a nested dict. The `/api/onboarding/state` endpoint was returning the raw dict, and `PersonaCard.tsx` called `.replace()` on it → TypeError. Fixed backend to extract scalar values.

---

## 8. Success metrics

- CAS import → profile complete rate (target: >60% of users complete all 3 profile steps)
- Action matrix engagement rate (recommendations clicked / total sessions)
- Goal creation rate post-onboarding
- P1 items shipped per sprint

---

*Last updated: 2026-05-29*
