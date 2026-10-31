# Phase 4.4: what stays out of scope, and what lifts each limit

**Status:** recorded 2026-10-27 on `feat/p4-research-hardening`. Criterion: `docs/NIVESH_AI_LAB_PHASE_SUCCESS_CRITERIA.md` 4.4.
Every code reference below was read in this branch. Every staging fact was checked read-only on 2026-10-27; the command is
given with it.

Nothing in this document enables a strategy. Each limit is lifted by a separate, reviewed change, after its preconditions
are shown with evidence.

---

## 1. Intraday strategies: out of scope

**What the code does today**
- A plan with an intraday horizon is refused as a data gate: `backend/services/strategy_plan/plan.py:185`
  (`intraday_not_supported`). Line 379 makes that gate block the plan.
- The DSL backtest, the paper desk and the exit step work on end-of-day bars only. Time is counted in sessions
  (`services/exit_rules.py`, `services/strategy_engine/backtest.py`).
- `services/kite_live_feed/intraday.py` can fetch raw 5/15/30/60-minute candles on demand. It has no 1-minute interval
  and stores nothing.
- `nidp/services/kite_bars` can collect minute bars into `nidp.intraday_bars`. That table comes from migration
  `152_kite_intraday_bars.sql`, and the collector needs a manual daily Kite login. It is not scheduled.

**Staging facts (read-only, 2026-10-27)**
```
warehouse: SELECT to_regclass('nidp.intraday_bars'), to_regclass('nidp.intraday_ingest_log')  ->  NULL, NULL  (migration 152 not applied)
warehouse: tables in schema nidp matching intraday|minute|tick                                    ->  0
Mongo (app backend, count_documents): kite_live_minute 156, kite_live_intraday 33, kite_live_close 2
```
The C study of 2026-10-27 recorded `kite_live_minute` at 0. The live feed has written 156 documents since then. That is
one partial session of quote snapshots, not a bar history. Their shape was not examined here.

**Preconditions to lift (all required, in order)** — from `guidelines_gap_study_20261027/C_research_and_data.md` Q6 and Q8(e):
1. Migration 152 is applied on the staging NIDP: `to_regclass('nidp.intraday_bars')` is not NULL.
2. A daily Kite login runbook exists, and the `kite_bars` collector is scheduled for a named pilot universe. The cron line
   is installed and visible in `/etc/cron.d/nidp-staging`.
3. At least 60 sessions of minute bars exist for the pilot universe, at 375 bars per full session (09:15–15:29 IST).
   Gaps are audited through `nidp.intraday_ingest_log`: per symbol and session, `count(*) = 375` or the gap has a reason.
4. A timestamp test passes: the first candle of every session is stamped 09:15 IST as the candle open, and none falls
   outside market hours.
5. The live feed writes `kite_live_minute` through whole sessions, for the spread estimate.
6. An intraday evaluation design, registered before results, models what criterion 4.4 lists: session boundaries (no
   bar crosses the close; an overnight position is a different strategy), timestamp alignment, realistic fills (next bar
   open or worse, never the signal bar's close), and slippage from the measured spread, plus a sweep.
7. Only then is `intraday_not_supported` lifted, in a reviewed PR that cites the evidence for 1–6.

**Who decides:** the owner, after 1–5 are shown on staging. Items 1, 2 and 5 are staging changes and need the go-ahead of
§9.2.

---

## 2. Bearish cash setups: not enabled as cash shorts

**What the code does today**
- A bearish cash view is recorded as "avoid / watch" with no entry: `backend/services/strategy_plan/candidates.py:249`
  (`long_only`).
- The paper desk accepts long trades only. `services/desk_trading.py:430` builds a long trade, and a stop at or above
  the entry is refused (`stop_not_below_entry`, line 437).
- The DSL backtest is long only: `services/strategy_engine/backtest.py:355` (`side="long"`).
- The AI Trader skips short signals and counts them (`services/ai_trader/validation.py:42`, `short_not_supported`).
  They are reported, not dropped.

**Preconditions to lift (all required)**
1. An instrument and workflow exist for a cash short. Delivery shorts are not possible in Indian cash equity: an
   intraday short must be squared off the same day, which Section 1 rules out. A positional bearish view needs SLB or
   F&O.
2. The bearish family passes the Phase 4 exit gate: a pre-registered, out-of-sample study on corrected prices, net of
   the desk cost card, beating its baseline in both regimes.
3. Phase 1's risk service sizes the short: its loss at the stop, gap stress upward, and borrow or margin cost.
4. The owner accepts it as a separately gated family (decision D2).

Until then a bearish view becomes either "avoid / watch" or the defined-risk options of Section 3.

---

## 3. Defined-risk bearish options: evaluated on the full multi-leg payoff and liquidity

**What the code does today**
- Every structure is priced by one engine, `services/strategy_plan/engine.compute_payoff`. The expiry payoff is exact
  over the strike kinks, so max loss and breakevens are exact, not read off a grid. Net figures and capital at risk use
  the desk cost card from **payoff-v2** (2026-10-27, this branch): STT, exchange, SEBI, stamp duty, GST and slippage per
  leg and per side, which are the costs a paper trade of the structure books. Before payoff-v2 the net figures included
  slippage and brokerage only.
- Undefined risk is refused at parse time: `services/strategy_plan/model.py:270` `_guard_risk` raises
  `undefined_risk_not_supported` for a net short call or an uncovered short put.
- The paper desk enforces the same rule when it records a structure (`services/desk_strategy_trades.py`, the
  defined-risk docstring at line 219: `unbounded_loss`, `naked_short_put`, `mixed_option_expiries`).
- Phase 1's risk gate checks it again at entry: `services/risk_gate/gate.py:181` `defined_risk_failures`, with
  `require_defined_risk: True` in `services/risk_gate/policy.py:24`.
- Liquidity is a gate, not a note:
  - Each leg's end-of-day facts carry open interest, volume and IV flags (`candidates.py:601`).
  - A leg with zero open interest, or no trades on the chain date, makes the candidate `illiquid_leg`
    (`candidates.py:906`, `:1022`).
  - Strike choice states its liquidity proxy (open interest and volume; there is no bid/ask in end-of-day data) at
    `candidates.py:881-884`.

**What a bearish options strategy still needs before promotion**
1. A study on the full structure, not the underlying. Each trade's P&L comes from leg marks at the close
   (`desk_strategy_trades` marks at `close_price`, never `settle_price`), net of the card.
2. A liquidity floor, registered before results, on each leg's open interest and volume on the entry day. Trades that
   fail it are reported as rejected-signal coverage, not removed silently.
3. The Phase 4 exit gate: out of sample, both regimes, net of costs, a robust improvement over the baseline. The F&O
   study on file, `docs/FO_STAGE_B2_FINDINGS_20261023.md` (short build-up, near month), is inconclusive (p 0.060). It
   does not support promotion.
4. IV history for the volatility axis (`fno_iv_history`). The backfill is the approved but unexecuted item b of the C
   study.

**Who decides:** the owner, per family, on the study's result.

---

## 4. Futures shorts: gated until the risk model handles futures exposure and adverse moves

**What the code does today**
- **Phase 0 refuses a futures-only structure that sells a future:** `services/desk_strategy_trades.py:244`
  (`short_futures_not_supported`, owner decision D2 of 2026-10-27).
- A long futures-only structure is allowed but marked as not defined risk (`defined_risk: False` with a note) and needs a
  stop on the underlying (`futures_stop_required`).
- Phase 1's risk gate refuses a futures-only structure (`futures_only`) and any future not covered by options
  (`unhedged_future`): `services/risk_gate/gate.py:189` and `:197` / `:205`.
- The payoff engine flags an unbounded loss on a short future (`loss_unbounded`, `capital_at_risk` null) and adds the
  caveat "Futures losses can exceed the initial margin".

**Preconditions to lift (all required)**
1. The risk service treats a short future as unbounded. It sizes it on the loss at the stop, plus a gap-stress move
   upward, plus margin. The Phase 1 estimate `est-risk-v1` must include a calibrated gap stress: today's
   `GAP_STRESS_PCT` is a named, uncalibrated research constant.
2. Margin comes from a live source (Zerodha's margin calculator through the platform's Kite login), or the gate refuses.
   No margin is assumed.
3. Daily mark-to-market and a margin-call scenario are modelled in the paper ledger. A futures loss can exceed the
   margin posted.
4. A study passes the Phase 4 exit gate for the short-futures family, net of the futures cost card (STT on the sell
   side, exchange 0.00183%, stamp 0.002%).
5. The owner lifts D2 for futures shorts in writing. The code change removes `short_futures_not_supported` in a reviewed
   PR with tests for the new sizing.

---

## Summary

| Area | Today | Enforced in | Lifted when |
|---|---|---|---|
| Intraday | refused | `plan.py:185` | migration 152 + scheduled collector + ≥ 60 audited sessions + 09:15 test + a registered fill model |
| Bearish cash | avoid / watch | `candidates.py:249`, `desk_trading.py:430`, `backtest.py:355` | an instrument (SLB/F&O), a passing study, sizing by the risk service, owner D2 |
| Bearish defined-risk options | allowed as candidates, gated on payoff and liquidity | `model.py:270`, `desk_strategy_trades.py:219`, `gate.py:181`, `candidates.py:906` | promotion only through a passing structure-level study |
| Futures shorts | refused | `desk_strategy_trades.py:244`, `gate.py:189-205` | unbounded-loss sizing with calibrated gap stress, live margin, MTM, a passing study, owner D2 |
