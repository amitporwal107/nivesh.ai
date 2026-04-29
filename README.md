# nivesh.ai — README

> **Agentic Wealth System for the Indian retail investor.**
> Parses CAS PDFs, scores every mutual fund across 38 deterministic primitives,
> flags concentration / cost / quality risks, generates an explainable action
> plan. Zero LLM-hallucinated numbers in the analytics path.

---

## 1. Stack at a glance

| Layer | Tech |
|---|---|
| Frontend | React · Tailwind · Shadcn UI · Recharts · Motion |
| Backend | FastAPI · asyncio · APScheduler (`Asia/Kolkata`) |
| Primary store | MongoDB (user-scoped documents) |
| Analytics store | PostgreSQL (tabular market data, 38k+ rows) |
| Cache | Redis (V3 composite scores + equity fundamentals) |
| LLM | OpenAI GPT-4o-mini via Emergent LLM key (copilot narrative only — never in analytics) |
| Data sources | `casparser.in` · AMFI `NAVAll.txt` · Groww `__NEXT_DATA__` |

---

## 2. PostgreSQL Schema (nivesh DB)

All DDL in `/app/backend/migrations/001-006_*.sql`. Idempotent — `IF NOT EXISTS`
everywhere. Applied additively by `datastore_bootstrap` service on container start.

### 2.1 Core instrument registry

```sql
instrument_master (
    instrument_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    symbol            TEXT,          -- AMFI scheme_code / NSE symbol
    instrument_name   TEXT NOT NULL,
    instrument_type   TEXT CHECK (instrument_type IN ('EQUITY','MUTUAL_FUND','SGB')),
    isin              TEXT,
    exchange          TEXT,
    currency          TEXT DEFAULT 'INR',
    is_active         BOOLEAN DEFAULT TRUE,
    created_at        TIMESTAMP,
    updated_at        TIMESTAMP
);
-- UNIQUE  (symbol, instrument_type)   WHERE symbol IS NOT NULL
-- UNIQUE  (isin)                      WHERE isin   IS NOT NULL
-- INDEX   lower(instrument_name)      -- fuzzy match via pg_trgm
```

### 2.2 `mutual_fund_metadata` — the central fund table (58 columns)

One row per fund. Upserted on every Groww scrape (COALESCE-preserving).

```sql
-- Identity
instrument_id          UUID PK FK
groww_slug             TEXT
amfi_scheme_code       TEXT
isin                   via instrument_master

-- Basic
aum_cr                 NUMERIC(12,2)
nav                    NUMERIC(12,4)
nav_date               DATE
category               TEXT
sub_category           TEXT
risk_label             TEXT
rating                 INTEGER             -- Groww 1–5
benchmark_index        TEXT

-- Age & manager
launch_date            DATE
allotment_date         DATE
fund_age_years         NUMERIC(4,1)
manager_name           TEXT
manager_since          DATE
manager_tenure_years   NUMERIC(4,1)
manager_education      TEXT
manager_funds_count    INTEGER
fund_managers          JSONB           -- full roster with per-person tenure

-- Cost
expense_ratio          NUMERIC(5,2)       -- generic (whichever plan was scraped)
expense_ratio_direct   NUMERIC(5,2)
expense_ratio_regular  NUMERIC(5,2)
expense_ratio_3y_ago   NUMERIC(5,2)
expense_trend_delta    NUMERIC(5,2)       -- latest − 3y_ago
historic_expense_json  JSONB              -- last 36 monthly rows
sibling_slug           TEXT               -- for Regular ⇄ Direct chase

-- Activity
turnover_ratio         NUMERIC(6,2)
turnover_as_of         DATE

-- Peer positioning
category_avg_1y/3y/5y           NUMERIC(6,2)
rank_within_category_1y/3y/5y   INTEGER

-- Concentration
top10_concentration_pct  NUMERIC(5,2)

-- NAV-derived analytics (computed locally by nav_analytics.py)
max_drawdown_pct        NUMERIC(5,2)
consistency_score       NUMERIC(4,2)   -- 0-10
downside_capture_pct    NUMERIC(5,2)
aum_trend_score         NUMERIC(4,2)   -- 0-10
nav_analytics_at        TIMESTAMP

-- V3 composite cache (Redis fallback)
quality_score           NUMERIC(5,2)   -- 0-100
health_score            NUMERIC(5,2)
exit_score_baseline     NUMERIC(5,2)
add_score_baseline      NUMERIC(5,2)
v3_scored_at            TIMESTAMPTZ

-- Analysis snapshot (Groww PROS/CONS + qualitative rating)
analysis_json           JSONB

-- Audit
last_scraped_at         TIMESTAMP
updated_at              TIMESTAMP
```

### 2.3 Fund holdings (top-10 look-through)

```sql
mutual_fund_holdings (
    id                     UUID PK,
    instrument_id          UUID FK mutual_fund
    holding_instrument_id  UUID FK instrument (nullable — stock may not be seeded)
    holding_name           TEXT NOT NULL,
    holding_stock_slug     TEXT,
    holding_sector         TEXT,
    holding_type           TEXT,
    weight_percent         NUMERIC(5,2),
    rank                   INTEGER,
    holding_date           DATE,
    created_at             TIMESTAMP
);
-- UNIQUE (instrument_id, holding_date, rank)
-- INDEX  (instrument_id, holding_date DESC)
```
Powers stock-level pairwise fund overlap (`portfolio_intelligence.py`).

### 2.4 Performance ratios (time-series per fund)

```sql
mutual_fund_performance_ratios (
    instrument_id   UUID FK,
    ratios_date     DATE,
    pe_ratio        NUMERIC(6,2),
    pb_ratio        NUMERIC(6,2),
    alpha           NUMERIC(6,2),
    beta            NUMERIC(6,3),
    sharpe          NUMERIC(6,3),
    sortino         NUMERIC(6,3),
    std_dev         NUMERIC(6,3),
    ret_1y          NUMERIC(6,2),
    ret_3y          NUMERIC(6,2),
    ret_5y          NUMERIC(6,2),
    created_at      TIMESTAMP,
    PRIMARY KEY (instrument_id, ratios_date)
);
```

### 2.5 Daily NAV history (time-series, ~34k rows today)

```sql
mutual_fund_nav_history (
    instrument_id  UUID FK ON DELETE CASCADE,
    nav_date       DATE,
    nav            NUMERIC(12,4) NOT NULL,
    source         TEXT DEFAULT 'amfi',
    created_at     TIMESTAMP,
    PRIMARY KEY (instrument_id, nav_date)
);
-- INDEX (nav_date)   -- window functions for rolling returns
```
Source: AMFI `NAVAll.txt` daily cron + 5-year backfill.

### 2.6 AUM snapshots (for trend score)

```sql
mutual_fund_aum_history (
    instrument_id  UUID FK ON DELETE CASCADE,
    snapshot_date  DATE,
    aum_cr         NUMERIC(12,2) NOT NULL,
    source         TEXT DEFAULT 'groww',
    created_at     TIMESTAMP,
    PRIMARY KEY (instrument_id, snapshot_date)
);
```
Populated opportunistically — every Groww scrape writes a snapshot idempotent on `(instrument_id, snapshot_date)`.

### 2.7 Benchmark master (SEBI standard)

```sql
benchmark_master (
    category              TEXT PRIMARY KEY,        -- e.g. "Large Cap"
    benchmark_name        TEXT NOT NULL,           -- e.g. "NIFTY 100 TRI"
    benchmark_symbol      TEXT,                    -- "NIFTY_100_TRI"
    notes                 TEXT,
    proxy_instrument_id   UUID FK instrument_master,  -- seeded index-tracker fund
    created_at            TIMESTAMP
);
```

**34 SEBI categories seeded** (Large Cap → NIFTY 100 TRI, Mid Cap → NIFTY Midcap 150 TRI, Liquid → CRISIL Liquid, …).  
**21 of 34** are wired to an actual index-tracker proxy fund so `downside_capture_pct` can be computed vs real NAVs.

### 2.8 Audit logs

```sql
scrape_audit_log (
    id                  UUID PK,
    instrument_id       UUID FK,
    instrument_name     TEXT,
    slug                TEXT,
    status              TEXT CHECK IN ('ok','partial','failed','skipped'),
    holdings_count      INTEGER,
    validation_issues   TEXT,
    source              TEXT,                -- 'fresh' | 'cache' | 'stale-cache'
    duration_ms         INTEGER,
    created_at          TIMESTAMP
);
-- INDEX created_at DESC, (instrument_id, created_at DESC)

amfi_nav_fetch_log (
    id, fetched_at, rows_parsed, rows_upserted, rows_skipped,
    duration_ms, status, error_msg
);

nav_analytics_job_log (
    id BIGSERIAL PK,
    job_name        TEXT,   -- 'analytics_sweep' | 'v3_rescore' | 'nav_analytics_manual'
    status          TEXT,   -- 'ok' | 'partial' | 'failed'
    funds_total/processed/skipped/failed INTEGER,
    duration_ms     INTEGER,
    error_msg       TEXT,
    started_at / finished_at  TIMESTAMPTZ
);
```

All three drive the **Admin Data Pipeline Monitor** tiles.

### 2.9 Live row counts (priyankamantri test env)

| Table | Rows |
|---|---|
| `instrument_master` | 735 (712 EQUITY + 23 MF + 0 SGB) |
| `mutual_fund_metadata` | 30 funds |
| `mutual_fund_holdings` | 2,102 top-10 rows |
| `mutual_fund_performance_ratios` | 30 snapshots |
| `mutual_fund_nav_history` | **33,994 NAV rows** across 30 funds |
| `mutual_fund_aum_history` | growing on every user-triggered scrape |
| `benchmark_master` | 34 rows (21 wired to proxy) |

---

## 3. Redis cache

Two namespaces. Graceful degradation — every read falls back to PG columns if Redis is unreachable.

### 3.1 V3 composite score cache

| Key format | `v3:score:{instrument_id}` |
|---|---|
| Value | JSON: `{quality_score, health_score, exit_score, add_score, quality_components, health_components, quality_missing, health_missing, v3_primitives, guardrail_blocked, guardrail_reasons}` |
| TTL | `V3_SCORE_TTL_S` env, **default 24h** |
| Prefix | `_KEY_PREFIX = "v3:score"` |
| Fallback | `mutual_fund_metadata.quality_score / health_score / v3_scored_at` columns |
| Write path | `services/v3_score_cache.set()` — invoked at the end of `run_v3_rescore()` sweep |
| Read path | `/api/intelligence/v3-score/{id}` reads cache first; `?refresh=true` bypasses |
| Eviction | TTL + explicit `invalidate()` / `invalidate_many()` / `invalidate_all()`. Sweep auto-invalidates funds whose primitives just changed |
| Bulk delete | `scan_iter(match="v3:score:*", count=500)` + batched `DEL` |
| Admin | "Invalidate all" button in Admin → Data Pipeline Monitor hits `POST /api/admin/data-pipeline/cache/invalidate` |

### 3.2 Equity fundamentals cache

| Key format | `groww:fundamentals:{nse_symbol}` |
|---|---|
| Value | JSON of Groww equity `__NEXT_DATA__` subset (P/E, P/B, market cap, sector, quarterly financials) |
| TTL | 24h |
| Path | `services/groww_fundamentals.py` |

No other keys are stored in Redis today. Sessions live in MongoDB, not Redis.

---

## 4. Groww Scraping — what we pull, how, when

`services/groww_client.py` + `services/pg_writer.py` + `services/fund_data_resolver.py`.

### 4.1 Primitives extracted per scrape (17 sourced — no compute)

Parsed by `_extract_v3_primitives(nd, holdings)` from Groww's `__NEXT_DATA__`:

| Primitive | Extracted from | Post-processing |
|---|---|---|
| `allotment_date` | `nd.allotment_date` → fallback `launch_date` | `_parse_iso_date` |
| `fund_age_years` | computed from allotment_date | `_years_between` helper |
| `fund_managers[]` | `nd.fund_manager_details` | full roster with `{name, since, tenure_years, education, experience, funds_managed_count}` |
| `primary_manager` | longest-tenured from above | max by `tenure_years` |
| `expense_ratio_direct` | sibling fetch (Regular ⇄ Direct) | stitched onto metadata |
| `expense_ratio_regular` | sibling fetch | stitched onto metadata |
| `expense_ratio_3y_ago` | walks `historic_fund_expense` (up to 1000 rows), finds closest entry to 3y-ago | ±90d tolerance |
| `expense_trend_delta` | `latest − 3y_ago` | rounded to 2dp |
| `historic_expense[]` | first 36 monthly rows of `historic_fund_expense` | truncated for PG JSONB |
| `turnover_ratio` | first non-null `turn_over_ratio` in historic rows (top-level is stale) | fallback to `portfolio_turnover` |
| `turnover_as_of` | `as_on_date` of the row that provided turnover | — |
| `category_avg_1y/3y/5y` | `nd.stats[type=CATEGORY_AVG_RETURN]` | — |
| `rank_within_category_1y/3y/5y` | `nd.stats[type=RANK_WITHIN_CATEGORY]` | int-cast |
| `top10_concentration_pct` | Σ `pct` across top-10 holdings | rounded |
| `sibling_slug` | `regular_search_id` OR `direct_search_id` based on current `plan_type` | used for sibling chase |
| `analysis[]` | `nd.analysis` | `{type, subject, desc, rating}` PROS/CONS bullets |
| `aum_cr`, `nav`, `expense_ratio`, `category`, `rating`, `risk_label`, `groww_slug` | top-level fields | — |

Plus **per-fund holdings** (top-10 stocks with `weight_percent` + sector) and **performance ratios** (`ret_1y/3y/5y`, `sharpe`, `sortino`, `alpha`, `beta`, `std_dev`).

### 4.2 Sibling-aware fetch

```
fetch_fund_with_sibling(scheme_name, slug)
  ├─ fetch_fund(primary)            → parse + extract
  ├─ if parsed.sibling_slug:
  │    fetch_fund(sibling)          → parse + extract
  │    stitch expense_ratio_direct + expense_ratio_regular onto primary
  └─ return parsed + parsed["sibling"] for recursive persistence
```
This is why every MF in PG has **both** expense ratios populated — sourced, not estimated.

### 4.3 Persistence (single SQL transaction)

`services/pg_writer.persist_scrape(parsed)`:
1. Upsert `instrument_master` (UUID on first insert, preserved on conflict)
2. Upsert `mutual_fund_metadata` — ALL 58 columns in one `INSERT ... ON CONFLICT UPDATE` using `COALESCE(EXCLUDED.col, existing.col)` so partial scrapes never null out previously-filled values
3. Replace `mutual_fund_holdings` for today's `holding_date`
4. Insert `mutual_fund_performance_ratios` row for today's `ratios_date` (PK guards duplicates)
5. Opportunistic snapshot to `mutual_fund_aum_history`
6. If sibling payload present → recurse into step 1 with the sibling
7. Emit `scrape_audit_log` row

### 4.4 Three scrape triggers

| Trigger | When | Max batch | File |
|---|---|---|---|
| **Live inline** | User hits `/api/intelligence/portfolio` or `/api/plans/generate` and a fund has no PG row | 1 | `fund_data_resolver.get_fund_data()` |
| **Off-hours drain** | APScheduler cron | 30 funds/batch | `fund_data_resolver.drain_queue()` (queue in `db.scrape_queue` MongoDB collection) |
| **Stale refresh** | 15+ days since `last_scraped_at` | re-enqueues | `mf_scheduler._stale_refresh_job()` |

### 4.5 Queue management

MongoDB collection `db.scrape_queue`:
```js
{
  instrument_id, slug, scheme_name,
  status: "pending" | "in_progress" | "done" | "failed",
  attempts: int,
  queued_at, started_at, finished_at, error
}
```
Unique on `instrument_id`. `drain_queue()` pulls `status:pending` sorted by `queued_at`, marks `in_progress`, scrapes, marks `done` or `failed`.

---

## 5. AMFI NAV ingestion

Complements Groww — provides daily EOD NAVs (1.6 MB dump, ~14k schemes) so we can compute NAV-derived analytics locally.

### 5.1 Daily cron — `scripts/fetch_amfi_navs.py`

- Pulls `https://portal.amfiindia.com/spages/NAVAll.txt`
- Resolves each scheme to `instrument_master.instrument_id` via:
  1. ISIN exact match
  2. AMFI scheme_code
  3. Fuzzy name match (`pg_trgm similarity ≥ 0.55`)
- Batch upserts (500/tx) into `mutual_fund_nav_history` with `ON CONFLICT (instrument_id, nav_date) DO UPDATE`
- Logs to `amfi_nav_fetch_log` — latest run parsed 13,968 NAVs, upserted 470 matched to our 735-instrument catalog

### 5.2 5-year backfill — `scripts/backfill_amfi_nav_history.py`

- Pulls AMFI's `DownloadNAVHistoryReport_Po.aspx` in 30-day chunks
- 61 HTTP calls, ~6 min runtime, ~3.5M rows parsed
- **Strict ISIN-only + scheme_code matching** (daily cron's fuzzy match would pollute historical data with IDCW/Dividend variants)
- Skips rows with keywords: `IDCW, Dividend, Payout, Reinvest, Bonus, Income Distribution`
- CLI flags: `--years N`, `--months N`, `--from YYYY-MM-DD --to YYYY-MM-DD`, `--dry-run`
- First full run: 25,922 rows across 23 funds; current total 33,994 across 30 funds

---

## 6. NAV-derived analytics (`services/nav_analytics.py`)

Pure compute from `mutual_fund_nav_history`. Four primitives written back to `mutual_fund_metadata`:

| Function | Formula | Min data required |
|---|---|---|
| `max_drawdown_from_series(navs)` | Peak-to-trough % on full series | 30 days |
| `consistency_score_from_series(navs, cat_avg_pct)` | 0–10 = fraction of rolling 12-month windows beating category avg | 18 months |
| `downside_capture_from_series(fund, benchmark)` | `Σ fund_returns(down months) / Σ benchmark_returns(down months) × 100`. Needs benchmark series via `benchmark_master.proxy_instrument_id` | 6 benchmark down months |
| `aum_trend_from_series(aum_snapshots)` | OLS slope of ln(AUM) over months → piecewise 0–10 | 3 snapshots |

`refresh_all_analytics(instrument_id)` computes all 4 + writes back + stamps `nav_analytics_at`.

---

## 7. V3 Composite Scoring (`services/v3_scoring.py`)

All pure functions. 5 composites + Switch formula + 4 Guardrails.

```
Quality   = Performance 25 + Risk-Adj 20 + Consistency 20 + Drawdown 15 + Cost 10 + AUM/Age 10
Health    = Manager 25 + AUM-Stab 20 + Turnover 15 + Concentration 15 + Downside 15 + Expense-Trend 10
Exit      = Overlap 25 + Tax 25 + Quality-inverse 25 + Cost 15 + Portfolio-Fit 10
Add       = Gap-Fit 30 + Low-Overlap 25 + Quality 20 + Need 15 + Cost 10
Portfolio = Diversification 25 + Overlap 25 + AMC 20 + Cost 15 + Asset-Alloc 15

Switch    = (Q_new − Q_old) + Overlap_reduction + Cost_saving/₹10K − Tax_cost/₹10K
            recommended = (score ≥ 2.0)

Guardrails:
  1. High-Quality Protection — block EXIT if Q≥75 AND H≥70 (override if overlap>80%)
  2. Tax-Exceeds-Benefit     — block EXIT if tax_liability > annual_benefit
  3. Recent-Investment       — block EXIT if holding age < 6 months
  4. Low-Confidence          — reduce actions if confidence < 50 (flag, not block)
```

**Weight redistribution**: any missing primitive's weight is proportionally redistributed across remaining components. `missing_primitives[]` returned so the UI can badge confidence.

`services/v3_explainer.py` converts any V3 bundle into:
- `classify_danger(bundle)` → `{level: critical|warning|ok, reasons: [...], is_danger: bool}`
- `build_explanation(bundle, plan_type, cost_leak_rs)` → plain-English paragraph citing weakest components + primitive values. **No LLM.**

Engine version constant: `v3.0-phase1`.

---

## 7A. Scoring Reference — full project map

This section is the **single source of truth** for every numeric score, grade,
and bucket users see in the UI. Each subsection links the visible label to the
source file and the exact formula. All scores are 0–100 unless noted.

### 7A.1 Portfolio Health (`services/portfolio_health.py`)

The number behind the **score ring** on Client 360 ("60/100", "Grade B").

```
Health = 0.30·D + 0.25·R + 0.20·C + 0.25·P
```

| Sub-score | Computation | Weight |
|---|---|---|
| **D — Diversification** | `0.5·D_concentration + 0.3·D_allocation + 0.2·D_overlap` | 30% |
| **R — Risk** | `100 − (0.6·VolScore + 0.4·DrawdownScore)` | 25% |
| **C — Cost** | `0.7·ExpenseScore + 0.3·TaxEfficiencyScore` | 20% |
| **P — Performance** | `0.5·SharpeScore + 0.3·AlphaScore + 0.2·ConsistencyScore` | 25% |

Letter grade thresholds:

| Score range | Grade |
|---|---|
| ≥ 90 | A+ |
| 80 – 89 | A |
| 70 – 79 | B+ |
| 60 – 69 | B |
| 50 – 59 | C |
| 40 – 49 | D |
| < 40 | F |

Calibration constants (`portfolio_health.py` top of file):

```
RISK_BANDS  vol_low=8% / vol_high=30% / dd_low=5% / dd_high=50%
IDEAL_ALLOCATIONS  conservative 30/60/10 · moderate 60/30/10 · aggressive 80/10/10
SHORT_HORIZON_CAP_EQUITY  40%   (overrides above when horizon < 5y)
IDEAL_EFFECTIVE_N  40            (effective-N target for stock diversification)
EXPENSE_SCORE_BANDS  good ≤0.5% → 100; poor ≥2.0% → 0
TAX_DRAG_BANDS       good ≤0.5% → 100; poor ≥4.0% → 0
STOCK_COST_PROXY_PCT  0.2%       (annual brokerage/slippage assumption)
```

Each sub-score is exposed via `HealthResult.to_dict().components.<name>` so the
UI can render per-component gauges + risk-driver chips ("Volatility is high
(28%) → vol_score 12/100").

### 7A.2 V3 Stock & Fund Composite Scoring (`services/v3_scoring.py`)

5 composites, each on the 0–100 scale. Weights are admin-editable via
`db.system_config.v3_stock_weights` / `v3_mf_weights`.

```
Quality   = Performance 25 + Risk-Adj 20 + Consistency 20 + Drawdown 15 + Cost 10 + AUM/Age 10
Health    = Manager 25 + AUM-Stab 20 + Turnover 15 + Concentration 15 + Downside 15 + Expense-Trend 10
Exit      = Overlap 25 + Tax 25 + Quality-inverse 25 + Cost 15 + Portfolio-Fit 10
Add       = Gap-Fit 30 + Low-Overlap 25 + Quality 20 + Need 15 + Cost 10
Portfolio = Diversification 25 + Overlap 25 + AMC 20 + Cost 15 + Asset-Alloc 15

Switch formula (NOT weighted; "raw bps"):
  Switch = (Q_new − Q_old) + Overlap_reduction + Cost_saving/₹10K − Tax_cost/₹10K
  Recommended when Switch ≥ 2.0
```

**Weight redistribution rule** — when any primitive is missing (e.g. no 5-year
returns for a young fund), the missing weight is **proportionally redistributed
across the remaining components** so the final score is always on a 100% base.
`missing_primitives[]` is returned so the UI shows a "heuristic" / "low-confidence"
badge. Same redistribution applies to Quality, Health, Exit, Add, Portfolio.

Per-component normalisers live in `v3_scoring.py` (`_norm_returns`,
`_norm_consistency`, `_norm_aum_trend`, `_norm_credit_quality`,
`_norm_duration_risk_flex`, `_norm_liquidity`, `_norm_allocation_stability`,
…). Each takes a primitive (e.g. 1Y/3Y/5Y returns or consistency_score) and
returns a 0–10 value, then `_weighted_composite` scales to 0–100.

### 7A.3 V3 Guardrails (`services/v3_scoring.py`, `_apply_guardrails`)

Block or down-rank an action even if its score is high. Applied after Exit/Add/Switch.

| # | Guardrail | Trigger | Effect |
|---|---|---|---|
| 1 | **High-Quality Protection** | `Quality ≥ 75 AND Health ≥ 70` | Block EXIT (override if `overlap > 80%`) |
| 2 | **Tax-Exceeds-Benefit** | `tax_liability > annual_benefit` | Block EXIT |
| 3 | **Recent-Investment** | `holding_age_months < 6` | Block EXIT |
| 4 | **Low-Confidence** | `confidence_score < 50` | Flag-only, do not block |

### 7A.4 Stock Direct-Equity Scoring (`services/stock_scoring.py`)

Refined V3 framework (Feb 2026 user-approved). Same 0–100 scale, separate
weight set from MFs, also admin-editable.

```
Quality:  ROE 25 + ROCE 20 + Earnings Growth 20 + Debt/Equity 15 + Margin 10 + Promoter 10
Health:   Momentum 30 + Volatility-Inverse 25 + Earnings Surprise 20 + Sentiment 15 + Volume 10
Exit:     Quality-inverse 30 + Health-inverse 25 + Overlap 20 + Tax 15 + Cost 10
Add:      Gap-Fit 30 + Quality 25 + Health 20 + Low-Overlap 15 + Need 10
```

Design-level decisions baked in:
- **PE band OUT of Quality** (valuation ≠ quality).
- **Beta OUT of Health** (poor retail signal).
- Dividend de-emphasised (growth investors don't care).
- Add is portfolio-driven, not stock-driven.

### 7A.5 Priority Engine (`services/priority_engine.py`) — MFD Advisor only

The **priority chip** ("High · 87", "Medium · 49") next to each client in the
advisor dashboard. Drives sort order in Today's Actions feed.

```
priority_score = 0.30·portfolio_weakness
               + 0.25·risk_factor
               + 0.20·aum_factor             (log-scaled ⟶ big clients don't dominate)
               + 0.15·recency_factor
               + 0.10·recommendation_severity
```

Each factor is normalised to 0–1 before weighting. Priority bucket assignment:

| Score | Bucket | UI |
|---|---|---|
| ≥ 0.70 | **HIGH** | 🔴 |
| 0.40 – 0.69 | **MEDIUM** | 🟡 |
| < 0.40 | **LOW** | 🟢 |

Recommendation severity table (`SEVERITY_BY_VERB` in `priority_engine.py`):

| Verb | Severity |
|---|---|
| `reduce` | 0.80 |
| `switch` | 0.70 |
| `rebalance`, `increase_sip`, `sip_increase` | 0.50 |
| `top_up` | 0.40 |
| `add_more` | 0.35 |
| `add` | 0.30 |
| `hold`, `(none)` | 0.10 |

`AUM_REFERENCE_RS = ₹10 Cr` — a client with ₹10 Cr AUM gives `aum_factor ≈ 1.0`
(log-scaled so a ₹100 Cr client only scores ~1.5× a ₹10 Cr client, not 10×).

### 7A.6 MFD Top-Issue Buckets (`MfdDashboard.jsx → deriveTopIssue`)

The **4 summary cards** on the advisor dashboard (Risk Issues / Underperformance
/ Rebalance Needed / Healthy). Each client gets exactly one `_issue.key` — first
threshold that hits wins, so the cards are **mutually exclusive**.

```js
deriveTopIssue(client) {
  const f = client.priority.factors;
  if (f.risk >= 0.6)                   → "over-risk"        // RISK ISSUES card
  if (f.portfolio_weakness >= 0.4)     → "underperforming"  // UNDERPERFORMANCE card
  if (f.recommendation_severity ≥ 0.7) → "exit-switch"      // REBALANCE NEEDED card
  if (f.recommendation_severity ≥ 0.4) → "rebalance"        // REBALANCE NEEDED card
  if (!last_reviewed_at)               → "unreviewed"       // (no card; review-stale chip)
  if (f.recency >= 1.0)                → "stale"            // (no card; review-stale chip)
  if (recommendation_count > 0)        → "review"           // (no card)
  else                                 → "healthy"          // HEALTHY card
}
```

**Why a counter shows 0:** the cards always sum to total clients. A client
showing as "Underperformance" cannot also count under "Risk Issues" — flip
that decision by editing the priority order in `deriveTopIssue` if desired.

The "Today's Actions" feed uses `deriveAction()` (same file) to pick the
recommended verb (Switch / Rebalance / Increase SIP / etc.) and prefers the
backend-computed `priority.dominant_action` when available.

### 7A.7 MFD Unified Health (`MfdDashboard.jsx → deriveHealth`)

The **75/100, Q 60 · R 5** number shown in the client list row. Distinct from
section 7A.1's portfolio_health — this is a quick blend the dashboard uses for
sorting:

```js
deriveHealth(p) {
  const q = p.portfolio_score;   // 0-100, V3 portfolio health (§7A.1)
  const r = p.risk_score;        // 0-100, higher = more risky
  if (q == null && r == null) return null;     // → "Calculating…"
  if (q == null) return Math.round(100 - r);
  if (r == null) return Math.round(q);
  return Math.round(0.6*q + 0.4*(100 - r));    // 60% quality + 40% risk-inverse
}
```

Tone bands:
- ≥ 70 → emerald (healthy)
- 50 – 69 → amber (review)
- < 50 → rose (action needed)

### 7A.8 Switch Decision Engine (`services/switch_decision_engine.py`)

Combines V3 Switch score + portfolio-context multipliers (overlap reduction,
tax cost) into a final switch verdict. Recommendation surfaces only when the
end-to-end score clears the +2.0 bps threshold (see §7A.2).

### 7A.9 Risk Drivers ("why this score?")

Each `Health_subscore` exposes `risk_drivers[]` with the worst-deviation
inputs. Format per driver:

```
Impact_i = Weight_i × Deviation_i
```

where `Deviation_i = max(0, ideal_value − actual_value) / ideal_range`. The
top-3 drivers per sub-score render as chips on the Insights tab:

> *"Volatility is 28% (band 8–30%) → vol_score 12/100, weight 60%, impact −18 pts"*

### 7A.10 Engine versions & cache keys

| Service | Version constant | Cache | Invalidation |
|---|---|---|---|
| V3 composite (MF) | `v3.0-phase1` (`v3_scoring.py`) | Redis (per-fund hash) | when AMFI NAV changes or admin re-weights |
| V3 stock | `stock-v3.0` (`stock_scoring.py`) | Redis | hourly cron |
| Portfolio Health | (in-process) | None | recomputed on every `/api/insights/analysis` call |
| Priority | (in-process) | per-MFD profile cache (`mfd_profile_signal_cache`, 60s stale-while-revalidate) | on holdings change or new recommendation |

---

## 8. Schedulers (APScheduler `Asia/Kolkata`)

All managed by `services/mf_scheduler.py`. Idempotent `start()` — called on server boot when `POSTGRES_URL` secret is available (and on first secret write).

| ID | Cron | Job | Purpose | File |
|---|---|---|---|---|
| `drain_weekday` | `mon-fri 02:00-05:59 IST hourly` | `_drain_job` | Pull up to 30 queued funds, scrape Groww, persist | `fund_data_resolver.drain_queue` |
| `drain_weekend` | `sat,sun every 2h` | `_drain_job` | Same as above | same |
| `stale_refresh` | `mon-fri 03:00 IST` | `_stale_refresh_job` | Re-enqueue funds with `last_scraped_at < now-15d` | inline in `mf_scheduler.py` |
| `amfi_navs_daily` | `daily 22:00 IST` | `_amfi_navs_job` | Fetch AMFI `NAVAll.txt`, upsert ~470 matched rows, write `amfi_nav_fetch_log` | `scripts/fetch_amfi_navs.py` |
| `analytics_sweep_daily` | `daily 22:30 IST` | `_analytics_sweep_job` | Parallel `refresh_all_analytics()` for every fund with ≥180 days NAV. `asyncio.gather` bounded by `V3_SWEEP_CONCURRENCY` semaphore (default 8). Writes `nav_analytics_job_log` | `nav_analytics_sweep.run_analytics_sweep` |
| `v3_rescore_daily` | `daily 22:45 IST` | `_v3_rescore_job` | Parallel Quality + Health composite recompute → PG columns + Redis cache. Invalidates cache for funds whose primitives changed | `nav_analytics_sweep.run_v3_rescore` |

Measured on priyankamantri env: analytics sweep 22 funds in **56 ms**, V3 rescore 24 funds in **18 ms** (~2.5 ms/fund with parallelism).

`max_instances=1` on every job — concurrent trigger returns HTTP 409 from Admin UI.

### 8.1 Admin on-demand triggers
- `POST /api/admin/data-pipeline/trigger/{job}` — fires any job immediately (respects concurrent-run guard)
- `POST /api/admin/data-pipeline/cache/invalidate` — bulk Redis wipe

---

## 9. Database processes & degradation behaviour

### 9.1 Connection management

- **Mongo** — Motor async client, connection string from `MONGO_URL` in `backend/.env`. Fails fast on missing.
- **Postgres** — `asyncpg` pool (default 10 connections). URL resolved in priority order:
  1. `POSTGRES_URL` admin secret
  2. `postgresql://postgres:postgres@localhost:5432/nivesh` fallback (matches bootstrap script)
  3. Graceful failure: `pg_client.get_pool()` returns `None`, `portfolio_intelligence` returns `{degraded: true}`, Plan engine falls back to Rule 5 only.
- **Redis** — `aioredis` client, URL from `REDIS_URL` admin secret with localhost fallback. Missing Redis never blocks reads — everything falls back to PG columns.

### 9.2 Bootstrap
`/app/scripts/restore_datastores.sh` — reruns every migration + seeds 41 canonical instruments + clears any `degraded=true` flag after a container restart wipes `nivesh` DB.

### 9.3 Degradation signals visible to the UI
- `portfolio_intelligence.degraded = true` → Insights tab shows "Postgres not configured — upload CAS to unlock"
- `plan.degraded = true` → PlanHeroCard renders amber warning banner
- Admin → Data Pipeline tile turns red when last job run failed

### 9.4 Idempotency guarantees
- Every upsert uses `ON CONFLICT DO UPDATE` with natural keys
- `persist_scrape` uses `COALESCE(EXCLUDED, existing)` so partial scrapes never null out data
- NAV ingestion batches 500/tx with `ON CONFLICT (instrument_id, nav_date)` — safe to re-run
- APScheduler `replace_existing=True` + `max_instances=1`

---

## 10. Quick Directory Map

```
/app/
├── backend/
│   ├── server.py
│   ├── deps.py                      DB clients + auth helper
│   ├── routes/
│   │   ├── portfolio.py             CAS upload + holdings CRUD
│   │   ├── intelligence.py          /api/intelligence/portfolio, /v3-score/{id}
│   │   ├── insights.py              /api/insights/generate, /v3-portfolio
│   │   ├── plans.py                 V2 plan generation + feedback
│   │   ├── chat.py                  Copilot (grounded on active plan)
│   │   ├── admin_secrets.py         SecretsRegistry CRUD
│   │   ├── admin_feature_flags.py
│   │   ├── admin_rules.py           Rules + prompts + DSL
│   │   ├── admin_data_pipeline.py   Scheduler observability
│   │   └── admin_users.py           User management
│   ├── services/
│   │   ├── groww_client.py          __NEXT_DATA__ parser + sibling fetch
│   │   ├── pg_writer.py             persist_scrape() transactional upsert
│   │   ├── pg_client.py             asyncpg pool + fallback
│   │   ├── redis_client.py
│   │   ├── fund_data_resolver.py    Live + drain paths
│   │   ├── mf_scheduler.py          APScheduler jobs
│   │   ├── nav_analytics.py         Pure compute (drawdown, consistency, …)
│   │   ├── nav_analytics_sweep.py   Parallel sweep + rescore
│   │   ├── v3_scoring.py            5 composites + switch + guardrails
│   │   ├── v3_integration.py        Enrich candidates for action engine
│   │   ├── v3_explainer.py          Deterministic classify + explanation
│   │   ├── v3_score_cache.py        Redis v3:score layer
│   │   ├── portfolio_intelligence.py Stock-level overlap + AMC + category
│   │   ├── action_plan_manager.py   7 rules (Reg→Direct, AMC, cat, perf, overlap, debt, hold)
│   │   ├── rules_config.py          DB-backed rule thresholds
│   │   ├── rules_dsl.py             Whitelisted AST evaluator
│   │   ├── prompts_manager.py       7 LLM prompts + sandbox
│   │   ├── tax_calculator.py        ClearTax FY25-26 rules
│   │   ├── ai_insights.py           Deterministic insight builder
│   │   ├── ai_engine.py             Chat with grounding
│   │   ├── cas_api_client.py
│   │   └── equity_sectors.py
│   ├── migrations/
│   │   ├── 001_phase2_mf_schema.sql
│   │   ├── 002_v3_engine_schema.sql
│   │   ├── 003_v3_phase0b_scrape_fields.sql
│   │   ├── 004_v3_phase1a_nav_analytics.sql
│   │   ├── 005_v3_phase2b_sweep_log.sql
│   │   └── 006_benchmark_proxy_mapping.sql
│   ├── scripts/
│   │   ├── fetch_amfi_navs.py               daily NAV cron
│   │   ├── backfill_amfi_nav_history.py     5y historical backfill
│   │   ├── seed_benchmark_trackers_v2.py    NIFTY proxy seeding
│   │   ├── reset_portfolio_data.py
│   │   └── restore_pg_from_mongo.py
│   └── tests/                       103+ pytest
│
├── frontend/
│   ├── src/components/
│   │   ├── admin/                   Data pipeline monitor, Rules/Prompts editors
│   │   ├── insights/                V3PortfolioInsights, V3FundBreakdown
│   │   ├── v2/                      PlanBoardView, PlanCard, PlanHeroCard, V3ScoreBadges
│   │   └── copilot/                 Nivesh Copilot drawer
│   └── src/context/AuthContext.js
│
├── scripts/
│   ├── restore_datastores.sh
│   ├── run_postgres.sh
│   └── run_redis.sh
│
├── docs/TECHNICAL_SPEC.md
├── memory/PRD.md                    Source of truth for completed work + backlog
└── README.md                        (this file)
```

---

## 11. Environment variables (`backend/.env`)

Only these two are protected / required at bootstrap:
```
MONGO_URL=mongodb://localhost:27017
DB_NAME=test_database
```

Everything else is an **admin secret** stored in `db.system_config.secrets` and hydrated into `os.environ` at startup:
```
POSTGRES_URL          → asyncpg pool
REDIS_URL             → aioredis client
CASPARSER_API_KEY     → CAS PDF parsing
CASPARSER_BASE_URL
EMERGENT_LLM_KEY      → copilot / narrative
OPENAI_API_KEY        → fallback
GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET
GMAIL_OAUTH_CLIENT_ID
V3_SCORE_TTL_S        → default 86400 (24h)
V3_SWEEP_CONCURRENCY  → default 8
```

Frontend:
```
REACT_APP_BACKEND_URL=https://wealth-advisor-96.preview.emergentagent.com
```

---

## 12. Running locally

```bash
sudo supervisorctl status          # backend, frontend, mongodb, postgres, redis
cd /app/backend && python -m pytest tests/ -v    # 103+ tests
```

Admin UI: sign in with a user whose `is_admin=True` (e.g. `priyankamantri@gmail.com`) → sidebar Admin → Data Pipeline → "Trigger" any job on demand.

---

## 13. Further reading

- **`/app/docs/TECHNICAL_SPEC.md`** — product spec, API surface, flows, testing
- **`/app/memory/PRD.md`** — session-by-session changelog + backlog
- **`/app/memory/V2_ACTION_GENERATION_RULES_COMPLETE.md`** — rule-engine spec
- **Excel**: V3 scoring sheet (Sheet1 inputs, weight tables, Switch + Guardrails) — source of truth for composite formulas
