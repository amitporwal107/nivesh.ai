# OVERRIDE: fno_lab_index_workspaces (NIFTY & BANKNIFTY workspaces, branch feat/fo-lab-index-workspaces)

REASON: Staging HTTP evidence needs the user's staging session_token cookie, which I do not have. The change adds no new route: it reads the existing GET /api/fno/{symbol}/futures and /chain, so no new endpoint is left unverified, but the screen has not been opened against real staging data.

Evidence (this session, real output):
- `tsc --noEmit` exit 0; production build exit 0.
- Playwright (production build, mocked API): lab + portfolio-fno + desk specs `97 passed, 2 skipped` (7 new index-workspace tests TC-1..TC-9; TC-30 and the phone test updated for the selector).
- Test cases: test_reports/fno_lab_index_workspaces_TESTCASES.md.

Not in this step (stated): the last-five-sessions state history (needs a new backend route) and Greek-weighted exposure.
UNVERIFIED: the screen against real staging data.
