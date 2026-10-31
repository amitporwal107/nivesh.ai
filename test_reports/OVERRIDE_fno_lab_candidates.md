# OVERRIDE: fno_lab_candidates (Candidates view, branch feat/fo-lab-candidates)

REASON: The staging HTTP check of GET /api/fno/scan/candidates needs the user's staging session_token cookie, which I do not have and must not invent. Staging API evidence is therefore not in this report. The user has been asked for the token.

Evidence that exists (this session, real output):
- Backend: pytest in nivesh/backend:staging (--network none): `122 passed` (tests/test_fno_candidates.py + tests/test_fno_routes.py), including the research block with both experiments.
- Frontend: `tsc --noEmit` exit 0; production build exit 0; Playwright lab spec `41 passed, 2 skipped` (13 Candidates tests TC-3..TC-13 included; the 2 skipped are the pre-existing screenshot tests).
- Regression comparison: the specs copilot-app-desk-strategy-graphs and copilot-app-desk-smart-money give `32 failed, 32 passed` on a clean build of origin/dev AND `32 failed, 32 passed` on this branch, so those failures (including TC-F3, date-dependent) predate this work. In the full copilot-app run on this branch the only failing tests seen were in those two specs; the run's final totals line was not captured.

UNVERIFIED: the route and screen against real staging data; the full-suite totals line; why strategy-graphs fails on dev (not investigated). Test cases: test_reports/fno_lab_candidates_TESTCASES.md.
