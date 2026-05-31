"""
AC coverage tests — PRD_RECOMMENDATION_ENGINE §4 acceptance criteria.

Each test is tagged with its AC number so Gate 1 results map directly to the spec.
All tests are pure Python — no DB, no external calls.
"""
import sys
sys.path.insert(0, "/app/backend")

import pytest
from tests.test_recommendation_engine.fixtures import (
    _BASE_RULES_CFG, _mf_holding, _mf_investment,
    empty_context, medium_portfolio_context,
)
from services.recommendation_engine.orchestrator import (
    build_context, run_engine_pipeline, _signal_to_action,
)
from services.recommendation_engine.context import EngineSignal
from services.recommendation_engine.engines.category_suitability_engine import CategorySuitabilityEngine
from services.recommendation_engine.engines.concentration_engine import ConcentrationEngine


# ── AC-1 · requires_persona gate ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ac1_no_persona_returns_gate_flag():
    """Given no risk persona, pipeline returns [] + requires_persona=True."""
    active_goals = [{"goal_name": "House", "goal_type": "home", "horizon_years": 3,
                     "goal_health": "on_track", "health_status": "on_track",
                     "on_track_pct": 80, "shortfall_rs": 0, "gap_rs": 0,
                     "monthly_sip_rs": 5000, "priority": "high"}]
    actions, _sim, gate = await run_engine_pipeline(
        user_id="u_ac1",
        risk_profile="",          # empty string + no score → get_persona_profile returns None
        total_value_rs=1_000_000,
        holdings=[], mf_holdings=[], stock_holdings=[],
        portfolio_intelligence={"mf_investments": [], "pairwise_overlap": [], "catalog": {}},
        mf_investments=[], exit_candidates=[],
        v3_scores={}, rules_cfg=_BASE_RULES_CFG, signals=[],
        goal_evaluations=active_goals,
        risk_score_numeric=None,
    )
    assert actions == []
    assert gate["requires_persona"] is True
    assert gate["requires_goal"] is False


# ── AC-2 · requires_goal gate ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ac2_no_goals_returns_gate_flag():
    """Given risk persona but zero goals, pipeline returns [] + requires_goal=True."""
    actions, _sim, gate = await run_engine_pipeline(
        user_id="u_ac2",
        risk_profile="moderate",
        total_value_rs=1_000_000,
        holdings=[], mf_holdings=[], stock_holdings=[],
        portfolio_intelligence={"mf_investments": [], "pairwise_overlap": [], "catalog": {}},
        mf_investments=[], exit_candidates=[],
        v3_scores={}, rules_cfg=_BASE_RULES_CFG, signals=[],
        goal_evaluations=[],          # <-- no goals
        risk_score_numeric=50.0,
    )
    assert actions == []
    assert gate["requires_goal"] is True
    assert gate["requires_persona"] is False


# ── AC-4 · CS-2 Moderate small-cap sub-cap breach ────────────────────────────

def test_ac4_moderate_smallcap_trim_when_over_10pct():
    """Moderate user: small-cap > 10% of equity → TRIM signal."""
    # 18% small-cap (180K of 1M total)
    sc_fund = {**_mf_holding("Nippon Small Cap", 180_000, "small cap"), "instrument_id": "isin_SC"}
    mf_invest = {**_mf_investment("Nippon Small Cap", 180_000, "small cap", "NIPPON"),
                 "instrument_id": "isin_SC"}
    ctx = build_context(
        user_id="u1", risk_profile="moderate", total_value_rs=1_000_000,
        holdings=[sc_fund], mf_holdings=[sc_fund], stock_holdings=[],
        portfolio_intelligence={"mf_investments": [mf_invest], "pairwise_overlap": [], "catalog": {}},
        exit_candidates=[{"instrument_id": "isin_SC", "instrument_name": "Nippon Small Cap",
                          "exit_score": 6.0, "tax_impact": {"tax_liability": 1000}}],
        v3_scores={}, rules_cfg=_BASE_RULES_CFG, signals=[], risk_score_numeric=50.0,
    )
    engine = CategorySuitabilityEngine()
    sigs = engine.safe_generate(ctx)
    trim_sigs = [s for s in sigs if s.action_type == "TRIM" and "small" in (s.instrument_name or "").lower()]
    assert len(trim_sigs) >= 1, "Expected TRIM for small-cap over Moderate 10% sub-cap"
    assert all("SUB_CATEGORY_CAP_BREACH" in s.reason_codes for s in trim_sigs)


def test_ac4_moderate_smallcap_no_signal_under_10pct():
    """Moderate user: small-cap ≤ 10% of MF portfolio → no CS-2 TRIM signal.

    CS-2 computes sub-cap weight as fraction of total_mf_value (not total_value_rs),
    so we need a large-cap holding to dilute small-cap below 10%.
    """
    sc_fund = {**_mf_holding("Nippon Small Cap", 80_000, "small cap"), "instrument_id": "isin_SC"}
    lc_fund = {**_mf_holding("ICICI Large Cap", 920_000, "large cap"), "instrument_id": "isin_LC"}
    sc_invest = {**_mf_investment("Nippon Small Cap", 80_000, "small cap", "NIPPON"), "instrument_id": "isin_SC"}
    lc_invest = {**_mf_investment("ICICI Large Cap", 920_000, "large cap", "ICICI"), "instrument_id": "isin_LC"}
    ctx = build_context(
        user_id="u1", risk_profile="moderate", total_value_rs=1_000_000,
        holdings=[sc_fund, lc_fund], mf_holdings=[sc_fund, lc_fund], stock_holdings=[],
        portfolio_intelligence={
            "mf_investments": [sc_invest, lc_invest], "pairwise_overlap": [], "catalog": {},
        },
        exit_candidates=[], v3_scores={},
        rules_cfg=_BASE_RULES_CFG, signals=[], risk_score_numeric=50.0,
    )
    engine = CategorySuitabilityEngine()
    sigs = engine.safe_generate(ctx)
    # small-cap = 80K / 1000K = 8% of MF total → below Moderate 10% sub-cap
    trim_sigs = [s for s in sigs if s.action_type == "TRIM" and "small" in (s.instrument_name or "").lower()]
    assert len(trim_sigs) == 0, "No CS-2 TRIM expected when small-cap is 8% (below 10% Moderate sub-cap)"


# ── AC-7 · CC-1 single-holding concentration ─────────────────────────────────

def test_ac7_conservative_concentration_trim_above_5pct():
    """Conservative cap is 5%; a 10% holding must emit TRIM."""
    # 100K in a 1M portfolio = 10% → above Conservative 5% cap
    h = {**_mf_holding("Large Cap Fund", 100_000, "Large Cap"), "instrument_id": "isin_LC"}
    ctx = build_context(
        user_id="u1", risk_profile="Conservative", total_value_rs=1_000_000,
        holdings=[h], mf_holdings=[h], stock_holdings=[],
        portfolio_intelligence={"mf_investments": [], "pairwise_overlap": [], "catalog": {}},
        exit_candidates=[], v3_scores={},
        rules_cfg=_BASE_RULES_CFG, signals=[], risk_score_numeric=75.0,
    )
    engine = ConcentrationEngine()
    sigs = engine.safe_generate(ctx)
    cc1_sigs = [s for s in sigs if s.rule_label == "CC-1"]
    assert len(cc1_sigs) >= 1, "Expected CC-1 TRIM for 10% holding vs Conservative 5% cap"
    assert all(s.action_type == "TRIM" for s in cc1_sigs)


def test_ac7_aggressive_no_concentration_at_14pct():
    """Aggressive cap is 15%; a 14% holding must NOT emit TRIM."""
    h = {**_mf_holding("Small Cap Fund", 140_000, "Small Cap"), "instrument_id": "isin_SC"}
    ctx = build_context(
        user_id="u1", risk_profile="Aggressive", total_value_rs=1_000_000,
        holdings=[h], mf_holdings=[h], stock_holdings=[],
        portfolio_intelligence={"mf_investments": [], "pairwise_overlap": [], "catalog": {}},
        exit_candidates=[], v3_scores={},
        rules_cfg=_BASE_RULES_CFG, signals=[], risk_score_numeric=20.0,
    )
    engine = ConcentrationEngine()
    sigs = engine.safe_generate(ctx)
    cc1_sigs = [s for s in sigs if s.rule_label == "CC-1"]
    assert len(cc1_sigs) == 0, "No CC-1 TRIM expected at 14% for Aggressive (cap=15%)"


# ── AC-9 · ELSS lock-in → no EXIT ────────────────────────────────────────────

def test_ac9_elss_locked_exit_suppressed():
    """ELSS holding within lock-in window must not produce an un-suppressed EXIT."""
    from datetime import date, timedelta
    from services.recommendation_engine.arbitration_engine import ArbitrationEngine
    from services.recommendation_engine.portfolio_impact_engine import PortfolioImpactEngine

    recent_buy = (date.today() - timedelta(days=180)).isoformat()  # 6 months ago → still locked
    elss_h = {
        "asset_type": "mutual_fund",
        "name": "Quant ELSS Tax Saver Fund - Direct Growth",
        "quantity": 1000, "current_price": 200, "buy_price": 180,
        "buy_date": recent_buy,
        "category": "elss",
        "instrument_id": "isin_ELSS_01",
        "user_id": "u1",
    }
    ctx = build_context(
        user_id="u1", risk_profile="conservative", total_value_rs=200_000,
        holdings=[elss_h], mf_holdings=[elss_h], stock_holdings=[],
        portfolio_intelligence={"mf_investments": [], "pairwise_overlap": [], "catalog": {}},
        exit_candidates=[{"instrument_id": "isin_ELSS_01",
                          "instrument_name": "Quant ELSS Tax Saver Fund - Direct Growth",
                          "exit_score": 8.0, "tax_impact": {"tax_liability": 5000}}],
        v3_scores={}, rules_cfg=_BASE_RULES_CFG, signals=[], risk_score_numeric=75.0,
    )

    # Run DataValidationEngine to populate tax_suppressed_instrument_ids
    from services.recommendation_engine.engines.data_validation_engine import DataValidationEngine
    DataValidationEngine().safe_generate(ctx)

    # Verify the ELSS is locked
    assert "isin_ELSS_01" in ctx.tax_suppressed_instrument_ids, "DV-4 must mark ELSS as locked"

    # Simulate an EXIT signal for the ELSS (as CS-1 would emit for Conservative)
    exit_sig = EngineSignal(
        signal_id="test::elss_exit",
        engine_name="CategorySuitabilityEngine", rule_label="CS-1",
        action_type="EXIT", instrument_id="isin_ELSS_01",
        instrument_name="Quant ELSS Tax Saver Fund",
        amount_rs=200_000, base_score=8.0, confidence=0.9,
        reason_codes=["CATEGORY_SUITABILITY_BREACH"], reason_text="ELSS not allowed.",
    )

    # Arbitration must suppress it
    weighted = PortfolioImpactEngine().apply([exit_sig], ctx)
    arbitrated = ArbitrationEngine().arbitrate(weighted, ctx)
    active = [s for s in arbitrated if not s.suppressed]
    assert len(active) == 0, "EXIT signal for locked ELSS must be suppressed"
    suppressed = [s for s in arbitrated if s.suppressed]
    assert len(suppressed) == 1


# ── AC-10 · PRD §12 output schema completeness ───────────────────────────────

def test_ac10_all_prd12_fields_present():
    """Every _signal_to_action output must contain all 11 PRD §12 field names."""
    required_fields = {"id", "action", "magnitude", "execution", "severity",
                       "requires_confirmation", "reason_text", "expected_effect",
                       "confidence", "status", "asset_name"}
    sig = EngineSignal(
        signal_id="test::schema",
        engine_name="TestEngine", rule_label="R",
        action_type="EXIT", instrument_id="isin_001",
        instrument_name="Test Fund",
        amount_rs=100_000, base_score=7.0, confidence=0.8,
        reason_codes=["TEST"], reason_text="Test reason.",
        severity="mismatch", execution_path="stagger",
    )
    action = _signal_to_action(sig, priority=1)
    missing = required_fields - set(action.keys())
    assert not missing, f"PRD §12 fields missing from action: {missing}"
    # expected_effect must be a 3-field struct
    ee = action["expected_effect"]
    assert "risk_band_delta" in ee
    assert "score_delta_pct" in ee
    assert "funding_probability_delta" in ee


# ── AC-11 · reason text in persona/goal terms ─────────────────────────────────

def test_ac11_cs1_reason_references_persona():
    """CS-1 reason text must mention the persona type, not a raw score."""
    sc_fund = {**_mf_holding("Nippon Small Cap", 200_000, "small cap"), "instrument_id": "isin_SC"}
    ctx = build_context(
        user_id="u1", risk_profile="Conservative", total_value_rs=200_000,
        holdings=[sc_fund], mf_holdings=[sc_fund], stock_holdings=[],
        portfolio_intelligence={
            "mf_investments": [_mf_investment("Nippon Small Cap", 200_000, "small cap", "NIPPON")],
            "pairwise_overlap": [], "catalog": {},
        },
        exit_candidates=[], v3_scores={},
        rules_cfg=_BASE_RULES_CFG, signals=[], risk_score_numeric=75.0,
    )
    engine = CategorySuitabilityEngine()
    sigs = engine.safe_generate(ctx)
    exit_sigs = [s for s in sigs if s.action_type == "EXIT"]
    assert exit_sigs, "Expected EXIT signal for Conservative + small-cap"
    reason = exit_sigs[0].reason_text.lower()
    assert "conservative" in reason, f"Reason must reference persona type, got: {reason!r}"
    # Must NOT say "quality score" or "score < X" — that's the score terms we're avoiding
    assert "quality_score" not in reason


# ── AC-13 · tax_impact non-null on EXIT/TRIM with candidate ──────────────────

def test_ac13_exit_signal_has_tax_impact():
    """An EXIT signal from CS-1 with a candidate must carry non-empty tax_impact.

    CS-1 stashes _holding + _candidate; _signal_to_action reads tax_impact from
    the candidate when holding is present.
    """
    # Use exact scheme name so fuzzy_match_holding succeeds
    fund_name = "Nippon Small Cap Fund - Direct Growth"
    sc_fund = {
        "asset_type": "mutual_fund", "name": fund_name,
        "quantity": 1000, "current_price": 200,
        "buy_price": 180, "category": "small cap",
        "instrument_id": "isin_SC", "user_id": "u1",
    }
    mf_invest = {
        "scheme_name": fund_name,
        "amount_rs": 200_000, "category": "small cap",
        "amc": "NIPPON", "resolved": True,
        "instrument_id": "isin_SC",
    }
    ctx = build_context(
        user_id="u1", risk_profile="Conservative", total_value_rs=200_000,
        holdings=[sc_fund], mf_holdings=[sc_fund], stock_holdings=[],
        portfolio_intelligence={
            "mf_investments": [mf_invest],
            "pairwise_overlap": [], "catalog": {},
        },
        exit_candidates=[{
            "instrument_id": "isin_SC",
            "instrument_name": fund_name,
            "exit_score": 7.0,
            "tax_impact": {"tax_liability": 8500, "stcg": 0, "ltcg": 8500},
        }],
        v3_scores={}, rules_cfg=_BASE_RULES_CFG, signals=[], risk_score_numeric=75.0,
    )
    engine = CategorySuitabilityEngine()
    sigs = engine.safe_generate(ctx)
    exit_sigs = [s for s in sigs if s.action_type == "EXIT"]
    assert exit_sigs, "Expected EXIT signal"

    action = _signal_to_action(exit_sigs[0], priority=1)
    ti = action.get("tax_impact")
    assert ti, f"tax_impact must be non-empty dict on EXIT, got: {ti!r}"
    assert ti.get("tax_liability") == 8500


def test_ac13_trim_signal_has_tax_impact():
    """A TRIM signal from CC-1 with a candidate must carry a tax_liability estimate."""
    # 200K in 200K portfolio = 100% → well above Conservative 5% cap
    h = {**_mf_holding("Large Cap Fund", 200_000, "Large Cap"), "instrument_id": "isin_LC"}
    ctx = build_context(
        user_id="u1", risk_profile="Conservative", total_value_rs=200_000,
        holdings=[h], mf_holdings=[h], stock_holdings=[],
        portfolio_intelligence={"mf_investments": [], "pairwise_overlap": [], "catalog": {}},
        exit_candidates=[{
            "instrument_id": "isin_LC",
            "instrument_name": "Large Cap Fund - Direct Growth",
            "exit_score": 5.0,
            "tax_impact": {"tax_liability": 4000},
        }],
        v3_scores={}, rules_cfg=_BASE_RULES_CFG, signals=[], risk_score_numeric=75.0,
    )
    engine = ConcentrationEngine()
    sigs = engine.safe_generate(ctx)
    trim_sigs = [s for s in sigs if s.action_type == "TRIM" and s.rule_label == "CC-1"]
    assert trim_sigs, "Expected CC-1 TRIM signal"

    action = _signal_to_action(trim_sigs[0], priority=1)
    ti = action.get("tax_impact")
    assert ti, f"tax_impact must be non-empty on TRIM, got: {ti!r}"
    assert ti.get("tax_liability", 0) > 0, "tax_liability must be > 0 (proportional fraction of 4000)"


# ── AC-14 · CC-2 sector concentration ────────────────────────────────────────

def test_ac14_sector_concentration_trim():
    """Sector > persona's max_single_sector_pct → CC-2 TRIM signal."""
    # Conservative max_single_sector_pct = 20%; Financial sector at 25%
    ctx = build_context(
        user_id="u1", risk_profile="Conservative", total_value_rs=1_000_000,
        holdings=[_mf_holding("Banking Fund", 250_000, "Sectoral/Thematic")],
        mf_holdings=[_mf_holding("Banking Fund", 250_000, "Sectoral/Thematic")],
        stock_holdings=[],
        portfolio_intelligence={
            "mf_investments": [],
            "pairwise_overlap": [], "catalog": {},
            "asset_allocation": {"equity_pct": 100},
            "sector_exposure": [
                {"sector": "Financial Services", "pct": 25.0},  # > Conservative 20% cap
                {"sector": "Technology", "pct": 15.0},
            ],
        },
        exit_candidates=[], v3_scores={},
        rules_cfg=_BASE_RULES_CFG, signals=[], risk_score_numeric=75.0,
    )
    engine = ConcentrationEngine()
    sigs = engine.safe_generate(ctx)
    cc2_sigs = [s for s in sigs if s.rule_label == "CC-2"]
    assert len(cc2_sigs) >= 1, "Expected CC-2 TRIM for Financial Services > 20% Conservative cap"
    assert all(s.action_type == "TRIM" for s in cc2_sigs)
    assert any("Financial" in (s.instrument_name or "") for s in cc2_sigs)


def test_ac14_sector_under_cap_no_signal():
    """Sector at 15% for Conservative (cap 20%) → no CC-2 signal."""
    ctx = build_context(
        user_id="u1", risk_profile="Conservative", total_value_rs=1_000_000,
        holdings=[], mf_holdings=[], stock_holdings=[],
        portfolio_intelligence={
            "mf_investments": [], "pairwise_overlap": [], "catalog": {},
            "asset_allocation": {"equity_pct": 100},
            "sector_exposure": [{"sector": "Financial Services", "pct": 15.0}],
        },
        exit_candidates=[], v3_scores={},
        rules_cfg=_BASE_RULES_CFG, signals=[], risk_score_numeric=75.0,
    )
    engine = ConcentrationEngine()
    sigs = engine.safe_generate(ctx)
    cc2_sigs = [s for s in sigs if s.rule_label == "CC-2"]
    assert len(cc2_sigs) == 0


# ── AC-16 · severity ordering ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ac16_severe_action_comes_first():
    """When a severe signal exists, it must be the first action in the output."""
    from services.recommendation_engine.arbitration_engine import ArbitrationEngine
    from services.recommendation_engine.portfolio_impact_engine import PortfolioImpactEngine

    ctx = medium_portfolio_context()
    minor_sig = EngineSignal(
        signal_id="test::minor",
        engine_name="TestEngine", rule_label="R",
        action_type="ADD", instrument_id=None,
        instrument_name="Debt Fund",
        amount_rs=50_000, base_score=5.0, confidence=0.7,
        severity="minor", reason_codes=["TEST"], reason_text="Minor drift.",
        dedup_key="ADD::debt_minor",
    )
    severe_sig = EngineSignal(
        signal_id="test::severe",
        engine_name="TestEngine", rule_label="R",
        action_type="EXIT", instrument_id="isin_FLEXI_CAP_FUND_A",
        instrument_name="Flexi Cap Fund A",
        amount_rs=400_000, base_score=4.0, confidence=0.9,
        severity="severe", reason_codes=["TEST"], reason_text="Severe mismatch.",
        dedup_key="EXIT::isin_FLEXI_CAP_FUND_A",
    )
    weighted = PortfolioImpactEngine().apply([minor_sig, severe_sig], ctx)
    arbitrated = ArbitrationEngine().arbitrate(weighted, ctx)
    active = [s for s in arbitrated if not s.suppressed]

    assert len(active) >= 2
    assert active[0].severity == "severe", (
        f"First action must be severe, got: {active[0].severity}"
    )


# ── AC-17 · multi-goal separate verdicts ─────────────────────────────────────

def test_ac17_two_goals_emit_separate_signals():
    """Retirement (20y, at_risk) and House (2y, at_risk) produce separate GBF signals."""
    from services.recommendation_engine.engines.goal_bucket_first_engine import GoalBucketFirstEngine

    two_goals = [
        {
            "goal_name": "Retirement", "goal_type": "retirement",
            "horizon_years": 20, "priority": "high", "monthly_sip_rs": 10000,
            "goal_health": "at_risk", "health_status": "at_risk",
            "on_track_pct": 55, "shortfall_rs": 5_000_000, "gap_rs": 5_000_000,
        },
        {
            "goal_name": "House Purchase", "goal_type": "home",
            "horizon_years": 2, "priority": "high", "monthly_sip_rs": 20000,
            "goal_health": "at_risk", "health_status": "at_risk",
            "on_track_pct": 40, "shortfall_rs": 1_500_000, "gap_rs": 1_500_000,
        },
    ]
    ctx = medium_portfolio_context(goal_evaluations=two_goals)
    engine = GoalBucketFirstEngine()
    sigs = engine.safe_generate(ctx)

    # Both goals are at_risk → 2 ADD signals, one per goal bucket
    assert len(sigs) == 2, f"Expected 2 GBF signals (one per goal), got {len(sigs)}"
    names = {s.__dict__.get("_goal_name") for s in sigs}
    assert "Retirement" in names
    assert "House Purchase" in names

    # Different asset classes: Retirement (20y) → equity; House (2y) → debt
    retirement_sig = next(s for s in sigs if s.__dict__.get("_goal_name") == "Retirement")
    house_sig = next(s for s in sigs if s.__dict__.get("_goal_name") == "House Purchase")
    assert "equity" in (retirement_sig.reason_text or "").lower() or \
           "Growth" in (retirement_sig.instrument_name or ""), \
        "Retirement 20y should suggest equity fund"
    assert "debt" in (house_sig.reason_text or "").lower() or \
           "bond" in (house_sig.instrument_name or "").lower() or \
           "liquid" in (house_sig.instrument_name or "").lower(), \
        "House 2y should suggest debt fund"


# ── AC-18 · ADD uses static fallback (xfail until DaaS wired in tests) ───────

@pytest.mark.xfail(reason="AC-18: AllocationEngine uses static fallback when DaaS unavailable in tests")
def test_ac18_add_candidate_from_daas():
    """ADD signal fund_name must come from NIDP DaaS top-quartile, not static list."""
    ctx = medium_portfolio_context()
    from services.recommendation_engine.engines.allocation_engine import AllocationEngine
    sigs = AllocationEngine().safe_generate(ctx)
    assert sigs, "AllocationEngine must fire (no debt in portfolio)"
    fund_name = sigs[0].instrument_name
    # DaaS-sourced fund names will have scheme_code or composite_score metadata
    # Static fallback uses fixed fund names like "ICICI Prudential Corporate Bond Fund"
    assert "ICICI Prudential Corporate Bond Fund" not in fund_name, \
        f"Expected live DaaS fund, got static fallback: {fund_name!r}"


# ── AC-20 · capacity_tolerance_diverged in gate_flags ────────────────────────

@pytest.mark.asyncio
async def test_ac20_capacity_tolerance_diverged_surfaced():
    """When capacity ≠ tolerance by ≥15pp, gate_flags must include the divergence flag."""
    active_goals = [{"goal_name": "Retirement", "goal_type": "retirement",
                     "horizon_years": 20, "goal_health": "on_track", "health_status": "on_track",
                     "on_track_pct": 85, "shortfall_rs": 0, "gap_rs": 0,
                     "monthly_sip_rs": 10000, "priority": "high"}]
    holdings = [_mf_holding("Flexi Cap Fund A", 1_000_000, "Flexi Cap")]
    _actions, _sim, gate = await run_engine_pipeline(
        user_id="u_ac20",
        risk_profile="moderate",
        total_value_rs=1_000_000,
        holdings=holdings,
        mf_holdings=holdings,
        stock_holdings=[],
        portfolio_intelligence={
            "mf_investments": [_mf_investment("Flexi Cap Fund A", 1_000_000, "Flexi Cap", "HDFC")],
            "pairwise_overlap": [], "catalog": {},
        },
        mf_investments=[_mf_investment("Flexi Cap Fund A", 1_000_000, "Flexi Cap", "HDFC")],
        exit_candidates=[],
        v3_scores={}, rules_cfg=_BASE_RULES_CFG, signals=[],
        goal_evaluations=active_goals,
        risk_score_numeric=50.0,
        capacity_score=70.0,    # 20pp gap → diverged
        tolerance_score=50.0,
        capacity_tolerance_diverged=True,
    )
    assert gate["capacity_tolerance_diverged"] is True, (
        "gate_flags must surface capacity_tolerance_diverged=True"
    )
