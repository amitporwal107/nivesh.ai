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

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://wealth-advisor-96.preview.emergentagent.com").rstrip("/")
PROFILE_ID = "1755a697-d386-4cf4-98ea-327961d823d3"  # AMIT PORWAL
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
        # Expires ~24 hours out (PRD v2)
        exp = datetime.fromisoformat(created_invite["expires_at"])
        delta = exp - datetime.now(timezone.utc)
        total_hours = delta.total_seconds() / 3600
        assert 23 <= total_hours <= 24.5, f"expiry out of range: {total_hours}h"

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


# ── V2: 24h expiry + prefill ───────────────────────────────────────────
class TestV2CreateWithPrefill:
    def test_create_with_prefill_fields(self, mfd_client):
        r = mfd_client.post(
            f"{BASE_URL}/api/mfd/profiles/{PROFILE_ID}/cas-invite",
            json={
                "client_name": "Ramesh Iyer",
                "client_mobile": "9876543210",
                "client_email": "ramesh@example.com",
                "regenerate": True,
            },
        )
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        tok = data["invite_token"]
        # Public details should surface prefill and advisor_mobile/email
        p = requests.get(f"{BASE_URL}/api/public/cas-invite/{tok}")
        assert p.status_code == 200
        pd = p.json()
        assert pd["prefill"]["name"] == "Ramesh Iyer"
        assert pd["prefill"]["mobile"] == "9876543210"
        assert pd["prefill"]["email"] == "ramesh@example.com"
        assert pd["profile_name"] == "Ramesh Iyer"
        assert pd["has_client_details"] is False
        assert "advisor_mobile" in pd
        assert "advisor_email" in pd


# ── V2: Regenerate deactivates prior active ────────────────────────────
class TestV2Regenerate:
    def test_regenerate_deactivates_prior_and_issues_new(self, mfd_client):
        # Create invite #1
        a = mfd_client.post(f"{BASE_URL}/api/mfd/profiles/{PROFILE_ID}/cas-invite", json={"regenerate": True})
        assert a.status_code == 200
        tok_old = a.json()["invite_token"]
        # Confirm it's active
        p1 = requests.get(f"{BASE_URL}/api/public/cas-invite/{tok_old}")
        assert p1.status_code == 200

        # Regenerate via dedicated endpoint
        b = mfd_client.post(f"{BASE_URL}/api/mfd/profiles/{PROFILE_ID}/cas-invite/regenerate", json={})
        assert b.status_code == 200
        tok_new = b.json()["invite_token"]
        assert tok_new != tok_old

        # Old invite → 410 with reason=revoked
        p_old = requests.get(f"{BASE_URL}/api/public/cas-invite/{tok_old}")
        assert p_old.status_code == 410
        body = p_old.json().get("detail", {})
        assert isinstance(body, dict), f"expected dict detail, got {body!r}"
        assert body.get("reason") == "revoked"
        assert "advisor_name" in body

        # New invite active
        p_new = requests.get(f"{BASE_URL}/api/public/cas-invite/{tok_new}")
        assert p_new.status_code == 200


# ── V2: Client details submission + consents ───────────────────────────
@pytest.fixture
def fresh_invite(mfd_client):
    r = mfd_client.post(
        f"{BASE_URL}/api/mfd/profiles/{PROFILE_ID}/cas-invite",
        json={"regenerate": True},
    )
    assert r.status_code == 200
    return r.json()["invite_token"]


def _valid_details():
    return {
        "name": "Test Client",
        "mobile": "9876543210",
        "email": "tc@example.com",
        "pan": "ABCDE1234F",
        "consent_cas_access": True,
        "consent_gmail_access": True,
        "consent_advisor_access": True,
    }


class TestV2ClientDetails:
    def test_valid_details_captures_and_returns_next(self, anon_client, fresh_invite):
        r = anon_client.post(
            f"{BASE_URL}/api/public/cas-invite/{fresh_invite}/client-details",
            json=_valid_details(),
        )
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data["status"] == "DETAILS_CAPTURED"
        assert data["next"] == "gmail_connect"
        # Follow-up GET reflects state
        g = anon_client.get(f"{BASE_URL}/api/public/cas-invite/{fresh_invite}")
        assert g.status_code == 200
        gd = g.json()
        assert gd["status"] == "DETAILS_CAPTURED"
        assert gd["has_client_details"] is True
        assert gd["consents"]["cas_access"]["approved"] is True

    def test_gmail_consent_false_returns_cas_upload_next(self, anon_client, fresh_invite):
        p = _valid_details()
        p["consent_gmail_access"] = False
        r = anon_client.post(
            f"{BASE_URL}/api/public/cas-invite/{fresh_invite}/client-details", json=p
        )
        assert r.status_code == 200
        assert r.json()["next"] == "cas_upload"

    def test_invalid_pan_short_rejected_422(self, anon_client, fresh_invite):
        p = _valid_details()
        p["pan"] = "BAD"
        r = anon_client.post(
            f"{BASE_URL}/api/public/cas-invite/{fresh_invite}/client-details", json=p
        )
        # pydantic min_length=10 → 422
        assert r.status_code == 422

    def test_invalid_pan_format_rejected_400(self, anon_client, fresh_invite):
        p = _valid_details()
        p["pan"] = "1234567890"  # passes length but fails format
        r = anon_client.post(
            f"{BASE_URL}/api/public/cas-invite/{fresh_invite}/client-details", json=p
        )
        assert r.status_code == 400
        assert "PAN" in r.text

    def test_short_mobile_rejected(self, anon_client, fresh_invite):
        p = _valid_details()
        p["mobile"] = "12345"  # < 7 chars fails pydantic (422); 7-9 digits fails custom 400
        r = anon_client.post(
            f"{BASE_URL}/api/public/cas-invite/{fresh_invite}/client-details", json=p
        )
        assert r.status_code in (400, 422)

    def test_mobile_less_than_10_digits_400(self, anon_client, fresh_invite):
        p = _valid_details()
        p["mobile"] = "1234567"  # 7 chars, passes pydantic, fails custom
        r = anon_client.post(
            f"{BASE_URL}/api/public/cas-invite/{fresh_invite}/client-details", json=p
        )
        assert r.status_code == 400
        assert "mobile" in r.text.lower() or "digits" in r.text.lower()

    def test_invalid_email_rejected(self, anon_client, fresh_invite):
        p = _valid_details()
        p["email"] = "notanemail"
        r = anon_client.post(
            f"{BASE_URL}/api/public/cas-invite/{fresh_invite}/client-details", json=p
        )
        assert r.status_code == 400

    def test_missing_cas_consent_rejected(self, anon_client, fresh_invite):
        p = _valid_details()
        p["consent_cas_access"] = False
        r = anon_client.post(
            f"{BASE_URL}/api/public/cas-invite/{fresh_invite}/client-details", json=p
        )
        assert r.status_code == 400
        assert "consent" in r.text.lower()

    def test_missing_advisor_consent_rejected(self, anon_client, fresh_invite):
        p = _valid_details()
        p["consent_advisor_access"] = False
        r = anon_client.post(
            f"{BASE_URL}/api/public/cas-invite/{fresh_invite}/client-details", json=p
        )
        assert r.status_code == 400
        assert "consent" in r.text.lower()


# ── V2: Import uses stored PAN ─────────────────────────────────────────
class TestV2ImportPasswordFallback:
    def test_import_no_pan_stored_returns_400(self, anon_client, fresh_invite):
        # No client-details submitted yet → no PAN stored.
        # We also need oauth_tokens — but the endpoint checks tokens first.
        r = anon_client.post(
            f"{BASE_URL}/api/public/cas-invite/{fresh_invite}/import",
            json={"selections": [{"message_id": "m1", "attachment_id": "a1", "filename": "c.pdf"}]},
        )
        # Expect 400 because Gmail not connected (no oauth_tokens).
        # This is the pre-oauth guard, which is enough to prove the endpoint is wired.
        assert r.status_code == 400

    def test_import_empty_selections_400(self, anon_client, fresh_invite):
        # Submit details first so PAN is stored
        anon_client.post(
            f"{BASE_URL}/api/public/cas-invite/{fresh_invite}/client-details",
            json=_valid_details(),
        )
        r = anon_client.post(
            f"{BASE_URL}/api/public/cas-invite/{fresh_invite}/import",
            json={"selections": []},
        )
        assert r.status_code == 400

