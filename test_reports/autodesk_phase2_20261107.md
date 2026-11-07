# Functionality Verification Report — Phase 2 risk-to-paper execution

- **Branch:** feat/autodesk-phase2-paper-exec (stacked on #499, which is merged into dev at 8d0b5449; that merge is in this branch's history at e9800d58)
- **Date:** 2026-11-07
- **Author:** Claude. Account 1 wrote the design, test cases, migration, capital ledger, fill model, adapters and sources, and reviewed and fixed the rest. Account 2 wrote the gateway, settlement, reports, wiring and most tests while Account 1 was at its usage limit (owner's instruction, recorded on STATUS.md); that work arrived here by fast-forward from feat/autodesk-phase2-paper-exec-a2 @ d44ebc3c.
- **Environment:** throwaway Postgres (autodesk-test-pg) and the nivesh/backend:staging image. Tests use test doubles; the replay reads the real data API, read-only. **Staging is NOT deployed with this branch, and no shared database was written.**
- **Changed areas:** backend routes/services: yes · frontend src: yes (4 result-label mappings by Account 2; no other UI change)

## Summary
An approved plan now becomes an execution intent, a capital reservation, orders, simulated fills, a position, ledger rows and journal entries. In a simulation it fills at OPEN from that session's exchange rows. On the live desk it fills from a live Zerodha quote during market hours; that path is proven only against fake quote sources (AD-P2-98 below). Design: docs/autodesk/PHASE2_DESIGN.md. No order placement exists: paper and shadow adapters only, `LIVE_EXECUTION_AVAILABLE = False`.

## What the review of the takeover branch found
The takeover branch passed its 255 tests but had never met real data. Review found these, each now fixed and covered by a test. All 20 parametrised cases of `test_p2_review.py` that existed at the time failed when run against d44ebc3c's code (`20 failed`). AD-P2-119 was added after that run.

| ID | Problem on d44ebc3c | Effect |
|---|---|---|
| AD-P2-101 | `decide()` passed a JSON string to a jsonb codec | **a person's approval turned the workflow outcome into an array** (real assertion: `AssertionError: [{'approval_id': …}, …`), which breaks every reader of `outcome.result` |
| AD-P2-103 | `live_tick` overwrote its `tenant_id` argument in a loop | marks reached only the last tenant in production |
| AD-P2-104, 105 | a quote read per intent, inside a transaction, and for open positions at any hour | Kite REST reads on weekends, and rows locked during a network call. Now one read per tick, before any lock, none while the market is shut |
| AD-P2-106 | no funds check at the fill (the design requires one) | a fill could overdraw buying power |
| AD-P2-107 | a basket's reservation converted leg by leg | consumed figure wrong, open risk off by rounding |
| AD-P2-108 | an intent left CREATED stayed stuck | now continues at the next call; refused at start-up with INTERRUPTED |
| AD-P2-109 | a duplicate refusal set the plan to EXECUTION_REFUSED | would end a plan another intent was working on |
| AD-P2-110 | after-close snapshot on any day | spurious P&L rows on Saturdays |
| AD-P2-111 | a working live order filled after the account was suspended or the policy changed | now held, with the reason |
| AD-P2-112..115, 119 | withdraw of UNKNOWN, fingerprint blind to marks and P&L, a failed read at the close failed the run, stale marks missing from /capital, journal missing marks and how orders ended | fixed |
| AD-P2-116, 117 | an AD-92 word in a reason; /health and /desk/status still said "Phase 1: no orders" | fixed; AD-P2-116 now lints every string literal in the execution code |

## Test Cases
docs/autodesk/TESTCASES.md, "Phase 2 — risk-to-paper [core]", AD-P2-01..119. Authored before implementation (commit 7ce422f2), with 101..119 added by the review.

| Group | IDs | Evidence | Type | Result |
|---|---|---|---|---|
| Ledger, reservation | 01–06, 10–14 | test_p2_capital.py, test_p2_products.py, test_p2_misc.py | integration | PASS |
| Intents, binding, controls | 20–31 | test_p2_gateway.py, test_p2_controls.py | integration | PASS |
| Order states | 32–35 | test_p2_fill_model.py, test_p2_gateway.py, test_p2_misc.py | unit, integration | PASS |
| Fill model, costs | 40–49 | test_p2_fill_model.py, test_p2_products.py | unit | PASS |
| Baskets | 50–52, 107 | test_p2_products.py, test_p2_review.py | integration | PASS |
| Simulator wiring | 60–69 | test_p2_simulation.py, test_p2_gateway.py, test_p2_misc.py | integration | PASS |
| Live desk (fake quotes) | 70–79, 103–105, 110, 111, 115 | test_p2_live.py, test_p2_controls.py, test_p2_misc.py, test_p2_review.py | integration | PASS with test doubles |
| API | 80–84, 92, 117 | test_p2_api.py, test_api.py, test_ui_request_contracts.py, test_p2_review.py | api | PASS |
| Safety, wording | 90, 91, 116 | test_p2_misc.py, test_safety.py, test_order_path_guard.py, test_p2_review.py | unit | PASS |
| Review fixes | 101, 102, 106, 108, 109, 112–114, 119 | test_p2_review.py | integration | PASS |
| Screens read APPROVED | 118 | autodesk-p2-result-labels.spec.ts | e2e | PASS |
| Real data replay | 95, 96, 97 | backend/scripts/autodesk_phase2_run.py | real data | PASS |
| Real Zerodha quote | 98 | backend/scripts/autodesk_quote_check.py, written, not run | real data | **UNVERIFIED** |

## API / Endpoint Tests
Not run against staging: nothing is deployed. Routes are tested through FastAPI's TestClient with a faked signed-in user.

- `sudo -n bash backend/scripts/run_autodesk_tests.sh /home/deploy/nivesh-wt-account1 tests/autodesk tests/test_order_path_guard.py -p no:warnings`
  - Output: `276 passed in 60.49s (0:01:00)` (166 baseline + 110 new). Result: PASS
- Production wiring, booted on a fresh throwaway database through `autodesk.main.create_app()`, real output:
  ```
  health 200 {"status": "ok", "db": true, "migrations": ["001_autodesk_core.sql", "002_desk_controls.sql", "003_paper_execution.sql"], "calendar_years": [2026], "execution": "paper only: simulated fills, no broker orders"}
  gateway ExecutionGateway sim SimulationPaperAdapter bars PitSessionBars live LivePaperAdapter quotes KiteQuoteSource
  orchestrator_has_gateway True simulator_has_gateway True
  live_loop_task_running True
  signed_out 401 401 401
  LIVE_EXECUTION_AVAILABLE False
  ```
  Result: PASS

## UI / Playwright Tests
- tsc, vite build and `npx playwright test --config pw.autodesk.config.ts` (Docker, route mocks, no real API):
  - Output: `TSC_OK`, `✓ built in 3.38s`, `162 passed (1.8m)` (160 baseline + 2 new). Result: PASS
- AD-UI-74, which Account 2 saw fail 1 in 3 repeats: `autodesk-policies --repeat-each=5` gave `70 passed (32.3s)`. Not reproduced on the resized VM. The cause was never found, so treat it as possibly flaky.

## Data Correctness (real data, read-only; fresh database on the throwaway Postgres)
Command: `python scripts/autodesk_phase2_run.py --sessions 3 --seed 42`, in a throwaway container on network autodesk-test with only NIDP_DAAS_BASE_URL and NIDP_DAAS_INTERNAL_TOKEN passed by process substitution. Sessions ['2026-11-03', '2026-11-04', '2026-11-05'], real agents, starting capital ₹1,00,00,000. Full output: test_reports/autodesk_phase2_replay_20261107.json.

**AD-P2-95, replay:**
- run a (seed 42): COMPLETED, 76.8 s, signals 566, plans {'EXECUTED': 7, 'REJECTED': 7, 'EXECUTION_REFUSED': 1}, trades 7, orders {'REJECTED': 2, 'FILLED': 13}, reject_codes {'BASKET_NET_LIMIT': 2}, fills 13, reservations 8, fill_ratio 0.8667, rejection_rate 0.1333, net_pnl_rs 33266.47, max_drawdown_rs 15874.53, fingerprint 6d64d0ff953e4f82903799a26c8272084a897a0a47c72cc66de43ead0ad0d16c
- run b (seed 42): COMPLETED, 79.1 s, signals 566, plans {'REJECTED': 7, 'EXECUTED': 7, 'EXECUTION_REFUSED': 1}, trades 7, orders {'REJECTED': 2, 'FILLED': 13}, reject_codes {'BASKET_NET_LIMIT': 2}, fills 13, reservations 8, fill_ratio 0.8667, rejection_rate 0.1333, net_pnl_rs 33266.47, max_drawdown_rs 15874.53, fingerprint 6d64d0ff953e4f82903799a26c8272084a897a0a47c72cc66de43ead0ad0d16c
- run other-seed (seed 43): COMPLETED, 81.2 s, signals 566, plans {'EXECUTED': 7, 'EXECUTION_REFUSED': 1, 'REJECTED': 7}, trades 7, orders {'REJECTED': 2, 'FILLED': 13}, reject_codes {'BASKET_NET_LIMIT': 2}, fills 13, reservations 8, fill_ratio 0.8667, rejection_rate 0.1333, net_pnl_rs 33159.73, max_drawdown_rs 15981.27, fingerprint 6ccbae204d61eeac715ce48042462385e033f0565629e162a265181f87774abb

**AD-P2-96, determinism.** Same seed: `{"a": "6d64d0ff953e4f82903799a26c8272084a897a0a47c72cc66de43ead0ad0d16c", "b": "6d64d0ff953e4f82903799a26c8272084a897a0a47c72cc66de43ead0ad0d16c", "equal": true, "net_pnl_equal": true}`. Other seed: `{"seed": 43, "fingerprint": "6ccbae204d61eeac715ce48042462385e033f0565629e162a265181f87774abb", "differs": true, "net_pnl_rs": "33159.73"}`. The fingerprint covers orders, fills, position legs, marks and session snapshots.

**AD-P2-97, independent check** (a new reader, no shared cache; prices, quantity share, value, charges against the card, marks, cash):
`{"fills_checked": 13, "mismatch_count": 0, "legs_checked": 13, "marks_equal_last_close": 13, "marks_flagged_stale": 0, "mark_mismatches": [], "cash_from_fills": {"expected_rs": "8980174.97", "ledger_rs": "8980174.97", "difference_rs": "0.00"}, "charges_from_fills": {"fills_rs": "1433.78", "ledger_rs": "1433.78"}, "notional_from_fills": {"fills_rs": "1104041.25", "ledger_rs": "1104041.25"}}`

**Reconciliation:** `{"equity_from_pnl_rs": "10033266.47", "equity_from_positions_rs": "10033266.47", "difference_rs": "0.00"}`

**No look-ahead:** `{"fill_engine_reads": 49, "reads_outside_the_clock_session": 0, "agent_tool_calls_checked": 1646, "calendar_only_calls": 3, "agent_look_ahead_violations": [], "violation_count": 0}`. The first version of this check reported 3 violations per run. They were the 3 `previous_session` calls (one per session), which read the holiday calendar only; the check now counts them separately and reports what remains, which is 0.

**Capital at the end (run a):** `{"equity_rs": "10033266.47", "cash_balance_rs": "8980174.97", "used_margin_rs": "0.00", "available_cash_rs": "8980174.97", "reserved_capital_rs": "0.00", "available_buying_power_rs": "8980174.97", "deployed_notional_rs": "1104041.25", "open_risk_rs": "293336.79", "pending_risk_rs": "0.00", "pending_order_commitment_rs": "0.00", "realized_gross_rs": "0.00", "fees_rs": "1433.78", "net_realized_rs": "-1433.78", "unrealized_gross_rs": "34700.25", "net_pnl_rs": "33266.47"}`

**P&L by session:** `[{"session_date": "2026-11-03", "equity_rs": "9985033.30", "day_pnl_rs": "-14966.70", "cumulative_pnl_rs": "-14966.70"}, {"session_date": "2026-11-04", "equity_rs": "9984125.47", "day_pnl_rs": "-907.83", "cumulative_pnl_rs": "-15874.53"}, {"session_date": "2026-11-05", "equity_rs": "10033266.47", "day_pnl_rs": "49141.00", "cumulative_pnl_rs": "33266.47"}]`. By strategy: `{"BEAR_PUT_SPREAD": "-19762.15", "BULL_CALL_SPREAD": "62214.30", "LONG_EQUITY": "-9185.68"}`. Charges: `{"gst": "72.70", "stt": "833.21", "sebi": "1.09", "stamp": "124.11", "exchange": "142.67", "slippage": "0.00", "brokerage": "260.00"}`. Measured spread ₹3013.30, slippage ₹1753.95 (both already in the fill prices). These figures are unrealized and exclude closing costs: positions stay open in Phase 2. They prove the arithmetic, not a strategy's merit: three sessions say nothing about performance.

**Reservations:** `[{"status": "CONSUMED", "n": 7, "amount": "1075804.10", "consumed": "1019825.03", "released": "55979.07"}, {"status": "RELEASED", "n": 1, "amount": "48817.11", "consumed": "0.00", "released": "48817.11"}]`. Consumed + released = amount in each row.

**Orders (run a):**

| Session | Instrument | Strategy | Leg | Side | Qty | Type | Plan price | Limit | State | Avg fill | Reject code |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-03 | BANKBARODA | BULL_CALL_SPREAD | L1 CE 245 | BUY | 8775 | BASKET_LEG | 6.38 | — | FILLED | 6.6 | — |
| 2026-11-03 | BANKBARODA | BULL_CALL_SPREAD | L2 CE 262.5 | SELL | 8775 | BASKET_LEG | 0.97 | — | FILLED | 0.85 | — |
| 2026-11-03 | DIVISLAB | BULL_CALL_SPREAD | L1 CE 9900 | BUY | 100 | BASKET_LEG | 384.8 | — | FILLED | 414.1 | — |
| 2026-11-03 | DIVISLAB | BULL_CALL_SPREAD | L2 CE 10700 | SELL | 100 | BASKET_LEG | 116.95 | — | FILLED | 123.15 | — |
| 2026-11-03 | PETRONET | BULL_CALL_SPREAD | L1 CE 300 | BUY | 5700 | BASKET_LEG | 9.35 | — | FILLED | 9.45 | — |
| 2026-11-03 | PETRONET | BULL_CALL_SPREAD | L2 CE 325 | SELL | 5700 | BASKET_LEG | 1.9 | — | FILLED | 1 | — |
| 2026-11-03 | POLICYBZR | BEAR_PUT_SPREAD | L1 PE 940 | BUY | 1050 | BASKET_LEG | 42.05 | — | FILLED | 40.35 | — |
| 2026-11-03 | POLICYBZR | BEAR_PUT_SPREAD | L2 PE 760 | SELL | 1050 | BASKET_LEG | 5.7 | — | FILLED | 4.15 | — |
| 2026-11-03 | RELIANCE | BULL_CALL_SPREAD | L1 CE 1300 | BUY | 2500 | BASKET_LEG | 19.4 | — | REJECTED | — | BASKET_NET_LIMIT |
| 2026-11-03 | RELIANCE | BULL_CALL_SPREAD | L2 CE 1400 | SELL | 2500 | BASKET_LEG | 2.45 | — | REJECTED | — | BASKET_NET_LIMIT |
| 2026-11-04 | BHARTIARTL | BULL_CALL_SPREAD | L1 CE 2060 | BUY | 1425 | BASKET_LEG | 37.5 | — | FILLED | 37.75 | — |
| 2026-11-04 | BHARTIARTL | BULL_CALL_SPREAD | L2 CE 2200 | SELL | 1425 | BASKET_LEG | 5.7 | — | FILLED | 5.75 | — |
| 2026-11-04 | MCX | LONG_EQUITY | L1 EQ | BUY | 226 | LIMIT | 3490.1 | 3519.5 | FILLED | 3402.5 | — |
| 2026-11-04 | RELIANCE | BULL_CALL_SPREAD | L1 CE 1310 | BUY | 2000 | BASKET_LEG | 24.1 | — | FILLED | 21.45 | — |
| 2026-11-04 | RELIANCE | BULL_CALL_SPREAD | L2 CE 1410 | SELL | 2000 | BASKET_LEG | 2.95 | — | FILLED | 2.4 | — |

**Worth reading:** the RELIANCE spread on 3 Nov was rejected all-or-none (`BASKET_NET_LIMIT`: net 54,000 past the limit 48,731.25) and its reservation of ₹48,817.11 came back. On 5 Nov one proposal ended `risk checks still failing after revisions: open_risk`: open positions used the open-risk budget (₹2,93,336.79 of ₹3,00,000 at the start capital), so the risk book does count filled positions (AD-P2-68 on real data). The other four that day, and both on 4 Nov, had no alternative meeting its own rule.

## Defaults used for pending owner decisions (DESIGN §10)
First-release strategies: long equity, long futures, long call/put, debit and credit spreads, iron condor; no short futures · AUTONOMOUS_PAPER auto-approves ≤ 0.5 % equity risk with signal score ≥ 70 · risk-profile default limits (3 % total open risk) · margin utilisation 25 % · futures margin estimate 15 %, not SPAN.

## Inputs required from user
The owner's daily Zerodha login, for AD-P2-98 only.

## UNVERIFIED
- **AD-P2-98, one real Zerodha quote.** Not run. Real status at 13:43 IST, Saturday 7 Nov: `token_status {'stored': True, 'valid_until': '2026-11-07T00:30:00+00:00', 'expired': True}`, and the market is closed. Only the owner can renew the login. `backend/scripts/autodesk_quote_check.py` is ready and has never run.
- **The live path has only met fake quotes.** Freshness rules, the Redis-then-REST source and live fills are tested with FakeQuotes, a fake Kite and a fake cache. The real Redis row shape and Kite's quote and instrument answers are read from existing code, not observed through this path.
- **The live loop has not run a real session.** It is shown to start (above); its ticks are tested by calling `settle.live_tick`.
- **Not deployed.** Migration 003 has not run on the shared staging Postgres. Nothing here ran on staging.
- **Paths real data did not reach.** This replay produced debit spreads and one share plan, and that plan's limit (3,519.50) was marketable at the open (filled 3,402.50). Credit spreads, iron condors, futures, partial fills, a resting limit filled at the close and an order expiring at the close are covered by crafted data only.
- **Agent tool-call counts vary slightly between same-seed runs** (1646 and 1647, 1645–1647 across runs), while signals, plans and fingerprints match. Cause not investigated. These are agent reads, which execution does not make, but a read that varies could one day change a plan, so it is worth a look.

## Known limits and follow-ups
- **Screens still carry Phase 1 wording** (UI was out of scope). False once this is deployed: frontend-v5/src/autodesk/screens/approvals/Detail.tsx:91 ("Phase 1 has no execution … nothing is sent to a broker or a paper engine"), :115 and :155. Stale placeholders: screens/Agents.tsx:276 and :291, screens/Phase2.tsx:20 and :26, screens/Overview.tsx:51 and :118–133, screens/simulator/model.ts:299. Run history columns are still placeholders; the API supplies `results.execution_summary`.
- **Holiday lists:** the data platform has no rows for 2024, 2025 or 2027 (seen in the boot log above). A simulation in those years is refused, and `next_session_for` needs the 2027 list before year-end.
- **Deferred, per PHASE2_DESIGN §11:** exits, realized P&L, expiry settlement, daily and drawdown limits, `amend`, other emergency controls, reconciliation of UNKNOWN orders, other allocation algorithms, real SPAN, band and tick files.

## Verdict: PASS
