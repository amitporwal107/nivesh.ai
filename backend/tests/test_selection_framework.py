"""Unit tests for the selection framework (services.selection) + builder wiring.

Pure-function tests — no DB, no network. Covers the spec acceptance criteria that
are verifiable without live data: hard gates (with negative/teeth fixtures), overlap
math + rejection, personalization (horizon/capacity/buyable/80C), and the audit
record. Data-dependent ACs (real AUM/age coverage, real holdings overlap) are gated
by spikes S1/S2/S4 and are NOT claimed here.
"""
import asyncio

import pytest

from services import selection as sel


# ── Hard gates ───────────────────────────────────────────────────────────────────
def _good_equity():
    return {"isin": "INF1", "scheme_name": "X Direct Growth", "aum_cr": 2000,
            "fund_age_years": 6, "manager_tenure_years": 4, "expense_ratio_direct": 0.4}


def test_aum_floor_excludes_sub_floor_equity():
    cand = {**_good_equity(), "aum_cr": 100}   # below ₹500cr equity floor
    res = sel.evaluate_gates(cand, asset_class="equity")
    assert res["passed"] is False
    g = next(x for x in res["gates"] if x["gate"] == "aum_floor")
    assert g["status"] == "failed"


def test_aum_floor_teeth_passes_when_above():
    res = sel.evaluate_gates(_good_equity(), asset_class="equity")
    assert res["passed"] is True
    assert all(x["status"] != "failed" for x in res["gates"])


def test_debt_floor_is_1000_not_500():
    # 700cr passes equity floor (500) but FAILS the debt floor (1000) — teeth.
    cand = {"isin": "D1", "scheme_name": "Bond Direct", "aum_cr": 700,
            "fund_age_years": 5, "manager_tenure_years": 3, "expense_ratio_direct": 0.3}
    assert sel.evaluate_gates(cand, asset_class="equity")["passed"] is True
    assert sel.evaluate_gates(cand, asset_class="debt")["passed"] is False


def test_track_record_gate_excludes_young_fund():
    cand = {**_good_equity(), "fund_age_years": 1.5}
    res = sel.evaluate_gates(cand, asset_class="equity")
    assert res["passed"] is False
    assert any(g["gate"] == "track_record" and g["status"] == "failed" for g in res["gates"])


def test_manager_tenure_gate():
    cand = {**_good_equity(), "manager_tenure_years": 0.5}
    res = sel.evaluate_gates(cand, asset_class="equity")
    assert any(g["gate"] == "manager_tenure" and g["status"] == "failed" for g in res["gates"])


def test_missing_field_is_not_evaluated_never_silent_pass():
    # No aum_cr at all -> aum_floor must be "not_evaluated", NOT "passed".
    cand = {"isin": "M1", "scheme_name": "Y Direct", "fund_age_years": 5,
            "manager_tenure_years": 3, "expense_ratio_direct": 0.4}
    res = sel.evaluate_gates(cand, asset_class="equity")
    g = next(x for x in res["gates"] if x["gate"] == "aum_floor")
    assert g["status"] == "not_evaluated"
    assert g["reason"] == "data_unavailable"


def test_debt_deferred_gates_declared_not_evaluated():
    cand = {"isin": "D2", "scheme_name": "Bond Direct", "aum_cr": 2000,
            "fund_age_years": 5, "manager_tenure_years": 3, "expense_ratio_direct": 0.3}
    res = sel.evaluate_gates(cand, asset_class="debt")
    statuses = {g["gate"]: g["status"] for g in res["gates"]}
    assert statuses["debt_safety"] == "not_evaluated"
    assert statuses["category_integrity"] == "not_evaluated"
    assert res["passed"] is True   # not_evaluated does not fail the candidate


def test_gates_do_not_loosen_by_profile():
    # evaluate_gates takes no profile; the same sub-floor fund is rejected always.
    cand = {**_good_equity(), "aum_cr": 100}
    eligible, rejected = sel.filter_eligible([cand], asset_class="equity")
    assert eligible == [] and len(rejected) == 1
    assert "aum_floor" in rejected[0]["gate_failed"]


def test_filter_eligible_splits_and_tags():
    good, bad = _good_equity(), {**_good_equity(), "isin": "BAD", "fund_age_years": 1}
    eligible, rejected = sel.filter_eligible([good, bad], asset_class="equity")
    assert [c["isin"] for c in eligible] == ["INF1"]
    assert rejected[0]["isin"] == "BAD" and "track_record" in rejected[0]["gate_failed"]


# ── Overlap ──────────────────────────────────────────────────────────────────────
def test_compute_overlap_sum_of_min_fractions():
    a = {"S1": 0.30, "S2": 0.20, "S3": 0.10}
    b = {"S1": 0.25, "S2": 0.25, "S4": 0.50}
    # min(.30,.25)+min(.20,.25) = .25+.20 = .45
    assert sel.compute_overlap(a, b) == pytest.approx(0.45)


def test_compute_overlap_normalizes_percentages():
    a = {"S1": 30, "S2": 20}
    b = {"S1": 25, "S2": 25}
    assert sel.compute_overlap(a, b) == pytest.approx(0.45)


def test_compute_overlap_disjoint_is_zero():
    assert sel.compute_overlap({"S1": 1.0}, {"S2": 1.0}) == 0.0


def test_reject_overlapping_drops_second_high_overlap():
    ranked = [{"isin": "A"}, {"isin": "B"}, {"isin": "C"}]
    holdings = {
        "A": {"S1": 0.5, "S2": 0.5},
        "B": {"S1": 0.5, "S2": 0.45},   # overlap vs A = 0.95 > 0.40 -> reject
        "C": {"S9": 1.0},               # overlap vs A = 0 -> keep
    }
    selected, rejected = sel.reject_overlapping(ranked, holdings_by_key=holdings, threshold=0.40)
    assert [s["isin"] for s in selected] == ["A", "C"]
    assert [r["isin"] for r in rejected] == ["B"]
    assert rejected[0]["overlap_with"] == "A"


def test_reject_overlapping_missing_holdings_not_evaluated_kept():
    ranked = [{"isin": "A"}, {"isin": "B"}]
    holdings = {"A": {"S1": 1.0}}   # B has none
    selected, rejected = sel.reject_overlapping(ranked, holdings_by_key=holdings, threshold=0.40)
    assert [s["isin"] for s in selected] == ["A", "B"]
    assert selected[1]["overlap_status"] == "not_evaluated"
    assert rejected == []


def test_reject_overlapping_holdingless_sibling_does_not_suppress_rejection():
    # Regression (adversarial verifier): a selected sibling B with NO holdings must
    # not poison the C-vs-A evaluation. C overlaps A at 95% (>0.40) and MUST be
    # rejected — not kept as "not_evaluated" just because B lacked holdings.
    ranked = [{"isin": "A"}, {"isin": "B"}, {"isin": "C"}]
    holdings = {
        "A": {"S1": 0.5, "S2": 0.5},
        # B intentionally absent (no holdings)
        "C": {"S1": 0.5, "S2": 0.45},   # overlap vs A = 0.95
    }
    selected, rejected = sel.reject_overlapping(ranked, holdings_by_key=holdings, threshold=0.40)
    sel_isins = [s["isin"] for s in selected]
    assert sel_isins == ["A", "B"]          # B kept (not_evaluated), C rejected
    assert [r["isin"] for r in rejected] == ["C"]
    assert rejected[0]["overlap_with"] == "A"
    assert rejected[0]["overlap_status"] == "rejected"


def test_normalize_weights_concentrated_fractions_not_misread_as_pct():
    # Two funds each 80%/80% fractional -> overlap should be ~1.6-clamped, not /100.
    a = {"S1": 0.8, "S2": 0.8}
    assert sel.compute_overlap(a, a) == pytest.approx(1.6)   # not 0.016


def test_direct_plan_bare_expense_ratio_is_not_evaluated_not_failed():
    # A fund with an expense_ratio but no plan signal must be "not_evaluated",
    # never "failed" (bare ER is not evidence of the plan type).
    cand = {"isin": "P1", "scheme_name": "Some Fund", "aum_cr": 2000,
            "fund_age_years": 5, "manager_tenure_years": 3, "expense_ratio": 0.9}
    res = sel.evaluate_gates(cand, asset_class="equity")
    g = next(x for x in res["gates"] if x["gate"] == "direct_plan")
    assert g["status"] == "not_evaluated"
    assert res["passed"] is True


# ── Personalization ──────────────────────────────────────────────────────────────
def test_horizon_under_3y_blocks_equity():
    assert sel.horizon_allows_equity(2) is False
    assert sel.horizon_allows_equity(3) is True
    assert sel.horizon_allows_equity(10) is True


def test_capacity_cap_scales_with_sip():
    assert sel.capacity_fund_cap(5000, hard_cap=3) == 2      # ₹5k -> 2, not 12
    assert sel.capacity_fund_cap(20000, hard_cap=3) == 3
    assert sel.capacity_fund_cap(20000, hard_cap=2) == 2     # never exceeds hard cap
    assert sel.capacity_fund_cap(None, hard_cap=3) == 3


def test_intersect_buyable_drops_non_buyable():
    cands = [{"isin": "A"}, {"isin": "B"}, {"isin": "C"}]
    kept, dropped = sel.intersect_buyable(cands, {"A", "C"})
    assert [c["isin"] for c in kept] == ["A", "C"]
    assert [c["isin"] for c in dropped] == ["B"]


def test_intersect_buyable_none_set_is_passthrough_fallback():
    cands = [{"isin": "A"}, {"isin": "B"}]
    kept, dropped = sel.intersect_buyable(cands, None)
    assert len(kept) == 2 and dropped == []


def test_is_elss():
    assert sel.is_elss("ELSS") is True
    assert sel.is_elss("Equity Linked Savings Scheme (ELSS)") is True
    assert sel.is_elss("Flexi Cap Fund") is False


# ── Audit ────────────────────────────────────────────────────────────────────────
def test_audit_record_has_all_required_fields():
    rec = sel.build_audit_record(
        inputs={"risk_profile": "Moderate", "horizon_years": 10},
        selected=[{"isin": "A", "scheme_name": "X", "quality_score": 80,
                   "gate_results": [], "overlap_status": "evaluated"}],
        rejected=[{"isin": "B", "gate_failed": ["aum_floor"], "gate_reason": "small"}],
        weights={"risk_adjusted": 25},
        scoring_config_version="1.0.0",
        generated_at="2026-06-28T00:00:00Z",
    )
    for field in ("inputs", "weights", "scoring_config_version", "generated_at", "picks", "rejected"):
        assert field in rec, f"audit missing {field}"
    assert rec["scoring_config_version"] == "1.0.0"
    assert rec["picks"][0]["isin"] == "A"
    assert rec["rejected"][0]["gate_failed"] == ["aum_floor"]


def test_audit_generated_at_autofilled_when_absent():
    rec = sel.build_audit_record(inputs={}, selected=[], rejected=[], weights={},
                                 scoring_config_version="1.0.0")
    assert rec["generated_at"]  # non-empty ISO timestamp


# ── Orchestration ────────────────────────────────────────────────────────────────
def test_select_for_sleeve_full_pipeline():
    cands = [
        {"isin": "A", "scheme_name": "A Direct", "aum_cr": 2000, "fund_age_years": 6,
         "manager_tenure_years": 4, "expense_ratio_direct": 0.4, "quality_score": 90},
        {"isin": "B", "scheme_name": "B Direct", "aum_cr": 50, "fund_age_years": 6,   # sub-floor -> gated out
         "manager_tenure_years": 4, "expense_ratio_direct": 0.4, "quality_score": 88},
        {"isin": "C", "scheme_name": "C Direct", "aum_cr": 1500, "fund_age_years": 5,
         "manager_tenure_years": 3, "expense_ratio_direct": 0.5, "quality_score": 70},
    ]
    res = sel.select_for_sleeve(cands, asset_class="equity", monthly_sip_rs=20000,
                                overlap_threshold=0.40, max_holdings=3)
    isins = [s["isin"] for s in res["selected"]]
    assert "B" not in isins                       # gated by aum_floor
    assert isins == ["A", "C"]
    assert any("aum_floor" in r.get("gate_failed", []) for r in res["rejected"])


def test_select_for_sleeve_capacity_caps_count():
    cands = [{"isin": f"I{i}", "scheme_name": f"F{i} Direct", "aum_cr": 2000,
              "fund_age_years": 6, "manager_tenure_years": 4, "expense_ratio_direct": 0.4,
              "quality_score": 90 - i} for i in range(5)]
    res = sel.select_for_sleeve(cands, asset_class="equity", monthly_sip_rs=5000,
                                overlap_threshold=0.40, max_holdings=3)
    assert len(res["selected"]) == 2   # ₹5k SIP -> 2 funds even though 5 eligible


# ── Builder wiring (category mode → no DB/network) ────────────────────────────────
def test_builder_allocation_regression_category_mode(monkeypatch):
    """Moderate/10y allocation matches the governed policy and sums to 100, and
    audit is null in category-and-model mode (names suppressed)."""
    from services import allocation_policy as _p
    from services import sleeve_builder
    monkeypatch.setattr(_p, "names_allowed", lambda: False)

    out = asyncio.get_event_loop().run_until_complete(
        sleeve_builder.build_sleeve_portfolio("moderate", horizon_years=10))

    expected = _p.apply_glide_path(_p.strategic_allocation("Moderate", "long"), 10)
    for cls in ("equity", "debt", "gold", "cash"):
        assert out["allocation"][cls] == pytest.approx(expected.get(cls, 0), abs=0.2)
    assert sum(out["allocation"].values()) == pytest.approx(100, abs=0.2)
    assert out["audit"] is None                      # category mode -> no named picks
    assert out["compliance"]["names_allowed"] is False
