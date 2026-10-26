# OVERRIDE — Evening exit job hardening + paper-account reconciliation

REASON: This fix group may not write to staging (no deploy, restart, cron install, `--apply`, test position or flag), so the new admin route `GET /api/admin/risk/jobs/check_desk_alerts` has no staging endpoint evidence, the job has never run non-dry on staging, and the reconciliation has only been dry-run there. To finish: the owner approves the approval pack; merge and deploy the branch; take the snapshot; run `reconcile_paper_accounts --apply` with the chosen decisions and validate with `--check` (exit 0); create the staging-only test position, install the cron, confirm the job closes the position once and writes its heartbeat, and curl the admin route; then record the outputs in `test_reports/paper_exit_job_reconcile_20261027.md`.

- **Date:** 2026-10-27
- **Verified:** 390 unit tests pass (40 new); 12 mutants checked (all killed after one added test); read-only staging dry runs of both tools with before/after counts unchanged and zero write attempts.
- **Verified on a throwaway local Mongo 7 (not staging):** concurrent applies move each entry once, apply-twice and revert-twice are no-ops, revert restores the account, 20 concurrent lease acquires give one winner.
- **Not verified:** the route on staging; the job's full run against real Mongo with real concurrency (two `run_job` processes); the cron line under real cron; `flock` on the staging host under real contention; any staging write.
- **This is not a pass.** Resolve before merge to `main`.
