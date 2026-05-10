# Local Development — run the full Nivesh + NIDP product on your laptop

This stack runs **everything** locally. **No** Emergent pod, **no** GCP VM, **no** Upstash, **no** Neon — just Docker on your machine.

## What gets run locally

| Service | Port | What it is |
|---|---|---|
| MongoDB | 27017 | Primary app store (users, holdings, reports, …) |
| Postgres (app) | 5432 | Analytics / MF data for main app (DB: `nivesh_dev`) |
| Postgres + TimescaleDB (nidp) | 5433 | NIDP warehouse (DB: `nidp`) |
| Redis | 6379 | Cache / lock substrate |
| NIDP DaaS API | 8083 | Versioned read APIs incl. `/v1/intelligence/*` |
| NIDP Query API | 8090 | NIDP Console data source (jobs / catalog / DQ) |
| Main backend | 8001 | FastAPI (the chat / portfolio / copilot / admin app) |
| Frontend | 3000 | React (craco dev server, hot-reload) |

All 8 share a single docker network `nivesh-local` and address each other by service name (e.g., the backend reaches the DaaS API at `http://nidp-daas-api:8083`). Host-port mappings are for *your* laptop only.

---

## 1. Prerequisites

| Requirement | Why | Install |
|---|---|---|
| **Docker Desktop** ≥ 4.x | runs all 8 services in containers | https://www.docker.com/products/docker-desktop |
| **Docker Compose v2** | brings up the stack | bundled with Docker Desktop |
| `openssl`, `curl`, `jq` | bootstrap script + smoke tests | macOS: `brew install jq` · Linux: `apt-get install jq` |
| **8 GB RAM free** | running everything at once | — |
| **2 GB disk** | docker images + volumes | — |

> First-time builds take ~3–6 min (image layers). Subsequent `make up` is < 30 s.

---

## 2. One-shot bring-up

```bash
git clone <repo> nivesh && cd nivesh
make all
```

`make all` runs every step below in order. Each step prints what it's doing — nothing is hidden.

That's it. When it finishes, open:
- **App:** http://localhost:3000
- **API docs:** http://localhost:8001/docs
- **NIDP DaaS docs:** http://localhost:8083/docs
- **NIDP Query docs:** http://localhost:8090/docs

---

## 3. Step-by-step (recommended for first-time setup)

If you want to understand each step or troubleshoot, run them one by one. Pass any step name to `setup.sh`:

```bash
./scripts/local/setup.sh prereqs       # 1. checks you have docker / openssl / jq
./scripts/local/setup.sh env           # 2. creates .env.local + frontend/.env.local from templates,
                                       #    auto-generates the NIDP internal token
./scripts/local/setup.sh build         # 3. docker compose build (long, one-time)
./scripts/local/setup.sh infra         # 4. boots mongo + postgres-app + postgres-nidp + redis
./scripts/local/setup.sh wait-infra    # 5. blocks until all 4 DBs are healthy
./scripts/local/setup.sh migrate       # 6. runs NIDP SQL migrations against postgres-nidp
./scripts/local/setup.sh seed          # 7. seeds source_registry + daas_api_keys internal row;
                                       #    triggers a first intelligence_layer materialization
./scripts/local/setup.sh services      # 8. boots nidp-daas-api + nidp-query-api + backend + frontend
./scripts/local/setup.sh verify        # 9. runs Phase-5 smoke tests
```

Or via Makefile:

```bash
make prereqs
make env
make build
make infra
make migrate
make seed
make services
make verify
```

---

## 4. Things you must fill in (after `make env`)

Open `.env.local` and paste in your keys. Defaults work for everything *except* features that hit external services:

### REQUIRED for AI features
```
OPENAI_API_KEY=sk-…                 # your OpenAI key — powers chat, copilot, document_parser, announcement_classifier
```

### OPTIONAL — add as you need them
```
GOOGLE_CLIENT_ID=…                  # Gmail sync + Google sign-in (see §5 below)
GOOGLE_CLIENT_SECRET=…
CASPARSER_API_KEY=…                 # NSDL CAS PDF parsing (Nivesh production key)
FRED_API_KEY=…                      # free at fred.stlouisfed.org
```

After updating `.env.local`, restart the backend:
```bash
docker compose -f docker-compose.local.yml restart backend
```

### Frontend env (frontend/.env.local)
Open `frontend/.env.local` and set:
```
REACT_APP_GOOGLE_CLIENT_ID=…        # SAME id as GOOGLE_CLIENT_ID above (frontend reads this for Google sign-in)
```
Frontend dev server picks this up on next save.

---

## 5. Google OAuth on localhost (Gmail sync + sign-in)

You **do not need a separate OAuth client** for local. Just add localhost to your existing client:

1. Go to https://console.cloud.google.com/apis/credentials
2. Find the OAuth 2.0 client you already use (the one whose ID is in your `.env.local`)
3. Click **Edit (pencil icon)**
4. **Authorized JavaScript origins** — add:  `http://localhost:3000`
5. **Authorized redirect URIs** — add:  `http://localhost:8001/api/oauth/gmail/callback`
6. Click **Save**

Wait ~30 seconds for Google to propagate. That's it — `GMAIL_REDIRECT_URI=http://localhost:8001/api/oauth/gmail/callback` is already wired by `setup.sh env`.

---

## 6. NIDP feeds — pulling real data on demand

The cron-driven fetchers don't run automatically locally (no cron in containers by design). Run any feed you want manually:

```bash
make ingest f=amfi_nav                  # fetch AMFI NAV
make ingest f=bhavcopy                  # NSE bhavcopy
make ingest f=fii_dii                   # FII/DII flows
make ingest f=intelligence_layer        # rebuild ref/dq/features/graph from whatever you have
```

Each ingester logs to stdout; if it fails (rate-limit, network blocked, missing API key), the error is shown directly. Most feeds work from a residential laptop. Some endpoints (NSE in particular) sometimes block VPN / data-center IPs — disable VPN if you see 403/429.

> The full feed list is in `backend/nidp/deploy/vm/seed_source_registry.py`. Anything wrapped via `nidp.shared.derived_run.run_with_job_log` will also write to `nidp.job_log` so the NIDP UI Console at http://localhost:3000/nidp shows it.

---

## 7. Day-to-day commands

```bash
make ps                         # list running containers
make logs s=backend             # tail backend logs (replace backend with any service name)
make logs s=frontend
make logs s=nidp-daas-api
make logs s=postgres-nidp

make shell-backend              # shell into backend container
make shell-pg-app               # psql into nivesh_dev
make shell-pg-nidp              # psql into nidp warehouse

make down                       # stop containers, keep data
make restart                    # down + up
make clean                      # DESTROY everything (containers + volumes + data) — use to start fresh
```

---

## 8. Switching CASparser keys from the admin UI

The `.env.local` value of `CASPARSER_API_KEY` is just the bootstrap default. The active key is read from the admin-managed secrets layer (`system_config` collection in Mongo). To switch:

1. Sign in as admin at http://localhost:3000
2. Go to **Admin → Secrets / API Keys**
3. Update `CASPARSER_API_KEY` (or toggle `CASPARSER_USE_SANDBOX=true` for sandbox mode)

Backend picks up changes within seconds — no restart needed.

---

## 9. Verifying everything (Phase-5 smoke)

```bash
make verify
```

Runs 12 checks:
1. NIDP DaaS API reachable
2. NIDP Query API reachable
3. `/v1/catalog?domain=Intelligence` returns ≥9 datasets
4. `/v1/intelligence/portfolio/{user}/snapshot` shape (200 or 404, never 5xx)
5. Auth enforced (no key → 401)
6. Main backend `/docs` reachable
7. Backend → NIDP connectivity through `/api/admin/nidp/diag`
8. Frontend dev server serves `/`
9. MongoDB ping
10. postgres-app ready
11. postgres-nidp ready
12. Redis PING

All 12 must pass.

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `port already allocated` | host port collision | edit ports in `.env.local`: `BACKEND_PORT=8002`, etc. |
| backend can't reach `mongodb:27017` | not on same docker network | `make down && make up` (recreates network) |
| `make migrate` fails with "schema_migrations does not exist" | postgres-nidp not yet healthy | run `./scripts/local/setup.sh wait-infra` first |
| `make seed` fails with "could not connect to server: localhost:5433" | leftover code path with hardcoded localhost | already fixed in `seed_source_registry.py` to read `NIDP_POSTGRES_URL`. If you see this, `git pull` again. |
| backend connects to wrong Mongo / Postgres | stray `backend/.env` from another checkout overrides docker-compose env | `rm backend/.env frontend/.env` (both are gitignored — local stack uses `.env.local` instead) |
| frontend hangs on "Compiling…" for >2 min | first compile + heavy bundle | normal, wait. After that it's < 5 s incremental |
| NIDP feed says `403 Forbidden` | upstream blocking your IP | disable VPN, retry. If on corp WiFi, use mobile hotspot |
| `OPENAI_API_KEY missing` errors in chat | not pasted into `.env.local` | paste it, then `docker compose -f docker-compose.local.yml restart backend` |
| Want to wipe everything and start fresh | — | `make clean` (DESTRUCTIVE) then `make all` |

---

## 11. What's NOT included in local mode (by design)

- **Cron-scheduled ingesters** — runnable on demand via `make ingest f=…`
- **Grafana / Prometheus** — present on the VM, omitted locally to keep the stack lean
- **MinIO / S3** — used for raw archive on the VM; locally feeds skip archive (set `NIDP_ARCHIVE_DIR=/tmp/nidp_archive` if you want local archiving)
- **GCP Cloud Storage / Secret Manager** — not used locally; secrets live in `.env.local` + `system_config` Mongo collection

---

## 12. Architecture reference

```
                          ┌──────────────────────┐
                          │  Browser (you)       │
                          │  http://localhost     │
                          └──────────┬───────────┘
                                     │
         ┌───────────────────────────┴────────────────────────────┐
         │                                                        │
   :3000 frontend (React / craco)                          :8001 backend (FastAPI)
                                                              │      │      │
                              ┌───────────────────────────────┘      │      │
                              ▼                                      ▼      ▼
                       :8083 nidp-daas-api ◄──── :8090 nidp-query-api  :27017 mongodb
                              │                          │                 :5432 postgres-app
                              ▼                          ▼                 :6379 redis
                       :5433 postgres-nidp  ◄────────────┘
                       (TimescaleDB)
```

---

Questions / issues → see `make logs s=<service>` first, then `make shell-<service>` for a poke-around. Most problems are one of: env var missing, container not yet healthy, or port collision.
