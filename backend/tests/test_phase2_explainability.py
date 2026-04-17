"""
Test Phase 2 UX Enhancements - Explainability and Drillable Insights
Tests for:
1. Portfolio Health explainability (gauge data)
2. Risk Assessment explainability (risk_gauge data)
3. Actionable Insights with affected holdings (performance_cards)
4. Issue Breakdown chart data (problem_distribution)
5. Chat streaming endpoint (no regression)
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
TEST_SESSION = "5770bebb-8a9a-41f7-a7b9-e8152ac25daa"


@pytest.fixture
def auth_cookies():
    """Return auth cookies for test user"""
    return {"session_token": TEST_SESSION}


class TestInsightsAnalysisAPI:
    """Test /api/insights/analysis endpoint for explainability data"""
    
    def test_analysis_returns_risk_gauge(self, auth_cookies):
        """Test that analysis returns risk_gauge data for health/risk explainability"""
        response = requests.get(
            f"{BASE_URL}/api/insights/analysis",
            cookies=auth_cookies
        )
        assert response.status_code == 200
        data = response.json()
        
        # Check risk_gauge exists and has required fields
        assert "risk_gauge" in data, "risk_gauge missing from analysis response"
        gauge = data["risk_gauge"]
        assert "current" in gauge, "current missing from risk_gauge"
        assert "target" in gauge, "target missing from risk_gauge"
        assert "current_label" in gauge, "current_label missing from risk_gauge"
        assert "target_label" in gauge, "target_label missing from risk_gauge"
        
        # Validate values
        assert isinstance(gauge["current"], (int, float))
        assert isinstance(gauge["target"], (int, float))
        assert gauge["current"] >= 0 and gauge["current"] <= 100
        assert gauge["target"] >= 0 and gauge["target"] <= 100
        print(f"Risk gauge: {gauge['current']}/{gauge['current_label']} -> {gauge['target']}/{gauge['target_label']}")
    
    def test_analysis_returns_problem_distribution(self, auth_cookies):
        """Test that analysis returns problem_distribution for Issue Breakdown chart"""
        response = requests.get(
            f"{BASE_URL}/api/insights/analysis",
            cookies=auth_cookies
        )
        assert response.status_code == 200
        data = response.json()
        
        # Check problem_distribution exists
        assert "problem_distribution" in data, "problem_distribution missing from analysis response"
        pd = data["problem_distribution"]
        assert isinstance(pd, list)
        assert len(pd) > 0, "problem_distribution is empty"
        
        # Check each item has required fields
        for item in pd:
            assert "name" in item, "name missing from problem_distribution item"
            assert "value" in item, "value missing from problem_distribution item"
            assert "color" in item, "color missing from problem_distribution item"
        
        print(f"Problem distribution: {[p['name'] + ':' + str(p['value']) + '%' for p in pd]}")
    
    def test_analysis_returns_insights(self, auth_cookies):
        """Test that analysis returns insights for Actionable Insights section"""
        response = requests.get(
            f"{BASE_URL}/api/insights/analysis",
            cookies=auth_cookies
        )
        assert response.status_code == 200
        data = response.json()
        
        # Check insights exists
        assert "insights" in data, "insights missing from analysis response"
        insights = data["insights"]
        assert isinstance(insights, list)
        assert len(insights) > 0, "insights is empty"
        
        # Check each insight has required fields
        for insight in insights:
            assert "title" in insight, "title missing from insight"
        
        print(f"Insights count: {len(insights)}")
        print(f"Insight titles: {[i['title'] for i in insights]}")
    
    def test_analysis_returns_before_after(self, auth_cookies):
        """Test that analysis returns before_after for Impact section"""
        response = requests.get(
            f"{BASE_URL}/api/insights/analysis",
            cookies=auth_cookies
        )
        assert response.status_code == 200
        data = response.json()
        
        # Check before_after exists
        assert "before_after" in data, "before_after missing from analysis response"
        ba = data["before_after"]
        assert "before" in ba, "before missing from before_after"
        assert "after" in ba, "after missing from before_after"
        
        print(f"Before: {ba['before']}")
        print(f"After: {ba['after']}")
    
    def test_analysis_returns_do_nothing_scenario(self, auth_cookies):
        """Test that analysis returns do_nothing_scenario"""
        response = requests.get(
            f"{BASE_URL}/api/insights/analysis",
            cookies=auth_cookies
        )
        assert response.status_code == 200
        data = response.json()
        
        # Check do_nothing_scenario exists
        assert "do_nothing_scenario" in data, "do_nothing_scenario missing from analysis response"
        dn = data["do_nothing_scenario"]
        assert "headline" in dn or "annual_cost_leak" in dn, "do_nothing_scenario missing key fields"
        
        print(f"Do nothing scenario: {dn}")


class TestDeepAnalyticsAPI:
    """Test /api/portfolio/deep-analytics endpoint for affected holdings data"""
    
    def test_deep_analytics_returns_performance_cards(self, auth_cookies):
        """Test that deep-analytics returns performance_cards for affected holdings"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/deep-analytics",
            cookies=auth_cookies
        )
        assert response.status_code == 200
        data = response.json()
        
        # Check performance_cards exists
        assert "performance_cards" in data, "performance_cards missing from deep-analytics response"
        cards = data["performance_cards"]
        assert isinstance(cards, list)
        assert len(cards) > 0, "performance_cards is empty"
        
        # Check each card has required fields for affected holdings display
        for card in cards[:5]:  # Check first 5
            assert "name" in card, "name missing from performance_card"
            assert "pct_return" in card, "pct_return missing from performance_card"
            assert "current_value" in card, "current_value missing from performance_card"
        
        print(f"Performance cards count: {len(cards)}")
        print(f"Sample card: {cards[0]}")
    
    def test_deep_analytics_returns_overexposure(self, auth_cookies):
        """Test that deep-analytics returns overexposure data for risk drivers"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/deep-analytics",
            cookies=auth_cookies
        )
        assert response.status_code == 200
        data = response.json()
        
        # Check overexposure exists
        assert "overexposure" in data, "overexposure missing from deep-analytics response"
        oe = data["overexposure"]
        
        # Check for fund_house and sector data
        if "fund_house" in oe:
            print(f"Fund house overexposure: {len(oe['fund_house'])} items")
        if "sector" in oe:
            print(f"Sector overexposure: {len(oe['sector'])} items")


class TestChatStreamingAPI:
    """Test /api/chat/stream endpoint (no regression)"""
    
    def test_chat_stream_returns_sse_events(self, auth_cookies):
        """Test that chat/stream returns SSE events with meta, token, done types"""
        response = requests.post(
            f"{BASE_URL}/api/chat/stream",
            json={"message": "Hello"},
            cookies=auth_cookies,
            stream=True,
            timeout=30
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        
        # Read first few events
        events_received = {"meta": False, "token": False, "done": False}
        for line in response.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                import json
                try:
                    data = json.loads(line[6:])
                    event_type = data.get("type")
                    if event_type in events_received:
                        events_received[event_type] = True
                        print(f"Received {event_type} event")
                    if event_type == "done":
                        break
                except:
                    pass
        
        assert events_received["meta"], "meta event not received"
        print(f"Events received: {events_received}")
    
    def test_chat_send_returns_messages(self, auth_cookies):
        """Test that chat/send (batch) returns user_message and ai_message"""
        response = requests.post(
            f"{BASE_URL}/api/chat/send",
            json={"message": "What is my portfolio value?"},
            cookies=auth_cookies,
            timeout=60
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "user_message" in data, "user_message missing from response"
        assert "ai_message" in data, "ai_message missing from response"
        
        print(f"User message ID: {data['user_message'].get('message_id')}")
        print(f"AI message ID: {data['ai_message'].get('message_id')}")


class TestAuthAPI:
    """Test auth endpoints (no regression)"""
    
    def test_auth_me_returns_user(self, auth_cookies):
        """Test that /api/auth/me returns user info"""
        response = requests.get(
            f"{BASE_URL}/api/auth/me",
            cookies=auth_cookies
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "user_id" in data
        assert "email" in data
        print(f"User: {data['email']}")
    
    def test_auth_me_returns_401_without_session(self):
        """Test that /api/auth/me returns 401 without session"""
        response = requests.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code == 401


class TestPortfolioAPI:
    """Test portfolio endpoints (no regression)"""
    
    def test_holdings_returns_data(self, auth_cookies):
        """Test that /api/portfolio/holdings returns holdings"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/holdings",
            cookies=auth_cookies
        )
        assert response.status_code == 200
        data = response.json()
        
        assert isinstance(data, list)
        assert len(data) > 0, "No holdings returned"
        print(f"Holdings count: {len(data)}")
    
    def test_analytics_returns_data(self, auth_cookies):
        """Test that /api/portfolio/analytics returns analytics"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/analytics",
            cookies=auth_cookies
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "total_invested" in data or "summary" in data
        print(f"Analytics keys: {list(data.keys())}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
