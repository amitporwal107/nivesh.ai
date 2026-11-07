# Phase 3A test cases (AD-P3-*): fill to reconciled closure — written before the code, 7 Nov 2026

Design: `PHASE3_DESIGN.md`. Phase 2 cases (AD-P2-*) live in `TESTCASES.md` and keep running unchanged. Layers: U = unit (pure, doubles), I = integration
(throwaway Postgres), A = API (FastAPI app, faked sign-in), R = real-data replay (credentialed container; UNVERIFIED until run and its output shown),
G = guard. Test doubles are labelled MOCK in code. "Hand check" cases show the arithmetic in the report.

Conventions: shares and futures are long unless stated; prices in rupees; the Phase 2 fill parameters apply (half spread 0.05 % shares / 0.02 % futures,
slippage 3 / 2 bps × seeded factor, volume share 10 %); costs are `desk-cost-v2`.

## A. Exit decisions (pure: `exits.py` over `services/exit_rules.step`)

| ID | L | Case | Expected |
|---|---|---|---|
| AD-P3-01 | U | Position opens with plan stop 970, target 1060, max 10 sessions, no trailing | `exits.start` builds state with that stop and target, version `exit-rules-v1`, from the actual average fill price (not the plan price) |
| AD-P3-02 | U | Bar low 965 (stop 970), high 1010 | exit reason `stop`, level 970, `both_in_range` false |
| AD-P3-03 | U | Bar low 965 and high 1065 (stop 970, target 1060) | exit `stop` (adverse level wins), `both_in_range` true |
| AD-P3-04 | U | Open 950 below stop 970 (gap) | exit `stop`, fill basis `gap_open` at 950, `gapped` true, never at 970 |
| AD-P3-05 | U | Bar high 1062, low 990 (target 1060 only) | exit `target` at 1060 |
| AD-P3-06 | U | Open 1075 above target 1060 | target fills at 1060, no credit for the better open |
| AD-P3-07 | U | `max_holding_days` 5, five sessions held, no touch | exit `time` at the close of session 5; sessions counted held, a holiday gap does not count |
| AD-P3-08 | U | Trailing on: new highs raise the stop; a lower bar | stop moves up only, each change a new `stop_history` version, never down; ATR unavailable → trail does not move and says so |
| AD-P3-09 | U | Trailing off | `trade_exit_state` keeps no trail rule; nothing in a later exit reads trail state |
| AD-P3-10 | U | A stop raised by this session's bar | in force from the **next** session; this bar's own low is tested against the old stop |
| AD-P3-11 | U | Bar with no usable high or low (`IncompleteBar`) | no decision; the scan stops with `EXIT_BLOCKED_NO_DATA`; no exit is invented |
| AD-P3-12 | U | Rule config from a plan that asks for a stop below the entry on a long, or a stop that loosens | refused at `start` / `manual_stop`; the manager never widens a stop |
| AD-P3-13 | U | Two decisions in one session for the same trade and reason | one order only (idempotency key `<trade>:EXIT:<session>:<reason>:<n>`) |
| AD-P3-14 | U | Hand-built 12-session series of bars | the decision sequence equals folding `exit_rules.step` over those bars (the manager adds no rule) |

## B. No hindsight

| ID | L | Case | Expected |
|---|---|---|---|
| AD-P3-20 | I | Simulated OPEN of session t | the decision is made from `open`, the stop as at t−1 close and the trend flag only; high, low, close of t are not passed in |
| AD-P3-21 | I | A replay of several sessions with the bar-reader log | every read is for the clock's session; zero reads of a later session (report shows the log count) |
| AD-P3-22 | I | An agent asking its view for the session being simulated | still raises `LookAheadError` (Phase 1 behaviour unchanged) |
| AD-P3-23 | I | Trail for t+1 computed after t's close | ATR uses bars up to and including t only; changing t+1's bar changes nothing decided at t |
| AD-P3-24 | U | A bar read for the wrong session | refused by `session_bars`, logged |

## C. Exit orders and fills

| ID | L | Case | Expected |
|---|---|---|---|
| AD-P3-30 | I | Stop touched inside the bar, shares | SELL order for the remaining quantity, filled at 970 less spread and slippage, `autodesk-fill-v1`, charges from `desk-cost-v2` |
| AD-P3-31 | I | Gap through the stop | filled at the session open (adverse), which is worse than the stop; the exit record says `gapped` |
| AD-P3-32 | I | Exit quantity above 10 % of the session's traded quantity | partial fill in whole lots; remainder carries to the next session on the same intent; the stop stays on the remainder |
| AD-P3-33 | I | Contract untraded that session, or failed read | no fill; position flagged `EXIT_BLOCKED_NO_DATA`; retried next session; never priced from an old bar |
| AD-P3-34 | I | Same seed, same exit | identical fill; a different seed gives a different slippage factor |
| AD-P3-35 | I | Exit order for a quantity greater than the remaining quantity | refused `QUANTITY_EXCEEDS_REMAINING` |
| AD-P3-36 | I | Target 1 with `exit_fraction` 0.5 of 100 shares | 50 shares sold; remaining 50; risk recalculated; stop unchanged (or at cost, tighten only, if the plan says so) |
| AD-P3-37 | I | Target 1 fraction gives a part-lot (1 lot of 500, fraction 0.5) | rounded down to whole lots (0); no partial exit; stated, the position is not corrupted |
| AD-P3-38 | I | Target 1 then target 2 then the stop on the remainder | three exit records; remaining quantities 100 → 50 → 25 → 0; one closed position |
| AD-P3-39 | I | The market touches a target but the exit order is volume-capped | quantity moves only by fills; a touch alone changes nothing |

## D. Closure, ledger and reconciliation

| ID | L | Case | Expected |
|---|---|---|---|
| AD-P3-40 | I | Hand check: 100 shares bought at ₹1,000.50 (fees f1), sold at ₹1,060.00 (fees f2) | realized gross = 100 × (1,060.00 − 1,000.50) = 5,950.00; net = 5,950.00 − f1 − f2; the arithmetic is shown in the report |
| AD-P3-41 | I | Ledger rows of an exit | `POSITION_FUNDS` (proceeds), `FEES_BOOKED`, `REALIZED_PNL` (no cash by itself), `MARGIN_RELEASED` for futures; all in one transaction with the order and position update |
| AD-P3-42 | I | Futures: 1 lot (500) bought at 1,000, sold at 1,040 | realized gross 20,000.00; margin 75,000 released; cash change equals gross − fees |
| AD-P3-43 | I | Debit spread 500 × (30 − 12), closed at (36 − 9) | realized by leg; net = Σ legs − fees; both legs close in one basket |
| AD-P3-44 | I | Credit spread width 10,000, credit 3,500, closed for 1,200 debit | realized 2,300 gross; margin 10,000 released; buying power returns by margin + realized − fees |
| AD-P3-45 | I | A closed position | `status` CLOSED, remaining quantity 0, open risk and capital 0, reservation consumed + released = amount, `CLOSURE` journal row, `trade_exit_records` written |
| AD-P3-46 | I | Reconciliation after **every** exit fill, including partials | equity = cash + Σ position market value, difference 0.00; Σ realized = proceeds − cost of exited quantity; Σ closed + remaining = filled; journal complete |
| AD-P3-47 | I | A tampered ledger (a planted delta in a copy) | reconciliation reports the non-zero difference and the position goes `RECONCILIATION_REQUIRED`; automatic actions for it stop |
| AD-P3-48 | I | Append-only | exit, ledger, lifecycle and journal rows cannot be updated or deleted (trigger) |
| AD-P3-49 | I | Two exits racing on one position | account row lock: the second sees the first's fills; no double sale; remaining quantity never negative |
| AD-P3-50 | I | Process stops mid-exit, then restarts | the half-done exit is finished or refused from durable state; no blind replay of the order; one fill |

## E. Lifecycle states

| ID | L | Case | Expected |
|---|---|---|---|
| AD-P3-60 | U | Allowed and refused moves in `LIFECYCLE_TRANSITIONS` | every PRD §8.2 move used here is allowed; CLOSED → ACTIVE_POSITION and SETTLED → anything are refused (`IllegalTransition`) |
| AD-P3-61 | I | Entry fill to settled | ACTIVE_POSITION → EXIT_PENDING → CLOSED → SETTLED, each a `trade_lifecycle_events` row with reason and session |
| AD-P3-62 | I | Partial exit | EXIT_PENDING → PARTIAL_EXIT → EXIT_PENDING → CLOSED |
| AD-P3-63 | I | An exit order that is submitted but not filled | state EXIT_PENDING, not CLOSED; a submitted exit is not a closed position |
| AD-P3-64 | I | CLOSED but reconciliation differs | stays CLOSED, never SETTLED; RECONCILIATION_REQUIRED with the invariant named |
| AD-P3-65 | I | Restart | active positions, working orders, exit state and last processed point are read from the database; the manager reconciles before acting |

## F. Expiry settlement (real data only)

| ID | L | Case | Expected |
|---|---|---|---|
| AD-P3-70 | I | Futures leg on its expiry day with a settlement price in the file | settles at that price; `REALIZED_PNL`, `MARGIN_RELEASED`, `SETTLEMENT` journal row |
| AD-P3-71 | I | Long call, underlying settles above strike | settles at intrinsic value (settlement − strike) × quantity, cash credited |
| AD-P3-72 | I | Long put out of the money | settles at zero; premium already paid is the loss; position CLOSED, reconciled |
| AD-P3-73 | I | Settlement price missing for the day | no price assumed: position `RECONCILIATION_REQUIRED` with `SETTLEMENT_DATA_MISSING`, stays open, reported |
| AD-P3-74 | I | Data lands later (F&O visible 22:45 IST) | the next pass settles it; history shows both steps |
| AD-P3-75 | I | Plan with `exit_days_before_expiry` 2 | the position is exited two sessions before expiry by the exit path, never reaching settlement |
| AD-P3-76 | I | Spread with one leg in the money and one out | both settle in one unit; net matches the sum |

## G. Limits and controls

| ID | L | Case | Expected |
|---|---|---|---|
| AD-P3-80 | I | Daily loss reaches 2 % of equity | risk-engine daily check FAILs for new entries until the next session; managed exits continue; a `LIMIT_ACTION` row |
| AD-P3-81 | I | Weekly loss reaches 4 % | same, until the next IST week |
| AD-P3-82 | I | Drawdown reaches 10 % | account suspended, state `RISK_BREACH`, event for escalation; exits continue; only a recorded human action lifts it |
| AD-P3-83 | I | P&L within the limits | checks PASS and show the measured values; no action |
| AD-P3-84 | I | Marks stale when a limit is judged | conservative reading (last mark, flagged stale), said in the result |
| AD-P3-85 | I | `SUSPEND_AUTOMATED_MODIFICATIONS` | trail stops moving, existing stops stay, exits continue |
| AD-P3-86 | I | `CANCEL_PENDING_ENTRIES` | working entry orders withdrawn with reservations released; exit orders untouched |
| AD-P3-87 | I | `REDUCE_ONLY` | the manager closes positions per policy order, all-or-none per trade; no new entries; every action a journal row |
| AD-P3-88 | I | Any control active | no position is left without its stop; the protective exit state is never deleted |
| AD-P3-89 | I | Controls on a simulation of past sessions | not applied (desk accounts only), as `STOP_NEW_ENTRIES` |
| AD-P3-90 | I | `amend` a working order toward the market, or smaller | allowed through `MODIFY_PENDING`, history row |
| AD-P3-91 | I | `amend` that raises quantity or loosens a limit | refused `AMEND_RAISES_RISK` |
| AD-P3-92 | I | UNKNOWN order, engine has a fill | the fill is applied once; order ends FILLED |
| AD-P3-93 | I | UNKNOWN order, engine has no fill | order ends EXPIRED per the transition table; reservation released after; no blind resubmit |

## H. Live path and the day's final mark

| ID | L | Case | Expected |
|---|---|---|---|
| AD-P3-100 | I | Fresh quote through the stop on the live tick | exit fills from that quote only; `price_source` names the quote and its `received_at` |
| AD-P3-101 | I | Quote missing or older than 120 s | no exit fill; position flagged; the stop is kept and the manager says so |
| AD-P3-102 | I | Cash exit after 15:15, F&O after 15:30 | waits; nothing is read or filled |
| AD-P3-103 | I | After the close: last live mark, then Kite close, then exchange end-of-day | the day's final mark follows that order; the source is stored on the mark |
| AD-P3-104 | I | Exchange end-of-day price lands and differs | a correction row (new `MARK` journal row, snapshot revision), the original kept; says which source replaced which |
| AD-P3-105 | I | Kite login expired after the close | waits for the exchange price; says so; reads no Kite price |
| AD-P3-106 | G | Order-path guard and the AD-91 isolation check | still pass; the exit path adds no order verbs but `submit`, `amend`, `withdraw` |

## I. Read APIs

| ID | L | Case | Expected |
|---|---|---|---|
| AD-P3-110 | A | The §11 routes signed out | 401 |
| AD-P3-111 | A | Another tenant's position, account or trade id | 404 |
| AD-P3-112 | A | `GET /positions/{id}/lifecycle` | state, history, exit state with stop history and rule versions, pending exits |
| AD-P3-113 | A | `GET /trades/closed` | prices, quantities, reasons, gross and net realized, charges, holding sessions, `reconciled` |
| AD-P3-114 | A | `GET /accounts/{id}/pnl` | realized non-zero after closes; `by_reason`; daily split; values equal the ledger sums |
| AD-P3-115 | A | `GET /accounts/{id}/limits`, `/reconciliation` | measured values, limits, states; each invariant and its difference |
| AD-P3-116 | A | `GET /simulations/{id}/results` | gains `closed_trades`, `win_rate`, `realized_pnl_rs`, `exits_by_reason`, `reconciliation`; existing keys unchanged |
| AD-P3-117 | A | Every text field in the new answers | holds none of: buy, sell, stop loss, SL, target, entry, exit, accumulate, book profit, upside, price target, recommend, pick (enum and field names exempt) |
| AD-P3-118 | A | Phase 2 reads with the lifecycle wired and unwired | unchanged keys and values when unwired |

## J. Determinism and the real-data replay

| ID | L | Case | Expected |
|---|---|---|---|
| AD-P3-120 | I | Same seed twice over a crafted 12-session set | identical fingerprint (now covering exit rows) |
| AD-P3-121 | I | Different seed | different fingerprint |
| AD-P3-122 | I | Replay fingerprint is independent of order ids and of the order orders are processed in | equal |
| AD-P3-123 | R | Real-data replay, at least 20 sessions (for example 5 Oct to 6 Nov 2026), throwaway database | positions managed from fill to closure; every reconciliation difference 0.00; no read outside the clock session; the run's numbers shown. **UNVERIFIED until run** |
| AD-P3-124 | R | The same replay with the same seed again, and with another seed | same fingerprint; different fingerprint |
| AD-P3-125 | R | Hand-check at least three closures against real prices | the arithmetic shown in the report: entry fill, exit fill, charges, realized, net |
| AD-P3-126 | R | Expiry in the window, if one falls in it | settles at the real settlement data, or the missing-data failure is shown |
| AD-P3-127 | R | The scan time of the replay | stated, not a target; sessions per minute |

The real-data cases need the credentialed container. If the safety check refuses it, they stay UNVERIFIED with that reason; no other way is tried.
