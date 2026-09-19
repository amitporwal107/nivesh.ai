# Consecutive-Session Trading Simulation & Diagnostic Framework — PRD v1.0

| Item | Value |
|---|---|
| Status | **DRAFT for owner approval** (2026-09-19). Nothing in this PRD has been built yet. |
| Source | Owner's specification of 2026-09-19 ("Consecutive-Session Trading Simulation & Diagnostic Framework"), sections 1–16. This PRD makes that specification buildable against the existing code, and lists the decisions it still needs. |
| Question | When the model selects stocks and the trades lose, is the cause **prediction quality, trade execution, risk management, allocation, costs, or simulation/data errors**? |
| Scope | Development data only (2021–22). The sealed Jan 2023 – Jul 2024 block is not read. **No model change**: the same frozen predictions go through every configuration. |
| Paused meanwhile | Phase 4 groups C and D. The pre-registration is FROZEN (88455a35) and the code is committed and tested (bce06b4f), but it has **not been run**; it resumes only after this framework reports. |

## 1. What the existing data already says (descriptive, development-only)

These figures come from the frozen H#32 development top-5 picks. They were computed with the same label code that H#32 used, so they are **not yet** independently reconciled (that is §5, step 2). They shape the priorities below; they do not replace the framework.

M8 = the H#32 gradient-boosting model's top 5 a day; random = the seeded random-selection control.

| Diagnostic (2022, top 5 a day) | M8 model (1,206 trades) | Random (1,205) | Points to |
|---|---|---|---|
| Outcome: TARGET / STOP / EXPIRED | 24.5% / 69.0% / 6.6% | 20.9% / 63.7% / 15.4% | – |
| Mean gross, no costs or slippage | **−0.15%** | −0.07% | no gross edge |
| Mean net, base costs | −0.68% | −0.56% | – |
| Cost + slippage drag per trade | 0.53% | 0.48% | costs turn ~0 into a loss |
| Ambiguous same-bar exits (stop and target both touched) | 15 (1.2%) | 10 (0.8%) | intrabar ordering is **not** the cause |
| Upper bound if every ambiguous bar went to target first | −0.07% gross | −0.02% | still ≤ 0 |
| Gap-through stops | 46 | 43 | small |
| Plain 5-session hold (no stop or target), mean gross | **0.00%** | +0.05% | **no directional edge** |
| Share of picks up after 5 sessions | 47.1% | 49.3% | direction ≈ coin flip |
| Median best move / median worst move (MFE / MAE) | +3.9% / −3.9% | +3.2% / −3.0% | symmetric: volatility, not direction |
| **Stop touched on the entry day (s1)** | **49.8%** | 38.5% | the −2% stop sits inside normal daily noise |
| Stopped although +5% was touched within 5 sessions | 16.9% | 9.4% | "volatility trap" |

**Working hypotheses for the framework to confirm or refute:**
1. The selections have no directional edge. Mode A tests this.
2. The fixed −2% stop is too tight for the volatile names the model selects. Mode B, stop models, tests this.
3. Costs of about 0.5% per round trip then turn a zero gross into a loss. Configurations E vs F test this.
4. Simulation ordering is not a material cause. The reconciliation in §5 step 2 tests this.

Allocation (Mode C) has not been tested at all: H#32 used equal-weight sleeves.

## 2. What exists and what is new

| Owner requirement | Existing component (reuse) | Gap to build |
|---|---|---|
| Immutable prediction snapshot | `dev_oof_20260919T214001.csv.gz` (sha256 `8763f064…`): **every** eligible candidate's score for every 2022 session and model; 103 hashed frozen models | A candidate ledger with rank, rejection reason and snapshot id |
| Order execution: gaps, unavailable open, partial fills, circuits | `tpd_model/risk/execution.py`:<br>• fill types MOO (market-on-open), BUY_STOP and MOC (market-on-close)<br>• gap-through stops; stop first on a same-bar touch<br>• upper/lower circuit locks; participation-capped partial fills | Entry models CONFIRMATION, LIMIT and VWAP_PROXY; an INTRABAR_AMBIGUOUS flag |
| Sizing and allocation constraints, with the binding constraint named | `risk/sizing.py` (Q = min of risk, stock, sector, cash, deployment, liquidity and portfolio-risk quantities, with coded rejection reasons), `risk/portfolio.py` | Configurations for 5 / 8 positions and 0.5 / 1 / 2% risk; the allocation audit report |
| Costs, itemised | `risk/costs.py` + `zerodha-equity-v1` (STT, exchange, SEBI, GST, stamp duty, DP charge; slippage buckets) | A no-cost diagnostic switch (configuration E) |
| Drawdown / kill switch | `risk/drawdown.py` | – |
| Append-only audit ledger | `risk/ledger.py` (JSONL + sha256 manifest) | Candidate, bar, data-quality and trade-audit record types |
| Bar-by-bar portfolio loop | `risk/engine.py` (used by the positional study) | Per-session cash, exposure and P&L reconciliation output |
| Selection vs random, risk vs none, costs, beta decomposition | Positional study (`research/positional/`) | Root-cause classification per trade |
| Data quality | Block guards; circuit heuristic; extreme-trade audit | A **per-session DQ report** covering every check in §6 |

## 3. Design

### 3.1 Simulation modes (the same frozen predictions throughout)

| Mode | Question | Engine |
|---|---|---|
| **A — Signal** | Do the selected stocks subsequently move up? | No execution rules. Per candidate: close-to-close returns for s1…s5, MFE / MAE, up-hit rate, and rank-decile lift (top 5 vs ranks 6–10, 11–20 and the rest) |
| **B — Execution** | What do the entry, stop, target, slippage and cost rules do to the same trades? | Per-trade bar-by-bar simulation using `risk/execution.py` fills; one position per signal; no portfolio constraints |
| **C — Portfolio** | What do sizing, allocation, concentration and overlap do? | `risk/engine.py` with configurable caps; reports the binding constraint and every rejected order |

### 3.2 Comparison matrix (identical sessions, universe and predictions)

This is the owner's matrix. A is the H#32 baseline.

| Configuration | Entry | Stop | Target | Portfolio | Costs | Purpose |
|---|---|---|---|---|---|---|
| **A** | next open | −2% fixed | +5% | 5 positions / day, equal weight | full | existing baseline |
| **B** | next open | ATR-based: entry − k × ATR14 | 2R | as A | full | stop/target test |
| **C** | confirmation (§3.3) | −2% fixed | +5% | as A | full | entry test |
| **D** | next open | −2% fixed | +5% | no allocation limits | full | allocation test |
| **E** | next open | −2% fixed | +5% | as A | **none** (diagnostic only) | cost attribution |
| **F** | next open | −2% fixed | +5% | as A | full + 2× slippage | cost stress |

Added to the owner's matrix (reported, not decision-bearing):
- **A-hold:** no stop and no target; exit at the s5 close. This isolates what stops do.
- **A-random:** configuration A on the seeded random picks. This isolates selection.

### 3.3 Definitions the owner must fix before any run

These are the pre-registration items. Defaults are proposed; no value may change after a result is seen.

| Item | Proposed default | Why |
|---|---|---|
| Replay window | **20 consecutive decision sessions: 2022-10-03 → 2022-11-01**; labels complete by 2022-11-09 | The first 20 sessions of the last development fold. Includes the 2022-10-24 Diwali muhurat session (a one-hour special session), a built-in data-quality edge case |
| Attribution window | **All 2022 decision sessions** (~1,200 trades per configuration) | 20 sessions × 5 = ~100 trades cannot separate configurations statistically. The replay is for **correctness**; the full year is for **attribution** |
| Predictions | H#32 frozen out-of-fold scores (M8, `tbs_5_2`) + the random control; top 5 per session among eligible names | The same snapshot for every configuration |
| CONFIRMATION entry | Buy-stop at the D high + 0.1%, valid on s1 only; no fill if not triggered | Reuses the tested BUY_STOP fill |
| LIMIT entry | Limit at the D close − 0.5% on s1 (fill at min(open, limit) if the low reaches it) | A simple pull-back entry |
| VWAP_PROXY entry | s1 typical price (high + low + close) / 3; diagnostic only | Daily bars have no true VWAP |
| ATR stop (configuration B) | k = 1.5 × ATR14 (the v4 `atr_pct`); target = entry + 2 × risk | A common volatility-scaled stop |
| Structure stop (optional) | Below the 10-session low, capped at 8% | As in the positional study |
| Portfolio for Mode C | ₹5,00,000; 5 and 8 positions; risk 0.5 / 1 / 2%; 20% per position; 100% exposure; 5 new per day; no compounding; no leverage | Owner §9 |
| Intrabar policy | STOP first on a same-bar touch; gap-through at the open; flag INTRABAR_AMBIGUOUS | Owner §8. Ambiguity is only 1.2%, so resolving it with 5-minute bars is **optional** (and would need a Kite fetch of 2022 minute bars) |

## 4. Required outputs

All outputs are append-only and hash-manifested.

1. **Session DQ report** (one per session). The checks:
   - OHLC integrity;
   - missing bars and fields;
   - duplicate bars;
   - price jumps above 20% (corporate-action suspects: Kite data is adjusted, so a jump means a missed adjustment);
   - zero or low volume;
   - circuit-locked opens and closes;
   - calendar match;
   - symbol ↔ ISIN via the Nifty 500 list;
   - no feature dated after D;
   - open availability at s1.

   Decision: PASS / FAIL. **A failure never removes a stock silently**: the reason and its effect on selection are recorded.
2. **Candidate ledger** (every eligible name, every session). The owner's §5 fields: rank, scores, sector, selected or rejected, rejection reason, intended entry / stop / target, quantity, rule version.
3. **Order / fill / position ledgers:** state-machine events from signal to audit (owner §10).
4. **Trade audit table:** the owner's §11 template, including MFE, MAE, R-multiple and data / execution / risk / review status.
5. **Portfolio reconciliation per session:** cash + positions = equity; exposure; realised and unrealised P&L; charges.
6. **Diagnostic scorecard:** the four owner §12 blocks (data, signal, execution, risk & allocation), reported separately and never as one score.
7. **Root-cause table:** one or more categories per losing trade, from versioned rules (§4.1).

### 4.1 Root-cause rules (proposed; thresholds fixed in the pre-registration)

| Category | Rule (losing trade unless stated) |
|---|---|
| DATA_FAILURE | Any DQ flag on a bar the trade used |
| SIMULATION_FAILURE | The two independent simulators disagree on this trade (§5 step 2) |
| ENTRY_FAILURE | The s1 open is ≥ 2% above the D close (entry gapped away) |
| VOLATILITY_TRAP | Stopped, and the +5% target was touched within the 5 sessions |
| STOP_FAILURE | Stopped, with the stop distance < 1.0 × ATR14 (inside normal daily noise) |
| DIRECTION_FAILURE | Stopped, target never touched, and the s5 close below entry |
| SIGNAL_FAILURE | Expired with MFE < +2% and MAE > −2% (the stock didn't move) |
| TARGET_FAILURE | Expired with MFE between +2% and +5% (target unrealistic for the horizon) |
| COST_FAILURE | Gross > 0 but net ≤ 0 (any trade) |
| LIQUIDITY_FAILURE | Partial fill or participation cap bound |
| ALLOCATION_FAILURE | Candidate rejected by a portfolio constraint that would have been profitable (candidate level) |
| RISK_FAILURE | Realised loss > 1.5 × the configured risk budget (for example a gap-through) |

## 5. Implementation plan

The work is in `research/simulation/` and reuses `tpd_model/risk/` unchanged. Tests go in before any real run.

| Step | Deliverable | Verification |
|---|---|---|
| 1 | Ledger schemas + DQ report + candidate ledger from the frozen snapshot | Synthetic tests; each DQ check fires on a planted defect |
| 2 | **Baseline reconciliation:** re-simulate H#32 configuration A bar by bar with `risk/execution.py` and compare trade by trade with the label-based result (`labels.py`) | Every trade matches (entry, exit, reason, net) or the difference is explained and filed as SIMULATION_FAILURE; deliberately planted bugs are caught |
| 3 | Mode A, Mode B (configurations A–F, A-hold, A-random) and Mode C | Synthetic tests for each entry, stop and target model and for ambiguity flagging; cash/exposure reconciliation in every session |
| 4 | **20-session replay** (correctness): every candidate, order, fill and exit explained; raw-OHLC audit of sampled trades | Acceptance criteria below |
| 5 | Full-2022 attribution run of the matrix + root-cause table | Paired date-clustered bootstrap for configuration differences (as H#32) |
| 6 | Report: fix any verified simulator defect, rerun the same frozen baseline, record the differences, then design the next hypothesis from the evidence | Owner review |

## 6. Acceptance criteria

These are the owner's §15, all required.

**Simulation correctness:**
- All sessions in the window are replayed without a silent skip.
- Every selected **and rejected** candidate has a reason.
- Every trade carries its prediction snapshot id + hash.
- Entry, stop and target are reproducible from the recorded formulas.
- Intrabar ambiguity is handled by one versioned policy and counted.
- Gap-through-stop behaviour is tested.
- Costs are reported separately from gross.
- Cash and exposure reconcile in every session.
- A raw-OHLC audit is done on sampled trades.
- Intentional bugs are caught by the tests.

**Research correctness:**
- No locked-period bar is read.
- The same dataset and predictions are used in every comparison.
- The baseline and every alternative configuration are pre-registered.
- No post-result tuning.
- Failed configurations stay recorded.
- No model improvement is declared from gross P&L.

## 7. Decisions needed from the owner

1. Approve this PRD's scope. In particular:
   - the **two windows**: a 20-session replay for correctness plus all of 2022 for attribution;
   - whether Phase 4 C/D waits until after the report.
2. Approve or change the §3.3 defaults. After approval they are frozen into a pre-registration, like H#32.
3. Optional: fetch 2022 five-minute bars from Kite to resolve ambiguous bars. The recommendation is not to, since only 1.2% of trades are affected and the upper bound is still negative.
