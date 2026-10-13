# OVERRIDE — One-screen Copilot app (`/v5/app`), branch `feat/copilot-one-screen`

REASON: Not a pass — blocked on deployment. Round 3 (2026-10-13: the screens wired to existing APIs, two new backend routes, icons, tool-builder templates) is committed and pushed on `feat/copilot-one-screen` (tip 58631505) but not merged to `dev`, so the protocol's staging steps cannot run yet: the new routes `POST /api/screeners/run` and `GET /api/fno/*` have not been called over HTTP on staging, and no screen of this round has been opened in a browser against the real backend. Everything that can run before a deploy has run and passed: `tsc -b` and the build from a clean checkout, 247 Playwright cases (mocked APIs), 233 backend unit tests, both new route handlers against the real staging data, and read-only shape checks of every endpoint the screens parse. Every write on the new screens was tested only against mocks. Full record, test cases and the gap list: `copilot_tools_wiring_20261013_2345.md` (Verdict: BLOCKED). To finish: merge to `dev`, then run `e2e/tests/copilot-app-live.spec.ts` on the deployed app and curl the two routes with a session. TC-23 (native Android / iOS build) is also still open and needs the user's go-ahead.

- Date: 2026-10-13
- On `dev` and staging: commit 034d8089 (the app). On the feature branch only: 56ff58d1 and later (four corrections found in the first live run, and the live test spec).
- This is not a pass. Do not merge to `main` on the strength of this file.

## What is still unverified
- The Capacitor (Android / iOS) shell: safe-area insets and the on-screen keyboard over the ask box.
- Every write path other than chat: `POST /api/plans/refresh` ("Build my plan"), CAS upload and Gmail import from the new onboarding and connections screens, saved-screen create / update / delete, goal archive, the advisor-workspace upgrade, and the advisor "open client" switch.
- Whether the figures are correct and fresh at source; only that the screens show what the API returns.
- The onboarding screen against the real backend (the test account is already onboarded).
