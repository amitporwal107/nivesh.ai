# Autonomous Trading Desk — Phase 3A design: from fill to reconciled closure

Written 7 Nov 2026 by Account 2 (continuing Account 1's package, owner's request) for the owner, the engineers and whoever builds
screens against the read APIs in §11. Status: **design and test cases only; no Phase 3 code exists yet.** Specs: `source/PRD_v2.0.md`
§8 (Trade Lifecycle Manager), §10.4 (emergency controls), §16.5, Phase 3 exit criteria; `PHASE2_DESIGN.md` (this builds on it, §11 lists
what it defers to here). Test cases: `testcases_phase3a.md` (AD-P3-*). Slice 3B (scenarios, pause/resume, run comparison, agent
timeline) is not designed here.

**Exit for 3A (brief):** a real-data replay of at least 20 sessions on a throwaway database where positions are managed from fill to
closure; every reconciliation difference 0.00; same seed same fingerprint, different seed different; no read outside the clock's session.

## 1. Decisions that bind this phase

| # | Decision | Source |
|---|---|---|
| L1 | **No order placement.** Exits are paper orders through the same gateway verbs (`submit` / `amend` / `withdraw`). `LIVE_EXECUTION_AVAILABLE = False`; `tests/test_order_path_guard.py` stays green. | Owner |
| L2 | **Zerodha gives live quotes only, read-only.** The live path prices an exit from a fresh quote exactly as Phase 2 prices an entry. | Owner |
| L3 | **No stale market data, no fabricated price, no silent fallback.** Missing data for an exit or a settlement is a stated failure that keeps the position open and flagged. | Owner rule 28 Oct |
| L4 | **No hindsight.** A simulated decision sees only what its clock allows (§4). | Brief, PRD §28.4 |
| L5 | **The manager only reduces risk.** It never widens a stop, adds quantity, adds leverage or raises approved downside without fresh authorisation (PRD §8.5). Stops move one way. | PRD §8.5 |
| L6 | One rule engine: `backend/services/exit_rules.py` (`exit-rules-v1`: `step`, `start`, `Rules`, `State`). This phase adapts it; it does not write a second one. | Brief |
| L7 | v1 scoring stays the only active selector. Nothing here reads shadow scores. | Standing rule |
| L8 | Generated narrative (reasons, journal text, API `summary` strings) avoids the AD-92 words. Field names and enum values may use trading words (`side: SELL`, reason `stop`). | Owner rule |
| L9 | Shares and futures with no long put show loss at the invalidation level, never the stock at zero (as in plan sizing). | Brief |

## 2. Shape

```
backend/autodesk/execution/            (additions; Phase 2 files change only where §10 says)
  lifecycle.py    the manager: one pass per clock moment over open positions; state machine; persists every move
  exits.py        adapter from a position + its plan's exit_rules to services.exit_rules (state per trade, one step per session)
  closure.py      exit fills -> realized P&L, closing charges, MARGIN_RELEASED, reservation / risk release, closed-trade record
  expiry.py       settlement of F&O positions at expiry from real exchange data; refusal when the data is missing
  limits.py       daily, weekly and drawdown limits acting on P&L (§8)
  recon.py        reconciliation: ledger = positions = journal at every step; UNKNOWN orders (§9)
backend/autodesk/db/migrations/004_lifecycle.sql
backend/autodesk/routers/lifecycle.py  read APIs (§11)
```

The simulator calls the manager at the same two moments Phase 2 uses (OPEN and CLOSE) plus an expiry step; the live loop calls it on
each tick. With no lifecycle wired both behave exactly as in Phase 2 (positions stay open), so Phase 2's tests keep running.

## 3. Lifecycle states (PRD §8.2) and data model

A position's `lifecycle_state` (new column on `trade_positions`; `status` stays OPEN / CLOSED):

```
ACTIVE_POSITION -> (RISK_MANAGEMENT while a stop moved or a limit is near, informational)
ACTIVE_POSITION | PARTIAL_EXIT -> EXIT_PENDING (an exit order is working)
EXIT_PENDING -> PARTIAL_EXIT (some quantity left) | CLOSED (zero left)
CLOSED -> SETTLED (reconciled: ledger, position, journal agree to 0.00; F&O settlement done)
any -> RECONCILIATION_REQUIRED | EXECUTION_ERROR | SUSPENDED | RISK_BREACH   (stated reason; leaves only through a recorded action)
```
An exit order is not a closed position: CLOSED needs filled quantity to bring the remaining quantity to zero, SETTLED needs the
reconciliation to pass (PRD §8.2). Moves outside `LIFECYCLE_TRANSITIONS` (a table in `contracts.py`, additive) raise `IllegalTransition`.

Migration 004 (additive; append-only tables refuse UPDATE and DELETE by trigger):

| Table | Kind | What it holds |
|---|---|---|
| `trade_lifecycle_events` | append-only | every state move: from, to, reason, session, sim time, wall time, actor (`tlm`) |
| `trade_exit_state` | head row | per trade: `exit-rules-v1` `State` as JSON (stop, stop_history, high-water mark, ATR state), `rules` JSON with versions, `stop_version` |
| `trade_exit_records` | append-only | one per exit fill group: reason (`stop`, `trailing_stop`, `target`, `time`, `trend`, `expiry`, `manual`, `risk_control`), session, level, fill price, gapped / both_in_range flags, quantity, realized gross, charges, link to order and fills |
| `trade_actions` | append-only | proposed and taken actions (PRD §16.5 `trade_action_proposals`): action, authority (pre-authorised / approval needed), status, idempotency key |
| `trade_positions` additions | columns | `lifecycle_state`, `remaining_qty`, `realized_gross_rs`, `closed_at`, `close_reason`, `settled_at` |
| `trade_position_legs` additions | columns | `closed_qty`, `exit_avg_price`, `realized_gross_rs` |

New ledger entry types already exist in `LedgerEntry` (`REALIZED_PNL`, `MARGIN_RELEASED`); new journal kinds: `EXIT_DECISION`, `EXIT_ORDER`,
`EXIT_FILL`, `CLOSURE`, `SETTLEMENT`, `LIMIT_ACTION`. New event types are additive.

## 4. Exits

### 4.1 Rules per position
Rules come from the approved plan version (never from the model): invalidation level (`invalidation.underlying_level`, `max_loss_exit_rs`),
targets with `exit_fraction` (`TargetLevel`), `holding.max_holding_days` (counted in **sessions held**, not days), `exit_rules.trailing`
(`trail-atr-v1`, tighten only) and the plan's `exit_days_before_expiry`. Stop, target and time are always on; `trail-atr-v1` only when the plan
says so. `exits.start()` builds the `State` from the actual average fill price and the plan's stop, once, when the position opens.

### 4.2 What the clock allows (L4)
For session *t*, in this order, exactly as `services/exit_rules.step` orders it, and each step sees nothing later:

| Clock moment | Decision sees | Decides |
|---|---|---|
| Session OPEN (09:15) | the session's `open`, the stop as it stood at the previous close, the previous close's trend flag | gap through the stop (fills at the real **open**, worse than the stop), a trend exit signalled at the previous close |
| Session CLOSE (15:30) | the whole bar of session *t* | an intrabar touch of the stop or a target; both in one bar means the **stop** (the adverse level wins); expiry; time exit at the close of session *max_hold* |
| After CLOSE | bars up to and including *t* | trail raise for the next session (ATR up to and including *t*), trend flag; never before the bar is known |

The bar reader is Phase 2's `market/session_bars.py`: it refuses any session but the clock's. Every read is logged and the tests assert none
is outside the clock session (AD-P3 checks the log). The **agents** still cannot read the session being simulated.

### 4.3 How an exit becomes a fill
A decision creates an **exit order** (side opposite to the leg, quantity from the remaining quantity and `exit_fraction`, in whole lots),
through `gateway.submit` with idempotency key `<trade_id>:EXIT:<session>:<reason>:<n>`, so a duplicate partial exit is impossible. The fill uses
`autodesk-fill-v1` with the same costs and rules as entries:

| Exit | Fill price | Why |
|---|---|---|
| Gap through the stop | the session **open**, adverse spread and slippage | never at the stop level the market skipped |
| Stop touched inside the bar | the stop level, adverse slippage | a resting stop order triggers at its level |
| Target touched | the target level, no credit for a better open (as `exit_rules`) | resting limit; touch fills, as the desk fill model |
| Time or trend exit | the close (time) or next open (trend) with spread and slippage | market exit |

Volume cap (10 % of the session's traded quantity, whole lots): a larger exit is **partial** and the rest carries to the next session as the
same intent; the stop level stays in force on the remainder. An untraded contract or a failed read does not fill: the exit stays pending, flagged
(`EXIT_BLOCKED_NO_DATA`), and is retried next session. It is never priced from an old bar. Multi-leg exits are all-or-none (§4.4).

### 4.4 Multi-leg positions
Close as a unit unless the plan says otherwise: a single basket with `net_limit_rs` (as entries), every leg priced from its own contract row.
Conditions use the plan's basis (`UNDERLYING` for the invalidation and targets): the underlying's bar decides, and each leg is priced from its
own row. If any leg cannot be priced that session the whole basket waits (stated), so one leg is never left naked by the manager. The plan's
emergency rule ("close every leg together if any leg cannot be managed") is what the `exit_rules.emergency` text says; it maps to a
`risk_control` exit that uses the same all-or-none basket.

### 4.5 Partial exits
Target 1 exits its `exit_fraction` of the **remaining** quantity, rounded down to whole lots; the stop is not loosened and, when the plan
says so, moves to cost after target 1 (tighten only). The partial updates `remaining_qty`, risk (recalculated after every fill), the pending
reservation figures and the leg's `closed_qty`. A target is not assumed filled because the market touched it: only an exit fill moves quantity.

## 5. Closure and the books

Every exit fill posts, in one transaction with the order and position updates (the ledger stays append-only):

| Ledger row | Meaning |
|---|---|
| `POSITION_FUNDS` | proceeds (sale value of shares and premium received) or premium paid to close a short leg: cash moves |
| `FEES_BOOKED` | closing charges (`desk-cost-v2`, brokerage once per order) |
| `REALIZED_PNL` | gross realized on the quantity closed: proceeds − cost of that quantity at the leg's average price, signed per side. It moves **no cash** by itself (the cash moved with `POSITION_FUNDS`); it exists so realized P&L can be summed |
| `MARGIN_RELEASED` | the margin held for the closed quantity: futures notional × `futures_margin_pct`; credit structures their share of the width |

When remaining quantity reaches zero: `trade_positions.status = CLOSED`, open risk and capital zero, the reservation's remaining amounts are
closed (consumed + released = amount), `trade_exit_records` and a `CLOSURE` journal row are written. Net realized = gross realized − all fees
(entry and exit). `equity_snapshots` gains realized and unrealized split by day; max drawdown reads equity, as before.

**Reconciliation invariants (checked after every exit fill, at every session end, and reported):**
1. equity = cash balance + Σ open position market value (Phase 2's invariant), difference 0.00;
2. Σ `REALIZED_PNL` over a trade = (Σ exit proceeds − Σ cost of exited quantity) for that trade;
3. Σ ledger cash deltas = opening capital + Σ fund movements (no cash from nowhere);
4. Σ leg `closed_qty` + `remaining_qty` = filled entry quantity, per leg;
5. journal rows exist for every entry fill, exit fill and closure, one each, in order;
6. reservation: consumed + released = amount once closed.
Any non-zero difference moves the position to `RECONCILIATION_REQUIRED`, stops its automatic actions, and shows in the API and the report.

## 6. Expiry settlement of F&O (real data only)

On the expiry session an open futures or option leg is settled, not exited: **futures** at the exchange's settlement price for that day;
**options** at intrinsic value against the underlying's final settlement price (the `settle` / underlying close of that expiry day from the
F&O file the desk already reads). Both come from `FnoContract.settle` / `underlying_price` on the contract's expiry-day row; settlement posts
`REALIZED_PNL`, the cash for in-the-money legs, `MARGIN_RELEASED`, `FEES_BOOKED` (settlement charges from the cost card where defined) and a
`SETTLEMENT` journal row. **If the settlement data for that day is missing or the row carries no settlement price: no price is assumed.** The
position becomes `RECONCILIATION_REQUIRED` with reason `SETTLEMENT_DATA_MISSING`, stays open, is retried when data lands (F&O end-of-day
data is visible from 22:45 IST), and is reported. The plan's `exit_days_before_expiry` exits first when it applies, so settlement is the exception.

## 7. Amend and emergency controls

- **`amend`** (`MODIFY_PENDING`): allowed only on a working order and only to a more conservative change (a limit toward the market, a smaller
  quantity). Anything that raises risk is refused `AMEND_RAISES_RISK`. Exit stops are not orders in this engine; they are `trade_exit_state`
  and tighten through `exit_rules.manual_stop` (never loosen).
- **Controls beyond `STOP_NEW_ENTRIES`** (PRD §10.4; desk accounts only, simulations of past sessions are not affected): `SUSPEND_AUTOMATED_MODIFICATIONS`
  (the trail stops moving; stops stay), `CANCEL_PENDING_ENTRIES` (withdraws working entry orders, never an exit), `SUSPEND_ACCOUNT` (no new
  entries; managed exits continue), `REDUCE_ONLY` (controlled risk-reducing exits: the manager closes positions by its policy order, all-or-none
  per trade). **None of them cancels a protective exit or leaves a position without its stop** (PRD §10.4). Each activation and lift is an
  event and a journal row, and an idempotent write like `STOP_NEW_ENTRIES`.

## 8. Daily, weekly and drawdown limits (policy `daily_loss_pct` 2, `weekly_loss_pct` 4, `max_drawdown_pct` 10 by default)

`risk_engine` today marks these SKIPPED (`LOSS_LIMITS_SKIP`). From this phase they read P&L: **daily** = net realized + change in unrealized
since the previous session's close snapshot; **weekly** = since the first session of the IST week; **drawdown** = equity vs its running peak
(`reports.drawdown`). Acting:

| Breach | Automatic action | Authority |
|---|---|---|
| Daily loss limit | block new entries for the account until the next session (`risk_engine` check turns FAIL); managed exits continue | automatic (PRD §8.5) |
| Weekly loss limit | same, until the next week | automatic |
| Drawdown limit | `SUSPEND_ACCOUNT`, state `RISK_BREACH`, event for escalation | automatic suspension, a human lifts it |

Limits use the same ledger and marks as everything else: no second P&L. A limit breach evaluated on stale marks says so and uses the
conservative reading (the last mark, flagged stale).

## 9. Reconciliation of UNKNOWN orders

Paper adapters have no external state, so `UNKNOWN` arises only from an adapter failure between submit and acknowledgement. `recon.py` resolves
each: it asks the paper engine (the order head row and any fills), then ends the order `EXPIRED` per `ORDER_TRANSITIONS[UNKNOWN]` when the engine
has no fill, or applies the fill that exists. It never resubmits blindly. The reservation stays held until the order is resolved (as Phase 2).

## 10. The live path, and the end-of-day mark rule

The live loop adds one pass of the manager to each tick, after the quote read Phase 2 already does: the same fresh-quote rules (≤ 120 s old,
today's, traded today), a stop or target is judged on the fresh quote, and an exit fills only from one (L2, L3). No quote or a stale one: no
exit fill, the position is flagged, the stop stays (the manager says so, it does not pretend). Fill windows: cash until 15:15, F&O until 15:30.

**Day's final mark (owner rule: live → Kite close → exchange end-of-day).** Phase 2 writes the snapshot at 15:31. From this phase the day's final
mark follows the rule: the last fresh live mark of the day, else the Kite close from the quote read after the close, else the exchange's end-of-day
price once it is published (cash 19:30 IST, F&O 22:45 IST). When the exchange price lands and differs, the manager writes a **correction**: a new
`MARK` journal row and an `equity_snapshots` revision row (append, never overwrite) saying which source replaced which. Cash in F&O stocks stops at
15:15 and the closing auction runs to about 15:35: that gap is why the 15:31 mark is provisional. Nothing here reads Kite after the close if the
login is expired; it then waits for the exchange price and says so.

## 11. Read APIs (signed in; 401 signed out; another tenant's id answers 404; money and prices are strings)

| Route | Answer |
|---|---|
| `GET /api/v1/positions/{id}/lifecycle` | lifecycle state, state history (`trade_lifecycle_events`), exit state (stop, stop history, rules and versions), pending exit orders |
| `GET /api/v1/trades/closed?account_id=&simulation_id=&after_seq=&limit=` | closed trades: entry and exit prices, quantities, reasons, gross and net realized, charges, holding sessions, `reconciled` flag |
| `GET /api/v1/execution/exits?account_id=&simulation_id=&trade_id=` | exit records with flags (`gapped`, `both_in_range`), links to orders and fills |
| `GET /api/v1/accounts/{id}/pnl` (extended) | realized gross and net now non-zero; `by_reason`, `by_strategy`, `daily` realized / unrealized split |
| `GET /api/v1/accounts/{id}/limits` | daily, weekly, drawdown: measured, limit, state, last action |
| `GET /api/v1/accounts/{id}/reconciliation` | each invariant of §5, its difference, the checked-at time and session |
| `GET /api/v1/simulations/{id}/results` (extended) | `execution_summary` gains `closed_trades`, `win_rate`, `realized_pnl_rs`, `exits_by_reason`, `reconciliation`; the fingerprint now covers exit rows |

No new screens in 3A. Screen text this slice makes false is corrected: the Phase 2 wording that says positions stay open.

## 12. Determinism

Exit fills use the same seeded stream per order (`random.Random(f"{seed}|{session}|{instrument key}|{side}")`), now with the exit's
`<reason>:<n>` in the key so an exit and an entry on the same instrument do not share a stream. The fingerprint (sha256 of id-free canonical
rows) extends to exit orders, fills, exit records, closed positions and every reconciliation row. Same seed, same fingerprint; different seed
differs when any fill is stochastic.

## 13. Defaults chosen where the PRD leaves a choice (owner: tell me if any is wrong)

1. **A resting stop that is touched inside the bar fills at the stop level with adverse slippage**, not at the worse of stop and open unless the bar opened through it (then the open).
2. **Both stop and target in one bar: the stop.** (Conservative; matches `exit_rules`.)
3. **A touch of a target fills at the target**, no credit for a better open.
4. **Time exit at the close of the session `max_holding_days` sessions held**, counted in sessions held.
5. **Option and futures legs settle on the expiry day** from the exchange file; missing data blocks settlement (never assumed).
6. **Drawdown breach suspends the account** (a human lifts it); daily and weekly breaches block new entries only.
7. **A volume-capped exit continues next session**; the stop stays on the remainder.
8. **`amend` may only be more conservative**; raising risk is refused.
9. **Trail and trend rules stay opt-in** (`trail-atr-v1`, `trend-ema-v1` are research rules; the plan decides).
10. **The day's final mark may be corrected** when the exchange end-of-day price lands (append-only correction).

## 14. What this does not do (3B and later)

Scenario injection and fault simulation (`SCENARIO` mode stays refused), pause / resume / checkpoint, deterministic replay of scenarios,
simulation reports and run comparison, the agent activity timeline and handoff trace data (3B). Exact exchange margin (SPAN) and price-band
files, allocation algorithms beyond fixed risk, live shadow (Phase 4): unchanged from `PHASE2_DESIGN.md` §11.
