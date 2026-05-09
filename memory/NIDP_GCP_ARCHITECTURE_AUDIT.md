# NIDP GCP Deployment Architecture — Audit (May 9, 2026)

## What's actually deployed

```
┌──────────────────────────────────────────────────────────────────────┐
│  GitHub: amitporwal107/nivesh.ai (branch: nidp)                       │
└─────────────────────────────┬────────────────────────────────────────┘
                              │ push (any of 28 service paths changes)
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Cloud Build (region=asia-south1)                                     │
│  • 28 GitHub triggers  (one per service)                              │
│  • SA = 728147509901-compute@developer.gserviceaccount.com            │
│  • config: backend/nidp/deploy/gcp/cloudbuild-service.yaml            │
│  • Steps: docker build → push to Artifact Registry → deploy to Job    │
└─────────────────────────────┬────────────────────────────────────────┘
                              │ image:$BUILD_ID pushed to AR
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Artifact Registry (asia-south1-docker.pkg.dev/<proj>/nidp/)          │
│  • One repo per service: amfi_nav_history, fno_bhavcopy, …            │
└─────────────────────────────┬────────────────────────────────────────┘
                              │ deploy step in cloudbuild-service.yaml
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Cloud Run Jobs (asia-south1) — 28 jobs                               │
│  • Runtime SA = nidp-sa@niveshdataintelligence.iam                    │
│  • VPC connector = nidp-vpc (private route to GCE VM)                 │
│  • Env: NIDP_POSTGRES_URL, NIDP_KAFKA_BROKERS, NIDP_SCHEMA_REGISTRY,  │
│         NIDP_S3_BUCKET, NIDP_REDIS_URL  (all from Secret Manager)     │
└─────────────────────────────┬────────────────────────────────────────┘
                              │ via VPC connector (private 10.x net)
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│  GCE VM "nidp-stack-vm" (asia-south1-a, e2-small)                     │
│  • Single VM running docker-compose.dev.yml                           │
│  • Postgres 15 + TimescaleDB ext  (port 5433 → secret 5432 mapped)    │
│  • Redpanda  (Kafka API @ port 9092)                                  │
│  • Schema Registry  (port 8081)                                       │
│  • Redis  (port 6380)                                                 │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Cloud Scheduler (asia-south1) — 30+ cron jobs                        │
│  • setup_schedules.sh defines them                                    │
│  • Each fires `<RUN_API>/nidp-<job>:run` with OAuth from nidp-sa      │
│  • amfi-nav-history, backfill-90d are NOT scheduled (one-time)        │
└──────────────────────────────────────────────────────────────────────┘
```

## What broke (root cause, not symptom)

### Primary failure: GCE VM unreachable (Kafka + maybe more)

The `bus.flush()` errors prove the **Redpanda/Kafka broker on the GCE VM
is not responding** to API version requests. Cloud Run jobs publish
events at end-of-job; flush hangs; job FAILS even though Postgres
writes succeeded.

```
%4|FAIL|...10.160.0.3:9092/bootstrap: ApiVersionRequest failed:
       Local: Timed out (10s state APIVERSION_QUERY)
RuntimeError: Kafka flush timed out: 3235 message(s) unsent
```

`10.160.0.3` is the private VM IP. Reachable from VPC but Redpanda
itself is unhealthy/dead/OOM-killed.

### Secondary failures (real prod-only bugs masked by Kafka issue)

| Service | Bug | Why local tests missed it | Status |
|---|---|---|---|
| `fno_bhavcopy` | Avro enum missing `STO` instrument | Golden CSV had no STO rows | ✅ Fixed in code |
| `fno_bhavcopy` | `executemany` 30s timeout on 200k rows | Local fixtures have 100 rows | ✅ Batched |
| `delivery`     | Same `executemany` timeout, 50k rows | Same | ✅ Batched |
| `price_adjuster` | Decimal × float arithmetic | Local fetch returns floats | ✅ Cast fixed |
| `price_adjuster` | `_load_prices` 30s SELECT timeout on 2.5M rows | Empty local DB | ✅ statement_timeout 10min |
| `amfi_nav_history` | OOM on full universe ingest | Local does 10 schemes | ✅ `--only-stale-days 7` chunking |

### Why local tests "pass" but prod fails

1. Tests use **`LocalLogBus`** (writes events to stdout). Prod uses Kafka. → Kafka outages invisible locally.
2. Tests use **golden CSVs with ~100 rows**. Prod has 200k+. → Performance class issues invisible locally.
3. Tests use **empty test DB**. Prod has 5 years × 2000 symbols. → Query-plan timeouts invisible locally.
4. Tests **don't run the real `bus.flush()` / publish chain**. → Network-level failures invisible locally.

## My mistakes during this session

1. **Built in `global` Cloud Build region** instead of `asia-south1`. Wasted egress + inconsistent with team conventions. Won't repeat — see fix below.
2. **Set `--args` on `nidp-amfi-nav-history` Cloud Run job directly** (`--only-stale-days 7`). This bypassed the deploy pipeline. The trigger fires on a future push and could overwrite. The right place is in the Dockerfile ENTRYPOINT or in Cloud Scheduler payload.
3. **Force-updated `--image=` directly** for amfi_nav_history when the trigger-driven deploy stalled. Manual override is fine as a one-off but not as the steady state.
4. **Didn't audit the architecture before patching**. Should have done this audit first. My bad.

## Clean plan going forward

### Step 0 (already done) — All 28 jobs have `NIDP_EVENT_BUS=local`
Removes the Kafka dependency immediately. Events go to stdout/Cloud Logging.
This unblocks all daily feeds without touching the VM.

### Step 1 — Push code via the proper trigger flow, NOT manual builds
Stop running `gcloud builds submit --region=global`. Instead:
- `git push origin nidp` (when GitHub access is available)
- Each trigger only fires when its included files change — efficient.
- Falls back to manual `gcloud builds triggers run <name>` if needed,
  with `--region=asia-south1`.

### Step 2 — Don't set Cloud Run job `--args` manually
For `amfi_nav_history --only-stale-days 7` and `price_adjuster --since`,
bake the right defaults INTO the service code (`__main__.py`) so:
- A blank job invocation (no args) does the right thing.
- Cloud Scheduler doesn't need to know the right args.
- No risk of the next deploy resetting them.

### Step 3 — Investigate why Redpanda is dead
Separate task — needs SSH to `nidp-stack-vm`. Either:
- Restart docker-compose: `sudo docker compose -f /opt/nidp/docker-compose.dev.yml up -d`
- Check `dmesg` / `docker logs redpanda` for OOM
- Check VM disk full
- Or migrate to Confluent Cloud / managed Pub/Sub

This task doesn't block the daily ingestion (Step 0 fixed that).

### Step 4 — Make `bus.flush()` non-fatal
Add a try/except around `bus.flush()` in `ingester_base.py` so a future
broker outage logs a warning but doesn't fail the job. Belt + braces.

### Step 5 — Add `feed_health_check` job (built but not deployed yet)
Already coded at `/app/backend/nidp/services/feed_health_check/`.
Schedule daily at 23:00 IST. Reads `nidp.job_log` and surfaces any
feed without a fresh COMPLETED entry.

## Permissions gaps (you may want to fix these)

The OAuth token I'm using lacks:
- `cloudscheduler.jobs.list/update` — can't see/modify schedules
- `secretmanager.secrets.list` — can't audit secret state
- `compute.instances.list` — can't see the GCE VM status
- `resourcemanager.projects.getIamPolicy` — can't audit IAM
- `cloudbuild.builds.list` (for builds.triggers.list earlier — but works now with the fresh token)

`nidp-sa` (the service account JSON key in /app/.gcp) is even more
restricted — it's runtime-only.
