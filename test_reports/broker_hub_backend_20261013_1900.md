# Functionality Verification Report — Broker hub backend (connect, sessions, sync, positions) + broker-export upload

- **Branch:** `feat/broker-hub` (worktree `/home/deploy/nivesh-broker-hub`, off `origin/dev` @ aace88d9), uncommitted
- **Date:** 2026-10-13
- **Author:** Claude (Full-stack developer + QA), with seven sub-agents
- **Environment:** unit tests in the staging backend image (`nivesh/backend:staging`). **Staging itself: NOT RUN** — the code is not deployed there; see Verdict
- **Changed areas:** backend routes/services: yes · frontend src: no (the Copilot Settings / onboarding / broker screens are owned by another session)

## Summary
IN PROGRESS. Backend for a central broker hub: redirect sign-in on the broker's own page, several
brokers and several accounts per user, a session that lives until the broker expires it or the user
logs out of Nivesh, holdings sync (on connect, on demand, daily), live F&O / intraday positions,
onboarding-state support, "broker wins" reconciliation between CAS, broker and uploaded holdings,
and reading broker holdings exports (.xlsx / .xls / .csv). Everything below was verified with unit
tests using stubbed HTTP and an in-memory database. **Nothing has been run against a live broker,
the staging API or the staging database.**

Broker sign-in, from each broker's official documentation (2026-10-13):

| Broker | Result |
|---|---|
| Zerodha | Redirect sign-in (Kite Connect). Needs Nivesh's app keys. |
| Upstox | Redirect sign-in (OAuth). Needs Nivesh's app keys. |
| Angel One | Redirect sign-in (SmartAPI publisher login) built. UNVERIFIED whether Angel One lets one app sign in other clients; staff forum replies lean against it. |
| Groww | No redirect in the Trading API. Only compliant route is a daily access token the user generates on Groww (needs a Trading API plan). Adapter built, not connectable. |
| ICICI Direct | Breeze app keys are personal (one per client, tied to a static IP) and third-party integration is prohibited in ICICI's own FAQ. Reader built, sign-in switched off. |

## Acceptance criteria
| ID | Criterion | Unit-level result |
|----|-----------|-------------------|
| AC-1 | Start from any Copilot screen and land back on it with success or a fixed error code | met |
| AC-2 | Reconnect refreshes the same account; several brokers and accounts; remove any one | met |
| AC-3 | Only the session token is stored (encrypted); no password, PIN or TOTP; no order calls | met |
| AC-4 | Session lasts until broker expiry or logout from the last device; then listed as needing reconnect, token wiped | met |
| AC-5 | Holdings sync on connect, on demand, daily while live; replaces only that account's rows | met |
| AC-6 | Positions on demand per account and across accounts, net or day, F&O / intraday filter; not stored | met; `day` is available only where the broker really has a day book (Zerodha, AliceBlue), otherwise refused |
| AC-7 | Accounts list shows session state and expiry; broker list shows what is connectable | met |
| AC-8 | Onboarding state reports broker connections and stored holdings | met |
| AC-9 | Broker exports (.xlsx/.xls/.csv) import correctly; files that import today import identically | met on synthetic fixtures |
| AC-10 | No token, secret or full client id in logs, audit, redirects or error bodies | met in app code; UNVERIFIED for nginx access logs (Angel One returns its token in the callback URL) |
| AC-11 | Broker wins: CAS imports keep broker rows; the CAS copy of a broker-held ISIN is left out or removed; a new broker file replaces that broker's earlier file | met |
| AC-12 | The first five brokers are connectable | **not met**: Zerodha and Upstox by redirect (keys needed), Angel One built but unconfirmed, Groww and ICICI Direct not connectable (see table above) |

## Test Cases
> TC-1 to TC-41 were authored up front, before implementation. TC-42 onward were added when the
> user made further decisions mid-build (priority brokers, broker wins). "PASS (unit)" means a
> passing pytest case with stubbed HTTP / in-memory database, shown under "pytest" below.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | connect | `start/{slug}?return_to=/v5/app/page/brokers` for a configured redirect broker | api | 302 to the broker; state keeps the return path | PASS (unit) |
| TC-2 | connect | `return_to` open-redirect attempts | edge | ignored; falls back to `/dashboard` | PASS (unit) |
| TC-3 | connect | unknown broker slug | edge | 404 | PASS (unit) |
| TC-4 | connect | broker app keys not configured | failure | 503, audited, no state written | PASS (unit) |
| TC-5 | connect | callback success | api | 302 with `broker_connected` + `account_id`; token encrypted | PASS (unit) |
| TC-6 | connect | broker `error=` with no `status` (precedence bug) | edge | `broker_error=denied` | PASS (unit) |
| TC-7 | connect | missing params / expired state / unknown broker / exchange failure | failure | matching fixed code; broker text never echoed | PASS (unit) |
| TC-8 | accounts | reconnect the same broker login | unit | same `account_id`, token replaced | PASS (unit) |
| TC-9 | accounts | second login at the same broker; second broker | unit | separate rows | PASS (unit) |
| TC-10 | accounts | broker returns no client id | edge | one row per broker, refreshed on reconnect | PASS (unit) |
| TC-11 | session | expiry per broker | unit | correct UTC instant or null | PASS (unit) for Zerodha 06:00, Upstox 03:30, 5paisa 23:59, Angel One and ICICI midnight, Groww 06:00 (all read as IST: timezone UNVERIFIED); null for Fyers, AliceBlue, Dhan |
| TC-12 | session | session past its expiry | unit | flipped to `expired`, token wiped, row kept | PASS (unit) |
| TC-13 | session | logout on the only device | api | broker sessions ended, audited | PASS (unit) |
| TC-14 | session | logout while signed in elsewhere | edge | broker sessions untouched | PASS (unit) |
| TC-15 | session | clean-up fails during logout | failure | logout still succeeds; logged | PASS (unit) |
| TC-16 | sync | sync a native account | api | only that account's rows replaced | PASS (unit) |
| TC-17 | sync | sync an OpenAlgo account | api | unchanged behaviour | PASS (unit) |
| TC-18 | sync | broker rejects the token | failure | 409 `BROKER_SESSION_EXPIRED`; session ended | PASS (unit) |
| TC-19 | sync | broker read fails otherwise | failure | 502 `BROKER_READ_FAILED`; nothing secret in body or log | PASS (unit) |
| TC-20 | sync | first sync after connect fails or times out | failure | connect still succeeds | PASS (unit) |
| TC-21 | sync | another user's account id | edge | 404 | PASS (unit) |
| TC-22 | positions | net vs day for one account | api | rows carry `kind`; counts | PASS (unit) |
| TC-23 | positions | `segment=fno` / `intraday` | api | filtered rows; counts describe the full read | PASS (unit) |
| TC-24 | positions | option, future, cash intraday, cash delivery | unit | classified correctly | PASS (unit) |
| TC-25 | positions | only a net book exists, `day` requested | edge | 400 `BROKER_READ_NOT_SUPPORTED` | PASS (unit) |
| TC-26 | positions | all accounts, one failing, one needing reconnect | failure | others returned; the two listed with `ok:false` | PASS (unit) |
| TC-27 | reader | Fenix header construction per broker | unit | exactly the keys Fenix requires | PASS (unit, Fenix image) |
| TC-28 | reader | Fenix not installed / slug not mapped | failure | not supported; backend still imports | PASS (unit) |
| TC-29 | reader | Fenix auth failure | failure | mapped to session-expired | PASS (unit, Fenix image) |
| TC-30 | daily | live, expired and failing accounts | unit | honest counts; failures isolated | PASS (unit) |
| TC-31 | daily | `BROKER_DAILY_SYNC_ENABLED` off | edge | run skipped | PASS (unit) |
| TC-32 | listing | `GET /broker/accounts` | api | existing keys kept; new ones added | PASS (unit) |
| TC-33 | listing | `GET /broker/native/supported` | api | `configured`, `connectable`; no secrets | PASS (unit) |
| TC-34 | onboarding | `GET /onboarding/state` | api | three new counts, this user only | PASS (unit) |
| TC-35 | onboarding | session sweep fails | failure | state still returned | PASS (unit) |
| TC-36 | upload | each broker export layout × .csv/.xlsx/.xls | unit | correct rows | PASS (unit, synthetic fixtures) |
| TC-37 | upload | preamble rows, totals, Indian numbers, BOM / latin-1 | edge | parsed | PASS (unit) |
| TC-38 | upload | generic file that imports today | unit | identical rows | PASS (unit; 14 tests written against the old parser first) |
| TC-39 | upload | unrecognised layout / empty file / legacy `.xls` | failure | clear 400; `.xls` read | PASS (unit); a real OLE2 `.xls` file is UNVERIFIED |
| TC-40 | security | secrets in logs, audit, redirects, errors | unit | none | PASS (unit) |
| TC-41 | live | connect a real broker on staging, sync, read positions | e2e | matches the broker's own app | **NOT RUN** — needs deploy, app keys, a real login |
| TC-42 | reconcile | CAS import with broker rows present | unit | broker rows kept; broker-held ISINs left out | PASS (unit) |
| TC-43 | reconcile | broker sync / export with CAS copies present | unit | CAS copies removed; manual rows untouched | PASS (unit) |
| TC-44 | reconcile | second export from the same broker | unit | replaces the first | PASS (unit) |
| TC-45 | data | symbol-named export row through real masterdata | unit | quantity, cost, symbol unchanged; name completed | PASS (unit, real masterdata files) |
| TC-46 | flag | `broker_hub` off / unreadable | api | 403 / 503 on start, native sync, positions; list and delete unaffected | PASS (unit) |
| TC-47 | errors | read errors through the real error handlers | api | standard envelope with stable `code` | PASS (unit) |
| TC-48 | brokers | Angel One path-style callback | api | sign-in completes; token not in the redirect | PASS (unit) |
| TC-49 | brokers | Groww and ICICI Direct in the listing | api | listed, not connectable; start refused with 400 | PASS (unit) |

## API / Endpoint Tests (staging)
**NOT RUN.** The code is not on staging (staging deploys from `dev`; this is an uncommitted feature
branch). No staging curl output exists for any endpoint in this report.

- **pytest (staging image, Fenix not installed):**
  `sudo docker run --rm --network none -v /home/deploy/nivesh-broker-hub:/work:ro -w /work/backend -e PYTHONDONTWRITEBYTECODE=1 -e MONGO_URL=mongodb://localhost:27017 -e DB_NAME=unit_test -e OPENAI_API_KEY=unit-test-placeholder nivesh/backend:staging python -m pytest tests/test_broker_sessions.py tests/test_broker_native_routes.py tests/test_broker_hub_reads.py tests/test_broker_connect_native_routes.py tests/test_broker_fenix_reader.py tests/test_broker_angelone.py tests/test_broker_groww.py tests/test_broker_icicidirect.py tests/test_holdings_reconcile.py tests/test_masterdata_broker_rows.py tests/test_statement_exports.py tests/test_onboarding_state_sources.py tests/test_openalgo_client.py tests/test_charting_feature_flag.py tests/test_research_feature_flags.py tests/test_move_odds_routes.py -q -p no:cacheprovider`
  - Output: `738 passed, 51 skipped, 1 warning in 11.99s` (the 51 skips are Fenix-dependent cases)
- **pytest (same files, image `nivesh-test/backend-fenix:local` = staging image + `fenix==2.0.2`):**
  - Output: `788 passed, 1 skipped, 1 warning in 13.21s`
- **App import check (staging image):** `import server` succeeds and registers
  `GET /api/broker/accounts`, `DELETE /api/broker/accounts/{account_id}`,
  `GET /api/broker/accounts/{account_id}/positions`, `POST /api/broker/accounts/{account_id}/sync`,
  `GET /api/broker/native/callback`, `GET /api/broker/native/callback/{broker_slug}`,
  `GET /api/broker/native/start/{broker_slug}`, `GET /api/broker/native/supported`,
  `GET /api/broker/positions`, plus the existing OpenAlgo routes. With no app keys set, every broker
  reports `connectable=False`.
- **Dependency check for Fenix:** the PyPI wheel `fenix-2.0.2` matches the GitHub source file for
  file (25 of 25 identical); `pip install --dry-run` against the staging image adds 10 packages and
  changes none.

## UI / Playwright Tests
Not applicable to this branch: no frontend source is changed here.

## Data Correctness (staging)
**NOT RUN.** No staging table was queried. The only data-level evidence is TC-45, which runs the
real `save_holdings` and real masterdata files against an in-memory database.

## Known gaps (not fixed here)
- A snapshot-health backfill computes historical health with today's broker rows still in place.
- After a broker is disconnected, instruments whose CAS copy was superseded return only with the next CAS import.
- Overlap matching is by ISIN only; the same company at a second, unconnected broker is not counted.
- `services/live_price.py` treats `ticker` as an ISIN, so broker rows are not repriced between syncs; Groww holdings arrive with no price.
- Adapters outside the first five: AliceBlue and Fyers sign-in likely cannot complete as written; AliceBlue, 5paisa turn an error body into an empty list; `fyers.py` strips symbol characters with `rstrip("-EQ")`.
- Account upsert is find-then-write with no unique index; a holdings sync is delete-then-insert.
- Existing scheduler jobs declared without a timezone fire in UTC on staging (the new daily job names Asia/Kolkata).
- `docs/API_DOCUMENTATION.md` states an error shape that differs from what the handlers return.

## Inputs required from user
- Commit and push of `feat/broker-hub`, then merge into `dev` (that is what deploys staging).
- Nivesh's developer-app keys for at least one redirect broker on staging, with the staging callback URL registered at that broker (Angel One: `/api/broker/native/callback/angel`).
- A real login at that broker, and a staging `session_token` for the endpoint checks.
- Decisions: Groww (daily token paste, approach Groww, or upload only), ICICI Direct (upload only, or ask ICICI), Angel One (written confirmation of multi-client use), and whether to keep the GPL-3.0 Fenix dependency.

## Verdict: BLOCKED
