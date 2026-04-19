#!/usr/bin/env python3
"""
Debug Action Status Update API Response
"""
import requests
import json

# Test credentials
base_url = "https://fund-overlap-3.preview.emergentagent.com"
session_token = "370eff71-fda1-46d8-b506-b81b894d634f"
headers = {
    'Content-Type': 'application/json',
    'Cookie': f'session_token={session_token}'
}

print("🔍 Testing Action Status Update API...")

# First get active plan
print("1. Getting active plan...")
response = requests.get(f"{base_url}/api/plans/active", headers=headers, timeout=30)
if response.status_code == 200:
    active_data = response.json()
    if active_data.get('has_plan') and active_data.get('plan'):
        plan_id = active_data['plan']['plan_id']
        print(f"Active plan ID: {plan_id}")
        
        # Get plan details to find action ID
        plan_response = requests.get(f"{base_url}/api/plans/{plan_id}", headers=headers, timeout=30)
        if plan_response.status_code == 200:
            plan_data = plan_response.json()
            plan = plan_data.get('plan', {})
            actions = plan.get('actions', [])
            
            if actions:
                action_id = actions[0].get('action_id')
                print(f"Action ID: {action_id}")
                
                # Update action status
                print("2. Updating action status...")
                update_data = {
                    "status": "COMPLETED",
                    "completion_note": "Test completion via API"
                }
                
                update_response = requests.patch(
                    f"{base_url}/api/plans/{plan_id}/actions/{action_id}", 
                    json=update_data, 
                    headers=headers, 
                    timeout=30
                )
                print(f"Update Status Code: {update_response.status_code}")
                
                if update_response.text:
                    try:
                        update_result = update_response.json()
                        print(f"\n📋 Update Response Structure:")
                        print(f"Type: {type(update_result)}")
                        print(f"Keys: {list(update_result.keys()) if isinstance(update_result, dict) else 'Not a dict'}")
                        
                        print(f"\n📄 Full Update Response:")
                        print(json.dumps(update_result, indent=2, default=str))
                        
                    except json.JSONDecodeError as e:
                        print(f"❌ JSON Decode Error: {e}")
                        print(f"Raw Response: {update_response.text[:500]}...")
                else:
                    print("❌ Empty update response")
            else:
                print("❌ No actions found in plan")
        else:
            print(f"❌ Failed to get plan details: {plan_response.status_code}")
    else:
        print("❌ No active plan found")
else:
    print(f"❌ Failed to get active plan: {response.status_code}")