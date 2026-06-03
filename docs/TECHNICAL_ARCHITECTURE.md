# Nivesh.ai + NIDP — Technical Architecture Document

**Version:** 1.0  
**Last updated:** 2026-05-29  
**Author:** Platform Engineering  
**Status:** VALIDATED AGAINST CODE AND DEPLOYED INFRASTRUCTURE

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Tech Stack](#2-tech-stack)
3. [Infrastructure — GCP & VMs](#3-infrastructure--gcp--vms)
4. [Nivesh Application Architecture](#4-nivesh-application-architecture)
5. [NIDP Data Platform Architecture](#5-nidp-data-platform-architecture)
6. [Database Schemas](#6-database-schemas)
7. [Data Lake & Storage](#7-data-lake--storage)
8. [Data Feeds & Cron Schedule](#8-data-feeds--cron-schedule)
9. [NIDP DaaS OpenAPI Reference](#9-nidp-daas-openapi-reference)
10. [Nivesh App OpenAPI Reference](#10-nivesh-app-openapi-reference)
11. [Observability Stack](#11-observability-stack)
12. [CI/CD Pipeline](#12-cicd-pipeline)
13. [Security & IAM](#13-security--iam)
14. [DevOps Guidelines](#14-devops-guidelines)
15. [Operations Cheat Sheet](#15-operations-cheat-sheet)

---

## 1. System Overview

Nivesh.ai is an AI-powered wealth management copilot for Indian retail investors. It is composed of two independently deployable systems:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           NIVESH PLATFORM                                     │
│                                                                                │
│  ┌────────────────────────────────┐   ┌───────────────────────────────────┐  │
│  │      NIVESH APPLICATION         │   │         NIDP DATA PLATFORM         │  │
│  │  nivesh-app-vm (34.47.250.214) │   │   nidp-stack-vm (34.93.60.254)    │  │
│  │                                 │   │                                    │  │
│  │  React 19 / Vite Frontend       │   │  28 Cloud Run Ingesters            │  │
│  │  FastAPI Backend (Python 3.11)  │   │  DaaS API (FastAPI)                │  │
│  │  MongoDB 7 (user data)          │   │  Query API (FastAPI)               │  │
│  │  PostgreSQL 16 (analytics)      │   │  TimescaleDB-pg16 (market data)    │  │
│  │  Redis 7 (cache / APScheduler)  │   │  Redpanda (event bus)              │  │
│  │  LangGraph Agent Framework      │   │  Prometheus + Grafana              │  │
│  │  APScheduler (nightly batch)    │   │  Loki + Promtail (logs)            │  │
│  │                                 │   │  MinIO (Parquet WARM archive)      │  │
│  └────────────────────────────────┘   └───────────────────────────────────┘  │
│                  ▲                                      ▼                      │
│                  └─── nidp-bridge Docker network ───────┘                     │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Public URLs:**
| Environment | URL |
|---|---|
| Production (Nivesh app) | https://niveshcopilot.com |
| Staging (Nivesh app) | https://staging.niveshcopilot.com |
| NIDP DaaS + Grafana | https://data.niveshcopilot.com |

---

## 2. Tech Stack

### 2.1 Nivesh Application

| Layer | Technology | Version |
|---|---|---|
| **Frontend** | React | 19.0.0 |
| **Frontend routing** | React Router | 7.5.1 |
| **Frontend state** | TanStack Query (V5) | frontend-v5 only |
| **UI components** | Radix UI | various |
| **Styling** | Tailwind CSS | 3.x |
| **Build tool** | Vite (frontend-v5), CRA+CRACO (legacy) | — |
| **Animations** | Framer Motion | — |
| **Charts** | Recharts | — |
| **Forms** | react-hook-form + Zod | — |
| **Mobile** | Capacitor 7 (iOS/Android) | 7.x |
| **Backend** | FastAPI | 0.110.1 |
| **Python** | CPython | 3.11 |
| **Async HTTP** | httpx, aiohttp | — |
| **ORM/DB** | asyncpg (PostgreSQL), Motor (MongoDB) | — |
| **Validation** | Pydantic v2 | — |
| **Task scheduler** | APScheduler | 3.11.2 |
| **AI / LLM** | OpenAI GPT-4o-mini (primary) | — |
| **AI framework** | LangGraph (agent orchestration) | — |
| **LLM routing** | LiteLLM | 1.80.0 |
| **Google AI** | google-genai, anthropic | 1.71.0 / 0.40+ |
| **Auth** | Authlib (Google OAuth 2.0) | 1.6.10 |
| **CAS parsing** | casparser, Google Document AI, Claude Vision | — |
| **Storage** | GCS (boto3 + google-cloud-storage) | — |
| **Secrets** | GCP Secret Manager | — |
| **Tracing / RAG** | emergentintegrations | 0.1.0 |

### 2.2 NIDP Data Platform

| Layer | Technology | Version |
|---|---|---|
| **Language** | Python | 3.11 |
| **HTTP API** | FastAPI + uvicorn | 0.110+ |
| **Async DB** | asyncpg | 0.29+ |
| **Database** | TimescaleDB (PostgreSQL 16 with timescaledb extension) | latest-pg16 |
| **Event bus** | Redpanda (Kafka-compatible) | latest |
| **Schema registry** | Confluent Schema Registry | 7.5.0 |
| **Kafka client** | confluent-kafka (Avro + schema-registry) | 2.3+ |
| **Cache** | Redis 7 | alpine |
| **Object storage** | MinIO (local dev), GCS (prod) | — |
| **GCS SDK** | google-cloud-storage | 2.14+ |
| **S3 SDK** | boto3 | 1.34+ |
| **HTML parsing** | beautifulsoup4 + lxml | 4.12+ / 5+ |
| **Excel parsing** | openpyxl, xlrd | 3.1+ / 1.2+ |
| **DataFrame** | pandas | 2.x |
| **PDF parsing** | pypdf | 4+ |
| **AI classifier** | anthropic (Claude Haiku) | 0.40+ |
| **Observability** | prometheus-client | 0.19+ |
| **Metrics** | Prometheus | latest |
| **Dashboards** | Grafana | latest |
| **Logs** | Loki + Promtail | 3.0.0 |

### 2.3 Infrastructure Tools

| Tool | Purpose |
|---|---|
| Docker / Docker Compose | Container runtime everywhere |
| Nginx 1.27 | Reverse proxy / TLS termination |
| Cloudflare | CDN + Origin Certificate (TLS) |
| GCP Cloud Build | CI/CD pipelines |
| GCP Cloud Run | Serverless NIDP ingester jobs + DaaS/Query APIs |
| GCP Cloud Scheduler | Cron triggers for Cloud Run jobs |
| GCP Artifact Registry | Docker image registry |
| GCP Secret Manager | Secrets (DB URLs, TLS certs, API keys) |
| GCP Cloud Logging | Centralised log aggregation |
| GCP Cloud Storage | Raw + parsed archive (NIDP data lake) |

---

## 3. Infrastructure — GCP & VMs

### 3.1 GCP Project

- **Project ID:** `niveshdataintelligence`
- **Region:** `asia-south1` (Mumbai)
- **Zone:** `asia-south1-a`

### 3.2 Compute Instances

#### `nivesh-app-vm` — Application Server

| Property | Value |
|---|---|
| External IP | `34.47.250.214` |
| Machine type | `e2-standard-4` |
| Zone | `asia-south1-a` |
| OS | Debian 12 |
| Disk | 50 GB SSD |

**Services running (Docker Compose):**

| Container | Image | Internal Port | Purpose |
|---|---|---|---|
| `nivesh-backend` | `nivesh/backend:prod` | 8001 | FastAPI application |
| `nivesh-frontend` | `nivesh/frontend:prod` | 80/443 | Nginx + React V2 bundle |
| `nivesh-mongo` | `mongo:7` | 27017 | Primary user-data store |
| `nivesh-postgres` | `postgres:16-alpine` | 5432 | Analytics / instrument master |
| `nivesh-redis` | `redis:7-alpine` | 6379 | Cache + APScheduler job store |

**Staging stack (isolated, same VM):** `/opt/nivesh-staging/`
- Separate Docker Compose (`docker-compose.staging.yml`)
- Port binding: `127.0.0.1:8443` (TLS, internal only)
- DB ports: Postgres `127.0.0.1:5532`, MongoDB `127.0.0.1:27117`, Redis `127.0.0.1:6479`
- V5 frontend container (`nivesh/frontend-v5:staging`) served at `/v5/`

#### `nidp-stack-vm` — Data Platform Server

| Property | Value |
|---|---|
| External IP | `34.93.60.254` |
| Machine type | `e2-small` |
| Zone | `asia-south1-a` |
| OS | Debian 12 |
| Disk | 50 GB SSD |

**Services running (Docker Compose):**

| Container | Image | Host Port | Purpose |
|---|---|---|---|
| `nidp-postgres` (primary) | `timescale/timescaledb:latest-pg16` | `127.0.0.1:5433` | TimescaleDB primary |
| `nidp-postgres` (standby) | `timescale/timescaledb:latest-pg16` | `127.0.0.1:5434` | Streaming replication standby |
| `nidp-redpanda` | `redpandadata/redpanda:latest` | `9092` | Kafka-compatible event bus |
| `nidp-schema-registry` | `confluentinc/cp-schema-registry:7.5.0` | `8081` | Avro schema registry |
| `nidp-redis` | `redis:7-alpine` | `6380` | Cache / locks |
| `nidp-minio` | `minio/minio:latest` | `9000/9001` | Parquet WARM archive (S3-compatible) |
| `nidp-prometheus` | `prom/prometheus:latest` | `9090` (loopback) | Metrics scrape/store |
| `nidp-grafana` | `grafana/grafana:latest` | `3000` (loopback) | Dashboards |
| `nidp-loki` | `grafana/loki:3.0.0` | `3100` | Log aggregation |
| `nidp-promtail` | `grafana/promtail:3.0.0` | — | Log shipper |

**Systemd services (on host):**

| Service | Port | Purpose |
|---|---|---|
| `nidp-daas-api` | 8083 | DaaS API (FastAPI/uvicorn) |
| `nidp-query-api` | 8090 | Query API (FastAPI/uvicorn) |
| `nidp-health.timer` | — | Health check timer (every 5 min) |

**Nginx proxying:**

| Path | Backend | Notes |
|---|---|---|
| `/daas/` | `127.0.0.1:8083` | Public DaaS API |
| `/query/` | `127.0.0.1:8090` | Query API |
| `/grafana/` | `127.0.0.1:3000` | Grafana dashboards |
| TLS | Cloudflare Origin Certificate | From GCP Secret Manager (`nidp-tls-cert`, `nidp-tls-key`) |

### 3.3 GCP Cloud Run

**28 Cloud Run Jobs** (stateless NIDP ingesters), region `asia-south1`:

- Runtime SA: `nidp-sa@niveshdataintelligence.iam.gserviceaccount.com`
- VPC connector: `nidp-vpc` (private access to `nidp-stack-vm` Postgres/Redis)
- Secrets from GCP Secret Manager: `NIDP_POSTGRES_URL`, `NIDP_KAFKA_BROKERS`, `NIDP_REDIS_URL`, `NIDP_SCHEMA_REGISTRY_URL`
- Env: `NIDP_EVENT_BUS=local` (bypasses Kafka; events logged to Cloud Logging)
- Images: `asia-south1-docker.pkg.dev/niveshdataintelligence/nidp/<service>:latest`

**2 Cloud Run Services:**

| Service | Port | Visibility |
|---|---|---|
| `nidp-daas-api` | 8081 | Public (`allUsers` invoker) |
| `nidp-query-api` | 8090 | Internal |

### 3.4 GCP Supporting Services

| Service | Resource | Purpose |
|---|---|---|
| **Artifact Registry** | `asia-south1-docker.pkg.dev/niveshdataintelligence/nidp/` | Docker images |
| **Cloud Storage** | `nidp-raw-niveshdataintelligence` | Raw + parsed data lake |
| **Cloud Scheduler** | 30+ jobs (asia-south1) | Cron-based job triggers |
| **Cloud Build** | 28+ triggers | CI/CD pipelines |
| **Secret Manager** | 8 secrets | DB URLs, TLS certs, API tokens |
| **Cloud Logging** | Default sink | Centralised log aggregation |
| **VPC Access Connector** | `nidp-vpc` | Cloud Run → GCE VM private access |

### 3.5 Networking

```
Internet
    │
    ▼
Cloudflare CDN (TLS termination, DDoS)
    │
    ▼
GCP External IP (34.47.250.214 / 34.93.60.254)
    │
    ▼
Nginx (TLS re-termination with Cloudflare Origin Cert)
    │
    ├── /api/      → FastAPI Backend (:8001)
    ├── /v2/       → React Frontend
    ├── /daas/     → DaaS API (:8083)
    ├── /grafana/  → Grafana (:3000)
    └── /query/    → Query API (:8090)

Cloud Run Jobs ──[VPC connector nidp-vpc]──→ nidp-stack-vm :5433 (Postgres)
                                          → nidp-stack-vm :6380 (Redis)
```

---

## 4. Nivesh Application Architecture

### 4.1 Layer Diagram

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: Data Sources                                       │
│  NSE/BSE, RBI, AMFI, FRED, Groww scrape, casparser.in       │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│  Layer 2: NIDP DaaS                                          │
│  /v1/prices, /v1/snapshots, /v1/mutual_funds, /v1/features  │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│  Layer 3: Analytics Engines (backend/services/)             │
│  V3 Scoring · Capital Gains · Portfolio Intelligence        │
│  Rec Engine (17 sub-engines) · Technical · Fundamental      │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│  Layer 4: LangGraph Agent Framework                         │
│  9 specialist nodes: market · stock · MF · portfolio        │
│  risk · goal · recommendation · compliance · intent         │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│  Layer 5: FastAPI Routes (backend/routes/)                  │
│  auth · portfolio · plans · goals · copilot · intelligence  │
│  admin · market · broker · compliance · mfd                 │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│  Layer 6: Frontend (React 19 + Tailwind)                    │
│  V2 React (CRA+CRACO)   V5 React (Vite, TanStack)          │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Backend Service Modules

| Module | File | Responsibility |
|---|---|---|
| V3 scoring engine | `services/v3_score_engine*.py` | 38 primitives → 5 composite scores |
| Action plan engine | `services/action_plan_manager.py` | 6 rules + 4 guardrails → plan generation |
| Capital gains | `services/capital_gains_engine.py` | FIFO LTCG/STCG Indian tax rules (FY25-26) |
| Portfolio intelligence | `services/ai_insights.py` | Stock overlap, AMC/sector concentration |
| Recommendation engine | `services/candidate_fund_hydrator.py` | 17 sub-engines, goal-aware filtering |
| CAS parser | `services/cas_parser.py` | 3-provider fallback: Doc AI → Claude → casparser.in |
| AMFI NAV ingestion | `services/amfi_nav.py` | Daily pull + 5-year backfill |
| Copilot agents | `services/copilot_agents.py` | RAG + LangGraph dispatch |
| Market intelligence | `services/benchmark_index.py` | Macro regime, sector heatmap |
| Positional engine | In routes/positional* | Technical picks + Chartink integration |
| Brokers | `services/brokers/` | Zerodha/Upstox/Angel/Dhan/Fyers/5P/Kotak/IIFL/HDFC |

### 4.3 Scheduled Jobs (APScheduler, Asia/Kolkata TZ)

| Job | Schedule | Action |
|---|---|---|
| AMFI NAV daily | Mon–Fri 22:00 | Pull 14,000 scheme NAVs |
| Stale holdings drain | Weekday 20:00 | Re-enrich holdings with latest NAV |
| Weekend drain | Sat 10:00 | Full portfolio refresh |
| Analytics sweep | Daily 23:00 | Recompute NAV analytics (MDD, Sharpe) |
| V3 rescore | Daily 23:30 | Recompute composite quality/health scores |
| Redis TTL eviction | Continuous | 24h TTL on V3 cache keys |

### 4.4 Post-Deploy 7-Phase Migration

Orchestrated by `backend/scripts/post_deploy_migrate.py` and exposed at `POST /api/admin/datastores/post-deploy-migrate`:

| Phase | Name | Duration | Skippable |
|---|---|---|---|
| 0 | hydrate_secrets | <200ms | No |
| 1 | health_check | <600ms | No |
| 2 | apply_migrations | <1.5s | No |
| 3 | restore_mirrors (Mongo→PG) | ~18s | No |
| 4 | replay_scrape_cache | ~5min | Yes (default: skip) |
| 5 | analytics_sweep | ~14s | Yes |
| 6 | v3_rescore | ~4s | Yes |
| 7 | smoke_check | <600ms | No |

**Total default run time: ~38 seconds**

---

## 5. NIDP Data Platform Architecture

### 5.1 Overview

NIDP (Nivesh Indian Data Platform) is an isolated data lake and API platform hosted under `backend/nidp/`. It:

- Ingests 41 data feeds from 15+ external sources
- Stores data in a 3-layer immutable archive
- Exposes a **DaaS API** (external, API-key gated) and **Query API** (internal)
- Feeds the Nivesh app with market data, portfolio intelligence, and V3 scores

### 5.2 Ingester Architecture

Every ingester follows the `BaseIngester` contract:

```
fetch() → raw_archive (GCS) → parse() → validate() → persist() → emit(Kafka/stdout)
```

**JobRun lifecycle:** `RUNNING → OK | PARTIAL | FAILED | SKIPPED`

**Validation severity levels:**
- `BLOCK` (CRITICAL) — suppresses Kafka emit, marks run FAILED
- `FIX` (ERROR) — logged, run continues
- `WARN / INFO` — informational only

**Rule types:** `CountAtLeastRule`, `NoNullsRule`, `RangeRule`, `CustomSQLRule`

### 5.3 Service Inventory (28 ingesters + APIs)

#### Tier 1A — Core Market Data
| Service | Source | Table | Frequency |
|---|---|---|---|
| `bhavcopy` | NSE CM CSV | `prices_eod` | Mon–Fri |
| `delivery` | NSE delivery CSV | `delivery_data` | Mon–Fri (T+1 10:30) |
| `index_close` | NSE indices CSV | `index_eod` | Mon–Fri |
| `index_constituents` | NSE index lists | `index_constituents` | Monthly 1st |
| `fii_dii` | NSE JSON API | `fii_dii_flows` | Mon–Fri |
| `corporate_actions` | NSE JSON API | `corporate_actions` | Daily |
| `bulk_deals` | NSE JSON API | `bulk_deals` | Mon–Fri |
| `block_deals` | NSE JSON API | `block_deals` | Mon–Fri |
| `nse_calendar` | NSE JSON API | `nse_holidays` | Monthly 1st |
| `rbi_yields` | RBI WSS HTML | `rbi_yields` | Weekdays |
| `fred_macro` | FRED CSV API | `fred_macro_observations` | Daily |
| `yfinance_backfill` | Yahoo Finance | `prices_eod` | Manual/event-driven |
| `snapshot_builder` | Domain tables | `market_daily_snapshot`, `stock_daily_snapshot` | Mon–Fri 22:00 |

#### Tier 1B — Fundamentals
| Service | Source | Table | Frequency |
|---|---|---|---|
| `nse_financials` | Screener.in / NSE XBRL | `nse_financials_quarterly` | Daily |
| `nse_financials.bank_npa_patch` | Screener.in (standalone) | `nse_financials_quarterly` | Daily 21:00 |
| `nse_shareholding` | NSE XBRL | `shareholding_pattern` | Daily |
| `price_adjuster` | `corporate_actions` | `price_adjustment_factors` | Mon–Fri 22:30 |
| `nse_equity_master` | NSE security master | `security_master` | Weekly (Sun) |
| `fno_bhavcopy` | NSE F&O CSV | `fno_bhavcopy` | Mon–Fri |

#### S4 — Corporate Announcements
| Service | Source | Table | Frequency |
|---|---|---|---|
| `corporate_announcements_nse` | NSE filings API | `corporate_announcements` | Every 10 min (9–23h weekdays) |
| `corporate_announcements_bse` | BSE filings API | `corporate_announcements` | Every 10 min (9–23h weekdays) |
| `announcement_classifier` | Claude Haiku | `documents` (classification) | Every 30 min |
| `document_parser` | PDFs from announcements | `documents` (chunks + pgvector) | Every 15 min |

#### S5 — Mutual Funds
| Service | Source | Table | Frequency |
|---|---|---|---|
| `amfi_nav` | AMFI NAVAll.txt | `mf_nav_daily` | Mon–Fri 20:00 |
| `amfi_nav_history` | mfapi.in | `mf_nav_daily` | Manual one-time backfill |
| `amfi_circulars` | AMFI notices | `amfi_circulars` | Daily 09:00 |
| `mf_disclosure_snapshot` | AMC factsheet pages (T1–T4) | `mf_disclosure_snapshot` | Monthly 12th 10:00 |
| `mf_holdings` | AMC portfolio pages | `mf_holdings` | Monthly 12th 11:00 |

#### Derived Analytics
| Service | Reads From | Writes To | Frequency |
|---|---|---|---|
| `mf_analytics_engine` | `mf_nav_daily` | `analytics.fund_category_rank` | Mon–Fri 20:30 |
| `technical_indicator_engine` | `prices_eod`, `price_adjustment_factors` | `stock_features_daily` | Mon–Fri 22:35 |
| `fundamental_engine` | `nse_financials_quarterly`, `stock_features_daily` | `stock_features_daily` | Mon–Fri 23:05 |
| `bank_scoring` | `nse_financials_quarterly` | `bank_metrics_daily`, `bank_quality_scores_daily` | Daily 21:30 |
| `v3_scores_engine` | `stock_features_daily`, MF analytics | `v3_mf_scores_daily`, `v3_stock_scores_daily` | Mon–Fri 23:55 |
| `analytics_refresh` | `v3_*_scores_daily`, `stock_daily_snapshot` | `analytics.stock_card`, materialized views | Tue–Sat 00:10 |
| `mf_derived_refresh` | `mf_nav_daily`, `mf_holdings` | `mf_derived_analytics` | Mon–Fri 23:50 |

#### Intelligence & Portfolio Sync
| Service | Frequency |
|---|---|
| `event_calendar` | Mon–Fri 06:30 + 20:30 |
| `event_day_poller` | Every 5 min 9–16h weekdays |
| `d1_prep` | Mon–Fri 19:00 |
| `intelligence` | Mon–Fri 20:00 |
| `portfolio_holdings_sync` | Mon–Fri 23:00 |
| `portfolio_transactions_sync` | Mon–Fri 23:10 |
| `portfolio_goals_sync` | Mon–Fri 23:15 |
| `intelligence_layer` | Mon–Fri 23:20 |
| `portfolio_intelligence_sync` | Mon–Fri 23:30 |

#### Infrastructure Services
| Service | Frequency |
|---|---|
| `quality_gate` | Mon–Fri 22:30 |
| `amc_urls_drift_check` | Daily 08:00 |
| `parquet_exporter` | Tue–Sat 00:30 |
| `container_health_collector` | Every minute |
| `gate4_replication_check` | Every minute (WAL) + Daily 01:00 (row counts) |

---

## 6. Database Schemas

### 6.1 NIDP TimescaleDB (nidp-stack-vm:5433)

Database: `nidp`  
Extension: `timescaledb`, `pgvector`

**Schema Map:**

```
nidp schema (operational + market data)
├── job_log                     — ingester run history
├── source_registry             — per-feed health counters
├── raw_archive_files           — GCS raw file index (SHA-256 dedup)
├── parsed_archive_files        — GCS parsed JSONL.gz index
├── daily_snapshot              — readiness coordinator
├── market_session_state        — "last NSE close" date
├── validation_findings         — DQ rule output (BLOCK/FIX/WARN)
├── feature_flags               — runtime toggles
├── daas_api_keys               — API key registry (plan, RPM, daily quota)
│
│   ── HYPERTABLES (time-series) ──
├── prices_eod                  — NSE bhavcopy OHLCV (symbol, date, O/H/L/C/volume, series)
├── delivery_data               — Delivery % per symbol per date
├── index_eod                   — NSE index closes (index_name, date, close_value, change_pct)
├── fii_dii_flows               — FII/DII net flows (date, category, buy_value, sell_value, net)
├── corporate_actions           — Dividends, splits, bonuses, rights (symbol, ex_date, type, value)
├── bulk_deals                  — NSE bulk deals >0.5% (symbol, date, client, qty, price, buy_sell)
├── block_deals                 — NSE negotiated block trades
├── rbi_yields                  — G-Sec 10Y/5Y/1Y + T-Bill 91D/364D per date
├── fred_macro_observations     — 8 US macro series (DGS10 mandatory; series_id, date, value)
├── nse_holidays                — Trading calendar (date, description)
├── index_constituents          — Nifty membership snapshots (index_name, symbol, effective_date)
│
│   ── SNAPSHOT TABLES ──
├── market_daily_snapshot       — Per date: indices, FII/DII totals, yields, breadth
├── stock_daily_snapshot        — Per (symbol, date): OHLCV + delivery% + index flags + upcoming CA
├── feed_snapshot               — Per (ingester, snapshot_date): JSONB parsed rows
│
│   ── FUNDAMENTALS ──
├── nse_financials_quarterly    — Revenue/PAT/EPS/ROE/debt per symbol+period; raw_data JSONB
├── shareholding_pattern        — Promoter/FII/DII/retail % per symbol+quarter
├── price_adjustment_factors    — Split/bonus adj factors per (symbol, ex_date, action_type)
├── fno_bhavcopy               — F&O OHLCV (symbol, expiry, instrument_type, strike, option_type)
├── corporate_announcements     — NSE+BSE filings (symbol, exchange, category, headline, attachment_url)
├── documents                   — Parsed PDFs: chunks + pgvector embeddings
│
│   ── FEATURES (stock_features_daily) ──
├── stock_features_daily        — Per (symbol, date): SMA20/50/200, RSI, MACD, ATR, Bollinger,
│                                  volatility_1y, return_252d, beta_1y, max_drawdown_1y,
│                                  delivery_rank, pe_ratio, pb_ratio, roe, debt_to_equity,
│                                  piotroski_score, altman_z, sector_median_pe, market_cap,
│                                  accumulation_score, sector_profile
│
│   ── MUTUAL FUND TABLES ──
├── mf_nav_daily               — Daily NAV per scheme (scheme_code, nav_date, nav)
├── mf_disclosure_snapshot     — Monthly factsheet data (TER, risk-o-meter, scheme metadata)
├── mf_holdings                — Monthly AMC portfolio per scheme (ISIN, stock_name, pct, value)
├── amfi_circulars             — AMFI/SEBI lifecycle notices
├── mf_derived_analytics       — Computed: consistency_score, downside_capture, aum_trend, turnover
├── mf_amc_source_registry     — AMC canonical URL registry (T1–T4 tiers, extraction strategies)
├── v3_mf_scores_daily         — Persisted Quality + Health per (scheme_code, as_of_date)
├── v3_stock_scores_daily      — Persisted Quality + Health per (symbol, as_of_date)
│
│   ── EVENT TABLES ──
├── event_calendar             — 60-day forward events per symbol
├── intelligence               — Per-symbol event signals (event_type, impact_level, sentiment)
│
│   ── BANK SCORING ──
├── bank_metrics_daily         — NIM, GNPA, NNPA, CAR, ROA, ROE per bank per date
└── bank_quality_scores_daily  — 5-pillar quality score per bank per date

ref schema
├── security_master            — Canonical ISIN → symbol → sector → industry mapping

dq schema
├── feed_sla                   — SLO definitions per feed
└── gate_verdicts              — PASS/AMBER/FAIL + P0/P1/P2/OK per gate per date

features schema
└── (engineered feature store, extends stock_features_daily)

graph schema
└── (entity relationships, correlations)

events schema
└── (normalised corporate events)

analytics schema
├── stock_card                 — Per-symbol summary card (price, V3 scores, rank)
├── sector_snapshot            — Per-sector aggregated metrics
├── fund_category_rank         — MF category ranking (Sharpe, CAGR, MaxDD, Alpha)
└── (4 materialized views: mv_top_momentum, mv_delivery_surge,
                           mv_sector_heatmap, mv_fund_category_top10)

portfolio schema
├── user_holdings_snapshot     — Bridged client holdings from Nivesh app
├── user_transactions_snapshot — Bridged client transactions
├── user_goals_snapshot        — Bridged client goals
└── user_intelligence_snapshot — Per-user per-holding intelligence signals

audit schema
└── (replay/backfill state tracking)

monitoring schema
└── container_health           — Docker ps status (written every minute by cron)
```

**Migration count:** 83 SQL files (`001_nidp_base.sql` → `083_fix_refresh_stock_card_delivery_rank.sql`)

### 6.2 Nivesh PostgreSQL (nivesh-app-vm:5432)

Database: `nivesh_prod`  
Extension: `uuid-ossp`, `pg_trgm`

**Tables (25+ migrations applied):**

| Table | Purpose | Key Columns |
|---|---|---|
| `instrument_master` | Canonical instrument registry (MF + equity) | `instrument_id UUID PK`, `symbol`, `isin`, `instrument_type` |
| `mutual_fund_metadata` | Fund metadata + V3 scores | `instrument_id FK`, `fund_name`, `category`, `amc_name`, `expense_ratio_direct`, `manager_name`, `quality_score`, `health_score`, `exit_score_baseline`, `add_score_baseline`, `v3_scored_at` |
| `mutual_fund_nav_history` | Daily NAV timeseries | `instrument_id FK`, `nav_date DATE PK`, `nav NUMERIC(12,4)` |
| `mutual_fund_aum_history` | Monthly AUM snapshots | `instrument_id FK`, `snapshot_date DATE PK`, `aum_cr NUMERIC(12,2)` |
| `mutual_fund_performance_ratios` | Risk/return ratios | `instrument_id FK`, `sharpe_ratio`, `sortino_ratio`, `alpha`, `beta_3y`, `max_drawdown_pct`, `consistency_score`, `downside_capture_pct` |
| `mutual_fund_holdings` | Per-fund stock allocations (Groww scraped) | `fund_id`, `symbol`, `company_name`, `sector`, `percentage`, `as_of_date` |
| `benchmark_master` | Index benchmarks | `benchmark_id`, `name`, `category_mapping` |
| `scrape_audit_log` | Per-scrape attempt audit | `fund_id`, `source`, `status`, `rows_fetched`, `scraped_at` |
| `nav_analytics_job_log` | Analytics sweep audit | `job_name`, `status`, `funds_processed`, `duration_ms` |
| `schema_migrations` | Applied migration tracker | `filename`, `applied_at` |

### 6.3 Nivesh MongoDB (nivesh-app-vm:27017)

Database: `nivesh_prod`

| Collection | Purpose | Key Fields |
|---|---|---|
| `users` | User profiles + preferences | `google_id`, `email`, `risk_profile`, `journey_type`, `preferences.ui_version`, `analytics_visibility` |
| `holdings` | User portfolio holdings | `user_id`, `fund_name`, `isin`, `units`, `buy_date`, `buy_nav`, `current_value` |
| `portfolio_snapshots` | Plan-time portfolio state | `user_id`, `plan_id`, `total_value`, `holdings_count`, `asset_allocation`, `sector_exposure` |
| `action_plans` | V2 action plans | `plan_id`, `user_id`, `version`, `status` (preview/active/in_progress/archived/completed), `actions[]`, `signals[]`, `score_before`, `score_after` |
| `plan_history` | Archived plan versions | `history_id`, `plan_id`, `version`, `archived_at`, `plan_snapshot` |
| `chat_sessions` | Copilot conversation threads | `session_id`, `user_id`, `messages[]`, `agent_type` |
| `portfolio_intelligence_signals` | NIDP intelligence per holding | `user_id`, `isin`, `signal_type`, `value`, `as_of_date` |
| `pg_mirror_*` | PG table mirrors (WORM, for post-deploy restore) | One collection per PG table |
| `fund_holdings_cache` | Groww scrape cache | `instrument_id`, `holdings_snapshot` |
| `system_config` | App secrets + feature flags | `secrets.POSTGRES_URL`, `secrets.REDIS_URL` |

---

## 7. Data Lake & Storage

### 7.1 Architecture

NIDP uses a 3-layer immutable storage model:

```
External Source (NSE, RBI, AMFI, FRED…)
        │
        ▼ fetch()
┌──────────────────────────────────────────────────────┐
│  Layer 1 — RAW ARCHIVE (GCS)                         │
│  gs://nidp-raw-niveshdataintelligence/               │
│  ├── <ingester>/<YYYY>/<MM>/<sha12>.<ext>            │
│  │   (deduplicated by SHA-256; exact bytes)          │
│  └── Indexed in nidp.raw_archive_files               │
└──────────────────────────────────────────────────────┘
        │
        ▼ parse()
┌──────────────────────────────────────────────────────┐
│  Layer 2 — PARSED ARCHIVE (GCS)                      │
│  gs://nidp-raw-niveshdataintelligence/               │
│  ├── parsed/<ingester>/<YYYY>/<MM>/<sha12>.jsonl.gz  │
│  │   (normalised JSONL; enables re-derive on schema) │
│  └── Indexed in nidp.parsed_archive_files            │
└──────────────────────────────────────────────────────┘
        │
        ▼ persist()
┌──────────────────────────────────────────────────────┐
│  Layer 3 — DOMAIN TABLES (TimescaleDB)               │
│  prices_eod, delivery_data, index_eod, fii_dii_flows │
│  corporate_actions, bulk_deals, block_deals, …       │
│  (Query substrate; hypertables for time-series)      │
└──────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────────┐
│  Layer 4 — SNAPSHOT COHERENCE (TimescaleDB)          │
│  market_daily_snapshot + stock_daily_snapshot        │
│  (Daily coherence; daily_snapshot.status='READY')    │
└──────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────────┐
│  Layer 5 — WARM ARCHIVE (MinIO, Parquet)             │
│  stock_features_daily → partitioned Parquet          │
│  nse_financials_quarterly → partitioned Parquet      │
│  (DuckDB-queryable; AI training datasets)            │
└──────────────────────────────────────────────────────┘
```

### 7.2 Replay Engine

The raw archive enables complete data replay:
- Policy-based replay (full feed, date range, specific symbols)
- Failure injection testing
- Parser version upgrades without re-fetching

### 7.3 Deduplication

Every fetched file is SHA-256 hashed. If the hash already exists in `raw_archive_files`, the fetch is skipped (idempotent runs).

### 7.4 Storage Estimates

| Tier | Volume | Retention |
|---|---|---|
| Raw archive (GCS) | ~200 MB/month | Indefinite (replay substrate) |
| Parsed archive (GCS) | ~50 MB/month | Indefinite |
| TimescaleDB domain tables | ~5 GB/year | HOT: 365 days, WARM: Parquet archive |
| stock_features_daily HOT | 180 days | Then Parquet export |
| MinIO Parquet | Growing | DuckDB access |

---

## 8. Data Feeds & Cron Schedule

### 8.1 NSE / BSE Source URLs

| Source | URL Template |
|---|---|
| NSE Archives | `https://nsearchives.nseindia.com` |
| NSE WWW | `https://www.nseindia.com` |
| BSE WWW | `https://www.bseindia.com` |
| RBI | `https://www.rbi.org.in` |
| AMFI | `https://www.amfiindia.com`, `https://portal.amfiindia.com` |
| FRED | FRED API CSV endpoint |
| Screener.in | Rolling quarterly endpoint |

**Bhavcopy format cutover date:** 2024-07-08 (pre/post-Jul-2024 CSV layouts differ)

### 8.2 Production Cron Schedule (`/etc/cron.d/nidp`, IST, CRON_TZ=Asia/Kolkata)

```
── Daily NSE EOD (weekdays) ──────────────────────────────
19:00   bhavcopy, index_close
19:30   fii_dii, bulk_deals, block_deals, fno_bhavcopy

── T+1 morning (Tue–Sat) ─────────────────────────────────
10:30   delivery

── Daily data ────────────────────────────────────────────
20:00   corporate_actions (daily)
20:30   rbi_yields (weekdays), nse_financials (daily)
20:30   mf_analytics_engine (weekdays)
20:30   event_calendar (weekdays)
20:00   intelligence (weekdays)
21:00   fred_macro (daily), nse_shareholding (daily)
21:00   nse_financials.bank_npa_patch (daily)
21:30   bank_scoring (daily)

── EOD pipeline (weekdays) ───────────────────────────────
22:00   snapshot_builder
22:30   price_adjuster, quality_gate
22:35   technical_indicator_engine

── S4 announcements (weekdays 09–23h) ────────────────────
*/10    corporate_announcements_nse, corporate_announcements_bse
*/30    announcement_classifier (all week, all day)
*/15    document_parser (all week, all day)

── Corporate events ──────────────────────────────────────
*/5 (9–16h weekdays) event_day_poller
19:00 weekdays  d1_prep
06:30 weekdays  event_calendar (morning refresh)

── Post-midnight (Tue–Sat) ───────────────────────────────
23:00   portfolio_holdings_sync
23:05   fundamental_engine
23:10   portfolio_transactions_sync
23:15   portfolio_goals_sync
23:20   intelligence_layer
23:30   portfolio_intelligence_sync
23:50   mf_derived_refresh
23:55   v3_scores_engine
00:10   analytics_refresh
00:30   parquet_exporter

── Mutual funds ──────────────────────────────────────────
20:00 weekdays  amfi_nav
09:00 daily     amfi_circulars
10:00 12th/mo   mf_disclosure_snapshot
11:00 12th/mo   mf_holdings

── Monthly / weekly ──────────────────────────────────────
06:00 1st/mo    nse_calendar
06:30 1st/mo    index_constituents
07:00 Sundays   nse_equity_master

── Infrastructure (continuous) ───────────────────────────
08:00 daily     amc_urls_drift_check
* * * * *       container_health_collector
* * * * *       gate4_replication_check (WAL lag)
01:00 daily     gate4_replication_check --mode=daily (row-count parity)
```

### 8.3 AMC Disclosure Tiers

| Tier | Extraction Strategy | AMCs |
|---|---|---|
| T1 | Static HTML / direct download | SBI, HDFC, Nippon, Tata, Axis, Mirae, ICICI Pru, ABSL, UTI, Kotak |
| T2 | ASP.NET WebMethod API | quant MF |
| T3 | Static CMS per-fund XLSX | JM Financial |
| T4 | Playwright / XHR intercept | Remaining AMCs |

---

## 9. NIDP DaaS OpenAPI Reference

**Base URL:** `https://data.niveshcopilot.com/daas` (proxied)  
**Spec file:** `/app/docs/nidp-openapi.yaml` (3,910 lines, OpenAPI 3.1.0)

### 9.1 Authentication

```
X-API-Key: nvd_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# or
Authorization: Bearer nvd_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

- Admin endpoints: `Authorization: Bearer <NIDP_DAAS_INTERNAL_TOKEN>`
- Key format: `nvd_` prefix, 32-char hex suffix
- Plans: `free`, `standard`, `pro`, `internal`

### 9.2 Rate Limiting

All responses include:
- `X-RateLimit-Limit` / `X-RateLimit-Remaining` / `X-RateLimit-Reset`
- `X-Daily-Limit` / `X-Daily-Remaining`
- HTTP 429 with `Retry-After` header on limit exceeded

### 9.3 Pagination

List endpoints: `limit` (1–5000, default 100), `offset`  
Response envelope: `pagination.next_offset`

### 9.4 Endpoint Groups

| Tag | Description | Sample Endpoints |
|---|---|---|
| `health` | Liveness (no auth) | `GET /health` |
| `admin` | Key lifecycle | `POST /admin/keys`, `GET /admin/keys`, `DELETE /admin/keys/{key_id}` |
| `me` | Caller identity + quota | `GET /v1/me` |
| `catalog` | Dataset index | `GET /v1/catalog` |
| `prices` | NSE EOD OHLCV | `GET /v1/prices/eod/{symbol}`, `GET /v1/prices/adjusted/{symbol}` |
| `corporate_actions` | Dividends, splits, bonuses, rights | `GET /v1/corporate-actions/{symbol}` |
| `indices` | Index list + constituents | `GET /v1/indices`, `GET /v1/indices/{index_name}/constituents` |
| `reference` | Symbol master, sectors, holidays | `GET /v1/reference/symbols`, `GET /v1/reference/sectors`, `GET /v1/reference/holidays` |
| `financials` | Quarterly P&L + shareholding | `GET /v1/financials/{symbol}/quarterly`, `GET /v1/financials/{symbol}/shareholding` |
| `fno` | F&O OHLCV, options chain | `GET /v1/fno/{symbol}/futures`, `GET /v1/fno/{symbol}/options` |
| `flows` | FII/DII, bulk/block deals | `GET /v1/flows/fii-dii`, `GET /v1/flows/bulk-deals` |
| `announcements` | NSE + BSE filings | `GET /v1/announcements`, `GET /v1/announcements/{symbol}` |
| `macro` | RBI yields + FRED series | `GET /v1/macro/rbi-yields`, `GET /v1/macro/fred/{series_id}` |
| `snapshots` | Pre-computed market/stock snapshots | `GET /v1/snapshots/market`, `GET /v1/snapshots/stock/{symbol}` |
| `features` | Engineered S4/S5 features | `GET /v1/features/{symbol}` |
| `mutual_funds` | AMC, scheme, NAV, holdings | `GET /v1/mutual-funds/nav/{scheme_code}`, `GET /v1/mutual-funds/holdings/{scheme_code}` |
| `mf_performance` | Category rankings, analytics | `GET /v1/mf-performance/category-rank` |
| `events` | Corporate event calendar | `GET /v1/events/{symbol}` |
| `intelligence` | Per-symbol intelligence signals | `GET /v1/intelligence/{symbol}` |
| `dq_ai` | AI anomaly detection results | `GET /v1/dq/verdicts` |
| `replay` | Trigger data replay | `POST /v1/replay/start`, `GET /v1/replay/status/{replay_id}` |
| `backfill` | Backfill orchestration | `POST /v1/backfill/start`, `GET /v1/backfill/status/{backfill_id}` |
| `query_health` | Query API liveness | `GET /health` (Query API) |
| `query_catalog` | Query API dataset index | `GET /catalog` (Query API) |
| `query_feeds` | Feed management | `GET /feeds`, `POST /feeds/{feed}/run` |
| `query_validation` | Validation findings | `GET /validation/findings` |
| `query_quality` | Quality gate verdicts | `GET /quality/gates` |
| `query_vm_ops` | VM operations | `POST /vm/restart-service` |
| `query_archive` | Archive management | `GET /archive/files`, `POST /archive/replay` |

### 9.5 Standard Response Envelope

```json
{
  "data": [...],
  "pagination": {
    "total": 1234,
    "limit": 100,
    "offset": 0,
    "next_offset": 100
  },
  "meta": {
    "as_of": "2026-05-28",
    "source": "nidp"
  }
}
```

---

## 10. Nivesh App OpenAPI Reference

**Base URL:** `https://niveshcopilot.com/api`  
**Spec file:** `/app/docs/nivesh-app-openapi.yaml` (4,599 lines, OpenAPI 3.1.0)

### 10.1 Authentication

- Google OAuth 2.0 (`/api/oauth/google`, `/api/oauth/gmail`)
- Session cookie (`/api/auth/dev-set-cookie?token=...` for headless auth)
- Admin token: `Authorization: Bearer <ADMIN_TOKEN>` for admin routes

### 10.2 Route Groups (180+ endpoints)

| Group | Prefix | Description |
|---|---|---|
| Auth | `/api/auth/`, `/api/oauth/` | Google login, session, logout, DPDP consent |
| User | `/api/user/` | Profile, risk questionnaire, journey type |
| Portfolio | `/api/portfolio/` | Holdings CRUD, CAS upload, time-machine snapshots |
| Plans | `/api/plans/` | V2 action plan lifecycle (preview → active → complete) |
| Goals | `/api/goals/` | Financial goals, Monte Carlo simulation |
| Intelligence | `/api/intelligence/` | Stock overlap, AMC/sector concentration, compression score |
| Insights | `/api/insights/` | Deterministic portfolio insights |
| Copilot / Chat | `/api/chat/` | LangGraph agent + RAG chat, streaming SSE |
| Copilot widgets | `/api/copilot/` | Widget queries, follow-up chips |
| Market | `/api/market/` | Macro dashboard, sector heatmap, positional picks |
| Broker | `/api/broker/` | OAuth, portfolio read (Zerodha/Upstox etc.) |
| Compliance | `/api/compliance/` | DPDP consent, data export, deletion |
| MFD | `/api/mfd/` | Advisor workspace, client list, impersonation |
| Admin — data | `/api/admin/datastores/` | Post-deploy migration, PG mirror, scrape trigger |
| Admin — NIDP | `/api/admin/nidp/` | Feed catalog, V3 scores, portfolio bridge |
| Admin — users | `/api/admin/users/` | User management |
| Admin — rules | `/api/admin/rules/` | DSL scoring rules |
| Admin — secrets | `/api/admin/secrets/` | CAS API key pool management |
| Admin — flags | `/api/admin/flags/` | Feature flag CRUD |
| Portfolio remediation | `/api/portfolio-remediation/` | AI-driven remediation actions |
| Portfolio exposure | `/api/portfolio-exposure/` | Concentration analysis |

### 10.3 Core Data Models

**Holdings (enriched response)**
```json
{
  "isin": "INF200K01RK0",
  "fund_name": "HDFC Mid Cap Opportunities Fund",
  "units": 150.23,
  "current_nav": 127.45,
  "current_value": 19140.55,
  "xirr": 14.2,
  "v3_scores": {
    "quality_score": 72.5,
    "health_score": 68.0,
    "exit_score": 35.2,
    "add_score": 61.0,
    "danger": "OK"
  },
  "action_badge": "HOLD",
  "tax_impact": { "ltcg": 0, "stcg": 1200 }
}
```

---

## 11. Observability Stack

### 11.1 Prometheus

**Config:** `/opt/nidp/dev-repo/nivesh.ai/backend/nidp/deploy/prometheus.yml`

- **Scrape interval:** 15s
- **Evaluation interval:** 30s
- **Scrape targets:**
  - `localhost:9090` (Prometheus self)
  - `host.docker.internal:9100–9109` (NIDP ingesters, one port per service)

**Service → Port mapping:**

| Port | Service |
|---|---|
| 9100 | bulk_deals |
| 9101 | bhavcopy |
| 9102 | block_deals |
| 9103 | delivery |
| 9104 | index_close |
| 9105 | index_constituents |
| 9106 | fii_dii |
| 9107 | corporate_actions |
| 9108 | rbi_yields |
| 9109 | nse_calendar |

### 11.2 Prometheus Recording Rules & SLO Alerts

**Config:** `/opt/nidp/dev-repo/nivesh.ai/backend/nidp/deploy/prometheus_rules.yml`

**Recording rules:**
- `nidp:gate1_pass_rate_1m` — Ingester pass rate per service
- `nidp:gate3_pass_rate_5m` / `nidp:gate3_pass_rate_30d` — Snapshot SLO windows
- `nidp:gate5_pass_rate_30d` — Parquet export SLO
- `nidp:ingester_seconds_since_last_ok` — Freshness per feed
- `nidp:dlq_pending_count` — Dead letter queue backlog

**Alert rules (burn-rate based):**

| Alert | Severity | Condition |
|---|---|---|
| `NIDPGate3SnapshotFastBurn` | pager | 2% error budget consumed in 1h |
| `NIDPGate3SnapshotSlowBurn` | ticket | 10% budget in 24h |
| `NIDPIngesterFailed` | pager | Any ingester failure in 30m window |
| `NIDPIngesterGate1P0` | pager | Gate 1 data not persisted |
| `NIDPReplicationLagHigh` | pager | Gate 4 replication lag exceeded |
| `NIDPParquetExportFailed` | ticket | Gate 5 export failure |
| `NIDPDLQBacklogHigh` | ticket | DLQ pending > 5 for 30m |
| `NIDPBhavcopyStalenessHigh` | pager | Bhavcopy not updated > 24h |
| `NIDPMFNavStalenessHigh` | pager | AMFI NAV not updated > 48h |

### 11.3 Grafana

**URL:** `https://data.niveshcopilot.com/grafana/`  
**Credentials:** admin / admin  
**Plugin:** `grafana-sentry-datasource` (installed)

**Provisioned datasources:**

| Name | Type | URL |
|---|---|---|
| Prometheus | Prometheus | `http://prometheus:9090` |
| Loki | Loki | `http://loki:3100` (max 1000 lines) |
| Postgres (NIDP) | PostgreSQL | `postgres:5432`, db=nidp, TimescaleDB enabled |
| Sentry | grafana-sentry-datasource | `${SENTRY_URL}`, org `${SENTRY_ORG}`, project `${SENTRY_PROJECT}` |

**Provisioned dashboards (VM production):**

| Dashboard | File |
|---|---|
| NIDP Job Health | `grafana/dashboards/prod/job_health.json` |
| Infrastructure | `grafana/dashboards/prod/infra.json` |
| DQ Chain Status | `grafana/dashboards/prod/dq_chain.json` |
| DQ Analytics | `grafana/dashboards/prod/dq_analytics.json` |
| Feed Schedule | `grafana/dashboards/prod/feed_sched.json` |

### 11.4 Loki (Log Aggregation)

**Config:** `/opt/nidp/dev-repo/nivesh.ai/backend/nidp/deploy/loki/loki-config.yaml`

- HTTP port: 3100 / gRPC: 9096
- Retention: 30 days
- Ingestion rate: 4 MB/s (burst 8 MB/s)
- Old sample rejection: 24h window

### 11.5 Promtail (Log Collector)

**Config:** `/opt/nidp/dev-repo/nivesh.ai/backend/nidp/deploy/loki/promtail-config.yaml`

Scrapes:
- `/opt/nidp/logs/*/*.log` → label `job=nidp_services, service=<extracted>`
- `/var/log/syslog` → label `job=syslog`

### 11.6 GCP Cloud Logging

**Explorer:** `https://console.cloud.google.com/logs/query?project=niveshdataintelligence`

**Useful filter patterns:**

```
# All errors
severity>=ERROR

# NIDP ingester failures
resource.type="cloud_run_job" AND severity>=ERROR

# Specific feed
resource.labels.job_name="nidp-nse-eod"

# Trace by correlation ID
jsonPayload.correlationId="<REPLACE>"

# DaaS 5xx
resource.labels.service_name="nidp-daas-api" AND httpRequest.status>=500
```

### 11.7 Sentry

**Status:** Configured as Grafana datasource (`${SENTRY_URL}`, `${SENTRY_AUTH_TOKEN}`)  
**Project:** `${SENTRY_PROJECT:-nivesh-copilot}`  
**Org:** `${SENTRY_ORG}`  
**Integration:** Grafana panel "Frontend Errors" (prod + staging dashboards)

---

## 12. CI/CD Pipeline

### 12.1 Overview

```
Developer pushes to GitHub (amitporwal107/nivesh.ai)
    │
    ├── [nidp/* file changes] → Cloud Build Trigger → Build → Push AR → Deploy Cloud Run
    │
    └── [nivesh app] → Manual: SSH + git reset + docker compose up
```

### 12.2 NIDP Cloud Build Pipelines

**Build SA:** `nivesh-devops@niveshdataintelligence.iam.gserviceaccount.com`  
**AR repo:** `asia-south1-docker.pkg.dev/niveshdataintelligence/nidp/`  
**Private pool:** `projects/niveshdataintelligence/locations/asia-south1/workerPools/nidp-private-pool`

| Pipeline | Config File | Trigger |
|---|---|---|
| DaaS API | `cloudbuild-daas.yaml` | Push to `backend/nidp/services/daas_api/**` |
| DB Migrations | `cloudbuild-migrations.yaml` | Manual or push when migrations change |
| Generic Service | `cloudbuild-service.yaml` | Per-service trigger (28 total) |

**DaaS pipeline steps:**
1. Docker build (`$BUILD_ID` + `:latest`)
2. Push SHA tag to Artifact Registry
3. Push `:latest` tag
4. `gcloud run services update nidp-daas-api` (idempotent)
5. Smoke test: `curl /health` (200) + `curl /v1/me` (401)

**Generic service pipeline steps:**
1. Kaniko build (registry cache, 90-day TTL)
2. Push `$BUILD_ID` + `:latest`
3. `gcloud run jobs update <service>` (idempotent)

### 12.3 Nivesh App Deployment

All deployments go through git, never rsync/scp:

```bash
# Full rebuild (on VM)
bash deploy/nivesh-app/redeploy.sh

# Frontend only (CSS/JS changes)
bash deploy/nivesh-app/redeploy.sh --frontend-only

# Backend only (Python changes, no new deps)
bash deploy/nivesh-app/redeploy.sh --backend-only

# Specific branch
bash deploy/nivesh-app/redeploy.sh --branch main
```

**Steps:**
1. `git reset --hard origin/<branch>`
2. Docker build (backend/frontend images)
3. `docker compose up -d --remove-orphans`
4. Health-check `/api/health`

### 12.4 NIDP VM Deployment

```bash
# Deploy to production
sudo -u nidp /opt/nidp/repo/backend/nidp/deploy/vm/deploy.sh --branch=main

# Deploy to dev/staging
sudo -u nidp /opt/nidp/repo/backend/nidp/deploy/vm/deploy.sh --branch=dev
```

**Steps:**
1. `git fetch + reset --hard origin/<branch>`
2. Pip deps update
3. SQL migrations
4. `systemctl restart nidp-daas-api nidp-query-api`
5. Smoke test `/daas/health` + `/query/health`

### 12.5 GCP Secret Manager Secrets

| Secret | Used By | Notes |
|---|---|---|
| `NIDP_POSTGRES_URL` | All Cloud Run + VM services | Rotated via `rotate_credentials.sh` |
| `NIDP_KAFKA_BROKERS` | Cloud Run jobs | When Redpanda changes |
| `NIDP_REDIS_URL` | Cloud Run jobs | When Redis changes |
| `NIDP_SCHEMA_REGISTRY_URL` | Cloud Run jobs | When registry moves |
| `NIDP_DAAS_INTERNAL_TOKEN` | Service-to-service DaaS | Quarterly |
| `nidp-tls-cert` | Nginx (nidp-stack-vm) | Cloudflare Origin Cert |
| `nidp-tls-key` | Nginx (nidp-stack-vm) | Cloudflare Origin Key |

---

## 13. Security & IAM

### 13.1 Service Accounts

| Account | Email | Purpose | Key Roles |
|---|---|---|---|
| `nidp-sa` | `nidp-sa@niveshdataintelligence.iam.gserviceaccount.com` | Cloud Run runtime | `secretmanager.secretAccessor`, `artifactregistry.reader`, `logging.logWriter` |
| `nivesh-devops` | `nivesh-devops@niveshdataintelligence.iam.gserviceaccount.com` | CI/CD (Cloud Build) | `cloudbuild.builds.editor`, `artifactregistry.writer`, `run.admin`, `secretmanager.secretAccessor`, `storage.admin`, `iam.serviceAccountUser` |

### 13.2 Human Access

| Identity | Type | Roles |
|---|---|---|
| `aporwal107@gmail.com` | GCP project owner | `roles/owner` |
| `nivesh_dev_ops@niveshcopilot.com` | Google Workspace user (interactive) | `compute.osAdminLogin`, `run.admin`, `cloudbuild.builds.editor`, `secretmanager.secretAccessor`, `logging.viewer` |
| `devops` | Linux user (CI/CD) | NOPASSWD sudo via sudoers drop-in |

### 13.3 TLS

- **Provider:** Cloudflare (CDN + DDoS)
- **Backend certs:** Cloudflare Origin Certificate (stored in GCP Secret Manager)
- **TLS version:** 1.3 (1.2 fallback during migration)
- **HSTS:** `max-age=31536000; includeSubDomains; preload`
- **Target SSL Labs rating:** A+

### 13.4 Token Management

GCP OAuth tokens expire in **1 hour**. Stored in `/app/.gcp-token`.

```bash
# Check token age
stat -c "Modified: %y" /app/.gcp-token

# Refresh (as service account or user)
gcloud auth print-access-token > /app/.gcp-token
```

Refresh when token is > 45 minutes old to avoid mid-deploy expiry.

### 13.5 Known Security Gaps (from SECURITY_GAP_ANALYSIS.md)

- **CRITICAL:** Live tokens may exist in git history — rotate regularly
- **HIGH:** PAN not AES-256 encrypted at rest (planned)
- **HIGH:** No gitleaks in CI pipeline (planned)
- **MEDIUM:** No MFA for admin endpoints (planned)

---

## 14. DevOps Guidelines

### 14.1 Core Principles

1. **Always commit to `dev` branch, never `main`** — main receives only PR merges
2. **Deploy via GitHub, never rsync/scp** — code reaches VMs via `git push` + `git fetch/reset`
3. **Test before deploying** — run Playwright + build locally, fix all issues, deploy ONCE
4. **Never skip hooks** — `--no-verify` is forbidden
5. **Never force-push to main** — always PR
6. **Migrations are forward-only** — write `IF NOT EXISTS`; use `alembic downgrade` only with a PG snapshot
7. **Secrets via Secret Manager only** — never hardcode in code or env files in git

### 14.2 Branch Strategy

```
main        ← production; only receives PR merges from dev
  └── dev   ← staging integration; all dev commits land here
       └── feat/xxx  ← feature branches (short-lived)
```

### 14.3 Deployment Checklist

**Before deploying Nivesh app:**
- [ ] `make verify` passes all 12 smoke tests locally
- [ ] Playwright E2E green
- [ ] `docker build` succeeds locally
- [ ] New migrations tested on local DB
- [ ] No secrets in diff (`git diff --name-only | grep -E ".env|.key|.pem"`)

**Before deploying NIDP VM:**
- [ ] `./test_locally.sh` green for affected services
- [ ] SQL migrations reviewed for forward-safety
- [ ] Smoke test new ingester against a 30-day date range locally
- [ ] `daas/health` + `query/health` confirmed after deploy

**After any deploy:**
- [ ] Check health endpoints
- [ ] Tail logs for 5 minutes (`docker logs -f <container>`)
- [ ] Check Grafana job_health dashboard
- [ ] Verify latest feed ran successfully in `v_feed_status`

### 14.4 Database Migration Rules

**Nivesh PostgreSQL (Alembic + SQL files):**
```bash
# Apply all pending migrations
cd /app/backend && python -m scripts.post_deploy_migrate

# Manual SQL migration
psql $POSTGRES_URL -f backend/migrations/<file>.sql
```

**NIDP TimescaleDB (raw SQL via deploy script):**
```bash
# On nidp-stack-vm, migrations run automatically on deploy
# Manual run:
sudo -u nidp /opt/nidp/repo/backend/nidp/deploy/vm/deploy.sh --branch=dev

# Check applied migrations
psql $NIDP_POSTGRES_URL -c "SELECT filename FROM nidp.schema_migrations ORDER BY applied_at;"
```

### 14.5 Adding a New NIDP Ingester

1. Create `backend/nidp/services/<name>/` with: `service.py`, `parser.py`, `validators.py`, `writer.py`, `__main__.py`, `Dockerfile`
2. Extend `BaseIngester` (`backend/nidp/shared/ingester_base.py`)
3. Register in `source_registry` via a new migration
4. Add cron entry to `backend/nidp/deploy/vm/nidp.cron`
5. Add Cloud Scheduler entry to `backend/nidp/deploy/gcp/setup_schedules.sh`
6. Create Cloud Build trigger in `backend/nidp/deploy/gcp/setup_github_triggers.sh`
7. Add Prometheus port assignment to `prometheus.yml`
8. Test locally with `./test_locally.sh`

### 14.6 Rollback Procedures

**Nivesh app:**
```bash
# Roll back to specific SHA
git -C /opt/nivesh/repo checkout <SHA>
bash /opt/nivesh/deploy/deploy.sh
```

**NIDP VM:**
```bash
sudo -u nidp /opt/nidp/repo/backend/nidp/deploy/vm/rollback.sh <git-sha>
```

**NIDP Cloud Run (DaaS API):**
```bash
# List revisions
gcloud run revisions list --service=nidp-daas-api \
  --region=asia-south1 --project=niveshdataintelligence | head -5

# Route 100% to previous revision
gcloud run services update-traffic nidp-daas-api \
  --to-revisions=<REVISION_NAME>=100 \
  --region=asia-south1 --project=niveshdataintelligence
```

**Database (emergency):**
```bash
# WARNING: Take snapshot before downgrade
NIDP_POSTGRES_URL=$(gcloud secrets versions access latest --secret=NIDP_POSTGRES_URL)
NIDP_POSTGRES_URL="$NIDP_POSTGRES_URL" python -m alembic downgrade -1
```

---

## 15. Operations Cheat Sheet

### 15.1 SSH Access

```bash
# nivesh-app-vm (production)
ssh -i ~/.ssh/nivesh_vm aporwal107_gmail_com@34.47.250.214

# nidp-stack-vm (data platform)
ssh aporwal107_gmail_com@34.93.60.254

# GCP fallback (OS Login)
gcloud compute ssh nivesh-app-vm --project=niveshdataintelligence --zone=asia-south1-a
gcloud compute ssh nidp-stack-vm --project=niveshdataintelligence --zone=asia-south1-a
```

### 15.2 Health Checks

```bash
# Nivesh app
curl -sf https://niveshcopilot.com/api/health

# NIDP DaaS
curl -sf https://data.niveshcopilot.com/daas/health

# NIDP Query
curl -sf https://data.niveshcopilot.com/query/health

# Feed freshness (on nidp-stack-vm)
psql $NIDP_POSTGRES_URL -c \
  "SELECT source_name, last_success_at, consecutive_failures FROM nidp.v_feed_status ORDER BY last_success_at DESC LIMIT 15;"
```

### 15.3 Nivesh App Service Management

```bash
COMPOSE="docker compose -f /opt/nivesh/deploy/docker-compose.prod.yml"

$COMPOSE ps                          # Status
$COMPOSE logs -f backend             # Live backend logs
$COMPOSE restart backend             # Restart backend
$COMPOSE restart                     # Restart all
$COMPOSE up -d --remove-orphans      # Start/update all
docker exec -it nivesh-mongo mongosh # MongoDB shell
docker exec -it nivesh-postgres psql -U postgres -d nivesh_prod  # PG shell
docker exec -it nivesh-redis redis-cli  # Redis shell
```

### 15.4 NIDP Service Management

```bash
# DaaS / Query API (systemd)
sudo systemctl restart nidp-daas-api nidp-query-api
sudo journalctl -u nidp-daas-api -f
sudo journalctl -u nidp-query-api -f

# Run ingester manually (on nidp-stack-vm)
sudo -u nidp /opt/nidp/repo/backend/nidp/deploy/vm/run_service.sh bhavcopy
sudo -u nidp /opt/nidp/repo/backend/nidp/deploy/vm/run_service.sh amfi_nav

# Docker containers
docker compose -f /opt/nidp/repo/backend/nidp/deploy/vm/docker-compose.prod.yml ps
docker logs nidp-postgres --tail 50

# Cron
cat /etc/cron.d/nidp
sudo systemctl reload cron
```

### 15.5 GCP Cloud Run (Manual Trigger)

```bash
TOKEN=$(cat /app/.gcp-token)
CLOUDSDK_AUTH_ACCESS_TOKEN="$TOKEN" \
  gcloud run jobs execute nidp-nse-eod \
  --region=asia-south1 --project=niveshdataintelligence --wait
```

### 15.6 GCP Cloud Build (Manual Submit)

```bash
TOKEN=$(cat /app/.gcp-token)
CLOUDSDK_AUTH_ACCESS_TOKEN="$TOKEN" \
  gcloud builds submit . \
  --config=backend/nidp/deploy/gcp/cloudbuild-daas.yaml \
  --substitutions="_REGION=asia-south1,_CORS_ORIGINS=*" \
  --project=niveshdataintelligence --async
```

### 15.7 GCP VM Management

```bash
# List instances
gcloud compute instances list --project=niveshdataintelligence \
  --format="table(name,zone,machineType,networkInterfaces[0].accessConfigs[0].natIP)"

# Stop / start
gcloud compute instances stop nidp-stack-vm --project=niveshdataintelligence --zone=asia-south1-a
gcloud compute instances start nidp-stack-vm --project=niveshdataintelligence --zone=asia-south1-a
```

### 15.8 GCP Cloud Logging Queries

```bash
# Recent DaaS errors
gcloud logging read \
  'resource.type=cloud_run_revision AND resource.labels.service_name=nidp-daas-api AND severity>=ERROR' \
  --limit=20 --project=niveshdataintelligence

# Specific job run
gcloud logging read \
  'resource.type=cloud_run_job AND resource.labels.job_name=nidp-nse-eod' \
  --limit=50 --format='value(timestamp,textPayload)' --project=niveshdataintelligence
```

### 15.9 Database Quick Access

```bash
# NIDP TimescaleDB
psql postgresql://postgres:<pass>@localhost:5433/nidp

# Feed status
SELECT source_name, last_success_at, consecutive_failures FROM nidp.v_feed_status;

# Latest job runs
SELECT ingester, status, started_at, rows_inserted FROM nidp.job_log
  ORDER BY started_at DESC LIMIT 20;

# Validation blockers
SELECT ingester, rule_name, severity, message FROM nidp.validation_findings
  WHERE severity='BLOCK' AND created_at > NOW() - INTERVAL '24h';

# Nivesh app PG
psql postgresql://postgres:<pass>@localhost:5432/nivesh_prod

# Check V3 scores
SELECT fund_name, quality_score, health_score, v3_scored_at FROM mutual_fund_metadata
  WHERE v3_scored_at > NOW() - INTERVAL '24h' ORDER BY quality_score DESC LIMIT 10;
```

### 15.10 Cost Reference

| Resource | Monthly Cost |
|---|---|
| `nidp-stack-vm` (e2-small) | ~$8 |
| `nivesh-app-vm` (e2-standard-4) | ~$25 |
| Cloud Run Jobs (28 ingesters) | ~$2–5 |
| Cloud Run Services (DaaS + Query) | ~$5–12 |
| Serverless VPC connector | ~$6 |
| Artifact Registry | ~$1–2 |
| Cloud Build | ~$1–5 |
| Secret Manager | ~$1 |
| Cloud Logging | ~$1–2 |
| **Subtotal** | **~$50–66/month** |
| Cloud Armor + Global LB (optional) | +~$20 |

### 15.11 Emergency Contacts & Links

| Resource | Link |
|---|---|
| Grafana (NIDP) | https://data.niveshcopilot.com/grafana/ |
| GCP Console | https://console.cloud.google.com |
| Cloud Logging | https://console.cloud.google.com/logs/query?project=niveshdataintelligence |
| Cloud Run jobs | https://console.cloud.google.com/run/jobs?project=niveshdataintelligence |
| Cloud Build history | https://console.cloud.google.com/cloud-build/builds?project=niveshdataintelligence |
| VM instances | https://console.cloud.google.com/compute/instances?project=niveshdataintelligence |
| Cloud Scheduler | https://console.cloud.google.com/cloudscheduler?project=niveshdataintelligence |
| Artifact Registry | https://console.cloud.google.com/artifacts?project=niveshdataintelligence |
| Secret Manager | https://console.cloud.google.com/security/secret-manager?project=niveshdataintelligence |

---

## 16. NIDP Data Quality Gates

**Source documents:** `/app/docs/NIDP_FEEDS/QUALITY_GATE.md` (472 lines, PRD v1.0, 2026-05-27) and `/app/docs/NIDP_FEEDS/EXTENDED_QUALITY_GATE.md` (rules catalogue)

### 16.1 Overview

NIDP processes 41 feeds across 4 layers. The Quality Gates PRD proposes a **layered DQ system** that places enforcement checkpoints at every storage-tier transition, replacing the current scattered, non-blocking checks.

**Current state:** Rules are column-level, finite, and non-blocking. Bad data propagates to V3 scores and user-facing Copilot recommendations silently.

**Target state:** Every tier boundary has a gate. Gates follow the same structure: `verify → record verdict → block or pass → emit metric`.

### 16.2 The 7-Gate Architecture

```
External Source
    │
    ▼
  [Gate 1] Ingestion Gate          — inside each ingester, pre-Kafka publish
    │
    ▼
Redpanda Topics + Schema Registry
    │
    ▼
  [Gate 2] Stream Processing Gate  — Kafka consumer → TimescaleDB
    │
    ▼
TimescaleDB Primary (:5433)
    │
    ├──► [Gate 3] Snapshot Completion Gate   — pre-derivation engines ⭐ Highest priority
    │       │
    │       ▼
    │     V3 Scores, Features, Fundamentals
    │
    ├──► [Gate 4] Replication Integrity Gate — Primary (:5433) → Standby (:5434)
    │
    └──► [Gate 5] Warm-Tier Export Gate      — TimescaleDB → MinIO Parquet
           │
           ▼
         DuckDB Analytics Endpoints
    │
    ▼
  [Gate 6] API Output Gate         — DaaS API middleware, user-facing DQ envelope ⭐
    │
    ▼
Nivesh Copilot → End User

  [Gate 7] Observability Gate      — continuous, cross-cutting SLO/error-budget alerting
```

### 16.3 Gate Anatomy (shared across all 7 gates)

Every gate is implemented as a shared Python library `nidp_dq_gates` with the same 4-step structure:

```
1. VERIFY        — run gate-specific invariants (GE expectations + custom rules)
2. RECORD VERDICT — persist to dq.gate_verdicts with ingest_run_id FK linkage
3. BLOCK or PASS  — P0 fail → block+raise | P1 fail → pass with AMBER | P2 → log only
4. EMIT METRIC    — Prometheus counter + structured Loki log
```

### 16.4 Severity Contract

| Severity | Meaning | Gate Action | Example |
|---|---|---|---|
| **P0** | Blocks downstream completely | Stop propagation, page on-call | `bhavcopy` row count < 1,800 |
| **P1** | Domain degraded, data still usable | Pass with AMBER flag, Slack alert | `mf_holdings` stale > 7 days |
| **P2** | Cosmetic / informational | Pass, log only | Single column null rate slightly elevated |

### 16.5 Gate Specifications

#### Gate 1 — Ingestion Gate
**Location:** Inside each ingester service, before `producer.send()` to Redpanda.  
**Speed budget:** < 50ms per message batch.

**Universal rules (all feeds):**

| Rule ID | Invariant | Severity |
|---|---|---|
| `G1-U-001` | Avro schema validates against Schema Registry | P0 |
| `G1-U-002` | Kafka headers `ingest_run_id`, `source_checksum`, `source_timestamp` present | P0 |
| `G1-U-003` | Source timestamp not in future | P0 |
| `G1-U-004` | Source timestamp not older than 7 days | P1 |
| `G1-U-005` | Trading-day alignment (for trading-day feeds) | P0 |
| `G1-U-006` | Row count within trailing 30-day band (±2%) | P0 |

**Feed-specific rules (sample):**

| Feed | Rule | Invariant | Severity |
|---|---|---|---|
| bhavcopy | `G1-BHV-001` | `symbol` not null, ≤ 20 chars | P0 |
| bhavcopy | `G1-BHV-002` | All OHLC prices > 0 | P0 |
| bhavcopy | `G1-BHV-004` | OHLC sanity: `low ≤ open, close ≤ high` | P0 |
| bhavcopy | `G1-BHV-005` | Symbol count 1,800–2,200 | P0 |
| bhavcopy | `G1-BHV-007` | Symbol cardinality drift < 2% vs previous trading day | P1 |
| delivery | `G1-DLV-001` | `deliv_per` between 0 and 100 | P0 |
| delivery | `G1-DLV-003` | `deliv_qty ≤ ttl_trd_qnty` | P0 |
| delivery | `G1-DLV-004` | Date is T+1 of a trading day | P0 |

**Failure action:** Route to `dq.quarantine.<feed>` Redpanda topic; do NOT publish to main topic.

---

#### Gate 2 — Stream Processing Gate
**Location:** Kafka consumer that writes from Redpanda to TimescaleDB hypertables.

**Invariants:**
- FK resolution: every `bhavcopy.symbol` exists in `ref.sector_master`; every `mf_nav_daily.scheme_code` in `mf_scheme_master`
- Idempotency: no duplicate writes for same `(primary_key, trade_date)`
- Cross-message ordering enforced per partition
- DLQ: failed messages → `dq.dlq.<feed>` Kafka topic + `dq.dlq_findings` table
- Consumer commits Kafka offset **only after** write AND verdict both persisted (transactional)

**Failure action:** Route to DLQ. Auto-retry: 3 attempts with exponential backoff, then permanent DLQ.

---

#### Gate 3 — Snapshot Completion Gate ⭐ Highest Priority
**Location:** Extends existing `snapshot_builder` service preflight.  
**Purpose:** Block all derivation engines from running on incomplete input.  
**Status:** Migration 077 created `dq.gate_verdicts` + `dq.feed_sla` tables (live).

**Services blocked by a Gate 3 FAIL:**
- `technical_indicator_engine`
- `fundamental_engine`
- `v3_scores_engine`
- `analytics_refresh`
- `mf_derived_refresh`

**Invariants enforced:**

| Check | Severity |
|---|---|
| All P0 input feeds for date D have landed AND passed Gates 1+2 | P0 |
| Row counts within trailing 30-day band per feed | P0 |
| No outstanding DLQ messages for date D | P0 |
| `count(bhavcopy.symbol) ≈ count(delivery.symbol)` within ±2% | P0 |
| `index_constituents` universe is superset of scored stocks | P1 |
| `shareholding_pattern` percentages sum to 100 ± 0.5% | P1 |
| TimescaleDB primary–standby replication lag = 0 | P0 |
| Last `corporate_actions` check within 24 hours | P1 |

**Failure action:** Derivation chain does not start. Emit `nidp_snapshot_blocked_total{reason="<feed>_missing"}`. Grafana panel shows "Daily Chain Status": GREEN / BLOCKED.

**Target SLO:** 99% of trading days complete all gates by 19:30 IST.

---

#### Gate 4 — Replication Integrity Gate
**Location:** `gate4_replication_check.py` cron — runs every minute (WAL) + daily 01:00 (row-count parity).  
**Status:** LIVE (migration 075 enabled; cron entry active in `nidp.cron`).

**Invariants:**

| Check | Frequency | Severity |
|---|---|---|
| WAL lag < 30 seconds | Every 60s | P0 |
| `pg_is_in_recovery() = true` on standby | Every 60s | P0 |
| Row-count parity on 5 hypertables (`bhavcopy`, `mf_nav_daily`, `v3_stock_scores_daily`, `portfolio_holdings`, `corporate_announcements`) | Daily 01:00 | P0 |
| Checksum parity (xxhash of sample partitions) | Daily 01:00 | P1 |

**Failure action:** DaaS API routes reads back to primary (:5433), SRE alert. P1 → Slack ticket within 24h.

---

#### Gate 5 — Warm-Tier Export Gate
**Location:** Inside `parquet_exporter` service (00:30 IST cron, Tue–Sat).

**Invariants (write-then-verify with atomic rename):**
1. Export to `parquet/<feed>/year=Y/month=M/_tmp/*.parquet`
2. Row count matches TimescaleDB source query (±0 tolerance)
3. Schema validation (column names, types, partition keys)
4. Sample 100 random rows through DuckDB, compare to source
5. Parquet file readable and valid
6. Atomic `mv _tmp/ → final/`

DuckDB reads only from finalized partitions (`_tmp/` excluded via glob pattern).

**Failure action:** Delete `_tmp/` files, partition stays at previous version, page SRE.

---

#### Gate 6 — API Output Gate ⭐ User-Facing
**Location:** DaaS API middleware on every `/v1/*` endpoint.

**DQ Envelope in every API response:**

```json
{
  "data": { "...endpoint payload..." },
  "data_quality": {
    "as_of_date": "2026-05-27",
    "data_freshness_seconds": 1847,
    "dq_status": "AMBER",
    "degraded_feeds": [
      {
        "feed": "mf_holdings",
        "last_successful_run": "2026-04-27T22:30:00+05:30",
        "staleness_days": 30,
        "impact": "MF concentration metrics are stale"
      }
    ],
    "snapshot_id": "snap_2026-05-27_abc123",
    "gate_verdict_uri": "/v1/dq/verdict/snap_2026-05-27_abc123"
  }
}
```

**Status values:** `GREEN` (all feeds fresh) | `AMBER` (P1 degradation) | `RED` (P0 blocked)

---

#### Gate 7 — Observability Gate (Cross-Cutting)
**Location:** Prometheus recording rules + Loki log patterns.  
**Purpose:** Replaces threshold-based alerting with SLO error-budget burn-rate alerts.

| Metric | Purpose |
|---|---|
| `nidp_dq_gate1_failures_total{feed, severity}` | Gate 1 block counter |
| `nidp_dq_gate3_snapshot_blocked_total{reason}` | Gate 3 blocks |
| `nidp_dq_gate4_wal_lag_seconds` | Replication lag gauge |
| `nidp_dq_gate5_export_failures_total` | Warm-tier export failures |
| `nidp_dq_dlq_messages_pending{feed}` | DLQ backlog per feed |

### 16.6 Data Model (`dq` schema)

| Table | Purpose |
|---|---|
| `dq.gate_verdicts` | Every gate invocation: `gate_id`, `feed`, `ingest_run_id`, `verdict`, `severity`, `details`, `timestamp` |
| `dq.dlq_findings` | Messages quarantined at Gate 1 or 2 with replay capability |
| `dq.feed_sla` | Per-feed SLO definitions (freshness window, row count band, severity weights) |
| `dq.feed_signatures` | Daily statistical fingerprint per feed (row count, null rates, min/max, cardinality) |
| `dq.snapshot_status` | Per-date status of Gate 3 (PENDING / PASS / BLOCKED) |

**FK linkage:** All `nidp.*` hypertable rows gain a `dq_verdict_id FK → dq.gate_verdicts.id` column (NULL for historical rows; NOT NULL enforced post-cutover).

### 16.7 Rollout Plan (Q3–Q4 2026)

| Phase | Weeks | Gates | Rationale |
|---|---|---|---|
| 1 | 1–4 | Gate 3 | Highest leverage; extends existing `snapshot_builder`; cheapest to build |
| 2 | 5–8 | Gate 5 | New warm-tier has zero protection; DuckDB risk rising |
| 3 | 9–14 | Gate 6 + Copilot | User-facing protection; requires Copilot team partnership |
| 4 | 15–22 | Gates 1 + 2 | Largest effort; touches all 28 ingesters |
| 5 | 23–26 | Gate 4 + Gate 7 SLO migration | Polish; decommission legacy threshold alerts |

Each gate follows: **Shadow mode (2w) → Canary (1w) → Progressive enable (2w) → Full enforcement**.

### 16.8 Configuration Layout

Rules are tuned via YAML, not code:

```
backend/nidp/services/quality_gate/nidp_dq_gates/config/
├── feeds/<feed>.yaml          — SLA, thresholds, enabled gates, notification channels
├── expectations/<feed>.json   — Great Expectations expectation suites
└── gates/gate<N>_<name>.yaml  — Which expectations run at each gate
```

### 16.9 Success KPIs

| Metric | Today | Target (Q4 2026) |
|---|---|---|
| Undetected DQ incidents per quarter | Unknown (est. 5–10) | < 1 |
| MTTD for DQ incidents | Hours to days | < 5 minutes |
| V3 scores generated on incomplete input | Unknown | 0 |
| DaaS responses with DQ envelope | 0% | 100% |
| Copilot DQ-aware responses | 0% | 100% |

---

## 17. Jenkins CI/CD Pipeline

**Source:** `/app/Jenkinsfile` (pipeline DSL, Groovy)

### 17.1 Overview

Jenkins provides a path-aware CI/CD pipeline triggered on every GitHub push. It determines from the diff which system changed and only deploys what's needed.

```
GitHub Push (any branch)
    │
    ▼ webhook
Jenkins (githubPush() trigger)
    │
    ▼
Stage: Changed Paths
    ├── frontend/** or backend/** (not nidp) or deploy/nivesh-app/** → DEPLOY_APP=true
    └── backend/nidp/**                                             → DEPLOY_NIDP=true
    │
    ├── [DEPLOY_APP=true]
    │   ├── Stage: CI — Backend Syntax (py_compile all .py files)
    │   ├── Stage: CI — Frontend Build (yarn build, REACT_APP_BACKEND_URL=https://niveshcopilot.com, PUBLIC_URL=/v2)
    │   └── Stage: Deploy → nivesh-app-vm (SSH redeploy.sh with --frontend-only / --backend-only flags)
    │
    └── [DEPLOY_NIDP=true]
        ├── (no separate build stage — rsync direct)
        └── Stage: Deploy → nidp-stack-vm (rsync backend/nidp/ + reload cron + restart services)
    │
    ▼
Stage: Health Check (parallel)
    ├── App health → curl https://niveshcopilot.com/api/health → HTTP 200
    └── NIDP health → curl http://34.93.60.254:8010/health → HTTP 200
```

### 17.2 Pipeline Configuration

| Setting | Value |
|---|---|
| **Trigger** | `githubPush()` (GitHub webhook on every push) |
| **Build retention** | Last 30 builds (`logRotator(numToKeepStr: '30')`) |
| **Timeout** | 45 minutes |
| **ANSI colour** | Enabled (`xterm`) |
| **Default deploy branch** | `main` |
| **NIDP VM host** | `34.93.60.254` (hardcoded) |
| **App VM host** | `credentials('NIVESH_APP_VM_HOST')` (Jenkins secret text) |
| **SSH user** | `aporwal107_gmail_com` |

### 17.3 Required Jenkins Credentials

| Credential ID | Type | Used By |
|---|---|---|
| `NIVESH_APP_VM_HOST` | Secret text | Nivesh app VM IP (env var) |
| `nivesh-app-vm-ssh` | SSH private key | Deploy → nivesh-app-vm stage |
| `nidp-stack-vm-ssh` | SSH private key | Deploy → nidp-stack-vm stage |

### 17.4 Stage Details

#### Stage: Changed Paths
Uses `git diff --name-only HEAD~1 HEAD` to detect what changed. Sets four env flags:

| Flag | Set when |
|---|---|
| `DEPLOY_APP` | `frontend/**` OR `backend/**` (not nidp) OR `deploy/nivesh-app/**` changed |
| `DEPLOY_NIDP` | `backend/nidp/**` changed |
| `ONLY_FRONTEND` | Only `frontend/**` changed (no backend changes) |
| `ONLY_BACKEND` | Only `backend/**` (not nidp) changed (no frontend changes) |

#### Stage: CI — Backend Syntax
- Runs `python3 -m py_compile backend/server.py`
- Then `find backend -name "*.py" ... -exec python3 -m py_compile {} +` (all Python files)
- Skips if neither `DEPLOY_APP` nor `DEPLOY_NIDP` is true

#### Stage: CI — Frontend Build
- `cd frontend && yarn install --frozen-lockfile --network-timeout 600000`
- `REACT_APP_BACKEND_URL=https://niveshcopilot.com PUBLIC_URL=/v2 CI=false yarn build`
- Skips if `ONLY_BACKEND=true`

#### Stage: Deploy → nivesh-app-vm
- SSH into `$NIVESH_VM_HOST` as `$SSH_USER` using `nivesh-app-vm-ssh` key
- Runs `sudo BRANCH=main bash /opt/nivesh/deploy/redeploy.sh [--frontend-only|--backend-only]`
- Flag selection: `ONLY_FRONTEND=true` → `--frontend-only`; `ONLY_BACKEND=true` → `--backend-only`; full change → no flags

#### Stage: Deploy → nidp-stack-vm
- `rsync -az --delete` `backend/nidp/` → `/opt/nidp/repo/backend/nidp/` (SSH tunnel)
  - Excludes: `__pycache__`, `*.pyc`, `.git`, `*.egg-info`
- SSH remote commands:
  1. `sudo systemctl reload cron`
  2. `sudo systemctl restart nidp-query-api` (if active)
  3. `sudo systemctl restart nidp-daas` (if active)

> **Note:** The Jenkins NIDP deploy uses `rsync` directly (unlike the documented `git push + git fetch/reset` pattern used in manual deployments). This is a Jenkins-specific fast path — it rsync-copies the workspace tree the CI runner already has checked out. The memory guideline "Deploy via GitHub, never rsync" applies to *manual* operator deployments, not to this CI pipeline.

#### Stage: Health Check (parallel)
- App: waits 15s, `curl -sf -w "%{http_code}" https://niveshcopilot.com/api/health` — expects `200`
- NIDP: waits 8s, `curl -sf http://34.93.60.254:8010/health` — expects `200`
- Both run in parallel after deploy stages complete
- Non-200 response emits `WARNING` (does not fail the build — intentional)

### 17.5 Post Actions

```
always  → echo "Pipeline finished: ${currentBuild.currentResult}"
failure → echo "❌ Build/deploy failed." 
          (Slack notification commented out — uncomment to enable:
           slackSend(channel:'#deploys', message:"Deploy failed: ${JOB_NAME} ${BUILD_URL}"))
```

### 17.6 Jenkins vs GCP Cloud Build — Split Responsibilities

| Task | Handled By | Trigger |
|---|---|---|
| Nivesh app deploy (frontend + backend) | **Jenkins** | GitHub push (any branch) |
| NIDP VM service deploy (DaaS + Query API + cron) | **Jenkins** | GitHub push to `backend/nidp/**` |
| NIDP Cloud Run Jobs (28 ingesters) | **GCP Cloud Build** | GitHub push to `backend/nidp/services/<svc>/**` (28 triggers) |
| NIDP DaaS API Cloud Run Service | **GCP Cloud Build** | Push to `backend/nidp/services/daas_api/**` |
| DB migrations (Cloud Run variant) | **GCP Cloud Build** | Manual or push when migrations change |
| Manual VM deploy (operator) | `deploy.sh` / `redeploy.sh` scripts | Manual SSH |

---

## 18. Admin Console & NIDP Console

**Source:** `/app/docs/FRD_ADMIN_CONSOLE.md` (validated against code, May 2026)  
**Access control:** All admin routes use `Depends(require_admin(request))`. Frontend `AdminView.js` gates the tab behind `user.is_admin = true` or `user.role = "admin"`.  
**URL:** `https://niveshcopilot.com/` (admin tab visible only to admins after login)

### 18.1 Admin Console Architecture

```
AdminView.js  (frontend shell)
    │
    ├── Users tab           → /api/admin/users, /api/admin/whitelist
    ├── Rules tab           → /api/admin/rules-config
    ├── CAS tab             → /api/admin/secrets (CAS keys)
    ├── Feature Flags tab   → /api/admin/feature-flags/{flag}/toggle
    ├── Data Pipeline tab   → /api/admin/data-pipeline/status, /trigger/{job}
    ├── NIDP Jobs tab       → /api/admin/nidp/jobs, /execute
    ├── V3 Engine tab       → /api/admin/v3-weights, /v3-stock-weights, /v3-master-funds
    ├── Datastores tab      → /api/admin/datastores/status
    ├── NIDP DQ tab         → NidpQualityDashboard.jsx (53 KB component)
    └── NIDP Backfill tab   → /api/admin/nidp/backfill/readiness
```

### 18.2 Module: Secrets Management (FR-ADM-001)

**Routes:** `GET/POST/DELETE /api/admin/secrets`  
**Backend:** `routes/admin.py`  
**Frontend:** `SecretsSection.jsx`  
**Status:** LIVE

Secrets are stored in MongoDB `system_config.secrets` and hydrated into process memory at startup. Changes take effect immediately without restart.

**30+ managed secrets by category:**

| Category | Secrets |
|---|---|
| CAS Parsing | `GOOGLE_DOCAI_CREDENTIALS_JSON`, `GOOGLE_DOCAI_PROJECT`, `GOOGLE_DOCAI_PROCESSOR`, `CASPARSER_API_KEY`, `CASPARSER_SANDBOX_KEY` |
| LLM | `EMERGENT_LLM_KEY` |
| Auth | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GMAIL_OAUTH_CLIENT_ID` |
| Datastores | `POSTGRES_URL`, `REDIS_URL`, `NIDP_POSTGRES_URL` |
| Market Data | `CHARTINK_WEBHOOK_SECRET`, `YFINANCE_API_KEY` |
| Broker APIs | 9 broker API keys (Zerodha, Upstox, Angel One, Dhan, Fyers, 5Paisa, Kotak, IIFL, HDFC) |

UI behaviour: values masked by default; eye-icon toggle to reveal; deletion requires confirmation modal.

### 18.3 Module: Feature Flags (FR-ADM-002)

**Routes:** `GET/POST /api/admin/feature-flags/{flag}/toggle`  
**Backend:** `routes/admin.py`  
**Frontend:** `FeatureFlagsSection.jsx`  
**Status:** LIVE

| Mode | Behaviour |
|---|---|
| `disabled` | Feature off for all users |
| `allowlist` | Feature on only for specified email list |
| `everyone` | Feature on for all users |

**Known active flags:**

| Flag | Purpose |
|---|---|
| `enable_positional_scanner` | Positional trading engine |
| `enable_goals_planning` | Goals module |
| `enable_mfd_workspace` | MFD advisor workspace |
| `USE_LANGGRAPH_AGENT` | Copilot V2 LangGraph path |
| `enable_nidp_copilot` | NIDP market context in Copilot responses |
| `copilot_persona_prompts_enabled` | 99-prompt persona catalog |

### 18.4 Module: Rules Configuration (FR-ADM-003/004)

**Routes:** `GET/PATCH /api/admin/rules-config`  
**Backend:** `routes/admin_rules.py`  
**Frontend:** `RulesConfigSection.jsx`  
**Status:** LIVE

**Live-tunable action plan parameters (no deploy required):**

| Parameter | Default | Affects |
|---|---|---|
| `amc_concentration_threshold_pct` | 15% | Rule 2 (AMC Concentration) |
| `category_concentration_threshold_pct` | 35% | Rule 2b (Category Concentration) |
| `debt_floor_conservative_pct` | 30% | Rule 5 (Debt Gap) |
| `debt_floor_moderate_pct` | 20% | Rule 5 (Debt Gap) |
| `debt_floor_aggressive_pct` | 10% | Rule 5 (Debt Gap) |
| `cost_leak_minimum_rs` | ₹10,000 | Rule 6 (Cost-Leak Switch) |
| `min_switch_score` | 1.0 | Rule 6 guardrail |
| `high_quality_protection_quality_threshold` | 75 | Guardrail 1 |
| `high_quality_protection_health_threshold` | 70 | Guardrail 1 |
| `overlap_override_pct` | 80% | Guardrail 1 exception |
| `recent_investment_lockout_months` | 6 | Guardrail 3 |
| `underperformer_ret_1y_threshold_pct` | 8% | Rule 3 |
| `underperformer_ret_3y_threshold_pct` | 10% | Rule 3 |

**Custom Rules DSL (FR-ADM-004):** Admin can define additional action plan rules using a safe AST DSL (whitelisted operations — no `eval()`). Applied after the 6 built-in rules via `_apply_custom_rules()`.

### 18.5 Module: LLM Prompts (FR-ADM-005)

**Routes:** `GET/POST /api/admin/prompts/{id}/test`  
**Backend:** `routes/admin_rules.py`  
**Frontend:** `PromptsSection.jsx`  
**Status:** LIVE

**7 managed prompts:**

| Prompt ID | Purpose |
|---|---|
| `copilot_system` | Main copilot persona + grounding instructions |
| `plan_summary` | Converts structured plan to 200-word plain English |
| `insight_narrative` | Portfolio insight description text |
| `goal_advice` | Goal-based investment guidance |
| `risk_profile_intro` | Risk questionnaire preamble |
| `whatsapp_export` | Mobile-friendly plan summary |
| `mfd_client_report` | Advisor report narrative |

Sandbox mode: admin provides mock data + test query → system runs prompt against LLM → completion shown in sandbox pane, no live-user impact.

### 18.6 Module: Data Pipeline Monitor (FR-ADM-006)

**Routes:** `GET /api/admin/data-pipeline/status`, `POST /api/admin/data-pipeline/trigger/{job}`  
**Backend:** `routes/admin_data_pipeline.py`  
**Frontend:** `DataPipelineMonitor.jsx`  
**Status:** LIVE

**Three-panel view:**

1. **Job Status Tiles** — per scheduled job: last run time, status (OK/FAILED), rows processed, duration ms
   - AMFI NAV (daily 22:00 IST)
   - Analytics Sweep (daily 22:30 IST)
   - V3 Rescore (daily 22:45 IST)
   - Nifty100 Refresh (weekly)
   - Stale Refresh (weekly Wed 03:00 IST)

2. **Recent Runs Log** — last 20 rows from `nav_analytics_job_log` (job_name, started_at, processed, failed, duration_ms, error_msg)

3. **Scheduler Status** — APScheduler next-fire times per job

4. **Redis Key Count** — live count of `v3:score:*` keys (cache health indicator)

**Manual Trigger:** `POST /api/admin/data-pipeline/trigger/{job}` where `job` ∈ `{amfi_navs, analytics_sweep, v3_rescore, nifty100_refresh}` — on-demand button in UI.

**Cache Invalidation:** `POST /api/admin/cache/invalidate` — drops all `v3:score:*` Redis keys. Use after major scoring weight change.

### 18.7 Module: V3 Engine Configuration (FR-ADM-007/008/009)

**Scoring weights are fully editable without code deploy:**

| Composite | Sub-weights Editable | Route |
|---|---|---|
| Quality | Performance, Risk-Adjusted, Consistency, Drawdown, Cost, AUM-Age (must sum 100%) | `PUT /api/admin/v3-weights` |
| Health | Manager, AUM-Stability, Turnover, Concentration, Downside, Expense-Trend | `PUT /api/admin/v3-weights` |
| Exit | Overlap, Tax, Quality-inverse, Cost, Portfolio-Fit | `PUT /api/admin/v3-weights` |
| Add | Gap-Fit, Low-Overlap, Quality, Need, Cost | `PUT /api/admin/v3-weights` |
| Portfolio-Fit | Diversification, Overlap, AMC, Cost, Asset-Alloc | `PUT /api/admin/v3-weights` |
| Stock scoring | Technical, Fundamental, Valuation, Risk, Portfolio-Fit | `PUT /api/admin/v3-stock-weights` |

**V3 Master Fund Catalogue:** `GET /api/admin/v3-master-funds` — browsable fund browser with all computed primitives and scores. XLSX export at `/api/admin/v3-master-funds/export.xlsx`.

**Reset to factory defaults:** `POST /api/admin/v3-weights/reset`

### 18.8 Module: Datastores Management (FR-ADM-010)

**Routes:** `GET /api/admin/datastores/status` + service restart endpoints  
**Backend:** `routes/admin_datastores.py`  
**Frontend:** `DatastoreSection.jsx`  
**Status:** LIVE

Shows live status of all three databases:
- **PostgreSQL:** connection status, table row counts (instrument_master, NAV history, performance ratios, etc.)
- **Redis:** connection status, key counts by prefix (`v3:score:*`, `session:*`, `intelligence:*`)
- **NIDP PostgreSQL:** connection status, migration level

Restart buttons reconnect connection pools without server restart:
- `POST /api/admin/datastores/postgres/restart`
- `POST /api/admin/datastores/redis/restart`

### 18.9 Module: CAS Parser Configuration (FR-ADM-011)

**Frontend:** `CasConfigSection.jsx`  
**Status:** LIVE

Three-provider toggle with independent enable/disable:

| Provider | Config Available | Notes |
|---|---|---|
| Nivesh Parser (Google Document AI) | Enable/Disable | Shows credential status from Secrets |
| Claude Vision (Anthropic) | Enable/Disable | Shows API key status |
| casparser.in API | Enable/Disable + Sandbox toggle | Shows key status; sandbox mode uses test endpoint |

### 18.10 Module: User Management (FR-ADM-012/013)

**Routes:** `GET /api/admin/users?q=`, `POST /api/admin/users/{id}/promote-admin`, `POST /api/admin/users/{id}/reset-portfolio`  
**Routes:** `GET/POST /api/admin/whitelist/add`, `POST /api/admin/whitelist/bulk-upload`  
**Backend:** `routes/admin_users.py`, `routes/admin.py`  
**Status:** LIVE

**User table columns:** email, total corpus value, holdings count, plan count, last active, active session flag

**Per-user actions:**
- **Promote to Admin** — sets `is_admin=true`
- **Force Logout** — invalidates all sessions
- **Reset Portfolio** — wipes 21 user-scoped MongoDB collections + all Redis caches; **gated by email-confirmation modal; cannot be undone**

**Whitelist management:**
- Single add: `POST /api/admin/whitelist/add`
- Bulk CSV/text upload: `POST /api/admin/whitelist/bulk-upload`
- Email not on whitelist → login attempt returns 403

### 18.11 Module: NIDP Console (FR-ADM-014 to FR-ADM-018)

The NIDP sub-panel within Admin Console provides direct control over the NIDP data platform.

#### NIDP Jobs Control Panel (FR-ADM-014)
**Routes:** `GET /api/admin/nidp/jobs`, `POST /api/admin/nidp/jobs/{ingester}/execute`  
**Backend:** `routes/admin_nidp.py`  
**Frontend:** `NidpJobsPanel.jsx`

Controls 13 ingesters with per-job: last_run, status (OK/FAILED/RUNNING), rows_ingested, duration_ms, error_msg.

**Controllable ingesters:** bhavcopy, delivery, index_close, fii_dii, corporate_actions, bulk_deals, rbi_yields, fred_macro, yfinance, amfi_nav, index_constituents, corporate_announcements, documents

#### NIDP Diagnostics (FR-ADM-015)
**Route:** `POST /api/admin/nidp/dump`  
**Status:** SCAFFOLDED

Full system diagnostic bundle: connectivity checks, table row counts, last-ingestion dates, data freshness per feed. Returns structured JSON.

#### NIDP Backfill Control (FR-ADM-016)
**Route:** `GET /api/admin/nidp/backfill/readiness`  
**Backend:** `routes/admin_nidp_backfill.py`  
**Frontend:** `NidpBackfillPanel.jsx`

**Readiness matrix:** per-feed readiness before triggering backfill:
- Feed name | Current row count | Earliest date | Gap days | Ready (yes/no)

Backfill trigger: SSH-driven Cloud Run job with `--from YYYY-MM-DD --to YYYY-MM-DD`.

#### NIDP Replay Engine (FR-ADM-017)
**Route:** `GET /api/admin/nidp/replay/policies`  
**Backend:** `routes/admin_nidp_replay.py`  
**Frontend:** `NidpReplayPanel.jsx`

Replays historical ingestion from GCS raw archives with updated parsers or validators. Supports policy-based and failure-injection replay.

#### NIDP Data Quality Dashboard (FR-ADM-018)
**Frontend:** `NidpQualityDashboard.jsx` (53 KB — largest admin component)  
**Sub-component:** `NidpDqAiPanel.jsx` (AI-generated fix suggestions)

**Four sections:**

| Section | Content |
|---|---|
| Validation Failures | Recent DQ failures by feed, severity (BLOCK/FIX/WARN), with timestamps |
| Quality Trends | Pass rate % per feed over last 30 days (line charts) |
| DQ Rules | All active validation rules with trigger conditions and severity |
| AI Suggestions | Claude-generated fix suggestions for active DQ issues |

### 18.12 Admin Console — Gap Analysis

| Feature | Status |
|---|---|
| Audit log viewer UI | NOT IMPLEMENTED (data exists in MongoDB; viewer is roadmap) |
| Automated data retention sweeps | NOT IMPLEMENTED |
| DPO alerting on suspicious access | NOT IMPLEMENTED |
| Admin MFA requirement | NOT IMPLEMENTED (role-check only) |
| SIEM integration | NOT IMPLEMENTED |
| Grafana dashboard embed | SCAFFOLDED (`NidpGrafanaEmbed.jsx` exists, not wired) |

### 18.13 Requirement Traceability Matrix

| Req ID | Feature | Status | Backend Route | Frontend Component |
|---|---|---|---|---|
| FR-ADM-001 | Secrets | LIVE | routes/admin.py | SecretsSection.jsx |
| FR-ADM-002 | Feature Flags | LIVE | routes/admin.py | FeatureFlagsSection.jsx |
| FR-ADM-003 | Rules Config | LIVE | routes/admin_rules.py | RulesConfigSection.jsx |
| FR-ADM-004 | Custom DSL Rules | LIVE | routes/admin_rules.py | RulesConfigSection.jsx |
| FR-ADM-005 | Prompt Sandbox | LIVE | routes/admin_rules.py | PromptsSection.jsx |
| FR-ADM-006 | Pipeline Monitor | LIVE | routes/admin_data_pipeline.py | DataPipelineMonitor.jsx |
| FR-ADM-007 | V3 MF Weights | LIVE | routes/admin_v3_weights.py | V3WeightsSection.jsx |
| FR-ADM-008 | V3 Stock Weights | LIVE | routes/admin_v3_stock.py | V3StockWeightsSection.jsx |
| FR-ADM-009 | V3 Master Funds | LIVE | routes/admin_v3_master.py | V3MasterFundsSection.jsx |
| FR-ADM-010 | Datastores | LIVE | routes/admin_datastores.py | DatastoreSection.jsx |
| FR-ADM-011 | CAS Config | LIVE | routes/admin.py | CasConfigSection.jsx |
| FR-ADM-012 | User Management | LIVE | routes/admin_users.py | UserManagementSection.jsx |
| FR-ADM-013 | Whitelist | LIVE | routes/admin.py | UserManagementSection.jsx |
| FR-ADM-014 | NIDP Jobs | LIVE | routes/admin_nidp.py | NidpJobsPanel.jsx |
| FR-ADM-015 | NIDP Diagnostics | SCAFFOLDED | routes/admin_nidp.py | NidpDiagnosticsPanel.jsx |
| FR-ADM-016 | NIDP Backfill | LIVE | routes/admin_nidp_backfill.py | NidpBackfillPanel.jsx |
| FR-ADM-017 | NIDP Replay | LIVE | routes/admin_nidp_replay.py | NidpReplayPanel.jsx |
| FR-ADM-018 | NIDP DQ Dashboard | LIVE | routes/admin_nidp.py | NidpQualityDashboard.jsx |
| FR-ADM-019 | Admin Shell | LIVE | — | AdminView.js |

---

## 19. URL Directory, Kafka Topics, Sentry & Credentials

### 19.1 Production URLs

#### Nivesh Application (`nivesh-app-vm`, 34.47.250.214)

| Service | URL | Notes |
|---|---|---|
| **Production app root** | https://niveshcopilot.com | Nginx TLS |
| **V2 React frontend** | https://niveshcopilot.com/v2/ | Main UI |
| **V5 React frontend** | https://niveshcopilot.com/v5/ | New design (staging only for now) |
| **Backend API** | https://niveshcopilot.com/api/ | FastAPI |
| **API health** | https://niveshcopilot.com/api/health | `{"status":"ok"}` |
| **API docs (Swagger)** | https://niveshcopilot.com/api/docs | Dev/internal only |
| **Admin console** | https://niveshcopilot.com/v2/ (admin tab) | Visible only to `is_admin=true` users |
| **Dev auth cookie** | https://niveshcopilot.com/api/auth/dev-set-cookie?token=... | Headless / script auth |
| **nip.io domain** | http://34.47.250.214.nip.io/ | Fallback / internal |

#### NIDP Data Platform (`nidp-stack-vm`, 34.93.60.254)

| Service | URL | Notes |
|---|---|---|
| **DaaS API root** | https://data.niveshcopilot.com/daas/ | Public; API key required |
| **DaaS health** | https://data.niveshcopilot.com/daas/health | No auth |
| **DaaS Swagger** | https://data.niveshcopilot.com/daas/docs | Dev/internal |
| **Query API root** | https://data.niveshcopilot.com/query/ | Internal; Bearer token |
| **Query API health** | https://data.niveshcopilot.com/query/health | No auth |
| **Grafana** | https://data.niveshcopilot.com/grafana/ | `admin` / `admin` |
| **Grafana — Job Health** | https://data.niveshcopilot.com/grafana/d/nidp-job-health/nidp-job-health | NIDP feed status |
| **nip.io domain** | http://34.93.60.254.nip.io:8083 | DaaS fallback |
| **Prometheus** | http://34.93.60.254:9090 | Loopback-only on VM |
| **MinIO console** | http://34.93.60.254:9001 | Parquet archive (VM-internal) |

### 19.2 Staging URLs

#### Nivesh Staging (`nivesh-app-vm`, same VM — isolated stack at `/opt/nivesh-staging/`)

| Service | URL | Notes |
|---|---|---|
| **Staging app** | https://staging.niveshcopilot.com | TLS via shared Cloudflare cert |
| **Staging API** | https://staging.niveshcopilot.com/api/ | FastAPI (staging env) |
| **Staging health** | https://staging.niveshcopilot.com/api/healthz | |
| **Internal TLS port** | https://staging.niveshcopilot.com:8443 | Before Cloudflare proxy |
| **Preview (V5)** | https://nidp-backfill-ui.preview.emergentagent.com | Frontend-v5 preview deployment |

**Staging DB ports (loopback-only on VM):**

| Service | Port |
|---|---|
| PostgreSQL (staging) | `127.0.0.1:5532` |
| MongoDB (staging) | `127.0.0.1:27117` |
| Redis (staging) | `127.0.0.1:6479` |

#### NIDP Staging (`nidp-stack-vm`, isolated TimescaleDB at port 5434)

| Service | Port / URL |
|---|---|
| TimescaleDB (staging) | `127.0.0.1:5434` |
| Query API (staging) | `https://staging-data.niveshcopilot.com` (Cloudflare CNAME — not yet live) |
| Crontab | `/etc/cron.d/nidp-staging` (all entries commented out by default) |
| Code repo | `/opt/nidp/dev-repo/` (same host as prod `/opt/nidp/repo/`) |
| DB name | `nidp_staging` (separate from `nidp` prod) |

### 19.3 Local Development URLs

| Service | URL / Port |
|---|---|
| Backend API | http://localhost:8001 |
| Frontend (React V2) | http://localhost:3000 |
| NIDP DaaS API (local) | http://localhost:8083 |
| NIDP Query API (local) | http://localhost:8090 |
| MongoDB | localhost:27017 |
| PostgreSQL (app) | localhost:5432 |
| PostgreSQL (NIDP) | localhost:5433 |
| Redis | localhost:6379 |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 (NIDP dev stack) |
| MinIO | http://localhost:9000 (API) / http://localhost:9001 (console) |
| Schema Registry | http://localhost:8081 |
| Redpanda | localhost:9092 |
| Loki | http://localhost:3100 |

### 19.4 GCP Console Links

| Resource | URL |
|---|---|
| Cloud Logging | https://console.cloud.google.com/logs/query?project=niveshdataintelligence |
| Cloud Monitoring | https://console.cloud.google.com/monitoring/dashboards?project=niveshdataintelligence |
| Cloud Run Jobs | https://console.cloud.google.com/run/jobs?project=niveshdataintelligence |
| Cloud Run Services | https://console.cloud.google.com/run?project=niveshdataintelligence |
| Cloud Build History | https://console.cloud.google.com/cloud-build/builds?project=niveshdataintelligence |
| GCE VM Instances | https://console.cloud.google.com/compute/instances?project=niveshdataintelligence |
| Cloud Scheduler | https://console.cloud.google.com/cloudscheduler?project=niveshdataintelligence |
| Artifact Registry | https://console.cloud.google.com/artifacts?project=niveshdataintelligence |
| Secret Manager | https://console.cloud.google.com/security/secret-manager?project=niveshdataintelligence |
| IAM & Admin | https://console.cloud.google.com/iam-admin?project=niveshdataintelligence |
| VPC Networks | https://console.cloud.google.com/networking/networks?project=niveshdataintelligence |

### 19.5 Redpanda / Kafka Topics

**Broker:** `localhost:9092` (on `nidp-stack-vm`) / Cloud Run → `NIDP_KAFKA_BROKERS` env var  
**Schema Registry:** `localhost:8081` / `NIDP_SCHEMA_REGISTRY_URL` env var  
**Event bus mode:** `NIDP_EVENT_BUS=local` (prod default — events go to stdout/Cloud Logging, not Kafka; Kafka mode is `kafka` when Redpanda is healthy)

**Ingester Output Topics (all `v1` schema version):**

| Topic | Ingester | DB Table |
|---|---|---|
| `nidp.bhavcopy.v1` | bhavcopy | `nidp.prices_eod` |
| `nidp.delivery.v1` | delivery | `nidp.delivery_data` |
| `nidp.index_close.v1` | index_close | `nidp.index_eod` |
| `nidp.index_constituents.v1` | index_constituents | `nidp.index_constituents` |
| `nidp.fii_dii.v1` | fii_dii | `nidp.fii_dii_flows` |
| `nidp.corporate_actions.v1` | corporate_actions | `nidp.corporate_actions` |
| `nidp.bulk_deals.v1` | bulk_deals | `nidp.bulk_deals` |
| `nidp.block_deals.v1` | block_deals | `nidp.block_deals` |
| `nidp.nse_calendar.v1` | nse_calendar | `nidp.nse_holidays` |
| `nidp.rbi_yields.v1` | rbi_yields | `nidp.rbi_yields` |
| `nidp.fno_bhavcopy.v1` | fno_bhavcopy | `nidp.fno_bhavcopy` |
| `nidp.shareholding_pattern.v1` | nse_shareholding | `nidp.shareholding_pattern` |
| `nidp.nse_financials.v1` | nse_financials | `nidp.nse_financials_quarterly` |
| `nidp.mf_nav_daily.v1` | amfi_nav | `nidp.mf_nav_daily` |
| `nidp.mf_scheme_master.v1` | amfi_nav (scheme metadata) | `nidp.mf_scheme_master` |
| `nidp.mf_amfi_circulars.v1` | amfi_circulars | `nidp.amfi_circulars` |
| `nidp.sector_master.v1` | nse_equity_master | `ref.sector_master` |
| `nidp.corporate_announcements.v1` | corp_announcements_nse/bse | `nidp.corporate_announcements` |

**System Topics:**

| Topic | Purpose |
|---|---|
| `nidp.ingestion_completed.v1` | Published by every ingester on success (orchestration signal) |
| `dq.quarantine.<feed>` | Gate 1 DLQ — messages blocked before main topic publish |
| `dq.dlq.<feed>` | Gate 2 DLQ — messages that failed TimescaleDB write |

**Kafka Client Config (production, from `ingester_base.py`):**
```
brokers:        NIDP_KAFKA_BROKERS env var (default localhost:9092)
client.id:      NIDP_KAFKA_CLIENT_ID env var (default "nidp-producer")
schema_registry: NIDP_SCHEMA_REGISTRY_URL env var (default http://localhost:8081)
flush timeout:  10 seconds
```

### 19.6 Sentry Configuration

Sentry is configured as a **Grafana datasource** (plugin `grafana-sentry-datasource`) for error monitoring dashboards. It is NOT yet instrumented as an SDK in the Python/React applications — error capture flows through Cloud Logging and Loki, with Sentry integrated for frontend error panels in Grafana.

**Grafana datasource config** (`/deploy/grafana/provisioning/datasources/sentry.yml`):

| Field | Value |
|---|---|
| Datasource name | `Sentry` |
| Plugin | `grafana-sentry-datasource` |
| Datasource UID | `sentry` |
| API URL | `${SENTRY_URL:-https://sentry.io}` |
| Organisation slug | `${SENTRY_ORG}` (set in Grafana container env) |
| Project slug | `${SENTRY_PROJECT:-nivesh-copilot}` |
| Auth token | `${SENTRY_AUTH_TOKEN}` (set in Grafana container env) |

**Grafana dashboards using Sentry:**

| Dashboard | File |
|---|---|
| Frontend errors (staging) | `grafana/provisioning/dashboards/nidp/frontend-errors-staging.json` |
| Frontend errors (prod) | `grafana/provisioning/dashboards/nidp/frontend-errors-prod.json` |

**To configure:** Set these environment variables in the Grafana Docker container (or `/opt/nidp/nidp.env` which is sourced into the compose stack):
```bash
SENTRY_ORG=<your-sentry-org-slug>
SENTRY_PROJECT=nivesh-copilot
SENTRY_URL=https://sentry.io          # or self-hosted URL
SENTRY_AUTH_TOKEN=<sentry-auth-token>
```

### 19.7 Credentials & Access Reference

> **Security note:** Credentials below are structured references to WHERE credentials live, not the actual values. Actual secrets are stored in GCP Secret Manager, MongoDB `system_config.secrets`, or VM env files — never in code or docs.

#### Nivesh Application

| Credential | Location | Rotation |
|---|---|---|
| MongoDB root password | `/opt/nivesh/.env.prod` → `MONGO_ROOT_PASSWORD` | On compromise |
| PostgreSQL password | `/opt/nivesh/.env.prod` → `POSTGRES_PASSWORD` | On compromise |
| Redis password | `/opt/nivesh/.env.prod` → `REDIS_PASSWORD` | On compromise |
| Google OAuth client secret | MongoDB `system_config.secrets.GOOGLE_CLIENT_SECRET` | On dev-account turnover |
| OpenAI API key | MongoDB `system_config.secrets.EMERGENT_LLM_KEY` | Quarterly |
| CAS parser API keys | MongoDB `system_config.secrets.CASPARSER_API_KEY` (pool) | When provider rotates |
| Screener.in session cookie | `/opt/nidp/nidp.env` → `SCREENER_SESSION_COOKIE` | Every 30–90 days |
| Admin session tokens | Created at login; stored in MongoDB `user_sessions` | 30-day expiry |

#### NIDP Platform

| Credential | Location | Rotation |
|---|---|---|
| NIDP Postgres URL | GCP Secret Manager `NIDP_POSTGRES_URL` | Via `rotate_credentials.sh` |
| NIDP Postgres (VM) | `/opt/nidp/nidp.env` → `NIDP_POSTGRES_URL` | Manually |
| NIDP Staging Postgres | `/opt/nidp-staging/nidp.env` | Manually |
| DaaS internal token | GCP Secret Manager `NIDP_DAAS_INTERNAL_TOKEN` | Quarterly |
| Kafka brokers | GCP Secret Manager `NIDP_KAFKA_BROKERS` | When Redpanda reconfigured |
| Redis URL | GCP Secret Manager `NIDP_REDIS_URL` | On rotation |
| TLS cert | GCP Secret Manager `nidp-tls-cert` | When Cloudflare Origin Cert reissued |
| TLS key | GCP Secret Manager `nidp-tls-key` | When Cloudflare Origin Cert reissued |
| FRED API key | `/opt/nidp/nidp.env` → `FRED_API_KEY` (optional) | On expiry |
| Claude API key | `/opt/nidp/nidp.env` → `CLAUDE_API_KEY` | Quarterly |
| Telegram bot token | `/opt/nidp/nidp.env` → `NIDP_TELEGRAM_BOT_TOKEN` | On compromise |

#### GCP Access

| Credential | How to Access | Notes |
|---|---|---|
| GCP owner account | `gcloud auth login aporwal107@gmail.com` | All IAM changes |
| GCP OAuth access token | `gcloud auth print-access-token > /app/.gcp-token` | Expires in 1 hour |
| Runtime SA key | `gcloud secrets versions access latest --secret=<KEY>` | Via nidp-sa impersonation |
| SSH to nivesh-app-vm | `ssh -i ~/.ssh/nivesh_vm aporwal107_gmail_com@34.47.250.214` | Ed25519 key |
| SSH to nidp-stack-vm | `ssh aporwal107_gmail_com@34.93.60.254` | OS Login |
| SSH CI/CD user | `ssh devops@<vm-ip>` | Ed25519, `~/.ssh/nivesh_devops_ci` |
| Jenkins SSH creds | Jenkins → Credentials → `nivesh-app-vm-ssh`, `nidp-stack-vm-ssh` | Stored in Jenkins |

#### Console & Dashboard Access

| Console | URL | Credentials |
|---|---|---|
| Grafana (NIDP) | https://data.niveshcopilot.com/grafana/ | `admin` / `admin` |
| Grafana (local dev) | http://localhost:3000 | `admin` / `admin` |
| Prometheus | http://localhost:9090 (or VM loopback) | No auth (loopback-only) |
| MinIO console | http://localhost:9001 | Set in docker-compose env |
| GCP Console | https://console.cloud.google.com | GCP account (`aporwal107@gmail.com`) |
| Admin Console (Nivesh) | https://niveshcopilot.com/v2/ → Admin tab | User must have `is_admin=true` in MongoDB |
| NIDP Console (Admin tab) | https://niveshcopilot.com/v2/ → Admin → NIDP Jobs | Same admin user |

#### Headless / Script Auth

To authenticate as an admin user for scripting or testing without a browser:

```bash
# Get admin token from MongoDB (replace with actual session_id)
curl -s "https://niveshcopilot.com/api/auth/dev-set-cookie?token=<SESSION_TOKEN>" \
  -c cookies.txt

# Use cookie for subsequent requests
curl -b cookies.txt "https://niveshcopilot.com/api/admin/nidp/jobs"
```

### 19.8 Environment Variable Reference

#### NIDP VM (`/opt/nidp/nidp.env`)

```bash
# Database
NIDP_PG_USER=nidp
NIDP_PG_PASSWORD=<set on VM>
NIDP_PG_DB=nidp
NIDP_POSTGRES_URL=postgresql://nidp:<pw>@localhost:5433/nidp
NIVESH_POSTGRES_URL=postgresql://<user>:<pw>@localhost:5432/<db>

# Event bus (local = stdout, kafka = Redpanda)
NIDP_EVENT_BUS=local

# Kafka (only used when NIDP_EVENT_BUS=kafka)
NIDP_KAFKA_BROKERS=localhost:9092
NIDP_KAFKA_CLIENT_ID=nidp-producer
NIDP_SCHEMA_REGISTRY_URL=http://localhost:8081

# Optional API keys
FRED_API_KEY=
CLAUDE_API_KEY=
SCREENER_SESSION_COOKIE=

# Alerts
NIDP_TELEGRAM_BOT_TOKEN=
NIDP_TELEGRAM_CHAT_ID=

# Runtime
PYTHONUNBUFFERED=1
TZ=Asia/Kolkata
```

#### NIDP Cloud Run (from GCP Secret Manager)

```bash
NIDP_POSTGRES_URL        # TimescaleDB on nidp-stack-vm (via VPC)
NIDP_KAFKA_BROKERS       # Redpanda on nidp-stack-vm (via VPC)
NIDP_REDIS_URL           # Redis on nidp-stack-vm (via VPC)
NIDP_SCHEMA_REGISTRY_URL # Schema Registry on nidp-stack-vm (via VPC)
NIDP_EVENT_BUS=local     # Hardcoded in Cloud Run env (bypass Kafka)
NIDP_STORAGE_BACKEND=gcs # Use GCS for raw archive
GCP_PROJECT=niveshdataintelligence
GCP_REGION=asia-south1
```

#### Nivesh Backend (`/opt/nivesh/.env.prod`)

```bash
# MongoDB
MONGO_ROOT_USER=<set>
MONGO_ROOT_PASSWORD=<set>
MONGO_DB=<set>

# PostgreSQL
POSTGRES_USER=<set>
POSTGRES_PASSWORD=<set>
POSTGRES_DB=<set>
POSTGRES_URL=postgresql://<user>:<pw>@localhost:5432/<db>

# Redis
REDIS_PASSWORD=<set>
REDIS_URL=redis://:$REDIS_PASSWORD@localhost:6379

# App
NIDP_API_BASE_URL=https://data.niveshcopilot.com/daas
NIDP_API_KEY=nvd_<internal key>
OPENAI_API_KEY=<set>
```

---

*All information in this document is sourced directly from the codebase, deployment scripts, and configuration files. No information is assumed or inferred. Last validated: 2026-05-29.*
