# nivesh.ai — Agentic Wealth System

> An AI-powered autonomous financial advisor for the Indian retail investor.
> Parses consolidated account statements (CAS), scores every mutual fund across
> 38 deterministic primitives, flags concentration/cost/quality risks, and
> generates an explainable, actionable Plan Board — all grounded in real market
> data with zero LLM-hallucinated numbers.

---

## 1. Product Overview

### 1.1 What it does
- **Portfolio ingestion** — parses CAMS/KFintech CAS PDFs and imports every
  mutual fund, demat MF, direct equity, bond, gold / SGB and liquid holding
  a user owns.
- **Deterministic V3 scoring engine** — computes Quality, Health, Exit, Add,
  Switch and Portfolio-Fit composite scores (0-100) for every fund based on
  38 primitives sourced from Groww + AMFI + computed NAV analytics.
- **Insight generation** — surfaces concentration (AMC, sector, category),
  cost leaks (Regular → Direct), fund overlap, and allocation gaps with
  plain-English explanations and exact ₹ / % citations.
- **Agentic plan board** — turns insights into a prioritised list of EXIT /
  SWITCH / ADD / HOLD actions governed by six business rules, scored with
  V3's Switch formula and gated by four Excel-specified guardrails.
- **Natural-language copilot** — chat interface grounded in the user's active
  plan so every recommendation is traceable back to deterministic engine
  output.
- **Admin console** — live-tunable rule thresholds, LLM prompts (with a
  sandbox), feature flags, infrastructure monitor, data-pipeline observability
  and user management.

### 1.2 Who it's for
Indian retail investors who have 5+ mutual funds, hold both Regular and Direct
plans, sometimes have double-digit AMC overlap, and want an honest engine —
not another feed of generic AI advice.

### 1.3 Non-goals (explicit)
- **No broker integration** — the app *recommends*; it does not place trades.
- **No guaranteed returns** — SEBI-compliant framing throughout.
- **No LLM in the analytics critical path** — LLM is used only for narrative
  / copilot; all numbers come from deterministic code.

---

## 2. High-level Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                           React frontend                               │
│  Dashboard · Plan Board (V2) · Insights · Copilot · Admin              │
│  Tailwind + Shadcn UI · Recharts · Motion                              │
└──────────────────────────┬─────────────────────────────────────────────┘
                           │ REACT_APP_BACKEND_URL
                           │ (cookie-based session)
┌──────────────────────────▼─────────────────────────────────────────────┐
│                        FastAPI backend                                 │
│  routes/           services/                   helpers/                │
│   portfolio        action_plan_manager          portfolio_utils        │
│   intelligence     v3_scoring / v3_integration  secrets / feature_flags│
│   insights         v3_explainer                                        │
│   plans            nav_analytics(_sweep)                               │
│   chat             portfolio_intelligence                              │
│   admin_*          pg_client / v3_score_cache                          │
│                    rules_config / prompts_manager                      │
│                    cas_api_client · fund_data_resolver · groww_client  │
│                    mf_scheduler (APScheduler)                          │
└──┬─────────────┬──────────────┬──────────────┬────────────────────────┘
   │             │              │              │
┌──▼──────┐ ┌────▼─────┐ ┌──────▼──────┐ ┌─────▼────────────────────┐
│ MongoDB │ │PostgreSQL│ │   Redis     │ │  External integrations   │
│ users,  │ │instrument│ │ V3 cache,   │ │ • casparser.in (CAS API) │
│ holdings│ │_master,  │ │ session     │ │ • AMFI NAV daily         │
│ plans,  │ │metadata, │ │ store       │ │ • Groww __NEXT_DATA__    │
│ insights│ │NAV hist, │ │             │ │ • OpenAI GPT-4o-mini via │
│ chat,   │ │benchmark,│ │             │ │   Emergent LLM key       │
│ configs │ │audit logs│ │             │ │ • Google OAuth, Gmail    │
└─────────┘ └──────────┘ └─────────────┘ └──────────────────────────┘
```

### 2.1 Why this storage split

| Store | Role | Why |
|---|---|---|
| **MongoDB** | User-scoped documents: holdings, action plans, insights, chat, config | Flexible schema (holdings shape differs per asset type); dynamic rules_config + prompts stored as JSON blobs. |
| **PostgreSQL** | Market-wide tabular data: `instrument_master`, `mutual_fund_metadata`, `mutual_fund_nav_history`, `mutual_fund_aum_history`, `benchmark_master`, `mutual_fund_holdings` (per-fund top-10), `mutual_fund_performance_ratios`, audit logs | Window functions (`LAG`, `ROWS BETWEEN`) make rolling NAV returns / drawdowns trivial; 25k+ NAV rows scale cleanly with btree index. |
| **Redis** | V3 composite score cache (24h TTL), session cache | Sub-ms lookups for the Insights + Plan Board hot path. |

---

## 3. V3 Scoring Engine (the heart of the product)

All six composite scores are **pure, deterministic, weight-redistributing**
functions. If a primitive is missing for a fund, its weight is proportionally
redistributed across the remaining components so the composite always sums to
100% and `missing_primitives[]` is returned for UI confidence badging.

### 3.1 Primitives (38, sourced + derived)

| # | Primitive | Source | Notes |
|---|---|---|---|
| 1-3 | `ret_1y / ret_3y / ret_5y` | Groww | Per-plan trailing returns |
| 4-6 | `category_avg_1y / 3y / 5y` | Groww | For excess-return calc |
| 7-9 | `rank_within_category_1y / 3y / 5y` | Groww | Peer ranking |
| 10-11 | `sharpe`, `sortino` | Groww | Risk-adjusted |
| 12 | `alpha` | Groww | ⚠ mapping key gap — returns 0 for some funds |
| 13 | `beta`, `std_dev` | Groww | Volatility |
| 14 | `expense_ratio_direct` | Groww (sibling fetch) | |
| 15 | `expense_ratio_regular` | Groww (sibling fetch) | |
| 16 | `expense_trend_delta` | Groww `historic_fund_expense` (36 months) | Δ vs 3y-ago |
| 17 | `turnover_ratio` | Groww | Bell curve peak 60% |
| 18 | `top10_concentration_pct` | Groww | Σ pct across top-10 holdings |
| 19 | `manager_tenure_years` | Groww `fund_manager_details` | Longest-tenured |
| 20 | `aum_cr` | Groww | |
| 21 | `fund_age_years` | Groww `allotment_date` | |
| 22 | `max_drawdown_pct` | ✅ computed from NAV history | Peak-to-trough |
| 23 | `consistency_score` | ✅ computed from NAV history | Fraction of rolling 12m windows beating cat avg |
| 24 | `downside_capture_pct` | ✅ computed vs benchmark proxy | Monthly returns ratio in down months |
| 25 | `aum_trend_score` | ✅ computed from AUM snapshots | OLS slope of ln(AUM) |
| 26-27 | `overlap_pct`, `avg_overlap_pct_with_portfolio` | computed from `mutual_fund_holdings` | Stock-level Σ min(w_a, w_b) |
| 28 | `sector_exposure` | enriched via `equity_sectors.py` | Drill-through to underlying stocks |
| 29-30 | `tax_liability_rs`, `tax_benefit_rs` | computed by `tax_calculator.py` | ClearTax FY25-26 rules |
| 31-32 | `holding_age_months`, `buy_date` | parsed from CAS transactions | |
| 33-34 | `portfolio_fit_score`, `gap_fit_0_10` | portfolio-level aggregation | Diversification / asset alloc |
| 35 | `amc_concentration_pct` | MF-only AMC value / MF corpus | |
| 36 | `category_concentration_pct` | MF-only category value / MF corpus | |
| 37 | `asset_alloc_fit_0_10` | vs risk-profile target | |
| 38 | `confidence_score` | data-completeness heuristic | feeds Guardrail #4 |

### 3.2 Composite scores

| Score | Excel weights | Formula (see `services/v3_scoring.py`) |
|---|---|---|
| **Quality** | Performance 25 + Risk-Adj 20 + Consistency 20 + Drawdown 15 + Cost 10 + AUM/Age 10 | `_weighted_composite({...})` |
| **Health** | Manager 25 + AUM-Stab 20 + Turnover 15 + Concentration 15 + Downside 15 + Expense-Trend 10 | same |
| **Exit** | Overlap 25 + Tax 25 + Quality-inverse 25 + Cost 15 + Portfolio-Fit 10 | ctx-driven |
| **Add** | Gap-Fit 30 + Low-Overlap 25 + Quality 20 + Need 15 + Cost 10 | ctx-driven |
| **Portfolio-Fit** | Diversification 25 + Overlap 25 + AMC 20 + Cost 15 + Asset-Alloc 15 | portfolio-level |
| **Switch** | *(not weighted — formula)* | `(Q_new − Q_old) + Overlap_reduction + Cost_saving/₹10K − Tax_cost/₹10K`; `recommended=True` iff ≥ 2.0 |

### 3.3 Guardrails

| # | Guardrail | Behaviour |
|---|---|---|
| 1 | **High-Quality Protection** | Q≥75 AND H≥70 → block EXIT, unless overlap > 80% (override) |
| 2 | **Tax-Exceeds-Benefit** | `tax_liability > annual_benefit` → block EXIT |
| 3 | **Recent-Investment Lockout** | holding age < 6 months → block EXIT |
| 4 | **Low-Confidence** | `confidence_score < 50` → reduce action count (flag, not block) |

### 3.4 Explainability (NEW — Feb 2026)

`services/v3_explainer.py` converts any V3 bundle into:
1. **Danger classification** — `{level: critical|warning|ok, reasons: [...]}` using concrete thresholds (Q<40, H<40, Exit≥75 = critical; Q<55, H<55, Exit≥60, Switch≥2.0 = warning).
2. **Deterministic explanation** — a plain-English paragraph citing the weakest Quality + Health components with primitive values (AUM, manager tenure, drawdown %, turnover %, top-10 concentration %, downside capture %).

**Example output for Sundaram Value Regular (live):**
> "**Below par** — Quality 37/100, Health 62/100. Drags: Small/young fund (AUM ₹1,212Cr) — maturity score 1.6/10; Risk-adjusted returns sub-par — Sharpe+Sortino combined score 2.3/10."

---

## 4. Action Plan Rule Engine (V2.5 + V3-gated)

Six priority-ordered rules fire in `services/action_plan_manager._apply_action_rules`. Every rule accepts a `rules_config` override so thresholds are live-tunable from the Admin UI.

| # | Rule | Trigger | Action |
|---|---|---|---|
| 1 | **Regular → Direct consolidation** | Same fund held in both plans | `EXIT` Regular |
| 2 | **AMC concentration** | Single AMC > 15% (configurable) | `EXIT` highest `exit_score` funds from that AMC until under threshold |
| 2b | **Category concentration** | Single SEBI category > 35% | Same, scoped by category; `_infer_category_from_name` handles unresolved funds |
| 3 | **Underperformer replacement** | Quality ≥6.5 AND ret_1y<8% AND ret_3y<10% | `EXIT` + `ADD` highest `add_score` replacement in *same category* |
| 4 | **Different-fund overlap** | Stock-level overlap > 60% on two distinct funds | `EXIT` fund with higher `exit_score` (only when `proxy_switch_score > 0`) |
| 5 | **Debt-allocation gap** | Debt < risk-profile floor (low=30% / mid=20% / high=10%) | `ADD` debt fund, amount = gap; skips over-concentrated AMCs |
| 6 | **Regular→Direct cost leak** | Annual leak > ₹10K AND V3 `switch_score ≥ 1.0` | `SWITCH` action with exact ₹ saving + tax impact |
| 7 | **Do-Nothing** | `portfolio_score ≥ 75` AND no high-priority actions | Synthetic `HOLD` with reason `PORTFOLIO_HEALTHY` |

Each action is stamped with `v3_scores = {quality, health, exit, add}` + `switch_score` for UI transparency and audit.

---

## 5. Key Flows

### 5.1 Onboarding + CAS ingest
```
User signs in (Google OAuth, Emergent-managed)
    ↓
Uploads CAS PDF (CAMS / KFintech / Mixed)
    ↓
routes/portfolio:POST /api/portfolio/cas-upload
    ↓
cas_api_client.parse_cas_pdf()  ──→ casparser.in API
    ↓
_extract_buy_date_from_transactions() per scheme
    ↓
_holding_from_*() builders classify asset_type (mutual_fund / equity / bond / gold / etf)
    ↓
MongoDB.holdings.insert_many()
    ↓
Background: fund_data_resolver.resolve_portfolio() kicks off Groww scrape + sibling fetch
    ↓
Dashboard renders
```

### 5.2 Insight generation
```
GET /api/intelligence/portfolio
    ↓
compute_portfolio_intelligence(user_id)
    ↓  (reads MongoDB holdings + PG mutual_fund_metadata + mutual_fund_holdings)
returns {mf_investments, pairwise_overlap, compression_score, redundancy_suggestions,
         asset_allocation{equity/debt/gold/other}, amc_exposure, category_breakdown,
         total_value, degraded: bool}
    ↓
POST /api/insights/generate
    ↓  (deterministic — NO LLM)
_deterministic_insights(holdings, deep_analytics, allocation_data, rules_config, intelligence)
    ↓
MongoDB.ai_insights.insert_many()   +   MongoDB.portfolio_analysis.insert_one()
```

### 5.3 V3 per-fund breakdown (Insights UI)
```
GET /api/insights/v3-portfolio
    ↓
v3_integration.enrich_candidates_with_v3()
    ↓  batch PG read of 24 primitive columns for every holding
compute_quality + compute_health + compute_exit + compute_add per fund
    ↓
v3_explainer.classify_danger(bundle) + build_explanation(bundle)
    ↓
Returns funds[] sorted critical → warning → ok → descending quality
```

### 5.4 Plan generation
```
POST /api/plans/generate
    ↓
ActionPlanManager.generate_plan(user_id)
    ├─ compute_portfolio_intelligence() → PG enrichment
    ├─ enrich_candidates_with_v3()       → V3 composite scores + guardrails
    ├─ _apply_action_rules()             → 6 rules, priority-ordered
    ├─ _apply_custom_rules()             → admin-defined rules via safe AST DSL
    ├─ _compute_portfolio_score()        → 5-component 0-100
    └─ _compute_confidence_score()       → data-completeness
    ↓
MongoDB.action_plans.insert_one(status=preview)
    ↓
User hits "Save" → POST /api/plans/{id}/save → status=active
    ↓
Plan Board renders with V2 hero card + V3 score badges
```

### 5.5 Nightly data-pipeline (APScheduler `Asia/Kolkata`)

| Time IST | Job | What it does |
|---|---|---|
| 02:00–05:00 | `drain_weekday` | Drains any queued fund-scrape tasks |
| 22:00 | `amfi_navs_daily` | Fetches 14k EOD NAVs, upserts to `mutual_fund_nav_history` |
| 22:30 | `analytics_sweep_daily` | Recomputes `max_drawdown / consistency / downside_capture / aum_trend` for every fund with ≥180 days of NAV history (parallel, `asyncio.gather` with semaphore) |
| 22:45 | `v3_rescore_daily` | Recomputes Quality + Health composites → writes to PG + Redis cache |
| Wed 03:00 | `stale_refresh` | Refreshes stale Groww metadata |

Each job writes an audit row to `nav_analytics_job_log (status, processed, failed, duration_ms, error_msg)` for the Admin Data Pipeline monitor.

---

## 6. API surface

### 6.1 User-facing

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/auth/me` | Current session |
| `POST` | `/api/auth/google` | Google OAuth sign-in |
| `POST` | `/api/portfolio/cas-upload` | CAS PDF upload |
| `GET` | `/api/portfolio/holdings` | All holdings with live prices |
| `PUT` | `/api/portfolio/holdings/{id}` | Edit holding (incl. `buy_date`) |
| `GET` | `/api/intelligence/portfolio` | Full portfolio intelligence |
| `POST` | `/api/insights/generate` | Deterministic insights |
| `GET` | `/api/insights/v3-portfolio` | Per-fund V3 scores + danger + explanation |
| `GET` | `/api/intelligence/v3-score/{instrument_id}` | Single-fund V3 detail |
| `POST` | `/api/plans/generate` | Generate preview plan |
| `POST` | `/api/plans/{id}/save` | Activate plan |
| `GET` | `/api/plans/active` | Current active plan |
| `PATCH` | `/api/plans/{id}/actions/{aid}/status` | Mark action done / skipped |
| `POST` | `/api/plans/{id}/actions/{aid}/feedback` | Thumbs up / down |
| `POST` | `/api/chat` | Copilot chat (grounded on active plan) |
| `POST` | `/api/scenarios/simulate` | What-if remove-fund simulator |

### 6.2 Admin-only

| Path | Purpose |
|---|---|
| `/api/admin/secrets` | CRUD on registered secrets |
| `/api/admin/feature-flags` | Per-flag mode + allowlist |
| `/api/admin/rules-config` | V2 rule thresholds (live) |
| `/api/admin/rules-config/custom` | Admin-defined rules (safe AST DSL) |
| `/api/admin/prompts` | 7 LLM prompts + sandbox test |
| `/api/admin/data-pipeline/status` | Scheduler + Redis cache observability |
| `/api/admin/data-pipeline/trigger/{job}` | On-demand job trigger |
| `/api/admin/cache/invalidate` | Drop all V3 cache keys |

---

## 7. Frontend structure

```
src/components/
├── Dashboard.js                     Top-level shell
├── Sidebar.js                       Dashboard · Plan Board · Portfolio · Insights
├── DashboardOverview.js             Portfolio Health · Risk · Recommendations
├── PortfolioView.js                 Holdings table with editable Buy Date
├── InsightsView.js                  AI Overview · Performance · Fund Overlap tabs
├── AdminView.js                     Secrets · Flags · Rules · Prompts · Data Pipeline
├── v2/
│   ├── PlanBoardView.js             Grid of plans
│   ├── PlanCard.js                  Single plan: header, actions, status
│   ├── PlanHeroCard.js              Big donut + confidence + improvements delta pills
│   └── V3ScoreBadges.js             Q/H/E/A pill cluster on PlanCard actions
├── insights/
│   ├── PortfolioIntelligenceTab.jsx Fund Overlap layout (drag-to-resize)
│   ├── V3PortfolioInsights.jsx      Headline tiles + Leaderboard + Danger-zone tile
│   └── V3FundBreakdown.jsx          Per-fund expandable row with Q/H/E/A/SW pills + explanation
├── copilot/                         Nivesh Copilot drawer · chat · scenario cards
└── admin/
    ├── SecretsSection.jsx · FeatureFlagsSection.jsx
    ├── RulesConfigSection.jsx · PromptsSection.jsx
    └── DataPipelineMonitor.jsx      3 job tiles · scheduler · Redis · recent runs
```

- Every interactive / info element carries a `data-testid`.
- All components are dark-mode-safe via Tailwind `dark:` prefixes.

---

## 8. Data model (abridged)

### 8.1 MongoDB
```
users               {user_id, email, google_sub, is_admin, risk_profile, created_at}
user_sessions       {session_token, user_id, expires_at}
holdings            {holding_id, user_id, name, quantity, buy_price, current_price,
                     asset_type, sector, category, buy_date, instrument_id?, transactions[]}
action_plans        {plan_id, user_id, status, engine_version, actions[],
                     portfolio_score, confidence_score, plan_summary, improvements,
                     created_at, saved_at, archived_at}
ai_insights         {insight_id, user_id, title, description, type, category,
                     impact, effort, current_value, target_value, affected_funds[], action}
portfolio_analysis  {user_id, analysis: {insights[], problem_distribution, risk_gauge,
                     cost_leakage, action_funnel, before_after}}
chat_sessions       {session_id, user_id, messages[], active_plan_context}
system_config       {key: "secrets|feature_flags|rules_config|prompts", values: {...}}
```

### 8.2 PostgreSQL (nivesh DB)
```sql
instrument_master (instrument_id UUID PK, instrument_type, instrument_name, isin, scheme_code)
mutual_fund_metadata (instrument_id FK, aum_cr, fund_age_years, manager_tenure_years,
                      expense_ratio_direct/regular, expense_trend_delta, turnover_ratio,
                      top10_concentration_pct, category_avg_1y/3y/5y,
                      max_drawdown_pct, consistency_score, downside_capture_pct,
                      aum_trend_score, quality_score, health_score, v3_scored_at, ...)
mutual_fund_holdings (instrument_id, stock_slug, stock_name, weight_pct, sector)
mutual_fund_performance_ratios (instrument_id, ratios_date, ret_1y/3y/5y,
                                sharpe, sortino, alpha, beta, std_dev)
mutual_fund_nav_history (instrument_id, nav_date, nav, source) — 33k+ rows
mutual_fund_aum_history (instrument_id, snapshot_date, aum_cr)
benchmark_master (category PK, benchmark_name, benchmark_symbol, proxy_instrument_id FK)
amfi_nav_fetch_log (run_at, rows_parsed, rows_upserted, status, error_msg)
nav_analytics_job_log (job_name, started_at, processed, failed, duration_ms, error_msg)
```

### 8.3 Redis
```
v3:score:{instrument_id}   →   JSON bundle, TTL 24h
```

---

## 9. Testing

- **Backend**: `pytest` — 103+ tests across
  `test_v3_scoring.py` (38), `test_v3_explainer.py` (13), `test_action_rules.py` (17),
  `test_deterministic_insights.py` (5), `test_rules_admin.py` (17), `test_groww_v3_primitives.py` (15),
  `test_v3_fund_breakdown_api.py` (12), `test_portfolio_intelligence.py`, …
- **Every rule** has positive AND negative regression tests (e.g. "AMC at exactly 15%
  fires Rule 2", "high-quality fund is protected from EXIT unless overlap > 80%").
- **Frontend**: Playwright end-to-end via the platform's testing agent.
- **Lint**: `ruff` (Python), ESLint with `react-hooks/exhaustive-deps` + `react/no-array-index-key`.

---

## 10. Environment & Operations

### 10.1 Backend `.env` (protected)
```
MONGO_URL=mongodb://localhost:27017
DB_NAME=test_database
```
All other secrets (`POSTGRES_URL`, `REDIS_URL`, `CASPARSER_API_KEY`, `EMERGENT_LLM_KEY`,
`GOOGLE_CLIENT_ID`, `GMAIL_OAUTH_CLIENT_ID`, …) live in `db.system_config.secrets`
and are hydrated at startup.

### 10.2 Frontend `.env` (protected)
```
REACT_APP_BACKEND_URL=https://nidp-backfill-ui.preview.emergentagent.com
```

### 10.3 Supervisor services
```
backend           uvicorn on :8001
frontend          CRA dev server on :3000
mongodb
postgres          nivesh DB
redis
```

### 10.4 Degradation behaviour
Both Postgres and Redis are *optional*. When either is unreachable:
- `pg_client.get_pool()` returns `None`; `portfolio_intelligence` returns `{degraded: true, degraded_reason: "..."}` and the UI shows a **"Postgres not configured — upload CAS to unlock"** tile.
- Only Rule 5 (debt gap) still fires in the action plan.
- `v3_score_cache` falls back to the `mutual_fund_metadata.quality_score/health_score`
  columns in PG (so even without Redis, V3 scores survive a cache wipe).
- Admin can re-hydrate `POSTGRES_URL` / `REDIS_URL` via the Secrets UI without restart.

### 10.5 DPDP / compliance (in-progress)
- SEBI-compliant framing in every copilot prompt and action reason.
- PAN is stored plain today — **AES-256 encryption is on P1 backlog**.
- Consent log + audit trail scaffolding exists; formal compliance module is P1.
- Zero PII leaves the container.

---

## 11. Third-party integrations

| Service | Purpose | Credentials |
|---|---|---|
| **casparser.in** | CAS PDF parsing | `CASPARSER_API_KEY` (admin secret) |
| **AMFI NAV** | Daily EOD NAV dump (`NAVAll.txt`) | None — public HTTP |
| **Groww** (scrape) | `__NEXT_DATA__` extraction for 17 fund primitives + sibling plan | None — public web |
| **Google OAuth** | Sign-in | `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` |
| **Gmail API** | Mail-based CAS import (optional) | `GMAIL_OAUTH_CLIENT_ID` |
| **OpenAI GPT-4o-mini** | Copilot narrative + category rating reason | Emergent LLM key (via `emergentintegrations`) |

No third-party SDK touches the scoring / insight critical path — all analytics are local, deterministic, and reproducible.

---

## 12. Engine versioning

```
V1    — static category/sector proxies, LLM-generated insights (deprecated)
V2    — rule engine with 6 priority rules, tax engine, hero card
V2.5  — scoring primitives (quality v2, switch formula v1, guardrails)
V3    — 38 primitives, 5 composite scores + switch + 4 guardrails (current)
V3.1  — (P1) hold_score output, HOLD action type, insight severity, alpha mapping fix
```

Every plan document stamps `engine_version` so downstream tooling can
backfill older plans when the engine is upgraded.

---

## 13. Coding conventions

- **Python**: FastAPI + async everywhere; Pydantic response models; `datetime.now(timezone.utc)` (never `utcnow`); always `.find({}, {"_id": 0})` when projecting Mongo docs to avoid ObjectId JSON errors; `asyncpg` pooled (default 10 connections).
- **React**: functional components, Shadcn UI, Tailwind `dark:` prefixes, named exports for components + default for pages, `data-testid` on every interactive element.
- **Testing**: pytest pure-logic first (no DB/network); integration tests guarded by env-overridable admin + user tokens.
- **Refactors**: avoid massive `search_replace` on `action_plan_manager.py` (2.4k lines) — use surgical edits to prevent indentation regressions.
