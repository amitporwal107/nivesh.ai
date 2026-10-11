# CloudPe staging bring-up — runbook for Claude Code on `cloudpe1`

**Scope:** bring up the existing **staging** stack (`deploy/nivesh-staging/`) on the CloudPe VM
`cloudpe1` (45.64.105.88, Ubuntu 24.04, user `deploy`) from the `dev` branch, with **fresh**
databases. **Out of scope:** prod data, DNS changes for `niveshcopilot.com`, NIDP, Cloud Run jobs,
anything on GCP. Live production is not touched.

**Who runs this:** Claude Code on `cloudpe1`, from `~/nivesh.ai`. Follow `CONTEXT.md` (status
vocabulary, no fabricated output). Every phase ends with a **gate**: run the command, show its real
output, and do not start the next phase until it passes.

**Stop and ask the user (NEEDS-INPUT) before:** writing any app secret (SMTP, Google OAuth,
CASParser, NIDP tokens), opening any port to the internet, touching DNS/Cloudflare, or deleting data.

---

## Phase 0 — Read before acting
- `deploy/nivesh-staging/README.md`, `docker-compose.staging.yml`, `bootstrap-staging.sh`,
  `redeploy-staging.sh`, `nginx-staging.conf`.
- `docs/DEVOPS_ENVIRONMENTS.md`, `docs/BUILD_AND_DEPLOYMENT.md`.

These files were written for GCP `nivesh-app-vm`. The GCP-specific assumptions below must be
handled for CloudPe. **Do not edit the shared staging files in a way that breaks GCP staging** —
put CloudPe-only changes in `deploy/cloudpe/` (e.g. a compose override and a wrapper script).

## Known GCP-specific assumptions (from the repo, verify each on the VM)

| # | Where | Assumption | What to do on CloudPe |
|---|---|---|---|
| 1 | `docker-compose.staging.yml` `build.cache_from/cache_to` | Build cache in GCP Artifact Registry (`asia-south1-docker.pkg.dev/...`) | No GCP auth here. Check whether `docker compose build` fails or only warns; if it fails, disable the registry cache for CloudPe (override / wrapper). |
| 2 | `networks.nidp-bridge: external: true` | Network created by the GCP prod stack | Does not exist here → `up` fails. Create an empty one (`docker network create nidp-bridge`) or drop it in an override. |
| 3 | `networks.nivesh-staging` MTU `1460` | GCP VPC MTU | Check `ip link` on the VM. OpenStack clouds are often **1450**. Use the host interface MTU. |
| 4 | `nginx` volume `/opt/nivesh/ssl` (`cert.pem`, `key.pem`) | Cloudflare Origin cert from prod | Not present. For this phase generate a **self-signed** cert into a CloudPe-only path. Real cert = later, with the user. |
| 5 | `redeploy-staging.sh` runs `git fetch` **as root** in `/opt/nivesh-staging/repo` | Root can fetch | The GitHub deploy key belongs to `deploy`, not root. Make fetch work without copying the key to root (e.g. repo owned by `deploy`, fetch as `deploy`). |
| 6 | App secrets | Live in GCP Mongo `system_config.secrets` + GCP `.env.staging` | Fresh Mongo has none. Expect degraded features (email, OAuth, CAS parsing). List what is missing; **ask the user** for values — never invent them. |
| 7 | `NIDP_*` URLs → `staging-data.niveshcopilot.com` | Not live even on GCP | Same behaviour as GCP staging; note it, do not fix in this phase. |

Also note (pre-existing, report to user, do not fix here): `docker-compose.staging.yml` contains a
hardcoded Mongo app password in `MONGO_URL`.

---

## Phase 1 — Host prerequisites
Install Docker Engine + Compose plugin from Docker's official apt repo; add `deploy` to the
`docker` group; enable the service.

**Gate:** `docker version`, `docker compose version`, `docker run --rm hello-world`, `df -h /`,
`free -h`, `ip link` (record MTU).

## Phase 2 — Layout
`/opt/nivesh-staging/` with `repo/` = clone of `dev` (owned by `deploy`), then
`sudo bash repo/deploy/nivesh-staging/bootstrap-staging.sh`.

**Gate:** `ls -la /opt/nivesh-staging`, `git -C /opt/nivesh-staging/repo log --oneline -1`,
`sudo stat -c '%a %U' /opt/nivesh-staging/.env.staging` → `600 root`. Never print the env file.

## Phase 3 — Handle assumptions 1–5
Create the CloudPe-only pieces in `deploy/cloudpe/` (override file, self-signed cert step, wrapper
that calls compose with both files). Keep `redeploy-staging.sh` behaviour (fetch → build → up →
health → nginx reload → smoke) intact.

**Gate:** `docker compose ... config -q` exits 0 with the override applied.

## Phase 4 — Build and start
Run the migrations profile once, then bring the stack up via the wrapper.

**Gate (all real output):**
```bash
docker ps --filter name=nivesh-staging --format '{{.Names}}\t{{.Status}}'
curl -k -fsS --resolve staging.niveshcopilot.com:8443:127.0.0.1 https://staging.niveshcopilot.com:8443/api/healthz
curl -k -s -o /dev/null -w '%{http_code}\n' --resolve staging.niveshcopilot.com:8443:127.0.0.1 https://staging.niveshcopilot.com:8443/v2/
curl -k -s -o /dev/null -w '%{http_code}\n' --resolve staging.niveshcopilot.com:8443:127.0.0.1 https://staging.niveshcopilot.com:8443/v5/
```
Expect all containers healthy/up, healthz `{"status":"ok"...}`, `200` for `/v2/` and `/v5/`.

## Phase 5 — Data check (CONTEXT §1: app AND data)
Confirm the backend is really using the CloudPe databases: migrations applied (list tables in
staging Postgres), Mongo `nivesh_staging` reachable, Redis `PING`. Show counts, not contents.

## Phase 6 — Browser check through the tunnel (user)
User adds `LocalForward 8443 127.0.0.1:8443` for `cloudpe1`, adds
`127.0.0.1 staging.niveshcopilot.com` to the Windows hosts file **temporarily**, and opens
`https://staging.niveshcopilot.com:8443/v5/` (self-signed warning expected). Remove the hosts entry
afterwards so the real staging site resolves normally again.

## Report
Write `test_reports/cloudpe_staging_<date>.md` from `test_reports/_TEMPLATE_functionality.md`:
each gate, its real output, what is degraded (missing secrets), and open items for the user
(real TLS cert, public exposure + DNS, secrets, NIDP). Status is **IN PROGRESS** until every gate
is green; say which ones are not.
