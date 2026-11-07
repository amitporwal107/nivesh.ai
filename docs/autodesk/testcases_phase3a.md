# Phase 3A test cases (AD-P3-*): fill to reconciled closure — written before the code, 7 Nov 2026

Design: `PHASE3_DESIGN.md`. Phase 2 cases (AD-P2-*) in `TESTCASES.md` keep running unchanged. Layers: **U** unit (pure, test doubles),
**I** integration (throwaway Postgres), **A** API (FastAPI app, faked sign-in), **R** real-data replay (throwaway database, read-only data
API; UNVERIFIED until run and its output shown), **G** guard. Test doubles and crafted rows are labelled TEST DATA / MOCK in code.
Phase 2 fill parameters apply (half spread 0.05 % shares, 0.02 % futures, 0.50 % options; slippage 3 / 2 / 20 bps × seeded 0.5–1.5;
volume share 10 %); costs `desk-cost-v2`. Shares long unless stated. "Level" = invalidation level; "objective" = plan target.

## A. Rules from the plan (pure, `lifecycle/rules.py` over `services/exit_rules`)

| ID | L | Case | Expected |
|---|---|---|---|
| AD-P3-01 | U | Share plan: level 960, objectives 1060 (0.5) and 1100 (1), 10 sessions, `trail-atr-v1 (2 × ATR14)`; filled at 1003.50 | Rules: side long, objective 1060 first, `max_hold_sessions` 10, k 2, period 14; State entry 1003.50 (the fill, not the plan price), level 960 v1 |
| AD-P3-02 | U | Future plan, level 960 on the underlying; entry-session previous closes: future 1010, share 1000 | trigger = the future's own row, levels × 1.01 (969.60), ratio and its source stored |
| AD-P3-03 | U | Bull call spread, BULLISH, level 960 | trigger = `EQ:<underlying>`, side long, levels as given; BEARISH put spread → side short |
| AD-P3-04 | U | Iron condor (NEUTRAL) | no level or objective rule; holding period, pre-expiry and settlement only; says why |
| AD-P3-05 | U | `exit_rules` text without `trail-atr-v1` / with `trend-ema-v1` named | trail off / trend on with its period; a rule that is off changes nothing |
| AD-P3-06 | U | Pre-expiry: expiry Thu 26 Nov, `close_days_before_expiry` 2, sessions known | closing session Tue 24 Nov; with no calendar loaded, weekdays only and the basis says so |

## B. Decisions and the clock (U, over a crafted series)

| ID | L | Case | Expected |
|---|---|---|---|
| AD-P3-10 | U | OPEN: trigger open 950 below the level 960 in force | closing at the open (`gapped`), never at 960 |
| AD-P3-11 | U | OPEN decision is given an open-only bar | high, low and close are not passed; the state is unchanged when nothing is decided (no ATR or high-water update from an open) |
| AD-P3-12 | U | CLOSE: low 955, high 1010 (level 960) | `stop` at level 960 (`level`) |
| AD-P3-13 | U | CLOSE: low 955 and high 1070 (level 960, objective 1060) | `stop`, `both_in_range` true (adverse level wins) |
| AD-P3-14 | U | CLOSE: high 1060.00 exactly (objective 1060), low 1001 | a touch: objective NOT filled (traded through required); state continues with the trail stepped |
| AD-P3-15 | U | CLOSE: high 1061, objective 1060 (0.5 of 100 shares) | 50 shares at 1060.00 exactly (passive, no spread or slippage); objective 2 is next; position stays |
| AD-P3-16 | U | Objective fraction 0.5 of 1 lot | rounds to 0 lots → the whole remainder closes (default 7) |
| AD-P3-17 | U | 10 sessions held, no touch | `time` at the 10th session's close |
| AD-P3-18 | U | Trail: rising highs raise the level; a lower session | level only rises; each change a new version; in force from the NEXT session; ATR unavailable says so |
| AD-P3-19 | U | Folding the manager's decisions over a 12-session crafted series | equals folding `exit_rules.step` over the same bars (no second engine) |
| AD-P3-20 | U | Opening limit filled at the CLOSE | not stepped that session; first step the next session |

## C. Closing prices (pure, `lifecycle/pricing.py`)

| ID | L | Case | Expected |
|---|---|---|---|
| AD-P3-25 | U | Share closing at the open 950 (long, 100 shares) | price = to_tick(950 − half spread − slippage) on the tick, ≤ 950, ≥ the row's low |
| AD-P3-26 | U | Share closing at the level 960 (touched) | arrival 960, adverse spread + slippage, never below the row's low |
| AD-P3-27 | U | Option leg closing at the close | the leg's own close, adverse spread (≥ one tick) + slippage, inside the leg's low–high |
| AD-P3-28 | U | Leg with no row / zero volume | REST `CLOSE_BLOCKED_NO_DATA`, no price |
| AD-P3-29 | U | Order bigger than 10 % of the session's traded quantity | partial in whole lots; the rest carries |
| AD-P3-30 | U | Same seed / other seed for one closing order | identical / different prices (stream `…|CLOSE|<reason>|<n>`) |

## D. Closure and the books (I)

| ID | L | Case | Expected |
|---|---|---|---|
| AD-P3-35 | I | Share position closed in full at the level | ledger POSITION_FUNDS (+value, notional − cost), FEES_BOOKED, REALIZED_PNL (gross = value − cost), MARGIN_RELEASED (risk −); position CLOSED → SETTLED; equity = cash + 0; every reconciliation difference 0.00; hand arithmetic shown |
| AD-P3-36 | I | Partial objective (50 of 100) then the level on the rest | two closings; after each: leg quantity, `closed_qty`, realized, open risk halved, reconciliation 0.00; duplicate decision same session → no second order |
| AD-P3-37 | I | Futures position closed | cash moves by realized gross − charges only; margin released in full; notional back to 0 |
| AD-P3-38 | I | Bull call spread closed as a unit at the closes | both legs in one closing intent; long leg sold, short leg bought back; realized per leg; one leg without a row → nothing fills, `CLOSE_BLOCKED_NO_DATA`, pending to next OPEN |
| AD-P3-39 | I | Credit spread closed | width margin released; buying power back to opening capital + net realized; reconciliation 0.00 |
| AD-P3-40 | I | Volume-capped closing | partial now, the rest at the next OPEN (open price), level not loosened, journal shows both |
| AD-P3-41 | I | Journal of a closed trade | … FILL, POSITION, MARK…, CLOSING_DECISION, CLOSING_FILL, CLOSURE, RECONCILIATION in order; no AD-92 word in any summary |
| AD-P3-42 | I | Lifecycle states | ACTIVE_POSITION → EXIT_PENDING → PARTIAL_EXIT → EXIT_PENDING → CLOSED → SETTLED, each a row; an illegal move raises |

## E. Expiry settlement (I)

| ID | L | Case | Expected |
|---|---|---|---|
| AD-P3-45 | I | Long call held to expiry, underlying close 1040, strike 1000 | settled at 40 × qty; no fill row; exit record `settlement`; charges per the cost card's convention |
| AD-P3-46 | I | Worthless leg (OTM) | settles at 0; closing side's brokerage + GST still charged |
| AD-P3-47 | I | Future held to expiry | settled at the row's `settle_price` |
| AD-P3-48 | I | Expiry row missing / no settle price / no underlying close | no price assumed: position stays OPEN, `RECONCILIATION_REQUIRED`, flag `SETTLEMENT_DATA_MISSING`; retried next CLOSE |

## F. Limits (I)

| ID | L | Case | Expected |
|---|---|---|---|
| AD-P3-50 | I | Session loss 2.5 % of the previous snapshot (limit 2 %) | `/limits` daily BREACHED; next session's new intent REFUSED `DAILY_LOSS_LIMIT`; closings still happen |
| AD-P3-51 | I | Week-to-date loss 4.2 % | `WEEKLY_LOSS_LIMIT` until the week ends; a new week clears it |
| AD-P3-52 | I | Drawdown 10.5 % from the peak | SUSPEND_ACCOUNT active by `RISK_LIMITS`; intents refused `ACCOUNT_SUSPENDED`; open positions still close by their rules |
| AD-P3-53 | U | Risk engine with a book carrying the measures | `daily_loss`, `weekly_loss`, `drawdown` PASS/FAIL (hard), not SKIPPED; a book without measures stays SKIPPED |

## G. Amend, controls, close requests, UNKNOWN (I / A)

| ID | L | Case | Expected |
|---|---|---|---|
| AD-P3-55 | I | Amend an OPEN single-leg opening LIMIT: fewer lots, lower limit | OPEN → MODIFY_PENDING → OPEN, history rows, quantity and limit changed |
| AD-P3-56 | I | Amend raising lots or the limit; amend a basket leg or a filled order | refused (`AMEND_RAISES_RISK` / `AMEND_NOT_ALLOWED`), nothing changed |
| AD-P3-57 | I | SUSPEND_AUTOMATED_MODIFICATIONS on | the trail does not move; the level in force still closes the position |
| AD-P3-58 | I | CANCEL_PENDING_ENTRIES | working opening orders CANCELLED and reservations released; closing orders untouched |
| AD-P3-59 | I | REDUCE_ONLY on an account | new intents refused; open positions closed at the next priceable moment (`risk_control`) |
| AD-P3-60 | I | SUSPEND_STRATEGY LONG_EQUITY | a LONG_EQUITY intent refused `STRATEGY_SUSPENDED`; other strategies pass |
| AD-P3-61 | I | Close request on a desk position | closed at the next fresh quote (`manual`); a second request does nothing new |
| AD-P3-62 | I | An order left UNKNOWN by an adapter failure | reconciler ends it EXPIRED with the reason, intent finished, reservation released; never resubmitted |

## H. Live path (I, FakeQuotes; MOCK quotes)

| ID | L | Case | Expected |
|---|---|---|---|
| AD-P3-65 | I | Fresh quote LTP below the level | closing priced by `decide_quote` (bid side), filled, books as §5 |
| AD-P3-66 | I | Quote stale / missing | no closing fill; position flagged, pending kept; next fresh tick closes |
| AD-P3-67 | I | Outside the fill window (cash after 15:15) | nothing read for that leg, nothing filled |
| AD-P3-68 | I | 15:41: final mark from the Kite close (fresh) / no quote | snapshot `mark_basis` KITE_CLOSE / LIVE_LAST, said in the journal |
| AD-P3-69 | I | Exchange EOD close differs from the 15:41 mark | leg re-marked EXCHANGE_EOD, MARK journal row names both sources, snapshot rewritten, old one in `equity_snapshot_revisions` |

## I. APIs and wiring (A, I)

| ID | L | Case | Expected |
|---|---|---|---|
| AD-P3-75 | A | Every new route signed out / another tenant | 401 / 404 (or empty list) |
| AD-P3-76 | A | `/positions/{id}/lifecycle`, `/trades/closed`, `/execution/exit-records`, `/lifecycle/events`, `/accounts/{id}/limits`, `/accounts/{id}/reconciliation` | shapes of §11; money as strings |
| AD-P3-77 | I | `/simulations/{id}/results` after a run with closings | `closed_trades`, `win_rate`, `realized_net_rs`, `exits_by_reason`, reconciliation all 0.00, fingerprint |
| AD-P3-78 | I | Gateway with no lifecycle wired | Phase 2 behaviour exactly (all AD-P2 tests pass unchanged) |
| AD-P3-79 | I | Simulation through the manager over 3 crafted sessions | positions opened, managed and closed; same seed same fingerprint; other seed differs |

## J. Guards

| ID | L | Case | Expected |
|---|---|---|---|
| AD-P3-85 | G | No string literal in `lifecycle/*.py` uses an AD-92 word (the Phase 2 source scan extended) | none |
| AD-P3-86 | G | Order-path guard, AD-91 | green; no place/modify/cancel order code; `LIVE_EXECUTION_AVAILABLE = False` |
| AD-P3-87 | G | Every fill-engine read during a simulation | session read = clock session (the read log) |
| AD-P3-88 | G | Result text and limitations | no "positions stay open" / "not enforced" text once the lifecycle is wired |

## R. Real data (throwaway database, data API read-only)

| ID | L | Case | Expected |
|---|---|---|---|
| AD-P3-90 | R | Replay ≥ 20 sessions (e.g. 5 Oct – 6 Nov 2026) with real agents, gateway and lifecycle | completed; positions opened and closed by their rules; counts by reason |
| AD-P3-91 | R | Every reconciliation run of the replay | all differences 0.00 |
| AD-P3-92 | R | Same seed twice; another seed | fingerprints equal; differs |
| AD-P3-93 | R | Fill-engine read log | 0 reads outside the clock session |
| AD-P3-94 | R | Hand check of at least three closings against the exchange rows read again | price rule, quantity, charges, realized arithmetic shown |
| AD-P3-95 | R | One real Zerodha quote on the live closing path | UNVERIFIED while the Kite login is expired |
