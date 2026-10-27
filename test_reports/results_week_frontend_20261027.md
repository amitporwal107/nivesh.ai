# Results week (Earnings Surprise & Guidance Tracker P1) — frontend functionality report

- **When:** 2026-10-27 19:33 IST · **Branch:** feat/earnings-tracker-ui · **Backend it pairs with:** PR #371 (feat/earnings-surprise-tracker)
- **Spec:** docs/EARNINGS_SURPRISE_TRACKER.md §6 (screens), §8 (test cases TC-F1..F6, authored before implementation), plus TC-F7 (coming-months F&O drawer) and RS-1..RS-6 (results chip in the AI scanner), and a contract test against the real backend response.

## Test cases
| TC | What | Result |
|---|---|---|
| TC-F1 | Events › Results week: basis label (vs historical trend, not consensus) and counts; macro and market strip from the desk's own reads | PASS |
| TC-F2 | Declared rows: verdict pill, PAT surprise, reaction; pending row says figures not filed yet; drawer | PASS |
| TC-F3 | Upcoming rows: expected range or "no reliable baseline"; past reactions, OI, stage | PASS |
| TC-F4 | Scanner › Results week ideas beside the Top 10: F&O / All toggle, rows, "not yet tested" note | PASS |
| TC-F5 | Loading, empty and error states (basis label stays) | PASS |
| TC-F6 | 390 px: no horizontal page scroll (view, drawer, ideas) | PASS |
| TC-F7 | Drawer › F&O coming months: near/next/far, rollover and premium vs own ranges, option-chain line, null parts said | PASS |
| RS-1..RS-6 | AI scanner chip: strong/weak chip with points and reasons; Top 10 and Overview order by final score; older backend without results_signal shows no chip | PASS |
| CONTRACT-1 | Events › Results week renders the REAL 27 Oct backend body (built read-only on staging from PR #371's branch; fixture e2e/fixtures/results_week_staging_20261027.json, trimmed): basis, counts (declared 35), both "above" rows (APLAPOLLO, SUPREMEIND), a pending note, an upcoming row, a drawer; no banned phrases; no uncaught page errors | PASS |
| CONTRACT-2 | Scanner › Results week ideas renders the REAL ideas (F&O #1 COFORGE, All #1 APOLLO), toggle, note; no page errors | PASS |
| Regression | Neighbouring desk specs: desk shell, events, expectation, results-today, scanner, top10, decision cards, macro, market | PASS |

## Real output (production build served by vite preview, base /v5/; every /api/* route-mocked or the real fixture; offline container)
```
✓ built in 39.02s
✓  102 [copilot-app] › e2e/tests/copilot-app-desk-results-signal.spec.ts:79:3 › AI scanner — results chip › RS-1/2/3 scanner list: strong ch
✓  103 [copilot-app] › e2e/tests/copilot-app-desk-results-signal.spec.ts:110:3 › AI scanner — results chip › RS-4 Top 10 stock ideas: the ro
✓  104 [copilot-app] › e2e/tests/copilot-app-desk-results-signal.spec.ts:130:3 › AI scanner — results chip › RS-5 Overview › Top AI opport
✓  105 [copilot-app] › e2e/tests/copilot-app-desk-results-signal.spec.ts:145:3 › AI scanner — results chip › RS-6 an older backend without r
✓  253 [copilot-app] › e2e/tests/copilot-app-results-week-contract.spec.ts:44:3 › Results week — real 27 Oct response (desktop 1440) › Event
✓  254 [copilot-app] › e2e/tests/copilot-app-results-week-contract.spec.ts:68:3 › Results week — real 27 Oct response (desktop 1440) › Scann
✓  255 [copilot-app] › e2e/tests/copilot-app-results-week.spec.ts:199:3 › Results week — Events view (desktop 1440) › TC-F1 basis label and 
✓  256 [copilot-app] › e2e/tests/copilot-app-results-week.spec.ts:229:3 › Results week — Events view (desktop 1440) › TC-F2 declared rows: v
✓  258 [copilot-app] › e2e/tests/copilot-app-results-week.spec.ts:328:3 › Results week — Events view (desktop 1440) › TC-F3 upcoming rows: e
✓  257 [copilot-app] › e2e/tests/copilot-app-results-week.spec.ts:295:3 › Results week — Events view (desktop 1440) › TC-F7 drawer › F&O: 
✓  260 [copilot-app] › e2e/tests/copilot-app-results-week.spec.ts:396:3 › Results week — Scanner ideas (desktop 1440) › TC-F4 Results week i
✓  261 [copilot-app] › e2e/tests/copilot-app-results-week.spec.ts:433:3 › Results week — phone 390 › TC-F6 no horizontal page scroll: Events
✓  259 [copilot-app] › e2e/tests/copilot-app-results-week.spec.ts:357:3 › Results week — Events view (desktop 1440) › TC-F5 loading, empty a
  ✓  251 [copilot-app] › e2e/tests/copilot-app-desk.spec.ts:949:3 › Smart trading desk — phone M1 Overview · design fidelity › M1: no holdings and a failed risk read show “—” with the reason, never 0 (5.6s)
  2 skipped
  261 passed (9.3m)
```
The 2 skipped are the screenshot-only cases (they run when RW_SHOTS names a directory). Typecheck of the app code (run at ~19:05 IST, before the contract spec was added; the specs themselves are compiled by Playwright, which ran them): `tsc: OK (no errors)`.
Screenshots (agent run, mock data, 1440 and 390): test_reports/screens_results_week_20261027/ — checked by eye: layout matches the desk.

## UNVERIFIED
- The real staging smoke (the deployed screen calling the deployed GET /api/desk/results-week) needs PR #371 and this PR merged and deployed.
- The response is ~1.6–1.8 MB uncompressed (the frontend nginx gzips JSON); load time in the browser on staging not measured.


## Addendum (22:10 IST): merged origin/dev (desk shell redesign #369) into this branch
- Conflict in ScannerTab.tsx resolved by keeping dev's `listOnly` (Market Overview hosts the list); the Results week ideas
  block now also sits right after the Top 10 on **Market Overview** (TradingDesk.tsx `Hosted id="results-week-ideas"`). The
  Results week view stays in the Events tab, which the shell hosts under Market Desk › Market Intelligence. Old
  `?tab=events` / `?tab=scanner` links redirect there.
- RS-1/2/3 now expects the shell's canonical place after the redirect (`tab=overview&section=scanner`).
- Full run after the merge (typecheck + 29 desk/results spec files): `tsc: OK (no errors)`; `668 passed, 33 failed, 31 skipped (18.8m)`.
  32 failures are `copilot-app-desk-strategy-graphs.spec.ts`, which by its own header fails under the standard build by design
  (needs VITE_STRATEGY_HARNESS=1 via e2e/fe-run-stgraph.sh); 1 was RS-1/2/3 (the URL above), fixed. Rerun of the results specs:
```
✓ built in 24.94s
  2 skipped
  13 passed (21.5s)
```


## Addendum (22:21 IST): the ideas badge follows the backend's `tested` flag (study PR #374)
"NO MEASURABLE SKILL SO FAR" when `ideas.tested` is true (the backend's note carries the result), "NOT YET TESTED" otherwise
(older backend). New case TC-F4b. Run (results specs, results chip, Top 10, desk shell):
```
tsc: OK (no errors)
✓ built in 37.06s
  10 skipped
  61 passed (2.3m)
```

## Verdict: PASS
