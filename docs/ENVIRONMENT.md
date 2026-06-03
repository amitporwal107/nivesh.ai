# Environment & Infrastructure Reference

> **Purpose:** Single source of truth for all running services, how they are built, and how they are deployed. Intended to be translated into an ops dashboard page.

---

## 1. Infrastructure Overview

| Item | Value |
|---|---|
| Cloud Provider | GCP (Google Cloud Platform) |
| Project | `niveshdataintelligence` |
| Region / Zone | `asia-south1` / `asia-south1-a` |
| VMs | 2 (see below) |
| Container runtime | Docker Compose (all services) |
| CI/CD | GCP Cloud Build (NIDP services) + manual redeploy scripts (Nivesh app) |
| DNS / CDN | Cloudflare |
| Logging | GCP Cloud Logging (Ops Agent) + Loki + Grafana |
| Monitoring | Prometheus + Grafana (`https://data.niveshcopilot.com/grafana`) |

---

## 2. Virtual Machines

| VM | External IP | Purpose | SSH User |
|---|---|---|---|
| `nivesh-app-vm` | `34.47.250.214` | Nivesh application stack (prod + staging) | `aporwal107_gmail_com` |
| `nidp-stack-vm` | `34.93.60.254` | NIDP data platform + infra observability stack | `aporwal107_gmail_com` |

---

## 3. Container Inventory

### 3.1 `nivesh-app-vm` — Production

| Container | Image | Role | Port (internal) |
|---|---|---|---|
| `nivesh-mongo` | `mongo:7` | Primary MongoDB | 27017 |
| `nivesh-postgres` | `postgres:16-alpine` | Primary PostgreSQL | 127.0.0.1:5432 |
| `nivesh-redis` | `redis:7-alpine` | Cache / sessions | 6379 |
| `nivesh-backend` | `nivesh/backend:prod` | FastAPI application server | 8001 |
| `nivesh-frontend` | `nivesh/frontend:prod` | Nginx serving React V2 + V5 + reverse proxy | 80, 443 |

**Compose file:** `/opt/nivesh/deploy/docker-compose.prod.yml`
**Env file:** `/opt/nivesh/.env.prod`
**Networks:** `nivesh-prod` (internal), `nidp-bridge` (cross-VM, reaches nidp-postgres)

---

### 3.2 `nivesh-app-vm` — Staging

| Container | Image | Role | Port (host-bound) |
|---|---|---|---|
| `nivesh-staging-postgres` | `postgres:16-alpine` | Staging PostgreSQL | 127.0.0.1:5532 |
| `nivesh-staging-mongo` | `mongo:7` | Staging MongoDB | 127.0.0.1:27117 |
| `nivesh-staging-redis` | `redis:7-alpine` | Staging cache | 127.0.0.1:6479 |
| `nivesh-staging-app-backend` | `nivesh/backend:staging` | FastAPI staging server | 8001 (internal) |
| `nivesh-staging-app-frontend` | `nivesh/frontend:staging` | React V2 static (staging) | internal only |
| `nivesh-staging-app-frontend-v5` | `nivesh/frontend-v5:staging` | Vite/React V5 static (staging) | internal only |
| `nivesh-staging-nginx` | `nginx:1.27-alpine` | Edge proxy / TLS termination | 127.0.0.1:8443 |

**Compose file:** `/opt/nivesh-staging/repo/deploy/nivesh-staging/docker-compose.staging.yml`
**Env file:** `/opt/nivesh-staging/.env.staging`
**Network:** `nivesh-staging` (isolated)
**Staging URL:** `https://staging.niveshcopilot.com`

---

### 3.3 `nidp-stack-vm` — NIDP Data Platform

| Container | Image | Role | Port (host-bound) |
|---|---|---|---|
| `nidp-postgres` | `timescale/timescaledb:latest-pg16` | TimescaleDB (prod, 55 migrations) | 127.0.0.1:5433 |
| `nidp-postgres-staging` | `timescale/timescaledb:latest-pg16` | TimescaleDB (staging) | 127.0.0.1:5434 |
| `nidp-daas-api-staging` | `python:3.11-slim` | DaaS REST API (staging, uvicorn) | 127.0.0.1:8084 |

**Prod compose:** `/opt/nidp/repo/backend/nidp/deploy/vm/docker-compose.prod.yml`
**Staging compose:** `/opt/nidp/repo/backend/nidp/deploy/vm/docker-compose.staging.yml`
**Env files:** `/opt/nidp/nidp.env` (prod), `/opt/nidp-staging/nidp.env` (staging)
**Network:** `nidp-default` + `nidp-bridge` (prod); `nidp-staging-default` + `nidp-staging-bridge` (staging)

> **Note:** The prod DaaS API runs as a **systemd service** (`nidp-daas-api`), not a Docker container. Restart: `sudo systemctl restart nidp-daas-api`

---

### 3.4 `nidp-stack-vm` — Observability / Infra Stack

| Container | Image | Role | Port (host-bound) |
|---|---|---|---|
| `nidp-grafana` | `grafana/grafana:latest` | Dashboards UI | 3000 → nginx `/grafana` |
| `nidp-prometheus` | `prom/prometheus:latest` | Metrics scraper + alerting | 9090 |
| `nidp-loki` | `grafana/loki:3.0.0` | Log aggregation | 3100 |
| `nidp-promtail` | `grafana/promtail:3.0.0` | Log shipper (Docker → Loki) | — |
| `nidp-minio` | `minio/minio:latest` | Object store (raw archive backups) | 9000 |
| `nidp-redpanda` | `redpandadata/redpanda:latest` | Kafka-compatible event broker | 9092 (host), 29092 (internal) |

**Compose file:** `/opt/nidp/repo/backend/nidp/deploy/docker-compose.dev.yml`
**Grafana URL:** `https://data.niveshcopilot.com/grafana` (admin / admin)

---

### 3.5 Non-Docker Services (`nidp-stack-vm`)

| Service | Type | Command | Role |
|---|---|---|---|
| `nidp-query-api` | systemd | `systemctl restart nidp-query-api` | Internal query API (port 8090) |
| `nidp-daas-api` | systemd | `systemctl restart nidp-daas-api` | Prod DaaS API (port 8010) |
| NIDP cron ingesters | cron | `/etc/cron.d/nidp` | 13 data feed ingesters (NSE, BSE, MF, etc.) |

---

### 3.6 Cloud-Hosted (no container)

| Service | Provider | Notes |
|---|---|---|
| Sentry | sentry.io | Error tracking; configured via `SENTRY_URL` env + Grafana datasource |
| GCP Cloud Logging | GCP | Ops Agent installed on both VMs; streams container logs |
| Cloudflare | Cloudflare | DNS + CDN + TLS for `niveshcopilot.com` and `data.niveshcopilot.com` |

---

## 4. URLs

| Environment | URL | Notes |
|---|---|---|
| Prod app | `https://niveshcopilot.com` | V1 landing + V2 `/v2` + V5 `/v5` |
| Staging app | `https://staging.niveshcopilot.com` | Port 8443 internally |
| NIDP DaaS (prod) | `https://data.niveshcopilot.com/daas` | nginx proxy → port 8010 |
| NIDP DaaS (staging) | `https://staging-data.niveshcopilot.com/daas` | nginx proxy → port 8084 |
| Grafana | `https://data.niveshcopilot.com/grafana` | admin / admin |
| Dev auth cookie | `/api/auth/dev-set-cookie?token=…` | Headless login for testing |

---

## 5. Build System

### Nivesh App (nivesh-app-vm)

Images are built **on the VM** during redeploy — no registry push.

| Image | Builder | Trigger | Notes |
|---|---|---|---|
| `nivesh/backend:prod` | `docker build` on VM | `requirements.txt` hash change or image missing | Python 3.11-slim + uv; code mounted as volume at runtime |
| `nivesh/frontend:prod` | `docker build` on VM | `frontend/src` hash change or image missing | Node 20 → craco build → nginx:1.25-alpine; bakes `REACT_APP_BACKEND_URL` + `PUBLIC_URL=/v2` |
| `nivesh/frontend-v5:prod` | `docker build` on VM | Explicit rebuild | Node 20 → vite build → nginx:1.27-alpine; bakes `VITE_BASE` + `VITE_API_URL` |
| `nivesh/backend:staging` | `docker build` on VM | `redeploy-staging.sh` | Same Dockerfile as prod |
| `nivesh/frontend:staging` | `docker build` on VM | `redeploy-staging.sh` | Bakes staging URL |
| `nivesh/frontend-v5:staging` | `docker build` on VM | `redeploy-staging.sh` | Bakes `VITE_BASE=/v5/` + staging API URL |

### NIDP Services (Cloud Build → Cloud Run Jobs)

| Service | Trigger | Builder | Registry | Deploy target |
|---|---|---|---|---|
| NIDP ingesters (13 services) | Push to `nidp` branch (file-path filter per service) | Kaniko + layer cache (720h TTL) | `asia-south1-docker.pkg.dev/niveshdataintelligence/nidp/<service>` | Cloud Run Job |
| DaaS API | Push to `nidp` branch (`daas_api/**` changed) | `docker build` via Cloud Build | Same registry | Cloud Run Service |
| DB migrations | Manual (`cloudbuild-migrations.yaml`) | Cloud Build | — | Runs against prod TimescaleDB |

---

## 6. Deployment Workflows

### 6.1 Nivesh App — Production Deploy

```
Local machine / Emergent pod
  └─ bash deploy/nivesh-app/redeploy.sh
       1. git fetch + reset --hard origin/main on VM
       2. Sync deploy/ files (Dockerfiles, nginx.conf, compose) to /opt/nivesh/deploy/
       3. Resolve external IP (baked into frontend bundle)
       4. docker build nivesh/backend:prod     (skip if requirements.txt unchanged)
       5. docker build nivesh/frontend:prod    (skip if frontend/src unchanged)
       6. docker rm nivesh-backend / nivesh-frontend
       7. docker compose up -d backend frontend
       8. Health check: GET /api/health → 200
```

**Env file:** `/opt/nivesh/.env.prod` (never touched by deploy — managed manually)
**Code path:** repo at `/opt/nivesh/repo` (branch: `main`)

---

### 6.2 Nivesh App — Staging Deploy

```
Local machine
  └─ bash deploy/nivesh-staging/deploy.sh
       1. git add <explicit paths> → commit on STAGING_BRANCH → push to GitHub
       2. SSH to VM → git clone/fetch STAGING_BRANCH → /opt/nivesh-staging/repo
       3. sudo bash bootstrap-staging.sh    (idempotent one-time setup)
       4. sudo bash redeploy-staging.sh
            a. docker compose build --pull  (all staging images)
            b. docker compose up -d --remove-orphans
            c. Wait for nivesh-staging-app-backend healthy
            d. Reload nivesh-staging-nginx
            e. Smoke: GET https://staging.niveshcopilot.com:8443/api/healthz
```

**Code path:** repo at `/opt/nivesh-staging/repo` (branch: `dev` or feature branch)

---

### 6.3 NIDP Services — Cloud Build CI/CD

```
GitHub push to `nidp` branch
  └─ Cloud Build trigger (file-path filter)
       1. Kaniko build with registry layer cache
       2. Push :BUILD_ID + :latest to Artifact Registry
       3. gcloud run jobs update nidp-<service> --image=...:BUILD_ID
       4. (DaaS only) Smoke: /health → 200, /v1/me → 401
```

**Rollback:** `deploy/gcp/rollback.sh` — re-deploys `:stable` tag (manually promoted via `promote_stable.sh`)

---

### 6.4 NIDP Stack VM — Code Sync (non-Docker services)

```
bash deploy/nidp-vm/redeploy.sh
  1. Register SSH key via OS Login API (1h TTL) using GOOGLE_OAUTH_ACCESS_TOKEN
  2. rsync /app/backend/nidp/ → VM:/opt/nidp/repo/backend/nidp/
  3. sudo systemctl reload cron
  4. sudo systemctl restart nidp-query-api  (if running)
  5. sudo systemctl restart nidp-daas       (if running)
  6. Health check: GET http://34.93.60.254:8010/health
```

---

## 7. Restart Reference (Quick Copy-Paste)

### `nidp-stack-vm`

```bash
# TimescaleDB (prod)
cd /opt/nidp/repo/backend/nidp/deploy
docker compose -f vm/docker-compose.prod.yml --env-file /opt/nidp/nidp.env up -d

# TimescaleDB + DaaS API (staging)
docker compose -f vm/docker-compose.staging.yml --env-file /opt/nidp-staging/nidp.env up -d

# Observability stack (Grafana, Prometheus, Loki, Promtail, MinIO, Redpanda)
docker compose -f /opt/nidp/repo/backend/nidp/deploy/docker-compose.dev.yml up -d

# Non-Docker systemd services
sudo systemctl restart nidp-daas-api
sudo systemctl restart nidp-query-api
```

### `nivesh-app-vm`

```bash
# Production stack (Mongo, Postgres, Redis, Backend, Frontend)
cd /opt/nivesh/deploy
docker compose -f docker-compose.prod.yml --env-file /opt/nivesh/.env.prod up -d

# Staging stack (all staging containers)
cd /opt/nivesh-staging/repo
docker compose -f deploy/nivesh-staging/docker-compose.staging.yml --env-file /opt/nivesh-staging/.env.staging up -d
```

---

## 8. Service Account & Secrets

| Secret | Storage | Consumed by |
|---|---|---|
| `NIDP_POSTGRES_URL` | GCP Secret Manager | Cloud Run (DaaS API) |
| `NIDP_DAAS_INTERNAL_TOKEN` | GCP Secret Manager | Cloud Run (DaaS API) |
| `/opt/nivesh/.env.prod` | VM filesystem (mode 600) | docker-compose.prod.yml |
| `/opt/nivesh-staging/.env.staging` | VM filesystem (mode 600) | docker-compose.staging.yml |
| `/opt/nidp/nidp.env` | VM filesystem (mode 600) | NIDP prod stack |
| `/opt/nidp-staging/nidp.env` | VM filesystem (mode 600) | NIDP staging stack |
| `CASPARSER_API_KEYS` | Admin console → Secrets | CAS parser key pool (hot-reloaded) |

**Service accounts:**
- `nidp-sa@niveshdataintelligence.iam.gserviceaccount.com` — NIDP ingester + DaaS runtime
- `nivesh-devops@niveshdataintelligence.iam.gserviceaccount.com` — Cloud Build CI/CD

---

## 9. Total Container Summary

| VM | Prod containers | Staging containers | Infra containers | Total |
|---|---|---|---|---|
| `nivesh-app-vm` | 5 | 7 | — | 12 |
| `nidp-stack-vm` | 1 | 2 | 6 | 9 |
| **Total** | **6** | **9** | **6** | **21** |

Plus **2 systemd services** on `nidp-stack-vm` (`nidp-daas-api`, `nidp-query-api`) and **13 cron-driven ingesters** running as Cloud Run Jobs.
