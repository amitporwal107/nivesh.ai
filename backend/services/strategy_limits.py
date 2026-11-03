"""Product limits shared by every path that stores, paper-trades or backtests a strategy.

A strategy has 1 to 4 configured legs (Strategy Copilot PRD §6, §22: "Four; enforced by schema validator and backend,
not just UI"). A leg is a position definition, not an exchange order: two lots on one leg are still one leg.

Who reads it: the desk's paper structures (services/desk_strategy_trades.MAX_LEGS) and the risk gate's default
(services/risk_gate/policy.Limits.max_legs); the strategy validator and store follow.

Who does not, on purpose: the analysis calculators. The payoff engine (services/strategy_plan/model.MAX_LEGS = 8), the
margin calculator (services/fno_margin.MAX_LEGS = 10) and the live-quotes batch (services/kite_live_feed/fno_quotes)
price whatever a user lays out in the F&O builder or the option chain. They must never refuse a valid strategy, so their
limits are at least this one, but they are not strategy limits and lowering them would break analyses that work today.
"""
from __future__ import annotations

MIN_STRATEGY_LEGS = 1
MAX_STRATEGY_LEGS = 4
