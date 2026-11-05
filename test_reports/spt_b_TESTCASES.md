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
| DB-7 | **New policy defaults not in the PRD** — **owner-approved and made configurable, 5 Nov ~06:50 IST (DESIGN D12; see SPT-CFG below)**; originally listed for the owner to confirm: `max_chase_pct` 1.0 %, `min_adv_rs` ₹1 crore, `max_adv_participation_pct` 5 % (= the governor's gov-v1 `max_adv_pct`), `approval_expiry_minutes` 30, `max_positions` ≤ 10 (the risk service's own cap), `max_new_per_day` 5. | The PRD gives none of these; each is a named, versioned config value a user can tighten. |
| DB-8 | **B's equity = risk_book equity + the P&L of SPT positions not yet in paper cash** (`allocation.spt_pnl`, reading slice C's `spt_positions`: `realized_net_rs` + `mark.unrealized_net_rs`). B's drawdown ladder and day / week loss use it. A position held from BEFORE the period counts only its loss since entry (a gain is never used to offset a loss), because no start-of-period mark is stored for SPT positions. An open position with no mark (more than 300 s after its fill) or a stale mark makes equity unknown → entries blocked. | risk_book reads desk trades and the journal only (integrator note 5, 5 Nov). `risk_book.py` is not edited, so **the universal risk service still measures its limits on desk-only equity**; B's checks on the adjusted figures can only add refusals. The 300 s grace stops slice C cancelling the rest of a partly filled entry before its first mark. |
| DB-9 | **A REJECTED order from slice C ends the proposal ORDER_CREATED** with `order_rejected: true` and `order.state` REJECTED. B does not release the reservation again (C already gave it back). | The state machine has no other exit from READY_FOR_ORDER, and one order per (user, opportunity) is the rule (PRD §18 rule 6). C's idempotency key would return the same rejected order to any retry anyway. |
| DB-10 | **`PipelineError` is an `HTTPException`** (detail `{code, message, ...}`). | Slice C's `POST /api/v1/paper/orders` (ENTRY) calls `place_entry_order` and does not catch its errors, so a refusal must still be a 4xx, not a 500. |
| DB-11 | **`kill_switch_state(db, user_id=...)` caches the account part for 15 s per user.** The kill switch and halt are re-read on every call. Passing `now` or `state` bypasses the cache. | Slice C asks on every monitor round (15 s), and risk_book reads the data platform for desk marks. |
| DB-12 | **P1 item 9 (F&O defined-risk proposals) is not built.** F&O stays NOT_TRADABLE `instrument_not_enabled`. | DESIGN §9 puts F&O multi-leg execution out of scope tonight, and slice C's `create_entry_order` is single-leg cash. A proposal nothing can execute would mislead. |

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
| SPT-B-10 | proposal | Price missing / stale | WF#18, PRD §18 r18 | no live quote, or one older than `SPT_QUOTE_MAX_AGE_S` → no proposal is written (`PriceUnavailable`), and the pipeline tries again next round; refusals that need no price are still written; inside the risk step a stale price → BLOCKED `price_stale`; no number is made up |
| SPT-B-11 | sizing | PRD §8.4 example | WF#6, PRD §8.4, WF §8.4 | equity ₹10,00,000, 0.5 %, 500/480, cost ₹0.50/share → 243 shares, capital ₹1,21,500, planned risk ₹4,981.50; stressed = planned + 243 × 480 × gap % |
| SPT-B-12 | sizing | Costs from the desk cost card | WF#6 | with no cost given, `desk_trading.max_units_within_budget`: loss at stop + desk-cost-v2 round trip ≤ allowed risk, and one share more would not be |
| SPT-B-13 | sizing | Caps in order | WF §8.2 | liquidity (≤ participation % of the 20-day ADV), position exposure (profile `max_position_pct`), available capital minus the reserve bucket; each step `{cap, before, after, reason}`; SPT risk % capped at the profile's per-trade % (never looser); the profile per-trade cap (DB-3) |
| SPT-B-14 | sizing | Liquidity unknown / below floor | WF#18 | ADV unknown → 0 shares `liquidity_unknown`; ADV < `min_adv_rs` → 0 `liquidity_below_floor` |
| SPT-B-15 | allocation | WF §9.4 ₹80,000 example | WF#7, WF §9.4 | ₹1,21,500 needed, ₹80,000 available: reserve 0 → ALLOCATION_REDUCED to 160 shares (₹80,000); default 10 % reserve → ALLOCATION_REJECTED `reserve_protected`; capital required never above available |
| SPT-B-16 | allocation | Reserved + buckets + limits | WF#7 | pending-entry reservations counted as reserved (not deployed); equity_positional bucket room; sector room; max positions and max new per day → REJECTED with the code |
| SPT-B-17 | allocation | Ranking | PRD §8.7 | ordered by opportunity_score, then R:R, then liquidity; a higher scanner score alone does not rank first; a batch never exceeds the room (capital/bucket/positions) |
| SPT-B-18 | risk | Risk before the order | WF#8 | auto mode: `create_entry_order` called only after an APPROVE / APPROVE_REDUCED with a reservation; `order_id` = the reservation's `trade_id`; EntryRequest path `spt_entry`, store `spt_orders`, mode paper, target = T2, actor `spt_pipeline` |
| SPT-B-19 | risk | PRD-S2: valid but breaches portfolio risk; the service's veto | WF#9, PRD-S2 | open risk already at the cap → BLOCKED_BY_RISK at allocation (`open_risk_full`), before the service, with no reservation and no order. 19b: SPT's checks pass and the service refuses (profile min R:R 5 set by an admin, MOCK) → REJECTED `reward_risk_too_low` |
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
| SPT-B-39 | contract (C→B) | `place_entry_order(db, *, user_id, proposal_id, actor_id)` | integrator note 1, WF §11.2 | READY_FOR_ORDER (left by a failed create) → re-validated, fresh risk with a new reservation, create with the same idempotency key → ORDER_CREATED; ORDER_CREATED → the existing order (`duplicate`); AWAITING → an approval; another user's → 404; refusals are 409 HTTP errors (`entry_no_longer_valid`, `risk_refused`) with `last_place_refusal` recorded |
| SPT-B-40 | contract (C→B) | C returns a REJECTED order | integrator note 4 | proposal ORDER_CREATED + `order_rejected`; the ledger shows one `cancel_reservation` (C's), none from B |
| SPT-B-41 | contract (C→B) | `kill_switch_state(db, user_id=...)` keys | integrator note 2, WF §19.3 | `entries_blocked`, `blocking`, `kill_switch`, `halted`, `state`, `reasons`, `code`, `reason`; the halt read live through the 15 s cache; ladder restricted / halt and period losses block |
| SPT-B-42 | SPT P&L | an open SPT loss today | integrator note 5, PRD-S7 | −₹30,000 marked → equity ₹9,70,000, day P&L −₹30,000, drawdown 3 % (reduce band), RESTRICTED `daily_loss_halt` |
| SPT-B-43 | SPT P&L | positions from before the period | DB-8 | losses since entry count, gains don't (`conservative`); a position opened this week counts in full in the week; one closed today and paid out counts in the day's P&L, not again in equity |
| SPT-B-44 | SPT P&L | unmarked / stale | DB-8 | no mark 10 min after the fill, or a 5-day-old mark → equity unknown, entries blocked; no mark 1 min after the fill → valued at the fill (− entry costs) |

## Not in slice B (stated so nobody assumes it)

Cancelling pending entry orders on the kill switch, fills, positions, exits and modifications themselves (slice C);
opportunity creation and validation (slice A); server wiring (integrator); correlation / VaR (P1, out of scope);
F&O proposals (P1 stretch, item 9).

## Status (5 Nov 2026 ~03:00 IST, `backend/tests/test_spt_b_*.py`, 121 tests)

Every id SPT-B-01 … SPT-B-44 has at least one test, and all of them pass. The full run, with the neighbour suites, is in
`test_reports/spt_b_pytest.txt`.

| Ids | Tests |
|---|---|
| 01–03, 05–17 | `test_spt_b_core.py` (config, proposals, sizing, allocation; 07b and 10 run the pipeline) |
| 18–33, 37, 38 | `test_spt_b_pipeline.py` (the risk decision through the real universal risk service and paper account, the modes, approvals, modifications in slice C's form too, the kill-switch state, events, stress) |
| 02–04, 31, 34–36 | `test_spt_b_routes.py` (over HTTP) |
| 39–44 | `test_spt_b_contract.py` (the integrator's slice-C contract notes and the SPT positions' P&L) |

**Cross-slice check (scratch only, not committed).** B's branch was combined with slice A's and slice C's current
modules in a scratch copy and tested together. C's real `POST /api/v1/paper/orders` (ENTRY) placed a READY_FOR_ORDER
proposal through `place_entry_order` and C's real `create_entry_order` (order PENDING, reservation held, the orphan
sweep keeps it). A kill-switch refusal came back as 409 `risk_refused`. C's `controls.entry_block` read B's restricted
band. A's real `transition` expired an invalidated opportunity.

Two of C's tests fail in that combined copy, both test-isolation issues in C's tests (B's code is not involved):
- `test_c28b`
- `test_c32c`

They simulate "B not importable" with `sys.modules[...] = None`, but `from services.spt import risk / pipeline` returns
the package attribute once B's real module has been imported. Fix (C's tests): also
`monkeypatch.delattr(services.spt, "risk" / "pipeline", raising=False)`.

**Not verified:**
- No staging run: no writes to staging were allowed, and the integrator owns the staging step.
- The real-Mongo reservation suite (`tests/test_risk_reservation_mongo.py`, 5 tests) is skipped: it needs `RISK_MONGO_URL`.

## Owner decisions of 5 Nov 2026 ~06:50 IST: SPT config (SPT-CFG)

Built in the integration worktree, `feat/spt-integration`. Tests are in `backend/tests/test_spt_config.py`; the B suites were updated
for the new defaults. Owner: "Risk Limits make in configurable. The default is as per user risk profile … for each user
make it configurable so admin can change it" · "Agree and make it configurable".

| Id | Case | Expected |
|---|---|---|
| SPT-CFG-01 | Defaults derived from the owner-default profile | ladder 3.33 / 6.67 / 10 (reduce factor 0.5), min R:R 1.5, risk 0.5 / 0.35 / 0.35; the rest are owner-approved SPT defaults; `defaults_source` names each one |
| SPT-CFG-02 | A profile change flows through | profile 0.3 / 9 / 2.0 → risk 0.3 / 0.21 / 0.21, ladder 3 / 6 / 9, min R:R 2.0; overrides kept; only `overrides` stored |
| SPT-CFG-03 | Overrides persist; null resets | an override is kept across reads; null removes it (back to the default); nothing to remove → `no_change` |
| SPT-CFG-04 | The holder tightens | 11 tightening / neutral changes accepted, no `loosened` |
| SPT-CFG-05 | Loosening needs an admin | 8 loosening changes → 403 `admin_required` with the `loosened` paths; an admin without a reason → 422; an admin with a reason → applied, version row `actor_is_admin`, `loosened`, `reason` |
| SPT-CFG-06 | Removing an override is judged by its fallback | removing max_positions 6 → default 10 is a loosening (403); an admin may |
| SPT-CFG-07 | An admin risk % above the profile | accepted with a warning; capped at the profile where it is used |
| SPT-CFG-08 | Routes | admin routes 401 without a session, 403 for a non-admin; user tightens / 403 on a loosening / admin loosens with a reason / an admin on their own account may loosen; the admin GET shows effective, overrides, defaults, profile, versions |
| SPT-CFG-09 | Market-wide settings | validation codes; stored > env > default; null resets to env; version rows; 409 on a stale version; the overlay feeds A (floor, window, per-round), B and C (quote age); the routes |
| SPT-CFG-10 | A qualifies against the settings floor | the same MOCK stock (≈ ₹10 crore a day) qualifies under ₹1 crore and is REJECTED `liquidity_too_low` under a ₹50 crore settings floor |
