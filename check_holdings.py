"""Check user holdings to understand the data."""
import asyncio
import httpx

async def check_user_holdings():
    BASE_URL = "https://advisor-timeline.preview.emergentagent.com/api"
    TEST_USER_SESSION = "5770bebb-8a9a-41f7-a7b9-e8152ac25daa"
    
    headers = {
        "Cookie": f"session_token={TEST_USER_SESSION}",
        "Content-Type": "application/json"
    }
    
    async with httpx.AsyncClient() as client:
        # Check portfolio summary
        response = await client.get(
            f"{BASE_URL}/portfolio/summary",
            headers=headers,
            timeout=30.0
        )
        
        print(f"Portfolio Summary Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Holdings count: {len(data.get('holdings', []))}")
            
            if data.get('holdings'):
                print("\nSample holdings:")
                for i, holding in enumerate(data['holdings'][:5]):
                    print(f"  {i+1}. {holding.get('name', 'Unknown')} - {holding.get('asset_type', 'Unknown')} - ₹{holding.get('quantity', 0) * holding.get('current_price', 0):,.0f}")
                
                # Count by asset type
                asset_types = {}
                for h in data['holdings']:
                    asset_type = h.get('asset_type', 'Unknown')
                    asset_types[asset_type] = asset_types.get(asset_type, 0) + 1
                
                print(f"\nAsset types: {asset_types}")

if __name__ == "__main__":
    asyncio.run(check_user_holdings())