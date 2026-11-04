# SPT slice C — paper orders → execution → fills → positions → monitoring/exits → modifications → reconciliation

- **Branch:** feat/spt-paper-exec (worktree /home/deploy/nivesh-wt-spt-c, based on e3b363f1)
- **Date:** 2026-11-05 (overnight build)
- **Author:** Claude (builder C; FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Design:** docs/scanner_paper_trading/DESIGN.md §3–§8 (binding), EXISTING_CODE_MAP.md
- **Scope verified here:** unit tests with in-memory fakes (no network, no real DB) in the backend image. NOT verified on
  staging: nothing is wired into server.py yet (the integrator does that), so there is no staging API evidence in this file.

## Deviations and clarifications (read first)

| # | Where | What | Why |
|---|---|---|---|
| X1 | execution, no-depth fills | "At most `SPT_NO_DEPTH_MAX_QTY_FRACTION` (0.25) **of the order** per round" (DESIGN §6 wording), at least 1 share, never more than the remaining. The brief said "of the remaining". | DESIGN is binding. "Of the remaining" never fills the last shares cleanly (25% of 3 shares) and leaves a stop exit dribbling out for many rounds. A 1–3 share order necessarily fills one share per round. |
| X2 | execution, slippage | The 0.05% slippage of desk-cost-v2 is put **in the fill price** (BUY ask × 1.0005, SELL bid × 0.9995) and is therefore **not charged again** as a cost component: the per-fill costs are the card's statutory charges + brokerage with `slippage_pct_per_side = 0`. Each fill records `slippage_rs` (price impact vs the quote) so it stays visible. | Charging it in both places would double count it. The desk card's slippage is also its spread allowance because the desk has no bid/ask; SPT fills at the real bid/ask. |
| X3 | execution, brokerage | ₹20 brokerage is charged **once per order** (on its first fill), statutory charges on every fill's value. | A broker charges brokerage per executed order, not per partial fill. |
| X4 | execution, no bid/ask | When bid/ask are absent the price is LTP ± `SPT_NO_DEPTH_SPREAD_PCT` (0.05 %, the desk's spread allowance) and then ± slippage. When bid/ask exist but their quantity does not, the bid/ask price is used with the no-depth quantity cap. Both are flagged `depth_unknown: true`. | The live cache holds only the top of book (bid, ask, bid_qty, ask_qty; read from feed.top_of_book and a key/type peek of the staging snapshot). Five-level depth is consumed when a quote carries `depth` (none does today). |
| X5 | execution, entry guard (addition) | An ENTRY fill is refused when the executable price is above the planned entry × (1 + `SPT_ENTRY_MAX_DEVIATION_PCT`/100, default 2 %) (`price_beyond_plan`) or at/below the plan's stop (`price_through_stop`). The order stays pending until its time in force. | The reservation blocked quantity × planned entry and the risk service sized the risk on the planned entry and stop. A MARKET buy after a gap would silently over-draw the blocked amount or buy below the stop. Not in DESIGN; configurable. |
| X6 | execution, same quote | One cached quote (same `received_at`) is consumed at most once per order. | The displayed quantity of a quote that has not changed was already taken. |
| X7 | quotes | The default reader is `kite_live_feed.day_quote.day_quotes` (Redis quote cache first, the feed snapshot behind it, `source == "kite_live"` only), then the ≤ 120 s `received_at` rule per quote. | It reads `quote_cache.read_quotes` (DESIGN §6) and adds the snapshot when Redis is down, and it refuses quotes when the feed is not live. |
| X8 | events | A REJECTED order emits `PAPER_ORDER_CANCELLED` with `payload.state = "REJECTED"`. | `constants.EVENT_TYPES` has no PAPER_ORDER_REJECTED and the contract is not changed here. |
| X9 | P&L into cash | Realised P&L of partial exits (T1) is kept on the position and credited to paper cash **once, at close**, in the single `paper_account.release(...)` call. | `release` also returns the risk reservation of the trade id; calling it at T1 would give back the open position's risk budget early. |
| X10 | trend exit | `close_below_sma20` is evaluated as the close below the simple 20-session average of closes (the exit plan's rule), not `exit_rules`' EMA rule. The ATR trail uses `exit_rules` (`trail-atr-v1` through `start`/`step`). | The plan names the SMA; `exit_rules` has only an EMA trend rule. |
| X11 | time exit | `max_hold_sessions` reached at the evening pass → EXIT_PENDING → exit at the next session's first live quote. | No fill is ever made from a bar (DESIGN D6). |
| X12 | missed stop | When the evening bar's low went through the stop and no live exit happened (stale quotes all day), the position becomes EXIT_PENDING (reason stop, `stop_breached_without_live_exit`) and exits at the next session's first live quote. | Never fill at a bar price; never leave a breached stop silently. |
| X13 | RECONCILIATION_REQUIRED | Positions in RECONCILIATION_REQUIRED (or EXECUTION_EXCEPTION) get **no automatic** exit orders; a manual exit through the API is still allowed. | Their quantity is in doubt; the morning check lists them. |
| X14 | ENTRY via the API | `POST /api/v1/paper/orders` with purpose ENTRY needs a proposal of the caller in READY_FOR_ORDER and hands it to slice B's `services.spt.pipeline.place_entry_order(db, *, user_id, proposal_id, actor_id)` (lazy import). Without that function: 503 `entry_pipeline_unavailable`. A proposal already in ORDER_CREATED returns its order. | Slice C must not call the risk service itself (B owns path `spt_entry`); this keeps "never bypass risk". The function name is a NEW contract for the integrator to confirm with B. |
| X15 | kill switch read | Entries are blocked when `risk_controls` (kill switch / halt; unreadable = blocked) says so, **or** when slice B's `services.spt.risk.kill_switch_state(db, user_id=...)` exists and reports any of `entries_blocked`, `blocking`, `kill_switch`, `halted` true or `state` in TRIGGERED/RESTRICTED/RESET_PENDING. Without B, the daily-loss block is not read by C. | B's function shape is not known tonight; the union is the strictest reading. |
| X16 | DAY orders out of session | A DAY order created after 15:30 (or on a weekend) is for the next weekday session and expires at its 15:30 IST. NSE holidays are not looked up: a holiday has no live quotes, so the order expires unfilled (DESIGN: "a day of stale quotes ends with the order EXPIRED"). | Keeps the clock deterministic and testable. |
| X17 | entry: reservation ownership (addition) | Before anything else, `create_entry_order` checks that the decision's `reservation_id` is on the account **with `trade_id == order_id`** (DESIGN §4). Missing → REJECTED `reservation_not_found`; another trade's → `reservation_trade_mismatch`. Both mark `reservation_state: not_ours`, so the refusal never cancels a reservation this order does not hold. | Enforces the contract and protects other trades' budgets from a wrong call. |
| X18 | one live exit per position | A position holds at most one live exit order. A full exit (stop, T2, trailing, trend, time, manual close) replaces a live partial one (T1 / manual reduce), which is cancelled first, and cancels the live remainder of the position's ENTRY. | Two exit orders could together sell more than is held. |
| X19 | where SPT P&L shows (open question, not a deviation) | `services/risk_book.read` (equity, day / week P&L, drawdown for the risk service) reads only `desk_paper_trades` and the journal. SPT positions are in the account's reservation counters (risk, exposure, positions, sector, held symbol) but their **unrealised** P&L is not in the risk book's equity or daily-loss figure; their realised P&L reaches paper cash at close. | Changing risk_book is outside slice C; flagged for slice B / the integrator. |

## Status (2026-11-05, unit tests in the backend image; staging NOT exercised — see OVERRIDE_spt_c_paper_exec.md)

| ID | Test(s) | Result |
|----|---------|--------|
| SPT-C-01 | test_c01_create_entry_order_happy_path, test_c01b_day_order_after_the_close_is_for_the_next_session | PASS |
| SPT-C-02 | test_c02_duplicate_create_returns_the_first_order | PASS |
| SPT-C-03 | test_c03_refusals_reject_and_release_once, test_c03b_kill_switch_at_create_rejects_and_releases, test_c03c_open_position_in_the_symbol_rejects_a_second_entry, test_c03d_reservation_must_be_this_orders | PASS |
| SPT-C-04 | test_c04_cancel_unfilled_entry_releases_exactly_once | PASS |
| SPT-C-05 | test_c05_day_and_gtd_expiry, test_c05b_gtd_in_the_past_is_rejected | PASS |
| SPT-C-06 | test_c06_partial_then_expiry_keeps_the_reservation_for_the_position | PASS |
| SPT-C-07 | test_c07_buy_at_ask_plus_slippage_capped_at_displayed_qty, test_c07b_sell_at_bid_minus_slippage, test_c07c_partial_fill_then_rest_on_a_new_quote | PASS |
| SPT-C-08 | test_c08_five_level_depth_fills_level_by_level | PASS |
| SPT-C-09 | test_c09_no_bid_ask_fills_at_most_a_quarter_of_the_order_at_ltp_plus_spread, test_c09b_ask_without_quantity_is_depth_unknown | PASS |
| SPT-C-10 | test_c10_no_fill_without_a_fresh_quote (5 cases), test_c10b_out_of_session_and_feed_not_live | PASS |
| SPT-C-11 | test_c11_limit_buy_never_above_its_limit, test_c11b_stop_orders_trigger_on_ltp_crossing | PASS |
| SPT-C-12 | test_c12_costs_per_fill_from_the_desk_card | PASS |
| SPT-C-13 | test_c13_one_quote_is_consumed_once | PASS |
| SPT-C-14 | test_c14_entry_guard_against_the_plan, test_c14b_exit_never_sells_more_than_held | PASS |
| SPT-C-15 | test_c15_position_on_first_fill_with_weighted_average | PASS |
| SPT-C-16 | test_c16_c17_pnl_from_fills_and_one_release | PASS |
| SPT-C-17 | test_c16_c17_pnl_from_fills_and_one_release, test_c17b_missing_reservation_is_recorded_not_fixed, test_c17c_a_fill_for_a_closed_position_is_never_applied | PASS |
| SPT-C-18 | test_c21_c22_c35_t1_breakeven_then_t2_and_the_outcome (R, MFE), test_c32d_positions_modify_trades_reconcile (R, MFE in /trades) | PASS |
| SPT-C-19 | test_c19_stop_on_the_bid_exits_at_the_bid_not_the_stop | PASS |
| SPT-C-20 | test_c20_gap_through_the_stop_exits_at_the_first_live_bid | PASS |
| SPT-C-21 | test_c21_c22_c35_t1_breakeven_then_t2_and_the_outcome, test_c21b_stop_after_t1_is_the_breakeven | PASS |
| SPT-C-22 | test_c21_c22_c35_t1_breakeven_then_t2_and_the_outcome | PASS |
| SPT-C-23 | test_c23_kill_switch_cancels_entries_but_exits_still_fill | PASS |
| SPT-C-24 | test_c24_replaying_a_round_never_double_fills, test_c24b_crash_after_the_fill_is_recovered_once, test_c24c_concurrent_writer_loses_cleanly | PASS |
| SPT-C-25 | test_c25_evening_trail_raises_only_and_waits_for_todays_bar, test_c25b_trend_exit_pending_then_next_session_first_quote, test_c25c_time_exit_and_missed_stop, test_c25d_a_low_below_only_a_stop_raised_later_that_day_is_not_a_missed_stop | PASS |
| SPT-C-26 | test_c26_gating_leader_and_robustness, test_c26b_start_respects_the_flag | PASS |
| SPT-C-27 | test_c27_reducing_changes_apply_without_b_also_under_the_kill_switch | PASS |
| SPT-C-28 | test_c28_increasing_changes_go_to_b, test_c28b_increasing_refused_under_kill_switch_and_without_b | PASS (B's check_modification is a FAKE) |
| SPT-C-29 | test_c29_target_reached_while_the_stop_is_being_modified | PASS |
| SPT-C-30 | test_c30_reduce_and_close_work_under_the_kill_switch | PASS |
| SPT-C-31 | test_c31_reconciliation_report_and_startup_marks | PASS |
| SPT-C-32 | test_c32_auth_and_ownership, test_c32b_orders_endpoints, test_c32c_entry_needs_a_ready_proposal_and_b, test_c32d_positions_modify_trades_reconcile | PASS (B's pipeline is a FAKE) |
| SPT-C-33 | test_c33_manual_exit_twice_is_one_order | PASS |
| SPT-C-34 | test_c34_events_after_sends_only_new_events_of_the_caller, test_c34b_stream_endpoint | PASS |
| SPT-C-35 | test_c21_c22_c35_t1_breakeven_then_t2_and_the_outcome | PASS |

## Test Cases

| ID | Area | Scenario | Covers | Type | Expected |
|----|------|----------|--------|------|----------|
| SPT-C-01 | orders | `create_entry_order` happy path (B's call per DESIGN §4 with `order_id=`) | WF §12.1, §12.4 | unit | `_id == order_id`; CREATED → VALIDATED → PENDING by conditional updates (version 0→3); risk {decision_id, reservation_id, decision} kept; DAY `expires_at` = 15:30 IST of the session; PAPER_ORDER_CREATED once |
| SPT-C-02 | orders | duplicate create: same idempotency_key (and the same order id) | WF §25 #2, PRD §23.3 #11 | unit | one order document; the second call returns the first order (`duplicate: true`); one PAPER_ORDER_CREATED |
| SPT-C-03 | orders | refusals: no reservation / blocked decision; quantity above the approved quantity; kill switch on at create; an open position in the symbol | WF §19.3, PRD §18 #13 | unit | order REJECTED with `reject_reason`; a held reservation cancelled exactly once (one `cancel_reservation` ledger row); no fills |
| SPT-C-04 | orders | cancel an ENTRY with zero fills, twice | WF §12.3 | unit | CANCELLED; reservation cancelled once; second cancel is a no-op (409 `order_not_live` at the API) |
| SPT-C-05 | orders | DAY expiry at 15:30 with zero fills; GTD at `expires_at` | DESIGN §6, WF §12.3 | unit | EXPIRED, ORDER_EXPIRED event, reservation released once; nothing expires before its time |
| SPT-C-06 | orders | partially filled then expired | WF §25 #12 | unit | state EXPIRED, remaining_quantity 0 cancelled, `cancelled_quantity` recorded, position keeps the filled quantity, reservation KEPT (released at close) |
| SPT-C-07 | execution | BUY MARKET at the ask + 0.05 %, capped at ask_qty → partial; next round (new quote) fills the rest | WF §25 #11 #12, PRD §23.3 #3 | unit | fills seq 1, 2 with `_id` order_id:seq; order PARTIALLY_FILLED then FILLED; filled + remaining = quantity; PAPER_ORDER_PARTIALLY_FILLED then PAPER_ORDER_FILLED |
| SPT-C-08 | execution | a quote with five depth levels | DESIGN §6 | unit | fills level by level, each at its own price (+ slippage), up to the displayed quantity |
| SPT-C-09 | execution | no bid/ask in the quote | DESIGN §6, X1, X4 | unit | at most 25 % of the order per round at LTP × (1 + 0.05 % + 0.05 %), `depth_unknown: true`; never the whole order in one round |
| SPT-C-10 | execution | stale quote (> 120 s), missing quote, out of session, feed not live | WF §20, WF §25 #18, PRD §23.3 #5 | unit | no fill; `last_attempt.reason` quote_stale / quote_missing / out_of_session; no price is invented |
| SPT-C-11 | execution | LIMIT buy: ask above the limit → no fill; ask ≤ limit → fill never above the limit. SL/SL_M: trigger on LTP crossing, then marketable | WF §12.3 | unit | as stated; `triggered_at` recorded once |
| SPT-C-12 | execution | costs per fill from desk-cost-v2 equity delivery | WF §12.2 #7, X2, X3 | unit | brokerage ₹20 on the first fill only; STT/exchange/SEBI/stamp/GST per fill equal `desk_cost_card.order_side`; slippage component 0; card snapshot on the order |
| SPT-C-13 | execution | the same quote twice | X6 | unit | the second round fills nothing (`quote_already_used`) |
| SPT-C-14 | execution | entry guard | X5 | unit | ask > planned × 1.02 → `price_beyond_plan`; ask ≤ stop → `price_through_stop`; no fill |
| SPT-C-15 | positions | position only on the first fill; weighted average; one open position per (user, symbol, direction) | WF §12.5, WF §25 #12 #13 | unit | no position before a fill; avg = Σ(q·p)/Σq; POSITION_OPENED once; a second open position for the symbol is refused |
| SPT-C-16 | positions | realised P&L per exit fill net of costs | WF §16.3, WF §25 #13 | unit | Σ exit fills' net = exit proceeds − entry cost − all costs (to the paisa); position P&L reconciles to the fills |
| SPT-C-17 | positions | close releases exactly once | DESIGN §4, WF §16.2 #10 | unit | `paper_account.release(amount = the reservation's funding_rs, net_pnl, trade_id = entry order id)` once: one release ledger row, blocked back to 0, cash += net; re-running the close / sync moves nothing |
| SPT-C-18 | positions | R multiple, MFE/MAE | WF §13.2, §17.2 | unit | R = net / initial risk; MFE/MAE from the executable price seen while open |
| SPT-C-19 | monitor | stop: bid ≤ stop | WF §13.4, PRD §18 #19 | unit | STOP_TRIGGERED; one MARKET exit for the full quantity; filled at the BID (not at the stop) |
| SPT-C-20 | monitor | gap through the stop at the open | PRD §23.3 #4 | unit | exit at the first live bid, `gap: true` on the exit order and fills |
| SPT-C-21 | monitor | T1: bid ≥ T1 | DESIGN §6 | unit | TARGET_TRIGGERED; exit of t1_exit_fraction; once filled the stop moves to breakeven (avg + costs per share), STOP_MOVED + an audit record |
| SPT-C-22 | monitor | T2 after T1 | DESIGN §6 | unit | the rest exits; CLOSED with exit reason target_2; release once |
| SPT-C-23 | monitor | kill switch on while entry orders are pending and a position is open | WF §19.3, WF §25 #15 #17, PRD §23.3 #14, PRD §18 #12–#14 | unit | pending ENTRY orders CANCELLED (reason kill_switch_on), reservations released; no entry fill; the stop exit still fills |
| SPT-C-24 | monitor | restart/replay: the same round twice; a crash after a fill insert and before the order update | WF §20.3, WF §25 #19, PRD §23.3 #10 | unit | no second fill; `sync_order` recovers the recorded fill into the order and the position once |
| SPT-C-25 | monitor | evening pass | DESIGN §6, X10–X12 | unit | waits for today's bar; ATR trail raises the stop only (never lowers it); close < SMA20 → EXIT_PENDING → exit at the next session's first live quote; time exit after max_hold_sessions; missed stop → EXIT_PENDING |
| SPT-C-26 | monitor | gating and robustness | DESIGN §2 | unit | `enabled()` by APP_ENV / SPT_C_ENABLED; not the leader → nothing written; a failing dependency is caught, counted in `spt_state.errors`, and the round returns |
| SPT-C-27 | modify | tighter stop / target change / enable trailing (reducing or neutral), also under the kill switch | WF §14, WF §25 #15 | unit | applied without B's check; audit {position_id, previous, new, requested_by, at, reason, risk_decision, market_ref}; POSITION_MODIFIED and STOP_MOVED |
| SPT-C-28 | modify | wider stop / removing the stop / disabling the trail (increasing) | WF §14.2, WF §25 #14, PRD §8.5 | unit | B's `check_modification` (fake) is called; reject → 409 `modification_rejected_by_risk`, nothing changes; approve → applied with the decision on the audit record; B missing → 503 `risk_check_unavailable` |
| SPT-C-29 | modify | a target reached while the stop is being modified | PRD §23.3 #9 | unit | the modification carries the version it read; a concurrent T1 exit bumps the version → 409 `position_changed`; no lost update |
| SPT-C-30 | modify | reduce quantity / close, under the kill switch | PRD §23.3 #13, PRD §18 #12 #14 | unit | an EXIT order (reason manual) is created and fills; a second close returns the same live exit order |
| SPT-C-31 | reconcile | clean book, then each mismatch | WF §20.3 | unit | ok on a clean book; reports order_fill_mismatch, position_quantity_mismatch, closed_without_release, reservation_without_order_or_position, fill_without_position; the startup pass marks RECONCILIATION_REQUIRED and moves no money |
| SPT-C-32 | routes | auth and ownership; every endpoint | PRD §17.4, §21.1 | api (TestClient, fakes) | 401 without a session; another user's order/position → 404; ENTRY without a READY_FOR_ORDER proposal → 422 `entry_requires_approved_proposal`; stable `detail.code`s |
| SPT-C-33 | routes | manual exit twice | WF §25 #2 | api | one live exit order |
| SPT-C-34 | P1 stream | GET /paper/stream | PRD §17.6 (SSE instead of WS, D8) | unit | only new events of the caller, in order; no snapshot per tick |
| SPT-C-35 | P1 outcome | trade outcome record at close | WF §17.2 | unit | entry/exit fills, costs, slippage vs the planned entry, planned risk, R, holding time, MFE/MAE, exit reason, versions; TRADE_ANALYTICS_COMPLETED once |

## Evidence

The pytest run and its real output are in `test_reports/spt_c_pytest.txt` (written at the end of the build).
