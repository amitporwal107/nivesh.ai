# Consecutive-Session Trading Simulation & Diagnostic Framework — PRD v1.0

**Status: DRAFT for owner approval (2026-09-19).** Requested by the owner after H#32 closed at development.

**Purpose:** before another model hypothesis is tested, establish whether the losing results come from:
- prediction quality;
- trade execution;
- risk management;
- allocation;
- costs;
- simulation or data errors.

**Scope:**
- development data only (2021–22); the sealed Jan 2023 – Jul 2024 block is not read;
- the model is not changed;
- no parameter is tuned after results are seen.

**Paused:** Phase 4 groups C and D (`PREREGISTRATION_P4_CD.md`, FROZEN 88455a35; code committed at bce06b4f and checked) are **not run** until this framework reports.

## 1. Problem

The H#32 model's top-5 daily picks lose −0.68% per trade after costs on 2022 development data. Every Phase 4 arm also loses. Before concluding that the model has no edge, we must show that the simulation itself is right, and attribute the loss to its causes.

**The framework must explain every trade, not only report P&L.**

## 2. What the existing results already show (descriptive; not yet independently verified)

These figures come from the H#32 development trades (M8 top 5 per day, 2022, 1,206 trades).
- They were computed with the same label code the loss came from, so an independent second simulator is still required (§6, D2).
- They set the leading hypotheses; they do not settle them.

M8 = the H#32 gradient-boosting model's top 5 a day; random = the seeded random-selection control.

| Diagnostic (2022, top 5 a day) | M8 model (1,206 trades) | Random (1,205) | Points to |
|---|---|---|---|
| Outcome: TARGET / STOP / EXPIRED | 24.5% / 69.0% / 6.6% | 20.9% / 63.7% / 15.4% | – |
| Mean gross, no costs or slippage | **−0.15%** | −0.07% | no gross edge |
| Mean net, base costs | −0.68% | −0.56% | – |
| Cost + slippage drag per trade | 0.53% | 0.48% | costs turn ~0 into a loss |
| Ambiguous same-bar exits (stop and target both touched) | 15 (1.2%) | 10 (0.8%) | intrabar ordering is **not** the cause |
| Upper bound if every ambiguous bar went to target first | −0.07% gross | −0.02% | still ≤ 0 |
| Gap-through stops | 46 (3.8%) | 43 | a small tail |
| Plain 5-session hold (no stop or target), mean gross | **0.00%** | +0.05% | **no directional edge** |
| Share of picks up after 5 sessions | 47.1% | 49.3% | direction ≈ coin flip |
| Median best move / median worst move (MFE / MAE) | +3.9% / −3.9% | +3.2% / −3.0% | symmetric: volatility, not direction |
| **Stop touched on the entry day (s1)** | **49.8%** | 38.5% | the −2% stop sits inside normal daily noise |
| Stopped although +5% was touched within 5 sessions | 16.9% | 9.4% | "volatility trap" |

**What the framework must confirm or reject:**
- signal / direction failure (no edge in the selections);
- stop failure (stop too tight for the selected volatility);
- cost drag;
- a simulation error.

Allocation and sizing were never tested for H#32: it used equal ₹50,000 trades, not a portfolio.

## 3. Goals and non-goals

**Goals:**
1. A bar-by-bar, portfolio-level simulation with an immutable ledger of:
   - predictions;
   - the complete candidate list;
   - orders, fills, positions;
   - the costs of every fill;
   - the bars used.
2. **Two independent simulators that must agree:** the existing label rule (`research/model_v5/labels.py`) and the risk engine (`tpd_model/risk/engine.py`), compared trade by trade. Any disagreement is a `SIMULATION_FAILURE` until explained.
3. Three diagnostic modes (§7): signal, execution and portfolio.
4. A per-session data-quality report, with no silent removals.
5. A root-cause label for every losing trade, and a scorecard with separate data, signal, execution and risk scores.
6. A pre-registered counterfactual matrix (§12) run on the **same frozen predictions**.

**Non-goals:**
- no model or feature change;
- no parameter optimisation;
- no use of the sealed block;
- no database, API or UI in v1 (files only);
- no live or forward trading.

## 4. Frozen inputs

| Input | Source |
|---|---|
| Predictions | H#32 development out-of-fold scores: `dev_oof_20260919T214001.csv.gz` (sha256 `8763f064…`), every model and label, for **every eligible stock**. `prediction_id` = sha256 of (code commit a499ce19, model, label, date, symbol, score) |
| Dataset | `dataset_dev_20260919T212230.csv.gz` (sha256 `7bb77e5a…b327`): eligibility, entry status, labels |
| Bars | Kite adjusted daily bars, cut at 2022-12-30 (the same guarded loader) |
| Calendar | NIFTY 500 Kite sessions (`index_dev.csv`) |
| Costs | `zerodha-equity-v1`, applied retroactively (flagged) |
| Sectors | Nifty 500 list `Industry` |

**Replay window (proposed):** the 20 consecutive decision sessions from **2022-10-03 to 2022-11-01**. Holdings end by 2022-11-09.
- These are the first 20 sessions of the 2022Q4 fold.
- It includes **2022-10-24, the Diwali Muhurat session.** It is a real edge case: a short special session that the current label code treats as a full session. The data-quality report must flag it, and the replay must show how it is handled.

**Full-year run:** the counterfactual matrix also runs on **all 2022 decision sessions** (about 1,200 trades per configuration).
- 20 sessions × 5 picks is about 100 trades. That is enough to audit every trade by hand, but not enough to tell configurations apart statistically.
- So the replay proves the simulation is correct; the full year attributes the losses.

## 5. Pipeline and component map

| # | Stage (owner's workflow) | Component | Reuse or new |
|---|---|---|---|
| 1 | Freeze the prediction | `predictions` ledger from the out-of-fold file, with `prediction_id` and sha256 manifest | new (small) |
| 2 | Validate the universe | dataset eligibility + **data-quality module** (§8) | reuse + new |
| 3 | Rank and select | **candidate ledger**: the full ranked list per session, status and reason (§9) | new |
| 4 | Entry, stop, target | **trade plans**: entry model × stop/target model (§10–§11), with validation rules | new |
| 5 | Order execution | `risk/execution.py`:<br>• existing: next-open, buy-stop, at-close orders; upper/lower circuit locks; volume participation and partial fills<br>• **new:** limit entry, confirmation entry, VWAP proxy | reuse + new |
| 6 | Bar processing | `risk/engine.py` daily loop. **New:**<br>• fixed **TARGET exits** (target reached intraday → exit at the target; gap over the target → exit at the open);<br>• an `INTRABAR_AMBIGUOUS` flag | reuse + **new (required for H#32 parity)** |
| 7 | Costs | `risk/costs.py`: per-fill breakdown (brokerage, STT, exchange charges, SEBI fee, GST, stamp duty, DP charge); slippage reported separately | reuse |
| 8 | Portfolio reconciliation | engine accounting + **new per-session check**: cash + positions at market = equity; exposure; risk at entry; no negative cash; no leverage | reuse + new |
| 9 | Diagnostics | **new:** trade audit (§14), root-cause classifier (§15), scorecard (§13), independent reconciliation against `labels.py` | new |

## 6. The independent reference (the simulation-correctness test)

Configuration A (next open, −2% / +5%, 5 sessions, ₹50,000 fixed position, costs on, no portfolio limits) must reproduce the H#32 label outcome **for every trade**:
- the same exit reason (TARGET, STOP, GAP_THROUGH_STOP, TIME);
- the same exit date;
- the exit price within ₹0.01 before slippage;
- net return within 1e-6.

**Every mismatch is listed and investigated.** No mismatch may be absorbed by a tolerance or silently re-coded. This proves or refutes the owner's concern that execution logic, OHLC ordering or cost arithmetic are wrong.

## 7. Diagnostic modes

| Mode | Question | Method | Key outputs |
|---|---|---|---|
| **A — Signal** | Do the selected stocks move up? | No execution rules. Forward paths from the s1 open for every ranked candidate | 1–5-session returns; best and worst move during the trade; share up; lift by rank decile; **top 5 vs ranks 6–10 vs 11–20 vs random**; volatility-matched comparison ("ranked high because of volatility alone?") |
| **B — Execution** | Do entries, stops, targets, slippage and costs cause the loss? | Each trade in isolation (fixed ₹50,000), across the entry and stop/target models | exit reasons, gap-through count, ambiguous-bar count, entry and exit slippage, cost %, R-multiples |
| **C — Portfolio** | Do sizing and allocation constraints change the result? | The risk engine with capital, position caps, sector caps and cash (§12) | accepted vs rejected positions and the binding constraint, risk budget used, exposure, drawdown, losing streaks |

## 8. Data-quality report (every session)

| Check | Implementation with our data |
|---|---|
| OHLC integrity | high ≥ max(open, close), low ≤ min(open, close), all > 0 |
| Missing bars | expected (eligible universe × calendar) vs present, per symbol and field |
| Corporate actions | Kite bars are adjusted, so signal and execution use one consistent adjusted series. Flag close-to-close moves > 20% and volume > 10× the 20-day median for manual review. **Limit:** adjusted prices are not the prices actually traded (§18) |
| Trading calendar | sessions vs the NIFTY 500 session list; special sessions flagged (**2022-10-24 Muhurat**) |
| Symbol mapping | symbol → ISIN from the Nifty 500 list; one instrument per symbol |
| Price continuity | open vs previous close beyond ±20% flagged |
| Volume | zero, missing, or below 5% of the 20-day median |
| Circuit limits | open, or close, locked at a 2/5/10/20% band (the existing heuristic in `execution.py`). Its known false positives are reported, not hidden |
| Prediction timestamp | the snapshot is a function of bars ≤ D. **Checked by recomputing the features of sampled rows from bars cut at D** (future-shock test) |
| Feature cutoff | the 44 features are price-only; the recomputation confirms no bar after D was used |
| Duplicate bars | none per (symbol, date) |
| Open availability | an s1 bar exists and its open is not locked; otherwise the reason is recorded |

**Output:** one block per session, in the owner's format, ending in PASS or FAIL.
- A session FAILS on any integrity, duplicate or cutoff violation.
- Flags (corporate action, circuit, special session) are PASS-with-flag.
- **No stock is removed silently.** Every exclusion carries its reason, and the report shows its effect on selection and P&L.

## 9. Candidate ledger (every eligible stock, every session)

Fields:
- `session_date`, `prediction_id`, `symbol`, `isin`, `rank`;
- `movement_probability`, the M4 score, and `tbs_probability`, the M8 score (raw and calibrated);
- `direction_probability` (M8 on `dir_5_5d`);
- `tradeability_score`: **NULL in v1**, because H#32 had no such model; the field is kept for later;
- `sector`, `value20`, `atr_pct`;
- `selection_status` (SELECTED / NOT_SELECTED / REJECTED) and `rejection_reason` (rank > 5, not eligible (with reason), data-quality flag, sector cap, cash, risk budget, liquidity);
- `risk_per_trade`, `entry_price`, `stop_price`, `target_price`, `position_size`;
- `selection_rule_version`.

The ledger must answer the owner's selection questions:
- volatility-only ranking;
- better candidates rejected by allocation;
- illiquid picks;
- correlated picks (same sector / pairwise correlation of the 60-day returns among the day's picks);
- ranks 1–5 vs 6–10 vs 11–20;
- avoidable concentration;
- insufficient reward-to-risk after costs.

## 10. Entry models (parameters proposed here, frozen at approval)

| Model | Definition on daily bars |
|---|---|
| NEXT_OPEN | the s1 official open (the H#32 baseline) |
| OPEN_WITH_SLIPPAGE | the s1 open plus the cost-model slippage bucket (0.05 / 0.10 / 0.20% per side) |
| OPEN_CONFIRMATION | a buy-stop at the D high + 0.1%, valid on s1 only; it fills at max(open, trigger) when the s1 high reaches the trigger, otherwise NO_ENTRY. This reuses the tested BUY_STOP fill in `execution.py` |
| LIMIT_ENTRY | a limit at the D close × 0.995, valid on s1 only. Fills at min(open, limit) when the s1 low ≤ limit |
| VWAP_PROXY | the s1 typical price (high + low + close) / 3. **Labelled an approximation:** true VWAP needs intraday data |
| NO_ENTRY conditions | no s1 bar; s1 open locked at the upper circuit; s1 open more than 3% above the D close (maximum chase); a stop at or above the entry after a gap |

**Each trade records:**
- `signal_timestamp`, `signal_close`, `next_session_open`;
- `intended_entry`, `actual_entry`, `entry_method`, `gap_pct`, `slippage_bps`;
- `fill_status`, `fill_quantity`, `entry_rejection_reason`.

## 11. Stop and target models, and validation (proposed, frozen at approval)

| Model | Stop | Target |
|---|---|---|
| FIXED (baseline) | entry × 0.98 | entry × 1.05 |
| ATR | entry − 1.5 × ATR(14) (the baseline's `atr_pct`) | 2R |
| STRUCTURE | the lowest low of the 10 sessions to D, less 0.1%, bounded to 1–8% below entry (as in the positional study) | 2R |
| VOLATILITY-ADJUSTED | entry × (1 − 1.5 × σ20), where σ20 = the standard deviation of the stock's daily returns over 20 sessions, bounded to 1–8% | 2.5R |

**A trade is rejected or flagged when:**
- stop ≥ entry, or target ≤ entry;
- risk per share ≤ 0 or invalid;
- the stop distance exceeds the risk budget;
- the target is too close to cover the round-trip cost plus slippage (reward < 2 × cost);
- the quantity is 0 after rounding;
- the position exceeds the capital or liquidity limits.

**Each trade records:**
- `initial_stop`, `initial_target`;
- `risk_per_share`, `reward_per_share`, `risk_reward_ratio`;
- `stop_method`, `target_method`;
- `stop_distance_atr`, `target_distance_atr`;
- any stop or target adjustments (none in v1).

## 12. Portfolio controls (Mode C) and the comparison matrix

**Configurations:**
- capital configurable (baseline ₹5,00,000);
- 5 and 8 maximum positions;
- risk per trade 0.5%, 1.0% and 2.0%;
- position cap 20%;
- sector cap configurable (baseline 40%);
- total exposure cap 100%;
- at most 5 new positions a day;
- portfolio-loss kill switch configurable (baseline off, so it doesn't truncate the diagnostic);
- cash reserve 0%;
- compounding **off**;
- leverage **disabled**.

**Sizing:** Q = min(Q_risk, Q_allocation, Q_cash, Q_liquidity), using the existing `sizing.size()`. The binding constraint and every rejection reason are recorded, and each session ends with an **allocation audit** in the owner's format.

**Mandatory comparison matrix**, all on the same sessions, universe and frozen predictions:

| Run | Entry | Stop | Target | Portfolio | Costs | Purpose |
|---|---|---|---|---|---|---|
| A | next open | 2% | 5% | ₹50,000 per trade | on | H#32 baseline (reconciled with `labels.py`, §6) |
| B | next open | ATR | 2R | ₹50,000 per trade | on | stop/target test |
| C | confirmation | 2% | 5% | ₹50,000 per trade | on | entry test |
| D | next open | 2% | 5% | risk engine, **no allocation limit** | on | allocation effect |
| E | next open | 2% | 5% | ₹50,000 per trade | **off** | cost effect (diagnostic only) |
| F | next open | 2% | 5% | risk engine, all limits | on | full realism |
| G (recommended) | as A | | | | | **random selection** (the same sessions, 200 seeds): selection vs execution |
| H (recommended) | next open | **none** | **none** | ₹50,000 per trade, 5-session hold | on | the "just hold" control: separates the stop/target rule from direction |

- The structure stop, volatility-adjusted stop, limit entry and VWAP proxy run as secondary rows.
- The interpretation rules are the owner's, fixed in advance: A vs E for costs; D vs F for allocation; B vs A for stops; everything negative means signal or direction.
- **Nothing is tuned between runs.**

## 13. Scorecard (separate scores, never one combined score)

| Score | Metrics |
|---|---|
| A. Data quality | valid-bar %, missing OHLC, invalid prices, corporate-action flags, cutoff (PIT) violations, late features, special sessions |
| B. Signal | top-5 up-rate, target-before-stop rate, target-hit rate, stop-hit rate, best and worst move during the trade, lift by rank decile, top-5 vs 6–10 vs 11–20 vs random |
| C. Execution | entry and exit slippage, gap-through count, fill rejections, ambiguous bars, cost as % of turnover and of gross P&L |
| D. Risk and allocation | actual risk per trade vs configured, exposure, sector concentration, concurrent positions, risk-budget use, maximum drawdown, largest loss, longest losing streak |

## 14. Trade lifecycle and audit

**States:** signal → candidate validated → order eligible → submitted → filled / partial / rejected → open → stop, target or time evaluated → closed → charges reconciled → audit complete.

**Exit reasons:** TARGET_HIT, STOP_HIT, TIME_EXIT, GAP_THROUGH_STOP, CORPORATE_ACTION, LIQUIDITY_EXIT, DATA_INVALIDATED, MANUAL_REVIEW_REQUIRED. Each exit has a date, price, trigger and the bar as evidence.

**Trade audit row:** the owner's template in full.
- trade ID, signal date, entry date, symbol, model rank;
- movement / target-first probability, entry method;
- intended vs actual entry, initial stop, target, quantity, initial risk;
- best move (MFE) and worst move (MAE) during the trade;
- exit date, exit price, exit reason;
- gross P&L, charges, slippage, net P&L, R-multiple;
- data-quality, execution and risk status, and review status.

**Sample:** 100% of replay-window trades are checked against the raw bars, plus the extreme-trade audit for the full year.

## 15. Root-cause classification (rule set RC-1, fixed before the run)

A losing trade can carry several causes. **Primary** is the first matching rule in this order.

| Cause | Rule |
|---|---|
| DATA_FAILURE | any data-quality integrity failure or unreviewed flag on a bar the trade used |
| SIMULATION_FAILURE | the engine and the `labels.py` reference disagree on the trade (§6) |
| RISK_FAILURE | realised loss > 1.5 × planned risk (gap-through beyond budget) or a position over a cap |
| LIQUIDITY_FAILURE | partial fill or participation cap binding |
| ENTRY_FAILURE | s1 open > D close × 1.02 (chased gap), and the trade lost |
| VOLATILITY_TRAP | stopped, although the target level was reached later within the 5 sessions |
| STOP_FAILURE | stopped with the stop distance < 1.0 × ATR (inside normal daily range) |
| DIRECTION_FAILURE | stopped, the target never reached, and the s5 close below entry |
| TARGET_FAILURE | expired, having reached at least +2.5% but never the target |
| SIGNAL_FAILURE | expired, never beyond ±2% (the stock didn't move) |
| COST_FAILURE | gross > 0 and net ≤ 0 |
| ALLOCATION_FAILURE | (candidate level) rejected by a portfolio constraint, when its execution-only outcome was a win |

## 16. Acceptance criteria

**Simulation correctness:**
- all replay sessions run with no silent skips;
- every selected and rejected candidate has a reason;
- all trades carry immutable `prediction_id`s;
- entry, stop and target are reproducible from the ledger;
- intrabar ambiguity follows one versioned policy (stop first, flagged);
- gap-through behaviour is tested;
- costs are reported separately;
- cash and exposure reconcile every session;
- 100% of replay trades are audited against the raw bars;
- **engine vs `labels.py` agree on every configuration-A trade, or every difference is explained;**
- deliberate code breaks are caught by the tests.

**Research correctness:**
- no sealed-block bar is read (the guarded loader asserts it);
- the same dataset and predictions are used for every run;
- the matrix is pre-registered before any run;
- the baseline is frozen; no tuning after results;
- failed runs stay recorded;
- no improvement is claimed from gross P&L.

## 17. Deliverables (order)

| # | Deliverable | Verification |
|---|---|---|
| D1 | Immutable ledgers (predictions, candidates, orders, fills, positions, bars used, costs) + data-quality module | synthetic tests; the replay window's data-quality reports |
| D2 | TARGET exits and the `INTRABAR_AMBIGUOUS` flag in `risk/execution.py` / `engine.py`; the new entry models | synthetic tests and deliberate code breaks; the existing 47 risk tests still pass |
| D3 | **Baseline reconciliation**: configuration A through the engine vs `labels.py` on all 2022 trades | the mismatch list is empty or fully explained |
| D4 | 20-session replay with the complete trade audit and allocation audits | a hand-checked sample against raw bars |
| D5 | Pre-registration of the matrix (§12), then the single run of A–H on the replay window and all of 2022 | results file with sha256; audits clean |
| D6 | Root-cause report and scorecard | `SIM_DIAGNOSTIC_RESULTS.md` |
| D7 | Fix only **verified** simulation defects, rerun the frozen baseline, record the differences | before/after table |
| — | Only then: resume Phase 4 C/D or design the next hypothesis from the evidence | owner decision |

All of this is research code under `research/sim_diag/`, plus engine extensions in `tpd_model/risk/`. It does **not** touch production crons, the pinned forward worktrees, or any database.

## 18. Known limits

- **Adjusted prices:** Kite daily bars are split/bonus/dividend-adjusted. Percentages are exact, but rupee prices before an ex-date differ from those actually traded, which affects rupee-based costs and the ₹50 price floor slightly. Cross-checking the replay window against unadjusted NSE bhavcopy is an option, if 2022 bhavcopy files are available locally (UNVERIFIED).
- **Intrabar order:** daily bars can't prove it. Resolving the ambiguous bars with Kite 5-minute data is possible, but needs a 2022 minute-data fetch with a fresh owner login (UNVERIFIED availability). Given 1.2% ambiguity, it is deferred.
- **Other shared limits:** survivorship (current Nifty 500 members); costs applied retroactively; only 2022 predictions exist out of fold.

## 19. Decisions needed from the owner

1. Approve this PRD (scope, the full-year run alongside the 20-session replay, and the recommended controls G and H).
2. Replay window: 2022-10-03 → 2022-11-01 (includes Diwali Muhurat), or another 20-session block.
3. Entry-model and stop/target parameters in §10–§11. These are frozen at approval, never tuned afterwards.
4. Phase 4 C/D stays paused until D6.
