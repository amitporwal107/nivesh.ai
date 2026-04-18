#!/usr/bin/env python3
"""
Backend API Testing for nivesh.ai - Architecture Refactor Testing
Tests new service layer, repository layer, AI engine, and middleware features
"""
import requests
import json
import time
import sys
from datetime import datetime

class NiveshAPITester:
    def __init__(self, base_url="https://nivesh-ai-preview.preview.emergentagent.com"):
        self.base_url = base_url
        self.session_token = "test_session_wealth001"
        self.user_id = "test-user-wealth001"
        self.tests_run = 0
        self.tests_passed = 0
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.session_token}'
        }

    def log_test(self, name, success, details=""):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
            print(f"✅ {name}")
        else:
            print(f"❌ {name} - {details}")
        return success

    def make_request(self, method, endpoint, data=None, expected_status=200):
        """Make API request with error handling"""
        url = f"{self.base_url}/api/{endpoint}"
        try:
            if method == 'GET':
                response = requests.get(url, headers=self.headers, timeout=30)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=self.headers, timeout=30)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=self.headers, timeout=30)
            elif method == 'DELETE':
                response = requests.delete(url, headers=self.headers, timeout=30)
            
            success = response.status_code == expected_status
            return success, response.json() if success else {}, response.status_code
        except Exception as e:
            return False, {}, f"Error: {str(e)}"

    def test_auth_endpoints(self):
        """Test authentication endpoints"""
        print("\n🔐 Testing Authentication...")
        
        # Test /auth/me with session token
        success, data, status = self.make_request('GET', 'auth/me')
        if success and data.get('user_id') == self.user_id:
            self.log_test("Auth: Get current user", True)
        else:
            self.log_test("Auth: Get current user", False, f"Status: {status}, Data: {data}")

    def test_portfolio_analytics_new_fields(self):
        """Test new fields in /api/portfolio/analytics"""
        print("\n📊 Testing Portfolio Analytics (New Architecture)...")
        
        success, data, status = self.make_request('GET', 'portfolio/analytics')
        
        if not success:
            self.log_test("Analytics: API call", False, f"Status: {status}")
            return False
        
        # Test health_score field
        health_score = data.get('health_score')
        if health_score and isinstance(health_score, dict):
            required_fields = ['overall', 'grade', 'diversification', 'risk', 'cost_efficiency', 'performance']
            has_all_fields = all(field in health_score for field in required_fields)
            self.log_test("Analytics: health_score structure", has_all_fields, 
                         f"Missing: {[f for f in required_fields if f not in health_score]}")
            
            # Validate grade format
            grade = health_score.get('grade')
            valid_grades = ['A+', 'A', 'B+', 'B', 'C', 'D', 'F', 'N/A']
            self.log_test("Analytics: health_score grade format", grade in valid_grades, f"Grade: {grade}")
        else:
            self.log_test("Analytics: health_score field", False, "Missing or invalid health_score")
        
        # Test risk_analysis field
        risk_analysis = data.get('risk_analysis')
        if risk_analysis and isinstance(risk_analysis, dict):
            required_fields = ['score', 'label', 'warnings']
            has_all_fields = all(field in risk_analysis for field in required_fields)
            self.log_test("Analytics: risk_analysis structure", has_all_fields,
                         f"Missing: {[f for f in required_fields if f not in risk_analysis]}")
            
            # Validate warnings is array
            warnings = risk_analysis.get('warnings', [])
            self.log_test("Analytics: risk_analysis warnings array", isinstance(warnings, list))
        else:
            self.log_test("Analytics: risk_analysis field", False, "Missing or invalid risk_analysis")
        
        # Test recommendations field
        recommendations = data.get('recommendations')
        if recommendations and isinstance(recommendations, list):
            self.log_test("Analytics: recommendations array", True)
            
            if recommendations:
                rec = recommendations[0]
                required_fields = ['action', 'title', 'priority', 'impact']
                has_all_fields = all(field in rec for field in required_fields)
                self.log_test("Analytics: recommendation structure", has_all_fields,
                             f"Missing: {[f for f in required_fields if f not in rec]}")
        else:
            self.log_test("Analytics: recommendations field", False, "Missing or invalid recommendations")
        
        return True

    def test_rate_limiting(self):
        """Test rate limiting middleware"""
        print("\n🚦 Testing Rate Limiting...")
        
        # Make rapid requests to trigger rate limit
        requests_made = 0
        rate_limited = False
        
        for i in range(25):  # Try to exceed the limit
            success, data, status = self.make_request('GET', 'portfolio/analytics')
            requests_made += 1
            
            if status == 429:
                rate_limited = True
                break
            
            time.sleep(0.1)  # Small delay between requests
        
        self.log_test("Rate Limiting: 429 response triggered", rate_limited, 
                     f"Made {requests_made} requests before rate limit")

    def test_holdings_crud(self):
        """Test holdings CRUD operations"""
        print("\n📝 Testing Holdings CRUD...")
        
        # Create a test holding
        holding_data = {
            "name": "Test Stock CRUD",
            "ticker": "TEST",
            "asset_type": "equity",
            "quantity": 100,
            "buy_price": 150.0,
            "current_price": 160.0,
            "sector": "Technology",
            "portfolio_id": ""
        }
        
        success, data, status = self.make_request('POST', 'portfolio/holdings', holding_data, 200)
        if success and data.get('holding_id'):
            holding_id = data['holding_id']
            self.log_test("Holdings: Create", True)
            
            # Update the holding
            update_data = {"current_price": 170.0}
            success, data, status = self.make_request('PUT', f'portfolio/holdings/{holding_id}', update_data)
            self.log_test("Holdings: Update", success and data.get('current_price') == 170.0)
            
            # Delete the holding
            success, data, status = self.make_request('DELETE', f'portfolio/holdings/{holding_id}')
            self.log_test("Holdings: Delete", success)
        else:
            self.log_test("Holdings: Create", False, f"Status: {status}, Data: {data}")

    def test_ai_chat_endpoints(self):
        """Test AI chat functionality"""
        print("\n🤖 Testing AI Chat...")
        
        # Test sending a chat message
        chat_data = {"message": "What is my portfolio risk level?"}
        success, data, status = self.make_request('POST', 'chat/send', chat_data)
        
        if success and data.get('ai_message'):
            self.log_test("AI Chat: Send message", True)
            
            # Test getting chat messages
            success, messages, status = self.make_request('GET', 'chat/messages')
            self.log_test("AI Chat: Get messages", success and isinstance(messages, list))
        else:
            self.log_test("AI Chat: Send message", False, f"Status: {status}")

    def test_insights_generation(self):
        """Test AI insights generation"""
        print("\n💡 Testing AI Insights...")
        
        success, data, status = self.make_request('POST', 'insights/generate')
        
        if success and data.get('insights'):
            insights = data['insights']
            self.log_test("Insights: Generate", isinstance(insights, list))
            
            if insights:
                insight = insights[0]
                required_fields = ['title', 'description', 'type', 'impact']
                has_all_fields = all(field in insight for field in required_fields)
                self.log_test("Insights: Structure", has_all_fields)
        else:
            self.log_test("Insights: Generate", False, f"Status: {status}")

    def test_search_instruments(self):
        """Test instrument search"""
        print("\n🔍 Testing Instrument Search...")
        
        success, data, status = self.make_request('GET', 'search/instruments?q=RELIANCE')
        self.log_test("Search: Instruments", success and isinstance(data, list))

    def test_portfolios_management(self):
        """Test portfolio management"""
        print("\n📁 Testing Portfolio Management...")
        
        # Create portfolio
        portfolio_data = {
            "name": "Test Portfolio",
            "member_name": "Test User",
            "relationship": "Self"
        }
        
        success, data, status = self.make_request('POST', 'portfolios', portfolio_data)
        if success and data.get('portfolio_id'):
            portfolio_id = data['portfolio_id']
            self.log_test("Portfolios: Create", True)
            
            # List portfolios
            success, portfolios, status = self.make_request('GET', 'portfolios')
            self.log_test("Portfolios: List", success and isinstance(portfolios, list))
            
            # Delete portfolio
            success, data, status = self.make_request('DELETE', f'portfolios/{portfolio_id}')
            self.log_test("Portfolios: Delete", success)
        else:
            self.log_test("Portfolios: Create", False, f"Status: {status}")

    def run_all_tests(self):
        """Run all test suites"""
        print("🚀 Starting nivesh.ai Backend API Tests")
        print(f"📍 Testing against: {self.base_url}")
        print(f"👤 User ID: {self.user_id}")
        print(f"🔑 Session: {self.session_token}")
        
        # Run test suites
        self.test_auth_endpoints()
        self.test_portfolio_analytics_new_fields()
        self.test_holdings_crud()
        self.test_portfolios_management()
        self.test_search_instruments()
        self.test_ai_chat_endpoints()
        self.test_insights_generation()
        self.test_rate_limiting()
        
        # Print summary
        print(f"\n📊 Test Summary:")
        print(f"   Tests Run: {self.tests_run}")
        print(f"   Tests Passed: {self.tests_passed}")
        print(f"   Success Rate: {(self.tests_passed/self.tests_run*100):.1f}%")
        
        return self.tests_passed == self.tests_run

if __name__ == "__main__":
    tester = NiveshAPITester()
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)