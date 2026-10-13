# OVERRIDE — Broker hub in Copilot Settings and onboarding (branch `feat/broker-hub-ui`)

REASON: The screens are verified only against mocked APIs (Playwright, 267 passed / 19 skipped / 0 failed; typecheck clean). They have not been opened on staging, because the branch is not merged into `dev` and I have no staging `session_token`; a real broker connect additionally needs Nivesh's app keys for a broker on staging and a broker login. To finish: merge the PR into `dev`, give a staging session token, then run the live checks L1 and L2 in `test_reports/broker_hub_ui_20261014_0015.md` (and `frontend-v5/e2e/tests/copilot-app-live.spec.ts` with `PW_BASE_URL=https://staging.niveshcopilot.com`) and replace this override with a report ending in the PASS verdict.

- **Date:** 2026-10-14
- **Status of the work:** IN PROGRESS. Backend (PR #206) is merged and its routes answer on staging; no authenticated staging call has been made for it either (see `test_reports/OVERRIDE_broker_hub_backend.md`).
- **This is not a pass.** Resolve before merge to `main`.
