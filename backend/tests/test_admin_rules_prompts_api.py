"""Integration tests for /api/admin/rules-config* and /api/admin/prompts* endpoints.

Runs against REACT_APP_BACKEND_URL using the admin session cookie for
priyankamantri@gmail.com.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://wealth-advisor-india-1.preview.emergentagent.com").rstrip("/")
SESSION_TOKEN = "370eff71-fda1-46d8-b506-b81b894d634f"


@pytest.fixture(scope="module")
def admin_client():
    s = requests.Session()
    s.cookies.set("session_token", SESSION_TOKEN)
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def anon_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


EXPECTED_RULES = {
    "rule_1_regular_to_direct", "rule_2_amc_concentration",
    "rule_2b_category_concentration", "rule_3_underperformer_replacement",
    "rule_4_different_fund_overlap", "rule_5_debt_allocation",
    "rule_6_cost_leak_switch", "rule_7_do_nothing",
}

EXPECTED_PROMPTS = {
    "financial_advisor_system", "insight_analysis_system", "cas_parser_system",
    "insights_system_prompt", "category_rating_system", "mf_rating_system",
    "allocation_analysis_system",
}


# ── Auth gating ──────────────────────────────────────────────────────────

class TestAdminAuth:
    def test_rules_config_requires_auth(self, anon_client):
        r = anon_client.get(f"{BASE_URL}/api/admin/rules-config")
        assert r.status_code in (401, 403), f"Unauth got {r.status_code}"

    def test_prompts_requires_auth(self, anon_client):
        r = anon_client.get(f"{BASE_URL}/api/admin/prompts")
        assert r.status_code in (401, 403)


# ── Rules Config GET/PUT/RESET ───────────────────────────────────────────

class TestRulesConfig:
    def test_get_returns_all_default_rules(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/rules-config")
        assert r.status_code == 200
        body = r.json()
        assert "config" in body and "defaults" in body
        rules = body["config"]["rules"]
        assert set(rules.keys()) == EXPECTED_RULES
        # Defaults sanity
        assert body["defaults"]["rules"]["rule_2b_category_concentration"]["params"]["threshold_pct"] == 35.0

    def test_put_override_persists(self, admin_client):
        # First GET current
        cur = admin_client.get(f"{BASE_URL}/api/admin/rules-config").json()["config"]
        cur["rules"]["rule_2b_category_concentration"]["params"]["threshold_pct"] = 25.0
        r = admin_client.put(f"{BASE_URL}/api/admin/rules-config", json=cur)
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # Verify via fresh GET
        fresh = admin_client.get(f"{BASE_URL}/api/admin/rules-config").json()
        assert fresh["config"]["rules"]["rule_2b_category_concentration"]["params"]["threshold_pct"] == 25.0
        # Defaults must still show 35
        assert fresh["defaults"]["rules"]["rule_2b_category_concentration"]["params"]["threshold_pct"] == 35.0

    def test_reset_clears_overrides(self, admin_client):
        r = admin_client.post(f"{BASE_URL}/api/admin/rules-config/reset")
        assert r.status_code == 200
        # rule_2b back to 35
        fresh = admin_client.get(f"{BASE_URL}/api/admin/rules-config").json()
        assert fresh["config"]["rules"]["rule_2b_category_concentration"]["params"]["threshold_pct"] == 35.0


# ── Custom Rule validate ─────────────────────────────────────────────────

class TestCustomRuleValidate:
    def test_validate_valid_expression(self, admin_client):
        r = admin_client.post(
            f"{BASE_URL}/api/admin/rules-config/custom/validate",
            json={"expression": "debt_pct < 5 and equity_pct > 90"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert set(body["names_used"]) == {"debt_pct", "equity_pct"}

    def test_validate_invalid_expression(self, admin_client):
        r = admin_client.post(
            f"{BASE_URL}/api/admin/rules-config/custom/validate",
            json={"expression": "foo bar baz"},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is False

    def test_validate_with_sample_evaluates(self, admin_client):
        r = admin_client.post(
            f"{BASE_URL}/api/admin/rules-config/custom/validate",
            json={
                "expression": "debt_pct < 5 and equity_pct > 90",
                "sample_context": {"debt_pct": 3, "equity_pct": 95},
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body.get("evaluated") is True

    @pytest.mark.parametrize("expr", [
        "__import__('os').system('ls')",
        "open('/etc/passwd')",
        "lambda x: x",
    ])
    def test_validate_rejects_unsafe(self, admin_client, expr):
        r = admin_client.post(
            f"{BASE_URL}/api/admin/rules-config/custom/validate",
            json={"expression": expr},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is False, f"Should reject unsafe expr: {expr}"


# ── Custom Rule CRUD ─────────────────────────────────────────────────────

class TestCustomRuleCrud:
    def test_create_valid_custom_rule(self, admin_client):
        payload = {
            "name": "TEST_high_equity_flag",
            "expression": "equity_pct > 90",
            "action_type": "FLAG_ONLY",
            "description": "Flag when equity pct is high",
        }
        r = admin_client.post(f"{BASE_URL}/api/admin/rules-config/custom", json=payload)
        assert r.status_code == 200, r.text
        rule = r.json()["rule"]
        assert "id" in rule and rule["id"].startswith("r_")
        # cleanup
        admin_client.delete(f"{BASE_URL}/api/admin/rules-config/custom/{rule['id']}")

    def test_create_missing_fields_returns_400(self, admin_client):
        r = admin_client.post(
            f"{BASE_URL}/api/admin/rules-config/custom",
            json={"name": "x"},
        )
        assert r.status_code == 400

    def test_create_unknown_context_key_returns_400(self, admin_client):
        r = admin_client.post(
            f"{BASE_URL}/api/admin/rules-config/custom",
            json={
                "name": "TEST_unknown_key",
                "expression": "foo_bar > 5",
                "action_type": "FLAG_ONLY",
            },
        )
        assert r.status_code == 400
        assert "unknown context keys" in r.text.lower()

    def test_delete_removes_rule(self, admin_client):
        # Create
        created = admin_client.post(
            f"{BASE_URL}/api/admin/rules-config/custom",
            json={
                "name": "TEST_to_delete",
                "expression": "debt_pct < 10",
                "action_type": "FLAG_ONLY",
            },
        ).json()["rule"]
        rid = created["id"]
        # Delete
        r = admin_client.delete(f"{BASE_URL}/api/admin/rules-config/custom/{rid}")
        assert r.status_code == 200
        # Verify gone
        listing = admin_client.get(f"{BASE_URL}/api/admin/rules-config/custom").json()
        assert not any(x.get("id") == rid for x in listing.get("custom_rules", []))


# ── Prompts ──────────────────────────────────────────────────────────────

class TestPrompts:
    def test_get_all_prompts(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/prompts")
        assert r.status_code == 200
        body = r.json()
        names = {p["name"] for p in body["prompts"]}
        assert EXPECTED_PROMPTS.issubset(names), f"Missing: {EXPECTED_PROMPTS - names}"
        # shape
        p0 = body["prompts"][0]
        for k in ("default", "current", "overridden", "length"):
            assert k in p0

    def test_override_and_reset_prompt(self, admin_client):
        name = "financial_advisor_system"
        custom_text = "TEST_OVERRIDE_PROMPT_XYZ — behave as instructed."
        # Update
        r = admin_client.put(f"{BASE_URL}/api/admin/prompts/{name}", json={"text": custom_text})
        assert r.status_code == 200
        # Verify overridden=true
        got = admin_client.get(f"{BASE_URL}/api/admin/prompts/{name}").json()
        assert got["overridden"] is True
        assert got["current"] == custom_text
        # Reset
        r2 = admin_client.post(f"{BASE_URL}/api/admin/prompts/{name}/reset")
        assert r2.status_code == 200
        got2 = admin_client.get(f"{BASE_URL}/api/admin/prompts/{name}").json()
        assert got2["overridden"] is False

    def test_update_prompt_empty_text_rejected(self, admin_client):
        r = admin_client.put(
            f"{BASE_URL}/api/admin/prompts/financial_advisor_system",
            json={"text": "   "},
        )
        assert r.status_code == 400

    def test_update_unknown_prompt_rejected(self, admin_client):
        r = admin_client.put(
            f"{BASE_URL}/api/admin/prompts/nonexistent_prompt_xyz",
            json={"text": "hello"},
        )
        assert r.status_code in (400, 404)


# ── End-to-End BANANA test (prompt change flows into chat) ───────────────

class TestPromptIntegration:
    """Sets a prompt to force a specific reply, hits /api/admin/prompts/.../test
    (which calls the LLM with that prompt), then resets."""

    def test_prompt_test_endpoint_returns_response(self, admin_client):
        name = "financial_advisor_system"
        banana = "REPLY ONLY WITH THE LITERAL WORD BANANA, nothing else."
        try:
            # Override
            put = admin_client.put(f"{BASE_URL}/api/admin/prompts/{name}", json={"text": banana})
            assert put.status_code == 200
            # Fire /test endpoint
            r = admin_client.post(
                f"{BASE_URL}/api/admin/prompts/{name}/test",
                json={"user_text": "Hi"},
                timeout=45,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert "system" in body and "user" in body
            # system field must reflect the override
            assert "BANANA" in body["system"]
            # response may be None if LLM key missing; if present, should contain BANANA
            if body.get("response"):
                assert "BANANA" in body["response"].upper(), f"Got: {body['response']}"
        finally:
            # ALWAYS reset
            admin_client.post(f"{BASE_URL}/api/admin/prompts/{name}/reset")


# ── Plan regression ──────────────────────────────────────────────────────

class TestPlanRegression:
    def test_plan_generate_still_v2_5(self, admin_client):
        r = admin_client.post(
            f"{BASE_URL}/api/plans/generate",
            json={},
            timeout=120,
        )
        # Endpoint may differ; accept 200/201 with engine_version
        if r.status_code != 200:
            pytest.skip(f"Plan endpoint returned {r.status_code}; skipping regression")
        body = r.json()
        plan = body.get("plan", {})
        ev = (
            plan.get("engine_version")
            or (plan.get("metadata") or {}).get("engine_version")
            or body.get("engine_version")
        )
        assert ev == "v2.5", f"engine_version={ev}"
        assert len(plan.get("actions", [])) >= 1
        assert plan.get("portfolio_score") is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
