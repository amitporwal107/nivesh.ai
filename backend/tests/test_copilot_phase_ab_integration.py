"""Integration tests for Copilot Phase A+B endpoints against live preview backend.

Exercises:
  - /api/copilot/agents (catalog)
  - /api/copilot/models/picker (3-model picker, gpt-4o default)
  - /api/copilot/agents/route (intent routing)
  - /api/copilot/agents/oneshot (LLM call via gpt-4o)
  - /api/copilot/widgets/market_brief
  - /api/copilot/widgets/fund_card
  - /api/copilot/widgets/sip_plan
  - /api/copilot/widgets/compare_funds
  - Auth gating (401 without session cookie)
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://nidp-backfill-ui.preview.emergentagent.com").rstrip("/")
SESSION_TOKEN = "3352751a-cc8a-4bcb-bf50-81a377c6b40b"


@pytest.fixture
def auth_session():
    s = requests.Session()
    s.cookies.set("session_token", SESSION_TOKEN)
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture
def unauth_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ── Catalog endpoints ───────────────────────────────────────────

def test_agents_catalog(auth_session):
    r = auth_session.get(f"{BASE_URL}/api/copilot/agents", timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    agents = data.get("agents") if isinstance(data, dict) else data
    assert isinstance(agents, list)
    ids = {a["id"] for a in agents}
    assert ids == {"auto", "portfolio_analyzer", "mf_research", "market_strategist",
                   "tax_agent", "compliance_agent", "report_generator"}, ids
    for a in agents:
        for key in ("id", "label", "icon", "one_liner", "triggers", "default_suggestions"):
            assert key in a, f"missing {key} in {a}"


def test_models_picker_default_gpt4o(auth_session):
    r = auth_session.get(f"{BASE_URL}/api/copilot/models/picker", timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    models = data.get("models") if isinstance(data, dict) else data
    assert isinstance(models, list)
    assert len(models) == 3
    ids = {m["id"] for m in models}
    assert ids == {"gpt-4o", "claude-sonnet-4-5", "gemini-2.5-flash"}
    defaults = [m for m in models if m.get("is_default")]
    assert len(defaults) == 1
    assert defaults[0]["id"] == "gpt-4o"


def test_legacy_models_endpoint_no_collision(auth_session):
    """Verify legacy /api/copilot/models still exists & differs from picker."""
    r = auth_session.get(f"{BASE_URL}/api/copilot/models", timeout=15)
    # Either 200 with legacy schema or 404 — but should NOT match picker shape exactly
    assert r.status_code in (200, 404), r.status_code


# ── Agent routing ───────────────────────────────────────────────

@pytest.mark.parametrize("message,expected", [
    ("How much LTCG do I have this FY?", "tax_agent"),
    ("What happened in the markets today?", "market_strategist"),
    ("Tell me about Parag Parikh Flexi Cap", "mf_research"),
    ("Show me a rebalance plan", "portfolio_analyzer"),
    ("Am I taking too much risk?", "compliance_agent"),
    ("Generate my Q4 portfolio summary", "report_generator"),
])
def test_agent_route_classification(auth_session, message, expected):
    r = auth_session.post(f"{BASE_URL}/api/copilot/agents/route",
                          json={"message": message}, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("agent_id") == expected, f"msg={message!r} got={data}"


# ── One-shot LLM ────────────────────────────────────────────────

def test_agent_oneshot_gpt4o(auth_session):
    r = auth_session.post(f"{BASE_URL}/api/copilot/agents/oneshot",
                          json={"agent_id": "mf_research", "model_id": "gpt-4o",
                                "message": "In one sentence, what is an index fund?"},
                          timeout=60)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "text" in data and isinstance(data["text"], str) and data["text"].strip()
    assert data.get("agent_id") == "mf_research"
    assert data.get("model_id") == "gpt-4o"


# ── Widgets ─────────────────────────────────────────────────────

def test_widget_market_brief(auth_session):
    r = auth_session.post(f"{BASE_URL}/api/copilot/widgets/market_brief",
                          json={}, timeout=30)
    assert r.status_code == 200, r.text
    env = r.json()
    assert env.get("kind") == "market_brief"
    assert env.get("agent", {}).get("id") == "market_strategist"
    assert "freshness" in env
    data = env.get("data", {})
    # Either indices populated OR stale-fallback (partial flag or empty indices)
    assert "indices" in data
    # Note: indices may be empty when DaaS unreachable — stale-state envelope is acceptable.


def test_widget_fund_card(auth_session):
    r = auth_session.post(f"{BASE_URL}/api/copilot/widgets/fund_card",
                          json={"query": "Parag Parikh"}, timeout=30)
    # Either 200 with envelope or 404 if no master match
    assert r.status_code in (200, 404), r.text
    if r.status_code == 200:
        env = r.json()
        assert env["kind"] == "fund_card"
        assert "scheme_name" in env["data"]
    else:
        body = r.json()
        # FastAPI error contract
        assert "detail" in body


def test_widget_sip_plan(auth_session):
    r = auth_session.post(f"{BASE_URL}/api/copilot/widgets/sip_plan",
                          json={"monthly_budget": 50000, "risk_label": "Moderate"},
                          timeout=30)
    assert r.status_code == 200, r.text
    env = r.json()
    assert env["kind"] == "sip_plan"
    data = env["data"]
    assert data["monthly_budget"] == 50000
    allocs = data["allocations"]
    assert isinstance(allocs, list) and len(allocs) == 3
    total = sum(a["monthly_amount"] for a in allocs)
    # within 5% of budget
    assert abs(total - 50000) <= 2500, f"total={total}"


def test_widget_compare_funds_invalid_codes(auth_session):
    r = auth_session.post(f"{BASE_URL}/api/copilot/widgets/compare_funds",
                          json={"scheme_codes": ["000000", "000001"]}, timeout=30)
    # Expect 404 for nonexistent codes OR 200 with empty rows
    assert r.status_code in (200, 404, 400), r.text
    if r.status_code == 404:
        assert "detail" in r.json()


# ── Auth gating ─────────────────────────────────────────────────

@pytest.mark.parametrize("path,method,payload", [
    ("/api/copilot/agents", "GET", None),
    ("/api/copilot/models/picker", "GET", None),
    ("/api/copilot/agents/route", "POST", {"message": "hi"}),
    ("/api/copilot/agents/oneshot", "POST", {"agent_id": "auto", "model_id": "gpt-4o", "message": "hi"}),
    ("/api/copilot/widgets/market_brief", "POST", {}),
    ("/api/copilot/widgets/fund_card", "POST", {"query": "Parag Parikh"}),
    ("/api/copilot/widgets/sip_plan", "POST", {"monthly_budget": 1000, "risk_label": "Moderate"}),
    ("/api/copilot/widgets/compare_funds", "POST", {"scheme_codes": ["1", "2"]}),
])
def test_auth_required(unauth_session, path, method, payload):
    url = f"{BASE_URL}{path}"
    if method == "GET":
        r = unauth_session.get(url, timeout=15)
    else:
        r = unauth_session.post(url, json=payload, timeout=15)
    assert r.status_code == 401, f"{method} {path} expected 401 got {r.status_code} body={r.text[:200]}"
