# Autonomous Trading Desk — Phase 3A design: from fill to reconciled closure

Written 7 Nov 2026 (Account 1) for the owner, the engineers and Account 2, who builds screens against the read APIs in §11.
Specs: `source/PRD_v2.0.md` §8 (Trade Lifecycle Manager), §10.4 (emergency controls), §16.5, Phase 3 exit criteria, §31 SIM-004/006/
007/008/009/015/018/020; `PHASE2_DESIGN.md` (this builds on it; its §11 lists what it defers here). Test cases: `testcases_phase3a.md`
(AD-P3-*). Migration: `backend/autodesk/db/migrations/004_lifecycle.sql`. Slice 3B (scenario injection, pause/resume/checkpoint,
run comparison, agent timeline) is not designed here.

Account 2 drafted a 3A design on `feat/autodesk-phase3-lifecycle-a2` (fa3a9f72) while covering for Account 1. This document keeps its
structure and most of its defaults; where it differs, the reason is the code as it stands (named in each place).

**Done for 3A (brief):** a real-data replay of at least 20 sessions on a throwaway database where positions are managed from fill to
closure; every reconciliation difference 0.00; same seed same fingerprint, different seed different; no fill-engine read outside the
clock's session; some closures checked by hand against real prices.

## 1. Decisions that bind this phase

| # | Decision | Source |
|---|---|---|
| L1 | **No order placement.** Closing orders are paper orders on the same adapters (`submit`, `amend`, `withdraw`); `LIVE_EXECUTION_AVAILABLE = False`; `tests/test_order_path_guard.py` unchanged. | Owner |
| L2 | **Zerodha gives live quotes only, read-only.** The live path closes from a fresh quote exactly as Phase 2 opens from one. | Owner |
| L3 | **No stale data, no fabricated price, no silent fallback.** A closing or a settlement that cannot be priced from a real row or a fresh quote does not happen: the position stays open, flagged, and the step says why. | Owner rule 28 Oct |
| L4 | **No hindsight.** A decision sees only what its clock allows (§4.2). The fill engine's bar reader still refuses any session but the clock's. | Brief, PRD §28.4 |
| L5 | **The manager only reduces risk** (PRD §8.5): it never widens a level, adds quantity or leverage. Levels move one way. | PRD §8.5 |
| L6 | **One rule engine:** `services/exit_rules.py` (`exit-rules-v1`, `trail-atr-v1`, `trend-ema-v1`). This phase adapts plans to it; no second engine. | Brief |
| L7 | v1 scoring stays the only active selector; nothing here reads shadow scores. | Standing rule |
| L8 | Narrative (journal, reasons, API `summary`) avoids the AD-92 words. Field values may use trading words, and they live in `contracts.py` enums so the source scan (`test_adp2_116`, extended to `lifecycle/`) stays strict. | Owner rule 3 Nov |
| L9 | Shares and futures without a long put show loss at the invalidation level, never the stock at zero. | Owner 30 Oct |

## 2. Shape

```
backend/autodesk/lifecycle/          (new package; execution/ changes only where §10 says)
  rules.py       PURE: plan version + actual fills -> exit-rules-v1 Rules/State per position; trigger series; partial objectives
  pricing.py     PURE: closing fills from a session row (open / level / close) or a fresh quote, on autodesk-fill-v1's params
  closure.py     closing fills -> fill rows, ledger (funds, fees, realized, margin and risk released), position legs, journal
  settlement.py  expiry of F&O legs at the exchange's settlement data; a stated failure when it is missing
  manager.py     the Trade Lifecycle Manager: activation, the OPEN and CLOSE passes, the live tick, pending closings, states
  limits.py      daily, weekly and drawdown limits measured on the ledger; automatic actions
  controls.py    emergency controls beyond STOP_NEW_ENTRIES; cancel pending entries; manual close requests
  recon.py       reconciliation invariants (every step, every session end) and UNKNOWN orders
backend/autodesk/routers/lifecycle.py   read APIs (§11) and the control / amend / close routes
backend/autodesk/db/migrations/004_lifecycle.sql
```

`ExecutionGateway(lifecycle=…)`: with no lifecycle wired, `settle.run_open`, `run_close`, `live_tick` behave exactly as in Phase 2
(positions stay open; all Phase 2 tests keep running). `main.py` and the real-data script wire it.

## 3. States and data model

### 3.1 Position lifecycle (PRD §8.2)

`trade_positions.lifecycle_state` (new; `status` stays OPEN / CLOSED):

```
ACTIVE_POSITION ──(closing order working)──> EXIT_PENDING ──(rest of quantity left)──> PARTIAL_EXIT ──> EXIT_PENDING …
EXIT_PENDING ──(remaining quantity 0)──> CLOSED ──(per-trade reconciliation 0.00)──> SETTLED
ACTIVE_POSITION | PARTIAL_EXIT ──(level moved, limit near, pending closing carried)──> RISK_MANAGEMENT ──> back
any open state ──> RECONCILIATION_REQUIRED (a difference ≠ 0.00, or settlement data missing) | EXECUTION_ERROR (an adapter failed)
```
`ORDER_SUBMITTED / FILLED / …` are the order's states (Phase 2), not repeated on the position. Allowed moves are a table in
`contracts.py` (`LIFECYCLE_TRANSITIONS`, additive); anything else raises `IllegalTransition`. Every move is a `trade_lifecycle_events`
row and a `LIFECYCLE_STATE_CHANGED` event in the same transaction. A position is CLOSED only when its remaining quantity is zero by
confirmed (simulated) fills or settlement; it is SETTLED only after its reconciliation passes (PRD §8.2).

### 3.2 Migration 004 (additive; append-only tables refuse UPDATE/DELETE with `autodesk.refuse_change`)

| Table / change | Kind | Holds |
|---|---|---|
| `trade_positions` + `lifecycle_state`, `realized_gross_rs`, `closing_charges_rs`, `closed_at`, `close_reason`, `settled_at`, `flags` | columns | state, realized gross, closing and settlement charges, why it closed, open problems (`flags`) |
| `trade_position_legs` + `opened_qty`, `closed_qty`, `close_value_rs`, `closing_charges_rs`, `realized_gross_rs` | columns | per leg: `opened_qty = quantity + closed_qty` always |
| `trade_orders` + `purpose` (`OPEN`/`CLOSE`), `close_reason`, `trigger_price` | columns | closing orders reuse the order table and its state machine |
| `trade_exit_state` | head row per trade | exit-rules-v1 `State` (JSON), `Rules`, trigger series, level ratio, objectives and the next one, pending closing, sessions held, pre-expiry session |
| `trade_lifecycle_events` | append-only | from, to, reason, detail, session, sim time |
| `trade_exit_records` | append-only | one per closing (or settlement): reason, how it was priced (`open`, `level`, `close`, `quote`, `settlement`), trigger price, level, `gapped`, `both_in_range`, per-leg quantities and prices, gross, charges, realized |
| `lifecycle_controls` | head row (tenant, control, scope) | §7.2 controls; every change is also an event |
| `close_requests` | head row | a person's or a control's request to close a position (manual, risk control), consumed by the manager |
| `reconciliation_runs` | append-only | each invariant of §5.2 with its difference, per account and moment |
| `equity_snapshot_revisions` | append-only | old and new snapshot when the day's final mark is corrected (§10.2) |
| `equity_snapshots` + `mark_basis` | column | `SESSION_CLOSE` (simulation), `LIVE_LAST`, `KITE_CLOSE`, `EXCHANGE_EOD` |
| `trade_journal_entries.kind` + `LIFECYCLE`, `CLOSING_DECISION`, `CLOSING_FILL`, `CLOSURE`, `SETTLEMENT`, `LIMIT`, `CONTROL`, `RECONCILIATION` | CHECK | the chain continues past the position |

## 4. Closing rules

### 4.1 Rules per position (from the approved plan version and the actual fills, never from a model)

| Plan field | Rule | exit-rules-v1 |
|---|---|---|
| `invalidation.underlying_level` | the level in force at activation | `State.stop` |
| `targets[]` (`level`, `exit_fraction`) | objectives in order; each closes its fraction of the **remaining** quantity, whole lots | `Rules.target` = the next objective |
| `holding.max_holding_days` | counted in **sessions held** | `Rules.max_hold_sessions` |
| `holding.close_days_before_expiry` (2 in plans today) | close at the session that many sessions before the earliest leg expiry | (manager) |
| `exit_rules.trailing` = `trail-atr-v1 (k × ATRn)` | ATR trail, tighten only, in force from the next session | `Rules.trail_atr_mult`, `atr_period` |
| `exit_rules.trend` naming `trend-ema-v1` | trend rule (no plan sets it today) | `Rules.trend_ema_period` |

**Trigger series** (which bar the levels are judged on), set once at activation and stored:
- **Shares:** the share's own row; levels as given; side long.
- **Futures (single leg):** the future's own row; levels translated by the basis known at the entry open:
  `level × future previous close ÷ underlying previous close` of the entry session (both published before the open). Stored with its
  ratio and source. Reason: an end-of-day row cannot show the future's price at the moment the underlying touched a level.
- **Option structures:** the underlying share's row (plans set levels on the underlying, `TargetLevel.basis = UNDERLYING`); side from
  the plan's direction (BULLISH long, BEARISH short). **NEUTRAL** (iron condor): no level rules; time, pre-expiry and settlement only.
  An index underlying has no share row in the fill engine's data: level rules are then not available and the position says so.
- **ATR seed:** the last `n + 1` published daily bars of the underlying before the entry session, through the agents' point-in-time view
  (it refuses anything published after the clock); scaled by the ratio for a future. With no history source the ATR seeds itself from the
  first n sessions held and the trail does not move until then (`atr_unavailable`, as exit-rules-v1 does).

### 4.2 What the clock allows

| Moment | Sees | Decides |
|---|---|---|
| OPEN 09:15, before entries | the trigger row's **open** only (exit-rules-v1 stepped on an open-only bar; its state is kept only if it decided something) and the previous close for the futures ratio | open through the level in force at the previous close (**gap**: filled at the real open, never at the level); an objective already beyond at the open (resting limit, filled at the objective); a trend closing due at this open; carried pending closings; close requests |
| CLOSE 15:30, after entries settle, before marks | the whole session row | intrabar touch of the level or an objective (both in one row: the **level**, the adverse reading); expiry settlement; holding period; pre-expiry closing; then the trail and trend for the next session |
| Live tick (desk) | the fresh quote of the trigger series (≤ 120 s, today's, traded today) | level, objectives, holding period after 15:00 IST on the last session, pre-expiry after 15:00; trail from the previous session's exchange row once published |

Positions whose opening order filled at the OPEN are stepped at that session's CLOSE (the open was their first trade; the rest of the row
came after). A position whose opening limit filled at the CLOSE (time of the fill unknown) is first stepped at the next session.

### 4.3 Prices of closing fills (`autodesk-fill-v1` params, same costs as openings)

| How | Leg price | Basis |
|---|---|---|
| `open` (gap, carried pending closing, trend, close request at the open) | leg's own open, adverse half spread + seeded slippage, on the tick against the order | real open |
| `level` (share or future: level touched inside the row) | the level (future: translated), adverse half spread + slippage, kept inside the row's low–high | a level that traded; a triggered resting order becomes a market order |
| `objective` (share or future) | **only if price traded through it** (`high > level` long, `low < level` short), at the level, no spread or slippage | resting limit: Phase 2's rule for limits (a touch does not fill; PRD §8.6) |
| `close` (holding period, pre-expiry, option structures on a touch inside the row) | leg's own close, adverse half spread + slippage, kept inside low–high | an end-of-day row cannot show an option premium at the moment the underlying touched a level; the close is the first price after the trigger it can vouch for |
| `quote` (live) | Phase 2's `decide_quote`: bid for a long leg's closing, ask for a short leg's, slippage, displayed quantity | fresh quote only |
| `settlement` | §6 | exchange data |

Volume: at most 10 % of the session's traded quantity, whole lots (as openings). A closing capped below the order **carries** the rest
to the next OPEN as a pending closing (the level is not loosened). A leg with no row or no trade cannot be priced: the whole closing waits
(`CLOSE_BLOCKED_NO_DATA`), stays pending and is retried at the next OPEN; it is never priced from an old row.

Seed: `rng_for(seed, session, "<instrument key>|CLOSE|<reason>|<n>", side)` — one stream per closing order, independent of the entry's.

### 4.4 Several legs: one unit

A multi-leg position closes as a unit (PRD: "manage strategy-level and leg-level states"; plans say "close every leg together if any
leg cannot be managed"): all legs priced, all inside their caps, or none fills and the closing waits, flagged. Partial objectives close the
same fraction of every leg, whole lots. One leg is never left alone by the manager.

### 4.5 Partial objectives

Objective *k* closes `exit_fraction` × remaining lots, **rounded down to whole lots**; if that is zero lots, it closes the whole remainder
(risk-reducing; default 3). Every partial recalculates `open_risk`, capital and margin of the remainder (PRD §8.6). A duplicate partial is
impossible: the closing intent's key is `<trade_id>:CLOSE:<session>:<reason>:<n>` and the objective index advances in the same
transaction as the fill. The level is not moved to cost after objective 1 (no plan asks for it).

## 5. Closure and the books

### 5.1 Ledger rows of one closing fill (append-only; one transaction with the order and position updates)

| Row | Buckets |
|---|---|
| `POSITION_FUNDS` | cash: + sale value of a long share/option leg, − cost of buying back a short option leg, 0 for futures; notional: − the closed share of the leg's cost |
| `FEES_BOOKED` | cash − charges, fees + charges (desk-cost-v2, brokerage once per order) |
| `REALIZED_PNL` | realized_gross + (value − cost of closed qty) for a long leg, (cost − value) for a short leg; **futures also move cash by it** (mark-to-market settles in cash); other legs move no cash here |
| `MARGIN_RELEASED` | once per closing unit: margin − (position margin × fraction closed), open_risk − (position risk × fraction) |

Net realized = gross realized − every charge (opening and closing). The opening reservation is already closed by Phase 2 (consumed +
released = amount); closure checks it (§5.2-6).

### 5.2 Reconciliation (after every closing, every settlement, every session end; stored in `reconciliation_runs`)

1. `equity_from_pnl − (cash + Σ open position market value)` = 0.00 (Phase 2's invariant, now with realized P&L).
2. Per trade: ledger `REALIZED_PNL` = Σ `trade_exit_records.realized_gross_rs` = position `realized_gross_rs`.
3. Per leg: opened quantity (Σ opening fills) − closed (Σ closing fills + settled) = position leg quantity.
4. Ledger fees = Σ fill charges + Σ settlement charges.
5. Ledger cash = opening capital + adjustments + Σ fill and settlement cash flows − Σ charges.
6. Every reservation of the account is ACTIVE or closed with consumed + released = amount.
7. Ledger open risk = Σ open positions' `open_risk_rs`; ledger margin = Σ open positions' `margin_rs`.
8. Journal: one `FILL` / `CLOSING_FILL` row per fill, one `CLOSURE` per closed position, one `SETTLEMENT` per settled leg group.

A difference on a trade moves it to `RECONCILIATION_REQUIRED` and stops its automatic actions; a CLOSED trade with all differences 0.00
moves to `SETTLED`.

## 6. Expiry settlement (real data only)

On a leg's expiry session, at CLOSE, after level checks, an open futures or option leg is **settled**, not traded:
- futures at the contract's `settle_price` on that session's F&O row;
- options at intrinsic value against the underlying's final settlement price = the underlying share's close that session (NSE's rule
  for stock options), cross-checked with the expiring future's settlement price when that row exists (a difference over 0.05 % is a
  stated failure).

Booking: `trade_exit_records` (how = `settlement`) and the §5.1 rows; charges per the cost card's expiry convention (the leg is priced
as closed at its settlement value; a worthless leg still pays its closing side's brokerage and GST). No `trade_fills` row (a fill has a
price above 0; a worthless option settles at 0). **Missing data** (no row, no settlement price, no underlying close, or the cross-check
fails): no price is assumed, the position goes to `RECONCILIATION_REQUIRED` with `SETTLEMENT_DATA_MISSING`, stays open and is retried
at the next CLOSE (F&O files land about 22:45 IST). Plans close two sessions before expiry, so settlement is the exception.

## 7. Amend, controls, close requests

### 7.1 `amend` (MODIFY_PENDING)
Only a working (OPEN) single-leg opening LIMIT order, only towards less risk: fewer lots (≥ what filled, > 0) and/or a less aggressive
limit (lower to pay, higher to receive). Anything else answers `409 AMEND_RAISES_RISK` / `AMEND_NOT_ALLOWED`. Moves
`OPEN → MODIFY_PENDING → OPEN` with history; the paper adapter's `amend` accepts. The reservation is not enlarged; what is no longer
needed is released when the order ends (Phase 2 rule).

### 7.2 Emergency controls (PRD §10.4) — never cancel a protective closing, never leave a position without its level

| Control | Scope | Effect |
|---|---|---|
| `STOP_NEW_ENTRIES` (Phase 1) | tenant desk | unchanged |
| `SUSPEND_AUTOMATED_MODIFICATIONS` | tenant desk or one account | the trail does not move; levels already in force stay and still close |
| `SUSPEND_ACCOUNT` | one account | no new intent validates or fills for it (`ACCOUNT_SUSPENDED`); managed closings continue |
| `SUSPEND_STRATEGY` | one strategy type | no new intent of that strategy (`STRATEGY_SUSPENDED`) |
| `REDUCE_ONLY` | tenant desk or one account | no new intents; the manager closes open positions at the next priceable moment (reason `risk_control`) |
| `CANCEL_PENDING_ENTRIES` | action | withdraws every working opening order of the desk (never a closing order) |
| `DISABLE_ADAPTER` | — | not built: the only adapters are paper; the shadow adapter already refuses everything |
| `SUSPEND_STRATEGY_GENERATION` | — | covered by STOP_NEW_ENTRIES today (no proposal starts); separate switch deferred |

Tenant-wide controls act on desk accounts only (as STOP_NEW_ENTRIES). Account-scoped ones act on any account, including a simulation's,
which is how the drawdown limit acts in a replay. Each change is idempotent, an event and a journal `CONTROL` row per affected trade.

### 7.3 Close requests
`POST /positions/{id}/close` (a person, desk only) and REDUCE_ONLY write a `close_requests` row; the manager closes the whole position at
the next priceable moment (sim: next OPEN; live: next fresh quote) with reason `manual` / `risk_control`. Idempotent per position.

## 8. Daily, weekly and drawdown limits (policy `daily_loss_pct` 2, `weekly_loss_pct` 4, `max_drawdown_pct` 10)

Measured from the ledger and marks only (no second P&L), after every session snapshot and on each live tick:
- **daily** = equity now − equity at the previous session's snapshot (opening capital if none), as % of that equity;
- **weekly** = equity now − equity at the last snapshot before the IST week (Monday) began, as % of it;
- **drawdown** = (running peak of snapshots and now − equity now) ÷ peak.

| Breach | Action | Authority |
|---|---|---|
| daily | new intents refused `DAILY_LOSS_LIMIT` for the rest of that session and the next session; closings continue | automatic |
| weekly | refused `WEEKLY_LOSS_LIMIT` until the IST week ends (and at least the next session) | automatic |
| drawdown | `SUSPEND_ACCOUNT` activated by `RISK_LIMITS` (a person lifts it) + `LIMIT_BREACHED` event for escalation | automatic suspension |

The risk engine's `daily_loss`, `weekly_loss`, `drawdown` checks stop being SKIPPED when the book carries the measures: they PASS or FAIL
on the same numbers (hard). The gateway controls refuse at validation and at submission (`LOSS_LIMIT`). On stale marks the measure says so
and uses the last mark (the conservative reading is the same number; it is never hidden).

## 9. UNKNOWN orders

A paper adapter has no external state; UNKNOWN arises only when the adapter raised between SUBMITTED and ACKNOWLEDGED. The reconciler,
at every lifecycle pass and at start-up: the order has no fill (fills are only written for OPEN or PARTIALLY_FILLED orders), so it ends
`EXPIRED` ("the paper venue holds no record of it; it never worked") and its intent finishes, releasing the reservation. Never resubmitted.

## 10. Live path

### 10.1 Closings on the live tick
The tick's single quote read adds the trigger series of open desk positions (underlying shares for option structures). Per position, in
its own transaction: level / objective on the trigger's fresh LTP → closing orders priced by `decide_quote`, fills only from fresh quotes,
inside the fill windows (cash to 15:15, F&O to 15:30). No fresh quote: no fill, the closing stays pending (`QUOTE_STALE`, …), retried next
tick; the level stays in force. Holding period and pre-expiry: from 15:00 IST of the due session. Trail: once a day, from the previous
session's exchange row after it is published (cash 19:30, F&O 22:45 IST), tighten only; if that row shows the level was crossed while no
fresh quote was there, a pending closing is set for the next fresh quote (conservative).

### 10.2 The day's final mark (owner rule: live → Kite close → exchange EOD)
Phase 2 snapshots at 15:31 from the last live marks. Cash in F&O stocks stops at 15:15, the closing auction ends about 15:35, F&O trades
to 15:40, so that mark is provisional. From this phase:
1. **15:41 IST** (after every segment): one quote read for every open desk leg; a fresh answer marks the leg (`KITE_CLOSE`); otherwise
   the last live mark stays (`LIVE_LAST`). The snapshot is written with its `mark_basis`.
2. **Exchange EOD** (cash after 19:30, F&O after 22:45 IST): each leg's exchange close for that session (`PitSessionBars`, published
   rows only). Where it differs from the mark, the leg is re-marked (`EXCHANGE_EOD`), a `MARK` journal row says which source replaced
   which, the snapshot is rewritten and the old one kept in `equity_snapshot_revisions` (append-only).
With the Kite login expired, step 1 keeps `LIVE_LAST` and says so; step 2 still corrects.

## 11. Read APIs (signed in; 401 signed out; another tenant's id 404; money and prices are strings; lists follow Phase 2's simulation rule)

| Route | Answer |
|---|---|
| `GET /api/v1/positions/{id}/lifecycle` | `lifecycle_state`, `flags`, state history, exit state (level in force, level history with versions, objectives with the next one, sessions held, pre-expiry session, trigger series and ratio, pending closing), closing orders, exit records |
| `GET /api/v1/trades/closed?account_id=&simulation_id=&limit=` | closed trades: instrument, strategy, opened/closed at, sessions held, close reason, per-leg opening and closing average prices and quantities, gross realized, opening + closing charges, net realized, `reconciled` |
| `GET /api/v1/execution/exit-records?account_id=&simulation_id=&trade_id=` | every closing and settlement with how it was priced, `gapped`, `both_in_range`, legs |
| `GET /api/v1/lifecycle/events?trade_id=&account_id=&simulation_id=&after_seq=&limit=` | lifecycle events in order |
| `GET /api/v1/accounts/{id}/pnl` (extended) | realized gross / net now real; `by_reason`; `by_strategy` = realized net + unrealized net; `closed_trades`, `win_rate` |
| `GET /api/v1/accounts/{id}/limits` | daily, weekly, drawdown: measured, limit, `state` (OK / BREACHED), basis, what it blocks until |
| `GET /api/v1/accounts/{id}/reconciliation` | latest run: each invariant, difference, moment |
| `GET /api/v1/lifecycle/controls` · `POST /api/v1/lifecycle/controls/{control}` `{active, reason, scope}` | §7.2 |
| `POST /api/v1/execution/cancel-pending-entries` `{reason}` | withdraws the desk's working opening orders; returns the ids |
| `POST /api/v1/execution/orders/{id}/amend` `{lots?, limit_price?}` | §7.1 |
| `POST /api/v1/positions/{id}/close` `{reason}` | §7.3 (desk positions only; 409 for a simulation's or a closed one) |
| `GET /api/v1/simulations/{id}/results` (extended) | `execution_summary` + `closed_trades`, `open_positions`, `win_rate`, `realized_net_rs`, `exits_by_reason`, `lifecycle` (states count), `reconciliation_runs` (count, all zero), the fingerprint now covering closings, exit records and reconciliation |

No new screens in 3A. Screen and result text this slice makes false ("positions stay open", "realized P&L arrives with Phase 3",
"loss limits are not enforced", "UNKNOWN-order reconciliation comes with Phase 3") is corrected in the same change.

## 12. Determinism

Closing fills use one seeded stream per closing order (§4.3). The fingerprint (Phase 2's id-free canonical rows) adds exit records,
lifecycle events (state moves, reasons, sessions) and reconciliation differences. Same seed, same fingerprint; another seed differs
whenever any fill was priced with slippage.

## 13. Defaults chosen where the PRD leaves a choice (owner: say if one is wrong)

1. **The invalidation level is a resting level judged inside the session** (a touch closes; an open through it fills at the open). The
   plan's text says "closes beyond"; a close-only rule would let futures and shares lose more than the plan's sized loss.
2. **Both the level and an objective inside one row: the level** (adverse reading; exit-rules-v1).
3. **An objective fills only if price traded through it, at the objective** (no credit for a better open), as Phase 2's limits.
4. **Holding period counted in sessions held**; plans' pre-expiry rule closes 2 sessions before the earliest leg expiry.
5. **Option structures closed on a touch inside the row are priced at the legs' closes** (the first price an end-of-day row can vouch for after the trigger), with adverse spread and slippage.
6. **Futures levels translated by the entry-open basis** (future ÷ underlying previous closes), fixed for the trade's life.
7. **A partial objective that rounds to zero lots closes the whole remainder.**
8. **A volume-capped or unpriceable closing carries to the next open as a market closing**; the level stays in force.
9. **Drawdown breach suspends the account (a person lifts it); daily and weekly breaches block new intents only** (daily: that session and the next; weekly: to the end of the IST week).
10. **`amend` only towards less risk.**
11. **Trail ATR seeded from the published daily bars before the entry session**; trend rule off unless a plan names it.
12. **The day's final mark is corrected when the exchange close lands** (append-only revision).
13. **Option final settlement uses the underlying share's close that session**, cross-checked with the expiring future's settlement price.

## 14. Not in 3A

Scenario injection and fault simulation (`SCENARIO` stays refused), pause / resume / checkpoint, replay of scenarios, simulation reports
and run comparison, agent activity timeline and handoff trace (3B). Exact SPAN margin, band and tick files, allocation algorithms beyond
fixed risk, live shadow (Phase 4): unchanged from `PHASE2_DESIGN.md` §11.
