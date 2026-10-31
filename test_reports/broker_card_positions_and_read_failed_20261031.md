# Functionality Verification Report — Broker connections: say what was fetched, and say why a read failed

- **Branch:** feat/broker-card-positions (from origin/dev 25c61610)
- **Date:** 2026-10-31
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** probes ran read-only in-process inside `nivesh-staging-app-backend` against the owner's live ICICI Direct
  session; unit tests and Playwright in containers (`--network none`), production build, mocked `/api`. Not deployed.
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary
The owner (31 Oct, ~11:35 IST) pressed **Sync now** on the ICICI Direct card and got "The request didn't reach the server", and asked
whether the connection expires. Findings, in order:

1. **The connection did not expire.** With the same session token, three rounds of the three reads a sync uses gave
   `portfolioholdings: ok rows=6`, `portfoliopositions: ok rows=5` every time, and `dematholdings: IciciDirectError … (HTTP 200,
   API status 500)` every time. ICICI's own demat-holdings call is failing; a sync needs it. (At 07:15 IST the same call failed
   twice and then worked, so it is intermittent on ICICI's side.)
2. **The screen blamed the wrong thing.** The server answered both clicks (06:04:53Z and 06:04:58Z) with `502` after ~0.65 s and the
   envelope code `BROKER_READ_FAILED`, which the screen turns into "ICICI Direct did not return your holdings". The screen showed the
   no-connection sentence instead, which it uses only when the browser's `fetch` itself fails. The edge is Cloudflare
   (`server: cloudflare`, `cf-ray`), the page (`:8443`) calls the API cross-origin (preflight `OPTIONS` before each call), and an origin
   `502` is replaced by Cloudflare with its own page that has no CORS headers, so the browser drops it. **Inferred, not reproduced:**
   I could not make the app emit a 502 from outside; the 401 control below shows the edge passes other errors with the CORS header.
3. **Open positions were not visible on this card.** It said holdings only. (The positions themselves are fine: see
   `r2_open_positions_real_icici_20261031.md`.)

Changes: a failed broker read is answered **424** (not 502); the connection card gets one line for open positions (count, F&O count,
how old, a link to the Open positions screen), read through the desk's shared cached live read.

## Test Cases
> Authored up front.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| BC-1 | probe | session still valid? three ICICI reads, three rounds | api (live, read-only) | all three work if the session is fine | portfolioholdings and positions PASS; **dematholdings fails every round (ICICI API status 500)** |
| BC-2 | edge | error reply through the public edge, with the page's Origin | api | an error passes with the CORS header | PASS for 401 (`server: cloudflare`, `access-control-allow-origin` present) |
| BC-3 | backend | sync of an account whose read fails | unit | HTTP 424, code `BROKER_READ_FAILED`, fixed message, no broker text or secret in body, log or audit | PASS |
| BC-4 | backend | positions, holdings and contract-chart read failures | unit | the same 424 and code; session-ended stays 409; unsupported stays 400 | PASS |
| BC-5 | backend | a failed broker read is never a 5xx | unit (new) | status 424 | PASS |
| BC-6 | e2e | native, signed-in account with 5 positions (2 F&O) | e2e | "5 open positions (2 F&O), read …" and a link to the Open positions screen | PASS |
| BC-7 | e2e | account with none; a failed read; retry | e2e | "No open positions at this broker right now."; failed → "couldn't be read", never "none"; Retry reads again; one shared request | PASS |
| BC-8 | e2e | expired session; hosted (non-native) accounts | e2e | no positions line, no positions request | PASS |
| BC-9 | e2e | each sync error code (424 mocks) | e2e | the broker's sentence shows | PASS |
| BC-10 | e2e | the "what Nivesh reads" table | e2e | the positions row says read live, not stored; no "Not shown" | PASS |

## API / Endpoint Tests (staging)
- **BC-1** (read-only, owner's live session, output is the outcome of each call only):
```
round 1 dematholdings      0.60s IciciDirectError: ICICI Direct demat holdings failed (HTTP 200, API status 500) | http=200
round 1 portfolioholdings  0.18s ok rows=6
round 1 portfoliopositions 0.21s ok rows=5
round 2 dematholdings      0.72s IciciDirectError: … (HTTP 200, API status 500)
round 2 portfolioholdings  0.09s ok rows=6      round 2 portfoliopositions 0.14s ok rows=5
round 3 dematholdings      0.53s IciciDirectError: … (HTTP 200, API status 500)
round 3 portfolioholdings  0.10s ok rows=6      round 3 portfoliopositions 0.14s ok rows=5
```
- **Logs** (backend, 06:04–06:05Z): `POST /api/broker/accounts/ba_<id>/sync 502 (689ms)` then `502 (626ms)`; `broker sync failed … error=IciciDirectError`;
  the edge logged the same two `POST … 502 348` with a preflight `OPTIONS … 200` before each.
- **BC-2:** `curl -sk -i -X POST https://staging.niveshcopilot.com/api/broker/accounts/ba_x/sync -H "Origin: https://staging.niveshcopilot.com:8443"` →
  `HTTP/2 401`, `server: cloudflare`, `access-control-allow-origin: https://staging.niveshcopilot.com:8443`.
- **pytest, broker route suites:** `440 passed` (`test_broker_connect_native_routes`, `_contract_chart`, `_live_holdings`, `_native_routes`, `_hub_reads`, `_funds_read`).
- **Full CI allowlist** (288 files): `20 failed, 7613 passed, 34 skipped`; the 20 failed test names are all among the 20 recorded for a clean
  `origin/dev` (diffed by name: none new).

## UI / Playwright Tests
- `tsc --noEmit` → `TSC_EXIT=0`; `vite build` → `BUILD_EXIT=0`.
- `copilot-app-account`, `-contract-chart`, `-broker-paper`, `-positions`, `-screens` specs → `134 passed`, 4 skipped (screenshot cases).
- `copilot-app`, `-daily-trader`, `-suggestions`, `-visual-answer`, `-desk`, `-desk-copilot-window`, `-trade-idea`, `-desk-decision-cards` → `146 passed`, 2 skipped.

## Data Correctness (staging)
The 5 net positions (3 equity, 2 F&O) ICICI returns are the ones the new line counts; the card's "5 open positions (2 F&O)" is the
route's own count (`counts: total 5, fno 2`, verified in `r2_open_positions_real_icici_20261031.md`). The screen text for a failed
read is fixed text in `hub_reads.describe_failure`; the broker's own error is not sent to the browser.

## Not verified
- That Cloudflare is what swallows the 502 (inferred from the stack and its documented default; the 401 control passes). The 424 change
  does not depend on it: a 4xx passes either way. After deploy, press Sync now while ICICI's demat call still fails; the card should say
  "ICICI Direct did not return your holdings. Try again in a little while."
- A signed-in walk of the deployed card.
- ICICI's `/dematholdings` itself. Nivesh cannot fix it. A fallback that syncs from `/portfolioholdings` alone is possible but those rows
  carry no ISIN, which the "broker wins" reconcile keys on: left for an owner decision.

## Inputs required from user
- A staging session token for the signed-in walk; the owner's call on the demat fallback.

## Verdict: PASS
Scope: the code on this branch by unit tests, a read-only live probe and mocked-API Playwright; not a deployed system.
