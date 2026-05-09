"""Live API regression — GET /api/insights/v3-portfolio switch_decision wiring.

Exercises the end-to-end candidate-fund hydrator + switch decision engine
on a real user portfolio (aporwal107@gmail.com — 59 MF holdings).
Validates PRD §12 output shape, peer hydration coverage and bucket
distribution.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://portfolio-ai-68.preview.emergentagent.com").rstrip("/")
SESSION_TOKEN = "3352751a-cc8a-4bcb-bf50-81a377c6b40b"

VALID_RECS = {"ADD", "SWITCH", "EXIT", "REVIEW", "WATCH"}
VALID_STRENGTHS = {"HIGH", "MEDIUM", "LOW"}
IMPACT_KEYS = {"cost_saving", "alpha_gain", "tax_cost", "exit_cost", "net_benefit"}


@pytest.fixture(scope="module")
def v3_payload():
    r = requests.get(
        f"{BASE_URL}/api/insights/v3-portfolio",
        headers={"Authorization": f"Bearer {SESSION_TOKEN}"},
        timeout=120,
    )
    if r.status_code != 200:
        pytest.skip(f"v3-portfolio unavailable: {r.status_code} {r.text[:200]}")
    return r.json()


@pytest.fixture(scope="module")
def mf_funds(v3_payload):
    # /api/insights/v3-portfolio returns MF holdings only — no need to filter by type
    funds = v3_payload.get("funds") or []
    if not funds:
        pytest.skip("No funds for this user")
    return funds


# ── Reachability ────────────────────────────────────────────────────────
def test_v3_endpoint_returns_funds(v3_payload):
    assert isinstance(v3_payload, dict)
    assert "funds" in v3_payload
    assert isinstance(v3_payload["funds"], list)
    assert len(v3_payload["funds"]) > 0


# ── Switch decision shape / PRD §12 ─────────────────────────────────────
def test_switch_decision_present_for_majority_of_mfs(mf_funds):
    with_sd = [f for f in mf_funds if f.get("switch_decision")]
    assert len(with_sd) >= int(0.7 * len(mf_funds)), (
        f"Only {len(with_sd)}/{len(mf_funds)} MF funds have switch_decision"
    )


def test_switch_decision_has_prd_v12_fields(mf_funds):
    sample = next((f for f in mf_funds if f.get("switch_decision")), None)
    assert sample is not None
    sd = sample["switch_decision"]
    for key in ("recommendation", "action_strength", "allocation_change",
                "from_fund", "to_fund", "impact"):
        assert key in sd, f"Missing PRD §12 key: {key}"
    assert sd["recommendation"] in VALID_RECS
    assert sd["action_strength"] in VALID_STRENGTHS
    assert isinstance(sd["impact"], dict)
    for k in IMPACT_KEYS:
        assert k in sd["impact"], f"Missing impact.{k}"


def test_backwards_compat_fields_retained(mf_funds):
    sample = next((f for f in mf_funds if f.get("switch_decision")), None)
    sd = sample["switch_decision"]
    for key in ("action", "label", "switch_score", "signals", "breakdown"):
        assert key in sd, f"Backwards-compat key missing: {key}"


# ── Hydrator coverage ───────────────────────────────────────────────────
def test_hydrator_covers_at_least_80pct_of_mfs(mf_funds):
    with_sd = [f for f in mf_funds if f.get("switch_decision")]
    with_candidates = [
        f for f in with_sd
        if (f["switch_decision"].get("_n_candidates") or 0) > 0
    ]
    total = len(with_sd) or 1
    coverage = len(with_candidates) / total
    assert coverage >= 0.8, (
        f"Peer hydration only {coverage:.0%} ({len(with_candidates)}/{total}); "
        "expected ≥80%"
    )


# ── Bucket distribution ─────────────────────────────────────────────────
def test_bucket_distribution_uses_5_taxonomy(mf_funds):
    distinct = {
        f["switch_decision"]["recommendation"]
        for f in mf_funds
        if f.get("switch_decision")
    }
    # The portfolio is large + heterogeneous → expect at least 2 buckets used
    assert distinct.issubset(VALID_RECS)
    assert len(distinct) >= 2, f"Only one bucket seen: {distinct}"


# ── Impact block carries real numbers ───────────────────────────────────
def test_impact_block_has_numeric_values(mf_funds):
    sd_with_impact = [
        f["switch_decision"] for f in mf_funds if f.get("switch_decision")
    ]
    # At least one fund should report a non-zero cost_saving or tax_cost
    has_signal = any(
        (sd["impact"].get("cost_saving") or 0) != 0
        or (sd["impact"].get("tax_cost") or 0) != 0
        for sd in sd_with_impact
    )
    assert has_signal, "All impact blocks are zero — engine looks unwired"


# ── Direct-plan SWITCH HIGH spot-check ──────────────────────────────────
def test_at_least_one_regular_plan_strong_switch(mf_funds):
    """Regular-plan funds with low cost_diff should produce
    STRONG_SWITCH_DIRECT → recommendation=SWITCH, action_strength=HIGH."""
    matches = [
        f for f in mf_funds
        if f.get("switch_decision")
        and f["switch_decision"].get("recommendation") == "SWITCH"
        and f["switch_decision"].get("action_strength") == "HIGH"
    ]
    assert len(matches) >= 1, "No SWITCH/HIGH recommendation found"
