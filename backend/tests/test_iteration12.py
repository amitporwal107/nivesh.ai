"""
Iteration 12 Backend Tests
Features to test:
1. GET /api/portfolio/analytics - top_gainers items should include asset_type field
2. GET /api/portfolio/analytics - top_gainers should return up to 10 items
3. CAS parser prompt should include SGB series extraction instruction (rule 10)
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
SESSION_TOKEN = "test_session_wealth001"

@pytest.fixture
def auth_headers():
    """Headers with test session token"""
    return {
        "Authorization": f"Bearer {SESSION_TOKEN}",
        "Content-Type": "application/json"
    }

class TestAnalyticsTopGainersLosers:
    """Test top_gainers and top_losers in analytics endpoint"""
    
    def test_analytics_returns_top_gainers_with_asset_type(self, auth_headers):
        """Test that top_gainers items include asset_type field"""
        response = requests.get(f"{BASE_URL}/api/portfolio/analytics", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "top_gainers" in data, "Response should contain top_gainers"
        
        top_gainers = data["top_gainers"]
        if len(top_gainers) > 0:
            # Check first gainer has asset_type
            first_gainer = top_gainers[0]
            assert "asset_type" in first_gainer, f"top_gainers item should have asset_type field. Got: {first_gainer.keys()}"
            assert first_gainer["asset_type"] in ["equity", "mutual_fund", "etf", "bond", "gold", "fd", "other"], \
                f"asset_type should be valid. Got: {first_gainer['asset_type']}"
            
            # Check all gainers have asset_type
            for i, gainer in enumerate(top_gainers):
                assert "asset_type" in gainer, f"Gainer {i} missing asset_type"
                assert "name" in gainer, f"Gainer {i} missing name"
                assert "pct_change" in gainer, f"Gainer {i} missing pct_change"
                assert "value" in gainer, f"Gainer {i} missing value"
            
            print(f"✓ top_gainers has {len(top_gainers)} items, all with asset_type field")
            print(f"  Sample: {first_gainer['name'][:40]}... - {first_gainer['asset_type']} - {first_gainer['pct_change']}%")
        else:
            print("⚠ No top_gainers returned (may be empty portfolio)")
    
    def test_analytics_returns_top_losers_with_asset_type(self, auth_headers):
        """Test that top_losers items include asset_type field"""
        response = requests.get(f"{BASE_URL}/api/portfolio/analytics", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        assert "top_losers" in data, "Response should contain top_losers"
        
        top_losers = data["top_losers"]
        if len(top_losers) > 0:
            # Check all losers have asset_type
            for i, loser in enumerate(top_losers):
                assert "asset_type" in loser, f"Loser {i} missing asset_type"
                assert loser["asset_type"] in ["equity", "mutual_fund", "etf", "bond", "gold", "fd", "other"], \
                    f"asset_type should be valid. Got: {loser['asset_type']}"
            
            print(f"✓ top_losers has {len(top_losers)} items, all with asset_type field")
        else:
            print("⚠ No top_losers returned")
    
    def test_analytics_returns_up_to_10_gainers(self, auth_headers):
        """Test that top_gainers returns up to 10 items"""
        response = requests.get(f"{BASE_URL}/api/portfolio/analytics", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        top_gainers = data.get("top_gainers", [])
        
        # Should return at most 10 items
        assert len(top_gainers) <= 10, f"top_gainers should have at most 10 items, got {len(top_gainers)}"
        
        # With 65 holdings, we expect 10 gainers
        holdings_count = data.get("holdings_count", 0)
        if holdings_count >= 10:
            assert len(top_gainers) == 10, f"With {holdings_count} holdings, expected 10 top_gainers, got {len(top_gainers)}"
        
        print(f"✓ top_gainers returns {len(top_gainers)} items (max 10)")
    
    def test_analytics_returns_up_to_10_losers(self, auth_headers):
        """Test that top_losers returns up to 10 items"""
        response = requests.get(f"{BASE_URL}/api/portfolio/analytics", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        top_losers = data.get("top_losers", [])
        
        # Should return at most 10 items
        assert len(top_losers) <= 10, f"top_losers should have at most 10 items, got {len(top_losers)}"
        
        print(f"✓ top_losers returns {len(top_losers)} items (max 10)")


class TestCASParserPrompt:
    """Test CAS parser prompt includes SGB series extraction rule"""
    
    def test_cas_parser_prompt_has_sgb_rule(self):
        """Verify CAS_PARSER_SYSTEM prompt includes rule 10 for SGB series names"""
        # Import the prompt from ai_engine
        import sys
        sys.path.insert(0, '/app/backend')
        from services.ai_engine import CAS_PARSER_SYSTEM
        
        # Check rule 10 exists and mentions SGB series
        assert "10." in CAS_PARSER_SYSTEM, "CAS_PARSER_SYSTEM should have rule 10"
        assert "Sovereign Gold Bond" in CAS_PARSER_SYSTEM or "SGB" in CAS_PARSER_SYSTEM, \
            "Rule 10 should mention Sovereign Gold Bond or SGB"
        assert "series" in CAS_PARSER_SYSTEM.lower(), "Rule 10 should mention series extraction"
        
        # Check for specific guidance about series names
        prompt_lower = CAS_PARSER_SYSTEM.lower()
        assert "full series name" in prompt_lower or "series number" in prompt_lower or "tranche" in prompt_lower, \
            "Rule 10 should guide on extracting full series name/number"
        
        print("✓ CAS_PARSER_SYSTEM includes SGB series extraction rule (rule 10)")
        
        # Print the relevant rule for verification
        lines = CAS_PARSER_SYSTEM.split('\n')
        for i, line in enumerate(lines):
            if '10.' in line or 'SGB' in line or 'Sovereign Gold' in line:
                print(f"  Found: {line.strip()[:100]}...")


class TestAnalyticsDataStructure:
    """Additional tests for analytics data structure"""
    
    def test_analytics_has_required_fields(self, auth_headers):
        """Test analytics response has all required fields"""
        response = requests.get(f"{BASE_URL}/api/portfolio/analytics", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        
        required_fields = [
            "holdings_count", "total_invested", "current_value", "total_returns",
            "returns_pct", "day_change", "day_change_pct", "risk_score", "risk_label",
            "asset_allocation", "sector_exposure", "top_gainers", "top_losers",
            "data_flags"
        ]
        
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        print(f"✓ Analytics response has all {len(required_fields)} required fields")
    
    def test_top_gainers_sorted_by_pct_change_desc(self, auth_headers):
        """Test that top_gainers are sorted by pct_change descending"""
        response = requests.get(f"{BASE_URL}/api/portfolio/analytics", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        top_gainers = data.get("top_gainers", [])
        
        if len(top_gainers) > 1:
            for i in range(len(top_gainers) - 1):
                assert top_gainers[i]["pct_change"] >= top_gainers[i+1]["pct_change"], \
                    f"top_gainers not sorted: {top_gainers[i]['pct_change']} < {top_gainers[i+1]['pct_change']}"
            print(f"✓ top_gainers sorted by pct_change descending")
        else:
            print("⚠ Not enough gainers to verify sorting")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
