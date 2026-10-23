# OVERRIDE: fno_forward_test (branch feat/fo-forward-test)

REASON: The new route and the recorder script are not deployed to staging yet (bind-mounted code is not loaded code) and I have no session token on hand, so neither the route nor the recorder has been run against staging. Nothing has been recorded: the panel will say "Recording has not started" until the recorder runs.

Evidence (this session, real output):
- pytest (staging image): tests/test_fno_forward.py (5) + tests/test_fno_routes.py + tests/test_fno_candidates.py `133 passed` (3 new forward-test route tests; route-list test updated).
- `tsc --noEmit` exit 0; build exit 0; Playwright portfolio-fno + desk + lab `116 passed, 2 skipped` (5 new forward-test panel tests).
- Test cases: test_reports/fno_forward_test_TESTCASES.md.

Design limits (stated): two settings are recorded (production floors, no threshold); the five frozen volume-floor settings are not (they need 20 sessions of the contract's own volume at signal time). A session is recorded only before the next open (the script refuses a late record). Signals are judged on adjusted prices read through the data platform, entry next open, exit close 5 sessions on, benchmark = equal-weight universe, 0.15% assumed cost; no mean/t before 30 judged sessions.
Not done: the nightly job that calls scripts/record_fno_forward.py (awaiting the user's yes to install a schedule). After deploy: `docker exec -w /app/backend nivesh-staging-app-backend python -m scripts.record_fno_forward --dry-run` then without --dry-run before the next open.
UNVERIFIED: the route and recorder on staging; latency of ~214 futures reads per recording.
