# Functional Requirements Document — NIVESH V2 BACKEND
**Layer:** Nivesh V2 Backend (Analytics & Decision Engine Layer)
**Status:** VALIDATED AGAINST CODE — May 2026
**Validation Source:** `services/v3_scoring.py`, `services/v3_integration.py`, `services/action_plan_manager.py`, `services/instrument_scoring.py`, `services/portfolio_intelligence.py`, `services/portfolio_health.py`, `services/portfolio_enrichment.py`, `services/tax_calculator.py`, `backend/tests/test_v3_*.py`, `backend/tests/test_action_rules.py`

---

## DOCUMENT NOTES — What "V2 Backend" Means

> **V2 Backend = the decision and analytics engine layer.** It layers on top of V1 (base platform). Specifically:
> - **V2.5 Action Plan Engine** — 6 priority-ordered rules + 4 guardrails + tax engine. Engine version constant: `"v2.5"` (in `action_plan_manager.py:380`)
> - **V3 Scoring Engine** — 38 primitives across 5 composite scores. Engine version constants: `"v3.0-phase1"` (scoring) and `"v3.0-phase2"` (integration)
> - **Portfolio Intelligence** — stock-level look-through, overlap, concentration
> - **Portfolio Health Scoring** — 0-100 composite health score
> - **Switch Cost Framework** — cost/tax/alpha math for every exit/switch recommendation
>
> V3 is NOT a replacement for V2.5 — it is an additive enrichment layer: funds without V3 primitives fall back to V2.5 heuristics. Both run in the same pipeline.

---

## 1. Module: V3 Scoring Engine (38 Primitives)

### FR-V3-001 — Quality Score Composite
| Field | Value |
|---|---|
| **Requirement ID** | FR-V3-001 |
| **Module** | V3 Scoring Engine |
| **Feature** | Fund Quality Score |
| **Priority** | Critical |
| **Source** | `services/v3_scoring.py` (ENGINE_VERSION = "v3.0-phase1") |
| **Status** | Live — nightly refresh |
| **Test File** | `backend/tests/test_v3_scoring.py` (38 tests) |

**Description:** Composite score (0–100) answering "Is this a good fund?"

**Inputs (weighted primitives):**
| Component | Weight | Primitives Used |
|---|---|---|
| Performance | 25% | ret_1y, ret_3y, ret_5y, category_avg_1y/3y/5y |
| Risk-Adjusted | 20% | sharpe_ratio, sortino_ratio, alpha |
| Consistency | 20% | consistency_score (% of 12-month windows beating category avg) |
| Drawdown | 15% | max_drawdown_pct |
| Cost | 10% | expense_ratio_direct vs category median |
| AUM/Age | 10% | aum_cr, fund_age_years, aum_trend_score |

**Weight Redistribution Rule:** If a primitive is missing, its weight is proportionally redistributed to available primitives in the same component. Score always sums to 100%; `missing_primitives[]` returned for UI confidence badging.

**Formula:** `_weighted_composite({component: (value, weight), ...})` in `v3_scoring.py`

**Acceptance Criteria:**
- Fund with all 38 primitives → score in [0,100], no missing_primitives
- Fund with no 5yr return (young fund) → weight redistributed to 1yr/3yr, score still computed
- Same input always produces same output (deterministic, no randomness)
- Score persisted to `mutual_fund_metadata.quality_score` + Redis cache `v3:score:{instrument_id}` (24h TTL)

---

### FR-V3-002 — Health Score Composite
| Field | Value |
|---|---|
| **Requirement ID** | FR-V3-002 |
| **Module** | V3 Scoring Engine |
| **Feature** | Fund Health Score |
| **Priority** | Critical |
| **Source** | `services/v3_scoring.py` |
| **Status** | Live |
| **Test File** | `backend/tests/test_v3_scoring.py` |

**Description:** Composite score (0–100) answering "Is it stable and improving?"

**Inputs (weighted primitives):**
| Component | Weight | Primitives Used |
|---|---|---|
| Manager Tenure | 25% | manager_tenure_years (longest-tenured manager) |
| AUM Stability | 20% | aum_trend_score (OLS slope of ln(AUM) over 24 months) |
| Turnover | 15% | turnover_ratio (bell curve peak ~60%; above or below = worse) |
| Concentration | 15% | top10_concentration_pct |
| Downside Capture | 15% | downside_capture_pct (lower = better) |
| Expense Trend | 10% | expense_trend_delta (vs 3yr ago) |

---

### FR-V3-003 — Exit Score Composite
| Field | Value |
|---|---|
| **Requirement ID** | FR-V3-003 |
| **Module** | V3 Scoring Engine |
| **Feature** | Fund Exit Score |
| **Priority** | Critical |
| **Source** | `services/v3_scoring.py` |
| **Status** | Live |
| **Test File** | `backend/tests/test_v3_scoring.py` |

**Description:** Composite score (0–100) answering "Should I exit this fund?" Higher = stronger exit signal.

**Inputs (context-driven):**
| Component | Weight | Primitives Used |
|---|---|---|
| Overlap | 25% | avg_overlap_pct_with_portfolio |
| Tax | 25% | tax_liability_rs (from tax engine) |
| Quality-inverse | 25% | (100 - quality_score) |
| Cost | 15% | expense_ratio_regular vs expense_ratio_direct |
| Portfolio-Fit | 10% | portfolio_fit_score |

---

### FR-V3-004 — Add Score Composite
| Field | Value |
|---|---|
| **Requirement ID** | FR-V3-004 |
| **Module** | V3 Scoring Engine |
| **Feature** | Fund Add Score |
| **Priority** | High |
| **Source** | `services/v3_scoring.py` |
| **Status** | Live |
| **Test File** | `backend/tests/test_v3_scoring.py` |

**Description:** Composite score (0–100) answering "Should I add to or buy this fund?"

**Inputs:**
| Component | Weight | Primitives Used |
|---|---|---|
| Gap-Fit | 30% | gap_fit (fills allocation gap) |
| Low-Overlap | 25% | 100 - avg_overlap_pct_with_portfolio |
| Quality | 20% | quality_score |
| Need | 15% | asset_alloc_fit (moves allocation closer to target) |
| Cost | 10% | expense_ratio_direct |

---

### FR-V3-005 — Portfolio-Fit Score Composite
| Field | Value |
|---|---|
| **Requirement ID** | FR-V3-005 |
| **Module** | V3 Scoring Engine |
| **Feature** | Portfolio-Level Fit |
| **Priority** | High |
| **Source** | `services/v3_scoring.py` |
| **Status** | Live |

**Inputs:**
| Component | Weight |
|---|---|
| Diversification | 25% |
| Overlap | 25% |
| AMC Concentration | 20% |
| Cost | 15% |
| Asset-Allocation Fit | 15% |

---

### FR-V3-006 — Switch Score Formula
| Field | Value |
|---|---|
| **Requirement ID** | FR-V3-006 |
| **Module** | V3 Scoring Engine |
| **Feature** | Switch Decision Score |
| **Priority** | Critical |
| **Source** | `services/v3_scoring.py`, `services/v3_integration.py` |
| **Status** | Live |
| **Test File** | `backend/tests/test_v3_scoring.py` |

**Formula:**
```
switch_score = (Quality_candidate − Quality_current)
             + overlap_reduction_pts
             + (annual_cost_saving_rs / 10,000)
             − (tax_cost_rs / 10,000)
```

**Decision Rule:** `recommended = True` if and only if `switch_score ≥ 2.0`

**Acceptance Criteria:**
- switch_score = (80-60) + 5 + (15000/10000) - (20000/10000) = 20 + 5 + 1.5 - 2 = 24.5 → recommend
- switch_score = (55-60) + 0 + 0.5 - 3 = -7.5 → do NOT recommend
- Fund with switch_score < 2.0 must NOT appear as SWITCH action in plan

---

### FR-V3-007 — Danger Classification
| Field | Value |
|---|---|
| **Requirement ID** | FR-V3-007 |
| **Module** | V3 Scoring Engine |
| **Feature** | Danger Level Labels |
| **Priority** | High |
| **Source** | `services/v3_explainer.py` |
| **Status** | Live |
| **Test File** | `backend/tests/test_v3_explainer.py` (13 tests) |

**Classification Bands:**
| Level | Quality/Health Condition | Exit Condition |
|---|---|---|
| CRITICAL | Q < 40 OR H < 40 | Exit ≥ 75 |
| WARNING | 40 ≤ Q < 55 OR 40 ≤ H < 55 | 55 ≤ Exit < 75 OR switch_score ≥ 2.0 |
| OK | Q ≥ 65 AND H ≥ 65 | Exit < 55 |

**Plain-English Explanation Output (deterministic):**
Cites exact primitive values: "Quality 37/100, Health 62/100. Drags: Small/young fund (AUM ₹1,212Cr) — maturity score 1.6/10; Risk-adjusted returns sub-par — Sharpe+Sortino combined score 2.3/10."

**Acceptance Criteria:**
- Q=37, H=62 → CRITICAL (Q<40 condition)
- Q=50, H=50 → WARNING (both in 40-55 range)
- Q=72, H=75, Exit=40 → OK
- Explanation always cites numeric values, never generic text

---

### FR-V3-008 — 38 Primitive Data Sources
| Field | Value |
|---|---|
| **Requirement ID** | FR-V3-008 |
| **Module** | V3 Scoring Engine |
| **Feature** | Primitive Data Sourcing |
| **Priority** | Critical |
| **Source** | `services/v3_integration.py`, PostgreSQL `mutual_fund_metadata` |
| **Status** | Live |

**Data Sources:**
| Category | Primitives | Source |
|---|---|---|
| Returns & Risk-Adjusted (#1–13) | ret_1y/3y/5y, category_avg, rank, sharpe, sortino, alpha, beta, std_dev, information_ratio, treynor | Groww scrape / NAV history |
| Cost (#14–16) | expense_ratio_direct, expense_ratio_regular, expense_trend_delta | Groww scrape |
| Activity & Concentration (#17–18) | turnover_ratio, top10_concentration_pct | Groww scrape |
| Fund Health (#19–21) | manager_tenure_years, aum_cr, fund_age_years | Groww scrape / AMFI |
| NAV-Derived (#22–25) | max_drawdown_pct, consistency_score, downside_capture_pct, aum_trend_score | Computed nightly from NAV history |
| Portfolio Context (#26–38) | overlap_pct, tax_liability_rs, holding_age_months, portfolio_fit_score, gap_fit, amc_concentration_pct, category_concentration_pct, asset_alloc_fit, confidence_score, buy_date | Computed per-user per-portfolio |

**Known Gap (P1 Backlog):** `alpha` primitive returns 0 for some funds due to Groww scraper field mapping issue. Fallback to benchmark-proxy computed alpha is planned.

---

## 2. Module: NAV Analytics (Nightly Computation)

### FR-V3-009 — NAV Analytics Sweep
| Field | Value |
|---|---|
| **Requirement ID** | FR-V3-009 |
| **Module** | NAV Analytics |
| **Feature** | Nightly Derived Primitive Computation |
| **Priority** | Critical |
| **Source** | `services/nav_analytics.py`, `services/nav_analytics_sweep.py` |
| **Status** | Live |
| **Schedule** | Daily 22:30 IST |

**Computed Primitives:**

**max_drawdown_pct:**
- Peak-to-trough maximum decline in full NAV history
- Formula: `max((peak_nav - trough_nav) / peak_nav)` over all time

**consistency_score:**
- Fraction of rolling 12-month windows where fund beat its category average return
- Requires ≥ 180 days of NAV history to compute

**downside_capture_pct:**
- Fund monthly return ÷ benchmark proxy monthly return, in months where benchmark fell
- Values < 100% = fund falls less than market in down months (good)

**aum_trend_score:**
- OLS (ordinary least squares) slope of ln(AUM) over trailing 24 months
- Positive slope = growing AUM = sign of investor confidence

**Processing:** `asyncio.gather` with semaphore for parallel processing per fund. Audit record written to `nav_analytics_job_log`.

---

## 3. Module: Action Plan Engine (V2.5 Rules)

### FR-PLAN-001 — Generate Action Plan
| Field | Value |
|---|---|
| **Requirement ID** | FR-PLAN-001 |
| **Module** | Action Plan |
| **Feature** | Plan Generation |
| **Priority** | Critical |
| **Source** | `services/action_plan_manager.py` (ENGINE_VERSION = "v2.5") |
| **Status** | Live |
| **Test File** | `backend/tests/test_action_rules.py` (17 tests) |

**API:** `POST /api/plans/generate`

**Processing Pipeline:**
1. `compute_portfolio_intelligence(user_id)` — pull holdings + resolve against PG metadata
2. `enrich_candidates_with_v3()` — batch-load 24 primitive columns, compute 5 composites + guardrails
3. `_apply_action_rules()` — fire 6 rules in priority order
4. `_apply_custom_rules()` — admin-defined rules via safe AST DSL
5. `_compute_portfolio_score()` — 5-component portfolio-level 0-100 score
6. `_compute_confidence_score()` — data completeness heuristic
7. Insert plan document to MongoDB with `status = "preview"`

**Critical Dependency:** PostgreSQL MUST be reachable. If `pg_client.get_pool()` returns None → portfolio intelligence is empty → Rules 1/2/3/4/6 short-circuit → ONLY Rule 5 fires. Response carries `degraded: true, degraded_reason: "..."`.

---

### FR-PLAN-002 — Rule 1: Regular → Direct Consolidation
| Field | Value |
|---|---|
| **Requirement ID** | FR-PLAN-002 |
| **Module** | Action Plan |
| **Feature** | Regular/Direct Deduplication |
| **Priority** | Critical (P0) |
| **Source** | `action_plan_manager._apply_action_rules()`, Rule 1 |
| **Status** | Live |

**Trigger:** User holds both Regular AND Direct variants of the same AMC scheme (detected by `_normalize_base_scheme_name()` which strips "Direct/Regular/Growth/IDCW" suffixes)

**Action Generated:** `EXIT` the Regular plan

**Reason Code:** `REGULAR_DIRECT_DUPLICATE`

**Calculations:** Amount = full Regular plan holding value. Tax = LTCG/STCG on unrealized gain.

**Business Rules:**
- Always applied first (P0) — always a net win for user
- Savings: expense ratio delta × fund value per year
- Tax cost: one-time LTCG/STCG on redemption

**Acceptance Criteria:**
- User has HDFC Flexi Cap Regular + HDFC Flexi Cap Direct → EXIT action for Regular generated
- EXIT score includes expense ratio differential as primary driver
- Tax impact calculated and shown on action card
- Already-exited funds (from Rule 1) are skipped by subsequent rules

---

### FR-PLAN-003 — Rule 2: AMC Concentration
| Field | Value |
|---|---|
| **Requirement ID** | FR-PLAN-003 |
| **Module** | Action Plan |
| **Feature** | AMC Over-Concentration Reduction |
| **Priority** | Critical (P0) |
| **Source** | `action_plan_manager._apply_action_rules()`, Rule 2 |
| **Status** | Live |
| **Test Coverage** | `test_action_rules.py` — "AMC at exactly 15% fires Rule 2" |

**Trigger:** Single AMC controls > 15% of total MF portfolio AUM (threshold configurable via admin UI)

**Algorithm:**
1. Compute `amc_exposure = Σ(mf_investment.amount_rs) grouped by amc_name ÷ total_mf_value`
2. For each AMC above threshold: rank its funds by exit_score DESC
3. EXIT funds from top-down until AMC exposure ≤ 15%

**Action Generated:** `EXIT` highest exit_score fund(s) from over-concentrated AMC

**Reason Code:** `AMC_CONCENTRATION_EXIT`

**Business Rules:**
- MF-only calculation (excludes stocks/ETFs by design)
- Skips funds already in EXIT queue from Rule 1
- Configurable threshold: default 15% (admin-tunable, no deploy required)

---

### FR-PLAN-004 — Rule 2b: Category Concentration
| Field | Value |
|---|---|
| **Requirement ID** | FR-PLAN-004 |
| **Module** | Action Plan |
| **Feature** | SEBI Category Over-Concentration |
| **Priority** | High (P0) |
| **Source** | `action_plan_manager._apply_action_rules()`, Rule 2b |
| **Status** | Live |

**Trigger:** Single SEBI MF category > 35% of MF portfolio AUM (configurable)

**Algorithm:** Same as Rule 2 but scoped by category. `_infer_category_from_name()` handles funds where category is not in metadata.

---

### FR-PLAN-005 — Rule 3: Underperformer Replacement
| Field | Value |
|---|---|
| **Requirement ID** | FR-PLAN-005 |
| **Module** | Action Plan |
| **Feature** | Underperformer Detection & Replacement |
| **Priority** | High (P1) |
| **Source** | `action_plan_manager._apply_action_rules()`, Rule 3 |
| **Status** | Live |

**Trigger:** Fund meets ALL of:
- `quality_score < 5.0` (V2.5 scale) OR V3 Quality < 6.5 / 10
- `ret_1y < 8%`
- `ret_3y < 10%`

**Algorithm:**
1. Find all underperforming funds
2. For each: find best same-SEBI-category fund by add_score NOT already held
3. Generate pair: EXIT underperformer + ADD candidate (for equivalent amount)

**Reason Code:** `UNDERPERFORMER_REPLACEMENT`

**Business Rules:**
- "Same category" uses resolved category from `mutual_fund_metadata`
- Replacement must be in SAME category (no category switching)
- Dedup: avoid adding a fund the user already holds from a different AMC

---

### FR-PLAN-006 — Rule 4: Fund Overlap Consolidation
| Field | Value |
|---|---|
| **Requirement ID** | FR-PLAN-006 |
| **Module** | Action Plan |
| **Feature** | Duplicate Fund Exit |
| **Priority** | High (P1) |
| **Source** | `action_plan_manager._apply_action_rules()`, Rule 4 |
| **Status** | Live |

**Trigger:** Two DISTINCT funds (not Regular/Direct siblings — those are Rule 1) share > 60% stock-level overlap

**Algorithm:**
1. For each overlap pair: pick fund with HIGHER exit_score
2. EXIT that fund

**Guardrail:** Only generates action when `proxy_switch_score > 0` (exit produces net value after tax)

**Cap:** At most 2 consolidation actions per plan

**Reason Code:** `OVERLAP_CONSOLIDATION`

---

### FR-PLAN-007 — Rule 5: Debt Allocation Gap
| Field | Value |
|---|---|
| **Requirement ID** | FR-PLAN-007 |
| **Module** | Action Plan |
| **Feature** | Asset Allocation Rebalancing |
| **Priority** | Critical (P0, also fires when Postgres is down) |
| **Source** | `action_plan_manager._apply_action_rules()`, Rule 5 |
| **Status** | Live |

**Trigger:** Debt allocation < risk-profile floor:
| Risk Profile | Debt Floor |
|---|---|
| Conservative | 30% |
| Moderate | 20% |
| Aggressive | 10% |

**Algorithm:**
1. Compute current debt_pct from asset_allocation
2. Gap = target_debt_pct - current_debt_pct (in ₹)
3. Suggest debt fund: priority order — SBI Magnum Gilt / ICICI Corporate Bond / HDFC Short Term
4. Skip AMCs already over-concentrated

**Action Generated:** `ADD` debt fund for gap amount

**Reason Codes:** `ALLOCATION_GAP`, `DIVERSIFICATION`

**Business Rules:**
- This is the ONLY rule that does NOT need PostgreSQL — reads asset_allocation only
- Amount = min(₹3L, 10% of portfolio) OR the exact gap amount, whichever is smaller

---

### FR-PLAN-008 — Rule 6: Cost-Leak Switch
| Field | Value |
|---|---|
| **Requirement ID** | FR-PLAN-008 |
| **Module** | Action Plan |
| **Feature** | Regular→Direct Switch |
| **Priority** | High (P1) |
| **Source** | `action_plan_manager._apply_action_rules()`, Rule 6 |
| **Status** | Live |

**Trigger:** Annual cost leak from Regular plan > ₹10,000 (configurable) AND switch_score ≥ 1.0

**Calculation:**
```
annual_leak = Σ(regular_fund.expense_ratio - direct_equivalent.expense_ratio) × fund_value
```

**Action Generated:** `SWITCH` with exact ₹ saving + estimated tax drag shown

**Note:** Rule 1 catches direct/regular pairs first; Rule 6 fills gap when user has Regular but has NOT yet subscribed to the Direct variant.

---

### FR-PLAN-009 — Four Guardrails
| Field | Value |
|---|---|
| **Requirement ID** | FR-PLAN-009 |
| **Module** | Action Plan |
| **Feature** | Action Guardrails |
| **Priority** | Critical |
| **Source** | `services/v3_integration.py`, `action_plan_manager.py` |
| **Status** | Live |
| **Test Coverage** | `test_action_rules.py` — "high-quality fund is protected from EXIT unless overlap > 80%" |

**Four Guardrails (applied after rules generate actions):**

| # | Name | Condition | Effect |
|---|---|---|---|
| 1 | High-Quality Protection | Quality ≥ 75 AND Health ≥ 70 | BLOCK EXIT — unless pairwise overlap > 80% (override) |
| 2 | Tax-Exceeds-Benefit | tax_liability > annual_benefit × 2 | BLOCK EXIT — show "tax too high" reason |
| 3 | Recent-Investment Lockout | holding_age < 6 months | BLOCK EXIT — show "too soon to exit" reason |
| 4 | Low-Confidence | confidence_score < 50 | REDUCE action count to max 2 — flag "data incomplete" |

**Acceptance Criteria:**
- Fund with Q=80, H=75 and overlap=40% → EXIT action blocked (Guardrail 1)
- Fund with Q=80, H=75 and overlap=85% → EXIT action allowed (overlap override)
- Fund bought 3 months ago → EXIT blocked regardless of scores (Guardrail 3)
- tax_liability=₹50K, annual_saving=₹10K → EXIT blocked (50K > 10K×2) (Guardrail 2)

---

### FR-PLAN-010 — Plan State Machine
| Field | Value |
|---|---|
| **Requirement ID** | FR-PLAN-010 |
| **Module** | Action Plan |
| **Feature** | Plan Lifecycle |
| **Priority** | High |
| **Source** | `services/action_plan_manager.py` |
| **Status** | Live |

**States:**
```
preview → [User saves] → active → [User acts] → in_progress → [30 days] → archived
                                                              → completed
```

**Action-Level States:** `pending` | `in_progress` | `completed` | `skipped` | `archived`

**APIs:**
- `POST /api/plans/generate` → creates `preview` plan
- `POST /api/plans/{id}/save` → promotes to `active` (archives previous active plan)
- `PATCH /api/plans/{id}/actions/{aid}/status` → update individual action
- `POST /api/plans/{id}/actions/{aid}/feedback` → `{feedback: useful|not_useful, note?}`

**Business Rules:**
- Only ONE active plan per user at a time
- Activating a new plan archives the previous active plan
- Plans are versioned — old plans never deleted, only archived

---

## 4. Module: Portfolio Intelligence

### FR-INTEL-001 — Portfolio Intelligence Computation
| Field | Value |
|---|---|
| **Requirement ID** | FR-INTEL-001 |
| **Module** | Portfolio Intelligence |
| **Feature** | Stock-Level Look-Through Analysis |
| **Priority** | Critical |
| **Source** | `services/portfolio_intelligence.py` |
| **Status** | Live |

**API:** `GET /api/intelligence/portfolio`

**Output:**
```
{
  mf_investments[],          // resolved MF with category/AUM/ER/NAV
  pairwise_overlap[],        // stock-level overlap between MF pairs: Σ min(w_a, w_b)
  amc_exposure{},            // MF-only AMC AUM concentration
  category_breakdown{},      // SEBI category percentages
  sector_exposure[],         // underlying stock sectors
  compression_score,         // how many unique effective stocks
  effective_stocks,          // theoretical diversification count
  top_stocks[],              // most repeated underlying stocks
  redundancy_suggestions[],  // "remove this fund, its overlap is X%"
  asset_allocation{equity/debt/gold/other pct},
  total_value,
  degraded: bool,
  degraded_reason: str
}
```

**Stock-Level Overlap Formula:** `overlap_pct(A,B) = Σ min(weight_A(stock_k), weight_B(stock_k))` for all stocks k in top-10 of either fund.

**Compression Score:** `effective_stocks = 1 / Σ(weight_i²)` (Herfindahl-like measure of diversification)

**Degraded Mode:** If PostgreSQL unreachable → returns `{degraded: true}` with only asset_allocation available

---

### FR-INTEL-002 — Switch Candidates
| Field | Value |
|---|---|
| **Requirement ID** | FR-INTEL-002 |
| **Module** | Portfolio Intelligence |
| **Feature** | Replacement Fund Shortlist |
| **Priority** | High |
| **Source** | `routes/portfolio.py` — `/api/portfolio/switch-candidates` |
| **Status** | Live |

**API:** `GET /api/portfolio/switch-candidates?holding_id={id}`

**Algorithm:**
1. Identify current fund's category
2. Filter `mutual_fund_metadata`: same category, Direct plans only, exclude Regular/Direct siblings
3. Rank by `(quality_gain + cost_gain) / 2` (i.e., switch_score components)
4. Return top 3 candidates with switch_score breakdown

---

## 5. Module: Portfolio Health Scoring

### FR-HEALTH-001 — Portfolio Health Score
| Field | Value |
|---|---|
| **Requirement ID** | FR-HEALTH-001 |
| **Module** | Portfolio Health |
| **Feature** | 0-100 Health Scorecard |
| **Priority** | High |
| **Source** | `services/portfolio_health.py` |
| **Status** | Live |

**Output:**
```
{
  overall_score: 0-100,
  grade: "A+" | "A" | "B+" | "B" | "C" | "D" | "F",
  components: {
    diversification: 0-100,
    risk: 0-100,
    cost: 0-100,
    performance: 0-100,
  },
  risk_drivers: [top 3 risk factors with severity],
  warnings: []
}
```

**Grade Bands:**
| Score | Grade |
|---|---|
| ≥ 85 | A+ |
| 75–84 | A |
| 65–74 | B+ |
| 55–64 | B |
| 45–54 | C |
| 35–44 | D |
| < 35 | F |

---

## 6. Module: Tax Engine

### FR-TAX-001 — Capital Gains Calculation (FIFO)
| Field | Value |
|---|---|
| **Requirement ID** | FR-TAX-001 |
| **Module** | Tax Engine |
| **Feature** | Tax Impact per Exit/Switch |
| **Priority** | Critical |
| **Source** | `services/tax_calculator.py`, `services/tax_engine_fifo/` |
| **Status** | Live |

**Tax Rates (FY 2025–26, post 23-Jul-2024 Budget):**
| Asset Class | STCG (< 1yr) | LTCG (≥ 1yr) | LTCG Exemption |
|---|---|---|---|
| Equity MF / Listed equity / Equity ETF | 20% | 12.5% | ₹1,25,000/FY (aggregated) |
| Debt MF (bought ≥ 1-Apr-2023) | Slab rate (default 30%) | Slab rate (no LTCG benefit) | — |
| Debt MF (bought < 1-Apr-2023) | Slab rate (<24m) | 12.5% (≥24m) | — |
| Gold / Gold ETF / SGB | Slab rate (<24m) | 12.5% (≥24m) | — |
| Listed bonds | 20% (<12m) | 12.5% (≥12m) | — |

**`calculate_tax_impact()` Returns:**
```
holding_period_days, is_long_term, asset_class, tax_regime,
capital_gain, taxable_gain, tax_liability, tax_rate,
exit_amount_rs, post_tax_proceeds, tax_efficiency_pct,
tax_score (0-10), tax_impact_pending (bool)
```

**Pending Case:** When `buy_date = None` OR `buy_price = 0` → returns `tax_impact_pending = True`, `tax_liability = 0`. Plan counts these separately as `pending_actions`.

**Known Gap (V1 approach, V2 backlog):** Currently uses average buy_price × total qty (no FIFO lot-level tracking). True FIFO lot matching is implemented in `tax_engine_fifo/` but integration with plan generation is partial.

---

### FR-TAX-002 — Switch Cost Calculator
| Field | Value |
|---|---|
| **Requirement ID** | FR-TAX-002 |
| **Module** | Tax Engine |
| **Feature** | Switch Cost Framework |
| **Priority** | Critical |
| **Source** | `services/action_plan_manager.py`, `services/tax_calculator.py` |
| **Status** | Live |

**Formula:**
```
switch_cost % = expense_delta + redemption_load + tax_drag − expected_alpha
```

**Full Switch Cost Breakdown (shown to user):**
```
Gross Benefit   = annual_expense_saving_rs × 5yr horizon
Switch Cost     = exit_load_rs + estimated_LTCG_or_STCG_rs
Net Benefit     = Gross Benefit − Switch Cost
Payback Period  = Switch Cost / annual_expense_saving_rs
```

**ELSS Lock-in Rule:** ELSS funds with `holding_age < 3 years` must NOT appear as EXIT targets (lock-in enforced). **Gap: this check is documented but not confirmed fully implemented in current code — needs test coverage.**

---

### FR-TAX-003 — Tax Harvesting Suggestions
| Field | Value |
|---|---|
| **Requirement ID** | FR-TAX-003 |
| **Module** | Tax Engine |
| **Feature** | LTCG Harvest Recommendations |
| **Priority** | Medium |
| **Source** | `services/tax_engine_fifo/` |
| **Status** | Live |

**Trigger:** Holdings with unrealized LTCG approaching ₹1.25L annual exemption

**Suggests:** Sell + rebuy to reset cost basis with zero tax impact, show: estimated annual tax saved, exit load check, bid-ask spread note

---

## 7. Module: Enriched Portfolio Endpoint

### FR-ENRICH-001 — Holdings-Enriched API
| Field | Value |
|---|---|
| **Requirement ID** | FR-ENRICH-001 |
| **Module** | Portfolio Enrichment |
| **Feature** | V3-Enriched Holdings Response |
| **Priority** | Critical |
| **Source** | `routes/portfolio.py` — `GET /api/portfolio/holdings-enriched` |
| **Status** | Live |

**Response per holding includes:**
- All base holding fields
- V3 scores: quality, health, exit, add, portfolio_fit, switch_score
- Danger classification: critical/warning/ok + reasons
- Deterministic explanation text
- Action badges (EXIT/HOLD/ADD/SWITCH recommendation)
- Tax impact (LTCG/STCG estimate)
- Switch candidates (top 3 replacements)

**Fallback:** If enrichment fails → returns raw holding with `_enrichment_error` flag (never throws 500)

---

## 8. Gap Analysis — V2 Backend (Docs vs Code)

| Documented Feature | Code Status | Notes |
|---|---|---|
| FIFO lot-by-lot tax (all paths) | **PARTIAL** | FIFO service built but plan generation uses avg cost basis; P1 backlog |
| ELSS lock-in enforcement | **PARTIAL** | Logic exists but not confirmed with test coverage; needs verification |
| Custom admin DSL rules | **LIVE** | `_apply_custom_rules()` with safe AST evaluator |
| `hold_score` composite (V3.1) | **NOT IMPLEMENTED** | Planned; currently no HOLD action type in engine |
| Insight severity levels | **NOT IMPLEMENTED** | All insights same visual weight; V3.1 planned |
| alpha primitive mapping | **BUGGY** | Returns 0 for some funds; P1 fix needed (Groww scraper field gap) |
| Benchmark proxy computed alpha | **NOT IMPLEMENTED** | Planned fallback when Groww alpha=0 |

---

## 9. Requirement Traceability Matrix

| Req ID | Feature | Status | Service/File | Test File | Priority |
|---|---|---|---|---|---|
| FR-V3-001 | Quality Score | IMPLEMENTED | v3_scoring.py | test_v3_scoring.py | Critical |
| FR-V3-002 | Health Score | IMPLEMENTED | v3_scoring.py | test_v3_scoring.py | Critical |
| FR-V3-003 | Exit Score | IMPLEMENTED | v3_scoring.py | test_v3_scoring.py | Critical |
| FR-V3-004 | Add Score | IMPLEMENTED | v3_scoring.py | test_v3_scoring.py | High |
| FR-V3-005 | Portfolio-Fit | IMPLEMENTED | v3_scoring.py | test_v3_scoring.py | High |
| FR-V3-006 | Switch Score | IMPLEMENTED | v3_scoring.py / v3_integration.py | test_v3_scoring.py | Critical |
| FR-V3-007 | Danger Classification | IMPLEMENTED | v3_explainer.py | test_v3_explainer.py | High |
| FR-V3-008 | Primitive Data Sources | IMPLEMENTED | v3_integration.py | test_groww_v3_primitives.py | Critical |
| FR-V3-009 | NAV Analytics Sweep | IMPLEMENTED | nav_analytics_sweep.py | — | Critical |
| FR-PLAN-001 | Plan Generation | IMPLEMENTED | action_plan_manager.py | test_action_rules.py | Critical |
| FR-PLAN-002 | Rule 1 Reg→Dir | IMPLEMENTED | action_plan_manager.py | test_action_rules.py | Critical |
| FR-PLAN-003 | Rule 2 AMC Conc. | IMPLEMENTED | action_plan_manager.py | test_action_rules.py | Critical |
| FR-PLAN-004 | Rule 2b Category | IMPLEMENTED | action_plan_manager.py | test_action_rules.py | High |
| FR-PLAN-005 | Rule 3 Underperformer | IMPLEMENTED | action_plan_manager.py | test_action_rules.py | High |
| FR-PLAN-006 | Rule 4 Overlap | IMPLEMENTED | action_plan_manager.py | test_action_rules.py | High |
| FR-PLAN-007 | Rule 5 Debt Gap | IMPLEMENTED | action_plan_manager.py | test_action_rules.py | Critical |
| FR-PLAN-008 | Rule 6 Cost Leak | IMPLEMENTED | action_plan_manager.py | test_action_rules.py | High |
| FR-PLAN-009 | Four Guardrails | IMPLEMENTED | v3_integration.py | test_action_rules.py | Critical |
| FR-PLAN-010 | Plan Lifecycle | IMPLEMENTED | action_plan_manager.py | — | High |
| FR-INTEL-001 | Portfolio Intelligence | IMPLEMENTED | portfolio_intelligence.py | test_portfolio_intelligence.py | Critical |
| FR-INTEL-002 | Switch Candidates | IMPLEMENTED | routes/portfolio.py | — | High |
| FR-HEALTH-001 | Health Score | IMPLEMENTED | portfolio_health.py | — | High |
| FR-TAX-001 | Capital Gains | IMPLEMENTED | tax_calculator.py | — | Critical |
| FR-TAX-002 | Switch Cost | IMPLEMENTED | action_plan_manager.py | — | Critical |
| FR-TAX-003 | Tax Harvesting | PARTIAL | tax_engine_fifo/ | — | Medium |
| FR-ENRICH-001 | Enriched Holdings | IMPLEMENTED | routes/portfolio.py | test_v3_fund_breakdown_api.py | Critical |

---

*Document generated May 2026. Validated against commit on branch `nivesh-v2-copilot`. Engine version: V2.5 (plans) + V3.0-phase2 (scoring).*
