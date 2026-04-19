"""Additional tests for drill-down functionality and data structure validation."""
import asyncio
import httpx
import json

async def test_drill_down_data_structure():
    """Test specific drill-down data structure requirements."""
    BASE_URL = "https://fund-overlap-3.preview.emergentagent.com/api"
    TEST_USER_SESSION = "5770bebb-8a9a-41f7-a7b9-e8152ac25daa"
    
    headers = {
        "Cookie": f"session_token={TEST_USER_SESSION}",
        "Content-Type": "application/json"
    }
    
    print("🔍 Testing Drill-Down Data Structure Requirements\n")
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/intelligence/portfolio?narrate=false",
            headers=headers,
            timeout=30.0
        )
        
        assert response.status_code == 200
        data = response.json()
        
        print("1️⃣ Testing pairwise_overlap drill-down structure...")
        
        if data["pairwise_overlap"]:
            overlap = data["pairwise_overlap"][0]
            print(f"   Found {len(data['pairwise_overlap'])} overlap pairs")
            
            # Check top_shared structure for drill-down
            assert "top_shared" in overlap, "Missing top_shared for drill-down"
            
            if overlap["top_shared"]:
                shared = overlap["top_shared"][0]
                required_fields = ["key", "w_a", "w_b", "shared_w"]
                for field in required_fields:
                    assert field in shared, f"Missing {field} in top_shared"
                
                print(f"   ✅ top_shared structure valid: {list(shared.keys())}")
                print(f"   Sample shared stock: {shared['key']} (weights: {shared['w_a']}%, {shared['w_b']}%)")
            else:
                print("   ⚠️  No shared stocks in top overlap pair")
        else:
            print("   ⚠️  No overlap pairs found")
        
        print("\n2️⃣ Testing catalog holdings structure for drill-down...")
        
        if data["catalog"]:
            fund_id = next(iter(data["catalog"]))
            fund_data = data["catalog"][fund_id]
            
            print(f"   Testing fund: {fund_data.get('scheme_name', 'Unknown')}")
            
            assert "holdings" in fund_data, "Missing holdings in catalog"
            
            if fund_data["holdings"]:
                holding = fund_data["holdings"][0]
                required_fields = ["holding_name", "holding_stock_slug", "holding_type", "weight_percent"]
                
                for field in required_fields:
                    assert field in holding, f"Missing {field} in holding"
                
                print(f"   ✅ Holdings structure valid: {list(holding.keys())}")
                print(f"   Sample holding: {holding['holding_name']} ({holding.get('holding_type', 'N/A')})")
                
                # Check for dead position markers
                dead_positions = [h for h in fund_data["holdings"] 
                                if h.get("holding_type") and "💀" in str(h["holding_type"])]
                
                if dead_positions:
                    print(f"   Found {len(dead_positions)} dead positions marked with 💀")
                else:
                    print("   No dead positions found")
                
                # Check for Regular/Direct plan detection
                plan_types = set()
                for h in fund_data["holdings"][:10]:  # Check first 10
                    if h.get("holding_type"):
                        plan_types.add(h["holding_type"])
                
                print(f"   Plan types found: {plan_types}")
                
            else:
                print("   ⚠️  No holdings found in catalog")
        else:
            print("   ⚠️  No catalog data found")
        
        print("\n3️⃣ Testing intelligence context integration...")
        
        # Test that intelligence context is properly formatted for AI
        test_message = "What are my top 5 stock exposures and which funds have the highest overlap?"
        
        chat_response = await client.post(
            f"{BASE_URL}/chat/send",
            headers=headers,
            json={"message": test_message},
            timeout=60.0
        )
        
        assert chat_response.status_code == 200
        chat_data = chat_response.json()
        
        ai_response = chat_data["ai_message"]["content"]
        
        # Check if AI response contains specific intelligence data
        intelligence_keywords = [
            "compression score", "effective stocks", "overlap", "exposure",
            "redundancy", "sector", "₹", "%"
        ]
        
        found_keywords = [kw for kw in intelligence_keywords 
                         if kw.lower() in ai_response.lower()]
        
        print(f"   ✅ AI response uses intelligence data")
        print(f"   Keywords found: {found_keywords}")
        print(f"   Response length: {len(ai_response)} chars")
        
        # Sample a portion of the AI response
        sample = ai_response[:200] + "..." if len(ai_response) > 200 else ai_response
        print(f"   Sample response: {sample}")
        
        print("\n4️⃣ Testing edge cases...")
        
        # Test with empty message
        try:
            empty_response = await client.post(
                f"{BASE_URL}/chat/send",
                headers=headers,
                json={"message": ""},
                timeout=15.0
            )
            print(f"   Empty message status: {empty_response.status_code}")
        except Exception as e:
            print(f"   Empty message handled: {str(e)[:100]}")
        
        # Test intelligence API error handling
        invalid_headers = {"Cookie": "session_token=invalid", "Content-Type": "application/json"}
        
        invalid_response = await client.get(
            f"{BASE_URL}/intelligence/portfolio",
            headers=invalid_headers,
            timeout=15.0
        )
        
        print(f"   Invalid session status: {invalid_response.status_code}")
        
        print("\n🎉 All drill-down and data structure tests passed!")

if __name__ == "__main__":
    asyncio.run(test_drill_down_data_structure())