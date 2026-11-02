# BUILD_AND_DEPLOYMENT.md — Nivesh.ai / NIDP

> Canonical detail: `TECHNICAL_ARCHITECTURE.md` §12 (Cloud Build), §14 (DevOps), §17 (Jenkins).
> Honesty rule: only commands that actually run today. These verify commands are mirrored
> in the role checklists and the hook `clear-if-verified.sh` regex — keep all three in sync.

## Prerequisites
Python 3.11, Node + yarn, Docker + Docker Compose. GCP access (`gcloud`) for Cloud Run/Build.

## Branch strategy (hard rule)
`feat/* → dev → main`. Commit to `dev`; `main` only via PR merge. Never force-push to `main`.
Never `--no-verify`.

## Build / test / verify commands

| Purpose | Command |
|---|---|
| App smoke suite (12 tests) | `make verify` |
| Frontend build (V2) | `REACT_APP_BACKEND_URL=https://niveshcopilot.com PUBLIC_URL=/v2 CI=false yarn build` |
| Frontend deps | `yarn install --frozen-lockfile --network-timeout 600000` |
| Backend syntax | `python3 -m py_compile backend/server.py` (+ all `.py`) |
| E2E | `playwright test` |
| Unit/integration | `pytest` (`pytest --cov` for coverage) |
| NIDP ingester local test | `./test_locally.sh <service>` |
| App migrations | `cd /app/backend && python -m scripts.post_deploy_migrate` |

> Nothing is "done" until the relevant command ran AND its real output is shown (CONTEXT §1, §1b).

## CI/CD split (TECHNICAL_ARCHITECTURE §12, §17)
- **GitHub Actions** deploy production (push to `main`) and staging (push to `dev`) over SSH to the CloudPe VMs — see
  `deploy/cloudpe-prod/README.md` and `deploy/cloudpe/README.md`. The Jenkins line below is the GCP-era setup.
- **Jenkins** (on GitHub push, path-aware): Nivesh app (frontend+backend) + NIDP VM services (DaaS/Query API + cron). Health-checks `/api/health` (200) + NIDP `/health` after deploy.
- **GCP Cloud Build**: 28 NIDP ingester Cloud Run jobs + DaaS Cloud Run service + DB migrations (per-path triggers).

## Deploy

### Staging (SSH to nivesh-app-vm, run as sudo)
```bash
ssh -i ~/.ssh/google_compute_engine aporwal107_gmail_com@34.47.250.214 \
  "cd /opt/nivesh-staging/repo && sudo bash deploy/nivesh-staging/redeploy-staging.sh"
```
Steps: git reset --hard origin/dev → docker compose up → wait healthy → reload nginx → smoke `{"status":"ok"}`.

### Production (CloudPe prod VM; app and NIDP on one host — `deploy/cloudpe-prod/README.md`)
```bash
sudo bash /opt/nivesh/repo/deploy/cloudpe-prod/deploy-app.sh main                  # full
sudo bash /opt/nivesh/repo/deploy/cloudpe-prod/deploy-app.sh main --frontend-only  # CSS/JS
sudo bash /opt/nivesh/repo/deploy/cloudpe-prod/deploy-app.sh main --backend-only   # Python, no new deps
sudo bash /opt/nivesh/repo/deploy/cloudpe-prod/deploy-nidp.sh main [--migrate]     # NIDP stack
```
Steps (app): `git reset --hard origin/main` → docker build → `docker compose up -d` → wait healthy → reload nginx →
smoke `/api/healthz`, `/api/readyz`, `/v2/`, `/v5/` through the host nginx on loopback.
Steps (NIDP): fetch+reset → pip deps → optional `nidp.cli migrate` → TimescaleDB, DaaS container, Query API unit →
smoke `/daas/health` + `/query/health` → sync `/etc/cron.d/nidp`.
GitHub Actions deploy on push to `main` via `deploy/cloudpe-prod/ci-deploy.sh` (main only).

### NIDP staging VM
```bash
sudo bash /opt/nidp/dev-repo/nivesh.ai/deploy/cloudpe/nidp/deploy.sh dev [--migrate]   # staging
```

## Environments & health
| Env | App health | NIDP health |
|---|---|---|
| Local | `localhost:8001/api/health` | `localhost:8083/health`, `localhost:8090/health` |
| Staging | `https://staging.niveshcopilot.com/api/healthz` | (NIDP staging CNAME not yet live) |
| Prod | `https://niveshcopilot.com/api/healthz` | `https://data.niveshcopilot.com/daas/health` + `/query/health` |

## Rollback (TECHNICAL_ARCHITECTURE §14.6)
```bash
# App
git -C /opt/nivesh/repo checkout <SHA> && bash /opt/nivesh/deploy/deploy.sh
# NIDP VM
sudo -u nidp /opt/nidp/repo/backend/nidp/deploy/vm/rollback.sh <git-sha>
# NIDP Cloud Run (DaaS)
gcloud run services update-traffic nidp-daas-api --to-revisions=<REV>=100 --region=asia-south1 --project=niveshdataintelligence
# DB (emergency) — SNAPSHOT FIRST, then: python -m alembic downgrade -1
```
Rollback is also verified, not assumed — confirm health after.

## Release checklist
- [ ] Verified on **staging** with real output (per role checklist).
- [ ] Reached `main` via PR; CI green on the release commit.
- [ ] Migrations forward-safe; destructive ones signed off with rollback note.
- [ ] Health endpoints green post-deploy; Grafana Job Health checked.
- [ ] Rollback path confirmed available.
