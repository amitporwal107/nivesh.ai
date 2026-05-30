# PROJECT_CONTEXT.md — Nivesh.ai + NIDP

> **Read this first when starting any task.** Project source-of-truth orientation.
> Different from repo-root `CONTEXT.md` (which defines *how the agent behaves*); this
> defines *facts about this project*.
>
> **Honesty rule:** describe only what is built. Statuses below are from the validated
> architecture doc (2026-05-29). Mark anything unbuilt `PLANNED`/`SCAFFOLDED`. Code and
> migrations are the ultimate truth — if a doc disagrees with the running system, trust
> the system and fix the doc.

---

## 1. Product in one paragraph

Nivesh.ai is an AI-powered wealth-management copilot for **Indian retail investors**
(with an advisor/MFD workspace). It is two independently deployable systems: the
**Nivesh Application** (user-facing copilot, portfolio, plans, goals) and **NIDP** (the
Nivesh Indian Data Platform — an isolated data lake + API platform that ingests 41 Indian
market data feeds and feeds the app market data, portfolio intelligence, and V3 scores).

## 2. The two systems

| System | VM | Public URL | Core stack |
|---|---|---|---|
| Nivesh App | `nivesh-app-vm` (34.47.250.214) | https://niveshcopilot.com | React 19 + FastAPI 3.11 + MongoDB 7 + PostgreSQL 16 + Redis 7 + LangGraph |
| NIDP Data Platform | `nidp-stack-vm` (34.93.60.254) | https://data.niveshcopilot.com | 28 Cloud Run ingesters + DaaS/Query APIs (FastAPI) + TimescaleDB-pg16 + Redpanda + Prometheus/Grafana/Loki + MinIO |

They communicate over the `nidp-bridge` Docker network. GCP project: `niveshdataintelligence`, region `asia-south1` (Mumbai).

## 3. Stack at a glance

| Layer | Technology |
|---|---|
| Frontend | React 19, React Router 7.5, TanStack Query v5 (frontend-v5), Radix UI, Tailwind 3, Vite (v5) / CRA+CRACO (legacy v2), Recharts, react-hook-form + Zod, Capacitor 7 (mobile) |
| Backend | FastAPI 0.110, Python 3.11, Pydantic v2, asyncpg (PG), Motor (Mongo), APScheduler 3.11 |
| AI | OpenAI GPT-4o-mini (primary), LangGraph (agent orchestration, 9 specialist nodes), LiteLLM 1.80, Anthropic Claude (CAS vision + NIDP classifier) |
| Auth | Google OAuth 2.0 (Authlib), session cookie, admin Bearer token |
| Data platform | TimescaleDB (PG16 + timescaledb + pgvector), Redpanda (Kafka-compat), Confluent Schema Registry, Redis 7, MinIO (Parquet WARM) |
| Infra | Docker Compose, Nginx 1.27, Cloudflare (CDN/TLS), GCP Cloud Run / Cloud Build / Cloud Scheduler / Artifact Registry / Secret Manager / Cloud Logging / GCS |
| CI/CD | Jenkins (Nivesh app + NIDP VM services) + GCP Cloud Build (28 ingester jobs + DaaS Cloud Run) |
| Observability | Prometheus + Grafana + Loki/Promtail; Sentry (as Grafana datasource only, not yet SDK-instrumented) |

## 4. Document index (canonical sources)

Read the doc that owns the facts you need before building — don't guess.

| If you need… | Read |
|---|---|
| Full validated system reference (everything) | `docs/TECHNICAL_ARCHITECTURE.md` (the master doc) |
| API conventions + endpoint groups | `docs/API_DOCUMENTATION.md` → full spec: `/api/docs`, `/daas/docs` |
| The 3 databases + migration rules | `docs/DATABASE_SCHEMA.md` |
| Environments, ports, secrets, observability | `docs/DEVOPS_ENVIRONMENTS.md` |
| Build/test/deploy/rollback + verify commands | `docs/BUILD_AND_DEPLOYMENT.md` |
| Why the product exists, users, constraints | `docs/BUSINESS_SPECIFICATION.md` |
| How to spec a feature | `docs/PRD_TEMPLATE.md` |
| Roadmap, sequencing, status, risk | `docs/PROJECT_PLAN.md` |
| Per-role guardrails & Definition of Done | `.claude/roles/*.md` |

## 5. Current status (from validated doc, 2026-05-29)

| Area | Status |
|---|---|
| Nivesh app (portfolio, plans, goals, copilot, admin console) | IMPLEMENTED |
| NIDP ingesters (28), DaaS API, Query API | IMPLEMENTED |
| V3 scoring (MF + stock), analytics, intelligence | IMPLEMENTED |
| V5 frontend (Vite/TanStack) | STAGING ONLY (prod still on V2) |
| Admin console modules FR-ADM-001..019 | Mostly LIVE; NIDP Diagnostics + Grafana embed = SCAFFOLDED |
| NIDP 7-Gate Data Quality system | PARTIAL — Gate 3 tables live (mig 077), Gate 4 LIVE (mig 075); Gates 1/2/5/6/7 = PLANNED (Q3–Q4 2026) |
| `staging-data.niveshcopilot.com` CNAME | NOT YET LIVE |
| Audit-log viewer, data-retention sweeps, DPO alerting, admin MFA, SIEM | NOT IMPLEMENTED |

## 6. Hard constraints (never violate)

- **Branch discipline:** commit to `dev`, never `main`. `main` only via PR merge. Never force-push to `main`. Never `--no-verify`.
- **Deploy via git, never rsync/scp** for *manual operator* deploys. (The Jenkins NIDP path uses rsync — that exception is documented and CI-only.)
- **Migrations are forward-only:** write `IF NOT EXISTS`; `alembic downgrade` only with a PG snapshot taken first.
- **Secrets via GCP Secret Manager / Mongo `system_config.secrets` / VM env files only** — never hardcode in code, never commit `.env`/`.key`/`.pem`, never print in logs.
- **Deploy once:** test (Playwright + build + `make verify`) locally, fix all issues, then deploy a single time.
- **Known security gaps (treat as live risk):** tokens may exist in git history (rotate); PAN not yet AES-256 at rest (PLANNED); no gitleaks in CI (PLANNED); no admin MFA (PLANNED).

## 7. Glossary

- **NIDP** — Nivesh Indian Data Platform (the data lake + API system under `backend/nidp/`).
- **DaaS API** — external, API-key-gated data API (`/daas`, keys prefixed `nvd_`).
- **Query API** — internal feed/ops API (`/query`, Bearer token).
- **V3 scores** — composite Quality / Health / Exit / Add / Portfolio-Fit scores for funds & stocks.
- **Gate 1–7** — the layered Data Quality checkpoints (mostly PLANNED; see PROJECT_PLAN).
- **CAS** — Consolidated Account Statement (parsed via 3-provider fallback: Google Doc AI → Claude Vision → casparser.in).
- **MFD** — Mutual Fund Distributor (advisor workspace).
