"""Tests for the 3rd CAS parser provider 'nivesh_cas_parser' (Doc AI)."""
import json
import os
import sys
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://nidp-backfill-ui.preview.emergentagent.com").rstrip("/")
ADMIN_TOKEN = "3352751a-cc8a-4bcb-bf50-81a377c6b40b"  # aporwal107@gmail.com

# Make backend modules importable
sys.path.insert(0, "/app/backend")


@pytest.fixture
def admin_client():
    s = requests.Session()
    s.cookies.set("session_token", ADMIN_TOKEN)
    s.headers.update({"Content-Type": "application/json"})
    return s


# ── Admin endpoint: GET cas-parser-provider ───────────────────────────
class TestCasProviderEndpoint:
    def test_get_returns_nivesh_configured_field(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/cas-parser-provider")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "provider" in data
        assert "nivesh_cas_parser_configured" in data
        assert "casparser_api_configured" in data
        assert "claude_vision_configured" in data
        # Per request — should be True in preview env
        assert data["nivesh_cas_parser_configured"] is True, (
            f"Expected nivesh configured True, got: {data}"
        )

    def test_put_set_nivesh_persists(self, admin_client):
        r = admin_client.put(
            f"{BASE_URL}/api/admin/cas-parser-provider",
            json={"provider": "nivesh_cas_parser"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data == {"ok": True, "provider": "nivesh_cas_parser"}
        # Verify persistence via GET
        g = admin_client.get(f"{BASE_URL}/api/admin/cas-parser-provider")
        assert g.json()["provider"] == "nivesh_cas_parser"

    def test_put_invalid_provider(self, admin_client):
        r = admin_client.put(
            f"{BASE_URL}/api/admin/cas-parser-provider",
            json={"provider": "invalid"},
        )
        # Endpoint returns 200 with ok:false
        assert r.status_code == 200
        body = r.json()
        assert body.get("ok") is False
        assert "error" in body

    def test_put_switch_back_to_casparser_api(self, admin_client):
        r = admin_client.put(
            f"{BASE_URL}/api/admin/cas-parser-provider",
            json={"provider": "casparser_api"},
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True, "provider": "casparser_api"}
        g = admin_client.get(f"{BASE_URL}/api/admin/cas-parser-provider")
        assert g.json()["provider"] == "casparser_api"

    def test_authenticated_active_endpoint(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/cas-parser-provider/active")
        assert r.status_code == 200
        body = r.json()
        assert "provider" in body
        # Must NOT leak admin-only configured flags
        assert "casparser_api_configured" not in body
        assert "nivesh_cas_parser_configured" not in body


# ── Secrets API: 4 new GOOGLE_DOCAI_* keys present ────────────────────
class TestNiveshSecretsListed:
    def test_admin_secrets_lists_four_docai_keys(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/secrets?env=preview")
        assert r.status_code == 200, r.text
        items = r.json()["secrets"]
        keys = {it["key"]: it for it in items}
        for expected in [
            "GOOGLE_DOCAI_CREDENTIALS_JSON",
            "GOOGLE_DOCAI_PROJECT",
            "GOOGLE_DOCAI_PROCESSOR",
            "GOOGLE_DOCAI_LOCATION",
        ]:
            assert expected in keys, f"Missing {expected} in secrets list"
            assert keys[expected]["category"] == "parsing"
            assert keys[expected]["configured"] is True, (
                f"Expected {expected} configured in preview env"
            )


# ── Module-level: services.nivesh_cas_parser.is_configured() ──────────
class TestNiveshParserModule:
    def test_is_configured_true_when_secrets_set(self):
        import asyncio
        from services import nivesh_cas_parser as ncp
        from helpers import secrets as sec
        from deps import db

        # Hydrate secrets cache from DB (since pytest doesn't trigger app startup)
        asyncio.get_event_loop().run_until_complete(sec.hydrate_from_db(db))
        assert sec.get("GOOGLE_DOCAI_PROJECT"), "Project secret missing in cache"
        assert sec.get("GOOGLE_DOCAI_PROCESSOR"), "Processor secret missing"
        assert sec.get("GOOGLE_DOCAI_CREDENTIALS_JSON"), "Creds JSON missing"
        assert ncp.is_configured() is True

    def test_is_configured_false_when_missing(self, monkeypatch):
        from services import nivesh_cas_parser as ncp
        from helpers import secrets as sec

        original_get = sec.get

        def fake_get(key):
            if key == "GOOGLE_DOCAI_CREDENTIALS_JSON":
                return ""
            return original_get(key)

        monkeypatch.setattr(sec, "get", fake_get)
        # Clear env so fallback also returns ""
        monkeypatch.delenv("GOOGLE_DOCAI_CREDENTIALS_JSON", raising=False)
        assert ncp.is_configured() is False


# ── Normalizer + Mapper offline tests on saved sample ─────────────────
class TestNiveshNormalizerAndMapper:
    @pytest.fixture(scope="class")
    def normalized(self):
        # Use the saved sample (already a normalized output, NOT raw docai).
        # This file is the *normalizer's output* for the sample PDF.
        with open("/tmp/nivesh_normalized.json") as f:
            return json.load(f)

    def test_normalized_schema_has_all_keys(self, normalized):
        # Validate schema matches Claude/CAS-Connect shape
        assert "statement_info" in normalized
        assert "investor_info" in normalized
        assert "portfolio_summary" in normalized
        assert "accounts" in normalized
        assert "holdings" in normalized
        h = normalized["holdings"]
        for k in [
            "equities",
            "preference_shares",
            "sovereign_gold_bonds",
            "mutual_funds_demat",
            "mutual_fund_folios",
        ]:
            assert k in h, f"Missing holdings.{k}"
        t = normalized["transactions"]
        assert "demat_transactions" in t
        assert "mutual_fund_transactions" in t

    def test_normalize_function_runs_on_minimal_input(self):
        from services.nivesh_cas_normalizer import normalize

        out = normalize({"text": "NSDL ID: 12345\nperiod from 01-Apr-2024 to 31-Mar-2025", "tables": []})
        assert isinstance(out, dict)
        assert "holdings" in out and "transactions" in out
        # All holdings buckets should exist (empty)
        for k in ["equities", "preference_shares", "sovereign_gold_bonds",
                  "mutual_funds_demat", "mutual_fund_folios"]:
            assert k in out["holdings"]

    def test_mapper_accepts_normalizer_output(self, normalized):
        from services import claude_cas_mapper as mapper

        # mapper.map_to_internal returns either a list, dict, or tuple (holdings, mf_data)
        result = mapper.map_to_internal(normalized)
        if isinstance(result, tuple):
            holdings = result[0]
        elif isinstance(result, dict):
            holdings = result.get("holdings") or result.get("internal_holdings") or []
        else:
            holdings = result
        assert isinstance(holdings, list)
        assert len(holdings) >= 100, f"Expected >=100 holdings, got {len(holdings)}"
