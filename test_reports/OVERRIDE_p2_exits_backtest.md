# OVERRIDE — p2 exits + backtest integrity (feat/p2-exits-backtest)

REASON: The staging API run of the new code is deferred. This task forbids push, PR and merge, and staging runs `dev`,
so the new endpoints' fields (exit_rules, stop_history, current_stop, stop_version, premium_plan, exit_basis) cannot be
called on staging yet. What did pass:
- every unit, contract and route test (TestClient);
- the full backend suite, with no regressions against origin/dev;
- Playwright on a mocked API;
- a read-only replay of all 12 stored staging trades, which agree 12/12.
To finish, after the owner merges to dev and the backend restarts, run the "Staging verification plan" in the PR body,
including the BANKNIFTY spread that expires on 27 Oct, which must be marked at close and settled at intrinsic value, never
at settle. Report: test_reports/p2_exits_backtest_20261027.md.
