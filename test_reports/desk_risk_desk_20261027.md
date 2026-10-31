# Functionality Verification Report — Risk Desk tab (desk redesign step 4)

- **Branch:** feat/desk-risk-desk (from feat/desk-redesign-shell, PR #369)
- **Date:** 2026-10-27
- **Author:** Claude (Design Engineer + Full Stack Developer, frontend; QA)
- **Environment:** offline (production build, every `/api/*` MOCKED) + read-only GETs against staging for the route shapes
- **Changed areas:** backend routes/services: no · frontend src: yes

## Summary
Tab 04 Risk Desk (`?tab=risk&view=limits|controls|log`), paper risk only, in
`frontend-v5/src/pages/CopilotApp/screens/tradingdesk/tabs/risk-desk/`. Limits & budgets (eight profile limits with
used / left, open risk reserved at entry, positions n of 10, BEAR / VIX factor and input freshness, F&O structure caps,
correlation note, My portfolio footnote); Controls & profile (kill switch and halt as the backend does them, control
changes, the risk profile and its change form, live trading not available with readiness rows); Decision log (allow /
reduce / block with reasons, size, estimate, budgets, versions; lineage and replay). An admin-only job-health strip.
No slider; no Policy & runtime view; no autonomous-agents panel. Reuses RiskControls (its parts exported, DecisionItem
given a children slot, outcomeOf learns "reduced"), risk-profile.ts (reads `reserved_risk_rs` / `legacy_risk_rs`),
fnolab/governance-data.ts (AuditDecision gains the risk service's fields) and fnolab/Audit.tsx `Lineage`.

## Test Cases
Authored up front: `test_reports/desk_risk_desk_TESTCASES.md` (RD-1 … RD-19). All PASS on mocked APIs (run below).

| ID | Result |
|----|--------|
| RD-1 / RD-17 views, one h1, paper-only wording, no Policy & runtime | PASS |
| RD-2 / RD-3 / RD-4 eight limits used/left, reserved, positions n of 10, KPIs, headline | PASS |
| RD-5 regime factor (BEAR ×0.5; BEAR + VIX 27 ×0.25; BULL; VIX 36 deferred; unknown) | PASS (5 tests) |
| RD-6 input freshness, newest share decision, typed symbol re-read | PASS |
| RD-7 correlation note, footnote, My portfolio link | PASS |
| RD-8 unknown live figures read unknown, never ₹0 | PASS |
| RD-9 kill switch: rule, reason, one PUT, admin-only off, audit row | PASS |
| RD-10 profile form: rule, reason required, tightening PUT, log | PASS |
| RD-11 live trading not available, readiness rows | PASS |
| RD-12 no slider | PASS |
| RD-13 / RD-14 decision log rows, budgets, lineage, replay (one POST) | PASS |
| RD-15 / RD-15b empty log; failing read | PASS |
| RD-16 / RD-16b admin strip; none for a non-admin, admin routes not called | PASS |
| RD-18 phone 390 px, no sideways scroll | PASS |
| RD-19 reading writes nothing | PASS |

## UI / Playwright Tests (mocked APIs, production build)
- Command: `PWEXTRA=--workers=2 run-fe.sh /home/deploy/nivesh-desk-risk run3.txt copilot-app-desk-risk-desk copilot-app-desk-risk-controls copilot-app-desk-risk-phase1 copilot-app-fnolab-governance copilot-app-desk-shell copilot-app-desk-decision-cards`
- Output (real, unedited head and tail):
```
== tsc
tsc: clean
== build
✓ built in 40.28s
== playwright
...
  1 skipped
  125 passed (3.2m)
exit 0
```
- Per spec (counted from the same output): risk-desk 21 passed · risk-controls 16 passed, 1 skipped (RC-1, skipped by
  the shell: the More menu is gone) · risk-phase1 10 · fnolab-governance 14 · desk-shell 35 · decision-cards 29. 0 failed.
- The Risk Desk lines (real):
```
✓   47 … copilot-app-desk-risk-desk.spec.ts:261:3 › … RD-1 / RD-17 three views from the switcher and the URL …
✓   48 … :280:3 › … RD-2 / RD-3 / RD-4 the eight limits with used and left …
✓   49 … :333:3 › … RD-5 the regime factor: BEAR halves the size limits; …
✓   50 … :347:5 › … RD-5 regime BEAR and VIX 27 (1.5s)
✓   51 … :347:5 › … RD-5 regime BULL (2.5s)
✓   52 … :347:5 › … RD-5 regime VIX 36 (2.8s)
✓   53 … :347:5 › … RD-5 regime unknown (2.3s)
✓   54 … :355:3 › … RD-6 input freshness: market state, and last close an…
✓   55 … :380:3 › … RD-7 the correlation note and the paper-only footnote
✓   56 … :389:3 › … RD-8 unreadable live figures read unknown, never ₹0
✓   57 … :404:3 › … RD-9 kill switch: the rule, on with a reason, one PUT
✓   58 … :433:3 › … RD-10 the profile form: the rule; no PUT without a re…
✓   59 … :456:3 › … RD-11 Live trading: not available, with each readines…
✓   61 … :477:3 › … RD-13 / RD-14 the log: allow / reduce / block newest …
✓   60 … :468:3 › … RD-12 no risk slider anywhere on the Risk Desk (3.3s)
✓   62 … :515:3 › … RD-15 no decisions is said (1.6s)
✓   63 … :522:3 › … RD-15b a failing decisions read shows an error with R…
✓   64 … :530:3 › … RD-16 an admin sees the job-health strip on every vie…
✓   65 … :546:3 › … RD-16b a non-admin sees no job-health strip, and the …
✓   66 … :556:3 › … RD-19 reading every view writes nothing (4.1s)
✓   67 … :571:3 › Risk Desk · phone 390px › RD-18 no sideways scroll on any view, with long reasons and an …
```
- An earlier run at 4 workers (load average 37 on 4 CPUs from other sessions' containers) had 30 s `page.goto` timeouts
  in the shell and decision-cards loops; every one of them passed in the run above. That run also showed the old
  risk-controls assertions that named the old layout (audit on Decision log, "reduced" as given); they now follow the
  screens (audit on Controls & profile, "Reduced").

## Data Correctness (staging, read-only GETs with the owner's session; token passed on stdin, not printed)
- `GET /api/risk/freshness` → HTTP 200: `market_state` `status ok`, `regime "BEAR"`, `vix 17.16`, `as_of "2026-10-26"`,
  `age_sessions 0`; `last_close` / `sector` `not_checked` without `?symbol=`. The screen would read
  "BEAR regime (as of 26 Oct): size limits ×0.5."
- `GET /api/risk/freshness?symbol=INFY` → HTTP 200: last close `1166.0` as of 2026-10-26 `ok`; sector
  "Information Technology" (as of 2026-10-22, undated budget) `ok`.
- `GET /api/admin/risk/jobs/check_desk_alerts` → HTTP 200 `state "never_run"`, "No run of this job has been recorded."
- `GET /api/admin/risk/jobs/positional_engine` → HTTP 200 `state "ok"`, last success 2026-10-26T21:43:20Z.
- `GET /api/risk/decisions?limit=200` → HTTP 200, 18 rows: 16 blocked, 1 reduced, 1 allowed; 13 older rows carry no
  instrument, budget or estimate (the log says "not sized" / "No budgets were recorded"). 3 rows carry
  `budget.max_open_positions`.
- `GET /api/risk/profile` → HTTP 200: the owner defaults (0.5 · 3 · 10 · 25 · 2 · 4 · 10 · 1.5),
  `live.open.risk_rs` = `reserved_risk_rs` (5 reserved positions, no legacy).

## Verdict
Mocked e2e: PASS. Staging: the route shapes the tab reads were checked read-only (above), but the tab itself is NOT
deployed, so its rendering on staging is UNVERIFIED. See `test_reports/OVERRIDE_desk_risk_desk.md`.
