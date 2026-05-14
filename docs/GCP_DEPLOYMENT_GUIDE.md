# NIDP — GCP Deployment Guide

**Project:** `niveshdataintelligence`
**Region:** `asia-south1`
**Last updated:** 2026-05-14

This guide covers everything needed to deploy the full NIDP stack from scratch, redeploy after a code change, and manage day-to-day operations.

---

## Live VM Reference

| VM | External IP | nip.io domain | Machine type | Zone |
|---|---|---|---|---|
| `nivesh-app-vm` | `34.100.186.141` | `34.100.186.141.nip.io` | e2-standard-4 | asia-south1-a |
| `nidp-stack-vm` | `34.93.60.254` | `34.93.60.254.nip.io` | e2-standard-4 | asia-south1-a |

### Fully Qualified Service URLs

**`nivesh-app-vm` (Main Application)**

| Service | URL |
|---|---|
| App (root) | `http://34.100.186.141.nip.io/` |
| V2 React Frontend | `http://34.100.186.141.nip.io/v2/` |
| Backend API | `http://34.100.186.141.nip.io/api/` |
| Health check | `http://34.100.186.141.nip.io/health` |
| Grafana (proxied) | `http://34.100.186.141.nip.io/api/admin/nidp/grafana/` |

**`nidp-stack-vm` (NIDP Data Plane)**

| Service | URL |
|---|---|
| DaaS API | `http://34.93.60.254.nip.io:8083` |
| DaaS API docs | `http://34.93.60.254.nip.io:8083/docs` |
| DaaS API health | `http://34.93.60.254.nip.io:8083/health` |
| Query API | `http://34.93.60.254.nip.io:8090` |
| Grafana dashboard | `http://34.93.60.254.nip.io:3000/d/nidp-job-health/nidp-job-health` |

**GCP Console Links**

| Console | URL |
|---|---|
| Logs Explorer | `https://console.cloud.google.com/logs/query?project=niveshdataintelligence` |
| Monitoring Dashboards | `https://console.cloud.google.com/monitoring/dashboards?project=niveshdataintelligence` |
| Cloud Run Services | `https://console.cloud.google.com/run?project=niveshdataintelligence` |
| Cloud Build History | `https://console.cloud.google.com/cloud-build/builds?project=niveshdataintelligence` |
| GCE VM Instances | `https://console.cloud.google.com/compute/instances?project=niveshdataintelligence` |
| Cloud Scheduler | `https://console.cloud.google.com/cloudscheduler?project=niveshdataintelligence` |

**Google OAuth redirect URI** (must be registered in [OAuth Console](https://console.cloud.google.com/apis/credentials?project=niveshdataintelligence)):
```
http://34.100.186.141.nip.io/api/oauth/gmail/callback
```

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Prerequisites](#2-prerequisites)
3. [Service Accounts](#3-service-accounts)
4. [One-Time Bootstrap](#4-one-time-bootstrap)
5. [Secret Manager Setup](#5-secret-manager-setup)
6. [Database & Data Plane (GCE VM)](#6-database--data-plane-gce-vm)
7. [Database Migrations](#7-database-migrations)
8. [Cloud Run Jobs (Ingesters)](#8-cloud-run-jobs-ingesters)
9. [DaaS API (Cloud Run Service)](#9-daas-api-cloud-run-service)
10. [Query API (Internal Service)](#10-query-api-internal-service)
11. [Mutual Fund Feeds](#11-mutual-fund-feeds)
12. [CI/CD with Cloud Build](#12-cicd-with-cloud-build)
13. [Monitoring & Logs](#13-monitoring--logs)
14. [Rollback Procedures](#14-rollback-procedures)
15. [Token Management](#15-token-management)
16. [Maintenance Operations](#16-maintenance-operations)
17. [Cost Reference](#17-cost-reference)
18. [Troubleshooting](#18-troubleshooting)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        GCP Project: niveshdataintelligence       │
│                                                                   │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐   │
│  │  Cloud Run   │    │  Cloud Run   │    │  Cloud Run Jobs  │   │
│  │  nidp-daas-  │    │  nidp-query- │    │  (11 ingesters)  │   │
│  │  api         │    │  api         │    │  nse-eod,amfi-   │   │
│  │  (public)    │    │  (internal)  │    │  nav, mf-holdings│   │
│  └──────┬───────┘    └──────┬───────┘    └────────┬─────────┘   │
│         │                  │                      │              │
│         └──────────────────┴──────────────────────┘             │
│                            │ (Serverless VPC connector)          │
│                    ┌───────▼───────┐                             │
│                    │  GCE VM       │                             │
│                    │  nidp-stack-vm│                             │
│                    │  ┌──────────┐ │   ┌──────────────────────┐ │
│                    │  │Postgres  │ │   │  Artifact Registry   │ │
│                    │  │+Timescale│ │   │  asia-south1-docker  │ │
│                    │  ├──────────┤ │   │  .pkg.dev/.../nidp   │ │
│                    │  │Redpanda  │ │   └──────────────────────┘ │
│                    │  │(Kafka)   │ │                             │
│                    │  ├──────────┤ │   ┌──────────────────────┐ │
│                    │  │Redis     │ │   │  Secret Manager      │ │
│                    │  └──────────┘ │   │  NIDP_POSTGRES_URL   │ │
│                    └───────────────┘   │  NIDP_KAFKA_BROKERS  │ │
│                                        │  NIDP_DAAS_*         │ │
│                                        └──────────────────────┘ │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  Cloud Scheduler → Cloud Run Jobs (daily cron triggers)     │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

**Key design decisions:**
- All persistent state lives on the GCE VM (Postgres/TimescaleDB). Cloud Run is stateless.
- Services connect to the VM via Serverless VPC connector (private IP — never public Postgres).
- The DaaS API is the only public-facing service; all others are internal.
- Secrets are stored in Secret Manager and injected at Cloud Run startup — never baked into images.

---

## 2. Prerequisites

### Tools (install on your machine)

```bash
# Google Cloud SDK
curl https://sdk.cloud.google.com | bash
gcloud components update
gcloud components install beta

# Docker (for local image builds, optional)
# macOS: https://docs.docker.com/desktop/mac/install/
# Linux: sudo apt-get install docker.io

# Python 3.11+ (for migration CLI)
python3 --version
```

### Authentication

```bash
# Login with your Google account (must have Owner or Editor on the project)
gcloud auth login

# Set default project
gcloud config set project niveshdataintelligence

# Application Default Credentials (needed for Python SDK calls)
gcloud auth application-default login
```

### Verify access

```bash
gcloud projects describe niveshdataintelligence
# Should print project info without errors
```

---

## 3. Service Accounts

NIDP uses two service accounts with separate responsibilities.

### 3a. `nidp-sa` — Runtime (Cloud Run)

**Email:** `nidp-sa@niveshdataintelligence.iam.gserviceaccount.com`

This SA is attached to every Cloud Run Service and Job. It has the minimum permissions to run:
- Read secrets from Secret Manager
- Pull images from Artifact Registry
- Write logs

**Create / verify:**
```bash
./backend/nidp/deploy/gcp/setup_credentials.sh \
    --project=niveshdataintelligence \
    --confirm
```

### 3b. `nivesh-devops` — CI/CD (Cloud Build + deployments)

**Email:** `nivesh-devops@niveshdataintelligence.iam.gserviceaccount.com`

Used by the agent and by Cloud Build pipelines to build images, push to AR, deploy Cloud Run.

**Create (run once as project Owner):**
```bash
# Pull latest script
git pull origin nidp

# Dry-run first — prints every command without executing
./backend/nidp/deploy/gcp/setup_devops_sa.sh \
    --project=niveshdataintelligence

# Apply for real
./backend/nidp/deploy/gcp/setup_devops_sa.sh \
    --project=niveshdataintelligence \
    --confirm
```

**Create a JSON key for the agent:**
```bash
gcloud iam service-accounts keys create /secure/path/nivesh-devops-key.json \
    --iam-account=nivesh-devops@niveshdataintelligence.iam.gserviceaccount.com \
    --project=niveshdataintelligence
```

> ⚠️ Never commit the JSON key file. Store it outside the repo.

---

## 4. One-Time Bootstrap

Run once per project. Creates APIs, GCS bucket, Artifact Registry, GCE VM.

```bash
export GCP_PROJECT=niveshdataintelligence
export GCP_REGION=asia-south1

# Dry-run first
./backend/nidp/deploy/gcp/bootstrap.sh

# Apply
./backend/nidp/deploy/gcp/bootstrap.sh --confirm
```

What this creates (logged to `gcp_resources.jsonl`):
- Enables APIs: Cloud Run, Cloud Build, Artifact Registry, Secret Manager, VPC Access
- Creates GCS bucket `nidp-raw-niveshdataintelligence` for raw data archive
- Creates Artifact Registry repo `nidp` in `asia-south1`
- Creates GCE VM `nidp-stack-vm` (e2-standard-2, 50GB SSD, asia-south1-a)
- Creates Secret Manager secrets (empty placeholders — fill in Step 5)
- Creates Serverless VPC connector `nidp-vpc`

---

## 5. Secret Manager Setup

After bootstrap creates the secret placeholders, fill in the real values:

```bash
PROJECT=niveshdataintelligence
VM_IP=$(gcloud compute instances describe nidp-stack-vm \
    --zone=asia-south1-a --project=$PROJECT \
    --format="value(networkInterfaces[0].networkIP)")

# PostgreSQL connection (TimescaleDB on the GCE VM)
echo -n "postgres://nidp:CHANGEME@${VM_IP}:5432/nidp" | \
    gcloud secrets versions add NIDP_POSTGRES_URL \
    --data-file=- --project=$PROJECT

# Kafka / Redpanda
echo -n "${VM_IP}:9092" | \
    gcloud secrets versions add NIDP_KAFKA_BROKERS \
    --data-file=- --project=$PROJECT

# Redis
echo -n "redis://${VM_IP}:6380/0" | \
    gcloud secrets versions add NIDP_REDIS_URL \
    --data-file=- --project=$PROJECT

# Schema Registry
echo -n "http://${VM_IP}:8081" | \
    gcloud secrets versions add NIDP_SCHEMA_REGISTRY_URL \
    --data-file=- --project=$PROJECT

# DaaS internal token (optional — for service-to-service calls)
openssl rand -hex 32 | \
    gcloud secrets versions add NIDP_DAAS_INTERNAL_TOKEN \
    --data-file=- --project=$PROJECT
```

**Verify:**
```bash
gcloud secrets versions access latest \
    --secret=NIDP_POSTGRES_URL \
    --project=$PROJECT
# Should print the connection string
```

---

## 6. Database & Data Plane (GCE VM)

The GCE VM runs Postgres/TimescaleDB, Redpanda, and Redis via Docker Compose.

### Start the data plane

```bash
VM_ZONE=asia-south1-a

# Copy docker-compose config to the VM
gcloud compute scp backend/nidp/docker-compose.dev.yml \
    nidp-stack-vm:/opt/nidp/docker-compose.yml \
    --zone=$VM_ZONE --project=$PROJECT

# SSH in and start services
gcloud compute ssh nidp-stack-vm --zone=$VM_ZONE --project=$PROJECT --command='
    sudo apt-get update -q && sudo apt-get install -y docker.io docker-compose-plugin
    sudo mkdir -p /opt/nidp
    sudo docker compose -f /opt/nidp/docker-compose.yml up -d
    sudo docker compose -f /opt/nidp/docker-compose.yml ps
'
```

### Verify

```bash
gcloud compute ssh nidp-stack-vm --zone=$VM_ZONE --project=$PROJECT --command='
    sudo docker compose -f /opt/nidp/docker-compose.yml ps
    # All services should show "running"
'
```

---

## 7. Database Migrations

Migrations use Alembic and must be run:
- After first deploy (to create all tables)
- After any schema change (`.sql` files in `backend/nidp/migrations/`)

### Option A — Via Cloud Build (recommended for production path)

```bash
TOKEN=$(cat /app/.gcp-token)
CLOUDSDK_AUTH_ACCESS_TOKEN="$TOKEN" gcloud builds submit . \
    --config=backend/nidp/deploy/gcp/cloudbuild-migrations.yaml \
    --project=$PROJECT \
    --async
# Copy the Build ID from the output and monitor in Cloud Console
```

### Option B — Direct (for local dev / emergencies)

```bash
# Get Postgres URL from Secret Manager
NIDP_POSTGRES_URL=$(gcloud secrets versions access latest \
    --secret=NIDP_POSTGRES_URL --project=$PROJECT)

# Run migrations (from repo root)
NIDP_POSTGRES_URL="$NIDP_POSTGRES_URL" \
    python -m nidp.cli migrate
```

**Check migration status:**
```bash
NIDP_POSTGRES_URL="$NIDP_POSTGRES_URL" \
    python -m nidp.cli migrate --status
```

---

## 8. Cloud Run Jobs (Ingesters)

Each ingester is a Cloud Run Job triggered by Cloud Scheduler daily.

### Deploy all jobs

```bash
TOKEN=$(cat /app/.gcp-token)
CLOUDSDK_AUTH_ACCESS_TOKEN="$TOKEN" \
    ./backend/nidp/deploy/gcp/deploy.sh \
    --project=$PROJECT \
    --confirm
```

### Run a job manually

```bash
gcloud run jobs execute nidp-nse-eod \
    --region=asia-south1 \
    --project=$PROJECT \
    --wait
# --wait blocks until completion and shows exit code
```

### Job inventory

| Job name                   | Schedule (IST)          | Data source                     |
|----------------------------|-------------------------|---------------------------------|
| `nidp-nse-eod`             | Mon–Fri 18:30           | NSE EOD bhavcopy                |
| `nidp-nse-delivery`        | Mon–Fri 18:45           | NSE delivery data               |
| `nidp-fii-dii`             | Mon–Fri 19:00           | NSE FII/DII flows               |
| `nidp-bulk-deals`          | Mon–Fri 19:00           | NSE bulk deals                  |
| `nidp-block-deals`         | Mon–Fri 19:00           | NSE block deals                 |
| `nidp-index-eod`           | Mon–Fri 18:30           | NSE index closing values        |
| `nidp-fno-bhavcopy`        | Mon–Fri 19:30           | NSE F&O bhavcopy                |
| `nidp-rbi-yields`          | Daily 08:00             | RBI DBIE G-Sec yields           |
| `nidp-fred-macro`          | Daily 08:00             | FRED (US macro series)          |
| `nidp-corporate-actions`   | Mon–Fri 19:00           | NSE corporate actions feed      |
| `nidp-announcements`       | Mon–Fri every 5 min     | NSE+BSE announcements           |
| `nidp-amfi-nav`            | Mon–Fri 20:00           | AMFI NAVAll.txt (~10k schemes)  |
| `nidp-amfi-circulars`      | Daily 09:00             | AMFI scheme-lifecycle notices   |
| `nidp-mf-disclosure`       | 12th of month 10:00     | AMC TER + risk-o-meter          |
| `nidp-mf-holdings`         | 12th of month 11:00     | Per-AMC monthly portfolio       |

### Check job execution history

```bash
gcloud logging read \
    'resource.type=cloud_run_job AND resource.labels.job_name=nidp-nse-eod' \
    --limit=20 \
    --format='table(timestamp,textPayload)' \
    --project=$PROJECT
```

---

## 9. DaaS API (Cloud Run Service)

The DaaS API is the externally-accessible REST API. It runs continuously (min-instances=1).

### First deploy

```bash
# Prerequisites: bootstrap, secrets, and VPC connector must already exist
./backend/nidp/deploy/gcp/setup_daas.sh \
    --project=$PROJECT \
    --confirm

# Build + deploy
TOKEN=$(cat /app/.gcp-token)
CLOUDSDK_AUTH_ACCESS_TOKEN="$TOKEN" gcloud builds submit . \
    --config=backend/nidp/deploy/gcp/cloudbuild-daas.yaml \
    --substitutions="_REGION=asia-south1,_CORS_ORIGINS=*" \
    --project=$PROJECT \
    --async
```

### Re-deploy after a code change

```bash
TOKEN=$(cat /app/.gcp-token)
CLOUDSDK_AUTH_ACCESS_TOKEN="$TOKEN" gcloud builds submit . \
    --config=backend/nidp/deploy/gcp/cloudbuild-daas.yaml \
    --substitutions="_REGION=asia-south1,_CORS_ORIGINS=*" \
    --project=$PROJECT \
    --async
# Note the Build ID. Build takes ~8–12 min.
```

### Smoke-test after deploy

```bash
SVC_URL=$(gcloud run services describe nidp-daas-api \
    --region=asia-south1 --project=$PROJECT \
    --format="value(status.url)")

curl "$SVC_URL/health"         # → {"status":"ok","version":"..."}
curl "$SVC_URL/v1/me"          # → 401 Unauthorized (auth gate working)
curl "$SVC_URL/docs"           # → OpenAPI UI
```

### Issue an API key

```bash
NIDP_POSTGRES_URL=$(gcloud secrets versions access latest \
    --secret=NIDP_POSTGRES_URL --project=$PROJECT)

NIDP_POSTGRES_URL="$NIDP_POSTGRES_URL" \
    python -m nidp.cli daas-keygen \
    --name "AcmeCorp" \
    --owner ops@acme.com \
    --plan standard
# Prints the key once — save it immediately, it is not stored in plaintext
```

### API plans

| Plan       | Req/min | Daily quota  | Use case                     |
|------------|---------|--------------|------------------------------|
| `free`     | 60      | 1,000        | Dev / trial                  |
| `standard` | 300     | 50,000       | Standard SaaS customer       |
| `pro`      | 1,500   | 500,000      | Bulk / analytics workloads   |
| `internal` | 6,000   | unlimited    | Service-to-service           |

---

## 10. Query API (Internal Service)

The Query API is an internal service used by the admin panel (`NidpCatalogPanel`, strategy engine).

### Deploy

```bash
TOKEN=$(cat /app/.gcp-token)
CLOUDSDK_AUTH_ACCESS_TOKEN="$TOKEN" gcloud builds submit . \
    --config=backend/nidp/deploy/gcp/cloudbuild-service.yaml \
    --substitutions="_SERVICE=query_api,_REGION=asia-south1" \
    --project=$PROJECT \
    --async
```

### What it exposes

| Endpoint          | Consumer                        |
|-------------------|---------------------------------|
| `GET /catalog`    | Admin `NidpCatalogPanel` (proxied via `/api/admin/nidp/catalog`) |
| `GET /health`     | Cloud Run health check          |

---

## 11. Mutual Fund Feeds

Five additional Cloud Run Jobs ingest AMFI and per-AMC data.

### First-time deploy of all MF feeds

```bash
# Dry-run
./backend/nidp/deploy/gcp/deploy_mf_feeds.sh \
    --project=$PROJECT

# Apply
./backend/nidp/deploy/gcp/deploy_mf_feeds.sh \
    --project=$PROJECT \
    --confirm
```

Steps the script runs:
1. Grant Cloud Build SA IAP roles for migration tunnel
2. Apply DB migrations (creates MF schema tables)
3. Build + push 5 MF service images
4. `gcloud run jobs create` for each service
5. Create Cloud Scheduler triggers
6. Create GitHub push triggers (requires connected repo)
7. Smoke-test `nidp-amfi-nav`

### One-time historical NAV backfill

Run **once** after first deploy to seed 3+ years of historical NAV data:

```bash
gcloud run jobs execute nidp-amfi-nav-history \
    --region=asia-south1 \
    --project=$PROJECT \
    --wait
# Takes 20–40 min. Do not interrupt.
```

---

## 12. CI/CD with Cloud Build

### How it works

Every `git push` to the `nidp` branch triggers Cloud Build pipelines via GitHub integration.

| File changed                              | Pipeline triggered                        |
|-------------------------------------------|-------------------------------------------|
| `backend/nidp/services/daas_api/**`       | `cloudbuild-daas.yaml` → build+push+deploy DaaS |
| `backend/nidp/services/query_api/**`      | `cloudbuild-service.yaml` → build+push+deploy Query API |
| `backend/nidp/services/<service>/**`      | `cloudbuild-service.yaml` → build+push+deploy that service |

### Manual build trigger (using devops token)

```bash
TOKEN=$(cat /app/.gcp-token)  # must be < 45 min old

CLOUDSDK_AUTH_ACCESS_TOKEN="$TOKEN" gcloud builds submit . \
    --config=backend/nidp/deploy/gcp/cloudbuild-daas.yaml \
    --substitutions="_REGION=asia-south1,_CORS_ORIGINS=*" \
    --project=$PROJECT \
    --async
```

Always use `--async`. Note the Build ID and monitor in Cloud Console:
`https://console.cloud.google.com/cloud-build/builds?project=niveshdataintelligence`

### Check build status

```bash
TOKEN=$(cat /app/.gcp-token)
CLOUDSDK_AUTH_ACCESS_TOKEN="$TOKEN" \
    gcloud builds describe <BUILD_ID> \
    --project=$PROJECT \
    --format="value(status,finishTime)"
```

### Build step summary (cloudbuild-daas.yaml)

```
1. build    — docker build daas_api image, tag with $BUILD_ID + :latest
2. push-sha — docker push :$BUILD_ID
3. push-latest — docker push :latest
4. deploy   — gcloud run services create/update nidp-daas-api
5. smoke    — curl /health (200) + /v1/me (401)
```

---

## 13. Monitoring & Logs

### Cloud Run service logs

```bash
# DaaS API — last 50 request logs
gcloud logging read \
    'resource.type=cloud_run_revision AND resource.labels.service_name=nidp-daas-api' \
    --limit=50 \
    --format='table(timestamp,httpRequest.status,httpRequest.requestUrl)' \
    --project=$PROJECT

# Errors only
gcloud logging read \
    'resource.type=cloud_run_revision AND resource.labels.service_name=nidp-daas-api AND severity>=ERROR' \
    --limit=20 \
    --project=$PROJECT
```

### Cloud Run job logs

```bash
gcloud logging read \
    'resource.type=cloud_run_job AND resource.labels.job_name=nidp-nse-eod' \
    --limit=50 \
    --format='value(timestamp,textPayload)' \
    --project=$PROJECT
```

### Cloud Build logs

```bash
TOKEN=$(cat /app/.gcp-token)
CLOUDSDK_AUTH_ACCESS_TOKEN="$TOKEN" \
    gcloud builds log <BUILD_ID> \
    --project=$PROJECT
```

### Service health

```bash
# All Cloud Run services and their latest revision status
gcloud run services list \
    --region=asia-south1 \
    --project=$PROJECT \
    --format='table(metadata.name,status.latestReadyRevisionName,status.conditions[0].type)'
```

---

## 14. Rollback Procedures

### Roll back DaaS API to the previous revision

```bash
# List recent revisions
gcloud run revisions list \
    --service=nidp-daas-api \
    --region=asia-south1 \
    --project=$PROJECT \
    --format='table(metadata.name,status.conditions[0].status,metadata.creationTimestamp)' \
    | head -5

# Route 100% traffic to the previous good revision
gcloud run services update-traffic nidp-daas-api \
    --to-revisions=<PREVIOUS_REVISION>=100 \
    --region=asia-south1 \
    --project=$PROJECT
```

### Roll back a Cloud Run Job to a previous image

```bash
# Find the previous image tag from build history
TOKEN=$(cat /app/.gcp-token)
CLOUDSDK_AUTH_ACCESS_TOKEN="$TOKEN" \
    gcloud builds list \
    --project=$PROJECT \
    --limit=10 \
    --format='table(id,status,createTime,images)'

# Update the job image
gcloud run jobs update nidp-amfi-nav \
    --image=asia-south1-docker.pkg.dev/$PROJECT/nidp/amfi_nav:<PREVIOUS_BUILD_ID> \
    --region=asia-south1 \
    --project=$PROJECT
```

### Emergency: revert a bad migration

Database rollbacks must be handled manually — Alembic supports `downgrade`:
```bash
NIDP_POSTGRES_URL=$(gcloud secrets versions access latest \
    --secret=NIDP_POSTGRES_URL --project=$PROJECT)

NIDP_POSTGRES_URL="$NIDP_POSTGRES_URL" \
    python -m alembic downgrade -1
# Downgrades by one migration step. Repeat if needed.
```

> ⚠️ Always take a Postgres snapshot before running `downgrade` in any shared environment.

---

## 15. Token Management

### Why tokens expire

The agent uses short-lived OAuth tokens from the `nivesh-devops` service account. These expire in **1 hour**. After expiry, all GCP API calls return `401 Unauthorized`.

### Get a fresh token

**Option A — JSON key (no expiry on key itself; token still lasts 1 hour):**
```bash
gcloud auth activate-service-account \
    --key-file=/secure/path/nivesh-devops-key.json
TOKEN=$(gcloud auth print-access-token)
echo "$TOKEN" > /app/.gcp-token
```

**Option B — Impersonation (requires `roles/iam.serviceAccountTokenCreator` on your account):**
```bash
# Make sure you're using your personal account, not the SA
gcloud config set account aporwal107@gmail.com

TOKEN=$(gcloud auth print-access-token \
    --impersonate-service-account=nivesh-devops@niveshdataintelligence.iam.gserviceaccount.com)
echo "$TOKEN" > /app/.gcp-token
```

### Check token age

```bash
stat -c "Modified: %y" /app/.gcp-token
# Token is valid for 60 min from modification time
# Refresh when token is > 45 min old to avoid mid-task expiry
```

### Verify token is working

```bash
TOKEN=$(cat /app/.gcp-token)
curl -s -o /dev/null -w "HTTP %{http_code}\n" \
    -H "Authorization: Bearer $TOKEN" \
    "https://cloudbuild.googleapis.com/v1/projects/niveshdataintelligence/builds?pageSize=1"
# 200 = valid | 401 = expired | 403 = wrong permissions
```

---

## 16. Maintenance Operations

### Rotate the runtime SA key (`nidp-sa`)

Run at the end of each dev session or on a weekly schedule:
```bash
./backend/nidp/deploy/gcp/rotate_credentials.sh \
    --project=$PROJECT \
    --confirm
# Creates new key → updates Secret Manager → updates Cloud Run env → smoke-tests → deletes old key
```

### Tear down all resources (caution)

```bash
# Dry-run first — lists every resource it will delete
./backend/nidp/deploy/gcp/teardown.sh

# Actually delete (requires explicit CONFIRM DELETE prompt response)
./backend/nidp/deploy/gcp/teardown.sh --confirm
```

---

## 17. Cost Reference

| Resource                            | Estimate/month |
|-------------------------------------|----------------|
| GCE VM `nidp-stack-vm` (e2-std-2)  | ~$25           |
| Cloud Run Jobs (ingester executions)| ~$2–5          |
| Cloud Run Service `nidp-daas-api`   | ~$3–8          |
| Cloud Run Service `nidp-query-api`  | ~$2–4          |
| Serverless VPC connector            | ~$6            |
| Artifact Registry                   | ~$1–2          |
| Cloud Build (build minutes)         | ~$1–5          |
| Secret Manager                      | ~$1            |
| Cloud Logging                       | ~$1–2          |
| **Total (without Cloud Armor)**     | **~$42–60**    |
| Cloud Armor + Global LB (optional)  | +~$20          |

---

## 18. Troubleshooting

### Build fails: `PERMISSION_DENIED` on Secret Manager

The Cloud Build SA needs `roles/secretmanager.secretAccessor`. Check if the build is using the project default SA or `nivesh-devops`:
```bash
TOKEN=$(cat /app/.gcp-token)
CLOUDSDK_AUTH_ACCESS_TOKEN="$TOKEN" \
    gcloud builds describe <BUILD_ID> \
    --project=$PROJECT \
    --format="value(serviceAccount)"
```
If it's the default SA (`<PROJECT_NUMBER>@cloudbuild.gserviceaccount.com`), the `cloudbuild-daas.yaml` service account override must be set, or grant the role to the default SA.

### Cloud Run service returns 503 after deploy

The new revision failed its startup health check. Check what the revision logged:
```bash
NEW_REV=$(gcloud run revisions list \
    --service=nidp-daas-api \
    --region=asia-south1 \
    --project=$PROJECT \
    --format="value(metadata.name)" \
    --limit=1)

gcloud logging read \
    "resource.type=cloud_run_revision AND resource.labels.revision_name=$NEW_REV" \
    --limit=30 \
    --project=$PROJECT
```
Rollback immediately (see [Section 14](#14-rollback-procedures)) while debugging.

### `gcloud builds submit` fails: bucket FORBIDDEN

The `nivesh-devops` SA lacks `storage.objectAdmin` on the Cloud Build bucket:
```bash
# Run as project Owner (aporwal107@gmail.com — NOT as nivesh-devops)
gcloud config set account aporwal107@gmail.com
gcloud projects add-iam-policy-binding niveshdataintelligence \
    --member="serviceAccount:nivesh-devops@niveshdataintelligence.iam.gserviceaccount.com" \
    --role="roles/storage.admin" \
    --condition=None
```

### Token error: `ACCESS_TOKEN_TYPE_UNSUPPORTED`

Your personal account uses Workforce Identity Federation, which produces tokens that some APIs reject. Always use the `nivesh-devops` SA token (via JSON key or impersonation) for GCP API calls — never use `gcloud auth print-access-token` from your personal account directly.

### Secret Manager secret not found

Secrets must be populated (see [Section 5](#5-secret-manager-setup)) before any Cloud Run service starts. Check:
```bash
gcloud secrets list --project=$PROJECT
gcloud secrets versions list NIDP_POSTGRES_URL --project=$PROJECT
```

### Postgres connection refused from Cloud Run

The Serverless VPC connector must be created and the Cloud Run service must reference it:
```bash
gcloud compute networks vpc-access connectors describe nidp-vpc \
    --region=asia-south1 \
    --project=$PROJECT
```
If it doesn't exist, run `setup_daas.sh --confirm` again. The `cloudbuild-daas.yaml` deploy step skips the VPC connector gracefully if absent, so the service may have started without it.
