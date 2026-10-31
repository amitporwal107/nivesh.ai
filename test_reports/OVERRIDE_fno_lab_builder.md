# OVERRIDE: fno_lab_builder (branch feat/fo-lab-builder)

REASON: Staging UI evidence needs the user's session_token cookie (not on hand now) and the deployed build. Frontend-only change; it reads the existing GET /api/fno/{symbol}/chain and POST /api/desk/strategy/payoff (a pure calculation).

Evidence (this session, real output):
- `tsc --noEmit` exit 0; production build exit 0.
- Playwright (mocked API): lab + portfolio-fno + desk specs `118 passed, 2 skipped` (7 new builder tests TC-1..TC-9; the 6 older Paper-strategies tests now open the Rule-based ideas mode first).
- copilot-app-desk-strategy-graphs.spec fails on a clean origin/dev build too (32 failed across it and smart-money before this work, measured earlier); not caused by this change.
- Test cases: test_reports/fno_lab_builder_TESTCASES.md.

Limits (stated): the browser computes no payoff/Greek/cost/capital figure (the route's answer is shown); the mock payoff in the spec is an independent expiry-payoff calculation, so the route's real answer (costs, pre-expiry Greeks) is exercised only through the existing strategy-graphs spec, which currently fails on dev for an unrelated reason. Mini payoff shapes on the tiles are illustrations.
UNVERIFIED: the builder on staging against the real payoff route; option legs priced at end-of-day closes only.
