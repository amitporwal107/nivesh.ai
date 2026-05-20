"""Unit tests for the duplicate-funds optimisation engine.

Covers Phases B (duplicate_optimizer), C (redeploy_suggester) and D
(switch_simulator).
"""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import duplicate_optimizer as dopt   # noqa: E402
from services import redeploy_suggester as redeploy  # noqa: E402
from services import switch_simulator as sim         # noqa: E402


def _two_yrs_ago():
    return (datetime.now(timezone.utc) - timedelta(days=730)).isoformat()


def _nippon_pair():
    """A realistic Regular-vs-Direct duplicate pair."""
    buy = _two_yrs_ago()
    return [
        {"asset_type": "mutual_fund", "name": "Nippon India Small Cap Regular Growth",
         "quantity": 500, "current_price": 1000, "buy_price": 700, "buy_date": buy,
         "expense_ratio": 0.0185, "sector": "Equity"},
        {"asset_type": "mutual_fund", "name": "Nippon India Small Cap Direct Growth",
         "quantity": 400, "current_price": 1000, "buy_price": 700, "buy_date": buy,
         "expense_ratio": 0.0075, "sector": "Equity"},
    ]


def _insight_for(holdings):
    return {
        "insight_id": "ins_test",
        "theme": "overlap",
        "severity": "critical",
        "title": "Nippon overlap 97%",
        "type": "warning", "impact": "high",
        "affected_funds": [h["name"] for h in holdings],
    }


# ── Phase B ──────────────────────────────────────────────────────────
class TestDuplicateOptimizer:
    def test_picks_direct_over_regular_when_lower_expense(self):
        holdings = _nippon_pair()
        plan = dopt.build_plan(_insight_for(holdings), holdings)
        assert plan is not None
        assert "Direct" in plan.keep["fund_name"]
        assert "Regular" in plan.exit["fund_name"]

    def test_token_matcher_distinguishes_regular_from_direct(self):
        """Regression: 20-char prefix matcher collapsed both variants
        into the same fund. Token-based matcher must resolve to 2."""
        holdings = _nippon_pair()
        resolved = dopt.find_holdings_for_insight(_insight_for(holdings), holdings)
        names = [h["name"] for h in resolved]
        assert "Regular" in names[0] or "Regular" in names[1]
        assert "Direct" in names[0] or "Direct" in names[1]
        assert names[0] != names[1]

    def test_capital_released_equals_exit_aum(self):
        holdings = _nippon_pair()
        plan = dopt.build_plan(_insight_for(holdings), holdings)
        # Exit is Regular at 500 × ₹1000 = ₹5L
        assert plan.capital_released_rs == 500_000

    def test_returns_none_for_non_duplicate_themes(self):
        ins = {"theme": "cost", "affected_funds": ["X"]}
        assert dopt.build_plan(ins, []) is None

    def test_returns_none_when_lt_two_holdings_resolve(self):
        ins = _insight_for(_nippon_pair())
        # Only one matching holding present
        single = _nippon_pair()[:1]
        assert dopt.build_plan(ins, single) is None

    def test_tax_impact_long_term_uses_ltcg(self):
        holdings = _nippon_pair()  # 2 years held → LTCG
        plan = dopt.build_plan(_insight_for(holdings), holdings)
        # Exit gain = (1000-700)*500 = 1.5L; LTCG = 10% × (1.5L - 1L exemption) = 5K
        assert plan.tax_impact_rs == 5_000

    def test_rationale_calls_out_expense_delta(self):
        holdings = _nippon_pair()
        plan = dopt.build_plan(_insight_for(holdings), holdings)
        joined = " ".join(plan.rationale).lower()
        assert "expense" in joined
        assert "direct" in joined


# ── Phase C ──────────────────────────────────────────────────────────
class TestRedeploySuggester:
    def test_diversification_into_debt_gold_international_for_equity_heavy(self):
        # Pure-equity ₹10L portfolio
        holdings = [
            {"asset_type": "mutual_fund", "name": "HDFC Top 100 Direct Growth",
             "quantity": 1000, "current_price": 1000, "sector": "Equity"},
        ]
        result = redeploy.suggest_redeployment(500_000, holdings)
        buckets = {a["bucket"] for a in result["allocations"]}
        assert "debt" in buckets
        assert "gold" in buckets
        assert "international" in buckets

    def test_allocations_sum_to_capital(self):
        result = redeploy.suggest_redeployment(500_000, [
            {"asset_type": "mutual_fund", "name": "HDFC Top 100",
             "quantity": 1000, "current_price": 1000, "sector": "Equity"},
        ])
        total = sum(a["rs"] for a in result["allocations"])
        assert abs(total - 500_000) < 1.0  # rounding tolerance

    def test_no_capital_returns_empty(self):
        result = redeploy.suggest_redeployment(0, [])
        assert result["allocations"] == []


# ── Phase D ──────────────────────────────────────────────────────────
class TestSwitchSimulator:
    def test_switch_only_produces_positive_wealth_delta(self):
        """Switching Regular → Direct should always yield a positive 10Y
        wealth delta after the LTCG cost — the ER spread compounds."""
        holdings = _nippon_pair()
        plan = dopt.build_plan(_insight_for(holdings), holdings)
        s = sim.simulate_switch(_insight_for(holdings), holdings, plan.to_dict(), redeploy=None)
        assert s["delta"]["projected_10y_wealth_gain_rs"] > 0

    def test_switch_only_drops_exactly_one_fund(self):
        holdings = _nippon_pair()
        plan = dopt.build_plan(_insight_for(holdings), holdings)
        s = sim.simulate_switch(_insight_for(holdings), holdings, plan.to_dict(), redeploy=None)
        assert s["delta"]["mf_count"] == -1

    def test_after_expense_ratio_lower_than_before(self):
        holdings = _nippon_pair()
        plan = dopt.build_plan(_insight_for(holdings), holdings)
        s = sim.simulate_switch(_insight_for(holdings), holdings, plan.to_dict(), redeploy=None)
        assert s["after"]["weighted_expense_ratio_pct"] < s["before"]["weighted_expense_ratio_pct"]

    def test_redeploy_simulation_uses_diversified_buckets(self):
        holdings = _nippon_pair()
        plan = dopt.build_plan(_insight_for(holdings), holdings)
        red = redeploy.suggest_redeployment(plan.capital_released_rs, holdings)
        s = sim.simulate_switch(_insight_for(holdings), holdings, plan.to_dict(), redeploy=red)
        # Allocation should have shifted away from 100% equity
        equity_after = s["after"]["allocation_pct"].get("equity", 100)
        assert equity_after < 90.0
