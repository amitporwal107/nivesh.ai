# CloudPe staging migration — verification report

Date: 2026-10-12 · Branch: `dev` @ `d1135c81` · Target: **staging only**
Scope: `deploy/cloudpe/` scripts, six NIDP migration fixes, `nidp.cli migrate` recording fix.

GCP access was revoked during this work, so staging was **rebuilt empty** from the
migrations; nothing was restored from GCP. All output below is from commands run this session.

## Test cases and results

| # | Case | Result |
|---|---|---|
| 1 | Merged compose configs render; no `pkg.dev`, `10.160.`, `nidp-bridge`, `/opt/nivesh/ssl` | PASS (Compose 2.33.1 and 2.39.1, exit 0; 2.32.4 rejects the base file) |
| 2 | `bash -n` + shellcheck (warning level) on all scripts | PASS (exit 0) |
| 3 | App VM bootstrap | PASS (exit 0) |
| 4 | App VM `docker compose build` (3 images) | PASS (exit 0) |
| 5 | App VM deploy incl. `--migrate` and edge smoke checks | PASS (exit 0) |
| 6 | NIDP VM bootstrap | PASS (exit 0) |
| 7 | All 139 NIDP migrations apply to an empty database | PASS (`applied=139 failed=0`) |
| 8 | Second `migrate` run is a no-op | PASS (`applied=0 already-applied=139 failed=0`) |
| 9 | NIDP VM deploy: DaaS, Query API, nginx health | PASS (exit 0) |
| 10 | Origin refuses non-Cloudflare clients | PASS (403 on app :443/:8443 and NIDP :443 from the other VM) |
| 11 | Origin certs served are the new Cloudflare Origin CA certs | PASS |
| 12 | Cloudflare cutover of `staging` and `staging-data` | PASS (apply exit 0; backup written) |
| 13 | Public URLs through Cloudflare | PASS (7/7 HTTP 200) |
| 14 | App backend reaches NIDP DaaS over the public hostname, authenticated | PASS (HTTP 200) |

## Evidence (real output)

App deploy (case 5):
```
[app-deploy] nivesh-staging-app-backend healthy after 1 checks.
Migrations done.
{"status":"ok","service":"portfolio_ingestion","version":"0.1.0","env":"staging"}
[app-deploy] OK  /api/healthz via edge :443
{"status":"ok","service":"portfolio_ingestion","version":"0.1.0","env":"staging","postgres":"ok","mongo":"ok","migration_version":"004_audit_log.sql","pg_pool_size":1}
[app-deploy] OK  /api/readyz via edge :443
[app-deploy] OK  /v2/ → 200
[app-deploy] OK  /v5/ → 200
deploy exit=0
```

Migration CLI against a fresh database, twice (cases 7, 8):
```
run 1: exit=0  applied=139  already-applied=0  failed=0
run 2: exit=0  applied=0  already-applied=139  failed=0
recorded in probe schema_migrations: 139
```

NIDP deploy (case 9):
```
{"ok":true,"service":"nidp-daas-api","db_ok":true,"db_latency_ms":4,"error":null}
[nidp-deploy] OK  DaaS API :8084/health
{"ok":true,"service":"nidp-query-api","db_ok":true,"db_latency_ms":3,"error":null}
[nidp-deploy] OK  Query API :8091/health
[nidp-deploy] OK  nginx /health
[nidp-deploy] OK  nginx /daas/health
[nidp-deploy] OK  nginx /query/health
deploy exit=0
```

Public, after the DNS change (case 13):
```
https://staging.niveshcopilot.com/api/healthz        → HTTP 200  {"status":"ok","service":"portfolio_ingestion","version":"0.1.0","env":"staging"}
https://staging.niveshcopilot.com/api/readyz         → HTTP 200  {"status":"ok",...,"postgres":"ok","mongo":"ok",...}
https://staging.niveshcopilot.com/v2/                → HTTP 200
https://staging.niveshcopilot.com/v5/                → HTTP 200
https://staging-data.niveshcopilot.com/health        → HTTP 200  ok-staging
https://staging-data.niveshcopilot.com/daas/health   → HTTP 200  {"ok":true,"service":"nidp-daas-api","db_ok":true,...}
https://staging-data.niveshcopilot.com/query/health  → HTTP 200  {"ok":true,"service":"nidp-query-api","db_ok":true,...}
```

## Data test

- App Postgres: tables per schema — analytics 1, dq 6, events 1, features 1, graph 2, portfolio_ingestion 6, public 43, ref 1. No user data (empty rebuild).
- NIDP: `nidp.schema_migrations` 139 rows; 18 hypertables; `nidp.v_feed_status` lists 22 feeds; `nidp.validation_findings` BLOCK = 0; `nidp.prices_eod` = 0 rows.
- The NIDP warehouse holds **no market data**: feeds have not run. `mutual_fund_metadata.v3_scored_at` is not populated for the same reason.

## Not verified

- Feed ingestion on the new VM (the staged crontab is the repo copy; feed lines are commented out) and NSE/BSE reachability from the CloudPe IP.
- Playwright against staging (not run).
- Login, CAS upload, Gmail OAuth and email: `CASPARSER_API_KEY`, `GOOGLE_CLIENT_ID/SECRET` and `SMTP_*` are not set.
- `app/restore.sh`, `nidp/restore.sh`, `migrate/capture-gcp-*.sh` and `cloudflare-cutover.sh rollback` have never been executed.
- The NIDP venv has `requirements.txt` only; modules importing undeclared packages (pyarrow, duckdb, yfinance) are untested.
- GitHub workflows `deploy-*-staging.yml` still target the GCP VMs.

## Verdict: PASS (infrastructure and deploy path on CloudPe staging) — product data and the items above remain IN PROGRESS
