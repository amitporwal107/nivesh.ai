# Functionality Verification Report — Phase 3 decision cards, carry-forward tags, Phase 0 follow-ups

- **Branch:** `feat/p3-decision-cards`. Head `cbf890ca`: origin/dev `87a90bca` (Phase 1 #363) merged in at `2fb3b9d1`.
- **Date:** 2026-10-27
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** local containers only. The backend ran in `nivesh/backend:staging` (pytest); the frontend in
  `playwright:v1.47.0-jammy` (tsc, production build, mocked APIs). **Not deployed, and nothing was written to staging**,
  as the brief requires.
- **Changed areas:** backend routes/services: yes · frontend src: yes
- **Test cases:** `test_reports/p3_decision_cards_TESTCASES.md`, committed (`7fe1f12b`) before any implementation.

## Summary

### One decision card for every surface
`tradingdesk/decision/DecisionCard.tsx` renders every criteria-3.1 field from the TradePlan. It has two forms:
- a **row** form (one line plus an expander), used by the Top 10 stock and F&O rows, the AI watchlist's cash and F&O rows,
  and the Top-by-regime cards;
- a **full** form, used by the lab focus panel, the Strategy Builder's candidate, and the paper-trade record (read by id).

A field the plan lacks is labelled "unavailable" with the reason.

### What the TradePlan now carries
The backend plan (v1.1) now carries:
- **evidence**: regime, trend, RS, momentum, volume and structure;
- **warnings**: event, liquidity, concentration (checked at entry) and correlation (not computed anywhere, said so);
- **`costs.gap_risk`**.

### Phase 1 risk seam
`GET /api/desk/trade-plans/{id}` now returns the user's newest universal-risk decision on the plan (`risk_decision`).
The card is "Risk-approved" only on a real ALLOW made under the current limits version, and "Provisional" with no
decision. A REDUCE shows the size it allows. A BLOCK disables the action while it still applies: same session, same
limits, and, if the kill switch or halt caused it, while that control is still on. "% of equity" uses the risk
profile's paper equity.

### Consistency
- Every view reads the plan by `plan_id` from one cache.
- The newest version the user may open is shown, with a "Plan changed" note.
- A plan that names the plan it `supersedes` refreshes the older plan's reading.

### Carry-forward and Phase 0 follow-ups
- Carry-forward tags on the watchlist and the Top 10.
- **P0 (a):** the F&O idea POST sends an Idempotency-Key.
- **P0 (b):** the job time reads 22:45 IST.
- **P0 (c):** the AI watchlist day stores and shows `scan_basis`.
- **P0 (d):** `GET /api/admin/risk/jobs/positional_engine` answers.

## Test Cases (results)

| ID | Result | Evidence |
|----|--------|----------|
| BE-1, BE-1b | PASS | `test_decision_cards.py` |
| BE-2, BE-2b | PASS | `test_decision_cards.py` |
| BE-3 | PASS | `test_decision_cards.py` |
| BE-4 | PASS | `test_decision_cards.py` (versions filtered per reader) |
| BE-5 | PASS | `test_decision_cards.py` |
| BE-6, BE-6b, BE-6c | PASS | `test_decision_cards.py` |
| BE-7 (8 statuses), BE-7b, BE-7c | PASS | `test_decision_cards.py` |
| BE-8, BE-8b | PASS | `test_decision_card_contract.py`: the fixtures are rebuilt from the real routes and compared |
| BE-9 | PASS | `test_trade_plan_contract.py` and `test_fno_idea_paper_trade_contract.py`, with the regenerated fixture |
| BE-10 | PASS | `test_order_path_guard.py` |
| BE-11, BE-11b (added with Phase 1) | PASS | real allow, reduce and block on the plan route; a validation refusal is not read as a decision |
| UI-1 … UI-6 | PASS | `copilot-app-desk-decision-cards.spec.ts` |
| UI-7, UI-7b (cross-view consistency) | PASS | same spec |
| UI-8a … UI-8g (empty, stale, rejected, provisional, approved, reduce, block, stale block) | PASS | same spec |
| UI-9, UI-9b, UI-9c (plan change refresh) | PASS | same spec |
| UI-10 … UI-13, UI-15, UI-16 | PASS | same spec |
| UI-14 (22:45 IST) | PASS | `copilot-app-ai-watchlist.spec.ts` F-8 |
| REG-1 | PASS | the "fails on branch, passes on dev" list is empty (below) |

## API / Endpoint Tests

- **Staging:** NOT RUN. The branch is not deployed, and the brief forbids staging writes. A signed-in GET would also need a
  user session token. See `OVERRIDE_p3_decision_cards.md`.
- **pytest, focused** (`python -m pytest tests/test_decision_cards.py tests/test_decision_card_contract.py tests/test_trade_plan_contract.py tests/test_fno_idea_paper_trade_contract.py tests/test_order_path_guard.py tests/test_ai_watchlist.py tests/test_desk_exit_job.py -q -rs`, at `cbf890ca`):
  ```
  SKIPPED [1] tests/test_decision_card_contract.py:48: writes the fixtures only when asked
  95 passed, 1 skipped, 3 warnings in 18.80s
  ```
- **pytest, desk/plan/risk subset.** Files: `test_trade_plan*`, `test_trade_lifecycle*`, `test_fno_*`,
  `test_ai_watchlist*`, `test_desk_*`, `test_strategy_*`, `test_order_path_guard*`, `test_positional*`, `test_scan*`,
  `test_risk_*`, `test_paper_*`, `test_regime*` and `test_decision_card*`.
  - branch `cbf890ca`: `1854 passed, 8 skipped, 4 warnings in 72.06s (0:01:12)` · exit 0
  - plain origin/dev `87a90bca` (a full `git archive` export, deleted afterwards): `1828 passed, 7 skipped, 4 warnings in 84.65s (0:01:24)` · exit 0
  - The extra 26 passes and 1 skip on the branch are the new tests (the skip is the fixture writer). No failure on either side.

## UI / Playwright Tests

Command: `run-fe.sh` (tsc, production build, Playwright with 4 workers, mocked API). Specs:
`copilot-app-desk*.spec.ts`, `copilot-app-ai-watchlist.spec.ts`, `copilot-app-watchlists.spec.ts` and
`copilot-app-workspace.spec.ts`.

- **branch `cbf890ca`:**
  ```
  tsc: clean
  32 failed
  16 skipped
  691 passed (11.7m)
  ```
- **origin/dev `87a90bca`** (export):
  ```
  32 failed
  16 skipped
  666 passed (10.0m)
  ```
- **The 32 failures are the same on both sides.** All are in `copilot-app-desk-strategy-graphs.spec.ts`
  (`getByTestId('payoff-svg')` not found on dev too). `comm -13 dev.failed branch.failed` printed nothing, so
  **"fails on branch, passes on dev" is empty**. desk-lab TC-7 and TC-34 passed in both runs; no rerun was needed.
- **Decision-card spec:** all 25 cases ✓ in the branch run (UI-1 … UI-16, as listed above).

## Data Correctness

- The decision fixture is real route output. `contract-decision-card.json` is written by pytest from the real routes,
  using the conftest's MOCK sector and market state, and compared by BE-8b.
- Its three decisions are the universal risk service's own answers on the same plan:
  - **allow:** 113 shares, estimated risk ₹6,308.33;
  - **reduce:** 83 shares, `per_trade_risk_exceeded`;
  - **block:** `kill_switch_on`.
- **No staging data was read.** UNVERIFIED: real `ai_watchlist_days.notes.scan_basis` and real `carried` values after
  the next job run; the real `GET /api/admin/risk/jobs/positional_engine` answer.

## Findings for the owner

1. **🔴 Release-blocker class (Phase 3 exit gate), NOT fixed here.** The plan sizes the stop plus costs inside the
   plan's stated capital × risk %. The risk service also adds a 1% **gap stress** and uses the account's paper equity.
   The real fixture shows the result: the plan says 113 shares (₹4,997.53 risk at 0.5%), but under the owner's
   default profile the service REDUCES the same plan to 83 shares.
   - The card shows both figures once a submission has been decided.
   - There is no preview, so before submission the card can only show the plan's size, marked "Provisional".
   - Proposed fix: size the plan with `risk_gate.estimate` and the profile's equity, or add a read-only decision
     preview route. This is an owner decision for Phase 1/2 code.
2. A plan's lineage ignores the sizing inputs. A Builder plan with capital and the board's unsized plan for the same
   setup day therefore become versions of each other, and the card follows the newest. Rebuilding cannot clear a
   "changed" block on a Builder or F&O row; cash rows record the shown version, so they are not affected.
3. Correlation is computed nowhere; the card says so. Concentration is checked by the risk service at entry, not shown
   ahead of a submission.

## Inputs required from user

- A deploy of this branch to staging, and a signed-in session token, to run the staging API checks
  (`GET /api/desk/trade-plans/{id}` with `risk_decision`, the AI watchlist day, `GET /api/admin/risk/jobs/positional_engine`).

## Verdict: BLOCKED

The verdict is BLOCKED for two reasons:
- the staging checks were not run, because the brief forbids staging writes and deploys;
- the plan-size vs risk-service-size gap above is open.
