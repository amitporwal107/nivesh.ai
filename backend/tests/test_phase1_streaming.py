"""
Phase 1 AI-first UX Testing - Backend API Tests
Tests: SSE streaming, legacy batch chat, portfolio endpoints, auth
"""
import pytest
import requests
import os
import json
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://nivesh-ai-preview.preview.emergentagent.com')

# Test credentials from test_credentials.md
TEST_USER_SESSION = "5770bebb-8a9a-41f7-a7b9-e8152ac25daa"
ADMIN_SESSION = "370eff71-fda1-46d8-b506-b81b894d634f"


@pytest.fixture
def auth_cookies():
    """Return cookies for authenticated test user"""
    return {"session_token": TEST_USER_SESSION}


@pytest.fixture
def admin_cookies():
    """Return cookies for admin user"""
    return {"session_token": ADMIN_SESSION}


class TestHealthAndAuth:
    """Basic health and authentication tests"""
    
    def test_api_root(self):
        """GET /api/ - root endpoint returns API message"""
        response = requests.get(f"{BASE_URL}/api/")
        assert response.status_code == 200
        data = response.json()
        assert data.get("message") == "nivesh.ai API"
    
    def test_auth_me_with_valid_session(self, auth_cookies):
        """GET /api/auth/me - returns user info with valid session"""
        response = requests.get(f"{BASE_URL}/api/auth/me", cookies=auth_cookies)
        assert response.status_code == 200
        data = response.json()
        assert "user_id" in data
        assert "email" in data
        assert data["email"] == "aporwal107@gmail.com"
    
    def test_auth_me_without_session(self):
        """GET /api/auth/me - returns 401 without session"""
        response = requests.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code == 401


class TestChatStreamingEndpoint:
    """Tests for POST /api/chat/stream - SSE streaming endpoint"""
    
    def test_stream_returns_sse_format(self, auth_cookies):
        """POST /api/chat/stream - returns SSE format with meta, token, done types"""
        response = requests.post(
            f"{BASE_URL}/api/chat/stream",
            json={"message": "Hi"},
            cookies=auth_cookies,
            stream=True,
            timeout=30
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        
        # Parse SSE events
        events = []
        for line in response.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                try:
                    event_data = json.loads(line[6:])
                    events.append(event_data)
                    # Stop after getting meta and a few tokens
                    if len(events) >= 5:
                        break
                except json.JSONDecodeError:
                    pass
        
        # Verify we got meta event first
        assert len(events) > 0, "Should receive at least one SSE event"
        assert events[0].get("type") == "meta", "First event should be meta"
        assert "session_id" in events[0], "Meta should contain session_id"
        assert "user_msg_id" in events[0], "Meta should contain user_msg_id"
        assert "ai_msg_id" in events[0], "Meta should contain ai_msg_id"
        
        # Verify token events
        token_events = [e for e in events if e.get("type") == "token"]
        assert len(token_events) > 0, "Should receive token events"
        for token_event in token_events:
            assert "content" in token_event, "Token event should have content"
    
    def test_stream_requires_message(self, auth_cookies):
        """POST /api/chat/stream - returns 400 if message is empty"""
        response = requests.post(
            f"{BASE_URL}/api/chat/stream",
            json={"message": ""},
            cookies=auth_cookies,
            timeout=10
        )
        assert response.status_code == 400
    
    def test_stream_requires_auth(self):
        """POST /api/chat/stream - returns 401 without auth"""
        response = requests.post(
            f"{BASE_URL}/api/chat/stream",
            json={"message": "Hi"},
            timeout=10
        )
        assert response.status_code == 401


class TestChatBatchEndpoint:
    """Tests for POST /api/chat/send - legacy batch endpoint"""
    
    def test_batch_chat_returns_messages(self, auth_cookies):
        """POST /api/chat/send - returns user_message and ai_message"""
        response = requests.post(
            f"{BASE_URL}/api/chat/send",
            json={"message": "Hello"},
            cookies=auth_cookies,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify user message
        assert "user_message" in data
        user_msg = data["user_message"]
        assert user_msg.get("role") == "user"
        assert user_msg.get("content") == "Hello"
        assert "message_id" in user_msg
        assert "session_id" in user_msg
        
        # Verify AI message
        assert "ai_message" in data
        ai_msg = data["ai_message"]
        assert ai_msg.get("role") == "assistant"
        assert "content" in ai_msg
        assert len(ai_msg["content"]) > 0, "AI should respond with content"
    
    def test_batch_chat_requires_auth(self):
        """POST /api/chat/send - returns 401 without auth"""
        response = requests.post(
            f"{BASE_URL}/api/chat/send",
            json={"message": "Hello"},
            timeout=10
        )
        assert response.status_code == 401


class TestChatSessions:
    """Tests for chat session management"""
    
    def test_list_sessions(self, auth_cookies):
        """GET /api/chat/sessions - returns list of sessions"""
        response = requests.get(f"{BASE_URL}/api/chat/sessions", cookies=auth_cookies)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        if len(data) > 0:
            session = data[0]
            assert "session_id" in session
            assert "title" in session
    
    def test_get_messages(self, auth_cookies):
        """GET /api/chat/messages - returns messages"""
        response = requests.get(f"{BASE_URL}/api/chat/messages", cookies=auth_cookies)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestPortfolioEndpoints:
    """Tests for portfolio data endpoints"""
    
    def test_get_holdings(self, auth_cookies):
        """GET /api/portfolio/holdings - returns holdings list"""
        response = requests.get(f"{BASE_URL}/api/portfolio/holdings", cookies=auth_cookies)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0, "Test user should have holdings"
        
        # Verify holding structure
        holding = data[0]
        assert "holding_id" in holding
        assert "name" in holding
        assert "asset_type" in holding
        assert "quantity" in holding
    
    def test_get_analytics(self, auth_cookies):
        """GET /api/portfolio/analytics - returns analytics data"""
        response = requests.get(f"{BASE_URL}/api/portfolio/analytics", cookies=auth_cookies)
        assert response.status_code == 200
        data = response.json()
        
        # Verify key analytics fields
        assert "total_invested" in data
        assert "current_value" in data
        assert "total_returns" in data
        assert "asset_allocation" in data
        assert "holdings_count" in data
        assert data["holdings_count"] > 0
    
    def test_holdings_requires_auth(self):
        """GET /api/portfolio/holdings - returns 401 without auth"""
        response = requests.get(f"{BASE_URL}/api/portfolio/holdings")
        assert response.status_code == 401
    
    def test_analytics_requires_auth(self):
        """GET /api/portfolio/analytics - returns 401 without auth"""
        response = requests.get(f"{BASE_URL}/api/portfolio/analytics")
        assert response.status_code == 401


class TestInsightsEndpoints:
    """Tests for insights endpoints"""
    
    def test_get_insights(self, auth_cookies):
        """GET /api/insights - returns insights list"""
        response = requests.get(f"{BASE_URL}/api/insights", cookies=auth_cookies)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_insights_requires_auth(self):
        """GET /api/insights - returns 401 without auth"""
        response = requests.get(f"{BASE_URL}/api/insights")
        assert response.status_code == 401


class TestUserProfile:
    """Tests for user profile endpoint"""
    
    def test_get_profile(self, auth_cookies):
        """GET /api/user/profile - returns user profile"""
        response = requests.get(f"{BASE_URL}/api/user/profile", cookies=auth_cookies)
        assert response.status_code == 200
        data = response.json()
        assert "user_id" in data or "journey_type" in data or "onboarding_completed" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
