"""
Backend API Tests for nivesh.ai - Deep Analytics & AMFI NAV Features
Tests: /api/nav/refresh, /api/portfolio/deep-analytics, /api/portfolio/analytics
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
SESSION_TOKEN = "test_session_wealth001"

@pytest.fixture(scope="module")
def api_client():
    """Shared requests session with auth"""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {SESSION_TOKEN}"
    })
    return session


class TestHealthAndAuth:
    """Basic health and authentication tests"""
    
    def test_api_root(self, api_client):
        """Test API root endpoint"""
        response = api_client.get(f"{BASE_URL}/api/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        print(f"✓ API root: {data}")
    
    def test_auth_me(self, api_client):
        """Test authentication with test session"""
        response = api_client.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code == 200, f"Auth failed: {response.text}"
        data = response.json()
        assert "user_id" in data
        assert data["user_id"] == "test-user-wealth001"
        print(f"✓ Auth verified: {data['email']}")


class TestPortfolioAnalytics:
    """Test /api/portfolio/analytics endpoint with AMFI NAV integration"""
    
    def test_analytics_returns_data(self, api_client):
        """Test analytics endpoint returns expected structure"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics")
        assert response.status_code == 200, f"Analytics failed: {response.text}"
        data = response.json()
        
        # Verify core analytics fields
        assert "total_invested" in data
        assert "current_value" in data
        assert "total_returns" in data
        assert "returns_pct" in data
        assert "asset_allocation" in data
        assert "sector_exposure" in data
        assert "risk_score" in data
        assert "holdings_count" in data
        
        # Verify new product intelligence fields
        assert "health_score" in data
        assert "risk_analysis" in data
        assert "recommendations" in data
        
        print(f"✓ Analytics: {data['holdings_count']} holdings, value={data['current_value']}")
        print(f"  Health Score: {data.get('health_score', {}).get('score', 'N/A')}")
    
    def test_analytics_has_heatmap_data(self, api_client):
        """Test analytics includes heatmap data for visualization"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics")
        assert response.status_code == 200
        data = response.json()
        
        assert "heatmap_data" in data
        assert isinstance(data["heatmap_data"], list)
        if data["heatmap_data"]:
            item = data["heatmap_data"][0]
            assert "name" in item
            assert "value" in item
            assert "return_pct" in item
        print(f"✓ Heatmap data: {len(data['heatmap_data'])} items")


class TestNAVRefresh:
    """Test /api/nav/refresh endpoint for AMFI NAV integration"""
    
    def test_nav_refresh_endpoint(self, api_client):
        """Test NAV refresh updates mutual fund holdings"""
        response = api_client.post(f"{BASE_URL}/api/nav/refresh")
        assert response.status_code == 200, f"NAV refresh failed: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "updated" in data
        assert "total_mf" in data
        assert "nav_entries" in data
        
        print(f"✓ NAV Refresh: updated={data['updated']}, total_mf={data['total_mf']}, nav_entries={data['nav_entries']}")
        
        # NAV entries should be > 0 if AMFI fetch worked
        assert data["nav_entries"] > 0, "AMFI NAV fetch returned 0 entries"


class TestDeepAnalytics:
    """Test /api/portfolio/deep-analytics endpoint"""
    
    def test_deep_analytics_returns_structure(self, api_client):
        """Test deep analytics returns overexposure, overlap, performance"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/deep-analytics")
        assert response.status_code == 200, f"Deep analytics failed: {response.text}"
        data = response.json()
        
        # Verify top-level structure
        assert "overexposure" in data
        assert "overlap_matrix" in data
        assert "performance_cards" in data
        
        print(f"✓ Deep Analytics structure verified")
    
    def test_overexposure_fund_house(self, api_client):
        """Test overexposure includes fund house concentration"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/deep-analytics")
        assert response.status_code == 200
        data = response.json()
        
        overexposure = data.get("overexposure", {})
        fund_house = overexposure.get("fund_house", [])
        
        # Should have fund house data if user has mutual funds
        if fund_house:
            fh = fund_house[0]
            assert "name" in fh
            assert "value" in fh
            assert "pct" in fh
            assert "count" in fh
            assert "risk_level" in fh
            print(f"✓ Fund House Concentration: {len(fund_house)} AMCs")
            for fh in fund_house[:3]:
                print(f"  - {fh['name']}: {fh['pct']}% ({fh['count']} funds)")
        else:
            print("⚠ No fund house data (may not have mutual funds)")
    
    def test_overexposure_sector(self, api_client):
        """Test overexposure includes sector concentration"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/deep-analytics")
        assert response.status_code == 200
        data = response.json()
        
        overexposure = data.get("overexposure", {})
        sectors = overexposure.get("sector", [])
        
        assert isinstance(sectors, list)
        if sectors:
            sec = sectors[0]
            assert "name" in sec
            assert "value" in sec
            assert "pct" in sec
            assert "count" in sec
            print(f"✓ Sector Concentration: {len(sectors)} sectors")
            for s in sectors[:3]:
                print(f"  - {s['name']}: {s['pct']}% ({s['count']} holdings)")
    
    def test_overlap_matrix(self, api_client):
        """Test fund overlap matrix computation"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/deep-analytics")
        assert response.status_code == 200
        data = response.json()
        
        overlap_matrix = data.get("overlap_matrix", [])
        assert isinstance(overlap_matrix, list)
        
        if overlap_matrix:
            overlap = overlap_matrix[0]
            assert "fund_a" in overlap
            assert "fund_b" in overlap
            assert "overlap_pct" in overlap
            assert "reasons" in overlap
            print(f"✓ Overlap Matrix: {len(overlap_matrix)} pairs")
            for o in overlap_matrix[:3]:
                print(f"  - {o['fund_a'][:30]} ↔ {o['fund_b'][:30]}: {o['overlap_pct']}%")
        else:
            print("⚠ No overlap data (may need 2+ mutual funds)")
    
    def test_performance_cards(self, api_client):
        """Test performance cards for all holdings"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/deep-analytics")
        assert response.status_code == 200
        data = response.json()
        
        cards = data.get("performance_cards", [])
        assert isinstance(cards, list)
        assert len(cards) > 0, "No performance cards returned"
        
        card = cards[0]
        # Verify card structure
        assert "name" in card
        assert "asset_type" in card
        assert "invested" in card
        assert "current_value" in card
        assert "pct_return" in card
        assert "weight" in card
        
        print(f"✓ Performance Cards: {len(cards)} holdings")
        
        # Check for AMFI NAV source
        nav_sourced = [c for c in cards if c.get("nav_source") == "AMFI"]
        print(f"  - AMFI NAV sourced: {len(nav_sourced)} holdings")
        
        # Show top performers
        sorted_cards = sorted(cards, key=lambda x: x.get("pct_return", 0), reverse=True)
        print("  Top 3 performers:")
        for c in sorted_cards[:3]:
            print(f"    - {c['name'][:40]}: {c['pct_return']}%")


class TestHoldingsEndpoint:
    """Test holdings CRUD operations"""
    
    def test_get_holdings(self, api_client):
        """Test getting all holdings"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/holdings")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Holdings: {len(data)} total")
    
    def test_filter_holdings_by_asset_type(self, api_client):
        """Test filtering holdings by asset type"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/holdings?asset_type=mutual_fund")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # All returned should be mutual_fund
        for h in data:
            assert h.get("asset_type") == "mutual_fund"
        print(f"✓ Mutual Fund Holdings: {len(data)}")


class TestInsightsEndpoints:
    """Test AI insights endpoints"""
    
    def test_get_insights(self, api_client):
        """Test getting existing insights"""
        response = api_client.get(f"{BASE_URL}/api/insights")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Insights: {len(data)} saved")
    
    def test_get_analysis(self, api_client):
        """Test getting full analysis data"""
        response = api_client.get(f"{BASE_URL}/api/insights/analysis")
        assert response.status_code == 200
        # May return null if no analysis generated yet
        data = response.json()
        if data:
            assert "insights" in data or "problem_distribution" in data
            print(f"✓ Analysis data available")
        else:
            print("⚠ No analysis data yet (need to generate)")


class TestPortfolioManagement:
    """Test portfolio management endpoints"""
    
    def test_list_portfolios(self, api_client):
        """Test listing portfolios"""
        response = api_client.get(f"{BASE_URL}/api/portfolios")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Portfolios: {len(data)}")


class TestInstrumentSearch:
    """Test instrument search/autocomplete"""
    
    def test_search_instruments(self, api_client):
        """Test instrument search"""
        response = api_client.get(f"{BASE_URL}/api/search/instruments?q=HDFC")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Search 'HDFC': {len(data)} results")
        if data:
            print(f"  First: {data[0].get('name', 'N/A')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
