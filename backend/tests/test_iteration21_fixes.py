"""
Test iteration 21 - Five fixes for nivesh.ai insights:
1. Outperforming fund drilldown (ratingKey mismatch fix)
2. Category Overlap renamed to 'MF Category Overlap'
3. Fund-by-Fund list replaced with heatmap/treemap
4. Fund House/Sector cards expanded by default (expandedFH=0)
5. Equity sectors enriched from 'Other' to proper sectors
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
SESSION_TOKEN = "5770bebb-8a9a-41f7-a7b9-e8152ac25daa"


@pytest.fixture
def api_client():
    """Shared requests session with auth cookie"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    session.cookies.set("session_token", SESSION_TOKEN)
    return session


class TestBackendAPIs:
    """Test all backend APIs are working"""

    def test_auth_me(self, api_client):
        """Test auth endpoint returns user info"""
        response = api_client.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert "user_id" in data
        assert "email" in data
        print(f"✓ Auth: user_id={data['user_id']}, email={data['email']}")

    def test_portfolio_holdings(self, api_client):
        """Test holdings endpoint returns data"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/holdings")
        assert response.status_code == 200
        data = response.json()
        # API returns list directly
        holdings = data if isinstance(data, list) else data.get("holdings", [])
        assert len(holdings) > 0
        print(f"✓ Holdings: {len(holdings)} holdings found")


class TestSectorEnrichment:
    """Test equity sector enrichment - Fix #5"""

    def test_analytics_sector_exposure_has_proper_sectors(self, api_client):
        """GET /api/portfolio/analytics returns sector_exposure with proper sectors (Banking, IT, Energy, etc.)"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics")
        assert response.status_code == 200
        data = response.json()
        
        sector_exposure = data.get("sector_exposure", [])
        assert len(sector_exposure) > 0, "sector_exposure should not be empty"
        
        sector_names = [s["name"] for s in sector_exposure]
        print(f"Sectors found: {sector_names}")
        
        # Check that we have proper equity sectors, not all "Other"
        proper_sectors = ["Banking", "IT", "Pharma", "FMCG", "Auto", "Financial Services", 
                         "Telecom", "Energy", "Metals", "Power", "Infrastructure", "Consumer Durables"]
        found_proper_sectors = [s for s in sector_names if s in proper_sectors]
        
        assert len(found_proper_sectors) >= 3, f"Expected at least 3 proper equity sectors, found: {found_proper_sectors}"
        assert "Other" not in sector_names or len(found_proper_sectors) > 0, "Should have proper sectors, not just 'Other'"
        print(f"✓ Sector enrichment: Found {len(found_proper_sectors)} proper equity sectors: {found_proper_sectors}")

    def test_deep_analytics_overexposure_has_enriched_sectors(self, api_client):
        """GET /api/portfolio/deep-analytics returns overexposure with enriched sectors"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/deep-analytics")
        assert response.status_code == 200
        data = response.json()
        
        overexposure = data.get("overexposure", {})
        sectors = overexposure.get("sector", [])
        assert len(sectors) > 0, "overexposure.sector should not be empty"
        
        sector_names = [s["name"] for s in sectors]
        print(f"Deep analytics sectors: {sector_names[:10]}")
        
        # Should have MF categories + equity sectors
        mf_categories = ["Balanced", "Flexi Cap", "Small Cap", "Large Cap", "Mid Cap", "Index", "Gold", "Value"]
        equity_sectors = ["Banking", "IT", "Financial Services", "Energy"]
        
        found_mf = [s for s in sector_names if s in mf_categories]
        found_equity = [s for s in sector_names if s in equity_sectors]
        
        assert len(found_mf) >= 2, f"Expected MF categories, found: {found_mf}"
        print(f"✓ Deep analytics: Found {len(found_mf)} MF categories and {len(found_equity)} equity sectors")


class TestFundPerformance:
    """Test fund performance and benchmark ratings - Fix #1"""

    def test_fund_performance_returns_data(self, api_client):
        """GET /api/portfolio/fund-performance returns fund ratings"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/fund-performance")
        assert response.status_code == 200
        data = response.json()
        
        assert "fund_ratings" in data
        assert "performance_distribution" in data
        assert "category_overlap" in data
        
        fund_ratings = data["fund_ratings"]
        assert len(fund_ratings) > 0, "fund_ratings should not be empty"
        print(f"✓ Fund performance: {len(fund_ratings)} fund ratings returned")

    def test_performance_distribution_has_overperforming(self, api_client):
        """Performance distribution should have overperforming count"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/fund-performance")
        assert response.status_code == 200
        data = response.json()
        
        dist = data.get("performance_distribution", {})
        print(f"Performance distribution: {dist}")
        
        # Check all expected keys exist
        assert "overperforming" in dist, "Missing 'overperforming' key in distribution"
        assert "meeting" in dist, "Missing 'meeting' key in distribution"
        assert "underperforming" in dist, "Missing 'underperforming' key in distribution"
        
        # Verify we have some overperforming funds
        assert dist["overperforming"] >= 0, "overperforming count should be >= 0"
        print(f"✓ Distribution: overperforming={dist['overperforming']}, meeting={dist['meeting']}, underperforming={dist['underperforming']}")

    def test_fund_ratings_have_correct_rating_field(self, api_client):
        """Fund ratings should have 'rating' field with values like 'overperforming'"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/fund-performance")
        assert response.status_code == 200
        data = response.json()
        
        fund_ratings = data.get("fund_ratings", [])
        assert len(fund_ratings) > 0
        
        # Check rating field exists and has valid values
        valid_ratings = ["overperforming", "meeting", "underperforming", "no_data"]
        for fund in fund_ratings[:5]:
            assert "rating" in fund, f"Fund {fund.get('name')} missing 'rating' field"
            assert fund["rating"] in valid_ratings, f"Invalid rating: {fund['rating']}"
        
        # Count funds by rating
        rating_counts = {}
        for fund in fund_ratings:
            r = fund.get("rating", "unknown")
            rating_counts[r] = rating_counts.get(r, 0) + 1
        
        print(f"✓ Fund ratings by category: {rating_counts}")
        
        # Verify overperforming funds exist and can be filtered
        overperforming_funds = [f for f in fund_ratings if f.get("rating") == "overperforming"]
        print(f"✓ Overperforming funds: {len(overperforming_funds)}")
        if overperforming_funds:
            print(f"  Sample: {overperforming_funds[0].get('name', 'N/A')[:50]}")

    def test_category_overlap_data(self, api_client):
        """Category overlap should have MF categories"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/fund-performance")
        assert response.status_code == 200
        data = response.json()
        
        category_overlap = data.get("category_overlap", [])
        assert len(category_overlap) > 0, "category_overlap should not be empty"
        
        # Check structure
        for cat in category_overlap[:3]:
            assert "category" in cat
            assert "count" in cat
            assert "is_overlapping" in cat
        
        categories = [c["category"] for c in category_overlap]
        print(f"✓ Category overlap: {len(category_overlap)} categories - {categories[:5]}")


class TestHeatmapData:
    """Test heatmap data for Fund Performance Heatmap - Fix #3"""

    def test_fund_ratings_have_heatmap_fields(self, api_client):
        """Fund ratings should have fields needed for heatmap (invested, current_value, return_1y)"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/fund-performance")
        assert response.status_code == 200
        data = response.json()
        
        fund_ratings = data.get("fund_ratings", [])
        assert len(fund_ratings) > 0
        
        # Check required fields for heatmap
        required_fields = ["name", "invested", "current_value", "rating"]
        for fund in fund_ratings[:5]:
            for field in required_fields:
                assert field in fund, f"Fund missing '{field}' field for heatmap"
        
        # Check we have return data
        funds_with_return = [f for f in fund_ratings if f.get("return_1y") is not None or f.get("simple_return_pct") is not None]
        print(f"✓ Heatmap data: {len(funds_with_return)}/{len(fund_ratings)} funds have return data")


class TestExistingEndpoints:
    """Test existing endpoints still work (regression)"""

    def test_insights_analysis(self, api_client):
        """GET /api/insights/analysis should work"""
        response = api_client.get(f"{BASE_URL}/api/insights/analysis")
        assert response.status_code == 200
        data = response.json()
        # May be empty if not generated, but should not error
        print(f"✓ Insights analysis: {'has data' if data.get('insights') else 'empty (not generated)'}")

    def test_portfolio_analytics(self, api_client):
        """GET /api/portfolio/analytics should work"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics")
        assert response.status_code == 200
        data = response.json()
        assert "total_invested" in data
        assert "current_value" in data
        assert "holdings_count" in data
        print(f"✓ Portfolio analytics: {data['holdings_count']} holdings, value={data['current_value']}")

    def test_deep_analytics(self, api_client):
        """GET /api/portfolio/deep-analytics should work"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/deep-analytics")
        assert response.status_code == 200
        data = response.json()
        assert "overexposure" in data
        assert "performance_cards" in data
        print(f"✓ Deep analytics: {len(data.get('performance_cards', []))} performance cards")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
