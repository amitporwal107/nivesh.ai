# Nivesh — Build / Deploy / Manage Cheatsheet

**Last updated:** 2026-05-14

Two GCP VMs, one GCP project:

| VM | IP | Role |
|---|---|---|
| `nivesh-app-vm` | `34.100.186.141` | Main app (Nginx + FastAPI + MongoDB + Postgres + Redis) |
| `nidp-stack-vm` | `34.93.60.254` | NIDP data plane (DaaS API + Query API + cron jobs + Grafana) |

**Project:** `niveshdataintelligence` · **Zone:** `asia-south1-a`

---

## 0. SSH Access

```bash
# nivesh-app-vm
gcloud compute ssh nivesh-app-vm \
  --project=niveshdataintelligence --zone=asia-south1-a

# nidp-stack-vm
gcloud compute ssh nidp-stack-vm \
  --project=niveshdataintelligence --zone=asia-south1-a

# nidp-stack-vm — direct SSH (OS Login username)
ssh aporwal107_gmail_com@34.93.60.254
```

---

## 1. nivesh-app-vm — First-time Setup

Run once from your laptop to create the VM, then bootstrap and deploy on the VM itself.

```bash
# Step 1: Create the VM (from laptop)
bash deploy/nivesh-app/create-vm.sh

# Step 2: Copy deploy files to the VM (from laptop)
gcloud compute scp --recurse deploy/nivesh-app/ nivesh-app-vm:~ \
  --project=niveshdataintelligence --zone=asia-south1-a

# Step 3: SSH into the VM
gcloud compute ssh nivesh-app-vm \
  --project=niveshdataintelligence --zone=asia-south1-a

# Step 4: On the VM — run bootstrap (installs Docker, creates dirs, clones repo)
sudo bash ~/nivesh-app/bootstrap.sh

# Step 5: On the VM — first deploy
sudo EXTERNAL_IP=34.100.186.141 bash /opt/nivesh/deploy/deploy.sh
```

---

## 2. nivesh-app-vm — Redeploy (Code Changes)

**Always use `redeploy.sh` — never build images or restart containers manually.**

`redeploy.sh` does 7 steps every run:
1. `git reset --hard origin/<branch>` — pulls latest code
2. Syncs ALL deploy files from repo → `/opt/nivesh/deploy/` **(prevents stale-file failures)**
3. Detects external IP
4. Builds backend image (if needed)
5. Builds frontend image with `PUBLIC_URL=/v2` **(mandatory — prevents MIME errors)**
6. Replaces and restarts changed containers
7. Health-checks `/api/health`

```bash
# Full redeploy (both backend + frontend) — standard workflow
bash deploy/nivesh-app/redeploy.sh

# Frontend only (CSS/JS changes — much faster, skips backend build)
bash deploy/nivesh-app/redeploy.sh --frontend-only

# Backend only (Python changes, requirements.txt changes)
bash deploy/nivesh-app/redeploy.sh --backend-only

# Specific branch
bash deploy/nivesh-app/redeploy.sh --branch main
```

> Run from your laptop — the script detects the local context and SSH-forwards to the VM automatically.

**When does each option apply?**

| Changed file(s) | Command |
|---|---|
| `frontend/src/**` (JS/CSS) | `--frontend-only` |
| `backend/**` (Python, no new deps) | `--backend-only` |
| `backend/requirements.txt` | (full rebuild, no flag) |
| `deploy/*/Dockerfile*` or `nginx.conf` | (full rebuild, no flag) |
| Both frontend and backend | (no flag) |

**Emergency: fast Python-only restart (no rebuild)**

```bash
# On the VM — pull code and restart backend process without rebuilding image
git -C /opt/nivesh/repo reset --hard origin/nivesh-v2-copilot
docker restart nivesh-backend
```

---

## 3. nivesh-app-vm — Build Images Manually

Use `redeploy.sh --backend-only` or `--frontend-only` instead. If you must build manually:

```bash
# On the VM — backend image
docker build \
  -f /opt/nivesh/deploy/Dockerfile.backend.prod \
  -t nivesh/backend:prod \
  /opt/nivesh/repo

# On the VM — frontend image (PUBLIC_URL=/v2 is MANDATORY)
docker build \
  -f /opt/nivesh/deploy/Dockerfile.frontend.prod \
  --build-arg PUBLIC_URL=/v2 \
  --build-arg REACT_APP_BACKEND_URL=https://niveshcopilot.com \
  -t nivesh/frontend:prod \
  /opt/nivesh/repo
```

> **Without `PUBLIC_URL=/v2`**: webpack bakes `/static/js/...` paths into `index.html`.
> nginx serves `/v2/` but not `/static/`, so all JS/CSS 301-redirect to `/v2/` and browsers get HTML
> instead of JS/CSS → MIME type error → blank page.

---

## 4. nivesh-app-vm — Manage Services

All commands run on the VM. The compose file is `/opt/nivesh/deploy/docker-compose.prod.yml`.

```bash
COMPOSE="docker compose -f /opt/nivesh/deploy/docker-compose.prod.yml"

# ── Status ────────────────────────────────────────────────────────────────────
$COMPOSE ps

# ── Logs (live tail) ──────────────────────────────────────────────────────────
docker logs -f nivesh-backend
docker logs -f nivesh-frontend
docker logs -f nivesh-mongo
docker logs -f nivesh-postgres
docker logs -f nivesh-redis

# ── Restart individual service ────────────────────────────────────────────────
$COMPOSE restart backend
$COMPOSE restart frontend
$COMPOSE restart mongodb
$COMPOSE restart postgres
$COMPOSE restart redis

# ── Restart all ───────────────────────────────────────────────────────────────
$COMPOSE restart

# ── Stop all ──────────────────────────────────────────────────────────────────
$COMPOSE down

# ── Start all ─────────────────────────────────────────────────────────────────
$COMPOSE --env-file /opt/nivesh/.env.prod up -d

# ── Health check ──────────────────────────────────────────────────────────────
curl -sf http://34.100.186.141.nip.io/health

# ── Run DB migrations (idempotent) ────────────────────────────────────────────
$COMPOSE --env-file /opt/nivesh/.env.prod --profile migrate up migrate
```

---

## 5. nidp-stack-vm — Deploy (Code Changes)

### Option A: Quick sync from dev pod (fastest)

```bash
# From the dev pod — rsyncs code directly, reloads cron
bash /app/backend/nidp/deploy/vm/quick_deploy.sh <GCP_OWNER_TOKEN>

# Or with env var
GOOGLE_OAUTH_ACCESS_TOKEN=<token> \
  bash /app/backend/nidp/deploy/vm/quick_deploy.sh
```

### Option B: Git pull on the VM

```bash
# SSH into VM first, then:
sudo -u nidp /opt/nidp/repo/backend/nidp/deploy/vm/deploy.sh

# Deploy a specific branch
sudo -u nidp /opt/nidp/repo/backend/nidp/deploy/vm/deploy.sh --branch=main
```

---

## 6. nidp-stack-vm — DaaS API Service

The DaaS API runs as a systemd service on `nidp-stack-vm`.

```bash
# ── Lifecycle ─────────────────────────────────────────────────────────────────
sudo systemctl start   nidp-daas-api
sudo systemctl stop    nidp-daas-api
sudo systemctl restart nidp-daas-api
sudo systemctl status  nidp-daas-api --no-pager

# ── Logs (live) ───────────────────────────────────────────────────────────────
sudo journalctl -u nidp-daas-api -f

# ── Logs (last 100 lines) ─────────────────────────────────────────────────────
sudo journalctl -u nidp-daas-api -n 100 --no-pager

# ── Smoke test ────────────────────────────────────────────────────────────────
curl http://34.93.60.254:8083/health
curl http://34.93.60.254:8083/docs
curl -H "X-API-Key: $NIDP_DAAS_API_KEY" \
  http://34.93.60.254:8083/v1/intelligence/snapshots/market
```

---

## 7. nidp-stack-vm — Query API Service

```bash
sudo systemctl start   nidp-query-api
sudo systemctl stop    nidp-query-api
sudo systemctl restart nidp-query-api
sudo systemctl status  nidp-query-api --no-pager
sudo journalctl -u nidp-query-api -f
```

---

## 8. nidp-stack-vm — Run Ingester Jobs Manually

```bash
# General form
sudo -u nidp /opt/nidp/repo/backend/nidp/deploy/vm/run_service.sh <service_name>

# Examples
sudo -u nidp /opt/nidp/repo/backend/nidp/deploy/vm/run_service.sh bhavcopy
sudo -u nidp /opt/nidp/repo/backend/nidp/deploy/vm/run_service.sh amfi_nav
sudo -u nidp /opt/nidp/repo/backend/nidp/deploy/vm/run_service.sh announcement_classifier
sudo -u nidp /opt/nidp/repo/backend/nidp/deploy/vm/run_service.sh document_parser
sudo -u nidp /opt/nidp/repo/backend/nidp/deploy/vm/run_service.sh intelligence

# One-time backfill (run only once)
sudo -u nidp /opt/nidp/repo/backend/nidp/deploy/vm/run_service.sh amfi_nav_history
```

All service names (from cron schedule):

| Service | Default schedule (IST) |
|---|---|
| `bhavcopy` | Mon–Fri 19:00 |
| `index_close` | Mon–Fri 19:00 |
| `fii_dii` | Mon–Fri 19:30 |
| `bulk_deals` | Mon–Fri 19:30 |
| `block_deals` | Mon–Fri 19:30 |
| `delivery` | Tue–Sat 10:30 |
| `corporate_actions` | Daily 20:00 |
| `rbi_yields` | Mon–Fri 20:30 |
| `fred_macro` | Daily 21:00 |
| `fno_bhavcopy` | Mon–Fri 19:30 |
| `nse_financials` | Daily 20:30 |
| `nse_shareholding` | Daily 21:00 |
| `nse_equity_master` | Sunday 07:00 |
| `nse_calendar` | 1st of month 06:00 |
| `index_constituents` | 1st of month 06:30 |
| `price_adjuster` | Mon–Fri 22:30 |
| `snapshot_builder` | Mon–Fri 22:00 |
| `corporate_announcements_nse` | Mon–Fri every 10 min 09:00–23:00 |
| `corporate_announcements_bse` | Mon–Fri every 10 min 09:00–23:00 |
| `announcement_classifier` | Every 30 min |
| `document_parser` | Every 15 min |
| `amfi_nav` | Mon–Fri 20:00 |
| `amfi_circulars` | Daily 09:00 |
| `mf_disclosure_snapshot` | 12th of month 10:00 |
| `mf_holdings` | 12th of month 11:00 |
| `event_calendar` | Mon–Fri 06:30 + 20:30 |
| `event_day_poller` | Mon–Fri every 5 min 09:00–16:00 |
| `d1_prep` | Mon–Fri 19:00 |
| `intelligence` | Mon–Fri 20:00 |
| `quality_gate` | Mon–Fri 22:30 |
| `intelligence_layer` | Mon–Fri 23:15 |
| `portfolio_intelligence_sync` | Mon–Fri 23:30 |

---

## 9. nidp-stack-vm — Cron Management

```bash
# View current cron schedule
cat /etc/cron.d/nidp

# Update cron after a schedule change in the repo
sudo install -m 644 \
  /opt/nidp/repo/backend/nidp/deploy/vm/nidp.cron \
  /etc/cron.d/nidp
sudo systemctl reload cron

# Check cron service is running
sudo systemctl status cron --no-pager
```

---

## 10. nidp-stack-vm — Health Check

```bash
# Run the health checker manually (checks all services against SLO, sends Telegram alert if stale)
sudo bash /opt/nidp/repo/backend/nidp/deploy/vm/health_check.sh

# Check systemd health timer
sudo systemctl status nidp-health.timer --no-pager
sudo journalctl -u nidp-health -n 50 --no-pager
```

---

## 11. Rollback

### nivesh-app-vm

```bash
# Roll back to a specific git SHA (on the VM)
git -C /opt/nivesh/repo checkout <SHA>
sudo bash /opt/nivesh/deploy/deploy.sh
```

### nidp-stack-vm (code rollback)

```bash
# On the VM, as nidp user
sudo -u nidp /opt/nidp/repo/backend/nidp/deploy/vm/rollback.sh <git-sha-or-tag>

# View deploy/rollback history
tail -20 /opt/nidp/logs/deploy.log
```

### nidp-daas-api (Cloud Run revision rollback)

```bash
# List recent revisions
gcloud run revisions list \
  --service=nidp-daas-api \
  --region=asia-south1 \
  --project=niveshdataintelligence \
  --format='table(metadata.name,status.conditions[0].status,metadata.creationTimestamp)' \
  | head -5

# Route 100% traffic to a previous revision
gcloud run services update-traffic nidp-daas-api \
  --to-revisions=<REVISION_NAME>=100 \
  --region=asia-south1 \
  --project=niveshdataintelligence
```

---

## 12. GCP Cloud Run — NIDP Jobs (manual trigger)

```bash
TOKEN=$(cat /app/.gcp-token)

# Run a specific job now
CLOUDSDK_AUTH_ACCESS_TOKEN="$TOKEN" gcloud run jobs execute nidp-nse-eod \
  --region=asia-south1 --project=niveshdataintelligence --wait

# List all jobs
CLOUDSDK_AUTH_ACCESS_TOKEN="$TOKEN" gcloud run jobs list \
  --region=asia-south1 --project=niveshdataintelligence

# View job execution logs
gcloud logging read \
  'resource.type=cloud_run_job AND resource.labels.job_name=nidp-nse-eod' \
  --limit=20 --format='table(timestamp,textPayload)' \
  --project=niveshdataintelligence
```

---

## 13. GCP Cloud Build — Deploy DaaS API

```bash
TOKEN=$(cat /app/.gcp-token)

# Submit build + deploy (async — note the Build ID)
CLOUDSDK_AUTH_ACCESS_TOKEN="$TOKEN" gcloud builds submit . \
  --config=backend/nidp/deploy/gcp/cloudbuild-daas.yaml \
  --substitutions="_REGION=asia-south1,_CORS_ORIGINS=*" \
  --project=niveshdataintelligence \
  --async

# Check build status
CLOUDSDK_AUTH_ACCESS_TOKEN="$TOKEN" \
  gcloud builds describe <BUILD_ID> \
  --project=niveshdataintelligence \
  --format="value(status,finishTime)"

# Stream build logs
CLOUDSDK_AUTH_ACCESS_TOKEN="$TOKEN" \
  gcloud builds log <BUILD_ID> \
  --project=niveshdataintelligence
```

---

## 14. GCP Token Management

```bash
# Refresh GCP token (expires every 60 min)
gcloud auth activate-service-account \
  --key-file=/secure/path/nivesh-devops-key.json
gcloud auth print-access-token > /app/.gcp-token

# Check token age (refresh when > 45 min old)
stat -c "Modified: %y" /app/.gcp-token

# Verify token is valid
TOKEN=$(cat /app/.gcp-token)
curl -s -o /dev/null -w "HTTP %{http_code}\n" \
  -H "Authorization: Bearer $TOKEN" \
  "https://cloudbuild.googleapis.com/v1/projects/niveshdataintelligence/builds?pageSize=1"
# 200 = valid | 401 = expired | 403 = wrong permissions
```

---

## 15. Logs — GCP Cloud Logging

Open [Logs Explorer](https://console.cloud.google.com/logs/query?project=niveshdataintelligence) and paste:

```
# All app errors (cross-app)
severity>=ERROR
(jsonPayload.application="nivesh-main-app"
 OR jsonPayload.application="nidp-console"
 OR jsonPayload.application="admin-app")

# Nivesh main app — 5xx only
jsonPayload.application="nivesh-main-app"
jsonPayload.httpStatus>=500

# Nivesh main app — slow requests (>3s)
jsonPayload.application="nivesh-main-app"
jsonPayload.responseTimeMs>3000

# NIDP — job failures
jsonPayload.application="nidp-console"
jsonPayload.eventType="JOB_FAILURE"

# NIDP — specific job trace (replace name)
jsonPayload.application="nidp-console"
jsonPayload.jobName="bulk_deals"

# Admin — audit trail
jsonPayload.application="admin-app"
jsonPayload.eventType="AUDIT_ACTION"

# Trace a specific request by correlation ID
jsonPayload.application="nivesh-main-app"
jsonPayload.correlationId="REPLACE_WITH_CORRELATION_ID"
```

---

## 16. VM Instance Management (from laptop)

```bash
# List both VMs with IPs
gcloud compute instances list \
  --project=niveshdataintelligence \
  --format="table(name,zone,machineType,networkInterfaces[0].accessConfigs[0].natIP)"

# Stop a VM (saves cost)
gcloud compute instances stop nivesh-app-vm \
  --project=niveshdataintelligence --zone=asia-south1-a

gcloud compute instances stop nidp-stack-vm \
  --project=niveshdataintelligence --zone=asia-south1-a

# Start a VM
gcloud compute instances start nivesh-app-vm \
  --project=niveshdataintelligence --zone=asia-south1-a

gcloud compute instances start nidp-stack-vm \
  --project=niveshdataintelligence --zone=asia-south1-a

# Check Cloud Run services
gcloud run services list \
  --region=asia-south1 \
  --project=niveshdataintelligence \
  --format='table(metadata.name,status.latestReadyRevisionName,status.conditions[0].type)'
```
