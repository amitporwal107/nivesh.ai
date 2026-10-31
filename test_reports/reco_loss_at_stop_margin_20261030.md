# Functionality Verification Report — strategy cards: covered call LOSS AT STOP, and MARGIN · ZERODHA on every card

- **Branch:** `fix/reco-loss-at-stop-margin` (worktree `/home/deploy/nivesh-wt-reco-margin`, from origin/dev a4294830)
- **Date:** 2026-10-30
- **Author:** Claude (FULL_STACK_DEVELOPER + DOMAIN_EXPERT_ANALYST + QA_ENGINEER)
- **Environment:** pytest in `nivesh/backend:staging` (no network); Playwright on a production build (mocked APIs); staging
  READ-ONLY in-process probe in `nivesh-staging-app-backend` (real warehouse data + the platform Kite session)
- **Changed areas:** backend routes/services: yes (`services/strategy_plan/plan.py`) · frontend src: yes (analysis/RecoStrategies.tsx,
  analysis/reco-data.ts, strategy/plan-contract.ts)
- **Test cases (authored before implementation):** `test_reports/reco_loss_at_stop_margin_TESTCASES.md`

## Summary
Owner, 30 Oct, on Trade Desk › Chart Analysis › "Strategies that fit" (TVSMOTOR): the covered call's MAX LOSS ₹7,40,906.25 assumed
the stock goes to zero; fix it, and show the broker's margin (Kite / Zerodha). Cause: for every non-linear structure the plan's
comparison row (`alternatives[].max_loss`) is the expiry payoff's worst case over all prices; shares with only a short call have no
floor but zero, (4,280 − 46.25) × 175. The same plan exits at its stop (the scanner's 4,130.22), and sizing and the card's own
R : R (2.14) already used the loss there. Now: the row for shares or a future with no long put under them is the loss at the stop
after costs (never below 0), with `max_loss_at: "stop" | "expiry"` on every row and the to-zero figure kept in the basis; the card
labels it LOSS AT STOP with the stop. Every card gets MARGIN · ZERODHA from the existing `POST /api/fno/margin` (Zerodha's
calculator through the platform Kite session) for its option and future legs; shares are stated as paid in full (delivery).
Protective put, collar, futures + put and options rows are unchanged (their put or the spread is the floor).

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| B1 | engine | Covered call row (fixture world, 4 lots) | unit | max_loss = risk_net at the stop, "stop", basis quotes 1,162,000.00 at zero | PASS |
| B2 | engine | Protective put, collar, futures + put rows | unit | expiry max_loss unchanged, "expiry" | PASS |
| B3 | engine | Cash, futures, options rows | unit | unchanged; "stop" / "stop" / "expiry" | PASS |
| B4 | engine | Premium covers the loss at the stop (1250 call at 46) | edge | max_loss 0.0, never negative | PASS |
| B5 | ideas | Ideas row for the covered call | unit | −risk_net, basis passes through | PASS |
| F1 | card logic | cardFigures, covered call | node | LOSS AT STOP, the row's figure, stop 1160 | PASS |
| F2 | card logic | Spread; a row without the field | node | MAX LOSS, no stop | PASS |
| F3 | card logic | cardMarginBody / cardShares | node | spread both legs; covered call the short call; future; cash null | PASS |
| U1 | card page | Mocked calculator answer | e2e (mocked) | each F&O card shows the figure; requests = the cards' legs, 2 calls | PASS |
| U2 | card page | Covered call card | e2e (mocked) | LOSS AT STOP ₹5,971.06, "stop 1,160.00", never ₹11,62,000.00; shares paid in full | PASS |
| U3 | card page | Margin route 503 | e2e (mocked) | "Margin needs today's Kite login.", "—", no ₹ | PASS |
| U4 | card page | Cash card | e2e (mocked) | no request; "No F&O margin", shares paid in full | PASS |
| R1 | regression | chart-analysis chain/basket, desk chart analysis, trade desk specs; 10 backend files reading the row | e2e/unit | all pass | PASS |
| S1 | staging data | TVSMOTOR plan, branch plan.py, real 29 Oct EOD data | data | covered call row 20,583.22 at the stop; spread unchanged | PASS |
| S2 | staging data | Zerodha calculator for each card's F&O legs, the real route function | data | Kite's figures | PASS |
| S3 | staging screen | The deployed card on TVSMOTOR | e2e | screenshot after deploy | NOT IN THIS SCOPE (not deployed; post-merge check) |

## API / Endpoint Tests (staging)

The branch is not deployed. `services/strategy_plan/plan.py` on staging equals the branch's base (`diff` of
`/opt/nivesh-staging/repo/backend/services/strategy_plan/plan.py` against `origin/dev` printed nothing: "staging plan.py == origin/dev
base"). The branch's plan.py was copied into the container as `/tmp/plan_reco_branch.py`, loaded as its own module (the deployed one
untouched), and the plan built in-process with a fake user (no trade plan stored; the `/plan` route's DB write was not called). The
margin figures are the deployed `POST /api/fno/margin` route function itself (`routes.fno.margin`), Zerodha's CALCULATOR through the
platform Kite session (the owner logged Kite in at ~11:40 IST); nothing is placed. Probe files were deleted afterwards
(`ls /tmp | grep -c reco` → 0).

```
$ sudo docker exec -w /app/backend nivesh-staging-app-backend timeout 150 python /tmp/probe_reco_loss.py TVSMOTOR bullish /tmp/plan_reco_branch.py
plan module -> /tmp/plan_reco_branch.py | has _unfloored: True
status plan preferred combination:covered_call data_as_of {'price': '2026-10-29', 'fno': '2026-10-29', 'reference_session': '2026-10-29', 'mode': 'end_of_day', 'fundamentals': '2026-10-29', 'regime': '2026-10-29'}

== options:bull_call_spread | Bull call spread (debit) | actionable True
  legs: [('option', 'buy', 4300, 'call', 1, 175, 115.65, '2026-11-23'), ('option', 'sell', 4500, 'call', 1, 175, 46.25, '2026-11-23')]
  stop (invalidation): 4000.0 | stop scenario: {'name': 'stop', 'underlying_price': 4000.0, 'gross': -12145.0, 'net': -12231.04}
  payoff expiry max_loss -12145.0 max_profit 22855.0 | risk_reward net 1.85 risk_net 12278.24
  ROW max_loss -12145.0 | max_loss_at expiry | basis: defined max loss at expiry (gross)
  margin body: {"underlying": "TVSMOTOR", "legs": [{"side": "buy", "option_type": "call", "expiry": "2026-11-23", "strike": 4300, "lots": 1}, {"side": "sell", "option_type": "call", "expiry": "2026-11-23", "strike": 4500, "lots": 1}]}
  ROUTE /api/fno/margin: {"required_margin": 36533.0, "initial_margin": 42509.25, "hedge_benefit": 79213.75, "standalone_margin": 115746.75, "as_of": "2026-10-30", "source": "Zerodha margin calculator (Kite Connect): exchange SPAN + exposure margin and order charges"}

== combination:covered_call | Covered call (shares + short call) | actionable True
  legs: [('cash', 'buy', None, None, 175, 1, 4280.0, None), ('option', 'sell', 4500, 'call', 1, 175, 46.25, '2026-11-23')]
  stop (invalidation): 4130.22 | stop scenario: {'name': 'stop', 'underlying_price': 4130.22, 'gross': -18117.75, 'net': -20583.22}
  payoff expiry max_loss -740906.25 max_profit 46593.75 | risk_reward net 2.14 risk_net 20583.22
  ROW max_loss 20583.22 | max_loss_at stop | basis: loss at the stop (net), where the plan exits; gaps can exceed it, and below the stop nothing limits the loss (held to expiry, 740,906.25 gross if the price falls to zero)
  margin body: {"underlying": "TVSMOTOR", "legs": [{"side": "sell", "option_type": "call", "expiry": "2026-11-23", "strike": 4500, "lots": 1}]}
  ROUTE /api/fno/margin: {"required_margin": 99244.25, "initial_margin": 105220.5, "hedge_benefit": 0.0, "standalone_margin": 99244.25, "as_of": "2026-10-30", "source": "Zerodha margin calculator (Kite Connect): exchange SPAN + exposure margin and order charges"}
```

Before the fix (the first version of the probe on the deployed plan.py, same data, ~11:25 IST, before the Kite login; excerpt):
```
== combination:covered_call | Covered call (shares + short call) | actionable True
  payoff expiry max_loss -740906.25 loss_unbounded False max_profit 46593.75 net_premium 8093.75
  stop scenario: {'name': 'stop', 'underlying_price': 4130.22, 'gross': -18117.75, 'net': -20583.22}
  risk_reward: net 2.14 gross 2.57 risk_net 20583.22 risk_gross 18117.75 level base
  comparison row: max_loss -740906.25 | basis: defined max loss at expiry (gross); for a structure that holds shares or a future this is the loss if the price falls to the long put's strike, or to zero without a put | keys: ['max_loss', 'max_loss_basis']
  kite margin failed: NoSession
```

Hand check: loss at the stop before costs = (4,280 − 4,130.22 − 46.25) × 175 = 103.53 × 175 = 18,117.75 = the scenario's gross. The
net 20,583.22 adds the payoff engine's estimated costs. R : R 2.14 = the base-level net reward ÷ 20,583.22, so the card's loss and
ratio now measure the same risk.

- **pytest** (the plan and ideas suites, then the ten files that build or read the comparison row):
  ```
  $ docker run … nivesh/backend:staging python -m pytest tests/test_strategy_ideas.py tests/test_strategy_plan.py -q -p no:cacheprovider
  110 passed, 2 warnings in 31.08s
  $ docker run … python -m pytest tests/test_ai_watchlist.py tests/test_chartink_picks.py tests/test_desk_audit_wave1_b3.py tests/test_fno_margin.py tests/test_regime_fit_distinct.py tests/test_strategy_evidence_sources.py tests/test_strategy_ideas.py tests/test_strategy_plan.py tests/test_strategy_plan_templates_route.py tests/test_watchlist_fno_chain_expiry.py -q -p no:cacheprovider
  283 passed, 2 warnings in 47.96s
  ```
  New: `test_covered_call_row_is_the_loss_at_the_stop_not_the_shares_at_zero` (B1, B3), `test_structures_with_a_long_put_keep_the_expiry_max_loss`
  (B2), `test_a_premium_that_covers_the_stop_is_a_loss_of_zero_never_negative` (B4); changed: `test_ideas_numbers_come_from_the_plan…`
  (B5: it pinned the old to-zero figure, −290,500 × lots, which is the behaviour the owner asked to change).
  Result: PASS

## UI / Playwright Tests

- **Typecheck:** `npx tsc --noEmit -p tsconfig.json` → `tsc_exit=0`
- **Specs:** production build (`VITE_USE_MOCK_API=false VITE_BASE=/v5/ npx vite build`, `build_exit=0`; the bundle contains
  "MARGIN · ZERODHA" in `assets/LiveChart-DQPgoq27.js`), `vite preview`, `npx playwright test --config pw.copilot-app.config.ts`:
  ```
  e2e/tests/copilot-app-chart-analysis-chain.spec.ts e2e/tests/copilot-app-chart-analysis-basket.spec.ts
  e2e/tests/copilot-app-desk-chart-analysis.spec.ts e2e/tests/copilot-app-desk-trade-desk.spec.ts
    75 passed (43.3s)
  e2e/tests/copilot-app-chart-analysis-chain.spec.ts (list reporter, new cases):
  ✓   7 … chain.spec.ts:207:3 › logic: analysis/reco-data.ts (pure) › F1 / F2 covered call: LOSS AT STOP from the …
  ✓   9 … chain.spec.ts:229:3 › logic: analysis/reco-data.ts (pure) › F3 margin body: the card's option and futur…
  ✓  19 … chain.spec.ts:500:3 › page: … U1 / U2 / U4 MARGIN · ZERODHA per card from the calculator; the covered call's loss is at its stop
  ✓  20 … chain.spec.ts:540:3 › page: … U3 MARGIN · ZERODHA without today's Kite login says so, no figure
  21 passed (14.2s)
  ```
  MOCK — not real data: the page tests' plan is `e2e/fixtures/strategy-plan-combo.json`, the REAL plan builder's output over the
  backend test world (RELIANCE-like, close 1200, lot 250, capital 5,000,000, risk budget 50,000), built with this branch; the
  calculator answers are inline mocks in the route's shape.
  Result: PASS

## Data Correctness (staging)
- S1: the covered call row on real TVSMOTOR data (29 Oct EOD, NSE bhavcopy chain) = the plan's own stop scenario net (20,583.22),
  and the hand check above matches the gross; the spread row is the same as before (−12,145.00 both runs).
- S2: Zerodha's calculator answered for both cards with the platform session of 30 Oct (`as_of` 2026-10-30): bull call spread
  4300/4500 CE 1 lot ₹36,533.00; short 4500 CE 1 lot ₹99,244.25 (hedge benefit 0, one leg). These are what the deployed cards will
  show for these legs while the session lasts.
- Result: PASS

## Not verified here
- S3, the deployed screen: the frontend is a built image and the backend needs a restart after the merge; the card on staging is
  checked after the deploy.
- Margin while nobody has done the day's Kite login reads "Margin needs today's Kite login." (U3, mocked 503); the real 503 was
  seen in the morning probe as `NoSession` from the same calculator.

## Inputs required from user
- The day's Kite login (owner: "kite connected", 30 Oct) for S2.

## Verdict: PASS
