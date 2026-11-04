# Scanner-to-Paper Trading (SPT): build design for the overnight build of 5 Nov 2026

**Requirements:**
- `docs/prd/Nivesh_Scanner_Paper_Trading_Capital_Allocation_Risk_Management_PRD.md` (the PRD)
- `docs/prd/Nivesh_Scanner_to_Paper_Trading_Workflow.md` (the Workflow, or WF)

**What exists:** `docs/scanner_paper_trading/EXISTING_CODE_MAP.md`. **Read it first: most of the risk engine and the paper
ledger are already built.**

The owner, 5 Nov ~01:30 IST: "Please ignore the requirement given in earlier conversation … Most of the things are
already in place, some needs changes and some requires addition of new changes." He then sent the Workflow, and:
"assign as many agent as possible to finish this work overnight".

## 1. Decisions taken for the build

These are reversible and listed in the morning review for the owner to confirm.

| # | Decision | Why |
|---|---|---|
| D1 | **MongoDB, not PostgreSQL** (PRD §16 deviation). New collections are prefixed `spt_`. | The paper ledger, risk decisions, reservations and the risk book are all in Mongo with atomic conditional updates and idempotency keys. A second system of record would split one paper account across two databases. Every store goes through a `store.py` module, so moving later touches one file per slice. |
| D2 | **Extend, don't duplicate.** | Risk decisions go through `services/risk_gate/service.enter` with a new path `spt_entry`. Budget goes through `services/paper_account` (reserve_entry / release / cancel_reservation). The kill switch is `services/risk_controls`. Limits come from `services/risk_profile` (the owner's limits). SPT adds only what is missing. |
| D3 | **One paper account per user** (the existing one, ₹10 lakh default) plus an SPT config doc per user. | Named multiple accounts (PRD §16.1) are a later change; `account_id` = `user_id` in the API for now. |
| D4 | **Account mode:** `off` (default) / `tracking` / `approval` / `auto`. | PRD §26 says "user approval initially". A user opts in with `PUT /api/v1/paper/accounts/{id}/config`. Nothing is booked for anyone who has not opted in. |
| D5 | **Tradable tonight: positional, long, cash equity.** | Owner 4 Nov: positional, long only, scan-plan-v3. Intraday, bearish, F&O and fundamental-only signals are still ingested, consolidated, validated and tracked (Mode C outcomes). Their proposals end as `NOT_TRADABLE` with reason `horizon_not_enabled`, `direction_not_enabled` or `instrument_not_enabled`. F&O defined-risk proposals through `services/strategy_plan` are a P1 stretch for slice B. |
| D6 | **Execution model `spt-exec-v1`.** | See §6. In session: bid/ask from the live quote cache, with partial fills capped at the displayed depth. Never fill from a missing or stale quote (WF §20). Out of session: the order stays PENDING and is never filled from a bar. |
| D7 | **No multi-document transactions** (staging Mongo is a single node). | Single-document conditional updates with `version`/`state` in the filter, idempotency keys on every write, and a reconciliation function per slice. |
| D8 | **New routes under `/api/v1/...`** (PRD §17). | The existing `/api/desk/...` routes are untouched. Streams use SSE like `/api/desk/pnl/stream`; there are no WebSockets tonight. |
| D9 | **No UI tonight.** | The owner is designing the trading screens himself (Paper Lab hold, 27 Oct). APIs are built to PRD §19's data needs. |
| D10 | **Standard words** (entry, stop loss, target) are allowed in these APIs. | They describe the user's own paper account, like the P&L dashboard (owner 3–4 Nov). Never "recommend", "pick" or "suggested". |

## 2. Layout and ownership

All new code is under `backend/services/spt/` and `backend/routes/spt_*.py`.

**Shared (written before the build; do not change the contracts without telling the integrator):**
- `services/spt/constants.py`: states, decisions, event types, versions.
- `services/spt/events.py`: the event envelope (WF §22) and the `spt_events` writer.

| Slice | Owner | Paths | Branch / worktree |
|---|---|---|---|
| **A: signals → opportunities → validation → signal outcomes** | agent A | `services/spt/signals/`, `services/spt/opportunities/`, `services/spt/outcomes/`, `routes/spt_signals.py`, `scripts/spt_backfill_signals.py`, a minimal hook in `services/scan_builder/signals.py` | `feat/spt-signals` · `/home/deploy/nivesh-wt-spt-a` |
| **B: proposal → sizing → allocation → risk → pipeline, plus account config/modes** | agent B | `services/spt/proposals.py`, `sizing.py`, `allocation.py`, `risk.py`, `policy.py`, `pipeline.py`, `routes/spt_risk.py`, `routes/spt_accounts.py`. Minimal edits: `services/risk_gate/service.py` (add path `spt_entry`; nothing else unless a test proves it is needed) | `feat/spt-risk-pipeline` · `/home/deploy/nivesh-wt-spt-b` |
| **C: paper orders → execution → fills → positions → monitoring/exits/modifications** | agent C | `services/spt/paper/`, `routes/spt_paper.py` | `feat/spt-paper-exec` · `/home/deploy/nivesh-wt-spt-c` |
| **Integration** (server.py startup and routers, CI allowlist, staging verification, report, PRs) | integrator | `server.py`, `.github/workflows/backend-tests.yml` | `feat/spt-integration` |

**No slice edits** `server.py`, `.github/`, `frontend*/`, or another slice's directory. Each slice exposes:
- `router` objects
- `start()` / `stop()` for its loop

The integrator wires them in.

## 3. Collections (all Mongo, all timestamps UTC ISO strings, IST trading day kept as `day`)

| Collection | Writer | Key / idempotency | Holds |
|---|---|---|---|
| `spt_signal_events` | A | `_id` = `sig:<day>:<widget>:<SYM>` (list entry) or `sig:<day>:strong:<SYM>` (strong); insert-only | the immutable scanner event (PRD §6.2 fields) + normalized fields |
| `spt_opportunities` | A | `_id` uuid4; unique `consolidation_key` while open | market-wide consolidated opportunity + validation |
| `spt_signal_outcomes` | A | `_id` = signal event id | T+1/5/10/20, MFE/MAE, hypothetical plan outcome |
| `spt_account_config` | B | `_id` = `user_id`; `version` increments; history in `spt_account_config_versions` | mode, SPT risk extras, allocation buckets |
| `spt_proposals` | B | `_id` uuid4; unique (`user_id`, `opportunity_id`) | per-account proposal, sizing, allocation, risk decision, per-account state |
| `spt_orders` | C | `_id` = order id (uuid4) = the risk reservation's `trade_id`; unique `idempotency_key` | order + state machine |
| `spt_fills` | C | `_id` uuid4; unique (`order_id`, `seq`) | every simulated fill |
| `spt_positions` | C | `_id` uuid4; one open position per (`user_id`, symbol, direction) | open/closed positions, stop/target plan, modifications |
| `spt_events` | all (via `events.py`) | `_id` = event_id; unique `idempotency_key` | the append-only event log (WF §22) |
| `spt_state` | A/B/C loops | `_id` = loop name | last round, leader, errors (for the morning check) |

## 4. Shared contracts

**Opportunity document** (written by A, read by B):

```
{_id, consolidation_key, symbol, exchange:"NSE", direction:"long"|"short", family, category, horizon:"positional"|"intraday",
 day, first_seen_at, window_until, expires_at, state (constants.OPP_*), version,
 signals:[{signal_id, scanner_id, scanner_name, detected_at, detected_price, scanner_score, score_version, category, family}],
 conflicts:[{signal_id, scanner_id, direction, detected_at}],
 strong: null | {signal_id, first_strong, score_at, parts_at, reasons_at, penalties_at,
                 plan:{rules:"scan-plan-v3", entry, stop_loss, target_1, target_2, atr, sma20, trend_exit, plan_ok, plan_note}},
 validation: null | {at, version, decision (OPP_*), reason_codes:[...], explanations:[...], opportunity_score, score_parts,
                     market:{...}, stock:{...}, liquidity:{adv_rs, ...}, derivatives:{...}|null, data_as_of:{...}, revalidate_at},
 created_at, updated_at}
```

**QUALIFIED** (tonight) requires all of:
- a strong signal with `plan_ok`
- direction long
- horizon positional
- validation passes: data fresh, liquidity ≥ the policy minimum, not a risk-off regime. Risk-off → `CONDITIONAL`.

**Read interface from A:**
- `services/spt/opportunities/store.py`:
  - `async get(db, opp_id) -> dict|None`
  - `async list_by_state(db, states, *, day=None, limit=500) -> list`
  - `async transition(db, opp_id, *, expect_states, to_state, reason, extra=None) -> dict|None`
- B never writes `spt_opportunities` except through `transition`, and only for the market-wide `EXPIRED` when a proposal
  finds the plan stale.

**Proposal → order call from B to C:**
- `services/spt/paper/orders.py`:

  ```
  async create_entry_order(db, *, user_id, proposal_id, opportunity_id, risk_decision, symbol, side, order_type,
                           quantity, limit_price, trigger_price, time_in_force, expires_at, exit_plan, idempotency_key)
      -> order dict
  ```

  - `risk_decision` is the dict returned by `risk_gate.service.enter`; its `reservation_id` is kept on the order.
  - `order_id` must equal the `trade_id` passed to `enter`, and `EntryRequest.store = "spt_orders"`, so the account's
    orphan sweep finds the order. **B generates the order id** and passes it in as `order_id=`.

- `exit_plan` is
  `{stop_loss, target_1, target_2, t1_exit_fraction:0.5, move_stop_to_breakeven_at_t1:true, trail:{rule:"trail-atr-v1", k:2}|null, trend_exit:{rule:"close_below_sma20"}|null, max_hold_sessions:20}`.

**Modification check from C to B:**
- `services/spt/risk.py`: `async check_modification(db, *, user_id, position, change) -> {decision, reason_codes, explanations, decision_id}`.
- It is called only for risk-increasing changes (a wider stop, more quantity, removing a stop).
- Risk-reducing changes and exits never go through it: they are always allowed, also under the kill switch (PRD §18 rules 12–14).

**Account state for B:**
- B reads the account through the existing `services/paper_account.read` and `services/risk_book.read`.
- C keeps those current: it calls `paper_account.release(..., trade_id=order_id, net_pnl=...)` on close, and
  `risk_gate.service.release_unused` or `paper_account.cancel_reservation` when an entry order ends unfilled.

## 5. State machines (constants.py)

- **Opportunity (market-wide, A):**
  - CREATED → VALIDATING → QUALIFIED | CONDITIONAL | WATCHLIST | REJECTED | DATA_INSUFFICIENT
  - any open state → EXPIRED
  - CONDITIONAL / WATCHLIST / DATA_INSUFFICIENT → VALIDATING (revalidation)
- **Proposal (per account, B):**
  - PROPOSAL_GENERATED → AWAITING_RISK → BLOCKED_BY_RISK | REJECTED | NOT_TRADABLE | RISK_APPROVED
  - RISK_APPROVED → AWAITING_USER_APPROVAL (approval mode) → USER_REJECTED | APPROVAL_EXPIRED | READY_FOR_ORDER
  - RISK_APPROVED → READY_FOR_ORDER (auto mode)
  - READY_FOR_ORDER → ORDER_CREATED
  - tracking mode: RISK_APPROVED → TRACKING_ONLY
- **Order (C):** CREATED → VALIDATED → PENDING → PARTIALLY_FILLED → FILLED, with CANCELLED / EXPIRED / REJECTED from
  CREATED, VALIDATED, PENDING or PARTIALLY_FILLED.
- **Position (C):** OPEN → MONITORING → PARTIALLY_EXITED → MONITORING → CLOSING → CLOSED, plus RISK_RESTRICTED,
  EXIT_PENDING, EXECUTION_EXCEPTION and RECONCILIATION_REQUIRED.
- **Risk decision (B):** APPROVE, APPROVE_REDUCED, CONDITIONAL_APPROVAL, REJECT, BLOCKED, EXIT_REQUIRED, HALT_ACCOUNT. These
  are mapped from the risk service's allow/reduce/block plus SPT's own checks:
  - drawdown ladder: 2% reduce, 4% restricted, 6% halt — the PRD §9.7 defaults, configurable in `spt_account_config`
  - stressed risk
  - max positions
  - min R:R for the strategy

## 6. Execution model `spt-exec-v1` (slice C)

**Entry, in session** (09:15–15:30 IST weekdays):
- Read the quote cache (`services/kite_live_feed/quote_cache.read_quotes`).
- Use it only when it was received ≤ 120 s ago (`SPT_QUOTE_MAX_AGE_S`).
- **BUY** marketable at the best ask + slippage (desk-cost-v2's 0.05%); **SELL** at the best bid − slippage.
- If depth is present, fill up to the displayed quantity across the 5 levels, each level at its own price. The remainder
  stays PENDING for the next round (a partial fill).
- If depth is absent, fill at most `SPT_NO_DEPTH_MAX_QTY_FRACTION` of the order per round, at LTP ± a spread allowance,
  marked `depth_unknown: true`. Never fill the whole order on a guess.
- **LIMIT** fills only when the ask ≤ the limit (buy). **SL / SL-M** trigger on LTP crossing the trigger, then fill as
  marketable.

**Out of session:** no fills. The order waits until its time in force: DAY expires at 15:30 IST, GTD at `expires_at`.

**No quote or a stale quote:** no fill, `last_attempt.reason = "quote_stale"`. A day of stale quotes ends with the order
EXPIRED and the reservation cancelled.

**Costs:** the desk cost card (`desk-cost-v2`) per fill, snapshotted on the order.

**Exits (monitor loop, every 15 s in session, leader-locked):**
- The stop triggers on the live bid ≤ stop; the target on the live bid ≥ target.
- T1 exits `t1_exit_fraction` of the position and moves the stop to breakeven, the entry average plus costs per share.
- T2 exits the rest.
- Fills go through the same depth-limited model.
- **Evening pass** (after NSE's end-of-day file): `exit_rules.step` for the ATR trail, the trend exit (close below the
  SMA20 → exit at the next session's first live quote) and the time exit.
- **A gap through the stop at the open:** exit at the first live bid; the gap is flagged.

**Kill switch / halt / daily-loss block:** new entries are refused and pending ENTRY orders cancelled. Exits and
risk-reducing changes keep working.

## 7. Events (events.py)

Each event gets the envelope from WF §22. `event_type` is one of WF §22's types plus:
- `SIGNAL_CONFLICT_DETECTED`
- `OPPORTUNITY_VALIDATED`
- `PROPOSAL_STATE_CHANGED`
- `ORDER_EXPIRED`
- `POSITION_PARTIALLY_EXITED`
- `STOP_MOVED`

`idempotency_key` is stable per business fact, so replays insert nothing new.

## 8. Testing and verification rules (every slice)

1. **Test cases first.** Write `test_reports/spt_<slice>_TESTCASES.md` (ids `SPT-A-01…`, `SPT-B-01…`, `SPT-C-01…`)
   before implementing. Cover the WF §25 acceptance criteria that belong to the slice and the PRD §23.3 scenarios that
   apply.
2. **Unit tests.** Write `backend/tests/test_spt_<slice>_*.py` with in-memory fakes, following
   `tests/test_desk_trading.FakeCollection` / `tests/test_exit_watch.py`.
3. **Run them in the backend image:**

   ```
   sudo -n docker run --rm --network none -v <worktree>:/work:ro -w /work/backend -e PYTHONDONTWRITEBYTECODE=1 \
     -e MONGO_URL=mongodb://localhost:27017 -e DB_NAME=unit_test -e OPENAI_API_KEY=unit-test-placeholder \
     nivesh/backend:staging python -m pytest tests/test_spt_<slice>_*.py <neighbour suites> -q
   ```

   Neighbour suites must stay green:
   - A: `test_scan_builder*`
   - B: `test_risk*`, `test_paper_account*`, `test_desk_trading*`
   - C: `test_paper*`, `test_desk_trading*`, `test_exit_rules*`
4. **No writes to staging** (Mongo, Redis, Postgres, containers). Read-only peeks at data shapes are allowed only by
   `sudo -n docker exec -i nivesh-staging-app-backend python -` scripts that read, never print secrets or user data, and
   never write. The 4 Nov signal archive (`/home/deploy/nivesh-signal-archive/redis_dump_20261105.jsonl`) is
   market-wide data and may be read for fixtures. **Never put real user positions in fixtures.**
5. **Commit** to your own branch in your own worktree, in small commits. **Do not push.**

## 9. Out of scope tonight (listed in the morning review)

- UI screens (PRD §19)
- WebSockets
- PostgreSQL migration of the ledger
- named multiple accounts
- F&O multi-leg execution and legging (P1)
- correlation matrix and portfolio VaR/CVaR (P1: the risk service's correlation check stays "skipped" with its reason)
- optimisation libraries (P2: `riskfolio` etc. are not installed and not needed for the deterministic P0)
- intraday trading
- bearish trades
- outbound notifications
