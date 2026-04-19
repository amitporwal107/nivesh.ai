"""
Iteration 24: AI-Powered Allocation Analysis Tests
Tests the new GET /api/portfolio/allocation-analysis endpoint that uses OpenAI gpt-4o-mini
to estimate underlying MF holdings and compute true sector/company exposure.
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
SESSION_TOKEN = os.environ.get("NIVESH_TEST_USER_TOKEN", "5770bebb-8a9a-41f7-a7b9-e8152ac25daa")


@pytest.fixture
def auth_cookies():
    """Return auth cookies for test user with 110 holdings"""
    return {"session_token": SESSION_TOKEN}


class TestAllocationAnalysisEndpoint:
    """Tests for GET /api/portfolio/allocation-analysis"""

    def test_allocation_analysis_returns_expected_fields(self, auth_cookies):
        """Verify API returns company_allocation, sector_allocation, top_10_companies, top_5_sectors, concentration_flags, data_quality"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/allocation-analysis",
            cookies=auth_cookies,
            timeout=60
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify all required fields exist
        required_fields = ['company_allocation', 'sector_allocation', 'top_10_companies', 'top_5_sectors', 'concentration_flags', 'data_quality']
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        print(f"✓ All required fields present: {required_fields}")

    def test_company_allocation_structure(self, auth_cookies):
        """Verify company_allocation has correct structure"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/allocation-analysis",
            cookies=auth_cookies,
            timeout=60
        )
        assert response.status_code == 200
        
        data = response.json()
        company_allocation = data.get('company_allocation', [])
        
        assert len(company_allocation) > 0, "company_allocation should not be empty"
        
        # Check structure of first entry
        first_company = company_allocation[0]
        assert 'name' in first_company, "company_allocation entry missing 'name'"
        assert 'weight' in first_company, "company_allocation entry missing 'weight'"
        assert 'sector' in first_company, "company_allocation entry missing 'sector'"
        assert 'sources' in first_company, "company_allocation entry missing 'sources'"
        
        # Verify weight is a number between 0 and 1
        assert isinstance(first_company['weight'], (int, float)), "weight should be numeric"
        assert 0 <= first_company['weight'] <= 1, f"weight should be between 0 and 1, got {first_company['weight']}"
        
        print(f"✓ company_allocation has {len(company_allocation)} entries with correct structure")

    def test_sector_allocation_structure(self, auth_cookies):
        """Verify sector_allocation has correct structure"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/allocation-analysis",
            cookies=auth_cookies,
            timeout=60
        )
        assert response.status_code == 200
        
        data = response.json()
        sector_allocation = data.get('sector_allocation', [])
        
        assert len(sector_allocation) > 0, "sector_allocation should not be empty"
        
        # Check structure
        first_sector = sector_allocation[0]
        assert 'sector' in first_sector, "sector_allocation entry missing 'sector'"
        assert 'weight' in first_sector, "sector_allocation entry missing 'weight'"
        
        print(f"✓ sector_allocation has {len(sector_allocation)} sectors")

    def test_top_10_companies_structure(self, auth_cookies):
        """Verify top_10_companies has correct structure and is sorted by weight"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/allocation-analysis",
            cookies=auth_cookies,
            timeout=60
        )
        assert response.status_code == 200
        
        data = response.json()
        top_10 = data.get('top_10_companies', [])
        
        assert len(top_10) > 0, "top_10_companies should not be empty"
        assert len(top_10) <= 10, f"top_10_companies should have at most 10 entries, got {len(top_10)}"
        
        # Check structure
        for comp in top_10:
            assert 'name' in comp, "top_10_companies entry missing 'name'"
            assert 'weight' in comp, "top_10_companies entry missing 'weight'"
            assert 'sector' in comp, "top_10_companies entry missing 'sector'"
        
        print(f"✓ top_10_companies has {len(top_10)} entries: {[c['name'][:20] for c in top_10[:3]]}...")

    def test_top_5_sectors_structure(self, auth_cookies):
        """Verify top_5_sectors has correct structure"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/allocation-analysis",
            cookies=auth_cookies,
            timeout=60
        )
        assert response.status_code == 200
        
        data = response.json()
        top_5 = data.get('top_5_sectors', [])
        
        assert len(top_5) > 0, "top_5_sectors should not be empty"
        assert len(top_5) <= 5, f"top_5_sectors should have at most 5 entries, got {len(top_5)}"
        
        # Check structure
        for sec in top_5:
            assert 'sector' in sec, "top_5_sectors entry missing 'sector'"
            assert 'weight' in sec, "top_5_sectors entry missing 'weight'"
        
        print(f"✓ top_5_sectors: {[s['sector'] for s in top_5]}")

    def test_concentration_flags_structure(self, auth_cookies):
        """Verify concentration_flags has correct structure and flags sectors >30% and companies >10%"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/allocation-analysis",
            cookies=auth_cookies,
            timeout=60
        )
        assert response.status_code == 200
        
        data = response.json()
        flags = data.get('concentration_flags', [])
        
        # Check structure of each flag
        for flag in flags:
            assert 'type' in flag, "concentration_flag missing 'type'"
            assert flag['type'] in ['sector', 'company'], f"Invalid flag type: {flag['type']}"
            assert 'name' in flag, "concentration_flag missing 'name'"
            assert 'weight' in flag, "concentration_flag missing 'weight'"
            assert 'threshold' in flag, "concentration_flag missing 'threshold'"
            assert 'severity' in flag, "concentration_flag missing 'severity'"
            
            # Verify threshold values
            if flag['type'] == 'sector':
                assert flag['threshold'] == 0.30, f"Sector threshold should be 0.30, got {flag['threshold']}"
            elif flag['type'] == 'company':
                assert flag['threshold'] == 0.10, f"Company threshold should be 0.10, got {flag['threshold']}"
        
        print(f"✓ concentration_flags has {len(flags)} flags")
        for flag in flags:
            print(f"  - {flag['type']}: {flag['name']} at {flag['weight']*100:.1f}% (threshold: {flag['threshold']*100}%)")

    def test_data_quality_field(self, auth_cookies):
        """Verify data_quality field indicates estimated_funds count"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/allocation-analysis",
            cookies=auth_cookies,
            timeout=60
        )
        assert response.status_code == 200
        
        data = response.json()
        data_quality = data.get('data_quality', {})
        
        assert 'estimated_funds' in data_quality, "data_quality missing 'estimated_funds'"
        assert isinstance(data_quality['estimated_funds'], int), "estimated_funds should be an integer"
        
        print(f"✓ data_quality: estimated_funds={data_quality.get('estimated_funds')}, direct_equity_count={data_quality.get('direct_equity_count')}")
        if data_quality.get('notes'):
            print(f"  Notes: {data_quality['notes'][:80]}...")

    def test_caching_works(self, auth_cookies):
        """Verify second call returns instantly (cached for 6 hours)"""
        # First call (may be slow if not cached)
        start1 = time.time()
        response1 = requests.get(
            f"{BASE_URL}/api/portfolio/allocation-analysis",
            cookies=auth_cookies,
            timeout=60
        )
        time1 = time.time() - start1
        assert response1.status_code == 200
        
        # Second call (should be instant from cache)
        start2 = time.time()
        response2 = requests.get(
            f"{BASE_URL}/api/portfolio/allocation-analysis",
            cookies=auth_cookies,
            timeout=10
        )
        time2 = time.time() - start2
        assert response2.status_code == 200
        
        # Second call should be much faster (< 1 second if cached)
        assert time2 < 2.0, f"Second call took {time2:.2f}s - caching may not be working"
        
        print(f"✓ Caching works: First call {time1:.2f}s, Second call {time2:.2f}s")

    def test_hdfc_bank_concentration_flagged(self, auth_cookies):
        """Verify HDFC Bank is flagged for >10% concentration"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/allocation-analysis",
            cookies=auth_cookies,
            timeout=60
        )
        assert response.status_code == 200
        
        data = response.json()
        flags = data.get('concentration_flags', [])
        
        # Find HDFC Bank flag
        hdfc_flags = [f for f in flags if 'HDFC' in f.get('name', '').upper() and f['type'] == 'company']
        
        assert len(hdfc_flags) > 0, "HDFC Bank should be flagged for concentration"
        hdfc_flag = hdfc_flags[0]
        assert hdfc_flag['weight'] >= 0.10, f"HDFC Bank weight should be >= 10%, got {hdfc_flag['weight']*100:.1f}%"
        
        print(f"✓ HDFC Bank flagged: {hdfc_flag['name']} at {hdfc_flag['weight']*100:.1f}%")


class TestNoRegressionExistingEndpoints:
    """Verify existing endpoints still work after adding allocation-analysis"""

    def test_auth_me_works(self, auth_cookies):
        """Verify /api/auth/me still works"""
        response = requests.get(
            f"{BASE_URL}/api/auth/me",
            cookies=auth_cookies,
            timeout=10
        )
        assert response.status_code == 200
        data = response.json()
        assert 'user_id' in data or 'email' in data
        print(f"✓ /api/auth/me works")

    def test_portfolio_holdings_works(self, auth_cookies):
        """Verify /api/portfolio/holdings still works"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/holdings",
            cookies=auth_cookies,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        # API returns holdings directly as array
        assert isinstance(data, list), "Holdings should be returned as array"
        assert len(data) > 0, "Holdings should not be empty"
        print(f"✓ /api/portfolio/holdings works - {len(data)} holdings")

    def test_portfolio_analytics_works(self, auth_cookies):
        """Verify /api/portfolio/analytics still works"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/analytics",
            cookies=auth_cookies,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        assert 'total_invested' in data
        assert 'current_value' in data
        print(f"✓ /api/portfolio/analytics works")

    def test_deep_analytics_works(self, auth_cookies):
        """Verify /api/portfolio/deep-analytics still works"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/deep-analytics",
            cookies=auth_cookies,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        assert 'overexposure' in data
        assert 'overlap_matrix' in data
        print(f"✓ /api/portfolio/deep-analytics works")


class TestSecurityNoPII:
    """Verify no PII is sent to OpenAI"""

    def test_projection_excludes_pii_fields(self):
        """Verify the MongoDB projection in analytics.py excludes PII fields"""
        import re
        
        # Read the analytics.py file
        with open('/app/backend/routes/analytics.py', 'r') as f:
            content = f.read()
        
        # Find the projection for allocation-analysis endpoint
        # Look for the SECURITY comment and the projection
        security_section = re.search(
            r'SECURITY:.*?holdings = await db\.holdings\.find\([^)]+\{([^}]+)\}',
            content,
            re.DOTALL
        )
        
        assert security_section, "Could not find SECURITY projection in analytics.py"
        
        projection = security_section.group(1)
        
        # Verify PII fields are NOT in the projection
        pii_fields = ['user_id', 'email', 'pan', 'address', 'phone', 'mobile']
        for field in pii_fields:
            assert field not in projection.lower() or f'"{field}": 0' in projection.lower() or f"'{field}': 0" in projection.lower(), \
                f"PII field '{field}' should not be in projection or should be explicitly excluded"
        
        # Verify only safe fields are included
        safe_fields = ['name', 'ticker', 'asset_type', 'quantity', 'current_price', 'sector']
        for field in safe_fields:
            assert field in projection, f"Safe field '{field}' should be in projection"
        
        print(f"✓ Projection correctly excludes PII and includes only: {safe_fields}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
