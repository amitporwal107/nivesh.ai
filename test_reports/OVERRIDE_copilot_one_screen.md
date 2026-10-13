# OVERRIDE — One-screen Copilot app (`/v5/app`), branch `feat/copilot-one-screen`

REASON: Verification against the real backend is deferred. The new frontend surface passes typecheck, a production build and 43 Playwright tests with mocked API responses (see `copilot_one_screen_20261013_1413.md`), but two test cases written up front have not run: TC-22 (real data on staging — needs the branch deployed to staging, which means a push to `dev` that the user has not approved, and a staging session token that is not on this machine) and TC-23 (native Android / iOS build — needs a device build, and the APK script publishes to a public download URL). To finish: the user approves the push to `dev` and supplies a staging session token; then open `/v5/app` with that session, confirm the home value against `GET /api/portfolio/holdings-enriched`, ask one real question, and check each screen's endpoints return the shapes the new hooks expect.

- Date: 2026-10-13
- Worktree: `/home/deploy/nivesh-copilot-ui` (code uncommitted; the design files are committed as c4a5c7fe)
- This is not a pass. Do not merge to `main` on the strength of this file.

## What is unverified because of this
- Every endpoint shape that was taken from backend route code instead of a live response (listed under "Data Correctness" in the report).
- Streaming behaviour with the real chat backend: frame timing, tool-step names, widget rendering inside the new thread.
- `POST /api/plans/refresh` from the "Build my plan" button, CAS upload and Gmail import from the new onboarding and connections screens, the advisor "open client" switch — exercised only against mocks.
- The Capacitor (Android / iOS) shell: safe-area insets and the on-screen keyboard over the ask box.
