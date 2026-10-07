# OVERRIDE — staging verification of the indicator catalogue is PENDING

REASON: this branch is not merged or deployed, and the Charts screen sits behind the `charting` feature
allowlist, so exercising the dialog against the deployed catalogue needs a fresh owner session token that this
session does not have and must not fabricate.

Verified locally instead, with real output in `test_reports/charting_w2_indicator_catalogue.md`: 8 catalogue
unit tests, 63 backend tests, 1,042 research tests, 97 Playwright cases, a clean `tsc -b` and `vite build`, and
a real re-export diffed against the previous snapshot (patterns 0/50 differ, bars 0/50 differ, config_hash
unchanged).

Next step, once merged and deployed, with a session token in a 0600 scratch file:

    curl -s -H "Cookie: session_token=<token>" https://staging.niveshcopilot.com/api/research/chart/catalogue
    cd frontend-v5 && STAGING_SESSION_FILE=<file> \
      npx playwright test e2e/tests/staging-research-charts.spec.ts --project=live-contracts

Confirm the served catalogue hash equals the deployed manifest's, then open the dialog, add SMA 200 on a symbol
with enough history, and check the RSI pane draws its 30/70 bands. Paste the result into the report and mark
this override SUPERSEDED.
