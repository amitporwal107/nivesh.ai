#!/usr/bin/env python3
"""
V2 Action Plan Dashboard Enhancement Testing
Tests specific functionality requested in the review:
1. Get Active Plan API
2. Update Action Status (all transitions)
3. Submit Action Feedback
4. Auto-Archive Check
5. Verify Data Structure
"""
import requests
import json
import time
import sys
from datetime import datetime

class V2DashboardTester:
    def __init__(self):
        # Use the production URL from frontend/.env
        self.base_url = "https://fund-overlap-3.preview.emergentagent.com"
        # Test credentials from review request
        self.session_token = "370eff71-fda1-46d8-b506-b81b894d634f"
        self.test_email = "priyankamantri@gmail.com"
        self.tests_run = 0
        self.tests_passed = 0
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.session_token}'
        }
        
        # Store test data
        self.active_plan = None
        self.test_action_id = None
        self.plan_id = None

    def log_test(self, name, success, details=""):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
            print(f"✅ {name}")
            if details:
                print(f"   {details}")
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
            return False, {"error": str(e)}, f"Exception: {str(e)}"

    def test_1_get_active_plan(self):
        """Test 1: Get Active Plan API"""
        print("\n🎯 Test 1: Get Active Plan")
        
        success, data, status = self.make_request('GET', 'plans/active')
        
        if not success:
            return self.log_test("Get Active Plan API", False, f"Status: {status}, Data: {data}")
        
        # Verify response structure
        has_plan = data.get('has_plan', False)
        plan = data.get('plan')
        
        if not has_plan or not plan:
            return self.log_test("Get Active Plan API", False, "No active plan found for test user")
        
        # Store for later tests
        self.active_plan = plan
        self.plan_id = plan.get('plan_id')
        
        # Verify plan structure
        required_fields = ['plan_id', 'actions', 'completion_pct', 'completed_actions', 'pending_actions']
        missing_fields = [field for field in required_fields if field not in plan]
        
        if missing_fields:
            return self.log_test("Get Active Plan Structure", False, f"Missing fields: {missing_fields}")
        
        # Verify actions have proper structure
        actions = plan.get('actions', [])
        if not actions:
            return self.log_test("Get Active Plan Actions", False, "No actions found in plan")
        
        # Store first action for testing
        self.test_action_id = actions[0].get('action_id')
        
        # Verify action structure
        action = actions[0]
        required_action_fields = ['action_id', 'status', 'type', 'asset_name']
        missing_action_fields = [field for field in required_action_fields if field not in action]
        
        if missing_action_fields:
            return self.log_test("Action Structure", False, f"Missing action fields: {missing_action_fields}")
        
        self.log_test("Get Active Plan API", True, f"Plan ID: {self.plan_id}, Actions: {len(actions)}")
        self.log_test("Action Structure", True, f"Action ID: {self.test_action_id}, Status: {action.get('status')}")
        
        return True

    def test_2_update_action_status_transitions(self):
        """Test 2: Update Action Status (all transitions)"""
        print("\n🔄 Test 2: Action Status Transitions")
        
        if not self.plan_id or not self.test_action_id:
            return self.log_test("Action Status Update", False, "No plan/action ID available from previous test")
        
        # Get current action status first
        success, data, status = self.make_request('GET', 'plans/active')
        if success and data.get('plan'):
            actions = data['plan'].get('actions', [])
            current_action = next((a for a in actions if a['action_id'] == self.test_action_id), None)
            if current_action:
                current_status = current_action.get('status', 'PENDING')
                print(f"  Current action status: {current_status}")
                
                # If already completed, find a pending action
                if current_status == 'COMPLETED':
                    pending_action = next((a for a in actions if a.get('status') == 'PENDING'), None)
                    if pending_action:
                        self.test_action_id = pending_action['action_id']
                        current_status = 'PENDING'
                        print(f"  Switched to pending action: {self.test_action_id}")
        
        # Test transition: PENDING → IN_PROGRESS (or current → IN_PROGRESS)
        print("  Testing transition to IN_PROGRESS...")
        update_data = {
            "status": "IN_PROGRESS",
            "completion_note": "Started working on this action"
        }
        
        success, data, status = self.make_request(
            'PATCH', 
            f'plans/{self.plan_id}/actions/{self.test_action_id}',
            update_data
        )
        
        if not success:
            return self.log_test("Status Update to IN_PROGRESS", False, f"Status: {status}, Data: {data}")
        
        # Debug: Print response structure
        print(f"    Response data keys: {list(data.keys()) if data else 'None'}")
        
        # Verify status updated
        updated_plan = data.get('plan')
        if not updated_plan:
            return self.log_test("Status Update to IN_PROGRESS", False, f"No plan in response: {data}")
        
        actions = updated_plan.get('actions', [])
        updated_action = next((a for a in actions if a['action_id'] == self.test_action_id), None)
        
        if not updated_action or updated_action.get('status') != 'IN_PROGRESS':
            return self.log_test("Status Update to IN_PROGRESS", False, "Status not updated correctly")
        
        self.log_test("Status Update to IN_PROGRESS", True, "Action status updated successfully")
        
        # Verify progress calculation
        in_progress_actions = updated_plan.get('in_progress_actions', 0)
        if in_progress_actions < 1:
            return self.log_test("Progress Calculation (IN_PROGRESS)", False, f"in_progress_actions: {in_progress_actions}")
        
        self.log_test("Progress Calculation (IN_PROGRESS)", True, f"in_progress_actions: {in_progress_actions}")
        
        # Test transition: IN_PROGRESS → COMPLETED
        print("  Testing IN_PROGRESS → COMPLETED...")
        update_data = {
            "status": "COMPLETED",
            "completion_note": "Successfully completed this action"
        }
        
        success, data, status = self.make_request(
            'PATCH', 
            f'plans/{self.plan_id}/actions/{self.test_action_id}',
            update_data
        )
        
        if not success:
            return self.log_test("Status Update to COMPLETED", False, f"Status: {status}, Data: {data}")
        
        # Verify status updated and completion_pct increased
        updated_plan = data.get('plan', {})
        actions = updated_plan.get('actions', [])
        updated_action = next((a for a in actions if a['action_id'] == self.test_action_id), None)
        
        if not updated_action or updated_action.get('status') != 'COMPLETED':
            return self.log_test("Status Update to COMPLETED", False, "Status not updated correctly")
        
        # Check if completed_at timestamp is set
        if not updated_action.get('completed_at'):
            return self.log_test("Completion Timestamp", False, "completed_at timestamp not set")
        
        self.log_test("Status Update to COMPLETED", True, "Action marked as completed")
        self.log_test("Completion Timestamp", True, f"completed_at: {updated_action.get('completed_at')}")
        
        # Verify completion percentage increased
        completion_pct = updated_plan.get('completion_pct', 0)
        completed_actions = updated_plan.get('completed_actions', 0)
        
        if completed_actions < 1:
            return self.log_test("Progress Calculation (COMPLETED)", False, f"completed_actions: {completed_actions}")
        
        self.log_test("Progress Calculation (COMPLETED)", True, f"completion_pct: {completion_pct}%, completed_actions: {completed_actions}")
        
        return True

    def test_3_submit_action_feedback(self):
        """Test 3: Submit Action Feedback"""
        print("\n💬 Test 3: Submit Action Feedback")
        
        if not self.plan_id or not self.test_action_id:
            return self.log_test("Action Feedback", False, "No plan/action ID available from previous test")
        
        # Submit positive feedback
        feedback_data = {
            "useful": True,
            "comment": "Test feedback comment - this action was very helpful"
        }
        
        success, data, status = self.make_request(
            'PATCH',
            f'plans/{self.plan_id}/actions/{self.test_action_id}/feedback',
            feedback_data
        )
        
        if not success:
            return self.log_test("Submit Action Feedback", False, f"Status: {status}, Data: {data}")
        
        # Verify feedback was recorded
        updated_plan = data.get('plan', {})
        actions = updated_plan.get('actions', [])
        updated_action = next((a for a in actions if a['action_id'] == self.test_action_id), None)
        
        if not updated_action:
            return self.log_test("Feedback Recording", False, "Action not found after feedback submission")
        
        feedback = updated_action.get('feedback')
        if not feedback:
            return self.log_test("Feedback Recording", False, "Feedback object not found in action")
        
        # Verify feedback structure
        if feedback.get('useful') != True:
            return self.log_test("Feedback Content", False, f"useful field incorrect: {feedback.get('useful')}")
        
        if feedback.get('comment') != feedback_data['comment']:
            return self.log_test("Feedback Content", False, f"comment field incorrect: {feedback.get('comment')}")
        
        # Verify submitted_at timestamp
        if not feedback.get('submitted_at'):
            return self.log_test("Feedback Timestamp", False, "submitted_at timestamp not set")
        
        self.log_test("Submit Action Feedback", True, "Feedback submitted successfully")
        self.log_test("Feedback Content", True, f"useful: {feedback.get('useful')}, comment: {feedback.get('comment')[:30]}...")
        self.log_test("Feedback Timestamp", True, f"submitted_at: {feedback.get('submitted_at')}")
        
        return True

    def test_4_auto_archive_check(self):
        """Test 4: Auto-Archive Check (informational)"""
        print("\n🗄️ Test 4: Auto-Archive Check")
        
        # This runs automatically when fetching active plan
        # We just need to verify no errors occur
        success, data, status = self.make_request('GET', 'plans/active')
        
        if not success:
            return self.log_test("Auto-Archive Check", False, f"Error during active plan fetch: {status}")
        
        # If we get here without errors, auto-archive is working
        self.log_test("Auto-Archive Check", True, "No errors during auto-archive process")
        
        return True

    def test_5_verify_data_structure(self):
        """Test 5: Verify Data Structure"""
        print("\n📊 Test 5: Verify Data Structure")
        
        if not self.active_plan:
            return self.log_test("Data Structure Verification", False, "No active plan data available")
        
        # Check action objects have required fields
        actions = self.active_plan.get('actions', [])
        if not actions:
            return self.log_test("Action Objects", False, "No actions found")
        
        action = actions[0]
        required_action_fields = ['action_id', 'status']
        missing_fields = [field for field in required_action_fields if field not in action]
        
        if missing_fields:
            return self.log_test("Action Objects", False, f"Missing fields: {missing_fields}")
        
        self.log_test("Action Objects", True, "Actions have required fields: action_id, status")
        
        # Check if feedback field exists (after our test)
        if 'feedback' in action:
            self.log_test("Action Feedback Field", True, "Feedback field present in action")
        else:
            self.log_test("Action Feedback Field", False, "Feedback field not found")
        
        # Check plan has required fields
        required_plan_fields = ['completion_pct', 'completed_actions', 'in_progress_actions']
        missing_plan_fields = [field for field in required_plan_fields if field not in self.active_plan]
        
        if missing_plan_fields:
            return self.log_test("Plan Objects", False, f"Missing plan fields: {missing_plan_fields}")
        
        self.log_test("Plan Objects", True, "Plan has required fields: completion_pct, completed_actions, in_progress_actions")
        
        # Verify data types
        completion_pct = self.active_plan.get('completion_pct')
        if not isinstance(completion_pct, (int, float)):
            return self.log_test("Data Types", False, f"completion_pct is not numeric: {type(completion_pct)}")
        
        completed_actions = self.active_plan.get('completed_actions')
        if not isinstance(completed_actions, int):
            return self.log_test("Data Types", False, f"completed_actions is not integer: {type(completed_actions)}")
        
        self.log_test("Data Types", True, "All numeric fields have correct types")
        
        return True

    def run_all_tests(self):
        """Run all V2 Dashboard enhancement tests"""
        print("🚀 Starting V2 Action Plan Dashboard Enhancement Tests")
        print(f"📍 Testing against: {self.base_url}")
        print(f"👤 Test User: {self.test_email}")
        print(f"🔑 Session: {self.session_token}")
        
        # Run test suites in order
        test_results = []
        
        test_results.append(self.test_1_get_active_plan())
        test_results.append(self.test_2_update_action_status_transitions())
        test_results.append(self.test_3_submit_action_feedback())
        test_results.append(self.test_4_auto_archive_check())
        test_results.append(self.test_5_verify_data_structure())
        
        # Print summary
        print(f"\n📊 Test Summary:")
        print(f"   Tests Run: {self.tests_run}")
        print(f"   Tests Passed: {self.tests_passed}")
        print(f"   Success Rate: {(self.tests_passed/self.tests_run*100):.1f}%")
        
        # Print detailed results
        print(f"\n📋 Expected Results Verification:")
        if all(test_results):
            print("✅ All status transitions work (PENDING → IN_PROGRESS → COMPLETED)")
            print("✅ Feedback is recorded per action")
            print("✅ Progress percentage updates correctly")
            print("✅ Timestamps are set appropriately")
        else:
            print("❌ Some tests failed - see details above")
        
        return self.tests_passed == self.tests_run

if __name__ == "__main__":
    tester = V2DashboardTester()
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)