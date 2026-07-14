"""Pure unit tests for portfolio_result_transformer.

No DB / no network. We feed hand-built builder_output dicts shaped exactly
like services.sleeve_builder.build_sleeve_portfolio output and assert the
honest card behaviour required by the deliverable:

  - category mode emits ZERO scheme names + the disclaimer
  - named mode renders one card per non-empty sleeve
  - a not_evaluated gate is NOT rendered as a pass (distinct severity)
  - an empty sleeve is surfaced with its reason (never silently dropped)
  - the mandatory disclosures block is always present
"""
from __future__ import annotations

import json

from services.copilot_tools.portfolio_result_transformer import (
    portfolio_result_to_cards,
    DISCLOSURES,
)

SCHEME_A = "Acme Bluechip Direct Growth"
SCHEME_B = "Beta Flexi Cap Direct Growth"
SCHEME_C = "Gamma Mid Cap Direct Growth"


def _category_output():
    """Compliance default: names NOT allowed -> category guidance only."""
    return {
        "risk_profile": "moderate",
        "horizon_years": 10.0,
        "allocation": {"equity": 60.0, "debt": 30.0, "gold": 5.0, "cash": 5.0},
        "sleeves": [
            {"key": "equity_core", "asset_class": "equity", "label": "Equity - Core",
             "detail": "Index & Large-cap", "category_members": ["Index Funds", "Large Cap"],
             "target_pct": 36.0, "funds": []},
            {"key": "debt_corporate_bond_fund", "asset_class": "debt", "label": "Corporate Bond",
             "detail": "Debt", "category_members": ["Corporate Bond"],
             "target_pct": 30.0, "funds": []},
        ],
        "validation": None,
        "audit": None,
        "compliance": {
            "mode": "category_and_model",
            "names_allowed": False,
            "stocks_allowed": False,
            "disclaimer": "This is model and category-level guidance, not a "
                          "recommendation of specific schemes or stocks. Mutual "
                          "funds are subject to market risk.",
        },
        "policy_version": "1.0.0",
    }


def _named_output():
    """Names allowed; one populated equity sleeve, one EMPTY debt sleeve."""
    return {
        "risk_profile": "aggressive",
        "horizon_years": 12.0,
        "allocation": {"equity": 75.0, "debt": 15.0, "gold": 5.0, "cash": 5.0},
        "sleeves": [
            {
                "key": "equity_core", "asset_class": "equity", "label": "Equity - Core",
                "detail": "Index & Large-cap", "category_members": ["Index Funds", "Large Cap"],
                "target_pct": 45.0,
                "funds": [
                    {
                        "scheme_name": SCHEME_A, "isin": "INF000A01010",
                        "quality_score": 82.0,
                        "gate_results": [
                            {"gate": "min_quality", "status": "passed", "reason": ""},
                            {"gate": "aum_floor", "status": "passed", "reason": ""},
                            # Overlap gate could not be evaluated -> NOT a pass.
                            {"gate": "overlap", "status": "not_evaluated",
                             "reason": "no holdings data"},
                        ],
                        "overlap_status": "not_evaluated", "overlap_pct": None,
                    },
                    {
                        "scheme_name": SCHEME_B, "isin": "INF000B02020",
                        "quality_score": 77.0,
                        "gate_results": [
                            {"gate": "min_quality", "status": "passed", "reason": ""},
                            {"gate": "expense_ceiling", "status": "failed",
                             "reason": "expense ratio above ceiling"},
                        ],
                        "overlap_status": "evaluated", "overlap_pct": 0.12,
                    },
                ],
                "selection": {"rejected": [], "shortlist_size": 4, "cap_applied": True},
            },
            {
                "key": "debt_gilt_fund", "asset_class": "debt", "label": "Gilt",
                "detail": "Debt", "category_members": ["Gilt"],
                "target_pct": 15.0,
                "funds": [],  # empty after gates
                "selection": {
                    "rejected": [
                        {"scheme_name": SCHEME_C, "isin": "INF000C03030",
                         "gate_failed": ["min_quality"],
                         "gate_reason": "quality_score below minimum",
                         "overlap_status": "not_evaluated"},
                    ],
                    "shortlist_size": 1, "cap_applied": False,
                },
            },
        ],
        "validation": {"passed": True, "summary": "All gates passed"},
        "audit": {"picks": [], "rejected": []},
        "compliance": {
            "mode": "named_scheme",
            "names_allowed": True,
            "stocks_allowed": False,
            "disclaimer": None,
        },
        "policy_version": "1.0.0",
    }


def _all_text(card):
    """Flatten a card envelope to a single searchable string.

    ensure_ascii=False keeps unicode (em-dash, ₹) intact so substring
    assertions match the human-readable source text rather than \\uXXXX escapes.
    """
    return json.dumps(card, ensure_ascii=False)


# ── Envelope shape ──────────────────────────────────────────────────────────

def test_cards_are_insight_card_envelopes():
    cards = portfolio_result_to_cards(_named_output())
    assert isinstance(cards, list) and cards
    for c in cards:
        assert c["kind"] == "insight_card"
        assert "title" in c and "freshness" in c and "agent" in c
        assert "hero" in c["data"]  # the frontend requires a hero


# ── Category mode: zero scheme names + disclaimer ───────────────────────────

def test_category_mode_has_no_scheme_names():
    out = _category_output()
    cards = portfolio_result_to_cards(out)
    blob = " ".join(_all_text(c) for c in cards)
    for name in (SCHEME_A, SCHEME_B, SCHEME_C):
        assert name not in blob, f"scheme name leaked in category mode: {name}"


def test_category_mode_has_disclaimer_text():
    out = _category_output()
    cards = portfolio_result_to_cards(out)
    blob = " ".join(_all_text(c) for c in cards)
    assert out["compliance"]["disclaimer"] in blob


def test_category_mode_shows_allocation():
    cards = portfolio_result_to_cards(_category_output())
    guidance = cards[0]
    kpi_labels = {k["label"] for k in guidance["data"]["kpis"]}
    assert "Equity" in kpi_labels and "Debt" in kpi_labels


# ── Named mode: one card per non-empty sleeve ───────────────────────────────

def test_named_mode_one_card_per_nonempty_sleeve():
    cards = portfolio_result_to_cards(_named_output())
    titles = [c["title"] for c in cards]
    # Equity - Core has funds -> its own card.
    assert "Equity - Core" in titles
    # Exactly one card whose title is the populated sleeve label.
    assert titles.count("Equity - Core") == 1


def test_named_mode_lists_each_pick_as_structured_field():
    cards = portfolio_result_to_cards(_named_output())
    sleeve_card = next(c for c in cards if c["title"] == "Equity - Core")
    finding_titles = [f["title"] for f in sleeve_card["data"]["findings"]]
    assert SCHEME_A in finding_titles
    assert SCHEME_B in finding_titles
    # Score is a structured field, not embedded in narration.
    a_finding = next(f for f in sleeve_card["data"]["findings"] if f["title"] == SCHEME_A)
    assert a_finding["impact_value"] == "82"
    assert a_finding["impact_label"] == "score"


def test_pick_name_never_inside_recommendation_string():
    """Engine-vs-narration: a scheme name must NOT appear in the free-text
    recommendation summary/rationale — only in structured findings/kpis."""
    cards = portfolio_result_to_cards(_named_output())
    sleeve_card = next(c for c in cards if c["title"] == "Equity - Core")
    rec = sleeve_card["data"]["recommendation"]
    rec_text = (rec.get("summary") or "") + " " + (rec.get("rationale") or "")
    assert SCHEME_A not in rec_text
    assert SCHEME_B not in rec_text


# ── not_evaluated gate is NOT a pass (distinct severity) ─────────────────────

def test_not_evaluated_gate_is_not_rendered_as_pass():
    cards = portfolio_result_to_cards(_named_output())
    sleeve_card = next(c for c in cards if c["title"] == "Equity - Core")
    a_finding = next(f for f in sleeve_card["data"]["findings"] if f["title"] == SCHEME_A)
    detail = a_finding["detail"]
    # The overlap gate was not_evaluated — it must read "not checked", never "OK".
    assert "overlap: not checked" in detail
    assert "overlap: OK" not in detail


def test_not_evaluated_gate_distinct_from_passed_severity():
    from services.copilot_tools.portfolio_result_transformer import (
        _gate_summary, _GATE_SEVERITY,
    )
    assert _GATE_SEVERITY["passed"] == "healthy"
    assert _GATE_SEVERITY["failed"] == "critical"
    assert _GATE_SEVERITY["not_evaluated"] == "medium"
    # And the three are mutually distinct.
    assert len({_GATE_SEVERITY["passed"], _GATE_SEVERITY["failed"],
                _GATE_SEVERITY["not_evaluated"]}) == 3
    # A fund with one passed + one not_evaluated gate -> worst is medium,
    # never healthy (a not_evaluated gate must downgrade the verdict).
    summary = _gate_summary([
        {"gate": "min_quality", "status": "passed", "reason": ""},
        {"gate": "overlap", "status": "not_evaluated", "reason": "no data"},
    ])
    assert summary["worst_severity"] == "medium"
    assert summary["not_evaluated"] == 1


def test_failed_gate_drives_critical_severity():
    cards = portfolio_result_to_cards(_named_output())
    sleeve_card = next(c for c in cards if c["title"] == "Equity - Core")
    b_finding = next(f for f in sleeve_card["data"]["findings"] if f["title"] == SCHEME_B)
    # Scheme B failed expense_ceiling -> high priority finding.
    assert b_finding["priority"] == "high"
    assert "expense_ceiling: FAILED" in b_finding["detail"]


# ── Empty sleeve surfaced with reason (never silently dropped) ───────────────

def test_empty_sleeve_is_surfaced_with_reason():
    cards = portfolio_result_to_cards(_named_output())
    # Gilt sleeve had no funds — it must still produce a card.
    gilt = next((c for c in cards if c["title"].startswith("Gilt")), None)
    assert gilt is not None, "empty sleeve was silently dropped"
    blob = _all_text(gilt)
    assert "no eligible fund" in blob.lower()
    # The rejection reason from selection must be surfaced.
    assert "quality_score below minimum" in blob


def test_empty_sleeve_lists_rejected_candidate():
    cards = portfolio_result_to_cards(_named_output())
    gilt = next(c for c in cards if c["title"].startswith("Gilt"))
    finding_titles = [f["title"] for f in gilt["data"]["findings"]]
    assert SCHEME_C in finding_titles


# ── Disclosures present (both modes) ────────────────────────────────────────

def test_disclosures_present_named_mode():
    cards = portfolio_result_to_cards(_named_output())
    blob = " ".join(_all_text(c) for c in cards)
    for d in DISCLOSURES:
        assert d in blob


def test_disclosures_present_category_mode():
    cards = portfolio_result_to_cards(_category_output())
    blob = " ".join(_all_text(c) for c in cards)
    for d in DISCLOSURES:
        assert d in blob


def test_disclosures_card_is_last():
    cards = portfolio_result_to_cards(_named_output())
    assert cards[-1]["title"] == "Disclosures"


# ── Mode selection edge cases ───────────────────────────────────────────────

def test_names_allowed_but_all_sleeves_empty_falls_back_to_category():
    out = _named_output()
    # Strip all funds — names allowed, but nothing to show by name.
    for s in out["sleeves"]:
        s["funds"] = []
    cards = portfolio_result_to_cards(out)
    blob = " ".join(_all_text(c) for c in cards)
    # No scheme names from picks should appear (there are none); the first card
    # is the category guidance card, not a per-sleeve named card.
    assert cards[0]["data"]["hero"]["eyebrow"] == "Model portfolio"


def test_malformed_input_still_returns_disclosures():
    cards = portfolio_result_to_cards(None)  # type: ignore[arg-type]
    assert cards and cards[-1]["title"] == "Disclosures"
