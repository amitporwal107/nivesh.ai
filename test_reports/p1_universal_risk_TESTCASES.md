# Phase 1 — Universal Risk Enforcement: test cases

Branch `feat/p1-universal-risk` (off origin/dev 6a3ec2e3). Acceptance standard: `docs/NIVESH_AI_LAB_PHASE_SUCCESS_CRITERIA.md`
Phase 1 (1.1, 1.2, 1.3, exit gate). Owner defaults: `docs/NIVESH_AI_LAB_GUIDELINES_GAP_STUDY.md` §9 item 3.

Authoring note (honest): the API contract and the service were designed first; these cases were written after the service
and the path wiring were drafted, and before the new suites below were written. The adapted Phase 0 suites existed already.

Paths (P): P1 desk cash POST · P2 desk strategy POST · P3 journal create · P4 journal ENTRY fill · P5 AI-trader signals ·
P6 AI-trader confirm.

## A. One service on every path (criteria 1.1)

| ID | Case | Type | Expected | Suite |
|---|---|---|---|---|
| U-1 | Route inventory: every route that writes `desk_paper_trades`, `trade_journal`, `ai_trader_tickets` or `oms_orders` (insert, or a `$push` of a fill) calls `risk_service.enforce/enter` | unit (AST) | test passes on the branch; a synthetic route without the call is flagged | test_risk_route_inventory |
| U-2 | The inventory finds all six paths (no path silently missing from the scan) | unit (AST) | P1–P6 handlers listed | test_risk_route_inventory |
| U-3 | No flag can bypass the core: with `fno_risk_gate` off, every path is judged, recorded and reserved | api | decision row `source=risk_service` on P1–P6 with the flag off | test_risk_entry_paths, adapted suites |
| U-4 | The flag adds only the F&O structure checks (`fno_additional`) | api | long future refused `futures_only` only with the flag on | test_risk_gate_desk_journal |
| U-5 | Order-path guard unchanged; `LIVE_EXECUTION_AVAILABLE` False | unit | test_order_path_guard passes | test_order_path_guard |

## B. Path × reason matrix (criteria 1.1 acceptance, 1.3 combined breaches)

For every path P1–P6 and every applicable reason: HTTP 409 (or 422 for the desk's own validation) — for P5 the ticket is
`rejected`; **no trade/journal/fill written; the account's reservations, counters and blocked funds unchanged; exactly one
new `risk_decisions` row from the service carrying the reason code, `policy_version=universal-risk-v1`, a `limits_version`
and the request's correlation id.**

| ID | Reason (code) | Setup | Paths |
|---|---|---|---|
| M-1 | kill switch (`kill_switch_on`) | control row | P1–P6 |
| M-2 | per-trade budget: min valid size over budget (`min_qty_exceeds_budget` / `min_lot_exceeds_budget`) | per_trade 0.05% | P1–P6 |
| M-3 | total open risk (`open_risk_exceeded`) | account open risk at the cap | P1–P6 |
| M-4 | sector (`sector_exceeded`) | sector exposure at the cap | P1, P2, P3, P5, P6 (P4 is an add) |
| M-5 | daily loss (`daily_loss_halt`) | a trade closed today at −2.5% | P1–P6 |
| M-6 | weekly loss (`weekly_loss_halt`) | a trade closed Monday at −4.5% | P1–P6 |
| M-7 | drawdown known (`drawdown_halt`) | equity peak 12 lakh, equity 10 lakh | P1–P6 |
| M-8 | drawdown unknown (`drawdown_unknown`) | an open structure with sessions but no F&O marks | P1–P6 |
| M-9 | stale data (`market_state_stale`) | regime as of 5 sessions ago | P1–P6 |
| M-10 | funds (`insufficient_paper_funds`) | nothing available | P1, P2, P3, P5, P6 |
| M-11 | reward:risk after costs (`reward_risk_too_low` / governor `RR_TOO_LOW`) | target too close | P1, P2, P3, P5 |

## C. Decisions, sizing and estimate (criteria 1.2)

| ID | Case | Type | Expected |
|---|---|---|---|
| D-1 | Example A under the 0.5% profile (equity ₹6 lakh → ₹3,000) | unit | 85 asked → reduce; approved total ≤ ₹3,000; at 85 the total exceeds it |
| D-2 | Example E (futures, lot 100, ₹2,500 budget = 0.5% of ₹5 lakh) | unit | block `min_lot_exceeds_budget` (one lot ₹2,500 gross + costs + gap) |
| D-3 | Example F (bull call spread, max loss ₹4,500 at ₹2,500 budget) | unit | block `min_lot_exceeds_budget`, value = max loss + costs |
| D-4 | Estimate = gross + desk-cost-v2 costs + 1% gap stress; stop-based reported separately | unit | figures match the cost card |
| D-5 | Sizing respects lots: a 3-lot spread over budget is reduced to the most lots that fit | unit | approved_lots < requested, total ≤ budget |
| D-6 | Exposure vs loss-at-stop are separate limits (tight stop, big position → POSITION_SIZE reduce, risk fine) | unit | reduce by the governor's position cap |
| D-7 | Decision shape: outcome, approved, reasons {code, check, severity, value, limit}, estimated_risk_rs, budget, policy/limits versions, inputs_hash, reservation_id | unit | all present |
| D-8 | Replay of a stored service decision matches | unit | `match: true` |

## D. Fail closed on each input (criteria 1.1 "missing or stale input")

| ID | Input | Expected code |
|---|---|---|
| F-1 | last close unreadable / missing | `last_close_unknown` |
| F-2 | last close older than 2 sessions | `last_close_stale` |
| F-3 | sector unknown | `sector_unknown` |
| F-4 | market state unavailable | `market_state_unknown` |
| F-5 | market state stale | `market_state_stale` |
| F-6 | average traded value unknown | `liquidity_unknown` |
| F-7 | equity unknown (an unmarked open position) | `equity_unknown` + `drawdown_unknown` |
| F-8 | controls unreadable | `controls_unreadable` |
| F-9 | profile/account unreadable | `account_unreadable` |
| F-10 | legacy open position whose risk cannot be estimated | `open_risk_unknown` |
| F-11 | decision cannot be recorded | 503 `risk_decision_unrecorded`, nothing written |
| F-12 | F&O marks: an option leg is marked at `close_price`, never `settle_price` (expiry-day trap) | equity uses the close |

## E. Profile (criteria 1.2)

| ID | Case | Expected |
|---|---|---|
| P-1 | No stored profile → owner defaults with `stored: false` | 0.5/3/10/25/2/4/10/1.5 |
| P-2 | User tightens (per trade 0.5 → 0.4) with a reason | 200; audit row who/when/before→after/effective_from |
| P-3 | User loosens | 403 `admin_required`; nothing changes, no audit row |
| P-4 | Admin loosens to the engineering profile | 200; audit row with `loosened` |
| P-5 | No reason | 422 |
| P-6 | Concurrent change (stale version) | 409 `concurrent_change` |
| P-7 | GET /api/risk/profile shows definitions, live equity basis, change log | 200 |

## F. Atomic reservation (criteria 1.3) — real Mongo (mongo:7, throwaway container)

| ID | Case | Expected |
|---|---|---|
| R-1 | 20 concurrent `reserve_entry` of ₹5,000 risk against a ₹30,000 cap | exactly 6 accepted; Σ reserved ≤ cap; counters = Σ entries |
| R-2 | 12 concurrent full service decisions (`enter`) whose sum exceeds the open-risk cap | accepted total ≤ cap; each loser has a `supersedes` blocked row; no leaked reservation |
| R-3 | Retry of the same reservation id | one entry, counters unchanged |
| R-4 | Duplicate request (same symbol) | `held_symbols` refuses the second atomically |
| R-5 | Cancellation (position never written) | funds and risk back; second cancel is a no-op |
| R-6 | Close releases exactly once (second release moves no risk) | invariants clean |
| R-7 | Simulated process restart (reserved, never inserted) | `sweep_orphans` releases it after the grace; not before |
| R-8 | Partial exits | NOT SUPPORTED (stated): a close takes no quantity |

## G. Migration (dry run only)

| ID | Case | Expected |
|---|---|---|
| G-1 | `scripts/migrate_risk_reservations.py` defaults to `--dry-run` and writes nothing | unit (fake db: zero writes) |
| G-2 | Dry run read-only against staging | real output: counts, per-trade estimate, validation, snapshot and rollback plan |

## H. Frontend (frontend-v5)

| ID | Case | Type |
|---|---|---|
| UI-1 | A Paper trade answered `risk_reduce` shows the approved size and the reasons, and offers the approved size | Playwright |
| UI-2 | A Paper trade answered `risk_blocked` shows the reasons | Playwright |
| UI-3 | Risk profile view: limits, equity basis, effective date, change log; tighten works; loosen shows admin-only | Playwright |
| UI-4 | tsc and the production build pass | build |

## I. Regression

| ID | Case | Expected |
|---|---|---|
| X-1 | All Phase 0 suites pass (desk_paper_safety, paper_fills_pnl, fno_idea_paper_trade_contract, paper_reconcile, desk_exit_job, risk_gate*) | pass |
| X-2 | Full `backend/tests` on the branch vs plain origin/dev: "fails on branch, passes on dev" list | empty |
