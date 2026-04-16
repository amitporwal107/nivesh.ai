"""
Iteration 14 Backend Tests - Bug Fixes Verification
Tests for: Issue 2 (Heatmap %), Issue 3 (AI Insights descriptions), Issue 4 (SGB prices)
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
SESSION_TOKEN = "test_session_wealth001"

@pytest.fixture
def api_client():
    """Shared requests session with auth cookie"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    session.cookies.set("session_token", SESSION_TOKEN)
    return session


class TestIssue2HeatmapPercentages:
    """Issue 2: Heatmap should show actual percentage numbers"""
    
    def test_analytics_heatmap_data_has_return_pct(self, api_client):
        """Verify heatmap_data contains return_pct values"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics")
        assert response.status_code == 200
        
        data = response.json()
        heatmap_data = data.get("heatmap_data", [])
        assert len(heatmap_data) > 0, "Heatmap data should not be empty"
        
        # Check that return_pct is present and is a number
        for item in heatmap_data[:10]:
            assert "return_pct" in item, f"Missing return_pct in heatmap item: {item.get('name')}"
            assert isinstance(item["return_pct"], (int, float)), f"return_pct should be a number"
    
    def test_heatmap_return_pct_values_are_reasonable(self, api_client):
        """Verify return_pct values are reasonable percentages"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics")
        assert response.status_code == 200
        
        data = response.json()
        heatmap_data = data.get("heatmap_data", [])
        
        # Check that values are in reasonable range (-100% to +500%)
        for item in heatmap_data[:10]:
            return_pct = item.get("return_pct", 0)
            assert -100 <= return_pct <= 500, f"return_pct {return_pct} out of reasonable range for {item.get('name')}"


class TestIssue3AIInsightsDescriptions:
    """Issue 3: AI Insights cards should show description text"""
    
    def test_insights_have_description(self, api_client):
        """Verify insights have description field"""
        response = api_client.get(f"{BASE_URL}/api/insights")
        assert response.status_code == 200
        
        data = response.json()
        insights = data.get("insights", data) if isinstance(data, dict) else data
        
        if isinstance(insights, list) and len(insights) > 0:
            for insight in insights[:5]:
                assert "title" in insight, "Insight should have title"
                # Description should be present and not empty
                description = insight.get("description", "")
                assert description and len(description) > 10, f"Insight '{insight.get('title')}' should have meaningful description"
    
    def test_insights_description_not_placeholder(self, api_client):
        """Verify descriptions are actual content, not placeholders"""
        response = api_client.get(f"{BASE_URL}/api/insights")
        assert response.status_code == 200
        
        data = response.json()
        insights = data.get("insights", data) if isinstance(data, dict) else data
        
        if isinstance(insights, list) and len(insights) > 0:
            for insight in insights[:5]:
                description = insight.get("description", "")
                # Should not be a placeholder
                assert "Click on Insights" not in description, "Description should not be placeholder text"


class TestIssue4SGBPrices:
    """Issue 4: SGB holdings should have RBI issue price as buy_price"""
    
    def test_sgb_holdings_have_buy_price(self, api_client):
        """Verify SGB holdings have buy_price from RBI mapping"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/holdings?asset_type=gold")
        assert response.status_code == 200
        
        holdings = response.json()
        sgb_holdings = [h for h in holdings if "SGB" in h.get("name", "").upper() or "SOVEREIGN" in h.get("name", "").upper()]
        
        if len(sgb_holdings) > 0:
            for h in sgb_holdings:
                buy_price = h.get("buy_price", 0)
                current_price = h.get("current_price", 0)
                
                # Buy price should be set and different from current price
                assert buy_price > 0, f"SGB {h.get('name')} should have buy_price > 0"
                
                # For SGBs, buy price should be the RBI issue price (typically 2500-6500 range)
                assert 2500 <= buy_price <= 7000, f"SGB buy_price {buy_price} should be in RBI issue price range"
    
    def test_sgb_returns_are_positive(self, api_client):
        """Verify SGB holdings show positive returns (gold has appreciated)"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/holdings?asset_type=gold")
        assert response.status_code == 200
        
        holdings = response.json()
        sgb_holdings = [h for h in holdings if "SGB" in h.get("name", "").upper()]
        
        if len(sgb_holdings) > 0:
            for h in sgb_holdings:
                buy_price = h.get("buy_price", 0)
                current_price = h.get("current_price", 0)
                
                if buy_price > 0 and current_price > 0:
                    return_pct = ((current_price - buy_price) / buy_price) * 100
                    # Gold has appreciated significantly, so returns should be positive
                    assert return_pct > 0, f"SGB {h.get('name')} should have positive returns, got {return_pct:.1f}%"
    
    def test_analytics_sgb_in_heatmap(self, api_client):
        """Verify SGB holdings appear in heatmap with correct returns"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics")
        assert response.status_code == 200
        
        data = response.json()
        heatmap_data = data.get("heatmap_data", [])
        
        # Find SGB entries in heatmap
        sgb_entries = [h for h in heatmap_data if "SGB" in h.get("name", "").upper() or "SOVEREIGN" in h.get("name", "").upper()]
        
        if len(sgb_entries) > 0:
            for entry in sgb_entries:
                return_pct = entry.get("return_pct", 0)
                # SGB returns should be positive and significant (gold has appreciated)
                assert return_pct > 50, f"SGB {entry.get('name')} should have significant positive returns, got {return_pct:.1f}%"


class TestExistingFeatures:
    """Verify existing features still work"""
    
    def test_live_prices_badge(self, api_client):
        """Verify live_price_stats is present in analytics"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics")
        assert response.status_code == 200
        
        data = response.json()
        live_stats = data.get("live_price_stats", {})
        assert "updated" in live_stats, "live_price_stats should have updated count"
    
    def test_recommendations_have_amounts(self, api_client):
        """Verify recommendations have reduce_amount and add_amount"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics")
        assert response.status_code == 200
        
        data = response.json()
        recommendations = data.get("recommendations", [])
        
        if len(recommendations) > 0:
            # At least some recommendations should have amounts
            has_amounts = any(
                r.get("reduce_amount", 0) > 0 or r.get("add_amount", 0) > 0
                for r in recommendations
            )
            assert has_amounts, "At least some recommendations should have reduce_amount or add_amount"
    
    def test_risk_factors_have_action_plan(self, api_client):
        """Verify risk factors have action_plan field"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics")
        assert response.status_code == 200
        
        data = response.json()
        risk_analysis = data.get("risk_analysis", {})
        risk_factors = risk_analysis.get("risk_factors", [])
        
        if len(risk_factors) > 0:
            for rf in risk_factors:
                assert "action_plan" in rf, f"Risk factor '{rf.get('factor')}' should have action_plan"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
