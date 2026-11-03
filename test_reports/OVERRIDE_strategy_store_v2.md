# OVERRIDE — Strategy Copilot Phase 1.1 (shared strategy store v2): staging verification deferred

REASON: This branch passes on the test bench, but staging is not verified yet:
- 34 of 35 test cases pass, including 19 route cases against a real PostgreSQL 16;
- the full CI allowlist shows 6911 passed with the same 3 failures `dev` already has.

See `test_reports/strategy_store_v2_20261028.md` for the evidence. The staging case (TC-35) cannot run yet:
1. Staging runs `dev`, and this PR is not merged. I may not merge without the owner's approval of this PR.
2. A merge does not apply `backend/migrations/026_strategy_store_v2.sql`. The owner must run the backend deploy workflow
   with `run_migrations=true`. Until then the new routes correctly answer 503 `store_not_migrated`.
3. The checks need a staging session token. The cross-user 404 cases also need a second staging user: the session's
   attempt to create a temporary user was refused by the permission check.

To finish:
1. Merge → migrate → confirm the backend restarted with the code.
2. Run TC-35 with a token: create, version, stale parent, clone, `include=summary`, `strategy_ref` on a paper trade.
   Check the rows in `portfolio_ingestion`.
3. Paste the output into the report, set the verdict to PASS, delete this file.

Owner-visible: yes. Date: 2026-10-28. Session 3d5d2da4.
