#!/usr/bin/env python3

import requests
import sys
import json
from datetime import datetime

class NiveshAITester:
    def __init__(self, base_url="https://ai-advisor-30.preview.emergentagent.com"):
        self.base_url = base_url
        self.api_url = f"{base_url}/api"
        self.session_token = "test_session_wealth001"
        self.tests_run = 0
        self.tests_passed = 0
        self.headers = {
            'Content-Type': 'application/json',
            'Cookie': f'session_token={self.session_token}'
        }

    def run_test(self, name, method, endpoint, expected_status, data=None, timeout=30):
        """Run a single API test"""
        url = f"{self.api_url}/{endpoint}"
        self.tests_run += 1
        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {url}")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=self.headers, timeout=timeout)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=self.headers, timeout=timeout)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=self.headers, timeout=timeout)
            elif method == 'DELETE':
                response = requests.delete(url, headers=self.headers, timeout=timeout)

            success = response.status_code == expected_status
            if success:
                self.tests_passed += 1
                print(f"✅ Passed - Status: {response.status_code}")
                try:
                    response_data = response.json()
                    if isinstance(response_data, dict) and len(str(response_data)) < 500:
                        print(f"   Response: {response_data}")
                    elif isinstance(response_data, list):
                        print(f"   Response: List with {len(response_data)} items")
                    else:
                        print(f"   Response: Large data object")
                except:
                    print(f"   Response: Non-JSON or large response")
            else:
                print(f"❌ Failed - Expected {expected_status}, got {response.status_code}")
                try:
                    error_data = response.json()
                    print(f"   Error: {error_data}")
                except:
                    print(f"   Error: {response.text[:200]}")

            return success, response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text

        except requests.exceptions.Timeout:
            print(f"❌ Failed - Request timeout after {timeout}s")
            return False, {}
        except Exception as e:
            print(f"❌ Failed - Error: {str(e)}")
            return False, {}

    def test_auth_me(self):
        """Test authentication with test session"""
        success, response = self.run_test(
            "Authentication Check",
            "GET",
            "auth/me",
            200
        )
        if success and isinstance(response, dict):
            print(f"   User: {response.get('name', 'Unknown')} ({response.get('user_id', 'No ID')})")
            return response.get('user_id')
        return None

    def test_portfolio_analytics(self):
        """Test portfolio analytics endpoint"""
        success, response = self.run_test(
            "Portfolio Analytics",
            "GET",
            "portfolio/analytics",
            200
        )
        if success and isinstance(response, dict):
            print(f"   Holdings: {response.get('holdings_count', 0)}")
            print(f"   Current Value: ₹{response.get('current_value', 0):,.2f}")
            print(f"   Returns: {response.get('returns_pct', 0):.1f}%")
            return response
        return None

    def test_holdings_list(self):
        """Test holdings list endpoint"""
        success, response = self.run_test(
            "Holdings List",
            "GET",
            "portfolio/holdings",
            200
        )
        if success and isinstance(response, list):
            print(f"   Found {len(response)} holdings")
            if len(response) > 0:
                sample = response[0]
                print(f"   Sample: {sample.get('name', 'Unknown')} - {sample.get('asset_type', 'Unknown type')}")
            return response
        return []

    def test_insights_analysis(self):
        """Test insights analysis endpoint (should return existing data)"""
        success, response = self.run_test(
            "Insights Analysis (Existing)",
            "GET",
            "insights/analysis",
            200
        )
        if success and response:
            print(f"   Analysis available: {bool(response)}")
            if isinstance(response, dict):
                insights = response.get('insights', [])
                print(f"   Insights count: {len(insights)}")
                if response.get('problem_distribution'):
                    print(f"   Problem distribution: {len(response['problem_distribution'])} categories")
                if response.get('risk_gauge'):
                    gauge = response['risk_gauge']
                    print(f"   Risk: {gauge.get('current', 0)}/100 → {gauge.get('target', 0)}/100")
            return response
        return None

    def test_insights_generate(self):
        """Test insights generation endpoint (AI analysis)"""
        print(f"\n🔍 Testing Insights Generation (AI Analysis)...")
        print(f"   URL: {self.api_url}/insights/generate")
        print("   ⚠️  This may take 30-60 seconds for AI processing...")
        
        success, response = self.run_test(
            "Insights Generation",
            "POST",
            "insights/generate",
            200,
            timeout=90  # Longer timeout for AI processing
        )
        if success and isinstance(response, dict):
            insights = response.get('insights', [])
            print(f"   Generated {len(insights)} insights")
            
            # Check key components
            components = ['problem_distribution', 'before_after', 'action_funnel', 'overlap_pairs', 'cost_leakage', 'risk_gauge']
            for comp in components:
                if comp in response:
                    print(f"   ✅ {comp}: Present")
                else:
                    print(f"   ❌ {comp}: Missing")
            
            return response
        return None

    def test_basic_insights(self):
        """Test basic insights endpoint"""
        success, response = self.run_test(
            "Basic Insights List",
            "GET",
            "insights",
            200
        )
        if success and isinstance(response, list):
            print(f"   Found {len(response)} basic insights")
            return response
        return []

def main():
    print("🚀 Starting nivesh.ai Backend API Tests")
    print("=" * 50)
    
    tester = NiveshAITester()
    
    # Test authentication first
    user_id = tester.test_auth_me()
    if not user_id:
        print("\n❌ Authentication failed - cannot proceed with other tests")
        return 1

    # Test core portfolio functionality
    analytics = tester.test_portfolio_analytics()
    holdings = tester.test_holdings_list()
    
    if not holdings:
        print("\n⚠️  No holdings found - insights tests may not be meaningful")
    
    # Test insights functionality
    basic_insights = tester.test_basic_insights()
    existing_analysis = tester.test_insights_analysis()
    
    # Test AI insights generation (this is the main new feature)
    generated_analysis = tester.test_insights_generate()
    
    # Print summary
    print("\n" + "=" * 50)
    print(f"📊 Test Results: {tester.tests_passed}/{tester.tests_run} passed")
    
    if tester.tests_passed == tester.tests_run:
        print("🎉 All backend tests passed!")
        return 0
    else:
        print(f"⚠️  {tester.tests_run - tester.tests_passed} tests failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())