# OVERRIDE: desk redesign backend routes (2026-10-27)

REASON: The four read-only routes (GET /api/desk/idea-scorecard, /api/desk/exit-job-status, /api/desk/paper-account/corrections, /api/risk/freshness) are built and tested on branch feat/desk-redesign-backend: 43 new tests pass, and the full CI allowlist shows the same 3 network-only failures as dev. Their handlers were also run read-only against staging's real data inside the staging backend container. They are not deployed until the PR to dev is merged, so no HTTP call to staging has been made. To finish: merge, deploy (backend bind mount + restart), then curl each route on staging with a signed-in session and append the output to test_reports/desk_redesign_backend_20261027.md.

Known at deploy time:
- Staging has no check_desk_alerts heartbeat in job_runs, so /api/desk/exit-job-status will answer "missed" (state never_run) until the evening job records a run.
- The prod compose does not mount research/, so /api/desk/idea-scorecard will answer 503 scorecard_unavailable there until it does.
