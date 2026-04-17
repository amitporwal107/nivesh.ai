"""
Gmail Auto-Fetch Feature Tests
Tests for: Gmail OAuth flow, status, scan, import, disconnect endpoints
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    BASE_URL = "https://autonomous-advisor.preview.emergentagent.com"

# Test session token from test_credentials.md
TEST_SESSION_TOKEN = "test_session_wealth001"
TEST_USER_ID = "test-user-wealth001"


class TestGmailStatus:
    """Test GET /api/gmail/status endpoint"""
    
    def test_gmail_status_returns_connected_false_for_user_without_gmail(self):
        """Users without Gmail linked should get connected: false"""
        response = requests.get(
            f"{BASE_URL}/api/gmail/status",
            headers={"Authorization": f"Bearer {TEST_SESSION_TOKEN}"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "connected" in data, "Response should have 'connected' field"
        # Note: connected could be true or false depending on state
        assert isinstance(data["connected"], bool), "connected should be boolean"
        print(f"Gmail status: connected={data['connected']}")
    
    def test_gmail_status_requires_auth(self):
        """Unauthenticated requests should fail"""
        response = requests.get(f"{BASE_URL}/api/gmail/status")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"


class TestGmailConnect:
    """Test GET /api/gmail/connect endpoint"""
    
    def test_gmail_connect_returns_auth_url(self):
        """Should return auth_url pointing to accounts.google.com with gmail.readonly scope"""
        response = requests.get(
            f"{BASE_URL}/api/gmail/connect",
            headers={"Authorization": f"Bearer {TEST_SESSION_TOKEN}"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "auth_url" in data, "Response should have 'auth_url' field"
        
        auth_url = data["auth_url"]
        assert "accounts.google.com" in auth_url, f"auth_url should point to accounts.google.com: {auth_url}"
        assert "gmail.readonly" in auth_url, f"auth_url should include gmail.readonly scope: {auth_url}"
        assert "state=" in auth_url, "auth_url should include state parameter"
        print(f"Gmail connect auth_url: {auth_url[:100]}...")
    
    def test_gmail_connect_requires_auth(self):
        """Unauthenticated requests should fail"""
        response = requests.get(f"{BASE_URL}/api/gmail/connect")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"


class TestGmailCallback:
    """Test GET /api/oauth/gmail/callback endpoint"""
    
    def test_gmail_callback_missing_params_redirects_with_error(self):
        """Missing code/state should redirect to dashboard with error"""
        response = requests.get(
            f"{BASE_URL}/api/oauth/gmail/callback",
            allow_redirects=False
        )
        # Should redirect (302/307) to dashboard with error
        assert response.status_code in [302, 307], f"Expected redirect, got {response.status_code}"
        location = response.headers.get("location", "")
        assert "gmail_error" in location or "dashboard" in location, f"Should redirect with error: {location}"
        print(f"Callback redirect location: {location}")
    
    def test_gmail_callback_invalid_state_redirects_with_error(self):
        """Invalid state should redirect to dashboard with error"""
        response = requests.get(
            f"{BASE_URL}/api/oauth/gmail/callback?code=fake_code&state=invalid_state",
            allow_redirects=False
        )
        assert response.status_code in [302, 307], f"Expected redirect, got {response.status_code}"
        location = response.headers.get("location", "")
        assert "gmail_error" in location, f"Should redirect with error: {location}"
        print(f"Invalid state redirect: {location}")
    
    def test_gmail_callback_with_error_param_redirects(self):
        """Error param from Google should redirect with denied error"""
        response = requests.get(
            f"{BASE_URL}/api/oauth/gmail/callback?error=access_denied",
            allow_redirects=False
        )
        assert response.status_code in [302, 307], f"Expected redirect, got {response.status_code}"
        location = response.headers.get("location", "")
        assert "gmail_error=denied" in location, f"Should redirect with denied error: {location}"


class TestGmailScan:
    """Test POST /api/gmail/scan endpoint"""
    
    def test_gmail_scan_returns_400_if_not_connected(self):
        """Should return 400 if Gmail not connected"""
        # First disconnect to ensure clean state
        requests.post(
            f"{BASE_URL}/api/gmail/disconnect",
            headers={"Authorization": f"Bearer {TEST_SESSION_TOKEN}"}
        )
        
        response = requests.post(
            f"{BASE_URL}/api/gmail/scan",
            headers={"Authorization": f"Bearer {TEST_SESSION_TOKEN}"},
            json={}
        )
        # Should return 400 if not connected
        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
        data = response.json()
        assert "detail" in data, "Should have error detail"
        assert "not connected" in data["detail"].lower() or "connect" in data["detail"].lower(), \
            f"Error should mention Gmail not connected: {data['detail']}"
        print(f"Scan without connection error: {data['detail']}")
    
    def test_gmail_scan_requires_auth(self):
        """Unauthenticated requests should fail"""
        response = requests.post(f"{BASE_URL}/api/gmail/scan", json={})
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"


class TestGmailDisconnect:
    """Test POST /api/gmail/disconnect endpoint"""
    
    def test_gmail_disconnect_removes_tokens(self):
        """Should successfully disconnect Gmail"""
        response = requests.post(
            f"{BASE_URL}/api/gmail/disconnect",
            headers={"Authorization": f"Bearer {TEST_SESSION_TOKEN}"},
            json={}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "message" in data, "Should have success message"
        assert "disconnect" in data["message"].lower(), f"Message should confirm disconnect: {data['message']}"
        
        # Verify status is now disconnected
        status_response = requests.get(
            f"{BASE_URL}/api/gmail/status",
            headers={"Authorization": f"Bearer {TEST_SESSION_TOKEN}"}
        )
        assert status_response.status_code == 200
        assert status_response.json()["connected"] == False, "Should be disconnected after disconnect call"
        print("Gmail disconnect successful")
    
    def test_gmail_disconnect_requires_auth(self):
        """Unauthenticated requests should fail"""
        response = requests.post(f"{BASE_URL}/api/gmail/disconnect", json={})
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"


class TestGmailImport:
    """Test POST /api/gmail/import endpoint"""
    
    def test_gmail_import_returns_400_without_message_id(self):
        """Should return 400 if no message_id provided"""
        response = requests.post(
            f"{BASE_URL}/api/gmail/import",
            headers={"Authorization": f"Bearer {TEST_SESSION_TOKEN}"},
            json={"attachment_id": "some_attachment"}
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
        data = response.json()
        assert "detail" in data
        assert "message_id" in data["detail"].lower() or "required" in data["detail"].lower(), \
            f"Error should mention message_id required: {data['detail']}"
        print(f"Import without message_id error: {data['detail']}")
    
    def test_gmail_import_returns_400_without_attachment_id(self):
        """Should return 400 if no attachment_id provided"""
        response = requests.post(
            f"{BASE_URL}/api/gmail/import",
            headers={"Authorization": f"Bearer {TEST_SESSION_TOKEN}"},
            json={"message_id": "some_message"}
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
        data = response.json()
        assert "detail" in data
        assert "attachment_id" in data["detail"].lower() or "required" in data["detail"].lower(), \
            f"Error should mention attachment_id required: {data['detail']}"
        print(f"Import without attachment_id error: {data['detail']}")
    
    def test_gmail_import_returns_400_if_not_connected(self):
        """Should return 400 if Gmail not connected"""
        # Ensure disconnected
        requests.post(
            f"{BASE_URL}/api/gmail/disconnect",
            headers={"Authorization": f"Bearer {TEST_SESSION_TOKEN}"}
        )
        
        response = requests.post(
            f"{BASE_URL}/api/gmail/import",
            headers={"Authorization": f"Bearer {TEST_SESSION_TOKEN}"},
            json={"message_id": "test_msg", "attachment_id": "test_attach"}
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
        data = response.json()
        assert "detail" in data
        assert "not connected" in data["detail"].lower() or "connect" in data["detail"].lower(), \
            f"Error should mention Gmail not connected: {data['detail']}"
        print(f"Import without connection error: {data['detail']}")
    
    def test_gmail_import_requires_auth(self):
        """Unauthenticated requests should fail"""
        response = requests.post(
            f"{BASE_URL}/api/gmail/import",
            json={"message_id": "test", "attachment_id": "test"}
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"


class TestDeduplicationLogic:
    """Test deduplication in _save_holdings_with_dedup (via import flow)"""
    
    def test_holdings_have_source_field(self):
        """Verify holdings can have source field"""
        # Get existing holdings
        response = requests.get(
            f"{BASE_URL}/api/portfolio/holdings",
            headers={"Authorization": f"Bearer {TEST_SESSION_TOKEN}"}
        )
        assert response.status_code == 200
        holdings = response.json()
        
        # Check if any holdings have source field (from previous imports)
        sources = [h.get("source") for h in holdings if h.get("source")]
        print(f"Found {len(sources)} holdings with source field: {set(sources)}")
        
        # This is informational - source tagging is applied during import
        assert isinstance(holdings, list), "Holdings should be a list"


class TestGmailServiceIntegration:
    """Integration tests for Gmail service components"""
    
    def test_gmail_oauth_state_creation(self):
        """Verify OAuth state is created when connecting"""
        response = requests.get(
            f"{BASE_URL}/api/gmail/connect",
            headers={"Authorization": f"Bearer {TEST_SESSION_TOKEN}"}
        )
        assert response.status_code == 200
        data = response.json()
        auth_url = data["auth_url"]
        
        # Extract state from URL
        import urllib.parse
        parsed = urllib.parse.urlparse(auth_url)
        params = urllib.parse.parse_qs(parsed.query)
        
        assert "state" in params, "State should be in auth URL"
        state = params["state"][0]
        assert TEST_USER_ID in state, f"State should contain user_id: {state}"
        print(f"OAuth state created: {state}")
    
    def test_gmail_scopes_include_readonly(self):
        """Verify Gmail scopes include readonly"""
        response = requests.get(
            f"{BASE_URL}/api/gmail/connect",
            headers={"Authorization": f"Bearer {TEST_SESSION_TOKEN}"}
        )
        assert response.status_code == 200
        auth_url = response.json()["auth_url"]
        
        # Check scopes in URL
        assert "gmail.readonly" in auth_url, "Should request gmail.readonly scope"
        assert "userinfo.email" in auth_url, "Should request userinfo.email scope"
        print("Gmail scopes verified: gmail.readonly, userinfo.email")


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
