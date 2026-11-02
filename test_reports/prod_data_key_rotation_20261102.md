# Functionality Verification Report — Prod gets its own data-encryption keys

- **Branch:** ops/prod-data-key-rotation (PR #452 → dev)
- **Date:** 2026-11-02
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** production VM (owner-approved run) + sandbox rehearsal; staging checked read-only
- **Changed areas:** backend routes/services: no (new script `backend/scripts/rotate_data_keys.py` only) · frontend src: no · ops: `deploy/cloudpe-prod/rotate-data-keys.sh`

## Summary
Prod had been built with copies of staging's `PII_ENCRYPTION_KEY` and `PI_PAN_ENCRYPTION_KEY` (fingerprints matched on
2 Nov). The owner asked for separate keys. The runbook generated two new keys, saved them root-only before any data
change, backed up the affected collections/table, re-encrypted every value under the old key, swapped the keys in
`.env.prod` and recreated the backend. Run on prod 22:22:55–22:23:31 IST; backend down ≈35 s.

## Test Cases (authored up front: prod_data_key_rotation_TESTCASES.md)

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| RK-1 | crypto | OLD→NEW round trip, compatible with services.pii_security | unit | exact; NEW opens, OLD does not | PASS |
| RK-2 | classify | raw: old / already_new / undecryptable / skipped | unit | as listed | PASS |
| RK-3 | classify | sealed `enc:v1:` + legacy plaintext | unit | as listed | PASS |
| RK-4 | keys | missing / bad base64 / wrong length / same / no Mongo → exit 2, key never printed | unit | as listed | PASS |
| RK-5 | Mongo | dry run | sandbox | counts, nothing written | PASS |
| RK-6 | Mongo | --apply | sandbox | app opens all rotated values with NEW; others untouched | PASS |
| RK-7 | Mongo | --verify after apply; second apply | sandbox | 0 left under OLD; refused | PASS |
| RK-8 | Mongo | compare-and-set vs a concurrent write | unit | newer value kept | PASS |
| RK-9 | app read | pii_security with NEW opens every rotated value | sandbox + prod | all open | PASS |
| RK-10 | Postgres | PAN column re-encrypted in one transaction | sandbox | NEW opens, OLD does not | PASS |
| RK-11 | Postgres | unopenable row → rollback before any downtime | sandbox | nothing changed, backend untouched | PASS |
| RK-12 | runbook | pending keys reused after interruption; second --apply refused; no key in output | sandbox | as listed | PASS |
| RK-13 | prod | dry run, apply, post-checks | prod | new keys ≠ staging; healthy; 0 unreadable | PASS |

## Unit tests
- Command: `docker run … nivesh/backend:staging python -m pytest tests/test_rotate_data_keys.py -v`
- Output: `10 passed, 1 warning in 0.66s`

## Sandbox rehearsal (real mongo:7 + postgres:16 + backend image running the real pii_security)
- Command: `sudo bash deploy/cloudpe-prod/rehearse-rotate-data-keys.sh`
- Output: `REHEARSAL: 35 passed, 0 failed` (first run 33/2: a name-mangling bug in the harness loop, fixed; rerun 35/0)

## Prod (owner approved: "I approve the prod access")
- Dry run (read-only): 6 values to re-encrypt — gmail_tokens.access_token 3, gmail_tokens.refresh_token 2
  (+1 legacy plaintext, left as is), kite_platform_token.token_enc 1; Postgres PAN table present, 0 rows.
- Apply: `{"gmail_tokens.access_token": {"rotated": 3}, "gmail_tokens.refresh_token": {"plaintext": 1, "rotated": 2},
  "kite_platform_token.token_enc": {"rotated": 1}}`; verify: all `already_new`; running backend fingerprints = the new
  keys; app-level read `app_cannot_open: 0` for every field (3 + 2 + 1 opened); `runbook exit=0`.
- Independent post-checks: `nivesh-backend` running/healthy; 0 "decrypt failed"/Traceback log lines since restart;
  public `/v5/` 200; `/api/auth/me`, `/api/markets/home`, `/api/copilot/suggested-prompts` 401 when signed out, and the
  backend's access log shows those exact requests (so the public API reaches the restarted backend); key file and
  `.env.prod` mode 600; backups present (env, 5 Mongo archives, PAN table dump).
- Separation: prod key fingerprints now differ from staging's for BOTH keys; staging's are unchanged (re-checked after).
  Fingerprint values are in the session transcript, deliberately not in git.

## Data Correctness
- The app's own `services.pii_security` (new key) decrypts every rotated value on prod: 3 Gmail access tokens,
  2 Gmail refresh tokens, 1 Kite platform token; 0 failures.

## Inputs required from user
- Owner approval for the prod run (given). Owner to copy the new keys from `/root/nivesh-keys/` into the password manager.

## Verdict: PASS
