# Functionality Verification Report — Weekly compressed DB snapshot cron (both CloudPe VMs)

- **Branch:** feat/provider-foundations
- **Date:** 2026-10-22
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER — no role guide owns ops/infra, per CONTEXT.md §0 Step 3)
- **Environment:** CloudPe staging — app VM `45.64.105.88`, NIDP VM `45.64.105.224`
- **Changed areas:** backend routes/services: **no** · frontend src: **no** (new files under `deploy/cloudpe/backup/` only)

## Summary

A weekly `pg_dump` snapshot job on both staging VMs: `pg_dump -Fc` with explicit
`--compress=zstd:12` (schema **and** data), GPG public-key encrypted, written to that VM's
own disk, retention latest-only. Installed with cron on both VMs and exercised end to end
against the real databases, including a full decrypt-and-validate round trip with the
real private key on both snapshots.

Scope reflects the user's decisions in order: weekly rather than daily, latest-only,
Postgres/Timescale only (Mongo excluded), and finally **local VM disk only — no GitHub,
nothing committed**. The GitHub release-asset path remains in the code as an opt-in
(`SNAPSHOT_DESTINATION=github`) and is **off**.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | preflight | Reads container/db/size/extensions, probes compression, checks disk floor | api | Correct metadata, floor computed | **PASS** |
| TC-2 | compression | Explicit `--compress` actually compresses | data | Materially smaller than `none` | **PASS** (6.6× / 13.7×) |
| TC-3 | compression | `SNAPSHOT_COMPRESS=none` is refused | failure | Non-zero exit | **PASS** |
| TC-4 | compression | Unsupported method fails in preflight, not after the dump | failure | Fail before dumping | **PASS** |
| TC-5 | dump (app) | `pg_dump -Fc --compress=zstd:12` of `portfolio_ingestion` | api | Non-empty archive | **PASS** |
| TC-6 | archive integrity | `pg_restore --list` with the container's own pg_restore 16 | api | ≥10 TOC entries | **PASS** (361) |
| TC-7 | schema + data | TOC holds DDL *and* `TABLE DATA` | data | Both present | **PASS** |
| TC-8 | encryption | Encrypt to the recipient public key | api | OpenPGP msg for that key | **PASS** |
| TC-9 | recipient check | Ciphertext addressed to the expected key id | edge | Guard confirms match | **PASS** |
| TC-10 | round trip (app) | Decrypt with the **real** private key, re-validate | e2e | Valid archive, schema+data | **PASS** |
| TC-11 | dump (NIDP) | 16 GB TimescaleDB, 18 hypertables | api | Archive + expected FK warnings | **PASS** (2862 TOC) |
| TC-12 | round trip (NIDP) | Decrypt the 1.2 GB warehouse snapshot, re-validate | e2e | Valid archive | **PASS** |
| TC-13 | Timescale internals | Hypertable chunks are in the archive | data | `_timescaledb_internal` present | **PASS** (1625 objects) |
| TC-14 | checksum | Manifest verifies after an off-VM transfer | e2e | sha256 matches | **PASS** |
| TC-15 | retention | Previous snapshot pruned after the new one verifies | e2e | Exactly one snapshot kept | **PASS** |
| TC-16 | install (app) | `install.sh --target app` | e2e | Scripts/keyring/config/cron in place | **PASS** |
| TC-17 | install (NIDP) | `install.sh --target nidp` | e2e | Same, cron at 03:30 | **PASS** |
| TC-18 | no secrets | Config holds no token in local mode | edge | No credential in the file | **PASS** |
| TC-19 | key generation | RSA-4096 with `[E]` subkey, passphrase-protected | api | Encrypt-capable, passphrase enforced | **PASS** |
| TC-20 | split path | Over-limit ciphertext splits and rejoins (github mode only) | edge | Parts sum to the whole | **PASS** (3 parts) |
| TC-21 | public-repo guard | github mode against a public repo | failure | Refuse, non-zero exit | **PASS** |
| TC-22 | restore into DB | `pg_restore` with the Timescale pre/post dance | e2e | Database restored | **NOT RUN** — would overwrite live staging |

## Compression — measured, not assumed (TC-2)

Real `pg_dump` runs against the 882 MB app database:

| method | dump | ratio | time |
|---|---|---|---|
| `none` | 679,548,435 | 1.3× | 6s |
| `gzip:6` (pg_dump's default) | 165,533,402 | 5.5× | 20s |
| `gzip:9` | 162,855,683 | 5.6× | 46s |
| `zstd:3` | 166,235,006 | 5.5× | 7s |
| **`zstd:12`** (configured) | **141,041,963** | **6.5×** | 48s |

Note `zlib` is **not** a valid method name in these builds — `gzip` is (my earlier wording
was wrong). `zstd` is available in both the `postgres:16-alpine` and
`timescale/timescaledb:2.26.4-pg16` images, and zstd archives are readable by the
containers' pg_restore 16 **and** by the hosts' pg_restore 18.6 (all verified exit 0).

On the warehouse the gain is much larger — 1.2 GB vs 1.6 GB for `gzip:6`, a 22.5% saving
for 207s more runtime (546s vs 339s). At 03:30 Sunday, with the warehouse's next cron job
at 06:00, there is ~2.5h of headroom, so the slower setting is affordable. `zstd:3` is one
config line away if dump duration ever matters.

## Command output (real, unedited)

### TC-5..TC-9, TC-15 — app VM, full run

```
[db-snapshot] 2026-10-22T08:42:40+05:30 VM=nivesh-app-vm container=nivesh-staging-postgres db=portfolio_ingestion postgres=16.15
[db-snapshot] 2026-10-22T08:42:40+05:30   size=882M timescaledb=none hypertables=0
[db-snapshot] 2026-10-22T08:42:40+05:30   compress=zstd:12 encrypt=true destination=local retention=latest-only
[db-snapshot] 2026-10-22T08:42:40+05:30   recipient=D11A7D05DBED2059CA17CEA0D901F2B0CD351F57
[db-snapshot] 2026-10-22T08:42:40+05:30   free at /opt/nivesh-staging/dumps: 18435 MiB (need ~1611 MiB)
[db-snapshot] 2026-10-22T08:42:40+05:30 pg_dump -Fc --compress=zstd:12 portfolio_ingestion (schema + data) → /opt/nivesh-staging/dumps/portfolio_ingestion_20261022.dump
[db-snapshot] 2026-10-22T08:43:29+05:30   dump: 135M in 49s
[db-snapshot] 2026-10-22T08:43:29+05:30   compressed 6.6x vs the live database
[db-snapshot] 2026-10-22T08:43:29+05:30 pg_restore --list (verifying the archive is readable and non-trivial)
[db-snapshot] 2026-10-22T08:43:29+05:30   TOC entries: 361
[db-snapshot] 2026-10-22T08:43:29+05:30 gpg --encrypt → /opt/nivesh-staging/dumps/portfolio_ingestion_20261022.dump.gpg
[db-snapshot] 2026-10-22T08:43:29+05:30   encrypted: 135M
[db-snapshot] 2026-10-22T08:43:29+05:30   ciphertext is an OpenPGP message for the expected key.
[db-snapshot] 2026-10-22T08:43:29+05:30   manifest: /opt/nivesh-staging/dumps/portfolio_ingestion_20261022.sha256
[db-snapshot] 2026-10-22T08:43:29+05:30 kept in /opt/nivesh-staging/dumps:
[db-snapshot] 2026-10-22T08:43:29+05:30   portfolio_ingestion_20261022.dump.gpg  135M
[db-snapshot] 2026-10-22T08:43:29+05:30   portfolio_ingestion_20261022.sha256  104
[db-snapshot] 2026-10-22T08:43:29+05:30 DONE — nivesh-app-vm portfolio_ingestion snapshot on this VM's disk (started 2026-10-22T08:42:40+05:30, took 49s)
--- exit=0 ---
```

### TC-10 — app round trip with the REAL private key

```
=== 1. manifest ===
portfolio_ingestion_20261022.dump.gpg: OK
=== 2. decrypt with the REAL private key ===
gpg: encrypted with rsa4096 key, ID 3B2D61F9FC356F77, created 2026-10-22
      "Nivesh DB Snapshots (CloudPe staging) <aporwal107@gmail.com>"
decrypted: 141041963 bytes
=== 3. zstd:12 archive readable by the container's pg_restore 16? ===
exit=0
TOC entries: 361
=== 4. schema + data present ===
    124 TABLE
     89 INDEX
     75 CONSTRAINT
     29 FK
     16 COMMENT
TABLE DATA entries: 62
```

### TC-11 — NIDP VM, 16 GB TimescaleDB

```
[db-snapshot] 2026-10-22T08:52:44+05:30   dump: 1.2G in 541s
[db-snapshot] 2026-10-22T08:52:44+05:30   compressed 13.7x vs the live database
[db-snapshot] 2026-10-22T08:52:44+05:30   TOC entries: 2862
[db-snapshot] 2026-10-22T08:52:48+05:30   encrypted: 1.2G
[db-snapshot] 2026-10-22T08:52:48+05:30   ciphertext is an OpenPGP message for the expected key.
[db-snapshot] 2026-10-22T08:52:49+05:30 kept in /opt/nidp-staging/dumps:
[db-snapshot] 2026-10-22T08:52:49+05:30   nidp_staging_20261022.dump.gpg  1.2G
[db-snapshot] 2026-10-22T08:52:49+05:30   nidp_staging_20261022.sha256  97
[db-snapshot] 2026-10-22T08:52:49+05:30 DONE — nidp-staging-vm nidp_staging snapshot on this VM's disk (started 2026-10-22T08:43:43+05:30, took 546s)
```

The three `pg_dump: warning: there are circular foreign-key constraints` lines
(`hypertable`, `chunk`, `continuous_agg`) are expected on TimescaleDB and are why the
restore brackets `pg_restore` in `timescaledb_pre_restore()` / `timescaledb_post_restore()`.

### TC-12..TC-14 — NIDP round trip with the REAL private key

```
=== sha256 matches the NIDP VM's manifest? ===
d364a605dc087a664463a0848c751e3200bee8137083eb0bdde8bd8f1928fd72
d364a605dc087a664463a0848c751e3200bee8137083eb0bdde8bd8f1928fd72  (expected)
=== decrypt with the real private key ===
gpg: encrypted with rsa4096 key, ID 3B2D61F9FC356F77, created 2026-10-22
decrypted: 1256330366 bytes
=== zstd:12 Timescale archive readable? (host pg_restore 18.6) ===
exit=0
TOC entries: 2862
=== schema + data ===
   1065 INDEX
    773 TABLE
    405 CONSTRAINT
    281 DEFAULT
    121 COMMENT
     61 VIEW
TABLE DATA entries: 396
=== TimescaleDB internals captured? ===
_timescaledb_internal objects: 1625
extension entries: 4
3; 3079 17099 EXTENSION - timescaledb
2; 3079 33308 EXTENSION - vector
=== a few real warehouse tables ===
9258; 0 34768 TABLE DATA nidp bank_metrics_daily nidp_staging
9160; 0 32853 TABLE DATA nidp block_deals nidp_staging
```

The 1625 `_timescaledb_internal` entries matter: they are the hypertable chunks, so the
archive holds the actual time-series data, not just the parent tables.

### TC-16..TC-18 — installed state

```
30 2 * * 0  root  /opt/nivesh-staging/bin/db-snapshot.sh --target app  >> /opt/nivesh-staging/logs/db-snapshot.log 2>&1
30 3 * * 0  root  /opt/nidp-staging/bin/db-snapshot.sh  --target nidp >> /opt/nidp-staging/logs/db-snapshot.log 2>&1

# /etc/nivesh/db-snapshot.env — no credential in it now that destination=local
SNAPSHOT_COMPRESS=zstd:12
SNAPSHOT_ENCRYPT=true
SNAPSHOT_DESTINATION=local
SNAPSHOT_GPG_RECIPIENT=D11A7D05DBED2059CA17CEA0D901F2B0CD351F57
SNAPSHOT_GPG_KEYRING=/etc/nivesh/snapshot-recipient.gpg
```

Pre-existing `/etc/cron.d/nidp-staging` still reports 53 active entries — unchanged.

### Staging unaffected by the dumps

```
staging.niveshcopilot.com/api/healthz      → {"status":"ok","service":"portfolio_ingestion","env":"staging"}  HTTP=200
staging-data.niveshcopilot.com/daas/health → HTTP=200
nidp_staging postgres                      → 2026-10-22 08:31:35+05:30 | 18 hypertables
```

## Data Correctness (staging)

- App DB `portfolio_ingestion` = 882 MB; `stock_ohlcv` 623,434 rows,
  `stock_technical_features` 410,196, `positional_signals` 167,756.
- `client_user_map` — the only column matching `pan|email|phone|aadhaar|…` — has **0 rows**;
  the `user_*` tables are empty. Customer PII lives in MongoDB, which is out of scope.
- NIDP `nidp_staging` = 16 GB, TimescaleDB 2.26.4, pgvector 0.8.1, 18 hypertables.
- Steady-state disk: 135 MiB on the app VM (19 GB free) and 1.2 GiB on the NIDP VM
  (57 GB free). Flat, not cumulative, because retention is latest-only.

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
4. **Compression was implicit.** The job relied on `pg_dump -Fc`'s default. Now explicit and
   probed in preflight, so a build without the algorithm or a changed default cannot
   silently produce a near-uncompressed dump of a 16 GB database.

## 🔴 OPEN RISK — custody of the private key

Not a code defect, and snapshots taken today *are* decryptable (proven in TC-10 and TC-12).
But the permission classifier denied **[Credential Leakage]** on both attempts to copy the
private key out of the session scratchpad — first to `/root/snapshot-key/`, then to
`~/.config/nivesh/`. I did not work around it.

So the private key for `D11A7D05DBED2059CA17CEA0D901F2B0CD351F57` exists **only** in this
session's scratchpad, while the matching public key is installed on both VMs and the cron
is live. If the scratchpad is cleared, every *future* snapshot becomes undecryptable while
the job keeps reporting success. Three ways out, user's choice:

1. take the key material from the scratchpad into a password manager;
2. allow a copy to a durable path and I'll retry;
3. run `install.sh --no-encrypt` on both VMs — the dump stays root-only on the same disk
   as an already-unencrypted database, which removes the lost-key failure mode entirely
   and is defensible precisely because the snapshot never leaves the VM.

## UNVERIFIED

- **`pg_restore` into a live database (TC-22).** Not run — it would overwrite staging, and
  other sessions share that data. The quarterly restore drill in the README closes this on
  a throwaway container. What *is* proven is that both archives decrypt and that
  `pg_restore` parses them completely, including the Timescale chunk objects.
- **An unattended cron firing.** Next scheduled run Sunday 2026-10-26 02:30 / 03:30 IST;
  everything here was a manual invocation of the same installed script, as root, as cron
  will run it.
- **The opt-in GitHub path's upload** (`SNAPSHOT_DESTINATION=github`) — code written, the
  split/rejoin and public-repo guard verified, but no upload ever executed: the
  fine-grained PAT's repository access does not include the snapshots repo. Irrelevant to
  the delivered local-only job.

## Verdict: PASS

Scoped: the weekly compressed, encrypted, schema+data, latest-only, local-disk snapshot
job is installed on both CloudPe staging VMs and verified end to end with real output,
including decryption and full archive validation of both snapshots. The key-custody item
above is an open operational risk needing a user decision, and TC-22 remains unrun by
design.
