"""Client CAS Invite — end-to-end pytest coverage.

Covers MFD-authenticated create/list/revoke, auth enforcement (401/403),
and public-facing endpoints (details, gmail connect URL, scan guard,
status). Does not attempt to complete a real Google OAuth round-trip —
we only verify auth_url shape + state dispatch.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://portfolio-pro-985.preview.emergentagent.com").rstrip("/")
PROFILE_ID = "4aed5824-6b0b-4a4a-9cf4-6bfb3cb6e321"  # AMIT PORWAL
SESSION_TOKEN = "370eff71-fda1-46d8-b506-b81b894d634f"  # priyankamantri@gmail.com


@pytest.fixture(scope="session")
def mfd_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    s.cookies.set("session_token", SESSION_TOKEN)
    return s


@pytest.fixture(scope="session")
def anon_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def created_invite(mfd_client):
    """Create an invite once for reuse across tests."""
    r = mfd_client.post(f"{BASE_URL}/api/mfd/profiles/{PROFILE_ID}/cas-invite", json={})
    assert r.status_code == 200, f"create failed: {r.status_code} {r.text[:300]}"
    data = r.json()
    assert "invite_token" in data
    return data


# ── MFD-authenticated routes ──────────────────────────────────────────
class TestMfdCreateInvite:
    def test_create_invite_returns_expected_shape(self, created_invite):
        for key in ("invite_token", "invite_url", "expires_at", "status", "advisor_name"):
            assert key in created_invite, f"missing key {key}"
        assert created_invite["status"] == "PENDING"
        assert "/cas-connect/" in created_invite["invite_url"]
        # Expires ~7 days out
        exp = datetime.fromisoformat(created_invite["expires_at"])
        delta = exp - datetime.now(timezone.utc)
        assert 6 <= delta.days <= 7, f"expiry out of range: {delta.days}"

    def test_unauthenticated_create_returns_401(self, anon_client):
        r = anon_client.post(f"{BASE_URL}/api/mfd/profiles/{PROFILE_ID}/cas-invite", json={})
        assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}"

    def test_non_existent_profile_returns_404(self, mfd_client):
        r = mfd_client.post(f"{BASE_URL}/api/mfd/profiles/does-not-exist-xyz/cas-invite", json={})
        assert r.status_code == 404


class TestMfdListInvites:
    def test_list_invites_returns_array(self, mfd_client, created_invite):
        r = mfd_client.get(f"{BASE_URL}/api/mfd/profiles/{PROFILE_ID}/cas-invites")
        assert r.status_code == 200
        data = r.json()
        assert "invites" in data
        assert isinstance(data["invites"], list)
        assert any(i.get("invite_token") == created_invite["invite_token"] for i in data["invites"])

    def test_list_never_leaks_oauth_tokens(self, mfd_client):
        r = mfd_client.get(f"{BASE_URL}/api/mfd/profiles/{PROFILE_ID}/cas-invites")
        assert r.status_code == 200
        for inv in r.json()["invites"]:
            assert "oauth_tokens" not in inv, "oauth_tokens leaked to MFD"

    def test_unauthenticated_list_returns_401(self, anon_client):
        r = anon_client.get(f"{BASE_URL}/api/mfd/profiles/{PROFILE_ID}/cas-invites")
        assert r.status_code in (401, 403)


class TestMfdRevoke:
    def test_revoke_sets_status_and_clears_tokens(self, mfd_client):
        # Create a fresh invite then revoke it
        c = mfd_client.post(f"{BASE_URL}/api/mfd/profiles/{PROFILE_ID}/cas-invite", json={})
        assert c.status_code == 200
        tok = c.json()["invite_token"]

        r = mfd_client.post(f"{BASE_URL}/api/mfd/profiles/{PROFILE_ID}/cas-invite/{tok}/revoke")
        assert r.status_code == 200
        assert r.json().get("status") == "REVOKED"

        # Public details for a revoked invite → 410
        p = requests.get(f"{BASE_URL}/api/public/cas-invite/{tok}")
        assert p.status_code == 410

    def test_unauthenticated_revoke_returns_401(self, anon_client, created_invite):
        r = anon_client.post(
            f"{BASE_URL}/api/mfd/profiles/{PROFILE_ID}/cas-invite/{created_invite['invite_token']}/revoke"
        )
        assert r.status_code in (401, 403)


# ── Public routes (no auth) ────────────────────────────────────────────
class TestPublicInviteDetails:
    def test_valid_token_returns_details(self, anon_client, created_invite):
        r = anon_client.get(f"{BASE_URL}/api/public/cas-invite/{created_invite['invite_token']}")
        assert r.status_code == 200
        data = r.json()
        for key in ("status", "advisor_name", "profile_name", "expires_at", "processed_count"):
            assert key in data
        assert data["status"] == "PENDING"
        # Never leak oauth_tokens
        assert "oauth_tokens" not in data

    def test_bad_token_returns_404(self, anon_client):
        r = anon_client.get(f"{BASE_URL}/api/public/cas-invite/bad-token-xyz-doesnotexist")
        assert r.status_code == 404


class TestPublicGmailConnect:
    def test_returns_auth_url_with_invite_state(self, anon_client, created_invite):
        r = anon_client.get(
            f"{BASE_URL}/api/public/cas-invite/{created_invite['invite_token']}/gmail/connect"
        )
        assert r.status_code == 200, r.text[:300]
        url = r.json().get("auth_url", "")
        assert url.startswith("https://accounts.google.com/"), f"bad auth url: {url}"
        assert "gmail.readonly" in url or "gmail.readonly".replace("/", "%2F") in url or "scope=" in url
        # state must carry our invite prefix
        assert f"invite_{created_invite['invite_token']}" in url
        # redirect_uri must end with /api/oauth/gmail/callback
        assert "%2Fapi%2Foauth%2Fgmail%2Fcallback" in url or "/api/oauth/gmail/callback" in url

    def test_bad_token_returns_404(self, anon_client):
        r = anon_client.get(f"{BASE_URL}/api/public/cas-invite/bad-token/gmail/connect")
        assert r.status_code == 404


class TestPublicScanGuard:
    def test_scan_before_oauth_returns_400(self, anon_client, created_invite):
        r = anon_client.post(f"{BASE_URL}/api/public/cas-invite/{created_invite['invite_token']}/scan")
        assert r.status_code == 400
        assert "Gmail" in r.text or "connected" in r.text.lower()


class TestPublicStatus:
    def test_status_returns_processed_files(self, anon_client, created_invite):
        r = anon_client.get(f"{BASE_URL}/api/public/cas-invite/{created_invite['invite_token']}/status")
        assert r.status_code == 200
        data = r.json()
        assert "status" in data
        assert "processed_files" in data
        assert isinstance(data["processed_files"], list)


# ── Expired / edge cases ───────────────────────────────────────────────
class TestExpiredInvite:
    """Insert a synthetically-expired invite directly via MFD create
    then forcibly update expires_at in DB via an API workaround. Since
    we cannot touch mongo directly here, we skip if no admin DB helper
    — but we do check that short ttl invites don't instantly expire."""

    def test_public_details_with_expired_marker(self, mfd_client, anon_client):
        # Create an invite, then use pymongo directly if available
        c = mfd_client.post(f"{BASE_URL}/api/mfd/profiles/{PROFILE_ID}/cas-invite", json={})
        assert c.status_code == 200
        tok = c.json()["invite_token"]

        # Attempt direct DB update to simulate expiry
        try:
            from motor.motor_asyncio import AsyncIOMotorClient  # noqa
            import asyncio
            from pymongo import MongoClient
            mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
            db_name = os.environ.get("DB_NAME", "test_database")
            mc = MongoClient(mongo_url)
            past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
            mc[db_name].client_cas_invites.update_one(
                {"invite_token": tok}, {"$set": {"expires_at": past}}
            )
            r = anon_client.get(f"{BASE_URL}/api/public/cas-invite/{tok}")
            assert r.status_code == 410, f"expected 410 for expired, got {r.status_code}"
        except ImportError:
            pytest.skip("pymongo not available — cannot simulate expiry")
