Ten-Percent Days: Model Improvement Roadmap

Based on your recent results, the central problem is:

The model can identify stocks likely to experience large movements, but it has not demonstrated that it can predict profitable direction after costs.

The next phase should not simply add more features or screeners. It should redesign the prediction target, improve point-in-time data, and test whether the model provides calibrated, actionable probabilities for +5% and +10% moves.

1. Redesign the prediction targets

Your current model appears to focus substantially on the probability of a large move. This can produce a volatility ranking without directional value.

Separate the model into four independent prediction tasks.

Four-model architecture

Model A — Movement probability

Will the stock move at least 5% or 10%?

Model B — Direction probability

Is the move more likely to be upward or downward?

Model C — Trade outcome

Will the target be reached before stop-loss or time expiry?

Model D — Expected net return

What return remains after costs, slippage and losses?

Do not force one model to solve all four problems.

2. Define the +5% and +10% targets precisely

You need separate labels for different trade horizons.

Proposed target definitions

Assuming an entry at the next trading session’s open:

Target

	

Label definition




+5% within 1 session

	

High reaches entry × 1.05




+5% within 3 sessions

	

Maximum high reaches target within 3 sessions




+5% within 5 sessions

	

Maximum high reaches target within 5 sessions




+10% within 5 sessions

	

Maximum high reaches entry × 1.10 within 5 sessions




Directional close

	

Close exceeds entry by target percentage




Net profitable trade

	

Net P&L is positive after all costs

Critical distinction

A stock reaching +10% intraday but closing down should not be counted as a successful directional investment unless your strategy explicitly trades that intraday excursion.

Create separate labels:

hit_high_5
hit_close_5
hit_high_10
hit_close_10
hit_target_before_stop
net_positive_after_costs

This prevents the model from learning a target that does not match the trading strategy.

3. Stop optimizing only for hit rate

A high hit rate can still produce losses.

For example:

Metric

	

Strategy A

	

Strategy B




Win rate

	

60%

	

35%




Average win

	

2%

	

8%




Average loss

	

−4%

	

−2%




Expected gross return

	

−0.8%

	

+1.5%

The model must be evaluated on the complete distribution of outcomes.

Required evaluation metrics
Prediction quality

PR-AUC for rare +5% and +10% events.

ROC-AUC as a secondary metric.

Brier score.

Calibration curve.

Reliability by probability bucket.

Precision at top 1%, 5% and 10%.

Lift over the unconditional base rate.

Trading quality

Average net return.

Median net return.

Profit factor.

Maximum drawdown.

Expected value per trade.

Return after brokerage, STT, taxes where applicable and slippage.

Turnover and exposure.

Performance across market regimes.

Do not select the next model solely because its accuracy or AUC increases.

4. Investigate the negative-control problem

Your earlier findings indicate that movement is predictable, while profitable direction is not yet demonstrated.

This requires a stronger set of controls.

Required control models

Control

	

Purpose




Random selection

	

Establish baseline performance




Movement-only ranking

	

Test whether volatility alone explains results




Momentum-only model

	

Measure contribution of recent returns




Market-only model

	

Test whether Nifty movement explains the signal




Sector-only model

	

Test sector-level effects




Simple logistic regression

	

Establish a transparent baseline




Gradient boosting model

	

Test nonlinear relationships




No-signal buy-and-hold

	

Compare against passive exposure

The important comparison is:

Full model net expectancy
        versus
Simple baseline net expectancy
        versus
Matched random control

If the complex model does not outperform the simple baseline out-of-sample, additional complexity is not justified.

5. Build features around direction, not only volatility

Your existing results suggest that volatility expansion and breakouts may identify large movements without establishing direction.

Prioritize feature groups that could distinguish upside potential from downside risk.

5.1 Market regime features

Calculate these as-of the decision time:

Nifty 50 trend.

Nifty 500 trend.

Index return over 1, 5, 20 and 60 sessions.

Market breadth.

Percentage of stocks above 20-day and 50-day moving averages.

India VIX or an equivalent validated volatility measure.

Market gap and intraday trend.

Sector-relative strength.

Use regime interactions rather than only absolute values.

Example:

breakout_signal × market_trend
breakout_signal × sector_strength
gap_down × market_volatility
5.2 Stock-relative features

Absolute price movement is often less informative than performance relative to its peers.

Add:

Stock return minus sector return.

Stock return minus Nifty 500 return.

Relative strength over 5, 20 and 60 sessions.

Volume relative to its own historical average.

Volume relative to sector peers.

Distance from 20-day and 55-day highs.

ATR as a percentage of price.

Gap size relative to ATR.

Previous breakout failure count.

Relative position within the sector’s return distribution.

Do not assume these features create an edge. Each must be tested through walk-forward validation.

5.3 Event and fundamental features

Your APARINDS review identified a significant ingestion delay, with NIDP receiving results a median of approximately 36 days late.

This makes event timing and fundamentals a major data-quality priority.

Potential features:

Earnings surprise versus prior expectation, where available.

Revenue growth.

Profit growth.

Margin change.

Order-book or business-update events.

Promoter holding changes.

FII/DII changes with definition consistency.

Corporate actions.

Regulatory announcements.

Earnings announcement proximity.

Data rule

A feature should not enter the primary model unless you can establish:

information_available_at <= decision_time

Current Trendlyne values cannot be assumed to represent what was known historically.

6. Correct the data architecture before expanding features

This is probably the highest-priority engineering work.

You identified:

Fundamentals overwritten with current values.

Missing profit for a common filing tag.

Historical shareholding gaps.

Mutual-fund holdings empty.

Trendlyne historical values forward-only.

Silent blank responses.

Incomplete announcement-time evidence.

A more complex model trained on defective data can produce more convincing but unreliable results.

Required feature metadata

Every generated feature should contain:

feature_name
symbol
ISIN
period_end
available_at
decision_time
source
source_version
parser_version
calculation_version
point_in_time_class
quality_status
Feature eligibility
ELIGIBLE:
  EXACT_PIT
  PIT_VALIDATED_RULE

INELIGIBLE:
  FORWARD_ONLY
  RESTATED
  UNVERIFIED
  DATA_DEFECT

Keep exploratory features in a separate dataset rather than mixing them into the primary training set.

7. Improve the +10% prediction strategy

A +10% move within five sessions is likely to be a rarer event than a +5% move. You should not necessarily use the same model or threshold for both.

Recommended approach
Stage 1 — Candidate generation

Generate a broad candidate set using:

Liquidity filters.

Data-quality filters.

Volatility and range expansion.

Relative strength.

Validated event signals.

Market and sector regime.

Stage 2 — Probability model

Predict:

P(+5% within 5 sessions)
P(+10% within 5 sessions)
P(+5% before stop-loss)
P(net_positive after costs)
Stage 3 — Trade selection

Select trades based on expected value:

expected_value =
    probability_of_success × average_net_win
    − probability_of_failure × average_net_loss

The average win and loss must be estimated out-of-sample and conditioned on the relevant setup.

Do not use a fixed probability threshold without calibration.

8. Use a two-stage model for rare +10% events

A useful research design is:

Stage 1: Will a large movement occur?
                    ↓
Stage 2: Conditional on a large movement,
         is the direction likely to be upward?

For example:

P(upward 10% event)
=
P(large movement)
×
P(upward direction | large movement)

This is a modeling decomposition, not a guarantee that it will outperform a direct classifier.

Compare it against a direct +10% classifier using the same locked test period.

Important

The two stages must be trained without using future outcome information in the second stage’s training features. Use out-of-fold predictions when constructing any stacked or conditional model.

9. Improve training methodology
Recommended walk-forward structure
Train:      2021–2022
Validate:   2023–2024
Test:       Later locked period
Forward:    Subsequent unseen data

The exact periods should be finalized based on your actual dataset and leakage audit.

Because you noted that January 2023–July 2024 is the only untouched period, lock its use before choosing model parameters.

Walk-forward process

Train using past data only.

Validate on the next time block.

Freeze parameters.

Evaluate on the next unseen block.

Move the training window forward.

Aggregate results across all windows.

Avoid random train/test splits for time-dependent stock prediction.

10. Address class imbalance correctly

The +10% target may be rare. Accuracy will be misleading.

Use:

Precision-recall curves.

Class-weighted loss.

Calibrated probabilities.

Time-based negative sampling, if justified.

Event-level evaluation.

Threshold selection on validation data only.

Do not simply oversample positive observations randomly across time. It can distort temporal structure and create duplicate information.

Important baseline

Calculate the unconditional event rate by:

Year.

Market regime.

Sector.

Liquidity bucket.

Volatility bucket.

Entry type.

A 10% hit probability in a high-volatility segment may not be comparable with a 10% hit probability in a low-volatility segment.

11. Add probability calibration

Suppose your model outputs:

Predicted probability = 70%

That should mean that approximately 70% of comparable observations satisfy the target, within the limits of sampling uncertainty.

Use:

Isotonic regression.

Platt scaling.

Calibration by time period.

Calibration by probability bucket.

Calibration by sector and volatility regime.

Evaluate calibration on data that was not used to fit the calibration layer.

Example output

Probability bucket

	

Predicted

	

Actual




0–10%

	

7%

	

6.4%




10–20%

	

15%

	

13.8%




20–30%

	

25%

	

24.1%




30–40%

	

35%

	

29.6%

The model may be ranking reasonably but still be overconfident. Calibration helps separate those two issues.

12. Test conditional performance, not just aggregate performance

Your model may work only under specific conditions.

Create a performance matrix across:

Dimension

	

Example buckets




Market regime

	

Bull / bear / sideways




Sector

	

Financials / IT / industrials




Volatility

	

Low / medium / high




Liquidity

	

Large / medium / small




Gap

	

Gap-up / flat / gap-down




Setup

	

Breakout / pullback / recovery




Holding period

	

1–5 sessions




Target

	

+5% / +10%




Stop distance

	

1 ATR / 1.5 ATR / 2 ATR

This may reveal that the overall result is negative while a narrowly defined setup has a potentially useful signal. That setup still requires independent validation.

13. Strengthen your existing gap-down hypothesis

Your prior research showed a potentially interesting result:

Gap-down below approximately −3%.

Intraday +5% hit rate around 18.17%.

Base rate around 2.24%.

Reported intraday return around +1.86%.

This is worth investigating, but it should not yet be treated as a validated trading edge.

Required follow-up

Test separately:

Gap-down followed by recovery.

Gap-down followed by continued decline.

Gap-down with high volume.

Gap-down near support.

Gap-down during a weak market.

Gap-down after results.

Gap-down with a valid stop-loss.

Gap-down after transaction costs and slippage.

Use the same decision time and entry rule across all variants.

Avoid this mistake

Do not select the −3% threshold, recovery window and exit rule after examining the complete test period. Pre-register them or use a separate validation period.

14. Make costs and execution realistic

For a five-session positional strategy, delivery transaction charges must be included.

At minimum, simulate:

Brokerage.

STT on both delivery sides.

Exchange charges.

SEBI charges.

Stamp duty.

GST.

Applicable DP charges.

Slippage.

Gap-through-stop losses.

Test multiple cost scenarios:

Scenario

	

Purpose




Optimistic

	

Lower execution friction




Base

	

Broker-calibrated assumptions




Conservative

	

Higher slippage and adverse fills

A signal that works only under optimistic costs should not be considered robust.

15. Reduce false discovery

You reported 26 hypothesis families, with the next study potentially taking the count to 30.

This creates a substantial multiple-testing problem.

Maintain a hypothesis registry
hypothesis_id
created_at
hypothesis_description
economic_rationale
feature_version
label_definition
entry_rule
exit_rule
cost_model
validation_period
test_period
pre_registration_hash
result
decision
Rules

Do not modify a hypothesis after seeing test results without creating a new version.

Record failed hypotheses permanently.

Separate exploratory analysis from confirmatory testing.

Track the number of tested variants, not just strategy families.

Use a locked test period for final evaluation.

Treat promising results as hypotheses requiring further confirmation.

You do not necessarily need to abandon every unsuccessful strategy. But you should avoid repeatedly tuning until one result looks attractive.

16. Recommended model-development sequence
Phase 1 — Reliability first

Priority: P0

Fix or exclude DEF-6, DEF-8 and DEF-9.

Prevent silent Trendlyne blanks.

Implement complete PIT metadata.

Validate timestamp boundaries.

Confirm universe construction.

Lock the validation and test periods.

Establish a reproducible baseline.

Phase 2 — Target redesign

Priority: P0

Create separate labels for:

+5% high within 1 session.

+5% high within 5 sessions.

+10% high within 5 sessions.

+5% close within 5 sessions.

Target before stop.

Net positive after costs.

Phase 3 — Baseline models

Priority: P0

Build and compare:

Base-rate model.

Logistic regression.

Movement-only model.

Gradient boosting.

Two-stage movement/direction model.

Phase 4 — Feature improvement

Priority: P1

Add validated:

Market regime.

Sector-relative strength.

Stock-relative momentum.

Liquidity.

Event and fundamental features.

Volatility and gap context.

Add feature groups incrementally so their contribution can be measured.

Phase 5 — Trading validation

Priority: P0

Walk-forward testing.

Cost and slippage scenarios.

Random-entry controls.

Risk-adjusted evaluation.

Probability calibration.

Independent QA review.

17. Suggested success criteria

Do not define success as “the model predicts 5% moves.”

Use a staged acceptance framework.

Gate

	

Requirement




Data quality

	

No unresolved critical data defects in used features




PIT

	

All primary features eligible under approved policy




Reproducibility

	

Same inputs reproduce the same predictions




Ranking

	

Demonstrable lift over base-rate ranking




Calibration

	

Probability estimates reasonably calibrated




Trading

	

Positive net expectancy in locked out-of-sample periods




Robustness

	

Not dependent on one stock, sector or regime




Costs

	

Remains viable under base and conservative scenarios




Controls

	

Outperforms matched random and simple baselines




Stability

	

Results persist across multiple walk-forward windows

These are research gates, not claims that the model will achieve them.

18. My prioritized recommendation

If I were organizing the next implementation sprint, I would do the following in order:

Freeze the current model and dataset.

Preserve the current results as a baseline. Do not overwrite the existing model or test results.

Fix data eligibility.

Resolve the critical parser issues and exclude all unverified or forward-only features.

Create separate +5% and +10% labels.

Distinguish high-based targets, close-based targets and target-before-stop outcomes.

Build a simple directional baseline.

Compare logistic regression and movement-only predictions before adding complex AI models.

Add market and sector context.

Test regime and relative-strength features independently.

Run a locked walk-forward experiment.

Use the pre-registered validation period and compare against matched controls.

Calibrate probabilities and convert them into expected net returns.

Only then evaluate whether a probability-based trade-selection layer is justified.

Bottom line

Your next breakthrough is more likely to come from better target definitions, reliable point-in-time data, directional modeling and disciplined validation than from adding many more technical indicators.

The most useful immediate objective is not:

“Predict more 5% and 10% moves.”

It is:

Identify whether any well-defined setup produces a stable, calibrated and positive net expectancy after costs across unseen market periods.