# Weekly encrypted DB snapshots — CloudPe staging VMs

A `pg_dump` of each staging database, every week, GPG-encrypted to the owner's
public key and published as a release asset in a **private** GitHub repo.

| | app VM | NIDP VM |
|---|---|---|
| Host | `45.64.105.88` (`nivesh-app-vm`) | `45.64.105.224` (`nidp-staging-vm`) |
| Container | `nivesh-staging-postgres` | `nidp-postgres-staging` |
| Database | `portfolio_ingestion` (PG 16.15) | `nidp_staging` (PG 16.15 + TimescaleDB 2.26.4, 18 hypertables) |
| Schedule | **Sunday 02:30 IST** | **Sunday 03:30 IST** |
| Cron file | `/etc/cron.d/nivesh-staging-db-snapshot` | `/etc/cron.d/nidp-staging-db-snapshot` |
| Release tag | `app-latest` | `nidp-latest` |
| Log | `/opt/nivesh-staging/logs/db-snapshot.log` | `/opt/nidp-staging/logs/db-snapshot.log` |

Snapshots repo: **`amitporwal107/nivesh-db-snapshots`** (private).

## Design decisions (and why)

- **Weekly, latest only.** Each run deletes the previous release's assets before
  uploading the new ones, then prunes the previous local copy *after* the upload
  verifies. There is no history: a bad week discovered late is not recoverable.
  That was the explicit instruction; raising retention means either more disk
  (the NIDP dump is GB-scale) or more release assets.
- **`pg_dump -Fc`** — one file, zlib-compressed, holds **schema and data**, and
  supports parallel `pg_restore`. Produced by the *container's* pg_dump 16, not
  the host's 18: an archive written by a newer pg_dump can be unreadable by the
  pg_restore that would restore it.
- **Public-key encryption, no passphrase on the VM.** The VMs carry only the
  public key, so compromising a VM does not expose its backups. The direct
  consequence: **nothing on either VM can verify a restore.** See *Restore drill*.
- **Release assets, not committed files.** GitHub rejects any file over 100 MB
  pushed into git history, and a weekly multi-GB blob would grow the repo
  forever since git history is immutable. Release assets stay out of history and
  allow up to 2 GiB each; the job splits anything larger with `split` and the
  restore script rejoins it.
- **A separate private repo.** `nivesh.ai` itself is public, where encrypted or
  not, the ciphertext would be world-downloadable and permanently harvestable,
  and the NIDP warehouse holds provider-licensed (Trendlyne/Kite/NSE) data.

## What the job refuses to do

It exits non-zero rather than produce a misleading success:

- the Postgres container is not running;
- free space at the dump directory is under ~⅔ of the database size + 1 GiB
  (this VM has filled its disk before and taken the stack down);
- the recipient public key is missing from the keyring;
- the target repo is **public**, or the token cannot push to it;
- `pg_dump` fails, or the archive lists fewer than 10 TOC entries;
- the ciphertext is not an OpenPGP message addressed to the expected key;
- an uploaded asset's size on GitHub does not match the local file.

## The encryption key

| | |
|---|---|
| Fingerprint | `D11A7D05DBED2059CA17CEA0D901F2B0CD351F57` |
| Key | RSA 4096 `[SC]` primary + RSA 4096 `[E]` encryption subkey, no expiry |
| UID | `Nivesh DB Snapshots (CloudPe staging) <aporwal107@gmail.com>` |
| Created | 2026-10-22 |
| Passphrase | 32 random bytes, base64 |

No expiry is deliberate: GPG refuses to *encrypt* to an expired key, so an
expiry date would turn into a silently failing backup job years from now.

Only the **public** key is installed, on both VMs, at
`/etc/nivesh/snapshot-recipient.gpg`. The private key is not on either VM and
must not be put there — that is what makes a VM compromise not also a backup
compromise.

### Where the private key lives

Stored as Actions secrets on the private snapshots repo:

| Secret | Holds |
|---|---|
| `SNAPSHOT_GPG_PRIVATE_KEY` | the ASCII-armored, passphrase-protected private key |
| `SNAPSHOT_GPG_PASSPHRASE` | its passphrase |
| `SNAPSHOT_GPG_FINGERPRINT` | the fingerprint |

Written by `set-github-secrets.sh`, which reads every value from a **file** so
nothing reaches the process list or shell history, and refuses outright if the
target repo is public.

**Actions secrets are write-only.** Once stored, no one — not the UI, not the
API, not the repo owner — can read a value back; only a workflow run can
decrypt one. The `Export snapshot key` workflow in the snapshots repo is
therefore the sole recovery path, and it self-tests that the stored key and
passphrase actually decrypt a probe message before handing them over.

**This puts the ciphertext and its key in the same GitHub account**, so one
account compromise opens the backups. To avoid that, delete the
`SNAPSHOT_GPG_PASSPHRASE` secret and keep the passphrase only in a password
manager: the key file alone is useless without it.

Rotating the key means re-running `install.sh` on both VMs with the new public
key and `set-github-secrets.sh` with the new private key. **Snapshots taken
with the old key still need the old key** — keep it until those are gone, which
with latest-only retention is one week.

## Install

Needs, on the VM: the owner's **public** key file and a GitHub token with
`contents:write` on the snapshots repo (in a file — never on the command line).

```bash
# app VM
sudo bash /opt/nivesh-staging/repo/deploy/cloudpe/backup/install.sh \
    --target app --repo amitporwal107/nivesh-db-snapshots \
    --token-file /root/.gh-snapshot-token --pubkey-file /root/owner-pubkey.asc

# NIDP VM
sudo bash /path/to/deploy/cloudpe/backup/install.sh \
    --target nidp --repo amitporwal107/nivesh-db-snapshots \
    --token-file /root/.gh-snapshot-token --pubkey-file /root/owner-pubkey.asc
```

The installer imports the key, writes `/etc/nivesh/db-snapshot.env` (mode 600),
installs the cron file, and then runs the job's own `--preflight` so a broken
install fails at install time instead of silently at 02:30 on Sunday.

Rotating the key or the token = re-run `install.sh` with the new file.

## Run one now / debug

```bash
sudo /opt/nivesh-staging/bin/db-snapshot.sh --target app --preflight   # checks only
sudo /opt/nivesh-staging/bin/db-snapshot.sh --target app               # full run
sudo /opt/nivesh-staging/bin/db-snapshot.sh --target app --no-upload   # local, no GitHub
tail -40 /opt/nivesh-staging/logs/db-snapshot.log
```

## Restore

Run this **where the private key is** (your laptop) — not on the VMs.

```bash
# fetch, checksum, rejoin parts, decrypt
./restore-snapshot.sh --target nidp --fetch --out ./snap

# restore into a container (prompts for the database name before overwriting)
./restore-snapshot.sh --restore ./snap/nidp_staging_YYYYMMDD.dump \
                      --container nidp-postgres-staging
```

On TimescaleDB the restore wraps `pg_restore` in
`timescaledb_pre_restore()` / `timescaledb_post_restore()` — chunk DDL under
`_timescaledb_internal` cannot be replayed with the extension active.
`post_restore` runs even if `pg_restore` dies, or the database is left stuck in
restore mode.

## Restore drill (do not skip)

Because the VMs hold no private key, the job can prove the *archive* was good
and the *ciphertext* is addressed correctly, but **it cannot prove the snapshot
is restorable**. Only a human with the private key can. Quarterly:

1. `restore-snapshot.sh --target app --fetch` on your laptop;
2. restore into a throwaway local Postgres container, not staging;
3. confirm table and row counts look like the live database;
4. note the date and result in `test_reports/`.

An un-drilled encrypted backup is a guess, not a backup.

## Known gaps

- **MongoDB is not covered.** Users, sessions, portfolios and
  `system_config.secrets` live in `nivesh-staging-mongo`, so the app-VM snapshot
  **cannot restore a working app** on its own. Postgres-only was the chosen
  scope; a `mongodump` beside it would close this.
- **Production is not covered.** The old GCP app VM (`34.47.250.214`) is
  unreachable and prod was never migrated to CloudPe.
- **No alerting.** A failed run is a non-zero exit and a line in the log; with
  `MAILTO=""` nothing pages anyone. Check the log, or wire the job into the
  existing Grafana/Loki stack.
- **One week of exposure.** Latest-only means a corruption noticed on day 8 has
  already overwritten the only good copy.

## Files here

| File | Role |
|---|---|
| `db-snapshot.sh` | the job: dump → verify → encrypt → split → upload → prune |
| `restore-snapshot.sh` | fetch → checksum → rejoin → decrypt → `pg_restore` |
| `install.sh` | installs the above, the keyring, the config and the cron entry on one VM |
| `set-github-secrets.sh` | stores the private key + passphrase as Actions secrets |
| `db-snapshot-app.cron` | Sunday 02:30 IST, app VM |
| `db-snapshot-nidp.cron` | Sunday 03:30 IST, NIDP VM |

## Status as of 2026-10-22

Installed and verified on both VMs; **uploads are blocked on one GitHub setting.**

The repo-access list of the fine-grained PAT in `.claude/.gh-token` covers five
repositories, and `nivesh-db-snapshots` is not one of them. The token could
*create* the repo (that is an account-level permission) but gets `404` on it,
while `nivesh.ai` returns `200` — for a fine-grained PAT, `404` means "not in
this token's repository access", not "no such repo". Both the release upload and
`set-github-secrets.sh` fail there.

To unblock, on GitHub → Settings → Developer settings → Personal access tokens →
Fine-grained → the token → **Repository access**: add
`amitporwal107/nivesh-db-snapshots`, with **Contents: Read and write** and
**Secrets: Read and write**. Then:

```bash
sudo /opt/nivesh-staging/bin/db-snapshot.sh --target app --preflight   # should pass
sudo /opt/nivesh-staging/bin/db-snapshot.sh --target app               # first real snapshot
```

No reinstall is needed — the cron entries are already in place and start
working as soon as the token can see the repo. Until then each Sunday run fails
fast, at the repo check and *before* dumping anything, leaving a `FATAL` line in
`db-snapshot.log`.
