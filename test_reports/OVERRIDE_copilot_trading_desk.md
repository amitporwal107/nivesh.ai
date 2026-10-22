# OVERRIDE — Smart trading desk (Copilot app, Trader tool) — staging check pending

REASON: The desk is built and verified on a local production build with mocked APIs, but it cannot be verified on staging yet. (1) Deployment: this session cannot push to `dev` (the auto-deploy branch); the user must merge `feat/copilot-trading-desk` before https://staging.niveshcopilot.com:8443/v5/app/trader/desk exists. (2) Data: the staging app DB's scanner tables (`stock_ohlcv`, `chartink_scan_hits`, `stock_technical_features`, `positional_signals`) have 0 rows because the positional engine was never scheduled on the CloudPe app VM; running it writes to shared staging and needs the user's go-ahead. Move-odds runs (`nidp.tpd_runs`) are empty by the user's choice (preview mode), so probabilities show "not published" there.

Verified this session (real output in test_reports/copilot_trading_desk_20261014_1200.md): `tsc --noEmit` clean; `vite build` ok; desk specs 49/49 pass (shell, Overview + Intel, Scanner + Chart + risk desk, Portfolio + F&O); every copilot-app spec 365 passed, 23 skipped (pre-existing), 0 failed. Read-only staging data checks: F&O bhavcopy, adjusted prices, filings, macro regime fresh to 13–14 Oct 2026.

Needed to close: the user's merge to dev → staging UI check with a real session; the user's decision on running the positional engine on staging.
