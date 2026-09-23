# OVERRIDE — staging verification of the saved-layout menu is PENDING

REASON: this branch is not merged or deployed, and the Charts screen sits behind the `charting` feature
allowlist, so reaching it needs a fresh owner session token that this session does not have and must not
fabricate. The layouts API itself IS live on staging as of the PR #148 deploy (`/api/research/chart-layouts`
answers 401, not 404), but exercising the menu against it needs a signed-in browser.

Verified locally instead, with real output in `test_reports/charting_w1b_layouts_ui.md`: `npx tsc -b`,
`npx vite build`, and 91 Playwright cases across the three chart specs.

Next step, once merged and deployed, with a session token in a 0600 scratch file:

    cd frontend-v5 && STAGING_SESSION_FILE=<file> \
      npx playwright test e2e/tests/staging-research-charts.spec.ts --project=live-contracts

Then save a layout on staging, reload, reopen it, and confirm the workspace comes back; paste the result into
`charting_w1b_layouts_ui.md` and mark this override SUPERSEDED.
