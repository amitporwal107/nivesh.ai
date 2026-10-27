# Phase 2.1 + 2.2 (+ F&O roll, + 2.6 storage) — test cases, authored before implementation

Branch `feat/p2-trade-plan-lifecycle` (off origin/dev `6a3ec2e3`). Acceptance standard:
`docs/NIVESH_AI_LAB_PHASE_SUCCESS_CRITERIA.md` Phase 2.1, 2.2 and the Phase 2 exit gate; design
`docs/ai_research/guidelines_gap_study_20261027/B_plan_lifecycle_exits.md` §10 Q8a/Q8b; roll design
`/home/deploy/phase0-approval/study_idea_persistence.md` §5 option C.

API and UI design, fixed before the code:

* `TradePlan` (`trade-plan-v1`, `services/strategy_plan/trade_plan.py`): `plan_id = "tp_" + digest(content)`
  (`strategy_plan/plan.digest`), content = strategy, instrument, timeframe, setup, entry {price, order_type, desk
  entry rule}, stop {price, method, atr, atr_multiple, swing_ref, measured_from, rationale, invalidation}, `r_per_unit`,
  targets [{name, price, r_multiple, rule}], size, costs (desk-cost-v2 breakdown), exit_plan {stop, targets, time,
  trailing/trend placeholders owned by `feat/p2-exits-backtest`, options premium stop from `strategy_levels`},
  evidence refs, risk flags, eligibility, data timestamps, rules version. Not hashed: `created_at`, `version`,
  `supersedes`, owners. `lifecycle.status` is `proposed` on a fresh plan and is DERIVED from linked trades on read.
* Mongo `trade_plans`, `_id = plan_id`, insert-once (`$setOnInsert`); a different plan for the same lineage
  (instrument, segment, family, direction, setup day) is stored as `version n+1` with `supersedes`, revalidated.
* `GET /api/desk/trade-plans/{plan_id}` — the plan, its derived lifecycle status, its versions and linked trades.
* `POST /api/desk/paper-trades` takes `plan_ref {plan_id, candidate_id, rules_version}`; the levels must equal the
  plan's (409 `plan_levels_mismatch`), the plan must be eligible (409 `plan_not_eligible`), unknown plan 404
  `plan_not_found`. The trade stores `plan_ref` and `plan_levels`.
* Lifecycle (`services/trade_lifecycle.py`): `NO_SETUP → WAIT_FOR_CONFIRMATION → TRADE_ELIGIBLE → ENTRY_TRIGGERED →
  POSITION_OPEN → EXIT_PENDING → CLOSED`, `REJECTED` terminal. `state` + append-only `transitions[]` on
  `desk_paper_trades` and `ai_trader_tickets`, each event written in the same conditional update that changes status.
* Roll: `GET /api/desk/paper-trades/{id}/roll` (preview, both legs and prices) and `POST …/roll` (executes;
  `Idempotency-Key` header). Both sides at session D's NSE bhavcopy `close_price`.
* Frontend: Top 10 stock row, AI watchlist cash row, F&O rows and the Builder send `plan_ref` and the plan's levels;
  F&O rows show the "conflicts with the cash setup" badge; Roll button + confirmation on the F&O paper-trade list
  and the paper-trade record.

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| TP-1 | TradePlan | Same inputs build the same plan twice | unit | identical `plan_id`; `created_at` not in the hash |
| TP-2 | TradePlan | Any level change (entry, stop, target) | unit | different `plan_id` |
| TP-3 | TradePlan, N13 | Scanner pick with stop = entry − 1.5×ATR (ICICIBANK 26 Oct real features) | unit | `stop.method = "atr"`, `atr_multiple = 1.5`; no "2 x ATR" text anywhere in the plan |
| TP-4 | TradePlan, N13 | Pick whose swing-low stop is tighter than 1.5 ATR | unit | `stop.method = "structural"`, `swing_ref` = the swing low |
| TP-5 | TradePlan | Targets carry R multiples | unit | t1 `r_multiple 2.0`, t2 `3.0`; `(t − entry)/R` equals the multiple to the paisa |
| TP-6 | TradePlan | Order type from the setup | unit | pre_breakout trigger above close → `stop_trigger` / `break_above`; ACCUMULATION below close → `limit_pullback` / `pullback_to`; confirmed → `at_close` / `at_once` |
| TP-7 | TradePlan | Costs | unit | `costs.model = desk-cost-v2`, breakdown equals `desk_trading.round_trip_breakdown` at the stop |
| TP-8 | TradePlan | Proposed vs approved | unit | fresh plan `lifecycle.status = "proposed"`; derived `approved/triggered/open/closed/rejected` from trades |
| TP-9 | TradePlan store | Insert-once | unit | second store of the same plan writes no new document; owner added |
| TP-10 | TradePlan store | Changed plan, same lineage | unit | stored as `version 2`, `supersedes` = v1 id, `revalidation.ok` recorded; an invalid change is stored with `revalidation.ok = false` and is not eligible |
| TP-11 | Options plan | F&O idea + `strategy_levels` | unit | `exit_plan.options` premium stop/T1/T2 = `strategy_levels.compute` for the same request; underlying stop/target = its underlying levels |
| TP-12 | N13 | Bearish stock F&O idea on a stock that is a bullish cash setup the same day | unit | `conflicts_with_cash_setup` set on the idea; its plan not eligible (REJECTED, `direction_conflict`) |
| TP-13 | N17 | Scanner re-run with different levels (real Postgres 16, throwaway container) | integration | old row copied to `positional_signals_history`, `revision` 2; an identical re-run writes no history |
| TP-14 | N17 | Migration 025 not applied | unit | pipeline falls back to the old upsert and logs an ERROR saying history is not recorded |
| LC-1 | Lifecycle | Allowed transitions table | unit | every PRD transition allowed; e.g. `CLOSED → POSITION_OPEN`, `REJECTED → *`, `NO_SETUP → POSITION_OPEN` refused |
| LC-2 | Lifecycle | Event fields | unit | from/to, at, IST session, reason, source, actor, rule version, signal/data timestamps, levels, qty, est. costs, risk decision id / rejection reasons, fill, slippage, exit reason |
| LC-3 | Lifecycle | at_once cash trade create | api | `state POSITION_OPEN`, transitions `∅→TRADE_ELIGIBLE→ENTRY_TRIGGERED→POSITION_OPEN` |
| LC-4 | Lifecycle | Conditional entry reached on read | api | `TRADE_ELIGIBLE→ENTRY_TRIGGERED→POSITION_OPEN` written once with fill and slippage; a second read writes nothing |
| LC-5 | Lifecycle | Stop exit on read; a second read; a racing manual close | api | `POSITION_OPEN→EXIT_PENDING→CLOSED` once, exit reason `stop`; no duplicate events |
| LC-6 | Lifecycle | Entry not reached | api | `TRADE_ELIGIBLE→CLOSED` exit reason `entry_not_reached` |
| LC-7 | Lifecycle | Strategy trade create and close | api | same chain on `kind: strategy`, close events in the same update as status |
| LC-8 | Lifecycle | Refused open (kill switch / duplicate / plan not eligible) | api | REJECTED recorded in `risk_decisions.detail.lifecycle` and, with a plan_ref, on the plan's events |
| LC-9 | Lifecycle | Replay / restart | unit | `replay(transitions)` rebuilds the stored state; a broken chain is reported, not silently fixed |
| LC-10 | Lifecycle | AI Trader tickets | api | paper cleared → `TRADE_ELIGIBLE→ENTRY_TRIGGERED→POSITION_OPEN`; governor refusal → `REJECTED`; assisted confirm / user reject / expire / desk refusal each one event |
| LC-11 | Lifecycle | Legacy trade without `state` closes | api | close update writes the derived history (flagged `derived`) then the close events |
| LC-12 | Plan status | Plan lifecycle derived from trades | api | GET trade-plan: `proposed` → `open` after a linked trade opens → `closed` after it closes |
| LC-13 | Backfill | `scripts/backfill_trade_lifecycle.py` | unit + staging read-only | dry run is the default and writes nothing; counts by derived state; `--apply` writes only docs without `state` (conditional) |
| PR-1 | Paper POST | Cash body with `plan_ref` and the plan's levels | api | 201; `plan_ref`, `plan_levels` stored |
| PR-2 | Paper POST | Levels differ from the plan | api | 409 `plan_levels_mismatch`, nothing written, REJECTED recorded |
| PR-3 | Paper POST | Unknown plan / another user's private plan | api | 404 `plan_not_found` |
| PR-4 | Paper POST | Plan not eligible (no_trade / direction conflict) | api | 409 `plan_not_eligible` with reasons |
| PR-5 | Paper POST | Strategy body with plan_ref (legs + underlying levels) | api | 201; mismatched leg → 409 |
| CT-1 | Contract | One `plan_id` across ideas / top / watchlist / builder / paper | contract | entry, stop and targets byte-identical in all five responses |
| CT-2 | Contract | The exact bodies the UI sends with `plan_ref` (shared fixture `contract-trade-plan-paper.json`) | contract | accepted by the real route; the Playwright specs assert the browser sends the same bodies |
| RL-1 | Roll | Fixture chain, roll on D after the bhavcopy is in | api | old closed `exit_reason roll` at D `close_price` (not settle); new trade on the next listed expiry, same family, strikes shifted by the same amount, legs at D `close_price`; costs desk-cost-v2 both sides |
| RL-2 | Roll | Before the D bhavcopy is in | api | 409 `roll_chain_not_ready` naming 22:15 IST; nothing written |
| RL-3 | Roll | A shifted strike is not listed on the next expiry | api | 409 `strike_not_listed` naming the strike; nothing written |
| RL-4 | Roll | Double click (same key, and a second key) | api | one close, one new trade; the second answers the same pair (`replayed`) |
| RL-5 | Roll | Link both ways | api | old `rolled_to` = new id; new `rolled_from.trade_id` = old id and a `rolled_from` source ref; plan lineage `rolled_from_plan_id` |
| RL-6 | Roll | Risk check | api | kill switch on → 409, old trade still open; insufficient funds → 409 before anything closes |
| RL-7 | Roll | Expiry day after close | api | allowed; old legs at D `close_price`, never `settle_price` (which holds the underlying on expiry day) |
| RL-8 | Roll | Not within the roll window / not a strategy / closed trade | api | 409 `roll_not_due` / 422 `not_a_strategy_trade` / 409 `trade_already_closed` |
| OP-1 | 2.6 | Strategy trade at entry stores the `strategy_levels` premium stop and T1/T2 | api | `exit_plan.options` stored; `evaluation` names `feat/p2-exits-backtest`; no exit is taken on it here |
| UI-1 | Top 10 stock row | Paper trade from the plan | e2e | body = plan levels + `plan_ref`; row shows plan id and stop method |
| UI-2 | AI watchlist cash row | Paper trade from the stored plan snapshot | e2e | body = stored plan levels + `plan_ref` |
| UI-3 | F&O rows | `plan_ref` and conflict badge | e2e | badge text; body carries `plan_ref`; not-eligible plan disables the button with its reason |
| UI-4 | Roll | Roll on the F&O paper-trade list and record | e2e | confirmation shows both legs and prices; confirm POSTs once; refusal reason shown |
| RG-1 | Regression | Full `backend/tests` on the branch vs origin/dev | suite | "fails on branch, passes on dev" list is empty |
| RG-2 | Regression | `tests/test_order_path_guard.py` | unit | passes: nothing places orders |
