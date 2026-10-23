# OVERRIDE: fix_chart_live_bar (branch feat/chart-live-bar)

REASON: Staging UI evidence needs the user's session_token cookie, which I do not have. Frontend-only change: no backend route touched.

Evidence (this session, real output): `tsc --noEmit` exit 0; build exit 0; Playwright copilot-app-desk-scanner spec `80 passed` (3 new tests TC-L1..TC-L3 on top of the existing header/chip tests). Test cases: test_reports/fix_chart_live_bar_TESTCASES.md.

Limits (stated): the indicator lines (EMA, VWAP 20D) come from the server's feature engine and stop at the adjusted session; the appended bar is Kite's quote (open/high/low/last/volume), not an adjusted bar. After a split or bonus on the new day Kite's bar and the adjusted history can disagree until the adjusted series catches up.
UNVERIFIED: the chart against the deployed staging build and the live feed during market hours.
