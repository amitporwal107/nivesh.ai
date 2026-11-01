# Production DB backup — weekly snapshot on the prod VM + restore drill

Date: 2026-11-01. Ask (owner): "NIDP — Database backup to GCS: make this job have a backup on the third VM, every week."
Branch `feat/prod-db-backup` → PR into `dev`. Status: **VERIFIED for the weekly snapshot and the restore path; two gaps remain (below).**

## What was wrong / what changed

| | |
|---|---|
| Old job | `.github/workflows/nidp-db-backup.yml` — nightly, SSH to the GCP `nidp-stack-vm`, upload to a GCS bucket. **Every one of its last 8 scheduled runs (24–31 Oct) failed** → no backup existed. Retired to a manual-only stub. |
| New job | The existing staging snapshot job (`deploy/cloudpe/backup/db-snapshot.sh`) with two new targets: `prod-nidp` (Sunday **03:30** IST → `/opt/nidp/dumps`) and `prod-app` (Sunday **02:30** IST → `/opt/nivesh/dumps`), under `nice`+`ionice`, zstd:12, latest-only, root-only 700/600, **unencrypted** (no recipient key exists; same state as staging). |
| Restore path | `restore-snapshot.sh` was **broken for TimescaleDB** (found by the drill, below) — rewritten to restore in sections into an empty DB, with `--confirm-db`, extension creation and a catalog check. |

## Evidence (real output)

**Installs** — both `install.sh` runs ended with the job's own preflight: `PREFLIGHT OK` (nidp 18G, timescaledb 2.26.4, 18 hypertables, 47 GB free; app 840M).

**First snapshots, taken now**
```
prod-app : portfolio_ingestion_20261101.dump  133M in 46s, 6.3x, TOC entries 376, sha256 written
prod-nidp: nidp_20261101.dump                 2.0G in 763s, 9.1x, TOC entries 3375, sha256 written
           pruned previous /opt/nidp/dumps/nidp_from_staging.dump   (the seed dump from the staging clone; matched the retention pattern, as predicted)
sha256sum -c nidp_20261101.sha256 → nidp_20261101.dump: OK
```

**Restore drill** — snapshot → throwaway `timescale/timescaledb:2.26.4-pg16` container (2 CPUs, own data dir, prod DB only read) → compared with live prod:

| Attempt | Script state | Result |
|---|---|---|
| 1 | as it was (`--clean --if-exists --jobs 2`) | **FAILED**: 26× `chunk not found`, 5× `cannot truncate only a hypertable`, 5× `ONLY option not supported on hypertable operations`, 4 catalog `COPY failed` (FK). Log: `/root/restore-drill-attempt1-clean-mode.log` on the VM. Stopped before finishing. |
| 2 | + sections | Timescale branch **not taken**: my new extension check used `pg_restore --list \| grep -q`, which SIGPIPEs under `pipefail` (reproduced on the real 3,390-line listing). Fixed (capture, then grep). The test harness also raced the image's init restart. |
| 3 | sections, fixed | **PASSED** in 8.5 min (14:29:56 → 14:38:20). Exactly one error: `COPY failed for table "metadata" … install_timestamp already exists` (benign, the new install's own row). |

```
                       live prod   restored
indexes                  518        518
constraints              353        353
views / functions         76 / 247   76 / 247
hypertables               18         18          (chunk counts per hypertable: identical)
chunk catalog rows       269        269          chunk_constraint 538 / 538
extensions               timescaledb@public, vector@nidp   — identical
tables: 175 / 175; 167 identical row counts, 8 differ by 1–4 rows with the RESTORED copy lower:
  dq.gate_verdicts 4424/4423   nidp.corporate_announcements 197361/197357   nidp.daas_usage_log 841777/841775
  nidp.documents 111013/111009  nidp.job_log 10454/10450   nidp.parsed_archive_files 4531/4530
  nidp.raw_archive_files 4073/4072   nidp.validation_runs 4549/4548     (tables prod kept writing after the snapshot began)
```
Prod stayed healthy throughout (`/api/healthz` HTTP 200, 0.15 s during the restore). Scratch container and data were removed afterwards.

## NOT done / UNVERIFIED — read this

- **The weekly cron has not fired yet.** First scheduled runs: Sunday 2026-11-08 02:30 / 03:30 IST. Installed and preflight-checked; the manual runs used the same command line minus the cron wrapper (`nice`/`ionice` prefix is the only difference). Check `/opt/nidp/logs/db-snapshot.log` after that date.
- **Same disk as the database.** The snapshot protects against bad data, a bad migration or a dropped table. It does **not** protect against losing the VM or its disk. No off-VM copy exists.
- **MongoDB is not dumped** (users, sessions, `system_config.secrets`, feature flags) and neither is `/opt/nivesh/data/app`. The app-Postgres snapshot alone cannot restore a working app. `/opt/nivesh/dumps` still holds the Oct-31 staging-clone seed files (`app.dump`, `mongo.archive.gz`, `app-data.tar.gz`) — those are staging data, not prod backups.
- **Unencrypted**, latest-only (one copy; the previous one is deleted only after the new one verifies).
- **Not drilled:** `prod-app` restore (small, plain Postgres — the old non-Timescale path is unchanged), and a restore over a populated database (now refused by design).
- No alerting: a failed run is a non-zero exit and a log line (`MAILTO=""`).
