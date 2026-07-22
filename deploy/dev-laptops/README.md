# Two-Laptop Dockerised Dev Environment

Replicates the two GCP VMs as Docker Compose stacks on two Windows laptops.

| | Laptop 1 | Laptop 2 |
|---|---|---|
| Replicates | `nivesh-app-vm` | `nidp-stack-vm` |
| Directory | [`laptop1-app/`](laptop1-app/) | [`laptop2-nidp/`](laptop2-nidp/) |
| Serves | app on **:3000** (cloudflared origin) | NIDP APIs on **:8080** |
| Stores | Mongo, Postgres, Redis | TimescaleDB, MinIO, Redis |
| Also runs | frontend-v5 + FastAPI (V2 optional) | 49 feed jobs, AI tier, Grafana/Prom/Loki |

Reconstructed from the **live VMs** (`docker inspect`, `/etc/cron.d/nidp`,
systemd units, `/opt/nidp/docker-compose.dev.yml`) and the repo's real
staging/prod compose files — not from documentation.

---

## ⚠️ Read this first: your tunnel topology is wrong for this split

Your Cloudflare tunnel `nivesh-copilot` currently has **2 replicas**, both
advertising `dev.niveshcopilot.com → https://localhost:3000`.

Cloudflare treats replicas as **interchangeable origins of the same service**
and load-balances between them. That is correct for HA of two identical
machines. It is wrong here: laptop 2 runs NIDP and has nothing on port 3000,
so roughly **half your requests will 502**, intermittently and confusingly.

**Fix — one tunnel per laptop:**

| Laptop | Tunnel | Hostname | Service |
|---|---|---|---|
| 1 | `nivesh-copilot-l1` | `dev.niveshcopilot.com` | `http://localhost:3000` |
| 2 | `nivesh-copilot-l2` | `nidp-dev.niveshcopilot.com` | `http://localhost:8080` |

Laptop 2's tunnel is optional — you only need it to reach NIDP from outside
your LAN. On the same network, laptop 1 talks to laptop 2 by direct IP.

### Also: `https://` → `http://`

The existing route points at `https://localhost:3000`. These stacks serve
**plain HTTP** — a laptop has no usable TLS certificate, and the traffic never
leaves the machine (cloudflared connects to localhost). Change the service to
`http://localhost:3000`, or keep https and set `noTLSVerify: true` with a
self-signed cert. HTTP is simpler and no less secure here.

---

## Which branch to build from

**Build from `dev`.** Both stacks bind-mount / build from a repo checkout, and
the branch you are on decides whether the images build at all.

```bash
git checkout dev && git pull
```

This is not a style preference:

- `dev` is the integration branch that feeds staging, so it is what the
  laptops should mirror.
- `main` has **diverged** from `dev` (main is not an ancestor of dev), so
  building from main gives you a different application than staging runs.
- A feature branch may be missing files its own code imports. Building
  `app-frontend-v5` from `feat/copilot-backtest` fails with:

  ```
  src/routes.tsx(29,26): error TS2307: Cannot find module './pages/Releases'
  ```

  because `routes.tsx` there imports `./pages/Releases`, which exists on
  `dev` and `main` but is untracked on that branch. Same Dockerfile, same
  compose — only the branch differs. The v5 build succeeds from `dev`.

If a frontend build fails on `Cannot find module`, check your branch before
suspecting the Docker setup.

## Prerequisites (both laptops)

- **Docker Desktop** with the **WSL2 backend** enabled
- **WSL2 + Ubuntu** — run the `.sh` scripts from there, not PowerShell
- **Git**, and this repo cloned to a path **inside the WSL filesystem**
  (e.g. `~/nivesh.ai`, not `/mnt/c/...` — bind-mounts across the Windows
  filesystem boundary are 10–50× slower and break file-watching, so
  `uvicorn --reload` will not fire reliably)

### Resource floor

Docker Desktop defaults to a fraction of host RAM, which is not enough.

| Stack | Minimum | Comfortable |
|---|---|---|
| Laptop 1 (app) | 8 GB | 16 GB |
| Laptop 2 (NIDP core) | 8 GB | 16 GB |
| Laptop 2 + `--with-feeds` (AI tier) | 16 GB | 32 GB |

Set in `%USERPROFILE%\.wslconfig`, then `wsl --shutdown`:

```ini
[wsl2]
memory=12GB
processors=6
swap=4GB
```

Disk: ~25 GB for laptop 2 (19 GB restored DB + images), ~10 GB for laptop 1.

---

## Laptop 2 (NIDP) — bring up first

Laptop 1 depends on it, so start here.

```bash
cd deploy/dev-laptops/laptop2-nidp
cp .env.example .env
# Fill in: NIDP_PG_PASSWORD, NIDP_DAAS_INTERNAL_TOKEN, NIDP_QUERY_API_TOKEN,
#          MINIO_ROOT_PASSWORD, GRAFANA_ADMIN_PASSWORD
# Generate tokens:  openssl rand -hex 32
./up.sh
```

Then load the data. The staging dump is on `nidp-stack-vm` at
`/opt/nidp/dumps/nidp_staging_20260719.dump` (**2.0 GB**, sha256 in the
`.sha256` file beside it). Pull it down:

```bash
gcloud compute scp nidp-stack-vm:/opt/nidp/dumps/nidp_staging_20260719.dump \
    ./dumps/ --tunnel-through-iap --zone <zone>
sha256sum -c dumps/nidp_staging_20260719.dump.sha256   # verify the transfer
./restore.sh dumps/nidp_staging_20260719.dump
```

`restore.sh` is **not** a thin `pg_restore` wrapper — see
[Why the restore is special](#why-the-restore-is-special).

Optional extras:

```bash
./up.sh --with-feeds    # the 49 scheduled feed jobs + AI tier
./up.sh --with-kafka    # redpanda + schema registry (rarely needed)
./up.sh --migrate       # apply the 112 migrations to an EMPTY db instead
```

Endpoints: `:8080/daas` · `:8080/query` · `:8080/grafana` · `:9090` Prometheus
· `:9001` MinIO console · `:5433` Postgres.

Note the laptop 2 LAN IP — laptop 1 needs it:

```bash
ip route get 1.1.1.1 | awk '{print $7; exit}'     # WSL
ipconfig | findstr IPv4                            # Windows
```

**Windows Firewall must allow inbound TCP 8080**, or laptop 1 cannot reach it.

---

## Laptop 1 (app)

```bash
cd deploy/dev-laptops/laptop1-app
cp .env.example .env
# Fill in NIDP_HOST (laptop 2's LAN IP) and the datastore passwords.
# NIDP_DAAS_INTERNAL_TOKEN and NIDP_QUERY_API_TOKEN must be BYTE-IDENTICAL
# to laptop 2's .env, or every NIDP call returns 401.
./up.sh --migrate     # create the app schema first
./up.sh
```

`up.sh` probes laptop 2 before starting and warns loudly if it is unreachable —
a wrong `NIDP_HOST` otherwise surfaces much later as silently empty screens.

Endpoints: `:3000/` (302 → `/v5/work`) · `:3000/v5/` · `:3000/api/docs` ·
`:8001/docs`.

### This stack is v5-only

The V2 frontend is behind the `v2` compose profile and is **not built or
started** by default; nginx 302s `/` to `/v5/work`, the same thing prod's
v5-only vhost does. v5 has no dependency on V2 — verified at three levels:
the v5 Dockerfile copies only `frontend-v5/`, there are no `/v2` links in
`frontend-v5/src`, and there are no cross-imports. Bring V2 back with
`./up.sh --with-v2` (and see the note in `nginx/edge.conf`).

### `OPENAI_API_KEY` is required to BOOT

Not optional, despite being an "AI" key. `backend/deps.py:41` constructs
`AIEngine(OPENAI_API_KEY)` at **import** time, so an unset value crashes the
backend before it serves anything:

```
openai.OpenAIError: Missing credentials. Please pass an `api_key` ...
```

Any non-empty string boots it; a real key is needed for LLM features to work.
`up.sh` fails fast on this rather than letting you discover it in a crash log.

---

## Why the restore is special

The source database has **17 hypertables and ~586 chunk tables** under
`_timescaledb_internal`. A plain `pg_restore` replays that chunk DDL while the
TimescaleDB extension is live, so the extension tries to re-manage objects
that are mid-creation → duplicate-chunk errors and circular-FK failures on the
`hypertable` catalog. `pg_dump` warns about this at dump time.

`restore.sh` therefore:

1. Asserts the local extension is **exactly 2.26.4** (the dump's source
   version) and refuses to run otherwise. The compose file pins
   `timescale/timescaledb:2.26.4-pg16` — **never** `latest-pg16`, which moves.
2. Wraps the restore in `timescaledb_pre_restore()` / `post_restore()`, with
   `post_restore` in a trap so a failed restore cannot strand the database in
   restore mode.
3. Verifies **after** the fact — hypertable count and row counts on the tables
   the app actually reads. A restore that silently degrades hypertables into
   plain tables looks like it worked; the row counts are what catch it.

Expected after a good restore: **17 hypertables**, `nidp` schema with
**72 tables + 38 views**.

---

## Cross-laptop wiring

One variable, `NIDP_HOST`, in laptop 1's `.env`. Everything else derives:

```
NIDP_DAAS_BASE_URL = http://$NIDP_HOST:8080/daas
NIDP_QUERY_API_URL = http://$NIDP_HOST:8080/query
```

Laptop 2's nginx deliberately reproduces the VM's path layout
(`/daas`, `/query`, `/grafana`), so these URLs differ from staging **only in
host:port** — no code changes to move between local and staging.

Give laptop 2 a **static DHCP lease**. Otherwise a reboot changes its IP and
laptop 1 silently loses its data source.

---

## Deliberate differences from the GCP VMs

| GCP VM | Here | Why |
|---|---|---|
| DaaS/Query API as systemd + host venv | containers | you asked for Docker; also removes the host-venv drift that has bitten that VM |
| Feed jobs via `/etc/cron.d/nidp` as user `nidp` | supercronic scheduler container | keeps the laptop host clean; real cron swallows env vars in containers |
| Feeds always on | behind `feeds` profile, **off by default** | they scrape NSE/BSE/AMFI/RBI from your home IP |
| Kafka/redpanda running | behind `kafka` profile, off | the VM's own env file says the bus is local "since Kafka is dead" |
| Alerts → Telegram + SMTP | **null receiver** | a dev laptop must never page the real on-call channel |
| nginx TLS (Cloudflare origin cert) | plain HTTP | no usable cert on a laptop; cloudflared terminates TLS |
| GCP VPC, MTU 1460 | LAN, default MTU | the VM's MTU pin exists for GCP's VPC path and is not needed here |
| Secrets from GSM | local `.env` files | your choice; templates document every variable |
| Loki 30d / Prom 14d retention | 7d each | laptop disk |
| Grafana on :3000 | **:3001** | laptop 1 owns 3000 for the tunnel |

---

## Troubleshooting

**Every NIDP screen is empty.** `NIDP_HOST` is wrong, laptop 2 is down, or
Windows Firewall is blocking 8080. Test from laptop 1:
`curl http://$NIDP_HOST:8080/healthz`

**401 from NIDP.** `NIDP_DAAS_INTERNAL_TOKEN` / `NIDP_QUERY_API_TOKEN` differ
between the two `.env` files. They must match exactly.

**Login does not persist.** `COOKIE_SECURE=true` while browsing plain
`http://localhost:3000`. Either use the https tunnel URL or set it to `false`.

**Frontend calls the wrong API host.** `APP_PUBLIC_URL` is baked in at build
time. Change it, then:
`docker compose -f docker-compose.app.yml build app-frontend-v5`

**`uvicorn --reload` never fires.** The repo is on `/mnt/c/...`. Move it into
the WSL filesystem — inotify does not cross that boundary.

**`.env: line N: syntax error near unexpected token`.** You are on an old
`up.sh` that shell-sourced `.env`. Pull `dev` and re-copy `.env.example` — a
`.env` is not a shell script, and values containing `< > ( ) | ' " ; &` (an
`SMTP_FROM` like `Nivesh <noreply@…>`, say) broke it. Current `up.sh` reads
keys literally and never evaluates the file.

**`pull access denied for nivesh/backend ... may require 'docker login'`.**
Harmless, and fixed on current `dev`. Those images are built locally by design
— there is no registry. `pull_policy: build` now stops compose from trying to
pull them. Use `./up.sh` (which builds) rather than `docker compose up`.

**`No such image: redis:7-alpine` right after it says `Pulled`.** Not a compose
problem — the Docker daemon's image store is in a split state. Confirm it:

```bash
docker pull redis:7-alpine                              # "Image is up to date"
docker image inspect redis:7-alpine --format '{{.Id}}'  # "No such image"
```

If those two disagree, the CLI is reading one image store and the daemon
another. Seen in the wild after toggling **Settings → General → "Use
containerd for pulling and storing images"**: unchecking it does NOT take
effect until the daemon restarts, which leaves the install *between* stores.

Fix: **fully quit Docker Desktop** (tray → Quit, not "Restart"), relaunch,
then re-pull. Re-pulling is required — images in the old store are invisible
to the new one. `docker image inspect` must return an ID before `./up.sh`
will work. If it still fails, **Troubleshoot → Clean / Purge data** forces a
single consistent store.

Note the containerd snapshotter is not itself the problem — it works fine
when the store is consistent; it is the half-applied toggle that breaks.

**Postgres crash-loops after restore.** Almost always disk. Check with
`docker system df`; reclaim with `docker builder prune -af`.

**Restore reports 0 hypertables.** Version skew. Confirm the image is pinned
to `2.26.4-pg16` and re-run; do not use that database.

---

## Verification status

Config validation is done and recorded in
[`test_reports/dev_env_two_laptop_docker.md`](../../test_reports/dev_env_two_laptop_docker.md):
compose schemas, all nginx configs, `promtool`, `amtool`, Loki, Promtail, and
`bash -n` all pass.

**Boot verification has NOT been done** — these stacks have never been started
end-to-end. That could not be done on the build host (it is `nidp-stack-vm`
itself, at ~14/15 GB RAM with a dump running; starting 16 more containers
risks the documented disk/memory failure mode that crash-loops Postgres and
takes DaaS down). Test cases TC-1 and TC-3…TC-17 must be run on the laptops.
Expect to fix a few things on first boot.
