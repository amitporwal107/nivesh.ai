# Nivesh Market Data Platform Improvement Program
## Two-VM High Availability & Scalable Architecture PRD

## Executive Summary

This PRD defines the modernization strategy for the NIDP/Master Data Feed ecosystem.

The target architecture is:

- Highly reliable
- Replayable
- Idempotent
- Scalable
- Cost optimized
- Institution-grade

while operating efficiently on:

```text
Two Linux VMs
```

The architecture focuses on:

- Event-driven processing
- Replayability
- Queue-based scalability
- Time-series optimization
- Hot/Warm/Cold storage
- High availability
- Deterministic pipelines
- Operational simplicity

---

# High-Level Architecture

```text
                External Sources
                        |
                        v
                Feed Downloaders
                        |
                        v
                 Immutable Raw Layer
                       (MinIO)
                        |
                        v
                 Redpanda Event Bus
                        |
    ------------------------------------------------
    |              |              |                |
    v              v              v                v
 Parsers      Validators     Replay Engine    Repair Engine
    |              |              |
    --------------------------------
                    |
                    v
           Canonical Processing Layer
                    |
       ----------------------------------
       |                                |
       v                                v
PostgreSQL + TimescaleDB          Redis Cache
       |
       v
Derived Intelligence Layer
       |
       v
      APIs
```

---

# Two-VM Deployment Architecture

## VM-1 — Core Services

### Responsibilities

- PostgreSQL
- TimescaleDB
- Redis Primary
- API Layer
- HAProxy / Nginx
- Prometheus
- Grafana
- Loki
- Feed Registry

### Recommended Specs

| Resource | Requirement |
|---|---|
| CPU | 8 vCPU |
| RAM | 32 GB |
| Storage | 500 GB NVMe SSD |

---

## VM-2 — Compute & Standby

### Responsibilities

- Feed ingestion workers
- Parser workers
- Validation workers
- Replay engine
- Factor engine
- Redpanda
- MinIO
- PostgreSQL replica
- Redis replica

### Recommended Specs

| Resource | Requirement |
|---|---|
| CPU | 16 vCPU |
| RAM | 64 GB |
| Storage | 1 TB NVMe SSD |

---

# Recommended Technology Stack

| Concern | Technology |
|---|---|
| Containers | Docker Compose |
| Reverse Proxy | HAProxy / Nginx |
| Event Streaming | Redpanda |
| Object Storage | MinIO |
| OLTP | PostgreSQL |
| Time-Series | TimescaleDB |
| Cache | Redis |
| Analytics | DuckDB |
| Monitoring | Prometheus |
| Visualization | Grafana |
| Logging | Loki |
| APIs | FastAPI / Spring Boot |

---

# Core Architectural Principles

## Immutable Raw Data

Every raw feed must be stored permanently.

Never overwrite raw data.

---

## Idempotent Processing

All writes must support UPSERT semantics:

```sql
INSERT ... ON CONFLICT DO UPDATE
```

---

## Event-Driven Processing

All downstream systems react using:

```text
Redpanda events
```

instead of direct process chaining.

---

## Replayability

Entire platform should rebuild from raw files.

---

## Partial Failure Isolation

Bad records should:

```text
quarantine
```

while good records continue processing.

---

# High Availability Strategy

## PostgreSQL HA

```text
Primary PostgreSQL (VM-1)
        ↓ WAL Replication
Standby PostgreSQL (VM-2)
```

### Features

- Streaming replication
- WAL archiving
- PITR recovery
- Standby promotion

---

## Redis HA

```text
Redis Primary
      ↓
Redis Replica
```

### Features

- AOF persistence
- Snapshot backups

---

## API HA

Run APIs on BOTH VMs behind:

- HAProxy
- Nginx

---

## Worker HA

Workers must remain stateless.

Queue-based retry handling mandatory.

---

# Feed Registry Design

## Core Tables

### feed_registry

Contains:

- feed_name
- source_name
- SLA
- parser_version
- retry_policy
- owner

---

### feed_execution

Contains:

- execution_id
- status
- row counts
- retry counts
- latency
- checksum

---

### feed_dependencies

Contains:

- upstream feeds
- downstream feeds
- dependency types

---

### quarantine_records

Contains:

- raw payload
- validation failures
- replay eligibility

---

# Queue Architecture

## Core Topics

| Topic | Purpose |
|---|---|
| raw_downloaded | feed arrival |
| parse_completed | parser completion |
| validation_failed | quarantine |
| replay_requested | replay engine |
| derived_ready | downstream rebuild |

---

# Time-Series Optimization Strategy

## TimescaleDB Hypertables

All time-series datasets must use:

```text
Hypertables
```

---

## Partition Strategy

### Primary Partition

```text
trade_date
```

### Secondary Partition

```text
hash(symbol)
```

---

## Compression Strategy

Enable:

- Chunk compression
- Continuous aggregates
- Compression policies

---

## Continuous Aggregates

Precompute:

- Moving averages
- Rolling volumes
- Factor summaries
- Technical indicators

---

# Hot / Warm / Cold Storage Architecture

## HOT Layer

Technologies:

- PostgreSQL
- TimescaleDB
- Redis

Datasets:

- Recent OHLC
- Live quotes
- Active factors
- Recent NAV

---

## WARM Layer

Technologies:

- Compressed Timescale chunks
- Parquet exports
- DuckDB analytics

Datasets:

- Historical OHLC
- Historical NAV
- Factor history
- Backtesting datasets

---

## COLD Layer

Technologies:

- MinIO

Datasets:

- Raw files
- Replay archives
- Historical snapshots
- Logs

---

# DuckDB Strategy

DuckDB shall support:

- Historical analytics
- Parquet querying
- Replay analytics
- AI datasets
- Factor research

DuckDB SHALL NOT be:

- OLTP database
- Transactional source of truth
- Distributed serving DB

---

# Scalability Strategy

Scale using:

- Additional workers
- Queue parallelism
- Partitioning
- Compression
- Caching
- Storage tiering

NOT through:

- Premature distributed clusters

---

# Load Balancing Strategy

## API Load Balancing

Use:

- HAProxy
- Nginx

across API containers on both VMs.

---

## Worker Distribution

Use:

```text
queue-based competing consumers
```

instead of classic load balancing.

---

# Backup & Disaster Recovery

## PostgreSQL

- WAL archiving
- Daily backups
- PITR recovery
- Standby replication

---

## Redis

- AOF persistence
- Snapshot backups

---

## MinIO

- Daily snapshots
- Backup replication

---

# Monitoring & Observability

## Metrics

Track:

- Feed latency
- Queue lag
- Validation failures
- Parser errors
- Replay status
- API latency
- DB replication lag

---

## Dashboards

- Feed Health
- Queue Monitoring
- API Health
- Replay Monitoring
- DB Replication

---

# Security Requirements

## Infrastructure

- Private internal networking
- Firewall isolation
- SSH key authentication

---

## APIs

- JWT authentication
- RBAC authorization
- Rate limiting

---

# Implementation Status — as of 2026-05-27

## Live / Production

| Component | Status | Notes |
|---|---|---|
| TimescaleDB (port 5433) | ✅ LIVE | 55+ migrations, nidp schema |
| PostgreSQL replica (port 5432) | ✅ LIVE | staging replica |
| Redis cache | ✅ LIVE | nidp-redis container |
| Redpanda event bus | ✅ LIVE | nidp-redpanda container (local dev) |
| MinIO object storage | ✅ LIVE | nidp-minio container |
| Prometheus + Grafana | ✅ LIVE | data.niveshcopilot.com/grafana |
| NSE/BSE price feed | ✅ LIVE | daily OHLCV, 13 Cloud Run ingesters |
| NSE/BSE announcement pipeline (S4) | ✅ LIVE | classifier → pgvector, since 2026-05-07 |
| V3 scoring engine | ✅ LIVE | quality + health scores, daily cron |
| NSE Integrated XBRL parser | ✅ LIVE | full P&L + balance sheet from \_WEB.xml |
| Screener.in quarterly parser | ✅ LIVE | event-driven on result announcement days |
| Screener.in balance sheet parser | ✅ LIVE | wired 2026-05-27 |
| Screener.in annual P&L parser | ✅ LIVE | wired 2026-05-27 (new) |
| Screener.in shareholding parser | ✅ LIVE | wired 2026-05-27 |
| Historical backfill (Nifty 500) | ✅ DONE | 213/504 symbols, remainder in progress |
| job_log + exception_queue | ✅ LIVE | DQ dashboard visibility |

## Primitive Coverage — Nifty 500 (2026-05-27 post-backfill)

| Primitive | Score | Weight | Coverage Before | Coverage After |
|---|---|---|---|---|
| roe_pct | Quality | 25% | 0% | ~42% → 85%+ after full backfill |
| debt_to_equity | Quality | 15% | 0% | ~42% → 85%+ |
| eps_growth_3y_cagr | Quality | 20% | 91% | 91% |
| promoter_pct | Quality | 10% | 9% | ~41% → 85%+ |
| market_cap_bucket | Quality | 10% | 0% | ~43% → 85%+ |
| earnings_consistency | Quality | 20% | 93% | 93% |
| revenue_growth_3y_cagr | Health | 25% | 0% | ~23% → 60%+ |
| profit_margin_trend | Health | 20% | 0% | ~36% → 70%+ |
| debt_trend | Health | 15% | 0% | ~35% → 70%+ |
| earnings_surprise | Health | 15% | 0% | 0% — needs consensus estimates source |
| volatility_1y | Health | 10% | 100% | 100% |
| dividend_yield | Health | 5% | 100% | 100% |

---

# Scaling Roadmap

## Phase 1 — Foundation

| Task | Status |
|---|---|
| PostgreSQL primary (TimescaleDB) | ✅ DONE |
| Redis | ✅ DONE |
| MinIO | ✅ DONE (container) |
| Redpanda | ✅ DONE (container) |
| Replay engine | ❌ NOT BUILT |
| Quarantine system (exception_queue) | ✅ DONE (DB table + DQ dashboard) |
| Feed registry (feed_registry table) | ❌ NOT BUILT |
| PostgreSQL HA / WAL replication | ❌ NOT BUILT |

---

## Phase 2 — Intelligence Layer

| Task | Status |
|---|---|
| Parquet archival | ❌ NOT BUILT |
| DuckDB analytics | ❌ NOT BUILT |
| TimescaleDB continuous aggregates | ❌ NOT BUILT |
| Distributed workers | ❌ NOT BUILT — single-threaded Cloud Run |
| S4/S5 embedding pipeline | 🔄 IN PROGRESS — S5 embedder Week 2 |

---

## Phase 3 — Advanced Platform

| Task | Status |
|---|---|
| AI-assisted feed healing | ❌ NOT BUILT |
| Schema drift intelligence | ❌ NOT BUILT |
| Automated anomaly explanations | ❌ NOT BUILT |

---

# Remaining Tasks — Prioritised

## P0 — Complete Current Backfill (this week)

1. **Resume Screener.in backfill for remaining 271 Nifty 500 symbols** — rate-limit cooldown ~45 min, then re-run without `--force`
2. **Re-run `populate_stock_features_extended` + `populate_stock_features_v3` + `v3_scores_engine`** — after backfill completes, recompute all primitives and scores for new symbols
3. **Add BAJAJFINSV slug to `_SCREENER_SLUG_MAP`** — currently returns not_found (correct slug is `BAJAJ-FINSERV`)

## P1 — Data Coverage Gaps (next 2 weeks)

4. **`earnings_surprise_pct` source** — needs quarterly consensus EPS estimates; evaluate NSE XBRL comparator or screener.in ratios section as proxy
5. **AMC scrapers fix** — `mf_holdings` + `mf_disclosure_snapshot` scrape 10 AMC sites that all 404/changed URL; blocks 4 MF scoring primitives at 0% coverage
6. **Screener.in session cookie rotation** — current cookie expires 2026-06; automate rotation or add alert before expiry
7. **Wire cron for `populate_stock_features_extended` + `v3_scores_engine`** — currently missing from NIDP cron schedule; both need daily entries after price feed runs

## P2 — Scoring Quality (next month)

8. **`earnings_consistency_score` methodology sweep** — currently uses EPS sign consistency over 5 quarters; verify it handles loss-making companies correctly
9. **Score band calibration** — with real primitive data now flowing, validate score distribution is not clustering near 50 (the null-fallback value); recalibrate bands if needed
10. **Ranking gate** — don't surface scores for symbols with quality_coverage_pct < 50%; UI should show "Insufficient data" instead of a potentially misleading score
11. **`short_term_debt_cr` gap** — Screener.in lumps all borrowings; no split available; affects D/E precision for NBFCs and banks; consider NSE XBRL balance sheet as supplemental source

## P3 — Infrastructure (next quarter)

12. **Feed registry table** — implement `feed_registry` + `feed_execution` tables for SLA tracking and replay eligibility
13. **Replay engine** — ability to re-derive primitives and scores from raw archived data without re-fetching from source
14. **PostgreSQL HA** — WAL replication from nidp-stack-vm to standby; currently single-point-of-failure
15. **TimescaleDB continuous aggregates** — precompute rolling 20/50/200 day averages for price features instead of computing on-the-fly
16. **Parquet export + DuckDB** — archive `nse_financials_quarterly` + `stock_features_daily` to MinIO as Parquet for backtesting and AI dataset generation
17. **Screener.in rate limit strategy** — implement polite batching with jitter + time-of-day scheduling (off-peak: 2–5 AM IST) to avoid hitting rate limits on full Nifty 500 weekly refresh

---

# Strategic Long-Term Moats

1. Replayable financial intelligence platform
2. Canonical security graph
3. AI-ready historical datasets
4. Deterministic derived analytics
5. Institutional-grade lineage
6. Scalable time-series intelligence
7. Unified equity + MF intelligence layer

---

# Final Recommendation

The architecture intentionally optimizes for:

- simplicity,
- replayability,
- deterministic processing,
- scalability,
- low cost,
- and evolution readiness.

The objective is NOT to prematurely build hyperscale infrastructure.

The objective is to build:

```text
A replayable, scalable, institution-grade financial intelligence core
that evolves incrementally without major rewrites.
```

---

*Last updated: 2026-05-27 — post Screener.in full-parsers wire-up and Nifty 500 backfill run*
