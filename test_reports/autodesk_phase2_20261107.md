# Functionality Verification Report — Phase 2 risk-to-paper execution (continued by Account 2)

- **Branch:** feat/autodesk-phase2-paper-exec-a2 (from origin/feat/autodesk-phase2-paper-exec, plus origin/dev merged at e9800d58)
- **Date:** 2026-11-07
- **Author:** Claude Sonnet 5.5 (Account 2), continuing Account 1's work after its usage limit was reached
- **Environment:** throwaway Postgres + test doubles for the tests; NOT deployed; no shared database written
- **Changed areas:** backend routes/services: yes (execution/*, routers/execution.py, orchestrator, simulator, control/book, main, config) · frontend src: yes (4 small result-label mappings)

## Summary
Account 1's uncommitted work (migration 003, capital ledger and reservation, fill model, adapters, orders, positions, journal, session-bar and live-quote sources, design and test cases) was copied read-only into this branch and checked: its modules ran correctly under 12 new capital tests. Written here: the **gateway** (intent first, controls, atomic reservation, orders, submit/withdraw), **settlement** (fills → ledger, reservation conversion, positions, journal, events; simulation OPEN/CLOSE; live tick; expiry; marks; snapshots), **reports** (capital view, P&L, execution summary, determinism fingerprint), the **live loop**, wiring into the orchestrator / simulator / `main.py`, the **risk book from the ledger**, the **read APIs + withdraw route**, and 89 new tests. With no gateway wired, behaviour is exactly Phase 1 (AD-P2-69).
**IN PROGRESS, not COMPLETE:** the real-data replay (AD-P2-95..97) and the real Kite quote (AD-P2-98) were not run (see UNVERIFIED).

## Test Cases (docs/autodesk/TESTCASES.md "Phase 2", AD-P2-01..98)
| Group | IDs | Evidence | Result |
|---|---|---|---|
| Ledger, reservation | 01, 02, 03–06, 10–14 | test_p2_capital.py (12), test_p2_gateway.py, test_p2_products.py, test_p2_misc.py | PASS |
| Intents and controls | 20–31 | test_p2_gateway.py, test_p2_controls.py (each refusal code, idempotency, 5 concurrent calls, stale version/hash, scope, mode, policy, STOP_NEW_ENTRIES at intent and between intent and submission, duplicate) | PASS |
| Order states | 32–35 | test_p2_fill_model.py (state machine), test_p2_gateway.py (history), test_p2_misc.py (adapter failure → UNKNOWN, withdraw, amend refused) | PASS |
| Fill model, costs | 40–49 | test_p2_fill_model.py (17) | PASS |
| Baskets | 50–52 | test_p2_products.py | PASS |
| Simulation | 60–69 | test_p2_simulation.py (phase by phase, two sessions, marks, drawdown, same seed same fingerprint, other seed differs, no look-ahead, isolation, person approves, no gateway) | PASS |
| Live desk | 70–79 | test_p2_live.py, test_p2_controls.py, test_p2_misc.py (FakeQuotes / fake Kite: TEST DOUBLES) | PASS |
| APIs | 80–84, 92 | test_p2_api.py (5) + the existing API and UI-contract suites unchanged | PASS |
| Safety, wording | 90, 91 | test_p2_misc.py; test_safety.py (AD-91 caught `cancel_order` in a new function name; renamed) | PASS |
| Real data | 95, 96, 97, 98 | script `backend/scripts/autodesk_phase2_run.py` written and compiled; **not run** | **UNVERIFIED** |

## API / Endpoint Tests
- `sudo -n bash backend/scripts/run_autodesk_tests.sh /home/deploy/nivesh-wt-account2 tests/autodesk tests/test_order_path_guard.py -p no:warnings`
  - Output: `255 passed in 55.97s` (166 existing + 89 new)
- `python3 -m py_compile` on all changed backend files: `compiled`
- Result: PASS (on a throwaway Postgres and test doubles; not staging)

## UI / Playwright Tests
- `tsc --noEmit && vite build && npx playwright test --config pw.autodesk.config.ts` (package 5 brief command)
  - Output: `159 passed`, `1 failed`: `autodesk-policies.spec.ts › AD-UI-74` (a dialog still present after save). A re-run of that spec with `--repeat-each=3` gave `1 failed, 41 passed`, so it is **flaky**; it was passing in the earlier full runs, the spec and the screen are not touched by this work, and I did not find the cause.
  - The only frontend change: the four places that label a workflow result now also map `APPROVED` (the result when execution is wired) beside `APPROVED_NO_EXECUTION`.
- Result: FAIL on one flaky pre-existing spec (see above); no spec for the new `APPROVED` labels was added.

## Data Correctness
Not run against real data. What was checked on test data: equity = cash + position value, difference 0.00 (AD-P2-06, 62, 66); balances are sums over an append-only ledger; reservation arithmetic (10 concurrent reservations → exactly 6 succeed). **Real-data evidence is missing** (below).

## Defaults used for pending decisions (DESIGN §10)
Strategies: long equity, long futures, long call/put, debit and credit spreads, iron condor; no short futures · AUTONOMOUS_PAPER auto-approves ≤ 0.5 % risk with score ≥ 70 · default risk limits · margin utilisation 25 % · futures margin estimate 15 % (not SPAN).

## Deviations from PHASE2_DESIGN.md and things to know
- `live_tick`/`mark_live` can be scoped to one tenant (used by the tests); production runs unscoped.
- A reservation's per-leg risk/commitment shares are capped at what the reservation still holds (rounding of four legs gave 12,000.01 once).
- Studio Run history columns (Trades / Net P&L / Max DD) are still the Phase 1 placeholders in the UI; the API now supplies them in `results.execution_summary` (the screens package should wire them).
- The simulation `/results` `execution` field stays a string; new figures are in `execution_summary`.

## Inputs required from user
The real-data replay needs the staging DaaS credentials passed to a throwaway container (`docker inspect` of the staging backend, never printed). The auto-mode safety check refused that command; it needs the owner's explicit go-ahead (or the owner running it). Real read-only Kite quote (AD-P2-98): needs the day's admin Kite login; not attempted.

## UNVERIFIED
AD-P2-95/96/97 (2–3 session replay with the real agents and the data API: fills against re-read exchange rows, same seed twice) · AD-P2-98 (one real read-only quote) · not deployed; the live loop has only run with fake quotes · the flaky AD-UI-74.

## Verdict: BLOCKED
