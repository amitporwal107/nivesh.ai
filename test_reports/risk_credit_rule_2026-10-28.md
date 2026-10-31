# Functionality Verification Report — risk service: the credit-structure rule (universal-risk-v2)

- **Branch:** feat/risk-credit-structure-rule (from origin/dev 7b926d9c; #380 not merged in)
- **Date:** 2026-10-28
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** unit and in-process API (real routes on the in-memory Mongo), Docker `nivesh/backend:staging`, `--network none`. Staging: NOT deployed (see OVERRIDE_risk_credit_rule.md)
- **Changed areas:** backend routes/services: yes (services/risk_gate/service.py, estimate.py, replay.py; risk_profile.py text; feature_flags.py text) · frontend src: no

## Summary
Owner decision 2026-10-28. A defined-risk credit structure (estimate.credit_terms decides it from the legs and payoff: no
futures, payoff flat beyond the outer strikes, options open for a net credit) skips min_reward_risk. Instead its net
credit less the risk estimate's round-trip costs must be at least 1/3 of its strike width (`credit_too_small`, value = credit
after costs, limit = width / 3). The per-trade budget and every other check are unchanged. Directional trades keep 1.5.
POLICY_VERSION goes from universal-risk-v1 to v2. replay re-decides a stored decision under its own version. Plan sizing calls
the same decide().

## Test Cases
Authored first: `test_reports/risk_credit_rule_TESTCASES.md`. Every case maps to a test in `backend/tests/test_risk_credit_rule.py`
(CR-1 … CR-18). CR-19 and CR-20 are the regression runs below.

| ID | Scenario | Result |
|----|----------|--------|
| CR-1 | bull put spread, credit after costs ≥ 1/3 width, fits budget → allow (v1 blocked it at 1.5) | PASS |
| CR-2 | bull put spread below 1/3 → block credit_too_small (value/limit) | PASS |
| CR-3 | bear call spread pass / fail | PASS |
| CR-4 | iron condor measured against its wider wing | PASS |
| CR-5 | collar for a net credit → credit rule (allow; small credit → credit_too_small) | PASS |
| CR-6 | collar for a net debit → 1.5 (reward_risk_too_low) | PASS |
| CR-7 | debit spread → 1.5 | PASS |
| CR-8 | cash → 1.5 | PASS |
| CR-9 | credit passes, max loss over the budget → min_lot_exceeds_budget | PASS |
| CR-10 | 3 lots over budget → reduce to 2, credit judged at 2 | PASS |
| CR-11 | costs in the credit (call and put side): value = credit − estimate costs | PASS |
| CR-12 | covered call is not a credit structure | PASS |
| CR-13 | futures leg → not a credit structure | PASS |
| CR-14 | legs decide, not order or name | PASS |
| CR-15 | v1 decision replays under v1 unchanged; v2 now allows the same request | PASS |
| CR-16 | v2 replays to itself; unknown policy not replayable; decide refuses it | PASS |
| CR-17 | new decisions under v2 (decide, stamp) | PASS |
| CR-18 | GET /api/desk/trade-plans/{id} account_size and POST /api/desk/paper-trades agree (sized + 201 / not_sizable + 409, both credit_too_small) | PASS |
| CR-19 | test_risk* + plan_sizing, strategy_payoff, payoff_cost_card, decision_card_contract, ai_trader_config_risk | PASS (685 = dev 664 + 21 new) |
| CR-20 | full CI allowlist | PASS (only dev's own 4 failures, see below) |

## API / Endpoint Tests
Command (each run): `sudo docker run --rm --network none -v <tree>:/work:ro -w /work/backend -e PYTHONDONTWRITEBYTECODE=1 -e MONGO_URL=mongodb://localhost:27017 -e DB_NAME=unit_test -e OPENAI_API_KEY=unit-test-placeholder nivesh/backend:staging python -m pytest <files> -q -p no:cacheprovider`

### New file, verbose (`tests/test_risk_credit_rule.py`, branch)
```
tests/test_risk_credit_rule.py::test_cr1_a_bull_put_spread_with_a_third_of_the_width_after_costs_is_allowed_below_1_5 PASSED [  4%]
tests/test_risk_credit_rule.py::test_cr2_a_bull_put_spread_below_a_third_of_the_width_is_blocked_credit_too_small PASSED [  9%]
tests/test_risk_credit_rule.py::test_cr3_a_bear_call_spread_is_judged_by_the_same_rule[40-True] PASSED [ 14%]
tests/test_risk_credit_rule.py::test_cr3_a_bear_call_spread_is_judged_by_the_same_rule[50-False] PASSED [ 19%]
tests/test_risk_credit_rule.py::test_cr4_an_iron_condor_is_measured_against_its_wider_wing PASSED [ 23%]
tests/test_risk_credit_rule.py::test_cr5_a_collar_opened_for_a_net_credit_is_a_credit_structure PASSED [ 28%]
tests/test_risk_credit_rule.py::test_cr6_a_collar_opened_for_a_net_debit_keeps_the_1_5_minimum PASSED [ 33%]
tests/test_risk_credit_rule.py::test_cr7_a_debit_spread_keeps_the_1_5_minimum PASSED [ 38%]
tests/test_risk_credit_rule.py::test_cr8_a_cash_trade_keeps_the_1_5_minimum PASSED [ 42%]
tests/test_risk_credit_rule.py::test_cr9_a_credit_that_passes_does_not_let_a_max_loss_over_the_budget_in PASSED [ 47%]
tests/test_risk_credit_rule.py::test_cr10_over_the_budget_at_three_lots_it_is_reduced_and_judged_at_two PASSED [ 52%]
tests/test_risk_credit_rule.py::test_cr11_the_credit_is_judged_after_the_estimates_round_trip_costs[legs0-bearish] PASSED [ 57%]
tests/test_risk_credit_rule.py::test_cr11_the_credit_is_judged_after_the_estimates_round_trip_costs[legs1-bullish] PASSED [ 61%]
tests/test_risk_credit_rule.py::test_cr12_a_covered_call_is_not_a_credit_structure_its_loss_runs_to_zero PASSED [ 66%]
tests/test_risk_credit_rule.py::test_cr13_a_structure_with_a_futures_leg_is_not_a_credit_structure PASSED [ 71%]
tests/test_risk_credit_rule.py::test_cr14_the_legs_decide_not_their_order_or_a_name PASSED [ 76%]
tests/test_risk_credit_rule.py::test_cr15_a_v1_decision_replays_under_v1_unchanged_though_v2_now_allows_it PASSED [ 80%]
tests/test_risk_credit_rule.py::test_cr16_a_v2_decision_replays_to_itself_and_an_unknown_policy_is_not_replayable PASSED [ 85%]
tests/test_risk_credit_rule.py::test_cr17_new_decisions_are_made_and_recorded_under_v2 PASSED [ 90%]
tests/test_risk_credit_rule.py::test_cr18_plan_sizing_and_the_paper_trade_route_apply_the_same_credit_rule[300.0-210.0-True] PASSED [ 95%]
tests/test_risk_credit_rule.py::test_cr18_plan_sizing_and_the_paper_trade_route_apply_the_same_credit_rule[300.0-240.0-False] PASSED [100%]
======================== 21 passed, 2 warnings in 7.57s ========================
```

### Related suites: `tests/test_risk_controls.py tests/test_risk_entry_paths.py tests/test_risk_equity.py tests/test_risk_gate.py tests/test_risk_gate_ai_trader.py tests/test_risk_gate_desk_journal.py tests/test_risk_migration.py tests/test_risk_replay.py tests/test_risk_reservation_mongo.py tests/test_risk_route_inventory.py tests/test_risk_routes.py tests/test_risk_service.py  tests/test_plan_sizing.py tests/test_strategy_payoff.py tests/test_payoff_cost_card.py tests/test_decision_card_contract.py tests/test_ai_trader_config_risk.py`
dev 7b926d9c (pristine `git archive origin/dev`):
```
664 passed, 6 skipped, 2 warnings in 25.80s
```
branch (the same files + tests/test_risk_credit_rule.py):
```
685 passed, 6 skipped, 2 warnings in 26.26s
```

### Full CI allowlist (`.github/workflows/backend-tests.yml`)
dev 7b926d9c, 251 files:
```
FAILED tests/test_cas_api_client.py::test_sandbox_parse_and_map - AssertionEr...
FAILED tests/test_cas_api_client.py::test_convenience_helper_returns_list - a...
FAILED tests/test_desk_paper_safety.py::test_i14_a_strategy_close_frees_the_structure
FAILED tests/test_nidp_stamp_broadcast_at.py::test_run_commits_in_batches - a...
4 failed, 6655 passed, 28 skipped, 15 warnings in 216.10s (0:03:36)
```
branch, first run (before the mechanics fixture update):
```
FAILED tests/test_cas_api_client.py::test_sandbox_parse_and_map - AssertionEr...
FAILED tests/test_cas_api_client.py::test_convenience_helper_returns_list - a...
FAILED tests/test_desk_paper_safety.py::test_i14_a_strategy_close_frees_the_structure
FAILED tests/test_desk_strategy_trades.py::test_defined_risk_structures_and_a_plain_futures_leg_are_accepted[bull put spread]
FAILED tests/test_desk_strategy_trades.py::test_defined_risk_structures_and_a_plain_futures_leg_are_accepted[iron condor]
FAILED tests/test_nidp_stamp_broadcast_at.py::test_run_commits_in_batches - a...
6 failed, 6674 passed, 28 skipped, 15 warnings in 213.73s (0:03:33)
```
branch, final (commit 3fcc2933, 252 files):
```
FAILED tests/test_cas_api_client.py::test_sandbox_parse_and_map - AssertionEr...
FAILED tests/test_cas_api_client.py::test_convenience_helper_returns_list - a...
FAILED tests/test_desk_paper_safety.py::test_i14_a_strategy_close_frees_the_structure
FAILED tests/test_nidp_stamp_broadcast_at.py::test_run_commits_in_batches - a...
4 failed, 6676 passed, 28 skipped, 15 warnings in 211.32s (0:03:31)
```

The 4 failures in the final run are dev's own. On pristine dev they fail identically: `test_cas_api_client` ×2 and
`test_nidp_stamp_broadcast_at` (network-only), plus `test_desk_paper_safety::test_i14`. That last one fails with
`DeskInputError: expiry_in_past`: its fixture expiry is before today's wall clock (2026-10-28). It is date-dependent,
fails on dev today, and is not touched here.

The first branch run failed `test_desk_strategy_trades` [bull put spread] and [iron condor]. That mechanics suite runs
under the loosest profile (min R:R 0), and its two credit structures carried a credit of 30% of the width. The fixed 1/3
rule now blocks them (`credit_too_small`, value 2,657.07, limit 4,166.67). The suite only tests defined-risk acceptance,
so their short premiums were raised to clear 1/3 after costs (commit 3fcc2933, commented). That suite now gives
69 passed.

## Finding: the risk estimate's put-side costs (NOT changed; owner decision needed)
Probe (scratch script, the branch's code, MOCK legs, 1 NIFTY lot of 50). Real output:
```
NIFTY bull put 24800/24900: worst_point=0.0 max_loss=3000.0 costs=4293.16 total=7293.16 | costs by exit point {0.0: 4293.16, 24800.0: 113.28, 24900.0: 108.52} | payoff [-3000.0, -3000.0, 2000.0]
NIFTY bear call 25100/25200: worst_point=25200.0 max_loss=3000.0 costs=110.74 total=3110.74 | costs by exit point {0.0: 105.98, 25100.0: 105.98, 25200.0: 110.74} | payoff [2000.0, 2000.0, -3000.0]
NIFTY iron condor equal wings 100/100: worst_point=0.0 max_loss=2750.0 costs=4376.35 total=7126.35 | costs by exit point {0.0: 4376.35, 24700.0: 213.32, 24800.0: 208.56, 25200.0: 208.56, 25300.0: 213.32} | payoff [-2750.0, -2750.0, 2250.0, 2250.0, -2750.0]
NIFTY bear put (debit) 25000/24800: worst_point=25000.0 max_loss=3500.0 costs=111.21 total=3611.21 | costs by exit point {0.0: 4315.3, 24800.0: 135.41, 25000.0: 111.21} | payoff [6500.0, 6500.0, -3500.0]
```
`estimate._worst_point` takes the first lowest-payoff point. When the payoff is flat on the put side, S = 0 ties with the
lower strike, so the exit of deep in-the-money puts is priced at about their strike value: Rs 4,293 against Rs 113 at
the nearest max-loss strike. The rule uses "the same costs the risk estimate uses", as specified, so an index bull put
spread or an equal-wing iron condor cannot pass it. The same artifact already inflates their per-trade risk today.
Pricing the exit at the nearest max-loss point would loosen per-trade risk for all put-side structures, so it is left
for the owner.

## Data Correctness (staging)
Not run: the code is not deployed (OVERRIDE_risk_credit_rule.md). No staging data was read or written.

## Inputs required from user
- Owner: the put-side cost finding above; the collar width (max loss before premiums = (share − put strike) × shares,
  vs the stricter call − put strike); confirm 1/3 is a policy constant that the loosest profile does not relax.

## UNVERIFIED
- Staging, after merge and a backend restart: a real credit-spread POST and a decision row with `policy_version: universal-risk-v2`.
- UI: `DecisionCard.tsx` still has the static text "universal-risk-v1". The Risk Desk log hides "Reward:risk" for credit
  structures and does not show the credit fields yet. Frontend not touched.

## Verdict: PASS
