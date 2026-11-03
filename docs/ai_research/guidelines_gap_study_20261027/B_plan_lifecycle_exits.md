# Study B — Trade plan, lifecycle, exits and the decision card

PRD: `docs/NIVESH_AI_LAB_TRADING_DECISION_GUIDELINES.md` (453 lines; §4 entry, §5 stops, §7 exits, §9 options, §10 lifecycle, §14 decision card).
Code read: clean worktree `/home/deploy/nivesh-idea-levels` at `5b6b3cfd` (= origin/dev). Paths below are relative to it.
Excluded as unshipped draft: the uncommitted `FnoLevels.tsx` edit (LevelsCard→LevelsView) and the untracked `IdeaLevels.tsx`; every FnoLevels citation below is the COMMITTED version (`git show HEAD:...`).
Staging: read-only queries (Mongo `nivesh_staging` and app Postgres through the backend container's own client; NIDP via `nidp-psql.sh`). Nothing was written, restarted or deployed. Pure-function probes ran in throw-away `--network none` containers with the worktree mounted read-only. Probe scripts: `docs/ai_research/guidelines_gap_study_20261027/probe/`.

Status words: VERIFIED = proven this session by code citation and/or real output shown here. UNVERIFIED = stated with the reason.

---

## 0. The outside reviewer's claims — verdicts

| Claim | Verdict | Key evidence |
|---|---|---|
| ATR trailing exits exist only in the backtest engine, not in desk paper trades | **CONFIRMED** | Only `services/strategy_engine/backtest.py:307-314` trails. No "trail" logic in any other service (grep). Desk cash rules `desk_trading.py:537-638`, strategy rules `desk_strategy_trades.py:554-586`: stop/target/time/expiry/manual only. All 3 staging backtests used `trailing_atr_mult` 2–2.5 (query §4c). |
| No moving-average/trend exit in paper trades | **CONFIRMED** | No MA exit anywhere. The journal's "Trail rest using 5 EMA / swing low" is display text with `trigger_price: None` (`routes/positional_journal.py:148`). The plan's "a close back below the trigger … cancels it" is text in `failure_conditions` (`strategy_plan/plan.py:312-323`), never evaluated. |
| No time exit in paper trades | **REFUTED in code, CONFIRMED in practice** | Cash paper trades implement `max_hold_sessions` → exit "time" at that session's close (`desk_trading.py:633-634`); strategy trades too (`desk_strategy_trades.py` EXIT_TEXT "time"). But no surface except the Strategy Builder's F&O path sends it: Top 10 / AI watchlist / Scanner bodies omit it, the plan's cash body omits it (`plan-data.ts:275-288`), the AI Trader drops the strategy's `max_hold_days` (`ai_trader/execution.py:266-280`). Staging: **0 of 9** paper trades have it (query §4a). |
| No unified lifecycle candidate → plan → risk decision → paper trade; no NO_SETUP…CLOSED/REJECTED state machine with per-transition audit | **CONFIRMED (one partial exception)** | Six stores with six status vocabularies (§3). Only the AI Trader path links ticket → trade (`ticket.trade_id`, trade stamped with `risk_decision_id`). Top 10 / watchlist / scanner paper trades carry `source {kind, bucket, signal_date}` only — no plan id, idea id or candidate id. The plan's own lifecycle is declared but never moves (`plan.py:32`: `"status": "draft"`; `paper_traded` occurs nowhere else). |
| Strategy Builder shows many details but Top 10 rows and AI watchlist rows show no entry/stop/target | **PARTLY REFUTED** | AI watchlist cash rows DO show "Scanner levels: entry · stop · target" in the row (`AiScannerWatchlist.tsx:155-157`). Top 10 stock rows show them only after "Paper trade" is expanded (`ScannerTop10.tsx:76-99`). F&O rows on both boards show no stop/target (only max loss, R:R, premiums). |
| R-multiple labels, stop method, % of portfolio, costs and an exit-plan block are missing from the decision card | **MOSTLY CONFIRMED** | No surface labels any target in R (grep for "R multiple"/"r_multiple": none). Stop method/rationale is shown only in the Strategy Builder (and there it is mislabelled, §2). Risk as % of portfolio is not computed anywhere. Costs: Builder + paper record only. Exit-plan block: only the lab builder's committed LevelsCard (options), display-only. |
| Breakdown/short setups absent (long-only) | **CONFIRMED for setups and cash; REFUTED for F&O structures** | Scanner buckets/stages are all long (`setup_rules.py:31-46`, `trade_planner.py:49-63`); cash plans and cash paper trades are long-only (`candidates.py:204-210`, `desk_trading.py:322-323`, `desk_strategy_trades.py:163-164`). Bearish F&O structures exist, but their direction comes from the **market regime**, not an instrument breakdown trigger (`regime_fit.py:142-145`). |

---

## 1. PRD rule → status table

Severity: Critical / High / Medium / Low (impact on the honesty of paper results and on the user's decision).

| # | PRD rule | Status | Evidence (file:line / data) | Sev. |
|---|---|---|---|---|
| 1 | §4 Breakout: defined level, trigger, volume confirmation, no chasing a gap | Partial | Scanner gates: `setup_rules.py:35-41` (dist 0–3 %, vol spike ≥1.5×, gap ≤5 %); entry = max(close, 20d high×1.001) `trade_planner.py:51-53`; plan entry logic text "a close above the trigger on volume confirms it" `candidates.py:300`. But Top 10 / watchlist / scanner paper trades are recorded `at_once` (no trigger) — see B3 | High |
| 2 | §4 Pullback: wait for a reversal trigger, stop below structure | Contradicts (paper layer) | `trend_continuation` bucket `setup_rules.py:44-45`; ACCUMULATION entry = swing_low×1.01 (a pullback/limit) `trade_planner.py:54-61`; but recorded `at_once` → booked at a price 8–11 % below the market (FEDERALBNK/SGMART/KOTAKBANK on 26 Oct, probe B3) | High |
| 3 | §4 Momentum continuation | Partial | No separate rule; nearest = `trend_continuation` / BREAKOUT-at-close | Low |
| 4 | §4 Breakdown / short setup | Missing (setups) / Partial (F&O) | see §0; bearish structures are regime-driven `regime_fit.py:142-145` | Medium |
| 5 | §4 Define invalidation before the order | Partial | Every cash generator emits a stop; Top-by-regime F&O ideas carry none by design (`top-actions.ts:62-64`) | Medium |
| 6 | §5 Structural stop, labelled | Partial | Considered but overridden: `trade_planner.py:69-73` takes `max(swing_low×0.995, entry−1.5 ATR)`; method never stored in `positional_signals`. Chart engine stores `stop_basis` atr/support20 (`routes/research_chart.py:396-401`); TPD stores `stop_method` (`paper_trades_live.py:54-64`) | Medium |
| 7 | §5 ATR stop, multiplier tested | Partial | Five different multipliers: scanner watchlist 1.5 (`setup_rules.py:49`), picks 1.5 (`trade_planner.py:72`), plan/chart 2.0 (`rules.py:44`, `research_chart.py:373`), TPD k·ATR, AI Trader/backtest a **fixed %** stop (`ai_trader/execution.py:150`, `strategy_engine/backtest.py:202`) | Medium |
| 8 | §5 Plan's stop label = actual method | **Contradicts** | Plan labels the scanner stop "2 x ATR below the trigger/EMA20" (`candidates.py:242` + `rules.py:44`); the real stop is 1.5 ATR (ICICIBANK 26 Oct: distance/ATR = **1.5**, probe §2b) | Medium |
| 9 | §5 Capital-risk sizing `qty = floor(risk/R)` | Partial | Implemented in plan `size_position` (`candidates.py:90-122`) and AI Trader (`execution.py:154`). Top 10 / watchlist / scanner: user types qty; the plan-sized default is null when no capital is given — **10 of 10** rows on 26 Oct have `sized_shares: None` (query §1c) | High |
| 10 | §5 Include fees, taxes, spread, slippage | Partial | One model everywhere: 5 bps/side + ₹20/side (`backtest.py:76-77`); payoff lists exclusions "taxes, STT, exchange and statutory charges, dividends, funding" (`payoff.py:29-30`). Real Zerodha charges (STT, exchange, SEBI, stamp, GST, brokerage) only for F&O baskets in the lab margin card (`fno_margin.py:84-96`). No spread estimate (no bid/ask in EOD) | Medium |
| 11 | §5 Never widen a stop after entry | Implemented | No update route for paper trades (`routes/desk_trading.py` endpoints); strategy trades immutable with `entry_record_hash` (`desk_strategy_trades.py:269-274`) | — |
| 12 | §5 Gap-through-stop fills worse | Implemented (paper) / **Contradicts (backtest)** | Desk cash: fill at the open (`desk_trading.py:620-621`; staging HAL exits at 4790 vs stop 4822.25, flag `gap_through_stop`). DSL backtest fills at the stop (`backtest.py:318-320`, probe §5: 970 on a 920–940 bar) | Medium |
| 13 | §7 Exits defined before entry | Partial | Cash paper: stop/target/(time) at open; F&O idea trades: none (B1); plan F&O trades: underlying stop/target + horizon | High |
| 14 | §7 Fixed-R targets | Partial | Plan base = 2× stop distance, optimistic = 3× (`candidates.py:56-85`, rule text only); picks fall back to 2R (`trade_planner.py:88-98`); AI Trader `target_rr`. Never labelled "R"; no card shows R multiples | Medium |
| 15 | §7 Partial exits only if tested | Missing (desk) | Close-all only; the journal takes manual staged EXIT fills (`positional_journal.py:206-255`) | Low |
| 16 | §7 ATR trailing stop, never loosened | Missing (paper) / Implemented (backtest) | Backtest never loosens (`backtest.py:307-314`, probe §5) but trails with the same bar's high before checking its low (look-ahead), ATR fixed at entry, exits reported as STOPLOSS | High |
| 17 | §7 Trend / MA exit | Missing | see §0 | Medium |
| 18 | §7 Time exit | Partial (implemented, unused) | see §0; backtest counts **calendar** days (`backtest.py:305`), paper counts sessions | High |
| 19 | §7 No averaging down / no re-entry without a new setup | Missing guard | Identical trades accepted: HAL ×3, ICICIBANK ×2 with identical levels on staging (query §4a); POST has no idempotency key | Medium |
| 20 | §9 Options exit on the combined position | Partial | `strategy_levels.py` (v2) computes a combined premium stop (70 % of debit kept / credit + 50 % of max loss), T1/T2, underlying thesis levels, Greek review rule, expiry-week flag (`strategy_levels.py:14-16, 96-150, 168-170`) — **display only** (FnoBuilder/FnoCompare); nothing after entry reads it (grep). Strategy paper exits: underlying touch, expiry, time, manual | High |
| 21 | §9 No single-leg stops | Implemented | Strategy exits are structure-level; LevelsCard says legs are "monitoring, not separate trades" (`FnoLevels.tsx@HEAD:148`) | — |
| 22 | §10 One state machine, one trade id | Missing / Partial | §3 mapping | High |
| 23 | §10 Per-transition audit record | Partial | Strategy trades store `events[]`, signal, rule version, hash (`desk_strategy_trades.py:355-361, 684-706`); cash trades' events are **derived on read**, not stored (`routes/desk_trading.py:356-366`); plan lifecycle never transitions | Medium |
| 24 | §10/§11 Idempotent, retry-safe | Partial | Exits: status in the update filter (`desk_trading.py:731`, `desk_strategy_trades.py:710`). AI Trader tickets: unique index + DuplicateKeyError (`routes/ai_trader.py:633-690`). Opening a paper trade: no idempotency key | Medium |
| 25 | §14 Decision card on every candidate | Partial | §6 matrix | High |

### Defects found on the way (all VERIFIED)

| ID | Defect | Evidence | Sev. |
|---|---|---|---|
| B1 | **Every F&O idea "Paper trade" button is refused by the backend.** `paperTradeBodyFor` sends no `signal`; `new_strategy_trade` requires it → 422 `invalid_signal`. Affects Top-by-regime, Top 10 F&O rows, lab focus, AI watchlist F&O rows (all use `IdeaActions`). The e2e test mocks the route to 201, so it passes | `top-actions.ts:65-88`; `desk_strategy_trades.py:226-228, 318`; `e2e/tests/copilot-app-desk-strategy-top.spec.ts:209-227`; probe §7a; staging: 0 strategy trades with the "Top by regime" note | High |
| B2 | Gross P&L of a closed trade uses the reference entry, not the simulated fill, when a conditional entry gapped: ₹1,000 booked vs ₹600 at the fill; the paper account is credited the overstated net. An OPEN trade's P&L uses the fill, so the figure jumps at close | `desk_trading.py:697-699, 714-715` vs `:860-862`; probe §7b | Medium–High |
| B3 | `at_once` recorded at stale or non-current scanner entries. ACCUMULATION entries are swing_low×1.01 (pullback limits), but Top 10 / watchlist / scanner send no `entry_rule` → booked as if filled. FEDERALBNK 26 Oct: entry 316.89 vs close 344.40 → ₹3,861 booked vs ₹1,110 for a real buyer; only a flag `entry_outside_day_range` | `ScannerTop10.tsx:83-86`, `AiScannerWatchlist.tsx:91-93`, `ScannerTab.tsx:724-726`; `desk_trading.py:554-563`; probe §7c | High |
| B4 | Plan stop label wrong (2× vs actual 1.5× ATR) | row 8 | Medium |
| B5 | Same instrument, same day, opposite directions: on the 26 Oct list UNIONBANK, COFORGE, LAURUSLABS, MPHASIS, FEDERALBNK are bullish cash ideas and bearish F&O ideas (bear put spread / long put, fit 92.5) | query §1d | High |
| B6 | The evening exit job is not installed on staging: `deploy/nivesh-staging/desk-alerts.cron` exists in the repo, but `/etc/cron.d` has no desk-alerts file and no log exists. Exits are written only when a user opens the paper-trade list | `ls /etc/cron.d` output §4b | Medium |
| B7 | AI Trader paper trades drop the strategy's `max_hold_days` (and `trailing_atr_mult` if the spec has it): the paper result is not the backtested strategy | `ai_trader/execution.py:266-280` | High |
| B8 | `positional_signals` is upserted `ON CONFLICT DO UPDATE`: a re-run silently rewrites the entry/stop/target a paper trade cited; no version | `positional_engine/pipeline.py:246-259` | Low–Medium |
| B9 | Scanner data staleness reaches trades: a NORTHARC paper trade opened 2026-10-19 carries `source.signal_date: 2026-01-22` (9 months old) with no guard (cross-area C) | query §4a | Medium |
| B10 | Stored AI watchlist rows drop `plan_id` (the ideas answer has it) | `ai_watchlist_build.py:47-65` | Medium |

---

## 2. Q1 — Every place entry/stop/target are computed

| # | Generator | Entry | Stop | Target | Stored? | Code |
|---|---|---|---|---|---|---|
| 1 | Positional engine picks (AI scanner) | BREAKOUT: close; EARLY_BREAKOUT: max(close, 20d high×1.001); ACCUMULATION: close or swing_low×1.01 | max(swing_low×0.995, entry−1.5 ATR) | nearest structural ≥1.8R else entry+2R; reject RR<1.5 | Postgres `positional_signals` (upsert) | `positional_engine/trade_planner.py:22-135`, `pipeline.py:238-259` |
| 2 | Scanner watchlist buckets | trigger = breakout level | ref − 1.5 ATR (ref = breakout level / close / EMA20 by bucket) | none | not stored (computed per GET) | `routes/positional.py:374-430` |
| 3 | Merge for the desk (Top 10, ideas) | pick entry else watchlist trigger | pick stop else watchlist stop | pick target | in the response; AI watchlist stores it | `strategy_plan/selection.py:95-147, 180-189` |
| 4 | Strategy plan (Builder, and each idea's plan) cash | **last close** | pick/watchlist stop, else chart engine ATR stop | conservative / base 2R / optimistic 3R | only if the user saves (`desk_strategy_plans`) | `strategy_plan/candidates.py:203-322`, `sources.py:222-239` |
| 5 | Strategy plan futures / options / combos | futures price / premiums | 2 ATR distance on underlying, walls | walls / expected move / R multiples | as 4 | `candidates.py:359-402, 662-760, 894-1020` |
| 6 | Chart engine hypothetical (ATR_2X_STOP) | last close | entry−2 ATR or 20d support | entry+2R | no | `routes/research_chart.py:371-412` |
| 7 | Reversal candidates | trigger | 10-session low − 0.5 ATR | resistance | no | `positional_engine/reversal_rules.py:57-60, 271-290` |
| 8 | AI Trader intents | candidate close | entry×(1−stoploss_pct) | entry + target_rr×R | `ai_trader_tickets` | `ai_trader/execution.py:107-158` |
| 9 | DSL backtest | close×(1+slip) | entry×(1−stoploss_pct), trailed | entry + target_rr×R | Postgres `strategy_trades` | `strategy_engine/backtest.py:189-231` |
| 10 | F&O levels v2 (lab) | net debit/credit | premium stop + underlying thesis stop | T1/T2 premium + underlying | no | `services/strategy_levels.py` |
| 11 | F&O lab "Paper strategies" | close | put wall / edge of expected move | call wall | no — **computed in the browser** | `FnoStrategies.tsx:1-36, 280-330` (header still says "paper trades hold shares only", outdated since desk-paper-v3) |
| 12 | Regime-fit board (Top 10 F&O) | leg premiums | none | none (max gain / max loss) | AI watchlist stores it | `strategy_plan/regime_fit.py` |
| 13 | Ten-Percent Days paper (NIDP, out of repo) | official open | entry − k·ATR or support, cap 8 %, `stop_method` | entry×(1+t %) | NIDP | mirrored in `paper_trades_live.py:54-64` |

**No canonical plan object.** The closest is the StrategyPlan (content-addressed `plan_id`, rules/calculation versions, snapshot hashes, `plan.py:427-456`), but the Top 10 / watchlist / scanner paper trades record generator #3's levels, not the plan's.

### 2b. Real disagreement, one instrument (ICICIBANK, 26 Oct) — VERIFIED

Query (staging app Postgres, SELECT only) and the shipped functions applied to the stored features (`probe/q4.py`, `probe/q5.py`):

```
{'nse_symbol': 'ICICIBANK', 'signal_date': datetime.date(2026, 10, 26), 'stage': 'EARLY_BREAKOUT', 'entry_price': Decimal('1413.2100'), 'stoploss': Decimal('1375.1600'), 'target_price': Decimal('1489.3100'), 'risk_reward': Decimal('2.00'), 'engine_version': 'positional.v1.0'}
features: {'close': 1403.0, 'atr_14': 25.36709576770533, ... 'high_20d': 1411.8, 'swing_low_20': 1291.0, 'swing_high_20': 1411.8, 'high_52w': 1480.0, ...} | stage: EARLY_BREAKOUT | resistance_level: 1411.8000
trade_planner.plan -> {'entry': 1413.21, 'stoploss': 1375.16, 'target': 1489.31, 'risk_reward': 2.0, 'timeframe_days_min': 5, 'timeframe_days_max': 15}
pick stop distance / ATR = 1.5  | entry-1.5ATR = 1375.16  swing_low*0.995 = 1284.55
plan stop_basis label says: 2 x ATR below the trigger/EMA20 | watchlist rule stop_atr_multiple: 1.5
strategy-plan cash candidate levels (entry = last close, stop = the pick's stop): [{'name': 'conservative', 'price': 1428.37, ...}, {'name': 'base', 'price': 1458.68, 'rule': '2 x the stop distance', 'gate': True}, {'name': 'optimistic', 'price': 1486.52, 'rule': '3 x the stop distance', 'gate': False}]
```
Stored 26 Oct AI watchlist row (Mongo, `probe/q3.py`):
```
 CASH 1 ICICIBANK bucket pre_breakout close 1403.0 2026-10-26 | scanner entry 1413.21 stop 1375.16 target 1489.31 rr 2.0 | plan plan | pref futures:long_buildup_continuation Long futures: build-up with cash confirmation max_loss -6902.94 rr_net 5.8 | sized None
```
So for one stock on one day: the watchlist row and its "Paper trade" button use 1413.21 / 1375.16 / 1489.31 (structural 52w-high rejected, 2R fallback); the "Strategy ›" plan's cash candidate uses 1403.00 / 1375.16 / 1458.68 (base) and labels the stop "2 x ATR" though it is 1.5 ATR; the row's "Strategy that fits" shows a long-futures max loss of ₹6,902.94 — a third instrument and risk figure. The stored row agrees with `positional_signals` (no recompute there). UNVERIFIED: the plan levels come from running the shipped `scenario_levels` on real inputs, not from a live `POST /plan` response (not called, to keep the study read-only).

### 2c/1d. Direction disagreement on the same list (VERIFIED, `probe/q6.py`)
```
regime: {'available': True, 'key': 'bearish', 'label': 'Bearish', 'as_of': '2026-10-23', 'trend': 'down', 'india_vix': 16.86, ...}
UNIONBANK | cash board: bullish pre_breakout plan plan | F&O board: bear_put_spread view down fit 92.5
COFORGE | cash board: bullish pre_breakout plan plan | F&O board: long_put view down fit 92.5
LAURUSLABS | cash board: bullish trend_continuation plan no_trade | F&O board: bear_put_spread view down fit 92.5
MPHASIS | cash board: bullish None plan no_trade | F&O board: bear_put_spread view down fit 92.5
FEDERALBNK | cash board: bullish None plan no_trade | F&O board: bear_put_spread view down fit 92.5
```
(Cross-area C: the regime used for the 26 Oct list is dated 23 Oct.)

---

## 3. Q2 — Stop methods, R multiples, costs

* Structural: computed in #1 (swing low, then discarded when the ATR stop is tighter), #6 (`stop_basis: support20`), #7, #13. Labelled as a machine field only in #6 and #13.
* ATR: #1/#2 1.5×, #4/#5/#6 2×, #13 k×. Labelled in the plan by free text (`invalidation.technical.basis`, `candidates.py:301`) — wrong for the scanner stop (B4).
* Capital-risk: sizing exists in the plan and the AI Trader, not on the boards (row 9).
* Invalidation rationale: plan only (`"meaning": "the thesis is wrong if price closes beyond this level"`, plus a separate "execution stop" with the gap caveat, `candidates.py:301-302`).
* R multiples: implicit only (rule text "2 x the stop distance"); no numeric `r_multiple` anywhere.
* Cost models found: (1) `strategy_engine/backtest.py:76-77` 5 bps + ₹20 per side — reused by the desk paper trades (snapshotted per trade, `desk_trading.py:121-126`) and the payoff engine (`payoff.py:24-30, 85-95`, with an explicit "excluded" list); (2) `fno_margin.py` Zerodha basket charges (brokerage, STT, exchange, SEBI, stamp, GST) for F&O baskets in the lab, needs the platform Kite session; (3) `reversal_backtest.py:40-42` 0.35 % / 0.60 % round trip; (4) TPD 0.25 % round trip (`paper_trades_live.py:39`). No cash-equity STT/stamp/GST and no spread estimate in any plan.

---

## 4. Q3 — Paper-trade data models and state mapping

| Store | Kind | Status values | Levels | Size | Exit | Version / provenance | Link to source |
|---|---|---|---|---|---|---|---|
| Mongo `desk_paper_trades` (cash) | user/AI Trader | `open`/`closed`; `entry_status` assumed/reached/waiting/not_reached | entry, stop, target | quantity | exit_reason stop/target/time/manual/entry_not_reached/cancelled, exit_price, exit_session, flags, MFE/MAE, costs, net | rules_version desk-paper-v2, cost_model, strategy_version, signal_at, rationale, risk ids (gate on) | `source {kind, bucket, signal_date}` only |
| same, `kind: strategy` | F&O | `open`/`closed` + stored `events[]` (created, entered, exit_rule_fired, closed) | stop_underlying, target_underlying, legs[] entry premiums | lots×lot_size | stop/target/expiry/time/manual | desk-paper-v3, signal{signal_at, rule_version, model_version, source_refs, evidence}, entry_record_hash | `strategy_plan_id` (dangling if the plan is deleted) |
| Mongo `ai_trader_tickets` | AI Trader | awaiting_confirmation, confirmed, executed_paper, rejected (by governor/desk/user), expired | entry, stop, target | requested/approved qty | via trade | strategy_id/name/version, decision, reason codes | `trade_id` → desk trade (one way) |
| Mongo `ai_trader_strategies.runs[]` | backtest runs | stage draft/backtested/paper/assisted | spec.exit | — | — | version | — |
| Mongo `desk_strategy_plans` | saved plans | plan.status plan/wait/no_trade/insufficient_data; lifecycle.status **always "draft"** | per candidate | sizing | — | plan_id hash, rules/calc version | — |
| Mongo `trade_journal` | manual journal | OPEN/CLOSED/STOPPED (close not status-filtered) | stop_loss, target | fills | manual | — | `plan_source`, `pick_signal_date` |
| Postgres `strategy_trades` | DSL backtest | — | entry, stoploss, target | qty | STOPLOSS/TARGET/TIME/BACKTEST_END | run_id | — |
| NIDP TPD paper | research | ENTRY_UNAVAILABLE, SUSPENDED, DATA_ERROR, CANCELLED_BY_RULE, exits TARGET_STOP CLOSED | entry, stop (+method), targets | — | target/stop/horizon | rules_v1 | prediction_date |

Mapping onto the PRD state machine:

| PRD state | Where it exists today |
|---|---|
| NO_SETUP | not persisted (scanner gate fail; plan `insufficient_data`/`no_trade`) |
| WAIT_FOR_CONFIRMATION | plan `wait`; cash trade `entry_status: waiting` (break_above/pullback_to) |
| TRADE_ELIGIBLE | plan `plan` + candidate `candidate`; ticket `awaiting_confirmation` |
| REJECTED | ticket `rejected` + `risk_decisions`; plan `no_trade`; a refused POST is not stored unless the risk gate is on |
| ENTRY_TRIGGERED | implicit: `entry_session` set; ticket `confirmed` (transient) |
| POSITION_OPEN | `status: open` with entry reached/assumed; ticket `executed_paper` |
| EXIT_PENDING | `pending_exit` computed on GET detail, never stored |
| CLOSED | `status: closed` + exit_reason |

Traceability: only the AI Trader path (ticket → trade_id; trade has `risk_decision_id`/`correlation_id`) and the Builder's F&O path (`strategy_plan_id`) link back. Top 10 / watchlist / scanner trades can only be matched heuristically to `positional_signals` by (symbol, signal_date), and that row can be rewritten (B8).

### 4a. Staging data (VERIFIED, `probe/q1.py`, `probe/q2.py`)
```
desk_paper_trades exists 9
ai_trader_tickets exists 0
ai_trader_strategies exists 2
desk_strategy_plans MISSING
trade_journal MISSING
(kind, status, exit_reason) -> [(('cash', 'closed', 'stop'), 4), (('cash', 'open', None), 2), (('cash', 'closed', 'manual'), 2), (('strategy', 'closed', 'manual'), 1)]
source.kind: [('scanner', 6), (None, 3)]
rules_version: [('desk-paper-v2', 8), ('desk-paper-v3', 1)]
entry_rule: [('at_once', 9)]
max_hold_sessions set: 0 of 9
strategy_version set: 0 | risk_decision_id set: 1
strategy trades: 1 with plan id: 0 with stop_underlying: 0 with note 'Top by regime': 0
distinct users with trades: 1
ai_trader_strategies: 2 stages: [('draft', 1), ('backtested', 1)] runs total: 3
spec.exit keys seen: [(('max_hold_days', 'stoploss_pct', 'target_rr'), 2)]
```
Trades (excerpt): NORTHARC opened 2026-10-19 with `source.signal_date: '2026-01-22'`, stop exit; three identical HAL trades (entry 4989.0 stop 4822.25 target 5322.51) each closed `stop` at **4790.0** on 2026-10-22 with flag `gap_through_stop` (third also `entry_outside_day_range`); two identical open ICICIBANK trades (1400.2 / 1363.26 / 1474.07).

### 4b. Is anything left open that should have exited? (VERIFIED: no)
NIDP bars (SELECT only):
```
 HAL       | 2026-10-21 | EQ |  4948.8000 |  4969.2000 | 4825.0000 |   4854.4000
 HAL       | 2026-10-22 | EQ |  4790.0000 |  4901.9000 | 4765.2000 |   4875.0000
 ICICIBANK | 2026-10-21 | EQ |  1406.0000 |  1409.7000 | 1383.0000 |   1385.0000
 ICICIBANK | 2026-10-22 | EQ |  1379.0000 |  1400.0000 | 1375.1000 |   1398.5000
 ICICIBANK | 2026-10-23 | EQ |  1404.5000 |  1404.5000 | 1377.9000 |   1394.2000
 ICICIBANK | 2026-10-26 | EQ |  1394.2000 |  1403.9000 | 1378.7000 |   1403.0000
```
ICICIBANK lowest low since entry 1375.10 > stop 1363.26; highest high 1409.70 < target 1474.07 → both open trades are correctly open. HAL: 10-21 low 4825 > stop; 10-22 opened at 4790 < stop → fill at the open is the correct conservative rule.
Exit job: `ls /etc/cron.d` → `nivesh-staging-ai-watchlist, -cache-clear, -db-snapshot, -positional-engine, -research-watchlist` (no desk-alerts); root crontab: `no crontab for root`.

### 4c. Backtest runs on staging (VERIFIED, `probe/q7.py`, `probe/q8.py`)
```
e082cb08 exit: {'target_rr': 2, 'stoploss_pct': 5, 'max_hold_days': 20, 'trailing_atr_mult': 2}
b0896898 exit: {'target_rr': 2.5, 'stoploss_pct': 6, 'max_hold_days': 30, 'trailing_atr_mult': 2.5}
f6417205 exit: {'target_rr': 2.5, 'stoploss_pct': 5, 'max_hold_days': 30, 'trailing_atr_mult': 2.5}
strategy_trades exit_reason: STOPLOSS 108, TIME 25, BACKTEST_END 12, TARGET 6
```
Trailed exits are reported as `STOPLOSS` — trailing and initial stops cannot be told apart.

---

## 5. Q4 — Exit evaluation for open paper trades

| Aspect | Cash (`desk_trading.py`) | Strategy (`desk_strategy_trades.py`) |
|---|---|---|
| Who runs it | `GET /api/desk/paper-trades` on every list read (`routes/desk_trading.py:172-186`) and `scripts/check_desk_alerts.py` (not scheduled on staging, B6) | same |
| Cadence / bars | EOD daily bars from `nidp.prices_eod` (raw), from the first session after the IST open date | underlying EOD bar; legs at bhavcopy settle/close |
| Intrabar vs close | daily high/low touch; both in one bar → stop (conservative) | underlying touch; legs closed at session marks, flagged |
| Live ticks | none (the Kite live feed is not read for exits) | none |
| After hours | nothing until the next bhavcopy is ingested | same |
| Trailing / trend | none | none |
| Time | `max_hold_sessions` (unused in practice) | `max_hold_sessions` (Builder F&O path only) |
| Expiry | n/a | settle at intrinsic on expiry |
| Gap through stop | fill at the open + flag | legs at session marks + flag |
| Partial exits | none | none |
| Idempotency | update filtered on `status: "open"` (`:731`) → a retry or a second tab cannot close twice | same (`:710`) |
| Exit audit | exit_reason, exit_session, exit_note, flags, checked_through; events derived on read | stored `events[]` |
| Read-side safety | the AI Trader's equity read deliberately does not apply exits (`routes/ai_trader.py:384-395`) → stale until a list read | same |

---

## 6. Q5 — Backtest exits (`services/strategy_engine/backtest.py`) — probe §5 output
```
day2 bar H1080 L1050 -> None stop now 1040.0
day3 bar H1060 L1045 -> None stop now 1040.0 (never loosened)
same-bar H1080 L1035 -> exit STOPLOSS at 1040.0 (assumes the high came before the low)
gap bar O930 H940 L920 (stop 970) -> exit STOPLOSS at 970.0
31 Jan (30 calendar days) -> exit TIME holding_days 30
```
* Never loosens: VERIFIED (`:307-314`). Matches PRD Example H (1080 − 2×20 = 1040).
* ATR: the entry day's `features.atr14`, rescaled to the adjusted basis, **fixed for the trade** (`:196-201, 237`). Known at decision time (entry is at that day's close), but never recalculated per bar; the PRD asks this to be specified.
* Bar ordering: the bar's own high raises the stop before the bar's low is tested → optimistic exit price when both happen inside one bar.
* Gap: fills at the stop (`:318-320`, "ignore for v1") — opposite of the desk paper rule.
* Time: calendar days (`:305`), paper uses sessions.
* No tests cover `trailing_atr_mult` (grep of `backend/tests`: none).
* Reuse: `_maybe_close_trade` cannot be reused as is (mutates a dataclass via `__dict__`, look-ahead, stop-fill on gaps, calendar days). Extract a shared pure bar-step function (Q8c) and use it in both.

Suites run this session (worktree mounted read-only):
```
python -m pytest tests/test_desk_trading.py tests/test_desk_paper_sim.py tests/test_desk_strategy_trades.py tests/test_strategy_levels.py tests/test_ai_trader_execution.py tests/test_strategy_backtest_sizing.py tests/test_strategy_engine.py tests/test_paper_account.py -q
327 passed, 3 warnings in 12.07s
```
(They pass while B1–B3 exist: the tests do not cover those cases.)

### 7. Probes for the defects
a) B1 (`probe/strat_body.py`):
```
REFUSED code = invalid_signal
WITH SIGNAL ACCEPTED open stop None target None max_hold None events ['created', 'entered']
```
b) B2 (`probe/gap_entry.py`):
```
entry_status reached | sim fill 104.0 | exit target 110.0 | flags ['entry_gap']
gross P&L close_trade books = realized_pnl(trade, exit) = 1000.0 | P&L from the simulated fill = 600.0
close_trade stored: realized_pnl_rs 1000.0 costs_rs 50.5 net 949.5 sim_entry_price 104.0
```
c) B3 (`probe/stale_entry.py`; the 27 Oct bar is HYPOTHETICAL, the 26 Oct bar is real):
```
entry_rule stored: at_once
entry_status assumed fill 316.89 | exit {'exit_reason': 'target', 'exit_price': 355.5, ...} | flags ['entry_outside_day_range']
gross booked: 3861.0 (a real buyer at the 26 Oct close 344.40 would have made 1110.0 )
same levels with entry_rule pullback_to -> entry_status waiting exit None
```

---

## 8. Q6 — Decision-card matrix

S = shown in the row/card · E = shown only after expanding a control · C = computed by the backend but not shown · A = absent.

| PRD §14 field | Strategy Builder card | Lab focus (IdeaCard) | Lab builder levels (FnoLevels@HEAD) | Desk Top 10 stock row | Top 10 F&O row | AI watchlist cash row | AI watchlist F&O row | Paper-trade detail |
|---|---|---|---|---|---|---|---|---|
| Setup + timeframe | S segment/direction/horizon sessions (`PlanSummary.tsx:63`) | S structure + expiry/days (`TopByRegime.tsx:172-174`) | S days to expiry, expiry-week flag | S bucket label; timeframe C (`horizon_days` sent, not shown) (`ScannerTop10.tsx:128`) | S structure + expiry (`:222-226`) | S bucket; timeframe C | S structure + expiry (`AiScannerWatchlist.tsx:237-240`) | S source kind/bucket via record; timeframe only if max_hold set |
| Status (watch/eligible/rejected/triggered/open/closed) | S plan + candidate pills | A (fit score only) | A | S plan pill (`:124`) | A | S plan pill (`:131`) | A | S open/closed + entry status (`PaperDesk.tsx:150`) |
| Entry trigger + order type | S trigger + logic text; order type A (`CandidateDetail.tsx:146-155`) | A (premiums only in payoff) | S net debit/credit "end-of-day closes" | E scanner entry; order type A (always at_once) | A | S scanner entry; order type A | S per-leg premiums (`:205`) | S entry rule + simulated fill (`PaperDesk.tsx:150-151`) |
| Stop price + method + rationale | S price + basis text + meaning + execution-stop caveat (label wrong, B4) (`:157-170`) | A | S strategy stop, thesis stop, boundary, "emergency stop: not built" (`FnoLevels.tsx@HEAD:125-136`) | E price only | A | S price only (`:155-157`) | A | S price; method A |
| Targets + R multiples | S 3 levels with rule text; R label A (`:172-184`) | A | S T1/T2 (premium %); R A | E target; R C (`risk_reward` sent, not shown) | A | S target; R C | A | S target; R A |
| Position size | S formula/qty or "incomplete" (`:202-221`) | A | S shares/lots in totals | E qty input, plan default C (null on 26 Oct) | A | E qty input (`sized_shares` null ×10) | S lots×size | S quantity |
| Rupee risk + % portfolio | S risk budget, risk at stop; % A | S max loss, capital at risk; % A | S planned stop loss ₹; % A | S max loss of the *preferred strategy* (not of the levels the button records); % A | S max loss, capital at risk; % A | S same as Top 10; % A | S max loss; % A | C (stop distance × qty, not shown); % A |
| Costs (spread, fees, taxes, slippage) | S round trip + "not included" list (`:225-231`) | C (in capital at risk; basis in a tooltip) | S round trip, entry, exit, basis (`@HEAD:194-200`) | A | A (tooltip basis only) | A | A | S est. costs at stop/target + model (`PaperDesk.tsx:154`) |
| Evidence | S evidence ledger, thesis, validation | S fit reasons ("Why") | S Greeks, scenarios | S score + setup only | E fit reasons (`:243-248`) | S score + setup | S Greeks, OI line | S rationale / signal (strategy) |
| Risks (event, liquidity, gap, concentration, correlation) | Partial: liquidity flags, conflicts, warnings; concentration/correlation A | A | S expiry-week flag | A | A | A | A | S rule flags after the fact (gap, outside range) |
| Exit plan (stop, target, trailing, time, emergency) | Partial: failure conditions + horizon; trailing/time rule A | A | S stop table + Greek review rule; trailing/time A | A | A | A | A | S exit rule text incl. time if set; trailing A |
| Audit (rule version, timestamps, explanation) | S rules + calc version, plan id, generated, sources (`PlanSummary.tsx:113`) | S price source, rules version on the board | S caveats, version C | Partial: scan date + ranking note; version A | Partial: chain date; version A | Partial: list date, days on list; version C (stored in notes) | Partial: list date; version C | S rules version, signal time, strategy version, events (strategy) |

---

## 9. Q7 — Options

* Combined-position exit is defined in `strategy_levels.compute` (premium stop/targets on the whole structure, underlying levels solved from the structure's own value, Greek review, expiry flag, scenario P&L) — VERIFIED `strategy_levels.py:96-170`.
* That stop is used nowhere after entry (grep: only the `/levels` route; the frontend only displays it in FnoBuilder/FnoCompare).
* Strategy paper trades exit on the **underlying** touch of `stop_underlying`/`target_underlying` (supplied only by the Builder, from `invalidation.technical` = a 2-ATR equity stop and the plan's base level, `plan-data.ts:249-271`), expiry settlement, `max_hold_sessions` (Builder passes `horizon_days`), or manual. No premium stop, no Greek rule, no theta/time rule beyond max hold.
* Ideas from the regime board carry no stop/target by design and cannot be recorded at all (B1).

---

## 10. Q8 — Recommendations

### (a) Canonical TradePlan (effort L; depends on nothing; unblocks c and d)
One backend function produces it; every surface reads it by id; nothing recomputes levels in a screen.

```
TradePlan {
  plan_id            "tp_" + digest(inputs, snapshot refs, rules_version)   # reuse plan.digest()
  rules_version, calculation_version, generated_at, data_as_of{price, fno, regime}
  instrument{symbol, segment cash|futures|options, legs[], lot_size, expiry}
  direction long|short|neutral, setup{family, bucket/stage, timeframe_sessions{min,max}, signal_at}
  entry{price, order_type at_close|stop_trigger|limit_pullback, valid_for_sessions, logic}
                     # maps 1:1 to the desk's at_once | break_above | pullback_to
  stop{price, method structural|atr|capital|premium|underlying, atr, atr_multiple, swing_ref, rationale, invalidation}
  R = |entry - stop| per unit
  targets[{name, price, r_multiple, rule}]
  size{qty|lots, risk_budget_rs, risk_rs, risk_pct_of_capital, binding}
  costs{model, entry_rs, exit_rs, round_trip_rs, excluded[]}
  exit_plan{stop, targets, trailing{atr_multiple, ref close|high, update bar_close} | null,
            time{max_sessions} | null, trend{ma, period} | null,
            options{premium_stop, t1, t2, greek_review, expiry_rule} | null}
  evidence_refs[], risk_flags[], status (state machine below)
}
```
Who computes it: extend `services/strategy_plan/candidates.py` (it already has invalidation + basis, target rules, sizing, costs, payoff, snapshot hashes). The positional engine (`trade_planner`) becomes a setup source (trigger, structural levels) feeding it, not a second level generator; `strategy_levels` supplies `exit_plan.options`. Where stored: insert-once Mongo `trade_plans` keyed by `plan_id` (or a per-candidate block inside `desk_strategy_plans`). The ideas route, `/top`, the AI watchlist job (store `plan_id` + snapshot), Top 10 rows, the Builder and the paper-trade POST all use `plan_id`. Fix B4/B5 inside it (method stored as data; one direction per instrument per day, with a "conflicts with the cash setup" flag on the F&O view).
Tests: cross-surface contract test — for one `plan_id`, ideas / top / watchlist / builder / paper responses carry byte-identical entry/stop/targets; staging data test — every `ai_watchlist_days.cash[*]` row's levels equal its TradePlan's; label test — `stop.method`/`atr_multiple` equals `(entry−stop)/ATR` within rounding.

### (b) Lifecycle state machine on existing stores (effort M; depends on a)
* Trade id = `plan_id` + candidate id, carried as `plan_ref{plan_id, candidate_id, rules_version}` on `desk_paper_trades` (cash and strategy) and on `ai_trader_tickets`.
* States as in §4 mapping; persist `state` and an append-only `transitions[]` (or a `trade_events` collection, unique `(trade_id, seq)`) written in the SAME conditional update that changes `status` (filter on the expected prior state). Each event: state from/to, at, session, rule version, signal and data timestamps, entry/stop/target/qty/est. costs, evidence ref, risk decision id or rejection reasons, fill price, slippage, exit reason.
* Minimal migration: add the fields (nullable); backfill cash events from stored fields exactly as `_cash_events` derives them; record a REJECTED event for every refused open (always call `rc.record_decision`, not only with the gate on).
* Idempotency: client `idempotency_key` per click, unique `(user_id, idempotency_key)`; a repeat returns the first trade (would have stopped HAL ×3 / ICICIBANK ×2).
* Make the plan's `lifecycle.status` derived from linked trades instead of the dead constant.
Tests: every transition writes exactly one event with all required fields; replaying a POST with the same key returns the same id and opens nothing; concurrent close + exit job → one close, one event.

### (c) Paper-trade exits, in order
1. **Fix B1, B2, B3 first (S each).** B1: `paperTradeBodyFor` sends `signal{signal_at: data_as_of.chain, rule_version: board rules_version, source_refs, evidence_summary}` plus the levels from `strategy_levels`; replace the mocked e2e with a backend contract test. B2: book gross/costs from `sim_entry_price`. B3: send `entry_rule` per stage (ACCUMULATION → pullback_to, EARLY_BREAKOUT → break_above, BREAKOUT → at_once) and refuse `at_once` when the entry lies outside the last session's range (`entry_not_tradable`). Tests: the three probes in §7 become unit tests with the corrected expectations.
2. **Install the evening job (S, ops)** from `deploy/nivesh-staging/desk-alerts.cron`; data test: `checked_through` of every open trade equals the latest `prices_eod` date the morning after.
3. **Wire time exits (S):** every surface sends `max_hold_sessions` (scanner `timeframe_days_max`, plan `horizon_days`); the AI Trader passes `spec.exit.max_hold_days`; switch the backtest to sessions. Test: AI Trader trade body contains it; backtest/paper parity on the same bars.
4. **ATR trailing for cash paper (M):** one pure function `step(state, bar, rules) -> (state', exit|None)` shared by the backtest and the paper simulator. Order inside a session: (i) gap rule on the open against the stop as it stood at the previous close; (ii) intrabar touch of that same stop; (iii) only after the bar, update the high-water mark with the close (or high, stated) and set `stop = max(stop, hw − k·ATR_t)`, ATR_t from bars up to t. Never loosen; store `stop_history[{session, stop, reason}]`; exit_reason `trailing_stop` distinct from `stop`. Idempotency: stop updates filtered on `{status: "open", stop_version: n}` → `n+1`; closes filtered on `status: "open"`. Then align the backtest's gap fill to the open. Tests: monotone stop property test; PRD Example H golden (1040); the "same-bar high then low" case must NOT exit at the raised stop; double-apply → one close; backtest/paper parity.
5. **Trend exit (M):** close below EMA-N at bar close, filled at the next open (stated). Golden tests on fixed bars.
6. **Options (M):** store `strategy_levels` premium stop/T1/T2 on the strategy trade and evaluate on EOD settle marks of the whole structure; Greek review as a flag event. Tests: debit spread hits 70 % value → `premium_stop`; neutral structure with no stop raises no premium exit.

### (d) What Top 10 / watchlist rows should show first (S–M, after a)
One line per row from the TradePlan: `Entry ₹x (break above | pullback to | at close) · Stop ₹y (1.5×ATR | swing low) · Targets ₹t1 (2R) ₹t2 (3R) · R ₹r/share · Size n (₹risk, p % of capital) · Est. costs ₹c · Horizon a–b sessions · signal age · plan id/rules`, a "levels are N % from the last close" warning when the entry is not tradable, and a badge when the F&O view conflicts with the cash setup. Tests: Playwright on staging (real route, not mocked) asserting the row numbers equal the Builder's for the same `plan_id`.

### Effort / dependency summary
B1 S · B2 S · B3 S–M · exit cron S · time exits S · trailing M (needs the shared step function) · trend M · options M (needs strategy_levels on trades) · lifecycle M (needs a) · canonical TradePlan L · row display S–M (needs a).

---

## 11. Cross-area notes (for studies A and C)
* A: only 1 of 9 staging paper trades carries a `risk_decision_id` (gate off for most opens); identical duplicate positions are accepted; the AI Trader governor's equity/drawdown read is stale until a list read applies exits.
* C: the 26 Oct list used a regime measured on 23 Oct; a trade was opened with a scanner `signal_date` of 2026-01-22; the chart engine prices on `prices_eod_adjusted` while paper trades use raw `prices_eod`; NIDP has no 2026-10-20 bar for ICICIBANK/HAL (holiday not verified).

## 12. UNVERIFIED
* The live `POST /api/desk/strategy/plan` answer for ICICIBANK was not called (read-only constraint); plan levels were derived by running the shipped pure function on real inputs.
* B1 was proven at the service layer and by the absence of such trades on staging; the button was not clicked on staging (that would write).
* The TPD paper engine lives on the research/NIDP side and was read only through its mirror in `paper_trades_live.py`.
