# OVERRIDE — One-screen Copilot app (`/v5/app`), branch `feat/copilot-one-screen`

REASON: One test case written up front is still open: TC-23, the native Android / iOS build, which needs a device build (and the APK script publishes to a public download URL, so it needs the user's go-ahead). Everything else in the plan has run, including TC-22 on the deployed staging app after PR #205 was merged (see `copilot_one_screen_20261013_1413.md`). To finish: decide on the native build and run it on a device.

- Date: 2026-10-13
- On `dev` and staging: commit 034d8089 (the app). On the feature branch only: 56ff58d1 and later (four corrections found in the first live run, and the live test spec).
- This is not a pass. Do not merge to `main` on the strength of this file.

## What is still unverified
- The Capacitor (Android / iOS) shell: safe-area insets and the on-screen keyboard over the ask box.
- Every write path other than chat: `POST /api/plans/refresh` ("Build my plan"), CAS upload and Gmail import from the new onboarding and connections screens, saved-screen create / update / delete, goal archive, the advisor-workspace upgrade, and the advisor "open client" switch.
- Whether the figures are correct and fresh at source; only that the screens show what the API returns.
- The onboarding screen against the real backend (the test account is already onboarded).
