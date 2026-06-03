# Bug Triage — V5 Frontend + Backend Contract Gaps

> Last updated: 2026-05-28  
> Sources: Playwright E2E discovery, live-contract suite against staging, manual investigation

---

## LEGEND

| Severity | Meaning |
|----------|---------|
| **P1**   | User-facing blocker — feature completely broken |
| **P2**   | Significant degradation — partial data or intermittent failure |
| **P3**   | Minor — cosmetic or edge-case |

| Status | Meaning |
|--------|---------|
| **OPEN** | Not yet fixed |
| **FIXED-UNDEPLOYED** | Fix committed, not yet on staging |
| **DEPLOYED** | Fix live on staging |

---

## P1 — Blockers

### BUG-011 · Dashboard contract drift — `portfolio.getNavHistory`
- **Status**: FIXED-UNDEPLOYED (this session)
- **Affected**: `/v5/dashboard`
- **Symptom**: ErrorState "Couldn't load your dashboard" on first load
- **Root cause**: `NavPointC` Zod schema expected `date` + `value_rs` fields; backend sends `snapshot_date` + `total_value`
- **Fix**: Updated `portfolio.contract.ts` + `portfolio.adapter.ts` to map backend fields
- **Live-contract test**: `live-contracts.spec.ts > @live Portfolio Trend contracts`

### BUG-016 · Chat send endpoint wrong path
- **Status**: FIXED-UNDEPLOYED (this session)
- **Affected**: `/v5/chat` — send message
- **Symptom**: Every message sent returns 404; user sees no AI response
- **Root cause**: `chat.adapter.ts` called `POST /api/chat`; real endpoint is `POST /api/chat/send`
- **Fix**: Updated `chat.adapter.ts` endpoint + response parsing for `{user_message, ai_message}` shape
- **Live-contract test**: `live-contracts.spec.ts > @live Chat send`

### BUG-017 · Google Sign-In silent failure (3P cookies blocked)
- **Status**: FIXED-UNDEPLOYED (committed `7431d38`, not yet on staging)
- **Affected**: `/v5/login`
- **Symptom**: "Continue with Google" does nothing in Chrome (3P blocked), Firefox, Safari
- **Root cause**: `google.accounts.id.prompt()` (One Tap) silently fails when 3rd-party cookies are blocked
- **Fix**: Switched to `google.accounts.id.renderButton()` + `onCredential` callback

---

## P2 — Significant

### BUG-012 · Plan Board shows `version` Zod failure when plan exists
- **Status**: FIXED-UNDEPLOYED (this session)
- **Affected**: `/v5/plan`
- **Symptom**: Plan board shows "Something went wrong" even when backend returns a valid plan
- **Root cause**: `plan.contract.ts` had `version: z.string()` but backend sends integer `1`
- **Fix**: Changed to `z.union([z.string(), z.number()]).optional()`

### BUG-013 · Goals / Performance / Tax pages show wrong field names
- **Status**: FIXED-UNDEPLOYED (this session)
- **Affected**: `/v5/goals`, `/v5/performance`, `/v5/tax`
- **Symptom**: Fields undefined or missing — pages show zeroed/empty state
- **Root cause**: Multiple contract mismatches (see live-contracts tests M11–M17)
- **Fix**: Updated `goals.adapter.ts`, `analytics.adapter.ts`, `dashboards.adapter.ts`, `goal.contract.ts`, `dashboard.contract.ts` to handle real backend shapes

### BUG-018 · Logout doesn't redirect to /login
- **Status**: FIXED-UNDEPLOYED (this session)
- **Affected**: `/v5/settings`
- **Symptom**: Clicking "Sign out" clears cache but leaves user stuck on settings page
- **Root cause**: `useLogout()` only called `qc.clear()`, no navigation
- **Fix**: Added `navigate("/login")` in both `onSuccess` and `onError` of `useLogout()`

### BUG-014 · Insights `portfolio_health.score` field missing
- **Status**: OPEN (backend returns `health_score`, frontend reads `score`)
- **Affected**: Dashboard health score display
- **Symptom**: Health score shows 0 or undefined
- **Root cause**: Contract mismatch M2 — backend sends `.health_score`, frontend Zod expects `.score`
- **Live-contract test**: `live-contracts.spec.ts > @live Insights contracts`
- **Fix needed**: Frontend already reads both (`v3.data.health.health_score || v3.data.health.score`) — verify end-to-end

### BUG-015 · Holdings enriched field names all wrong
- **Status**: FIXED-UNDEPLOYED (this session — portfolio.adapter.ts rewritten)
- **Affected**: `/v5/portfolio`, `/v5/concentration`, `/v5/diversification`
- **Symptom**: Holdings show ₹0 value, no gain/loss data
- **Root cause**: Contract mismatches M1–M6 — backend sends `value_rs/pnl_rs/pnl_pct`, frontend expected `current_value_rs/gain_rs/gain_pct`; totals nested in `totals.{}` not top-level
- **Fix**: Updated `portfolio.contract.ts` + `portfolio.adapter.ts` to map both field variants

---

## P3 — Minor / Cosmetic

### BUG-019 · Concentration — `herfindahl` vs `hhi` field
- **Status**: OPEN (backend sends `hhi`, frontend may read `herfindahl`)
- **Affected**: `/v5/concentration` sector breakdown
- **Root cause**: Contract mismatch M10 — `sector.items[]` not `sector.breakdown[]`, `hhi` not `herfindahl`, no `top_stock`
- **Live-contract test**: `live-contracts.spec.ts > @live Concentration contracts`

### BUG-020 · Intelligence/Overlap — field name mismatch
- **Status**: OPEN (low impact — page not built yet)
- **Affected**: `/v5/diversification` overlap matrix
- **Root cause**: Contract mismatch M9 — backend sends `pairwise_overlap[].a_name/b_name`, frontend expects `overlap_matrix[].fund_a/fund_b`

### BUG-021 · Dashboard badge/insight are objects, not strings
- **Status**: OPEN (adapters need defensive mapping)
- **Affected**: `/v5/performance`, `/v5/goals`, `/v5/tax` dashboard envelopes
- **Root cause**: Contract mismatches M11–M12 — `badge` is `{label, tone}` object, `insight` is `{headline, subtext, hero}` object; frontend had them as strings
- **Partial fix**: `dashboards.adapter.ts` now extracts string fields from objects

---

## Advisor/MFD API Contract Gaps (validated 2026-05-28)

These mismatches exist between the advisor.yaml YAML spec and what staging actually returns.  
**Status**: Advisor pages not yet built in V5 — gaps will need to be resolved when pages are built.

| ID | Endpoint | YAML spec says | Real staging sends | Impact |
|----|----------|---------------|-------------------|--------|
| ADV-001 | `GET /api/mfd/workspace` | `{mode, firm_name, advisor_name, ...}` | `{workspace_id, owner_user_id, type, created_at, mode_selected_at}` | `mode` field → `type`; `firm_name` missing |
| ADV-002 | `GET /api/mfd/profiles` | `{total, profiles[]}` | `{workspace, profiles[], count}` | `total` → `count`; `workspace` added |
| ADV-003 | `ClientProfileC` shape | `{profile_id, name, email, aum_rs, ...}` | `{profile_id, type, name, portfolio_score, portfolio_value_rs, ai_summary, priority:{score, bucket, factors, reasons}, ...}` | Entire priority system missing from contract |
| ADV-004 | `GET /api/advisor/today` | `{high_priority[], medium_priority[], low_priority[], summary}` | `{rows[], total_clients, shown, buckets:{high,medium,low}, headline}` | Completely different shape — flat `rows[]` not pre-bucketed |
| ADV-005 | `GET /api/advisor/aum` | `{total_aum_rs, mom_change_pct, clients[]}` | `{rows[], total_aum_rs, aggregate_mom_pct, headline}` | `clients[]` → `rows[]`; `mom_change_pct` → `aggregate_mom_pct` |
| ADV-006 | `GET /api/advisor/underperformers` | `{benchmark, benchmark_xirr_pct, gap_threshold_pct, underperformers[]}` | `{rows[], benchmark, benchmark_return_pct, gap_threshold_pct, headline}` | `underperformers[]` → `rows[]`; `benchmark_xirr_pct` → `benchmark_return_pct` |
| ADV-007 | `GET /api/advisor/rebalance` | `{threshold_pp, clients_needing_rebalance, clients[]}` | `{rows[], gap_threshold_pp, headline}` | `clients[]` → `rows[]`; top-level count gone |

### Advisor endpoints that DO work (all 200 on staging):
- `GET /api/mfd/workspace` ✅ 200
- `GET /api/mfd/profiles` ✅ 200
- `POST /api/mfd/profiles` ✅ 200
- `GET /api/mfd/profiles/{id}` ✅ 200
- `POST /api/mfd/profiles/{id}/activate` ✅ 200
- `POST /api/mfd/profiles/deactivate` ✅ 200 (was incorrectly listed as 404 in MISSING-APIS.md A4)
- `GET /api/advisor/today` ✅ 200
- `GET /api/advisor/aum` ✅ 200
- `GET /api/advisor/underperformers` ✅ 200
- `GET /api/advisor/rebalance` ✅ 200
- `GET /api/advisor/summary` ✅ 200

---

## Missing Backend APIs (still truly 404)

| # | Endpoint | Notes |
|---|----------|-------|
| M1 | `GET /api/portfolio/upload-latest-task` | Backend not yet built |
| M2 | `GET /api/portfolio/upload-status/{taskId}` | Backend not yet built |
| M3 | `GET /api/intelligence/sector-peers/{symbol}` | Backend not yet built |
| M4 | `GET /api/intelligence/v3-score/{isin}` | Route exists, backend throws 500 (pipeline data issue) |

> **Chat send was missing (POST /api/chat → 404) but the real endpoint is POST /api/chat/send — now fixed in frontend adapter.**

---

## Quick-fix scorecard (this session)

| Bug | Fix committed | Needs deploy |
|-----|--------------|-------------|
| BUG-011 Dashboard nav-history drift | ✅ | ✅ |
| BUG-016 Chat wrong endpoint | ✅ | ✅ |
| BUG-017 Google sign-in (7431d38) | ✅ | ✅ |
| BUG-012 Plan version field | ✅ | ✅ |
| BUG-013 Goals/Perf/Tax fields | ✅ | ✅ |
| BUG-018 Logout no navigate | ✅ | ✅ |
| BUG-015 Holdings field names | ✅ | ✅ |
| ADV-001–007 Advisor contract gaps | ⬜ recorded | ⬜ pages not built yet |
| M1–M3 Missing backend endpoints | ⬜ documented | ⬜ backend work needed |
