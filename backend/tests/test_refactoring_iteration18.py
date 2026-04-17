"""
Test suite for server.py refactoring verification (Iteration 18)
Verifies all endpoints work correctly after splitting server.py into route modules.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials - using admin session since test user session expired
ADMIN_SESSION_TOKEN = "55bb716c-ac0d-4966-8b26-ecddbbdf774b"
ADMIN_EMAIL = "priyankamantri@gmail.com"
VALID_SESSION_TOKEN = ADMIN_SESSION_TOKEN
VALID_USER_EMAIL = ADMIN_EMAIL


class TestRootEndpoint:
    """Test root API endpoint"""
    
    def test_root_endpoint_returns_message(self):
        """GET /api/ - root endpoint returns {message: 'nivesh.ai API'}"""
        response = requests.get(f"{BASE_URL}/api/")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert "message" in data, "Response should contain 'message' key"
        assert data["message"] == "nivesh.ai API", f"Expected 'nivesh.ai API', got '{data['message']}'"


class TestAuthRoutes:
    """Test authentication routes from routes/auth.py"""
    
    def test_google_client_id_endpoint(self):
        """GET /api/auth/google-client-id - returns Google client ID"""
        response = requests.get(f"{BASE_URL}/api/auth/google-client-id")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert "client_id" in data, "Response should contain 'client_id' key"
        assert len(data["client_id"]) > 0, "client_id should not be empty"
    
    def test_auth_me_with_valid_session(self):
        """GET /api/auth/me - returns user info with valid session cookie"""
        cookies = {"session_token": VALID_SESSION_TOKEN}
        response = requests.get(f"{BASE_URL}/api/auth/me", cookies=cookies)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert "user_id" in data, "Response should contain 'user_id'"
        assert "email" in data, "Response should contain 'email'"
        assert data["email"] == VALID_USER_EMAIL, f"Expected email '{VALID_USER_EMAIL}', got '{data['email']}'"
    
    def test_auth_me_without_session(self):
        """GET /api/auth/me - returns 401 with no session"""
        response = requests.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    
    def test_auth_me_with_invalid_session(self):
        """GET /api/auth/me - returns 401 with invalid session"""
        cookies = {"session_token": "invalid-session-token-12345"}
        response = requests.get(f"{BASE_URL}/api/auth/me", cookies=cookies)
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    
    def test_auth_me_with_bearer_token(self):
        """GET /api/auth/me - returns user info with Bearer token"""
        headers = {"Authorization": f"Bearer {VALID_SESSION_TOKEN}"}
        response = requests.get(f"{BASE_URL}/api/auth/me", headers=headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["email"] == VALID_USER_EMAIL


class TestAdminRoutes:
    """Test admin routes from routes/admin.py"""
    
    def test_admin_stats_with_admin_session(self):
        """GET /api/admin/stats - returns whitelist stats for admin user"""
        cookies = {"session_token": ADMIN_SESSION_TOKEN}
        response = requests.get(f"{BASE_URL}/api/admin/stats", cookies=cookies)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert "whitelist" in data, "Response should contain 'whitelist' key"
        assert "usage" in data, "Response should contain 'usage' key"
        assert "total" in data["whitelist"], "whitelist should contain 'total'"
        assert "active" in data["whitelist"], "whitelist should contain 'active'"
    
    def test_admin_whitelist_with_admin_session(self):
        """GET /api/admin/whitelist - returns list for admin user"""
        cookies = {"session_token": ADMIN_SESSION_TOKEN}
        response = requests.get(f"{BASE_URL}/api/admin/whitelist", cookies=cookies)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert isinstance(data, list), "Response should be a list"
        # Verify admin email is in whitelist
        emails = [entry.get("email") for entry in data]
        assert ADMIN_EMAIL.lower() in emails, f"Admin email should be in whitelist"
    
    def test_admin_stats_without_auth(self):
        """GET /api/admin/stats - returns 401 without authentication"""
        response = requests.get(f"{BASE_URL}/api/admin/stats")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    
    def test_admin_whitelist_without_auth(self):
        """GET /api/admin/whitelist - returns 401 without authentication"""
        response = requests.get(f"{BASE_URL}/api/admin/whitelist")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"


class TestPortfolioRoutes:
    """Test portfolio routes from routes/portfolio.py"""
    
    def test_portfolio_holdings_authenticated(self):
        """GET /api/portfolio/holdings - returns holdings for authenticated user"""
        cookies = {"session_token": VALID_SESSION_TOKEN}
        response = requests.get(f"{BASE_URL}/api/portfolio/holdings", cookies=cookies)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert isinstance(data, list), "Response should be a list"
    
    def test_portfolio_holdings_unauthenticated(self):
        """GET /api/portfolio/holdings - returns 401 without auth"""
        response = requests.get(f"{BASE_URL}/api/portfolio/holdings")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    
    def test_portfolios_list_authenticated(self):
        """GET /api/portfolios - returns portfolios list"""
        cookies = {"session_token": VALID_SESSION_TOKEN}
        response = requests.get(f"{BASE_URL}/api/portfolios", cookies=cookies)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert isinstance(data, list), "Response should be a list"
    
    def test_portfolios_list_unauthenticated(self):
        """GET /api/portfolios - returns 401 without auth"""
        response = requests.get(f"{BASE_URL}/api/portfolios")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"


class TestUserRoutes:
    """Test user routes from routes/user.py"""
    
    def test_user_profile_authenticated(self):
        """GET /api/user/profile - returns user profile"""
        cookies = {"session_token": VALID_SESSION_TOKEN}
        response = requests.get(f"{BASE_URL}/api/user/profile", cookies=cookies)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert "user_id" in data, "Response should contain 'user_id'"
    
    def test_user_profile_unauthenticated(self):
        """GET /api/user/profile - returns 401 without auth"""
        response = requests.get(f"{BASE_URL}/api/user/profile")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"


class TestChatRoutes:
    """Test chat routes from routes/chat.py"""
    
    def test_chat_sessions_authenticated(self):
        """GET /api/chat/sessions - returns chat sessions"""
        cookies = {"session_token": VALID_SESSION_TOKEN}
        response = requests.get(f"{BASE_URL}/api/chat/sessions", cookies=cookies)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert isinstance(data, list), "Response should be a list"
    
    def test_chat_sessions_unauthenticated(self):
        """GET /api/chat/sessions - returns 401 without auth"""
        response = requests.get(f"{BASE_URL}/api/chat/sessions")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"


class TestInsightsRoutes:
    """Test insights routes from routes/insights.py"""
    
    def test_insights_list_authenticated(self):
        """GET /api/insights - returns insights list"""
        cookies = {"session_token": VALID_SESSION_TOKEN}
        response = requests.get(f"{BASE_URL}/api/insights", cookies=cookies)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert isinstance(data, list), "Response should be a list"
    
    def test_insights_list_unauthenticated(self):
        """GET /api/insights - returns 401 without auth"""
        response = requests.get(f"{BASE_URL}/api/insights")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"


class TestLogoutRoute:
    """Test logout route from routes/auth.py"""
    
    def test_logout_clears_session(self):
        """POST /api/auth/logout - clears session"""
        # Use admin session for logout test (won't actually invalidate it since we're testing the endpoint)
        cookies = {"session_token": VALID_SESSION_TOKEN}
        response = requests.post(f"{BASE_URL}/api/auth/logout", cookies=cookies)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert "message" in data, "Response should contain 'message'"
        assert data["message"] == "Logged out", f"Expected 'Logged out', got '{data['message']}'"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
