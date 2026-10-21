# OVERRIDE — Desk results expectation backend — UNIT + READ-ONLY DATA VERIFIED, STAGING HTTP NOT RUN

REASON: GET /v1/desk/events-calendar/expectation (DaaS) and GET /api/markets/events-calendar/expectation (app) exist only on branch feat/desk-results-expectation. Staging HTTP verification is blocked until (1) the user merges the branch to dev (this fork cannot push or deploy) and (2) a staging session token is supplied for the signed-in app route.

What was run: 185 tests pass (55 new in test_daas_desk_expectation.py); the real method and backtest ran offline on rows read from the staging warehouse (15,257 quarterly rows). Report: test_reports/desk_results_expectation_backend_20261021.md. No staging write was made.
