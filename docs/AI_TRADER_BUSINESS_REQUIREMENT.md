# Nivesh AI Trader — Business Requirement

> **Status:** Business requirement captured 2026-10-21 (verbatim intent from the product owner's brief; not yet a PRD or implementation plan).
> **Next step:** derive a PRD from `docs/PRD_TEMPLATE.md`, reconcile with `docs/INTEGRATED_STOCK_ENGINE_DESIGN.md`, `docs/SMART_TRADING_DESK_FUNCTIONALITY.md` and `docs/smart_trader/`.
> Editorial note: the pasted source contained rendering CSS for a Mermaid diagram; that was dropped and the diagram is restated as the text flow in §4.

## Goal

Build a trader that thinks, analyses, plans and manages risk like a professional: a **unified AI trading intelligence system** that combines the skills of a market analyst, fundamental analyst, technical analyst, chart reader, derivatives specialist, strategy designer and risk manager.

Design principle: a real trader does not look at every data point independently. They build a coherent view of the market, identify what is changing, decide which opportunities are supported by evidence, and decide whether the reward justifies the risk.

Architecture: specialist analytical engines + a shared market understanding (evidence model) + a strategy decision engine + an **independent risk governor**.

## 1. How a real trader thinks — six ordered questions

| # | Question | Looks at | Output |
|---|---|---|---|
| 1 | What is the market telling me? | Regime, breadth, sector rotation, volatility, institutional activity, global cues, upcoming events | Market context and directional scenarios |
| 2 | Where is the opportunity? | Improving momentum, favourable structure, catalysts, relative strength, potential reversals | Ranked opportunities and watchlists |
| 3 | Does the evidence support the trade? | Fundamentals, chart structure, indicators, volume, price action, derivatives positioning | Trade thesis with supporting **and contradicting** evidence |
| 4 | Which strategy fits? | Breakout, pullback, trend continuation, reversal, mean reversion, intraday momentum, futures, options structures | Strategy, entry trigger, exit conditions |
| 5 | Is the trade worth the risk? | Position size, expected payoff, stop distance, portfolio exposure, correlation, liquidity, costs, gap risk | Approved / reduced / rejected / deferred |
| 6 | What do I do after entering? | Thesis monitoring, exits, new information, outcome vs. rules | Hold, add only if permitted, reduce, exit or hedge |

These form **one** decision process. A bullish indicator is not a buy instruction if the market is deteriorating, the trade is overcrowded, or the downside is unacceptable.

## 2. Seven specialist capabilities

### Skill 1 — Market Intelligence Analyst
- **Reads:** index structure (Nifty 50, Bank Nifty, broader indices; trend and key levels); market breadth (advances/declines, new highs/lows, stocks above moving averages); sector rotation (relative performance, leadership, improving/weakening sectors); volatility and flows (volatility regime, futures positioning, available flow data, liquidity).
- **Reasons about:** trending vs range-bound; broad participation vs a few heavyweights; sectors gaining relative strength; whether volatility expansion favours momentum or creates unacceptable risk; whether upcoming events invalidate otherwise attractive setups.
- **Produces:** a timestamped market-regime classification, directional scenarios, sector ranking, volatility assessment, evidence, contradictions, and the conditions that would change the view.
- **Example rule:** a rising Nifty with declining breadth must not be read as a strong bullish market; recognise the divergence, investigate concentration, and reduce the strength of any broad-market conclusion.

### Skill 2 — Fundamental Analyst
Question answered: *is there a credible business or earnings reason for this stock to outperform, and is it already reflected in the price?*

- **Financial statements:** revenue, operating profit, margins, cash flows, debt, working capital, capex.
- **Business quality:** competitive position, customer concentration, industry dynamics, management execution.
- **Profitability:** ROE, ROCE, ROIC, consistency of earnings.
- **Valuation:** P/E, EV/EBITDA, P/B, FCF yield, sector-appropriate comparisons.
- **Growth and expectations:** quarterly results, guidance, order book, earnings revisions, catalysts.
- **Ownership and governance:** promoter pledges, shareholding changes, related-party transactions, material disclosures.
- **Corporate events:** dilution, acquisitions, demergers, auditor changes, regulatory developments, other material risks.
- Must distinguish **reported facts from estimates and interpretations**; must not infer a healthy business solely from a low P/E or strong revenue growth.

| Finding | Trading implication |
|---|---|
| Improving earnings and price strength | May support a positional trend strategy |
| Good business, weak price structure | Watchlist candidate; not automatically a buy |
| Strong breakout, deteriorating fundamentals | Potentially tradable short-term, with elevated event and thesis risk |
| Expensive valuation and negative earnings revisions | Greater caution on longs |
| Material governance or regulatory concern | Potential exclusion or stricter risk controls |

Fundamentals matter more for multi-day/multi-week decisions than for a five-minute trade; their influence depends on the strategy's holding period.

### Skill 3 — Technical Analyst and Chart Reader
Must interpret the relationship between price, time, volume and market structure — not merely calculate indicators.

- **A. Market structure:** HH/HL, LH/LL, consolidation, range boundaries, swing points, trend breaks, structural invalidation.
- **B. Support/resistance and price action:** price zones, breakout and retest behaviour, rejection wicks, failed breaks, gaps, acceptance/rejection near key levels.
- **C. Volume and participation:** volume vs historical baseline, ordinary vs unusual activity, whether a breakout has meaningful participation.
- **D. Indicators:** moving averages, RSI, MACD, ATR, ROC, relative strength, VWAP, volume-derived measures — *supporting evidence, not independent trade commands*.
- **Patterns** (flags, triangles, wedges, double tops/bottoms, head-and-shoulders, cup-and-handle, volatility compression) must be validated with explicit rules. Each pattern has: a defined formation and timeframe; a measurable trigger (not visual resemblance); confirmation conditions; a price-based invalidation level; historical performance and failure statistics; a confidence assessment **calibrated against actual outcomes**.
- **Multi-timeframe analysis is essential.** E.g. a 5-minute bullish breakout inside a strong daily downtrend: the bot must either choose a strategy that tolerates the conflict or reject the trade.

### Skill 4 — Futures and Options Specialist
Reasons about derivatives independently of the cash chart.

- Futures vs spot, basis, open interest and OI change; price/OI combinations are *possible positioning signals, not definitive evidence of intent*.
- Options chain liquidity, bid–ask spreads, implied volatility, Greeks, skew, expiry.
- Lot sizes, margin requirements, expiry schedules, instrument eligibility.
- Payoff diagrams, breakevens, maximum loss where defined, tail risk where losses are potentially large.
- Hedging relationships between cash portfolio, futures and options.
- Must distinguish an attractive **directional view** from an attractive **derivatives trade** (a bullish stock may have options that are too expensive, illiquid or poorly structured).

### Skill 5 — Strategy Architect
Translates evidence into a formal, testable strategy. For every proposed strategy define:
1. Market conditions in which it is eligible.
2. Instrument universe and liquidity requirements.
3. Entry trigger and confirmation criteria.
4. Initial stop and exit rules.
5. Position sizing and maximum portfolio allocation.
6. Holding period, time stop and event restrictions.
7. Expected transaction costs and execution assumptions.
8. Backtest methodology, out-of-sample validation and acceptance criteria.

AI may propose and compare hypotheses, but each candidate must become **reproducible rules and be tested before it may generate live trade instructions**.

### Skill 6 — Risk Manager
**Has veto power over every strategy, including the highest-ranked model prediction.**

- Evaluates trade-level risk, total portfolio exposure, sector concentration, correlation, leverage, margin, liquidity, gaps, overnight events, daily loss limits, drawdown limits.
- Scenario analysis: sharp index drop, volatility spike, correlated stocks falling together, stop that cannot be executed near its intended price.
- Output is a **concrete decision**, not just a score: approve, reduce size, hedge, defer, reject, or halt new trading — with reasons.

### Skill 7 — Execution and Learning Specialist
- Manages order states, partial fills, rejected orders, broker reconciliation, slippage, transaction costs, protective exits, connectivity failures.
- Compares expected vs actual performance; attributes losses to strategy quality, market regime, execution or risk sizing; recommends changes **for formal testing**.
- **Must never silently rewrite live strategy rules based on a few recent wins or losses.**

## 3. Making the skills work together

The seven specialists must not behave as seven independent chatbots with conflicting recommendations. They share an evidence model and a formal decision process.

**Illustrative investigation (hypothetical, not a live signal):** NSE stock at ₹500, prior resistance ₹495.
- Market intelligence: sector outperforming, breadth improving.
- Fundamentals: earnings and margins improving, no material negative catalyst in available data.
- Technicals: price crossed resistance, but candle close, volume confirmation and hold must be verified.
- Derivatives: inconclusive; do not assume a derivatives position is attractive because the cash setup is bullish.
- Risk: proceed only if stop, size, portfolio exposure, costs and reward-to-risk meet limits.
- **Decision: wait for confirmation, then reassess.** The system preserves the distinction between a promising stock and an executable trade.

### Shared evidence model (single structured record per piece of evidence)
| Field | Meaning |
|---|---|
| Observation | What actually happened in the data |
| Interpretation | What it could mean |
| Confidence | Reliability, based on validation |
| Contradictions | Evidence that challenges the conclusion |
| Conditions | What would confirm or invalidate it |
| Time horizon | How long the conclusion stays relevant |
| Source and timestamp | Where it came from, when it was valid |
| Decision impact | Whether it changes eligibility, ranking, sizing or exit conditions |

"Volume increased" is an observation; "institutional buying is occurring" is an interpretation that volume alone cannot establish. The system must preserve that distinction.

## 4. End-to-end workflow

```
Real-time and EOD data
  -> Data quality and normalization
  -> Market intelligence and regime
  -> Universe selection
  -> [Fundamental analysis | Technical and chart analysis | Derivatives and positioning analysis]
  -> Shared evidence model
  -> Strategy eligibility and selection
  -> Entry and exit plan
  -> Independent risk governor
  -> Approved?
       No  -> Reject, defer or resize (loops back to the plan)
       Yes -> Paper, assisted or authorized live mode
  -> Order and position management
  -> Reconciliation and performance analysis
  -> Strategy monitoring and controlled retraining
```

- **Event-driven**, with different refresh rates per data type: a tick may update a 5-minute signal immediately; a quarterly result triggers fundamental reassessment; an EOD update recalculates daily indicators and positional setups.
- Must not rerun every specialist on every tick: reuse valid cached results, update only affected features, trigger deeper reasoning on material events.

## 5. Three kinds of intelligence (separate them)

| Kind | Cadence | What | Implementation |
|---|---|---|---|
| A. Fast analytical | Real time | Indicators, candle patterns, volume changes, relative strength, breadth, price levels, position risk, trigger conditions | Python services, streaming processors, indicator libraries, deterministic rules |
| B. Deep analytical | Event-driven | Financial results, news, chart context, conflicting evidence, strategy suitability, unusual market events | LLM reasoning grounded in structured data, source documents and verified calculations |
| C. Independent control | Mandatory | Capital limits, permissions, instrument restrictions, exposure constraints, order-state safety, emergency procedures | Deterministic risk service, authorization checks, auditable state machines |

An LLM must not inspect millions of ticks, compute indicators from raw text, or enforce hard risk limits by reasoning. It interprets reliable computed evidence and explains decisions.

## 6. Chart-reading protocol (applied to every chart)
1. **Establish context** — instrument, timeframe, session, benchmark, market regime.
2. **Read structure** — swing highs/lows, trend, ranges, support/resistance, gaps.
3. **Interpret latest price action** — candle closes, wicks, range expansion, breakout attempts, failed moves.
4. **Examine participation** — volume vs baseline, relative strength.
5. **Check indicator alignment** — MAs, momentum, volatility as corroboration.
6. **Compare timeframes** — intraday vs hourly vs daily conflicts.
7. **Build scenarios** — bullish, bearish, neutral, and the evidence that distinguishes them.
8. **Convert to a plan** — trigger, invalidation, stop, target, quantity, no-trade conditions.

Pattern *detection* is a hypothesis; a qualifying breakout with required volume, price behaviour and risk profile may become a tradable setup. **Retain the candle and indicator evidence that caused each pattern detection** for historical validation and explaining false positives.

## 7. Proving proficiency (measurable competency tests)

| Capability | How to test |
|---|---|
| Market intelligence | Regime classifications and sector rankings vs subsequent, correctly time-aligned outcomes |
| Fundamental analysis | Extracted facts vs original filings; conclusions use only information available at decision time |
| Chart reading | Detected structures/levels vs predefined reproducible labels; false-positive evaluation |
| Strategy design | Reproducibility, look-ahead bias, overfitting, after-cost expectancy |
| Risk management | Simulations of gaps, correlated losses, margin stress, rejected orders, breached limits |
| Execution | Partial fills, duplicate submissions, delayed acks, disconnections, broker reconciliation |
| Adaptation | Performance across distinct regimes; detect deterioration without uncontrolled live rule changes |
| Explainability | Reconstruct any decision from original data snapshot, rule versions and risk checks |

- Use chronological out-of-sample testing, walk-forward evaluation and a **sealed holdout period**; the model must never see future prices or outcomes when creating historical analysis.
- **Calibration:** a stated probability (e.g. "60% to reach target before stop") must be supported by sufficiently numerous comparable observations — never a subjective LLM confidence score.

## 8. Recommended phasing
Each phase builds on the same shared evidence schema and trade lifecycle — no separate, disconnected decision engines.

1. **Market and chart literacy** — regime, breadth, sector rotation, multi-timeframe structure, indicators, explainable chart-pattern detection.
2. **Fundamentals and catalysts** — financial statements, results, valuation, corporate events, ownership changes, source-grounded news interpretation.
3. **Strategy intelligence** — strategy library, regime-based eligibility, formal entry/exit rules, historical testing, candidate ranking.
4. **Risk-first trading lifecycle** — independent risk governor, sizing, paper trading, position management, broker reconciliation, emergency controls.
5. **Derivatives and controlled autonomy** — futures/options payoff analysis, volatility and expiry risk, portfolio hedging, and eventually constrained autonomous execution after required validation.

## 9. Success definition
Build Nivesh's AI trader as a professional trading workflow encoded in software: AI interprets, investigates and explains; quantitative models estimate probabilities; deterministic strategies define what qualifies; an independent risk governor controls what is allowed.

The defining capability is not the number of agents or indicators, but whether the system can consistently:
- Read the market in context.
- Understand the business and technical evidence.
- Identify a suitable, validated strategy.
- Recognise conflicting signals and uncertainty.
- Calculate an acceptable risk and position size.
- Manage the trade safely through its entire lifecycle.
- Demonstrate, with reproducible evidence, whether it has a durable trading edge.

It must be disciplined enough to know when its evidence is insufficient and when the safest decision is not to trade.

## 10. Strategy creation and execution (added 2026-10-21)

**Requirement (product owner):** the AI trader must not only analyse; it must also **create strategies and execute them**, using the Strategy Builder defined in [STRATEGY_BUILDER_CONFIG_SPEC.md](STRATEGY_BUILDER_CONFIG_SPEC.md).

How this fits the architecture above:
- **Creation (Skill 5, Strategy Architect):** the AI proposes a strategy as a `strategy.py` (`strategy_info(config)` + `@nv.strategy()` handler) with a `NiveshConfig` (symbols, capital, commission, pyramiding, short margin, custom parameters). Each candidate is stored with its config, is reproducible, and must pass backtest and out-of-sample validation before it may generate live instructions (§2 Skill 5, §7).
- **Execution (Skill 7 + §5C control intelligence):** every order the strategy emits goes through the independent risk governor (approve / reduce / hedge / defer / reject / halt) before it reaches a broker. The LLM never bypasses or overrides the governor, and never edits a live strategy's frozen config or code; changes are new, versioned, re-validated candidates.
- **Modes (Phase 4/5 gating):** backtest → paper → assisted (user confirms each order) → constrained autonomous live. Each promotion is an explicit, logged, user-authorised step.
- **Provenance:** every run, paper trade and live order records the frozen resolved config, strategy code hash, rule/model versions and the risk-governor decision (§7 Explainability).

**Known conflicts with the current codebase (to resolve in the PRD, not assumed):**
1. Brokers are read-only today by design (`backend/services/brokers/zerodha.py` never calls place/modify/cancel order; the desk "never places, changes or cancels an order"). Live execution reverses that decision and needs an explicit owner decision, broker order APIs, an order-state machine, reconciliation, a kill switch, and SEBI/regulatory review (algo-trading rules, API/algo registration, static-IP and audit requirements).
2. The repo's `backend/services/strategy_engine` uses a declarative DSL; this spec runs user/AI-written **Python in a sandbox**. Decide: keep the DSL as the AI's primary target and compile to it, or build the Python sandbox (code-execution security is then in scope).
3. The repo's own measured results show **no validated edge** in current signals (0 of 8 entry setups validated; walk-forward paper-trade verdict FAIL). The AI must not promote any strategy to assisted or live mode until it clears the out-of-sample acceptance criteria in §7.

### Decisions recorded 2026-10-21 (product owner)
1. **Execution scope for the first release: backtest → paper → assisted only.** No autonomous live order placement yet; brokers stay read-only until a separate, explicit decision.
2. **Build location: the desk worktree** (`/home/deploy/nivesh-trading-desk`, branch `feat/trading-desk-backend`), not the `feat/provider-foundations` checkout.
3. **OPEN:** AI strategy target — existing declarative DSL (`strategy_engine`) vs Python sandbox (not yet answered).
4. **OPEN:** PRD scope — all five phases vs Phase 1 in detail (recommended: Phase 1 in detail).
