# Functionality Verification Report — One-screen Copilot app (desktop + mobile)

- **Branch:** feat/copilot-one-screen (worktree `/home/deploy/nivesh-copilot-ui`, based on `origin/dev` b0184b1a; code changes are uncommitted)
- **Date:** 2026-10-13
- **Author:** Claude (design engineer + full-stack developer + QA)
- **Environment:** production build (`vite build`, base `/v5/`) served by `vite preview`, every `/api/*` call answered by Playwright route mocks. NOT staging: nothing is deployed and no real session was used.
- **Changed areas:** backend routes/services: no · frontend src: yes

## Summary
Status: **IN PROGRESS**. A new signed-in surface at `/v5/app` implements the "Nivesh Copilot"
one-screen design (`frontend-v5/design/nivesh-copilot/`): rail, home, ask box with
suggestions, answer thread with tool steps, evidence panel, and 21 tool / workspace / trader /
advisor / internal screens, at desktop and phone widths. It reads existing backend endpoints
only; no backend file is changed. Existing routes (`/lite`, `/chat`, `/dashboard`, …) are not
modified — the only edit outside the new folder is one added route in `src/routes.tsx`.

Verified here: typecheck, production build, and 43 Playwright tests (shell and screens,
desktop 1280×800 and phone 390×844) plus the existing `/lite` regression spec, all with
mocked API responses. Not verified: anything against the real backend (TC-22) and the native
Android / iOS build (TC-23). Those need a deploy to staging, a session token and a device build.

Every response in these tests is a fixture or an inline test payload (MOCK — not real data).
Expected values in the per-screen tests were worked out from the payload, not copied from the
screen.

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
| TC-22 | Live data | `/v5/app` on staging with a real session | e2e · live | Real portfolio value and a real streamed answer | **NOT RUN** — needs a deploy to staging and a session token |
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

Commands (run inside `mcr.microsoft.com/playwright:v1.47.0-jammy` with no network, from
`frontend-v5/`):

```
VITE_USE_MOCK_API=false VITE_BASE=/v5/ npx vite build --outDir /tmp/cp-dist --emptyOutDir
VITE_BASE=/v5/ npx vite preview --outDir /tmp/cp-dist --port 5174 --strictPort &
npx playwright test --config pw.copilot-app.config.ts copilot-app.spec.ts copilot-app-screens.spec.ts
npx playwright test --config pw.copilot.config.ts lite-copilot.spec.ts
```

- **Typecheck**

```
$ npx tsc --noEmit -p tsconfig.json
tsc exit=0
```

- **Specs:** `frontend-v5/e2e/tests/copilot-app.spec.ts`, `frontend-v5/e2e/tests/copilot-app-screens.spec.ts` — Result: PASS (43 passed)

```
- Use build.rollupOptions.output.manualChunks to improve chunking: https://rollupjs.org/configuration-options/#output-manualchunks
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
✓ built in 19.86s
Running 43 tests using 3 workers
  ✓   1 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:106:3 › Copilot app screens — phone (390×844) › TC-17 every destination renders without sideways page scroll (17.4s)
  ✓   2 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:77:3 › Copilot app screens — desktop › TC-17 every rail destination renders (17.6s)
  ✓   3 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:85:3 › Copilot app screens — desktop › TC-18 with empty API responses no screen shows the design's sample data (17.9s)
  ✓   4 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:157:3 › TC-19 screens show their endpoint's data — desktop › Portfolio analysis ← holdings-enriched + concentration (751ms)
  ✓   5 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:172:3 › TC-19 screens show their endpoint's data — desktop › Portfolio ledger ← holdings-enriched (848ms)
  ✓   7 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:202:3 › TC-19 screens show their endpoint's data — desktop › Markets ← markets/home, and a mover row asks the Copilot (972ms)
  ✓   8 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:217:3 › TC-19 screens show their endpoint's data — desktop › Research ← instrument search + company financials (1.3s)
  ✓   9 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:237:3 › TC-19 screens show their endpoint's data — desktop › Screener ← saved screeners; a rule compiles to the query that is asked (881ms)
  ✓   6 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:184:3 › TC-19 screens show their endpoint's data — desktop › Recommendations and Action plan ← plans/active (2.8s)
  ✓  11 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:273:3 › TC-19 screens show their endpoint's data — desktop › Saved ← screeners + chat sessions; a thread opens (852ms)
  ✓  10 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:251:3 › TC-19 screens show their endpoint's data — desktop › Watchlist ← filing alerts only; the internal research list is not requested (1.2s)
  ✓  12 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:285:3 › TC-19 screens show their endpoint's data — desktop › Trader desk ← journal, scanner, watch levels, broker accounts, markets/home (942ms)
  ✓  14 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:341:3 › TC-19 screens show their endpoint's data — desktop › Paper trades ← paper-trades portfolio, evaluation, live (1.0s)
  ✓  13 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:316:3 › TC-19 screens show their endpoint's data — desktop › Options lab: payoff is computed from typed legs; chain and open interest are declared missing (1.2s)
  ✓  15 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:369:3 › TC-19 screens show their endpoint's data — desktop › Advisor ← client book + SIP board; opening a client lands in the Copilot (1.1s)
  ✓  16 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:400:3 › TC-19 screens show their endpoint's data — desktop › Advisor screen explains itself to a non-advisor account (794ms)
  ✓  18 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:447:3 › TC-19 screens show their endpoint's data — desktop › Tool builder: the contract is derived from what is typed; saving is declared missing (1.1s)
  ✓  19 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:463:3 › TC-19 screens show their endpoint's data — desktop › the engineering 'needs' list on a not-connected block is shown to admins only (1.3s)
  ✓  17 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:405:3 › TC-19 screens show their endpoint's data — desktop › Internal pages ← feeds, audit trail, admin stats, routing agents (2.3s)
  ✓  21 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:512:3 › TC-19 account screens — desktop › Onboarding: if recording completion fails the user still gets out, and is told (794ms)
  ✓  20 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:497:3 › TC-19 account screens — desktop › Onboarding: skipping records completion and lands on home for good (1.4s)
  ✓  22 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:522:3 › TC-19 account screens — desktop › Onboarding: the four steps in order, showing what is on file, then finish (1.2s)
  ✓  23 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:545:3 › TC-19 account screens — desktop › Broker connections ← broker accounts, statement on file, Gmail, import log (890ms)
  ✓  25 [copilot-app] › e2e/tests/copilot-app.spec.ts:125:3 › Copilot app — desktop › TC-01 shell renders: rail, greeting, ask box (865ms)
  ✓  24 [copilot-app] › e2e/tests/copilot-app-screens.spec.ts:569:3 › TC-19 account screens — desktop › Settings ← profile, risk, goals; mode and theme take effect (1.3s)
  ✓  26 [copilot-app] › e2e/tests/copilot-app.spec.ts:144:3 › Copilot app — desktop › TC-02 rail lists saved threads and opens one (1.1s)
  ✓  27 [copilot-app] › e2e/tests/copilot-app.spec.ts:172:3 › Copilot app — desktop › TC-03 market strip shows /api/markets/home values, and nothing when it is empty (1.3s)
  ✓  28 [copilot-app] › e2e/tests/copilot-app.spec.ts:192:3 › Copilot app — desktop › TC-04 'for your portfolio today' cards come from suggested-prompts and ask their query (1.2s)
  ✓  29 [copilot-app] › e2e/tests/copilot-app.spec.ts:211:3 › Copilot app — desktop › TC-05 asking a question streams an answer with class, tool steps and follow-ups (1.4s)
  ✓  30 [copilot-app] › e2e/tests/copilot-app.spec.ts:252:3 › Copilot app — desktop › TC-06 an error frame shows a partial-result banner with a working retry (1.2s)
  ✓  31 [copilot-app] › e2e/tests/copilot-app.spec.ts:269:3 › Copilot app — desktop › TC-07 a failed stream request shows an error and leaves the ask box usable (1.1s)
  ✓  32 [copilot-app] › e2e/tests/copilot-app.spec.ts:284:3 › Copilot app — desktop › TC-07b stopping an answer in flight keeps the question and offers a retry (1.2s)
  ✓  33 [copilot-app] › e2e/tests/copilot-app.spec.ts:308:3 › Copilot app — desktop › TC-08 an account with no holdings gets the connect banner and no zero values (1.3s)
  ✓  34 [copilot-app] › e2e/tests/copilot-app.spec.ts:328:3 › Copilot app — desktop › TC-09 evidence panel: context on home, tools and sources in a thread, and the toggle (1.6s)
  ✓  35 [copilot-app] › e2e/tests/copilot-app.spec.ts:365:3 › Copilot app — desktop › TC-10 ask-box suggestions: ranked prompts, completions, keyboard (1.6s)
  ✓  36 [copilot-app] › e2e/tests/copilot-app.spec.ts:394:3 › Copilot app — desktop › TC-11 mode pill swaps the tools; Advisor only for an advisory workspace (1.8s)
  ✓  38 [copilot-app] › e2e/tests/copilot-app.spec.ts:446:3 › Copilot app — desktop › TC-13 a signed-out visitor is sent to login (939ms)
  ✓  37 [copilot-app] › e2e/tests/copilot-app.spec.ts:425:3 › Copilot app — desktop › TC-12 internal pages are for admins only (1.8s)
  ✓  39 [copilot-app] › e2e/tests/copilot-app.spec.ts:453:3 › Copilot app — desktop › a user who has not finished onboarding lands on the onboarding screen (843ms)
  ✓  40 [copilot-app] › e2e/tests/copilot-app.spec.ts:462:3 › Copilot app — desktop › an unknown view falls back to home (790ms)
  ✓  41 [copilot-app] › e2e/tests/copilot-app.spec.ts:486:3 › Copilot app — phone (390×844) › TC-14 no rail; the menu opens a drawer that navigates and closes (1.0s)
  ✓  42 [copilot-app] › e2e/tests/copilot-app.spec.ts:513:3 › Copilot app — phone (390×844) › TC-15 evidence opens as a bottom sheet and closes (849ms)
  ✓  43 [copilot-app] › e2e/tests/copilot-app.spec.ts:529:3 › Copilot app — phone (390×844) › TC-16 the ask flow works and the ask box stays on screen (832ms)
  43 passed (35.5s)
playwright exit=0
```

- **Regression spec:** `frontend-v5/e2e/tests/lite-copilot.spec.ts` — Result: PASS (4 passed)

```
✓ built in 18.85s

Running 4 tests using 1 worker

  ✓  1 [unauthenticated] › e2e/tests/lite-copilot.spec.ts:31:3 › Lite Copilot surface › /lite renders the Copilot (1.1s)
  ✓  2 [unauthenticated] › e2e/tests/lite-copilot.spec.ts:38:3 › Lite Copilot surface › /lite hides the dashboard sidebar (no app chrome) (1.1s)
  ✓  3 [unauthenticated] › e2e/tests/lite-copilot.spec.ts:44:3 › Lite Copilot surface › NOT-onboarded user on /lite is routed to onboarding (CAS upload / Gmail sync) (525ms)
  ✓  4 [unauthenticated] › e2e/tests/lite-copilot.spec.ts:57:3 › Lite Copilot surface › CONTROL: /chat renders the SAME Copilot WITH the sidebar (1.1s)

  4 passed (4.8s)
playwright exit=0
```

Screenshots of every screen at both sizes, plus the light theme, were captured with
`copilot-app-shots.spec.ts` (skipped unless `SHOT_DIR` is set) and reviewed by eye against the
design. They are not committed.

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
NOT RUN. Mocked tests prove the screens show what the endpoint returns; they cannot prove the
real endpoints return correct, fresh data. `GET /api/markets/home` answers 401 without a
session (output above), so this needs TC-22.

Response shapes for endpoints that had no frontend hook were taken from the backend route
code, not from a live response: positional journal / picks / watchlist, broker accounts and
adapters, plans history and health projection, capital-gains statement, portfolio compare,
company financials widget, filings signals / feed / alerts, thematic prefs, admin stats,
copilot agents, compliance audit / export, Gmail history. Each is UNVERIFIED against staging.

## Inputs required from user
- A staging session token and a go-ahead to push the branch to `dev` (which deploys to staging), for TC-22.
- A decision on building the Android / iOS app for TC-23 (the build script publishes the APK to a public download URL).

## Verdict: BLOCKED
<!-- 43/43 mocked UI tests, typecheck, build and the /lite regression pass. The verdict stays
     BLOCKED because TC-22 (real data on staging) and TC-23 (native build) have not run.
     See test_reports/OVERRIDE_copilot_one_screen.md. -->
