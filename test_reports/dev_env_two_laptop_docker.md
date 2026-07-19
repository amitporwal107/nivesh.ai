# Functionality Verification Report — Two-Laptop Dockerised Dev Environment

- **Branch:** feat/copilot-backtest
- **Date:** 2026-07-19
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** local dev laptops (laptop 1 = nivesh-app-vm replica, laptop 2 = nidp-stack-vm replica)
- **Changed areas:** backend routes/services: no (infra only) · frontend src: no (infra only)

## Summary

Replicating the two GCP VMs as Docker Compose stacks runnable on two Windows laptops
(Docker Desktop + WSL2), connected over the same LAN by direct IP.

- **Laptop 1** — `nivesh-app-vm`: FastAPI backend, V2 frontend, frontend-v5, MongoDB,
  Postgres (app/`portfolio_ingestion`), Redis, edge nginx on **:3000** (cloudflared origin).
- **Laptop 2** — `nidp-stack-vm`: TimescaleDB+pgvector, DaaS API, Query API, MinIO, Redis,
  Prometheus/Grafana/Loki/Promtail/Alertmanager, feed ingesters on cron, AI tier
  (OCR + ffmpeg + faster-whisper + classifiers).

Data strategy: restore a real `pg_dump` from GCP (nidp DB measured at **6473 MB** live).
Secrets: local git-ignored `.env` files from generated templates.

**Scope of this report:** the infrastructure stands up and the services are reachable and
correctly wired. It does NOT re-verify app features themselves (no product code changed).

## Test Cases

> Authored UP FRONT — before writing any compose/Dockerfile. One row per case.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | L2 infra | `docker compose -f docker-compose.nidp.yml up -d` brings up all NIDP services | e2e | every container reports `healthy` (or `running` where no healthcheck) | PENDING |
| TC-2 | L2 db | TimescaleDB container has required extensions | api | `timescaledb` **and** `vector` present in `pg_extension` | PENDING |
| TC-3 | L2 db | NIDP migration chain applies to an empty DB | e2e | runner completes; no migration left in failed state | PENDING |
| TC-4 | L2 api | DaaS API responds | api | `GET /health` (or `/docs`) → HTTP 200 | PENDING |
| TC-5 | L2 api | Query API responds and rejects a bad token | api/failure | valid token → 200; missing/wrong token → 401/403 | PENDING |
| TC-6 | L2 restore | GCP dump restores incl. TimescaleDB hypertables | e2e | `timescaledb_information.hypertables` non-empty after restore; row counts match source within tolerance | PENDING |
| TC-7 | L2 obs | Observability stack live | api | Prometheus targets UP; Grafana `/api/health` 200; Loki ready | PENDING |
| TC-8 | L2 ai | AI-tier host deps present in image | unit | `tesseract --version`, `pdftoppm -v`, `ffmpeg -version` all exit 0 | PENDING |
| TC-9 | L2 ai | faster-whisper model loads and transcribes | e2e | short sample audio → non-empty transcript text | PENDING |
| TC-10 | L2 cron | Scheduler container holds the real feed schedule | unit | crontab in container matches `/etc/cron.d/nidp` job set (~25 jobs) | PENDING |
| TC-11 | L2 cron | A single ingester runs on demand | e2e | `run_service.sh <feed>` exits 0 and writes a `nidp.job_log` row | PENDING |
| TC-12 | L1 infra | `docker compose -f docker-compose.app.yml up -d` brings up the app stack | e2e | all containers healthy | PENDING |
| TC-13 | L1 db | App Postgres + Mongo initialise with app schema | e2e | app migrations applied; Mongo `nivesh` user can authenticate | PENDING |
| TC-14 | L1 api | Backend serves | api | `GET /docs` → HTTP 200; `GET /api/health` → 200 | PENDING |
| TC-15 | L1 ui | V2 frontend and frontend-v5 both served | e2e | `GET /` → 200 HTML; `GET /v5/` → 200 HTML | PENDING |
| TC-16 | L1 edge | Edge nginx serves the whole app on **:3000** (cloudflared origin) | e2e | `GET localhost:3000/` 200; `/api/*` proxied to backend; `/v5/` served | PENDING |
| TC-17 | X-laptop | Laptop 1 backend reaches laptop 2 DaaS over LAN | e2e | from L1 backend container: DaaS `/health` via `$NIDP_HOST` → 200 | PENDING |
| TC-18 | X-laptop | Wrong/stale `NIDP_HOST` fails loudly, not silently | failure | connection error surfaced in logs/health, no silent empty-data fallback | PENDING |
| TC-19 | Secrets | No secret values are committed | unit | `.env` git-ignored; only `.env.example` tracked; `git grep` finds no live keys | PENDING |
| TC-20 | Portability | Windows/WSL2 correctness | edge | no host bind-mount paths that break on Windows; CRLF-safe entrypoints; documented resource floor | PENDING |

## Deviations from the GCP VMs (intentional, documented)

| GCP VM behaviour | Local replica | Why |
|---|---|---|
| DaaS/Query API run as **systemd + host venv** | run as containers | user asked for a Docker install; removes host-venv drift |
| Feed jobs via host `/etc/cron.d/nidp` as user `nidp` | dedicated scheduler container | keeps the laptop host clean |
| Cloudflare tunnel → nginx TLS on 443/8443 | edge nginx on **:3000** | matches the existing cloudflared route `→ localhost:3000` |
| Cross-VM traffic over GCP VPC (MTU 1460) | LAN direct IP via `NIDP_HOST` (MTU 1500) | no GCP VPC locally; MTU pin dropped deliberately |
| Secrets from GSM | local `.env` files | user choice |

## Static / Config Validation (run 2026-07-19, real unedited output)

> This is CONFIG validation only. It proves the artifacts are well-formed.
> It does NOT prove the stacks boot or serve traffic — see "Not yet verified".

- **Compose schema — laptop 2**
  - Command: `docker compose -f docker-compose.nidp.yml config --quiet`
  - Output: `CORE: VALID`
  - With profiles: `docker compose ... --profile feeds --profile kafka config --quiet` → `PROFILES: VALID`
  - Services resolved (16): `alertmanager daas-api grafana loki minio minio-init nginx node-exporter postgres prometheus promtail query-api redis redpanda scheduler schema-registry`
  - Result: **PASS**

- **Shell syntax**
  - Command: `bash -n up.sh restore.sh bin/run-feed.sh`
  - Output: `up.sh OK / restore.sh OK / bin/run-feed.sh OK`
  - Result: **PASS**

- **nginx** — `docker run --rm -v .../nidp.conf:... nginx:1.27-alpine nginx -t`
  - FIRST RUN **FAILED**, and this was a real bug, not a test artifact:
    ```
    [emerg] host not found in upstream "daas-api:8083" in /etc/nginx/conf.d/default.conf:14
    nginx: configuration file /etc/nginx/nginx.conf test failed
    ```
    Static `upstream` blocks resolve at startup, so the edge would crash-loop
    whenever it started before the APIs, and would not follow container
    restarts. Fixed by moving to Docker's embedded resolver (127.0.0.11)
    with `set $upstream_x ...` + `rewrite ... break`, deferring DNS to
    request time.
  - RE-RUN after fix:
    ```
    nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
    nginx: configuration file /etc/nginx/nginx.conf test is successful
    ```
  - Result: **PASS** (after fix)

- **Prometheus** — `promtool check config /p.yml`
  - Output: `SUCCESS: /p.yml is valid prometheus config file syntax`
  - Result: **PASS**

- **Alertmanager** — `amtool check-config /a.yml`
  - Output: `- global config / - route / - 1 inhibit rules / - 1 receivers / - 0 templates`
  - Result: **PASS**

- **Loki** — `loki -config.file=/l.yaml -verify-config`
  - Output: one `level=warn ... global timeout not configured, using default engine timeout ("5m0s")`; no errors, verify passed.
  - Result: **PASS**

- **Promtail** — `promtail -config.file=/p.yaml -check-syntax`
  - Output: `Valid config file! No syntax issues found`
  - Result: **PASS**

## Source-of-truth capture (live VM, 2026-07-19)

Laptop 2 was reconstructed from the RUNNING `nidp-stack-vm` (`hostname` confirmed),
not from docs:

- Extensions that must exist locally: `timescaledb 2.26.4`, `vector 0.8.1`, `postgres_fdw 1.1`, PG `16.13`
  → compose pins `timescale/timescaledb:2.26.4-pg16` (NOT `latest-pg16`).
- 17 hypertables / 586 `_timescaledb_internal` chunk tables.
- `nidp` schema on prod: 72 BASE TABLE + 38 VIEW.
- Feed schedule: 49 jobs in `/etc/cron.d/nidp` → replicated to `cron/nidp.crontab`.
- `nidp_staging` database size: **19 GB**.

## Laptop 1 config validation (run 2026-07-19, real unedited output)

- **Compose schema** — `docker compose -f docker-compose.app.yml config --quiet`
  - Output: `CORE: VALID` · `MIGRATE PROFILE: VALID`
  - Services (8): `app-backend app-frontend app-frontend-v5 app-migrate mongo nginx postgres redis`
  - Result: **PASS**
- **Shell syntax** — `bash -n up.sh` → `up.sh OK` — **PASS**
- **nginx edge.conf** (the :3000 cloudflared origin) — `nginx -t`
  - Output: `nginx: configuration file /etc/nginx/nginx.conf test is successful`
  - Result: **PASS**
- **nginx app-frontend.conf** — `nginx -t`
  - Output: `nginx: configuration file /etc/nginx/nginx.conf test is successful`
  - Result: **PASS**

Backend env surface derived from code (no `.env.example` exists in the repo and
the real one lives on the app VM): 161 distinct vars referenced; only
**MONGO_URL, DB_NAME, POSTGRES_URL, REDIS_URL** are required to boot
(`os.environ[...]` bracket access). All others gate a feature and are
documented as optional in `laptop1-app/.env.example`.

## Dump artifact (staging → laptops)

- `pg_dump -Fc --no-owner --no-privileges` of `nidp_staging` (19 GB source)
- Result: `EXIT=0`, **2.0 GB**, at `/opt/nidp/dumps/nidp_staging_20260719.dump`
- sha256: `a7b04683368f6e58e7006b2f80633df0e60e9472589de313994f60edb36c2107`
- Integrity: `pg_restore --list` exit=0, **2722 TOC entries**, no errors
  (348 TABLE · 338 DATA · 1027 INDEX · 49 VIEW · 13 SCHEMA · 1745 hypertable chunks)
- Left in place on the VM at the user's instruction (compressed, no space concern).
- **Not uploaded to Drive** — GCS writes are blocked by a delinquent billing
  account, and the Drive path needs an OAuth token from the user.

## Live boot verification (run 2026-07-19 on the build host, real output)

Scoped boot of the laptop-2 serving path on non-conflicting ports
(`15433/18083/18090/28080`, `shared_buffers=256MB`) so the VM's own services
were never at risk. Torn down with `down -v` afterwards; VM services confirmed
still healthy (`nidp-postgres Up 45 hours (healthy)`).

- **Image build** — `docker compose build daas-api`
  - Output: `Image nidp-laptop-daas-api Built` · `BUILD_EXIT=0`
  - Result: **PASS**

- **Image smoke tests**
  - `supercronic -version` → `v0.2.33` (the pinned SHA1 is correct)
  - `pdftoppm -v` → `pdftoppm version 25.03.0` (poppler present for document_parser)
  - AI_TIER=false stage → `correct: no tesseract in base` (multi-stage arg works)
  - `python3 -c "import asyncpg, fastapi, uvicorn, openai, pypdf, fitz, pandas, lxml"` → `imports OK`
  - With repo bind-mounted: `import nidp.services.daas_api.app` → `daas_api app imported OK: FastAPI`
  - Result: **PASS** — proves image + bind-mount + PYTHONPATH work together

- **TC-2 — extensions** (the pinned tag `timescale/timescaledb:2.26.4-pg16` exists and pulls)
  ```
  plpgsql 1.0
  postgres_fdw 1.1
  timescaledb 2.26.4
  vector 0.8.1
  PostgreSQL 16.13 on x86_64-pc-linux-musl
  ```
  Exact match to the dump source (timescaledb 2.26.4 / vector 0.8.1 / PG 16.13).
  - Result: **PASS**

- **TC-4 — DaaS API health**
  - `curl http://localhost:18083/health` →
    `HTTP 200 {"ok":true,"service":"nidp-daas-api","db_ok":true,"db_latency_ms":9,"error":null}`
  - `/openapi.json` → `HTTP 200`; container reports `(healthy)`; logs confirm `--root-path /daas`.
  - Result: **PASS**

- **TC-5 (partial) — Query API health**
  - `curl http://localhost:18090/health` →
    `HTTP 200 {"ok":true,"service":"nidp-query-api","db_ok":true,"db_latency_ms":1,"error":null}`
  - Result: **PARTIAL PASS** — health verified; bad-token rejection NOT tested.

- **TC-1 (partial) — routing through the nginx edge**
  ```
  edge /healthz      : ok  HTTP 200
  edge /daas/health  : {"ok":true,"service":"nidp-daas-api","db_ok":true,...}  HTTP 200
  edge /query/health : {"ok":true,"service":"nidp-query-api","db_ok":true,...} HTTP 200
  ```
  Confirms both the resolver fix and the prefix-stripping `rewrite`.
  - Result: **PASS** for postgres/daas-api/query-api/nginx (4 of 16 services).

  ⚠️ **Correction recorded for honesty:** the first attempt at this test reported
  `/healthz 200` and `/daas/health 401`. Those numbers were NOT from this stack —
  nginx had failed to start (`failed to bind host port 0.0.0.0:18080: address
  already in use`) and the responses came from an unrelated service already on
  that port. Re-run on a verified-free port (28080) produced the results above.

## Not yet verified (honest gaps)

- **TC-3 (migrations)** — the 112-file chain was NOT run. Needs an empty DB and
  ~10 min; the restore path supersedes it for normal use.
- **TC-6 (restore)** — the single biggest untested item. The TimescaleDB
  pre/post_restore logic in `restore.sh` is written from the documented
  contract but has never been executed against the 2.0 GB dump. Verify on
  laptop 2 first; expect this to need a fix.
- **TC-7 (observability)** — Prometheus/Grafana/Loki/Promtail/Alertmanager
  configs validate but were not booted.
- **TC-8/TC-9 (AI tier)** — the `AI_TIER=true` image was never built. tesseract,
  ffmpeg and faster-whisper are unproven, and the whisper model download on
  first use is untested. Adds ~1.5 GB to the image.
- **TC-10/TC-11 (scheduler)** — supercronic is installed and versioned, but the
  crontab has never been loaded and no feed job has been run.
- **TC-12..TC-16 (all of laptop 1)** — built and config-validated, never booted.
  No image built, no frontend compiled. The frontend builds are the most likely
  to need iteration (Vite/CRA build args).
- **TC-17/TC-18 (cross-laptop)** — untestable here; needs two machines on a LAN.
- **TC-20 (Windows/WSL2)** — no Windows machine available; the WSL2 guidance in
  the README is reasoned, not empirically verified.

**Net:** 4 of 16 laptop-2 services proven to boot and serve. 0 of 8 laptop-1
services booted. Treat first bring-up on the laptops as a debugging session,
not a formality.

## UI / Playwright Tests

No frontend src changed; no Playwright run applicable.

## Data Correctness

Not applicable yet — no local database exists to query until the restore runs.

## Inputs required from user

- Google Drive OAuth token (`rclone authorize "drive"`) — REQUESTED, outstanding.
- Laptop 2 LAN IP for `NIDP_HOST` at bring-up.
- Real secret values for `.env` on each laptop.

## Inputs required from user

- Laptop 2 LAN IP (for `NIDP_HOST`) — supplied at bring-up time, not needed to build.
- Real secret values (OpenAI key, SMTP, Screener cookie) — user pastes into `.env`.
- The GCP dump pull is run BY THE USER (production-derived data; not pulled autonomously).

## Verdict: BLOCKED
<!-- Flips to PASS only when every case above has real evidence. -->
