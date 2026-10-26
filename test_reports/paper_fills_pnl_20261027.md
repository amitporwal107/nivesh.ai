# Functionality Verification Report — Paper fills, P&L from the simulated fill, entry rules per setup, costs in sizing

- **Branch:** fix/paper-fills-pnl (stacked on fix/desk-paper-safety @ aaca6cb1)
- **Date:** 2026-10-27
- **Author:** Claude (full-stack developer + QA)
- **Environment:** local containers (`nivesh/backend:staging` image, `--network none`, worktree read-only; Playwright 1.47 Chromium against a production build with a mocked API). Staging was read only; nothing was deployed or written.
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary
Phase 0 items 0.2 and 0.3, plus costs in sizing (part of 1.3). Release gates 3 and 4; criteria group 0.2.
1. **P&L from the simulated fill.** `close_trade` books gross P&L and costs from `sim_entry_price`, as open-trade
   P&L already did. A gapped break-above now books ₹600, not ₹1,000, and the paper account is credited that net. An
   older closed record without stored costs is priced at its stored fill. Strategy trades were checked: they have no
   separate fill, and open and closed P&L both use the recorded leg prices, so nothing changed there.
2. **A documented fill model.** It is the "FILL MODEL" block in `backend/services/desk_trading.py`. It covers entry
   per rule, gap-through entry and stop (fill at the open), the target jump (fill at the target, conservative), stop
   and target in one bar (the stop), and partial fills and exits (not modelled). It also covers missing bars (the
   trade waits), an entry never reached (no fill, no P&L) and unavailable prices (refused, no invented fill). Every
   rule is pinned by a test.
3. **No impossible fills.** The server refuses `at_once` when the entry lies outside the last completed session's
   low–high range (422 `entry_not_tradable`, naming the session and the range). With no bar the answer is 422
   `entry_unverifiable`; with unreadable prices, 503 `prices_unavailable`. Top 10, AI watchlist and Scanner now send
   an `entry_rule` from one helper (`entryRuleFor`): an entry above the scan's close → `break_above`, below →
   `pullback_to`, at the close → `at_once`. With no close, the setup decides. Each screen says how the entry fills.
   FEDERALBNK (316.89 against a range of 337.20–344.80) is refused as `at_once` and sent as `pullback_to`.
4. **Costs consistent (gate 4).** One cost function (`cost_terms`, `round_trip_cost`, `max_units_within_budget` in
   `services/desk_trading.py`) prices the realised costs, each trade's cost estimate, the plan's sizing
   (`size_position` via `linear_candidate`), the desk scenario (`_trade_scenario`) and the basket (`_size_position`).
   Sizing keeps the loss at the stop after costs within the budget: PRD Example A gives 82 shares, not 85, with
   ₹2,990.975 after costs against ₹3,000. The basket no longer forces one share past its risk cap. The cost model
   snapshot is versioned (`desk-flat-v1`) and lists what it excludes. Every cost/risk figure says whether costs are
   in it: `costs_basis`, the plan's `risk_basis` and its net-of-cost line in the Builder, the basket's
   "after costs" label. Strategy rules were bumped to `strategy-rules.v1.6`.

## Test Cases
Authored up front in `test_reports/paper_fills_pnl_TESTCASES.md`.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| FM-1 | fill | at_once inside the last range | api | 201, fill = entry, range stored | PASS |
| FM-2 | fill | FEDERALBNK at_once 316.89 vs 337.20–344.80; one paisa outside; a later bar ignored | api | 422 with session and range; recorded | PASS (base: 201) |
| FM-3/FM-4 | fill | no bar / prices unreadable | edge/failure | 422 entry_unverifiable / 503; nothing written | PASS |
| FM-5..FM-11, FM-13 | fill | break_above, gap entry, pullback, gap-down entry, stop, gap-through stop, target, target jump, both in one bar, time, not reached, missing high/low | unit | as the doc (12 cases) | PASS |
| FM-12 | fill | partial exit | api | 422 unknown_field on a close with a quantity | PASS |
| FM-14 | fill | FEDERALBNK as pullback_to | api | waiting, never filled at 316.89 by those bars | PASS |
| P-1/P-2 | P&L | probe B2 through the API and the service | api/unit | ₹600 gross, ₹50.70 costs, ₹549.30 net; account +549.30; open and closed agree | PASS (base: ₹1,000 / ₹50.50 / ₹949.50) |
| P-3 | P&L | older record without costs | unit | priced at its stored fill | PASS |
| P-4 | P&L | strategy trades | unit | open and closed P&L both from the leg prices | PASS |
| P-5 | P&L | gap-through-stop P&L | api | (open − fill) × qty − costs | PASS |
| C-1 | costs | Example A, plan sizing | unit | 82 shares; ₹2,990.975 ≤ ₹3,000; costs_included | PASS (85 on the gross distance; ₹3,098.94) |
| C-2 | costs | desk scenario, Example A | unit | 82; net loss ≤ budget | PASS (base: 85) |
| C-3 | costs | basket: no forced share; cap after costs | unit | 0 for a too-wide stop; 47 not 50 | PASS (base: 2 shares, ₹9,800 at risk) |
| C-4 | costs | plan cost at the stop = trade estimate = realised | unit | ₹285.44 = ₹285.44 = ₹285.44 | PASS |
| C-5 | costs | versioned, explicit; an old trade keeps its model | unit | as stated | PASS |
| C-6 | costs | tests that asserted gross numbers | unit | updated with the reason in each | PASS |
| R-1..R-3 | reconciliation | target, stop (gap), manual, not reached, cancelled; refusals | api | realised = (exit − fill) × qty; net = gross − costs; cash = start + Σ net; blocked = Σ open reservations = reserves − releases | PASS |
| R-4 | reconciliation | partial exit | doc | not supported, stated in the fill model | PASS |
| ER-1..ER-4 | frontend | entry rule per setup in Top 10, AI watchlist, Scanner bodies and notes | e2e | at_once / pullback_to / break_above as mapped | PASS |
| ER-5 | frontend | Builder sizing line after costs | e2e | "₹8,605.44 after estimated costs (₹8,320.00 before)" | PASS |
| ER-6 | frontend | tsc + production build | build | clean | PASS |
| L-1 | live execution | `test_order_path_guard.py` | unit | pass | PASS |
| S-1/S-2 | staging | at_once far from the range; stored P&L unchanged | staging api | — | NOT RUN (no deploy allowed) |

## API / Endpoint Tests (staging)
**Not run on staging**: writes and deploys are not allowed in this task. The real routers were exercised through
`TestClient` with the desk's in-memory fakes, using the bodies the UI sends.

- **pytest, touched suites (27 files) + this branch's new file + plan consumers (`test_chartink_strategy`, `test_chartink_picks`, `test_strategy_evidence_sources`, `test_strategy_ideas`, `test_ai_watchlist`, `test_regime_fit`):**
  - Command: `sudo docker run --rm --network none -v /home/deploy/nivesh-desk-integrity:/work:ro -w /work/backend -e PYTHONDONTWRITEBYTECODE=1 -e MONGO_URL=mongodb://localhost:27017 -e DB_NAME=unit_test -e OPENAI_API_KEY=unit-test-placeholder nivesh/backend:staging python -m pytest <those files> -q -p no:cacheprovider`
  - Output before (aaca6cb1, same files without the new one): `1334 passed, 4 warnings in 63.67s (0:01:03)`
  - Output after: `1366 passed, 4 warnings in 63.44s (0:01:03)`
  - `tests/test_paper_fills_pnl.py tests/test_order_path_guard.py` → `40 passed, 3 warnings in 15.00s`
  - Result: PASS
- **Whole backend test directory**, to catch ripple effects of the sizing change, run on this branch and on origin/dev 5b6b3cfd with `--continue-on-collection-errors` (many suites need services absent under `--network none`):
  - branch: `580 failed, 6016 passed, 577 skipped, 41 warnings, 166 errors in 406.43s` · base: `589 failed, 5927 passed, 580 skipped, 39 warnings, 166 errors in 401.99s`
  - The failing sets compared with `comm`: **0 tests fail on the branch that pass on base**. The 9 that fail only on base read repo files outside `backend/`, which the base `git archive` did not include. Result: PASS (no regression)
- **The same tests against the unfixed code** (aaca6cb1 with this branch's test files copied over): `28 failed, 213 passed`. Every FM-1…FM-4, P-1, P-3, C-1…C-5 and R case fails, and so do the deliberately updated sizing tests. Failure lines:
  ```
  test_fm2_federalbnk_...                assert (201 == 422)                                  <- booked at 316.89
  test_p1_p2_a_gapped_entry_...          assert 1000.0 == 600.0
  test_p1_the_service_close_uses_...     (1000.0, 50.5, 949.5) == (600.0, 50.7, 549.3)
  test_c2_the_desk_scenario_...          assert (85 == 82)
  test_c3_the_basket_never_forces_...    assert (2 == 0)
  ```
- **Probes on origin/dev (before):** `gross P&L close_trade books = realized_pnl(trade, exit) = 1000.0 | P&L from the simulated fill = 600.0` · `entry_rule stored: at_once` · `entry_status assumed fill 316.89 ... gross booked: 3861.0`

## UI / Playwright Tests
- **Specs:** `copilot-app-desk-top10` (F-5 body with `entry_rule`; new F-5c FEDERALBNK → `pullback_to`, trigger → `break_above`), `copilot-app-ai-watchlist` (F-5), `copilot-app-desk-scanner` (SP-9 body and note), `copilot-app-desk-strategy-builder` (new SB-10f net-of-cost line; formula assertions updated), plus the desk regression set (`-desk-lab`, `-desk-strategy-top`, `-desk`, `-desk-risk-controls`, `-desk-strategy-ideas`, `-desk-chartink-picks`)
  - Command: `run-fe.sh` (tsc, `vite build`, `vite preview`, `npx playwright test --config pw.copilot-app.config.ts <10 specs>`)
  - Output: `tsc: clean` · `✓ built in 31.16s` · `16 skipped` (screenshot cases) · `344 passed (3.7m)`
  - Result: PASS
- The Builder fixtures `strategy-plan-cash.json` and `strategy-plan-futures.json` got the sizing block the backend now returns
  for the same fixture world (dumped from `tests/test_strategy_plan.py` `build()`). The quantities are unchanged: 208 and 1.

## Data Correctness (staging, read-only)
- Query: `sudo docker exec -i nivesh-staging-app-backend python - < staging_fills_readonly.py` (read-only, allow-list projection, no user ids, no credentials printed)
- Output:
  ```
  closed cash trades: 6 | entry rules: ['at_once']
    FIXA  ... fill=100.0 exit=100.0 (manual) stored_gross=0.0 gross_from_fill=0.0 same=True
    FIXC  ... fill=100.0 exit=100.0 (manual) stored_gross=0.0 gross_from_fill=0.0 same=True
    HAL x3 ... entry=4989.0 fill=4989.0 exit=4790.0 (stop) stored_gross=-4975.0 gross_from_fill=-4975.0 same=True
    NORTHARC ... entry=280.66 fill=280.66 exit=268.67 (stop) stored_gross=-4999.83 gross_from_fill=-4999.83 same=True
  ```
- Result: PASS for what it shows. Every stored closed trade is `at_once` with fill = entry, so the P&L fix changes no
  stored figure, and none was misbooked by B2 on staging. No backfill is needed or proposed.
- Cost-model evidence (read-only computation with the repo's `research/costs/engine.py`, card `zerodha-equity-v1`
  delivery NSE):
  ```
  Example A, 82 sh, stop: flat 120.97 (slippage 80.98 + brokerage 40.00) | zerodha-equity-v1 delivery statutory 195.70 (brokerage 0.00, STT 161.95, exch 4.97, SEBI 0.16, stamp 12.36, GST 0.92, DP 15.34) + the same 5 bps slippage 80.98
  ICICIBANK 89 sh 1400.2 -> stop 1363.26: flat 162.97 ... | zerodha-equity-v1 delivery statutory 289.17 (... STT 245.95 ...) + the same 5 bps slippage 122.97
  Example A sizing with the card (slippage 5 bps + statutory): 78
  ```
  **OPEN ITEM, owner decision.** The flat model is now explicit, versioned and consistent everywhere. It still leaves
  out STT, stamp duty, exchange and SEBI charges, GST and DP charges. On Example A those are ₹195.70, more than the
  flat model's whole ₹120.97. Adopting the card was judged not small and safe in this change; reasons are in the PR.

## Inputs required from user
- Approval to deploy to staging and a test session for S-1/S-2.
- The owner decisions listed in the PR: the cost card, the entry-rule mapping and the target-jump convention.

## Verdict: BLOCKED
<!-- Every local test case passed with real output above; the staging API cases (S-1, S-2) are not run because this task
     forbids staging writes and deploys. Not PASS until they are. -->
