# nivesh.ai - Product Requirements Document

## Implemented Features (Latest)

### Feb 2026 — V3 Engine Phase 1: Scoring Layer + NAV Analytics + 5y AMFI Backfill

Complete delivery of the V3 scoring engine per the Excel spec. Takes 80% coverage from Phase 0b to 100% by (a) backfilling 5 years of daily AMFI NAVs, (b) computing NAV-derived primitives locally (no Moneycontrol dependency), and (c) shipping all 5 composite scores + Switch formula + 4 Guardrails as pure-Python deterministic functions.

**Phase 0c — Historical NAV backfill** (`scripts/backfill_amfi_nav_history.py`):
- Pulls AMFI's public `DownloadNAVHistoryReport_Po.aspx` in 30-day chunks over 5 years (61 HTTP calls, ~6 min runtime, ~3.5M rows parsed)
- Custom 8-column parser for historical dumps (different from daily `NAVAll.txt` 6-col format)
- **Strict ISIN-only + scheme_code matching** — the daily cron's fuzzy name match pollutes historical data (IDCW/Dividend variants share names with Growth plans). Skips rows containing "IDCW"/"Dividend"/"Payout"/"Reinvest"/"Bonus"/"Income Distribution" before matching.
- CLI: `--years N`, `--months N`, `--from YYYY-MM-DD --to YYYY-MM-DD`, `--dry-run`
- First full run: 25,922 rows upserted across 23 funds spanning 2021-04 → 2026-04.

**Phase 1a — NAV-derived analytics** (`services/nav_analytics.py`, new migration `004_v3_phase1a_nav_analytics.sql`):
- 4 new PG columns on `mutual_fund_metadata`: `max_drawdown_pct`, `consistency_score`, `downside_capture_pct`, `aum_trend_score`, `nav_analytics_at`
- Pure compute functions (all testable, no I/O):
  - `max_drawdown_from_series(navs)` — peak-to-trough % (returns None if < 30 days of data)
  - `consistency_score_from_series(navs, cat_avg_pct)` — 0-10 score = fraction of rolling 1y windows beating category avg (needs ≥ 18 months)
  - `downside_capture_from_series(fund, benchmark)` — monthly-returns ratio in down months (needs ≥ 6 benchmark down months)
  - `aum_trend_from_series(aum_snapshots)` — OLS slope of ln(AUM) over months → piecewise 0-10 score (needs ≥ 3 snapshots)
- `refresh_all_analytics(instrument_id)` — computes all 4 + writes back to metadata in one call
- **Weekly AUM snapshot** wired into `pg_writer.persist_scrape` — every user-triggered Groww scrape now snapshots AUM to `mutual_fund_aum_history` (idempotent on `(instrument_id, snapshot_date)`). Accumulates organically without a dedicated cron.
- `benchmark_index` is now auto-populated on scrape by joining `benchmark_master` on category.

**Phase 1b — V3 Composite Scoring** (`services/v3_scoring.py`):
- All 5 composite scores per Excel weights:
  - **Quality** = Performance 25% + Risk-Adj (Sharpe+Sortino) 20% + Consistency 20% + Drawdown 15% + Cost 10% + AUM/Age 10%
  - **Health** = Manager Tenure 25% + AUM Stability 20% + Turnover 15% + Concentration 15% + Downside Protection 15% + Expense Trend 10%
  - **Exit** = Overlap 25% + Tax 25% + Quality-Inverse 25% + Cost 15% + Portfolio-Fit 10%
  - **Add** = Gap-Fit 30% + Low-Overlap 25% + Quality 20% + Need 15% + Cost 10%
  - **Portfolio-Fit** = Diversification 25% + Overlap 25% + AMC-Concentration 20% + Cost 15% + Asset-Allocation 15%
- **Switch formula** (Excel Switch_Score sheet): `(Quality_new − Quality_old) + Overlap_reduction + Cost_saving − Tax_cost` → score, `recommended=True` iff ≥ 2.0
- **4 Guardrails** (Excel Guardrails sheet):
  - High-Quality Protection (Quality≥75 AND Health≥70, overridden if overlap > 80%)
  - Tax-exceeds-Benefit block
  - Recent-Investment lockout (<6 months)
  - Low-Confidence flag (reduces actions, doesn't block)
- **Weight redistribution**: any missing primitive's weight is proportionally redistributed across remaining components so the composite always sums to 100%. `missing_primitives[]` returned so UI can show "Quality 78 (confidence 80%)".
- 9 pure normalisers (0-10 scale): `_norm_returns`, `_norm_risk_adjusted`, `_norm_consistency`, `_norm_drawdown`, `_norm_cost`, `_norm_aum_age`, `_norm_manager_tenure`, `_norm_aum_trend`, `_norm_turnover`, `_norm_top10`, `_norm_downside_capture`, `_norm_expense_trend` — each documented with its curve.

**New API endpoints** (`routes/intelligence.py`):
- `GET /api/intelligence/v3-score/{instrument_id}?refresh=true/false` (admin) — returns all 5 composite scores + per-component values + effective weights after redistribution + missing_primitives + engine_version. Pass `?refresh=true` to recompute NAV analytics first.
- `POST /api/intelligence/v3-score/{instrument_id}/refresh-analytics` (admin) — recomputes the 4 NAV-derived primitives on demand.

**Verified end-to-end on HDFC Balanced Advantage Direct (live PG after backfill)**:
- max_drawdown = 10.18% (realistic for a low-vol balanced fund)
- consistency_score = 4.4/10 (beats category in 44% of rolling 12m windows)
- Quality = **71.45/100 with ZERO missing primitives**
- Health = 63.53 (missing aum_stability + downside_protection; weights redistributed to the 4 available components)
- All scores numeric, no NaN, no LLM in the path

**Testing**: 38 pure-logic unit tests in `tests/test_v3_scoring.py` covering every normaliser + each composite (full-data & missing-primitive cases) + switch formula + 4 guardrails + engine version constant. Plus integration-tested live via curl. Full backend suite: **87/87 green**.

### Feb 2026 — V3 Engine Phase 0b: Groww scraper expansion (all scoring primitives sourced, zero compute)

User direction: **"source from Groww, don't compute"**. Groww's `__NEXT_DATA__` payload was audited and found to expose every V3 Excel input natively. Phase 0b extracts them all in one scrape per plan, plus the sibling plan (regular ⇄ direct) to get both expense ratios without any post-processing.

**New Postgres columns on `mutual_fund_metadata`** (`migrations/003_v3_phase0b_scrape_fields.sql`, additive / idempotent):
- **Fund identity**: `allotment_date`, `fund_age_years`
- **Fund manager**: `manager_since`, `manager_education`, `manager_funds_count`, `fund_managers` (JSONB — full roster with tenure per person)
- **Expense trend**: `expense_ratio_3y_ago`, `expense_trend_delta`, `historic_expense_json` (last 36 monthly entries)
- **Turnover**: `turnover_ratio`, `turnover_as_of`
- **Category peers**: `category_avg_1y/3y/5y`, `rank_within_category_1y/3y/5y`
- **Concentration**: `top10_concentration_pct`
- **Sibling plan**: `sibling_slug` (for expense parity / cost-leak rule)
- **Analysis**: `analysis_json` (Groww PROS/CONS bullets)

**Parser** (`services/groww_client._extract_v3_primitives`):
- Reads `allotment_date` (falls back to `launch_date`), computes fund_age with `_years_between()` helper
- Iterates `fund_manager_details`, computes tenure per person from `date_from`, flags the longest-tenured as `primary_manager`
- Walks `historic_fund_expense` (1,000+ entries in HDFC sample) to find latest + closest-to-3y-ago entry → `expense_trend_delta`
- Pulls turnover from the first non-null entry in the history (top-level `portfolio_turnover` is stale)
- Maps Groww `stats[type=CATEGORY_AVG_RETURN]` and `stats[type=RANK_WITHIN_CATEGORY]` into structured dicts
- Sums `pct` across top-10 holdings for `top10_concentration_pct`
- Picks `regular_search_id` or `direct_search_id` (whichever is opposite of current `plan_type`) as `sibling_slug`

**Sibling-aware fetch** (`services/groww_client.fetch_fund_with_sibling`):
- Fetches primary plan, then chases `sibling_slug` to fetch the opposite plan
- Stitches `expense_ratio_direct` + `expense_ratio_regular` onto `metadata` — both expense ratios are now **sourced, not estimated**
- Attaches the full sibling scrape at `parsed["sibling"]` for downstream persistence

**Persistence** (`services/pg_writer.persist_scrape`):
- Upserts all 20 new V3 columns in a single SQL statement
- Recursively persists the sibling plan so both instrument_master rows (Regular + Direct) get their own V3 metadata records with cross-filled expense pair
- Uses `COALESCE(EXCLUDED, existing)` for expense_ratio_direct/regular so a partial scrape never nulls out a previously-filled value

**Resolver wiring** (`services/fund_data_resolver`):
- Live inline scrape path: `fetch_fund` → `fetch_fund_with_sibling`
- Off-hours drain path: same swap
- Every user-triggered fund resolution now pulls both plans automatically

**Coverage vs V3 Excel spec (Sheet1 inputs)**:
- ✅ Sourced natively (no compute): fund_age, manager_name + tenure, expense_direct, expense_regular, expense_trend, turnover_ratio, category_avg_1y/3y/5y, rank_within_category, top10_concentration, sharpe, sortino, alpha, beta, std_dev, returns_1y/3y/5y, aum, nav, allotment_date (17 of 24 primitives)
- ⏳ Accumulating via AMFI cron (Phase 0a): will unlock max_drawdown, consistency_score, downside_capture once history builds
- 📋 Phase 1 compute: `benchmark_isin` mapping (34 indices seeded in `benchmark_master`) → alpha/beta recomputation for validation

**Verified live on 3 funds** (HDFC Balanced Advantage, SBI Contra, Parag Parikh Flexi Cap):
- HDFC BAF: age=13.3y, manager=Anil Bamboli (3.7y, 6-person team), expense D/R=0.75/1.36, trend=-0.12, turnover=14.58%, cat_avg_3y=11.87, rank=2/category, top10=30.81%, 36 monthly expense entries + 3 analysis bullets
- SBI Contra Direct: age=13.3y, manager=Dinesh Balachandran (8.0y), expense D/R=0.75/1.53, trend=-0.15, top10=33.84% — **sibling Regular plan also auto-persisted** with same cross-filled expense pair
- Parag Parikh Flexi Cap: age=12.9y, manager=Rajeev Thakkar (12.9y — founder), expense D/R=0.62/1.27, top10=49.82%

**Testing**: 15 pytest unit tests (`tests/test_groww_v3_primitives.py`) — all pass, zero network/DB dependencies. Locks parser contract against future `__NEXT_DATA__` schema drift.

### Feb 2026 — V3 Engine Phase 0a: NAV/AUM history + extended metadata + benchmark master

Foundational data-layer work for the V3 engine. No backfill per user direction — data accumulates forward from today.

**New Postgres schema** (`migrations/002_v3_engine_schema.sql`):
- `mutual_fund_nav_history (instrument_id, nav_date, nav, source, created_at)` — PK on `(instrument_id, nav_date)`. Daily AMFI EOD NAV store.
- `mutual_fund_aum_history (instrument_id, snapshot_date, aum_cr, source, created_at)` — PK on `(instrument_id, snapshot_date)`. Monthly AUM snapshots (to start accumulating).
- `mutual_fund_metadata` extended with: `launch_date`, `manager_name`, `manager_tenure_years`, `expense_ratio_direct`, `expense_ratio_regular`, `benchmark_index`, `sub_category`, `amfi_scheme_code`.
- `benchmark_master (category → benchmark_name, benchmark_symbol, notes)` — **34 SEBI-standard categories seeded** (NIFTY 100 TRI for Large Cap, NIFTY Midcap 150 TRI for Mid Cap, CRISIL Liquid Fund Index for Liquid, etc.).
- `amfi_nav_fetch_log` — audit trail for each ingestion run.

**AMFI daily NAV ingestion** (`backend/scripts/fetch_amfi_navs.py`):
- Pulls `https://portal.amfiindia.com/spages/NAVAll.txt` (1.6 MB EOD dump, ~14K schemes).
- Resolves each scheme to `instrument_master.instrument_id` via ISIN → scheme_code → fuzzy name match (pg_trgm similarity ≥0.55).
- Batch upserts (500/tx) with `ON CONFLICT (instrument_id, nav_date)` for idempotency.
- Logs every run to `amfi_nav_fetch_log`. CLI supports `--dry-run`.
- **First real run**: parsed 13,968 NAVs, upserted 470 rows matched to our 735-fund catalog.

**Scheduling**:
- Registered in existing `services/mf_scheduler.py` (APScheduler, `Asia/Kolkata` TZ).
- `_amfi_navs_job` triggers daily at `22:00 IST` (AMFI publishes EOD NAVs ~20:30 IST).
- Runs in the same supervisor backend process — no OS-level cron required.

**Why PG (not Mongo) for NAV history**:
- NAV data is inherently time-series tabular; PG window functions (`LAG`, `ROWS BETWEEN`) make rolling returns / drawdowns trivial.
- Mongo aggregation pipelines are painful for the same. Index lookups ~1ms at projected 5M-row scale (4K MFs × 5y × 252 trading days).

**V3 primitives unlocked (future)**:
- NAV history → once accumulated: `max_drawdown`, `consistency_score`, `downside_capture`, rolling returns.
- AUM history → `aum_trend` after 3+ months of snapshots.
- Benchmark master → category → benchmark lookups for Alpha/Beta comparison.

**Turnover ratio — deferred to V1.1**: scraping complexity (SEBI annual factsheets PDF-only, AMC-specific formats) doesn't justify blocking V3. Health score will redistribute the 15% Turnover weight across other components. User confirmed.

### Feb 2026 — Light-Mode Fix for PortfolioIntelligenceTab
User flagged: "light mode is broken in most of the app". Audit revealed the **Fund & Overlap Insights** tab (`components/insights/PortfolioIntelligenceTab.jsx`) was authored dark-only — hardcoded `bg-slate-900`, `border-slate-800`, `text-white`, `text-slate-300/400`, `bg-black/20`, `border-white/5/20` without any `dark:` variants. In light mode the cards stayed pitch black and the hero gradient text went invisible (white text on near-white gradient).

- **Fix**: systematically added `dark:` variants to every hardcoded dark-theme utility in `PortfolioIntelligenceTab.jsx`. Mapping used:
  - `text-white` → `text-slate-900 dark:text-white`
  - `border-slate-800` → `border-slate-200 dark:border-slate-800`
  - `bg-slate-800/{50,30,40}` → `bg-slate-100 dark:bg-slate-800/{50,30,40}`
  - `text-slate-300` → `text-slate-600 dark:text-slate-300`
  - `text-slate-400` → `text-slate-500 dark:text-slate-400`
  - `bg-black/20` → `bg-slate-100 dark:bg-black/20`
  - `border-white/{5,20}` → `border-slate-{200,300} dark:border-white/{5,20}`
  - `bg-white/10`, `hover:bg-white/20` (buttons) → slate-100/200 equivalents in light
- **Verified**: light mode now renders clean white hero gradient with dark text, card backgrounds switch properly between bg-white (light) and bg-slate-900 (dark). Dark mode regression-checked — identical to previous design.
- **Other components already theme-aware** (verified by audit): `InsightsView.js`, `PlanBoardView.js`, `PlanHeroCard.js`, `ScenarioCard.jsx`, `RulesConfigSection.jsx`, `PromptsSection.jsx`, `AICopilotView.jsx`. Remaining `text-white` instances are all intentional white text on colored CTA buttons/badges (`bg-emerald-600 text-white`, `bg-red-600 text-white` etc.) which are correct in both themes.

### Feb 2026 — Insights↔Engine Consistency: CRITICAL flag now always ships with an action
User reported: insights flag "Reduce ICICI Prudential AMC concentration — CRITICAL (15.0%)" but the V2 Action Plan had no ICICI exit. Same pattern suspected for other users. Three discrete bugs found + fixed:

1. **Threshold inequality mismatch**: insights used `>= 15%` (so exactly-15% trips), engine used strict `> 15%` (so exactly-15% slips). Changed engine's Rule 2 and Rule 2b to `>=` for parity.
2. **Exit-loop break condition off-by-one**: `if current_pct <= target_pct: break` meant the engine exited the greedy loop as soon as it hit the threshold — without actually emitting an action. Changed to `< target_pct` so at-threshold AMCs/categories get one more exit to drop below.
3. **Name-matching skipped CAS broker prefixes**: PG returns clean scheme names (e.g. `ICICI Prudential Value Fund Growth`); Mongo holdings have broker prefixes + parenthetical notes (e.g. `DFG - ICICI Prudential Value Fund (erstwhile Value Discovery Fund) - Growth`). Old exact-match `_normalize_fund_name` missed them. New `_normalize_fund_name` strips 2-5 char broker codes + paren content; new `_fuzzy_match_holding` uses token-overlap (≥60% Jaccard) as a fallback.

- **Impact for `nivessh.ai@gmail.com`**: active plan 1 → 3 actions (EXIT HDFC Mid Cap + **EXIT ICICI Value Fund** + ADD debt). Portfolio score 62.2 → 77.2. Insights and plan now agree.
- **Priyankamantri** verified unchanged: 6 actions, including `AMC_CONCENTRATION_EXIT` on HDFC Focused (already worked).
- **2 new regression tests**: `test_fuzzy_match_strips_broker_prefixes_and_parens` (broker-prefix fuzzy match), `test_rule_2_amc_threshold_uses_gte_not_strict_gt` (ICICI-at-exactly-15% case). Full suite 62/62.

### Feb 2026 — Plan Generation on Unresolved Funds (fix for "action plan not generating")
User reported: insights now show 5 clean issues (Mid Cap 26%, HDFC 20.4%, ICICI 15%, etc.) but the **V2 Plan Board** only shows 1 ADD action. Investigation revealed:

- **Root cause**: `_calculate_amc_exposure_from_mf_investments` and the Rule 2 AMC-exit loop both skipped MF investments where `resolved == False`. When a user's holdings aren't yet mapped to PG `instrument_master` (common for freshly parsed CAS data or niche funds), the entire AMC rule became silent. Rule 2b (category) had the same blind spot because `category` is `None` for unresolved funds.
- **Fix**: removed the `resolved` gate from both paths. AMC is now extracted purely from `scheme_name` (name-based, always works). Added `_infer_category_from_name` helper that maps keywords ("Mid Cap", "Flexi Cap", "Bluechip", "Corporate Bond", etc.) to SEBI categories so Rule 2b fires on unresolved funds too.
- **Impact on `nivessh.ai@gmail.com`**: active plan went from 1 action (ADD debt) → 2 actions (EXIT HDFC Mid Cap via Rule 2 + ADD debt) with portfolio_score 62.2 → 77.2.
- **Tests locked in**: `test_rule_2_amc_fires_for_unresolved_funds` (reproduces the exact bug), `test_category_inferred_from_scheme_name` (Rule 2b on inferred categories), `test_infer_category_helper` (keyword matcher unit test). Full suite 60/60 green.
- **UX note**: `POST /api/plans/generate` creates a *preview* plan; the user must hit `POST /api/plans/{plan_id}/save` (or the "Save as Plan" button in UI) to activate. Existing users with stale active plans need to click "Regenerate plan" to see the new rules apply.

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
