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

## 13. Market Intelligence Layer

A separate vertical from the V3 fund-scoring path. Drives the **Market Dashboard** (`/market` route) — answers *"what is the market doing right now, and what should I trade?"* — and adds a 5–30 day positional trade engine for the equity side.

### 13.1 Market Dashboard composition

[`MarketDashboard.jsx`](frontend/src/components/MarketDashboard.jsx) — page shell, composes existing components in this order:

```
MacroBar              → regime pills + values + admin Refresh button
TodayStrategyCard     → bias / aggression / focus / avoid sectors
SectorHeatmap         → top + weak sector lists, per-sector cards with rationale
AlignedPicks          → stocks in tailwind sectors
WhatChanged           → diff vs prior trading day
MondayGamePlan        → weekend/holiday-only synth view
WeekendWatchlist      → 4-bucket prep view (Friday's data)
PositionalPicks       → live picks with readiness chips
```

Each component has its own fetch, all `withCredentials`, all degrade-on-error.

### 13.2 Macro pipeline

```
yfinance/AV (5 metrics) → macro_daily → macro_features → macro_state + sector_macro_scores
```

| Stage | File | What it does |
|---|---|---|
| **Ingest** | [`macro_ingester.py`](backend/services/macro_ingester.py) | Pulls crude (`BZ=F`), USDINR (`USDINR=X`), US 10y (`^TNX`), Nifty (`^NSEI`), India VIX (`^INDIAVIX`) every weekday at 18:35 IST. Sanity gate rejects values >10% off the prior bar. Sources have fallback chains (yfinance → Alpha Vantage → RBI stub). |
| **Features** | [`macro_engine.compute_features()`](backend/services/macro_engine.py#L119) | 5d momentum, 60d z-scores, VIX percentile, composite risk score → `macro_features` table. |
| **Regime** | [`macro_engine.classify_regime()`](backend/services/macro_engine.py#L437) | Maps features → 4 categorical labels: Market (BULL/BEAR/NEUTRAL), Inflation (RISING/FALLING/NEUTRAL), Liquidity (ABUNDANT/TIGHT/NEUTRAL), Risk (LOW/MEDIUM/HIGH) + `macro_multiplier` (1.0× / 0.9× / 0.8×) + insight + interpretation. Persisted to `macro_state`. |
| **Sectors** | [`macro_sector.compute_modifier()`](backend/services/macro_sector.py#L130) | `score = Σ (sensitivity × momentum)` per sector. Hardcoded sensitivity vector in [`SECTOR_MACRO_MAP`](backend/services/macro_sector.py#L37) (PAINT crude=−1.0, IT usd=+1.0, BANK yield=−0.5, etc.). Plain-English causal chain in [`_REASONS`](backend/services/macro_sector.py#L185). Persisted to `sector_macro_scores`. |

**API surface** ([`routes/macro.py`](backend/routes/macro.py)):

| Endpoint | Returns |
|---|---|
| `GET /api/macro/today` | latest regime + values + insight + multiplier |
| `GET /api/macro/sector` | sector heatmap (sorted, with rationale) |
| `GET /api/macro/changes` | yesterday → today diff |
| `GET /api/macro/aligned-picks` | stocks in tailwind sectors |
| `POST /api/macro/refresh` *(admin)* | manual run of the daily pipeline |
| `POST /api/macro/backfill` *(admin)* | re-pull last N days |

Cron: [`mf_scheduler._macro_intelligence_job`](backend/services/mf_scheduler.py#L188) fires `macro_engine.run_daily()` at 18:35 IST every day. Manual override: admin "Refresh data" button on `MacroBar`. Cron-of-last-resort: scheduled remote agent `macro-daily-refresh` hits `/api/macro/refresh` weekdays 19:00 IST.

### 13.3 Positional Engine (5–30 day technical trades)

Layered **on top of** V3 fund scoring, not a replacement. Drives the Positional Picks panel on `MarketDashboard` and the Stocks tab on the Portfolio page.

```
NSE bhavcopy → stock_ohlcv ┐
Chartink scans → chartink_scan_hits ┤→ feature_calculator → scorer → trade_planner → positional_signals
                                    ┘
```

Module: [`backend/services/positional_engine/`](backend/services/positional_engine/)

| File | Role |
|---|---|
| `bhavcopy_ingester.py` | Pulls NSE `sec_bhavdata_full_DDMMYYYY.csv`, parses EQ/BE rows, upserts to `stock_ohlcv` |
| `feature_calculator.py` | Pure-Python — SMA/EMA/RSI(Wilder)/MACD/ATR/Bollinger/slope/swing levels/volume Z/delivery trend |
| `scorer.py` | 6 sub-scores (trend / momentum / structure / accumulation / sector / risk), final weighted, stage classifier (ACCUMULATION / EARLY_BREAKOUT / BREAKOUT / EXTENDED / WEAK), confidence (HIGH/MEDIUM/LOW) |
| `trade_planner.py` | Stage-aware entry/SL/target with ≥1.5 RR floor; macro-aware position-size factor |
| `chartink_api.py` | Polling client for Chartink `/screener/process` (bootstrap session → POST clause → parse JSON) |
| `chartink_loader.py` | CSV upload parser + scan-hit upsert |
| `scan_config.py` | Mongo-backed scan list + webhook token storage |
| `pipeline.py` | `run_for_date()` orchestrator + `score_symbol()` testable pure-function path |
| `portfolio_filter.py` | Annotates picks with overlap/sector-cap warnings against caller's holdings |

**API surface** ([`routes/positional.py`](backend/routes/positional.py)):

| Endpoint | Purpose |
|---|---|
| `GET /api/positional/picks?date=&min_score=&stage=&limit=` | Top picks with optional `live=true` LTP overlay |
| `GET /api/positional/picks/mine?live=true` | Same, filtered/annotated against caller's holdings |
| `GET /api/positional/picks/{symbol}` | Full breakdown for one symbol |
| `GET /api/positional/scans/active` | Saved scan list (auth) |
| `GET /api/positional/scans/config` *(admin)* | Same with edit access |
| `PUT /api/positional/scans/config` *(admin)* | Replace the scan list |
| `POST /api/positional/scans/test` *(admin)* | Probe a clause without saving |
| `POST /api/positional/scans/run-all` *(admin)* | Fetch every enabled scan from Chartink |
| `POST /api/positional/ohlcv/bhavcopy` *(admin)* | Trigger NSE bhavcopy ingest |
| `POST /api/positional/run` *(admin)* | End-to-end pipeline run for a date |
| `POST /api/positional/run-full` *(admin)* | Bhavcopy + scans + run, all in one |
| `POST /api/positional/chartink/webhook?token=` | **Production path** — Chartink alert receiver |
| `GET /api/positional/chartink/webhook-info` *(admin)* | Webhook URL + token + setup hints |
| `POST /api/positional/chartink/webhook-info/rotate` *(admin)* | Rotate the webhook token |
| `GET /api/positional/health` *(admin)* | Freshness counts of every engine table |

**Live readiness layer** — when the IST market is open (09:15–15:30 IST = 03:45–10:00 UTC), the frontend polls `/picks/mine?live=true` every 60s. Each pick gets a `readiness` chip (TRIGGERED / NEAR / WAIT / FAR / STOPPED) computed against the current LTP from yfinance batch. Outside market hours, polls every 5 min for admin-run catches.

### 13.4 Chartink integration — two paths

| Path | When | Trade-off |
|---|---|---|
| **Webhook (production)** | Chartink alert fires → POSTs to `/api/positional/chartink/webhook?token=…` | Real-time, no rate limits, supported. Authenticated via per-tenant URL token. |
| **Polling (dev / backfill)** | Admin clicks "Run all scans" or `/scans/run-all` cron | Unofficial — uses Chartink's internal `/screener/process` endpoint. Rate-limited, can break. Kept as fallback. |

Webhook payload:
```json
{
  "stocks": "INFY,TCS,RELIANCE",
  "trigger_prices": "1500.5,3500.0,2400.25",
  "triggered_at": "2:34 pm",
  "scan_name": "TODAYS TOP BUY",
  "scan_url": "todays-top-buy"
}
```

Receiver maps Chartink's free-text `scan_name` to internal saved-scan names (`scan_config.match_scan_name()`) — e.g. `"TODAYS TOP BUY"` → `atlas.todays_top_buy`. Hits land in `chartink_scan_hits` immediately; the next pipeline run picks them up.

UI: Admin-only **Chartink webhook setup** card on the picks panel — click to copy URL, includes Rotate button + setup instructions + auto-matched scan list.

### 13.5 New tables added

```sql
-- Macro layer (migrations 016, 017)
macro_daily              -- raw daily prints from yfinance/Alpha Vantage
macro_features           -- computed momentum / z-scores / composite risk
macro_state              -- regime classification + insight + interpretation
sector_macro_scores      -- per-sector tilt scores with rationale

-- Positional layer (migration 015)
stock_ohlcv              -- daily OHLCV + delivery_pct
chartink_scan_hits       -- (date, scan_name, symbol) — webhook + polling
stock_technical_features -- per-(symbol,date) sub-scores + raw values + components JSON
positional_signals       -- final ranked picks with entry/SL/target/RR
positional_outcomes      -- learning loop (TARGET_HIT / SL_HIT / EXPIRED)
```

Plus Mongo: `system_config.chartink_scans` (scan list + webhook token).

---

## 14. Feature inventory & PRD ledger

> **Convention** — every shipped feature lands here as an entry with **[Shipped]** (what works today, with file refs) and **[Pending]** (known gaps + planned follow-ups). When something on a `[Pending]` list lands, *don't rewrite the original entry* — add a new dated delta below it. The README is the running PRD; `/app/memory/PRD.md` is the iteration-by-iteration timeline.
>
> Entries are grouped: **A** Foundation → **B** Data ingestion → **C** Scoring → **D** Decision engines → **E** Frontend / UX → **F** MFD / multi-tenant → **G** Admin → **H** Compliance / cross-cutting → **I** Market intelligence (macro + positional) → **J** Roadmap (NIDP). Search the section ID (e.g. §14.C1) to jump.

---

### A · Foundation

#### 14.A1 Auth + sessions + role gating

**[Shipped]**
- Google OAuth signin → server-side session token in Mongo `user_sessions`, cookie + `Authorization: Bearer …` both accepted ([routes/auth.py](backend/routes/auth.py), [deps.py:get_current_user](backend/deps.py))
- `whitelisted_users` collection — only invited emails can sign in; admin invitation flow via [routes/admin_users.py](backend/routes/admin_users.py)
- `is_admin` flag on whitelist + users — drives admin-only routes and UI gates via `require_admin()`
- Founder/seed accounts (`SEED_FOUNDER_EMAILS`) auto-created with `is_admin=True` on cold boot ([deps.py:seed_admin_and_whitelist](backend/deps.py))
- Frontend `AuthContext` (`useAuth()` hook) — fetches `/auth/me`, exposes `{user, login, logout}`, refreshable
- Rate limit middleware on every API route ([middleware.py:RateLimitMiddleware](backend/middleware.py))

**[Pending]**
- TOTP / 2FA — out of scope; rely on Google OAuth's posture
- Email-link signin (passwordless) for users who can't use Google — not requested yet
- Session inactivity timeout — currently sessions persist until logout

---

#### 14.A2 Datastore bootstrap + degradation

**[Shipped]**
- Mongo via `motor` AsyncIOMotorClient, fail-fast on missing `MONGO_URL`
- Postgres via `asyncpg` pool (10 conns) with three-stage URL resolution: secret → env → `localhost:5432/nivesh` fallback ([services/pg_client.py](backend/services/pg_client.py))
- Redis via `aioredis`, missing-Redis is non-fatal (everything falls back to PG columns)
- Idempotent migrations (001 → 017) applied additively by `datastore_bootstrap` on container start; `IF NOT EXISTS` everywhere
- Schema-drift catchup migration ([013_schema_drift_catchup.sql](backend/migrations/013_schema_drift_catchup.sql)) recovers any environment that landed without applying earlier migrations cleanly
- `restore_datastores.sh` — one command to rerun every migration + seed 41 canonical instruments + clear `degraded=true` flags
- Graceful degradation flags: `portfolio_intelligence.degraded`, `plan.degraded`, admin pipeline tile turns red on job failure
- Admin secrets stored in `db.system_config.secrets`, hydrated into `os.environ` at startup ([helpers/secrets.py](backend/helpers/secrets.py))

**[Pending]**
- Migration runner doesn't auto-trigger on first request — needs explicit container restart or `restore_datastores.sh` call. Should run idempotently on every startup.
- No backup/restore tooling for Mongo — relies on the platform-level snapshot
- No connection-pool autoscaling under load

---

#### 14.A3 Schedulers + observability

**[Shipped]**
- APScheduler `Asia/Kolkata` configured in [services/mf_scheduler.py](backend/services/mf_scheduler.py) with `replace_existing=True` + `max_instances=1` for safety
- Daily cron jobs:
  - **08:30 IST** — V3 nightly rescore of every fund
  - **17:30 IST** — AMFI NAV pull + nav_analytics_sweep
  - **18:30 IST** — `benchmark_index.refresh_all()` (Nifty 50 + Midcap + Smallcap + 500)
  - **18:35 IST** — `macro_engine.run_daily()` (macro intelligence layer)
  - **23:30 IST** — `portfolio_snapshot.run_eod_snapshot_job()`
- Pipeline progress tracking (`pipeline_progress` collection) — admin Data Pipeline tile shows last-run + duration + row counts per job
- Admin `/api/admin/data-pipeline/*` endpoints to inspect + trigger any job on demand

**[Pending]**
- No alerting on job failure — admin tile turns red but no email/Slack notification fires
- No SLA dashboard — "is bhavcopy fresh?" requires opening the admin panel
- Scheduler doesn't always restart cleanly when the backend container restarts mid-job — known but rare

---

### B · Data ingestion

#### 14.B1 CAS pipeline (PDF → snapshot → transactions)

**[Shipped]**
- 3-provider CAS parser dispatch with admin-managed override ([services/nivesh_cas_parser.py](backend/services/nivesh_cas_parser.py), [cas_parser.py](backend/services/cas_parser.py), [claude_cas_parser.py](backend/services/claude_cas_parser.py)) — defaults to `nivesh_cas_parser` (Google Document AI), falls back to legacy
- Image-based CAS fallback via poppler `pdftoppm` (auto-installs on container start in [server.py](backend/server.py))
- OCR correction + identity uniqueness ([services/ocr_correction.py](backend/services/ocr_correction.py), [identity_uniqueness.py](backend/services/identity_uniqueness.py)) — fixes pdftoppm artifacts, dedupes folio variants
- CAS snapshot engine — every CAS upload creates a frozen point-in-time snapshot ([services/cas_snapshot_engine.py](backend/services/cas_snapshot_engine.py), migration [012_portfolio_snapshot.sql](backend/migrations/012_portfolio_snapshot.sql))
- Transaction extraction + SIP detection ([services/cas_transactions.py](backend/services/cas_transactions.py)) — finds recurring SIPs, period detection
- Cost-basis recovery from snapshots when CAS doesn't ship invested-amount ([services/cost_basis_from_snapshots.py](backend/services/cost_basis_from_snapshots.py))
- Client CAS invite v2 — MFD generates a 24h shareable Gmail-connect link with consent flow ([routes/client_cas_invite.py](backend/routes/client_cas_invite.py))
- Frontend `CasUploadButton` + `CasConnect` page + `ClaudeCasUploadButton` for the alternate parser

**[Pending]**
- Multi-folio NSDL parsing has edge cases — some legacy NSDL CAS layouts produce a "share count" instead of folio-level rows; handled but not robust
- CAS PDF password handling is per-upload — no remembered-password flow
- No automatic re-upload reminder when CAS goes stale (>30 days)
- Encrypted CAS PDFs from a few AMCs still need manual unlock

---

#### 14.B2 AMFI NAV ingestion + analytics

**[Shipped]**
- Daily AMFI `NAVAll.txt` pull at 17:30 IST ([services/amfi_nav.py](backend/services/amfi_nav.py))
- 5-year historical backfill script ([scripts/backfill_amfi_nav_history.py](backend/scripts/backfill_amfi_nav_history.py)) — tested on 41-fund canonical set
- Batched 500/tx upserts with `ON CONFLICT (instrument_id, nav_date)` — safe to re-run
- NAV analytics sweep ([services/nav_analytics.py](backend/services/nav_analytics.py), [nav_analytics_sweep.py](backend/services/nav_analytics_sweep.py)) — drawdown, consistency, max DD recovery time, alpha vs benchmark
- Per-fund analytics cached + invalidated on NAV update
- `nav_analytics_sweep_log` audit table tracks every sweep run

**[Pending]**
- AMFI NAV doesn't ship intraday — analytics lag end-of-day by 1 day
- No NAV gap detection (e.g. AMC reports a NAV jump that's a corporate action, not a real return) — flagged but not auto-corrected
- No per-share-class disambiguation when AMC merges share classes mid-history

---

#### 14.B3 Groww fundamentals + scraping

**[Shipped]**
- Groww `__NEXT_DATA__` parser for fund pages ([services/groww_client.py](backend/services/groww_client.py))
- COALESCE-preserving upserts via `pg_writer.persist_scrape()` — partial scrapes never null out existing data
- Sibling-fund chase (Regular ⇄ Direct plan resolution)
- Equity stock scraper ([services/groww_stock_scraper.py](backend/services/groww_stock_scraper.py)) for stock fundamentals (PE, PB, ROE, ROCE, debt, promoter holding, eps growth, etc.)
- Refresh rate-limit + admin trigger via `/api/portfolio/refresh-stock-fundamentals` and `/api/admin/data-pipeline/groww-refresh-all`
- 38-column `mutual_fund_metadata` table populated from a single scrape pass

**[Pending]**
- Groww layout changes break the parser ~quarterly — needs an automated regression test
- No fallback scraper if Groww blocks (MoneyControl client exists but isn't wired in primary path)
- Stock fundamentals refresh is full-portfolio, not delta — wasteful for re-runs

---

#### 14.B4 Equity stock data (Morningstar + sector + benchmarks)

**[Shipped]**
- `stock_master` (NSE symbol → name, sector, cap bucket, ISIN) seeded from a canonical list ([migration 008](backend/migrations/008_equity_scoring.sql))
- `stock_primitives` table — 30+ raw signals per stock (PE, PB, ROE, EPS growth, debt trends, momentum, dividend, beta, drawdown, etc.)
- Morningstar quantitative star rating end-to-end ([services/morningstar_stock_client.py](backend/services/morningstar_stock_client.py), [migration 010](backend/migrations/010_stock_morningstar.sql))
- Sector classification via `equity_sectors.py` ISIN map (covers Nifty 100 + most Nifty 500)
- Stock refresh job log ([migration 011](backend/migrations/011_stock_refresh_job_log.sql))
- Admin endpoint to trigger Morningstar refresh for the entire equity universe

**[Pending]**
- Sector map is hand-curated — drift over time when stocks change sector
- ISIN map only covers ~Nifty 500; small-cap stocks fall through to "Other"
- No fundamentals as-of-date tracking — assume "latest scrape = current truth"

---

#### 14.B5 Benchmark indices

**[Shipped]**
- yfinance ingester for 4 core indices (NIFTY_50, NIFTY_MIDCAP_150, NIFTY_SMALLCAP_250, NIFTY_500) plus sector indices ([services/benchmark_index.py](backend/services/benchmark_index.py))
- Per-index OHLC + computed metrics (1d/1m/3m/6m/1y/3y/5y returns, volatility, drawdown, max drawdown)
- Redis cache layer with TTL invalidation on refresh
- Daily 18:30 IST refresh + admin-triggered manual refresh via `POST /api/index/refresh`
- Casing-safe lookups (the original `nifty_50` vs `NIFTY_50` bug fixed)
- Benchmark proxy mapping for fund categories ([migration 006](backend/migrations/006_benchmark_proxy_mapping.sql)) — "Flexi Cap" → "NIFTY 500", "Banking" → "NIFTY BANK", etc.

**[Pending]**
- Sector indices ingest is on the same yfinance path — fragile when yfinance changes ticker symbols
- No alternate source (NSE archive direct CSV) wired as fallback
- Refresh button on Underperformers card works but doesn't surface progress for slow yfinance pulls

---

#### 14.B6 Bhavcopy + delivery (positional engine source)

**[Shipped]**
- NSE `sec_bhavdata_full_DDMMYYYY.csv` ingester with EQ/BE filtering ([services/positional_engine/bhavcopy_ingester.py](backend/services/positional_engine/bhavcopy_ingester.py))
- 87-day backfill (Jan 2026 → May 2026) populated `stock_ohlcv` with ~220k rows
- Holiday-aware (skips weekends; 0-row days log a warning)
- Per-symbol delivery_pct + delivery_qty preserved alongside OHLCV
- Source-tagged ingest (`source='bhavcopy' | 'manual' | 'broker'`)

**[Pending]**
- F&O bhavcopy (OI + open-interest changes) — not ingested
- BSE bhavcopy (backup source) — not wired
- Adjusted prices (post-split, post-bonus) — not yet — currently raw close
- NSE archive 403/503 handling is best-effort; the resilient retry framework lives in §14.J5

---

### C · Scoring layers

#### 14.C1 V3 Fund Scoring (Quality / Health / Exit / Add)

**[Shipped]**
- 4 orthogonal composites computed deterministically from 38 primitives ([services/v3_scoring.py / stock_scoring.py](backend/services/stock_scoring.py))
- Quality (long-term strength) — ROE, debt-to-equity, EPS growth, promoter holding, market-cap stability, earnings consistency
- Health (current trajectory) — revenue growth, margin trend, debt trend, earnings surprise, volatility, dividend yield
- Exit (sell-signal) — PE overvaluation, earnings decline, quality deterioration, debt spike, liquidity risk, tax impact
- Add (buy/top-up signal) — sector gap, low overlap, relative valuation, quality, momentum, dividend
- Weights editable via admin UI ([routes/admin_v3_weights.py](backend/routes/admin_v3_weights.py)) — persisted to `system_config.v3_weights` Mongo doc
- Switch decision taxonomy — 5-bucket peer-fund hydrator ([services/candidate_fund_hydrator.py](backend/services/candidate_fund_hydrator.py))
- Per-fund Redis cache ([services/v3_score_cache.py](backend/services/v3_score_cache.py)) with TTL = `V3_SCORE_TTL_S` (default 24h)
- Score breakdown JSON in `stock_scores.{quality,health,exit,add}_components` for UI explainability
- Recommendation: BUY / HOLD / TRIM / EXIT / REVIEW with deterministic reason text
- Low-confidence flag when too many primitives are null

**[Pending]**
- Weights tuning is admin-driven, not learned from outcomes
- 38 primitives is a lot — some sub-factors haven't been backtested individually
- Score doesn't account for fund mandate violations (e.g. "Multi-Cap" fund holding 95% large-cap)

---

#### 14.C2 V3 Stock Scoring (parked)

**[Shipped]**
- Stock-level primitives + composites infrastructure ([services/stock_scoring.py](backend/services/stock_scoring.py)) using the same V3 framework
- `stock_scores` table parallels `mutual_fund_v3_scores`
- Admin UI for stock weights ([routes/admin_v3_stock.py](backend/routes/admin_v3_stock.py))
- Morningstar rating column appended to enable cross-validation

**[Pending — explicitly parked per Feb 2026 design call]**
- Recommendation logic (BUY/HOLD/etc.) is **disabled** for stocks pending the equity decision engine; the UI shows score breakdown only
- Per-row decision card on stocks shows scores but no action verb
- Equity decision engine (§14.D2) needs to be built before this lights up

---

#### 14.C3 Portfolio intelligence (overlap + concentration)

**[Shipped]**
- Stock-level overlap detection across funds ([services/portfolio_intelligence.py](backend/services/portfolio_intelligence.py)) — flags when 2+ funds hold >70% identical stocks
- AMC concentration check — alerts when one AMC owns >30% of MF book
- Category over-concentration (e.g. 60% in Small Cap)
- Sector concentration via `equity_sectors.ISIN_SECTOR_MAP`
- Duplicate-fund detection (Regular vs Direct of the same scheme) with auto-AMC normalisation
- `portfolio_intelligence` table caches the analysis per portfolio for fast reads

**[Pending]**
- Overlap doesn't account for partial-position weights — flags "high overlap" even when the matching stocks are 1% positions
- Sector concentration uses a hand-curated map; small-caps fall through
- No "ideal allocation" computation per risk profile — caller must decide

---

#### 14.C4 Tax-aware decisions

**[Shipped]**
- ClearTax FY25-26 tax rules ([services/tax_calculator.py](backend/services/tax_calculator.py)) — LTCG (12.5% > ₹1.25L), STCG (20%), debt fund slabs, ELSS lock-in
- Per-holding tax impact computed on every recommendation (Exit / Switch)
- Switch cost framework ([memory/TAX_AWARE_FINAL_DECISION.md](memory/TAX_AWARE_FINAL_DECISION.md)) — 3-threshold rule for whether to switch given tax drag
- `SwitchCostPanel` UI on every holding row showing % cost + ₹ amount
- Buy-date tracking on holdings (inline editor, drives LTCG/STCG split)
- `cost_basis_from_snapshots` recovers buy_date when CAS doesn't ship it

**[Pending]**
- Tax rules are hardcoded — needs admin-editable config when FY26-27 lands
- No partial-redemption optimization (sell only the LTCG-eligible portion to minimise tax)
- No tax-loss harvesting suggestions

---

#### 14.C5 Switch cost framework

**[Shipped]**
- Switch cost % = expense delta + redemption load + tax drag − expected alpha ([services/decision_engine_actions.py](backend/services/decision_engine_actions.py))
- 3 threshold rules — auto-recommend switch when cost <X% AND alpha >Y%
- Per-holding panel showing the math, not just the verdict ([components/insights/SwitchCostPanel.jsx](frontend/src/components/insights/SwitchCostPanel.jsx))
- Cost-of-switch UI rolled out across all action paths (not just MF rebalance)

**[Pending]**
- Expected alpha is a peer-cohort estimate; could be replaced with model-derived alpha when V3 scoring is backtested
- No "wait and see" recommendation — current logic is binary switch/hold

---

### D · Decision engines

#### 14.D1 V2 Action Plan Engine (7 rules)

**[Shipped]**
- Rule-based action plan generator ([services/action_plan_manager.py](backend/services/action_plan_manager.py))
- 7 rules in sequenced execution: Reg→Direct, AMC concentration, category drift, performance laggards, overlap collapse, debt allocation, hold-everything fallback
- DSL evaluator ([services/rules_dsl.py](backend/services/rules_dsl.py)) — whitelisted AST, no eval, admin-editable thresholds
- Admin Rules + Prompts editor ([routes/admin_rules.py](backend/routes/admin_rules.py))
- 7 LLM prompts + sandbox for narrative generation ([services/prompts_manager.py](backend/services/prompts_manager.py)) — prompts test as fixtures, never against live data
- Rule 3 (underperformers) uses V3 quality_issues + exit_score for stricter trigger
- Plan persists with versioning + feedback loop
- Frontend `PlanBoardView`, `PlanCard`, `PlanHeroCard` ([components/v2/](frontend/src/components/v2/))

**[Pending]**
- Rules are sequential, not weighted — a fund can be exited for one reason, missing the others
- Rule 6 (debt allocation) is conservative; doesn't account for client age + risk profile
- LLM prompt drift — narrative quality varies when LLM provider versions change

---

#### 14.D2 Decision engine (V3) — current

**[Shipped]**
- 5-bucket switch decision taxonomy ([services/decision_engine.py](backend/services/decision_engine.py)) — STAY / SWITCH-TO-DIRECT / SWITCH-TO-PEER / EXIT-TO-CASH / REVIEW
- Peer-fund hydrator ([services/candidate_fund_hydrator.py](backend/services/candidate_fund_hydrator.py)) — top-3 peer candidates per category with V3 score, alpha, expense delta
- Per-holding `DecisionCard` ([components/insights/DecisionCard.jsx](frontend/src/components/insights/DecisionCard.jsx)) answers 4 questions: Why · What to do · Cost & Tax · Worth it?
- Deviation engine ([services/deviation_engine.py](backend/services/deviation_engine.py)) — flags when a fund drifts from category/style mandate
- Holding-action-score ([services/holding_action_score.py](backend/services/holding_action_score.py)) — single 0-100 number summarising priority
- Priority engine ([services/priority_engine.py](backend/services/priority_engine.py)) — ranks the action plan items

**[Pending]**
- Stocks are **parked** — no equity decision verb (see §14.C2)
- Decision logic is per-holding; no portfolio-level "rebalance now" recommendation
- Behavioural overlay ([services/behavioural_signals.py](backend/services/behavioural_signals.py)) is wired but lightly used

---

#### 14.D3 Goal-based planning

**[Shipped]**
- Goal engine + fund picker ([services/goal_engine.py](backend/services/goal_engine.py), [goal_fund_picker.py](backend/services/goal_fund_picker.py))
- Goal copilot ([services/goal_copilot.py](backend/services/goal_copilot.py)) — guided goal-creation flow
- 3-tier goal model: target amount, target date, monthly SIP needed
- Per-goal tracking with on-track / off-track + corrective action
- Migration [007_goal_planning.sql](backend/migrations/007_goal_planning.sql)
- Frontend `GoalsView` + goal-specific Copilot route

**[Pending]**
- Goals don't yet auto-allocate from incoming SIPs — user manually maps
- No "merge goals" or "split goals" UI
- Tax-saving goals (ELSS) need special handling — currently mapped manually

---

### E · Frontend / UX

#### 14.E1 Portfolio page (two implementations live)

**[Shipped]**
- `ActionablePortfolioView` (default at `/portfolio` route) — V3 score columns, dual rating (Morningstar + Nivesh), action badges, expandable rows with `DecisionCard`, sub-category filter chips, asset-type tabs (All / Stocks / MFs / ETFs / Gold), search + sort
- `PortfolioView` (legacy, at `/portfolio_legacy`) — simpler holdings table + top movers chart
- Inline buy-date editor on every holding (drives LTCG/STCG)
- CAS upload + Gmail import + manual add buttons in header
- Export to CSV/XLSX ([routes/portfolio_export.py](backend/routes/portfolio_export.py))
- Duplicate-funds detection banner with normalised scheme key
- Refresh stock fundamentals button + spinner state
- Snapshot info banner — shows which CAS upload is currently authoritative

**[Pending]**
- Stocks tab still uses fund-style score columns even though the equity decision engine is parked
- No multi-select bulk action
- No per-asset chart drilldown (only the row expands; clicking the chart icon doesn't yet open a modal)

---

#### 14.E2 Insights views

**[Shipped]**
- `V3PortfolioInsights` — Quality / Health / Exit / Add summary at portfolio level
- `V3FundBreakdown` — sub-factor explainability per fund
- `DecisionCard` rolled out to every holding (replaces the old `DecisionVerdict` + `SwitchCostPanel` split)
- AI insights ([services/ai_insights.py](backend/services/ai_insights.py)) — deterministic insight builder seeds the LLM narrative
- `InsightsView` — sectional layout: Quality issues / Health gaps / Exit candidates / Add suggestions
- Discover International view ([components/insights/DiscoverInternationalView.jsx](frontend/src/components/insights/DiscoverInternationalView.jsx))

**[Pending]**
- Insights don't yet drive a notification feed
- No "insights since you last visited" diff

---

#### 14.E3 Action Plan board

**[Shipped]**
- `PlanBoardView` ([components/v2/](frontend/src/components/v2/)) — kanban-style board with EXIT / SWITCH / ADD / HOLD lanes
- `PlanCard` per recommendation with reason + cost + tax + alpha
- `PlanHeroCard` — top-of-page summary with confidence + amber warning when degraded
- Rules + Prompts editor (admin) — visual JSON editor with sandbox
- Plan feedback loop (👍/👎 + free-text) persisted for prompt-tuning

**[Pending]**
- Plan can't be exported to a brokerage order list yet
- No "execute via Angel One" button — out of scope for v1
- Feedback loop is captured but not yet feeding back into prompt selection

---

#### 14.E4 Risk profile flow

**[Shipped]**
- 12-question risk profile questionnaire ([components/RiskProfileView.js](frontend/src/components/RiskProfileView.js))
- Maps to Conservative / Moderate / Aggressive buckets
- Drives the `behavioural_signals` overlay + plan tone
- Re-takeable any time

**[Pending]**
- Profile doesn't yet drive automatic rebalancing suggestions
- No "your peers in your risk band" comparison

---

#### 14.E5 Onboarding

**[Shipped]**
- 4-step `OnboardingView` — name → CAS upload → risk profile → goals
- MFD/Advisor path branch on welcome screen
- CAS upload step links into the parser dispatch

**[Pending]**
- Onboarding doesn't yet personalise based on age (under-30 vs over-50 risk defaults)
- No "skip and explore" path — every step is mandatory

---

#### 14.E6 Nivesh Copilot (CIO assistant)

**[Shipped]**
- Embedded chat drawer ([components/NiveshCopilotDrawer.jsx](frontend/src/components/NiveshCopilotDrawer.jsx)) accessible from any page
- Grounded on the active plan + portfolio + V3 scores — no hallucinated numbers
- RAG retrievers ([services/copilot_rag/retrievers.py](backend/services/copilot_rag/retrievers.py)) for fund metadata, transactions, snapshots
- Intent router ([services/copilot_rag/intent_router.py](backend/services/copilot_rag/intent_router.py)) directs queries to the right retriever
- Orchestrator ([services/copilot_rag/orchestrator.py](backend/services/copilot_rag/orchestrator.py)) glues it all
- Chart blocks ([components/copilot/ChartBlock.jsx](frontend/src/components/copilot/ChartBlock.jsx)) — bar/donut/line/stacked_bar charts emitted by the LLM and validated server-side
- Prompts library editable by admin ([routes/copilot_prompts.py](backend/routes/copilot_prompts.py))

**[Pending]**
- No multi-turn memory across drawer-opens
- Chart spec is narrow (4 chart types) — doesn't support scatter, heatmap, candlestick
- No streaming responses — answer renders in one shot

---

#### 14.E7 Chat (legacy, separate from Copilot)

**[Shipped]**
- Standalone `ChatView` ([components/ChatView.js](frontend/src/components/ChatView.js)) accessible at `/chat` — pre-Copilot UI
- Auto-redirects to Copilot drawer when user lands on `/chat` directly

**[Pending]** — explicitly being deprecated; new work goes into Copilot only.

---

### F · MFD / multi-tenant

#### 14.F1 MFD workspace + profile

**[Shipped]**
- Workspace model ([services/mfd_workspace.py](backend/services/mfd_workspace.py)) — one MFD owns multiple client profiles
- Profile = a shadow user (synthetic email, no signin) with full portfolio + plans + insights
- Profile activation (impersonation) — `enterProfile(profile)` sets `active_profile_id` server-side; every subsequent API call returns the impersonated user's data
- `/auth/me` returns the shadow user when impersonating, so top-bar greeting reflects the active client
- `MfdDashboard` ([components/mfd/MfdDashboard.jsx](frontend/src/components/mfd/MfdDashboard.jsx)) — client list with portfolio summary
- Migration scaffolding for multi-client billing (not yet wired)

**[Pending]**
- No MFD-side analytics ("AUM growth across all clients") — partial via `/api/advisor/aum` but not surfaced in a dedicated view
- No client tagging / segmentation
- Client invite is uni-directional (MFD → client); no "request connection from client side"

---

#### 14.F2 Advisor home insight cards

**[Shipped]**
- `AdvisorHomeView` ([components/mfd/AdvisorHomeView.jsx](frontend/src/components/mfd/AdvisorHomeView.jsx)) — 4-card proactive grid
- **Today** card — clients meeting today / called recently / at risk
- **AUM** card — AUM movement, top contributors, churn
- **Underperformers** card — clients lagging Nifty 50 by ≥ N pp; with admin "Refresh NIFTY 50" button on missing-benchmark state
- **Rebalance** card — clients off target allocation by drift threshold
- Each row click → `enterProfile()` impersonation
- "Ask Copilot" deep-link per card

**[Pending]**
- "Risk attention" 5th card on the roadmap (specific compliance/risk flags)
- No saved-segments or filter chips
- No A/B test on which Copilot prompt converts a card-click into action

---

#### 14.F3 Client CAS invite

**[Shipped]**
- v2 invite flow with 24h expiry + consent banner + regeneration ([routes/client_cas_invite.py](backend/routes/client_cas_invite.py))
- Public route (no auth) for the client-side landing page
- Email-based delivery via Gmail API
- Audit trail of every invite + consent acceptance

**[Pending]**
- No SMS / WhatsApp delivery channel
- No "invite a list" bulk feature
- Consent revocation flow is admin-driven, not self-serve

---

### G · Admin

#### 14.G1 Admin panel (full surface)

**[Shipped]**
- Datastore tile ([routes/admin_datastores.py](backend/routes/admin_datastores.py)) — Mongo / Postgres / Redis health, secret rotation, restore button
- Data Pipeline tile ([routes/admin_data_pipeline.py](backend/routes/admin_data_pipeline.py)) — every job's last-run + duration + row counts + manual trigger
- V3 Master tile ([routes/admin_v3_master.py](backend/routes/admin_v3_master.py)) — fund universe management, force-rescore, low-confidence filter
- V3 Weights tile ([routes/admin_v3_weights.py](backend/routes/admin_v3_weights.py)) — sliders for sub-factor weights with live preview
- V3 Stock tile ([routes/admin_v3_stock.py](backend/routes/admin_v3_stock.py)) — stock universe + Morningstar refresh
- Rules tile ([routes/admin_rules.py](backend/routes/admin_rules.py)) — rule thresholds + DSL syntax check
- Users tile ([routes/admin_users.py](backend/routes/admin_users.py)) — whitelist + admin-toggle + invite

**[Pending]**
- Audit log viewer (data exists in `audit_log`; no UI surface yet)
- Secret rotation forces a server restart; should hot-reload
- No "what changed in the last 7 days" feed

---

### H · Compliance + cross-cutting

#### 14.H1 DPDP Act 2023 compliance

**[Shipped]**
- Consent collection on every onboarding step ([services/consents.py](backend/services/consents.py))
- Audit log for every consent + every PII operation ([services/audit.py](backend/services/audit.py))
- PII security helpers ([services/pii_security.py](backend/services/pii_security.py)) — redact, mask, hash
- PAN handling — never stored raw, hashed at write
- User-data export endpoint ([routes/compliance.py](backend/routes/compliance.py)) — full data download in JSON
- Consent revocation flow with cascade-delete

**[Pending]**
- No automated retention policy enforcement (e.g. delete CAS PDFs after N days)
- Audit log retention is unbounded — needs a sweep job
- No DPO alerting

---

#### 14.H2 Data health banner

**[Shipped]**
- Global stale-data warning banner ([routes/data_health.py](backend/routes/data_health.py)) — appears when AMFI NAV > 2 trading days old, or Morningstar refresh > 7 days old
- Banner is dismissible per-session
- Different copy for admin vs regular user

**[Pending]**
- No per-fund staleness flag (banner is portfolio-wide)
- No automated re-fetch trigger from the banner

---

### I · Market intelligence (macro + positional)

#### 14.I1 Macro Intelligence v1 — *2026-04 → ongoing*

**[Shipped]**
- 5-metric daily ingest (crude / USDINR / 10y / Nifty / VIX) with fallback chains and sanity gate ([services/macro_ingester.py](backend/services/macro_ingester.py))
- 4-axis regime classifier (Market / Inflation / Liquidity / Risk) → `macro_multiplier` ([services/macro_engine.py](backend/services/macro_engine.py))
- Sector heatmap with hardcoded sensitivity matrix + plain-English rationale per sector ([services/macro_sector.py](backend/services/macro_sector.py))
- Market Dashboard page composition with `MacroBar`, `TodayStrategyCard`, `SectorHeatmap`, `AlignedPicks`, `WhatChanged`, `MondayGamePlan`
- Admin "Refresh data" button on `MacroBar` → `POST /api/macro/refresh`
- 18:35 IST cron in `mf_scheduler` + remote-agent fallback `macro-daily-refresh` (weekdays 19:00 IST)
- Casing-safe `get_latest_index()` (case-insensitive lookup; original `nifty_50` vs `NIFTY_50` bug fixed)
- Migrations [016](backend/migrations/016_macro_intelligence.sql) + [017](backend/migrations/017_macro_global_indicators.sql)

**[Pending]**
- RBI 10y yield direct ingest (currently a stub — uses `^TNX` US 10y as a proxy)
- Sector sensitivity weights are hardcoded; needs admin UI to tune
- "Macro confidence" rendering on the dashboard (data is computed, UI surface is partial)
- WhatChanged daily diff is functional but doesn't yet drive a notification feed

---

#### 14.I2 Positional Engine v1 — *2026-05*

**[Shipped]**
- NSE bhavcopy ingester + 87-day backfill (2026-01 → 2026-05)
- Pure-Python feature math: SMA, EMA, RSI (Wilder), MACD, ATR, Bollinger, slope, returns, swing levels, volume Z, delivery trend (33 unit tests passing)
- 6-sub-score weighted final (trend / momentum / structure / accumulation / sector / risk) + stage classifier + confidence band
- Stage-aware trade planner (entry / SL / target / RR ≥1.5 floor) + macro-aware position-size factor
- Portfolio-aware annotation — overexposure warnings (35% sector / 8% per-stock)
- Migration [015_positional_engine.sql](backend/migrations/015_positional_engine.sql) (`stock_ohlcv` / `chartink_scan_hits` / `stock_technical_features` / `positional_signals` / `positional_outcomes`)

**[Pending]**
- `positional_outcomes` table is created but the daily evaluator job (target/SL hit detection over a 5/10/20-day horizon) is not wired
- Learning loop — outcomes table → weight adjustment is the v2 design; current weights are hardcoded
- F&O OI / open-interest signals — out of v1 scope (cash-side delivery % covers most positional setups)

---

#### 14.I3 Chartink integration v1 — *2026-05*

**[Shipped]**
- 11 saved scans (atlas.todays_top_buy + 10 BTST/positional setups from PRD spec) with full Chartink syntax stored in `system_config.chartink_scans`
- Polling client ([services/positional_engine/chartink_api.py](backend/services/positional_engine/chartink_api.py)) — `run_scan/run_scans` with session-cookie bootstrap + XSRF-TOKEN handling
- Per-scan CSV upload (`/scans/upload`) as the offline fallback path
- Auto-matched scan-name resolver — `"TODAYS TOP BUY"` → `atlas.todays_top_buy` via `scan_config.match_scan_name()`
- **Webhook receiver** (`POST /api/positional/chartink/webhook?token=…`) — production-grade real-time integration
- Token storage + rotation endpoint
- Admin UI card on the Picks panel — copy URL, Rotate button, inline instructions, auto-matched scan list

**[Pending]**
- Per-scan webhook URL (currently one shared URL for all alerts; scan_name matching does the routing). A per-scan token model would let you revoke one alert without breaking the others.
- HMAC signature verification — Chartink doesn't sign payloads, so URL token is the only auth. If Chartink ever ships signing, we should adopt it.
- Webhook event log table — currently we upsert hits into `chartink_scan_hits` but don't keep raw event audit. Useful for compliance / debugging.

---

#### 14.I4 Picks UI v2 — *2026-05*

**[Shipped]**
- Card / Table view toggle on the picks panel
- "+" / "Show more" button — 12 → 30 → 60 → 100 picks
- Live LTP overlay + readiness chip (TRIGGERED / NEAR / WAIT / FAR / STOPPED) with auto-poll every 60s during IST market hours
- Scan criteria panel — collapsible per-scan condition lists, click to expand
- Source-scan chips on each card (e.g. `near_breakout`, `inside_day`)
- min_score floor lowered to 0.45 (was 0.55) so picks always render under HIGH-risk macro multiplier
- Stocks-tab gating in `ActionablePortfolioView` (hidden on MF / ETF / Gold tabs)
- Empty-state copy with admin-vs-user variants

**[Pending]** — these were in the user's UI uplift spec but not yet shipped:
- Playbook header (Bias / Aggression / Max Trades / Focus / Avoid as a sticky strip above picks)
- Hero / Secondary / Watchlist priority layout (currently single equal-priority list)
- Distance-to-trigger explicit display ("Breakout level / Current / Distance −1.1%")
- Execution rules per trade ("Skip if gap-up >2%", "Enter only above ₹X")
- "What changed since yesterday" on the picks panel (the macro version exists; per-pick diff is pending)
- Mini sparkline (last 20 days) on each card
- Portfolio Impact view ("If you take all trades: Total Exposure 80% · Sector Concentration Banking 40%")

---

### J · Roadmap — NIDP (Nivesh Intelligence Data Platform)

**Scope per the May 2026 PRD** — building the data backbone, not just analytics. Sequenced *after* the in-flight UI uplift.

#### 14.J1 Snapshot Engine *(highest priority)*

**[Pending]** — `stock_daily_snapshot(symbol, as_of_date, price, delivery_pct, fii_dii_flow, sma_50, sma_200, rsi_14, atr_14, return_5d_pct, score, stage, …)` materialised from existing tables with carry-forward rules for non-daily data. Eliminates "mixed timelines" risk — every consumer reads from one frozen as-of row instead of joining 5 tables on every call.

#### 14.J2 Data validation framework

**[Pending]** — assert row_count > 1500 on bhavcopy; assert promoter+fii+dii+public ≈ 100 on shareholding; reject before insert; log to `validation_log` with severity + rule + actual vs expected. Per-source rule sets.

#### 14.J3 Observability

**[Pending]** — `jobs_success_total` / `jobs_failed_total` / `data_freshness_minutes` Prometheus-style metrics; admin Grafana-style dashboard with bhavcopy / delivery / failure / delay panels. Alert on freshness > 24h.

#### 14.J4 Failure classification

**[Pending]** — typed errors (NSE_DOWN → retry, PARSER_FAIL → fix, DATA_MISMATCH → block + alert) instead of single-bucket fail. Each type has its own retry policy.

#### 14.J5 NSE hardening

**[Pending]** — rotating user agents, session reuse, retry windows on 403/503, optional proxy rotation. Currently the bhavcopy ingester is best-effort.

#### 14.J6 FII/DII flow ingester

**[Pending]** — daily NSE archive `fii_stats_YYYYMMDD.xls` → `fii_dii_flows(date, segment, fii_buy, fii_sell, fii_net, dii_buy, dii_sell, dii_net)`.

#### 14.J7 Shareholding poller

**[Pending]** — quarterly NSE corporate-filings page, change detection via hash, alert on promoter pledge spikes.

#### 14.J8 Bulk/block deals ingester

**[Pending]** — `bulk.csv` + `block.csv` daily → `bulk_deals` + `block_deals` tables.

#### 14.J9 Corporate actions feed

**[Pending]** — event-driven, polled every 30–60 min → `corporate_actions(symbol, ex_date, type, value, narration)`.

#### 14.J10 StockEdge cross-check

**[Pending]** — field-level diff with tolerance bands; `quality_score` per symbol-day. Validation only, never a primary source.

---

#### 14.I5 Pre-breakout accumulation detector + backtest calibration — *2026-05*

The signal-quality leap from "show me what's breaking out" to "show me what's about to break out". Three-layer design (per the user's quant-system spec):

| Layer | What it does | Status |
|---|---|---|
| 1. Accumulation detection | 4 named pre-breakout signals, fed by existing feature pack | ✅ shipped |
| 2. Trigger detection | Stage classifier + Chartink confirmation | ✅ already shipped (§14.I2) |
| 3. AI confidence | Bucketed empirical hit-rate from labelled backtest | ✅ deterministic v1 shipped; ML calibration v2 pending |

**[Shipped]**

*Detector* ([services/positional_engine/accumulation_detector.py](backend/services/positional_engine/accumulation_detector.py))

- 4 named pre-breakout signals, each `(fired, strength)`:
  - `vol_divergence` — volume Z > 1.0 AND |slope| < 0.1%/bar (volume rising while price stays flat → smart-money accumulation)
  - `delivery_spike` — delivery-trend > +15% AND slope ≤ 0.3%/bar (rising delivery during sideways action — India-specific edge)
  - `bb_squeeze` — BB width < 8% AND ATR% < 2.5% (compression always precedes expansion)
  - `sector_lag` — stock 20d return < bench 20d return × 0.4 AND above SMA50 (catch-up trade)
- Composite `accumulation_score` with **confirmation factor** — rewards multiple signal confirmation over one isolated strong signal. Mapping: 1→0.5×, 2→0.85×, 3→1.0×, 4→1.05×.
- `is_early_opportunity` flag when score ≥ 0.55

*Pipeline integration* ([pipeline.py](backend/services/positional_engine/pipeline.py))
- Every scored symbol now carries a `pre_breakout` block — signals list + accumulation_score + early_opportunity flag
- Persisted in `stock_technical_features.components` JSONB (no migration needed)
- Pre-breakout signal names appended to the human-readable `reasons` list when fired

*Backtest framework* ([backtest.py](backend/services/positional_engine/backtest.py), [migration 018](backend/migrations/018_positional_backtest.sql))
- `label_universe()` — sweeps every (symbol, date) in `stock_ohlcv` history, replays the detector against bars-as-they-were-on-that-date, looks forward 5/10/20 trading days, records realised max-return + max-drawdown, and a binary "moved ≥5%" label per horizon
- `positional_backtest_labels` table — labelled training set; (symbol, scan_date) PK
- `calibrate()` — buckets the labelled rows by accumulation_score (7 buckets, 3 horizons) and stores the empirical hit-rate per bucket per horizon → `accumulation_calibration` table
- `probability_of_move(score, horizon)` — bucket lookup that converts a live accumulation score into "47% chance of ≥5% move within 10 days, based on 1,234 historical setups"

*API* ([routes/positional.py](backend/routes/positional.py))
- `POST /api/positional/backtest/label` *(admin)* — kick off a label sweep (params: `max_symbols`, `step_days`)
- `POST /api/positional/backtest/calibrate` *(admin)* — rebuild calibration table from latest labels
- `GET /api/positional/backtest/calibration` *(auth)* — return the bucketed hit-rate table for UI display
- `/api/positional/picks/mine` now returns `pre_breakout` block per pick (LEFT JOIN on `stock_technical_features`)

*UI three-rail layout* ([PositionalPicks.jsx](frontend/src/components/PositionalPicks.jsx))
- 🔥 **Early Opportunities** — `accumulation_score ≥ 0.55 AND stage = ACCUMULATION`. Indigo header. Where the actual alpha lives.
- ⚡ **Active Trades** — `stage in (BREAKOUT, EARLY_BREAKOUT)` or weak-pre-breakout actionables. Emerald header.
- 🧊 **Avoid Zone** — `stage in (EXTENDED, WEAK)`. Slate header, collapsed by default, opacity-60 when expanded.
- Each card shows the fired pre-breakout signals as indigo chips + the % accumulation score in the chip header
- 13 new unit tests (49 → 49 passing total in [tests/test_positional_engine.py](backend/tests/test_positional_engine.py))

**[Shipped — calibration v2, 2026-05]**

After the v1 calibration run revealed an inverted hit-rate (low-score buckets had the highest "moved ≥5% in 10d" rate), we sat with the data and figured out the v1 outcome metric was wrong, not the detector. Migration [019_positional_backtest_v2.sql](backend/migrations/019_positional_backtest_v2.sql) adds three metrics to disentangle the issue:

| Metric | Definition | Purpose |
|---|---|---|
| `moved_5pct` (v1) | `fwd_max_return ≥ 5%` (fixed) | Backwards-compat. Baseline noise. |
| `moved_scaled` | `fwd_max_return ≥ max(5%, atr_pct × 3)` | Vol-aware "expansion" — high-vol stocks need bigger moves to count. |
| **`broke_high`** | Forward bar's high crosses scan_date's 20d-high | The actual breakout event. Scale-invariant. **Default metric for `probability_of_move`.** |

`accumulation_calibration` table now keys on `(metric, bucket_lo, bucket_hi, horizon_days)` so all three live alongside each other. `probability_of_move(score, horizon, metric=…)` API takes a metric arg.

**Honest finding from the 87-day, 56,831-label sweep**

In an 87-day strong-bull-tape sample:
- `broke_high` 20d shows a **U-shape**, not a monotonic curve. Top accumulation buckets (0.65–0.85) sit at 55–62% probability of breaking high; baseline (no signal) sits at 76%.
- `moved_scaled` is **monotonically inverse** — top buckets move less in absolute terms because by construction they're tight-range stocks. This is the detector working as designed — it identifies *what won't move violently*, which has portfolio-management value (lower drawdown, cleaner stops) but isn't a "probability of move" lift over baseline.

**What this means**

- The infrastructure is correct; the empirical lift is dilute in a strong bull tape because **baseline is already very high** (76% of stocks break their 20d-high within 20 days when the index is up).
- Real validation needs **≥1 year of OHLCV** spanning regimes (bull / sideways / bear). The detector's edge probably manifests in non-bull tapes.
- UI should NOT surface a "P(move) 84%" calibrated probability today — it would be misleading. Stick to honest framing: signal count + named signals + setup quality, not a calibrated probability we can't yet defend over baseline.

**[Pending — sequenced post-v2 finding]**

- **OHLCV backfill to 2 years** — single biggest lever. Strong-bull 87-day sample doesn't show edge; longer history with regime mix probably does.
- **Regime-conditional calibration** — split the calibration table by macro regime (BULL/BEAR/NEUTRAL on scan_date). Probable result: detector has stronger lift in non-bull tapes.
- **Drop `probability_of_move` UI surface** until v3 calibration shows a real lift over baseline. The 4-signal-chip UI we already have is honest and informative as-is.
- **ML calibration (v3)** — once OHLCV is 2 years deep AND we have regime-conditional calibration, swap the bucketed lookup for a calibrated logistic regression / gradient boosting model with proper cross-validation and Brier-score evaluation.
- **Sector-lag signal upgrade** — currently approximated using Nifty-50 as the bench (gives directional intuition but blurs sector-specific lag). Needs per-sector index OHLC ingester to be fully accurate. The signal is flagged in the `components` blob so the upgrade is non-breaking.
- **F&O accumulation signal** — OI rising while price range-bound is a strong institutional-positioning signal but requires F&O bhavcopy ingest, which is out of v1 scope.
- **Backtest scheduling** — currently admin-triggered. Should run nightly after the daily pipeline (label new day's outcomes, re-calibrate weekly). Needs a cron entry in `mf_scheduler.py`.
- **Behavioural features** — retail participation spike, prior-breakout success rate per symbol — listed in the user's spec but require additional data sources (broker order-flow, historical signal outcomes per symbol).

---

#### 14.I6 Conviction framework v1 — *2026-05*

The user's quant-system feedback caught a real bug: ASTERDM at +12.8% past entry was showing as 🟢 TRIGGERED with MEDIUM confidence — i.e. the panel was treating "blew past entry by 30%" identically to "just crossed entry". Fixed by introducing a 4-pillar conviction score with hard penalties + a readiness-based cap.

**[Shipped]**

*Pillars + penalties* ([services/positional_engine/conviction.py](backend/services/positional_engine/conviction.py))

- 4 pillar scores (each 0–100): **trend** (30%), **volume** (25%), **structure** (25%), **rr** (20%)
- Penalties (point deductions from base score):
  - `extended_chasing` — LTP > 15% past entry → −25
  - `extended_late` — LTP 8–15% past entry → −15
  - `overbought_rsi` — RSI > 75 → −15
  - `high_rsi` — RSI 70–75 → −8
  - `recent_spike` — 5d return > 12% → −10
  - `above_breakout` — already 5%+ above 20d high → −10
- Multi-scan bonus — 1 scan +3, 2 scans +6, 3+ scans +10 (signal clustering as alpha)
- Final verdict: **HIGH_CONVICTION** (≥65) · **SETUP_FORMING** (45–65) · **AVOID_LATE** (<45)

*Hard cap by readiness* — the breakthrough fix. Score alone wasn't enough to demote a clean-but-extended setup; now:
- LTP > 15% past entry → forced `AVOID_LATE` regardless of score
- LTP 8–15% past entry → capped at `SETUP_FORMING`

*Readiness bucketing v2* ([routes/positional.py:_readiness()](backend/routes/positional.py))
- New `LATE` bucket — LTP > entry × 1.08 (was missing; everything past entry was `TRIGGERED`)
- `TRIGGERED` now means "0 to +8% above entry" — actionable now, not chasing

*API integration* — `picks/mine?live=true` now returns a `conviction` block per pick:
```json
{
  "verdict": "HIGH_CONVICTION",
  "final_score": 81.7,
  "pillars": {"trend": 86, "volume": 75, "structure": 66, "rr": 54},
  "penalties": [],
  "scan_bonus": 3,
  "reasons": ["Strong trend (above 50/200 DMA)", "Volume confirms (rising delivery)"]
}
```
Best-effort — yfinance hiccup degrades to `conviction: null`, never breaks the response.

*UI three-rail v2* ([PositionalPicks.jsx](frontend/src/components/PositionalPicks.jsx))
- Each card now leads with a verdict badge — 🟢 HIGH CONVICTION / 🟡 SETUP FORMING / 🔴 AVOID/LATE — with the 0–100 final score
- Rails are now keyed on **verdict** (not stage): `🟢 High Conviction` / `🟡 Setup Forming` / `🧊 Avoid Zone`
- LATE readiness chip (rose) replaces the misleading green TRIGGERED for stocks 8%+ past entry
- LTP delta vs entry colours red when ≥+8% (previously emerald regardless of distance)

*Tests* — 6 new conviction tests covering: clean setup → HIGH_CONVICTION; same setup +12% extended → SETUP_FORMING (capped); +20% extended → AVOID_LATE; weak pillars → AVOID_LATE; RSI 78 penalty fires; multi-scan bonus lifts borderline picks. **56/56 passing**.

**Verified on live preview env**

| Symbol | LTP +% | Old conf | New verdict |
|---|---|---|---|
| TATATECH | +3.5 | LOW | 🟢 HIGH_CONVICTION (81.7) |
| HEMIPROP | +1.5 | MEDIUM | 🟢 HIGH_CONVICTION (75.7) |
| **ASTERDM** | **+12.8** | **MEDIUM** | 🟡 **SETUP_FORMING** (68.7, capped) |
| **QUESS** | **+30.0** | **MEDIUM** | 🔴 **AVOID_LATE** (59.8, capped) |
| **INOXWIND** | **+33.0** | **LOW** | 🔴 **AVOID_LATE** (60.0) |

The bold rows are the bug fix in action. The fix produces 8 high-conviction / 1 setup-forming / 6 avoid-late on today's 15-pick sample — much closer to the user's "2-3 high conviction, not 10 mediocre" target.

**[Pending]**

- **Gap-up detection** — current `recent_spike` proxy uses 5d return >12%. A proper gap-up check needs the open price vs prior close, which the trade-plan API doesn't yet expose. Per-bar gap detection in `feature_calculator.py` is the upgrade.
- **Near-resistance penalty** — flagged in user spec but needs intraday support/resistance levels beyond `high_20d` / `swing_high_20`. Pivot-point computation lives in features but isn't surfaced as a "distance to next R" yet.
- **Sector momentum integration** — already in scoring (sector pillar in `scorer.py`), but conviction's `volume` pillar should pull from sector strength too. Currently only Z-score + delivery.
- **Backtest the verdicts** — once conviction is in production for ≥1 month of decisions, sweep `positional_signals` for verdicts and check whether HIGH_CONVICTION outcomes really do beat SETUP_FORMING. Adds another row to `accumulation_calibration` keyed by verdict.

---

### 14.99 In-flight (mid-conversation, not yet shipped)

- Playbook header + hero/secondary/watchlist split (UI uplift §1, §2 — see [14.I4 Pending](#14i4-picks-ui-v2--2026-05))
- Trade readiness banner aggregation across picks (UI uplift §3 — partially shipped via per-card chip)
- Per-pick distance-to-trigger / execution rules / position size display (UI uplift §4, §6, §7)
- ML model on top of empirical calibration (§14.I5 Pending)
- `probability_of_move` rendered on each card (§14.I5 Pending)

---

## 15. Further reading

- **`/app/docs/FUNCTIONAL_DOCUMENT.md`** — *non-engineer friendly* what / how / why / unique. Start here if you're new to the project or doing a stakeholder pitch.
- **`/app/docs/TECHNICAL_SPEC.md`** — product spec, API surface, flows, testing
- **`/app/memory/PRD.md`** — session-by-session changelog + backlog
- **`/app/memory/V2_ACTION_GENERATION_RULES_COMPLETE.md`** — rule-engine spec
- **Excel**: V3 scoring sheet (Sheet1 inputs, weight tables, Switch + Guardrails) — source of truth for composite formulas
