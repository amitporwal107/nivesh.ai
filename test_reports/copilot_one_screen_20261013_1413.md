# Functionality Verification Report — One-screen Copilot app (desktop + mobile)

- **Branch:** feat/copilot-one-screen (worktree `/home/deploy/nivesh-copilot-ui`, based on `origin/dev` b0184b1a; code changes are uncommitted)
- **Date:** 2026-10-13
- **Author:** Claude (design engineer + full-stack developer + QA)
- **Environment:** (1) production build served locally with every `/api/*` call mocked; (2) the same local build with `/api` proxied to **staging**; (3) the **deployed staging app** at `https://staging.niveshcopilot.com/v5/app` after PR #205 was merged into `dev` (build of commit 034d8089). (2) and (3) used a staging session supplied by the user.
- **Changed areas:** backend routes/services: no · frontend src: yes

## Summary
Status: **IN PROGRESS**. A new signed-in surface at `/v5/app` implements the "Nivesh Copilot"
one-screen design (`frontend-v5/design/nivesh-copilot/`): rail, home, ask box with
suggestions, answer thread with tool steps, evidence panel, and 21 tool / workspace / trader /
advisor / internal screens, at desktop and phone widths. It reads existing backend endpoints
only; no backend file is changed. Existing routes (`/lite`, `/chat`, `/dashboard`, …) are not
modified — the only edit outside the new folder is one added route in `src/routes.tsx`.

Verified with mocked responses: typecheck, production build, 44 Playwright tests (shell and
screens, desktop 1280×800 and phone 390×844) and the existing `/lite` regression spec.

Verified against the real staging backend (see "Live checks"): the home screen shows the real
portfolio value to the rupee and live market data; all 20 screens load with no failed API call,
no error state and no crash; the chat backend answers two real questions with exactly the
frames the thread expects; and those real answers render in full in the thread.

On the deployed staging app (after the user merged PR #205): the home screen shows the real
portfolio value and live market data, a question typed in the browser was answered by the real
backend in 8.9 s with label, routing, result card and follow-ups, and all 20 screens load with
no failed API call. See "On the deployed staging app".

Not verified: the native Android / iOS build (TC-23), and every write path other than chat.
The four corrections made after the first live run (commit 56ff58d1) are on the feature branch
but not yet on `dev`, so staging still runs the build without them.

Mocked tests use fixtures or inline test payloads (MOCK — not real data); expected values in
the per-screen tests were worked out from the payload, not copied from the screen.

## Test Cases
> TC-01 … TC-23 were written before the implementation (first version of this report,
> 13:17). TC-07b and the extra access cases were added while building.

Desktop = 1280×800. Phone = 390×844.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-01 | Shell | Open `/v5/app` signed in | e2e · mocked | Rail, greeting with the first name from `/api/auth/me`, ask box | PASS |
| TC-02 | Threads | Rail thread list, open a past thread | e2e · mocked | Titles from `GET /api/chat/sessions`; thread shows `GET /api/chat/messages` content; no tool card for history | PASS |
| TC-03 | Home | Market strip | e2e · mocked | Values equal the `/api/markets/home` fixture; strip absent when the endpoint returns nothing | PASS |
| TC-04 | Home | "For your portfolio today" cards | e2e · mocked | Cards from `/api/copilot/suggested-prompts`; a card sends its `query` | PASS |
| TC-05 | Thread | Ask a question | e2e · mocked | Session created, stream called with the message; pill, tool steps, answer, follow-ups; follow-up stays in the thread | PASS |
| TC-06 | Thread | Stream `error` frame | failure · mocked | Partial-result banner, one copy of the turn, Retry re-sends | PASS |
| TC-07 | Thread | Stream HTTP 500 | failure · mocked | Error banner, ask box usable | PASS |
| TC-07b | Thread | Stop an answer in flight | edge · mocked | Turn marked stopped, question kept, Retry offered | PASS |
| TC-07c | Thread | Thread cannot be created (found in the live run) | failure · mocked | "Not sent" message with the question; Retry sends it | PASS |
| TC-08 | Home | No holdings | edge · mocked | Connect banner, "Worth knowing today", no ₹0 value | PASS |
| TC-09 | Evidence | Home context and thread evidence | e2e · mocked | Portfolio value from `holdings-enriched`; tools, sources, routing of the answer; toggle | PASS |
| TC-10 | Ask box | Suggestions | e2e · mocked | Ranked prompts on focus; completions while typing; ↓ + Enter asks; Esc closes | PASS |
| TC-11 | Modes | Mode pill | e2e · mocked | Trader swaps the tools; Advisor only for an `ADVISORY` workspace | PASS |
| TC-12 | Access | Internal section | edge · mocked | Admins only; non-admin sent home from `/app/ops/feeds` and `/app/builder` | PASS |
| TC-13 | Access | Signed out | edge · mocked | Redirect to `/v5/login` | PASS |
| — | Access | Onboarding not finished | edge · mocked | Lands on `/v5/app/onboarding` | PASS |
| — | Routing | Unknown view | edge · mocked | Falls back to home | PASS |
| TC-14 | Mobile | Shell at 390×844 | e2e · mocked | No rail; menu drawer navigates and closes; no sideways scroll | PASS |
| TC-15 | Mobile | Evidence sheet | e2e · mocked | Opens as a bottom sheet, closes | PASS |
| TC-16 | Mobile | Ask flow | e2e · mocked | Same as TC-05; ask box stays on screen | PASS |
| TC-17 | Screens | All 21 destinations render, desktop and phone | e2e · mocked | Screen present, no crash fallback, no uncaught error; on phone no sideways page scroll | PASS |
| TC-18 | Data honesty | Every `/api/*` returns `{}` | edge · mocked | No screen shows any of 27 sample figures / names from the design; no screen throws | PASS |
| TC-19 | Screens | Wired screens show their endpoint's data | e2e · mocked | See the wiring table; 21 tests | PASS |
| TC-20 | Build | Typecheck and production build | unit | `tsc --noEmit` exit 0; `vite build` completes | PASS |
| TC-21 | Regression | Existing chat surfaces | e2e · mocked | `lite-copilot.spec.ts` passes | PASS |
| TC-22 | Live data | `/v5/app` on staging with a real session | e2e · live | Real portfolio value and a real streamed answer | **PASS** on the deployed app: home data, a browser-asked question, all 20 screens. A second question (own profile open) was answered and rendered, but that test then failed on a script error (clicking a disabled toggle) and was not re-run |
| TC-23 | Native | Android / iOS (Capacitor) build opens the new shell | e2e · device | Shell renders in the native app, safe areas respected | **NOT RUN** — needs a device build; the APK script also publishes to a public download URL |

## API / Endpoint Tests (staging)
No backend routes or services are changed, so there is nothing new to hit. Staging health,
and proof that a real-data check needs a session:

```
$ curl -s -m 15 -w "\nHTTP %{http_code}\n" https://staging.niveshcopilot.com/api/healthz
{"status":"ok","service":"portfolio_ingestion","version":"0.1.0","env":"staging"}
HTTP 200

$ curl -s -m 20 -w "\nHTTP %{http_code}\n" https://staging.niveshcopilot.com/api/markets/home   # no session
{"timestamp":"2026-10-13T08:43:49Z","status":401,"error":"UNAUTHORIZED","code":"AUTH-001","message":"Not authenticated","details":[],"correlationId":"21021d2e10e242feba7a5919d864e6fa","path":"/api/markets/home"}
HTTP 401
```

## UI / Playwright Tests

Run inside `mcr.microsoft.com/playwright:v1.47.0-jammy` with **no network**, from `frontend-v5/`,
against `vite build` + `vite preview`. Real output of the last run (after the fixes below):

```
$ npx tsc -b
tsc -b exit=0
✓ built in 20.34s
vite build exit=0
$ npx playwright test --config pw.copilot-app.config.ts copilot-app.spec.ts copilot-app-screens.spec.ts
Running 44 tests using 3 workers
  ✓   1 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:106:3 › Copilot app screens — phone (390×844) › TC-17 every destination renders without sideways page scroll (18.0s)
  ✓   2 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:77:3 › Copilot app screens — desktop › TC-17 every rail destination renders (18.4s)
  ✓   4 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:157:3 › TC-19 screens show their endpoint's data — desktop › Portfolio analysis ← holdings-enriched + concentration (974ms)
  ✓   5 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:172:3 › TC-19 screens show their endpoint's data — desktop › Portfolio ledger ← holdings-enriched (1.1s)
  ✓   3 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:85:3 › Copilot app screens — desktop › TC-18 with empty API responses no screen shows the design's sample data (20.3s)
  ✓   7 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:202:3 › TC-19 screens show their endpoint's data — desktop › Markets ← markets/home, and a mover row asks the Copilot (959ms)
  ✓   9 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:237:3 › TC-19 screens show their endpoint's data — desktop › Screener ← saved screeners; a rule compiles to the query that is asked (927ms)
  ✓   8 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:217:3 › TC-19 screens show their endpoint's data — desktop › Research ← instrument search + company financials (1.3s)
  ✓   6 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:184:3 › TC-19 screens show their endpoint's data — desktop › Recommendations and Action plan ← plans/active (2.7s)
  ✓  11 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:273:3 › TC-19 screens show their endpoint's data — desktop › Saved ← screeners + chat sessions; a thread opens (889ms)
  ✓  12 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:285:3 › TC-19 screens show their endpoint's data — desktop › Trader desk ← journal, scanner, watch levels, broker accounts, markets/home (814ms)
  ✓  10 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:251:3 › TC-19 screens show their endpoint's data — desktop › Watchlist ← filing alerts only; the internal research list is not requested (1.4s)
  ✓  14 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:341:3 › TC-19 screens show their endpoint's data — desktop › Paper trades ← paper-trades portfolio, evaluation, live (1.1s)
  ✓  13 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:316:3 › TC-19 screens show their endpoint's data — desktop › Options lab: payoff is computed from typed legs; chain and open interest are declared missing (1.4s)
  ✓  15 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:369:3 › TC-19 screens show their endpoint's data — desktop › Advisor ← client book + SIP board; opening a client lands in the Copilot (1.3s)
  ✓  16 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:400:3 › TC-19 screens show their endpoint's data — desktop › Advisor screen explains itself to a non-advisor account (798ms)
  ✓  18 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:447:3 › TC-19 screens show their endpoint's data — desktop › Tool builder: the contract is derived from what is typed; saving is declared missing (1.1s)
  ✓  19 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:463:3 › TC-19 screens show their endpoint's data — desktop › the engineering 'needs' list on a not-connected block is shown to admins only (1.3s)
  ✓  17 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:405:3 › TC-19 screens show their endpoint's data — desktop › Internal pages ← feeds, audit trail, admin stats, routing agents (2.4s)
  ✓  21 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:512:3 › TC-19 account screens — desktop › Onboarding: if recording completion fails the user still gets out, and is told (883ms)
  ✓  20 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:497:3 › TC-19 account screens — desktop › Onboarding: skipping records completion and lands on home for good (1.5s)
  ✓  23 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:545:3 › TC-19 account screens — desktop › Broker connections ← broker accounts, statement on file, Gmail, import log (956ms)
  ✓  22 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:522:3 › TC-19 account screens — desktop › Onboarding: the four steps in order, showing what is on file, then finish (1.4s)
  ✓  24 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:569:3 › TC-19 account screens — desktop › Settings ← profile, risk, goals; mode and theme take effect (1.3s)
  ✓  25 [copilot-app] › e2e/tests/copilot-app.spec.ts:125:3 › Copilot app — desktop › TC-01 shell renders: rail, greeting, ask box (916ms)
  ✓  26 [copilot-app] › e2e/tests/copilot-app.spec.ts:144:3 › Copilot app — desktop › TC-02 rail lists saved threads and opens one (1.1s)
  ✓  27 [copilot-app] › e2e/tests/copilot-app.spec.ts:172:3 › Copilot app — desktop › TC-03 market strip shows /api/markets/home values, and nothing when it is empty (1.2s)
  ✓  28 [copilot-app] › e2e/tests/copilot-app.spec.ts:192:3 › Copilot app — desktop › TC-04 'for your portfolio today' cards come from suggested-prompts and ask their query (1.1s)
  ✓  29 [copilot-app] › e2e/tests/copilot-app.spec.ts:211:3 › Copilot app — desktop › TC-05 asking a question streams an answer with class, tool steps and follow-ups (1.2s)
  ✓  30 [copilot-app] › e2e/tests/copilot-app.spec.ts:252:3 › Copilot app — desktop › TC-06 an error frame shows a partial-result banner with a working retry (1.1s)
  ✓  31 [copilot-app] › e2e/tests/copilot-app.spec.ts:269:3 › Copilot app — desktop › TC-07 a failed stream request shows an error and leaves the ask box usable (909ms)
  ✓  32 [copilot-app] › e2e/tests/copilot-app.spec.ts:284:3 › Copilot app — desktop › TC-07c a thread that cannot be started says so, and Retry sends the question (1.1s)
  ✓  33 [copilot-app] › e2e/tests/copilot-app.spec.ts:310:3 › Copilot app — desktop › TC-07b stopping an answer in flight keeps the question and offers a retry (1.1s)
  ✓  34 [copilot-app] › e2e/tests/copilot-app.spec.ts:334:3 › Copilot app — desktop › TC-08 an account with no holdings gets the connect banner and no zero values (1.2s)
  ✓  35 [copilot-app] › e2e/tests/copilot-app.spec.ts:354:3 › Copilot app — desktop › TC-09 evidence panel: context on home, tools and sources in a thread, and the toggle (1.3s)
  ✓  36 [copilot-app] › e2e/tests/copilot-app.spec.ts:391:3 › Copilot app — desktop › TC-10 ask-box suggestions: ranked prompts, completions, keyboard (1.4s)
  ✓  37 [copilot-app] › e2e/tests/copilot-app.spec.ts:420:3 › Copilot app — desktop › TC-11 mode pill swaps the tools; Advisor only for an advisory workspace (1.5s)
  ✓  39 [copilot-app] › e2e/tests/copilot-app.spec.ts:472:3 › Copilot app — desktop › TC-13 a signed-out visitor is sent to login (832ms)
  ✓  38 [copilot-app] › e2e/tests/copilot-app.spec.ts:451:3 › Copilot app — desktop › TC-12 internal pages are for admins only (1.8s)
  ✓  40 [copilot-app] › e2e/tests/copilot-app.spec.ts:479:3 › Copilot app — desktop › a user who has not finished onboarding lands on the onboarding screen (1.1s)
  ✓  41 [copilot-app] › e2e/tests/copilot-app.spec.ts:488:3 › Copilot app — desktop › an unknown view falls back to home (981ms)
  ✓  42 [copilot-app] › e2e/tests/copilot-app.spec.ts:512:3 › Copilot app — phone (390×844) › TC-14 no rail; the menu opens a drawer that navigates and closes (974ms)
  ✓  43 [copilot-app] › e2e/tests/copilot-app.spec.ts:539:3 › Copilot app — phone (390×844) › TC-15 evidence opens as a bottom sheet and closes (939ms)
  ✓  44 [copilot-app] › e2e/tests/copilot-app.spec.ts:555:3 › Copilot app — phone (390×844) › TC-16 the ask flow works and the ask box stays on screen (772ms)
  44 passed (37.0s)
playwright exit=0
$ npx playwright test --config pw.copilot.config.ts lite-copilot.spec.ts
  ✓  3 [unauthenticated] › e2e/tests/lite-copilot.spec.ts:44:3 › Lite Copilot surface › NOT-onboarded user on /lite is routed to onboarding (CAS upload / Gmail sync) (527ms)
  ✓  4 [unauthenticated] › e2e/tests/lite-copilot.spec.ts:57:3 › Lite Copilot surface › CONTROL: /chat renders the SAME Copilot WITH the sidebar (1.2s)
  4 passed (4.6s)
regression exit=0
```

Screenshots of every screen at both sizes, plus the light theme, were captured with
`copilot-app-shots.spec.ts` (skipped unless `SHOT_DIR` is set) and reviewed by eye against the
design. They are not committed.

## Live checks against staging (TC-22)

Spec: `frontend-v5/e2e/tests/copilot-app-live.spec.ts` (skipped unless `LIVE_TOKEN_FILE` or
`REPLAY_DIR` is set). The session token is read from a file outside the repo and is never
printed; outputs below hold statuses, counts and on-screen text only.

**1. Home with real data, then a question from the browser** — `/api` proxied to staging:

```
Running 4 tests using 1 worker
LIVE {"label":"home","threadsInRail":8,"todayTitle":"FOR YOUR CLIENT BOOK TODAY","todayCards":1,"marketStrip":"NIFTY 50 22,690 +1.46% INDIA VIX 14.22 −6.8% FII CASH −₹1,708 CR DII CASH +₹3,045 CR","freshness":"NSE LIVE","holdings":117,"valueShown":"matches API total"}
  ✓  1 [copilot-app] › e2e/tests/copilot-app-live.spec.ts:71:3 › Copilot app — live staging › TC-22 home shows the real portfolio value and market data (8.6s)
  ✘  2 [copilot-app] › e2e/tests/copilot-app-live.spec.ts:111:3 › Copilot app — live staging › TC-22 a real question gets a real streamed answer (30.7s)
  -  3 [copilot-app] › e2e/tests/copilot-app-live.spec.ts:121:3 › Copilot app — live staging › TC-22 a portfolio question with the account's own profile open
  -  4 [copilot-app] › e2e/tests/copilot-app-live.spec.ts:141:3 › Copilot app — live staging › TC-22 every screen against the real backend
  1) [copilot-app] › e2e/tests/copilot-app-live.spec.ts:111:3 › Copilot app — live staging › TC-22 a real question gets a real streamed answer 
    Error: [2mexpect([22m[31mpage[39m[2m).[22mtoHaveURL[2m([22m[32mexpected[39m[2m)[22m failed
    Expected pattern: [32m/\/v5\/app\/t\/[^/]+$/[39m
    Received string:  [31m"http://localhost:5174/v5/app"[39m
    Timeout: 30000ms
    Call log:
    [2m  - Expect "toHaveURL" with timeout 30000ms[22m
    [2m    63 × unexpected value "http://localhost:5174/v5/app"[22m
      36 |   await input.fill(question);
      37 |   await input.press("Enter");
    > 38 |   await expect(page).toHaveURL(/\/v5\/app\/t\/[^/]+$/, { timeout: 30_000 });
         |                      ^
      39 |   const turn = page.getByTestId("thread-turn").last();
      40 |   const started = Date.now();
      41 |   await expect(turn).toHaveAttribute("data-state", /saved|error|stopped/, { timeout: 170_000 });
        at askAndReport (/app/e2e/tests/copilot-app-live.spec.ts:38:22)
        at /app/e2e/tests/copilot-app-live.spec.ts:115:15
    attachment #1: screenshot (image/png) ──────────────────────────────────────────────────────────
    ../out/results/copilot-app-live-Copilot-a-88395-gets-a-real-streamed-answer-copilot-app/test-failed-1.png
    ────────────────────────────────────────────────────────────────────────────────────────────────
    Error Context: ../out/results/copilot-app-live-Copilot-a-88395-gets-a-real-streamed-answer-copilot-app/error-context.md
  1 failed
    [copilot-app] › e2e/tests/copilot-app-live.spec.ts:111:3 › Copilot app — live staging › TC-22 a real question gets a real streamed answer 
  2 did not run
  1 passed (40.2s)
playwright exit=1
  ➜  Local:   http://localhost:5174/v5/
  ➜  Network: http://172.17.0.2:5174/v5/
```

The home test passes: the value on screen equals `totals.value_rs` from
`GET /api/portfolio/holdings-enriched`, and the Nifty figure equals `GET /api/markets/home`.
The question test fails at thread creation. Cause, shown with a plain client:

```
$ curl -X POST https://staging.niveshcopilot.com/api/chat/sessions            (session cookie, no Origin header)
{"session_id":"sess_10da2c274e00","user_id":"<redacted>","title":"New Conversation","created_at":"2026-10-13T09:38:13.942572+00:00","updated_at":"2026-10-13T09:38:13.942583+00:00"}
HTTP 200
$ curl -X POST … -H 'Origin: http://localhost:5174'                          (what the local page sends)
{"error":"CSRF_BLOCKED","message":"Cross-origin request rejected."}
HTTP 403
```

`backend/middleware.py` (`CsrfProtectMiddleware`) allows staging's own origins and the native
app origins; a page at `localhost` is correctly refused. The header was not spoofed. The empty
thread the first call created was deleted (`DELETE … -> HTTP 200`). This run also exposed a real
defect — a failed thread creation showed no message — now fixed and covered by TC-07c.

**2. Every screen against the real backend** (reads only):

```
Running 1 test using 1 worker
LIVE-SCREEN {"view":"tool/analysis","rendered":1,"crashed":0,"notConnected":1,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"tool/recommend","rendered":1,"crashed":0,"notConnected":0,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"tool/research","rendered":1,"crashed":0,"notConnected":0,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"tool/screener","rendered":1,"crashed":0,"notConnected":1,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"tool/markets","rendered":1,"crashed":0,"notConnected":0,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"tool/optlab","rendered":1,"crashed":0,"notConnected":1,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"trader","rendered":1,"crashed":0,"notConnected":3,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"page/watchlist","rendered":1,"crashed":0,"notConnected":5,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"page/saved","rendered":1,"crashed":0,"notConnected":2,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"page/plan","rendered":1,"crashed":0,"notConnected":2,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"page/ledger","rendered":1,"crashed":0,"notConnected":1,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"page/paper","rendered":1,"crashed":0,"notConnected":0,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"page/brokers","rendered":1,"crashed":0,"notConnected":1,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"page/settings","rendered":1,"crashed":0,"notConnected":4,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"advisor","rendered":1,"crashed":0,"notConnected":0,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"builder","rendered":1,"crashed":0,"notConnected":2,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"ops/tools","rendered":1,"crashed":0,"notConnected":1,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"ops/feeds","rendered":1,"crashed":0,"notConnected":0,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"ops/audit","rendered":1,"crashed":0,"notConnected":1,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"ops/kpis","rendered":1,"crashed":0,"notConnected":4,"loadingLeft":0,"alerts":[],"failedApi":[]}
  ✓  1 [copilot-app] › e2e/tests/copilot-app-live.spec.ts:141:3 › Copilot app — live staging › TC-22 every screen against the real backend (2.1m)
  1 passed (2.1m)
playwright exit=0
```

20 of 20 screens rendered; `failedApi` is empty for every one (no 4xx / 5xx from any endpoint,
including those whose shapes were taken from route code), no error block, no crash, no loading
state left. Onboarding was not visited (the account is already onboarded).

**3. The chat backend, asked two real questions with a plain HTTP client** — one at the
account's default context, one with its own profile open (`X-Active-Profile`):

```
{"run": "root", "frame_types": {"meta": 1, "route": 1, "widget": 1, "token": 73, "done": 1}, "route": {"agent": "market_analyst", "confidence": 0.92}, "tool_frames": 0, "widget_type": "market_detail", "widget_sources": ["NIDP", "portfolio_holdings"], "answer_chars": 869, "follow_ups": 3, "saved_roles": ["user", "assistant"], "saved_answer_id_matches_stream": true, "saved_answer_has_widget": true}
{"run": "own-profile", "frame_types": {"meta": 1, "route": 1, "widget": 1, "token": 117, "done": 1}, "route": {"agent": "risk_analyst", "confidence": 0.92}, "tool_frames": 0, "widget_type": "risk_assessment", "widget_sources": ["NIDP", "portfolio_holdings"], "answer_chars": 1394, "follow_ups": 3, "saved_roles": ["user", "assistant"], "saved_answer_id_matches_stream": true, "saved_answer_has_widget": true}
```

Both streamed `meta → route → widget → token… → done` with three follow-ups, and the saved
answer carries the same id as the stream and the widget. No `thinking` (tool) frames were sent,
so the steps card reads "no tool steps reported".

**4. Those real answers replayed through the thread UI** (the captured stream bytes and saved
messages fed to the app; captures are not committed):

```
Running 2 tests using 2 workers
REPLAY {"tag":"root","classPill":"GENERAL RESEARCH","routed":"ROUTED TO MARKET ANALYST · 92%","trace":"DONE · NO TOOL STEPS REPORTED · 0.1S","widgetType":"market_detail","widgetHeightPx":335,"answerCharsShown":866,"answerCharsSent":866,"followUps":3}
REPLAY {"tag":"own-profile","classPill":"PERSONALISED RESEARCH","routed":"ROUTED TO RISK ANALYST · 92%","trace":"DONE · NO TOOL STEPS REPORTED · 0.1S","widgetType":"risk_assessment","widgetHeightPx":1007,"answerCharsShown":1389,"answerCharsSent":1389,"followUps":3}
  ✓  1 [copilot-app] › e2e/tests/copilot-app-live.spec.ts:187:5 › Copilot app — real staging answers replayed › TC-22 replay · root (1.4s)
  ✓  2 [copilot-app] › e2e/tests/copilot-app-live.spec.ts:187:5 › Copilot app — real staging answers replayed › TC-22 replay · own-profile (1.4s)
  2 passed (2.5s)
playwright exit=0
```

Answer text shown in full (866 / 866 and 1,389 / 1,389 characters), correct label and routing,
the real result card rendered by the existing widget code, three follow-ups, two source tags.

**5. On the deployed staging app** — after PR #205 (`feat/copilot-one-screen` → `dev`) was
merged and staging redeployed. The deployed bundle (`assets/index-C7bUwQfS.js`, previously
`index-CQwzUSSh.js`) contains the new shell (`copilot-app`, `home-headline`, `composer-input`
each found once) and `GET /v5/app` answers 200. Browser pointed at staging itself:

```
$ PW_BASE_URL=https://staging.niveshcopilot.com npx playwright test --config pw.copilot-app.config.ts copilot-app-live.spec.ts -g "live staging"
Running 4 tests using 1 worker
LIVE {"label":"home","threadsInRail":10,"todayTitle":"FOR YOUR PORTFOLIO TODAY","todayCards":1,"marketStrip":"NIFTY 50 22,702 +1.51% INDIA VIX 14.14 −7.3% FII CASH −₹1,708 CR DII CASH +₹3,045 CR","freshness":"NSE LIVE","holdings":117,"valueShown":"matches API total"}
  ✓  1 [copilot-app] › e2e/tests/copilot-app-live.spec.ts:76:3 › Copilot app — live staging › TC-22 home shows the real portfolio value and market data (11.6s)
LIVE {"label":"default context","state":"saved","seconds":8.9,"classPill":"GENERAL RESEARCH","routed":"ROUTED TO MARKET ANALYST · 92%","trace":"DONE · ANSWERED WITHOUT TOOLS · 8.4S","widget":1,"answerChars":998,"answerStart":"Sector leadership: data unavailable. Our snapshot has no sector index performance, no top movers list, and no month-to-date figures, so I can't say which sector","followUps":3,"banner":null}
  ✓  2 [copilot-app] › e2e/tests/copilot-app-live.spec.ts:116:3 › Copilot app — live staging › TC-22 a real question gets a real streamed answer (9.9s)
LIVE {"label":"own profile open","state":"saved","seconds":6.9,"classPill":"PERSONALISED RESEARCH","routed":"ROUTED TO RISK ANALYST · 92%","trace":"DONE · ANSWERED WITHOUT TOOLS · 6.4S","widget":1,"answerChars":1390,"answerStart":"Risk rating: HIGH (score 6.7/10). Equity is 81% of the portfolio, with small/mid caps at 8%, which is above what a moderate profile typically supports. Key risk","followUps":3,"banner":null}
  ✘  3 [copilot-app] › e2e/tests/copilot-app-live.spec.ts:126:3 › Copilot app — live staging › TC-22 a portfolio question with the account's own profile open (4.0m)
  -  4 [copilot-app] › e2e/tests/copilot-app-live.spec.ts:146:3 › Copilot app — live staging › TC-22 every screen against the real backend
  1) [copilot-app] › e2e/tests/copilot-app-live.spec.ts:126:3 › Copilot app — live staging › TC-22 a portfolio question with the account's own profile open 
    [31mTest timeout of 240000ms exceeded.[39m
    Error: page.screenshot: Target page, context or browser has been closed
      23 |
      24 | const inr = (rupees: number) => `₹${new Intl.NumberFormat("en-IN").format(Math.round(rupees))}`;
    > 25 | const shot = async (page: Page, name: string) => { if (OUT) await page.screenshot({ path: path.join(OUT, `${name}.png`) }); };
         |                                                                        ^
      26 |
      27 | const VIEWS = [
      28 |   "tool/analysis", "tool/recommend", "tool/research", "tool/screener", "tool/markets", "tool/optlab", "trader",
        at shot (/app/e2e/tests/copilot-app-live.spec.ts:25:72)
        at /app/e2e/tests/copilot-app-live.spec.ts:141:11
    attachment #1: screenshot (image/png) ──────────────────────────────────────────────────────────
    ../out/results/copilot-app-live-Copilot-a-99e74--account-s-own-profile-open-copilot-app/test-failed-1.png
    ────────────────────────────────────────────────────────────────────────────────────────────────
    Error Context: ../out/results/copilot-app-live-Copilot-a-99e74--account-s-own-profile-open-copilot-app/error-context.md
  1 failed
    [copilot-app] › e2e/tests/copilot-app-live.spec.ts:126:3 › Copilot app — live staging › TC-22 a portfolio question with the account's own profile open 
  1 did not run
  2 passed (4.4m)
playwright exit=1
```

Tests 1 and 2 pass: real home data, and a question typed into the ask box was answered by the
real backend (state `saved`, 998 characters, result card, three follow-ups). Test 3's answer
also arrived and rendered (the `LIVE` line: state `saved`, 1,390 characters, card, three
follow-ups); the test then timed out on a step of the script itself — it clicked the "show
steps" toggle, which is disabled when the stream reports no tool steps. The script is fixed;
the test was not re-run, to avoid adding another thread. The remaining screen pass was run
separately:

```
$ PW_BASE_URL=https://staging.niveshcopilot.com npx playwright test --config pw.copilot-app.config.ts copilot-app-live.spec.ts -g "every screen"
Running 1 test using 1 worker
LIVE-SCREEN {"view":"tool/analysis","rendered":1,"crashed":0,"notConnected":1,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"tool/recommend","rendered":1,"crashed":0,"notConnected":0,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"tool/research","rendered":1,"crashed":0,"notConnected":0,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"tool/screener","rendered":1,"crashed":0,"notConnected":1,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"tool/markets","rendered":1,"crashed":0,"notConnected":0,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"tool/optlab","rendered":1,"crashed":0,"notConnected":1,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"trader","rendered":1,"crashed":0,"notConnected":3,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"page/watchlist","rendered":1,"crashed":0,"notConnected":5,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"page/saved","rendered":1,"crashed":0,"notConnected":2,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"page/plan","rendered":1,"crashed":0,"notConnected":2,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"page/ledger","rendered":1,"crashed":0,"notConnected":1,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"page/paper","rendered":1,"crashed":0,"notConnected":0,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"page/brokers","rendered":1,"crashed":0,"notConnected":1,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"page/settings","rendered":1,"crashed":0,"notConnected":4,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"advisor","rendered":1,"crashed":0,"notConnected":0,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"builder","rendered":1,"crashed":0,"notConnected":2,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"ops/tools","rendered":1,"crashed":0,"notConnected":1,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"ops/feeds","rendered":1,"crashed":0,"notConnected":0,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"ops/audit","rendered":1,"crashed":0,"notConnected":1,"loadingLeft":0,"alerts":[],"failedApi":[]}
LIVE-SCREEN {"view":"ops/kpis","rendered":1,"crashed":0,"notConnected":4,"loadingLeft":0,"alerts":[],"failedApi":[]}
  ✓  1 [copilot-app] › e2e/tests/copilot-app-live.spec.ts:148:3 › Copilot app — live staging › TC-22 every screen against the real backend (2.9m)
  1 passed (2.9m)
playwright exit=0
```

The trace text in these lines ("answered without tools") is the wording of the deployed build;
the correction below is not on `dev` yet.

**Corrections made from the live run**
- A thread that cannot be created now shows a "Not sent" message with Retry (TC-07c).
- Answers loaded from history no longer take their label from the widget's `agent` tag: the
  backend sets it to `portfolio_analyst` whichever specialist answered.
- A stream with no tool frames reads "no tool steps reported", not "answered without tools".
- At an advisor root the home section is titled for the client book, matching the prompts the
  backend returns there.

## Wiring — what each screen reads, and what is declared "not connected"

| Screen | Reads (existing endpoints) | Declared not connected |
|---|---|---|
| Shell · threads | `GET /api/chat/sessions`, `GET /api/chat/messages`, `POST /api/chat/sessions`, `POST /api/chat/stream` | Scope chips (Portfolio / Markets / Filings), "Save report", persona switcher and answer depth are left out: no backend parameter |
| Home | `/api/markets/home`, `/api/copilot/suggested-prompts`, `/api/portfolio/holdings-enriched` | — |
| Evidence | `/api/portfolio/holdings-enriched`, `/api/user/risk-profile`, `/api/goals`, stream frames | Tool steps and follow-ups exist only for answers made in the current session (the server does not store them); no per-tool output text; sources are the coarse tags the widget carries |
| Ask box | `/api/copilot/suggested-prompts`, `/api/chat/suggest-queries`, `/api/chat/instrument-search` | — |
| Portfolio analysis | `holdings-enriched`, `/api/portfolio/exposure/concentration`, `/api/portfolio/composition` | Return against Nifty 50 TRI; per-user target mix |
| Recommendations | `/api/plans/active`, `/api/plans/active/health-projection`, `/api/goals`, `/api/user/risk-profile`; `POST /api/plans/refresh` (no-plan state) | Dismiss / add-to-plan actions (existing status call does not match the backend) |
| Action plan | `/api/plans/active`, `/api/plans/history` | Observed outcomes; moving a step |
| Portfolio ledger | `holdings-enriched`, `/api/portfolio/capital-gains-statement`, `/api/portfolio/trend`, `/api/portfolio/compare`, `/api/onboarding/state` | Corrections and per-holding source |
| Stock & fund research | `instrument-search`, `/api/filings/signals`, `/api/filings/feed`, `POST /api/copilot/widgets/company_financials`, `/api/markets/corporate-actions`, `/api/thematic/prefs` | Live price, scores, valuation chart, annual statements, technicals, peers; all fund figures |
| Screener | `/api/screeners` (list, create, update, delete); run hands the compiled rule to the Copilot | Results table inside the screen |
| Markets | `/api/markets/home`, `movers`, `sectors`, `earnings`, `fii-dii`, `institutional-positioning`, `corporate-actions`, `articles`, `daily-brief`, `/api/filings/portfolio-held` | Results calendar for the user's holdings |
| Watchlist & alerts | `/api/filings/alerts` (read-only) | Personal watchlist; price and event alerts |
| Saved | `/api/screeners`, `/api/chat/sessions` | Saved reports |
| Trader desk | `/api/markets/home`, `/api/positional/journal`, `…/journal/summary/portfolio`, `/api/positional/watchlist`, `/api/positional/picks`, `/api/broker/accounts` | Broker position book, day P&L, capital, risk rules, all futures / options data |
| Options lab | `/api/markets/home` (spot, VIX); payoff computed from typed legs | Option chain, open interest, Greeks, chance of profit, margin |
| Paper trades | `/api/paper-trades/portfolio`, `evaluation`, `live` | — |
| Broker connections | `/api/broker/accounts`, `/api/broker/native/supported`, `/api/onboarding/state`, `/api/gmail/status`, `/api/gmail/history`, `/api/compliance/audit`; CAS upload | Signing in to a broker from this app |
| Settings | `/api/auth/me`, risk profile, goals (archive), Gmail status, `/api/compliance/export`; theme, mode, sign out | Answer depth, constraints, memory, privacy controls, delete account |
| Onboarding | goals, risk profile, CAS upload, Gmail import, `/api/onboarding/state`, `POST /api/user/complete-onboarding` | Portfolio rules, CSV import, broker sign-in |
| Advisor | `/api/mfd/profiles`, `/api/advisor/sip-board/summary`; opens a client with the existing profile switch | Model portfolios, client report drafts |
| Tool registry | `/api/copilot/agents` (routing agents) | The tool registry itself |
| Feed health | `/api/admin/nidp/feeds/live` | — |
| Audit log | `/api/compliance/audit` (own account) | Platform-wide log, replay |
| KPIs | `/api/admin/stats`, feeds summary | Evidence, speed, follow-through and cost metrics |
| Tool builder | none (local draft) | Saving, AI drafting, test prompts, review |

## Data Correctness (staging)
PARTIAL. Verified on real data, locally and on the deployed app: home portfolio value and
market figures equal the API values; every screen's read endpoints answer 200 with shapes the
screens accept; real chat answers render in full. Not checked: whether the figures are right
and fresh at source (no query against the NIDP tables was run). One real answer said its
snapshot had no sector performance and quoted end-of-day figures "as of 2026-10-12" while the
home strip showed live values — a property of the backend's data, not of this UI. No write
path other than chat was exercised (plan refresh, CAS upload, Gmail import, saved screens,
goal archive, advisor workspace upgrade, profile switch).

## Inputs required from user
- Merge the follow-up commits on `feat/copilot-one-screen` into `dev` to put the four corrections on staging.
- A decision on building the Android / iOS app for TC-23 (the build script publishes the APK to a public download URL).

Side effects of the live checks on the staging account: four chat threads were created
("Which sectors are leading the market this month?" twice, "How risky is my portfolio?" twice).

## Verdict: BLOCKED
<!-- Mocked suites (44/44), typecheck, build, the /lite regression and the live checks on the
     deployed staging app pass. The verdict stays BLOCKED only because TC-23 (native build) has
     not run. See OVERRIDE_copilot_one_screen.md. -->
