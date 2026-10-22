# Functionality Verification Report — Broker hub: Motilal Oswal and ICICI Direct sign-in

- **Branch:** `feat/broker-hub-motilal-icici` (stacked on `fix/broker-hub-storage-failure`, PR #209)
- **Date:** 2026-10-14
- **Author:** Claude (Full-stack developer + QA), with two sub-agents
- **Environment:** unit tests in the staging backend image; a real-browser check of the cookie behaviour on local stand-in sites. **Staging: NOT RUN for these two brokers; no live broker account used**
- **Changed areas:** backend routes/services: yes · frontend src: no (the hub lists brokers from the server, so both appear without a frontend change)

## Summary
IN PROGRESS. The product owner asked for Motilal Oswal and ICICI Direct connections. Both now have
a redirect sign-in in code: the user signs in on the broker's own page and Nivesh stores only the
session the broker returns. Neither has been run against a live account, and for both brokers the
official pages leave open whether one app key can sign in other customers.

- **Motilal Oswal** (new adapter): MOFSL's "Login through Portal" returns an `authtoken` by GET.
- **ICICI Direct** (sign-in switched on): Breeze's login page returns the session key by a
  cross-site form POST and echoes no `state`. A new `POST /api/broker/native/callback/{slug}` only
  redirects (303) to the GET callback, where the signed-in user's pending attempt is matched.

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| M1 | Motilal | `auth_url` | unit | MOFSL login URL with only `apikey` | PASS (unit) |
| M2 | Motilal | sign-in exchange: success, failure, rejected token | unit | access token + client code stored in `extras`; failures raise without leaking the body | PASS (unit) |
| M3 | Motilal | required headers on every read | unit | the documented header set | PASS (unit) |
| M4 | Motilal | holdings and positions mapping (net and day; option, future, intraday cash) | unit | mapped to the hub's shapes; unknown fields left empty | PASS (unit, documented sample payloads) |
| M5 | Motilal | session ended vs operator-side failure | unit | only session codes end the session | PASS (unit) |
| M6 | Motilal | nothing order-related exposed | unit | no such name in the module | PASS (unit) |
| I1 | ICICI | `start` | unit | 307 to Breeze's login URL; state row stored; path-style redirect URL | PASS (unit) |
| I2 | ICICI | POST with `API_Session` in the body | api | 303 to the GET with `apisession` in the query; value never logged | PASS (unit) |
| I3 | ICICI | POST when the query already has the value; oversized or non-form body | edge | query kept; body ignored | PASS (unit) |
| I4 | ICICI | GET with a signed-in user and no `state` | api | completes through the pending-attempt fallback | PASS (unit) |
| I5 | ICICI | GET with nobody signed in; unknown broker; broker with no form field | edge | to login; `unknown_broker`; 405 | PASS (unit) |
| I6 | ICICI | cross-site POST through the real CSRF middleware, cookie `SameSite=Lax` | api | passes (no cookie on the POST) | PASS (unit) |
| I7 | ICICI | same with cookie `SameSite=None` | failure | 403 `CSRF_BLOCKED` — a known limit, see below | PASS (pins the limit) |
| B1 | Browser | cross-site form POST then 303 to GET, cookie `SameSite=Lax; Secure` | e2e (local stand-in sites) | no cookie on the POST; cookie on the redirected GET | PASS: Chromium 148, Firefox 130, WebKit 18 |
| B2 | Browser | full start → POST → GET round trip with the real router, CSRF middleware and adapter, ICICI replaced by stand-ins | e2e (local) | browser ends on the return page with `broker_connected=icicidirect`; one active account | PASS |
| R1 | Regression | all broker-hub test files | unit | 0 failed | PASS: 888 passed, 1 skipped |
| L1 | Live | Motilal Oswal connect, sync, positions on staging | e2e | account connected; rows match the broker's app | **NOT RUN** |
| L2 | Live | ICICI Direct connect, sync, positions on staging | e2e | same | **NOT RUN** |
| L3 | Live | a second customer signing in through the same app key (each broker) | e2e | allowed or refused by the broker | **NOT RUN** |

## API / Endpoint Tests (staging)
NOT RUN for this branch (not deployed). Checked on staging today, before this code:
`POST /api/broker/native/callback/icicidirect` → `HTTP 405` on both `staging.niveshcopilot.com` and
`:8443`, i.e. the request reaches the app through Cloudflare and nginx and the deployed build has no
POST route yet. Staging backend settings read from the running container: `COOKIE_SAMESITE=lax`,
`COOKIE_SECURE=true`. Staging's public egress IP, from the VM and from inside the backend
container: `45.64.105.88`.

- **pytest (this branch, staging image):** 17 broker-hub test files,
  `python -m pytest $T -q -p no:cacheprovider` → `888 passed, 1 skipped, 1 warning in 13.64s`
- **App import (this branch, staging image):** `import server` exits 0; routes include
  `POST /api/broker/native/callback/{broker_slug}`; `icicidirect` and `motilal` list as
  `implemented=True`, `connectable=False` until their keys are set.
- **Browser check (sub-agent's real output):**
  `=== A. https, SameSite=Lax; Secure  (staging: COOKIE_SAMESITE=lax)` →
  `RESULT  cookie on the cross-site POST: NO   |   cookie on the redirected GET: YES`

## UI / Playwright Tests
No frontend source changed.

## Data Correctness (staging)
NOT RUN.

## Known limits and open points
- **One app, many customers:** unconfirmed for both brokers. ICICI's FAQ says Breeze keys are
  created per customer and prohibits third-party integration. MOFSL describes the portal login as
  the vendor flow but also says a key must be created by the client. Only a live test with a second
  account, or the broker in writing, settles it.
- **Cookie setting:** ICICI's return works with the session cookie as `SameSite=Lax` (staging).
  With `SameSite=None` (the code default) the CSRF middleware rejects ICICI's POST. A narrow CSRF
  exemption for that one path was NOT added: the edit was refused by the permission system for the
  sub-agent, and it is the product owner's call.
- **No `state`** from either broker: the returning user is matched by session cookie plus a sign-in
  attempt started in the last 10 minutes.
- **Static IP:** both brokers require the server's public IP on the app.
- **Motilal Oswal holdings carry no price**; ICICI holdings carry ICICI's own stock codes, with the
  ISIN as the key.
- **Device-style headers** Motilal requires are filled with server values; which values MOFSL
  accepts from a server is not documented.

## Inputs required from user
- Merge of the PR into `dev`.
- App key and secret for each broker (and the Motilal client code), placed in a file on the VM.
- A login at each broker; ideally a second account to test the one-app question.
- A decision on the cookie setting / CSRF exemption for any deployment that is not `SameSite=Lax`.

## Verdict: BLOCKED
