# Test cases — desk paper safety (branch `fix/desk-paper-safety`)

Authored before implementation, 2026-10-27. Scope: Phase 0 work items 0.4 (kill switch), 0.5 (duplicates,
idempotency), 0.6 (futures validator) and the refusal audit; release gates 1 and 2 of
`docs/NIVESH_AI_LAB_GUIDELINES_GAP_STUDY.md` §9, and criteria group 0.3 of
`docs/NIVESH_AI_LAB_PHASE_SUCCESS_CRITERIA.md`.

Probes that reproduce the defects on origin/dev `5b6b3cfd` (study `guidelines_gap_study_20261027/probe/`):
`test_probe_bypass.py` (journal fill 200 with the kill switch on; identical desk POST 201 201 201) and the
study A probes D1/D2 (short future accepted as `defined_risk: True`; NIFTY lot 1 accepted).

Backend tests run in `nivesh/backend:staging` with the worktree mounted read-only and `--network none`. They feed
the exact body shapes the UI sends (`trade_body`, `strategy_body`, the Strategy Builder's `strategyPaperBody`).
MOCK — not real data: FIXA, FIXU, MOCKA and their prices are the suites' made-up fixtures.

## Gate 1 — no paper trade while the kill switch is on (every path, gate off and on)

| ID | Path | Scenario | Type | Expected |
|---|---|---|---|---|
| K-1 | desk cash `POST /api/desk/paper-trades` | kill switch on, gate off | api | 409 `risk_blocked`; no trade, no account row, no ledger row; one `risk_decisions` row with path, symbol, correlation id |
| K-2 | desk cash | kill switch on, gate on | api | 409 `risk_blocked` (`kill_switch_on`); nothing written |
| K-3 | desk strategy (kind `strategy`) | kill switch on, gate off and on | api | 409; nothing written |
| K-4 | journal create `POST /api/positional/journal` | kill switch on, gate off and on | api | 409; no journal row |
| K-5 | journal ENTRY fill `POST /api/positional/journal/{id}/fill` | kill switch on, **gate off** (the bypass) | api | 409 `risk_blocked`; no fill; decision row with path `journal_fill`, symbol, requested qty, correlation id |
| K-6 | journal ENTRY fill | kill switch on, gate on | api | 409; no fill |
| K-7 | journal EXIT fill | kill switch on, gate off and on | api | 200: selling out reduces risk and is not blocked |
| K-8 | journal ENTRY fill | halted (not kill switch), gate off | api | 409 |
| K-9 | journal ENTRY fill | controls store unreadable, gate off | failure | 409 (fail closed); no fill |
| K-10 | AI trader `POST .../signals` (paper) | kill switch on, gate off | api | governor halts: ticket recorded as refused, **no desk trade** |
| K-11 | AI trader signals | kill switch on, gate on | api | 409; no ticket, no trade (existing test kept) |
| K-12 | AI trader `POST /tickets/{id}/confirm` | kill switch on, gate off and on | api | 409; no desk trade; ticket still awaiting |
| K-13 | tests that locked the bypass in | `test_flag_off_a_journal_entry_is_as_before`, `test_the_fill_write_is_filtered_on_owner_and_status` | unit | flipped: with the flag off the kill switch is still consulted and refuses |

## Gate 2 — a repeated submission creates neither a second trade nor a second reservation

| ID | Scenario | Type | Expected |
|---|---|---|---|
| I-1 | same `Idempotency-Key`, same body, twice (cash) | api | first 201; second 200 with the **same trade id** and `replayed: true`; one trade, one ledger `reserve`, `blocked_rs` = one reservation |
| I-2 | same key, same body, twice (strategy) | api | as I-1 |
| I-3 | same key, different body | api | 409 `idempotency_conflict`; nothing written; refusal recorded |
| I-4 | malformed key (too long, bad characters) | edge | 422 `invalid_idempotency_key`; nothing written |
| I-5 | two requests with one key race past the lookup (insert hits the unique index) | failure | the loser answers with the winner's trade; its reservation is released; net blocked = one reservation |
| I-6 | no key, second identical cash POST (the HAL x3 case) | api | 409 `duplicate_open_trade` with `existing_trade_id`; no second reservation; refusal recorded |
| I-7 | a second open cash trade in the same symbol at other levels or quantity | api | 409 `duplicate_open_trade` (adding is not supported yet, PRD §7) |
| I-8 | same symbol after the first trade closed; another symbol | api | 201 |
| I-9 | an open trade stored before this change (no `open_key`, like staging's ICICIBANK x2) | api | a new trade in that symbol is refused 409 with that trade's id |
| I-10 | strategy: identical open structure (same underlying, legs; different premium) | api | 409 `duplicate_open_structure` with the existing id |
| I-11 | strategy: different strikes or expiry | api | 201 |
| I-12 | race on the open-position index (insert hits `user_id + open_key`) | failure | 409 `duplicate_open_trade`; reservation released |
| I-13 | indexes | unit | unique, partial indexes on `(user_id, idempotency_key)` and `(user_id, open_key)` are requested |
| I-14 | closing a trade frees its symbol (`open_key` cleared by the cash and the strategy close) | unit | `open_key` is null on the closed document |
| I-15 | AI trader paper trades (written directly) are unaffected | regression | existing AI trader suites pass |

## Futures are not defined risk (0.6)

| ID | Scenario | Type | Expected |
|---|---|---|---|
| F-1 | long future only, with a stop (gate off) | api | 201; `risk.defined_risk` false; unbounded note |
| F-2 | short future only (probe D1) | api | 422 `short_futures_not_supported`; nothing written; recorded |
| F-3 | a futures leg with no `stop_underlying` | api | 422 `futures_stop_required` |
| F-4 | gate off, lot size 1 where the exchange lot is 250 (probe D2) | api | 422 `lot_size_mismatch` with the exchange lot, source and date in the message |
| F-5 | gate off, exchange reference unreadable | failure | 422 `lot_size_unverified` with the reason; nothing written |
| F-6 | option spread, correct lot | api | 201; `defined_risk` true (unchanged) |
| F-7 | short future covered by a long call | api | 201; `defined_risk` false (futures exposure) |
| F-8 | gate on | api | the gate's own lot check decides (no second lookup); a mismatch is the gate's 409 |
| F-9 | the Strategy Builder's long-future body (`strategyPaperBody` shape) | contract | 201 |
| F-10 | Strategy Builder short-future candidate | unit (UI rule) | `paperBlocker` names the reason before any request |

## Refusal audit (item 4)

| ID | Scenario | Type | Expected |
|---|---|---|---|
| A-1 | each new refusal: kill switch (desk, journal create, journal fill), duplicate, idempotency conflict, validator 422, lot size, funding 409, open-trade limit 409 | api | one `risk_decisions` row: `outcome` blocked, `reasons[0].code` = the answer's code, `path`, `correlation_id`, `symbol` where known |
| A-2 | the decision store fails on a refusal | failure | the refusal still answers its own code (the record is fail-open, as `record_decision` documents) |

## Frontend

| ID | Scenario | Type | Expected |
|---|---|---|---|
| UI-1 | Top 10 "Add paper trade" | e2e (mocked API) | the POST carries an `Idempotency-Key` header; the body shape is unchanged |
| UI-2 | the same submission retried after a failure | e2e | the retry reuses the key; a changed quantity gets a new key |
| UI-3 | the route answers 409 `duplicate_open_trade` | e2e | the existing error line shows the server's message and the code |
| UI-4 | AI watchlist and Strategy Builder paper POSTs | e2e | carry the header |
| UI-5 | tsc and production build | build | clean |

## Live execution unchanged

| ID | Scenario | Type | Expected |
|---|---|---|---|
| L-1 | `tests/test_order_path_guard.py` | unit | passes: no order call anywhere |

## Staging verification (after an approved deploy; not run on this branch — no staging writes allowed)

| ID | Scenario | Expected |
|---|---|---|
| S-1 | `curl` POST twice with one key (test user, kill switch off) | 201 then 200 with one id |
| S-2 | kill switch on, gate off, journal ENTRY fill | 409 |
| S-3 | read-only: `risk_decisions` rows for the refusals carry path and correlation id | present |
