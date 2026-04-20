# nivesh.ai - Product Requirements Document

## Implemented Features (Latest)

### Feb 2026 — /api/insights/generate: LLM → deterministic (hallucination kill #2)
User reported a second hallucination path: **818% Pharma exposure**, **Banking 773%**, phantom action "Reduce Banking ₹10L" tagged to wrong funds. Root cause: `routes/insights.py` was a *different* codepath using GPT-4o-mini with `response_format=json_object`. Despite a grounded prompt, the model fabricated impossible percentages and mismatched affected_funds.

- [x] **Replaced the OpenAI call in `/api/insights/generate` with `_deterministic_insights(...)`** — every insight is now built from the actual `holdings` + PG-backed `mf_investments` + optional `deep_analytics`/`allocation_data`. No LLM in the critical path.
- [x] **Hard clamps**: every percentage is `max(0.0, min(100.0, v))` so 818% is mathematically impossible. Regression-tested by `test_no_percentage_exceeds_100_ever`.
- [x] **PG-backed categories**: the builder prefers `portfolio_intelligence.mf_investments` (PG-joined category data) so Mid Cap / Large Cap / etc. appear correctly. Falls back to Mongo holdings when PG is degraded.
- [x] **New "heads-up" tier** for category concentration (25-35%) — explains why Mid Cap isn't flagged when it's only ~22%: a visible info-tier insight shows "Large Cap is your largest category at 28.3% (still below 35% guardrail)".
- [x] **Uses live `rules_config`** thresholds — edit AMC/category cutoffs in the Admin UI and insights update on next generation.
- [x] **`problem_distribution`** now counts real insight categories; `cost_leakage` totals come from actual regular-plan holdings; `action_funnel` mirrors top 5 insights.
- [x] **Pytest suite**: `tests/test_deterministic_insights.py` (5 tests) locks the no-hallucination contract plus the new heads-up tier. Total test suite 57/57.
- [x] **End-to-end verified** on `priyankamantri@gmail.com` (post PG restore): 5 insights — HDFC AMC 25.3%, Nippon India AMC 18.0%, Heads-up Large Cap 28.3%, Regular→Direct ₹13,938/yr, Debt 0.7%. Zero >100% values, zero fabricated sectors.
- [x] **Operational**: Postgres was down (container restart had wiped `nivesh` DB); ran `/app/scripts/restore_datastores.sh` which re-seeded 41 instruments and cleared the `degraded` flag.

### Feb 2026 — Admin UI: V2 Rules Manager + LLM Prompts Manager (Phase 1 + Phase 2)
Live-tunable configuration and auditability for the entire V2 engine + every LLM system prompt, behind the admin gate.

**Backend**
- [x] **`services/rules_config.py`** — DB-backed registry (`db.system_config.key="rules_config"`) with deep-merged defaults. Exposes `get_config()`, `get_param()`, `is_enabled()`, `save_overrides()`, `reset_to_defaults()`. In-memory cache, invalidated on write.
- [x] **`services/prompts_manager.py`** — 7 prompts registered (`financial_advisor_system`, `insight_analysis_system`, `cas_parser_system`, `insights_system_prompt`, `category_rating_system`, `mf_rating_system`, `allocation_analysis_system`). Each exposes default/current/overridden. `get(name, **kwargs)` supports template `.format()`.
- [x] **`services/rules_dsl.py`** — whitelisted AST evaluator for custom rules. No `eval`/`exec`/`compile`. Allowed: constants, names (context lookup), comparisons, bool ops, arithmetic, chained compares, `min/max/abs/len/sum/round`. `validate_expression` rejects `lambda/def/comprehensions/assignments/imports/if-exp` *in addition to* unsafe `Call`s to stay in sync with the runtime allow-list.
- [x] **`routes/admin_rules.py`** — admin endpoints:
  - `GET/PUT/POST(reset) /api/admin/rules-config` — built-in rule params + enable toggles.
  - `GET/POST/DELETE /api/admin/rules-config/custom[/{id}]` — custom rules.
  - `POST /api/admin/rules-config/custom/validate` — expression validator + sample-context evaluator.
  - `GET/PUT/POST(reset)/POST(test) /api/admin/prompts[/{name}]` — prompt listing, editing, LLM sandbox.
- [x] **`services/action_plan_manager._apply_action_rules`** — every hardcoded threshold replaced by a `rules_config.get_config()` lookup. Per-rule `enabled` flag honoured. New `_apply_custom_rules` method evaluates admin custom rules after built-ins, supporting `FLAG_ONLY`, `ADD_DEBT_FUND`, `EXIT_HIGHEST_EXIT_SCORE` action types with optional category/AMC targeting.
- [x] `services/ai_engine.chat/chat_stream` now fetch the Copilot system prompt from `prompts_manager` at runtime (fallback to code default).
- [x] Pytest coverage: `tests/test_rules_admin.py` (17 tests — DSL safety, config shape, lambda/comprehension rejection, prompts registry) + `tests/test_admin_rules_prompts_api.py` (20/21 integration tests hitting the public URL).

**Frontend**
- [x] **`components/admin/RulesConfigSection.jsx`** — per-rule card with enable/disable toggle, numeric inputs for every param (threshold, cost-leak-₹, max-switches, debt targets, etc.), "default X" tag when a param is overridden, global Save/Reset buttons. Below that, a **Custom Rules** editor with live expression validator (`Validate` + `Test against sample portfolio`), action type selector (FLAG/ADD DEBT/EXIT), category/AMC/max-exits targeting, reason code & text.
- [x] **`components/admin/PromptsSection.jsx`** — expandable row per prompt with length badge, "Overridden" pill, full-text editor, Save/Reset, **Test prompt** sandbox that actually hits `gpt-4o-mini` and shows the LLM response inline.
- [x] Registered both sections in `AdminView.js` directly under Secrets + Feature Flags.

**Verified by testing agent (iteration_31)**
- Backend API: 20/21 (95%) — the single red test (`validate rejects lambda`) is now fixed and covered by pytest (17/17) + live curl check.
- Frontend: 100% — both sections render, rule toggle/param/save/reset/add-custom/validate/test-prompt flows all working, no console errors.
- End-to-end BANANA test: override `financial_advisor_system` → chat → response contains BANANA → reset restored normal behaviour.

### Feb 2026 — Data-Accuracy Guardrails: Deterministic Insights + Rule 2b (VERIFIED)
- [x] **Deterministic insights** — `services/ai_insights.generate_insights` now bypasses LLM completely and builds each insight from pre-computed metrics. Kills the "Banking 773%" / "Pharma 818%" hallucinations the user flagged. Sector % clamped to `[0, 100]` for defence-in-depth. Added a new `category_concentration` insight that flags any MF category > 35% of corpus.
- [x] **Rule 2b — MF category concentration >35%** (`services/action_plan_manager._apply_action_rules`): if a single category (Mid Cap, Large Cap, etc.) exceeds 35% of total MF AUM, emit `CATEGORY_CONCENTRATION_EXIT` actions for the highest-exit-score funds in that category until under the threshold. Skips already-exited holdings; respects `priority_counter`.
- [x] **Regression tests** (`backend/tests/test_action_rules.py`): added `test_rule_2b_category_concentration_trims_over_35_pct` (fires on 100% Mid Cap, picks DSP with top exit_score first) and `test_rule_2b_skipped_when_category_under_threshold` (no trim when balanced). Fixed `test_rule_4_different_fund_overlap` to use diverse categories so Rule 2b doesn't subsume Rule 4. **35/35 tests green.**
- [x] **End-to-end verified** on `priyankamantri@gmail.com` (64 holdings, ₹64.90L):
  - `GET /api/intelligence/portfolio` → 4 AI insights, all numbers within `[0, 100]`, no hallucinations.
  - `POST /api/plans/generate` → engine v2.5, portfolio_score=64.2, confidence=98.2 High, 6 actions (5 Regular→Direct + 1 debt ADD).
  - Rule 2b correctly silent since no category > 35% for this user.

### Feb 2026 — V2.5 Batch C: Plan Board Hero Card (UX one-screen decision)
- [x] **New `PlanHeroCard.js`** surfaces the three numbers that actually matter on top of the Plan Board:
  - Big portfolio-score donut (amber/emerald/red by tier) with "Healthy/Good/Needs work/Critical" label
  - Confidence badge (shield icon · "98% · High")
  - Plan summary text (2 lines)
  - Before→After delta pills: Overlap / Top AMC / Debt / Save-per-year · pills are muted when a plan doesn't move the needle, emerald when improved
  - Degraded banner (amber) when `plan.degraded=true`
  - Do-Nothing celebratory card when `plan.do_nothing=true` (emerald gradient, "Nothing to fix right now · review next quarter")
  - V2 ENGINE provenance badge
- [x] Integrated into `PlanBoardView.js` — renders above the plans grid, driven by the active plan.
- [x] Verified via screenshot: hero card renders with 64/100 amber donut, "6 recommended actions", confidence 98% · High, pills showing the real before→after state, and existing plan cards untouched below.

### Feb 2026 — V2.5 Decision Engine (Batch A + B)
Implements the user's full V2.5 PRD:

**New scoring primitives** (`services/instrument_scoring.py`):
- `score_mf_switch(from, to, tax, intel)` → `switch_score = quality_improvement + overlap_reduction + cost_saving − tax_penalty`. Returns `recommended` (≥2.0 threshold), `annual_benefit_rs`, `tax_efficiency_score`.
- `score_mf_hold(mf, intel, tax)` → `hold_score = 0.4·high_quality + 0.3·low_overlap + 0.3·tax_penalty`. Returns `strong_hold` (≥6.5 threshold).
- **Quality v2** — 6 components with category-percentile normalization: Performance 25% / Risk-adj 20% / Consistency 20% / Drawdown 15% / Expense 10% / AUM 10%.
- **EXIT v2.5** — weights rebalanced 25/25/25/15/10, with **guardrails**: `quality_floor ≥ 7.5` blocks EXIT unless `overlap > 80%`; `tax_efficiency_score < 1.0` also blocks.
- **ADD v2.5** — new `need` component (15%) driven by `debt_target_pct` context.

**Plan-level outputs** (`services/action_plan_manager.py`):
- `portfolio_score` (0–100) with 5-component breakdown (diversification / overlap / AMC concentration / cost efficiency / asset allocation).
- `confidence_score` (0–100) + label High/Medium/Low using system health + data completeness + tax certainty + freshness.
- `plan_summary` hero-card string ("6 actions to improve your portfolio score. Save ₹4,302/yr. Raise debt 1%→21%. Est. tax ₹19,675.").
- `improvements` before-after dict for overlap / top_amc / debt / annual cost saving.
- `do_nothing: true` when portfolio_score ≥ 75 and no high-priority actions → synthetic HOLD action with reason `PORTFOLIO_HEALTHY`.
- `degraded` flag propagated from portfolio_intelligence when PG is down.
- Hard cap of 6 actions; `_priority_rank` helper handles both int and string priority encodings.
- `engine_version: "v2.5"` stamped in metadata.

**Rule engine updates**:
- Rule 3 — stricter trigger: `quality≥6.5 AND (ret_1y<8% AND ret_3y<10%)`. Was: OR on either.
- Rule 4 — only fires when `proxy_switch_score > 0` (exit benefit > tax cost).
- Rule 5 — **dynamic debt target** from user risk profile (low→30%, medium→20%, high→10%). Add amount auto-sized to close the actual gap.
- Rule 7 — Do-Nothing state when portfolio_score ≥ 75 and no high-priority actions.

**Verified** (iteration_30, 23/23 pytest passing): engine_version=v2.5, portfolio_score=64.2, confidence=98.2 (High), plan_summary rendering, dynamic debt target in action, Rule 7 path, guardrails, 6 new schema fields.

### Feb 2026 — V2 degradation fix + full logic spec
- [x] **Root cause of "only 1 action" bug**: admin secret `POSTGRES_URL` was missing after container restart → `pg_client.get_pool()` returned None → `portfolio_intelligence` returned `_empty_response` → only Rule 5 (debt gap, the only rule that doesn't need PG) fired. Plan Board showed just "ADD SBI Magnum Gilt".
- [x] **Fix**: `pg_client.get_pool()` now falls back to `postgresql://postgres:postgres@localhost:5432/nivesh` when the secret is missing (matches the bootstrap script's DB). Also hydrates `POSTGRES_URL` and `REDIS_URL` into admin secrets so auto-recovery is permanent.
- [x] **Transparency**: `compute_portfolio_intelligence` now logs `V2 DEGRADED` error and sets `response.degraded = true, degraded_reason = "..."` when Postgres is unreachable so the UI can show a warning instead of silent-fail.
- [x] **Verified**: plan regenerated → 6 actions (5 Rule 1 Regular→Direct + 1 Rule 5 debt gap). Previously: 1 action.
- [x] **Full V2 logic spec written** to `/app/memory/V2_COMPLETE_LOGIC.md` — scoring weights, rule priorities, failure modes, public APIs, Phase B gaps.

### Feb 2026 — V2 is the single source of truth (AI grounding fix)
- [x] **Critical architecture fix**: Copilot AI was fabricating recommendations (e.g. "sell IRB Infrastructure for tax-loss harvesting") that V2 Decision Engine never produced. Resulting plan actions never matched AI's narrative.
- [x] Rewrote `FINANCIAL_ADVISOR_SYSTEM` prompt in `services/ai_engine.py` with hard grounding rules: AI cannot invent stocks, funds, exits, switches, or numbers outside V2's output; must cite V2 action or deflect.
- [x] Added `_v2_active_plan_context(user_id)` in `routes/chat.py` that compacts the active V2 plan (actions + reason_codes + tax_impact) and injects it into **every** chat turn (stream + non-stream).
- [x] Verified: "Which stocks should I sell for tax-loss harvesting?" now deflects → lists V2's actual MF Regular→Direct exits instead of fabricating stock picks. "What should I do?" returns V2 actions with exact tax numbers (₹935, ₹15,260).

### Feb 2026 — Save-as-Plan flow fixes
- [x] **Fix: "Save as Plan" now activates the plan** — chains `/plans/generate` → `/plans/{id}/save` to promote preview→active.
- [x] **Fix: "Open Plan Board" navigation** — threaded `onNavigateToPlanBoard` prop through `Dashboard → NiveshCopilotDrawer → ChatView → SaveAsPlanCard`.
- [x] **Fix: stale Plan Board** — `SaveAsPlanCard` dispatches `nivesh:plan-saved` event; `PlanBoardView` subscribes and refetches.
- [x] Silent save failures no longer masked as ✓ PLAN READY — surface errors with retry.

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
