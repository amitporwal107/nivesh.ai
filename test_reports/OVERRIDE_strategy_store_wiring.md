# OVERRIDE — Strategy Lab wizard ⇄ shared strategy store (frontend wiring): staging verification deferred

REASON: The wiring is verified in mocked Playwright on a production build, but not live:
- the wizard spec shows 29 passed (WZ-13 rewritten, WZ-20 … WZ-25 new);
- `tsc --noEmit` shows 0 errors;
- the desk + builder regression run is in progress (`test_reports/strategy_store_wiring_20261028.md`).

It cannot be checked live on staging yet, because the routes it calls are PR #398:
1. #398 must be merged and its migration 026 run (deploy workflow `run_migrations=true`).
2. Then this PR must be merged and the frontend image rebuilt. Each merge needs the owner's approval.
3. The live check (save, version, clone, open on staging, with rows read from `strategy_versions`) needs a session token.

Until then the deployed wizard answers "Saving is not available on this server yet", which is safe by design (WZ-23).

To finish: run the live check, paste its output into the report, set the verdict to PASS and delete this file.
Owner-visible: yes. Date: 2026-10-28. Session 3d5d2da4.
