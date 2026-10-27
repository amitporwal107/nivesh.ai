# OVERRIDE — p2_trade_plan_lifecycle (staging endpoint verification deferred)

Branch `feat/p2-trade-plan-lifecycle`. Report: `test_reports/p2_trade_plan_lifecycle_20261027.md`.

REASON: The brief for this branch is read-only towards staging (no push, PR, merge or deploy), so the new and changed
endpoints (GET /api/desk/trade-plans/{id}, POST /api/desk/paper-trades with plan_ref, GET/POST
/api/desk/paper-trades/{id}/roll, the trade_plan fields of /api/desk/strategy/plan|ideas|top) cannot be called on staging
yet. What was verified instead: the backend unit, route and contract tests, a real-PostgreSQL run of migration 025, the
mocked Playwright specs, and two READ-ONLY staging data checks (the lifecycle backfill dry run and the stop-method
classification of the 26 Oct scanner signals). To finish: merge to dev, let the CI deploy, apply migration 025, then run
the staging verification plan in the PR body (steps 1-6) and replace this override with a report whose last line is
`## Verdict: PASS`.
