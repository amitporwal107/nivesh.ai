# OVERRIDE — Risk Control Center (Desk › More › Risk controls), PR D

REASON: staging render needs the backend PR (feat/fno-risk-foundation) merged and deployed plus a user session; local tsc/Playwright: tsc --noEmit exit 0; new spec copilot-app-desk-risk-controls 17 passed; with the affected desk specs (lab, scanner incl. the new 409 risk_blocked test, portfolio-fno, strategy-builder, desk, chartink, chartink-picks, events) 326 passed, 16 skipped, 0 failed; untouched origin/dev baseline of lab+scanner+portfolio-fno+strategy-builder+desk 255 passed, 16 skipped, 0 failed (now 256 = +1 new test).

- **Branch:** feat/risk-control-center (from origin/dev b74c7f4f). Frontend only.
- **Test cases:** test_reports/risk_control_center_TESTCASES.md (written before the code).
- **What ran (2026-10-24/25, docker `mcr.microsoft.com/playwright:v1.47.0-jammy`, Chromium build 1223, production build
  on vite preview :5174, `--network none`, every /api mocked — MOCK, not real data):**
  ```
  npx tsc --noEmit -p tsconfig.json          -> tsc exit 0
  vite build                                 -> build exit 0
  playwright: risk-controls lab scanner portfolio-fno strategy-builder desk.spec chartink events
    Running 342 tests using 3 workers
    16 skipped
    326 passed (5.2m)
    per spec: risk-controls 17, lab 95 (+2 skipped), scanner 81, portfolio-fno 35, strategy-builder 26 (+14 skipped,
    screenshot cases), desk 19, chartink 24, chartink-picks 20, events 9
  baseline (untouched origin/dev copy): lab scanner portfolio-fno strategy-builder desk.spec
    16 skipped
    255 passed (3.2m)
  ```

## UNVERIFIED (needs the backend and a session)
- The real `/api/risk/status|policy|audit|decisions` and `PUT /api/risk/kill-switch|halt` answers on staging: field
  names and units are taken from the contract in the PR D brief and backend/routes/risk_controls.py; `/policy`,
  `can_reset`, `live_authorization`, `modes`, `gate` and the 403 `admin_required` come from the parallel backend PR and
  were not exercised against a real server.
- The current route renames a decision's `_id` to `event_id`; the reader accepts both.
- The 409 risk_blocked wording was checked on the Chart tab's "Add to paper trades" only; other paper actions share
  `writeProblem`, so they get the same text, but were not each re-run with a 409.
- Data test (CONTEXT.md §1): not possible until the backend is deployed. Then: trip the switch on staging with a test
  account and read the stored row and the appended `risk_control_audit` event back.
