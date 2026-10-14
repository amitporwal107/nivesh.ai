# Functionality Verification Report — Broker hub on staging: first live Zerodha connect, and the token-storage fix

- **Branch:** `fix/broker-hub-storage-failure` (off `dev` @ 29c0eba0, which has PRs #206, #207, #208)
- **Date:** 2026-10-14 (events below are 2026-10-13 22:01–22:21 UTC)
- **Author:** Claude (Full-stack developer + QA)
- **Environment:** staging (staging.niveshcopilot.com, database `nivesh_staging`), live Zerodha (Kite Connect)
- **Changed areas:** backend routes/services: yes · frontend src: no

## Summary
IN PROGRESS. The user connected a real Zerodha account from Copilot Settings on staging. The first
attempt failed with a raw 500 after Zerodha signed them in: staging had no `PII_ENCRYPTION_KEY`, so
the session token could not be encrypted for storage. With the user's approval the key was created
on staging and the backend recreated; the next attempt connected, synced and read positions against
live Zerodha. This branch makes the hub refuse to start a sign-in when the token cannot be stored,
and turns a failed save into a return-to-screen code instead of a 500. That code change is
unit-tested but **not yet deployed**.

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| L1 | connect | sign in at Zerodha from Settings on staging, with the redirect URL registered as `/api/broker/native/callback/zerodha` | e2e (live) | lands back on Settings; account stored, token encrypted, status active | PASS (staging, live) |
| L2 | session | expiry recorded for the Zerodha session | data | next 06:00 IST | PASS (staging): `session_expires_at = 2026-10-14T00:30:00+00:00` |
| L3 | sync | Sync now on the connected account | api (live) | 200; count equals what Zerodha holds | PASS (staging): count 0; Zerodha's SDK also reports 0 |
| L4 | reads | hub reader vs Zerodha's own SDK for holdings, net and day positions | data (live) | same counts | PASS (staging): 0 / 0 / 0 on both; user confirmed the account is empty |
| L5 | remove | Remove the account | api | account and its holdings gone; audited | PASS (staging) |
| L6 | reconnect | sign in again after removing | e2e (live) | new active account | PASS (staging) |
| L7 | mapping | a NON-empty holdings / positions read from a live account | data (live) | rows match the broker's app | **NOT RUN** — the only connected account holds nothing |
| F1 | fix | token cannot be stored | unit | `supported` shows nothing configured or connectable; `start` is 503 with no key name; no state row | PASS (unit) — not deployed |
| F2 | fix | save fails after the broker signed the user in | unit | redirect to the return page with `broker_error=server_error`; audited; no 500; no token or key name in logs | PASS (unit) — not deployed |
| F3 | fix | `storage_ready()` | unit | true with a key, false when encryption raises | PASS (unit) — not deployed |

## API / Endpoint Tests (staging)
- **Failure seen by the user:** `GET /api/broker/native/callback/zerodha` →
  `{"timestamp":"2026-10-13T22:10:18Z","status":500,"error":"SYSTEM_ERROR","code":"SYS-001",...,"correlationId":"acc7f72320644953bc78260ed9bbde64","path":"/api/broker/native/callback/zerodha"}`
  - Server log for that correlation id ends:
    `File "/app/backend/services/brokers/sessions.py", line 310, in upsert_native_account` →
    `RuntimeError: PII_ENCRYPTION_KEY is not configured (or invalid) and APP_ENV='staging' is not a dev environment.`
- **After the key was set** (backend recreated, `healthy` after 6 s):
  - `GET /api/healthz` → `HTTP 200`
  - encrypt/decrypt round-trip inside the running backend: `decrypt returns the plaintext: True`
- **Access log, live session:**
  - `GET /api/broker/native/callback/zerodha 307 (987ms)`
  - `GET /api/broker/accounts 200 (18ms)` · `GET /api/broker/native/supported 200 (78ms)`
  - `POST /api/broker/accounts/ba_7510671532f3/sync 200 (61ms)`
  - `DELETE /api/broker/accounts/ba_7510671532f3 200 (18ms)`
- **pytest (this branch, staging image):** the 16 broker-hub test files,
  `python -m pytest $T -q -p no:cacheprovider` → `792 passed, 1 skipped, 1 warning in 13.43s`

## UI / Playwright Tests
No frontend source changed on this branch. The Settings hub was exercised by the user on staging
(sign-in started with `return_to=/v5/app/page/settings`, then Sync now and Remove); no Playwright
run was made against staging.

## Data Correctness (staging)
- `audit_log` (staging):
  - `2026-10-13T22:18:58 | broker_connect | success | {'broker': 'zerodha', 'native': True}`
  - `2026-10-13T22:19:15 | broker_sync | success | {'broker': 'zerodha', 'count': 0, 'native': True}`
  - `2026-10-13T22:20:06 | broker_disconnect | success | {'broker': 'zerodha'}`
- `broker_accounts` (staging, token fields not read): `status: active`, `native: True`,
  `broker_user_masked: ••••37`, `session_expires_at: 2026-10-14T00:30:00+00:00`,
  `last_sync_count: 0`, `last_error: None`.
- Live comparison on the re-connected account `ba_a268264b3058` (counts only):
  - Zerodha's SDK: `equity holdings rows: 0`, `positions (net, day): (0, 0)`, `mutual-fund holdings rows (Coin): 0`
  - hub reader (Fenix path, `supports: {'holdings': True, 'positions': True}`): `holdings rows: 0`,
    `net positions rows: 0`, `day positions rows: 0`
- Result: PASS for an empty account. The mapping of real rows is unproven (L7).

## Staging changes made (with the user's approval)
- Added `PII_ENCRYPTION_KEY` (base64 of 32 random bytes, generated on the VM, never printed) to
  `/opt/nivesh-staging/.env.staging`; backup at `/opt/nivesh-staging/.env.staging.bak-20261014-before-pii-key`.
- Recreated only the `app-backend` container with the same compose invocation `deploy.sh` uses.
- The user changed the Kite Connect app's Redirect URL to
  `https://staging.niveshcopilot.com/api/broker/native/callback/zerodha`. That app is also the one
  the research Move-odds job uses for its daily token; its manual login no longer lands on 127.0.0.1.

## Inputs required from user
- Merge of the fix PR into `dev`.
- A Zerodha (or other broker) account that holds something, to verify the row mapping (L7).
- A copy of the staging `PII_ENCRYPTION_KEY` line kept with the other staging secrets.
- Production: whether `PII_ENCRYPTION_KEY` is set there is UNVERIFIED.

## Verdict: BLOCKED
