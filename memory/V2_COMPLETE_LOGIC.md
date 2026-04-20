# V2 Decision Engine — Complete Logic Spec
_Source of truth for all plans, actions, and numbers in nivesh.ai._
Last verified: Feb 2026.

---

## 1. Data Pipeline

```
MongoDB.holdings                             Postgres.instrument_master
       │                                                  │
       ▼                                                  ▼
services/portfolio_intelligence.py     ── resolves ─▶   mutual_fund_holdings
       │                                                  mutual_fund_metadata
       ▼                                                  mutual_fund_performance_ratios
       intel = {                                          │
         total_value,                                     │
         asset_allocation,            (from MongoDB holistic calc)
         mf_investments[],            (resolved MF with category/AUM/ER/NAV)
         pairwise_overlap[],          (stock-level overlap between MFs)
         amc_exposure{},              (MF-only AMC concentration)
         catalog{id: {...}},          (quality ratios per MF)
         top_stocks, sector_exposure, ...
       }
       │
       ▼
services/action_plan_manager.py::_apply_action_rules()
       │
       ▼
   6 rules fire in priority order → actions[]
       │
       ▼
   tax_calculator.calculate_tax_impact() per EXIT/SELL action
       │
       ▼
   plan = {plan_id, actions, total_tax_impact, asset_allocation, ...}
       status: "preview" → "active" on save
```

**Critical dependency**: Postgres MUST be reachable. If `pg_client.get_pool()` returns None, intel is empty → rules 1/2/3/4/6 all short-circuit → **only Rule 5 fires**. This is now:
- Auto-fallback to `postgresql://postgres:postgres@localhost:5432/nivesh` when secret missing
- Logged as `V2 DEGRADED`
- Flagged on the response as `degraded: true, degraded_reason: "..."`

---

## 2. Scoring Engine (`services/instrument_scoring.py`)

### 2a. MF EXIT score (0–10)

| Component | Weight | Formula |
|---|---|---|
| Overlap | 30% | `min(10, max_pairwise_overlap_pct / 10)` — e.g. 85% overlap → 8.5 |
| Tax | 25% | `tax_result.tax_score` (0 for losses, up to 10 for high STCG hit as % of exit) |
| Cost | 15% | `min(10, expense_ratio × 5)` — 2% ER → 10 |
| Quality | 20% | `quality_scorer.calculate_mf_quality(metadata, ratios)` (alpha/sharpe/sortino/beta) |
| Portfolio Fit | 10% | Fixed at 5.0 (MVP — placeholder) |

**Decision thresholds**:
- `exit_score >= 7.0` → action = EXIT (high priority)
- `4.0 <= exit_score < 7.0` → HOLD (medium priority, still a candidate if rules need one)
- `< 4.0` → KEEP (skipped)

### 2b. MF ADD score (0–10)

| Component | Weight |
|---|---|
| Gap fit | 30% |
| Low overlap vs existing | 25% |
| Quality | 25% |
| Low cost | 10% |
| Headroom | 10% |

- `add_score >= 7.0` → ADD candidate

### 2c. Stock EXIT score (0–10) — *currently disabled for plan generation*
45% quality + 20% momentum + 20% concentration + 5% tax + 5% sector + 5% role.

---

## 3. Six Action Rules (applied in priority order)

Implemented in `action_plan_manager._apply_action_rules()`.
Every rule caps itself so a plan has **at most ~5–8 actions**.

### Rule 1 — Regular → Direct consolidation (P0)
```
FOR pair in mf_holdings where base_scheme_name matches across plan types:
    IF one is Regular AND one is Direct:
        EXIT the Regular plan
        reason_code = "REGULAR_DIRECT_DUPLICATE"
```
- Uses `_normalize_base_scheme_name()` to strip "Direct/Regular/Growth/IDCW" suffixes.
- Amount = full holding value. Tax = ClearTax calc on unrealized gain.

### Rule 2 — AMC concentration > 15% (P0)
```
amc_exposure = Σ(mf_investment.amount_rs) grouped by amc_name ÷ total_mf_value
FOR each AMC with exposure > 15%:
    candidates = funds of that AMC, ranked by exit_score DESC
    EXIT funds top-down until (AMC value / total_mf_value) <= 15%
    reason_code = "AMC_CONCENTRATION_EXIT"
```
- Uses `_calculate_amc_exposure_from_mf_investments()` (MF-only, excludes stocks/ETFs by design).
- Skips funds already in EXIT queue from Rule 1.

### Rule 3 — Underperformer replacement (P1)
```
underperformers = MFs where quality_score < 5.0 (from scoring engine)
FOR each underperformer u:
    candidate = best same-category fund (highest ADD score) NOT already held
    EXIT u  +  ADD candidate (for equivalent amount)
    reason_code = "UNDERPERFORMER_REPLACEMENT"
```
- "Same category" uses the resolved `category` from `mutual_fund_metadata`.
- Falls back to dedup-across-AMC-already-held to avoid doubling up.

### Rule 4 — Different-fund overlap > 60% (P1)
```
FOR each pair in pairwise_overlap with overlap_pct > 60% AND different base schemes:
    pick fund with HIGHER exit_score
    EXIT that fund
    reason_code = "OVERLAP_CONSOLIDATION"
CAP: at most 2 consolidation actions per plan.
```

### Rule 5 — Debt allocation gap (P0)
```
IF equity_pct > 90% AND debt_pct < 10%:
    target = ₹3L OR 10% of portfolio (whichever is smaller)
    ADD debt fund (_suggest_debt_fund): SBI Magnum Gilt / ICICI Corporate Bond / HDFC Short Term
        — excluded_amcs = AMCs already over concentration
    reason_codes = ["ALLOCATION_GAP", "DIVERSIFICATION"]
```
- **This is the only rule that does NOT need Postgres** — it reads asset_allocation only.
  If PG is down, this is the only rule that fires (bug you saw).

### Rule 6 — Regular→Direct cost leak (P1)
```
leak = Σ(regular_fund.expense_ratio − direct_equivalent.expense_ratio) × fund_value
IF leak > ₹10,000/year:
    Generate SWITCH action for each Regular fund with Direct equivalent
    reason_code = "COST_LEAK_SWITCH"
```
- In practice Rule 1 catches these first; Rule 6 fills the gap when Regular exists but no
  corresponding Direct is currently held (user needs to subscribe to Direct).

---

## 4. Tax Engine (`services/tax_calculator.py`)

ClearTax FY 2025–26 rates (post 23-Jul-2024):

| Asset class | STCG threshold | STCG rate | LTCG rate | LTCG exemption |
|---|---|---|---|---|
| Equity MF / Listed equity / Equity ETF | ≤12m | **20%** | **12.5%** | ₹1,25,000 / FY (aggregated) |
| Debt MF (buy_date ≥ 1-Apr-2023) | — | slab (default 30%) | — (always slab) | — |
| Debt MF (buy_date < 1-Apr-2023) | ≤24m | slab | 12.5% | — |
| Gold / Gold ETF / SGB | ≤24m | slab (30%) | 12.5% | — |
| Listed bonds | ≤12m | 20% | 12.5% | — |

`calculate_tax_impact(holding, exit_amount_rs, user_slab_rate, ltcg_exemption_used)` returns:
```
holding_period_days, is_long_term, asset_class, tax_regime,
capital_gain, taxable_gain, tax_liability, tax_rate,
exit_amount_rs, post_tax_proceeds, tax_efficiency_pct,
tax_score (0-10), tax_impact_pending (bool)
```

**Pending case**: When `buy_date` is None OR `buy_price`==0, returns `tax_impact_pending=True` and `tax_liability=0`. Plan-level aggregate counts these separately as `pending_actions` instead of pretending tax is ₹0.

---

## 5. Plan State Machine (`action_plan_manager`)

```
   create_plan()            save_plan()           auto_archive_old_completed_plans()
       │                         │                             │
       ▼                         ▼                             ▼
    preview ─── promote ──▶ active ── user acts ──▶ in_progress ── completed (30d) ──▶ archived
                             │
                             ├── skipped  (individual actions)
                             └── new active plan generated ──▶ previous active → archived
```

Action-level status: `pending | in_progress | completed | skipped | archived`.
Action feedback: `useful | not_useful` + optional text.

---

## 6. Failure Modes (most common)

| Symptom | Likely cause | Fix |
|---|---|---|
| Plan has only 1 action (Rule 5 ADD debt) | **Postgres unreachable** — `POSTGRES_URL` secret missing or PG service down | `/admin/datastores/postgres/restart`, or set secret. `pg_client` now falls back to local default. Response carries `degraded: true`. |
| AMC concentration doesn't detect 22% HDFC | `mf_investments` empty because PG resolution failed | same as above |
| All actions show `tax_liability: null` | `_create_exit_action_with_tax_analysis` wasn't receiving holding context | fixed Feb 2026 — falls back to `tax_calculator.calculate_tax_impact(holding)` |
| Every holding has `buy_date = today` | CAS parser didn't emit buy_date; portfolio.py back-filled `datetime.now()` | fixed Feb 2026 — parser extracts from `transactions[*].date`; missing stays `None` |
| Plan shows `other_pct: 100%` | Copilot `_build_context` fallback math bug | fixed Feb 2026 |
| "Save as Plan" shows PLAN READY but Plan Board empty | plan left in `preview` status | fixed Feb 2026 — chains `/generate` → `/save` |

---

## 7. Public APIs

| Endpoint | Purpose |
|---|---|
| `POST /api/plans/generate` | Run V2 → return preview plan |
| `POST /api/plans/{id}/save` | Promote preview → active (archives previous active) |
| `GET /api/plans/active` | Current active plan `{plan, has_plan}` |
| `GET /api/plans/history` | All plans for user (active + archived) |
| `PATCH /api/plans/{id}/actions/{aid}/status` | Update single action status |
| `POST /api/plans/{id}/actions/{aid}/feedback` | `{feedback: useful/not_useful, note?}` |
| `POST /api/admin/datastores/{postgres|redis}/restart` | Manually restore datastore |

---

## 8. Known Gaps (Phase B)

- Direct stocks excluded from concentration / overlap analysis (by design; MF-only)
- FIFO lot-wise tax — we use avg buy_price × total qty (no lot tracking)
- No user income slab captured → debt/gold STCG defaults to 30% flat
- No handling for ELSS lock-in (3yr) — can suggest EXIT when unit is locked
- Underperformer detection uses category benchmarks from metadata; not live alpha
