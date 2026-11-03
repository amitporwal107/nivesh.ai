# OVERRIDE — Market Overview tab (desk redesign step 2)

REASON: Staging deploys only after a PR merges into dev, and this branch builds on the step 1 shell
(`feat/desk-redesign-shell`), which is not merged yet. The page could therefore only be verified with mocked APIs on a
production build (tsc, vite build, Playwright: `test_reports/desk_market_overview_20261027.md`). Not verified yet, and
needed to finish: after the shell PR and this PR merge and deploy, open `/v5/app/trader/desk` on staging signed in and check
(1) `GET /api/risk/freshness` answers with `inputs.market_state` and the strip shows that regime and its as-of date
(the plan notes `macro_daily` has had no rows since 23 Oct, so a "Stale" regime is the expected honest answer until the
regime feed is fixed); (2) the Top AI ideas' rows read `GET /api/desk/trade-plans/{id}` with a real `account_size`;
(3) the stored AI watchlist's date and scan basis; (4) no `GET /api/desk/paper-trades` in the network log on this tab;
(5) 390 px on a phone.

This is not a pass. Resolve it after the merge.
