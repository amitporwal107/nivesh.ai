"""Check actual intelligence data for test user."""
import asyncio
import httpx
import json

async def check_intelligence_data():
    BASE_URL = "https://wealth-advisor-india-1.preview.emergentagent.com/api"
    TEST_USER_SESSION = "5770bebb-8a9a-41f7-a7b9-e8152ac25daa"
    
    headers = {
        "Cookie": f"session_token={TEST_USER_SESSION}",
        "Content-Type": "application/json"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/intelligence/portfolio?narrate=false",
            headers=headers,
            timeout=30.0
        )
        
        print(f"Status: {response.status_code}")
        data = response.json()
        
        print(f"Empty: {data.get('empty', False)}")
        print(f"Reason: {data.get('reason', 'N/A')}")
        print(f"MF Investments: {len(data.get('mf_investments', []))}")
        print(f"Pairwise Overlap: {len(data.get('pairwise_overlap', []))}")
        print(f"Top Stocks: {len(data.get('top_stocks', []))}")
        print(f"Catalog: {len(data.get('catalog', {}))}")
        
        if data.get('mf_investments'):
            print("\nMF Investments:")
            for i, inv in enumerate(data['mf_investments'][:3]):
                print(f"  {i+1}. {inv.get('scheme_name', 'Unknown')} - ₹{inv.get('amount_rs', 0):,.0f} - Resolved: {inv.get('resolved', False)}")
        
        if data.get('narrative'):
            print(f"\nNarrative:")
            print(f"  Total Invested: ₹{data['narrative'].get('total_invested_rs', 0):,.0f}")
            print(f"  Unique Stocks: {data['narrative'].get('unique_stocks', 0)}")
            print(f"  Effective Stocks: {data['narrative'].get('effective_stocks', 0)}")
            print(f"  Compression Score: {data['narrative'].get('compression_score', 0)}")

if __name__ == "__main__":
    asyncio.run(check_intelligence_data())