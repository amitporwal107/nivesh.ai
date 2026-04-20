# nivesh.ai - Product Requirements Document

## Implemented Features (Latest)

### Feb 2026 — Save-as-Plan flow fixes
- [x] **Fix: "Save as Plan" now activates the plan.** Previously `/plans/generate` only created a preview (`status="preview"`) but PlanBoardView only reads `status="active"`, so users saw nothing. `SaveAsPlanCard.handleGenerate` now chains `/plans/generate` → `/plans/{id}/save` to promote preview→active (archiving any prior active plan).
- [x] **Fix: "Open Plan Board" navigation works.** `window.location.hash = "plan_board"` wasn't triggering react-router's `useLocation`. The drawer now receives an `onNavigateToPlanBoard` prop from Dashboard that calls `setActiveTab("plan_board")` + closes the copilot. Hard fallback uses `history.pushState` + `hashchange` event.
- [x] Threaded prop: `Dashboard → NiveshCopilotDrawer → ChatView → SaveAsPlanCard`.

### Feb 2026 — Phase A: Holistic Asset Coverage + ClearTax Tax Engine + Editable Buy Date
- [x] **Copilot is no longer equity-only** — `_build_context` classifies ETFs (GOLDBEES/SGB → gold, LIQUIDBEES/GILT/BHARAT BOND → debt, rest → equity), bonds/FDs → debt, direct equity+MF → equity. Fixed `other_pct=100%` math bug.
- [x] **`portfolio_intelligence.compute_portfolio_intelligence`** now always returns a holistic `total_value` + `asset_allocation{equity_pct, debt_pct, gold_pct, other_pct, *_rs}` covering MF+equity+ETF+debt+gold (was MF-only). AMC/overlap stays MF-only by design.
- [x] **`tax_calculator` rewritten to ClearTax FY 25-26 rules** (https://cleartax.in/s/capital-gains-income):
  - Equity STCG 20% (≤12m), Equity LTCG 12.5% over ₹1.25L exemption (>12m)
  - Debt MF acquired ≥ 1-Apr-2023 → always slab (default 30%); pre-Apr-2023 → 12.5% LTCG >24m
  - Gold/SGB → slab STCG, 12.5% LTCG >24m
  - Asset-class classifier (`_classify_asset`) drives rate selection
  - **When `buy_date` is missing**, returns `tax_impact_pending=True` instead of fabricating ₹0
- [x] **`action_plan_manager`**:
  - `_create_exit_action_with_tax_analysis` now falls back to `tax_calculator.calculate_tax_impact(holding)` when the candidate didn't pre-compute `tax_impact` → every EXIT action now carries `tax_liability`, `asset_class`, `tax_regime`
  - `_calculate_total_tax_impact` rewritten to aggregate per asset class with new rates; returns `total_tax_liability` (read by Copilot/UI), keeping `total_tax` as legacy alias
- [x] **CAS parser `buy_date` extraction** — `cas_api_client._extract_buy_date_from_transactions` scans per-scheme `transactions[*].date`, picks the earliest purchase date, and populates `buy_date` on every `_holding_from_*` builder (MF, demat MF, equity, bond/SGB). `routes/portfolio.py` no longer back-fills `datetime.now()`; missing dates stay `None` → taxed as pending.
- [x] **PUT `/api/portfolio/holdings/{id}`** uses `exclude_unset=True` so callers can explicitly clear `buy_date` with `null` without hitting 400 "No fields to update".
- [x] **Editable Buy Date UI** — new `InlineBuyDateCell` in `PortfolioView.js` adds a dedicated **Buy Date** column; calendar-icon cell with "Set date" hint for missing values; click → native date picker; Enter/blur persists (toast: "Buy date updated"); Escape cancels.
- [x] **Verified** (iteration_29): `plan_tax_liability` moved from ₹0 → ₹19,675; `gold_pct` 0→18.8%, `debt_pct` 0→0.7%, `other_pct` 100→0% for the test user.

### Phase B (parked plan — not in this release)
- Factor equity ETFs into overlap analysis (treat equity ETFs as MF-like containers).
- Factor direct-stock concentration into "concentration" prompt (e.g., "30% of portfolio in 1 stock").
- FIFO lot-wise tax using the full `transactions` array per holding.
- Accept user's income slab as a profile field so slab-rate debt/gold STCG uses the real rate (currently default 30%).
- One-click "Apply current NAV as buy date" for legacy holdings where CAS didn't provide transaction history.
- Back-populate tool: re-run CAS parse for existing users to repair the `buy_date = upload_date` artifact on already-imported portfolios.

### Feb 2026 — Nivesh Copilot Interactive Charts & Save-as-Plan
- [x] **Replaced static prompt templates** with context-aware interactive cards driven by real portfolio signals.
  - New `CopilotPromptCard.jsx` with 3 variants (hero / compact / tiny) — each renders a mini Recharts viz (MiniDonut / MiniBar / MiniGauge / MiniStat / MiniSplit) backed by `viz` payload from backend.
  - Backend `_build_viz_for_prompt` in `routes/copilot_prompts.py` emits `{kind, series, headline, caption}` per prompt using real asset mix, top-3 overlaps, top-3 AMC exposure, action count, tax liability, underperformers.
  - `context_summary` enriched with `top_overlaps`, `top_amcs`, `gold_pct`, `other_pct`, `fund_count`, `underperformer_count`, `plan_tax_liability`.
- [x] **Input-bar chip strip** shows viz headline pills (e.g. `96%`, `6`, `77%`) next to each prompt label.
- [x] **Save-as-Plan CTA** (`SaveAsPlanCard.jsx`) auto-injects under high-intent AI responses (heuristic-matched via `shouldShowSavePlan`). Click → POST `/api/plans/generate` → success state with action count + est. tax → "Open Plan Board" button navigates to `#plan_board`.
- [x] Tested end-to-end via frontend testing agent: 100% backend + frontend pass (iteration_28).

### Apr 2026 — V2 Action Generation Rule Engine (6 Core Rules)
- [x] **Implemented 6 explicit business logic rules** in `services/action_plan_manager._apply_action_rules` per user spec (see `/app/memory/V2_ACTION_GENERATION_RULES_COMPLETE.md`):
  - **Rule 1**: Regular → Direct consolidation (same fund, exit Regular plan)
  - **Rule 6**: Regular → Direct cost-leak detection (>₹10K/yr threshold → SWITCH actions)
  - **Rule 2**: AMC concentration >15% → EXIT funds by highest exit_score until <15%
  - **Rule 3**: Underperformer → EXIT + ADD same-category top replacement (by category)
  - **Rule 4**: Different-fund overlap >60% → EXIT fund with higher exit_score
  - **Rule 5**: Debt <10% → ADD debt fund (excluding over-concentrated AMCs)
- [x] New helpers: `_classify_plan_type`, `_normalize_base_scheme_name`, `_find_regular_direct_pairs`, `_estimate_cost_leak`, `_find_underperformers`, `_find_best_same_category_replacement`, `_build_exit_action_from_holding`
- [x] Full test coverage: `backend/tests/test_action_rules.py` (10 tests, all passing, no DB/network deps)
- [x] **Verified on real user (priyankamantri, 64 holdings)**: Engine produced 6 actions — 5 Regular→Direct consolidations (HDFC Balanced, HDFC Small Cap, HDFC Flexi Cap, Parag Parikh Flexi, SBI Contra) + 1 debt ADD (ICICI Corporate Bond). Tax impact computed for all EXIT actions.
- [x] Rules applied in priority order with shared `exited_holding_keys` set to prevent duplicate recommendations for same holding.


### Feb 2026 — Code Review Fixes (Security + Hooks + Keys)
- [x] **MD5 → SHA-256** in `routes/analytics.py:179, 191` (day_hash seeds for fake price generation)
- [x] **eval()** — verified not present in current codebase (previously removed)
- [x] **Hardcoded test tokens** — 13 instances across 9 test files migrated to `os.environ.get("NIVESH_TEST_ADMIN_TOKEN"/"NIVESH_TEST_USER_TOKEN", <dev_fallback>)` pattern; new `tests/conftest.py` with `admin_token` + `user_token` + `base_url` fixtures for CI override
- [x] **ESLint config** (`frontend/eslint.config.mjs`) — enabled `react-hooks/exhaustive-deps` + `react/no-array-index-key` as `warn`; hooks/keys issues are now discoverable via `npx eslint`
- [x] **Array index keys** fixed in AICopilotView.jsx (actions list, problem pills) + MFDataSection.jsx (holdings table)
- [x] **Unused catch clauses** → `_err` with `caughtErrorsIgnorePattern: ^_` — top-3 reviewed files now lint clean

### Feb 2026 — Container recovery + LLM Circuit Breaker (Preview Fix)
- [x] **Supervisor recovery** — postgres/redis supervisor configs restored after container package wipe; DB schema reapplied; secrets re-hydrated
- [x] **Bulk rescrape** — aporwal107 + priyankamantri portfolios re-seeded via APScheduler; 20 funds currently in PG (drain continuing in background)
- [x] **LLM circuit breaker** (`ai_insights._LLM_CB_UNTIL`) — Emergent LLM upstream was blocking event loop 60s+ despite `asyncio.wait_for + shield`; circuit is now permanently **open by default** so `/api/intelligence/portfolio` returns in <0.5s with deterministic fallback. Admin can reset via `POST /api/admin/ai/circuit/reset` once upstream is healthy.
- [x] **Deterministic fallback insights** retain full quality (cite exact ₹ + % from real PG metrics):
  - "Your ₹64.90L portfolio behaves like ₹19.60L due to overlap."
  - "HDFC Bank Ltd. is 5.01% of your portfolio via 15 funds."
  - "3 Large Cap funds with 60.96% average overlap."
  - "Parag Parikh Flexi Cap Direct Growth and Parag Parikh Flexi Cap Fund Growth overlap 85.81%."

### Feb 2026 — CAGR fix + Category Ratings + Copilot wiring
- [x] **CAGR bug fix** (`routes/analytics.py`) — only computes CAGR when holding is ≥1 year old. Previously ingested `buy_date=today` produced absurd values like +720,699,398% (ratio^10). Now shows `—` until real purchase dates are parsed from CAS transactions.
- [x] **Category AI ratings** (`services/ai_insights.rate_portfolio_categories`) — per-category 1-5 star rating based on fund count + avg pair overlap; LLM upgrades the reason text. Exposed in `/api/intelligence/portfolio` response as `category_ratings[]`.
- [x] **On-demand scraping** — `fund_data_resolver.get_fund_data` now scrapes Groww whenever user hits the endpoint (cache miss), regardless of market hours. Background APScheduler drain still respects off-hours gate for bulk operations.
- [x] **Real PG data in AI Copilot** — `/api/scenarios/suggest` now prepends 2 intelligence-driven scenario cards: "Consolidate: remove <fund>" (from top redundancy suggestion) + "Consolidate <Category> funds" (for categories with ≥50% avg overlap), each citing exact ₹ amounts + pp overlap reduction + sector drift.
- [x] **Category ratings UI** — `PortfolioIntelligenceTab.jsx` CategoryStrip now shows 1-5 star rating per category with AI-upgraded reason text.

### Feb 2026 — Portfolio Intelligence (AI-grade Fund Overlap Rewrite)
- [x] **Bulk scrape pipeline** — seeded aporwal107@gmail.com + priyankamantri@gmail.com portfolios into scrape queue, APScheduler-drained 21/22 funds; PG now has 22 MUTUAL_FUND + 712 EQUITY rows + 2102 holdings + ratios
- [x] **`services/portfolio_intelligence.py`** — real stock-level engine:
  - `compute_portfolio_intelligence(user_id)` returns narrative + compression + pairwise_overlap + top_stocks + category_inefficiency + sector_exposure + redundancy_suggestions
  - Pairwise overlap: `Σ min(w_A[i], w_B[i])` on stock-slug/name keys
  - Compression Score: HHI-reciprocal, normalised vs 80-stock target
  - Dedupe by instrument_id (collapses direct+regular plan variants)
  - Redundancy ranked by `overlap_reduced_pp - 0.3 * sector_l1_drift`
- [x] **`services/ai_insights.py`** — GPT-4o-mini via **emergentintegrations LlmChat** (JSON-parsed loose); deterministic fallback when LLM unavailable. Insights cite specific ₹/% amounts.
- [x] **MF AI rating** — `/api/intelligence/rate-fund/{uuid}` generates 1-5 stars + reason, cached in `mutual_fund_metadata.ai_rating/reason/rated_at`
- [x] **`routes/intelligence.py`** — 4 endpoints: GET `/portfolio`, GET `/portfolio/{user_id}` (admin), POST `/simulate` (what-if removal), POST `/rate-fund/{id}` (admin)
- [x] **Frontend — `PortfolioIntelligenceTab.jsx`** — compression hero ring + AI insights grid + top-stocks bars + pairwise heatmap + redundancy picker with live what-if simulator + category/sector strips. Mounted as the Fund Overlap tab in InsightsView.
- [x] 87 backend tests passing (including new `test_portfolio_intelligence.py`)
- Dependencies: `emergentintegrations` (Emergent internal SDK for Universal LLM key)

### Feb 2026 — Groww MF Data Fetcher Phase 1, 2 & 3
- [x] **Phase 1**: deterministic parser (JSON-first from `__NEXT_DATA__`, HTML regex fallback) + search-API slug resolution
- [x] **Phase 2**: APScheduler (Asia/Kolkata) — 3 cron jobs: drain_weekday (02-05h), drain_weekend (every 2h), stale_refresh (Wed 03:00)
- [x] **Phase 3**: Postgres persistence (UUID schema: instrument_master, mutual_fund_holdings, mutual_fund_performance_ratios, mutual_fund_metadata, scrape_audit_log) + admin dashboard (MFDataSection.jsx)
- [x] 3-tier read chain: Redis → Mongo → PG aggregate → live Groww scrape
- [x] Pluggable Postgres + Redis via admin secrets (POSTGRES_URL, REDIS_URL — "Data Layer" category)
- Dependencies: `asyncpg==0.31.0`, `redis==7.4.0`, `APScheduler==3.11.2`, local Postgres 15 + Redis 7 (supervisor-managed)

### Feb 2026 - Generic Admin Config Panel (Secrets + Feature Flags)
- [x] **Unified Secrets Registry** (`backend/helpers/secrets.py`)
  - DB-first with env fallback, module-level cache
  - Pre-registered: CASPARSER_API_KEY, EMERGENT_LLM_KEY, OPENAI_API_KEY, GOOGLE_CLIENT_ID, GMAIL_OAUTH_CLIENT_ID, CASPARSER_BASE_URL
  - Admin can add arbitrary custom secrets
  - Plain-text storage in `db.system_config.{key:"secrets"}.values` (TODO: Fernet encryption in Phase 2)
- [x] **DB-backed Feature Flags** (`backend/feature_flags.py`)
  - 3 modes per flag: `off` / `allowlist` / `everyone`
  - Pre-registered: ai_copilot, gmail_import, chat_streaming
  - Per-user email allowlist management
  - `/api/user/profile` returns `features: {key: enabled_bool}` for frontend gating
- [x] **Admin endpoints**: GET/PUT/DELETE `/api/admin/secrets/{key}` + POST test, GET/PUT `/api/admin/feature-flags/{flag}` + POST/DELETE users
- [x] **Frontend**: `SecretsSection.jsx` (grouped by category, mask/show/edit/test/delete/add-custom), `FeatureFlagsSection.jsx` (mode dropdown, allowlist chip editor)
- [x] Server startup hydrates both from DB (survive restarts)
- [x] Legacy `/admin/cas-config` endpoints kept for backward compat

### Feb 2026 - Admin CAS Parser API Key Management (superseded by Secrets)
- [x] Migrated into unified Secrets registry

### Feb 2026 - AI Copilot Phase 2
- [x] Custom Scenario Builder (sliders), Rebalance Plan, Save/Load scenarios, Apply → pending_actions
- [x] "Your Applied Action Plans" card with expand/collapse, mark-done, delete

### Feb 2026 - AI Copilot Phase 1 MVP
- [x] `/api/scenarios/suggest` + `/simulate` + `/rebalance-plan`
- [x] PortfolioContextHeader, ScenarioCard, SimulationPanel, AICopilotView
- [x] Real CAGR quick win (per-holding annualized return, fallback to static)
- [x] Feature-flag gated to aporwal107@gmail.com (now managed via Feature Flags UI)

### Feb 2026 - Mobile-First Responsive Overhaul
- [x] All screens mobile-first, body `overflow-x: hidden`, `min-w-0` on Dashboard shell
- [x] Horizontal scroll for tabs, donut+legend stacks, ChatView sidebar hidden by default
- [x] Suppressed cross-origin "Script error." overlays

### Apr 2026 - Enhanced AI Insights Engine
- [x] Full portfolio context in OpenAI prompt (overexposure, overlap, cost data)
- [x] Specific ₹/% citations in insights

### Prior UX & Architecture
- [x] server.py refactored into 10 route modules
- [x] SSE streaming chat, action intent cards, MF category cards, P&L heatmap
- [x] True look-through allocation via OpenAI gpt-4o-mini
- [x] Motilal Oswal-inspired dark/light dual theme

## Backlog

### P0
- Fernet-encrypt secrets at rest (SECRETS_ENCRYPTION_KEY env)
- Fix `/api/insights/generate` Action Plan still 1-step
- Security hardening: replace hardcoded test secrets with env, remove `eval()`, MD5→SHA-256 in analytics.py
- PAN encryption + consent logging + audit trails (DPDP)

### P1
- **Groww Phase 2**: APScheduler off-hours queue, admin panel for queue mgmt, bulk seed from user portfolios
- **Groww Phase 3**: wire ISIN-level overlap + true sector exposure into AI Copilot + InsightsView (replaces static category-proxy)
- AI Copilot Phase 3: chat-as-secondary, color system polish, icon library
- Fund & Stock Rating System (Morningstar-style)
- React hook dependency & array-index key cleanup
- Split oversized components (InsightsView 2122 lines, OnboardingView 904, DashboardOverview 861)
- CAS parser enhancement to preserve purchase dates → unlocks real CAGR coverage
- Goal-based planning (Retirement, Child Edu, SIPs)
- Stock-level overlap via AMFI disclosure data

### P2
- Historical-backtest CAGR model
- Real "Apply Changes" with broker integration
- Portfolio versioning (delta tracking)
- PostgreSQL migration
- Android wrap via Capacitor
- Admin audit log for secrets/flags changes (who changed what, when)
- Pending-plan badge on Dashboard sidebar

## Data Model Additions
- `db.system_config` — admin-managed config
  - `{key: "secrets", values: {KEY: value}, updated_at, updated_by}`
  - `{key: "feature_flags", flags: {flag_key: {mode, allowlist}}, updated_at, updated_by}`
  - `{key: "cas_parser", use_sandbox: bool, ...}` (legacy sandbox toggle)
- `db.saved_scenarios` — named scenario saves
- `db.pending_actions` — applied rebalance plans
- `db.scenario_simulations` — every simulate click log
