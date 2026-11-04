# SPT slice A — test cases: signals → opportunities → validation → signal outcomes

- **Branch:** `feat/spt-signals` (worktree `/home/deploy/nivesh-wt-spt-a`)
- **Date:** 2026-11-05 (written ~02:15 IST, before implementation)
- **Author:** Claude (builder A: FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Design:** `docs/scanner_paper_trading/DESIGN.md` (D1–D10, §3 collections, §4 contracts, §5 state machines, §7 events, §8 tests)
- **Scope:** `services/spt/signals/`, `services/spt/opportunities/`, `services/spt/outcomes/`, `routes/spt_signals.py`,
  `scripts/spt_backfill_signals.py`, a minimal hook in `services/scan_builder/signals.py`.
- **Environment of these tests:** unit tests in the backend image (`nivesh/backend:staging`, `--network none`), in-memory
  Mongo fakes. Nothing here is verified on staging (no staging writes are allowed tonight; the integrator verifies on staging).

## Deviations from DESIGN.md (kept short; each is also in the final report)

1. **Consolidation key window.** DESIGN/PRD: `SYMBOL|direction|horizon|window`. The window part is the IST day the window
   starts (the opportunity's first signal day), e.g. `RELIANCE|long|positional|2026-11-04`. A later signal attaches when it
   falls inside an existing opportunity's window (positional: `SPT_POSITIONAL_WINDOW_SESSIONS`, default 5 sessions from
   `first_seen_at`, weekday calendar; intraday: the same IST day until 15:31 IST, the end of the 15:30 minute). The key alone cannot be computed from one
   signal without knowing when the window started, so lookup is by (symbol, direction, horizon, window covers the signal).
2. **A REJECTED opportunity keeps absorbing signals of its own window** (they are attached, it stays REJECTED). Otherwise
   every later list mark of an illiquid stock would open a new opportunity that is rejected again (churn). EXPIRED does not
   absorb: a signal after an expiry starts a new opportunity.
3. **Conflicting evidence present at validation downgrades QUALIFIED to CONDITIONAL** (reason `conflicting_signals`).
   DESIGN's QUALIFIED rule does not mention conflicts; WF §5.4 says they must be surfaced. This is stricter than DESIGN,
   never looser. A conflict that arrives AFTER an opportunity is QUALIFIED does not change its state (DESIGN §5: QUALIFIED
   is left only for EXPIRED); it is recorded in `conflicts` and sets `conflict_after_qualified: true` for slice B to read.
4. **`timeframe` uses "1h" and "1W"** besides "1D"/"15m"/"5m" where a list's conditions use those bars (Long Build Up's
   1-hour DMI; Uptrend 52-week and High growth use weekly bars). PRD §6.2 allows "5m, 15m, 1D, 1W etc.".
5. **`scanner_score` of a list mark** is the stock's strength score from the day's scores doc only when that doc was saved
   at or after the detection and at most `SCORE_MATCH_S` (120 s) later; otherwise null with `scanner_score_note`. The scan
   round that records a mark saves the scores (with the same timestamp) right after recording; an earlier doc predates the
   mark and a later one (4 Nov's final doc is as of 22:45 IST) is not the score at detection. The hook waits
   `SPT_INGEST_DELAY_S` (20 s) and the catch-up leaves marks younger than 35 s to the hook, so the round's doc is read.
6. **QUALIFIED, REJECTED and EXPIRED are not revalidated.** `POST /opportunities/{id}/validate` answers 409
   `opportunity_not_revalidatable` for them (DESIGN §5 allows VALIDATING only from CREATED, CONDITIONAL, WATCHLIST,
   DATA_INSUFFICIENT).
7. **The first strong signal extends the window to its own** (`window_until` / `expires_at` = max(current, the strong
   signal's day + N sessions)). Without it, a plan that joins a window opened by list marks days earlier could be
   QUALIFIED with hours left. The consolidation key keeps the window's start day.
8. **`stale` has a grace of `STALE_GRACE_S` (120 s)** after `expiry_at`, so a mark recorded in the session's last seconds is
   not called late because of the hook's own 20 s delay.

## Test cases

Type: unit = pure function; svc = service with in-memory fakes; api = FastAPI TestClient with the in-memory fakes;
data = a fixture copied from the real 4 Nov Redis dump (`/home/deploy/nivesh-signal-archive/redis_dump_20261105.jsonl`,
market-wide data only).

| ID | Area | Scenario | Type | Expected | Covers |
|----|------|----------|------|----------|--------|
| SPT-A-01 | normalize | Every widget id whose rows are stocks (`ROW_KIND == "symbol"`) on every dashboard in `market_dashboard.DASHBOARDS` (Atlas, Day trade, Early movers) is in `LIST_MAP` | unit | test fails naming any missing id; every map entry has a known category, timeframe, horizon and direction | P0-1 |
| SPT-A-02 | normalize | Horizon rules | unit | every `POSITIONAL_LISTS` id → positional; 15-minute breakouts, RSI VWAP, 10x first 5 min (both), early movers, strong movers, Nifty 50 gainers, explosive → intraday | P0-1 |
| SPT-A-03 | normalize | Direction rules | unit | `open_interest`/`oi_7` take the recorded entry's `direction` (short when the stock fell); below-50/200-DMA and 10 %-down lists are short/bearish whatever the entry says; others long | P0-1 |
| SPT-A-04 | normalize | A strong signal | unit | scanner_id `strength_70`, family `signal_strength`, horizon positional, direction long, category from its `lists_at` (positional list first) | P0-1 |
| SPT-A-05 | ingest | A list mark becomes the PRD §6.2 event | svc | `_id` = `sig:<day>:<widget>:<SYM>`; signal_id, scanner_id, scanner_name, instrument_id = symbol, exchange NSE, segment Equity, direction, timeframe, detected_at = `first_seen`, detected_price = `entry`, scanner_score, score_version, signal_type/category, supporting_metrics = the raw entry, market_regime null, expiry_at, normalizer_version | P0-2, WF 25.1 |
| SPT-A-06 | ingest | Scanner score at detection | svc | list mark: score from the scores doc when its `as_of` is within 120 s of detection, else null + note (never invented); strong: `score_at` | P0-2 |
| SPT-A-07 | ingest | The same mark delivered twice (hook + catch-up, two workers) | svc | one document, one RECEIVED and one NORMALIZED event; second call reports duplicate | WF 25.2, PRD 23.3 #11 |
| SPT-A-08 | ingest | Quarantine reasons | svc | missing mapping, invalid symbol, missing price, invalid timestamp, outside session → stored with `status: quarantined` and the reason code(s); RECEIVED emitted, NORMALIZED not | P0-2, WF 4.4/4.5 |
| SPT-A-09 | ingest | An expired signal received late | svc | received more than 120 s after its `expiry_at` → quarantined `stale`; never consolidated | PRD 23.3 #12 |
| SPT-A-10 | ingest | Original score and timestamp are never overwritten | svc | re-delivery with a different score / time leaves the stored event byte-identical | PRD §18 rule 7, WF 25.1 |
| SPT-A-11 | ingest | Events | svc | idempotency keys `sig:<id>:received` / `sig:<id>:normalized`; envelope per events.py; replay inserts no event | DESIGN §7 |
| SPT-A-12 | ingest | Real 4 Nov marks (copied from the dump) | data | 2 strong + list marks of 6 widgets normalize; the archive's `scan-plan-v2` marks keep their raw fields in supporting_metrics | P0-2 |
| SPT-A-13 | hook | `scan_builder.signals.record` / `record_strong` with the hook | svc | flag: staging on, `SPT_INGEST_ENABLED=0` off, `=1` on elsewhere; returns what it returned before; ingest runs as a task; an ingest error is logged, never raised; nothing scheduled for an already-stored mark | P0-3 |
| SPT-A-14 | hook | Catch-up of a day | svc | reads the day's list index and strong index from the signal store, ingests the missing ones; a second run inserts nothing | P0-3, WF 20.3 |
| SPT-A-15 | consolidate | Four scanners flag the same stock long, positional | svc | ONE opportunity with four signals (ids, scanner ids, times, scores, families kept); scores not summed; OPPORTUNITY_CREATED once, OPPORTUNITY_UPDATED per attach | PRD 23.3 #1, WF 25.3 |
| SPT-A-16 | consolidate | Windows and horizons | svc | intraday and positional marks of one stock → two opportunities; a positional mark 6 sessions later → a new opportunity; an intraday mark the next day → a new one | P0-4 |
| SPT-A-17 | consolidate | Opposite directions on one stock | svc | both opportunities carry the other side's signals in `conflicts`; SIGNAL_CONFLICT_DETECTED once per signal (idempotent) | WF 25.4 |
| SPT-A-18 | consolidate | Strong signal | svc | attaches the frozen scan-plan-v3 plan in `strong`; a later strong signal in the window is attached but does not replace the first plan | P0-4 |
| SPT-A-19 | consolidate | Re-runs and races | svc | a second consolidation pass changes nothing; an open opportunity with the same key appearing between lookup and insert → the signal is attached to it, no duplicate | WF 25.2 |
| SPT-A-20 | consolidate | Quarantined events | svc | never attached to any opportunity | WF 4.4 |
| SPT-A-21 | store | `get`, `list_by_state`, `transition` | svc | conditional on expected states + version; wrong state → None, no write; version +1; `state_history` appended; QUALIFIED/REJECTED/EXPIRED emit their events | DESIGN §4 |
| SPT-A-22 | validate | Strong, plan ok, long, positional, fresh data, liquid, bullish | svc | QUALIFIED; the record has at, version, decision, reason_codes, explanations, opportunity_score, score_parts, market, stock, liquidity, derivatives (null, not_checked), data_as_of, revalidate_at; OPPORTUNITY_VALIDATED + OPPORTUNITY_QUALIFIED | P0-5, WF 6.5 |
| SPT-A-23 | validate | Risk-off regime (bearish, high volatility) | svc | CONDITIONAL, reason `regime_risk_off` | P0-5 |
| SPT-A-24 | validate | 20-day average traded value below the minimum | svc | REJECTED `liquidity_too_low` (OPPORTUNITY_REJECTED) | P0-5 |
| SPT-A-25 | validate | Data provider down / stale | svc | bars unreadable, bars stale, regime unavailable → DATA_INSUFFICIENT with reason; nothing invented; once data is back the revalidation moves it on | PRD 23.3 #5, WF 20 |
| SPT-A-26 | validate | Not tradable tonight | svc | no strong signal, intraday, short → validated and kept (WATCHLIST), never QUALIFIED | DESIGN D5 |
| SPT-A-27 | validate | Opportunity score | unit | built from DISTINCT families (two lists of one family count once), trend, participation, liquidity, regime; parts sum to the score; labelled "not a probability"; versioned; same inputs → same score | PRD 6.5, WF 25.21 |
| SPT-A-28 | validate | A bonus/split jump in the bars | unit | indicators use only the bars after `series_break` | P0-5 |
| SPT-A-29 | validate | Expiry | svc | past `window_until` → EXPIRED `window_ended`; a daily close below the plan's stop after detection → EXPIRED `closed_below_stop`; OPPORTUNITY_EXPIRED | P0-5 |
| SPT-A-30 | validate | Conflicting signals | svc | an otherwise qualifying opportunity with conflicts → CONDITIONAL `conflicting_signals` | WF 25.4 |
| SPT-A-31 | loop | Round | svc | enabled flag (staging / SPT_A_ENABLED); only the leader runs; catch-up → consolidate → validate → expire; `spt_state` {_id: spt_a, at, counts, errors}; a failing step is recorded and the round does not raise | P0-6 |
| SPT-A-32 | api | No session | api | 401 on every route | P0-7 |
| SPT-A-33 | api | GET /api/v1/scanner/signals(/{id}) | api | filters day, symbol, scanner_id, category, status; limit ≤ 500 (422 `invalid_limit`); bad day 422 `invalid_day`; unknown id 404 `signal_not_found` | P0-7 |
| SPT-A-34 | api | GET /api/v1/opportunities(/{id}), POST …/validate | api | filters state, day, symbol, horizon, direction, limit; 404 `opportunity_not_found`; 409 `opportunity_not_revalidatable`; 200 returns the validation | P0-7 |
| SPT-A-35 | backfill | `scripts/spt_backfill_signals.py` on an archive | svc | dry-run (default) prints counts and writes nothing; `--write` ingests and consolidates; a second `--write` adds nothing | P0-8, WF 20.3 |
| SPT-A-36 | outcomes | Forward returns and excursions | unit | T+1/5/10/20 close returns from the detection price; MFE/MAE per horizon (worked by hand); short signals measured in their own direction | P1-9, PRD 13.1 |
| SPT-A-37 | outcomes | Strong signal, hypothetical scan-plan-v3 | unit | first of stop / T1 / T2 / trend exit / time exit; the stop is judged on daily closes (scan-plan-v3's own rule), so a session that reaches a target and closes below the stop counts as the stop (conservative), and a gap below the stop is flagged (`gap_open`) and exits at that session's close; targets exit at the target, or the open on a gap above | P1-9, WF 17.1 |
| SPT-A-38 | outcomes | Series break after detection | unit | horizons after the break are null with reason `series_break` | P1-9 |
| SPT-A-39 | outcomes | Fade | svc | strong score below 70 in the detection day's scores doc → `faded: true`; no doc → null + reason | P1-9 |
| SPT-A-40 | outcomes | Kept apart from trades | svc | stored in `spt_signal_outcomes` keyed by signal id; no paper-trade collection is read or written; GET /api/v1/analytics/scanners gives counts, hit rates, average returns with sample sizes, small samples labelled | WF 25.20, PRD 13.7 |
| SPT-A-41 | outcomes | Evening run | svc | runs only after NSE's file for the day is in the bars; once per day | P1-9 |

## Not covered here (owned elsewhere or out of scope tonight)

- WF §25 items 5–19, 22: slices B and C.
- Real Mongo / Redis behaviour (unique index under concurrency, TTLs): verified by the integrator on staging, not here.
- Derivatives validation (WF §6.2 step 4): not built tonight; every validation says `derivatives: null` (not_checked).

## Results (unit tests, backend image, no network; NOT a staging verification)

Run: `test_reports/spt_a_pytest.txt` (the command is in its header) — `494 passed` for test_spt_a_*.py (76 tests) plus the
neighbour suites that import scan_builder.signals (test_scan_builder*.py, test_exit_watch.py, test_kite_trade_side.py,
test_market_recovery_indices.py, test_paper_pnl_live.py).

| ID | Test(s) | Result |
|----|---------|--------|
| SPT-A-01 | test_spt_a_signals.py::test_SPT_A_01_every_recordable_list_on_every_dashboard_is_mapped | PASS (unit) |
| SPT-A-02 | test_spt_a_signals.py::test_SPT_A_02_horizons_positional_lists_and_intraday_only_lists | PASS (unit) |
| SPT-A-03 | test_spt_a_signals.py::test_SPT_A_03_direction_rules | PASS (unit) |
| SPT-A-04 | test_spt_a_signals.py::test_SPT_A_04_strong_signal_is_its_own_scanner_with_the_category_of_its_lists | PASS (unit) |
| SPT-A-05 | test_spt_a_signals.py::test_SPT_A_05_a_list_mark_becomes_the_prd_event_with_its_original_identity | PASS (unit) |
| SPT-A-06 | test_spt_a_signals.py::test_SPT_A_06_scanner_score_only_when_the_scores_doc_is_at_the_detection | PASS (unit) |
| SPT-A-07 | test_spt_a_signals.py::test_SPT_A_07_duplicate_delivery_is_a_no_op | PASS (unit) |
| SPT-A-08 | test_spt_a_signals.py::test_SPT_A_08_quarantined_events_are_stored_with_their_reason<br>test_spt_a_signals.py::test_SPT_A_08b_a_mark_in_the_last_session_minute_is_in_session_and_not_stale_after_the_hook_delay | PASS (unit) |
| SPT-A-09 | test_spt_a_signals.py::test_SPT_A_09_an_expired_signal_received_late_is_quarantined_stale | PASS (unit) |
| SPT-A-10 | test_spt_a_signals.py::test_SPT_A_10_original_score_and_timestamp_are_never_overwritten | PASS (unit) |
| SPT-A-11 | test_spt_a_signals.py::test_SPT_A_11_events_carry_the_envelope_and_stable_keys | PASS (unit) |
| SPT-A-12 | test_spt_a_signals.py::test_SPT_A_12_real_4_nov_marks_normalize | PASS (unit) |
| SPT-A-13 | test_spt_a_signals.py::test_SPT_A_13_flag<br>test_spt_a_signals.py::test_SPT_A_13_record_hands_new_marks_to_ingest_without_blocking<br>test_spt_a_signals.py::test_SPT_A_13_an_ingest_failure_is_logged_and_never_reaches_the_scan_loop<br>test_spt_a_signals.py::test_SPT_A_13_the_hook_is_off_by_default | PASS (unit) |
| SPT-A-14 | test_spt_a_signals.py::test_SPT_A_14_catch_up_ingests_what_the_hook_missed_and_is_idempotent | PASS (unit) |
| SPT-A-15 | test_spt_a_opportunities.py::test_SPT_A_15_four_scanners_one_stock_one_opportunity_attribution_kept | PASS (unit) |
| SPT-A-16 | test_spt_a_opportunities.py::test_SPT_A_16_horizons_and_windows_split_opportunities | PASS (unit) |
| SPT-A-17 | test_spt_a_opportunities.py::test_SPT_A_17_opposite_directions_are_kept_as_conflicts_on_both_sides<br>test_spt_a_opportunities.py::test_SPT_A_17_a_conflict_on_a_qualified_opportunity_is_flagged_not_hidden | PASS (unit) |
| SPT-A-18 | test_spt_a_opportunities.py::test_SPT_A_18_strong_signal_attaches_its_frozen_plan_once<br>test_spt_a_opportunities.py::test_SPT_A_18_a_strong_signal_joining_an_old_window_gets_its_own_sessions | PASS (unit) |
| SPT-A-19 | test_spt_a_opportunities.py::test_SPT_A_19_reruns_and_a_lost_race_never_duplicate<br>test_spt_a_opportunities.py::test_SPT_A_19_a_placing_that_fails_after_the_attach_is_retried_with_its_conflicts | PASS (unit) |
| SPT-A-20 | test_spt_a_opportunities.py::test_SPT_A_20_quarantined_events_are_never_consolidated | PASS (unit) |
| SPT-A-21 | test_spt_a_opportunities.py::test_SPT_A_21_get_list_by_state_and_conditional_transition | PASS (unit) |
| SPT-A-22 | test_spt_a_opportunities.py::test_SPT_A_22_strong_long_positional_fresh_liquid_bullish_is_qualified | PASS (unit) |
| SPT-A-23 | test_spt_a_opportunities.py::test_SPT_A_23_risk_off_regime_is_conditional | PASS (unit) |
| SPT-A-24 | test_spt_a_opportunities.py::test_SPT_A_24_illiquid_is_rejected_and_keeps_its_window | PASS (unit) |
| SPT-A-25 | test_spt_a_opportunities.py::test_SPT_A_25_data_provider_down_or_stale_is_data_insufficient_then_recovers | PASS (unit) |
| SPT-A-26 | test_spt_a_opportunities.py::test_SPT_A_26_not_qualifiable_tonight_is_watchlist | PASS (unit) |
| SPT-A-27 | test_spt_a_opportunities.py::test_SPT_A_27_score_counts_distinct_families_and_is_not_a_probability | PASS (unit) |
| SPT-A-28 | test_spt_a_opportunities.py::test_SPT_A_28_a_bonus_jump_does_not_corrupt_the_indicators | PASS (unit) |
| SPT-A-29 | test_spt_a_opportunities.py::test_SPT_A_29_expiry_window_ended_and_close_below_stop | PASS (unit) |
| SPT-A-30 | test_spt_a_opportunities.py::test_SPT_A_30_conflicting_signals_make_it_conditional | PASS (unit) |
| SPT-A-31 | test_spt_a_opportunities.py::test_SPT_A_31_flag_and_max_per_round<br>test_spt_a_opportunities.py::test_SPT_A_31_a_round_runs_every_step_once_per_leader<br>test_spt_a_opportunities.py::test_SPT_A_31_a_failing_step_is_recorded_and_the_round_goes_on<br>test_spt_a_opportunities.py::test_SPT_A_31_the_evening_round_runs_the_outcomes_step<br>test_spt_a_opportunities.py::test_SPT_A_31_a_worker_that_loses_the_lock_mid_round_stops | PASS (unit) |
| SPT-A-32 | test_spt_a_api.py::test_SPT_A_32_every_route_needs_a_session | PASS (unit) |
| SPT-A-33 | test_spt_a_api.py::test_SPT_A_33_signals_list_filters_and_limits | PASS (unit) |
| SPT-A-34 | test_spt_a_api.py::test_SPT_A_34_opportunities_list_get_and_revalidate | PASS (unit) |
| SPT-A-35 | test_spt_a_api.py::test_SPT_A_35_backfill_dry_run_writes_nothing_and_write_is_idempotent<br>test_spt_a_api.py::test_SPT_A_35_backfill_bad_arguments | PASS (unit) |
| SPT-A-36 | test_spt_a_outcomes.py::test_SPT_A_36_forward_returns_mfe_mae_by_hand | PASS (unit) |
| SPT-A-37 | test_spt_a_outcomes.py::test_SPT_A_37_target_1_first_then_target_2<br>test_spt_a_outcomes.py::test_SPT_A_37_target_and_stop_in_one_session_counts_the_stop<br>test_spt_a_outcomes.py::test_SPT_A_37_detection_day_close_below_the_stop_and_a_gap<br>test_spt_a_outcomes.py::test_SPT_A_37_trend_exit_time_exit_and_open | PASS (unit) |
| SPT-A-38 | test_spt_a_outcomes.py::test_SPT_A_38_a_bonus_after_the_signal_ends_the_measurement<br>test_spt_a_outcomes.py::test_SPT_A_38_the_plans_trend_average_never_spans_a_bonus_and_a_split_without_a_signal_day_bar | PASS (unit) |
| SPT-A-39 | test_spt_a_outcomes.py::test_SPT_A_39_fade_from_the_days_scores | PASS (unit) |
| SPT-A-40 | test_spt_a_outcomes.py::test_SPT_A_40_outcomes_are_stored_by_signal_apart_from_trades<br>test_spt_a_outcomes.py::test_SPT_A_40_analytics_groups_with_sample_sizes | PASS (unit) |
| SPT-A-41 | test_spt_a_outcomes.py::test_SPT_A_41_evening_run_waits_for_the_nse_file_and_runs_once | PASS (unit) |
| extra | test_spt_a_opportunities.py::test_validation_never_left_in_validating<br>test_spt_a_opportunities.py::test_a_validation_stuck_in_validating_is_resumed_after_five_minutes<br>test_spt_a_opportunities.py::test_evidence_that_arrives_during_a_validation_is_not_lost<br>test_spt_a_outcomes.py::test_bars_are_read_once_per_symbol_and_the_cache_is_bounded<br>test_spt_a_signals.py::test_clock_windows | PASS (unit) |

Also checked offline (not a test in the suite): the fixture's 4 Nov signals through ingest → consolidate → validate →
outcomes on REAL NSE bars and the real desk regime copied read-only from staging on 5 Nov ~02:30 IST: HDFCAMC (its
2025-11-26 bonus break found and cut) and VINCOFE QUALIFIED, the four without a strong signal WATCHLIST; and a dry run of
`scripts/spt_backfill_signals.py` on the whole 4 Nov dump: 2,367 events, 1,807 normalized (all positional), 560 intraday
marks quarantined `stale` (read the next day), 996 opportunity groups, all 86 strong signals scored.

UNVERIFIED: nothing here ran against staging Mongo/Redis (no staging writes were allowed). The integrator's staging run is
the verification of the real unique index, the Redis hand-off and the loop under the real scan.
