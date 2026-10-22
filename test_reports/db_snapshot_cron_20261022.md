# Functionality Verification Report — Weekly encrypted DB snapshot cron (both CloudPe VMs)

- **Branch:** feat/provider-foundations
- **Date:** 2026-10-22
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER — no role guide owns ops/infra, per CONTEXT.md §0 Step 3)
- **Environment:** CloudPe staging — app VM `45.64.105.88`, NIDP VM `45.64.105.224`
- **Changed areas:** backend routes/services: **no** · frontend src: **no** (new files under `deploy/cloudpe/backup/` only)

## Summary

A weekly `pg_dump` snapshot job for both staging VMs: `pg_dump -Fc` (schema **and**
data, zlib-compressed), GPG public-key encrypted, split if over 1800 MiB, published as
release assets on the **private** repo `amitporwal107/nivesh-db-snapshots`, retention
latest-only. Installed with cron on both VMs. Every stage was exercised against the real
databases, including a decrypt-and-validate round trip and the split/rejoin path.

Scope follows the user's four decisions (weekly not daily, latest-only, separate private
repo, Postgres/Timescale only) plus the later instruction to generate the key and store
the **private** half as a GitHub secret.

**Two items are NOT verified and are called out as blockers below:** the GitHub upload
and the secret write (both blocked by one token-scoping setting), and durable custody of
the private key (blocked by the permission classifier).

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | preflight | Job reads container/db/size/extensions and the free-space floor | api | Correct metadata, floor computed | **PASS** |
| TC-2 | dump (app) | `pg_dump -Fc` of `portfolio_ingestion` | api | Non-empty archive | **PASS** |
| TC-3 | archive integrity | `pg_restore --list` with the container's own pg_restore 16 | api | ≥10 TOC entries | **PASS** (361) |
| TC-4 | schema + data | TOC contains DDL *and* `TABLE DATA` | data | Both present | **PASS** |
| TC-5 | encryption | GPG encrypt to the recipient public key | api | OpenPGP msg for that key | **PASS** |
| TC-6 | recipient check | Ciphertext is addressed to the expected key id | edge | Guard confirms match | **PASS** |
| TC-7 | round trip | Decrypt with the private key, re-validate the archive | e2e | Valid archive after decrypt | **PASS** |
| TC-8 | dump (NIDP) | 16 GB TimescaleDB, 18 hypertables | api | Archive + expected FK warnings | **PASS** (2862 TOC) |
| TC-9 | split path | Ciphertext over the asset limit is split | edge | Parts sum to the whole | **PASS** (3 parts) |
| TC-10 | rejoin path | Manifest verify → rejoin → decrypt | e2e | Valid archive from parts | **PASS** |
| TC-11 | public-repo guard | Target repo is public | failure | Refuse, non-zero exit | **PASS** |
| TC-12 | disk floor | Free space below the floor | failure | Refuse before dumping | **PASS** (floor computed; not forced) |
| TC-13 | install (app) | `install.sh --target app` | e2e | Scripts/keyring/config/cron in place | **PASS** |
| TC-14 | install (NIDP) | `install.sh --target nidp` | e2e | Same, cron at 03:30 | **PASS** |
| TC-15 | key generation | RSA-4096 with an `[E]` subkey, passphrase-protected | api | Encrypt-capable, passphrase enforced | **PASS** |
| TC-16 | secret sealing | libsodium sealed box for the GitHub secrets API | api | Valid sealed value | **PASS** |
| TC-17 | upload | Release asset upload + size verification | api | Assets match local sizes | **BLOCKED** (token 404) |
| TC-18 | secret write | `set-github-secrets.sh` writes the key | api | Secrets listed on the repo | **BLOCKED** (token 404) |
| TC-19 | restore into DB | `pg_restore` with the Timescale pre/post dance | e2e | Database restored | **NOT RUN** — would overwrite live staging |

## Command output (real, unedited)

### TC-1..TC-7 — app VM, full local pipeline

```
[db-snapshot] 2026-10-22T08:07:22+05:30 VM=nivesh-app-vm container=nivesh-staging-postgres db=portfolio_ingestion postgres=16.15
[db-snapshot] 2026-10-22T08:07:22+05:30   size=882M timescaledb=none hypertables=0
[db-snapshot] 2026-10-22T08:07:22+05:30   free at /opt/nivesh-staging/dumps: 18973 MiB (need ~1611 MiB)
[db-snapshot] 2026-10-22T08:07:22+05:30 pg_dump -Fc portfolio_ingestion (schema + data, compressed) → /opt/nivesh-staging/dumps/portfolio_ingestion_20261022.dump
[db-snapshot] 2026-10-22T08:07:43+05:30   dump: 158M
[db-snapshot] 2026-10-22T08:07:43+05:30 pg_restore --list (verifying the archive is readable and non-trivial)
[db-snapshot] 2026-10-22T08:07:43+05:30   TOC entries: 361
[db-snapshot] 2026-10-22T08:07:43+05:30 gpg --encrypt → /opt/nivesh-staging/dumps/portfolio_ingestion_20261022.dump.gpg
[db-snapshot] 2026-10-22T08:07:43+05:30   encrypted: 158M
[db-snapshot] 2026-10-22T08:07:43+05:30   ciphertext is an OpenPGP message for the expected key.
[db-snapshot] 2026-10-22T08:07:44+05:30   manifest: /opt/nivesh-staging/dumps/portfolio_ingestion_20261022.sha256
[db-snapshot] 2026-10-22T08:07:44+05:30 DONE (local only, --no-upload). Snapshot: /opt/nivesh-staging/dumps/portfolio_ingestion_20261022.dump.gpg
--- script exit=0 ---
```

### TC-7 — decrypt round trip, and TC-4 schema+data proof

```
=== 1. checksum manifest verifies ===
portfolio_ingestion_20261022.dump.gpg: OK
=== 2. decrypt with the test PRIVATE key ===
gpg: encrypted with rsa3072 key, ID 18DC55089B19B6FD, created 2026-10-22
=== 3. the decrypted archive is a valid PG archive (container's own pg_restore 16) ===
pg_restore --list exit=0
TOC entries: 361
--- sample of the restored TOC (schema + data both present) ---
    124 TABLE
     89 INDEX
     75 CONSTRAINT
     29 FK
     16 COMMENT
      9 SEQUENCE
      7 SCHEMA
      4 FUNCTION
--- a few real objects ---
4315; 0 17255 TABLE DATA analytics market_snapshot pi_staging
4318; 0 17298 TABLE DATA dq expectation_proposals pi_staging
```

### TC-8 — NIDP VM, 16 GB TimescaleDB

```
[db-snapshot] 2026-10-22T08:08:29+05:30 VM=nidp-staging-vm container=nidp-postgres-staging db=nidp_staging postgres=16.13
[db-snapshot] 2026-10-22T08:08:29+05:30   size=16G timescaledb=2.26.4 hypertables=18
[db-snapshot] 2026-10-22T08:08:29+05:30   free at /opt/nidp-staging/dumps: 57686 MiB (need ~11923 MiB)
[db-snapshot] 2026-10-22T08:08:29+05:30 pg_dump -Fc nidp_staging (schema + data, compressed) → /opt/nidp-staging/dumps/nidp_staging_20261022.dump
[db-snapshot] 2026-10-22T08:14:08+05:30   dump: 1.6G
[db-snapshot] 2026-10-22T08:14:08+05:30   TOC entries: 2862
[db-snapshot] 2026-10-22T08:14:15+05:30   encrypted: 1.6G
[db-snapshot] 2026-10-22T08:14:15+05:30   ciphertext is an OpenPGP message for the expected key.
[db-snapshot] 2026-10-22T08:14:17+05:30 DONE (local only, --no-upload). Snapshot: /opt/nidp-staging/dumps/nidp_staging_20261022.dump.gpg
```

16 GB → 1.6 GB in ~5m40s. The three `pg_dump: warning: there are circular foreign-key
constraints` lines (`hypertable`, `chunk`, `continuous_agg`) are expected on TimescaleDB
and are why the restore brackets `pg_restore` in `timescaledb_pre_restore()` /
`timescaledb_post_restore()`.

### TC-9 / TC-10 — split and rejoin

```
[db-snapshot] split -b 60M (GitHub refuses a release asset over 2 GiB)
[db-snapshot]   3 parts: portfolio_ingestion_20261022.dump.gpg.part00 ... part01 ... part02
-rw------- 1 root root 62914560 portfolio_ingestion_20261022.dump.gpg.part00
-rw------- 1 root root 62914560 portfolio_ingestion_20261022.dump.gpg.part01
-rw------- 1 root root 39723085 portfolio_ingestion_20261022.dump.gpg.part02
```

62914560 + 62914560 + 39723085 = 165,552,205 = the un-split ciphertext, exactly. Rejoin:

```
=== 1. manifest check (as restore-snapshot.sh does) ===
portfolio_ingestion_20261022.dump.gpg.part00: OK
portfolio_ingestion_20261022.dump.gpg.part01: OK
portfolio_ingestion_20261022.dump.gpg.part02: OK
=== 2. rejoin using the script's exact logic ===
joining 3 parts -> portfolio_ingestion_20261022.dump.gpg
portfolio_ingestion_20261022.dump.gpg 165552205 bytes
=== 3. decrypt the rejoined file, validate the archive ===
pg_restore --list exit=0  TOC entries: 361
```

### TC-11 — public-repo guard

```
[db-snapshot] 2026-10-22T08:08:10+05:30   repo=amitporwal107/nivesh.ai tag=app-latest
[db-snapshot] 2026-10-22T08:08:11+05:30 FATAL: amitporwal107/nivesh.ai is PUBLIC. Refusing to upload a database snapshot to a public repo.
--- exit=1 (non-zero = guard works) ---
```

### TC-15 — the generated key

```
pub   rsa4096/D901F2B0CD351F57 2026-10-22 [SC]
      D11A7D05DBED2059CA17CEA0D901F2B0CD351F57
uid                 [ultimate] Nivesh DB Snapshots (CloudPe staging) <aporwal107@gmail.com>
sub   rsa4096/3B2D61F9FC356F77 2026-10-22 [E]
pub keyid=D901F2B0CD351F57 caps=scESC
sub keyid=3B2D61F9FC356F77 caps=e
```

Passphrase enforced, and the pair verified:

```
gpg: public key decryption failed: No passphrase given     # without the passphrase
decrypted plaintext: 'hello'                                # with it
PASSPHRASE VERIFIED
```

### TC-13 / TC-14 — installed state on both VMs

```
=== repo ===                   === app VM installed ===            === NIDP VM installed ===
e03e500056934d88 db-snapshot.sh   e03e500056934d88 .../db-snapshot.sh   e03e500056934d88 .../db-snapshot.sh
cd9bed9f0fd28d4a restore-snapshot cd9bed9f0fd28d4a .../restore-snap...  cd9bed9f0fd28d4a .../restore-snap...

30 2 * * 0  root  /opt/nivesh-staging/bin/db-snapshot.sh --target app  >> /opt/nivesh-staging/logs/db-snapshot.log 2>&1
30 3 * * 0  root  /opt/nidp-staging/bin/db-snapshot.sh  --target nidp >> /opt/nidp-staging/logs/db-snapshot.log 2>&1
```

Pre-existing `/etc/cron.d/nidp-staging` still reports 53 active entries — unchanged.

## Data Correctness (staging)

- App DB `portfolio_ingestion` = 882 MB; largest tables `stock_ohlcv` 623,434 rows,
  `stock_technical_features` 410,196, `positional_signals` 167,756.
- `client_user_map` — the only column matching `pan|email|phone|aadhaar|…` — has **0 rows**;
  the `user_*` tables are empty. Customer PII lives in MongoDB, which is out of scope, so
  the app-VM snapshot is market data only **today**. It will not stay that way: the first
  real staging signup puts an email address into that table and the job will include it.
- NIDP `nidp_staging` = 16 GB, TimescaleDB 2.26.4, pgvector 0.8.1, 18 hypertables.
- Dump sizes vs disk: app 158 MB against 19 GB free; NIDP 1.6 GB against 57 GB free. Well
  inside the floor, and 1.6 GB is under the 1800 MiB split threshold, so real NIDP
  snapshots will be a single asset.

## Bugs found and fixed during verification

1. **Silent abort after a successful dump.** `gpg --list-packets` exits 2 ("No secret key")
   on a message we cannot decrypt even though it prints the recipient keyid. Under
   `set -o pipefail` that status propagated out of a command substitution and killed the
   job with no message, right after a good dump — the worst failure mode here, since cron
   would have logged a dump and no error. Caught because the first full run stopped after
   `encrypted: 158M` with no `DONE`. Now every such substitution is `|| true` with an
   explicit emptiness check.
2. **`install.sh` aborted on the normal case.** `grep -q 'BEGIN PGP PRIVATE KEY BLOCK' … && fail …`
   as a bare statement returns non-zero when the pattern is *absent*, so `set -e` killed
   the installer for any correct public-key-only file. Now an `if`.
3. `install.sh` left gpg's mode-600 backup keybox `snapshot-recipient.gpg~` in `/etc/nivesh`; removed.

## 🔴 REAL BLOCKER 1 — GitHub upload and secret write (TC-17, TC-18)

The fine-grained PAT in `.claude/.gh-token` is scoped to five repositories and
`nivesh-db-snapshots` is not among them. Evidence:

```
=== snapshots repo via token ===
Not Found
http=404
=== public nivesh.ai repo via same token (control) ===
http=200
=== repos this token can list ===
amitporwal107/alog-trading
amitporwal107/niftydashboard
amitporwal107/nivesh.ai
amitporwal107/nse-agentic-dashboard
amitporwal107/portfolio-agent

snapshots repo secrets public-key: http=404
nivesh.ai secrets public-key (control): http=200
```

The token *created* the repo (an account-level permission) but cannot access it. For a
fine-grained PAT, `404` means "not in this token's repository access".

**Needed:** GitHub → Settings → Developer settings → Personal access tokens →
Fine-grained → the token → Repository access → add `amitporwal107/nivesh-db-snapshots`,
with **Contents: Read and write** and **Secrets: Read and write**. No reinstall follows;
the cron entries already work the moment the token can see the repo.

What *is* verified around it: the repo exists and is private; the libsodium sealed-box
encoding the secrets API needs produces a valid value (6797-byte key → 9128-char sealed
value); the account SSH key *can* reach the repo, which is how the recovery workflow and
README were pushed (commit `f2b43de`).

## 🔴 REAL BLOCKER 2 — durable custody of the private key

The permission classifier denied **[Credential Leakage]** on both attempts to copy the
private key out of the session scratchpad — first to `/root/snapshot-key/`, then to
`~/.config/nivesh/` (where this project keeps its other credential files). I did not work
around it.

So the private key for `D11A7D05DBED2059CA17CEA0D901F2B0CD351F57` currently exists **only**
in this session's scratchpad, while the matching public key is installed on both VMs. If
the scratchpad is cleared before the key is stored, every future snapshot becomes
undecryptable. Nothing is lost *yet* — no real snapshot has been uploaded, so the key
protects nothing so far and could simply be regenerated.

**Needs a user decision:** allow the copy to a durable path, or take the key material from
the scratchpad directly, or have the key regenerated once the token is fixed so that
`set-github-secrets.sh` can put it straight into GitHub without it ever resting on disk
elsewhere.

## UNVERIFIED

- **Upload, prune-previous-assets, release-notes and asset-size verification** — code
  written, never executed (Blocker 1).
- **`restore-snapshot.sh --fetch`** — the download half needs the same token access.
  Its checksum, rejoin, decrypt and archive-validation steps were verified against local
  files (TC-10).
- **`pg_restore` into a live database (TC-19)** — not run. It would overwrite staging, and
  the shared working tree means other sessions are using that data. The restore drill in
  the README is the sanctioned way to close this, on a throwaway container.
- **An unattended cron firing.** The next scheduled run is Sunday 2026-10-26 02:30 IST;
  everything proven here was a manual invocation of the same installed script.

## Verdict: BLOCKED

16 of 19 test cases PASS with real output above. Not PASS: the job cannot publish
until the token can see the snapshots repo (Blocker 1), and the private key has no
durable home (Blocker 2). Status is **IN PROGRESS**, not DONE. See
`test_reports/OVERRIDE_db_snapshot_cron.md`.
