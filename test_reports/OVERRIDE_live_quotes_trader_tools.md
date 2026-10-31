# Override: live Kite quotes across the trader tools

REASON: frontend-only change tested locally on a production build with mocked /api (tsc clean; 168 Playwright passed, 1 failed on a date-dependent test unrelated to the change; see live_quotes_trader_tools_20261023.md). It is not deployed: staging needs the PR merged to dev and the frontend image rebuilt, and no staging session token has been provided for a deployed Playwright run.
