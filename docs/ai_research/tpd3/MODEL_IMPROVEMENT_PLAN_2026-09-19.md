# Nivesh.ai Model Improvement Plan (owner, 2026-09-19)

Saved from the owner's message of 2026-09-19 (~20:40 IST). The text is verbatim; the tables that were flattened in the message are restored. The source's "Pasted markdown.md" citation markers are dropped. Status of each item: see §11 at the end, maintained by the agent.

## 1. Fix the fundamental problem: movement versus tradeable opportunity

Your current model predicts whether the next session's high or low touches a +5% or +10% threshold.

But your actual objective is to identify stocks where a defined trading strategy has a reasonable probability of reaching its target before its stop, generating positive returns after costs.

These are different prediction problems.

**Introduce separate prediction heads.**

| Head | Prediction |
|---|---|
| `p_up5_touch_1d` | High reaches +5% next session |
| `p_up10_touch_1d` | High reaches +10% next session |
| `p_up5_close_5d` | Closing price reaches +5% within 5 sessions |
| `p_up10_close_5d` | Closing price reaches +10% within 5 sessions |
| `p_target_before_stop` | Target is reached before stop |
| `p_net_positive` | Trade produces positive net return |
| `expected_net_return` | Expected return after costs and slippage |

Do not remove the existing touch models. Retain them as movement/volatility signals and add trade-outcome models alongside them.

## 2. Prioritize a positional strategy study

Your current document identifies the positional study as the next untested structure.

**Locked initial configuration**

| Parameter | Proposed setting |
|---|---|
| Holding period | Maximum 5 sessions |
| Risk per trade | 0.5% baseline |
| Maximum risk | 2% configurable ceiling |
| Maximum positions | 8 |
| Maximum allocation per stock | 20% |
| Benchmark | Nifty 500 |
| Entry strategies | Pre-breakout, pullback, 55-day breakout, signal-day close |
| Costs | Delivery charges, STT, brokerage where applicable, slippage |
| Controls | Random entries with identical exits and sizing |

These parameters come from your existing agreed study and should be preregistered before testing.

**Required comparison.** Every strategy must be compared against:
- random stock selection;
- random entries with identical risk management;
- the Nifty 500 benchmark;
- existing v4 top-ranked selections;
- a simple momentum baseline.

This will tell us whether the model adds value beyond the trading rules themselves.

## 3. Improve the labels before adding features

This is the highest-priority model change.

**Recommended target definition.** For every stock on day D:
- Features are frozen at the permitted cutoff on day D.
- Entry occurs according to the registered strategy on day D+1.
- Target, stop and expiry are evaluated over the next five sessions.
- All costs and slippage are included.
- If both stop and target are touched in the same bar and the sequence is unknown, apply a conservative predefined rule.

```text
Signal date:       Monday
Entry:             Tuesday open
Target:            +5%
Stop:              -2%
Expiry:            Friday close
Output:            Target first / Stop first / Expired
```

Avoid using only the next session's high because it does not reveal whether the target was realistically achievable after entry.

## 4. Improve the features in four focused groups

Do not add hundreds of indicators indiscriminately. Test each feature group independently.

**A. Market regime.** Add or validate:
- Nifty trend over 5, 20 and 60 sessions;
- market volatility regime;
- market breadth;
- percentage of stocks above 20-day and 50-day averages;
- index gap and intraday range;
- market trend strength.

The same stock setup can behave differently in a trending, sideways or stressed market.

**B. Sector-relative strength.** This is particularly important for directional prediction.

| Feature | Example |
|---|---|
| Stock versus sector return | 20-day relative performance |
| Stock versus Nifty return | 5/20/60-day relative performance |
| Sector breadth | Advancing stocks versus declining stocks |
| Sector momentum | Sector ranking and trend |
| Relative volume | Stock volume versus sector volume |

Your APARINDS case study already identified the absence of trend, sector and event inputs as a limitation.

**C. Breakout and continuation quality.** Your research found that 20/55-day breakouts predict larger movements but lose money. Therefore, don't simply add a breakout flag. Test:
- breakout distance relative to ATR;
- volume confirmation;
- prior failed breakout count;
- distance from breakout level;
- sector confirmation;
- market regime at breakout;
- follow-through after breakout;
- gap-through-breakout frequency.

The objective is to determine when a breakout becomes tradeable, not merely whether it precedes a large movement.

**D. Tradeability and execution.** Add:
- median traded value;
- price gap risk;
- ATR relative to price;
- historical target-before-stop ratio;
- expected slippage;
- liquidity-adjusted position size;
- frequency of gap-through-stop events.

These features connect the prediction to actual executable trades.

## 5. Fix the fundamental data pipeline

Before trusting any fundamental-feature improvement:

| Priority | Action |
|---|---|
| P0 | Fix the nightly model snapshot failure caused by uncommitted code |
| P0 | Separate development and forward-test worktrees |
| P0 | Validate PIT eligibility of every fundamental feature |
| P1 | Fix DEF-6 profit parsing |
| P1 | Fix DEF-8 historical shareholding parsing |
| P1 | Fix DEF-9 mutual-fund holdings |
| P1 | Resolve Trendlyne blank-cache behavior |
| P1 | Improve results availability using validated exchange filings |

Your status document records a median 36-day delay in NIDP results and three production parser defects.

Do not allow revised or late-arriving fundamentals to enter historical training as though they were known at the decision time.

## 6. Build a directional model from the existing features

Before adding sophisticated algorithms, create a dedicated directional baseline.

**Candidate models:**
- logistic regression;
- the existing HistGradientBoosting;
- LightGBM/XGBoost, if available within your environment;
- a simple rule-based momentum model.

**Keep these identical across candidates:** universe, training periods, validation periods, costs, entry rules, risk limits, feature cutoff and random seed.

The objective is to discover whether the current features contain directional information that the present touch model is not using effectively.

## 7. Use a two-stage decision system

Instead of ranking stocks solely by `p_up10_1d`, calculate a tradeability score.

**Stage 1: movement likelihood.** Movement probability = P(price reaches target within horizon).

**Stage 2: trade outcome.** Trade probability = P(target before stop | entry, strategy, market conditions).

**Decision layer (illustrative structure):**

```text
Expected value
= (P(target) × net_target_return)
  - (P(stop) × net_stop_loss)
  + (P(expiry) × net_expiry_return)
```

Then apply:
- risk limits;
- liquidity constraints;
- portfolio concentration;
- correlation limits;
- minimum expected value;
- probability calibration requirements.

The model should not automatically trade the stock with the highest movement probability.

## 8. Correct the evaluation framework

Your current 10% model has a strong ranking result, but the trading results do not yet establish profitability. Your document reports approximately 14.8% hit rate for the top five versus 1.1% overall, alongside negative trading results.

Evaluate the following separately:

| Evaluation | Why it matters |
|---|---|
| PR-AUC | Rare-event ranking |
| Precision at top 1%, 5%, 10% | Selection quality |
| Calibration/Brier score | Whether odds are reliable |
| Target-before-stop rate | Trade structure |
| Average and median net return | Profitability |
| Profit factor | Gains versus losses |
| Maximum drawdown | Risk |
| Exposure-adjusted return | Capital efficiency |
| Performance by regime | Stability |
| Performance by sector | Concentration risk |

A model should not be promoted solely because its AUC improves.

## 9. Preregister the next experiment

Before using the untouched historical period, create a fixed experiment specification. It should include:
- exact target definitions;
- feature cutoff;
- training and validation periods;
- universe membership rules;
- entry and exit rules;
- stop and target;
- cost and slippage assumptions;
- position sizing;
- maximum positions;
- evaluation metrics;
- promotion criteria;
- random seed;
- prohibited post-test tuning.

The document notes that clean testing periods are becoming limited, so protecting the untouched period is essential.

## 10. Recommended implementation sequence

1. **Stabilize the forward test.** Fix the uncommitted-file failure and isolate nightly scoring from development.
2. **Freeze the data and labels.** Define target-before-stop, five-session outcomes, costs and execution rules.
3. **Run the positional study.** Compare the registered strategies with random and benchmark controls.
4. **Build a directional baseline.** Use existing v4 features before introducing additional feature groups.
5. **Add market and sector context.** Run separately controlled experiments with preregistration.
6. **Add tradeability features.** Include liquidity, gap risk, slippage and target-before-stop history.
7. **Calibrate and combine the signals.** Use movement probability, direction, expected return and risk constraints.
8. **Promote only after locked validation.** Require repeatable net improvement on unseen data.

**My clear recommendation.** Do not spend the next phase adding more technical indicators or changing the algorithm. Focus on these three deliverables:
1. a correctly labelled five-session trade-outcome dataset;
2. a directional and target-before-stop model using the existing v4 features;
3. a preregistered positional backtest with realistic costs and risk controls.

## 11. Status (agent-maintained)

| Item | Status 2026-09-19 |
|---|---|
| §5 P0 nightly snapshot failure | **Diagnosed.** Friday 18 Sep's v4 and v2/v3 scoring both refused ("uncommitted changes in tpd_model"): an untracked `build_features_v6.py` in the shared dev worktree `tpd3-mvp`. |
| §5 P0 separate worktrees | **Done in configuration:** `run_v4.sh` and `run_daily.sh` now use `worktrees/forward-v4` (detached at 4d90472b, the last good snapshot's commit); `run_paper.sh` uses `worktrees/forward-paper` (detached at b3305593). Backups: `*.bak-20260919-worktree`. **UNVERIFIED by a real nightly run** until Monday 21 Sep 20:45 IST. |
| §2 / §10.3 positional study | Pre-registered (fe60155f), run started 20:30. The v4 top-ranked and momentum comparisons were **not** in the frozen design; if added, they are supplementary and labelled post-freeze. |
| §2 / §10.3 positional study (result) | **All six arms CLOSED**: `positional/RESULTS.md` (0af4cba6). Negative even before costs; random entries under the same rules also lose; stops made five of six arms worse. |
| Owner decisions 20:55 IST (roadmap v2) | Periods **chronological**: develop and walk-forward on 2021-01..2022-12 only, one locked test on 2023-01..2024-07, then confirm on Aug-2024..Sep-2026 and forward. Fundamentals **excluded** from the primary dataset until DEF-6/8/9 are fixed and PIT-validated. Primary trade-outcome label **+5% target / −2% stop / 5 sessions** (stop first on a same-bar touch); +10% / −4% secondary. Monday 21 Sep: **missed session, recorded**, no catch-up (`/app/research/tpd3_forward/MISSED_SESSIONS.md`). |
| Roadmap v2 Phases 2–3 (§1, §3, §6, §7, §8) | Pre-registered and FROZEN (50fe02fd). Dataset builder (10758e8f) and walk-forward (a499ce19) built with synthetic tests and mutation checks. Development result (2021–22 only), `model_v5/DEV_RESULTS.md` (070cd103): movement is predictable (3–6× lift) and there is a weak directional tilt beyond volatility, but every top-5 selection loses after costs; M8 is −0.68%/trade, below random. **Owner decision 2026-09-19: H#32 CLOSED at development**; the locked test was not spent and the 2023-01..2024-07 block stays sealed. |
| Phase 4 groups A + B (§4 A–B) | Pre-registered, FROZEN ac54c1b4; single development run 2026-09-19 22:15 (`model_v5/P4_AB_RESULTS.md`). **A (market regime) DROPPED** under the frozen rule, although it had the largest trading gain (+0.40%/trade); **B (sector-relative strength) KEPT** (significant target-before-stop ranking gain, trading +0.19%/trade). No arm is profitable (best −0.28%/trade), so nothing goes to the sealed test. |
| everything else | Not started: Phase 4 groups C (breakout quality) and D (tradeability) each need their own pre-registration. |
