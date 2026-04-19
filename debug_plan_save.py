#!/usr/bin/env python3
"""
Debug Plan Save API Response
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

print("🔍 Testing Plan Save API...")

# First generate a plan
print("1. Generating a plan...")
response = requests.post(f"{base_url}/api/plans/generate", headers=headers, timeout=30)
if response.status_code == 200:
    plan_data = response.json()
    plan_id = plan_data['plan']['plan_id']
    print(f"Generated plan ID: {plan_id}")
    
    # Now save the plan
    print("2. Saving the plan...")
    save_response = requests.post(f"{base_url}/api/plans/{plan_id}/save", headers=headers, timeout=30)
    print(f"Save Status Code: {save_response.status_code}")
    
    if save_response.text:
        try:
            save_data = save_response.json()
            print(f"\n📋 Save Response Structure:")
            print(f"Type: {type(save_data)}")
            print(f"Keys: {list(save_data.keys()) if isinstance(save_data, dict) else 'Not a dict'}")
            
            print(f"\n📄 Full Save Response:")
            print(json.dumps(save_data, indent=2, default=str))
            
        except json.JSONDecodeError as e:
            print(f"❌ JSON Decode Error: {e}")
            print(f"Raw Response: {save_response.text[:500]}...")
    else:
        print("❌ Empty save response")
else:
    print(f"❌ Failed to generate plan: {response.status_code}")