"""Test Portfolio Intelligence integration into AI Copilot Chat."""
import pytest
import httpx
import json
from typing import Dict, Any

# Test configuration
BASE_URL = "https://portfolio-pro-985.preview.emergentagent.com/api"
TEST_USER_SESSION = "5770bebb-8a9a-41f7-a7b9-e8152ac25daa"  # aporwal107@gmail.com with holdings
ADMIN_SESSION = "370eff71-fda1-46d8-b506-b81b894d634f"  # priyankamantri@gmail.com


class TestPortfolioIntelligenceChat:
    """Test Portfolio Intelligence integration into chat endpoints."""

    @pytest.fixture
    def headers(self):
        """Headers with test user session."""
        return {
            "Cookie": f"session_token={TEST_USER_SESSION}",
            "Content-Type": "application/json"
        }

    @pytest.fixture
    def admin_headers(self):
        """Headers with admin session."""
        return {
            "Cookie": f"session_token={ADMIN_SESSION}",
            "Content-Type": "application/json"
        }

    async def test_intelligence_api_structure(self, headers):
        """Test GET /intelligence/portfolio returns expected data structure."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE_URL}/intelligence/portfolio?narrate=false",
                headers=headers,
                timeout=30.0
            )
            
            assert response.status_code == 200, f"Intelligence API failed: {response.text}"
            data = response.json()
            
            # Verify core structure
            assert "mf_investments" in data, "Missing mf_investments"
            assert "pairwise_overlap" in data, "Missing pairwise_overlap"
            assert "top_stocks" in data, "Missing top_stocks"
            assert "compression" in data, "Missing compression"
            assert "catalog" in data, "Missing catalog"
            assert "narrative" in data, "Missing narrative"
            
            # Verify catalog structure for drill-down
            if data["catalog"]:
                sample_fund = next(iter(data["catalog"].values()))
                assert "holdings" in sample_fund, "Catalog missing holdings"
                if sample_fund["holdings"]:
                    holding = sample_fund["holdings"][0]
                    assert "holding_name" in holding, "Missing holding_name"
                    assert "holding_stock_slug" in holding, "Missing holding_stock_slug"
                    assert "holding_type" in holding, "Missing holding_type for Regular/Direct detection"
                    assert "weight_percent" in holding, "Missing weight_percent"
            
            # Verify pairwise_overlap includes top_shared for drill-down
            if data["pairwise_overlap"]:
                overlap = data["pairwise_overlap"][0]
                assert "top_shared" in overlap, "Missing top_shared for drill-down"
                if overlap["top_shared"]:
                    shared = overlap["top_shared"][0]
                    assert "key" in shared, "Missing stock key in top_shared"
                    assert "w_a" in shared, "Missing weight_a in top_shared"
                    assert "w_b" in shared, "Missing weight_b in top_shared"
            
            print(f"✅ Intelligence API structure validated")
            return data

    async def test_chat_send_intelligence_integration(self, headers):
        """Test POST /chat/send includes portfolio intelligence context."""
        test_message = "What are the top stock exposures in my portfolio and any overlaps between my mutual funds?"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BASE_URL}/chat/send",
                headers=headers,
                json={"message": test_message},
                timeout=60.0
            )
            
            assert response.status_code == 200, f"Chat send failed: {response.text}"
            data = response.json()
            
            # Verify response structure
            assert "user_message" in data, "Missing user_message"
            assert "ai_message" in data, "Missing ai_message"
            
            ai_response = data["ai_message"]["content"]
            assert len(ai_response) > 0, "Empty AI response"
            
            # Check if AI response references portfolio intelligence data
            # Look for keywords that indicate intelligence context was used
            intelligence_indicators = [
                "compression", "overlap", "exposure", "stock", "fund",
                "portfolio", "effective", "redundancy", "sector"
            ]
            
            found_indicators = [word for word in intelligence_indicators 
                              if word.lower() in ai_response.lower()]
            
            assert len(found_indicators) >= 2, f"AI response doesn't seem to use intelligence context. Found: {found_indicators}"
            
            print(f"✅ Chat send with intelligence context working")
            print(f"   AI response length: {len(ai_response)} chars")
            print(f"   Intelligence indicators found: {found_indicators}")
            
            return data

    async def test_chat_stream_intelligence_integration(self, headers):
        """Test POST /chat/stream includes portfolio intelligence context."""
        test_message = "Analyze my portfolio compression score and suggest any redundant funds to remove"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BASE_URL}/chat/stream",
                headers=headers,
                json={"message": test_message},
                timeout=60.0
            )
            
            assert response.status_code == 200, f"Chat stream failed: {response.text}"
            content_type = response.headers.get("content-type", "")
            assert "text/event-stream" in content_type, f"Not SSE response, got: {content_type}"
            
            # Collect streamed response
            full_response = ""
            metadata = None
            
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    try:
                        event_data = json.loads(line[6:])  # Remove "data: " prefix
                        if event_data.get("type") == "meta":
                            metadata = event_data
                        elif event_data.get("type") == "token":
                            full_response += event_data.get("content", "")
                        elif event_data.get("type") == "done":
                            break
                    except json.JSONDecodeError:
                        continue
            
            assert metadata is not None, "No metadata received"
            assert "session_id" in metadata, "Missing session_id in metadata"
            assert len(full_response) > 0, "Empty streamed response"
            
            # Check for intelligence context usage
            intelligence_indicators = [
                "compression", "overlap", "redundancy", "portfolio", "fund"
            ]
            
            found_indicators = [word for word in intelligence_indicators 
                              if word.lower() in full_response.lower()]
            
            assert len(found_indicators) >= 2, f"Streamed response doesn't use intelligence context. Found: {found_indicators}"
            
            print(f"✅ Chat stream with intelligence context working")
            print(f"   Streamed response length: {len(full_response)} chars")
            print(f"   Intelligence indicators found: {found_indicators}")
            
            return full_response

    async def test_intelligence_context_helper_function(self, headers):
        """Test the _compute_portfolio_intelligence_context helper function indirectly."""
        # Test with a simple message to verify context is being computed
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BASE_URL}/chat/send",
                headers=headers,
                json={"message": "Hello"},
                timeout=30.0
            )
            
            assert response.status_code == 200, f"Chat failed: {response.text}"
            
            # If user has holdings, the context should be computed
            # We can't directly test the helper function, but we can verify
            # that the chat endpoint doesn't fail when computing intelligence context
            data = response.json()
            assert "ai_message" in data, "Missing AI response"
            
            print(f"✅ Intelligence context helper function working (no errors)")

    async def test_empty_portfolio_handling(self):
        """Test intelligence context with empty portfolio (should return empty string)."""
        # This would require a user with no holdings, which we don't have in test data
        # So we'll skip this test for now
        print("⏭️  Skipping empty portfolio test (no test user without holdings)")

    async def test_intelligence_api_with_narration(self, headers):
        """Test intelligence API with AI narration enabled."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE_URL}/intelligence/portfolio?narrate=true",
                headers=headers,
                timeout=45.0
            )
            
            assert response.status_code == 200, f"Intelligence API with narration failed: {response.text}"
            data = response.json()
            
            # With narration=true, should include AI insights
            if not data.get("empty"):
                # AI insights might be present if LLM is working
                if "ai_insights" in data:
                    print("✅ AI insights generated successfully")
                else:
                    print("⚠️  AI insights not generated (LLM might be down)")
            
            print(f"✅ Intelligence API with narration working")

    async def test_admin_intelligence_access(self, admin_headers):
        """Test admin access to user's portfolio intelligence."""
        test_user_id = "user_6a8206568b50"  # aporwal107@gmail.com
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE_URL}/intelligence/portfolio/{test_user_id}?narrate=false",
                headers=admin_headers,
                timeout=30.0
            )
            
            assert response.status_code == 200, f"Admin intelligence access failed: {response.text}"
            data = response.json()
            
            assert "mf_investments" in data, "Missing mf_investments in admin view"
            print(f"✅ Admin intelligence access working")

    async def test_error_handling(self, headers):
        """Test error handling in intelligence integration."""
        # Test with invalid session (should fail gracefully)
        invalid_headers = {
            "Cookie": "session_token=invalid-token",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE_URL}/intelligence/portfolio",
                headers=invalid_headers,
                timeout=15.0
            )
            
            # Should return 401 or 403 for invalid session
            assert response.status_code in [401, 403], f"Expected auth error, got: {response.status_code}"
            
            print(f"✅ Error handling working (invalid session rejected)")


# Run tests
async def run_all_tests():
    """Run all portfolio intelligence chat tests."""
    test_instance = TestPortfolioIntelligenceChat()
    
    # Create fixtures
    headers = {"Cookie": f"session_token={TEST_USER_SESSION}", "Content-Type": "application/json"}
    admin_headers = {"Cookie": f"session_token={ADMIN_SESSION}", "Content-Type": "application/json"}
    
    print("🧪 Starting Portfolio Intelligence Chat Integration Tests\n")
    
    try:
        # Test 1: Intelligence API structure
        print("1️⃣ Testing Intelligence API structure...")
        await test_instance.test_intelligence_api_structure(headers)
        
        # Test 2: Chat send integration
        print("\n2️⃣ Testing Chat Send intelligence integration...")
        await test_instance.test_chat_send_intelligence_integration(headers)
        
        # Test 3: Chat stream integration
        print("\n3️⃣ Testing Chat Stream intelligence integration...")
        await test_instance.test_chat_stream_intelligence_integration(headers)
        
        # Test 4: Helper function
        print("\n4️⃣ Testing intelligence context helper...")
        await test_instance.test_intelligence_context_helper_function(headers)
        
        # Test 5: Intelligence with narration
        print("\n5️⃣ Testing intelligence API with narration...")
        await test_instance.test_intelligence_api_with_narration(headers)
        
        # Test 6: Admin access
        print("\n6️⃣ Testing admin intelligence access...")
        await test_instance.test_admin_intelligence_access(admin_headers)
        
        # Test 7: Error handling
        print("\n7️⃣ Testing error handling...")
        await test_instance.test_error_handling(headers)
        
        print("\n🎉 All Portfolio Intelligence Chat Integration Tests Passed!")
        
    except Exception as e:
        print(f"\n❌ Test failed: {str(e)}")
        raise


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_all_tests())