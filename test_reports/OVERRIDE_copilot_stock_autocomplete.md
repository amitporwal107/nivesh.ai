# OVERRIDE — Copilot stock autocomplete (feat/copilot-stock-autocomplete): staging check after merge

REASON: SC-18 (the deployed route on staging) can only run after the merge and deploy. Everything else passes:
- SC-1 … SC-17: 25 backend tests; the new code run against the REAL staging symbol master; 5 Playwright cases; tsc clean;
- backend regression 6972 passed, with the same 3 failures `dev` already has;
- frontend regression 118 passed, 0 failed.
See `test_reports/copilot_stock_autocomplete_20261029.md`.

To finish after the merge: confirm the backend restarted, then `curl` the deployed
`/api/chat/instrument-search?q=…&tail=1` for the SC-1 … SC-10 cases (the route needs no session) and check the served
bundle has "Tab to complete". Then paste the output, set the verdict to PASS and delete this file.
Owner-visible: yes. Date: 2026-10-29. Session 3d5d2da4.
