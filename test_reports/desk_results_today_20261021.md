# Desk "Results today & tomorrow" board — functionality report

- **Branch:** feat/desk-results-today (local, not pushed)
- **Date:** 2026-10-21
- **Scope of this report:** code, unit tests, mocked-UI Playwright, and a read-only real-data run. NOT yet verified on staging (not deployed). Staging HTTP and live-UI checks follow after merge.

## Test cases
See `desk_results_today_TESTCASES.md` (TC-1..TC-25).

## Results
| Cases | Evidence | Result |
|---|---|---|
| TC-1..TC-14 backend + app route | pytest in `nivesh/backend:staging`, desk expectation/events/macro + route tests: `198 passed, 1 warning in 8.36s` | PASS |
| TC-17..TC-25 UI (mocked, labelled `// MOCK — not real data`) | `copilot-app-desk-results-today.spec.ts`: 7 passed; whole desk run (events, macro, expectation, results-today, desk): `66 passed (1.1m)` | PASS |
| Typecheck | `tsc --noEmit -p tsconfig.json` printed nothing (exit clean) | PASS |
| TC-15/16 real data (read-only export of the staging warehouse, handler run offline, today = 2026-10-21) | F&O: 13 events (6 today, 7 tomorrow): declared_figures 0, declared_pending 5, upcoming 8. All NSE: 60 events, 0 with figures. First call 409 ms, cached 3–17 ms, F&O payload ~25 KB | recorded |

## Finding: actuals availability (TC-16)
Stored quarterly figures reach the warehouse from Screener/Trendlyne about a day after the filing. On the day, most companies that have filed show **"filed, figures pending"**, not a number. The board says so and links the filing; it never shows a figure it does not hold. Same-day actuals would need a new source for the filed numbers (e.g. parsing the exchange's result XBRL), which was not part of this change.

## Side fix
`copilot-app-desk-expectation.spec.ts` route glob `expectation*` also matched the new `expectations` route; narrowed to `expectation?*`.

## UNVERIFIED
- Staging deploy and live UI with real data (needs merge, then session-token run).
- Phone layout checked only at 390 px in the mocked build.

## Verdict: PASS
(For the code/mocked scope above; staging verification is pending and will be reported separately.)
