# NIDP — Data Platform Status

_Last updated: 2026-05-06_

A single-page snapshot of what the Nivesh Intelligence Data Platform is fetching, storing, processing — and what isn't done yet. Each section ends with a verification snippet you can paste straight into `psql` or a shell.

## 0. The shape of NIDP, in one paragraph

NIDP is an isolated subproject under `backend/nidp/`. It runs **13 ingester services** as Cloud Run jobs (project `niveshdataintelligence`, region `asia-south1`). Each ingester `fetch → archive raw → parse → validate → persist → emit Kafka event → snapshot the parsed rows in DB`. Daily ingesters land in domain tables (`nidp.prices_eod`, `nidp.fii_dii_flows`, etc.). A separate `snapshot_builder` reads those domain tables and produces two cross-feed snapshot tables (`nidp.market_daily_snapshot`, `nidp.stock_daily_snapshot`) that downstream consumers (the Nivesh app, models, dashboards) read from. Storage backend is GCS (`nidp-raw-niveshdataintelligence`); database is TimescaleDB on a single GCP VM (`nidp-stack-vm`); event bus is Redpanda + Confluent Schema Registry on the same VM.

---

## 1. Data sources and where they land

| # | Service | Source | Frequency | Domain table | Notes |
|---|---------|--------|-----------|--------------|-------|
| 1 | `bhavcopy` | NSE archives — unified post-2024 CM CSV (`BhavCopy_NSE_CM_*.csv`) | Daily, ~18:00 IST | `nidp.prices_eod` (`source='NSE_BHAV'`) | EQ rows only (Sgmt=CM, FinInstrmTp∈{STK,EQ}); F&O rows filtered out. Bumps `nidp.market_session_state`. |
| 2 | `delivery` | NSE archives — bhavcopy with delivery columns (republished T+1) | Daily, ~10:30 IST next morning | `nidp.delivery_data` | Delivery qty + delivery % per symbol-date. |
| 3 | `index_close` | NSE archives — `ind_close_all_DDMMYYYY.csv` | Daily, ~19:00 IST | `nidp.index_eod` | Closes for Nifty 50/100/500/Bank Nifty/India VIX, etc. |
| 4 | `index_constituents` | NSE archives — `ind_<index>list.csv` per index | Monthly, 1st of month | `nidp.index_constituents` | Nifty 50, 100, 500 membership snapshots. |
| 5 | `fii_dii` | NSE rolling JSON API `/api/fiidiiTradeReact` | Daily, ~19:30 IST | `nidp.fii_dii_flows` | EQUITY_CASH only (new endpoint dropped F&O). FII/FPI folded into 'FII'. |
| 6 | `corporate_actions` | NSE JSON API `/api/corporates-corporateActions?index=equities` | Daily, ~20:00 IST | `nidp.corporate_actions` | Dividends, splits, bonuses, rights — with ex-date / record-date. |
| 7 | `nse_calendar` | NSE JSON API `/api/holiday-master?type=trading` | Monthly, 1st of month | `nidp.nse_holidays` | Drives `compute_last_trading_day_ist()`. |
| 8 | `bulk_deals` | NSE JSON API `/api/historical/bulk-deals` | Daily, ~19:30 IST | `nidp.bulk_deals` | Trades > 0.5% of listed quantity. |
| 9 | `block_deals` | NSE JSON API `/api/historical/block-deals` | Daily, ~19:30 IST | `nidp.block_deals` | Negotiated block trades. |
| 10 | `rbi_yields` | RBI WSS HTML (`WSSViewDetail.aspx`) | Weekdays, ~20:30 IST | `nidp.rbi_yields` | G-Sec 10Y/5Y/1Y, T-Bill 91D/364D. Parser handles daily-rows AND weekly-cols layouts. |
| 11 | `fred_macro` | FRED CSV (`fredgraph.csv?id=<series>`) | Daily, ~21:00 IST | `nidp.fred_macro_observations` | 8 curated US macro series. |
| 12 | `yfinance_backfill` | Yahoo Finance per-symbol chart API | **Manual / event-driven** | `nidp.prices_eod` (`source='YFINANCE'`) | Backfill only — fills the long-tail history bhavcopy doesn't cover (older years, missing days). |
| 13 | `snapshot_builder` | Reads from above tables | Daily, ~22:00 IST after all ingesters | `nidp.market_daily_snapshot`, `nidp.stock_daily_snapshot` | Per-(symbol,date) row with OHLCV + delivery + flows + index membership + upcoming corporate actions. |

### Verify (run on the VM)

```bash
sudo docker exec nidp-postgres psql -U postgres -d nidp -c "
-- Per-feed health: when did each feed last run, and did it land rows?
SELECT
    ingester,
    last_run_status,
    last_run_at::timestamp(0) AS last_run,
    last_run_duration_ms      AS dur_ms,
    success_count             AS oks,
    failure_count             AS fails,
    consecutive_failures      AS cons_fails
  FROM nidp.v_feed_status
 ORDER BY last_run_at DESC NULLS LAST;
"
```

---

## 2. Storage architecture

Three layers, three intents.

### 2a. Raw archive (`nidp.raw_archive_files`) — replay substrate

Every fetched response is hashed (sha256), de-duplicated, and pushed to GCS at `gs://nidp-raw-niveshdataintelligence/<ingester>/<YYYY>/<MM>/<sha12>.<ext>`. The DB row indexes the bytes by `(ingester, target_date, sha256)`. If the parser changes tomorrow, we can replay every past run from these bytes — never re-fetching from upstream.

### 2b. Parsed archive (`nidp.parsed_archive_files`) — recompute substrate

The normalised rows (post-parse + validate) are also serialised to gzipped JSONL on GCS at `parsed/<ingester>/<YYYY>/<MM>/<sha12>.jsonl.gz`. Indexed in `parsed_archive_files`. This means a model-rebuild can read the parsed JSONL directly — without re-running the parser at all.

### 2c. Domain tables — query substrate

The 13 service-specific tables listed above (`prices_eod`, `delivery_data`, `index_eod`, `fii_dii_flows`, `corporate_actions`, `bulk_deals`, `block_deals`, `nse_holidays`, `rbi_yields`, `fred_macro_observations`, `index_constituents`). These are what production consumers actually `SELECT` from.

### 2d. Snapshot tables — coherence layer

- `nidp.market_daily_snapshot` — one row per `as_of_date`. Headline indices, FII/DII totals, RBI yields, market breadth.
- `nidp.stock_daily_snapshot` — one row per `(symbol, as_of_date)`. OHLCV + delivery % + index membership + recent deal activity + upcoming-corp-actions flag.
- `nidp.feed_snapshot` — one row per `(ingester, snapshot_date)` with the parsed rows as JSONB. Lets a model rebuild replay any past day with a single SELECT.
- `nidp.daily_snapshot` — readiness coordinator; only date-Ds with `snapshot_status='READY'` and no `BLOCK` validation findings produce a stock snapshot.

### 2e. Operational tables

- `nidp.job_log` — one row per run; status + duration + rows_fetched/inserted/skipped + error.
- `nidp.source_registry` — one row per feed; counters (success/failure/partial), `last_run_at`, `next_run_at`, `consecutive_failures`, schedule.
- `nidp.v_feed_status` — view joining the above with the latest `feed_snapshot` and `job_log`. **Single-pane health view.**
- `nidp.market_session_state` — denormalised "last NSE close" date. Read by all date-defaulting ingesters; bumped by bhavcopy on success.
- `nidp.validation_findings` — DQ engine output; one row per BLOCK/FIX/WARN finding.

### Verify

```bash
sudo docker exec nidp-postgres psql -U postgres -d nidp -c "
-- All NIDP tables and approximate row counts
SELECT relname AS table, n_live_tup AS rows
  FROM pg_stat_user_tables
 WHERE schemaname='nidp'
 ORDER BY n_live_tup DESC LIMIT 30;
"
```

```bash
# Spot-check the GCS raw archive
gcloud storage ls gs://nidp-raw-niveshdataintelligence/bhavcopy/2026/05/ \
    --project=niveshdataintelligence | head
gcloud storage ls gs://nidp-raw-niveshdataintelligence/parsed/bhavcopy/2026/05/ \
    --project=niveshdataintelligence | head
```

---

## 3. Processing layer

### 3a. BaseIngester (the orchestration spine)

Every ingester subclasses `nidp.shared.ingester_base.BaseIngester` and implements `fetch / parse / validate / persist`. The base class wraps:

1. **JobRun** lifecycle (RUNNING → OK / PARTIAL / FAILED / SKIPPED) — exactly one `nidp.job_log` row per invocation.
2. **Raw archive** — write source bytes, index sha256.
3. **Validation** — DQ engine runs after persist; writes findings; BLOCK suppresses the Kafka event.
4. **Parsed archive + per-feed snapshot** — gzipped JSONL on GCS + JSONB row in `feed_snapshot`.
5. **Kafka emit** — Avro-serialised `IngestionCompleted` event on `nidp.ingestion_completed.v1` (suppressed on BLOCK).
6. **Source-registry roll-up** — `success_count`, `last_run_status`, `next_run_at` derived from `expected_freq`.
7. **Market-session bump** — for the canonical "trading day closed" feed (currently bhavcopy only).

### 3b. Validation engine (Data Quality)

Per-feed rules registered in `nidp/services/<svc>/validators.py`. Three rule types:
- `CountAtLeastRule` — assert ≥ N rows for the run (e.g. bhavcopy: ≥1500).
- `NoNullsRule` — required columns must be non-null.
- `RangeRule` — numeric columns must lie in a sane range (e.g. RBI yields ∈ [0.5%, 20%]).
- `CustomSQLRule` — arbitrary SQL (e.g. fii_dii: `net = buy − sell` within ₹1 cr).

Findings are classified BLOCK / FIX / WARN. BLOCK suppresses downstream Kafka emit. FIX is logged but lets the run proceed.

### 3c. Snapshot builder

After all daily ingesters run, `snapshot_builder` reads from domain tables and produces:
- `market_daily_snapshot` — one row per as-of date (indices, FII/DII totals, breadth).
- `stock_daily_snapshot` — one row per `(symbol, as_of_date)` joining bhavcopy + delivery + index membership + upcoming corp actions.

Has a **preflight** check: requires ≥1500 rows in `prices_eod` for the target date before it'll build. If less, fails loudly — never builds a half-baked snapshot.

### Verify

```bash
sudo docker exec nidp-postgres psql -U postgres -d nidp -c "
-- Snapshot health: latest snapshot dates
SELECT 'market_daily_snapshot' AS tbl,
       max(as_of_date)         AS latest,
       count(*)                AS total_dates
  FROM nidp.market_daily_snapshot
UNION ALL
SELECT 'stock_daily_snapshot',
       max(as_of_date),
       count(DISTINCT as_of_date)
  FROM nidp.stock_daily_snapshot;

-- BLOCK / FIX findings open right now
SELECT failure_class, count(*)
  FROM nidp.validation_findings
 WHERE created_at > NOW() - INTERVAL '7 days'
 GROUP BY failure_class
 ORDER BY count(*) DESC;
"
```

---

## 4. Operational layer

| Component | Status | Notes |
|-----------|--------|-------|
| **Cloud Run jobs (13)** | Live | All deployed; some still on stale image versions (need rebuild — see §5). |
| **Cloud Scheduler triggers (12)** | Script ready (`setup_schedules.sh`); not yet activated for all jobs | Daily fires at IST evening (~19:00–22:00). yfinance is event-driven only. |
| **GitHub-push → Cloud Build** | YAMLs + script ready (`setup_github_triggers.sh`); 14 triggers fire on push to nidp branch | One per service + 1 for migrations. Migration trigger uses IAP-tunnelled SSH. Auth issue resolved (commit `b97052b`). |
| **Local validation loop** | Working | `./test_locally.sh` brings up Postgres + Redpanda + Schema Registry, runs full Kafka path. ~60s per service. |
| **Migrations** | 12 SQL files; 023 latest | Applied via `phase6_robust.sh` (idempotent). Wired into `build_on_gcp.sh` so a code rebuild also applies pending SQL. |
| **Storage backend** | GCS bucket `nidp-raw-niveshdataintelligence` | Pluggable: LocalDisk for tests, S3 supported, GCS in prod. |
| **Event bus** | Redpanda (Kafka-compatible) on VM, port 9092 | Built-in Schema Registry on container port 8081 — published to host after listener fix. |
| **Database** | TimescaleDB-pg16 on VM, port 5433 | 8 GB RAM is the bottleneck if all containers are up at once. |
| **Observability** | Prometheus + Grafana on VM (no NIDP dashboards yet) | Each ingester exposes `/metrics` on per-service port. |

### Verify

```bash
# Cloud Run jobs (laptop)
gcloud run jobs list --region=asia-south1 --project=niveshdataintelligence \
    --format='table(metadata.name,status.latestCreatedExecution.creationTimestamp.date(format="%Y-%m-%d %H:%M"))' \
    | grep ^nidp-

# Cloud Build triggers (laptop)
gcloud builds triggers list --region=asia-south1 --project=niveshdataintelligence \
    --format='table(name,filename)' | grep ^nidp-

# Cloud Scheduler triggers (laptop)
./list_schedules.sh

# VM containers (on the VM)
sudo docker ps --format 'table {{.Names}}\t{{.Status}}'

# Migration history (on the VM)
sudo docker exec nidp-postgres psql -U postgres -d nidp -c "
SELECT filename FROM nidp.schema_migrations ORDER BY filename;
"
```

---

## 5. What's pending

Ordered by P0 → P3.

### P0 — Production validation (today)

- [ ] **All 13 Cloud Run jobs verified green** (latest image, latest run = OK). bhavcopy / snapshot_builder / fred_macro / yfinance still need their first clean run on the latest code.
- [ ] **`yfinance_backfill` 180-day run** so `prices_eod` has ≥6 months of history before models start consuming.
- [ ] **GitHub push-trigger wired up end-to-end** — `setup_github_triggers.sh` must show all 14 triggers green; one trivial-edit-and-push test confirms auto-rebuild fires.

### P1 — NIDP → app integration (this week)

- [ ] Replace existing Nivesh dashboard's signal proxies with reads from `nidp.market_daily_snapshot` / `nidp.stock_daily_snapshot`.
  - Removes the `^TNX` US-yield bug (use `rbi_yields.10Y` instead).
  - Removes broken FII/DII path.
  - Unlocks correct delivery %, index membership, upcoming-corp-action flags in stock detail pages.

### P2 — Operational visibility (this week)

- [ ] **Validation findings dashboard.** `nidp.validation_findings` is being written but nothing reads it. Either a Grafana panel or a small `/admin/data-health` page in the Nivesh app.
- [ ] **Grafana dashboard from `nidp.v_feed_status` + Prometheus** — at-a-glance "is everything green today" without `psql`.
- [ ] **Cloud Scheduler activation** — run `setup_schedules.sh` once and confirm next-fire times in `list_schedules.sh`.

### P3 — Untracked Strategy Builder code

A pile of files from prior sessions sits in working-tree limbo:
- `backend/nidp/services/feature_snapshotter/`
- `backend/nidp/migrations/020_strategy_builder_core.sql`, `021_stock_features_daily.sql`
- `backend/services/strategy_engine/`, `backend/routes/strategy_builder.py`, `backend/tests/test_strategy_engine.py`
- `frontend/src/components/strategyBuilder/`, `frontend/src/pages/StrategyBuilder.jsx`, `frontend/src/api/`
- `docs/STRATEGY_BUILDER_PLAN.md`

Decision needed: commit, refactor, or remove.

### P4 — Deferred PRD items (next sprint)

- [ ] **Shareholding pattern** ingester (BSE/NSE quarterly XBRL).
- [ ] **Quarterly financial results** ingester (BSE corporate filings JSON).
- [ ] **Corporate filings** broader (board meetings, AGM resolutions).
- [ ] **Cloud Run timeout / retry tuning** — defaults work; revisit when load patterns are visible.

---

## 6. End-to-end verification (one-liner)

For a fresh-eyes "is this whole thing actually working?" check, run on the VM:

```bash
sudo docker exec nidp-postgres psql -U postgres -d nidp <<'SQL'
\echo === FEED HEALTH ===
SELECT ingester, last_run_status, success_count AS oks, failure_count AS fails,
       last_run_at::timestamp(0) AS last_run
  FROM nidp.v_feed_status ORDER BY ingester;

\echo === DOMAIN TABLE COUNTS (last 7 days) ===
SELECT 'prices_eod'        tbl, count(*) FROM nidp.prices_eod        WHERE as_of_date >= CURRENT_DATE - 7
UNION ALL SELECT 'delivery_data',     count(*) FROM nidp.delivery_data     WHERE as_of_date >= CURRENT_DATE - 7
UNION ALL SELECT 'index_eod',         count(*) FROM nidp.index_eod         WHERE as_of_date >= CURRENT_DATE - 7
UNION ALL SELECT 'fii_dii_flows',     count(*) FROM nidp.fii_dii_flows     WHERE as_of_date >= CURRENT_DATE - 7
UNION ALL SELECT 'corporate_actions', count(*) FROM nidp.corporate_actions WHERE record_date >= CURRENT_DATE - 7
UNION ALL SELECT 'bulk_deals',        count(*) FROM nidp.bulk_deals        WHERE as_of_date >= CURRENT_DATE - 7
UNION ALL SELECT 'block_deals',       count(*) FROM nidp.block_deals       WHERE as_of_date >= CURRENT_DATE - 7
UNION ALL SELECT 'rbi_yields',        count(*) FROM nidp.rbi_yields        WHERE as_of_date >= CURRENT_DATE - 14
UNION ALL SELECT 'nse_holidays',      count(*) FROM nidp.nse_holidays
ORDER BY 1;

\echo === SNAPSHOTS ===
SELECT 'market_daily' tbl, count(*) FROM nidp.market_daily_snapshot
UNION ALL SELECT 'stock_daily', count(*) FROM nidp.stock_daily_snapshot
UNION ALL SELECT 'feed_snapshot', count(*) FROM nidp.feed_snapshot;

\echo === MARKET SESSION ===
SELECT * FROM nidp.v_market_session;

\echo === RECENT VALIDATION FINDINGS ===
SELECT failure_class, severity, count(*)
  FROM nidp.validation_findings
 WHERE created_at > NOW() - INTERVAL '7 days'
 GROUP BY 1, 2 ORDER BY 1, 2;
SQL
```

A green NIDP looks like:
- `v_feed_status`: every row `last_run_status='OK'`, `consecutive_failures=0`
- Domain table counts: each daily feed > 0 for the last 7 days; bhavcopy ~14k (2k/day × 7 days)
- `market_daily_snapshot` ≥ 5; `stock_daily_snapshot` ≈ 14k; `feed_snapshot` ≥ 60 (12 daily × 5 days)
- `v_market_session.last_close_date` = yesterday or today IST
- Validation findings: zero BLOCK; FIX/WARN < 5
