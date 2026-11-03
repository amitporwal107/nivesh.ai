# OVERRIDE — Phase 1 universal risk: signed-in staging API verification deferred

REASON: The signed-in staging API checks (GET/PUT /api/risk/profile, desk POST reduce/block with risk_decisions rows,
F&O index idea judged, kill switch on every path) need the branch deployed to staging and an owner session token. The
brief forbids deploys and writes to staging, and no token was provided. Everything else is verified with real output in
test_reports/p1_universal_risk_20261027.md: the unit and integration suites, the real-Mongo concurrency tests, the
full-suite comparison with origin/dev, Playwright with a mocked API, and read-only probes of the real staging book and
the migration dry run. To finish: deploy (backend restart + frontend-v5 rebuild), then run the PR's "Staging
verification plan" with the owner's token, and append the real output to the report. This is not a pass.
