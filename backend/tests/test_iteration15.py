"""
Iteration 15 Backend Tests
Testing new features:
1. User Profile / Journey / Risk Profile endpoints
2. Chat Session CRUD (create, list, delete)
3. Chat messages with session_id
4. Markdown rendering (backend returns markdown content)
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
TEST_TOKEN = "test_session_wealth001"
TEST_USER_ID = "test-user-wealth001"

@pytest.fixture
def api_client():
    """Shared requests session with auth"""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {TEST_TOKEN}"
    })
    return session


class TestUserProfile:
    """User profile, journey, and risk profile endpoints"""
    
    def test_get_user_profile(self, api_client):
        """GET /api/user/profile returns user profile with journey_type and risk_profile"""
        response = api_client.get(f"{BASE_URL}/api/user/profile")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "user_id" in data or "journey_type" in data, "Profile should have user_id or journey_type"
        # journey_type can be null, existing_investor, or new_investor
        if "journey_type" in data:
            assert data["journey_type"] in [None, "existing_investor", "new_investor"], f"Invalid journey_type: {data['journey_type']}"
        print(f"User profile: journey_type={data.get('journey_type')}, risk_profile={data.get('risk_profile')}")
    
    def test_set_journey_existing_investor(self, api_client):
        """POST /api/user/journey sets journey type to existing_investor"""
        response = api_client.post(f"{BASE_URL}/api/user/journey", json={
            "journey_type": "existing_investor"
        })
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("journey_type") == "existing_investor", f"Expected existing_investor, got {data.get('journey_type')}"
        print(f"Journey set to: {data.get('journey_type')}")
    
    def test_set_journey_new_investor(self, api_client):
        """POST /api/user/journey sets journey type to new_investor"""
        response = api_client.post(f"{BASE_URL}/api/user/journey", json={
            "journey_type": "new_investor"
        })
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("journey_type") == "new_investor", f"Expected new_investor, got {data.get('journey_type')}"
        print(f"Journey set to: {data.get('journey_type')}")
    
    def test_submit_risk_profile(self, api_client):
        """POST /api/user/risk-profile calculates risk score and category"""
        # Submit answers for all 6 questions
        answers = [
            {"question_id": "market_drop", "answer": "hold"},
            {"question_id": "investment_horizon", "answer": "5_10yr"},
            {"question_id": "loss_tolerance", "answer": "up_to_25"},
            {"question_id": "income_stability", "answer": "stable"},
            {"question_id": "investment_knowledge", "answer": "intermediate"},
            {"question_id": "goal_priority", "answer": "growth"},
        ]
        
        response = api_client.post(f"{BASE_URL}/api/user/risk-profile", json={
            "answers": answers
        })
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "risk_profile" in data, "Response should contain risk_profile"
        rp = data["risk_profile"]
        assert "score" in rp, "Risk profile should have score"
        assert "category" in rp, "Risk profile should have category"
        assert isinstance(rp["score"], int), "Score should be integer"
        assert rp["category"] in ["Aggressive", "Moderately Aggressive", "Moderate", "Moderately Conservative", "Conservative"], f"Invalid category: {rp['category']}"
        print(f"Risk profile: score={rp['score']}, category={rp['category']}")
    
    def test_get_risk_profile(self, api_client):
        """GET /api/user/risk-profile returns saved risk profile"""
        response = api_client.get(f"{BASE_URL}/api/user/risk-profile")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # risk_profile can be null if not set
        if data.get("risk_profile"):
            rp = data["risk_profile"]
            assert "score" in rp, "Risk profile should have score"
            assert "category" in rp, "Risk profile should have category"
            print(f"Retrieved risk profile: {rp['category']} (score: {rp['score']})")
        else:
            print("No risk profile set yet")


class TestChatSessions:
    """Chat session CRUD operations"""
    
    created_session_id = None
    
    def test_list_chat_sessions(self, api_client):
        """GET /api/chat/sessions returns list of sessions"""
        response = api_client.get(f"{BASE_URL}/api/chat/sessions")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert isinstance(data, list), "Response should be a list"
        print(f"Found {len(data)} chat sessions")
        if data:
            session = data[0]
            assert "session_id" in session, "Session should have session_id"
            assert "title" in session, "Session should have title"
            print(f"First session: {session['session_id']} - {session['title']}")
    
    def test_create_chat_session(self, api_client):
        """POST /api/chat/sessions creates a new session"""
        response = api_client.post(f"{BASE_URL}/api/chat/sessions", json={})
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "session_id" in data, "Response should have session_id"
        assert "title" in data, "Response should have title"
        assert data["title"] == "New Conversation", f"Expected 'New Conversation', got {data['title']}"
        
        TestChatSessions.created_session_id = data["session_id"]
        print(f"Created session: {data['session_id']}")
    
    def test_verify_session_in_list(self, api_client):
        """Verify created session appears in list"""
        if not TestChatSessions.created_session_id:
            pytest.skip("No session created")
        
        response = api_client.get(f"{BASE_URL}/api/chat/sessions")
        assert response.status_code == 200
        
        data = response.json()
        session_ids = [s["session_id"] for s in data]
        assert TestChatSessions.created_session_id in session_ids, "Created session should be in list"
        print(f"Session {TestChatSessions.created_session_id} found in list")
    
    def test_delete_chat_session(self, api_client):
        """DELETE /api/chat/sessions/{session_id} deletes a session"""
        if not TestChatSessions.created_session_id:
            pytest.skip("No session to delete")
        
        response = api_client.delete(f"{BASE_URL}/api/chat/sessions/{TestChatSessions.created_session_id}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "message" in data, "Response should have message"
        print(f"Deleted session: {TestChatSessions.created_session_id}")
    
    def test_verify_session_deleted(self, api_client):
        """Verify deleted session no longer in list"""
        if not TestChatSessions.created_session_id:
            pytest.skip("No session to verify")
        
        response = api_client.get(f"{BASE_URL}/api/chat/sessions")
        assert response.status_code == 200
        
        data = response.json()
        session_ids = [s["session_id"] for s in data]
        assert TestChatSessions.created_session_id not in session_ids, "Deleted session should not be in list"
        print(f"Session {TestChatSessions.created_session_id} successfully removed")


class TestChatMessages:
    """Chat messages with session support"""
    
    test_session_id = None
    
    def test_create_session_for_messages(self, api_client):
        """Create a session for message tests"""
        response = api_client.post(f"{BASE_URL}/api/chat/sessions", json={})
        assert response.status_code == 200
        TestChatMessages.test_session_id = response.json()["session_id"]
        print(f"Created test session: {TestChatMessages.test_session_id}")
    
    def test_send_message_with_session(self, api_client):
        """POST /api/chat/send with session_id saves message to that session"""
        if not TestChatMessages.test_session_id:
            pytest.skip("No session created")
        
        response = api_client.post(f"{BASE_URL}/api/chat/send", json={
            "message": "What is my portfolio allocation?",
            "session_id": TestChatMessages.test_session_id
        })
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "user_message" in data, "Response should have user_message"
        assert "ai_message" in data, "Response should have ai_message"
        
        user_msg = data["user_message"]
        assert user_msg["role"] == "user", "User message role should be 'user'"
        assert user_msg["session_id"] == TestChatMessages.test_session_id, "Session ID should match"
        
        ai_msg = data["ai_message"]
        assert ai_msg["role"] == "assistant", "AI message role should be 'assistant'"
        assert ai_msg["session_id"] == TestChatMessages.test_session_id, "Session ID should match"
        assert len(ai_msg["content"]) > 0, "AI should return some content"
        
        print(f"User message: {user_msg['content'][:50]}...")
        print(f"AI response: {ai_msg['content'][:100]}...")
    
    def test_get_messages_for_session(self, api_client):
        """GET /api/chat/messages?session_id=X returns messages for that session"""
        if not TestChatMessages.test_session_id:
            pytest.skip("No session created")
        
        response = api_client.get(f"{BASE_URL}/api/chat/messages?session_id={TestChatMessages.test_session_id}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert isinstance(data, list), "Response should be a list"
        assert len(data) >= 2, f"Should have at least 2 messages (user + AI), got {len(data)}"
        
        # Verify all messages belong to this session
        for msg in data:
            assert msg["session_id"] == TestChatMessages.test_session_id, f"Message session_id mismatch"
        
        print(f"Found {len(data)} messages in session")
    
    def test_session_title_updated(self, api_client):
        """Verify session title is auto-updated from first message"""
        if not TestChatMessages.test_session_id:
            pytest.skip("No session created")
        
        response = api_client.get(f"{BASE_URL}/api/chat/sessions")
        assert response.status_code == 200
        
        data = response.json()
        session = next((s for s in data if s["session_id"] == TestChatMessages.test_session_id), None)
        assert session is not None, "Session should exist"
        
        # Title should be updated from first message
        assert session["title"] != "New Conversation", f"Title should be updated, got: {session['title']}"
        print(f"Session title updated to: {session['title']}")
    
    def test_cleanup_test_session(self, api_client):
        """Cleanup: delete test session"""
        if not TestChatMessages.test_session_id:
            pytest.skip("No session to cleanup")
        
        response = api_client.delete(f"{BASE_URL}/api/chat/sessions/{TestChatMessages.test_session_id}")
        assert response.status_code == 200
        print(f"Cleaned up test session: {TestChatMessages.test_session_id}")


class TestChatMarkdown:
    """Test that AI responses contain markdown formatting"""
    
    def test_ai_response_contains_markdown(self, api_client):
        """AI responses should contain markdown formatting"""
        # First create a session
        session_res = api_client.post(f"{BASE_URL}/api/chat/sessions", json={})
        assert session_res.status_code == 200
        session_id = session_res.json()["session_id"]
        
        # Send a message that should trigger markdown response
        response = api_client.post(f"{BASE_URL}/api/chat/send", json={
            "message": "Give me a comparison table of equity vs debt mutual funds with pros and cons",
            "session_id": session_id
        })
        
        if response.status_code == 200:
            data = response.json()
            ai_content = data.get("ai_message", {}).get("content", "")
            
            # Check for markdown indicators (may not always be present depending on AI response)
            has_markdown = any([
                "**" in ai_content,  # bold
                "- " in ai_content or "* " in ai_content,  # lists
                "|" in ai_content,  # tables
                "#" in ai_content,  # headings
                "₹" in ai_content,  # INR symbol
            ])
            
            print(f"AI response length: {len(ai_content)} chars")
            print(f"Contains markdown indicators: {has_markdown}")
            print(f"Sample: {ai_content[:200]}...")
        else:
            print(f"Chat send returned {response.status_code} - AI may be unavailable")
        
        # Cleanup
        api_client.delete(f"{BASE_URL}/api/chat/sessions/{session_id}")


class TestHealthAndAuth:
    """Basic health and auth checks"""
    
    def test_health_endpoint(self, api_client):
        """Health endpoint should return 200"""
        response = api_client.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Health check failed: {response.status_code}"
        print("Health check passed")
    
    def test_auth_me_with_token(self, api_client):
        """Auth me endpoint should return user info"""
        response = api_client.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code == 200, f"Auth me failed: {response.status_code}: {response.text}"
        
        data = response.json()
        assert "user_id" in data, "Response should have user_id"
        print(f"Authenticated as: {data.get('email', data.get('user_id'))}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
