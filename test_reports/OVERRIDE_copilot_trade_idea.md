# OVERRIDE — Copilot trade idea card (feat/copilot-trade-idea): staging verification deferred

REASON: the live staging check (TI-19) cannot run before this PR is merged and deployed. That check is a real trading
question on staging with a session, then the stored TradePlans read back from Mongo `trade_plans`. Everything else passes
on the test bench:
- TI-1 … TI-18: 35 backend tests; 5 Playwright cases; tsc clean;
- backend regression 6912 → 6947 passed, with the same 3 failures `dev` already has;
- 189 frontend cases passed, 0 failed.
See `test_reports/copilot_trade_idea_20261029.md`.

To finish:
1. The owner merges the PR (per-PR approval). This change touches no migration.
2. Confirm the backend restarted with the code, and the frontend bundle has `Trade idea`.
3. With a session token: ask "Plan a breakout trade for <an F&O stock>" on /v5/app (Trader mode) and in the desk's
   Copilot panel. Check the card, its plan ids and `trade_plans` in Mongo.
4. Paste the output into the report, set the verdict to PASS and delete this file.

Owner-visible: yes. Date: 2026-10-29. Session 3d5d2da4.
