# Weekly DB snapshots — CloudPe staging VMs

A compressed `pg_dump` of each staging database, every week, encrypted and kept
**on that VM's own disk**. Nothing is uploaded anywhere.

| | app VM | NIDP VM |
|---|---|---|
| Host | `45.64.105.88` (`nivesh-app-vm`) | `45.64.105.224` (`nidp-staging-vm`) |
| Container | `nivesh-staging-postgres` | `nidp-postgres-staging` |
| Database | `portfolio_ingestion` (PG 16.15) | `nidp_staging` (PG 16.13 + TimescaleDB 2.26.4, 18 hypertables) |
| Schedule | **Sunday 02:30 IST** | **Sunday 03:30 IST** |
| Cron file | `/etc/cron.d/nivesh-staging-db-snapshot` | `/etc/cron.d/nidp-staging-db-snapshot` |
| Snapshots | `/opt/nivesh-staging/dumps` (700) | `/opt/nidp-staging/dumps` (700) |
| Log | `/opt/nivesh-staging/logs/db-snapshot.log` | `/opt/nidp-staging/logs/db-snapshot.log` |

## Production (CloudPe prod VM, added 2026-11-01)

Production runs both stacks on **one** VM (`45.64.105.249`, see `deploy/cloudpe-prod/README.md`), so the same
job runs there with two extra targets. It replaced the nightly GitHub workflow *"NIDP — Database backup to
GCS"*, whose GCP VM and bucket no longer exist (its last 8 scheduled runs all failed — it produced no backup).

| | NIDP warehouse | App Postgres |
|---|---|---|
| Target | `--target prod-nidp` | `--target prod-app` |
| Container | `nidp-postgres` | `nivesh-postgres` |
| Database | `nidp` (PG 16.13 + TimescaleDB 2.26.4, 18 hypertables, ~18 GB) | `portfolio_ingestion` (PG 16.15, ~840 MB) |
| Schedule | **Sunday 03:30 IST** | **Sunday 02:30 IST** |
| Cron file | `/etc/cron.d/nidp-prod-db-snapshot` | `/etc/cron.d/nivesh-prod-db-snapshot` |
| Snapshots | `/opt/nidp/dumps` (700) | `/opt/nivesh/dumps` (700) |
| Log | `/opt/nidp/logs/db-snapshot.log` | `/opt/nivesh/logs/db-snapshot.log` |

Both run under `nice -n 10 ionice -c2 -n7` so a dump never competes with the site. Installed **unencrypted**
(`--no-encrypt`, same state as staging; root-only, mode 600, in 700 folders) because no recipient key exists yet.
Install / reinstall: `sudo bash deploy/cloudpe/backup/install.sh --target prod-nidp --no-encrypt` (and `prod-app`).

**The snapshot sits on the same disk as the database it protects.** It covers a bad migration, bad data or a
dropped table; it does **not** cover losing the VM or its disk. Copy it elsewhere for that.

**MongoDB is not covered** (users, sessions, `system_config.secrets`, feature flags live in `nivesh-mongo`),
nor `/opt/nivesh/data/app`. The app snapshot alone cannot restore a working app.

The first prod run also prunes the seed dump `/opt/nidp/dumps/nidp_from_staging.dump` (it matches the
`nidp_*.dump` retention pattern and is superseded by the first real snapshot).

## Compression

`pg_dump -Fc` with an **explicit** `--compress=` — explicit so a changed default
or a build without the algorithm can never silently produce a fat dump, and the
preflight probes the method before committing to a 16 GB dump.

Measured on the real 882 MB app database:

| method | dump | ratio | time |
|---|---|---|---|
| `none` | 679.5 MB | 1.3× | 6s |
| `gzip:6` (pg_dump's own default) | 165.5 MB | 5.5× | 20s |
| `gzip:9` | 162.9 MB | 5.6× | 46s |
| `zstd:3` | 166.2 MB | 5.5× | 7s |
| **`zstd:12`** (what is configured) | **141.1 MB** | **6.6×** | 49s |

`zstd:12` is the default: 15% smaller than pg_dump's own default for time that
does not matter in a 02:30 Sunday window. `zstd:3` is the better choice if dump
duration ever does matter — same ratio as gzip at a third of the time — and both
`gzip` and `zstd` archives are readable by the pg_restore in these containers
**and** by the hosts' pg_restore 18.6 (verified). `SNAPSHOT_COMPRESS=none` is
refused outright.

## Design decisions (and why)

- **Weekly, latest only, on the VM.** Each run keeps the new snapshot and then
  deletes the previous one. There is no history and no off-VM copy: a snapshot
  dies with its VM, and a corruption noticed on day 8 has already overwritten
  the only good copy. That is the explicit instruction; see *Known gaps*.
- **`pg_dump -Fc`** — one file, compressed, holds **schema and data**, and
  supports parallel `pg_restore`. Produced by the *container's* pg_dump 16, not
  the host's 18: an archive written by a newer pg_dump can be unreadable by the
  pg_restore that would restore it.
- **Public-key encryption, no passphrase on the VM.** The VMs carry only the
  public key, so compromising a VM does not expose its backups. The direct
  consequence: **nothing on either VM can verify a restore.** See *Restore drill*.
- **The dump never goes into git.** GitHub rejects any file over 100 MB pushed
  into history, and a weekly 100 MB–2 GB blob would grow the repo forever since
  git history is immutable. An opt-in GitHub *release asset* path exists (see
  below) but is **off**; moving snapshots off-VM is an open question.

## What the job refuses to do

It exits non-zero rather than produce a misleading success:

- the Postgres container is not running;
- `pg_dump` in that container rejects the configured compression method
  (probed in preflight, before the real dump);
- `SNAPSHOT_COMPRESS=none`;
- free space at the dump directory is under ~⅔ of the database size + 1 GiB
  (this VM has filled its disk before and taken the stack down);
- the recipient public key is missing from the keyring;
- `pg_dump` fails, or the archive lists fewer than 10 TOC entries;
- the ciphertext is not an OpenPGP message addressed to the expected key.

The previous snapshot is deleted only *after* the new one is complete and
verified, so a failed run leaves the last good snapshot in place.

## The encryption key

| | |
|---|---|
| Fingerprint | `D11A7D05DBED2059CA17CEA0D901F2B0CD351F57` |
| Key | RSA 4096 `[SC]` primary + RSA 4096 `[E]` subkey, no expiry |
| UID | `Nivesh DB Snapshots (CloudPe staging) <aporwal107@gmail.com>` |
| Created | 2026-10-22 |

No expiry is deliberate: GPG refuses to *encrypt* to an expired key, so an
expiry date would turn into a silently failing backup job years from now.

Only the **public** key is installed, on both VMs, at
`/etc/nivesh/snapshot-recipient.gpg`. The private key is not on either VM and
must not be put there — that is what makes a VM compromise not also a backup
compromise.

> ⚠️ **An encrypted snapshot is worthless without the private key.** Custody of
> that key is an open item, not something this directory can solve. Until it is
> settled, either keep the key somewhere durable yourself or run with
> `--no-encrypt` (below), which trades at-rest encryption for the certainty that
> the dump can still be read. `set-github-secrets.sh` can escrow the key as
> Actions secrets on a private repo, which needs no dump to leave the VM.

### Unencrypted mode

`install.sh --no-encrypt` writes the `.dump` straight to `/opt/<stack>/dumps`
(mode 600, root-only). Defensible while the file never leaves the VM — the
database on the same disk is not encrypted at rest either — and it removes the
lost-key failure mode entirely. Encrypt at the point the dump leaves the VM
instead. The job logs a loud warning on every such run.

## Install

```bash
# app VM
sudo bash /opt/nivesh-staging/repo/deploy/cloudpe/backup/install.sh \
    --target app --pubkey-file /root/snapshot-pubkey.asc

# NIDP VM
sudo bash /path/to/deploy/cloudpe/backup/install.sh \
    --target nidp --pubkey-file /root/snapshot-pubkey.asc

# options: --compress zstd:3 · --no-encrypt
```

No GitHub token is involved. The installer imports the public key, writes
`/etc/nivesh/db-snapshot.env` (mode 600), installs the cron file, and then runs
the job's own `--preflight` so a broken install fails at install time instead of
silently at 02:30 on Sunday. Rotating the key = re-run `install.sh`.

## Run one now / debug

```bash
sudo /opt/nivesh-staging/bin/db-snapshot.sh --target app --preflight   # checks only
sudo /opt/nivesh-staging/bin/db-snapshot.sh --target app               # full run
sudo tail -40 /opt/nivesh-staging/logs/db-snapshot.log
sudo ls -la /opt/nivesh-staging/dumps/
```

## Restore

Run this **where the private key is** — not on the VMs.

```bash
# decrypt a snapshot copied off the VM
gpg --output restored.dump --decrypt portfolio_ingestion_YYYYMMDD.dump.gpg

# restore it into a container (prompts for the database name before overwriting)
./restore-snapshot.sh --restore ./restored.dump --container nidp-postgres-staging
```

On TimescaleDB the restore wraps `pg_restore` in `timescaledb_pre_restore()` /
`timescaledb_post_restore()` — chunk DDL under `_timescaledb_internal` cannot be
replayed with the extension active. `post_restore` runs even if `pg_restore`
dies, or the database is left stuck in restore mode.

`restore-snapshot.sh --fetch` downloads from a GitHub release instead; it is
only useful with the opt-in publishing path below.

## Publishing elsewhere (opt-in, currently OFF)

A GitHub release-asset path is implemented but not enabled:
`SNAPSHOT_DESTINATION=github` with `SNAPSHOT_REPO` and `SNAPSHOT_GITHUB_TOKEN`
publishes to a **private** repo, splitting anything over 1800 MiB because GitHub
refuses a release asset over 2 GiB, and refusing outright if the repo is public.
Enabling it needs a token whose *repository access* lists that repo — a
fine-grained PAT returns `404`, not `403`, when it does not.

This is one option among several for getting snapshots off-VM (object storage,
`rsync` to another host, cross-VM copy). None is in use yet.

## Restore drill (do not skip)

Because the VMs hold no private key, the job can prove the *archive* was good
and the *ciphertext* is addressed correctly, but **it cannot prove the snapshot
is restorable**. Only a human with the private key can. Quarterly:

1. copy a snapshot off the VM and decrypt it;
2. restore into a throwaway local Postgres container, not staging;
3. confirm table and row counts look like the live database;
4. note the date and result in `test_reports/`.

An un-drilled encrypted backup is a guess, not a backup.

## Known gaps

- **No off-VM copy.** The snapshot shares a disk with the database it protects,
  so it covers a bad migration or an accidental `DROP`, not VM or disk loss.
  This is the biggest gap and is deliberate for now.
- **MongoDB is not covered.** Users, sessions, portfolios and
  `system_config.secrets` live in `nivesh-staging-mongo`, so the app-VM snapshot
  **cannot restore a working app** on its own. Postgres-only was the chosen scope.
- **Production** is covered since 2026-11-01 (see above) — but the same two gaps apply there: no off-VM
  copy, and MongoDB is not dumped.
- **No alerting.** A failed run is a non-zero exit and a line in the log; with
  `MAILTO=""` nothing pages anyone. Check the log, or wire the job into the
  existing Grafana/Loki stack.
- **Key custody is unresolved** — see the warning above.

## Files here

| File | Role |
|---|---|
| `db-snapshot.sh` | the job: dump → verify → encrypt → checksum → prune previous |
| `restore-snapshot.sh` | decrypt/rejoin → `pg_restore` (with the Timescale dance; creates the extension in an empty database and repairs/refuses a lost chunk catalog) |
| `install.sh` | installs the above, the keyring, the config and the cron entry |
| `set-github-secrets.sh` | optional: escrow the private key as Actions secrets |
| `db-snapshot-app.cron` | Sunday 02:30 IST, app VM |
| `db-snapshot-nidp.cron` | Sunday 03:30 IST, NIDP VM |
| `db-snapshot-prod-app.cron` | Sunday 02:30 IST, prod VM (app Postgres) |
| `db-snapshot-prod-nidp.cron` | Sunday 03:30 IST, prod VM (NIDP warehouse) |
