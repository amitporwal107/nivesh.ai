# OVERRIDE: Trade Desk tab (desk redesign step 3, #377, which supersedes #376), staging check deferred

REASON: Staging serves origin/dev, and this PR is not merged yet, so the Trade Desk tab cannot be deployed to staging until this PR is merged and the frontend image is rebuilt. Verified here: tsc, the production build and Playwright with mocked APIs (test_reports/desk_trade_desk_20261027.md). Still needed after merge and deploy: open /v5/app/trader/desk?tab=trade signed in on staging, confirm (at ?tab=trade&view=paper&sub=live, and that ?tab=trade opens AI Scanner › Ranked candidates, and a row's chart opens Chart Analysis › Live chart) GET /api/desk/paper-account, /api/risk/profile, /api/desk/exit-job-status and one GET /api/desk/paper-trades per load in the network log, and compare the open and closed rows, a journal drawer and an F&O structure's payoff figures with the user's real desk_paper_trades rows.

This is not a pass. No backend file was changed.
