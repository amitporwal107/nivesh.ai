# Functionality Verification Report — Phase 3 decision cards, account sizing, carry-forward tags, Phase 0 follow-ups

- **Branch:** `feat/p3-decision-cards`, head `a3b2568e`.
  - origin/dev `87a90bca` (Phase 1, #363) merged in at `2fb3b9d1`.
  - origin/dev `7a44f84c` (Phase 4, #364) merged in at `fa3d2b33`.
- **Date:** 2026-10-27
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** local containers only.
  - Backend: pytest in `nivesh/backend:staging`.
  - Frontend: tsc, production build and Playwright with mocked APIs, in `playwright:v1.47.0-jammy`.
  - **Not deployed. Nothing was written to staging** (the brief forbids it).
- **Changed areas:** backend routes/services: yes · frontend src: yes
- **Test cases:** `test_reports/p3_decision_cards_TESTCASES.md`.
  - The original cases were committed (`7fe1f12b`) before any code.
  - Addendum 1 covers the Phase 1 wiring.
  - Addendum 2 covers the sizing and lineage fix. Its cases were written before that code changed.

## Summary

### The decision card
One card (`tradingdesk/decision/DecisionCard.tsx`) shows every criteria-3.1 field. It is used by:
- the Top 10 stock and F&O rows, the AI watchlist rows and the Top-by-regime cards (row form);
- the lab focus panel, the Builder's selected candidate and the paper-trade record (full form).

The levels come from the TradePlan (v1.1 adds evidence, warnings and gap risk).

### Size, risk and costs (release blocker fixed: option a)
- The size, rupee risk, costs and % of equity are the **universal risk service's own sizing for the signed-in account**:
  `account_size` on `GET /api/desk/trade-plans/{id}`, from `services/risk_gate/plan_sizing.py`.
- It is worked out with the service's own `gather()` and `decide()` on a neutral book. That sizing applies:
  - the per-trade budget (est-risk-v1: the stop's loss + desk-cost-v2 costs + 1% gap stress, within the profile's
    per-trade % of paper equity);
  - the position and liquidity caps;
  - the VIX and BEAR factors;
  - the share and lot rounding.
- It is then **confirmed** by a second `decide()` at exactly that size. A third `decide()` on the real book names what
  portfolio limits would cut today, and the budgets left.
- Nothing is recorded.
- A plan the route cannot size shows **no size**, never the plan's own input-based number.

### Approval and the action gate
- "Risk-approved" appears only on a real ALLOW decision.
- One action gate covers the card and every paper-trade button. It refuses what the service would refuse:
  - no size it allows;
  - a size it would cut again;
  - a structure row whose lots exceed the allowed size.

### Version identity (finding 2 fixed)
- `sizing_inputs` is part of each plan's content and lineage.
- A sized plan and the same setup unsized are separate lineages, so no "Plan changed" appears between them.

### Shared plan status (fixed while verifying)
- One user's refused submission no longer shows a shared plan as Rejected to everyone.

### Carry-forward and Phase 0 follow-ups
- Carry-forward tags: shipped.
- Phase 0 (a) to (d): shipped.

## Test Cases (results)

| ID | Result | Evidence |
|----|--------|----------|
| BE-1 … BE-7 (evidence, warnings, gap risk, versions, scan basis, carry-forward, scanner job health) | PASS | `test_decision_cards.py` |
| BE-8, BE-8b, BE-11, BE-11b (contract, real decisions) | PASS | `test_decision_card_contract.py`: fixtures rebuilt from the real routes and compared |
| BE-9 | PASS | `test_trade_plan_contract.py`, `test_fno_idea_paper_trade_contract.py` |
| BE-10 | PASS | `test_order_path_guard.py` |
| **SZ-1** (acceptance) | PASS | **default profile:** the plan's own 113 is reduced by the route to exactly the card's 83, and 83 is ALLOWED; **loosest profile:** the card's size is allowed |
| SZ-2, SZ-3, SZ-5, SZ-6 | PASS | `test_plan_sizing.py` |
| SZ-4 | PASS | BEAR: the card's size carries the factor once and is `not_confirmed` |
| SZ-4b | **XFAIL (strict)** | Phase 1 finding below: in BEAR the card's size is not allowed as is |
| BE-12 | PASS | `test_plan_sizing.py`: a refusal by user B does not change user A's status |
| UI-1 … UI-20 (29 cases) | PASS | `copilot-app-desk-decision-cards.spec.ts`, including UI-17 (the card shows 83 and the POST sends 83), UI-18 (portfolio note), UI-19 (BEAR) and UI-20 (F&O over budget) |
| UI-14 | PASS | `copilot-app-ai-watchlist.spec.ts` F-8 |
| REG-1 | PASS | the "fails on branch, passes on dev" lists below are empty |

## API / Endpoint Tests

### Staging
NOT RUN. The branch is not deployed and staging writes are forbidden. See `OVERRIDE_p3_decision_cards.md`.

### pytest, CI allowlist
The 244 files of `.github/workflows/backend-tests.yml`, plus this branch's 3 new files. Branch head `a3b2568e`:
```
3 failed, 6471 passed, 28 skipped, 1 xfailed, 15 warnings in 221.47s (0:03:41)
FAILED tests/test_cas_api_client.py::test_sandbox_parse_and_map
FAILED tests/test_cas_api_client.py::test_convenience_helper_returns_list
FAILED tests/test_nidp_stamp_broadcast_at.py::test_run_commits_in_batches
XFAIL tests/test_plan_sizing.py::test_sz4b_in_a_bear_regime_the_cards_size_is_allowed_as_is
```

### pytest, same allowlist on plain origin/dev `7a44f84c`
Run on a full `git archive` export, deleted afterwards:
```
3 failed, 6438 passed, 27 skipped, 15 warnings in 203.23s (0:03:23)
FAILED tests/test_cas_api_client.py::test_sandbox_parse_and_map
FAILED tests/test_cas_api_client.py::test_convenience_helper_returns_list
FAILED tests/test_nidp_stamp_broadcast_at.py::test_run_commits_in_batches
```
The same 3 failures happen without this branch (environment-dependent). **Fails on branch, passes on dev: none.**

## UI / Playwright Tests

Spec set: `copilot-app-desk*.spec.ts`, `copilot-app-ai-watchlist.spec.ts`, `copilot-app-watchlists.spec.ts` and
`copilot-app-workspace.spec.ts`. Runner: `run-fe.sh` (tsc, production build, 4 workers).

- **Branch head `a3b2568e`:**
  ```
  tsc: clean
  32 failed
  16 skipped
  695 passed (8.0m)
  ```
  The 29 decision-card cases all pass.
- **origin/dev `7a44f84c`:**
  ```
  32 failed
  16 skipped
  666 passed (7.7m)
  ```
- **Comparison:** all 32 failures, on both sides, are in `copilot-app-desk-strategy-graphs.spec.ts` (`payoff-svg` not
  found). `comm -13 dev.failed branch.failed` printed nothing, so **fails on branch, passes on dev: none**.
- An earlier branch run (`27a43116`) also had desk-lab TC-7 failing. That case is known to be timing-flaky; it passed
  rerun alone (`1 passed (2.9s)`) and passed in the final run.

## Data Correctness

- `contract-decision-card.json` is real route output for:
  - the sizing of three profiles (loosest: 666 shares; default: 83; BEAR: 41, not allowed as is);
  - the three decisions (allow, reduce, block);
  - an F&O plan over the default budget (refused).
- It uses the conftest's MOCK sector and market state.
- **UNVERIFIED on staging:** real `account_size` values, `ai_watchlist_days.notes.scan_basis`, `carried`, and the scanner's
  job health.

## Findings for the owner

1. **🔴 Phase 1 defect: no desk share entry is ever allowed in a BEAR or high-VIX regime.**
   - The governor applies its 0.5 factor to whatever size is submitted. Submitted at the size it allows (41), a request
     is cut again (20), and so on.
   - The desk path accepts only an ALLOW, so every share paper trade is refused (409 risk_reduce).
   - The desk regime's trend was down on 21–26 Oct, so this may be the live state on staging. UNVERIFIED: I did not
     query staging.
   - The card says so ("not allowed as is", and the action is off), and the strict xfail `test_sz4b` flips when the
     defect is fixed.
   - Proposed fix: apply the factor to the caps, not to the request: `allowed = min(q, floor(min(caps) × factor))`.
   - This is Phase 1 / AI-trader governor code, so I did not change it.
2. Each card's plan read runs one risk-service snapshot (`gather`) for the sizing. A Top 10 page makes up to about 20 of
   these. The cost on staging is UNVERIFIED.
3. Correlation is not computed anywhere; the card says so.

## Inputs required from user

- A staging deploy and a signed-in session token, to run the staging checks.

## Verdict: BLOCKED

The verdict is BLOCKED for two reasons:
- the staging checks have not been run;
- finding 1 (BEAR/VIX) is an open Phase 1 defect that the card can only report.

The Phase 3 release blocker itself (a displayed size that differs from the approved size) is closed. SZ-1 shows it on
the real route when no portfolio limit binds; finding 1 is the exception.
