"""
Test suite for Onboarding Flow - Iteration 16
Tests: POST /api/user/journey, POST /api/user/quick-setup, POST /api/user/complete-onboarding, GET /api/user/profile
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
SESSION_TOKEN = "hkaz5rKJX05a-ky0p-fnncyta-MabtLwVwglXQ_PvA0"
USER_ID = "user_0b63665e3e03"


@pytest.fixture(scope="module")
def api_client():
    """Shared requests session with auth"""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {SESSION_TOKEN}"
    })
    return session


@pytest.fixture(scope="module", autouse=True)
def reset_user_profile():
    """Reset user profile before tests"""
    from motor.motor_asyncio import AsyncIOMotorClient
    import asyncio
    
    async def reset():
        client = AsyncIOMotorClient('mongodb://localhost:27017')
        db = client['test_database']
        await db.user_profiles.update_one(
            {'user_id': USER_ID},
            {'$set': {
                'journey_type': None,
                'onboarding_completed': False,
                'quick_setup': None,
                'starter_plan': None,
                'risk_profile': None
            }}
        )
        client.close()
    
    asyncio.run(reset())
    yield
    # Cleanup after tests - reset again
    asyncio.run(reset())


class TestUserProfile:
    """Tests for GET /api/user/profile endpoint"""
    
    def test_get_profile_returns_initial_state(self, api_client):
        """Profile should return journey_type=null, onboarding_completed=false initially"""
        response = api_client.get(f"{BASE_URL}/api/user/profile")
        assert response.status_code == 200
        
        data = response.json()
        assert "user_id" in data
        assert data["user_id"] == USER_ID
        assert data.get("journey_type") is None
        assert data.get("onboarding_completed") == False
        print(f"✓ Profile initial state: journey_type=None, onboarding_completed=False")


class TestJourneySelection:
    """Tests for POST /api/user/journey endpoint"""
    
    def test_set_journey_new_investor(self, api_client):
        """Should set journey_type to new_investor"""
        response = api_client.post(
            f"{BASE_URL}/api/user/journey",
            json={"journey_type": "new_investor"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["journey_type"] == "new_investor"
        assert data.get("onboarding_completed") == False
        print(f"✓ Journey set to new_investor")
    
    def test_set_journey_existing_investor(self, api_client):
        """Should set journey_type to existing_investor"""
        response = api_client.post(
            f"{BASE_URL}/api/user/journey",
            json={"journey_type": "existing_investor"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["journey_type"] == "existing_investor"
        print(f"✓ Journey set to existing_investor")
    
    def test_set_journey_invalid_type(self, api_client):
        """Should reject invalid journey_type"""
        response = api_client.post(
            f"{BASE_URL}/api/user/journey",
            json={"journey_type": "invalid_type"}
        )
        assert response.status_code == 422  # Validation error
        print(f"✓ Invalid journey_type rejected with 422")
    
    def test_journey_persists_in_profile(self, api_client):
        """Journey type should persist in profile"""
        # Set journey
        api_client.post(f"{BASE_URL}/api/user/journey", json={"journey_type": "new_investor"})
        
        # Verify in profile
        response = api_client.get(f"{BASE_URL}/api/user/profile")
        assert response.status_code == 200
        assert response.json()["journey_type"] == "new_investor"
        print(f"✓ Journey type persisted in profile")


class TestQuickSetup:
    """Tests for POST /api/user/quick-setup endpoint (New Investor flow)"""
    
    def test_quick_setup_valid_input(self, api_client):
        """Should accept valid quick setup input and return starter plan"""
        payload = {
            "age": 28,
            "goal": "retirement",
            "risk_appetite": "moderate",
            "investment_horizon": "long",
            "monthly_investment": 10000
        }
        response = api_client.post(f"{BASE_URL}/api/user/quick-setup", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        
        # Verify quick_setup is returned
        assert "quick_setup" in data
        qs = data["quick_setup"]
        assert qs["age"] == 28
        assert qs["goal"] == "retirement"
        assert qs["risk_appetite"] == "moderate"
        assert qs["investment_horizon"] == "long"
        assert qs["monthly_investment"] == 10000
        
        # Verify starter_plan is returned
        assert "starter_plan" in data
        sp = data["starter_plan"]
        
        # Check allocation
        assert "allocation" in sp
        alloc = sp["allocation"]
        assert "equity" in alloc
        assert "debt" in alloc
        assert "gold" in alloc
        assert "cash" in alloc
        assert sum(alloc.values()) == 100  # Should sum to 100%
        
        # Check fund recommendations
        assert "fund_recommendations" in sp
        assert len(sp["fund_recommendations"]) > 0
        for rec in sp["fund_recommendations"]:
            assert "category" in rec
            assert "allocation_pct" in rec
            assert "rationale" in rec
        
        # Check projection (since monthly_investment provided)
        assert "projection" in sp
        proj = sp["projection"]
        assert proj["monthly_sip"] == 10000
        assert proj["years"] == 10  # long horizon = 10 years
        assert proj["total_invested"] == 10000 * 12 * 10  # 1,200,000
        assert proj["projected_value"] > proj["total_invested"]  # Should grow
        
        # Check insights
        assert "insights" in sp
        assert len(sp["insights"]) >= 2
        
        print(f"✓ Quick setup returned valid starter plan with allocation: {alloc}")
    
    def test_quick_setup_without_monthly_investment(self, api_client):
        """Should work without monthly_investment (optional field)"""
        payload = {
            "age": 35,
            "goal": "house",
            "risk_appetite": "conservative",
            "investment_horizon": "medium",
            "monthly_investment": None
        }
        response = api_client.post(f"{BASE_URL}/api/user/quick-setup", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        assert "starter_plan" in data
        # Projection should be None when no monthly_investment
        assert data["starter_plan"]["projection"] is None
        print(f"✓ Quick setup works without monthly_investment")
    
    def test_quick_setup_all_goals(self, api_client):
        """Should accept all valid goal types"""
        goals = ["retirement", "house", "education", "travel", "wealth", "emergency"]
        for goal in goals:
            payload = {
                "age": 30,
                "goal": goal,
                "risk_appetite": "moderate",
                "investment_horizon": "medium"
            }
            response = api_client.post(f"{BASE_URL}/api/user/quick-setup", json=payload)
            assert response.status_code == 200, f"Goal '{goal}' should be accepted"
        print(f"✓ All 6 goals accepted: {goals}")
    
    def test_quick_setup_all_risk_appetites(self, api_client):
        """Should accept all valid risk appetite levels"""
        risk_levels = ["conservative", "moderate", "aggressive"]
        for risk in risk_levels:
            payload = {
                "age": 30,
                "goal": "wealth",
                "risk_appetite": risk,
                "investment_horizon": "medium"
            }
            response = api_client.post(f"{BASE_URL}/api/user/quick-setup", json=payload)
            assert response.status_code == 200, f"Risk '{risk}' should be accepted"
            
            # Verify allocation changes based on risk
            alloc = response.json()["starter_plan"]["allocation"]
            if risk == "aggressive":
                assert alloc["equity"] >= 60  # Higher equity for aggressive
            elif risk == "conservative":
                assert alloc["equity"] <= 50  # Lower equity for conservative
        print(f"✓ All 3 risk appetites accepted: {risk_levels}")
    
    def test_quick_setup_all_horizons(self, api_client):
        """Should accept all valid investment horizons"""
        horizons = ["short", "medium", "long", "very_long"]
        for horizon in horizons:
            payload = {
                "age": 30,
                "goal": "wealth",
                "risk_appetite": "moderate",
                "investment_horizon": horizon
            }
            response = api_client.post(f"{BASE_URL}/api/user/quick-setup", json=payload)
            assert response.status_code == 200, f"Horizon '{horizon}' should be accepted"
        print(f"✓ All 4 horizons accepted: {horizons}")
    
    def test_quick_setup_age_validation(self, api_client):
        """Should validate age range (18-100)"""
        # Age too low
        response = api_client.post(f"{BASE_URL}/api/user/quick-setup", json={
            "age": 17, "goal": "wealth", "risk_appetite": "moderate", "investment_horizon": "medium"
        })
        assert response.status_code == 422
        
        # Age too high
        response = api_client.post(f"{BASE_URL}/api/user/quick-setup", json={
            "age": 101, "goal": "wealth", "risk_appetite": "moderate", "investment_horizon": "medium"
        })
        assert response.status_code == 422
        
        # Valid edge cases
        for age in [18, 100]:
            response = api_client.post(f"{BASE_URL}/api/user/quick-setup", json={
                "age": age, "goal": "wealth", "risk_appetite": "moderate", "investment_horizon": "medium"
            })
            assert response.status_code == 200, f"Age {age} should be valid"
        print(f"✓ Age validation works (18-100)")
    
    def test_quick_setup_invalid_goal(self, api_client):
        """Should reject invalid goal"""
        response = api_client.post(f"{BASE_URL}/api/user/quick-setup", json={
            "age": 30, "goal": "invalid_goal", "risk_appetite": "moderate", "investment_horizon": "medium"
        })
        assert response.status_code == 422
        print(f"✓ Invalid goal rejected")
    
    def test_quick_setup_persists_in_profile(self, api_client):
        """Quick setup should persist in user profile"""
        payload = {
            "age": 32,
            "goal": "education",
            "risk_appetite": "aggressive",
            "investment_horizon": "very_long",
            "monthly_investment": 25000
        }
        api_client.post(f"{BASE_URL}/api/user/quick-setup", json=payload)
        
        # Verify in profile
        response = api_client.get(f"{BASE_URL}/api/user/profile")
        assert response.status_code == 200
        
        profile = response.json()
        assert profile.get("quick_setup") is not None
        assert profile["quick_setup"]["age"] == 32
        assert profile["quick_setup"]["goal"] == "education"
        
        assert profile.get("starter_plan") is not None
        assert "allocation" in profile["starter_plan"]
        print(f"✓ Quick setup and starter plan persisted in profile")


class TestCompleteOnboarding:
    """Tests for POST /api/user/complete-onboarding endpoint"""
    
    def test_complete_onboarding(self, api_client):
        """Should mark onboarding as completed"""
        response = api_client.post(f"{BASE_URL}/api/user/complete-onboarding", json={})
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("status") == "ok"
        assert data.get("onboarding_completed") == True
        print(f"✓ Onboarding marked as completed")
    
    def test_onboarding_completed_persists(self, api_client):
        """Onboarding completion should persist in profile"""
        api_client.post(f"{BASE_URL}/api/user/complete-onboarding", json={})
        
        response = api_client.get(f"{BASE_URL}/api/user/profile")
        assert response.status_code == 200
        assert response.json()["onboarding_completed"] == True
        print(f"✓ Onboarding completion persisted in profile")


class TestFullNewInvestorFlow:
    """End-to-end test for new investor onboarding flow"""
    
    def test_complete_new_investor_flow(self, api_client):
        """Test complete new investor flow: journey -> quick-setup -> complete"""
        # Reset first
        from motor.motor_asyncio import AsyncIOMotorClient
        import asyncio
        
        async def reset():
            client = AsyncIOMotorClient('mongodb://localhost:27017')
            db = client['test_database']
            await db.user_profiles.update_one(
                {'user_id': USER_ID},
                {'$set': {
                    'journey_type': None,
                    'onboarding_completed': False,
                    'quick_setup': None,
                    'starter_plan': None
                }}
            )
            client.close()
        asyncio.run(reset())
        
        # Step 1: Set journey type
        r1 = api_client.post(f"{BASE_URL}/api/user/journey", json={"journey_type": "new_investor"})
        assert r1.status_code == 200
        assert r1.json()["journey_type"] == "new_investor"
        print("  Step 1: Journey set to new_investor ✓")
        
        # Step 2: Quick setup
        r2 = api_client.post(f"{BASE_URL}/api/user/quick-setup", json={
            "age": 28,
            "goal": "retirement",
            "risk_appetite": "moderate",
            "investment_horizon": "long",
            "monthly_investment": 15000
        })
        assert r2.status_code == 200
        assert "starter_plan" in r2.json()
        print("  Step 2: Quick setup completed with starter plan ✓")
        
        # Step 3: Complete onboarding
        r3 = api_client.post(f"{BASE_URL}/api/user/complete-onboarding", json={})
        assert r3.status_code == 200
        assert r3.json()["onboarding_completed"] == True
        print("  Step 3: Onboarding completed ✓")
        
        # Verify final profile state
        r4 = api_client.get(f"{BASE_URL}/api/user/profile")
        assert r4.status_code == 200
        profile = r4.json()
        assert profile["journey_type"] == "new_investor"
        assert profile["onboarding_completed"] == True
        assert profile["quick_setup"] is not None
        assert profile["starter_plan"] is not None
        print("  Final profile verified ✓")
        print(f"✓ Complete new investor flow successful")


class TestFullExistingInvestorFlow:
    """End-to-end test for existing investor onboarding flow"""
    
    def test_complete_existing_investor_flow(self, api_client):
        """Test complete existing investor flow: journey -> complete (skip upload)"""
        # Reset first
        from motor.motor_asyncio import AsyncIOMotorClient
        import asyncio
        
        async def reset():
            client = AsyncIOMotorClient('mongodb://localhost:27017')
            db = client['test_database']
            await db.user_profiles.update_one(
                {'user_id': USER_ID},
                {'$set': {
                    'journey_type': None,
                    'onboarding_completed': False,
                    'quick_setup': None,
                    'starter_plan': None
                }}
            )
            client.close()
        asyncio.run(reset())
        
        # Step 1: Set journey type
        r1 = api_client.post(f"{BASE_URL}/api/user/journey", json={"journey_type": "existing_investor"})
        assert r1.status_code == 200
        assert r1.json()["journey_type"] == "existing_investor"
        print("  Step 1: Journey set to existing_investor ✓")
        
        # Step 2: Complete onboarding (skip upload for now)
        r2 = api_client.post(f"{BASE_URL}/api/user/complete-onboarding", json={})
        assert r2.status_code == 200
        assert r2.json()["onboarding_completed"] == True
        print("  Step 2: Onboarding completed (skipped upload) ✓")
        
        # Verify final profile state
        r3 = api_client.get(f"{BASE_URL}/api/user/profile")
        assert r3.status_code == 200
        profile = r3.json()
        assert profile["journey_type"] == "existing_investor"
        assert profile["onboarding_completed"] == True
        # quick_setup and starter_plan should be None for existing investor
        print("  Final profile verified ✓")
        print(f"✓ Complete existing investor flow successful")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
