# OVERRIDE — staging verification of the W1b chart workspace is PENDING

REASON: staging cannot be exercised from this session. The W1b wiring is not deployed (it is not yet merged to
`dev`, which is what staging redeploys from), and the Charts screen is behind the `charting` feature allowlist, so
reaching it needs a fresh owner session token that this session does not have and must not fabricate.

What IS verified locally, with real output in `test_reports/charting_w1b_workspace_wiring.md`:
`npx tsc -b`, `npx vite build`, and the three chart Playwright suites against mocked API fixtures.

What is NOT verified: the same screen against the real staging API and the real published snapshot — in
particular the weekly/monthly interval switch against real resampled bars, the pane layout at the real bar
counts, and both themes on the deployed build.

Next step, after this is merged and deployed to staging, with a session token in a 0600 scratch file:

    cd frontend-v5 && STAGING_SESSION_FILE=<file> \
      npx playwright test e2e/tests/staging-research-charts.spec.ts --project=live-contracts

Then paste the real output into `test_reports/charting_w1b_workspace_wiring.md`, flip its verdict to PASS, and
mark this override SUPERSEDED.
