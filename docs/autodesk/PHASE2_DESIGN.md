# Autonomous Trading Desk — Phase 2 design: risk-to-paper execution

Written 7 Nov 2026 for the owner, the engineers and Account 2 (who will build screens against the read APIs in §9).
Specs: `source/PRD_v2.0.md` (§9, §10.3, §10.4, §11, §12.1–12.2), `source/TECH_ARCH_v1.0.md` (§8, §9, §10.4, §10.6). Phase 1:
`DESIGN.md`. Test cases: `TESTCASES.md`, "Phase 2 — risk-to-paper [core]". Migration: `backend/autodesk/db/migrations/003_paper_execution.sql`.

**Exit (PRD Phase 2 + owner):** an approved plan fills in an isolated simulation with correct capital reservation, simulated fills
and an audit trail; on the live desk the same plan fills from a live Zerodha quote during market hours.

## 1. Decisions that bind this phase

| # | Decision | Source |
|---|---|---|
| P1 | **No order placement of any kind.** Adapters are PAPER (simulation + live desk) and a SHADOW stub. `LIVE_EXECUTION_AVAILABLE = False`. Gateway verbs are `submit` / `amend` / `withdraw` (order-path guard). | Owner |
| P2 | **Zerodha gives live quotes only, read-only**, through `ReadOnlyKite` (`instruments`, `quote`) and the feed's Redis cache. | Owner |
| P3 | **No stale market data.** Only today's live quote can price a fill. No quote or a stale quote: the order stays open and retries, it never fills at an old price. Outside market hours orders wait for the session. | Owner rule 28 Oct |
| P4 | Simulations use the desk's historical data, with no look-ahead (§5.4). | Brief |
| P5 | Paper fills are labelled simulated, in the database (`fill_kind = 'SIMULATED'`, CHECK) and in every API answer (`broker_confirmed: false`). | PRD §11.5 |
| P6 | Generated narrative (reasons, journal summaries) avoids the AD-92 words. API field names may use standard trading words (`side: BUY`). | Owner rule 3 Nov |
| P7 | Exits, stops, trailing and expiry settlement are Phase 3. **Positions stay open in Phase 2.** Unfilled orders expire at the session close and release their reservation. | Brief |

Pending owner decisions use the `DESIGN.md` §10 defaults: first-release strategies (long equity, long futures, long call/put, debit
spreads, credit spreads, iron condor; no short futures); AUTONOMOUS_PAPER auto-approves ≤ 0.5 % equity risk with signal score ≥ 70; risk-profile default limits; margin utilisation 25 %.

## 2. Shape

```
backend/autodesk/execution/        (new)
  capital.py      append-only ledger, derived balances, atomic reservation (row lock), convert / release / expire
  orders.py       plan version → order spec (leg limits, basket net limit); order state machine moves + history
  fill_model.py   PURE: session bar → decision; live quote → decision. Spread, slippage, latency, volume cap, rejections
  costs.py        desk-cost-v2 → Decimal; slippage is in the price, so the card's slippage component is 0
  positions.py    fills → positions and legs; marks; unrealized P&L
  journal.py      the §12.1 chain, one row per link
  adapters.py     ExecutionAdapter contract, mode router, SimulationPaperAdapter, LivePaperAdapter, ShadowAdapter
  gateway.py      controls (§11.4), intents, submission, withdraw, start-up recovery
  settle.py       fills → ledger, reservation, position, journal; simulation OPEN and CLOSE; the live tick; marks; snapshots
  live_loop.py    background task of the desk process: the live tick (`AUTODESK_LIVE_LOOP`, default on)
  reports.py      capital view, P&L, simulation execution summary, determinism fingerprint
backend/autodesk/routers/execution.py   the read APIs of §9 and the withdraw route
backend/autodesk/market/
  session_bars.py the fill model's only historical data; separate from the agents' view; refuses any later session
  live_quotes.py  QuoteSource contract, freshness rule, Redis-then-REST source over ReadOnlyKite
```

`Orchestrator(execution=…)` calls the gateway after an approval; `SimulationManager(execution=…)` calls `settle` at OPEN and CLOSE. **With no gateway
wired, both behave exactly as in Phase 1** (the tests of that behaviour keep running); production wires it in `main.py`.

## 3. Data model (migration 003, schema `autodesk`)

Money is `numeric(18,2)`, prices `numeric(18,4)`, Decimal in Python, strings in JSON. Rows carry `tenant_id`, `account_id` and
`simulation_id` (null on the desk). Append-only tables refuse UPDATE and DELETE by trigger (`autodesk.refuse_change`).

| Table | Kind | What it holds |
|---|---|---|
| `capital_ledger_entries` | append-only | one row per movement: `entry_type`, signed bucket deltas (`cash`, `reserved`, `margin`, `notional`, `open_risk`, `pending_risk`, `pending_commitment`, `realized_gross`, `fees`), `ref_type/ref_id`, `trade_id`, `memo`, `sim_time` |
| `capital_reservations` | head row | `status`, `amount_rs`, `consumed_rs`, `released_rs` (consumed + released = amount once closed), `risk_rs`, `commitment_rs`, `capital_rs`, `sector`, `fno`, `expires_at`, unique `idempotency_key` |
| `execution_intents` | head row | exact binding (`trade_id`, `plan_version`, `plan_hash`, `approval_id`), `execution_mode`, `adapter` (server-side), `action`, `session_date`, `status`, `refusal_codes`, `controls` (every check with its outcome), `order_spec`, unique `(tenant_id, idempotency_key)` |
| `trade_orders` | head row | one per plan leg: instrument fields, `side` BUY/SELL, `lots`, `lot_size`, `quantity`, `order_type` MARKET/LIMIT/BASKET_LEG, `limit_price`, `ref_price`, `state`, `filled_qty`, `avg_fill_price`, `reject_code`, `reject_reason`, `attempts`, `last_no_fill_reason`, unique `idempotency_key` |
| `trade_order_events` | append-only | every state move: from, to, reason, sim time, wall time |
| `trade_fills` | append-only | `quantity`, `price`, `arrival_price`, `value_rs`, `spread_rs`, `slippage_rs`, `charges` (breakdown), `charges_rs`, `cost_model`, `price_source`, `latency_ms`, `fill_time`, `fill_kind` = SIMULATED (CHECK) |
| `trade_positions` | materialised | one per trade: `status` OPEN (CLOSED in Phase 3), `open_risk_rs`, `capital_rs`, `margin_rs`, `sector`, `fno` |
| `trade_position_legs` | materialised | one per trade leg: `quantity`, `avg_price`, `cost_value_rs`, `charges_rs`, `mark_price`, `mark_source`, `marked_at`, `unrealized_rs` |
| `equity_snapshots` | one per account per session | equity, cash, margin, reserved, buying power, notional, risk, gross realized, fees, gross unrealized, net P&L (daily and cumulative P&L, maximum drawdown) |
| `trade_journal_entries` | append-only, unique `(trade_id, kind, ref_id)` | the §12.1 chain: SIGNAL, PLAN_VERSION, RISK_ASSESSMENT, APPROVAL, EXECUTION_INTENT, RESERVATION, ORDER, FILL, POSITION, MARK |

`trade_plans.status` gains `EXECUTING` (reservation held, orders working), `EXECUTED` (at least one fill; position open) and
`EXECUTION_REFUSED` (a control or the paper engine refused). The opening row is written when an account is created; migration 003
writes it for accounts that already exist.

### 3.1 Capital model (PRD §9.2): never derived by mutation, always from the ledger and the marks

| Measure | Definition |
|---|---|
| `cash_balance_rs` | Σ cash deltas: opening capital − shares and premium paid + premium received − fees |
| `used_margin_rs` | Σ margin deltas: futures notional × `futures_margin_pct` (estimate, not SPAN); credit structures: the width |
| `available_cash_rs` | cash balance − used margin |
| `reserved_capital_rs` | Σ reserved deltas (active reservations) |
| `available_buying_power_rs` | available cash − reserved capital |
| `deployed_notional_rs` | Σ gross traded value at fill (premium for options). A size measure: it never moves buying power by itself |
| `open_risk_rs` / `pending_risk_rs` | maximum loss of filled quantity / of what is still reserved |
| `pending_order_commitment_rs` | gross value of working orders at their limit |
| `realized_gross_rs`, `fees_rs` | gross realized (0 until Phase 3 has exits), charges booked at each fill |
| `unrealized_gross_rs` | Σ leg (mark − cost) signed, from the latest marks |
| `net_realized_rs`, `net_pnl_rs`, `equity_rs` | gross realized − fees; net realized + unrealized; opening capital + adjustments + net P&L |

Reconciliation invariant, tested and reported: **equity = cash balance + Σ position market value** (long shares and options at mark, short
options negative, futures at their unrealized), difference 0.00.

Worked figures for ₹10,00,000 (`AD-P2-03..05` check these to the paisa):
- 100 shares at 1,000: cash −1,00,000 − fees, notional +1,00,000, margin 0, risk = plan loss.
- 1 lot (500) of futures at 1,000: cash − fees only, margin +75,000 (15 %), notional +5,00,000, risk = plan loss. Three different numbers.
- Debit spread 500 × (30 − 12): cash −9,000 − fees, margin 0. Credit spread width 10,000, credit 3,500: cash +3,500 − fees, margin +10,000, so buying power falls by the maximum loss 6,500 + fees.

## 4. Reservation (PRD §9.4, ARCH §8.2)

`capital.reserve()` runs in one transaction: `SELECT … FROM accounts … FOR UPDATE` (the account's allocation state) → release anything past its expiry →
derive the balances → check → insert reservation + `CAPITAL_RESERVED` ledger row + event. Two proposals cannot read the same free funds: the second waits for the
first's commit and then sees its reservation (`AD-P2-10` runs ten at once).

Amount = worst-acceptable funds for the order: cash out at the limit (or collar) + margin + estimated charges.
Refusal codes: `INSUFFICIENT_FUNDS`, `PER_TRADE_RISK`, `OPEN_RISK_LIMIT`, `POSITION_LIMIT`, `SECTOR_LIMIT`, `MARGIN_LIMIT`.

State: `ACTIVE → CONSUMED` (a fill used it; any remainder is released when the order ends) | `RELEASED` (rejected or withdrawn, nothing used) | `EXPIRED` (session close,
nothing used). Expiry is the plan's validity (session close). A reservation past expiry is released by the session-close step, by the live tick and lazily by the next `reserve` on the account.

## 5. Execution

### 5.1 Path (ARCH §9.1)

`APPROVED plan → Execution intent (persisted first, status CREATED, own commit) → controls + reservation + orders (one transaction; VALIDATED or REFUSED) →
mode router (server-side, from account.kind) → adapter.submit → paper fill → position + ledger + journal`.

When it happens: **simulation** the intent and reservation at approval (09:00), submission and fills at OPEN (09:15). **Live desk** the intent, reservation and submission at approval; fills while the session is open.

### 5.2 Controls (PRD §11.4 adapted to paper; ARCH §9.3). Each is stored on the intent with its outcome

| Control | Refusal code |
|---|---|
| Tenant owns the account; account ACTIVE | `ACCOUNT_NOT_ACTIVE` |
| Mode: RESEARCH never; router finds PAPER or SIMULATION for the account kind (SHADOW refuses) | `MODE_NOT_ALLOWED` |
| Account mode unchanged since the plan's workflow began | `ACCOUNT_MODE_CHANGED` |
| Policy version unchanged since the risk assessment | `POLICY_CHANGED` |
| An APPROVED, unexpired approval of this exact trade and version, with a PASS assessment | `NO_APPROVAL`, `APPROVAL_EXPIRED`, `NO_PASS_ASSESSMENT` |
| Plan version is the current one | `PLAN_VERSION_STALE` |
| Plan hash: the stored version's recomputed hash = scope's = caller's | `PLAN_HASH_MISMATCH` |
| Scope: tenant, account, instrument, strategy, lots, notional, risk, action ENTER, execution mode | `SCOPE_EXCEEDED` |
| Plan state APPROVED | `PLAN_STATE` |
| STOP_NEW_ENTRIES (desk only, as in Phase 1; simulations of past sessions are not affected) | `ENTRIES_STOPPED` |
| Strategy and segments allowed by the policy; no short futures | `STRATEGY_NOT_ALLOWED`, `SEGMENT_NOT_ALLOWED` |
| Contract not expired by the session | `CONTRACT_EXPIRED` |
| Quantity a multiple of the leg's lot; limit on the tick; limit inside the collar | `LOT_SIZE`, `TICK_SIZE`, `COLLAR` |
| Idempotency: same key returns the same intent. Same trade, version and action under another key | `DUPLICATE_INTENT` |
| Funds and limits (§4) | codes of §4 |

The binding, stop and account controls run again at submission, and on the live desk before each pricing pass. A refused intent is kept, with its codes and no orders or reservation; a duplicate or an old version's refusal does not change the status of a plan another intent is working on. An intent left CREATED by a stopped process goes on at the next call for it; at start-up what is left is refused (`INTERRUPTED`).
Idempotency key: `<trade_id>:v<version>:ENTER`. Same key, same intent, no new rows, also under concurrency.

### 5.3 State machines

**Intent:** `CREATED → VALIDATED → SUBMITTED → COMPLETED`; `CREATED | VALIDATED → REFUSED`. `result` on completion: FILLED, PARTIALLY_FILLED, NOT_FILLED.

**Order (PRD §11.3):**
```
CREATED → VALIDATED → SUBMITTED → ACKNOWLEDGED → OPEN → PARTIALLY_FILLED → FILLED
          any open state → REJECTED | EXPIRED | CANCEL_PENDING → CANCELLED
          SUBMITTED → UNKNOWN (RECONCILIATION_REQUIRED): never retried blindly; reservation kept until it expires
          MODIFY_PENDING is in the contract; `amend` answers "not available in Phase 2"
```
A move outside `contracts.ORDER_TRANSITIONS` raises `IllegalTransition`. Every move adds a `trade_order_events` row and an event in the same transaction.

**Reservation:** §4. **Position:** OPEN (activated by a fill, never by an acknowledgement). **Plan:** `APPROVED → EXECUTING → EXECUTED | EXPIRED | EXECUTION_REFUSED`.

### 5.4 Order spec (from the approved plan version; part of the intent)

- Plans today say `entry.order_type = LIMIT`. MARKET is supported for a plan that says so.
- Single leg, LIMIT: shares at `entry.zone_high`, else `ref × (1 + max_slippage_pct)`; futures at the same distance from their own ref; one option at `ref × 1.15`. Limits go on the 0.05 tick, never past the limit's side.
- **Several legs: all-or-none in Phase 2.** Each leg is a `BASKET_LEG` order with no price of its own; the intent carries `net_limit_rs` = net plan value + 15 % of its size (debit may cost at most that much more, credit may collect at most that much less). Per-leg limits would refuse spreads whose legs moved together while the net hardly changed. A basket never rests: the daily bar cannot show that all legs were inside the net at one moment. Failure: every leg `REJECTED`, code names the leg and why, reservation released, no position.

## 6. Fill model `autodesk-fill-v1`

### 6.1 Simulation: from the session's daily bar (one bar per leg: the raw bhavcopy row; an option leg is priced from its own contract's row, never from the underlying)

The fill engine plays the market, so it may read the session it is simulating. **The agents cannot**: their view still raises `LookAheadError` for that bar until it is published. The bar reader (`market/session_bars.py`) refuses any session other than the one the clock is in and logs every read (`AD-P2-64`).

At **OPEN (09:15)** the decision sees only `open`, `prev_close`, the lot size and the session's traded quantity. High, low and close are not passed in.

| Step | Rule | On failure |
|---|---|---|
| Traded | a contract row with zero traded volume carries an old close | `REJECTED UNTRADED_CONTRACT` |
| No row | a share with no bar that session (not traded, suspended) | stays open, expires at close |
| Lot | leg lot = that session's exchange lot | `REJECTED LOT_SIZE` |
| Band | shares, futures: open within ±20 % of the exchange's previous close (proxy: no band file; options not checked) | `REJECTED PRICE_BAND` |
| Reference | shares, futures: open within ±10 % of the plan's price (large gap, or a corporate action the plan does not know) | `REJECTED REFERENCE_MOVED` |
| Invalidation | a long single leg (shares, futures) does not open at or through its invalidation level | `REJECTED THROUGH_INVALIDATION` |
| Price | BUY = open × (1 + half spread) × (1 + slippage), SELL mirrored, rounded to the tick against the order | |
| MARKET collar | filled price within ±3 % of plan (shares, futures), ±15 % (options) | `REJECTED COLLAR` |
| LIMIT | marketable if the priced fill ≤ limit (BUY): fills at that price | else rests |
| Volume | filled ≤ 10 % of the session's traded quantity, in whole lots | partial; 0 → no fill |
| Funds | fill's funds ≤ buying power + its own reservation, under the account lock | `REJECTED INSUFFICIENT_FUNDS` |
| Latency | `fill_time` = 09:15 + 50..400 ms on the simulated clock | |

At **CLOSE (15:30)** the whole bar has happened. A resting LIMIT fills **at the limit** only if price traded **through** it (`low < limit` for BUY; a touch does not fill), capped by the same volume share, with no spread or slippage (it was passive). Whatever is unfilled then `EXPIRES` and the remaining reservation is released. Then every open position leg is marked at the session's close (a leg with no row, no trade that session, or a failed read keeps its last mark, flagged stale: under the owner's rule a zero-volume row has no price that day) and the account's `equity_snapshots` row is written.

Assumptions (`FillParams`, recorded in the results): half spread 0.05 % shares (the cost card's spread allowance), 0.02 % futures, 0.50 % options and at least one tick; slippage 3 / 2 / 20 bps × a seeded factor 0.5..1.5; volume share 10 %; latency 50..400 ms.

**Seed.** `random.Random(f"{seed}|{session}|{instrument key}|{side}")`: one stream per order, independent of order ids and of the order orders are processed in. Same seed, same fills. Results carry a `fingerprint`: sha256 of the id-free canonical rows of every order, fill, position leg and session snapshot.

**What OHLCV cannot tell (ARCH §10.6), stated in the results' limitations:** no queue position or depth; the time of a resting fill within the session; simultaneity of basket legs other than at the open; the session's volume is known to the fill engine at 09:15, as a capacity assumption only; spreads are proxies.

**Costs:** `desk_cost_card.order_side` (`desk-cost-v2`) by segment (equity delivery, futures, options) on each fill. Slippage is in the price, so the card's slippage component is 0 (as in `spt/paper/execution`). Brokerage once per order, on its first fill. A fill records `slippage_rs` and `spread_rs` so they stay measurable.

### 6.2 Live desk: from the live quote

Each live tick (5 s in session, 60 s otherwise) makes **one** quote read, before any row is locked, for everything that can be priced or marked now. Then, per intent:

| Condition | Outcome |
|---|---|
| Not a session day, or outside the fill window: cash 09:15–15:15 (F&O stocks' continuous trading ends at 15:15 since 3 Aug 2026), F&O 09:15–15:30 | waits; no quote is read |
| `QUOTE_MISSING`, `QUOTE_STALE` (older than 120 s by `received_at`), `QUOTE_NOT_TODAY`, `QUOTE_NOT_TRADED_TODAY`, `QUOTE_NO_PRICE` | **no fill**; `attempts` + 1, `last_no_fill_reason`; retries next tick |
| The binding no longer holds: STOP_NEW_ENTRIES, account not active, mode or policy changed, approval expired | no fill; the reason names the code; waits or expires |
| Price | BUY = ask (else LTP + half spread, labelled `ltp_spread`) × (1 + base slippage); SELL mirrored |
| LIMIT | a price past the limit fills at the limit if the ask or bid itself is inside it; else no fill |
| Collar / invalidation / lot | collar and invalidation: no fill this tick; lot differs from the exchange's: `REJECTED LOT_SIZE` |
| Quantity | up to the displayed quantity in whole lots; no displayed quantity: 25 % of the order per tick, at least one lot. One quote is used once per order |
| Basket | every leg fresh, full quantity displayed (or unknown), net inside `net_limit_rs`, or nothing fills |
| Past the session close | `EXPIRED`, reservation released |

The fill says which quote priced it (`price_source`: source, symbol, `received_at`). Open positions are marked from fresh quotes on the same tick while the market is open; a mark older than 120 s is flagged on read then, not presented as live (`mark_age_s`, `mark_stale`, `/capital` `marks.stale_legs`). The first tick after 15:31 on a session day writes the snapshot.

## 7. Live-price source (P2, P3): `market/live_quotes.py`

**Chosen: the feed's Redis cache first, then `ReadOnlyKite.quote()` over REST for what the cache does not hold.**

- **Redis** (`services/kite_live_feed/quote_cache.read_quotes`): the main backend's lease leader already writes `nivesh:quote:NSE:<SYM>` and `nivesh:quote:NFO:<TS>` with bid, ask, quantities, LTP, volume, `received_at`. The desk container has `REDIS_URL`. No Kite call, no token in the desk process, no second websocket against Kite's limits. It holds cash stocks, near-month futures and a window of index options.
- **REST** (`gateway.default_kite_factory` → `ReadOnlyKite`: `instruments`, `quote`, `historical_data`, `profile`; **no order method exists on it**): for what the socket does not carry, above all stock options and next-month futures, which the desk's plans use. This is the same path as `routes/live_quotes.py /fno-quotes`. The desk process calls `platform_token.refresh_cache(deps.db)` first (a non-leader process otherwise holds a stale token). One bounded call per tick; the contract list is read once per IST day.
- **Rejected:** `day_quote.py` (its docstring says nothing that fills a paper order reads it; provisional bars), the HTTP route (needs a user session), opening a second ticker (Kite's connection limit).
- **Freshness** is judged here, once, for both: `received_at` age ≤ 120 s (the feed's `exchange_ts` is the container's UTC clock labelled +05:30, so it is not used for age), today's IST date, a positive day volume, and for REST a `last_trade_time` of today (Kite answers a price for contracts that have not traded for days; 1970 for never).
- **Failure** (no login, Kite refuses, Redis down): the source answers no quote with the reason. Nothing falls back to an older price. The order waits and expires at the close. Only the owner can renew the daily login.

Tests use `FakeQuoteSource`, labelled in code as not real data.

## 8. Risk book and the existing APIs

`control/book.load_book` now reads equity from the ledger and marks, and its commitments are: approved plans with no intent yet, plus each trade's remaining risk in the ledger (reservations and open positions), so a filled plan stays counted after its plan row expires. Daily loss, weekly loss and drawdown checks stay SKIPPED: they go live with the lifecycle (DESIGN §7, Phase 3).

Contract notes for existing consumers:
- `results.execution` stays a string. New figures are in `results.execution_summary`.
- `TRADE_PROPOSAL` outcome `result` is `APPROVED` with an `execution` object when a gateway is wired; `APPROVED_NO_EXECUTION` remains only for no gateway. The desk's existing screens map both.
- New plan statuses and event types are additive.

## 9. Read APIs (signed in; 401 signed out; another tenant's id answers 404)

Lists follow `/trade-plans`: without `simulation_id` they show desk rows only; with it, that simulation's rows only. Money and prices are strings.

| Route | Answer |
|---|---|
| `GET /api/v1/accounts/{id}/capital` | every §3.1 measure, `reconciliation {equity_from_pnl_rs, equity_from_positions_rs, difference_rs}`, `marks {as_of, stale_legs}` |
| `GET /api/v1/accounts/{id}/capital/ledger?after_seq=&limit=` | ledger rows, ascending; with no cursor the newest `limit` |
| `GET /api/v1/accounts/{id}/reservations?status=` | reservations, newest first |
| `GET /api/v1/accounts/{id}/pnl` | gross realized, gross unrealized, charges by component, slippage + spread (measured), net realized, net unrealized, `by_strategy`, `daily` (day and cumulative), `max_drawdown_rs/_pct` |
| `GET /api/v1/execution/intents?account_id=&simulation_id=&trade_id=&status=` · `GET …/intents/{id}` | intents (with controls, refusal codes, order spec) |
| `GET /api/v1/execution/orders?account_id=&simulation_id=&trade_id=&state=` · `GET …/orders/{id}` | orders; the single read adds `history` (state moves) and `fills` |
| `GET /api/v1/execution/fills?account_id=&simulation_id=&trade_id=&order_id=` | fills, each with `fill_kind: SIMULATED`, `broker_confirmed: false` |
| `GET /api/v1/positions?account_id=&simulation_id=&status=` · `GET /api/v1/positions/{id}` | positions with legs, marks, unrealized P&L, charges |
| `GET /api/v1/journal?trade_id=&account_id=&simulation_id=&after_seq=&limit=` | the §12.1 chain in order |
| `GET /api/v1/simulations/{id}/results` | as before, plus `execution_summary`: `trades`, `net_pnl_rs`, `max_drawdown_rs`, `max_drawdown_pct` (the Studio's Run history columns), `intents`, `intents_refused`, `orders`, `orders_by_state`, `reject_codes`, `fills`, `reservations`, `positions`, `capital`, `pnl`, `fill_ratio`, `rejection_rate`, `fill_model`, `cost_model`, `reconciliation`, `fingerprint`, `seed` |

One write: `POST /api/v1/execution/orders/{id}/cancel` (PRD §17.4) withdraws a working paper order and releases what it held. 409 once the order is terminal.

## 10. Isolation (ARCH §10.4)

Own account and ledger per simulation (`simulation_id` on every row). `SimulationPaperAdapter` refuses an order with no simulation id; `LivePaperAdapter` refuses one that has one; the router reads `account.kind`, never client input. The simulator uses no quote source, the live desk no session bar reader. Writes go only to schema `autodesk` (AD-91).

## 11. Deferred

| What | When |
|---|---|
| Exits, stops, targets, trailing, partial exits, realized P&L from exits, `MARGIN_RELEASED`, expiry settlement of open positions | Phase 3 |
| Daily, weekly, drawdown limits acting on P&L; scenarios (gap, illiquidity injection) | Phase 3 |
| `amend` (MODIFY_PENDING) | Phase 3, answers "not available" until then |
| Emergency controls beyond STOP_NEW_ENTRIES (suspend strategy, cancel eligible entries in bulk) | Phase 3 |
| Reconciliation of UNKNOWN orders | Phase 3 (paper adapters have no external state, so UNKNOWN arises only from an adapter failure) |
| Allocation algorithms beyond fixed risk per trade (PRD §9.5) | The plan's sizing is the fixed risk method; others need owner choice |
| Exact exchange margin (SPAN), price-band and tick files, instrument master version | No data source wired; proxies labelled |
| Closing auction: desk close stays 15:30 for F&O, cash fills stop at 15:15; a SEBI revision reported for Dec 2026 needs a re-check | Re-check in December |
| Live shadow | Phase 4 |
