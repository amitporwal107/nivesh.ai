"""
Iteration 23: Fund Overlap Tab Redesign Tests
Tests the complete redesign of Fund Overlap tab:
1. Duplication Score at top as circular gauge (89.4% High Duplication)
2. AI-first overlap insights with warning/alert/info cards
3. Category-Level Overlap with stacked bars showing unique vs overlapping ₹ allocation
4. Sector Exposure across funds
5. Cleaned up fund-to-fund overlap matrix
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
    session.headers.update({"Content-Type": "application/json"})
    session.cookies.set("session_token", SESSION_TOKEN)
    return session


class TestDeepAnalyticsDuplication:
    """Tests for the duplication object in deep-analytics endpoint"""

    def test_deep_analytics_returns_duplication_object(self, api_client):
        """Verify deep-analytics returns duplication key with required fields"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/deep-analytics")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "duplication" in data, "Response missing 'duplication' key"
        
        dup = data["duplication"]
        # Required fields
        assert "score" in dup, "duplication missing 'score'"
        assert "level" in dup, "duplication missing 'level'"
        assert "category_detail" in dup, "duplication missing 'category_detail'"
        assert "insights" in dup, "duplication missing 'insights'"
        assert "sector_overlaps" in dup, "duplication missing 'sector_overlaps'"
        assert "overlapping_value" in dup, "duplication missing 'overlapping_value'"
        assert "mf_total" in dup, "duplication missing 'mf_total'"

    def test_duplication_score_is_high(self, api_client):
        """Verify duplication score is ~89.4% with 'high' level for test user"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/deep-analytics")
        assert response.status_code == 200
        
        dup = response.json()["duplication"]
        score = dup["score"]
        level = dup["level"]
        
        # Score should be around 89.4% (allow some variance)
        assert 85 <= score <= 95, f"Expected score ~89.4%, got {score}%"
        assert level == "high", f"Expected level 'high', got '{level}'"

    def test_category_detail_structure(self, api_client):
        """Verify category_detail has correct structure for stacked bars"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/deep-analytics")
        assert response.status_code == 200
        
        category_detail = response.json()["duplication"]["category_detail"]
        assert len(category_detail) > 0, "category_detail is empty"
        
        # Check first category has all required fields
        cat = category_detail[0]
        required_fields = ["category", "fund_count", "total_value", "unique_value", 
                          "overlap_value", "is_overlapping", "funds", "pct_of_mf"]
        for field in required_fields:
            assert field in cat, f"category_detail missing '{field}'"
        
        # Verify values make sense
        assert cat["total_value"] > 0, "total_value should be positive"
        assert cat["unique_value"] >= 0, "unique_value should be non-negative"
        assert cat["overlap_value"] >= 0, "overlap_value should be non-negative"
        assert isinstance(cat["funds"], list), "funds should be a list"
        assert isinstance(cat["is_overlapping"], bool), "is_overlapping should be boolean"

    def test_category_detail_has_overlapping_categories(self, api_client):
        """Verify there are categories with multiple funds (overlapping)"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/deep-analytics")
        assert response.status_code == 200
        
        category_detail = response.json()["duplication"]["category_detail"]
        overlapping = [c for c in category_detail if c["is_overlapping"]]
        
        assert len(overlapping) >= 3, f"Expected at least 3 overlapping categories, got {len(overlapping)}"
        
        # Balanced should be overlapping with 7 funds
        balanced = next((c for c in category_detail if c["category"] == "Balanced"), None)
        if balanced:
            assert balanced["fund_count"] >= 5, f"Expected Balanced to have 5+ funds, got {balanced['fund_count']}"
            assert balanced["is_overlapping"] == True, "Balanced should be overlapping"

    def test_insights_structure(self, api_client):
        """Verify insights array has correct structure"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/deep-analytics")
        assert response.status_code == 200
        
        insights = response.json()["duplication"]["insights"]
        assert len(insights) > 0, "insights array is empty"
        
        # Check first insight has required fields
        ins = insights[0]
        required_fields = ["type", "text", "detail", "category", "impact"]
        for field in required_fields:
            assert field in ins, f"insight missing '{field}'"
        
        # Type should be one of: warning, alert, info, success
        valid_types = ["warning", "alert", "info", "success"]
        assert ins["type"] in valid_types, f"Invalid insight type: {ins['type']}"

    def test_insights_contain_warnings_for_high_overlap(self, api_client):
        """Verify insights contain warnings about category overlap"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/deep-analytics")
        assert response.status_code == 200
        
        insights = response.json()["duplication"]["insights"]
        warnings = [i for i in insights if i["type"] == "warning"]
        
        assert len(warnings) >= 2, f"Expected at least 2 warning insights, got {len(warnings)}"
        
        # Check that warnings mention fund counts
        warning_texts = [w["text"] for w in warnings]
        has_fund_count_warning = any("funds" in t.lower() for t in warning_texts)
        assert has_fund_count_warning, "Expected warnings to mention fund counts"

    def test_sector_overlaps_structure(self, api_client):
        """Verify sector_overlaps has correct structure"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/deep-analytics")
        assert response.status_code == 200
        
        sector_overlaps = response.json()["duplication"]["sector_overlaps"]
        assert len(sector_overlaps) > 0, "sector_overlaps is empty"
        
        # Check first sector has required fields
        sec = sector_overlaps[0]
        required_fields = ["sector", "value", "pct", "fund_count", "amc_count", "risk_level"]
        for field in required_fields:
            assert field in sec, f"sector_overlaps missing '{field}'"
        
        # Risk level should be valid
        valid_levels = ["high", "moderate", "low"]
        assert sec["risk_level"] in valid_levels, f"Invalid risk_level: {sec['risk_level']}"


class TestOverlapMatrix:
    """Tests for the fund-to-fund overlap matrix"""

    def test_overlap_matrix_exists(self, api_client):
        """Verify overlap_matrix is returned"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/deep-analytics")
        assert response.status_code == 200
        
        data = response.json()
        assert "overlap_matrix" in data, "Response missing 'overlap_matrix'"
        assert len(data["overlap_matrix"]) > 0, "overlap_matrix is empty"

    def test_overlap_matrix_structure(self, api_client):
        """Verify overlap_matrix entries have correct structure"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/deep-analytics")
        assert response.status_code == 200
        
        overlap_matrix = response.json()["overlap_matrix"]
        entry = overlap_matrix[0]
        
        required_fields = ["fund_a", "fund_b", "overlap_pct", "reasons"]
        for field in required_fields:
            assert field in entry, f"overlap_matrix entry missing '{field}'"
        
        # Overlap percentage should be valid
        assert 0 <= entry["overlap_pct"] <= 100, f"Invalid overlap_pct: {entry['overlap_pct']}"
        assert isinstance(entry["reasons"], list), "reasons should be a list"

    def test_overlap_matrix_has_high_overlap_pairs(self, api_client):
        """Verify there are fund pairs with high overlap (>60%)"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/deep-analytics")
        assert response.status_code == 200
        
        overlap_matrix = response.json()["overlap_matrix"]
        high_overlap = [o for o in overlap_matrix if o["overlap_pct"] >= 60]
        
        assert len(high_overlap) >= 2, f"Expected at least 2 high-overlap pairs, got {len(high_overlap)}"


class TestExistingEndpoints:
    """Verify existing endpoints still work"""

    def test_auth_me_works(self, api_client):
        """Verify /api/auth/me returns user info"""
        response = api_client.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code == 200
        
        data = response.json()
        assert "user_id" in data or "email" in data, "auth/me should return user info"

    def test_portfolio_holdings_works(self, api_client):
        """Verify /api/portfolio/holdings returns holdings"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/holdings")
        assert response.status_code == 200
        
        data = response.json()
        # Holdings endpoint returns array directly
        assert isinstance(data, list), "Response should be a list of holdings"
        assert len(data) > 50, f"Expected 50+ holdings, got {len(data)}"

    def test_portfolio_analytics_works(self, api_client):
        """Verify /api/portfolio/analytics returns analytics"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics")
        assert response.status_code == 200
        
        data = response.json()
        assert "total_invested" in data, "Response missing 'total_invested'"
        assert "current_value" in data, "Response missing 'current_value'"

    def test_deep_analytics_overexposure_still_works(self, api_client):
        """Verify deep-analytics still returns overexposure data"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/deep-analytics")
        assert response.status_code == 200
        
        data = response.json()
        assert "overexposure" in data, "Response missing 'overexposure'"
        assert "fund_house" in data["overexposure"], "overexposure missing 'fund_house'"
        assert "sector" in data["overexposure"], "overexposure missing 'sector'"

    def test_deep_analytics_performance_cards_still_works(self, api_client):
        """Verify deep-analytics still returns performance_cards"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/deep-analytics")
        assert response.status_code == 200
        
        data = response.json()
        assert "performance_cards" in data, "Response missing 'performance_cards'"
        assert len(data["performance_cards"]) > 0, "performance_cards is empty"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
