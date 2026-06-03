# DEVOPS_ENVIRONMENTS.md — Nivesh.ai / NIDP

> Canonical detail: `TECHNICAL_ARCHITECTURE.md` §3 (Infra/VMs), §11 (Observability), §13
> (Security/IAM), §19 (URLs, Kafka, Sentry, Credentials).
> Honesty rule: list only what exists. **Never write a real secret here or anywhere.**

## Environments
| Env | App URL | Health | Deploy branch | Data | Notes |
|---|---|---|---|---|---|
| local | `localhost:8001` (FE 3000) | `/api/health` | — | seed/fake | full stack on Docker |
| staging | https://staging.niveshcopilot.com | `/api/healthz` | `dev` | prod-like, isolated | same VM, isolated stack `/opt/nivesh-staging/` |
| production | https://niveshcopilot.com | `/api/health` | `main` (PR only) | real | `nivesh-app-vm` 34.47.250.214 |

**NIDP:** prod `https://data.niveshcopilot.com/daas` + `/query` + `/grafana` on
`nidp-stack-vm` 34.93.60.254; staging CNAME `staging-data.niveshcopilot.com` **not yet live**.

**GCP:** project `niveshdataintelligence`, region `asia-south1` (Mumbai), zone `asia-south1-a`.

### Port map
| Service | Local | Staging (loopback) | Prod (internal) |
|---|---|---|---|
| Backend API | 8001 | :8443 (TLS) | 8001 |
| PostgreSQL (app) | 5432 | 5532 | 5432 |
| MongoDB | 27017 | 27117 | 27017 |
| Redis (app) | 6379 | 6479 | 6379 |
| NIDP TimescaleDB | 5433 | 5434 (`nidp_staging`) | 5433 (primary) / 5434 (standby) |
| NIDP DaaS / Query API | 8083 / 8090 | — | 8083 / 8090 |

> **Verification target:** "works" claims about a deploy are checked against **staging**
> (`/api/healthz`) with real output — never asserted from theory; prod verified read-only.

## Configuration & secrets
- **Stores:** GCP Secret Manager (DB URLs, TLS certs, tokens), MongoDB `system_config.secrets`
  (app secrets, hot-reloaded at startup — 30+ keys), VM env files `/opt/nivesh/.env.prod`,
  `/opt/nidp/nidp.env`, `/opt/nidp-staging/nidp.env`.
- **Rules:** never commit `.env`/`.key`/`.pem`; never print secrets; secrets never in code/logs.
  GCP OAuth token (`/app/.gcp-token`) expires in 1h — refresh if >45 min old.
- Key GCP secrets: `NIDP_POSTGRES_URL`, `NIDP_KAFKA_BROKERS`, `NIDP_REDIS_URL`,
  `NIDP_SCHEMA_REGISTRY_URL`, `NIDP_DAAS_INTERNAL_TOKEN`, `nidp-tls-cert`, `nidp-tls-key`.

## Infrastructure
2 GCE VMs (app `e2-standard-4`, NIDP `e2-small`, Debian 12) + 28 Cloud Run jobs + 2 Cloud Run
services + Cloud Build (28+ triggers) + Cloud Scheduler (30+ jobs) + Artifact Registry + GCS
(`nidp-raw-niveshdataintelligence`) + VPC connector `nidp-vpc`. Nginx 1.27 TLS via Cloudflare
Origin Cert. ~$50–66/month.

## Observability
- **Prometheus** (15s scrape) + **Grafana** `https://data.niveshcopilot.com/grafana/`
  (dashboards: Job Health, Infra, DQ Chain, DQ Analytics, Feed Schedule).
- **Loki + Promtail** — 30-day log retention.
- **Cloud Logging** — `severity>=ERROR`, filter by `resource.labels.job_name` / `service_name`.
- **Sentry** — configured as a Grafana datasource only (frontend-error panels); **not yet
  SDK-instrumented** in app code (PLANNED).
- Burn-rate SLO alerts (pager/ticket) for ingester failures, snapshot blocks, replication lag,
  parquet export, DLQ backlog, bhavcopy/NAV staleness.

## Deploy commands

### Staging (from repo root on `nivesh-app-vm` or via SSH)
```bash
# Full staging redeploy (backend + frontend + frontend-v5)
ssh -i ~/.ssh/google_compute_engine aporwal107_gmail_com@34.47.250.214 \
  "cd /opt/nivesh-staging/repo && sudo bash deploy/nivesh-staging/redeploy-staging.sh"

# The script: pulls latest dev branch, recreates Docker Compose services,
# waits for healthy, reloads nginx, runs smoke check → {"status":"ok"}
```

### Production (from repo root on `nivesh-app-vm`)
```bash
bash deploy/nivesh-app/redeploy.sh                  # full
bash deploy/nivesh-app/redeploy.sh --frontend-only  # CSS/JS only
bash deploy/nivesh-app/redeploy.sh --backend-only   # Python, no new deps
```

### NIDP VM
```bash
bash deploy/nidp-vm/redeploy.sh
```

**Rule:** deploy via git push + the redeploy script only. Never `docker cp` or `rsync` files directly into containers.

## Runbooks
SSH, health checks, service restart, manual ingester runs, Cloud Run/Build triggers, DB access:
see `TECHNICAL_ARCHITECTURE.md` §15 (Operations Cheat Sheet).

## Known gaps (PLANNED — treat as live risk)
PAN not AES-256 at rest · no gitleaks in CI · no admin MFA · possible tokens in git history
(rotate) · audit-log viewer / retention sweeps / DPO alerting / SIEM not implemented.
