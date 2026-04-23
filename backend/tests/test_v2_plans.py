"""Test V2 Decision & Allocation Engine Backend APIs.

Tests the complete flow:
1. Generate plan (preview)
2. Save plan (activate)
3. Get active plan
4. Update action status
5. Refresh plan
6. Get plan history
7. Generate signals

Test User: user_f087c6332922 (Admin user with 110+ holdings)
Session Token: 370eff71-fda1-46d8-b506-b81b894d634f
"""
import pytest
import requests
import json
import os
from typing import Dict, Any, Optional

# Test configuration
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
API_BASE = f"{BASE_URL}/api"

# Test user credentials from review request
TEST_USER_ID = "user_f087c6332922"
TEST_SESSION_TOKEN = "370eff71-fda1-46d8-b506-b81b894d634f"

# Headers for authenticated requests
AUTH_HEADERS = {
    "Authorization": f"Bearer {TEST_SESSION_TOKEN}",
    "Content-Type": "application/json"
}


class TestV2PlansAPI:
    """Test suite for V2 Decision & Allocation Engine APIs."""
    
    def setup_method(self):
        """Setup for each test method."""
        self.plan_id = None
        self.action_id = None
    
    def test_01_generate_plan(self):
        """Test POST /api/plans/generate - Generate a new action plan."""
        print("\n=== Testing Plan Generation ===")
        
        response = requests.post(
            f"{API_BASE}/plans/generate",
            headers=AUTH_HEADERS
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        
        if response.status_code != 200:
            print(f"Error Response: {response.text}")
            
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        print(f"Response Keys: {list(data.keys())}")
        
        # Validate response structure
        assert "plan" in data, "Response should contain 'plan' key"
        assert "message" in data, "Response should contain 'message' key"
        
        plan = data["plan"]
        print(f"Plan Keys: {list(plan.keys())}")
        
        # Validate plan structure
        required_fields = [
            "plan_id", "user_id", "version", "status", "created_at", 
            "signals", "actions", "total_actions", "completed_actions",
            "pending_actions", "completion_pct"
        ]
        
        for field in required_fields:
            assert field in plan, f"Plan should contain '{field}' field"
        
        # Validate plan content
        assert plan["user_id"] == TEST_USER_ID, f"Expected user_id {TEST_USER_ID}, got {plan['user_id']}"
        assert plan["status"] == "preview", f"Expected status 'preview', got {plan['status']}"
        assert plan["version"] == 1, f"Expected version 1, got {plan['version']}"
        assert isinstance(plan["signals"], list), "Signals should be a list"
        assert isinstance(plan["actions"], list), "Actions should be a list"
        assert len(plan["actions"]) >= 2, f"Expected at least 2 actions, got {len(plan['actions'])}"
        assert plan["total_actions"] == len(plan["actions"]), "total_actions should match actions length"
        assert plan["completed_actions"] == 0, "completed_actions should be 0 for new plan"
        assert plan["pending_actions"] == len(plan["actions"]), "pending_actions should equal total_actions"
        assert plan["completion_pct"] == 0.0, "completion_pct should be 0.0 for new plan"
        
        # Validate signals structure
        if plan["signals"]:
            signal = plan["signals"][0]
            signal_fields = ["signal_id", "type", "severity", "title", "description", "impact"]
            for field in signal_fields:
                assert field in signal, f"Signal should contain '{field}' field"
            assert signal["severity"] in ["HIGH", "MEDIUM", "LOW"], f"Invalid severity: {signal['severity']}"
        
        # Validate actions structure
        action = plan["actions"][0]
        action_fields = ["action_id", "type", "priority", "asset_type", "asset_name", "amount", "status"]
        for field in action_fields:
            assert field in action, f"Action should contain '{field}' field"
        assert action["type"] in ["EXIT", "ADD"], f"Invalid action type: {action['type']}"
        assert action["status"] == "PENDING", f"Expected status 'PENDING', got {action['status']}"
        
        # Store plan_id and action_id for subsequent tests
        self.plan_id = plan["plan_id"]
        self.action_id = plan["actions"][0]["action_id"]
        
        print(f"✅ Plan generated successfully: {self.plan_id}")
        print(f"   - Signals: {len(plan['signals'])}")
        print(f"   - Actions: {len(plan['actions'])}")
        print(f"   - First Action: {action['type']} {action['asset_name']}")
    
    def test_02_save_plan(self):
        """Test POST /api/plans/{plan_id}/save - Save preview plan as active."""
        print("\n=== Testing Plan Save ===")
        
        # First generate a plan to save
        gen_response = requests.post(f"{API_BASE}/plans/generate", headers=AUTH_HEADERS)
        assert gen_response.status_code == 200
        plan_id = gen_response.json()["plan"]["plan_id"]
        
        # Now save the plan
        response = requests.post(
            f"{API_BASE}/plans/{plan_id}/save",
            headers=AUTH_HEADERS
        )
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code != 200:
            print(f"Error Response: {response.text}")
            
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Validate response structure
        assert "plan" in data, "Response should contain 'plan' key"
        assert "message" in data, "Response should contain 'message' key"
        
        plan = data["plan"]
        
        # Validate plan status changed to active
        assert plan["status"] == "active", f"Expected status 'active', got {plan['status']}"
        assert plan["plan_id"] == plan_id, f"Plan ID should match: {plan_id}"
        
        print(f"✅ Plan saved successfully: {plan_id}")
        print(f"   - Status: {plan['status']}")
    
    def test_03_get_active_plan(self):
        """Test GET /api/plans/active - Get user's active plan."""
        print("\n=== Testing Get Active Plan ===")
        
        response = requests.get(
            f"{API_BASE}/plans/active",
            headers=AUTH_HEADERS
        )
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code != 200:
            print(f"Error Response: {response.text}")
            
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Validate response structure
        assert "plan" in data, "Response should contain 'plan' key"
        assert "has_plan" in data, "Response should contain 'has_plan' key"
        
        # Should have an active plan (from previous test or existing)
        if data["has_plan"]:
            plan = data["plan"]
            assert plan is not None, "Plan should not be None when has_plan is True"
            assert plan["status"] == "active", f"Expected status 'active', got {plan['status']}"
            assert plan["user_id"] == TEST_USER_ID, f"Expected user_id {TEST_USER_ID}, got {plan['user_id']}"
            
            print(f"✅ Active plan found: {plan['plan_id']}")
            print(f"   - Version: {plan['version']}")
            print(f"   - Actions: {plan['total_actions']}")
            print(f"   - Progress: {plan['completion_pct']}%")
        else:
            print("ℹ️ No active plan found (this is valid)")
    
    def test_04_get_plan_by_id(self):
        """Test GET /api/plans/{plan_id} - Get specific plan by ID."""
        print("\n=== Testing Get Plan by ID ===")
        
        # First generate a plan to retrieve
        gen_response = requests.post(f"{API_BASE}/plans/generate", headers=AUTH_HEADERS)
        assert gen_response.status_code == 200
        plan_id = gen_response.json()["plan"]["plan_id"]
        
        # Now get the plan by ID
        response = requests.get(
            f"{API_BASE}/plans/{plan_id}",
            headers=AUTH_HEADERS
        )
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code != 200:
            print(f"Error Response: {response.text}")
            
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Validate response structure
        assert "plan" in data, "Response should contain 'plan' key"
        
        plan = data["plan"]
        assert plan["plan_id"] == plan_id, f"Plan ID should match: {plan_id}"
        assert plan["user_id"] == TEST_USER_ID, f"Expected user_id {TEST_USER_ID}, got {plan['user_id']}"
        
        print(f"✅ Plan retrieved successfully: {plan_id}")
        print(f"   - Status: {plan['status']}")
        print(f"   - Version: {plan['version']}")
    
    def test_05_update_action_status(self):
        """Test PATCH /api/plans/{plan_id}/actions/{action_id} - Update action status."""
        print("\n=== Testing Action Status Update ===")
        
        # First generate and save a plan
        gen_response = requests.post(f"{API_BASE}/plans/generate", headers=AUTH_HEADERS)
        assert gen_response.status_code == 200
        plan_data = gen_response.json()["plan"]
        plan_id = plan_data["plan_id"]
        action_id = plan_data["actions"][0]["action_id"]
        
        save_response = requests.post(f"{API_BASE}/plans/{plan_id}/save", headers=AUTH_HEADERS)
        assert save_response.status_code == 200
        
        # Update action status
        update_data = {
            "status": "COMPLETED",
            "completion_note": "Test completion via API"
        }
        
        response = requests.patch(
            f"{API_BASE}/plans/{plan_id}/actions/{action_id}",
            headers=AUTH_HEADERS,
            json=update_data
        )
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code != 200:
            print(f"Error Response: {response.text}")
            
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Validate response structure
        assert "plan" in data, "Response should contain 'plan' key"
        assert "message" in data, "Response should contain 'message' key"
        
        plan = data["plan"]
        
        # Find the updated action
        updated_action = None
        for action in plan["actions"]:
            if action["action_id"] == action_id:
                updated_action = action
                break
        
        assert updated_action is not None, f"Action {action_id} not found in updated plan"
        assert updated_action["status"] == "COMPLETED", f"Expected status 'COMPLETED', got {updated_action['status']}"
        
        # Validate progress was updated
        assert plan["completed_actions"] >= 1, "completed_actions should be at least 1"
        assert plan["completion_pct"] > 0, "completion_pct should be greater than 0"
        
        print(f"✅ Action status updated successfully: {action_id}")
        print(f"   - New Status: {updated_action['status']}")
        print(f"   - Progress: {plan['completion_pct']}%")
        print(f"   - Completed Actions: {plan['completed_actions']}/{plan['total_actions']}")
    
    def test_06_refresh_plan(self):
        """Test POST /api/plans/refresh - Refresh active plan."""
        print("\n=== Testing Plan Refresh ===")
        
        response = requests.post(
            f"{API_BASE}/plans/refresh",
            headers=AUTH_HEADERS
        )
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code != 200:
            print(f"Error Response: {response.text}")
            
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Validate response structure
        assert "plan" in data, "Response should contain 'plan' key"
        assert "message" in data, "Response should contain 'message' key"
        
        plan = data["plan"]
        
        # Validate plan structure
        assert plan["user_id"] == TEST_USER_ID, f"Expected user_id {TEST_USER_ID}, got {plan['user_id']}"
        assert plan["status"] == "active", f"Expected status 'active', got {plan['status']}"
        assert plan["version"] >= 1, f"Version should be at least 1, got {plan['version']}"
        
        print(f"✅ Plan refreshed successfully: {plan['plan_id']}")
        print(f"   - Version: {plan['version']}")
        print(f"   - Status: {plan['status']}")
        print(f"   - Actions: {plan['total_actions']}")
    
    def test_07_generate_signals(self):
        """Test GET /api/signals/generate - Generate portfolio signals."""
        print("\n=== Testing Signal Generation ===")
        
        response = requests.get(
            f"{API_BASE}/signals/generate",
            headers=AUTH_HEADERS
        )
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code != 200:
            print(f"Error Response: {response.text}")
            
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Validate response structure
        assert "signals" in data, "Response should contain 'signals' key"
        assert "summary" in data, "Response should contain 'summary' key"
        
        signals = data["signals"]
        summary = data["summary"]
        
        # Validate signals structure
        assert isinstance(signals, list), "Signals should be a list"
        
        if signals:
            signal = signals[0]
            signal_fields = ["signal_id", "type", "severity", "title", "description", "impact"]
            for field in signal_fields:
                assert field in signal, f"Signal should contain '{field}' field"
            assert signal["severity"] in ["HIGH", "MEDIUM", "LOW"], f"Invalid severity: {signal['severity']}"
        
        # Validate summary structure
        summary_fields = ["total_signals", "high_severity", "medium_severity", "low_severity"]
        for field in summary_fields:
            assert field in summary, f"Summary should contain '{field}' field"
            assert isinstance(summary[field], int), f"Summary field '{field}' should be an integer"
        
        # Validate summary counts
        total_expected = summary["high_severity"] + summary["medium_severity"] + summary["low_severity"]
        assert summary["total_signals"] == total_expected, "Total signals should equal sum of severity counts"
        assert summary["total_signals"] == len(signals), "Total signals should match signals array length"
        
        print(f"✅ Signals generated successfully")
        print(f"   - Total Signals: {summary['total_signals']}")
        print(f"   - High Severity: {summary['high_severity']}")
        print(f"   - Medium Severity: {summary['medium_severity']}")
        print(f"   - Low Severity: {summary['low_severity']}")
        
        if signals:
            print(f"   - First Signal: {signals[0]['type']} - {signals[0]['severity']}")
    
    def test_08_get_plan_history(self):
        """Test GET /api/plans/history - Get user's plan history."""
        print("\n=== Testing Plan History ===")
        
        response = requests.get(
            f"{API_BASE}/plans/history",
            headers=AUTH_HEADERS
        )
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code != 200:
            print(f"Error Response: {response.text}")
            
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Validate response structure
        assert "plans" in data, "Response should contain 'plans' key"
        assert "count" in data, "Response should contain 'count' key"
        
        plans = data["plans"]
        count = data["count"]
        
        # Validate plans structure
        assert isinstance(plans, list), "Plans should be a list"
        assert isinstance(count, int), "Count should be an integer"
        assert count == len(plans), "Count should match plans array length"
        
        if plans:
            plan = plans[0]
            # Should have basic plan structure
            assert "plan_id" in plan, "Plan should contain 'plan_id' field"
            assert "user_id" in plan, "Plan should contain 'user_id' field"
            assert "status" in plan, "Plan should contain 'status' field"
            assert "created_at" in plan, "Plan should contain 'created_at' field"
            assert plan["user_id"] == TEST_USER_ID, f"Expected user_id {TEST_USER_ID}, got {plan['user_id']}"
        
        print(f"✅ Plan history retrieved successfully")
        print(f"   - Total Plans: {count}")
        
        if plans:
            print(f"   - Latest Plan: {plans[0]['plan_id']} ({plans[0]['status']})")
    
    def test_09_error_cases(self):
        """Test error cases and edge conditions."""
        print("\n=== Testing Error Cases ===")
        
        # Test invalid plan ID
        response = requests.get(
            f"{API_BASE}/plans/invalid_plan_id",
            headers=AUTH_HEADERS
        )
        assert response.status_code == 404, f"Expected 404 for invalid plan ID, got {response.status_code}"
        print("✅ Invalid plan ID returns 404")
        
        # Test unauthorized access (no token)
        response = requests.get(f"{API_BASE}/plans/active")
        assert response.status_code in [401, 422], f"Expected 401/422 for unauthorized access, got {response.status_code}"
        print("✅ Unauthorized access properly rejected")
        
        # Test invalid action status update
        gen_response = requests.post(f"{API_BASE}/plans/generate", headers=AUTH_HEADERS)
        if gen_response.status_code == 200:
            plan_id = gen_response.json()["plan"]["plan_id"]
            
            # Invalid status
            response = requests.patch(
                f"{API_BASE}/plans/{plan_id}/actions/invalid_action",
                headers=AUTH_HEADERS,
                json={"status": "INVALID_STATUS"}
            )
            assert response.status_code in [400, 404, 422], f"Expected 400/404/422 for invalid action, got {response.status_code}"
            print("✅ Invalid action update properly rejected")
    
    def test_10_data_validation(self):
        """Test data validation and BSON compatibility."""
        print("\n=== Testing Data Validation ===")
        
        # Generate a plan and check for Decimal/BSON issues
        response = requests.post(f"{API_BASE}/plans/generate", headers=AUTH_HEADERS)
        
        if response.status_code == 200:
            data = response.json()
            plan = data["plan"]
            
            # Check that all numeric fields are JSON-serializable (no Decimal objects)
            def check_json_serializable(obj, path=""):
                if isinstance(obj, dict):
                    for key, value in obj.items():
                        check_json_serializable(value, f"{path}.{key}")
                elif isinstance(obj, list):
                    for i, item in enumerate(obj):
                        check_json_serializable(item, f"{path}[{i}]")
                elif isinstance(obj, (int, float, str, bool, type(None))):
                    pass  # Valid JSON types
                else:
                    raise AssertionError(f"Non-JSON-serializable type {type(obj)} at {path}: {obj}")
            
            try:
                check_json_serializable(plan)
                print("✅ All plan data is JSON-serializable (no Decimal objects)")
            except AssertionError as e:
                print(f"❌ Data validation failed: {e}")
                raise
            
            # Verify numeric fields are proper floats
            if plan.get("freed_capital"):
                assert isinstance(plan["freed_capital"], (int, float)), "freed_capital should be numeric"
            if plan.get("completion_pct"):
                assert isinstance(plan["completion_pct"], (int, float)), "completion_pct should be numeric"
            
            print("✅ Numeric fields are properly typed")


def test_complete_flow():
    """Test the complete V2 plans flow end-to-end."""
    print("\n" + "="*60)
    print("RUNNING COMPLETE V2 PLANS API TEST FLOW")
    print("="*60)
    
    test_instance = TestV2PlansAPI()
    
    try:
        # Run all tests in sequence
        test_instance.test_01_generate_plan()
        test_instance.test_02_save_plan()
        test_instance.test_03_get_active_plan()
        test_instance.test_04_get_plan_by_id()
        test_instance.test_05_update_action_status()
        test_instance.test_06_refresh_plan()
        test_instance.test_07_generate_signals()
        test_instance.test_08_get_plan_history()
        test_instance.test_09_error_cases()
        test_instance.test_10_data_validation()
        
        print("\n" + "="*60)
        print("✅ ALL V2 PLANS API TESTS PASSED")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        print("="*60)
        raise


if __name__ == "__main__":
    test_complete_flow()