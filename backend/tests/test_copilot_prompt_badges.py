"""Suggested-prompt badges are facts about the user's portfolio, so a user with no portfolio gets none
(routes/copilot_prompts.py scorers; audit of 30 Oct: "Equity 0% · Debt 0%" and "Debt gap — only 0%" were ranked for a
user with no holdings, and Home showed them as FACT cards).

MOCK — not real data: the contexts below are invented; the scorers are the real ones.
"""
from __future__ import annotations

import pytest

from routes import copilot_prompts as cp

# What _build_context starts from and keeps when the user has no portfolio and no plan.
EMPTY = {"total_value": 0, "equity_pct": 0, "debt_pct": 0, "gold_pct": 0, "other_pct": 0, "max_overlap_pct": 0,
         "overlap_pair_count": 0, "top_overlaps": [], "top_amc_name": None, "top_amc_pct": 0, "top_amcs": [],
         "action_count": 0, "has_exit_actions": False, "plan_tax_liability": 0, "underperformer_count": 0, "fund_count": 0}


@pytest.mark.parametrize("tpl", cp._PROMPT_TEMPLATES, ids=lambda t: t["id"])
def test_no_portfolio_gives_no_badge(tpl):
    _, badge = tpl["scorer"](dict(EMPTY))
    assert badge is None, (tpl["id"], badge)


def test_a_total_without_a_known_mix_gives_no_allocation_badge():
    ctx = {**EMPTY, "total_value": 250000}                       # value known, asset mix not
    assert cp._score_risk_alloc(ctx)[1] is None and cp._score_add(ctx)[1] is None


def test_an_amc_share_without_a_name_gives_no_badge():
    assert cp._score_concentration({**EMPTY, "total_value": 1, "top_amc_pct": 18})[1] is None


def test_a_real_portfolio_still_gets_its_figures():
    ctx = {**EMPTY, "total_value": 1000000, "equity_pct": 93.0, "debt_pct": 0.0, "other_pct": 7.0,
           "top_amc_name": "HDFC", "top_amc_pct": 31.0}
    assert cp._score_risk_alloc(ctx) == (90, "Equity 93% · Debt 0%")
    assert cp._score_add(ctx) == (75, "Debt gap — only 0%")
    assert cp._score_concentration(ctx) == (85, "HDFC 31%")
