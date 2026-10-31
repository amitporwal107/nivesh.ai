# Production on CloudPe

Build and deploy scripts for running **production** — the Nivesh app *and* the NIDP stack — on
one CloudPe VM. Staging (`deploy/cloudpe/`) keeps its two VMs and is not touched by anything here.

| | |
|---|---|
| VM | `45.64.105.249` (4 vCPU / 15 GB / 100 GB, Ubuntu 24.04) — previously the research VM; its Move-odds nightly cron is paused (`crontab -l` shows `# PAUSED 2026-10-31`, backup in `/root/crontab.research.bak-20261031`), `/app/research` is untouched |
| Public hostnames | `niveshcopilot.com` (+ `www`, `api`, `admin`, `assets`, `work`) → the app · `data.niveshcopilot.com` → NIDP DaaS `/daas/` + Query API `/query/` |
| Deploy branch | `main` only (`feat/* → dev → main`) |

## Layout on the VM

```
host nginx  :80/:443   ── the ONLY public listener (Cloudflare-only allow-list, Origin CA cert)
  ├─ data.niveshcopilot.com  /daas/ → 127.0.0.1:8083 (nidp-daas-api, Docker)
  │                          /query/ → 127.0.0.1:8090 (nidp-query-api, systemd)
  └─ everything else         → 127.0.0.1:8444 (nivesh-edge, Docker) → backend :8001 / frontends
Docker, project nivesh-prod: nivesh-{postgres,mongo,redis,backend,frontend,frontend-v5,edge}
Docker, project nidp-prod:   nidp-{postgres (TimescaleDB, 127.0.0.1:5433),daas-api}
cron: /etc/cron.d/nivesh-prod (app jobs)   /etc/cron.d/nidp (NIDP feeds, generated from the staging cron)
```

| Path | What |
|---|---|
| `/opt/nivesh/repo` | the **one** git checkout; `/opt/nidp/repo` is a symlink to it, so both stacks always run the same commit |
| `/opt/nivesh/.env.prod`, `/opt/nidp/nidp.env` | secrets (mode 600, never in git); generated from the staging env files |
| `/opt/nivesh/data/*`, `/opt/nidp/data/postgres` | database volumes |
| `/opt/nivesh/dumps`, `/opt/nidp/dumps` | restore inputs (700) |
| `/opt/nidp/venv` | Python 3.11 venv the DaaS container and cron feeds import from |

Everything is the staging design with the names changed; the differences that matter:

- **One VM, one edge.** Staging gives each stack its own VM and nginx. Here the host nginx owns 443 and
  proxies the app to the edge container on loopback (`edge/nginx-prod.conf`).
- **`APP_ENV=production`**, Mongo database `nivesh_prod`, hostnames `niveshcopilot.com` /
  `data.niveshcopilot.com`. The backend reaches NIDP over its public HTTPS URL, exactly as staging does.
- **No default for `PI_PAN_ENCRYPTION_KEY`** — a missing key fails the deploy instead of silently using a dev key.
- **Fresh internal secrets.** DB passwords, `NIDP_QUERY_API_TOKEN`, `NIDP_DAAS_INTERNAL_TOKEN` and
  `PI_ADMIN_TOKEN` are new; external credentials and the two data-encryption keys
  (`PI_PAN_ENCRYPTION_KEY`, `PII_ENCRYPTION_KEY`) are copied from staging because cloned rows are encrypted with them.
- `COPILOT_LLM_PROVIDER=openai`: the Claude Code gateway (`deploy/cloudpe/app/claude-gateway`) needs a Claude login
  on the VM and is not installed here.

## Files

| File | Purpose |
|---|---|
| `lib.sh` | constants + helpers (sources `deploy/cloudpe/lib/common.sh`) |
| `bootstrap.sh` | one-time host setup: packages, Docker, Python 3.11, users, dirs, checkout, venv, nginx, Query API unit |
| `deploy-app.sh` | pull, build, start the app stack, install the app cron, smoke-check through nginx |
| `deploy-nidp.sh` | pull, start TimescaleDB + DaaS + Query API, reload nginx, health-check, sync the feed cron |
| `nidp/restore.sh` | TimescaleDB-aware `pg_restore` of a dump into the prod warehouse |
| `ci-deploy.sh` | the single command GitHub Actions runs over SSH (main only, serialized by a lock) |
| `cloudflare-cutover.py` | `plan` / `apply` / `rollback` for the 7 production A records (fixed allow-list, backup file, origin check) |
| `app/`, `nidp/`, `edge/` | compose files, edge nginx confs, Query API unit, app cron |

## First-time setup (what was done on 2026-10-31)

```bash
# 1. On the VM (as root), from a copy of deploy/cloudpe-prod + deploy/cloudpe/lib:
bash deploy/cloudpe-prod/bootstrap.sh --tsdb-tag 2.26.4-pg16 --ci-pubkey ci.pub \
     --freeze pip-freeze.txt --cert origin.crt --key origin.key        # or --self-signed for origin testing
#    First run prints the deploy key → add it to the GitHub repo as a READ-ONLY deploy key → re-run.
# 2. Env files: derive from the staging ones (internal secrets regenerated, see above).
# 3. Data (cloned from staging, 2026-10-31):
#      NIDP:  pg_dump -Fc --compress=zstd:3 on the staging NIDP container, streamed to /opt/nidp/dumps/
#             → bash deploy/cloudpe-prod/nidp/restore.sh /opt/nidp/dumps/<file>
#      app:   pg_dump -Fc of portfolio_ingestion + mongodump --db nivesh_staging --archive --gzip
#             → pg_restore --no-owner --no-privileges; mongorestore --nsFrom 'nivesh_staging.*' --nsTo 'nivesh_prod.*'
#             → copy the `secrets:staging` doc to `secrets:production` in nivesh_prod.system_config
#             → tar of /opt/nivesh-staging/data/app into /opt/nivesh/data/
# 4. bash deploy/cloudpe-prod/deploy-nidp.sh <branch> --install-cron
#    bash deploy/cloudpe-prod/deploy-app.sh  <branch>
# 5. DNS (from a host that has the Cloudflare token):
#      python3 -I deploy/cloudpe-prod/cloudflare-cutover.py plan
#      python3 -I deploy/cloudpe-prod/cloudflare-cutover.py apply --backup ~/cf-prod-dns-backup-<date>.json --yes
#    Rollback: ... rollback --backup <that file> --yes   (the old addresses are the dead GCP ones, so a rollback
#    only restores the previous state, not a working site).
```

**Origin certificate.** Cloudflare SSL mode is *Full (strict)*, so the VM serves a Cloudflare Origin CA certificate for
`niveshcopilot.com` + `*.niveshcopilot.com` (created through the API from a CSR generated on the VM; expires 2041-10-27).
The private key exists only on the VM (`/etc/nginx/ssl/prod.key`, copy in `/root/origin/`). Staging has its own cert for
`staging.niveshcopilot.com` only. To renew: new CSR on the VM → `POST /certificates` → replace `/etc/nginx/ssl/prod.crt`
→ `systemctl reload nginx`.

**Things that behaved differently from what the staging scripts suggest** (found during the 2026-10-31 clone):
- `pg_restore --jobs N` loses the TimescaleDB chunk catalog (`dimension_slice`, `chunk`, `chunk_constraint`: circular
  foreign keys), leaving every hypertable with 0 chunks and `prices_eod` reading 0 rows although the DB is full size. Fix:
  re-load those three tables with `pg_restore --data-only --disable-triggers -n _timescaledb_catalog -t dimension_slice -t chunk -t chunk_constraint`
  inside `timescaledb_pre_restore()` / `timescaledb_post_restore()`. `nidp/restore.sh` does not repair this itself:
  it compares the catalog with the restored chunk tables at the end and exits 5 with this exact command if they differ.
- The `vector` extension must live in schema `nidp` (see `nidp/restore.sh`).

## Routine deploys

Push to `main` → the three workflows (`deploy-backend.yml`, `deploy-frontend.yml`, `deploy-nidp.yml`) SSH in as
`ci-deploy` and run `sudo /usr/bin/bash /opt/nivesh/repo/deploy/cloudpe-prod/ci-deploy.sh app|nidp main [flags]`.
Repository secrets: `PROD_VM_HOST`, `PROD_SSH_USER` (`ci-deploy`), `PROD_SSH_KEY` — separate from the `STAGING_*` ones.
By hand: `sudo bash /opt/nivesh/repo/deploy/cloudpe-prod/deploy-app.sh main [--backend-only|--frontend-only] [--migrate]`
and `deploy-nidp.sh main [--migrate]`.

`deploy-nidp-cron.yml` is retired: it installed the GCP-era cron over `/etc/cron.d/nidp`.

## Rollback

The normal path is a revert PR into `main` (CI redeploys). For an emergency, push a branch at the last good
commit and deploy it by hand — the scripts take a **branch name**, not a SHA, and `ci-deploy.sh` accepts only `main`:

```bash
git push origin <good-sha>:refs/heads/rollback/<date>
sudo bash /opt/nivesh/repo/deploy/cloudpe-prod/deploy-app.sh  rollback/<date>
sudo bash /opt/nivesh/repo/deploy/cloudpe-prod/deploy-nidp.sh rollback/<date>
```
Database changes are not rolled back by this; restore from a snapshot if a migration has to be undone.

## Not covered / known gaps

- **Backups:** `deploy/cloudpe/backup/` is wired to the staging containers only. Until `prod-app` / `prod-nidp`
  targets exist there, production has **no scheduled DB snapshot** and a single copy of its data.
- Grafana/Loki, the code-server IDE (`ide.niveshcopilot.com`) and the Android APK build stay unmoved (as on staging).
- `backend/nidp/services/daas_api/tpd_preview_loader.py` and `services/kite_bars/collect.py` hardcode the staging
  container/DB names (`nidp-postgres-staging`, `nidp_staging`); they are manual tools and will not work against prod.
- Broker apps (Zerodha, ICICI Direct, Motilal) must have the production redirect URLs and this VM's public IP
  (`45.64.105.249`) registered; Google OAuth needs `https://niveshcopilot.com` redirect URIs.
- Other workflows still targeting the old GCP hosts: `nidp-run-service.yml`, `nidp-db-backup.yml`, `nidp-rollback.yml`,
  `deploy-grafana.yml`, `android-release.yml`.
