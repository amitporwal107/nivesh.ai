# OVERRIDE — reversal engine (feat/reversal-engine)

REASON: The staging API endpoint tests required by .claude/VERIFICATION_PROTOCOL.md cannot be run yet. The new routes
(GET /api/positional/reversal-candidates on the app, GET /v1/features/reversal-snapshot on the data platform) exist only in
the worktree /home/deploy/nivesh-reversal-engine; nothing is pushed or deployed, and pushing to `dev` auto-deploys the staging
app VM, which is an outward-facing action the user has not authorised for this work. Staging therefore has no such endpoint to call.

What WAS run, with real output, is in test_reports/reversal_engine_20261020.md: pytest (203 passed), the real DaaS endpoint
function replayed on real staging rows, an independent SQL recomputation on staging, tsc, and the full copilot-app Playwright suite.

Needed from the user to close this: permission to push feat/reversal-engine (or to deploy it to staging by the method they choose)
so the two endpoints can be called on staging, plus a session token for the app route.
