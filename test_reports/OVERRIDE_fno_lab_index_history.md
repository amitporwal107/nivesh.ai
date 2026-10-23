# OVERRIDE: fno_lab_index_history (branch feat/fo-lab-index-history)

REASON: Staging HTTP/UI evidence of the NEW route needs the backend deployed and restarted first (bind-mounted code is not loaded code); it is not on staging yet. The frontend degrades to the panel's own notice if the route is absent.

Evidence (this session, real output):
- pytest (staging image): tests/test_fno_routes.py + tests/test_fno_candidates.py `128 passed` (3 new positioning-history tests; route-list test updated).
- `tsc --noEmit` exit 0; build exit 0; Playwright lab + portfolio-fno `96 passed, 2 skipped` (4 new tests TC-5..TC-8).
- Test cases: test_reports/fno_lab_index_history_TESTCASES.md.
UNVERIFIED: GET /api/fno/NIFTY/positioning-history on staging (16 weekday reads of /desk/fno-buildup per call, 4 at a time: latency not measured); the workspace on the deployed build.
