# Test cases — Phase 2.3–2.6 paper exits + Phase 4.1/4.5 deterministic examples and backtest integrity

Branch `feat/p2-exits-backtest` (off origin/dev 6a3ec2e3). Authored before implementation, after the API/UI design below.
Acceptance standard: `docs/NIVESH_AI_LAB_PHASE_SUCCESS_CRITERIA.md` §2.3, the Phase 2 exit gate, §4.1, §4.2.

## Design fixed before the tests

`services/exit_rules.py` — `step(state, bar, rules) -> (state', exit | None)`, pure, version `exit-rules-v1`.
Order inside one session t:
1. gap rule on the OPEN against the stop as it stood at the previous close (open through the stop → fill at the open);
2. a pending trend exit (set at the previous close) fills at the open;
3. intrabar touch of that SAME stop, or of the target (both in one bar → the stop: conservative); a target jump fills at
   the target (no credit for the better open: the desk FILL MODEL, pinned by tests/test_paper_fills_pnl.py);
4. time exit at the close of the session `max_hold_sessions` sessions held;
5. only after the bar: ATR_t (Wilder, bars up to t), high-water mark from the bar's HIGH, `stop = max(stop, hw − k·ATR_t)`
   (effective next session, never loosens, versioned history); trend check `close < EMA-N` → exit at the next open.
Exit reasons: `stop`, `trailing_stop`, `target`, `time`, `trend`, `expiry`, `manual`, `risk_control`.
ATR trailing (`trail-atr-v1`) and the EMA trend exit (`trend-ema-v1`) are opt-in research rules, off by default.

API additions (cash trade): `exit_rules[]` {code, version, label, params}, `exit_rules_version`, `stop_history[]`
{session, stop, reason, version}, `current_stop`, `stop_version`. Strategy trade: `premium_plan`, `exit_basis`,
`structure_value_per_unit`; option leg marks use `close_price` only.

## Test cases

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| TC-1 | exit_rules | intrabar touch of the stop | unit | `stop` at the stop level |
| TC-2 | exit_rules | open below the stop (gap) | unit | `stop` at the OPEN, gapped |
| TC-3 | exit_rules | high reaches target; open above target (jump) | unit | `target` at the target level both times |
| TC-4 | exit_rules | one bar touches stop and target | unit/edge | `stop` (conservative), both_in_range |
| TC-5 | exit_rules | time exit counted in sessions | unit | exits at the close of session N held |
| TC-6 | exit_rules | PRD Example H golden: entry 1000, stop 970, ATR 20, k 2, bar H1080 L1045 | unit | no exit, stop 1040 after the bar |
| TC-7 | exit_rules | same bar H1080 L1035 | unit/edge | NO exit at the raised stop on that bar; stop 1040 from the next session |
| TC-8 | exit_rules | random paths, long and short | property | stop never loosens; history versions strictly increase |
| TC-9 | exit_rules | exit at a raised stop vs the initial stop | unit | `trailing_stop` vs `stop` |
| TC-10 | exit_rules | opt-in rules disabled | property | identical exits to the always-on rules only |
| TC-11 | exit_rules | ATR per bar (Wilder, bars up to t); zero / missing ATR | unit/edge | trail uses ATR_t; no ATR → no trail move, flagged; never a stand-in ATR |
| TC-12 | exit_rules | close below EMA-N → next open; time exit on the same close wins | unit | `trend` at the next open |
| TC-13 | exit_rules | short side mirror (stop above, gap up) | unit | mirror of TC-1..TC-7 |
| TC-14 | exit_rules | invalid stop (≥ entry long), missing high/low, missing open | edge | ValueError / IncompleteBar / gap rule skipped and flagged |
| TC-20 | backtest | gap through stop | unit | STOPLOSS at the open (was: at the stop) |
| TC-21 | backtest | trailed exit | unit | TRAILING_STOP, not STOPLOSS |
| TC-22 | backtest | time exit | unit | sessions, not calendar days |
| TC-23 | backtest | next-open entry option; default labelled `signal_close` | unit | entry at the next open; metrics.entry_timing |
| TC-24 | backtest | new metrics on a hand-computed fixture | unit | expectancy ₹/R per trade and per session, payoff, Sharpe/Sortino, exposure, turnover, capital deployed, signals seen/taken, slippage sweep 0/5/10/20 bps |
| TC-25 | backtest | desk-cost-v2 card charges; flat model still selectable | unit | card statutory charges in pnl_abs; `desk-flat-v1` reproduces old arithmetic |
| TC-26 | backtest | persist_run | unit | snapshot_as_of + metrics.code_version written; an old run without them still reads |
| TC-27 | parity | backtest and paper simulator on the same bars | unit | same exit reason, session and pre-slippage price |
| TC-30 | paper cash | existing desk suites | regression | unchanged results |
| TC-31 | paper cash | opt-in ATR trailing on a paper trade | unit | stop history recorded; `trailing_stop` exit |
| TC-32 | paper cash | opt-in rules off | unit | trade identical to the same trade without the field |
| TC-33 | paper cash | stop update + close applied twice | unit/failure | one stop_version step, one close, one event |
| TC-34 | exit job | one close write fails | failure | other trades processed; failure counted in job_runs; next run retries and closes once |
| TC-35 | exit job | new reasons counted | unit | no KeyError on trailing_stop / trend |
| TC-40 | strategy | option marks | unit | close_price, never settle_price (expiry-day settle = underlying) |
| TC-41 | strategy | debit structure value ≤ premium stop | unit | `stop`, exit_basis `premium` |
| TC-42 | strategy | structure value ≥ T1 | unit | `target`, exit_basis `premium` |
| TC-43 | strategy | no stored premium plan / neutral structure | unit | today's rules only, no premium exit |
| TC-44 | strategy | Greek review threshold crossed | unit | flag + `greek_review` event, no exit |
| TC-50 | AI Trader | paper trade body | unit/contract | max_hold_sessions = spec.exit.max_hold_days; trailing ATR k = trailing_atr_mult; accepted by desk validator |
| TC-60 | 4.1 | PRD Examples A–H, parametrised | unit | real numbers asserted (A: 85 gross → 77 under desk-cost-v2) |
| TC-61 | 4.1 | missing prices, invalid stops, zero/stale ATR, minimum lot, gap fill, same-bar, monotone, parity | edge/property | as listed in the task |
| TC-70 | frontend | Top 10, AI watchlist, scanner, risk desk, plan (cash) bodies | e2e | `max_hold_sessions` sent from the scanner window / plan horizon |
| TC-71 | frontend | paper-trade detail | e2e | exit-reason label (trailing stop, trend), stop history, opt-in rule labels |
| TC-72 | frontend | strategy detail | e2e | option mark basis "close"; premium plan when stored |
| TC-80 | staging | replay the step function on real NIDP bars for the stored staging paper trades | data, read-only | live rules and the new function agree on every past exit, or each difference explained |
| TC-81 | safety | tests/test_order_path_guard.py | regression | passes |
| TC-82 | regression | full backend suite, branch vs origin/dev | regression | "fails on branch, passes on dev" list empty |
