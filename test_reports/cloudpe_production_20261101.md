# CloudPe production environment — verification report

Date: 2026-11-01 (work 2026-10-31 22:00 IST → 2026-11-01 03:10 IST)
Scope: new production environment (app + NIDP on one CloudPe VM `45.64.105.249`), GitHub Actions for it, Cloudflare cutover.
Branch: `feat/prod-cloudpe` (PR into `dev`). Code under test: commit `99731f29` + later doc/script commits (no product code changed — only `deploy/`, `.github/`, `docs/`).
Status: **IN PROGRESS** — production is serving; the GitHub Actions deploy path is NOT yet exercised (see UNVERIFIED).

## What was built

| Item | Where |
|---|---|
| Prod compose (app), edge nginx, app cron | `deploy/cloudpe-prod/app/` |
| Prod compose (NIDP), Query API unit, restore script | `deploy/cloudpe-prod/nidp/` |
| Host nginx (single :80/:443 listener, Cloudflare-only allow-list) | `deploy/cloudpe-prod/edge/nginx-prod.conf` |
| bootstrap / deploy-app / deploy-nidp / ci-deploy (main only) | `deploy/cloudpe-prod/*.sh` |
| DNS cutover with backup + rollback | `deploy/cloudpe-prod/cloudflare-cutover.py` |
| Workflows: backend, frontend, NIDP → prod VM; old NIDP cron workflow retired | `.github/workflows/deploy-{backend,frontend,nidp,nidp-cron}.yml` |
| Docs | `docs/DEVOPS_ENVIRONMENTS.md`, `docs/BUILD_AND_DEPLOYMENT.md`, `deploy/cloudpe-prod/README.md` |

## Test cases (authored before the checks were run)

| # | Case | Result |
|---|---|---|
| T1 | Host bootstrap completes; Docker ≥ 2.33 compose, Python 3.11, nginx, users, checkout, venv | PASS |
| T2 | App stack builds and passes smoke checks through the host nginx (`/api/healthz`, `/api/readyz`, `/v2/`, `/v5/`) | PASS |
| T3 | Staging app data cloned: every Postgres table and Mongo collection matches | PASS (1 live-growing collection +1 row) |
| T4 | NIDP warehouse cloned: all tables present, counts match, hypertables readable | PASS after two fixes (below) |
| T5 | NIDP DaaS + Query API healthy; app tokens accepted, wrong/missing token rejected | PASS |
| T6 | Origin locked to Cloudflare; real Origin CA cert served | PASS |
| T7 | Public end-to-end through Cloudflare after DNS flip | PASS (one transient 522, see T7) |
| T8 | Authenticated app endpoint that depends on NIDP returns the same shape as staging | PASS |
| T9 | Feed sources reachable from the prod IP; cron wrapper runs a feed end to end | PASS (BSE API 403 — same as staging) |
| T10 | CI deploy path refuses non-`main` and any other sudo command | PASS |
| T11 | GitHub Actions workflows deploy to the VM | **NOT RUN** (they trigger on `main`) |

## Evidence (real output, abbreviated)

**T2** (`deploy-app.sh`):
```
[prod-app-deploy] OK  /api/healthz via host nginx :443
[prod-app-deploy] OK  /api/readyz via host nginx :443
[prod-app-deploy] OK  /v2/ → 200
[prod-app-deploy] OK  /v5/ → 200
```

**T3** exact counts, staging vs prod: Postgres `portfolio_ingestion` 66 tables, diff empty. Mongo 79 collections, only difference
`truedata_shadow_minutes 2022 (staging) vs 2021 (prod)` — a collection staging was still writing to after the dump.
`secrets:staging` copied to `secrets:production` (3 secret names).

**T4** — two real defects found and fixed (both in `nidp/restore.sh`, which was derived from staging's):
1. `vector` created in `public`, the dump expects `nidp.vector` → `document_chunks`, `embedding_cache` did not restore. Fixed (`CREATE EXTENSION vector SCHEMA nidp`), tables re-loaded: `document_chunks` 2,178,585 rows.
2. Parallel `pg_restore` lost the TimescaleDB chunk catalog (circular FK): every hypertable showed 0 chunks and `nidp.prices_eod` read 0 rows with a 14 GB database.
   Before: `catalog.dimension_slice 0 / chunk 0 / chunk_constraint 0 / prices_eod 0`. Fix: data-only reload of those three tables with
   `--disable-triggers` inside `timescaledb_pre_restore()`/`post_restore()`. After: `269 / 269 / 538 / prices_eod 1988490` — identical to staging.
Final comparison, all 175 tables: **163 identical**; 12 differ with prod *lower* than staging (feeds that kept writing on staging after the dump), e.g.
`nidp.document_chunks 2195791 vs 2178585`, `nidp.job_log 10401 vs 10375`, `nidp.daas_usage_log 830381 vs 828068`. No table is higher on prod or missing.

**T5**
```
DaaS /daas/v1/prices/latest/RELIANCE (app key)  → HTTP 200  {"data":{"as_of_date":"2026-10-30","symbol":"RELIANCE",...,"close_price":1164.9,...
DaaS with a wrong key                           → HTTP 401
Query API /query/feeds (app bearer token)       → HTTP 200 91197B
Query API without a token                       → HTTP 401
```

**T6** from a non-Cloudflare host: `https://45.64.105.249/` → 403, `http://45.64.105.249/` → 301; served cert `issuer=CloudFlare Origin SSL Certificate Authority`, `DNS:*.niveshcopilot.com, DNS:niveshcopilot.com`, expires 2041-10-27.

**T7** after repointing the 7 A records (`data`, apex, `www`, `api`, `admin`, `assets`, `work`; backup in `~/cf-prod-dns-backup-20261101.json`):
```
https://niveshcopilot.com/api/healthz      200 {"status":"ok","service":"portfolio_ingestion","version":"0.1.0","env":"production"}
https://niveshcopilot.com/api/readyz       200 {... "postgres":"ok","mongo":"o...
https://niveshcopilot.com/v2/  200   https://niveshcopilot.com/v5/  200   https://www.niveshcopilot.com/api/healthz 200
https://data.niveshcopilot.com/health 200
https://data.niveshcopilot.com/daas/health   522 (first call, 19.7 s) → 200 {"ok":true,"service":"nidp-daas-api","db_ok":true} on every later call
https://data.niveshcopilot.com/query/health  200 {"ok":true,"service":"nidp-query-api","db_ok":true}
https://staging.niveshcopilot.com/api/healthz 200 ... "env":"staging"   (unaffected)
```
The single 522 happened seconds after the DNS change (edge still resolving the old origin) and did not recur in the 6 later calls to the two data hosts.

**T8** `/api/auth/me` with the owner's cloned session → 200 (sessions survived the clone). `/api/markets/home` → 200, identical field structure to staging (0 differing paths of 11, no error fields).
First calls were slow (20.4 s, 6.9 s) because the caches were cold; calls 3–6 took 0.06–0.10 s. Backend→NIDP latency via Cloudflare, measured in both backend containers: prod 0.38 s then 0.03 s; staging 0.36 s then 0.04 s.

**T9** from the prod VM: NSE cash and F&O bhavcopy archives → 200 (staging control: 200); `api.bseindia.com` → 403 on prod and on staging (the known `BSE_PROXY_URL` gap, not a regression).
`sudo -u nidp /opt/nidp/run_service.sh macro_calendar` → exit 0, `macro_calendar upserted 31 rows`, job_log `PARTIAL 31/31` — byte-for-byte the same outcome as staging's 02:30 run (`PARTIAL 31/31`).
Cron installed: `/etc/cron.d/nidp` 54 active entries, `/etc/cron.d/nivesh-prod` 9. docker, nginx, cron, nidp-query-api enabled at boot; all containers `unless-stopped`.

**T10**
```
ci-deploy.sh app dev (as ci-deploy)  → [ci-deploy] FATAL: production deploys only 'main' (got 'dev')   exit=2
sudo -n /usr/bin/id                  → sudo: a password is required
```

## UNVERIFIED / not done

- **T11 — the GitHub Actions deploy.** The prod workflows trigger on pushes to `main`, and `main` is 606 commits behind `dev` (and 34 ahead). A deploy of today's `main` would put old code on a database cloned from `dev`'s schema, so it was deliberately NOT run. The SSH login and sudo scope the workflows use were tested by hand (T10); the workflow files themselves are only YAML-validated. Needs: this PR merged to `dev`, then a `dev → main` release PR, then one `workflow_dispatch` run watched.
- **Reboot survival** — enabled-at-boot and restart policies were inspected, the VM was not rebooted.
- **Backups** — none scheduled for production (the snapshot script only knows the staging containers). A single copy of prod data exists.
- **Chat (Copilot LLM)** — set to `openai`; the Claude Code gateway is not installed on this VM. Not exercised.
- **Broker / Google sign-in** — redirect URLs and the new server IP (`45.64.105.249`) must be registered with Zerodha, ICICI Direct, Motilal and the Google OAuth client; not possible from here.
- `restore.sh`'s new catalog check was verified only by running its two queries on the real database (269 = 269); the failing branch was not exercised.
- Secrets handling: the Cloudflare API token and a Trendlyne MCP token were printed into the working session's output by mistake earlier in the session; rotation is advisable.
