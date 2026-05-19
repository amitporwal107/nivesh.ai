"""Regression test for the persona-aware suggested-prompts selection logic.

The bug this guards against:
    Shipped 99 persona-tagged templates + 10 universal templates with
    `personas: list[str]` filter. The endpoint correctly filtered persona
    templates IN, but their scorers returned a flat 55 (secondary tier)
    while universal scorers returned 80-100 — so universals swept every
    tier slot and no persona-tagged prompt ever surfaced in the UI for a
    user with a real portfolio.

Fix:
    Two-layered guarantee in routes/copilot_prompts.py:
      1. +35 score boost when a template's `personas` list contains the
         resolved persona (so persona templates compete on equal footing).
      2. Persona floor — if no persona template ends up in the secondary
         tier despite the boost (extreme universal signals), force the
         top-scored persona-tagged secondary in and drop the lowest
         universal one.

This test exercises the actual selection logic (not just the import) and
asserts that at least one persona-tagged prompt appears in the visible
tiers for each of the 10 personas given a realistic portfolio context.
"""
from __future__ import annotations

import importlib
import pytest


# ---------------------------------------------------------------------------
# Helpers — replay the selection logic from suggested_prompts() against a
# given ctx + persona, without needing FastAPI / Mongo / auth.
# ---------------------------------------------------------------------------

def _replay_selection(ctx, persona, persona_prompts_on=True, category=None):
    """Mirror the scoring + tier-shape + persona-floor logic in
    routes/copilot_prompts.suggested_prompts(). Returns (primary, secondary,
    advanced) lists of selected templates."""
    cp = importlib.import_module("routes.copilot_prompts")
    DEFAULT_PERSONA = cp._DEFAULT_PERSONA

    scored = []
    for tpl in cp._PROMPT_TEMPLATES:
        # Persona filter
        if persona_prompts_on:
            if not cp._matches_persona(tpl, persona):
                continue
        else:
            if tpl.get("personas"):
                continue

        if not cp._matches_category(tpl, category):
            continue

        score, badge = tpl["scorer"](ctx)
        if score <= 0:
            continue

        # Same boosts as the endpoint
        if persona_prompts_on and tpl.get("personas") and persona in tpl["personas"]:
            score += 35

        scored.append({**tpl, "score": score, "badge": badge})

    scored.sort(key=lambda p: p["score"], reverse=True)
    primary = [p for p in scored if p["tier"] == "primary"][:1]
    secondary = [p for p in scored if p["tier"] == "secondary"][:3]
    advanced = [p for p in scored if p["tier"] == "advanced"][:3]

    # Persona floor — duplicate of the endpoint's secondary-slot guarantee
    if persona_prompts_on and persona and persona != DEFAULT_PERSONA:
        if not any(p.get("personas") for p in secondary):
            top_persona_secondary = next(
                (p for p in scored if p["tier"] == "secondary" and p.get("personas")),
                None,
            )
            if top_persona_secondary:
                secondary = [p for p in secondary if not p.get("personas")][:2]
                secondary.append(top_persona_secondary)

    return primary, secondary, advanced


def _mf_heavy_ctx():
    """Realistic context for an MF-heavy HNI investor — the exact profile
    that exposed the original bug in production."""
    return {
        "total_value": 10_000_000,           # ₹1cr — HNI tier
        "equity_pct": 80,
        "debt_pct": 15,
        "gold_pct": 3,
        "other_pct": 2,
        "max_overlap_pct": 65,               # strong universal signal
        "overlap_pair_count": 4,
        "top_overlaps": [
            {"a": "Fund A", "b": "Fund B", "overlap_pct": 65},
        ],
        "top_amc_name": "HDFC",
        "top_amc_pct": 32,                   # also strong universal signal
        "top_amcs": [{"name": "HDFC", "pct": 32}],
        "action_count": 5,
        "has_exit_actions": True,
        "plan_tax_liability": 50000,
        "underperformer_count": 3,
        "fund_count": 60,
    }


def _modest_ctx():
    """Smaller portfolio with no extreme signals — persona templates should
    dominate easily here."""
    return {
        "total_value": 500_000,
        "equity_pct": 70,
        "debt_pct": 25,
        "gold_pct": 3,
        "other_pct": 2,
        "max_overlap_pct": 10,
        "overlap_pair_count": 0,
        "top_overlaps": [],
        "top_amc_name": None,
        "top_amc_pct": 0,
        "top_amcs": [],
        "action_count": 0,
        "has_exit_actions": False,
        "plan_tax_liability": 0,
        "underperformer_count": 0,
        "fund_count": 6,
    }


# All 10 product personas — matches PersonaType.value used in the catalog.
ALL_PERSONAS = [
    "beginner_investor",
    "mutual_fund_investor",
    "stock_investor",
    "hni_investor",
    "retirement_planner",
    "parents_planning",
    "tax_saver",
    "conservative_investor",
    "active_trader",
    "nri_investor",
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("persona", ALL_PERSONAS)
def test_persona_template_surfaces_for_each_persona_on_modest_portfolio(persona):
    """For every persona with a modest portfolio (no extreme universal
    signals), at least one persona-tagged template must reach the visible
    primary or secondary tier."""
    primary, secondary, _ = _replay_selection(_modest_ctx(), persona)
    visible = primary + secondary

    persona_tagged = [
        p for p in visible
        if p.get("personas") and persona in p["personas"]
    ]
    assert persona_tagged, (
        f"persona={persona}: zero persona-tagged prompts surfaced in primary+secondary. "
        f"Visible IDs: {[p['id'] for p in visible]}"
    )


@pytest.mark.parametrize("persona", ALL_PERSONAS)
def test_persona_floor_holds_against_extreme_universal_signals(persona):
    """Even with a portfolio that triggers the universal scorers hard (high
    overlap, AMC concentration, exit actions, underperformers), the persona
    floor must still place at least one persona-tagged template in the
    secondary tier."""
    primary, secondary, _ = _replay_selection(_mf_heavy_ctx(), persona)
    visible = primary + secondary

    persona_tagged = [
        p for p in visible
        if p.get("personas") and persona in p["personas"]
    ]
    assert persona_tagged, (
        f"persona={persona} with strong universal signals: zero persona-tagged "
        f"prompts in primary+secondary. Visible IDs: {[p['id'] for p in visible]}"
    )


def test_mf_investor_sees_mf_specific_label_not_just_universal_fix_overlap():
    """The original bug case: an MF-heavy investor was only seeing 'Fix
    overlap in my funds' (universal) and never any MF-tagged template like
    'Do I have too many mutual funds?' / 'Should I switch to direct plans?'.
    This asserts at least one MF-specific question label appears."""
    primary, secondary, advanced = _replay_selection(_mf_heavy_ctx(), "mutual_fund_investor")
    visible = primary + secondary + advanced

    mf_specific_ids = {
        "mf_too_many", "mf_overlap_deep", "mf_drag", "mf_sip_optimal",
        "mf_direct_plans", "mf_best_sip_funds", "mf_categories_explained",
        "mf_equity_for_age", "mf_sip_in_correction", "mf_expense_ratio_impact",
    }
    surfaced_mf_ids = {p["id"] for p in visible} & mf_specific_ids
    assert surfaced_mf_ids, (
        f"MF investor saw zero MF-specific prompts. Surfaced: "
        f"{[p['id'] for p in visible]}"
    )


def test_universal_strong_signal_can_still_win_primary():
    """Sanity check the boost isn't so aggressive it disenfranchises strong
    universal signals. With action_count=5 the universal 'fix_portfolio'
    primary should still be the user's hero card — but a persona secondary
    should also be present in the secondary tier."""
    primary, secondary, _ = _replay_selection(_mf_heavy_ctx(), "mutual_fund_investor")
    assert primary, "no primary selected"
    assert primary[0]["id"] in {"fix_portfolio", "mf_too_many"}, (
        f"unexpected primary winner: {primary[0]['id']}"
    )
    assert any(p.get("personas") for p in secondary), (
        "persona floor failed — no persona template in secondary"
    )


def test_no_persona_falls_back_to_universal_only():
    """User with no persona (anonymous / fresh signup) should still see the
    classic 10-universal experience. No persona templates should appear."""
    primary, secondary, advanced = _replay_selection(
        _modest_ctx(), persona="retail_investor"
    )
    visible = primary + secondary + advanced
    assert not any(p.get("personas") for p in visible), (
        "retail_investor (default) should see only universal templates; "
        f"got: {[p['id'] for p in visible if p.get('personas')]}"
    )


def test_flag_off_returns_universal_only_zero_regression():
    """With the feature flag off the endpoint must behave exactly like
    pre-P1: only the 10 universal templates compete. Persona templates
    must not leak through."""
    primary, secondary, advanced = _replay_selection(
        _mf_heavy_ctx(), persona="mutual_fund_investor", persona_prompts_on=False
    )
    visible = primary + secondary + advanced
    assert not any(p.get("personas") for p in visible), (
        "flag=off: persona templates leaked through; "
        f"got: {[p['id'] for p in visible if p.get('personas')]}"
    )


def test_category_filter_narrows_results():
    """When category=tax is requested, every returned template must have
    intent_category=='tax'."""
    primary, secondary, advanced = _replay_selection(
        _mf_heavy_ctx(), persona="tax_saver", category="tax"
    )
    visible = primary + secondary + advanced
    assert visible, "tax filter returned zero prompts for tax_saver persona"
    bad = [p for p in visible if p.get("intent_category") != "tax"]
    assert not bad, f"category=tax leaked non-tax prompts: {[p['id'] for p in bad]}"
