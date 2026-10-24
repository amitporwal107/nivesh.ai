# OVERRIDE: paper_accounting_fixes (branch fix/paper-accounting, from origin/dev 19263e08)

REASON: staging verification needs merge to dev, backend restart and a user session token (and the cron must be installed by an operator); local pytest: `438 passed, 4 warnings in 16.73s` (10 files: test_paper_account, test_desk_trading, test_desk_paper_sim, test_honesty_safety_pass, test_desk_strategy_trades, test_fno_forward, test_desk_alerts, test_ai_trader_execution, test_fno_routes, test_paper_trades_routes); baseline on origin/dev for the first 9 of those files: `2 failed, 415 passed` (the two stale gap-fill tests); `python -m compileall -q services scripts` exit 0.

Test cases: test_reports/paper_accounting_fixes_TESTCASES.md (PA-1 … PA-16), written before the implementation.

Evidence (this session, throwaway container `nivesh/backend:staging`, worktree mounted read-only, `--network none`):
- Full run: `438 passed, 4 warnings in 16.73s`.
- New and renamed tests, `-rA`: the five account, sim and cron tests PASSED (`5 passed`); the eight strategy-release and evening-script tests PASSED (`8 passed, 60 deselected`).
- The concurrency test against origin/dev's `services/paper_account.py` (mounted over the new file) FAILS as intended: `AssertionError: [600000.0, 600000.0]`, meaning both ₹6 lakh reserves passed on a ₹10 lakh account. With the new code exactly one passes.

What changed:
1. `services/desk_strategy_trades.close_strategy_trade` releases `paper_reserved_rs` with the structure's `net_pnl_rs`, only when its status-filtered update matched. Every close goes through it: manual (route), list read and evening script (`apply_exits`). With an unknown net P&L (a leg with no mark), the capital comes back and cash is not moved.
2. `scripts/check_desk_alerts.py` runs `desk_strategy_trades.apply_exits` for open strategy trades and honours `--dry-run` (`persist=not dry_run`). New output fields: `open_strategy_trades`, `strategy_exits` (by reason) and `strategy_not_checked`. `ok` counts strategy reads. The share-trade bar read no longer fetches strategy underlyings. The route is unchanged.
3. `services/paper_account.reserve` is now one conditional `update_one`: the filter is `{"user_id", "$expr": {"$gte": [{"$subtract": ["$cash_rs", "$blocked_rs"]}, amount]}}`, with `$inc` in the same write. On a miss it re-reads and raises InsufficientFunds with the current numbers. `ensure()` and the ledger are unchanged.
4. In `tests/test_desk_paper_sim.py`, the two tests were renamed and updated to the fill-at-the-open rule. The `services/desk_trading.py` docstring was fixed at three places (stop gap, entry gap, exit rule).
5. New files `deploy/nivesh-staging/fno-forward.cron` and `install-fno-forward.sh`: `45 22 * * 1-5` IST, after the 22:15 fno_bhavcopy retry.

Operator install, on the staging app VM after this is merged and `/opt/nivesh-staging/repo` is pulled:
```
sudo bash /opt/nivesh-staging/repo/deploy/nivesh-staging/install-fno-forward.sh
sudo bash /opt/nivesh-staging/repo/deploy/nivesh-staging/install-desk-alerts.sh    # NOT installed today (see below)
/usr/bin/docker exec nivesh-staging-app-backend python -m scripts.record_fno_forward --dry-run
/usr/bin/docker exec nivesh-staging-app-backend python -m scripts.check_desk_alerts --dry-run
```
Before running the dry runs, restart the backend process so it loads the new code (the bind-mounted code is not loaded until then).

UNVERIFIED:
- Nothing has been run against staging Mongo or the data platform.
- `/etc/cron.d` on this host (the one running `nivesh-staging-app-backend`) has no `nivesh-staging-desk-alerts` entry. The evening check therefore runs for neither cash nor F&O trades today, and fix 2 does nothing until that installer is run.
- `paper_accounts` has no unique index on `user_id`. Two first-ever trades racing in `ensure()` can create two account rows. This race existed before this branch and is not changed here.
