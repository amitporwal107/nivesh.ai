# FRD — NIDP Project (Nivesh Intelligent Data Platform)
**Document Version:** 1.0  
**Date:** 2026-05-14  
**Status:** VALIDATED AGAINST CODE  
**Layer:** 8 of 8 — NIDP Project

---

## Document Notes

NIDP is an **isolated subproject** under `backend/nidp/`. It is a standalone data warehouse and ingestion platform that runs independently of the main Nivesh application. It deploys as Cloud Run jobs on GCP project `niveshdataintelligence` (region `asia-south1`) and exposes a DaaS (Data-as-a-Service) API consumed by the Nivesh app and external clients.

**Codebase root:** `backend/nidp/`  
**Admin surface:** `backend/routes/admin_nidp.py`, `admin_nidp_backfill.py`, `admin_nidp_replay.py`  
**Database:** TimescaleDB-pg16 on VM `nidp-stack-vm`, schema `nidp`  
**Event bus:** Redpanda (Kafka-compatible) on same VM  
**Storage:** GCS bucket `nidp-raw-niveshdataintelligence`  
**Observability:** Prometheus + Grafana on VM; `nidp.v_feed_status` single-pane DB view

---

## Requirements Index

| ID | Requirement | Status |
|---|---|---|
| FR-NIDP-001 | Ingester Base Contract | IMPLEMENTED |
| FR-NIDP-002 | Phase 1A Core Market Data Ingesters (13) | IMPLEMENTED |
| FR-NIDP-003 | Phase 1B Fundamentals Ingesters | IMPLEMENTED |
| FR-NIDP-004 | S4 Corporate Announcements Pipeline | IMPLEMENTED |
| FR-NIDP-005 | Mutual Fund Pipeline | IMPLEMENTED |
| FR-NIDP-006 | Corporate Event Intelligence Pipeline | IMPLEMENTED |
| FR-NIDP-007 | Post-Ingestion Quality Pipeline | IMPLEMENTED |
| FR-NIDP-008 | Intelligence Layer (Phase 2) | IMPLEMENTED |
| FR-NIDP-009 | Validation Engine (BLOCK / FIX / WARN) | IMPLEMENTED |
| FR-NIDP-010 | Per-Feed Validation Rules | IMPLEMENTED |
| FR-NIDP-011 | Storage Architecture (3 layers) | IMPLEMENTED |
| FR-NIDP-012 | Snapshot Builder | IMPLEMENTED |
| FR-NIDP-013 | Avro Schema Contracts (24 contracts) | IMPLEMENTED |
| FR-NIDP-014 | NIDP CLI | IMPLEMENTED |
| FR-NIDP-015 | Database Migrations (35 SQL files) | IMPLEMENTED |
| FR-NIDP-016 | DaaS API + Key Management | IMPLEMENTED |
| FR-NIDP-017 | Backfill Orchestration | IMPLEMENTED |
| FR-NIDP-018 | Replay Engine | IMPLEMENTED |
| FR-NIDP-019 | Feature Flags | IMPLEMENTED |
| FR-NIDP-020 | GCP Deployment (Cloud Run + Scheduler + Build) | PARTIAL |
| FR-NIDP-021 | Observability (Grafana + Prometheus + job_log) | PARTIAL |
| FR-NIDP-022 | Admin API Surface | IMPLEMENTED |
| FR-NIDP-023 | S5 Document Intelligence (pgvector) | IMPLEMENTED |
| FR-NIDP-024 | Portfolio Bridge | IMPLEMENTED |
| FR-NIDP-025 | Test Suite | IMPLEMENTED |

---

## FR-NIDP-001 — Ingester Base Contract

### Description
Every NIDP ingester subclasses `nidp.shared.ingester_base.BaseIngester` and implements four abstract methods: `fetch`, `parse`, `validate`, `persist`. The base class provides a standardised lifecycle wrapping all four steps.

### Functional Requirements

**FR-NIDP-001.1 — JobRun Lifecycle**  
The base class manages exactly one `nidp.job_log` row per invocation, progressing through states: `RUNNING → OK | PARTIAL | FAILED | SKIPPED`.
- `OK`: all 3 validation checks pass, Kafka event emitted
- `PARTIAL`: FIX-class validation findings; rows persisted but flagged
- `FAILED`: exception or BLOCK-class finding; Kafka emit suppressed
- `SKIPPED`: fetch succeeded but parser returned 0 rows (legitimate on weekends/holidays)

**FR-NIDP-001.2 — Raw Archive**  
Every fetched response is SHA-256 hashed, de-duplicated, and pushed to GCS at:  
`gs://nidp-raw-niveshdataintelligence/<ingester>/<YYYY>/<MM>/<sha12>.<ext>`  
The `nidp.raw_archive_files` table indexes each file by `(ingester, target_date, sha256)`. Enables parser replay without re-fetching upstream.

**FR-NIDP-001.3 — Parsed Archive**  
Normalised rows (post-parse + validate) are serialised to gzipped JSONL on GCS at:  
`gs://nidp-raw-niveshdataintelligence/parsed/<ingester>/<YYYY>/<MM>/<sha12>.jsonl.gz`  
Indexed in `nidp.parsed_archive_files`. Enables model rebuilds without re-parsing.

**FR-NIDP-001.4 — Kafka Emit**  
On `OK`, emits Avro-serialised `IngestionCompleted` event on topic `nidp.ingestion_completed.v1` via Redpanda + Confluent Schema Registry. Event is suppressed on `FAILED` to prevent downstream consumption of condemned data.

**FR-NIDP-001.5 — Source Registry Rollup**  
After each run, updates `nidp.source_registry`: `success_count`, `failure_count`, `partial_count`, `last_run_status`, `last_run_at`, `next_run_at` (derived from `expected_freq`), `consecutive_failures`.

**FR-NIDP-001.6 — Market Session Bump**  
The bhavcopy ingester (and only bhavcopy) bumps `nidp.market_session_state` on success, recording the "last NSE close" date. All date-defaulting ingesters read this table to determine their default `target_date`.

**Source:** `backend/nidp/shared/ingester_base.py`

---

## FR-NIDP-002 — Phase 1A Core Market Data Ingesters

### Description
13 ingesters forming the core daily market data pipeline for the Indian equity market.

### Ingester Registry

| # | Name | Source | Cadence | Domain Table |
|---|------|--------|---------|--------------|
| 1 | `bhavcopy` | NSE archives — `BhavCopy_NSE_CM_*.csv` | Daily ~18:00 IST | `nidp.prices_eod` (source=`NSE_BHAV`) |
| 2 | `delivery` | NSE archives — delivery columns CSV (T+1) | Daily ~10:30 IST next day | `nidp.delivery_data` |
| 3 | `index_close` | NSE archives — `ind_close_all_DDMMYYYY.csv` | Daily ~19:00 IST | `nidp.index_eod` |
| 4 | `index_constituents` | NSE archives — `ind_<index>list.csv` per index | Monthly 1st | `nidp.index_constituents` |
| 5 | `fii_dii` | NSE rolling JSON `/api/fiidiiTradeReact` | Daily ~19:30 IST | `nidp.fii_dii_flows` |
| 6 | `corporate_actions` | NSE JSON `/api/corporates-corporateActions` | Daily ~20:00 IST | `nidp.corporate_actions` |
| 7 | `nse_calendar` | NSE JSON `/api/holiday-master?type=trading` | Monthly 1st | `nidp.nse_holidays` |
| 8 | `bulk_deals` | NSE JSON `/api/historical/bulk-deals` | Daily ~19:30 IST | `nidp.bulk_deals` |
| 9 | `block_deals` | NSE JSON `/api/historical/block-deals` | Daily ~19:30 IST | `nidp.block_deals` |
| 10 | `rbi_yields` | RBI WSS HTML `WSSViewDetail.aspx` | Weekdays ~20:30 IST | `nidp.rbi_yields` |
| 11 | `fred_macro` | FRED CSV `fredgraph.csv?id=<series>` | Daily ~21:00 IST | `nidp.fred_macro_observations` |
| 12 | `yfinance_backfill` | Yahoo Finance per-symbol chart API | Manual / event-driven | `nidp.prices_eod` (source=`YFINANCE`) |
| 13 | `snapshot_builder` | Reads from domain tables above | Daily ~22:00 IST | `nidp.market_daily_snapshot`, `nidp.stock_daily_snapshot` |

### Functional Requirements

**FR-NIDP-002.1 — bhavcopy Filter**  
Parser filters to `Sgmt=CM` and `FinInstrmTp ∈ {STK, EQ}` only. F&O rows are discarded. Approximately 2,000 EQ rows per trading day.

**FR-NIDP-002.2 — fii_dii Normalisation**  
Ingests `EQUITY_CASH` category only (new NSE endpoint dropped F&O flows). FII and FPI are folded into a single `FII` category.

**FR-NIDP-002.3 — rbi_yields Dual Layout**  
Parser handles two HTML table layouts from the RBI WSS page: daily-rows format AND weekly-columns format. Parses 5 instruments: G-Sec 10Y, 5Y, 1Y and T-Bill 91D, 364D.

**FR-NIDP-002.4 — fred_macro Series**  
Ingests 8 curated US macro series from FRED. `DGS10` (US 10Y Treasury) is mandatory — its absence triggers a BLOCK finding.

**FR-NIDP-002.5 — yfinance Backfill Role**  
`yfinance_backfill` is not a scheduled ingester. It fills long-tail history that NSE bhavcopy doesn't cover (older years, missing days). Runs manually or on event trigger. All its validation findings are WARN/INFO only — never blocks.

**FR-NIDP-002.6 — DATE_REQUIRED Services**  
`bhavcopy`, `delivery`, `index_close`, `fii_dii` require an explicit `--date` argument when invoked via CLI. The CLI enforces this at startup.

**Source:** `backend/nidp/services/`, `backend/nidp/cli.py:69`

---

## FR-NIDP-003 — Phase 1B Fundamentals Ingesters

### Description
Extended ingester suite covering equity fundamentals, F&O market data, price adjustments, sector taxonomy, and shareholding patterns.

### Ingester Registry

| Name | Source | Cadence | Domain Table |
|------|--------|---------|--------------|
| `nse_financials` | NSE quarterly financial filings | Quarterly | `nidp.nse_financials` |
| `nse_shareholding` | NSE shareholding pattern XBRL | Quarterly | `nidp.shareholding_pattern` |
| `price_adjuster` | Computed from `corporate_actions` | Event-driven | `nidp.prices_eod` (adj columns) |
| `nse_equity_master` | NSE security master CSV | Monthly | `nidp.nse_equity_master` |
| `fno_bhavcopy` | NSE F&O BhavCopy CSV | Daily | `nidp.fno_bhavcopy` |

### Functional Requirements

**FR-NIDP-003.1 — price_adjuster**  
Reads from `nidp.corporate_actions` (splits, bonuses, dividends) and back-adjusts historical OHLCV in `prices_eod` by computing adjustment factors. Triggered on new corporate action events, not on a fixed schedule.

**FR-NIDP-003.2 — nse_equity_master**  
Maintains a reference table of all NSE-listed securities: ISIN, symbol, series, listing date, face value, sector, industry. Used as a JOIN key by other ingesters.

**FR-NIDP-003.3 — fno_bhavcopy**  
Ingests F&O (futures and options) bhavcopy separately from equity bhavcopy. Stored in `nidp.fno_bhavcopy` table with Avro schema `fno_bhavcopy_v1.avsc`.

**Source:** `backend/nidp/services/nse_financials/`, `nse_shareholding/`, `price_adjuster/`, `nse_equity_master/`, `fno_bhavcopy/`

---

## FR-NIDP-004 — S4 Corporate Announcements Pipeline

### Description
High-frequency pipeline ingesting corporate announcements from both NSE and BSE, classifying them using an AI classifier, and making them available for downstream document intelligence.

### Components

| Component | Role |
|-----------|------|
| `corporate_announcements_nse` | Polls NSE announcement API at high frequency |
| `corporate_announcements_bse` | Polls BSE announcement API at high frequency |
| `announcement_classifier` | AI-driven classifier: categorises announcements (earnings, board meeting, dividend, AGM, etc.) |
| `document_parser` | Downloads and parses announcement PDFs; extracts structured content |

### Functional Requirements

**FR-NIDP-004.1 — NSE Announcements Ingestion**  
Polls NSE corporate filings endpoint at high frequency (sub-hourly). De-duplicates by announcement ID. Persists to `nidp.corporate_announcements` with `source='NSE'`.

**FR-NIDP-004.2 — BSE Announcements Ingestion**  
Polls BSE corporate filings endpoint at high frequency. Persists to `nidp.corporate_announcements` with `source='BSE'`. De-duplicates across NSE+BSE for the same filing.

**FR-NIDP-004.3 — Announcement Classifier**  
Event-driven: fires after each new announcement batch. Applies ML/rule-based classifier to assign `announcement_type` (earnings, dividend, board_meeting, agm, rights, merger, other). Writes back to `nidp.corporate_announcements.announcement_type`.

**FR-NIDP-004.4 — Document Parser (S5 Week 1)**  
Downloads PDF attachments from announcement URLs. Extracts structured text. Produces embedding-ready chunks. Stores chunks in `nidp.documents` with `NULL` embeddings initially (embedder is S5 Week 2). Migration: `031_nidp_documents.sql`.

**FR-NIDP-004.5 — Intraday Mode**  
`corporate_announcements` supports `--intraday` flag in CLI and admin API. Intraday mode: applies market-hours guard (runs only during NSE market hours 09:00–15:30 IST) + triggers classifier on completion.

**Source:** `backend/nidp/services/corporate_announcements_nse/`, `corporate_announcements_bse/`, `announcement_classifier/`, `document_parser/`; migration `030_nidp_corporate_announcements.sql`, `031_nidp_documents.sql`

---

## FR-NIDP-005 — Mutual Fund Pipeline

### Description
Pipeline for AMFI mutual fund data: daily NAVs, NAV history, SEBI circulars, scheme disclosures, and portfolio holdings.

### Ingester Registry

| Name | Source | Cadence | Domain Table |
|------|--------|---------|--------------|
| `amfi_nav` | AMFI daily NAV file | Daily | `nidp.mf_nav_daily` |
| `amfi_nav_history` | AMFI historical NAV | Manual | `nidp.mf_nav_daily` |
| `amfi_circulars` | AMFI circulars page | Daily | `nidp.mf_amfi_circulars` |
| `mf_disclosure_snapshot` | SEBI/AMFI monthly factsheet | Monthly | `nidp.mf_disclosure_snapshot` |
| `mf_holdings` | AMFI monthly portfolio disclosure | Monthly | `nidp.mf_holdings` |

### Avro Contracts

- `mf_nav_daily_v1.avsc` — daily NAV per scheme
- `mf_scheme_master_v1.avsc` — scheme metadata
- `mf_scheme_event_v1.avsc` — scheme lifecycle events (merge, NFO, closure)
- `mf_amfi_circular_v1.avsc` — SEBI/AMFI regulatory circulars
- `mf_holdings_monthly_v1.avsc` — monthly portfolio holdings per scheme

**Source:** `backend/nidp/services/amfi_nav/`, `amfi_nav_history/`, `amfi_circulars/`, `mf_disclosure_snapshot/`, `mf_holdings/`; migration `034_nidp_mutual_funds.sql`

---

## FR-NIDP-006 — Corporate Event Intelligence Pipeline

### Description
Pipeline that builds a forward-looking event calendar from corporate announcements, polls for real-time events on event days, and produces D+1 intelligence reports.

### Components

| Component | Role |
|-----------|------|
| `event_calendar` | Aggregates upcoming corporate events from all sources into `nidp.event_calendar` |
| `event_day_poller` | On event days, polls for actual outcomes at high frequency (e.g. earnings numbers, dividend amounts) |
| `d1_prep` | Runs D+1 morning: prepares consolidated event outcome summary for the intelligence layer |
| `intelligence` | Produces daily intelligence narrative / signal per symbol based on event outcomes |

### Functional Requirements

**FR-NIDP-006.1 — Event Calendar Aggregation**  
`event_calendar` ingester reads from `nidp.corporate_actions`, `nidp.corporate_announcements`, and other sources to build a 60-day forward-looking calendar of dividends, splits, bonus issues, board meetings, earnings release dates. De-duplication logic in migration `039_nidp_event_calendar_dedup.sql`.

**FR-NIDP-006.2 — Event Day Poller**  
On days when ≥1 event is expected (`nidp.event_calendar.event_date = today`), `event_day_poller` runs at high frequency to capture actual outcomes as they are announced. Cadence: high-freq (sub-hourly during market hours).

**FR-NIDP-006.3 — D+1 Preparation**  
`d1_prep` runs each morning to prepare a consolidated summary of yesterday's events for the `intelligence` ingester. Reads from `event_day_poller` results and `corporate_announcements`.

**FR-NIDP-006.4 — Intelligence Ingester**  
`intelligence` produces per-symbol intelligence signals based on event outcomes: earnings beat/miss, dividend declared, split ratio confirmed. Writes to `nidp.intelligence` table (migration `038_nidp_intelligence.sql`).

**Source:** `backend/nidp/services/event_calendar/`, `event_day_poller/`, `d1_prep/`, `intelligence/`; migrations `036_nidp_corporate_events.sql`, `038_nidp_intelligence.sql`, `039_nidp_event_calendar_dedup.sql`

---

## FR-NIDP-007 — Post-Ingestion Quality Pipeline

### Description
Quality gate ingester that runs after all daily ingesters complete, performing cross-feed consistency checks and producing a daily DQ report.

### Functional Requirements

**FR-NIDP-007.1 — Quality Gate Ingester**  
`quality_gate` runs daily after all other ingesters complete (~22:30 IST). Performs cross-feed consistency checks: e.g., delivery data has matching symbols in prices_eod; bhavcopy row count matches delivery row count within tolerance; FII/DII date matches bhavcopy date.

**FR-NIDP-007.2 — AI DQ Layer**  
`dq_ai` service (migration `043_nidp_dq_ai.sql`) provides AI-assisted anomaly detection on top of rule-based validation. Flags statistical outliers and unusual patterns not caught by deterministic rules.

**FR-NIDP-007.3 — Consistency Quality Rules**  
Migration `040_nidp_consistency_quality.sql` installs SQL-based consistency check jobs. Runs as scheduled function within the DB.

**Source:** `backend/nidp/services/quality_gate/`, `dq_ai/`; migrations `040_nidp_consistency_quality.sql`, `043_nidp_dq_ai.sql`

---

## FR-NIDP-008 — Intelligence Layer (Phase 2)

### Description
Phase 2 of NIDP builds derived intelligence on top of raw ingested data: security master, feature engineering, graph relationships, portfolio sync.

### Components

| Component | Role |
|-----------|------|
| `intelligence_layer` | Orchestrates security_master + DQ + features + graph + events + analytics |
| `portfolio_intelligence_sync` | Syncs NIDP intelligence signals back to the Nivesh app's portfolio context |
| `feature_snapshotter` | Computes and snapshots 100+ technical/fundamental features per symbol per day |
| `mf_analytics_engine` | Produces rolling analytics (returns, volatility, Sharpe) for MF schemes |
| `market_intelligence` | Aggregates market-wide intelligence: breadth, momentum, regime signals |

### Functional Requirements

**FR-NIDP-008.1 — Intelligence Layer Orchestration**  
`intelligence_layer` is a meta-ingester that sequences: (1) security master refresh, (2) DQ checks, (3) stock feature computation, (4) portfolio graph updates, (5) event summaries, (6) analytics aggregation. Migration: `041_nidp_core_intelligence_layer.sql`.

**FR-NIDP-008.2 — Portfolio Intelligence Sync**  
`portfolio_intelligence_sync` reads from `nidp.intelligence`, `nidp.stock_daily_snapshot`, and `nidp.corporate_announcements` and pushes derived signals to the main Nivesh MongoDB for use by the portfolio intelligence tab. Migration: `042_nidp_portfolio_bridge.sql`.

**FR-NIDP-008.3 — Feature Snapshotter**  
Computes per-symbol daily features from `prices_eod`, `delivery_data`, `fii_dii_flows`, `corporate_actions`. Stores in `nidp.stock_features_daily` (migration `021_stock_features_daily.sql`). Avro schema: `stock_features_daily_v1.avsc`.

**Source:** `backend/nidp/services/intelligence_layer/`, `portfolio_intelligence_sync/`, `feature_snapshotter/`, `mf_analytics_engine/`, `market_intelligence/`; migrations `041`, `042`

---

## FR-NIDP-009 — Validation Engine (BLOCK / FIX / WARN)

### Description
Every ingester has a `validators.py` module that registers per-feed DQ rules. The validation engine runs after `persist` and writes findings to `nidp.validation_findings`.

### Rule Types

| Rule Class | Description |
|---|---|
| `CountAtLeastRule` | Assert ≥ N rows for the run (e.g. bhavcopy: ≥1500) |
| `NoNullsRule` | Required columns must be non-null |
| `RangeRule` | Numeric column must lie in a sane range (e.g. RBI yields ∈ [0.5%, 20%]) |
| `CustomSQLRule` | Arbitrary SQL assertion (e.g. `net = buy − sell` within ₹1 cr for FII/DII) |

### Severity Levels

| Severity | Class | Effect |
|---|---|---|
| CRITICAL | BLOCK | Run set to FAILED; Kafka emit suppressed; downstream consumers blocked |
| ERROR | FIX | Run set to PARTIAL; rows persisted but flagged; Kafka emit proceeds |
| WARN | INFO | Run stays OK; logged only |

### Functional Requirements

**FR-NIDP-009.1 — Finding Schema**  
Each finding written to `nidp.validation_findings` contains: `finding_id`, `ingester`, `job_run_id` (NOT `source_run_id`), `rule_name`, `severity`, `failure_class`, `message`, `actual` (TEXT — `'True'`/`'False'`, not boolean), `sample_rows` (JSONB), `detected_at`.

**FR-NIDP-009.2 — BLOCK Suppression**  
When `failure_class = 'BLOCK'`, the base ingester skips the Kafka publish step entirely. This prevents downstream pipelines (snapshot builder, copilot tools, DaaS API) from consuming condemned data.

**FR-NIDP-009.3 — Ad-Hoc Validation**  
CLI command `nidp validate <service> [--date YYYY-MM-DD]` runs the validation rules against the most recent successful run without re-ingesting. Returns exit code 0 if no BLOCK findings, 1 otherwise.

**Source:** `backend/nidp/shared/validation/`, `backend/nidp/shared/validation/rules.py`, `backend/nidp/shared/validation/runner.py`

---

## FR-NIDP-010 — Per-Feed Validation Rules

### Description
Complete catalogue of validation rules registered for each Phase 1A feed.

### Rules Catalogue

| Feed | Rule | Severity | Class | Assertion |
|---|---|---|---|---|
| bhavcopy | `row_count_min` | CRITICAL | BLOCK | ≥ 1500 EQ rows per trading day |
| bhavcopy | `required_fields_present` | ERROR | FIX | symbol/series/OHLC not null |
| bhavcopy | `close_price_range` | ERROR | FIX | close ∈ (0, 1e7] |
| bhavcopy | `ohlc_consistent` | ERROR | FIX | low ≤ open, close ≤ high |
| bhavcopy | `symbol_series_unique` | CRITICAL | BLOCK | (symbol, series) unique within run |
| delivery | `row_count_min` | CRITICAL | BLOCK | ≥ 1500 rows (should match bhavcopy) |
| delivery | `deliv_pct_range` | ERROR | FIX | 0 ≤ pct ≤ 100 |
| delivery | `deliverable_le_traded` | ERROR | FIX | delivered_qty ≤ traded_qty |
| delivery | `cross_check_prices_eod_present` | WARN | FIX | symbol must exist in prices_eod same date |
| index_close | `row_count_min` | ERROR | FIX | ≥ 20 indices |
| index_close | `nifty50_present` | CRITICAL | BLOCK | Nifty 50 close must be present |
| index_close | `pct_change_in_range` | WARN | INFO | \|day-over-day pct\| < 20% |
| fii_dii | `any_row_present` | CRITICAL | BLOCK | Rolling JSON returned ≥ 1 row |
| fii_dii | `cash_rows_present` | CRITICAL | BLOCK | Both FII and DII EQUITY_CASH rows present |
| fii_dii | `net_equals_buy_minus_sell` | ERROR | FIX | \|net − (buy−sell)\| < ₹1 cr |
| bulk_deals / block_deals | `required_fields` | ERROR | FIX | symbol/qty/price not null |
| bulk_deals / block_deals | `quantity_positive` | ERROR | FIX | qty > 0 |
| bulk_deals / block_deals | `price_range` | ERROR | FIX | price ∈ (0, 1e6] |
| bulk_deals / block_deals | `deal_type_valid` | ERROR | FIX | deal_type ∈ {BUY, SELL} |
| corporate_actions | `required_fields` | ERROR | FIX | symbol/ex_date not null |
| corporate_actions | `split_has_face_values` | WARN | FIX | SPLIT rows have face_value_pre/post |
| corporate_actions | `bonus_has_ratio` | WARN | FIX | BONUS rows have ratio |
| corporate_actions | `dividend_has_amount` | WARN | FIX | DIVIDEND rows have amount |
| corporate_actions | `other_ratio_not_dominant` | ERROR | FIX | ≤ 30% in OTHER category |
| rbi_yields | `10y_present` | CRITICAL | BLOCK | India 10Y G-Sec yield is present |
| rbi_yields | `required_fields` | ERROR | FIX | yield_pct not null |
| rbi_yields | `yield_in_sane_range` | ERROR | FIX | yield ∈ [0.5%, 20%] |
| fred_macro | `series_coverage` | ERROR | FIX | all 8 SERIES_CATALOG ids returned data |
| fred_macro | `us10y_present` | CRITICAL | BLOCK | DGS10 must be present |
| yfinance_backfill | `close_price_present` | WARN | INFO | best-effort; never blocks |
| yfinance_backfill | `close_price_range` | WARN | INFO | best-effort; never blocks |
| yfinance_backfill | `ohlc_consistent` | WARN | INFO | best-effort; never blocks |
| nse_calendar | (none) | — | — | Idempotent upsert; trust the source |
| index_constituents | (none) | — | — | Quarterly snapshot; trust the source |

**Source:** `backend/nidp/services/<svc>/validators.py` (per service)

---

## FR-NIDP-011 — Storage Architecture (3 Layers)

### Description
NIDP uses a three-layer storage model: raw archive (replay substrate), parsed archive (recompute substrate), domain tables (query substrate).

### Functional Requirements

**FR-NIDP-011.1 — Raw Archive Layer**  
`nidp.raw_archive_files` — every fetched HTTP response stored in GCS. Content-addressed by SHA-256. Enables full parser replay from any historical date without re-fetching upstream (upstream APIs may change or disappear).

**FR-NIDP-011.2 — Parsed Archive Layer**  
`nidp.parsed_archive_files` — normalised rows serialised to gzipped JSONL in GCS. Enables model rebuilds without re-running the parser. Particularly useful when the parsing logic changes.

**FR-NIDP-011.3 — Domain Tables Layer**  
13 feed-specific tables that production consumers query:

| Table | Key Columns |
|---|---|
| `nidp.prices_eod` | symbol, as_of_date, open, high, low, close, volume, source |
| `nidp.delivery_data` | symbol, as_of_date, delivered_qty, delivered_pct |
| `nidp.index_eod` | index_name, as_of_date, close, pct_change |
| `nidp.fii_dii_flows` | as_of_date, category, buy_value, sell_value, net_value |
| `nidp.corporate_actions` | symbol, ex_date, record_date, action_type, amount |
| `nidp.bulk_deals` | symbol, as_of_date, deal_type, qty, price |
| `nidp.block_deals` | symbol, as_of_date, deal_type, qty, price |
| `nidp.rbi_yields` | instrument, as_of_date, yield_pct |
| `nidp.fred_macro_observations` | series_id, as_of_date, value |
| `nidp.nse_holidays` | holiday_date, description |
| `nidp.index_constituents` | index_name, symbol, as_of_date, weight |

**FR-NIDP-011.4 — Snapshot Tables Layer**  
Two cross-feed snapshot tables produced by `snapshot_builder`:
- `nidp.market_daily_snapshot` — one row per `as_of_date`: headline indices, FII/DII totals, RBI yields, market breadth
- `nidp.stock_daily_snapshot` — one row per `(symbol, as_of_date)`: OHLCV + delivery % + index membership + recent deal activity + upcoming-corp-action flags

**FR-NIDP-011.5 — Operational Tables**  
- `nidp.job_log` — one row per run; status + duration + rows_fetched/inserted/skipped + error_class + error_message
- `nidp.source_registry` — one row per feed with counters, schedule, `consecutive_failures`
- `nidp.v_feed_status` — view joining job_log + source_registry + feed_snapshot (single-pane ops health view)
- `nidp.market_session_state` — denormalised "last NSE close" date
- `nidp.validation_findings` — DQ engine output

**FR-NIDP-011.6 — Pluggable Storage Backend**  
Storage layer is abstracted behind a `StorageBackend` ABC. Implementations: `GCSBackend` (production), `LocalDiskBackend` (tests), `S3Backend` (supported). Selected via `STORAGE_BACKEND` env var.

**Source:** `backend/nidp/shared/storage/`, `backend/nidp/migrations/001_nidp_base.sql` through `007_nidp_snapshot_tables.sql`

---

## FR-NIDP-012 — Snapshot Builder

### Description
`snapshot_builder` is the final daily ingester. After all other ingesters have completed, it reads from domain tables and produces the two cross-feed snapshot tables consumed by the Nivesh app and NIDP DaaS API.

### Functional Requirements

**FR-NIDP-012.1 — Preflight Check**  
Before building a snapshot for `target_date`, `snapshot_builder` asserts:
- `prices_eod` has ≥ 1500 rows for `target_date`  
- `index_eod` has ≥ 1 row for `target_date` with Nifty 50 present  

If preflight fails: exits with `FAILED` status. Will not build a partial snapshot. `--force` flag overrides preflight.

**FR-NIDP-012.2 — market_daily_snapshot Build**  
Joins: `index_eod` (Nifty 50/100/500/Bank Nifty/India VIX closes), `fii_dii_flows` (FII net equity cash), `rbi_yields` (10Y G-Sec), aggregate `prices_eod` stats (advances, declines, unchanged). One row per `as_of_date`.

**FR-NIDP-012.3 — stock_daily_snapshot Build**  
Joins per symbol: `prices_eod` OHLCV, `delivery_data` delivery%, `index_constituents` index membership flags, `corporate_actions` upcoming events within 30 days, `bulk_deals`/`block_deals` recent activity flag. One row per `(symbol, as_of_date)`.

**FR-NIDP-012.4 — Snapshot Status Tracking**  
`nidp.daily_snapshot` table tracks readiness: `snapshot_status ∈ {PENDING, BUILDING, READY, FAILED}`. Only `READY` snapshots with zero BLOCK findings are served by the DaaS API.

**FR-NIDP-012.5 — CLI Access**  
`nidp snapshot build --date YYYY-MM-DD [--force]` — build snapshot for date.  
`nidp snapshot status [--date YYYY-MM-DD]` — show readiness status.

**Source:** `backend/nidp/services/snapshot_builder/service.py`, `backend/nidp/cli.py:174`

---

## FR-NIDP-013 — Avro Schema Contracts

### Description
All Kafka events emitted by NIDP ingesters are serialised using Avro schemas registered with Confluent Schema Registry. 24 schema files in `backend/nidp/contracts/`.

### Schema Catalogue

| Schema File | Topic / Usage |
|---|---|
| `ingestion_completed_v1.avsc` | Emitted by every ingester on success |
| `snapshot_ready_v1.avsc` | Emitted by snapshot_builder when snapshot is READY |
| `bhavcopy_v1.avsc` | NSE daily equity prices |
| `delivery_v1.avsc` | NSE delivery data |
| `index_close_v1.avsc` | NSE index closes |
| `index_constituents_v1.avsc` | Index membership snapshots |
| `fii_dii_v1.avsc` | FII/DII flows |
| `corporate_actions_v1.avsc` | Dividends, splits, bonuses, rights |
| `bulk_deals_v1.avsc` | NSE bulk deals |
| `block_deals_v1.avsc` | NSE block deals |
| `rbi_yields_v1.avsc` | RBI G-Sec + T-Bill yields |
| `fred_macro_v1.avsc` | US macro series from FRED |
| `fno_bhavcopy_v1.avsc` | NSE F&O bhavcopy |
| `nse_calendar_v1.avsc` | NSE trading holidays |
| `nse_financials_v1.avsc` | NSE quarterly financials |
| `shareholding_pattern_v1.avsc` | Quarterly shareholding pattern |
| `mf_nav_daily_v1.avsc` | AMFI daily NAVs |
| `mf_scheme_master_v1.avsc` | MF scheme metadata |
| `mf_scheme_event_v1.avsc` | MF scheme lifecycle events |
| `mf_amfi_circular_v1.avsc` | SEBI/AMFI circulars |
| `mf_holdings_monthly_v1.avsc` | Monthly MF portfolio holdings |
| `stock_features_daily_v1.avsc` | Per-symbol daily features |
| `validation_finding_v1.avsc` | DQ validation findings (Kafka) |
| `portfolio_holdings_snapshot_v1.schema.json` | Portfolio bridge (JSON Schema) |

### Functional Requirements

**FR-NIDP-013.1 — Schema Evolution**  
All schemas are versioned with `_v1` suffix. Breaking changes require a new version (e.g., `_v2`). Confluent Schema Registry enforces backward/forward compatibility.

**FR-NIDP-013.2 — `ingestion_completed_v1` Required Fields**  
`ingester` (string), `target_date` (string ISO-8601), `run_id` (string UUID), `status` (enum: OK/PARTIAL/FAILED/SKIPPED), `rows_inserted` (int), `duration_ms` (int).

**Source:** `backend/nidp/contracts/`

---

## FR-NIDP-014 — NIDP CLI

### Description
`python -m nidp.cli` — unified command-line interface for all NIDP operations. Registered as `nidp` entrypoint.

### Command Reference

| Command | Syntax | Description |
|---|---|---|
| `migrate` | `nidp migrate [--force]` | Apply all pending `.sql` files in `nidp/migrations/` in name order; each in a single transaction; idempotent |
| `ingest` | `nidp ingest <service> [--date YYYY-MM-DD] [--intraday]` | Run one ingester; `--date` required for DATE_REQUIRED services; `--intraday` for sub-hourly market-hours mode |
| `list-services` | `nidp list-services` | Print all registered service names with date-required flag |
| `health` | `nidp health` | Check Postgres connectivity, TimescaleDB extension version, table count in `nidp` schema |
| `backfill` | `nidp backfill --from D --to D [options]` | Historical ingestion over a date range (see FR-NIDP-017) |
| `snapshot build` | `nidp snapshot build --date YYYY-MM-DD [--force]` | Build daily snapshot for date |
| `snapshot status` | `nidp snapshot status [--date YYYY-MM-DD]` | Show snapshot readiness for date |
| `validate` | `nidp validate <service> [--date YYYY-MM-DD]` | Run DQ validation rules against most recent successful run without re-ingesting; exits 1 if BLOCK findings |
| `daas-keygen` | `nidp daas-keygen --name N --owner E --plan free\|standard\|pro\|internal [--rpm N] [--daily-quota N] [--expires-in-days N]` | Issue new DaaS API key; cleartext token printed once and never stored |
| `daas-keys list` | `nidp daas-keys list` | List all keys with status, plan, last_used |
| `daas-keys revoke` | `nidp daas-keys revoke --key-id <uuid>` | Revoke a key by ID |
| `feature-flags list` | `nidp feature-flags list` | Show all runtime feature flags and current state |
| `feature-flags set` | `nidp feature-flags set <flag> on\|off [--notes N]` | Toggle a feature flag |

### Service Registry (27 services in cli.py:40-67)

`bulk_deals`, `block_deals`, `corporate_announcements`, `bhavcopy`, `delivery`, `index_close`, `index_constituents`, `fii_dii`, `corporate_actions`, `nse_calendar`, `rbi_yields`, `fred_macro`, `yfinance_backfill`, `amfi_nav`, `amfi_nav_history`, `amfi_circulars`, `mf_disclosure_snapshot`, `mf_holdings`, `event_calendar`, `nse_financials`, `event_analyzer`, `d1_prep`, `intelligence`, `intelligence_layer`, `portfolio_intelligence_sync`, `event_day_poller`

**Source:** `backend/nidp/cli.py`

---

## FR-NIDP-015 — Database Migrations

### Description
35 idempotent SQL migration files in `backend/nidp/migrations/`, applied in filename order via `nidp migrate`. Each file uses `CREATE … IF NOT EXISTS` / `INSERT … ON CONFLICT` to ensure safe re-runs.

### Migration Catalogue

| File | Purpose |
|---|---|
| `001_nidp_base.sql` | `nidp` schema, `schema_migrations` table, `job_log`, `source_registry` |
| `002_nidp_market_data.sql` | `prices_eod`, `delivery_data`, `index_eod`, `corporate_actions`, `bulk_deals`, `block_deals` |
| `003_nidp_flows_events.sql` | `fii_dii_flows`, `nse_holidays` |
| `004_nidp_macro_reference.sql` | `rbi_yields`, `fred_macro_observations`, `index_constituents` |
| `005_nidp_timescale.sql` | TimescaleDB hypertable promotion for time-series tables |
| `006_nidp_validation.sql` | `validation_findings`, `raw_archive_files`, `parsed_archive_files` |
| `006_nidp_views.sql` | `v_feed_status`, `v_market_session` views |
| `007_nidp_snapshot_tables.sql` | `market_daily_snapshot`, `stock_daily_snapshot`, `feed_snapshot`, `daily_snapshot` |
| `008_nidp_fred_macro.sql` | Fred macro series catalog and observation upsert helpers |
| `020_strategy_builder_core.sql` | Strategy builder schema (P3 — uncommitted) |
| `021_stock_features_daily.sql` | `nidp.stock_features_daily` table |
| `022_nidp_feed_management.sql` | Feed subscriptions and management tables |
| `023_nidp_market_session.sql` | `market_session_state` table (last NSE close date) |
| `024_nidp_nse_financials.sql` | `nse_financials` table (quarterly results) |
| `025_nidp_shareholding_pattern.sql` | `shareholding_pattern` table |
| `026_nidp_price_adjustments.sql` | `price_adjustment_factors` table |
| `027_nidp_sector_master.sql` | `sector_master`, `industry_master` reference tables |
| `028_nidp_fno_bhavcopy.sql` | `fno_bhavcopy` table (F&O daily prices) |
| `029_nidp_stock_features_extended.sql` | Extended feature columns in `stock_features_daily` |
| `030_nidp_corporate_announcements.sql` | `corporate_announcements` table (NSE + BSE) |
| `031_nidp_documents.sql` | `nidp.documents` table with `embedding` vector(1536) NULL column (S5) |
| `032_nidp_feeds_subscriptions.sql` | Feed subscription and notification config |
| `033_nidp_register_phase1b_s4_s5_ingesters.sql` | Seeds Phase 1B, S4, S5 ingesters into `source_registry` |
| `034_nidp_mutual_funds.sql` | `mf_nav_daily`, `mf_scheme_master`, `mf_holdings`, `mf_amfi_circulars` |
| `035_nidp_daas_api.sql` | `daas_api_keys` table (key hash, plan, rate limits, quotas) |
| `036_nidp_corporate_events.sql` | `event_calendar` table (forward-looking event schedule) |
| `037_nidp_feature_flags.sql` | `nidp.feature_flags` table (runtime toggle switches) |
| `038_nidp_intelligence.sql` | `nidp.intelligence` table (per-symbol event intelligence signals) |
| `039_nidp_event_calendar_dedup.sql` | Deduplication constraints on `event_calendar` |
| `040_nidp_consistency_quality.sql` | Cross-feed consistency check SQL jobs |
| `041_nidp_core_intelligence_layer.sql` | Intelligence layer supporting tables and views |
| `042_nidp_portfolio_bridge.sql` | Portfolio bridge sync state tracking |
| `043_nidp_dq_ai.sql` | AI-assisted DQ layer tables |
| `044_nidp_replay_engine.sql` | Replay engine state and policy tables |
| `045_nidp_backfill.sql` | Backfill orchestration state tables |

**Source:** `backend/nidp/migrations/`

---

## FR-NIDP-016 — DaaS API + Key Management

### Description
NIDP exposes a Data-as-a-Service API (DaaS API) running on the VM as a separate FastAPI process. It is the primary interface for the Nivesh app and external clients to consume NIDP data without direct DB access.

### Functional Requirements

**FR-NIDP-016.1 — API Key System**  
Keys are issued via `nidp daas-keygen`. The cleartext token is printed once at issuance and never stored. Only the SHA-256 hash is stored in `nidp.daas_api_keys`. Keys have: name, owner_email, plan (free/standard/pro/internal), rpm cap, daily_quota, expires_at.

**FR-NIDP-016.2 — Rate Limiting Tiers**  
| Plan | Default RPM | Default Daily Quota |
|---|---|---|
| free | 30 | 1,000 |
| standard | 200 | 10,000 |
| pro | 600 | unlimited |
| internal | unlimited | unlimited |

Overridable per key via `--rpm` and `--daily-quota` flags.

**FR-NIDP-016.3 — Key Revocation**  
`nidp daas-keys revoke --key-id <uuid>` sets `status = 'revoked'` in `daas_api_keys`. Revoked keys return HTTP 401.

**FR-NIDP-016.4 — DaaS API Endpoints**  
Exposed by `backend/nidp/services/daas_api/` and `query_api/`:
- `GET /v1/catalog` — list all feeds with row counts + first/last dates
- `GET /v1/snapshot/market?date=YYYY-MM-DD` — latest market_daily_snapshot
- `GET /v1/snapshot/stock/{symbol}?date=YYYY-MM-DD` — latest stock_daily_snapshot for symbol
- `GET /v1/feeds/{feed}/rows?date=YYYY-MM-DD&limit=N` — raw domain table rows
- `GET /v1/backfill/status` — backfill orchestration status (see FR-NIDP-017)
- `POST /v1/replay/...` — replay engine endpoints (see FR-NIDP-018)

**FR-NIDP-016.5 — Admin Key Management in Console**  
`backend/routes/admin_data_pipeline.py` exposes `GET/POST /api/admin/nidp/daas-keys` — lists and revokes keys via the Nivesh Admin Console without SSH access to the VM.

**Source:** `backend/nidp/services/daas_api/`, `backend/nidp/cli.py:240-323`, migration `035_nidp_daas_api.sql`

---

## FR-NIDP-017 — Backfill Orchestration

### Description
Backfill system fills historical gaps in domain tables. The CLI `backfill` command and Admin Console panel provide control. The DaaS API exposes status endpoints. An SSH-tunnelled trigger kicks off backfill workers on the VM.

### Functional Requirements

**FR-NIDP-017.1 — Backfill CLI**  
`nidp backfill --from YYYY-MM-DD --to YYYY-MM-DD [--services s1,s2] [--concurrency N] [--dry-run]`  
- Iterates dates in range; for each trading day, runs each specified service's ingester
- Respects NSE holiday calendar (skips non-trading days)
- Concurrency: parallel service execution within a day; default 1
- `--dry-run`: prints plan without executing

**FR-NIDP-017.2 — Backfill Readiness Matrix**  
`GET /api/admin/nidp/backfill/readiness?target_days=90` returns a per-feed matrix:
- Pulls coverage stats from VM DaaS `/v1/catalog`
- Joins with static provenance metadata from `_nidp_feed_provenance.py`
- Computes per-feed: `coverage_pct`, `missing_days`, `first_date`, `last_date`, `certification` (CERTIFIED / PARTIAL / MISSING)
- Considers only trading days within the target window (~5/7 of calendar days)

**FR-NIDP-017.3 — VM SSH Trigger**  
`POST /api/admin/nidp/backfill/trigger` — fires the backfill orchestrator on the VM via SSH (`ssh_run_detached_as_nidp`). Returns immediately with a `backfill_id`. Use `GET /api/admin/nidp/backfill/status/{backfill_id}` to poll.

**FR-NIDP-017.4 — Backfill State Tracking**  
Migration `045_nidp_backfill.sql` installs backfill state tables: one row per `(feed, date)` with status `PENDING/RUNNING/OK/FAILED/SKIPPED`. The VM DaaS `/v1/backfill/status` reads from these tables.

**Source:** `backend/nidp/backfill.py`, `backend/routes/admin_nidp_backfill.py`, migration `045_nidp_backfill.sql`

---

## FR-NIDP-018 — Replay Engine

### Description
The replay engine re-processes historical raw archive files through updated parsers and/or validation rules without re-fetching from upstream. Used for parser bug fixes, schema changes, and DQ rule updates.

### Functional Requirements

**FR-NIDP-018.1 — Replay Policies**  
Policies define what to replay and how. Policy fields: `policy_name`, `ingester`, `date_from`, `date_to`, `mode` (PARSE_ONLY / VALIDATE_ONLY / FULL), `failure_handling` (SKIP / ABORT / CONTINUE). Built-in default policies are always available even if the VM is unreachable (`list_policies()` fallback in `admin_nidp_replay.py`).

**FR-NIDP-018.2 — Replay Execution**  
`POST /v1/replay/start` with a policy kicks off a background task on the VM. Reads raw archive bytes from GCS for the specified date range, runs them through the current parser version, and re-persists to domain tables (upsert, not delete-reinsert). Emits new Kafka events on success.

**FR-NIDP-018.3 — Failure Injection**  
`backend/nidp/quality/replay/failure_injector.py` — injects synthetic failures into raw archive bytes for testing the validation engine and failure handling paths.

**FR-NIDP-018.4 — Admin Proxy**  
`backend/routes/admin_nidp_replay.py` is a verb-agnostic proxy forwarding all `/api/admin/nidp/replay/*` requests to the VM DaaS `/v1/replay/*` with injected `X-API-Key`. `GET /api/admin/nidp/replay/policies` has a graceful fallback to built-in policies if the VM is unreachable.

**Source:** `backend/nidp/quality/replay/`, `backend/routes/admin_nidp_replay.py`, migration `044_nidp_replay_engine.sql`

---

## FR-NIDP-019 — Feature Flags

### Description
Runtime toggle switches stored in `nidp.feature_flags` table. Changed without code deployment.

### Functional Requirements

**FR-NIDP-019.1 — Flag Operations**  
`nidp feature-flags list` — show all flags with current state and notes.  
`nidp feature-flags set <flag_name> on|off [--notes reason]` — toggle; `value` accepted as `on/off/true/false/1/0/yes/enable/enabled`.

**FR-NIDP-019.2 — Known Flags**  
Per `backend/nidp/shared/feature_flags.py`:
- `event_processing` — enable/disable the event calendar + intelligence pipeline
- `telegram_alerts` — enable/disable Telegram notifications for ingester failures
- `daas_api` — enable/disable the DaaS API server

**FR-NIDP-019.3 — Persistence**  
Flags stored in `nidp.feature_flags` table (migration `037_nidp_feature_flags.sql`). Read at ingester startup via `shared.feature_flags.list_flags()`.

**Source:** `backend/nidp/shared/feature_flags.py`, `backend/nidp/cli.py:278-300`, migration `037_nidp_feature_flags.sql`

---

## FR-NIDP-020 — GCP Deployment

### Description
NIDP ingesters deploy as Cloud Run jobs on GCP project `niveshdataintelligence`, region `asia-south1`. Each ingester has its own Docker image and Cloud Run job definition.

### Functional Requirements

**FR-NIDP-020.1 — Cloud Run Jobs**  
34 ingesters registered in `admin_nidp.py:NIDP_INGESTERS`. Cloud Run job names follow pattern `nidp-<ingester-with-dashes>`. Each job is triggered by Cloud Scheduler or manually via Admin Console.

**FR-NIDP-020.2 — Cloud Scheduler**  
`setup_schedules.sh` in `backend/nidp/deploy/gcp/` configures 12+ Cloud Scheduler triggers. Daily jobs fire at IST evening (19:00–22:00). `yfinance_backfill` is event-driven only — no Scheduler trigger.  
**Status:** Script ready; not yet activated for all jobs (P0 pending item).

**FR-NIDP-020.3 — GitHub Push → Cloud Build**  
`setup_github_triggers.sh` configures 14 Cloud Build triggers: one per service + one for migrations. On push to `nidp` branch, Cloud Build rebuilds the affected Docker image and deploys to Cloud Run.  
**Status:** YAMLs + script ready; auth issue resolved (commit `b97052b`). End-to-end test pending (P0).

**FR-NIDP-020.4 — Migration on Build**  
`build_on_gcp.sh` runs `nidp migrate` as part of every build, so code pushes automatically apply pending SQL migrations.

**FR-NIDP-020.5 — VM Infrastructure**  
Core infrastructure runs on single GCP VM `nidp-stack-vm`:
- TimescaleDB-pg16 (port 5433)
- Redpanda (port 9092) + Schema Registry (port 8081)
- Redis (port 6379)
- MinIO (S3-compatible, port 9000) — dev/test only; production uses GCS
- Prometheus (port 9090)
- Grafana (port 3000)

**FR-NIDP-020.6 — Grafana Dashboard**  
`/d/nidp-job-health/nidp-job-health` — served at `http://34.93.60.254:3000`. Embedded in Admin Console via HTTPS proxy at `/api/admin/nidp/grafana/*` to avoid mixed-content browser block. Dashboard path: `backend/nidp/deploy/grafana/provisioning/dashboards/nidp/`.  
**Status:** Dashboard JSON exists; NIDP-specific Grafana panels not fully wired up (P2).

**Source:** `backend/nidp/deploy/gcp/`, `backend/nidp/deploy/vm/`, `backend/routes/admin_nidp.py`

---

## FR-NIDP-021 — Observability

### Description
Four observability surfaces for monitoring NIDP health.

### Functional Requirements

**FR-NIDP-021.1 — nidp.v_feed_status (Primary Ops View)**  
SQL view joining `source_registry` + `job_log` + `feed_snapshot`. One row per ingester with: `last_run_status`, `success_count`, `failure_count`, `partial_count`, `consecutive_failures`, `last_run_at`, `next_run_at`. `consecutive_failures > 0` is the primary alert signal.

**FR-NIDP-021.2 — nidp.job_log (Run History)**  
Every run logged: `ingester`, `target_date`, `status`, `duration_ms`, `rows_fetched`, `rows_inserted`, `rows_skipped`, `error_class` (HTTP/PARSE/VALIDATE/DB/KAFKA), `error_message`.

**FR-NIDP-021.3 — nidp.validation_findings (DQ Output)**  
Every BLOCK/FIX/WARN finding logged with `rule_name`, `severity`, `failure_class`, `message`, `actual` (TEXT), `sample_rows` (JSONB), `detected_at`.

**FR-NIDP-021.4 — Cloud Run Logs**  
Full Python tracebacks available via:  
`gcloud logging read 'resource.labels.job_name="nidp-<svc>" severity>=ERROR' --project=niveshdataintelligence`

**FR-NIDP-021.5 — Prometheus Metrics**  
Each ingester exposes `/metrics` on a per-service port. Prometheus scrapes all services. Grafana dashboards provisioned at `deploy/grafana/provisioning/`.  
**Status:** Metrics exposed; NIDP-specific Grafana panels pending (P2).

**FR-NIDP-021.6 — Telegram Alerts**  
`nidp.shared.telegram.py` — sends Telegram alerts on ingester FAILED status when `telegram_alerts` feature flag is `on`.  
**Status:** Code implemented; flag default = off.

**FR-NIDP-021.7 — Admin Diagnostics Dump**  
`POST /api/admin/nidp/dump` — runs `dump_for_claude.sh` on the VM (via gcloud shell), bundles feed health + failed runs + logs + image tags into a diagnostic bundle. Returns as JSON. Used for "one-button debugging" without copy-pasting psql output.

**Source:** `backend/nidp/shared/metrics.py`, `backend/nidp/shared/telegram.py`, `backend/routes/admin_nidp.py`

---

## FR-NIDP-022 — Admin API Surface

### Description
Three FastAPI routers expose NIDP management endpoints to the Nivesh Admin Console, all protected by `require_admin`.

### Endpoint Catalogue

**`/api/admin/nidp/` — `admin_nidp.py`**

| Endpoint | Method | Description |
|---|---|---|
| `/api/admin/nidp/dump` | POST | Run diagnostic bundle on VM |
| `/api/admin/nidp/script` | GET | Pre-flight check (script + gh CLI available) |
| `/api/admin/nidp/jobs` | GET | List all 34 ingesters with Cloud Run status |
| `/api/admin/nidp/jobs/{ingester}/execute` | POST | Trigger Cloud Run job execution |
| `/api/admin/nidp/jobs/{ingester}/runs` | GET | Last N rows from job_log for ingester |
| `/api/admin/nidp/jobs/{ingester}/logs` | GET | Tail Cloud Run logs (streams) |
| `/api/admin/nidp/grafana/*` | GET | HTTPS proxy to Grafana dashboard (avoids mixed-content) |
| `/api/admin/nidp/dq/*` | GET/POST | Proxy to DaaS /v1/dq/* (DQ dashboard data) |

**`/api/admin/nidp/backfill/` — `admin_nidp_backfill.py`**

| Endpoint | Method | Description |
|---|---|---|
| `/api/admin/nidp/backfill/readiness` | GET | Backfill readiness matrix (coverage %) |
| `/api/admin/nidp/backfill/trigger` | POST | SSH-trigger backfill orchestrator on VM |
| `/api/admin/nidp/backfill/{tail:path}` | * | Generic proxy to DaaS /v1/backfill/* |

**`/api/admin/nidp/replay/` — `admin_nidp_replay.py`**

| Endpoint | Method | Description |
|---|---|---|
| `/api/admin/nidp/replay/policies` | GET | List replay policies (fallback to built-ins if VM unreachable) |
| `/api/admin/nidp/replay/{tail:path}` | GET/POST/PATCH/DELETE | Generic proxy to DaaS /v1/replay/* |

**GCP Project Config:**  
`GCP_PROJECT=niveshdataintelligence`, `GCP_REGION=asia-south1`  
Cloud Run job names: `nidp-<ingester-with-dashes>`

**Source:** `backend/routes/admin_nidp.py`, `admin_nidp_backfill.py`, `admin_nidp_replay.py`

---

## FR-NIDP-023 — S5 Document Intelligence (pgvector)

### Description
S5 Week 1: corporate announcement PDF documents are parsed and stored as text chunks in `nidp.documents`. S5 Week 2 (not yet implemented): embeddings computed and stored in the `embedding vector(1536)` column.

### Functional Requirements

**FR-NIDP-023.1 — Document Storage Schema**  
`nidp.documents` table (migration `031_nidp_documents.sql`):
- `document_id` (UUID PK)
- `announcement_id` (FK → `corporate_announcements`)
- `source` (NSE/BSE)
- `symbol` (equity ticker)
- `announcement_type` (from classifier)
- `chunk_index` (integer — position within document)
- `chunk_text` (TEXT — extracted content)
- `embedding` (vector(1536) NULL — populated by S5 Week 2 embedder)
- `ingested_at` (timestamptz)

**FR-NIDP-023.2 — Document Parser**  
`document_parser` ingester downloads PDF attachments from announcement URLs. Splits into chunks (target ~500 tokens per chunk). Writes to `nidp.documents` with `embedding = NULL`.

**FR-NIDP-023.3 — pgvector Extension**  
`nidp.documents.embedding` uses `pgvector` extension (type `vector(1536)`). NULL for all rows until S5 Week 2 embedder runs. Similarity search: `ORDER BY embedding <=> $query_embedding`.

**FR-NIDP-023.4 — S5 Week 2 Status**  
Embedder service: NOT YET IMPLEMENTED. The column exists and accepts vector data; no service currently populates it.

**FR-NIDP-023.5 — NIDP Copilot Integration**  
`backend/NIDP_COPILOT_INTEGRATION_PLAN.md` describes planned integration: Copilot V2 calls NIDP DaaS to inject market context (top movers, FII/DII flows, RBI yields, recent announcements) into agent prompts. Status: **PLANNED — not yet implemented**.

**Source:** `backend/nidp/services/document_parser/`, migration `031_nidp_documents.sql`

---

## FR-NIDP-024 — Portfolio Bridge

### Description
`portfolio_intelligence_sync` syncs NIDP-derived intelligence signals back to the Nivesh application's MongoDB, enabling the portfolio intelligence tab to display NIDP-enriched data.

### Functional Requirements

**FR-NIDP-024.1 — Sync Scope**  
Reads from `nidp.intelligence`, `nidp.stock_daily_snapshot`, `nidp.corporate_announcements` (last 7 days). Maps NIDP symbol space to Nivesh ISIN/fund space. Upserts to MongoDB collection `portfolio_intelligence_signals`.

**FR-NIDP-024.2 — Portfolio Sync Contract**  
Avro schema: `portfolio_holdings_snapshot_v1.schema.json` (JSON Schema format, not `.avsc`). Defines the shape of portfolio context sent from Nivesh app to NIDP.

**FR-NIDP-024.3 — Sync State Tracking**  
Migration `042_nidp_portfolio_bridge.sql` installs sync state table: `(symbol, sync_date, status, last_synced_at)`. Prevents redundant re-sync of already-current data.

**Source:** `backend/nidp/services/portfolio_intelligence_sync/`, `backend/nidp/docs/PORTFOLIO_SYNC_CONTRACT.md`, migration `042_nidp_portfolio_bridge.sql`

---

## FR-NIDP-025 — Test Suite

### Description
`backend/nidp/tests/` — test suite covering parsers, validation engine, backfill orchestration, and golden-file regression tests.

### Test Coverage

| Test File / Directory | Coverage |
|---|---|
| `backend/nidp/tests/parsers/` | Unit tests for each ingester's parser (bhavcopy, delivery, fii_dii, rbi_yields, fred_macro, corporate_actions, bulk_deals, block_deals) |
| `backend/nidp/tests/quality/` | Validation engine unit tests; BLOCK/FIX/WARN classification; CustomSQLRule tests |
| `backend/nidp/tests/services/` | Integration tests per ingester service |
| `backend/nidp/tests/test_backfill.py` | Backfill orchestrator: date range iteration, holiday skipping, concurrency |
| `backend/nidp/tests/test_failing_feeds_golden.py` | Golden-file tests: known-failing feed states produce expected `validation_findings` |
| `backend/nidp/tests/test_failing_feeds_persistence.py` | Failing feeds: BLOCK suppresses Kafka; PARTIAL still persists rows |
| `backend/nidp/tests/conftest.py` | Fixtures: in-memory Postgres (via `asyncpg` + Docker), Redpanda mock, GCS local stub |
| `backend/nidp/tests/fixtures/` | Sample CSV/JSON/HTML files for each feed (snapshot of known-good upstream responses) |

### Functional Requirements

**FR-NIDP-025.1 — Local Test Stack**  
`./deploy/test_locally.sh` brings up full test stack via Docker Compose: Postgres + Redpanda + Schema Registry + Redis + MinIO. Full Kafka event path tested. ~60 seconds per service.

**FR-NIDP-025.2 — Golden File Tests**  
`test_failing_feeds_golden.py` uses fixture files in `backend/nidp/tests/fixtures/` as known-good upstream responses. Parser output is compared against a golden snapshot. Failures indicate parser regression.

**FR-NIDP-025.3 — Persistence Tests**  
`test_failing_feeds_persistence.py` verifies the invariants:
- BLOCK finding → `job_log.status = FAILED`, Kafka emit suppressed, domain table rows still present (rows landed before validation)
- FIX finding → `job_log.status = PARTIAL`, rows present, Kafka emit proceeds
- `actual` column in `validation_findings` is TEXT `'True'`/`'False'` (not Python bool)

**Source:** `backend/nidp/tests/`

---

## Gap Analysis

| Requirement | Status | Notes |
|---|---|---|
| Phase 1A 13 core ingesters | IMPLEMENTED | All deployed as Cloud Run jobs; some need image rebuild (P0) |
| Phase 1B fundamentals | IMPLEMENTED | `nse_financials`, `nse_shareholding`, `price_adjuster`, `fno_bhavcopy` deployed |
| S4 announcements pipeline | IMPLEMENTED | NSE + BSE + classifier + document_parser live as of 2026-05-07 |
| S5 document intelligence | PARTIAL | `nidp.documents` table + `document_parser` implemented; embedder (S5 Week 2) NOT YET IMPLEMENTED |
| Mutual fund pipeline | IMPLEMENTED | 5 ingesters deployed |
| Corporate event intelligence | IMPLEMENTED | `event_calendar`, `event_day_poller`, `d1_prep`, `intelligence` deployed |
| Quality gate | IMPLEMENTED | `quality_gate` + `dq_ai` deployed |
| Intelligence layer (Phase 2) | IMPLEMENTED | `intelligence_layer`, `portfolio_intelligence_sync` deployed |
| Validation engine | IMPLEMENTED | BLOCK/FIX/WARN with `actual` TEXT gotcha documented |
| Avro contracts | IMPLEMENTED | 24 `.avsc` + 1 `.schema.json` in `contracts/` |
| GCS raw + parsed archive | IMPLEMENTED | Both layers write to GCS on every run |
| Snapshot builder | IMPLEMENTED | Preflight check implemented; fires after all daily ingesters |
| DaaS API | IMPLEMENTED | `daas_api/` service; `query_api/` serving DaaS routes |
| Key management | IMPLEMENTED | SHA-256 hash only stored; cleartext shown once |
| Backfill orchestration | IMPLEMENTED | CLI + Admin Console + SSH trigger; state tables in migration 045 |
| Replay engine | IMPLEMENTED | Policy-based; failure injector; admin proxy with VM-unreachable fallback |
| Feature flags | IMPLEMENTED | DB-backed; CLI + shared module |
| NIDP CLI | IMPLEMENTED | 13 commands; 27 registered services |
| 35 SQL migrations | IMPLEMENTED | Files 001–045 (non-sequential numbering in 006, 020-range) |
| GCP Cloud Run deployment | PARTIAL | All jobs deployed; Cloud Scheduler not activated for all (P0); GitHub triggers ready but untested end-to-end (P0) |
| Grafana + Prometheus | PARTIAL | Metrics exposed; NIDP-specific Grafana panels not complete (P2) |
| NIDP → Copilot integration | PLANNED | `NIDP_COPILOT_INTEGRATION_PLAN.md` written; no code wired yet |
| Strategy Builder | DEFERRED (P3) | Migrations 020-021 exist but service code uncommitted; decision pending |
| Shareholding pattern | DEFERRED (P4) | Table exists (migration 025); ingester stub present; not fully implemented |
| S5 Week 2 embedder | NOT STARTED | `embedding vector(1536)` column NULL for all rows |
| Telegram alerts | IMPLEMENTED (off) | Code present; `telegram_alerts` flag defaults to off |

---

*End of FRD — NIDP Project. All 8 layer FRDs are now complete.*
