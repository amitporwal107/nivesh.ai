# Test cases — strategy cards: covered call loss at the stop, and Zerodha margin on every card

- **Branch:** `fix/reco-loss-at-stop-margin` (worktree `/home/deploy/nivesh-wt-reco-margin`, from origin/dev a4294830)
- **Date:** 2026-10-30 · **Roles:** FULL_STACK_DEVELOPER + DOMAIN_EXPERT_ANALYST + QA_ENGINEER
- **Owner's ask (30 Oct, screenshot of Trade Desk › Chart Analysis › "Strategies that fit", TVSMOTOR):** "why maximum loss is
  assuming the stock price goes to zero — please fix this. Also display margin requirement from the broker assuming Kite Zerodha."

## Why it read ₹7,40,906.25

The card's MAX LOSS for a combination is the plan's comparison row `max_loss`, which for every non-linear structure is the
expiry payoff's worst case over all prices. Shares with only a short call have no floor, so that worst case is the stock at
zero: (4,280 − 46.25) × 175 = 7,40,906.25. The same plan exits the trade at its stop (the scanner's 4,130.22): sizing and the
card's own R : R (2.14) already use the loss there (₹20,583.22 net, staging 29 Oct EOD), so the card mixed two risk measures.

## Design (API + UI)

**API — `POST /api/desk/strategy/plan`, `alternatives[]` (services/strategy_plan/plan.py `_comparison`).**
- New field `max_loss_at`: `"stop"` | `"expiry"`. `"stop"` for cash, futures, and a combination that holds shares or a future
  long with no long put under them (today: the covered call). `"expiry"` otherwise (options; protective put, collar,
  futures + put, whose put is the floor).
- Covered call row: `max_loss` = `risk_reward.risk_net` (the loss at the stop after costs, positive, as the cash and futures rows),
  never below 0 (a premium that covers the loss at the stop is a loss of 0, not a negative loss). `max_loss_basis` says it is the
  loss at the stop, that a gap can exceed it, and quotes the to-zero expiry figure so nothing is hidden.
- Rows for cash, futures, options, protective put, collar, futures + put: `max_loss` and `max_loss_basis` values unchanged
  (the combination basis drops its "or to zero without a put" clause, which no longer applies).
- Readers of the row: the cards; `ideas.strategies_of` (Chartink picks, AI watchlist), which turns it into a negative P&L.

**UI — `RecoStrategies` card (analysis/reco-data.ts `cardFigures`, new `cardMarginBody`).**
- Label LOSS AT STOP when the row says `max_loss_at: "stop"` (or the card is cash/futures, as before); under the figure,
  `stop <price>` from `invalidation.technical.price`. MAX LOSS and no stop line otherwise. A row without the field (an older
  engine) keeps today's labels.
- New wide row `MARGIN · ZERODHA` (testid `ca-reco-margin`): `POST /api/fno/margin` (Zerodha's calculator through the platform
  Kite session, existing route, cached with the basket's query) for the card's option and future legs.
  ok → Kite's `required_margin`; the note names the legs and, for a card with shares, adds the shares' cost paid in full
  (delivery). Cash only → no request, "No F&O margin", shares paid in full. 503 → "Margin needs today's Kite login.";
  other failures → the route's reason; the figure reads "—", never a guess.

## Test cases

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| B1 | engine | Covered call (fixture world, 4 lots) comparison row | unit | `max_loss` = its `risk_reward.risk_net` (> 0), `max_loss_at` "stop", basis names the stop and quotes 290,500 × 4 at zero |
| B2 | engine | Protective put, collar, futures + put, options rows | unit | `max_loss` = expiry `max_loss` (unchanged), `max_loss_at` "expiry" |
| B3 | engine | Cash, futures rows | unit | values unchanged, `max_loss_at` "stop" |
| B4 | engine | Covered call whose premium covers the loss at the stop | edge | `max_loss` 0.0, never negative |
| B5 | ideas | Ideas strategy row for the covered call | unit | `max_loss` = −risk_net (negative P&L), basis passes through |
| F1 | card logic | `cardFigures` on the covered call (row `max_loss_at` "stop") | node | LOSS AT STOP, the row's `max_loss`, `stop` = invalidation price |
| F2 | card logic | Spread; a combination row without the field | node | MAX LOSS, `stop` null (unchanged) |
| F3 | card logic | `cardMarginBody` | node | spread → both legs with lots; covered call → the short call only; cash → null; future → `option_type` "future", strike null |
| U1 | card page | Mocked margin answer | e2e (mocked) | each F&O card shows Kite's `required_margin`; the request carries the card's legs |
| U2 | card page | Covered call card | e2e (mocked) | LOSS AT STOP with the row's figure and "stop …"; margin note adds "for … shares, paid in full (delivery)" |
| U3 | card page | Margin route 503 | e2e (mocked) | "Margin needs today's Kite login.", figure "—" |
| U4 | card page | Cash card | e2e (mocked) | no margin request for it; "No F&O margin" and shares paid in full |
| R1 | regression | Existing chart-analysis chain spec, strategy plan + ideas pytest | e2e/unit | all pass |
| S1 | staging | TVSMOTOR plan built in-process with the changed plan.py (read only) | data | covered call row = loss at the stop (20,583.22 on 29 Oct EOD), `max_loss_at` "stop"; spread row unchanged |
| S2 | staging | Real Zerodha margin for the cards' legs | data | Kite's figure — needs the day's admin Kite login (none at 11:24 IST 30 Oct: `NoSession`) |
