# OVERRIDE — One-screen Copilot app (`/v5/app`)

REASON: Not a pass — round 4 is blocked on deployment (2026-10-14). Round 3 is merged (PR #207) and verified on the deployed staging app. Round 4 is committed and pushed on `feat/copilot-round4` (tip 75dc1da3 plus the report commit): Trendlyne fundamentals with the source recorded, the statements "import all" mode, personal watchlists, the option model, live broker positions and two plan documents. Everything that can run before a deploy has run and passed: `tsc -b` and the build from a clean checkout, 315 Playwright cases (mocked APIs), 467 backend tests, and the option model on a real staging chain. What the protocol still requires cannot run yet: the new routes are not on staging until the branch is merged; migration 162 and the Trendlyne pass need the owner's go-ahead on the staging data platform; the statement-history import has never met real Gmail or a real statement. One instruction is blocked outright: fund factsheets cannot come from Trendlyne (its server has no fund data), and the owner has not yet chosen another source. Full record: `copilot_round4_20261014_0430.md` (Verdict: BLOCKED). To finish: merge, run the runbooks in that report, then test on staging.

- Date: 2026-10-13
- On `dev` and staging: commit 034d8089 (the app). On the feature branch only: 56ff58d1 and later (four corrections found in the first live run, and the live test spec).
- This is not a pass. Do not merge to `main` on the strength of this file.

## What is still unverified
- The Capacitor (Android / iOS) shell: safe-area insets and the on-screen keyboard over the ask box.
- Every write path other than chat: `POST /api/plans/refresh` ("Build my plan"), CAS upload and Gmail import from the new onboarding and connections screens, saved-screen create / update / delete, goal archive, the advisor-workspace upgrade, and the advisor "open client" switch.
- Whether the figures are correct and fresh at source; only that the screens show what the API returns.
- The onboarding screen against the real backend (the test account is already onboarded).
