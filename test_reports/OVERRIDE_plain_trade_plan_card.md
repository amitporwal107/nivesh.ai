# OVERRIDE — Plain trade plan card, why not / what you can do, payoff today and at expiry (feat/plain-trade-plan-card): staging pass after merge

REASON: ST-1 needs the merge. It checks the served bundle on staging and a live F&O plan's full card with a session. Every
other case passes:
- PC-1 … PC-5, WF-1 … WF-4 and PO-1 … PO-9 in mocked Playwright on a production build. The full set of 17 specs passed with
  0 failures, after two new assertions were fixed; the final decision-cards run had 35 passed.
- `tsc` is clean.
- PO-10: the backend contract tests pass (113 passed).
- PO-11: the staging payoff engine, run in-process, gives exactly the fixture's answers.

See `test_reports/plain_trade_plan_card_20261029.md`. This branch carries the commits of PRs #404 and #405, so merge those
first.

To finish: after the deploy, check that the served bundle has "Profit or loss: today and at expiry" and "What you can do".
Then open a live F&O plan's full card with a session. Paste the result, set the verdict to PASS and delete this file.
Owner-visible: yes. Date: 2026-10-29. Session 3d5d2da4.
