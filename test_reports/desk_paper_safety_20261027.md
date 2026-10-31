# Functionality Verification Report — Desk paper safety (kill switch on every path, idempotent submit, no duplicates, futures not defined risk)

- **Branch:** fix/desk-paper-safety (off origin/dev 5b6b3cfd)
- **Date:** 2026-10-27
- **Author:** Claude (full-stack developer + QA)
- **Environment:** local containers (`nivesh/backend:staging` image, `--network none`, worktree read-only; Playwright 1.47 Chromium against a production build with a mocked API). Staging was read only; nothing was deployed or written.
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary
Phase 0 items 0.4, 0.5 and 0.6 and the refusal audit (release gates 1 and 2; criteria group 0.3).
1. The journal ENTRY fill now checks the kill switch and halt when the F&O gate is off (it was skipped:
   `positional_journal.py:315`). Journal create and fill refusals are recorded with path, symbol and correlation id.
2. `POST /api/desk/paper-trades` takes an `Idempotency-Key` header (8–64 chars). The same key returns the first
   trade (200, `replayed: true`) with no second reservation; the same key with another body is 409
   `idempotency_conflict`. A second OPEN cash trade in a symbol is 409 `duplicate_open_trade`, and an identical open
   structure is 409 `duplicate_open_structure`; both carry `existing_trade_id`. Two unique partial indexes,
   `(user_id, idempotency_key)` and `(user_id, open_key)`, make the rule hold under races. The frontend sends one key
   per submission (a retry reuses it) and shows the 409 reason.
3. Any futures leg is now `defined_risk: false`. A short futures-only structure is refused
   (`short_futures_not_supported`, decision D2). A futures leg needs `stop_underlying`. The exchange lot is enforced
   with the gate off, using the gate's own reference, and fails closed (`lot_size_mismatch` / `lot_size_unverified`
   with the reason). The Strategy Builder blocks a short-futures candidate before sending.
4. Every refusal of a desk create is recorded through `risk_controls.record_decision` with its code, path
   `desk_paper_trade`, correlation id, symbol and quantity: kill switch, validator 422, duplicate, idempotency conflict,
   lot size, funds and open-trade cap.

## Test Cases
Authored up front in `test_reports/desk_paper_safety_TESTCASES.md`. Results below; evidence in the sections that follow.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| K-1/2/3 | desk cash + strategy | kill switch or halt on, gate off and on | api | 409, nothing written, recorded | PASS |
| K-4..K-8 | journal create, ENTRY fill, EXIT fill | kill switch or halt, gate off and on; ₹1 crore fill | api | 409 / 409 / 200 | PASS (failed on base: fill 200) |
| K-9 | journal fill | controls unreadable | failure | 409 | PASS |
| K-10..K-12 | AI trader signals / confirm | kill switch, gate off and on | api | no desk trade | PASS (also passes on base: the governor already halted; now locked by tests) |
| K-13 | flipped tests | `test_flag_off_a_journal_entry_is_as_before`, `test_the_fill_write_is_filtered_on_owner_and_status` | unit | refuse with the switch on | PASS (fail on base) |
| I-1/I-2 | idempotency | same key twice, cash and strategy | api | one trade, one reserve, 200 replay | PASS (base: 201 twice) |
| I-3 | idempotency | same key, other body | api | 409 idempotency_conflict | PASS |
| I-4 | idempotency | malformed key x4 | edge | 422 | PASS |
| I-5 | idempotency | race on one key (unique index) | failure | winner's trade; loser's reservation released | PASS |
| I-6/I-7 | duplicates | identical and different-level second trade (HAL x3 case) | api | 409 with existing id | PASS (base: 201) |
| I-8/I-14 | duplicates | after close; other symbol; other user | api | 201; `open_key` null after close | PASS |
| I-8b | duplicates | a trade closed by older code with its key still set | api | 201 (the index covers open trades only) | PASS |
| I-9 | duplicates | grandfathered open trade without `open_key` | api | 409 | PASS |
| I-10/I-11 | duplicates | identical structure (repriced, reordered) / other strikes | api | 409 / 201 | PASS |
| I-12 | duplicates | race on the open-position index | failure | 409; reservation released | PASS |
| I-13 | indexes | the two unique partial indexes are requested | unit | present | PASS |
| I-15 | AI trader | suites unchanged | regression | pass | PASS |
| F-1/F-9 | futures | Builder long-future body | contract | 201, defined_risk false | PASS (base: true) |
| F-2 | futures | short future only (probe D1) | api | 422 short_futures_not_supported | PASS (base: 201) |
| F-3 | futures | no stop | api | 422 futures_stop_required | PASS |
| F-4 | futures | lot size 1 vs exchange 250, future and spread (probe D2) | api | 422 lot_size_mismatch with lot, source | PASS (base: 201) |
| F-5 | futures | reference unusable / raising | failure | 422 lot_size_unverified with reason | PASS |
| F-6/F-7 | futures | spread / hedged future | api | defined_risk true / false | PASS |
| F-8 | futures | gate on: one lookup (the gate's) | api | gate's 409 | PASS |
| F-10 | UI | Builder short-futures candidate | e2e | blocked before any request | PASS |
| A-1 | audit | 7 refusal kinds | api | one row each: code, path, correlation id, symbol, http status | PASS |
| A-2 | audit | decision store down | failure | refusal still answered | PASS |
| UI-1..UI-4 | frontend | key header on Top 10, AI watchlist, Builder; retry reuses; new body new key; 409 text | e2e | as stated | PASS |
| UI-5 | frontend | tsc + production build | build | clean | PASS |
| L-1 | live execution | `test_order_path_guard.py` | unit | pass | PASS |
| S-1..S-3 | staging | POST twice / fill with switch on / decision rows | staging api | — | NOT RUN (no deploy allowed; see below) |

## API / Endpoint Tests (staging)
**Not run on staging.** The brief forbids any staging write or deploy, and these endpoints write. The code on staging is
still origin/dev, so a staging call would test the old code. In place of that, the real FastAPI routers were exercised
through `TestClient` with the desk's in-memory fakes, and the request bodies are the ones the UI sends.

- **pytest (all suites the change touches, plus the new one):**
  - Command: `sudo docker run --rm --network none -v /home/deploy/nivesh-desk-integrity:/work:ro -w /work/backend -e PYTHONDONTWRITEBYTECODE=1 -e MONGO_URL=mongodb://localhost:27017 -e DB_NAME=unit_test -e OPENAI_API_KEY=unit-test-placeholder nivesh/backend:staging python -m pytest tests/test_desk_trading.py tests/test_desk_paper_sim.py tests/test_desk_strategy_trades.py tests/test_paper_account.py tests/test_risk_controls.py tests/test_risk_gate.py tests/test_risk_gate_ai_trader.py tests/test_risk_gate_desk_journal.py tests/test_risk_replay.py tests/test_risk_routes.py tests/test_ai_trader.py tests/test_ai_trader_config_risk.py tests/test_ai_trader_execution.py tests/test_ai_trader_strategy.py tests/test_positional_scenario.py tests/test_strategy_plan.py tests/test_strategy_plan_templates_route.py tests/test_strategy_backtest_sizing.py tests/test_paper_trades_routes.py tests/test_order_path_guard.py tests/test_oms_contract.py tests/test_execution_modes.py tests/test_desk_alerts.py tests/test_positional_desk_fields.py tests/test_strategy_levels.py tests/test_strategy_engine.py tests/test_desk_paper_safety.py -q -p no:cacheprovider`
  - Output (before, origin/dev 5b6b3cfd, same suites without the new file): `1078 passed, 4 warnings in 55.90s`
  - Output (after): `1123 passed, 4 warnings in 57.26s`
  - Result: PASS
- **New and flipped tests only:** `tests/test_desk_paper_safety.py tests/test_risk_gate_desk_journal.py tests/test_risk_gate_ai_trader.py tests/test_order_path_guard.py` → `75 passed, 3 warnings in 15.75s` — PASS
- **The same tests against the unfixed code.** origin/dev `backend/` and `research/` were extracted with `git archive` and the changed test files copied over. Result: `37 failed, 30 passed`. Every K-1…K-9, I, F and A case fails, as do the three flipped journal tests. I-8b is the exception: it is a rollback-safety case and holds on base too. The AI-trader cases pass on base: the governor already halted there, and the new tests now lock that in. Failure lines for the defects:
  ```
  test_k4_to_k8_...[kill_switch-False]   AssertionError: ('{"detail":{"code":"risk_blocked",...  <- create 409 but the ENTRY fill answered 200
  test_i6_i7_...                          assert 201 == 409        <- second identical trade accepted
  test_f2_a_short_future_alone_...        assert (201 == 422)      <- short future accepted
  test_f4_..._gate_off[future]            assert (201 == 422)      <- lot size 1 accepted
  test_i1_i2_...[cash]                    assert (201 == 200)      <- same key made a second trade
  ```
- **Study probe on base (before the fix):** `PROBE journal ENTRY fill qty=100000 @100 (Rs 1 crore) with kill switch ON, gate OFF -> 200` · `PROBE desk identical POST twice -> 201 201 | a third at qty 9000 -> 201 created` · `PROBE open trades for the same symbol: 3`

## UI / Playwright Tests
- **Specs:** `copilot-app-desk-top10.spec.ts` (F-5 key header; new F-5b: retry reuses the key, a new body gets a new key, the 409 duplicate text), `copilot-app-ai-watchlist.spec.ts` (F-5 key header), `copilot-app-desk-strategy-builder.spec.ts` (SB-10a/SB-10c key header; new SB-10e short-futures blocker)
  - Command: `run-fe.sh` (tsc, `vite build`, `vite preview`, `npx playwright test --config pw.copilot-app.config.ts <specs>`)
  - Output: `tsc: clean` · `✓ built in 28.10s` · `14 skipped` (the Builder's screenshot cases, skipped by that spec) · `66 passed (56.5s)`
  - Result: PASS
- **Regression run, other desk specs that post paper trades or show their errors:** `copilot-app-desk-scanner`, `-desk-lab`, `-desk-strategy-top`, `-desk`, `-desk-risk-controls`, `-desk-strategy-ideas`, `-desk-chartink-picks`
  - Output: `tsc: clean` · `✓ built in 34.48s` · `2 skipped` · `276 passed (3.0m)`
  - Result: PASS
- Mocked API: these prove the UI. The backend tests above feed the same body shapes to the real routers.

## Data Correctness (staging, read-only)
- Query: `sudo docker exec -i nivesh-staging-app-backend python - < staging_desk_readonly.py`. It is read-only, uses the
  backend's own env without printing it, has an allow-list projection, and hashes user ids.
- Output:
  ```
  desk_paper_trades: 9 | with open_key: 0 | with idempotency_key: 0
  by kind/status: [(('cash', 'closed'), 6), (('cash', 'open'), 2), (('strategy', 'closed'), 1)]
  open cash trades per (user, symbol) > 1: {('a5530afb', 'ICICIBANK'): 2}
  open cash without paper_reserved_rs: [('ICICIBANK', '2026-10-20T03:03')]
  indexes: ['_id_', 'status_1_symbol_1', 'user_id_1_status_1']
  ```
- Result: PASS for what it is meant to show. No stored document has `open_key` or `idempotency_key`, so the two new
  unique partial indexes can be created on staging without a conflict. The two open ICICIBANK trades are untouched
  (grandfathered), and a third ICICIBANK would be refused. The missing reservation on the first ICICIBANK is item 0.9
  and is not repaired here. **UNVERIFIED:** the index build on the live collection and the endpoint behaviour on
  staging, both pending an approved deploy.

## Inputs required from user
- Approval to deploy this branch to staging (a backend restart; the indexes are created on first use) and a test
  user's session to run S-1…S-3.

## Verdict: BLOCKED
<!-- Every local test case passed with real output above; the staging API cases (S-1..S-3) are not run because this
     task forbids staging writes and deploys. Not PASS until they are. -->
