# Staging on CloudPe

Build, deploy and data-migration scripts for running **staging** on two CloudPe VMs
instead of the GCP VMs it shared with prod. Prod is not touched by anything here.

| VM | IP | Runs | Public hostname |
|---|---|---|---|
| App | 45.64.105.88 | Postgres, Mongo, Redis, backend, two frontends, edge nginx (all Docker Compose) | `staging.niveshcopilot.com` |
| NIDP | 45.64.105.224 | TimescaleDB + DaaS API (Docker), Query API (systemd), cron feeds, host nginx | `staging-data.niveshcopilot.com` |

Both VMs are Ubuntu 24.04. Paths, container names and ports are the same as on GCP
(`/opt/nivesh-staging`, `/opt/nidp-staging`, `/opt/nidp/dev-repo/nivesh.ai`).

## How it is put together

The existing staging compose files are still what GCP staging deploys from, so they are
not edited. Each stack adds an override file that replaces only the GCP-coupled parts:

| Stack | Base | Override | What the override changes |
|---|---|---|---|
| App | `deploy/nivesh-staging/docker-compose.staging.yml` | `app/docker-compose.cloudpe.yml` | No Artifact Registry build cache; no `nidp-bridge` network; nginx publishes 443 and 8443 itself; own cert directory; Cloudflare-only allow-list |
| NIDP | `backend/nidp/deploy/vm/docker-compose.staging.yml` | `nidp/docker-compose.cloudpe.yml` | Postgres on loopback only (no `10.160.0.3` bind); TimescaleDB image pinned to the source version; DB password from `nidp.env`; `/dumps` mount |

Requires Docker Compose ≥ 2.33.1 (the bootstrap scripts install a current one and check).

No GCP credentials exist on these VMs. Secrets come from the env files only; the backend's
Secret Manager lookups return nothing and fall back to env. `check-env.sh` reports, by
variable name, what is missing or still points into GCP.

The origin only answers Cloudflare: each nginx gets an `allow`/`deny` list generated from
Cloudflare's published ranges (the GCP firewall rule did this before). CloudPe's own
firewall/security group must allow inbound 22, 443 and 8443 on the app VM and 22, 80 and
443 on the NIDP VM.

## Files

| File | Run on | Purpose |
|---|---|---|
| `migrate/capture-gcp-app.sh` | GCP app VM | Dump app Postgres + Mongo, app data, env, cert, cron → bundle |
| `migrate/capture-gcp-nidp.sh` | GCP NIDP VM | Dump `nidp_staging`, env, unit, cron, cert, pip freeze → bundle |
| `app/bootstrap.sh` | App VM | One-time setup |
| `app/restore.sh` | App VM | Load the app bundle, compare counts with the source |
| `app/deploy.sh` | App VM | Pull, build, start, smoke-check |
| `nidp/bootstrap.sh` | NIDP VM | One-time setup; starts Postgres only |
| `nidp/restore.sh` | NIDP VM | TimescaleDB-aware restore, compare with the source |
| `nidp/deploy.sh` | NIDP VM | Pull, start DaaS + Query API, health-check, optionally enable cron |
| `check-env.sh` | either | Validate an env file by name |
| `lib/` | — | Shared helpers |

Every script takes `--help`. All of them need root.

## First-time migration

### 1. Capture on GCP

Copy `deploy/cloudpe/` to each GCP VM (or use the staging checkout there once this is on
`dev`). The capture scripts only read; they do not stop anything.

```bash
# on nivesh-app-vm
sudo bash deploy/cloudpe/migrate/capture-gcp-app.sh  --stream-to deploy@45.64.105.88:/home/deploy/bundle-app
# on nidp-stack-vm
sudo bash deploy/cloudpe/migrate/capture-gcp-nidp.sh --stream-to deploy@45.64.105.224:/home/deploy/bundle-nidp
```

`--stream-to` pipes straight over SSH because the GCP disks are nearly full; use
`--out DIR` instead to write locally. The bundles contain secrets and are written mode 600.

Row counts are recorded right after each dump. For counts that match exactly, stop the
staging writers on GCP first (app backend container; NIDP cron file); otherwise expect a
small drift on tables written during the capture.

### 2. App VM

```bash
sudo bash deploy/cloudpe/app/bootstrap.sh --bundle /home/deploy/bundle-app
#   first run prints a deploy key → add it to the GitHub repo (read-only) → re-run
sudo bash /opt/nivesh-staging/repo/deploy/cloudpe/check-env.sh app /opt/nivesh-staging/.env.staging
sudo bash /opt/nivesh-staging/repo/deploy/cloudpe/app/restore.sh /home/deploy/bundle-app
sudo bash /opt/nivesh-staging/repo/deploy/cloudpe/app/deploy.sh dev
```

Secrets that lived only in GCP Secret Manager (the CAS Parser key pool
`casparser-api-keys-staging`, possibly `OPENAI_API_KEY`) must be added to
`/opt/nivesh-staging/.env.staging` by hand.

### 3. NIDP VM

```bash
sudo bash deploy/cloudpe/nidp/bootstrap.sh --bundle /home/deploy/bundle-nidp
#   deploy key as above
sudo bash /opt/nidp/dev-repo/nivesh.ai/deploy/cloudpe/nidp/restore.sh /home/deploy/bundle-nidp
sudo bash /opt/nidp/dev-repo/nivesh.ai/deploy/cloudpe/nidp/deploy.sh dev --install-cron
```

`NSE_HTTPS_PROXY` in the copied `nidp.env` points at a proxy inside the GCP VPC;
`check-env.sh` flags it. Remove it and test NSE reachability from this VM's own IP.

### 4. Check the origins before touching DNS

`deploy.sh` on each VM already probes through its nginx on loopback. From outside, a
direct request to either IP should be refused (403) because it is not from Cloudflare.

### 5. Cut over

In Cloudflare DNS, point `staging` → `45.64.105.88` and `staging-data` → `45.64.105.224`
(both proxied). GCP staging stops receiving traffic at that moment. Then:

```bash
curl -sf https://staging.niveshcopilot.com/api/healthz
curl -sf https://staging-data.niveshcopilot.com/health
```

**Rollback:** point the two records back at `34.47.250.214` / `34.93.60.254`. Nothing on
GCP is changed by these scripts.

## Rebuilding without a capture (what was done on 2026-10-12)

GCP access was revoked before a capture could be taken, so staging was rebuilt empty:

- Both bootstraps were run without `--bundle`. The NIDP one generates `nidp.env` with a
  fresh DB password and internal tokens; the app one generates `.env.staging`. The two
  tokens `NIDP_QUERY_API_TOKEN` and `NIDP_DAAS_INTERNAL_TOKEN` were copied from the NIDP
  env into the app env, and `OPENAI_API_KEY` was added to both by hand.
- `nidp/bootstrap.sh --tsdb-tag 2.26.4-pg16`, then `nidp/deploy.sh dev --migrate --install-cron`
  built the NIDP schema from the 139 migrations.
- `app/deploy.sh dev --migrate` built and started the app stack.
- Each VM has its own Cloudflare Origin CA certificate (key generated on the VM).
- `cloudflare-cutover.sh apply` repointed the two A records.

The warehouse starts with no market data, and the staged crontab is the repo copy with
the feed lines commented out. Enable feeds in `/opt/nidp-staging/cron/nidp-staging.cron`
and re-run `nidp/deploy.sh dev --install-cron`.

## Routine deploys

```bash
# App VM
sudo bash /opt/nivesh-staging/repo/deploy/cloudpe/app/deploy.sh dev [--backend-only|--frontend-only] [--migrate]
# NIDP VM
sudo bash /opt/nidp/dev-repo/nivesh.ai/deploy/cloudpe/nidp/deploy.sh dev [--migrate]
```

## CI

The three staging workflows (`deploy-backend-staging.yml`, `deploy-frontend-staging.yml`,
`deploy-nidp-staging.yml`) SSH to these VMs as the user `ci-deploy` and run one command:

```bash
sudo /usr/bin/bash <checkout>/deploy/cloudpe/ci-deploy.sh app|nidp <branch> [flags]
```

`ci-deploy` exists on both VMs with a sudoers entry (`/etc/sudoers.d/91-ci-deploy`) that
allows only that command. The workflows read four repository secrets, separate from the
prod ones: `STAGING_APP_VM_HOST`, `STAGING_NIDP_VM_HOST`, `STAGING_SSH_USER` (`ci-deploy`)
and `STAGING_SSH_KEY` (the private key whose public half is in
`/home/ci-deploy/.ssh/authorized_keys` on both VMs).

Other workflows that used the GCP NIDP VM for staging (`deploy-android-staging.yml`,
`nidp-run-service.yml`, `deploy-grafana.yml`) have not been moved.

## Not covered

- Grafana/Loki, the code-server IDE and the Android APK build stay on the GCP NIDP VM.
  `/grafana/` on the new `staging-data` host returns 502.
- No scheduled backups (staging had none on GCP either).
- Backend paths that need GCP credentials are inert here: the `gcloud compute ssh` bridge,
  the GCS export job, the Cloud Logging client-log sink.
