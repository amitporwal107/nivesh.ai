import requests
import sys
import json
import io
from datetime import datetime

class WealthSystemAPITester:
    def __init__(self, base_url="https://ai-advisor-30.preview.emergentagent.com"):
        self.base_url = base_url
        self.session_token = "test_session_wealth001"  # Pre-created test session
        self.tests_run = 0
        self.tests_passed = 0
        self.failed_tests = []

    def run_test(self, name, method, endpoint, expected_status, data=None, files=None):
        """Run a single API test"""
        url = f"{self.base_url}/api/{endpoint}"
        headers = {'Content-Type': 'application/json'}
        
        # Add session token via Authorization header
        if self.session_token:
            headers['Authorization'] = f'Bearer {self.session_token}'

        self.tests_run += 1
        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {url}")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers)
            elif method == 'POST':
                if files:
                    # Remove Content-Type for file uploads
                    headers.pop('Content-Type', None)
                    response = requests.post(url, files=files, headers=headers)
                else:
                    response = requests.post(url, json=data, headers=headers)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=headers)
            elif method == 'DELETE':
                response = requests.delete(url, headers=headers)

            success = response.status_code == expected_status
            if success:
                self.tests_passed += 1
                print(f"✅ Passed - Status: {response.status_code}")
                try:
                    response_data = response.json()
                    print(f"   Response: {json.dumps(response_data, indent=2)[:200]}...")
                except:
                    print(f"   Response: {response.text[:100]}...")
            else:
                print(f"❌ Failed - Expected {expected_status}, got {response.status_code}")
                print(f"   Response: {response.text[:200]}...")
                self.failed_tests.append({
                    "test": name,
                    "expected": expected_status,
                    "actual": response.status_code,
                    "response": response.text[:200]
                })

            return success, response.json() if success and response.text else {}

        except Exception as e:
            print(f"❌ Failed - Error: {str(e)}")
            self.failed_tests.append({
                "test": name,
                "error": str(e)
            })
            return False, {}

    def test_auth_me(self):
        """Test /auth/me endpoint"""
        success, response = self.run_test(
            "Get Current User",
            "GET",
            "auth/me",
            200
        )
        if success and 'user_id' in response:
            print(f"   User: {response.get('name')} ({response.get('email')})")
            return response
        return None

    def test_auth_logout(self):
        """Test logout endpoint"""
        success, _ = self.run_test(
            "Logout",
            "POST",
            "auth/logout",
            200
        )
        return success

    def test_get_holdings(self):
        """Test get holdings"""
        success, response = self.run_test(
            "Get Holdings",
            "GET",
            "portfolio/holdings",
            200
        )
        if success:
            print(f"   Found {len(response)} holdings")
            return response
        return []

    def test_add_holding(self):
        """Test add holding"""
        test_holding = {
            "name": "Test Stock SDET",
            "ticker": "TESTSDET",
            "asset_type": "equity",
            "quantity": 10,
            "buy_price": 1000,
            "current_price": 1200,
            "sector": "IT",
            "buy_date": "2024-01-01"
        }
        
        success, response = self.run_test(
            "Add Holding",
            "POST",
            "portfolio/holdings",
            201,
            data=test_holding
        )
        return response.get('holding_id') if success else None

    def test_update_holding(self, holding_id):
        """Test update holding"""
        update_data = {
            "current_price": 1300,
            "quantity": 15
        }
        
        success, response = self.run_test(
            "Update Holding",
            "PUT",
            f"portfolio/holdings/{holding_id}",
            200,
            data=update_data
        )
        return success

    def test_delete_holding(self, holding_id):
        """Test delete holding"""
        success, _ = self.run_test(
            "Delete Holding",
            "DELETE",
            f"portfolio/holdings/{holding_id}",
            200
        )
        return success

    def test_csv_upload(self):
        """Test CSV upload"""
        csv_content = """name,ticker,asset_type,quantity,buy_price,current_price,sector
Test CSV Stock,TESTCSV,equity,5,800,900,Banking
Test MF,TESTMF,mutual_fund,100,50,55,Financial Services"""
        
        csv_file = io.StringIO(csv_content)
        files = {'file': ('test_holdings.csv', csv_file.getvalue(), 'text/csv')}
        
        success, response = self.run_test(
            "CSV Upload",
            "POST",
            "portfolio/upload-csv",
            200,
            files=files
        )
        if success:
            print(f"   Imported {response.get('count', 0)} holdings")
        return success

    def test_portfolio_analytics(self):
        """Test portfolio analytics"""
        success, response = self.run_test(
            "Portfolio Analytics",
            "GET",
            "portfolio/analytics",
            200
        )
        if success:
            print(f"   Total Value: ₹{response.get('current_value', 0)}")
            print(f"   Returns: ₹{response.get('total_returns', 0)} ({response.get('returns_pct', 0):.1f}%)")
            print(f"   Risk Score: {response.get('risk_score', 0)} ({response.get('risk_label', 'N/A')})")
        return success

    def test_chat_messages(self):
        """Test get chat messages"""
        success, response = self.run_test(
            "Get Chat Messages",
            "GET",
            "chat/messages",
            200
        )
        if success:
            print(f"   Found {len(response)} messages")
        return success

    def test_send_chat(self):
        """Test send chat message"""
        test_message = {
            "message": "What is my portfolio's risk level?"
        }
        
        success, response = self.run_test(
            "Send Chat Message",
            "POST",
            "chat/send",
            200,
            data=test_message
        )
        if success:
            print(f"   AI Response: {response.get('ai_message', {}).get('content', '')[:100]}...")
        return success

    def test_clear_chat(self):
        """Test clear chat"""
        success, _ = self.run_test(
            "Clear Chat",
            "DELETE",
            "chat/clear",
            200
        )
        return success

    def test_get_insights(self):
        """Test get insights"""
        success, response = self.run_test(
            "Get Insights",
            "GET",
            "insights",
            200
        )
        if success:
            print(f"   Found {len(response)} insights")
        return success

    def test_generate_insights(self):
        """Test generate insights"""
        success, response = self.run_test(
            "Generate Insights",
            "POST",
            "insights/generate",
            200
        )
        if success:
            insights = response.get('insights', [])
            print(f"   Generated {len(insights)} insights")
            for insight in insights[:2]:  # Show first 2
                print(f"   - {insight.get('title', '')}: {insight.get('type', '')} ({insight.get('priority', '')})")
        return success

def main():
    print("🚀 Starting Agentic Wealth System API Tests")
    print("=" * 60)
    
    tester = WealthSystemAPITester()
    
    # Test authentication
    print("\n📋 AUTHENTICATION TESTS")
    user = tester.test_auth_me()
    if not user:
        print("❌ Authentication failed - cannot proceed with other tests")
        return 1
    
    # Test portfolio endpoints
    print("\n📊 PORTFOLIO TESTS")
    holdings = tester.test_get_holdings()
    
    # Test CRUD operations
    holding_id = tester.test_add_holding()
    if holding_id:
        tester.test_update_holding(holding_id)
        # Don't delete immediately, keep for other tests
    
    tester.test_csv_upload()
    tester.test_portfolio_analytics()
    
    # Test AI features
    print("\n🤖 AI FEATURES TESTS")
    tester.test_chat_messages()
    tester.test_send_chat()
    tester.test_get_insights()
    tester.test_generate_insights()
    
    # Test cleanup
    print("\n🧹 CLEANUP TESTS")
    tester.test_clear_chat()
    if holding_id:
        tester.test_delete_holding(holding_id)
    
    tester.test_auth_logout()
    
    # Print results
    print("\n" + "=" * 60)
    print(f"📊 FINAL RESULTS")
    print(f"Tests passed: {tester.tests_passed}/{tester.tests_run}")
    print(f"Success rate: {(tester.tests_passed/tester.tests_run*100):.1f}%")
    
    if tester.failed_tests:
        print(f"\n❌ FAILED TESTS:")
        for failure in tester.failed_tests:
            print(f"  - {failure.get('test', 'Unknown')}: {failure}")
    
    return 0 if tester.tests_passed == tester.tests_run else 1

if __name__ == "__main__":
    sys.exit(main())