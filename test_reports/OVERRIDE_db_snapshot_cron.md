# OVERRIDE — weekly encrypted DB snapshot cron (2026-10-22)

REASON: Blocked on two things only the user can release, so no `## Verdict: PASS` is
honest. (1) The fine-grained PAT in `.claude/.gh-token` is scoped to five repositories and
does not include the new private `amitporwal107/nivesh-db-snapshots`, so it gets HTTP 404
on that repo while returning 200 on `nivesh.ai` — the release upload and the Actions
secret write both fail there, and a fine-grained PAT's repository-access list cannot be
changed through the API. (2) The permission classifier denied **[Credential Leakage]** on
both attempts to copy the generated private key out of the session scratchpad to a durable
path, so the key that decrypts every future snapshot currently exists only in scratchpad.

Changed areas are new files under `deploy/cloudpe/backup/` — no backend route/service and
no frontend `src` was touched.

Everything not gated by those two blockers WAS verified against the real databases on both
VMs, with real output in `test_reports/db_snapshot_cron_20261022.md`: dump, archive
validation with the container's own `pg_restore`, encryption, recipient check, the decrypt
round trip, the split/rejoin path, the public-repo refusal, the generated key, sealed-box
encoding for the secrets API, and the installed cron on both VMs. Two real bugs were found
and fixed in the process (a `pipefail` silent abort after a successful dump, and a
`grep && fail` that aborted the installer on its normal path).

Unblock, then this closes out:

```
# 1. add nivesh-db-snapshots to the token (Contents + Secrets: Read and write)
sudo /opt/nivesh-staging/bin/db-snapshot.sh --target app --preflight
sudo /opt/nivesh-staging/bin/db-snapshot.sh --target app
# 2. decide where the private key should live, then
deploy/cloudpe/backup/set-github-secrets.sh --repo amitporwal107/nivesh-db-snapshots ...
```
