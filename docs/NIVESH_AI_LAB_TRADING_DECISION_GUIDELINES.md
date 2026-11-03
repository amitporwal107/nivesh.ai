# Nivesh AI Lab — Complete Trading Decision Guidelines
## Entry • Stop-Loss • Position Sizing • Profit Booking • Exit • Risk Management

> **Purpose:** A practical, explainable framework for evaluating trades. This is educational and product-design guidance—not a promise of returns or a recommendation to trade a specific security. Rules and thresholds must be validated on point-in-time data and after costs before use.

---

## 1. The five decision gates

A trade should pass all five gates before it is considered eligible:

1. **Market regime:** Is the broader market supportive, bearish, range-bound, or unusually volatile?
2. **Instrument selection:** Is the stock, future, or options strategy liquid and suitable for the intended holding period?
3. **Entry setup:** Is there a defined pattern with a trigger and confirmation?
4. **Risk validation:** Can the position be sized within per-trade, portfolio, and drawdown limits?
5. **Execution validation:** Are spread, slippage, event risk, margin, and order mechanics acceptable?

A strong indicator score must never override a hard risk rejection.

## 2. Market and instrument indicators

### Market context

| Signal | What it helps assess | Example interpretation |
|---|---|---|
| Nifty vs. EMA20/50/200 | Short-, medium-, and long-term trend | Above rising averages is generally more supportive of long setups |
| ADX | Trend strength, not direction | A rising ADX can indicate strengthening trend; pair it with direction |
| India VIX | Implied volatility / uncertainty | High or rapidly rising VIX may require smaller size and wider risk allowances |
| Market breadth | Participation | Broad participation is generally healthier than a narrow rally |
| Sector relative strength | Sector leadership | Prefer candidates in sectors outperforming the benchmark |
| FII/DII flows and futures OI | Context about positioning and flows | Treat as supporting evidence; neither is a standalone direction signal |

### Instrument-level indicators

| Indicator / data | Use |
|---|---|
| EMA20 / EMA50 / EMA200 | Trend and dynamic support/resistance context |
| RSI | Momentum and potential exhaustion; avoid treating fixed levels as automatic buy/sell signals |
| ADX / +DI / -DI | Trend strength and directional context |
| ATR / ATR% | Volatility-aware stops and position sizing |
| Relative strength vs. benchmark | Identify outperformers or underperformers |
| Relative volume (RVOL) | Assess whether participation supports the move |
| Support / resistance and swing structure | Define setup, trigger, and invalidation |
| Liquidity, spread, event calendar | Determine whether execution is practical |

## 3. Illustrative setup score

A scoring model can help rank candidates, but it must not replace eligibility rules or risk checks.

| Component | Illustrative weight |
|---|---:|
| Market regime | 15 |
| Trend quality | 20 |
| Relative strength | 15 |
| Momentum | 15 |
| Volume confirmation | 15 |
| Price setup quality | 20 |
| **Total** | **100** |

These weights are examples only. Calibrate them through out-of-sample research. Reject a trade if its stop is unclear, liquidity is inadequate, or portfolio risk is exceeded—even if its score is high.

## 4. Entry rules

### Breakout
- Identify a well-defined resistance level or consolidation boundary.
- Require a close or defined intraday trigger above the level.
- Confirm with relative volume, trend context, and preferably sector/benchmark strength.
- Avoid chasing a large gap or an entry whose stop makes the risk/reward unattractive.
- Define the invalidation level before placing the order.

### Pullback in an uptrend
- Confirm the broader trend is intact (for example, price above a rising EMA50).
- Look for a pullback toward a prior support, EMA, or breakout retest.
- Wait for a reversal/continuation trigger rather than buying solely because price touched an average.
- Place the stop below the setup’s structural invalidation, with volatility allowance where appropriate.

### Momentum continuation
- Require trend alignment, positive relative strength, and evidence of renewed momentum.
- Use volume and price structure to distinguish continuation from an exhausted move.
- Avoid entering after an extended move if the stop distance produces poor reward-to-risk.

### Breakdown / short setup
- Define support and require a valid breakdown trigger.
- Confirm weakness with relative strength, volume, and market/sector context.
- Define the stop above the breakdown/retest structure.
- Check applicable short-selling, product, broker, and exchange constraints.

## 5. Stop-loss methods

Choose a stop method that matches the strategy and market structure.

### Structural stop
Place the stop beyond the price level that invalidates the setup, such as:
- Below a swing low for a long.
- Above a swing high for a short.
- Beyond the failed-breakout or retest structure.

### ATR-based stop
For a long, an illustrative formula is:

`Stop = Entry − (ATR × multiplier)`

For a short:

`Stop = Entry + (ATR × multiplier)`

The multiplier depends on the strategy and timeframe and must be tested. ATR is a volatility measure, not a guarantee that the stop will fill at its price.

### Capital-risk stop
The maximum acceptable loss determines quantity—not the other way around.

`Risk per share = |Entry − Stop|`

`Quantity = floor(Maximum trade risk ÷ Risk per share)`

Then round quantity down to the permitted lot size or quantity increment. Include fees, taxes, spread, and realistic slippage in the risk estimate.

**Do not widen a stop after entry to avoid realizing a loss.** A stop order can also fill worse than its trigger price during gaps or fast markets.

## 6. Position sizing and portfolio risk

Before entry, check:
- Maximum rupee risk per trade.
- Total open risk across positions.
- Correlation and concentration across holdings.
- Daily and weekly loss limits.
- Portfolio drawdown and available margin.
- Whether the position remains acceptable under a gap/slippage stress scenario.

For options, calculate the strategy’s maximum loss and breakeven from the full multi-leg payoff. For defined-risk spreads, premium/debit and contract multiplier determine maximum loss at expiry, but early exits, liquidity, and execution costs can change realized outcomes.

## 7. Exit and profit-booking rules

Define exits before entering. A trade can use one primary exit rule and secondary safeguards.

### Fixed risk-multiple targets
Let `R` be the initial per-unit risk.

- `1R` = entry-to-stop distance.
- `2R` target = entry plus/minus two times initial risk.
- `3R` target = entry plus/minus three times initial risk.

Targets are planning levels, not guarantees. Consider partial exits only if the strategy’s tested rules support them and the remaining position has a clear stop.

### ATR trailing stop
For a long, an illustrative trailing rule is:

`Trailing stop = Highest price since entry − (ATR × multiplier)`

For a short:

`Trailing stop = Lowest price since entry + (ATR × multiplier)`

A trailing stop should move only in the direction that reduces risk; it should not be loosened to accommodate adverse movement.

### Trend / momentum exit
Examples include:
- Close below a strategy-defined moving average.
- A confirmed break of the latest higher low.
- Momentum deterioration together with price weakness.
- A failed breakout that closes back below the breakout level.

Use a clear trigger and timeframe. Avoid exiting solely because one indicator briefly crosses a threshold.

### Time exit
If the expected move does not occur within the strategy’s holding window, exit or reassess according to a predefined rule. Time exits are especially relevant for short-term setups and options where time decay matters.

### Mandatory safeguards
- Honor the initial risk plan.
- Respect daily/weekly loss and portfolio drawdown limits.
- Do not average down unless the strategy explicitly permits it, has been tested, and remains within the original total risk budget.
- Do not reverse a stopped trade without a new, independently valid setup.

---

## 8. Worked examples

All names, prices, and quantities below are hypothetical. They illustrate arithmetic and decision structure, not live trade ideas. Quantities omit transaction costs unless noted.

### Example A — Positional breakout

Assume:
- Resistance: ₹1,000
- Triggered entry: ₹1,005
- Structural stop: ₹970
- Maximum trade risk: ₹3,000

Calculations:
- Risk per share = ₹1,005 − ₹970 = **₹35**
- Quantity = floor(₹3,000 ÷ ₹35) = **85 shares**
- Approximate planned risk = 85 × ₹35 = **₹2,975**
- 2R target = ₹1,005 + (2 × ₹35) = **₹1,075**
- 3R target = ₹1,005 + (3 × ₹35) = **₹1,110**

Decision:
- Enter only if the breakout trigger and confirmation occur.
- If price gaps far above ₹1,005, recalculate risk/reward rather than chasing.
- If the stop is hit, exit according to the plan; do not widen it.

### Example B — Pullback in an uptrend

Assume:
- Price: ₹880
- EMA20: ₹875
- EMA50: ₹850
- EMA200: ₹810
- Entry after a valid reversal trigger: ₹882
- Structural stop: ₹868
- Maximum risk: ₹2,500

Calculations:
- Risk per share = ₹14
- Quantity = floor(₹2,500 ÷ ₹14) = **178 shares**
- Approximate planned risk = ₹2,492
- 2R target = ₹882 + ₹28 = **₹910**

The moving averages provide context; the actual entry requires a price trigger and the stop must correspond to setup invalidation.

### Example C — Intraday opening-range breakout

Assume:
- Opening range high: ₹520
- Opening range low: ₹510
- Entry trigger: ₹522
- ATR reference: ₹2.50
- Stop: ₹517
- Maximum risk: ₹2,000

Calculations:
- Risk per share = ₹5
- Quantity = floor(₹2,000 ÷ ₹5) = **400 shares**
- 2R target = ₹532

Confirm that the breakout is not a low-volume false move and that spread/slippage are acceptable. If price returns inside the range and invalidates the setup, follow the predefined exit.

### Example D — Bearish breakdown

Assume:
- Support: ₹680
- Breakdown entry: ₹675
- Stop: ₹686
- Maximum risk: ₹2,500

Calculations:
- Risk per share = ₹11
- Quantity = floor(₹2,500 ÷ ₹11) = **227 shares**
- Approximate planned risk = ₹2,497
- 2R target = ₹675 − ₹22 = **₹653**

Short-selling availability and restrictions vary by instrument and market rules. Confirm product eligibility and broker requirements before acting.

### Example E — Futures long buildup

Illustrative context:
- Price rising and open interest rising may be consistent with long buildup.
- This is not conclusive by itself; interpret it with price structure, volume, basis, and broader context.

Assume:
- Futures entry: ₹1,250
- Stop: ₹1,225
- Lot size: 100
- Maximum risk per lot: ₹2,500

Risk per lot = ₹25 × 100 = **₹2,500**.  
A 2R target would be ₹1,300.

Check margin, expiry, basis, liquidity, and gap risk. Open interest alone does not establish direction or intent.

### Example F — Bull call spread

Assume one lot with multiplier 50:
- Buy 25,000 call at ₹220
- Sell 25,200 call at ₹130
- Net debit = ₹90 per unit

At expiry:
- Maximum loss = ₹90 × 50 = **₹4,500**
- Maximum gain = (₹200 − ₹90) × 50 = **₹5,500**
- Breakeven = 25,000 + ₹90 = **25,090**

If the trade risk budget is ₹2,500, this one-lot position exceeds the budget and should be rejected or resized only if the instrument permits it. Monitor the spread as a whole, including combined Greeks, volatility, time to expiry, liquidity, and exit costs.

### Example G — Failed breakout

Assume:
- Entry: ₹1,005
- Stop: ₹970
- Quantity: 71 shares

Planned risk = ₹35 × 71 = **₹2,485**, before costs. If price fails and reaches the stop, execute the planned exit. Do not average down or reverse without a new setup and fresh risk calculation.

### Example H — ATR trailing stop

Assume:
- Entry: ₹1,000
- Initial stop: ₹970
- ATR reference: ₹20
- Trailing multiplier: 2
- Highest price since entry: ₹1,080

Illustrative trailing stop = ₹1,080 − (2 × ₹20) = **₹1,040**.

This is an example only. Specify whether ATR is recalculated each bar and whether the stop updates at bar close or intrabar; those choices materially affect backtest results.

---

## 9. Options-specific checks

For options strategies, evaluate the position as a complete strategy rather than treating each leg independently.

Before entry:
- Plot payoff at expiry and, where available, scenario P&L before expiry.
- Calculate maximum loss, maximum profit, breakeven, and margin.
- Review delta, gamma, theta, vega, IV rank/percentile, and expected move.
- Check bid/ask spread, depth, legging risk, expiry, and event risk.
- Define whether exit is based on underlying price, strategy P&L, Greeks, time, or a combination.
- Avoid relying on a single-leg stop when the spread’s combined risk is what matters.

## 10. Trade lifecycle

A practical state machine:

`NO_SETUP → WAIT_FOR_CONFIRMATION → TRADE_ELIGIBLE → ENTRY_TRIGGERED → POSITION_OPEN → EXIT_PENDING → CLOSED`

Other terminal state:
- `REJECTED` — a hard rule failed.

At every transition, record:
- Strategy and rule version.
- Instrument and timeframe.
- Signal timestamp and data timestamp.
- Entry, stop, target, quantity, and estimated costs.
- Supporting evidence and invalidation condition.
- Risk checks and rejection reasons.
- Actual fills, slippage, and exit reason.

## 11. Conceptual evaluation pseudocode

```python
def evaluate_trade(candidate, market, portfolio, config):
    if not candidate.has_valid_setup:
        return reject("No valid setup")

    if not market.regime_allowed(candidate.strategy):
        return reject("Market regime not allowed")

    if not candidate.liquidity_pass:
        return reject("Liquidity or spread constraint failed")

    entry = candidate.trigger_price
    stop = candidate.invalidation_price

    if entry is None or stop is None:
        return reject("Entry or stop is undefined")

    risk_per_unit = abs(entry - stop)
    if risk_per_unit <= 0:
        return reject("Invalid risk distance")

    quantity = floor(config.max_trade_risk / risk_per_unit)
    quantity = round_down_to_lot(quantity, candidate.lot_size)

    if quantity <= 0:
        return reject("Risk budget cannot support minimum size")

    estimated_risk = estimate_total_risk(
        entry, stop, quantity, candidate.cost_model
    )

    if estimated_risk > config.max_trade_risk:
        return reject("Trade risk limit exceeded")

    if portfolio.open_risk + estimated_risk > config.max_portfolio_risk:
        return reject("Portfolio risk limit exceeded")

    if portfolio.daily_loss >= config.daily_loss_limit:
        return reject("Daily loss limit reached")

    return eligible(
        entry=entry,
        stop=stop,
        quantity=quantity,
        estimated_risk=estimated_risk,
        target=derive_target(entry, stop, config.target_rule),
        explanation=candidate.explanation,
    )
```

This is conceptual pseudocode, not production-ready execution code. Production systems need broker-specific order handling, concurrency controls, retries, reconciliation, audit logs, and failure-safe behavior.

## 12. Backtesting and validation checklist

Before promoting a strategy to paper trading or live use, validate:

- Point-in-time data and correct signal timestamps.
- No look-ahead bias or survivorship bias.
- Realistic fees, taxes, spread, slippage, and market impact.
- Gap-through-stop and partial-fill behavior.
- Corporate actions, symbol changes, expiry rolls, and delisted securities where relevant.
- Out-of-sample tests and walk-forward evaluation.
- Multiple market regimes and sufficient trade count.
- Sensitivity to thresholds and costs.
- Paper trading with realistic order and fill assumptions.

Track at minimum:
- Net expectancy per trade and per session.
- Win rate, average win, average loss, and payoff ratio.
- Profit factor and maximum drawdown.
- Sharpe / Sortino where appropriate.
- Exposure, turnover, and capital usage.
- Slippage sensitivity and rejected-signal coverage.

A positive backtest is not proof of future profitability. If results disappear after costs, modest parameter changes, or out-of-sample evaluation, do not deploy the strategy.

## 13. Suggested MVP rule families

Start with a small, interpretable set:
1. Breakout with confirmation.
2. Pullback in a confirmed trend.
3. Momentum continuation.
4. Breakdown / bearish setup where permitted.

Support:
- Structural and ATR-based stops.
- Risk-based sizing.
- Fixed-R targets and tested trailing exits.
- Time exits and portfolio-level risk exits.
- Options defined-risk strategy evaluation.

Avoid adding many indicators simply to increase apparent confidence. Prefer a few signals with distinct, tested information.

## 14. Nivesh AI Lab trade decision card

Every candidate should display:

- **Setup:** strategy name and timeframe.
- **Status:** watch / eligible / rejected / triggered / open / closed.
- **Entry:** trigger and order type.
- **Stop:** price, method, and invalidation rationale.
- **Targets:** levels and R multiples.
- **Position size:** quantity / lots.
- **Estimated risk:** rupee risk and percentage of portfolio.
- **Costs:** estimated spread, fees, taxes, and slippage.
- **Evidence:** market regime, trend, relative strength, momentum, volume, structure.
- **Risks:** event, liquidity, gap, concentration, and correlation.
- **Exit plan:** stop, target, trailing, time, and emergency rules.
- **Audit:** rule version, timestamps, and explanation.

Avoid presenting only “BUY — 82% confidence.” Explain why the setup qualifies, what invalidates it, and what can be lost.

## Core principle

**The entry identifies an opportunity; the stop defines invalidation; position sizing controls planned risk; the exit follows a tested rule.** Never increase risk merely because a model score or expected profit looks attractive.
