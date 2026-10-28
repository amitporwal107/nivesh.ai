# OVERRIDE — Strategy Copilot Phase 0 (PRs #390, #391, #392): staging API verification deferred

REASON: The three backend fixes (run access 404, FAILED runs, one 4-leg limit) are verified by unit and regression tests only. The combined tree passes 1921 tests in the staging backend image, with no existing test edited (`test_reports/strategy_phase0_runs_20261028_0528.md`). They are NOT verified on staging. Staging runs `dev`, and these PRs are open, not merged; I may not merge them without the owner's per-PR approval. The cross-user check (TC-18) also needs two signed-in staging users, and I have no session tokens. To finish:
1. ~~The owner merges #390, #391 and #392.~~ **DONE 07:10 IST** (owner: "Please merge the PR's"): dev 3a94da9b. The deploy succeeded at 07:11:52, and the running backend has the code (see the report).
2. ~~TC-19 and the owner-side TC-18 checks.~~ **DONE 07:18 IST** with the owner's session: FAILED run c92d2f56 stored with its reason; own read 200; malformed id 404; `/api/risk/policy` `max_legs: 4`.
3. **REMAINING (only this):** a second staging user (a session token, or the owner's permission to create a disposable test user) runs `GET /api/strategy-builder/runs/c92d2f56-2cd7-4113-af13-be35b9718f17` and gets 404 "run not found", and an `audit_log` row `strategy_run_view` / `denied` appears. The unit tests TC-2/TC-4/TC-5 already cover this logic.
4. Paste the real output into the report and set its verdict to PASS. Then delete this file.

Owner-visible: yes. This file is the record of the debt.
Date: 2026-10-28 06:15 IST. Session 3d5d2da4.
