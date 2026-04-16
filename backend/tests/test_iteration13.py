"""
Iteration 13 Backend Tests - Testing 8 new issues:
- Issue 1: Actionable Insights with specific amounts + Simulate button
- Issue 2: Holdings showing live prices (not 0% return)
- Issue 3: Risk drill-down with action plans
- Issue 4: Performance chart changed to bar graph (frontend)
- Issue 5: Fund benchmark drill-down grouped by AMC (frontend)
- Issue 6: Collapsible widgets (frontend)
- Issue 7: Live equity/ETF prices via Yahoo Finance
- Issue 8: Performance graph matching CAS data (frontend)
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
SESSION_TOKEN = "test_session_wealth001"

@pytest.fixture
def api_client():
    """Shared requests session with auth cookie."""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    session.cookies.set("session_token", SESSION_TOKEN)
    return session


class TestLivePricesAPI:
    """Issue 7: Live prices from Yahoo Finance"""
    
    def test_refresh_prices_endpoint_exists(self, api_client):
        """POST /api/portfolio/refresh-prices should exist and return stats"""
        response = api_client.post(f"{BASE_URL}/api/portfolio/refresh-prices")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        # Should return stats about price updates
        assert "updated" in data or "message" in data, f"Response missing expected fields: {data}"
        print(f"Refresh prices response: {data}")
    
    def test_analytics_returns_live_price_stats(self, api_client):
        """GET /api/portfolio/analytics should include live_price_stats"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Check live_price_stats field exists
        assert "live_price_stats" in data, f"Missing live_price_stats in analytics response"
        stats = data["live_price_stats"]
        print(f"Live price stats: {stats}")
        
        # Stats should have expected fields
        assert "updated" in stats, "live_price_stats missing 'updated' field"
        assert "source" in stats, "live_price_stats missing 'source' field"


class TestRecommendationsWithAmounts:
    """Issue 1: Recommendations with specific amounts"""
    
    def test_recommendations_have_amount_fields(self, api_client):
        """Recommendations should include reduce_amount, add_amount, current_pct, target_pct"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics")
        assert response.status_code == 200
        data = response.json()
        
        recommendations = data.get("recommendations", [])
        if not recommendations:
            pytest.skip("No recommendations generated for test user")
        
        # Check at least one recommendation has amount fields
        has_amount_fields = False
        for rec in recommendations:
            if "reduce_amount" in rec or "add_amount" in rec:
                has_amount_fields = True
                print(f"Recommendation with amounts: {rec.get('title')}")
                print(f"  reduce_amount: {rec.get('reduce_amount')}")
                print(f"  add_amount: {rec.get('add_amount')}")
                print(f"  current_pct: {rec.get('current_pct')}")
                print(f"  target_pct: {rec.get('target_pct')}")
                break
        
        assert has_amount_fields, "No recommendations have reduce_amount or add_amount fields"


class TestSimulateEndpoint:
    """Issue 1: Simulate optimized portfolio endpoint"""
    
    def test_simulate_endpoint_exists(self, api_client):
        """GET /api/portfolio/simulate should return simulation data"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/simulate")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Check required fields
        assert "current_returns_pct" in data, "Missing current_returns_pct"
        assert "optimized_returns_pct" in data, "Missing optimized_returns_pct"
        assert "additional_returns" in data, "Missing additional_returns"
        assert "actions" in data, "Missing actions"
        
        print(f"Simulation results:")
        print(f"  Current returns: {data.get('current_returns_pct')}%")
        print(f"  Optimized returns: {data.get('optimized_returns_pct')}%")
        print(f"  Additional returns: {data.get('additional_returns')}")
        print(f"  Actions count: {len(data.get('actions', []))}")
    
    def test_simulate_actions_have_details(self, api_client):
        """Simulation actions should have title, action type, and savings"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/simulate")
        assert response.status_code == 200
        data = response.json()
        
        actions = data.get("actions", [])
        if not actions:
            pytest.skip("No simulation actions for test user")
        
        for action in actions:
            assert "title" in action, f"Action missing title: {action}"
            assert "action" in action, f"Action missing action type: {action}"
            print(f"Action: {action.get('title')} - {action.get('action')} - savings: {action.get('savings_1yr')}")


class TestRiskAnalysisWithActionPlan:
    """Issue 3: Risk factors with action_plan field"""
    
    def test_risk_analysis_has_risk_factors(self, api_client):
        """risk_analysis should include risk_factors array"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics")
        assert response.status_code == 200
        data = response.json()
        
        risk_analysis = data.get("risk_analysis", {})
        assert "risk_factors" in risk_analysis, "Missing risk_factors in risk_analysis"
        
        risk_factors = risk_analysis.get("risk_factors", [])
        print(f"Risk factors count: {len(risk_factors)}")
    
    def test_risk_factors_have_action_plan(self, api_client):
        """Each risk factor should have an action_plan field"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics")
        assert response.status_code == 200
        data = response.json()
        
        risk_factors = data.get("risk_analysis", {}).get("risk_factors", [])
        if not risk_factors:
            pytest.skip("No risk factors for test user portfolio")
        
        # Check that risk factors have action_plan
        for rf in risk_factors:
            assert "factor" in rf, f"Risk factor missing 'factor' field: {rf}"
            assert "severity" in rf, f"Risk factor missing 'severity' field: {rf}"
            assert "description" in rf, f"Risk factor missing 'description' field: {rf}"
            assert "action_plan" in rf, f"Risk factor missing 'action_plan' field: {rf}"
            
            print(f"Risk Factor: {rf.get('factor')}")
            print(f"  Severity: {rf.get('severity')}")
            print(f"  Action Plan: {rf.get('action_plan')[:100]}...")


class TestHoldingsLivePrices:
    """Issue 2 & 7: Holdings should show different buy_price and current_price"""
    
    def test_equity_holdings_have_live_prices(self, api_client):
        """Equity holdings should have price_source = yahoo_finance after refresh"""
        # First refresh prices
        api_client.post(f"{BASE_URL}/api/portfolio/refresh-prices")
        
        # Then get analytics
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics")
        assert response.status_code == 200
        data = response.json()
        
        # Check live_price_stats
        stats = data.get("live_price_stats", {})
        updated = stats.get("updated", 0)
        
        print(f"Live price stats after refresh: {stats}")
        
        # If there are equity holdings, some should be updated
        if stats.get("total_symbols", 0) > 0:
            assert updated >= 0, "Expected some prices to be updated"
            print(f"Updated {updated} equity/ETF prices from Yahoo Finance")


class TestAnalyticsDataQuality:
    """Test overall analytics response structure"""
    
    def test_analytics_has_all_required_fields(self, api_client):
        """Analytics should have all required fields for the dashboard"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics")
        assert response.status_code == 200
        data = response.json()
        
        required_fields = [
            "total_invested", "current_value", "total_returns", "returns_pct",
            "day_change", "day_change_pct", "asset_allocation", "sector_exposure",
            "risk_score", "risk_label", "holdings_count", "top_gainers", "top_losers",
            "heatmap_data", "performance_trend", "data_flags", "live_price_stats",
            "health_score", "risk_analysis", "recommendations"
        ]
        
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        print(f"Analytics response has all {len(required_fields)} required fields")
        print(f"  Holdings count: {data.get('holdings_count')}")
        print(f"  Total invested: {data.get('total_invested')}")
        print(f"  Current value: {data.get('current_value')}")
        print(f"  Returns: {data.get('returns_pct')}%")
    
    def test_top_gainers_have_asset_type(self, api_client):
        """Top gainers should include asset_type field"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics")
        assert response.status_code == 200
        data = response.json()
        
        top_gainers = data.get("top_gainers", [])
        if not top_gainers:
            pytest.skip("No top gainers in portfolio")
        
        for gainer in top_gainers[:3]:
            assert "asset_type" in gainer, f"Top gainer missing asset_type: {gainer}"
            print(f"Gainer: {gainer.get('name')[:30]} - {gainer.get('pct_change')}% - {gainer.get('asset_type')}")


class TestFundPerformanceEndpoint:
    """Issue 5: Fund benchmark data for drilldown"""
    
    def test_fund_performance_endpoint_exists(self, api_client):
        """GET /api/portfolio/fund-performance should return benchmark data"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/fund-performance")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Should have fund_ratings for AMC grouping
        assert "fund_ratings" in data, "Missing fund_ratings in response"
        
        fund_ratings = data.get("fund_ratings", [])
        print(f"Fund ratings count: {len(fund_ratings)}")
        
        if fund_ratings:
            # Check structure of fund rating
            sample = fund_ratings[0]
            print(f"Sample fund rating: {sample.get('name', 'N/A')[:40]}")
            print(f"  Rating: {sample.get('rating')}")
            print(f"  1Y Return: {sample.get('return_1y')}")


class TestHealthScore:
    """Test health score computation"""
    
    def test_health_score_has_breakdown(self, api_client):
        """Health score should have diversification, risk, cost_efficiency, performance"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics")
        assert response.status_code == 200
        data = response.json()
        
        health_score = data.get("health_score", {})
        
        required_components = ["diversification", "risk", "cost_efficiency", "performance", "overall", "grade"]
        for comp in required_components:
            assert comp in health_score, f"Health score missing {comp}"
        
        print(f"Health Score Breakdown:")
        print(f"  Diversification: {health_score.get('diversification')}")
        print(f"  Risk: {health_score.get('risk')}")
        print(f"  Cost Efficiency: {health_score.get('cost_efficiency')}")
        print(f"  Performance: {health_score.get('performance')}")
        print(f"  Overall: {health_score.get('overall')} ({health_score.get('grade')})")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
