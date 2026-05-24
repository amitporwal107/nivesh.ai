"""
Unit tests for the v4 Recommendation schema augmentation helper.

Per docs/api-changes.md Decision 2 (approved 2026-05-24). Verifies:
- Every v4 field is added by augment()
- No existing field is overwritten
- HOLD lowercase status bug is fixed
- FLAG dual id/action_id support
- source_domain inference per reason_code
- verb derivation (stock vs fund, SWITCH/MERGE special cases)
- Goals get exclusive=true and Goals priority labels
- augment() is idempotent (safe to call twice)
"""
import pytest

from services.action_recommendation_schema import (
    augment, augment_all, _derive_source_domain, _derive_verb,
    REASON_CODE_DOMAIN,
)


# ─── Field additions (preserve existing, add new) ───────────────────────

def test_augment_adds_all_v4_fields():
    """Every v4 schema field should be present after augment()."""
    action = {
        "action_id": "act_12345",
        "type": "TRIM",
        "status": "PENDING",
        "priority": 1,
        "asset_type": "mutual_fund",
        "asset_name": "HDFC Banking ETF",
        "amount": 180000,
        "reason_text": "Financials sector over-concentrated",
        "reason_codes": ["SECTOR_CONCENTRATION"],
        "created_at": "2026-05-24T10:00:00Z",
    }
    augment(action)

    # New v4 fields
    assert action["verb"] == "TRIM"
    assert action["priority_label"] == "Critical"
    assert action["source_domain"] == "concentration"
    assert action["effort"] == "MEDIUM"
    assert action["trade_off"] == ""
    assert action["impact"] == {"label": "Impact", "value": ""}
    assert action["expected_impact"] == {}
    assert action["exclusive"] is False
    assert action["scores"] is None
    assert action["switch_target"] is None
    # dual id/action_id
    assert action["id"] == "act_12345"
    assert action["action_id"] == "act_12345"


def test_augment_preserves_existing_fields():
    """Augmentation must never overwrite a field already populated."""
    action = {
        "action_id": "act_X",
        "type": "EXIT",
        "verb": "SWITCH",                          # already set
        "priority_label": "Custom",                # already set
        "trade_off": "Realises 3.1K LTCG",         # already set
        "expected_impact": {"health_delta": 6},    # already set
        "exclusive": True,                         # already set
        "scores": {"exit": 78, "add": 12, "hold": 22},
    }
    augment(action)

    assert action["verb"] == "SWITCH"
    assert action["priority_label"] == "Custom"
    assert action["trade_off"] == "Realises 3.1K LTCG"
    assert action["expected_impact"] == {"health_delta": 6}
    assert action["exclusive"] is True
    assert action["scores"] == {"exit": 78, "add": 12, "hold": 22}


def test_augment_is_idempotent():
    """Calling augment() twice must produce the same result as calling once."""
    action = {
        "action_id": "act_X", "type": "TRIM", "asset_type": "mutual_fund",
        "reason_codes": ["SECTOR_CONCENTRATION"], "priority": 1,
    }
    augment(action)
    snapshot = dict(action)
    augment(action)
    assert action == snapshot


# ─── Bug fixes ──────────────────────────────────────────────────────────

def test_augment_fixes_lowercase_pending_status():
    """HOLD synthetic action wrote 'pending' lowercase — must normalise to 'PENDING'."""
    action = {"action_id": "x", "type": "HOLD", "status": "pending", "reason_codes": []}
    augment(action)
    assert action["status"] == "PENDING"


def test_augment_normalises_all_lowercase_statuses():
    for lower, upper in [("pending", "PENDING"), ("in_progress", "IN_PROGRESS"),
                          ("completed", "COMPLETED"), ("skipped", "SKIPPED")]:
        a = {"action_id": "x", "type": "REVIEW", "status": lower}
        augment(a)
        assert a["status"] == upper, f"{lower!r} should normalise to {upper!r}"


def test_augment_leaves_uppercase_status_unchanged():
    a = {"action_id": "x", "type": "REVIEW", "status": "PENDING"}
    augment(a)
    assert a["status"] == "PENDING"


def test_augment_dual_id_action_id_for_flag_path():
    """FLAG action originally used 'id' instead of 'action_id' — augment must mirror both."""
    a_id_only = {"id": "custom-x-1", "type": "REVIEW"}
    augment(a_id_only)
    assert a_id_only["id"] == "custom-x-1"
    assert a_id_only["action_id"] == "custom-x-1"

    a_action_id_only = {"action_id": "act_x", "type": "EXIT"}
    augment(a_action_id_only)
    assert a_action_id_only["id"] == "act_x"
    assert a_action_id_only["action_id"] == "act_x"


# ─── source_domain inference ────────────────────────────────────────────

@pytest.mark.parametrize("reason_code,expected_domain", [
    ("SECTOR_CONCENTRATION",       "concentration"),
    ("AMC_CONCENTRATION_EXIT",     "concentration"),
    ("PORTFOLIO_HEALTHY",          "concentration"),
    ("OVERLAP_CONSOLIDATION",      "diversification"),
    ("REGULAR_DIRECT_DUPLICATE",   "diversification"),
    ("COST_LEAK_SWITCH_TO_DIRECT", "diversification"),
    ("DEBT_UNDERWEIGHT",           "diversification"),
    ("HIGH_BETA",                  "risk"),
    ("HIGH_VOLATILITY",            "risk"),
    ("LOW_RETURN_EFFICIENCY",      "performance"),
    ("UNDERPERFORMING_FUND",       "performance"),
    ("GOAL_SHORTFALL",             "goals"),
    ("GOAL_SIP_INCREASE",          "goals"),
    ("GOAL_LUMPSUM_TOPUP",         "goals"),
    ("TAX_HARVEST",                "tax"),
    ("TAX_80C",                    "tax"),
])
def test_source_domain_from_known_reason_codes(reason_code, expected_domain):
    assert _derive_source_domain([reason_code]) == expected_domain


@pytest.mark.parametrize("reason_code,expected_domain", [
    ("GOAL_UNKNOWN_NEW_CODE",   "goals"),     # GOAL_ prefix
    ("SIP_STEP_UP_v2",           "goals"),    # SIP_ prefix
    ("TAX_NEW_RULE_XYZ",         "tax"),
    ("SECTOR_NEW_RULE",          "concentration"),
    ("OVERLAP_NEW_DETECTOR",     "diversification"),
    ("BETA_REGIME",              "risk"),
    ("XIRR_LAG_NEW",             "performance"),
])
def test_source_domain_prefix_heuristics(reason_code, expected_domain):
    assert _derive_source_domain([reason_code]) == expected_domain


def test_source_domain_first_match_wins():
    """When multiple codes are present, first match should win."""
    assert _derive_source_domain(["TAX_HARVEST", "SECTOR_CONCENTRATION"]) == "tax"
    assert _derive_source_domain(["SECTOR_CONCENTRATION", "TAX_HARVEST"]) == "concentration"


def test_source_domain_empty_or_unknown():
    assert _derive_source_domain([]) is None
    assert _derive_source_domain(None) is None
    assert _derive_source_domain(["UNKNOWN_ZZZ"]) is None


# ─── verb derivation (PRD §7.4 vocabulary) ──────────────────────────────

def test_verb_stock_uses_stock_vocabulary():
    """Stock verbs per PRD §7.4 — Add / Exit / Trim / Hold."""
    assert _derive_verb("ADD",  "equity") == "ADD"
    assert _derive_verb("EXIT", "equity") == "EXIT"
    assert _derive_verb("TRIM", "equity") == "TRIM"
    assert _derive_verb("HOLD", "equity") == "HOLD"


def test_verb_fund_exit_with_switch_code_becomes_switch():
    """For funds, EXIT + REGULAR_DIRECT_DUPLICATE reason → SWITCH verb."""
    assert _derive_verb("EXIT", "mutual_fund", ["REGULAR_DIRECT_DUPLICATE"]) == "SWITCH"
    assert _derive_verb("EXIT", "mutual_fund", ["COST_LEAK_SWITCH_TO_DIRECT"]) == "SWITCH"


def test_verb_fund_exit_with_overlap_code_becomes_merge():
    """For funds, EXIT + OVERLAP_CONSOLIDATION reason → MERGE verb."""
    assert _derive_verb("EXIT", "mutual_fund", ["OVERLAP_CONSOLIDATION"]) == "MERGE"


def test_verb_unknown_type_passes_through():
    """Unknown action types should pass through unchanged so we don't drop signal."""
    assert _derive_verb("CUSTOM_NEW_VERB", "stock") == "CUSTOM_NEW_VERB"


# ─── priority_label vocabulary (Goals vs default) ──────────────────────

def test_priority_label_default_dashboards():
    """Critical / Optimise / Enhance for most dashboards (PRD §7.4)."""
    for p, expected in [(1, "Critical"), (2, "Optimise"), (3, "Enhance")]:
        a = {"action_id": "x", "type": "EXIT", "priority": p,
             "reason_codes": ["SECTOR_CONCENTRATION"]}
        augment(a)
        assert a["priority_label"] == expected


def test_priority_label_goals_dashboard():
    """Closes the gap / Closes most / Partial for Goals (PRD §7.4)."""
    for p, expected in [(1, "Closes the gap"), (2, "Closes most"), (3, "Partial")]:
        a = {"action_id": "x", "type": "ADD", "priority": p,
             "reason_codes": ["GOAL_SHORTFALL"]}
        augment(a)
        assert a["priority_label"] == expected


def test_priority_label_string_values():
    """`priority: 'high'/'medium'/'low'` must also map correctly."""
    for p, expected in [("high", "Critical"), ("medium", "Optimise"), ("low", "Enhance")]:
        a = {"action_id": "x", "type": "EXIT", "priority": p,
             "reason_codes": ["AMC_CONCENTRATION"]}
        augment(a)
        assert a["priority_label"] == expected


# ─── exclusive flag (Goals are mutually exclusive per PRD §7.4) ────────

def test_goals_actions_are_exclusive():
    a = {"action_id": "x", "type": "ADD", "reason_codes": ["GOAL_SHORTFALL"], "priority": 1}
    augment(a)
    assert a["exclusive"] is True


def test_non_goals_actions_are_not_exclusive():
    for codes in [["SECTOR_CONCENTRATION"], ["OVERLAP_CONSOLIDATION"], ["HIGH_BETA"],
                   ["TAX_HARVEST"], ["LOW_RETURN_EFFICIENCY"]]:
        a = {"action_id": "x", "type": "TRIM", "reason_codes": codes, "priority": 2}
        augment(a)
        assert a["exclusive"] is False, f"Codes {codes} should not be exclusive"


# ─── augment_all on a list ──────────────────────────────────────────────

def test_augment_all_handles_empty_list():
    assert augment_all([]) == []
    assert augment_all(None) is None


def test_augment_all_applies_to_every_action():
    actions = [
        {"action_id": "1", "type": "TRIM", "reason_codes": ["SECTOR_CONCENTRATION"], "priority": 1},
        {"action_id": "2", "type": "ADD",  "reason_codes": ["GOAL_SHORTFALL"], "priority": 2},
        {"action_id": "3", "type": "HARVEST", "reason_codes": ["TAX_HARVEST"], "priority": 1},
    ]
    augment_all(actions)
    assert actions[0]["source_domain"] == "concentration"
    assert actions[1]["source_domain"] == "goals" and actions[1]["exclusive"] is True
    assert actions[2]["source_domain"] == "tax"
    # every action got all v4 fields
    for a in actions:
        for field in ("verb", "priority_label", "source_domain", "effort", "trade_off",
                      "impact", "expected_impact", "exclusive", "scores", "switch_target"):
            assert field in a, f"action {a['action_id']} missing field {field}"


# ─── Non-dict input is returned unchanged ───────────────────────────────

def test_augment_non_dict_returns_unchanged():
    assert augment("not a dict") == "not a dict"
    assert augment(None) is None
    assert augment(42) == 42
