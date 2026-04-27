"""Test with admin user and check available endpoints."""
import asyncio
import httpx

async def test_admin_intelligence():
    BASE_URL = "https://advisor-timeline.preview.emergentagent.com/api"
    ADMIN_SESSION = "370eff71-fda1-46d8-b506-b81b894d634f"
    
    headers = {
        "Cookie": f"session_token={ADMIN_SESSION}",
        "Content-Type": "application/json"
    }
    
    async with httpx.AsyncClient() as client:
        # Test admin's own intelligence
        response = await client.get(
            f"{BASE_URL}/intelligence/portfolio?narrate=false",
            headers=headers,
            timeout=30.0
        )
        
        print(f"Admin Intelligence Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Admin Empty: {data.get('empty', False)}")
            print(f"Admin Reason: {data.get('reason', 'N/A')}")
            print(f"Admin MF Investments: {len(data.get('mf_investments', []))}")
            
            if data.get('mf_investments'):
                print("\nAdmin MF Investments:")
                for i, inv in enumerate(data['mf_investments'][:3]):
                    print(f"  {i+1}. {inv.get('scheme_name', 'Unknown')} - ₹{inv.get('amount_rs', 0):,.0f} - Resolved: {inv.get('resolved', False)}")

if __name__ == "__main__":
    asyncio.run(test_admin_intelligence())