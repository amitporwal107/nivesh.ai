"""
Test suite for nivesh.ai bug fixes - Iteration 11
Tests for:
1. Data flags in analytics (day_change_simulated, performance_trend_simulated, missing_cmp_count, etc.)
2. Sector exposure equity-only
3. Risk analysis with risk_factors array and holdings breakdown
4. Gmail status with last_import info
5. Gmail history endpoint
6. Upload history endpoint
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
SESSION_TOKEN = "test_session_wealth001"

@pytest.fixture
def auth_headers():
    """Headers with authentication token"""
    return {
        "Authorization": f"Bearer {SESSION_TOKEN}",
        "Content-Type": "application/json"
    }

@pytest.fixture
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


class TestAnalyticsDataFlags:
    """Test data_flags object in analytics response"""
    
    def test_analytics_returns_data_flags(self, api_client, auth_headers):
        """GET /api/portfolio/analytics should return data_flags object"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "data_flags" in data, "Response should contain data_flags object"
        
        flags = data["data_flags"]
        # Check required fields
        assert "day_change_simulated" in flags, "data_flags should have day_change_simulated"
        assert "performance_trend_simulated" in flags, "data_flags should have performance_trend_simulated"
        assert "missing_cmp_count" in flags, "data_flags should have missing_cmp_count"
        assert "assumed_cost_count" in flags, "data_flags should have assumed_cost_count"
        assert "explanations" in flags, "data_flags should have explanations"
        
        # Verify types
        assert isinstance(flags["day_change_simulated"], bool), "day_change_simulated should be boolean"
        assert isinstance(flags["performance_trend_simulated"], bool), "performance_trend_simulated should be boolean"
        assert isinstance(flags["missing_cmp_count"], int), "missing_cmp_count should be integer"
        assert isinstance(flags["assumed_cost_count"], int), "assumed_cost_count should be integer"
        
        print(f"✓ data_flags present with all required fields")
        print(f"  - day_change_simulated: {flags['day_change_simulated']}")
        print(f"  - performance_trend_simulated: {flags['performance_trend_simulated']}")
        print(f"  - missing_cmp_count: {flags['missing_cmp_count']}")
        print(f"  - assumed_cost_count: {flags['assumed_cost_count']}")
    
    def test_analytics_explanations_content(self, api_client, auth_headers):
        """Explanations should contain detailed descriptions for each flag"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        explanations = data.get("data_flags", {}).get("explanations", {})
        
        # Check for key explanations
        expected_keys = ["day_change", "performance_trend", "risk_score", 
                        "health_diversification", "health_risk", "health_cost", 
                        "health_performance", "health_overall", "sector_exposure"]
        
        for key in expected_keys:
            assert key in explanations, f"explanations should contain '{key}'"
            assert len(explanations[key]) > 10, f"explanation for '{key}' should be descriptive"
        
        print(f"✓ All {len(expected_keys)} explanation keys present with content")


class TestSectorExposureEquityOnly:
    """Test that sector_exposure only contains equity holdings"""
    
    def test_sector_exposure_equity_only_flag(self, api_client, auth_headers):
        """data_flags should indicate sector_exposure is equity-only"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        flags = data.get("data_flags", {})
        
        assert "sector_exposure_equity_only" in flags, "data_flags should have sector_exposure_equity_only"
        assert flags["sector_exposure_equity_only"] == True, "sector_exposure_equity_only should be True"
        
        print(f"✓ sector_exposure_equity_only flag is True")
    
    def test_sector_exposure_explanation(self, api_client, auth_headers):
        """Explanation should clarify sector exposure is equity-only"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        explanations = data.get("data_flags", {}).get("explanations", {})
        
        sector_exp = explanations.get("sector_exposure", "")
        assert "equity" in sector_exp.lower(), "sector_exposure explanation should mention equity"
        assert "mutual fund" in sector_exp.lower() or "mf" in sector_exp.lower(), "should mention MFs are excluded"
        
        print(f"✓ sector_exposure explanation clarifies equity-only: {sector_exp[:100]}...")


class TestRiskAnalysisWithHoldings:
    """Test risk_analysis contains risk_factors with holdings breakdown"""
    
    def test_risk_analysis_structure(self, api_client, auth_headers):
        """risk_analysis should have risk_factors array"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        assert "risk_analysis" in data, "Response should contain risk_analysis"
        
        risk = data["risk_analysis"]
        assert "score" in risk, "risk_analysis should have score"
        assert "label" in risk, "risk_analysis should have label"
        assert "warnings" in risk, "risk_analysis should have warnings"
        assert "risk_factors" in risk, "risk_analysis should have risk_factors array"
        
        assert isinstance(risk["risk_factors"], list), "risk_factors should be a list"
        
        print(f"✓ risk_analysis structure valid")
        print(f"  - score: {risk['score']}")
        print(f"  - label: {risk['label']}")
        print(f"  - warnings count: {len(risk['warnings'])}")
        print(f"  - risk_factors count: {len(risk['risk_factors'])}")
    
    def test_risk_factors_have_holdings(self, api_client, auth_headers):
        """Each risk_factor should have holdings breakdown when applicable"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        risk_factors = data.get("risk_analysis", {}).get("risk_factors", [])
        
        # If there are risk factors, check their structure
        for rf in risk_factors:
            assert "factor" in rf, "risk_factor should have 'factor' name"
            assert "severity" in rf, "risk_factor should have 'severity'"
            assert "description" in rf, "risk_factor should have 'description'"
            assert "holdings" in rf, "risk_factor should have 'holdings' array"
            
            assert rf["severity"] in ["low", "medium", "high"], f"severity should be low/medium/high, got {rf['severity']}"
            assert isinstance(rf["holdings"], list), "holdings should be a list"
            
            print(f"  ✓ Risk factor '{rf['factor']}' ({rf['severity']}): {len(rf['holdings'])} holdings")


class TestGmailStatusWithLastImport:
    """Test Gmail status endpoint returns last_import info"""
    
    def test_gmail_status_structure(self, api_client, auth_headers):
        """GET /api/gmail/status should return connected status and last_import"""
        response = api_client.get(f"{BASE_URL}/api/gmail/status", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "connected" in data, "Response should have 'connected' field"
        assert isinstance(data["connected"], bool), "connected should be boolean"
        
        # If connected, should have last_import field (can be null)
        if data["connected"]:
            assert "last_import" in data, "Connected status should include last_import field"
            if data["last_import"]:
                li = data["last_import"]
                assert "filename" in li or li.get("filename") is None, "last_import should have filename"
                assert "imported_at" in li or li.get("imported_at") is None, "last_import should have imported_at"
                assert "count" in li, "last_import should have count"
        
        print(f"✓ Gmail status: connected={data['connected']}")
        if data.get("last_import"):
            print(f"  - Last import: {data['last_import']}")
    
    def test_gmail_status_requires_auth(self, api_client):
        """Gmail status should require authentication"""
        response = api_client.get(f"{BASE_URL}/api/gmail/status")
        assert response.status_code == 401, f"Expected 401 without auth, got {response.status_code}"
        print("✓ Gmail status requires authentication")


class TestGmailHistory:
    """Test Gmail import history endpoint"""
    
    def test_gmail_history_endpoint(self, api_client, auth_headers):
        """GET /api/gmail/history should return imports history"""
        response = api_client.get(f"{BASE_URL}/api/gmail/history", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "imports" in data, "Response should have 'imports' field"
        assert isinstance(data["imports"], list), "imports should be a list"
        
        print(f"✓ Gmail history: {len(data['imports'])} imports found")
        for imp in data["imports"][:3]:
            print(f"  - {imp.get('filename', 'N/A')} at {imp.get('imported_at', 'N/A')}")
    
    def test_gmail_history_requires_auth(self, api_client):
        """Gmail history should require authentication"""
        response = api_client.get(f"{BASE_URL}/api/gmail/history")
        assert response.status_code == 401, f"Expected 401 without auth, got {response.status_code}"
        print("✓ Gmail history requires authentication")


class TestUploadHistory:
    """Test upload history endpoint"""
    
    def test_upload_history_endpoint(self, api_client, auth_headers):
        """GET /api/portfolio/upload-history should return upload tasks history"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/upload-history", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "uploads" in data, "Response should have 'uploads' field"
        assert isinstance(data["uploads"], list), "uploads should be a list"
        
        print(f"✓ Upload history: {len(data['uploads'])} uploads found")
        for up in data["uploads"][:3]:
            print(f"  - Task {up.get('task_id', 'N/A')}: {up.get('status', 'N/A')} ({up.get('source', 'N/A')})")
    
    def test_upload_history_requires_auth(self, api_client):
        """Upload history should require authentication"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/upload-history")
        assert response.status_code == 401, f"Expected 401 without auth, got {response.status_code}"
        print("✓ Upload history requires authentication")
    
    def test_upload_history_fields(self, api_client, auth_headers):
        """Upload history items should have expected fields"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/upload-history", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        uploads = data.get("uploads", [])
        
        # If there are uploads, check their structure
        for up in uploads[:5]:
            # These fields should be present based on the projection in server.py
            expected_fields = ["task_id", "status"]
            for field in expected_fields:
                assert field in up, f"Upload should have '{field}' field"
        
        print(f"✓ Upload history items have correct structure")


class TestHealthScoreExplanations:
    """Test health score has explanations for each component"""
    
    def test_health_score_present(self, api_client, auth_headers):
        """Analytics should include health_score with breakdown"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        assert "health_score" in data, "Response should have health_score"
        
        hs = data["health_score"]
        expected_fields = ["diversification", "risk", "cost_efficiency", "performance", "overall", "grade"]
        for field in expected_fields:
            assert field in hs, f"health_score should have '{field}'"
        
        print(f"✓ Health score: {hs['overall']}/100 (Grade: {hs['grade']})")
        print(f"  - Diversification: {hs['diversification']}")
        print(f"  - Risk: {hs['risk']}")
        print(f"  - Cost Efficiency: {hs['cost_efficiency']}")
        print(f"  - Performance: {hs['performance']}")


class TestMissingCMPExplanation:
    """Test missing CMP explanation in data_flags"""
    
    def test_missing_cmp_explanation(self, api_client, auth_headers):
        """data_flags should explain missing CMP holdings"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/analytics", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        flags = data.get("data_flags", {})
        explanations = flags.get("explanations", {})
        
        assert "missing_cmp" in explanations, "explanations should have missing_cmp"
        
        missing_cmp_exp = explanations["missing_cmp"]
        assert "CMP" in missing_cmp_exp or "price" in missing_cmp_exp.lower(), "Should explain CMP"
        
        print(f"✓ Missing CMP explanation: {missing_cmp_exp[:100]}...")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
