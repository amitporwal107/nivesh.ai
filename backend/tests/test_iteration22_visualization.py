"""
Iteration 22 Tests: Visualization Fixes
Tests for:
1. Fund House Concentration stacked chart (Current vs Balanced)
2. Portfolio Performance Heatmap with P&L metrics
3. MF Category Overlap card grid
4. Backend API regression tests
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
SESSION_TOKEN = os.environ["NIVESH_TEST_USER_TOKEN"]

@pytest.fixture
def api_client():
    """Shared requests session with auth cookie"""
    session = requests.Session()
    session.cookies.set("session_token", SESSION_TOKEN)
    session.headers.update({"Content-Type": "application/json"})
    return session


class TestAuthAndBasicAPIs:
    """Test authentication and basic API endpoints"""
    
    def test_auth_me(self, api_client):
        """Test /api/auth/me returns user info"""
        response = api_client.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert "user_id" in data
        assert "email" in data
        assert data["email"] == "aporwal107@gmail.com"
        print(f"✓ Auth verified: {data['email']}")
    
    def test_portfolio_holdings(self, api_client):
        """Test /api/portfolio/holdings returns holdings"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/holdings")
        assert response.status_code == 200
        data = response.json()
        # API returns list directly
        assert isinstance(data, list)
        assert len(data) == 110
        print(f"✓ Holdings count: {len(data)}")


class TestDeepAnalyticsAPI:
    """Test deep analytics API for overexposure data"""
    
    def test_deep_analytics_returns_overexposure(self, api_client):
        """Test /api/portfolio/deep-analytics returns overexposure data"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/deep-analytics")
        assert response.status_code == 200
        data = response.json()
        
        # Check overexposure structure
        assert "overexposure" in data
        overexposure = data["overexposure"]
        
        # Check fund_house data for stacked chart
        assert "fund_house" in overexposure
        fund_houses = overexposure["fund_house"]
        assert len(fund_houses) > 0
        
        # Verify fund house structure
        first_fh = fund_houses[0]
        assert "name" in first_fh
        assert "pct" in first_fh
        assert "count" in first_fh
        assert "value" in first_fh
        assert "funds" in first_fh
        assert "risk_level" in first_fh
        
        print(f"✓ Fund houses found: {len(fund_houses)}")
        print(f"✓ Top fund house: {first_fh['name']} at {first_fh['pct']}%")
    
    def test_hdfc_is_top_fund_house(self, api_client):
        """Test HDFC is the top fund house (should be expanded by default)"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/deep-analytics")
        assert response.status_code == 200
        data = response.json()
        
        fund_houses = data["overexposure"]["fund_house"]
        # First fund house should be HDFC (highest allocation)
        assert fund_houses[0]["name"] == "HDFC"
        assert fund_houses[0]["pct"] >= 30  # Should be around 35.5%
        print(f"✓ HDFC is top fund house with {fund_houses[0]['pct']}% allocation")
    
    def test_sector_data_exists(self, api_client):
        """Test sector data exists for sector composition chart"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/deep-analytics")
        assert response.status_code == 200
        data = response.json()
        
        assert "sector" in data["overexposure"]
        sectors = data["overexposure"]["sector"]
        assert len(sectors) > 0
        print(f"✓ Sectors found: {len(sectors)}")


class TestFundPerformanceAPI:
    """Test fund performance API for heatmap and category overlap"""
    
    def test_fund_performance_returns_ratings(self, api_client):
        """Test /api/portfolio/fund-performance returns fund ratings"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/fund-performance")
        assert response.status_code == 200
        data = response.json()
        
        assert "fund_ratings" in data
        ratings = data["fund_ratings"]
        assert len(ratings) > 0
        print(f"✓ Fund ratings count: {len(ratings)}")
    
    def test_fund_ratings_have_pnl_fields(self, api_client):
        """Test fund ratings have invested and current_value for P&L calculation"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/fund-performance")
        assert response.status_code == 200
        data = response.json()
        
        ratings = data["fund_ratings"]
        # Check first rating has required fields for P&L
        first_rating = ratings[0]
        assert "invested" in first_rating
        assert "current_value" in first_rating
        assert "name" in first_rating
        
        # Verify P&L can be calculated
        invested = first_rating.get("invested", 0)
        current = first_rating.get("current_value", 0)
        if invested > 0:
            pnl = current - invested
            pnl_pct = (pnl / invested) * 100
            print(f"✓ P&L calculation works: {first_rating['name'][:30]}... = {pnl_pct:.1f}%")
    
    def test_category_overlap_data(self, api_client):
        """Test category_overlap data for card grid"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/fund-performance")
        assert response.status_code == 200
        data = response.json()
        
        assert "category_overlap" in data
        overlap = data["category_overlap"]
        assert len(overlap) > 0
        
        # Check structure
        first_cat = overlap[0]
        assert "category" in first_cat
        assert "count" in first_cat
        assert "is_overlapping" in first_cat
        
        # Count overlapping categories (2+ funds)
        overlapping = [c for c in overlap if c["is_overlapping"]]
        unique = [c for c in overlap if not c["is_overlapping"]]
        
        print(f"✓ Category overlap: {len(overlapping)} overlapping, {len(unique)} unique")
    
    def test_performance_distribution(self, api_client):
        """Test performance distribution for pie chart"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/fund-performance")
        assert response.status_code == 200
        data = response.json()
        
        assert "performance_distribution" in data
        dist = data["performance_distribution"]
        
        # Check all rating categories exist
        assert "overperforming" in dist
        assert "meeting" in dist
        assert "underperforming" in dist
        assert "no_data" in dist
        
        total = dist["overperforming"] + dist["meeting"] + dist["underperforming"] + dist["no_data"]
        print(f"✓ Performance distribution: {dist['overperforming']} outperforming, {dist['meeting']} meeting, {dist['underperforming']} underperforming, {dist['no_data']} no data")
        print(f"✓ Total funds in distribution: {total}")


class TestInsightsAPI:
    """Test insights API for AI analysis"""
    
    def test_insights_analysis(self, api_client):
        """Test /api/insights/analysis returns analysis data"""
        response = api_client.get(f"{BASE_URL}/api/insights/analysis")
        assert response.status_code == 200
        data = response.json()
        
        # Check basic structure
        assert "insights" in data or data.get("insights") is not None or len(data) > 0
        print(f"✓ Insights analysis returned successfully")


class TestPortfolioAnalyticsAPI:
    """Test portfolio analytics API"""
    
    def test_portfolio_analytics(self, api_client):
        """Test /api/portfolio/analytics returns analytics data"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics")
        assert response.status_code == 200
        data = response.json()
        
        # Check basic structure
        assert "total_invested" in data or "sector_exposure" in data
        print(f"✓ Portfolio analytics returned successfully")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
