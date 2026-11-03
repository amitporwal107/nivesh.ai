"""One 4-leg limit for every strategy path (Strategy Copilot PRD §6, §22; release blocker §19.2 "A strategy exceeding four
configured legs can bypass validation").

Covers TC-21 … TC-23 of test_reports/strategy_phase0_runs_20261028_0528.md. TC-24 (five legs refused by the paper desk
and the risk gate) is the existing `test_desk_strategy_trades.py` BAD case "five legs" and
`test_risk_gate.py::test_more_legs_than_the_policy_allows_blocks`, which must keep passing unchanged.

Pure: no network, no database, no mocks.
"""
from __future__ import annotations

from services import desk_strategy_trades, fno_margin, strategy_limits
from services.risk_gate import policy
from services.strategy_plan import model as payoff_model


def test_tc21_the_product_limit_is_one_to_four_legs():
    assert strategy_limits.MIN_STRATEGY_LEGS == 1
    assert strategy_limits.MAX_STRATEGY_LEGS == 4


def test_tc22_the_paper_desk_and_the_risk_gate_read_the_shared_limit_not_a_copy():
    assert desk_strategy_trades.MAX_LEGS is strategy_limits.MAX_STRATEGY_LEGS
    assert desk_strategy_trades.MIN_LEGS is strategy_limits.MIN_STRATEGY_LEGS
    assert policy.Limits().max_legs == strategy_limits.MAX_STRATEGY_LEGS
    assert policy.LIMITS.max_legs == strategy_limits.MAX_STRATEGY_LEGS
    # The value did not change, so stored risk decisions still read against the same policy version.
    assert policy.POLICY_VERSION == "fno-risk-v1"


def test_tc23_analysis_calculators_never_refuse_a_valid_strategy_and_keep_their_own_limits():
    # They price what a user lays out in the F&O builder or the option chain; lowering them would break 5-8 leg
    # analyses that work today. They only have to accept every valid strategy.
    assert payoff_model.MAX_LEGS >= strategy_limits.MAX_STRATEGY_LEGS
    assert fno_margin.MAX_LEGS >= strategy_limits.MAX_STRATEGY_LEGS
    assert (payoff_model.MAX_LEGS, fno_margin.MAX_LEGS) == (8, 10)
