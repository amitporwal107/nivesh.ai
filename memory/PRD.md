# nivesh.ai - Product Requirements Document

## Implemented Features (Latest)

### Feb 2026 — V3.1 Debt pipeline complete: Moneycontrol primitives scraped, persisted, and consumed
Completes the Category-Aware Scoring rollout for Debt funds.

**Scraper** (`services/moneycontrol_client.py`):
- `fetch_by_url()` parses MC's embedded `<script id="__NEXT_DATA__">` JSON to extract Morningstar-style `investmentStyle` (e.g., "Moderate Sensitivity High Quality"), ISIN, AUM, expense, CAGRs, manager, launch date, etc.
- `parse_investment_style()` maps to `credit_quality_score` (High=9, Medium=6, Low=3) and `duration_risk_score` (Limited=9, Moderate=6, Extensive=3).
- `search_fund()` (NEW) uses MC autosuggest `type=2` + Direct-plan prefilter, returning `{imid, url, display_name}`.
- Backward-compatible `search_imid()` wrapper retained.

**Persistence** (`services/pg_writer.persist_moneycontrol_scrape`):
- Matches existing funds by ISIN → scheme_name. Upserts debt columns into `mutual_fund_metadata`: `credit_quality_score`, `duration_risk_score`, `ytm`, `modified_duration`, `investment_style`, `moneycontrol_imid` + metadata fallbacks (aum, expense_ratio, manager_name, launch_date, etc.).
- Cleanly skips unknown funds (no blind inserts) — MC is enrichment-only.

**Scoring wiring** (`services/v3_scoring._norm_duration_risk_flex`):
- New flex normaliser prefers the pre-normalised `duration_risk_score` (0-10) from MC investment-style parsing, falls back to `_norm_duration_risk(modified_duration_years)`.
- `compute_quality_score()` debt weight profile now actively consumes credit_quality + duration_risk + yield_vs_category.

**APIs updated to surface new debt primitives**:
- `GET /api/admin/v3-master-funds` — `primitives.{credit_quality_score, duration_risk_score, ytm, modified_duration, investment_style, moneycontrol_imid}`.
- `GET /api/insights/v3-portfolio` — same keys under each fund's `primitives` block.

**Bulk import script** (`scripts/bulk_import_moneycontrol_debt.py` — NEW):
- Hydrates Mongo secrets, iterates debt funds classified by `v3_weights.classify_fund_category`, resolves imid via autosuggest, scrapes + persists, then triggers `nav_analytics_sweep.run_v3_rescore`.
- One-off data load: **36/36 debt funds persisted** with credit_quality=9.0 and duration_risk=9.0/6.0 mix. 185/185 funds rescored in 4.3s.

**Testing**:
- 14 new unit tests in `tests/test_moneycontrol_client.py` (style parsing, payload builder, helpers).
- 6 new unit tests in `tests/test_v3_debt_scoring.py` (flex normaliser, debt weight routing).
- Backend testing agent verified live: 36/36 debt funds return correct primitives in admin API; debt weight profile applied to all; 0 regressions across 69 previously-green V3 tests. `iteration_33.json`.

### Feb 2026 — Per-fund V3 breakdown + Danger-zone highlighting in Insights UI
User requested per-fund V3 scores (Quality, Health, Exit, Add, Switch) in the Insights UI, with danger-zone highlighting and deterministic explanations (no LLM).

**Backend** (`services/v3_explainer.py` — NEW):
- `classify_danger(bundle)` → `{level: 'critical'|'warning'|'ok', reasons:[], is_danger: bool}`. Critical: Quality<40 OR Health<40 OR Exit≥75. Warning: Quality<55 OR Health<55 OR Exit≥60 OR Switch≥2.0. Correctly ignores the positive `high_quality_protection` guardrail.
- `build_explanation(bundle, plan_type, cost_leak_rs)` → deterministic paragraph citing weakest Quality + Health components by name with primitive values (AUM, manager tenure, drawdown%, turnover%, top-10 concentration%, downside capture%). Caps at 3 drags + 1 strength + exit/switch notes. No LLM.

**API** (`routes/insights.py`, `/api/insights/v3-portfolio` extended):
- Each fund now returns: `plan_type`, `cost_leak_rs_per_yr`, `scores{quality,health,exit,add,switch}`, `danger`, `explanation`, `quality_components`, `health_components`, `primitives`, `guardrail_blocked`, `guardrail_reasons`.
- Switch score computed via `compute_switch_score(cost_saving_rs_per_yr=cost_leak, tax_cost_rs=0)` for Regular plans; null for Direct plans.
- `portfolio.n_danger_critical` + `n_danger_warning` counts exposed for headline tile.
- Funds sorted: critical → warning → ok, then by descending quality (funds needing attention float to top).

**Frontend** (`components/insights/V3FundBreakdown.jsx` — NEW, 240 LOC):
- Per-fund expandable card list with 5 score pills (Q / H / E / A / SW), tone-coded (emerald ≥75 · amber 55–74 · rose <55; inverted for Exit).
- DANGER badge (rose) + left border on critical funds; WARN badge (amber) + left border on warnings.
- Filter chips: All · Danger · Critical (with counts) — testids `v3-filter-all/danger/critical`.
- Click any row → deterministic explanation paragraph (bold headline preserved) + danger banner with bullet-list of reasons + primitives grid (AUM, manager tenure, drawdown, etc.).
- Full data-testid coverage: `v3-fund-breakdown`, `v3-fund-row-{id}`, `v3-fund-toggle-{id}`, `v3-fund-explain-{id}`, `v3-q-{id}`, `v3-h-{id}`, `v3-e-{id}`, `v3-a-{id}`, `v3-sw-{id}`, `danger-banner-critical/warning`.
- `V3PortfolioInsights.jsx` updated: replaced static "Flagged" tile with a "Danger zone" tile showing `n_danger_critical` / `n_danger_warning`. Mounts `<V3FundBreakdown>` below the leaderboard.
- Fully dark-mode safe.

**Live verified on priyankamantri** (26 MFs): 2 critical + 8 warning danger-zone funds. Example surfaced — Sundaram Value Fund Regular: DANGER, Q=37, H=62, E=54, A=38, SW=0.1, explanation cites "Small/young fund (AUM ₹1,212Cr) — maturity score 1.6/10; Risk-adjusted returns sub-par — Sharpe+Sortino 2.3/10". Below-par Parag Parikh Large Cap Regular: Q=27, E=82 (critical), explanation cites cost strength + exit recommendation.

**Testing**: 13 new pure-logic unit tests in `tests/test_v3_explainer.py` (all pass). Testing agent verified backend (25/25 integration tests pass) + frontend code review PASS. End-to-end Playwright screenshot confirms 26 rows render with correct colour-coding, filters work, row-expand shows primitives grid, critical/warning banners visible. Full backend suite **103/103 green**.

### Feb 2026 — NIFTY index-tracker proxies seeded → downside_capture unlocked

Final gap-close on the V3 analytics pipeline. Seeded 6 canonical NIFTY index-tracker funds as benchmark proxies for `downside_capture` computation.

**Seeded** (via `scripts/seed_benchmark_trackers_v2.py`):

| Tracker | AMFI Code | Benchmarks Covered |
|---|---|---|
| UTI Nifty 50 Index Fund Direct Growth | 120716 | NIFTY 50 TRI |
| UTI Nifty Next 50 Index Fund Direct Growth | 143341 | NIFTY Next 50 TRI |
| HDFC NIFTY 100 Index Fund Direct Growth | 149868 | NIFTY 100 TRI |
| Nippon India Nifty Midcap 150 Direct Growth | 148726 | NIFTY Midcap 150 TRI |
| Nippon India Nifty Smallcap 250 Direct Growth | 148519 | NIFTY Smallcap 250 TRI |
| ICICI Prudential Nifty 500 Direct Growth | 153161 | NIFTY 500 TRI |

Analytics sweep now fills downside_capture for **26 of 31 funds in PG**. Priyanka's portfolio avg Health 68.66 → 69.16.

### Feb 2026 — V3 Engine Ops Layer: Parallel Sweep + Redis Cache + Admin Monitor
Parallel sweep jobs (`services/nav_analytics_sweep.py`) + Redis composite-score cache + Admin Data Pipeline Monitor. 22/22 funds swept in 56ms, 24/24 rescored in 18ms. 92/92 backend tests green.

### Feb 2026 — V3 Engine Phases 2 & 3: Rules Migration + UI Integration
Phase 2 ports the V2.5 action-rule engine to consume V3 composite scores. Phase 3 surfaces V3 scores in PlanCard UI + adds V3 panel to Insights tab. Live-verified: coverage 100%, 26/26 funds scored.

### Feb 2026 — V3 Engine Phase 1: Scoring Layer + NAV Analytics + 5y AMFI Backfill
- Phase 0c: 5y AMFI NAV backfill (25,922 rows).
- Phase 1a: NAV-derived analytics (max_drawdown, consistency_score, downside_capture, aum_trend).
- Phase 1b: 5 composite scores + Switch formula + 4 Guardrails as pure-Python deterministic functions.
- 38 pure-logic unit tests + integration-tested live via curl.

### Feb 2026 — V3 Engine Phase 0b: Groww scraper expansion (all scoring primitives sourced, zero compute)
Extracts: `allotment_date`, `fund_manager_details` + tenure, `expense_ratio_direct/regular`, `historic_fund_expense`, `turnover_ratio`, `category_avg_1y/3y/5y`, `rank_within_category`, `top10_concentration`, `analysis_json`. Sibling Regular/Direct plan auto-fetched. 15 pytest unit tests.

### Feb 2026 — V3 Engine Phase 0a: NAV/AUM history + benchmark master
New PG schema: `mutual_fund_nav_history`, `mutual_fund_aum_history`, `benchmark_master` (34 SEBI-standard categories). Daily AMFI NAV ingestion @22:00 IST.

### Apr 2026 — V2 Action Generation Rule Engine (6 Core Rules)
Implemented 6 explicit business logic rules in `services/action_plan_manager._apply_action_rules`: Regular→Direct consolidation, cost-leak detection, AMC concentration, underperformer replacement, fund overlap, debt allocation gap. 10 tests pass.

### Feb 2026 — Admin UI: V2 Rules Manager + LLM Prompts Manager
Live-tunable config + auditability for the V2 engine + every LLM system prompt.

### Feb 2026 — Data-Accuracy Guardrails: Deterministic Insights + Rule 2b
`services/ai_insights.generate_insights` now bypasses LLM completely. Rule 2b fires for MF category concentration >35%.

### Feb 2026 — V2.5 Decision Engine (Batch A + B + Hero Card)
5 composite scores, Switch formula, guardrails. Plan Board Hero Card surfaces portfolio score donut, confidence badge, plan summary, before→after delta pills.

### Earlier work (condensed)
- Portfolio Intelligence (AI-grade fund overlap rewrite) — `portfolio_intelligence.py`, `ai_insights.py`, `PortfolioIntelligenceTab.jsx`.
- Groww MF Data Fetcher Phase 1/2/3 — parser, APScheduler cron, PG persistence.
- Generic Admin Config Panel — unified Secrets Registry + DB-backed Feature Flags.
- AI Copilot Phase 1 + 2 + interactive charts + Save-as-Plan.
- Mobile-first responsive overhaul, CAS parsing, Google OAuth, risk profile, Gmail import.

## Backlog

### P0 (next)
- **User Data Purge**: Admin UI button + `DELETE /api/admin/users/{user_id}/portfolio-data` endpoint to wipe 9 MongoDB collections (`holdings`, `action_plans`, `plan_history`, `portfolio_analysis`, `pending_actions`, `ai_insights`, `scenario_simulations`, `allocation_analysis_cache`, `fund_performance_cache`) for a single user while preserving `users`, `user_profiles`, `user_sessions`, `chat_sessions`. Enables fresh CAS re-upload testing.

### Recently completed (Feb 2026)
- **V3.1 Category-Aware Scoring Engine (Equity / Hybrid / Debt)** (2026-02-22): Per PRD. `services/v3_weights.py` stores editable weight profiles per category in MongoDB `system_config`. `v3_scoring.py` refactored to classify each fund (equity / hybrid / debt / liquid) and apply the category's weight profile. New primitive normalisers for debt (`credit_quality`, `yield_vs_category`, `duration_risk`, `credit_concentration`, `liquidity`) and hybrid (`allocation_stability`, `allocation_consistency`, `downside_capture`). Liquid funds classified but fall through to Equity weights (user deferred). Admin API `GET/PUT/POST /api/admin/v3-weights` with sum-to-100 validation. Frontend `V3WeightsSection.jsx` (editable numeric inputs + reset + dirty-state tracking) mounted in Admin > V3 Rules Engine tab. Classification distribution: 111 equity, 36 debt, 25 hybrid, 13 liquid. 12 new pytest tests + 4 regression tests updated → 70 total passing.
- **5-year AMFI NAV backfill for 157 new funds** (2026-02-22): `scripts/run_amfi_backfill.py` wrapper (hydrates Mongo secrets → runs backfill → analytics sweep → V3 rescore). Added **246,895 new NAV rows**, brought 165/185 funds to full `consistency_score`, 184/185 to `max_drawdown_pct`. `aum_trend_score` still blocked (empty `mutual_fund_aum_history` table).
- **V3 Master Funds admin dashboard** (2026-02-22): New 4th admin tab with Compact/Detailed/Dense view toggle, filters, row-expand showing per-component contribution tables, Excel export (5 sheets). Fixed ratios table-name typo so performance + risk_adjusted primitives now display correctly.
- **Groww+Tickertape bulk import** (2026-02-22): 185 unique MFs scored (168 via Groww, 14 via Tickertape fallback for SEBI-renamed funds).
- **Remove danger/warn flags → per-fund Exit/Switch recommendations** (2026-02-22): `derive_recommendation()` returns `{action: EXIT|SWITCH|REVIEW|HOLD|BUY}`. 40 tests passing.


### P1
- Close 4 minor V3 Excel spec gaps: `compute_hold_score()`, `type=HOLD` P2 actions, insight `severity` field, Groww `alpha_ratio` mapping.
- DPDP compliance: PAN AES-256 encryption, consent logging, audit trails.
- Fernet-encrypt secrets at rest.

### P2
- Phase B Asset Coverage: equity ETFs in overlap, FIFO lot-wise tax, debt/gold taxation.
- Goal-based planning module (Retirement, Child Education, AI-calculated SIPs).
- Admin dashboard tab split (Infrastructure / Data Management / User Management).
- Radix DialogContent a11y warnings (wrap titles with VisuallyHidden).
- Portfolio versioning (delta tracking).
- Historical-backtest CAGR model.

## Data Model Additions
- `db.system_config` — `{key: "secrets", ...}`, `{key: "feature_flags", ...}`, `{key: "rules_config", ...}`, `{key: "prompts", ...}`
- `db.saved_scenarios`, `db.pending_actions`, `db.scenario_simulations`, `db.action_plans`
- PG: `mutual_fund_nav_history`, `mutual_fund_aum_history`, `benchmark_master` (with `proxy_instrument_id`), `mutual_fund_metadata` (extended with V3 columns), `amfi_nav_fetch_log`, `nav_analytics_job_log`
