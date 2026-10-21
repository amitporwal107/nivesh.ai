"""Strategy plan calculation engine (PRD §16, §17.4): cash, futures and options payoff. Pure functions."""
from .engine import CALCULATION_VERSION, compute_payoff  # noqa: F401
from .plan import build_plan, explain_plan_context, normalise_inputs  # noqa: F401
from .rules import PLAN_SCHEMA, RULES, STRATEGY_RULES_VERSION  # noqa: F401
