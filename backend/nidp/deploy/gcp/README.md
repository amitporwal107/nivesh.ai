# NIDP — GCP runbook

This directory contains:

| File | Purpose |
|---|---|
| `setup_credentials.sh` | One-time: create the runtime service account `nidp-sa@…`, bind narrow runtime roles, mint a JSON key to `/app/.gcp/nidp-sa.json`. Run before bootstrap. |
| `bootstrap.sh`         | Create project resources (APIs, SA, GCS bucket, secrets, Artifact Registry, GCE VM). Idempotent. |
| `deploy.sh`            | Build all NIDP service Docker images, push to Artifact Registry, create/update Cloud Run Jobs. Re-run after any code change. |
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
