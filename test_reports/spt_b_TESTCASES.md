# SPT slice B — test cases (proposal → sizing → allocation → risk → pipeline, account config)

Written 5 Nov 2026 ~02:10 IST, BEFORE the implementation (DESIGN.md §8 rule 1). Branch `feat/spt-risk-pipeline`.
Tests: `backend/tests/test_spt_b_*.py`, in-memory fakes only (MOCK data: every symbol, price, user and opportunity is
made up; no staging data in any fixture). Status column is filled in at the end of the build.

## Deviations and interpretations (read first)

| # | What | Why |
|---|---|---|
| DB-1 | **Approval mode holds NO reservation while it waits for the user.** The screening decision is recorded with `service.enter(reserve=False)`; `POST …/approve` always re-runs the full risk service with `reserve=True` (a fresh decision, a new order id) before it creates the order. So "re-run if older than N minutes" is N = 0. | `paper_account.sweep_orphans` (called by every `enter(reserve=True)`) releases any reservation older than 120 s whose `trade_id` is not a document in its store (`spt_orders`). The order does not exist until the user approves, so a held reservation would be silently swept away and the order created later would hold none. WF §11.2 ("never approve without fresh validation") is met strictly. The expiry sweep still releases a reservation if a proposal ever records one. |
| DB-2 | **Tracking mode is a dry run**: `gather` + `decide`, nothing written to `risk_decisions`, no reservation. The decision body is kept on the proposal with `dry_run: true`. | No position-creating write follows a tracking proposal, so the risk service's "recorded before a write" rule does not apply; it would only fill the user's decision log with rows that authorised nothing. |
| DB-3 | **Sizing adds the risk profile's own per-trade cap** (step `risk_profile_per_trade`, `estimate.max_cash_qty`: stop loss + costs + the 1% gap stress, ≤ equity × profile `per_trade_risk_pct`) after the PRD §8.4 formula. | The PRD sizes on planned risk (stop distance + costs, no gap). The owner's profile defines per-trade risk INCLUDING the gap stress (`risk_profile.DEFINITIONS`), and the risk service is the authority. Without this step every SPT proposal would come back APPROVE_REDUCED. The PRD §8.4 example is reproduced by the pure calculation (243 / ₹1,21,500 / ₹4,981.50); an account sized under the owner profile gets fewer shares, and the steps say why. |
| DB-4 | **min R:R (config `min_rr.positional`, PRD §26 1:2) is measured to TARGET 2 at the actual entry**, on prices (no costs). R:R to T1 is reported too. | scan-plan-v3 puts T1 at exactly 2R from the PLAN entry, so a 2.0 minimum to T1 would refuse every entry even 1 paisa above the plan entry, making `max_chase_pct` meaningless. T2 is also the target the risk service measures (`target_price` = T2, which then applies the profile's 1.5 after costs). |
| DB-5 | **Drawdown ladder bands:** below `reduce_at` normal; `reduce_at`–`restrict_at` the SPT risk % × `reduce_factor`; `restrict_at`–`halt_at` RESTRICTED = new entries BLOCKED; ≥ `halt_at` HALT_ACCOUNT. Exits and risk-reducing changes are never refused. | PRD §9.7 names the bands but not what "restricted" allows; refusing new risk while not halting the account is the conservative reading. |
| DB-6 | **Kill-switch state `RESET_PENDING` is not produced.** | `risk_controls` has no reset-request record: clearing is one admin action. The mapping (in `risk.kill_switch_state`) says so instead of inventing a state. |
| DB-7 | **New policy defaults not in the PRD** (owner to confirm): `max_chase_pct` 1.0 %, `min_adv_rs` ₹1 crore, `max_adv_participation_pct` 5 % (= the governor's gov-v1 `max_adv_pct`), `approval_expiry_minutes` 30, `max_positions` ≤ 10 (the risk service's own cap), `max_new_per_day` 5. | The PRD gives none of these; each is a named, versioned config value a user can tighten. |
| DB-8 | **Equity basis = `risk_book.read` equity** (paper cash + net unrealised P&L of desk positions at end-of-day marks). SPT positions are in the account's reservation counters (open risk, exposure, sector, positions, funds) but **not in risk_book's equity or day/week P&L**: risk_book does not read `spt_positions`. | Outside slice B's allowed edits. Flagged for the integrator (risk_book needs an `spt_positions` reader once slice C's position shape is fixed). |

## Test cases

Ids map to WF §25 acceptance items (WF#), PRD §23.3 scenarios (PRD-S#) and the worked examples.

| Id | Area | Case | Covers | Expected |
|---|---|---|---|---|
| SPT-B-01 | config | No stored config | WF#22, PRD §26 | mode `off`, PRD §26 defaults (ladder 2/4/6 ×0.5, 10 positions, min R:R 2.0, risk 0.5/0.35/0.35, buckets 45/25/20/10, gap stress = `estimate.GAP_STRESS_PCT`), `stored:false`, `version:0` |
| SPT-B-02 | config | Invalid changes | WF#22 | 422 with a stable code each: `invalid_mode`, `unknown_field`, `out_of_range`, `buckets_must_sum_100`, `ladder_not_ascending`, `risk_pct_above_profile`, `reason_too_long`; nothing written |
| SPT-B-03 | config | Versioned changes | WF#21, WF#22, PRD §18 r15 | every change writes a `spt_account_config_versions` row (actor, at, old, new, reason, version) before the config moves; version +1; a stale `expected_version` → 409 `concurrent_change`; no-op → 422 `no_change` |
| SPT-B-04 | routes | Auth | — | no session → 401; `account_id` ≠ caller → 403 `not_your_account` on every account-scoped route |
| SPT-B-05 | proposal | Immediate entry | WF#5 | price ≤ plan entry × (1 + chase) and > stop → `entry.type` MARKET (marketable), entry = the live ask (else LTP, said which), stop = plan stop, T1/T2 = plan, exit_plan per DESIGN §4 (T1 50 % + breakeven, trail-atr-v1 k=2, close<SMA20, 20 sessions), R:R at the actual entry |
| SPT-B-06 | proposal | Pullback entry | WF#5 | price above the chase bound → LIMIT at the plan entry, GTD until min(opportunity window, expiry) |
| SPT-B-07 | proposal | Refusals | WF#5, PRD §18 r1-2 | no plan / `plan_ok` false → REJECTED `no_valid_plan`; price ≤ stop → REJECTED `price_at_or_below_stop` and the opportunity → EXPIRED through A's `transition`; R:R(T2) < min → REJECTED `rr_below_minimum`. Stop never widened |
| SPT-B-08 | proposal | Out of scope | D5 | intraday → NOT_TRADABLE `horizon_not_enabled`; short → `direction_not_enabled`; non-cash → `instrument_not_enabled` |
| SPT-B-09 | proposal | Idempotent | WF#2, PRD §18 r6 | a second create for the same (user, opportunity) returns the first proposal; one document |
| SPT-B-10 | proposal | Price missing / stale | WF#18, PRD §18 r18 | no live quote, or one older than `SPT_QUOTE_MAX_AGE_S` → no entry is priced; the risk decision BLOCKED `price_stale` / `price_unavailable`; no number is made up |
| SPT-B-11 | sizing | PRD §8.4 example | WF#6, PRD §8.4, WF §8.4 | equity ₹10,00,000, 0.5 %, 500/480, cost ₹0.50/share → 243 shares, capital ₹1,21,500, planned risk ₹4,981.50; stressed = planned + 243 × 480 × gap % |
| SPT-B-12 | sizing | Costs from the desk cost card | WF#6 | with no cost given, `desk_trading.max_units_within_budget`: loss at stop + desk-cost-v2 round trip ≤ allowed risk, and one share more would not be |
| SPT-B-13 | sizing | Caps in order | WF §8.2 | liquidity (≤ participation % of the 20-day ADV), position exposure (profile `max_position_pct`), available capital minus the reserve bucket; each step `{cap, before, after, reason}`; SPT risk % capped at the profile's per-trade % (never looser); the profile per-trade cap (DB-3) |
| SPT-B-14 | sizing | Liquidity unknown / below floor | WF#18 | ADV unknown → 0 shares `liquidity_unknown`; ADV < `min_adv_rs` → 0 `liquidity_below_floor` |
| SPT-B-15 | allocation | WF §9.4 ₹80,000 example | WF#7, WF §9.4 | ₹1,21,500 needed, ₹80,000 available: reserve 0 → ALLOCATION_REDUCED to 160 shares (₹80,000); default 10 % reserve → ALLOCATION_REJECTED `reserve_protected`; capital required never above available |
| SPT-B-16 | allocation | Reserved + buckets + limits | WF#7 | pending-entry reservations counted as reserved (not deployed); equity_positional bucket room; sector room; max positions and max new per day → REJECTED with the code |
| SPT-B-17 | allocation | Ranking | PRD §8.7 | ordered by opportunity_score, then R:R, then liquidity; a higher scanner score alone does not rank first; a batch never exceeds the room (capital/bucket/positions) |
| SPT-B-18 | risk | Risk before the order | WF#8 | auto mode: `create_entry_order` called only after an APPROVE / APPROVE_REDUCED with a reservation; `order_id` = the reservation's `trade_id`; EntryRequest path `spt_entry`, store `spt_orders`, mode paper, target = T2, actor `spt_pipeline` |
| SPT-B-19 | risk | PRD-S2: valid but breaches portfolio risk | WF#9, PRD-S2 | open risk already at the cap → BLOCKED_BY_RISK, decision BLOCKED with the risk service's `open_risk_exceeded`, no reservation, no order |
| SPT-B-20 | risk | PRD-S7: daily loss breached | PRD-S7, WF#17 | day loss ≥ limit → BLOCKED (`daily_loss_halt`), no order; `kill_switch_state` RESTRICTED |
| SPT-B-21 | risk | PRD-S14: kill switch with orders pending | PRD-S14, WF#17 | kill switch on → HALT_ACCOUNT before any reservation; approve refused (409); `kill_switch_state` TRIGGERED. Cancelling pending ENTRY orders is slice C's (DESIGN §6) |
| SPT-B-22 | risk | Drawdown ladder | PRD §9.7 | 2.5 % → risk % × 0.5 in sizing; 4.5 % → BLOCKED `drawdown_restricted`; 6.5 % → HALT_ACCOUNT `drawdown_halt_ladder` |
| SPT-B-23 | risk | Reduce + the decision record | WF#21, WF §10.4 | the risk service reduces → APPROVE_REDUCED with its quantity; the record holds decision_id, risk-service decision id, reservation_id, reason codes + explanations, policy versions, planned/stressed risk, open risk before/after, exposure before/after, requested/approved qty |
| SPT-B-24 | risk | SPT checks before the service | WF §10.2 | stressed risk > remaining open-risk room, R:R below the minimum, max positions reached → refused with no risk-service call and no reservation |
| SPT-B-25 | approval | Approval cannot override a hard limit | WF#10, WF §11.2 | approving while the account is blocked (or the fresh risk run blocks) → 409, proposal APPROVAL_EXPIRED with the reasons, no order |
| SPT-B-26 | pipeline | Order creation fails after the reservation | WF#18, WF#19 | the reservation is released (`release_unused`), the error is recorded on the proposal and in `spt_state`, no retry |
| SPT-B-27 | modification | Risk-increasing changes | WF#14, PRD §18 r11 | wider stop within the budget → APPROVE (recorded in `risk_decisions`, source `spt_risk`); wider stop beyond the per-trade budget → REJECT; removing the stop → REJECT; more quantity beyond the budget/funds → REJECT; under the kill switch → HALT_ACCOUNT |
| SPT-B-28 | modification | Risk-reducing changes | WF#15, PRD §18 r12-14 | a tighter stop / smaller quantity → APPROVE even under the kill switch and the drawdown halt |
| SPT-B-29 | pipeline | Modes | PRD §11.1, D4 | off → nothing; tracking → TRACKING_ONLY, no reservation, no order, no `risk_decisions` row; approval → AWAITING_USER_APPROVAL, `expires_at` ≤ min(now + N min, session close, opportunity expiry); auto → ORDER_CREATED, idempotency key `spt:<user>:<opp>:entry` |
| SPT-B-30 | pipeline | Idempotent rounds, leader, session | WF#2, WF#19 | a second round makes nothing new; a non-leader worker does nothing; out of session nothing; `spt_state` `spt_b` written |
| SPT-B-31 | approval | Approve / reject routes | WF §11.1 | approve → READY_FOR_ORDER → ORDER_CREATED (fresh risk); past `expires_at` → 409 `approval_expired`; price outside the entry range → 409, APPROVAL_EXPIRED; reject needs a reason → USER_REJECTED; another user's proposal → 404 |
| SPT-B-32 | pipeline | Expiry sweep | WF §11.2 | AWAITING past expires_at → APPROVAL_EXPIRED; a recorded reservation is released |
| SPT-B-33 | events | Event log | WF §22 | TRADE_PROPOSAL_CREATED, PROPOSAL_STATE_CHANGED, POSITION_SIZE_CALCULATED, ALLOCATION_*, RISK_APPROVED / RISK_REJECTED with stable idempotency keys; a replayed round adds none |
| SPT-B-34 | routes | POST /risk/calculate-position-size | PRD §17.3 | pure: the PRD §8.4 example over HTTP; 422 on bad input; no writes |
| SPT-B-35 | routes | POST /risk/validate-trade | PRD §17.3 | `dry_run: true`; no `risk_decisions` row, no reservation, no proposal |
| SPT-B-36 | routes | Account, risk, exposures, allocation, proposals, ledger | PRD §17.1, §17.3 | shapes present; recommendations write nothing; recalculate re-runs allocation on the caller's AWAITING proposals; proposals are the caller's only; ledger paginated by `before` |
| SPT-B-37 | risk service | `spt_entry` path | D2 | `"spt_entry" in service.PATHS`; an spt_entry request decides like a desk one; the neighbour suites stay green |
| SPT-B-38 | P1 stress test | GET /risk/stress-test | PRD §9.2, §10.5 | each open SPT reservation gaps x % through its stop; sector −5 %; market −3 / −5 % with beta 1 labelled `beta_assumed`; planned vs stressed totals |

## Not in slice B (stated so nobody assumes it)

Cancelling pending entry orders on the kill switch, fills, positions, exits and modifications themselves (slice C);
opportunity creation and validation (slice A); server wiring (integrator); correlation / VaR (P1, out of scope);
F&O proposals (P1 stretch, item 9).
