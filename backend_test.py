import requests
import sys
import json
from datetime import datetime

class WealthManagementAPITester:
    def __init__(self, base_url="https://ai-advisor-30.preview.emergentagent.com"):
        self.base_url = base_url
        self.api_url = f"{base_url}/api"
        self.session_token = "test_session_wealth001"
        self.tests_run = 0
        self.tests_passed = 0
        self.created_portfolio_id = None
        self.created_holding_id = None

    def run_test(self, name, method, endpoint, expected_status, data=None, headers=None):
        """Run a single API test"""
        url = f"{self.api_url}/{endpoint}"
        test_headers = {'Content-Type': 'application/json'}
        
        # Add session token via cookie
        cookies = {'session_token': self.session_token}
        
        if headers:
            test_headers.update(headers)

        self.tests_run += 1
        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {url}")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=test_headers, cookies=cookies)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=test_headers, cookies=cookies)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=test_headers, cookies=cookies)
            elif method == 'DELETE':
                response = requests.delete(url, headers=test_headers, cookies=cookies)

            success = response.status_code == expected_status
            if success:
                self.tests_passed += 1
                print(f"✅ Passed - Status: {response.status_code}")
                try:
                    response_data = response.json()
                    if isinstance(response_data, dict) and len(str(response_data)) < 500:
                        print(f"   Response: {response_data}")
                    elif isinstance(response_data, list):
                        print(f"   Response: {len(response_data)} items returned")
                    return True, response_data
                except:
                    return True, {}
            else:
                print(f"❌ Failed - Expected {expected_status}, got {response.status_code}")
                try:
                    error_data = response.json()
                    print(f"   Error: {error_data}")
                except:
                    print(f"   Error: {response.text}")
                return False, {}

        except Exception as e:
            print(f"❌ Failed - Error: {str(e)}")
            return False, {}

    def test_auth_me(self):
        """Test authentication endpoint"""
        success, response = self.run_test(
            "Auth - Get Current User",
            "GET",
            "auth/me",
            200
        )
        if success and response.get('user_id') == 'test-user-wealth001':
            print(f"   ✅ Authenticated as: {response.get('name', 'Unknown')}")
            return True
        return False

    def test_portfolios_list(self):
        """Test listing portfolios"""
        success, response = self.run_test(
            "Portfolios - List All",
            "GET",
            "portfolios",
            200
        )
        if success:
            print(f"   📊 Found {len(response)} portfolios")
            return True, response
        return False, []

    def test_create_portfolio(self):
        """Test creating a new portfolio"""
        portfolio_data = {
            "name": "Test Portfolio",
            "member_name": "Test Member",
            "relationship": "Self"
        }
        success, response = self.run_test(
            "Portfolios - Create New",
            "POST",
            "portfolios",
            200,
            data=portfolio_data
        )
        if success and response.get('portfolio_id'):
            self.created_portfolio_id = response['portfolio_id']
            print(f"   ✅ Created portfolio: {self.created_portfolio_id}")
            return True
        return False

    def test_delete_portfolio(self):
        """Test deleting a portfolio"""
        if not self.created_portfolio_id:
            print("❌ No portfolio ID to delete")
            return False
            
        success, response = self.run_test(
            "Portfolios - Delete",
            "DELETE",
            f"portfolios/{self.created_portfolio_id}",
            200
        )
        if success:
            print(f"   ✅ Deleted portfolio and holdings")
            return True
        return False

    def test_search_instruments_stocks(self):
        """Test instrument search for stocks"""
        success, response = self.run_test(
            "Search - Stock Instruments (reliance)",
            "GET",
            "search/instruments?q=reliance",
            200
        )
        if success and len(response) > 0:
            found_reliance = any('reliance' in item.get('name', '').lower() for item in response)
            if found_reliance:
                print(f"   ✅ Found Reliance in search results")
                return True
            else:
                print(f"   ❌ Reliance not found in results")
        return False

    def test_search_instruments_mf(self):
        """Test instrument search for mutual funds"""
        success, response = self.run_test(
            "Search - Mutual Fund Instruments (hdfc flexi)",
            "GET",
            "search/instruments?q=hdfc flexi",
            200
        )
        if success and len(response) > 0:
            found_hdfc_flexi = any('hdfc' in item.get('name', '').lower() and 'flexi' in item.get('name', '').lower() for item in response)
            if found_hdfc_flexi:
                print(f"   ✅ Found HDFC Flexi Cap in search results")
                return True
            else:
                print(f"   ❌ HDFC Flexi Cap not found in results")
        return False

    def test_holdings_crud(self):
        """Test holdings CRUD operations"""
        # Create holding
        holding_data = {
            "name": "Test Stock",
            "ticker": "TEST",
            "asset_type": "equity",
            "quantity": 100,
            "buy_price": 500,
            "current_price": 550,
            "sector": "IT",
            "portfolio_id": self.created_portfolio_id or ""
        }
        
        success, response = self.run_test(
            "Holdings - Create",
            "POST",
            "portfolio/holdings",
            200,
            data=holding_data
        )
        
        if success and response.get('holding_id'):
            self.created_holding_id = response['holding_id']
            print(f"   ✅ Created holding: {self.created_holding_id}")
            
            # Test get holdings
            success, holdings = self.run_test(
                "Holdings - Get All",
                "GET",
                "portfolio/holdings",
                200
            )
            
            if success:
                print(f"   ✅ Retrieved {len(holdings)} holdings")
                
                # Test update holding
                update_data = {"current_price": 600}
                success, updated = self.run_test(
                    "Holdings - Update",
                    "PUT",
                    f"portfolio/holdings/{self.created_holding_id}",
                    200,
                    data=update_data
                )
                
                if success:
                    print(f"   ✅ Updated holding price to 600")
                    
                    # Test delete holding
                    success, deleted = self.run_test(
                        "Holdings - Delete",
                        "DELETE",
                        f"portfolio/holdings/{self.created_holding_id}",
                        200
                    )
                    
                    if success:
                        print(f"   ✅ Deleted holding")
                        return True
        
        return False

    def test_analytics(self):
        """Test portfolio analytics"""
        success, response = self.run_test(
            "Analytics - Portfolio Summary",
            "GET",
            "portfolio/analytics",
            200
        )
        if success:
            required_fields = ['total_invested', 'current_value', 'total_returns', 'returns_pct', 'holdings_count']
            has_all_fields = all(field in response for field in required_fields)
            if has_all_fields:
                print(f"   ✅ Analytics contains all required fields")
                print(f"   📊 Holdings: {response.get('holdings_count', 0)}, Value: ₹{response.get('current_value', 0):,.0f}")
                return True
            else:
                missing = [f for f in required_fields if f not in response]
                print(f"   ❌ Missing fields: {missing}")
        return False

    def test_chat_functionality(self):
        """Test AI chat functionality"""
        chat_data = {"message": "What is my portfolio performance?"}
        success, response = self.run_test(
            "Chat - Send Message",
            "POST",
            "chat/send",
            200,
            data=chat_data
        )
        if success and response.get('ai_message'):
            print(f"   ✅ AI responded to chat message")
            return True
        return False

    def test_insights_generation(self):
        """Test AI insights generation"""
        success, response = self.run_test(
            "Insights - Generate AI Insights",
            "POST",
            "insights/generate",
            200
        )
        if success and response.get('insights'):
            insights = response['insights']
            print(f"   ✅ Generated {len(insights)} insights")
            return True
        return False

def main():
    print("🚀 Starting Wealth Management API Tests")
    print("=" * 50)
    
    tester = WealthManagementAPITester()
    
    # Test sequence
    tests = [
        ("Authentication", tester.test_auth_me),
        ("List Portfolios", tester.test_portfolios_list),
        ("Create Portfolio", tester.test_create_portfolio),
        ("Search Stocks", tester.test_search_instruments_stocks),
        ("Search Mutual Funds", tester.test_search_instruments_mf),
        ("Holdings CRUD", tester.test_holdings_crud),
        ("Delete Portfolio", tester.test_delete_portfolio),
        ("Analytics", tester.test_analytics),
        ("Chat Functionality", tester.test_chat_functionality),
        ("Insights Generation", tester.test_insights_generation),
    ]
    
    failed_tests = []
    
    for test_name, test_func in tests:
        print(f"\n{'='*20} {test_name} {'='*20}")
        try:
            result = test_func()
            if not result:
                failed_tests.append(test_name)
        except Exception as e:
            print(f"❌ {test_name} failed with exception: {e}")
            failed_tests.append(test_name)
    
    # Print final results
    print(f"\n{'='*50}")
    print(f"📊 FINAL RESULTS")
    print(f"{'='*50}")
    print(f"✅ Tests passed: {tester.tests_passed}/{tester.tests_run}")
    print(f"❌ Tests failed: {tester.tests_run - tester.tests_passed}/{tester.tests_run}")
    
    if failed_tests:
        print(f"\n❌ Failed tests:")
        for test in failed_tests:
            print(f"   - {test}")
    else:
        print(f"\n🎉 All tests passed!")
    
    success_rate = (tester.tests_passed / tester.tests_run * 100) if tester.tests_run > 0 else 0
    print(f"\n📈 Success rate: {success_rate:.1f}%")
    
    return 0 if success_rate >= 80 else 1

if __name__ == "__main__":
    sys.exit(main())