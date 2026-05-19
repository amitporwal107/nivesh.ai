# NIDP on a single GCE VM (Docker-free deployment)

This is the **Plan B** deployment for the 28 NIDP services — no Cloud
Run, no Cloud Build, no Artifact Registry, no Kaniko, no triggers.
Just one Linux VM running the Python code on cron.

## Why this exists

GCP Cloud Build in `asia-south1` has `E2_CPUS=0` quota, which
indefinitely stalls every CI/CD run. Rather than fight the quota or
shim Kaniko in-pod, NIDP services run as plain Python processes on
a small VM. Deploys are `git pull`. Rollbacks are `git checkout`.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  GCE VM  (e2-small, asia-south1-a, ~$13/mo)              │
│  ─────────────────────────────────────────────           │
│  /opt/nidp/repo            ← git checkout                │
│  /opt/nidp/venv            ← Python 3.11 + deps          │
│  /opt/nidp/logs/<service>  ← stdout/stderr (logrotate)   │
│  /etc/cron.d/nidp          ← all 28 schedules            │
│  systemd: nidp-health.timer (job_log freshness check)    │
└──────────────────────────────┬───────────────────────────┘
                               │ asyncpg (NIDP_POSTGRES_URL)
                               ▼
                ┌──────────────────────────────┐
                │  Cloud SQL Postgres          │
                │  schema: nidp                │
                └──────────────────────────────┘
```

## Files in this directory

| File                  | Purpose                                                          |
|-----------------------|------------------------------------------------------------------|
| `bootstrap.sh`        | One-shot VM provisioning (run on the VM as root, first boot)     |
| `nidp.cron`           | Crontab with all 28 service schedules (drop into `/etc/cron.d/`) |
| `run_service.sh`      | Wrapper invoked by cron — sets env, logs, records exit status    |
| `deploy.sh`           | Pull latest code, install deps, restart cron (idempotent)        |
| `rollback.sh`         | `git checkout <sha>` + restart                                   |
| `health_check.sh`     | Scans `nidp.job_log` for stale services; alerts via Telegram     |
| `nidp.env.example`    | Template env file (copy to `/opt/nidp/nidp.env`, fill secrets)   |
| `nidp-health.service` | systemd unit for the health checker                              |
| `nidp-health.timer`   | systemd timer (runs health_check every 30 min)                   |
| `nidp-daas-api.service` | systemd unit — DaaS API (binds to 127.0.0.1:8083; behind nginx) |
| `nidp-query-api.service`| systemd unit — Query API (binds to 127.0.0.1:8090; behind nginx)|
| `nginx.conf`          | Reverse-proxy config: TLS termination + path routing             |
| `install_nginx.sh`    | Installs nginx + pulls TLS cert/key from Secret Manager          |
| `restore_firewall.sh` | Emergency: re-create the pre-cutover public 8083/8090/3000 rules |

## One-time setup (5 steps, ~30 min)

```bash
# 1. From your laptop / Emergent pod:
gcloud compute instances create nidp-vm \
  --project=niveshdataintelligence \
  --zone=asia-south1-a \
  --machine-type=e2-small \
  --image-family=debian-12 --image-project=debian-cloud \
  --service-account=nidp-sa@niveshdataintelligence.iam.gserviceaccount.com \
  --scopes=cloud-platform \
  --tags=nidp \
  --metadata-from-file=startup-script=bootstrap.sh

# 2. SSH in:
gcloud compute ssh nidp-vm --zone=asia-south1-a

# 3. As root, finish setup:
sudo -i
cd /opt/nidp
cp /opt/nidp/repo/backend/nidp/deploy/vm/nidp.env.example /opt/nidp/nidp.env
$EDITOR /opt/nidp/nidp.env          # fill DB password, Telegram token, etc.

# 4. Install crontab + systemd timer:
sudo install -m 644 /opt/nidp/repo/backend/nidp/deploy/vm/nidp.cron      /etc/cron.d/nidp
sudo install -m 644 /opt/nidp/repo/backend/nidp/deploy/vm/nidp-health.service /etc/systemd/system/nidp-health.service
sudo install -m 644 /opt/nidp/repo/backend/nidp/deploy/vm/nidp-health.timer   /etc/systemd/system/nidp-health.timer
sudo systemctl daemon-reload
sudo systemctl enable --now nidp-health.timer

# 5. Smoke-test one service manually:
sudo -u nidp /opt/nidp/repo/backend/nidp/deploy/vm/run_service.sh fno_bhavcopy
sudo -u nidp psql "$NIDP_POSTGRES_URL" -c \
  "select service, status, finished_at from nidp.job_log order by finished_at desc limit 5"
```

## Daily deploy

```bash
gcloud compute ssh nidp-vm --zone=asia-south1-a --command \
  'sudo -u nidp /opt/nidp/repo/backend/nidp/deploy/vm/deploy.sh'
```

That's it. ~10 seconds. No build, no registry, no quota.

## Rollback

```bash
gcloud compute ssh nidp-vm --zone=asia-south1-a --command \
  'sudo -u nidp /opt/nidp/repo/backend/nidp/deploy/vm/rollback.sh <git-sha>'
```

## Disabling Cloud Run jobs (after VM is healthy)

Don't delete them — just remove their Cloud Scheduler triggers so
they stop firing. The job definitions stay as a fast rollback path
if the VM ever goes sideways.

```bash
for trig in $(gcloud scheduler jobs list \
        --location=asia-south1 --format='value(name)' \
        --filter='name~nidp-cron-'); do
    gcloud scheduler jobs pause "$trig" --location=asia-south1
done
```

## Monitoring

`nidp-health.timer` fires every 30 min. The health script:
1. Connects to Postgres
2. Compares `nidp.job_log.finished_at` against expected SLO per service
3. Posts a Telegram alert for any service stale > 24h

Logs live in `/opt/nidp/logs/<service>/<service>.log` rotated daily
by `logrotate` (configured by `bootstrap.sh`).

## Cost

| Resource          | Spec                  | ~Monthly  |
|-------------------|-----------------------|-----------|
| GCE VM            | e2-small, 30GB disk   | $13       |
| Egress            | Same-region to SQL    | $0        |
| Cloud Logging     | ~1 GB/mo retained     | $0 (free) |
| **Total**         |                       | **~$13**  |

Compared to: 28 Cloud Run jobs ($0–$5/mo, but the build pipeline
costs your time) + Cloud Build ($0 but blocked by quota anyway).
