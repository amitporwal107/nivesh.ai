# Test cases — paper fills, P&L and costs (branch `fix/paper-fills-pnl`, on top of `fix/desk-paper-safety`)

Authored before implementation, 2026-10-27. Scope: Phase 0 work items 0.2 (P&L from the simulated fill), 0.3 (entry
rules per setup, no impossible fills) and costs in sizing (part of 1.3); release gates 3 and 4 of
`docs/NIVESH_AI_LAB_GUIDELINES_GAP_STUDY.md` §9; criteria group 0.2 of
`docs/NIVESH_AI_LAB_PHASE_SUCCESS_CRITERIA.md`.

Probes on origin/dev `5b6b3cfd`: `gap_entry.py` (₹1,000 booked against ₹600 from the fill) and `stale_entry.py`
(FEDERALBNK booked `at_once` at 316.89 against a 26 Oct range of 337.20–344.80). The FEDERALBNK 26 Oct bar is real
(study B §7c); the 27 Oct bar is HYPOTHETICAL. Everything else is MOCK fixture data.

## Fill model (each rule pinned by a test)

| ID | Rule | Type | Expected |
|---|---|---|---|
| FM-1 | `at_once` entry inside the last completed session's low–high | api | 201; fill = the entry; `entry_status` assumed |
| FM-2 | `at_once` entry outside that range — FEDERALBNK 316.89 vs 337.20–344.80 | api | 422 `entry_not_tradable`, the message names the session and its range; nothing written; refusal recorded |
| FM-3 | `at_once` with no bar on record for the symbol | edge | 422 `entry_unverifiable`; nothing written |
| FM-4 | `at_once` when prices cannot be read | failure | 503 `prices_unavailable`; nothing written (no invented fill) |
| FM-5 | `break_above`: a later session's high reaches the entry | unit | fill = the entry |
| FM-6 | `break_above`: the session opens above the entry (gap-through entry) | unit | fill = the open; flag `entry_gap` |
| FM-7 | `pullback_to`: low reaches the entry; opens below it | unit | fill = the entry; on a gap down fill = the open |
| FM-8 | conditional entry not reached in its window | unit | closes `entry_not_reached`; no fill, no P&L, no costs; reservation released |
| FM-9 | gap through the stop | unit | exit fill = the open (worse than the stop); flag `gap_through_stop` |
| FM-10 | target jump: the session opens above the target | unit | exit fill = the target (documented as conservative: no credit for the better open) |
| FM-11 | stop and target inside one session | unit | the stop; flag `both_in_range` |
| FM-12 | partial fills | doc + unit | not modelled: the whole quantity fills or nothing does; a close takes no quantity (422 `unknown_field`) |
| FM-13 | a session with no high/low | unit | the scan stops there; the trade waits; nothing is invented |
| FM-14 | the FEDERALBNK body with `pullback_to` (what the Top 10 now sends for a level below the close) | unit | `waiting`; never filled at 316.89 by the 26 Oct bar |

## P&L from the simulated fill (gate 3)

| ID | Scenario | Type | Expected |
|---|---|---|---|
| P-1 | probe B2: break_above 100, opens 104, target 110, 100 shares | unit | `realized_pnl_rs` = 600 (not 1,000); costs from 104 and 110; net = 600 − costs; account credited that net |
| P-2 | an open trade's P&L and the same trade's closed P&L | unit | both from the fill (no jump at close) |
| P-3 | a closed trade stored without `costs_rs` (older record) | unit | costs recomputed from its stored `sim_entry_price` |
| P-4 | strategy trades | unit | open and closed P&L both use the recorded leg prices (no separate fill exists): consistent, no change |
| P-5 | gap-through-stop exit P&L | unit | (open − fill) x qty − costs |

## Costs consistent in sizing, risk reporting and realised P&L (gate 4)

| ID | Scenario | Type | Expected |
|---|---|---|---|
| C-1 | PRD Example A (entry 1005, stop 970, budget ₹3,000), plan sizing `size_position` | unit | 82 shares (85 before); net loss at the stop ≤ ₹3,000; the sizing says costs are included and gives gross and net |
| C-2 | the desk scenario `_trade_scenario`, Example A | unit | quantity 82; `loss_at_stop_net` ≤ budget |
| C-3 | the basket `_size_position` when the risk cap allows no share | unit | quantity 0 (no forced 1); risk cap includes costs |
| C-4 | one cost function: plan sizing cost at the stop = the desk's `est_costs_rs.at_stop` for the same trade = the realised costs of a stop exit filled at the entry and the stop | unit | equal to the paisa |
| C-5 | the cost model snapshot | unit | versioned (`version`), lists what it excludes (STT, stamp, exchange, SEBI, GST, DP); old trades keep their stored model |
| C-6 | tests that asserted the old gross-only numbers | unit | updated deliberately, each with the reason |

## Reconciliation invariants

| ID | Scenario | Type | Expected |
|---|---|---|---|
| R-1 | entry then full exit at the target, stop, time and by hand | unit/api | `realized_pnl_rs` = (exit fill − entry fill) x qty; `net_pnl_rs` = that − `costs_rs`; account `cash` = start + Σ net; `blocked` = Σ open reservations; ledger reserves − releases = blocked |
| R-2 | cancellation (conditional entry not reached, or cancelled by hand) | api | no P&L, no costs; reservation released; cash unchanged |
| R-3 | a refused or replayed submission | api | cash and blocked unchanged; no ledger row |
| R-4 | partial exit | doc | not supported; stated in the fill-model doc |

## Entry rules per setup (frontend)

| ID | Scenario | Type | Expected |
|---|---|---|---|
| ER-1 | `entryRuleFor`: entry above the close → `break_above`; below → `pullback_to`; at the close → `at_once`; no close → the stage/bucket table | unit (in e2e) | as stated |
| ER-2 | Top 10 "Add paper trade" | e2e | body carries `entry_rule` and the key; the note says how the entry fills |
| ER-3 | AI watchlist "Add paper trade" | e2e | same |
| ER-4 | Scanner tab paper trade | e2e | same |
| ER-5 | Strategy Builder sizing line | e2e | says the risk at the stop is after estimated costs |
| ER-6 | tsc and production build | build | clean |

## Live execution unchanged

| ID | Scenario | Type | Expected |
|---|---|---|---|
| L-1 | `tests/test_order_path_guard.py` | unit | passes |

## Staging verification (after an approved deploy; not run here)

| ID | Scenario | Expected |
|---|---|---|
| S-1 | POST an `at_once` trade far from the last range (test user) | 422 `entry_not_tradable` with the range |
| S-2 | read-only: existing closed trades keep their stored P&L (no backfill) | unchanged |
