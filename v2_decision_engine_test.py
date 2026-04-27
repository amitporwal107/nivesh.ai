#!/usr/bin/env python3
"""
V2 Decision Engine Backend API Testing
Tests the V2 MF-Only Action Plan System with specific validation requirements
"""
import requests
import json
import time
import sys
from datetime import datetime

class V2DecisionEngineAPITester:
    def __init__(self):
        self.base_url = "https://advisor-timeline.preview.emergentagent.com"
        self.session_token = "370eff71-fda1-46d8-b506-b81b894d634f"
        self.user_id = "user_f087c6332922"
        self.email = "priyankamantri@gmail.com"
        self.tests_run = 0
        self.tests_passed = 0
        self.generated_plan_id = None
        self.saved_plan_id = None
        
        # Headers with session token cookie
        self.headers = {
            'Content-Type': 'application/json',
            'Cookie': f'session_token={self.session_token}'
        }

    def log_test(self, name, success, details=""):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
            print(f"✅ {name}")
            if details:
                print(f"   Details: {details}")
        else:
            print(f"❌ {name}")
            if details:
                print(f"   Error: {details}")
        return success

    def make_request(self, method, endpoint, data=None, expected_status=200):
        """Make API request with error handling"""
        url = f"{self.base_url}/api/{endpoint}"
        try:
            if method == 'GET':
                response = requests.get(url, headers=self.headers, timeout=30)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=self.headers, timeout=30)
            elif method == 'PATCH':
                response = requests.patch(url, json=data, headers=self.headers, timeout=30)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=self.headers, timeout=30)
            elif method == 'DELETE':
                response = requests.delete(url, headers=self.headers, timeout=30)
            
            success = response.status_code == expected_status
            try:
                response_data = response.json() if response.text else {}
            except:
                response_data = {"raw_response": response.text}
            
            return success, response_data, response.status_code
        except Exception as e:
            return False, {"error": str(e)}, 0

    def test_plan_generation(self):
        """Test POST /api/plans/generate - Core V2 Decision Engine"""
        print("\n🎯 Testing V2 Plan Generation API...")
        
        success, data, status = self.make_request('POST', 'plans/generate')
        
        if not success:
            self.log_test("Plan Generation: API call", False, f"Status: {status}, Response: {data}")
            return False
        
        # Extract plan from response
        plan = data.get('plan', {})
        
        # Store plan ID for subsequent tests
        self.generated_plan_id = plan.get('plan_id')
        
        # Test 1: Basic plan structure
        required_fields = ['plan_id', 'status', 'signals', 'actions', 'created_at']
        has_all_fields = all(field in plan for field in required_fields)
        self.log_test("Plan Generation: Basic structure", has_all_fields, 
                     f"Missing: {[f for f in required_fields if f not in plan]}")
        
        # Test 2: Plan status should be 'preview'
        status_correct = plan.get('status') == 'preview'
        self.log_test("Plan Generation: Status is 'preview'", status_correct, 
                     f"Status: {plan.get('status')}")
        
        # Test 3: Signals array exists and has content
        signals = plan.get('signals', [])
        has_signals = isinstance(signals, list) and len(signals) > 0
        self.log_test("Plan Generation: Signals array", has_signals, 
                     f"Signals count: {len(signals)}")
        
        # Test 4: Actions array exists and has content
        actions = plan.get('actions', [])
        has_actions = isinstance(actions, list) and len(actions) > 0
        self.log_test("Plan Generation: Actions array", has_actions, 
                     f"Actions count: {len(actions)}")
        
        if not has_actions:
            return False
        
        # Test 5: CRITICAL - All actions must be MF-only (no equity/stock)
        mf_only_actions = True
        non_mf_actions = []
        for action in actions:
            asset_type = action.get('asset_type', '').lower()
            if asset_type not in ['mutual_fund', 'mf']:
                mf_only_actions = False
                non_mf_actions.append(f"{action.get('action_type', 'UNKNOWN')} - {asset_type}")
        
        self.log_test("Plan Generation: MF-only actions (CRITICAL)", mf_only_actions, 
                     f"Non-MF actions found: {non_mf_actions}" if non_mf_actions else "All actions are MF-only")
        
        # Test 6: EXIT actions have detailed tax analysis
        exit_actions = [a for a in actions if a.get('action_type') == 'EXIT']
        exit_tax_analysis_complete = True
        exit_issues = []
        
        for exit_action in exit_actions:
            tax_impact = exit_action.get('tax_impact', {})
            required_tax_fields = ['tax_liability', 'net_benefit', 'tax_efficient']
            missing_tax_fields = [f for f in required_tax_fields if f not in tax_impact]
            
            if missing_tax_fields:
                exit_tax_analysis_complete = False
                exit_issues.append(f"Missing tax fields: {missing_tax_fields}")
            
            # Check for exit_warning if tax is not efficient
            if not tax_impact.get('tax_efficient', True) and 'exit_warning' not in exit_action:
                exit_tax_analysis_complete = False
                exit_issues.append("Missing exit_warning for tax-inefficient exit")
            
            # Check for reason_text
            if 'reason_text' not in exit_action:
                exit_tax_analysis_complete = False
                exit_issues.append("Missing reason_text")
        
        self.log_test("Plan Generation: EXIT tax analysis", exit_tax_analysis_complete, 
                     f"Issues: {exit_issues}" if exit_issues else f"All {len(exit_actions)} EXIT actions have complete tax analysis")
        
        # Test 7: ADD actions have specific fund names (not TBD)
        add_actions = [a for a in actions if a.get('action_type') == 'ADD']
        specific_fund_names = True
        fund_name_issues = []
        
        for add_action in add_actions:
            fund_details = add_action.get('fund_details', {})
            fund_name = fund_details.get('fund_name', '')
            
            if not fund_name or 'TBD' in fund_name.upper() or 'TO BE DETERMINED' in fund_name.upper():
                specific_fund_names = False
                fund_name_issues.append(f"Generic/TBD fund name: {fund_name}")
            
            # Check for required fund details
            required_fund_fields = ['fund_name', 'fund_type', 'expense_ratio', 'rating', 'returns_3y']
            missing_fund_fields = [f for f in required_fund_fields if f not in fund_details]
            
            if missing_fund_fields:
                specific_fund_names = False
                fund_name_issues.append(f"Missing fund details: {missing_fund_fields}")
        
        self.log_test("Plan Generation: Specific fund names", specific_fund_names, 
                     f"Issues: {fund_name_issues}" if fund_name_issues else f"All {len(add_actions)} ADD actions have specific fund names")
        
        # Test 8: Check freed_capital and post_tax_proceeds calculations
        has_capital_calculations = 'freed_capital' in plan and 'post_tax_proceeds' in plan
        self.log_test("Plan Generation: Capital calculations", has_capital_calculations, 
                     f"freed_capital: {plan.get('freed_capital')}, post_tax_proceeds: {plan.get('post_tax_proceeds')}")
        
        return True

    def test_active_plan_retrieval(self):
        """Test GET /api/plans/active"""
        print("\n📋 Testing Active Plan Retrieval...")
        
        success, data, status = self.make_request('GET', 'plans/active')
        
        if not success:
            self.log_test("Active Plan: API call", False, f"Status: {status}, Response: {data}")
            return False
        
        # Should have has_plan boolean
        has_plan_field = 'has_plan' in data
        self.log_test("Active Plan: has_plan field", has_plan_field, 
                     f"has_plan: {data.get('has_plan')}")
        
        return True

    def test_save_plan(self):
        """Test POST /api/plans/{plan_id}/save"""
        print("\n💾 Testing Plan Save...")
        
        if not self.generated_plan_id:
            self.log_test("Plan Save: No plan ID", False, "Need to generate plan first")
            return False
        
        success, data, status = self.make_request('POST', f'plans/{self.generated_plan_id}/save')
        
        if not success:
            self.log_test("Plan Save: API call", False, f"Status: {status}, Response: {data}")
            return False
        
        # Store saved plan ID
        saved_plan = data.get('plan', {})
        self.saved_plan_id = saved_plan.get('plan_id', self.generated_plan_id)
        
        # Status should change to 'active'
        status_active = saved_plan.get('status') == 'active'
        self.log_test("Plan Save: Status changed to active", status_active, 
                     f"Status: {saved_plan.get('status')}")
        
        return True

    def test_plan_history(self):
        """Test GET /api/plans/history"""
        print("\n📚 Testing Plan History...")
        
        success, data, status = self.make_request('GET', 'plans/history')
        
        if not success:
            self.log_test("Plan History: API call", False, f"Status: {status}, Response: {data}")
            return False
        
        # Should return list of plans
        plans = data.get('plans', [])
        is_list = isinstance(plans, list)
        self.log_test("Plan History: Returns list", is_list, 
                     f"Type: {type(plans)}, Count: {len(plans) if is_list else 'N/A'}")
        
        # Check sorting (most recent first)
        if is_list and len(plans) > 1:
            sorted_correctly = True
            for i in range(len(plans) - 1):
                current_date = plans[i].get('created_at', '')
                next_date = plans[i + 1].get('created_at', '')
                if current_date < next_date:
                    sorted_correctly = False
                    break
            
            self.log_test("Plan History: Sorted by date DESC", sorted_correctly)
        
        return True

    def test_signals_generation(self):
        """Test GET /api/signals/generate"""
        print("\n🚨 Testing Signals Generation...")
        
        success, data, status = self.make_request('GET', 'signals/generate')
        
        if not success:
            self.log_test("Signals Generation: API call", False, f"Status: {status}, Response: {data}")
            return False
        
        # Should have signals array
        signals = data.get('signals', [])
        has_signals = isinstance(signals, list)
        self.log_test("Signals Generation: Signals array", has_signals, 
                     f"Signals count: {len(signals)}")
        
        # Should have summary with counts
        summary = data.get('summary', {})
        has_summary = isinstance(summary, dict) and ('total' in summary or 'total_signals' in summary)
        self.log_test("Signals Generation: Summary with counts", has_summary, 
                     f"Summary: {summary}")
        
        # Check signal types
        if has_signals and signals:
            signal_types = set(signal.get('type', '') for signal in signals)
            expected_types = {'OVERLAP_REDUNDANCY', 'QUALITY_ISSUES'}
            has_expected_types = bool(signal_types.intersection(expected_types))
            self.log_test("Signals Generation: Expected signal types", has_expected_types, 
                         f"Found types: {signal_types}")
        
        return True

    def test_action_status_update(self):
        """Test PATCH /api/plans/{plan_id}/actions/{action_id}"""
        print("\n✏️ Testing Action Status Update...")
        
        if not self.saved_plan_id:
            self.log_test("Action Update: No saved plan", False, "Need to save plan first")
            return False
        
        # First get the plan to find an action ID
        success, plan_response, status = self.make_request('GET', f'plans/{self.saved_plan_id}')
        
        if not success:
            self.log_test("Action Update: Get plan for action ID", False, f"Status: {status}")
            return False
        
        # Extract plan from response
        plan_data = plan_response.get('plan', {})
        actions = plan_data.get('actions', [])
        
        if not actions:
            self.log_test("Action Update: No actions found in plan", False)
            return False
        
        action_id = actions[0].get('action_id')
        if not action_id:
            self.log_test("Action Update: No action ID found", False)
            return False
        
        # Update action status
        update_data = {
            "status": "COMPLETED",
            "completion_note": "Test completion via API"
        }
        
        success, data, status = self.make_request('PATCH', f'plans/{self.saved_plan_id}/actions/{action_id}', update_data)
        
        if not success:
            self.log_test("Action Update: API call", False, f"Status: {status}, Response: {data}")
            return False
        
        # Extract plan from response
        updated_plan = data.get('plan', {})
        
        # Check progress updates
        progress_fields = ['completed_actions', 'completion_pct', 'pending_actions']
        has_progress = all(field in updated_plan for field in progress_fields)
        self.log_test("Action Update: Progress tracking", has_progress, 
                     f"Progress: {updated_plan.get('completion_pct')}%, Completed: {updated_plan.get('completed_actions')}")
        
        return True

    def test_plan_refresh(self):
        """Test POST /api/plans/refresh"""
        print("\n🔄 Testing Plan Refresh...")
        
        success, data, status = self.make_request('POST', 'plans/refresh')
        
        if not success:
            self.log_test("Plan Refresh: API call", False, f"Status: {status}, Response: {data}")
            return False
        
        # Extract plan from response
        refreshed_plan = data.get('plan', {})
        
        # Should create new plan with incremented version
        has_version = 'version' in refreshed_plan
        is_active = refreshed_plan.get('status') == 'active'
        
        self.log_test("Plan Refresh: New version created", has_version, 
                     f"Version: {refreshed_plan.get('version')}")
        self.log_test("Plan Refresh: New plan is active", is_active, 
                     f"Status: {refreshed_plan.get('status')}")
        
        return True

    def run_all_tests(self):
        """Run all test suites in sequence"""
        print("🚀 Starting V2 Decision Engine Backend API Tests")
        print(f"📍 Testing against: {self.base_url}")
        print(f"👤 User ID: {self.user_id}")
        print(f"📧 Email: {self.email}")
        print(f"🔑 Session Token: {self.session_token[:20]}...")
        
        # Run tests in sequence (some depend on previous results)
        test_results = []
        
        test_results.append(self.test_plan_generation())
        test_results.append(self.test_active_plan_retrieval())
        test_results.append(self.test_save_plan())
        test_results.append(self.test_plan_history())
        test_results.append(self.test_signals_generation())
        test_results.append(self.test_action_status_update())
        test_results.append(self.test_plan_refresh())
        
        # Print summary
        print(f"\n📊 Test Summary:")
        print(f"   Tests Run: {self.tests_run}")
        print(f"   Tests Passed: {self.tests_passed}")
        print(f"   Success Rate: {(self.tests_passed/self.tests_run*100):.1f}%")
        
        # Highlight critical failures
        if self.tests_passed < self.tests_run:
            print(f"\n⚠️  {self.tests_run - self.tests_passed} tests failed - review details above")
        
        return self.tests_passed == self.tests_run

if __name__ == "__main__":
    tester = V2DecisionEngineAPITester()
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)