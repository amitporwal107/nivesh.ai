# CloudPe staging bring-up — runbook for Claude Code on `cloudpe1`

**Scope:** move the two GCP **staging** environments onto the single CloudPe VM `cloudpe1`
(45.64.105.88, Ubuntu 24.04, 4 vCPU / 16 GiB / 100 GiB, user `deploy`), from the `dev` branch:

- **Part A — Nivesh app staging** (`deploy/nivesh-staging/`): backend, frontends (v2, v5),
  Postgres, Mongo, Redis, edge nginx.
- **Part B — NIDP staging** (`backend/nidp/deploy/vm/*staging*`): TimescaleDB, DaaS API (:8084),
  Query API (:8091), Grafana (:3000), feed cron, host nginx for `staging-data.niveshcopilot.com`.
- **Part C — wire A → B** on the same host.

**Hard constraint: no GCP.** The GCP project is inaccessible (compliance lock; prod returns
Cloudflare 522 as of 2026-10-11). Nothing may depend on `gcloud`, Secret Manager, Artifact Registry,
GCS, Cloud SQL or the GCP VPC (`10.160.0.x`). All data starts **fresh**; NIDP data is rebuilt by
running the feeds. Prod (`main`) and DNS are out of scope.

**Who runs this:** Claude Code on `cloudpe1`, from `~/nivesh.ai`. Follow `CONTEXT.md` (status
vocabulary, no fabricated output). Each phase ends with a **gate**: run it, show real output, and do
not start the next phase until it passes.

**Stop and ask the user (NEEDS-INPUT) before:** writing any app secret (SMTP, Google OAuth,
CASParser, Telegram, NIDP tokens), opening any port to the internet, touching DNS/Cloudflare,
enabling more than the default staging feeds, or deleting data.

**Rules for changes:** do not edit the shared GCP files in a way that changes their GCP behaviour.
Put CloudPe-only pieces in `deploy/cloudpe/` (compose overrides, wrapper scripts, env templates
without secrets). Never commit secrets or env files.

---

## Phase 0 — Read before acting
- App: `deploy/nivesh-staging/{README.md,docker-compose.staging.yml,bootstrap-staging.sh,redeploy-staging.sh,nginx-staging.conf}`
- NIDP: `backend/nidp/deploy/vm/{README.md,bootstrap-staging.sh,docker-compose.staging.yml,nidp.staging.cron,nidp.env.staging.example,nginx.staging.conf,install_nginx_staging.sh,install_query_api.sh,install_grafana.sh,run_service.sh}`
- `docs/DEVOPS_ENVIRONMENTS.md`, `docs/BUILD_AND_DEPLOYMENT.md`

## Known GCP-specific assumptions (from the repo — verify each on the VM)

| # | Where | Assumption | CloudPe handling |
|---|---|---|---|
| A1 | app `docker-compose.staging.yml` `build.cache_from/cache_to` | Artifact Registry cache | No GCP auth. If `build` fails on it, disable the registry cache via CloudPe override/wrapper. |
| A2 | app compose `networks.nidp-bridge: external` | Created by GCP prod stack | Create it (Part C uses it to reach NIDP) or replace in override. |
| A3 | app compose network MTU `1460` | GCP VPC MTU | Use the VM's real MTU from `ip link` (OpenStack is often 1450). |
| A4 | app nginx volume `/opt/nivesh/ssl` | Prod Cloudflare origin cert | Absent. Self-signed for now; real cert later with user. |
| A5 | `redeploy-staging.sh` runs `git fetch` as root | Root can reach GitHub | Deploy key belongs to `deploy`. Fetch as `deploy`; do not copy the key to root. |
| A6 | app secrets in GCP Mongo/Secret Manager | — | Fresh Mongo has none → degraded features. List them; ask user. |
| B1 | NIDP compose binds Postgres on `10.160.0.3:5434` | GCP VPC IP | That IP does not exist here → `up` fails. Bind loopback only (override). |
| B2 | `setup_staging_secrets.sh`, `install_nginx_staging.sh` | `gcloud secrets` | **Do not run.** Write `/opt/nidp-staging/nidp.env` from `nidp.env.staging.example` with locally generated DB password; self-signed cert for nginx. |
| B3 | NIDP raw archives / GCS | GCS bucket | Use local disk (`/opt/nidp-staging/raw_archives`). Check which feeds need GCS and leave them off. |
| B4 | NSE access via `tinyproxy` on GCP app VM (`deploy/nidp/tinyproxy-nse-egress.conf`) because NSE 403s some cloud IPs | GCP egress IP | Test NSE directly from this VM early (Phase B4 gate). If 403 → **REAL BLOCKER** for NSE feeds; report, do not work around. |
| B5 | Host nginx `staging-data` vhost listens on 80/443 | Separate VM from app | Same VM as app's container nginx (8443/8444) — no clash on 443 today, but confirm with `ss -tlnp`. |
| B6 | Query API staging on `:8091`, Grafana on `:3000` | Installed by GCP-era scripts | Check `install_query_api.sh` / `install_grafana.sh` for gcloud use before running. |

Pre-existing issue to report (do not fix here): `deploy/nivesh-staging/docker-compose.staging.yml`
hardcodes a Mongo app password in `MONGO_URL`.

---

## Phase 1 — Host prerequisites (shared)
Docker Engine + Compose plugin (Docker's apt repo), `deploy` in `docker` group, Python 3.11
(+ venv) for NIDP, `postgresql-client`, `nginx`, `jq`, `cron`.

**Gate:** `docker version`, `docker compose version`, `docker run --rm hello-world`,
`python3.11 --version`, `df -h /`, `free -h`, `ip link` (record MTU), `sudo ss -tlnp`.

## Part A — App staging

**A-1 Layout:** `/opt/nivesh-staging/repo` = clone of `dev` owned by `deploy`;
`sudo bash .../deploy/nivesh-staging/bootstrap-staging.sh`.
Gate: `git -C /opt/nivesh-staging/repo log --oneline -1`; `sudo stat -c '%a %U' /opt/nivesh-staging/.env.staging` → `600 root`. Never print env files.

**A-2 CloudPe overrides** for A1–A5 in `deploy/cloudpe/`. Gate: `docker compose ... config -q` exits 0.

**A-3 Build + start** (migrations profile once, then up). Gate:
```bash
docker ps --filter name=nivesh-staging --format '{{.Names}}\t{{.Status}}'
curl -k -fsS --resolve staging.niveshcopilot.com:8443:127.0.0.1 https://staging.niveshcopilot.com:8443/api/healthz
for p in /v2/ /v5/; do curl -k -s -o /dev/null -w "$p %{http_code}\n" --resolve staging.niveshcopilot.com:8443:127.0.0.1 https://staging.niveshcopilot.com:8443$p; done
```

## Part B — NIDP staging

**B-1 Bootstrap:** run `backend/nidp/deploy/vm/bootstrap-staging.sh` (read it first; it expects
code at `/opt/nidp/dev-repo/nivesh.ai`, user `nidp-staging`, venv `/opt/nidp-staging/venv`).
Skip/replace any gcloud step. Gate: `id nidp-staging`, venv `pip check`, `ls -la /opt/nidp-staging`.

**B-2 Env:** `/opt/nidp-staging/nidp.env` (600, owner `nidp-staging`) with a freshly generated
`NIDP_PG_PASSWORD`; tokens (Telegram, Query API) → ask user or leave empty. Gate: key names only:
`sudo cut -d= -f1 /opt/nidp-staging/nidp.env`.

**B-3 DB + DaaS:** NIDP staging compose with a CloudPe override for B1; apply NIDP migrations
(`backend/nidp/migrations`) to the staging TimescaleDB. Gate:
```bash
docker ps --filter name=nidp --format '{{.Names}}\t{{.Status}}'
curl -fsS http://127.0.0.1:8084/health
psql "<staging url>" -c "select count(*) from information_schema.tables where table_schema='nidp'"
```

**B-4 NSE reachability (early, decides feed scope):**
```bash
curl -s -o /dev/null -w 'NSE %{http_code}\n' -A 'Mozilla/5.0' https://www.nseindia.com/
curl -s -o /dev/null -w 'BSE %{http_code}\n' https://www.bseindia.com/
curl -s -o /dev/null -w 'AMFI %{http_code}\n' https://www.amfiindia.com/spages/NAVAll.txt
```
Report the codes. NSE 403 = REAL BLOCKER for NSE feeds (needs a different egress IP — user decision).

**B-5 Query API + Grafana + host nginx** (self-signed cert, `server_name staging-data.niveshcopilot.com`). Gate:
```bash
curl -fsS http://127.0.0.1:8091/health
curl -k -fsS --resolve staging-data.niveshcopilot.com:443:127.0.0.1 https://staging-data.niveshcopilot.com/daas/health
curl -k -fsS --resolve staging-data.niveshcopilot.com:443:127.0.0.1 https://staging-data.niveshcopilot.com/query/health
```

**B-6 Feeds:** install `nidp.staging.cron` to `/etc/cron.d/nidp-staging` with only its
default-enabled lines. Run **one** feed by hand first via `run_service.sh` (AMFI NAV is a good
first candidate if it is in the list). Gate (data, not just exit code):
```bash
psql "<staging url>" -c "select service, status, finished_at from nidp.job_log order by finished_at desc limit 5"
psql "<staging url>" -c "select * from nidp.v_feed_status limit 20"
```
Ask the user before enabling additional feeds or any historical backfill.

## Part C — Wire app → NIDP
Point app staging at the local NIDP (`NIDP_DAAS_BASE_URL`, `NIDP_QUERY_API_URL`, tokens) via the
CloudPe override — reachable through the host (e.g. `host-gateway`), not the GCP IP.
Gate: from inside `nivesh-staging-app-backend`, `curl` the DaaS and Query `/health`; then one app
endpoint that reads NIDP data returns real rows (show count + one non-sensitive field).

## Phase Z — Browser check through the tunnel (user)
User adds `LocalForward 8443 127.0.0.1:8443` to `cloudpe1` and temporarily maps
`127.0.0.1 staging.niveshcopilot.com` in the Windows hosts file, opens
`https://staging.niveshcopilot.com:8443/v5/` (self-signed warning expected), then removes the
hosts entry.

## Report
`test_reports/cloudpe_staging_<date>.md` from `test_reports/_TEMPLATE_functionality.md`: every
gate with real output; degraded features (missing secrets, disabled feeds, NSE status); open items
for the user (real TLS certs, public exposure + DNS, secrets, prod plan). Status is
**IN PROGRESS** until every gate is green — name the ones that are not.
