# Test cases — the credit-structure rule in the universal risk service (authored before the code)

- **Branch:** feat/risk-credit-structure-rule (from origin/dev 7b926d9c; #380's templates NOT merged in: every
  structure here is built from its own legs, which is what the rule reads)
- **Date:** 2026-10-28
- **Owner decision (28 Oct 2026):** "Separate rule for credit: defined-risk credit structures skip the 1.5 reward:risk
  minimum. Instead the net credit must be at least 1/3 of the strike width after costs, and the max loss must fit the
  per-trade budget. Directional trades keep 1.5."
- **Roles:** FULL_STACK_DEVELOPER + QA_ENGINEER.

## The rule as it will be coded (policy `universal-risk-v2`)

A **credit structure** is decided from the legs and the payoff, never the template name:

1. no futures leg (a futures leg is not defined risk under the desk rule);
2. at least one option leg, every option leg one expiry;
3. the payoff at expiry is **flat beyond the outermost strikes on both sides** (slope 0 as the underlying falls to 0 and
   as it rises without limit): the loss is bounded by long options, not by a share price of zero. A covered call's loss
   runs to zero, so it is not one; a long call or protective put has an open upside, so it is not one;
4. the option legs open for a **net credit**: Σ premium of the sold options × quantity − Σ premium of the bought
   options × quantity > 0.

For a credit structure the `reward_risk` check applies, **instead of** `min_reward_risk`:

    credit after costs = net credit − estimated_risk_rs.costs   (the round-trip desk-cost-v2 costs the risk estimate uses)
    width              = the maximum loss at expiry BEFORE the premiums (payoff with every option premium set to 0)
                         = |strike difference| × lots × lot size for a vertical spread
                         = the wider wing × lots × lot size for an iron condor
                         = (share price − put strike) × shares for a collar (see NEEDS-INPUT below)
    pass when          credit after costs ≥ width / 3
    else BLOCK         code credit_too_small, value = credit after costs (Rs), limit = width / 3 (Rs)

Everything else is unchanged: defined risk, lots, expiry, freshness, the per-trade budget (max loss + costs, the
existing `per_trade_risk` check), open risk, exposure, sector, funding, the BEAR/VIX governor. Every other trade keeps
`reward_risk_too_low` at the profile's `min_reward_risk` (1.5 by default).

A decision recorded under `universal-risk-v1` replays under v1 (1.5 for everything), so it still matches.

## Cases

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| CR-1 | decide | Bull put spread, credit after costs ≥ 1/3 of width, max loss + costs within the per-trade budget | unit | `allow`; no `reward_risk_too_low` although max gain / max loss < 1.5; `reward_risk` check `pass`; budget names the rule `credit_vs_width` with credit, width, minimum |
| CR-2 | decide | Bull put spread, credit after costs < 1/3 of width | unit | `block`, reason `credit_too_small` on check `reward_risk`, `value` = credit after costs, `limit` = width / 3 |
| CR-3 | decide | Bear call spread (credit) passes / fails the same way | unit | pass → allow; fail → `credit_too_small` |
| CR-4 | decide | Iron condor with unequal wings: width = wider wing × qty; a credit ≥ 1/3 of the narrower wing but < 1/3 of the wider one | unit | `credit_too_small`, limit = wider wing × qty / 3; with enough credit → allow |
| CR-5 | decide | Collar (shares + long put + short call) opened for a net credit on its options | unit | judged by the credit rule (`credit_vs_width`), never `reward_risk_too_low` |
| CR-6 | decide | Collar opened for a net debit | unit | judged by `min_reward_risk` (1.5): `reward_risk_too_low` when below |
| CR-7 | decide | Debit spread (bull call) with reward:risk < 1.5 | unit | still `reward_risk_too_low`; never `credit_too_small` |
| CR-8 | decide | Cash share trade with reward:risk < 1.5 | unit | still `reward_risk_too_low` (and the governor unchanged) |
| CR-9 | decide | Credit spread whose credit passes but max loss + costs exceeds the per-trade budget at one lot | unit | still `block` `min_lot_exceeds_budget` (check `per_trade_risk`); the credit rule does not let it in |
| CR-10 | decide | Credit spread over budget at 3 lots, fits at 2 | unit | `reduce` to 2 lots; the credit rule is judged at the approved size |
| CR-11 | decide | Costs are in the credit: a spread whose GROSS credit is ≥ 1/3 of width but whose credit after the estimate's costs is below | unit | `credit_too_small`; `value` = gross credit − `estimated_risk_rs.costs` exactly |
| CR-12 | classify | Covered call (shares + short call) opens for a premium but its loss runs to zero | unit | NOT a credit structure → 1.5 applies |
| CR-13 | classify | A structure with a futures leg and a short call (synthetic covered call) | unit | NOT a credit structure |
| CR-14 | classify | Credit is computed from the legs, not the template name: the same bull-put legs listed in any order, any `family` | unit | same terms |
| CR-15 | replay | A decision recorded under `universal-risk-v1` for a credit spread blocked `reward_risk_too_low` | unit | replays under v1: `match: true`, same reason; the same request decided now (v2) is allowed |
| CR-16 | replay | A v2 decision replays to itself; an unknown policy version is `replayable: false` with the reason | unit | as stated |
| CR-17 | version | New decisions record `policy_version` `universal-risk-v2` (row, decision, stamp, plan sizing) | unit/api | as stated |
| CR-18 | plan sizing ↔ POST | A bear call spread TradePlan: `GET /api/desk/trade-plans/{id}` `account_size` and `POST /api/desk/paper-trades` with the same legs agree: credit ≥ 1/3 → sized at N lots and the POST at N lots is 201; credit < 1/3 → `not_sizable` with `credit_too_small` and the POST is 409 `risk_blocked` with `credit_too_small` | api (real routes, in-memory Mongo) | as stated |
| CR-19 | regression | Every `test_risk*` file, `test_plan_sizing`, `test_strategy_payoff`, `test_payoff_cost_card`, `test_decision_card_contract`, `test_ai_trader_config_risk` | unit | pass (version assertions updated to v2 where they pin the string) |
| CR-20 | regression | Full CI allowlist in Docker `--network none` | unit | only dev's 3 network-only failures (`test_cas_api_client` ×2, `test_nidp_stamp_broadcast_at`) |

## NEEDS-INPUT (stated, not silently assumed)

- **Collar width.** The owner defined the width for a vertical spread and an iron condor. A collar has no single "strike
  width". This code uses the definition that reproduces both of the owner's: the maximum loss at expiry before the
  premiums, which for a collar is (share price − put strike) × shares. The alternative (call strike − put strike) is
  stricter. Owner to confirm.
- **The 1/3 is a policy constant, not a profile field.** It is versioned with the policy (`universal-risk-v2`), so a
  profile set to min reward:risk 0 (the loosest, admin only) does not relax it.
