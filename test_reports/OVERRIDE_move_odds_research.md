# OVERRIDE — Move odds screen on /research (not yet staging-verified)

REASON: Staging API and real-staging Playwright checks (TC-28..TC-30) cannot run until (1) the user approves deploying the DaaS router and the app — the app deploys from `dev`, which also redeploys live login — and (2) the user supplies staging session tokens for one allowlisted and one non-allowlisted account. Everything that can run without them has run with real output in test_reports/move_odds_research_20260916_2351.md: unit tests (DaaS 49 passed, app 12 passed, publisher 6 passed), mocked Playwright (13 passed), production build, migration 149 applied to nidp_staging, and the published data checked by SQL against the frozen snapshot. The feature flag defaults to an empty allowlist, so nothing is visible to any user.

Status: IN PROGRESS. The report's verdict stays BLOCKED until TC-28..TC-30 pass on staging.
