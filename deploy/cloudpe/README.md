# CloudPe deployment (staging)

GCP is inaccessible, so staging runs on two CloudPe VMs (region IN-WEST2, Ubuntu 24.04,
4 vCPU / 16 GiB / 100 GiB each). Nothing here depends on GCP.

| VM | IP | Runs | Deploy script | Workflow |
|---|---|---|---|---|
| `cloudpe1` | 45.64.105.88 | Nivesh app: backend, v2 + v5 frontends, Postgres, Mongo, Redis, edge nginx (:8443) | `app-vm/deploy.sh` | `.github/workflows/deploy-cloudpe-app.yml` |
| `cloudpe2` | 45.64.105.224 | NIDP: TimescaleDB (:5434), DaaS API (:8084), Query API (:8091), feed cron | `nidp-vm/deploy.sh` | `.github/workflows/deploy-cloudpe-nidp.yml` |

Both reuse the existing GCP staging compose files unchanged, plus a CloudPe override
(`*/docker-compose.override.yml`) that removes the GCP-only parts (Artifact Registry build
cache, GCP VPC IP binds, GCP MTU) and adds the NIDP Query API as a container.
All ports are bound to `127.0.0.1`; nothing is public until you decide to expose it.

## 1. One-time setup on each VM

On each VM, as `deploy`, with the VM's GitHub deploy key already working (`ssh -T git@github.com`):

```bash
# cloudpe1 (app)
git clone -b dev git@github.com:amitporwal107/nivesh.ai.git ~/nivesh.ai   # if not already
sudo bash ~/nivesh.ai/deploy/cloudpe/app-vm/deploy.sh --setup
exit   # log out and back in so the docker group applies
bash /opt/nivesh-staging/repo/deploy/cloudpe/app-vm/deploy.sh --migrate      # first deploy

# cloudpe2 (NIDP)
git clone -b dev git@github.com:amitporwal107/nivesh.ai.git ~/nivesh.ai   # if not already
sudo bash ~/nivesh.ai/deploy/cloudpe/nidp-vm/deploy.sh --setup
exit
bash /opt/nidp/dev-repo/nivesh.ai/deploy/cloudpe/nidp-vm/deploy.sh --migrate
# feeds: only after the first deploy is healthy
sudo bash /opt/nidp/dev-repo/nivesh.ai/deploy/cloudpe/nidp-vm/deploy.sh --setup --install-cron
```

`--setup` installs Docker (and Python 3.11 on the NIDP VM), creates `/opt/...` dirs, clones the
repo, and generates env files with fresh random DB passwords. Existing env files are never
overwritten. The app VM gets a **self-signed** TLS cert at `/opt/nivesh/ssl/` until a Cloudflare
Origin cert is installed there.

## 2. GitHub Actions

Create a **CI-only** SSH keypair (not your personal key):

```bash
ssh-keygen -t ed25519 -C "github-actions-cloudpe" -f cloudpe_ci -N ""
```

Append `cloudpe_ci.pub` to `/home/deploy/.ssh/authorized_keys` on **both** VMs. Then in
GitHub → repo → Settings → Secrets and variables → Actions:

| Kind | Name | Value |
|---|---|---|
| Secret | `CLOUDPE_SSH_KEY` | contents of `cloudpe_ci` (private key) |
| Secret | `CLOUDPE_SSH_USER` | `deploy` |
| Secret | `CLOUDPE_APP_HOST` | `45.64.105.88` |
| Secret | `CLOUDPE_NIDP_HOST` | `45.64.105.224` |
| Secret (optional) | `CLOUDPE_APP_FINGERPRINT`, `CLOUDPE_NIDP_FINGERPRINT` | `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` on each VM (SHA256 value) |
| Variable | `CLOUDPE_DEPLOY_ENABLED` | `true` — the workflows do nothing until this is set |

Then delete the local `cloudpe_ci` private key file.

**Triggers:** push to `dev` (app: backend/frontend/app deploy files; NIDP: `backend/nidp/**`),
or run manually from the Actions tab (branch, rebuild mode, migrations).
On push the app workflow rebuilds only what changed (backend, frontends, or everything).

## Manual deploy (same thing CI runs)

```bash
bash /opt/nivesh-staging/repo/deploy/cloudpe/app-vm/deploy.sh [--backend-only|--frontend-only] [--migrate]
bash /opt/nidp/dev-repo/nivesh.ai/deploy/cloudpe/nidp-vm/deploy.sh [--migrate]
```

Each run ends with health checks and fails loudly if they do not pass:
app — `/api/healthz`, `/v2/`, `/v5/` through the edge nginx; NIDP — DaaS and Query API `/health`.

## Known gaps (not handled by these scripts)

- **Secrets:** SMTP, Google OAuth, CASParser, Telegram etc. lived in GCP. Add them to
  `/opt/nivesh-staging/.env.staging` / `/opt/nidp-staging/nidp.env` by hand; until then those
  features are degraded.
- **App → NIDP link:** the app still points at `staging-data.niveshcopilot.com`. Once NIDP is
  exposed (nginx + TLS + DNS on `cloudpe2`), set `CLOUDPE_NIDP_DAAS_URL` / `CLOUDPE_NIDP_QUERY_URL`
  in `.env.staging` if the URL differs.
- **Public access:** DNS/Cloudflare, real TLS certs and firewall rules are manual and not done.
- **NSE:** on GCP, NSE traffic went through a proxy because NSE blocks some cloud IPs. Check from
  `cloudpe2` before relying on NSE feeds:
  `curl -s -o /dev/null -w '%{http_code}\n' -A 'Mozilla/5.0' https://www.nseindia.com/`
- **Data:** all databases start empty; NIDP data rebuilds as feeds run.
- **Old GCP workflows** (`deploy-*-staging.yml`, `deploy-nidp*.yml`, …) still fire on push and will
  fail while GCP is unreachable. Disable them in the Actions tab if the noise is a problem.
- **Python on the NIDP VM:** the venv is built with host Python 3.11 (Ubuntu) and mounted into
  `python:3.11-slim` containers (Debian). Packages compiled from source on the host could fail to
  load in the containers; wheels from PyPI are fine. Watch the first deploy's health output.
