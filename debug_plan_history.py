#!/usr/bin/env python3
"""
Debug Plan History API Response
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

print("🔍 Testing Plan History API Response Structure...")

try:
    response = requests.get(f"{base_url}/api/plans/history", headers=headers, timeout=30)
    print(f"Status Code: {response.status_code}")
    
    if response.text:
        try:
            data = response.json()
            print(f"\n📋 Response Structure:")
            print(f"Type: {type(data)}")
            print(f"Keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
            
            print(f"\n📄 Full Response:")
            print(json.dumps(data, indent=2, default=str))
            
        except json.JSONDecodeError as e:
            print(f"❌ JSON Decode Error: {e}")
            print(f"Raw Response: {response.text[:500]}...")
    else:
        print("❌ Empty response")
        
except Exception as e:
    print(f"❌ Request Error: {e}")