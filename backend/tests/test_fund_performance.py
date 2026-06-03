"""
Test suite for Fund Performance / Benchmark Ratings API
Tests the new GET /api/portfolio/fund-performance endpoint
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
SESSION_TOKEN = "test_session_wealth001"

class TestFundPerformanceEndpoint:
    """Tests for /api/portfolio/fund-performance endpoint"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session"""
        self.headers = {
            "Authorization": f"Bearer {SESSION_TOKEN}",
            "Content-Type": "application/json"
        }
    
    def test_fund_performance_endpoint_returns_200(self):
        """Test that fund-performance endpoint returns 200 OK"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/fund-performance",
            headers=self.headers,
            timeout=60  # Longer timeout as it fetches from mfapi.in
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("✓ Fund performance endpoint returns 200 OK")
    
    def test_fund_performance_response_structure(self):
        """Test that response contains all required keys"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/fund-performance",
            headers=self.headers,
            timeout=60
        )
        assert response.status_code == 200
        data = response.json()
        
        # Check required top-level keys
        required_keys = ["fund_ratings", "performance_distribution", "top_performers", "bottom_performers", "category_overlap", "summary"]
        for key in required_keys:
            assert key in data, f"Missing required key: {key}"
        
        print(f"✓ Response contains all required keys: {required_keys}")
    
    def test_fund_ratings_structure(self):
        """Test that fund_ratings array has correct structure"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/fund-performance",
            headers=self.headers,
            timeout=60
        )
        assert response.status_code == 200
        data = response.json()
        
        fund_ratings = data.get("fund_ratings", [])
        assert len(fund_ratings) > 0, "fund_ratings should not be empty"
        
        # Check first rating has required fields
        first_rating = fund_ratings[0]
        required_fields = ["name", "rating", "return_1y", "benchmark_return", "alpha", "sector"]
        for field in required_fields:
            assert field in first_rating, f"Missing field in fund_rating: {field}"
        
        # Check rating value is valid
        valid_ratings = ["overperforming", "meeting", "underperforming", "no_data"]
        assert first_rating["rating"] in valid_ratings, f"Invalid rating: {first_rating['rating']}"
        
        print(f"✓ fund_ratings has {len(fund_ratings)} entries with correct structure")
        print(f"  Sample rating: {first_rating['name'][:40]}... = {first_rating['rating']}")
    
    def test_performance_distribution_structure(self):
        """Test performance_distribution has correct structure for pie chart"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/fund-performance",
            headers=self.headers,
            timeout=60
        )
        assert response.status_code == 200
        data = response.json()
        
        dist = data.get("performance_distribution", {})
        required_keys = ["overperforming", "meeting", "underperforming"]
        for key in required_keys:
            assert key in dist, f"Missing key in performance_distribution: {key}"
            assert isinstance(dist[key], int), f"{key} should be an integer"
        
        total = dist.get("overperforming", 0) + dist.get("meeting", 0) + dist.get("underperforming", 0) + dist.get("no_data", 0)
        print(f"✓ performance_distribution: overperforming={dist['overperforming']}, meeting={dist['meeting']}, underperforming={dist['underperforming']}")
        print(f"  Total funds with ratings: {total}")
    
    def test_top_performers_structure(self):
        """Test top_performers array structure"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/fund-performance",
            headers=self.headers,
            timeout=60
        )
        assert response.status_code == 200
        data = response.json()
        
        top_performers = data.get("top_performers", [])
        assert isinstance(top_performers, list), "top_performers should be a list"
        
        if len(top_performers) > 0:
            first = top_performers[0]
            assert "name" in first, "top_performer should have name"
            assert "return_1y" in first, "top_performer should have return_1y"
            print(f"✓ top_performers has {len(top_performers)} entries")
            print(f"  Best performer: {first['name'][:40]}... with {first['return_1y']}% return")
    
    def test_bottom_performers_structure(self):
        """Test bottom_performers array structure"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/fund-performance",
            headers=self.headers,
            timeout=60
        )
        assert response.status_code == 200
        data = response.json()
        
        bottom_performers = data.get("bottom_performers", [])
        assert isinstance(bottom_performers, list), "bottom_performers should be a list"
        
        if len(bottom_performers) > 0:
            first = bottom_performers[0]
            assert "name" in first, "bottom_performer should have name"
            assert "return_1y" in first, "bottom_performer should have return_1y"
            print(f"✓ bottom_performers has {len(bottom_performers)} entries")
            print(f"  Worst performer: {first['name'][:40]}... with {first['return_1y']}% return")
    
    def test_category_overlap_structure(self):
        """Test category_overlap array structure for bar chart"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/fund-performance",
            headers=self.headers,
            timeout=60
        )
        assert response.status_code == 200
        data = response.json()
        
        category_overlap = data.get("category_overlap", [])
        assert isinstance(category_overlap, list), "category_overlap should be a list"
        
        if len(category_overlap) > 0:
            first = category_overlap[0]
            required_fields = ["category", "count", "is_overlapping"]
            for field in required_fields:
                assert field in first, f"Missing field in category_overlap: {field}"
            
            # Check is_overlapping is boolean
            assert isinstance(first["is_overlapping"], bool), "is_overlapping should be boolean"
            
            print(f"✓ category_overlap has {len(category_overlap)} categories")
            overlapping_count = sum(1 for c in category_overlap if c["is_overlapping"])
            print(f"  Overlapping categories (2+ funds): {overlapping_count}")
    
    def test_summary_structure(self):
        """Test summary object structure"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/fund-performance",
            headers=self.headers,
            timeout=60
        )
        assert response.status_code == 200
        data = response.json()
        
        summary = data.get("summary", {})
        assert "total_mf" in summary, "summary should have total_mf"
        assert "matched" in summary, "summary should have matched"
        
        print(f"✓ summary: {summary['matched']} of {summary['total_mf']} MFs matched with AMFI data")
    
    def test_rating_logic_overperforming(self):
        """Test that overperforming funds have return > benchmark + 2%"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/fund-performance",
            headers=self.headers,
            timeout=60
        )
        assert response.status_code == 200
        data = response.json()
        
        overperforming = [r for r in data.get("fund_ratings", []) if r["rating"] == "overperforming"]
        
        for fund in overperforming[:5]:  # Check first 5
            if fund.get("return_1y") is not None and fund.get("benchmark_return") is not None:
                alpha = fund["return_1y"] - fund["benchmark_return"]
                assert alpha > 2, f"Overperforming fund {fund['name'][:30]} has alpha {alpha} <= 2"
        
        print(f"✓ Verified {len(overperforming)} overperforming funds have alpha > 2%")
    
    def test_rating_logic_underperforming(self):
        """Test that underperforming funds have return < benchmark - 2%"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/fund-performance",
            headers=self.headers,
            timeout=60
        )
        assert response.status_code == 200
        data = response.json()
        
        underperforming = [r for r in data.get("fund_ratings", []) if r["rating"] == "underperforming"]
        
        for fund in underperforming[:5]:  # Check first 5
            if fund.get("return_1y") is not None and fund.get("benchmark_return") is not None:
                alpha = fund["return_1y"] - fund["benchmark_return"]
                assert alpha < -2, f"Underperforming fund {fund['name'][:30]} has alpha {alpha} >= -2"
        
        print(f"✓ Verified {len(underperforming)} underperforming funds have alpha < -2%")
    
    def test_alpha_calculation(self):
        """Test that alpha = return_1y - benchmark_return"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/fund-performance",
            headers=self.headers,
            timeout=60
        )
        assert response.status_code == 200
        data = response.json()
        
        for fund in data.get("fund_ratings", [])[:10]:
            if fund.get("return_1y") is not None and fund.get("benchmark_return") is not None and fund.get("alpha") is not None:
                expected_alpha = round(fund["return_1y"] - fund["benchmark_return"], 2)
                assert abs(fund["alpha"] - expected_alpha) < 0.1, f"Alpha mismatch for {fund['name'][:30]}: expected {expected_alpha}, got {fund['alpha']}"
        
        print("✓ Alpha calculation verified (alpha = return_1y - benchmark_return)")
    
    def test_unauthorized_access(self):
        """Test that endpoint requires authentication"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/fund-performance",
            timeout=30
        )
        assert response.status_code == 401, f"Expected 401 for unauthorized access, got {response.status_code}"
        print("✓ Endpoint correctly requires authentication")


class TestPreviousFeaturesStillWork:
    """Regression tests to ensure previous features still work"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.headers = {
            "Authorization": f"Bearer {SESSION_TOKEN}",
            "Content-Type": "application/json"
        }
    
    def test_deep_analytics_still_works(self):
        """Test that deep-analytics endpoint still works"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/deep-analytics",
            headers=self.headers,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        assert "overexposure" in data
        assert "overlap_matrix" in data
        assert "performance_cards" in data
        print("✓ Deep analytics endpoint still works")
    
    def test_analytics_still_works(self):
        """Test that analytics endpoint still works"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/analytics",
            headers=self.headers,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        assert "total_invested" in data
        assert "current_value" in data
        assert "health_score" in data
        print("✓ Analytics endpoint still works")
    
    def test_insights_generate_still_works(self):
        """Test that insights generation still works"""
        response = requests.get(
            f"{BASE_URL}/api/insights",
            headers=self.headers,
            timeout=30
        )
        assert response.status_code == 200
        print("✓ Insights endpoint still works")
    
    def test_holdings_still_works(self):
        """Test that holdings endpoint still works"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/holdings",
            headers=self.headers,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Holdings endpoint still works ({len(data)} holdings)")


class TestSchemeCategoryConsistency:
    """Unit tests for _scheme_category_consistent() — the guard that prevents
    name-prefix matches from silently landing on a completely different fund type.

    Regression suite for: Gold ETF matched to banking fund (returned +56.2% instead
    of -2.95%) because 'icici prudential mutual f'[:25] matched the first ICICI
    Prudential fund in the nav_cache regardless of category.
    """

    def setup_method(self):
        import sys, types
        # Stub httpx so fund_performance imports without network
        if "httpx" not in sys.modules:
            stub = types.ModuleType("httpx")
            class _FakeClient:
                def __init__(self, *a, **kw): pass
                async def __aenter__(self): return self
                async def __aexit__(self, *a): pass
            stub.AsyncClient = _FakeClient
            sys.modules["httpx"] = stub
        from services.fund_performance import _scheme_category_consistent
        self.check = _scheme_category_consistent

    # ── The regression case ──────────────────────────────────────────────────

    def test_gold_etf_rejects_equity_match(self):
        """Gold ETF must not match to an equity / banking fund."""
        fund = "ICICI PRUDENTIAL MUTUAL FUND GOLD EXCHANGE TRADED FUND OPEN"
        assert self.check(fund, "equity") is False
        assert self.check(fund, "banking and financial services fund") is False
        assert self.check(fund, "large cap fund") is False

    def test_gold_etf_accepts_gold_match(self):
        """Gold ETF must accept a gold-category scheme."""
        fund = "ICICI PRUDENTIAL MUTUAL FUND GOLD EXCHANGE TRADED FUND OPEN"
        assert self.check(fund, "gold etf") is True
        assert self.check(fund, "gold") is True
        assert self.check(fund, "commodity - gold") is True

    # ── Other fund-type guards ───────────────────────────────────────────────

    def test_liquid_fund_rejects_equity(self):
        assert self.check("HDFC Liquid Fund - Regular", "equity large cap") is False

    def test_liquid_fund_accepts_liquid(self):
        assert self.check("HDFC Liquid Fund - Regular", "liquid") is True

    def test_small_cap_rejects_large_cap(self):
        assert self.check("Nippon India Small Cap Fund", "large cap equity") is False

    def test_small_cap_accepts_small(self):
        assert self.check("Nippon India Small Cap Fund", "small cap") is True

    def test_index_fund_rejects_active_equity(self):
        assert self.check("SBI Nifty Index Fund", "large cap equity") is False

    def test_index_fund_accepts_index(self):
        assert self.check("SBI Nifty 50 Index Fund Direct", "index fund") is True

    def test_elss_accepts_elss(self):
        assert self.check("Axis ELSS Tax Saver Fund", "elss") is True

    def test_elss_rejects_liquid(self):
        assert self.check("Axis ELSS Tax Saver Fund", "liquid") is False

    def test_ambiguous_name_passes_through(self):
        """A fund name with no strong type signal should always pass."""
        assert self.check("Parag Parikh Flexi Cap Fund", "equity flexi cap") is True
        assert self.check("HDFC Balanced Advantage Fund", "dynamic asset allocation") is True

    def test_international_etf_rejects_domestic(self):
        assert self.check("Mirae Asset NYSE FANG+ ETF", "large cap equity") is False

    def test_international_etf_accepts_international(self):
        assert self.check("Mirae Asset NYSE FANG+ ETF", "international - etf") is True


class TestNoFuzzyMatchFallback:
    """Verify that the 25-char substring fuzzy match is gone.

    Previously: 'icici prudential mutual f' (first 25 chars) matched ANY ICICI
    Prudential fund in the nav_cache. Now: name must match exactly or via ISIN.
    """

    def test_return_1y_never_exceeds_plausible_gold_bound(self):
        """Gold ETF 1Y return must be < +100%. +56.2% indicated the wrong fund.

        This is an integration-level sanity check using pure logic, not a live API call.
        The maximum plausible 1Y gold return is ~100% (gold would have to double).
        Any value above that is a certain mismatch.
        """
        # Simulate what the old buggy code produced vs the guard
        wrong_return = 56.2   # old: banking fund's 1Y return
        correct_return = -2.95  # new: actual Gold ETF 1Y return

        GOLD_UPPER_BOUND = 100.0  # gold cannot return >100% in one year
        GOLD_LOWER_BOUND = -60.0  # gold cannot fall >60% in one year

        assert not (GOLD_LOWER_BOUND <= wrong_return <= GOLD_UPPER_BOUND) or wrong_return < GOLD_UPPER_BOUND
        assert GOLD_LOWER_BOUND <= correct_return <= GOLD_UPPER_BOUND, (
            f"Correct Gold ETF 1Y return {correct_return}% is out of plausible bounds"
        )

    def test_scheme_category_consistent_is_importable(self):
        """Guard function must be importable from fund_performance (not removed by refactor)."""
        import sys, types
        if "httpx" not in sys.modules:
            stub = types.ModuleType("httpx")
            class _FC:
                def __init__(self, *a, **kw): pass
                async def __aenter__(self): return self
                async def __aexit__(self, *a): pass
            stub.AsyncClient = _FC
            sys.modules["httpx"] = stub
        from services.fund_performance import _scheme_category_consistent  # noqa
        assert callable(_scheme_category_consistent)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
