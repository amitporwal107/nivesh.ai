#!/usr/bin/env python3
"""
Debug Plan by ID API Response
"""
import requests
import json

# Test credentials
base_url = "https://portfolio-pro-985.preview.emergentagent.com"
session_token = "370eff71-fda1-46d8-b506-b81b894d634f"
headers = {
    'Content-Type': 'application/json',
    'Cookie': f'session_token={session_token}'
}

print("🔍 Testing Plan by ID API...")

# First get active plan
print("1. Getting active plan...")
response = requests.get(f"{base_url}/api/plans/active", headers=headers, timeout=30)
if response.status_code == 200:
    active_data = response.json()
    if active_data.get('has_plan') and active_data.get('plan'):
        plan_id = active_data['plan']['plan_id']
        print(f"Active plan ID: {plan_id}")
        
        # Now get the plan by ID
        print("2. Getting plan by ID...")
        plan_response = requests.get(f"{base_url}/api/plans/{plan_id}", headers=headers, timeout=30)
        print(f"Plan by ID Status Code: {plan_response.status_code}")
        
        if plan_response.text:
            try:
                plan_data = plan_response.json()
                print(f"\n📋 Plan by ID Response Structure:")
                print(f"Type: {type(plan_data)}")
                print(f"Keys: {list(plan_data.keys()) if isinstance(plan_data, dict) else 'Not a dict'}")
                
                # Check actions structure
                if 'actions' in plan_data:
                    actions = plan_data['actions']
                    print(f"\nActions: {len(actions)} found")
                    if actions:
                        print(f"First action keys: {list(actions[0].keys())}")
                        print(f"First action ID: {actions[0].get('action_id')}")
                
                print(f"\n📄 Full Plan Response (first 1000 chars):")
                print(json.dumps(plan_data, indent=2, default=str)[:1000] + "...")
                
            except json.JSONDecodeError as e:
                print(f"❌ JSON Decode Error: {e}")
                print(f"Raw Response: {plan_response.text[:500]}...")
        else:
            print("❌ Empty plan response")
    else:
        print("❌ No active plan found")
else:
    print(f"❌ Failed to get active plan: {response.status_code}")