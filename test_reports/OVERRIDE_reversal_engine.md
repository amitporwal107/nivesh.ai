# OVERRIDE — reversal engine (feat/reversal-engine)

REASON: Awaiting a staging session token from the user. The branch is deployed to staging (user-approved 2026-10-20) and the
data-platform endpoint, the unauthenticated route (401) and the deployed route code with only login stubbed were all exercised
with real output (test_reports/reversal_engine_20261020.md, section "Staging"). Still not done: an authenticated external call of
GET /api/positional/reversal-candidates and a Playwright run against the live staging UI, both of which need a logged-in session
cookie I do not have and will not fabricate.

Needed from the user: a staging session token (cookie) for staging.niveshcopilot.com.
