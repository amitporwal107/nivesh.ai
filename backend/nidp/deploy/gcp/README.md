# NIDP — GCP runbook

This directory contains:

| File | Purpose |
|---|---|
| `setup_credentials.sh` | One-time: create the runtime service account `nidp-sa@…`, bind narrow runtime roles, mint a JSON key to `/app/.gcp/nidp-sa.json`. Run before bootstrap. |
| `bootstrap.sh`         | Create project resources (APIs, SA, GCS bucket, secrets, Artifact Registry, GCE VM). Idempotent. |
| `deploy.sh`            | Build all NIDP service Docker images, push to Artifact Registry, create/update Cloud Run **Jobs**. Re-run after any code change. |
| `setup_daas.sh`        | **DaaS** one-time: VPC connector, secrets, Cloud Build IAM, optional Cloud Armor. Run after bootstrap. |
| `deploy_daas.sh`       | **DaaS** build + push + create/update Cloud Run **Service** (`nidp-daas-api`). |
| `cloudbuild-daas.yaml` | **DaaS** Cloud Build CI/CD pipeline (build → migrate → deploy → smoke-test). |
| `setup_github_trigger_daas.sh` | **DaaS** create Cloud Build GitHub trigger. |
| `deploy_mf_feeds.sh`   | **MF feeds** one-shot deploy: IAP grants → migrations → build 5 images → create Cloud Run Jobs → schedules → GitHub triggers → smoke-test. |
| `rotate_credentials.sh`| Mint a new SA key, push to Secret Manager + Cloud Run env, smoke-test, delete the old key. Run at end of dev. |
| `teardown.sh`          | Destroy every resource recorded in `gcp_resources.jsonl`. `--dry-run` is default; `--confirm` actually deletes. |
| `gcp_resources.jsonl`  | Append-only log of every GCP resource created. Source of truth for rotate/teardown. |

## End-to-end deploy sequence

```bash
# 0. One-time on your machine
gcloud auth login
gcloud config set project <PROJECT>
gcloud auth application-default login

# 1. Mint runtime SA + key (creates /app/.gcp/nidp-sa.json)
./setup_credentials.sh --project=<PROJECT> --confirm

# 2. Provision project resources (APIs, bucket, secrets, AR, GCE VM)
export GCP_PROJECT=<PROJECT>
./bootstrap.sh --confirm

# 3. Populate Secret Manager values that bootstrap created as 'SET_ME'
gcloud secrets versions add NIDP_POSTGRES_URL --data-file=- <<< 'postgres://nidp:CHANGEME@<VM_IP>:5432/nidp'
gcloud secrets versions add NIDP_KAFKA_BROKERS --data-file=- <<< '<VM_IP>:9092'
gcloud secrets versions add NIDP_S3_BUCKET --data-file=- <<< "nidp-raw-${GCP_PROJECT}"
gcloud secrets versions add NIDP_REDIS_URL --data-file=- <<< 'redis://<VM_IP>:6380/0'
gcloud secrets versions add NIDP_SCHEMA_REGISTRY_URL --data-file=- <<< 'http://<VM_IP>:8081'

# 4. Bring up the data plane on the GCE VM
gcloud compute scp --recurse ../docker-compose.dev.yml ../prometheus.yml ../grafana \
    nidp-stack-vm:/opt/nidp/ --zone=<REGION>-a
gcloud compute ssh nidp-stack-vm --zone=<REGION>-a --command='
    sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin
    sudo docker compose -f /opt/nidp/docker-compose.dev.yml up -d'

# 5. Apply NIDP migrations against the VM's Postgres
NIDP_POSTGRES_URL='postgres://postgres:postgres@<VM_IP>:5433/nidp' \
    python -m nidp.cli migrate

# 6. Build, push, and deploy all 11 service images
./deploy.sh --project=<PROJECT> --confirm

# 7. Smoke-test one job
gcloud run jobs execute nidp-nse-calendar --region=<REGION> --wait
```

## Phase 2a deploy shape (smallest viable)

```
GCE e2-small VM (asia-south1)         ← Postgres + TimescaleDB + Redpanda + Redis (docker-compose)
GCS bucket  nidp-raw-{project}        ← raw archive (NIDP_STORAGE_BACKEND=s3 with GCS-S3 interop)
Cloud Run Jobs (one per ingester)     ← daily cron via Cloud Scheduler
Secret Manager  NIDP_*                ← POSTGRES_URL, S3 creds, Kafka brokers
Cloud Scheduler                       ← market-eod, flows, macro, reference cron
```

Estimated cost: ~$25 / mo. Most of it is the GCE VM.

## Step sequence (each step pauses for `--confirm`)

```
gcloud config set project <YOUR_PROJECT>
./bootstrap.sh --confirm   # provisions everything; logs to gcp_resources.jsonl
```

Then verify:

```
gcloud run jobs execute nidp-bulk-deals --region=asia-south1
```

When dev/test is done:

```
./rotate_credentials.sh --confirm    # new key, old key deleted, env updated
./teardown.sh --confirm              # tears down everything (or skip if you want to keep prod)
```

## Credential handling

- Service account file: `/app/.gcp/nidp-sa.json` (gitignored).
- Required roles: `roles/run.developer`, `roles/storage.objectAdmin` on the
  bucket, `roles/secretmanager.secretAccessor`, `roles/cloudsql.client`
  if Cloud SQL is added later.
- **Never paste the JSON into chat.** `bootstrap.sh` reads from
  `$GOOGLE_APPLICATION_CREDENTIALS`.

---

## Mutual Fund data feeds (MF phase)

Five Cloud Run Jobs ingest AMFI and per-AMC mutual fund data:

| Service | Source | Schedule (IST) | Notes |
|---|---|---|---|
| `amfi_nav` | AMFI NAVAll.txt (all ~10k schemes) | Mon–Fri 20:00 | Published ~18:30; 90-min buffer |
| `amfi_nav_history` | AMFI historical NAV archive | **manual only** | One-time backfill; run after first deploy |
| `amfi_circulars` | AMFI scheme-lifecycle notices | Daily 09:00 | Mergers, renames, new scheme filings |
| `mf_disclosure_snapshot` | AMFI central TER + risk-o-meter Excels | 12th of month 10:00 | SEBI mandates publication by the 10th |
| `mf_holdings` | Per-AMC monthly portfolio Excels (10 AMCs) | 12th of month 11:00 | SEBI XBRL-format disclosure; 1h after snapshot |

AMCs covered by `mf_holdings`: SBI, ICICI Pru, HDFC, Nippon, Kotak, ABSL, UTI, Axis, Tata, Mirae Asset.

### First-time deploy

```bash
# Dry-run first — shows every command, touches nothing
cd backend/nidp/deploy/gcp
./deploy_mf_feeds.sh --project=niveshdataintelligence

# Deploy for real
./deploy_mf_feeds.sh --project=niveshdataintelligence --confirm
```

The script runs 7 steps in order:

| Step | Action |
|---|---|
| 0 | Grant Cloud Build SA the 3 IAP roles needed for SSH migrations (idempotent) |
| 1 | Apply DB migrations via Cloud Build + IAP tunnel to the GCE VM |
| 2 | Build + push 5 service images via `cloudbuild-service.yaml` |
| 3 | `gcloud run jobs create` for each service (skips if already exists) |
| 4 | Create 4 Cloud Scheduler triggers (skips if already exists) |
| 5 | Create 5 GitHub push triggers via `setup_github_triggers.sh` |
| 6 | Smoke-test `nidp-amfi-nav` with `--wait` and tail logs |

### One-time NAV history backfill

Run **once** after the first deploy to seed historical NAV data:

```bash
gcloud run jobs execute nidp-amfi-nav-history \
    --region=asia-south1 --project=niveshdataintelligence --wait
```

### Re-deploying after a code change

Pushing to the `nidp` branch auto-triggers rebuild via Cloud Build for
whichever service's files changed. To force a manual redeploy of all 5:

```bash
./deploy_mf_feeds.sh --project=niveshdataintelligence --confirm
```

### Tail logs

```bash
# Replace <job> with e.g. nidp-amfi-nav, nidp-mf-holdings, etc.
gcloud logging read \
    'resource.type=cloud_run_job AND resource.labels.job_name=<job>' \
    --limit=50 --format='value(textPayload)' \
    --project=niveshdataintelligence
```

### Secret Manager secrets used by MF feeds

All 5 services use the same common secrets as the Phase 1A/1B ingesters:

| Secret | Purpose |
|---|---|
| `NIDP_POSTGRES_URL` | TimescaleDB connection |
| `NIDP_KAFKA_BROKERS` | Redpanda event bus |
| `NIDP_SCHEMA_REGISTRY_URL` | Avro schema registry |
| `NIDP_REDIS_URL` | Dedup / state cache |

No additional secrets needed — TER, risk-o-meter, NAV, and circular data
are all fetched from public AMFI/SEBI URLs without authentication.

---

## DaaS API — public Cloud Run Service

The DaaS API (`nidp.services.daas_api`) is a **long-running HTTP Cloud
Run Service**, not a Job. It runs at all times (min-instances=1) and is
publicly reachable; auth is enforced in-app via per-caller API keys.

### Architecture

```
Internet callers (API key auth)
       │
       ▼
Cloud Run Service: nidp-daas-api          ← asia-south1, --allow-unauthenticated
  │  Port 8081 (reads $PORT)              ← min=1, max=20, 512Mi, 1 vCPU
  │  env: NIDP_POSTGRES_URL (secret)
  │  env: NIDP_DAAS_INTERNAL_TOKEN (opt)
  │
  ▼  (Serverless VPC connector: nidp-vpc)
GCE VM: nidp-stack-vm                     ← Postgres:5432 on private IP
```

Optional upgrade path:
```
Internet → Global HTTPS LB → Cloud Armor WAF → Cloud Run Service
```
(Needed for IP-level rate limiting / WAF rules; adds ~$20/mo.)

### First-time deploy

> **Pre-requisites**:
> - `bootstrap.sh --confirm` has already run.
> - `setup_daas.sh --project=$GCP_PROJECT --confirm` has already run (VPC connector, secrets, IAM).
> - All commands below run from the **repo root** (the directory containing `backend/`).

```bash
export GCP_PROJECT=<PROJECT_ID>
export GCP_REGION=asia-south1
```

#### Step 2 — Build, migrate, and deploy

`deploy_daas.sh` now handles migrations automatically — it runs
`python -m nidp.cli migrate` inside a one-off Cloud Run Job (same image +
VPC connector as the Service, so it can reach the private Postgres without
any SSH or IAP setup):

```bash
cd backend/nidp/deploy/gcp
./deploy_daas.sh --project=$GCP_PROJECT --confirm
```

This does, in order:
1. Build and push the `daas_api` Docker image to Artifact Registry
2. Run `nidp.cli migrate` as a Cloud Run Job (creates/updates all DB tables)
3. Create/update the `nidp-daas-api` Cloud Run Service

#### Step 4 — Issue your first API key

The Cloud Run Service connects to Postgres via the VPC connector. To run the
keygen CLI you need `NIDP_POSTGRES_URL` from Secret Manager:

```bash
NIDP_POSTGRES_URL="$(gcloud secrets versions access latest \
    --secret=NIDP_POSTGRES_URL --project=$GCP_PROJECT)"

NIDP_POSTGRES_URL="$NIDP_POSTGRES_URL" \
    python -m nidp.cli daas-keygen \
    --name "first-user" --owner ops@yourco.com --plan free
```

> The cleartext token is printed **once** and never stored. Save it immediately.

#### Step 5 — Smoke-test

```bash
SVC_URL=$(gcloud run services describe nidp-daas-api \
    --region=$GCP_REGION --project=$GCP_PROJECT \
    --format="value(status.url)")

curl $SVC_URL/health                           # → {"status":"ok"}
curl -H "X-API-Key: nvd_..." $SVC_URL/v1/me   # → key info + plan
curl $SVC_URL/docs                             # OpenAPI UI
```

---

### Re-deploying after a code change

```bash
# From repo root:
cd backend/nidp/deploy/gcp
./deploy_daas.sh --project=$GCP_PROJECT --confirm
# Builds new image, deploys it, and auto smoke-tests /health.
```

If migrations also changed, run Step 2 first.

---

### CI/CD (Cloud Build, auto on push)

```bash
# 1. Connect your GitHub repo in Cloud Console first:
#    Cloud Build → Triggers → Connect Repository

# 2. Create the trigger (from repo root)
./backend/nidp/deploy/gcp/setup_github_trigger_daas.sh \
    --project=$GCP_PROJECT \
    --repo-owner=<GH_ORG> \
    --repo-name=<GH_REPO> \
    --branch=nidp \
    --confirm
```

On every push to `nidp` that touches `backend/nidp/services/daas_api/**`,
Cloud Build will:
1. Build and push the Docker image (tagged `$SHORT_SHA`)
2. Run `python -m nidp.cli migrate` inside the image (idempotent)
3. Update the Cloud Run Service to the new image
4. Smoke-test `/health` and `/v1/me` (200 and 401 respectively)

### Key management

```bash
# Issue
NIDP_POSTGRES_URL="$URL" python -m nidp.cli daas-keygen \
    --name "AcmeCorp" --owner ops@acme.com --plan standard

# List
NIDP_POSTGRES_URL="$URL" python -m nidp.cli daas-keys list

# Revoke
NIDP_POSTGRES_URL="$URL" python -m nidp.cli daas-keys revoke \
    --key-id <uuid>
```

The cleartext token is printed once at issuance and never stored — only
its SHA-256 hash lives in `nidp.daas_api_keys`.

### Plans

| plan     | rpm  | daily quota |  cost note         |
|----------|------|-------------|--------------------|
| free     |  60  |     1,000   | dev / trial        |
| standard | 300  |    50,000   | SaaS standard tier |
| pro      | 1500 |   500,000   | bulk / analytics   |
| internal | 6000 | unlimited   | service-to-service |

### Secret Manager secrets used by DaaS

| Secret                     | Required | Purpose                                    |
|----------------------------|----------|--------------------------------------------|
| `NIDP_POSTGRES_URL`        | ✓        | DB connection (shared with ingesters)       |
| `NIDP_DAAS_INTERNAL_TOKEN` | optional | Escape-hatch for service-to-service calls   |

### Estimated cost (DaaS-only additions)

| Resource                     | Cost/mo (est.) |
|------------------------------|----------------|
| Cloud Run Service (min=1)    | ~$3–8          |
| Serverless VPC connector     | ~$6            |
| Cloud Armor + Global LB      | ~$20 (optional)|
| **Total (without Armor)**    | **~$10–15**    |
