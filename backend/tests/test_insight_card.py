"""Insight Card schema + transformer tests.

User-visible failure modes this guards against (per the project rule
'list user-visible failure modes BEFORE coding, write one E2E test per
mode'):

  1. Schema rejects a card without a hero → never renders blank chrome.
  2. Severity tag mapping matches the documented thresholds → hero tint
     can't silently turn green during a 40% drawdown.
  3. Stress transformer produces a card with hero + recommendation +
     actions even when the breakdown list is empty (new user case).
  4. Stress transformer always carries education + actions for FAQs.
  5. JSON round-trip preserves all section fields → no quiet drop on
     wire transit.
"""
from __future__ import annotations

import json

import pytest

from models_copilot_widgets import (
    InsightCardData,
    InsightHero,
    InsightKpi,
    InsightFinding,
    InsightRecommendation,
    InsightImpact,
    InsightAction,
    InsightEducation,
    StressTestData,
    StressTestBreakdown,
    FundCardData,
    MarketBriefData,
    MarketBriefIndex,
    CompareTableData,
    CompareRow,
    SipPlanData,
    SipPlanAllocation,
    RebalancePlanData,
    RebalanceAction,
    TaxHarvestData,
    TaxHarvestCandidate,
    SectorRotationData,
    SectorPoint,
    OverlapRevealData,
    OverlapStock,
    WidgetEnvelope,
    FreshnessChip,
    AgentInfo,
)
from services.copilot_tools.insight_card_transformers import (
    stress_to_insight_card,
    fund_card_to_insight_card,
    market_brief_to_insight_card,
    compare_to_insight_card,
    sip_plan_to_insight_card,
    rebalance_to_insight_card,
    tax_harvest_to_insight_card,
    sector_rotation_to_insight_card,
    overlap_to_insight_card,
    _stress_severity,
)


# ── 1. Schema invariants ────────────────────────────────────────


def test_insight_card_requires_hero():
    """A card without a hero is invalid — there is no headline."""
    with pytest.raises(Exception):
        InsightCardData()  # type: ignore[call-arg]


def test_insight_card_minimal_card_is_valid():
    """A card with only a hero must validate — every other section is optional."""
    card = InsightCardData(hero=InsightHero(headline="Hello", severity="info"))
    assert card.hero.headline == "Hello"
    assert card.kpis == []
    assert card.findings == []
    assert card.recommendation is None
    assert card.actions == []


def test_insight_card_full_round_trip():
    """JSON round-trip preserves every section. Locks the wire contract."""
    card = InsightCardData(
        hero=InsightHero(severity="critical", eyebrow="COVID 2020",
                          headline="Projected impact: -34.2%",
                          primary_value="₹6,57,000", primary_label="Stressed value",
                          subtitle="Equity-heavy portfolio is vulnerable.", trend="down"),
        kpis=[
            InsightKpi(label="Current value", value="₹10,00,000"),
            InsightKpi(label="Drawdown", value="-34.2%", tone="critical", trend="down"),
        ],
        findings=[
            InsightFinding(priority="high", title="Axis Bluechip",
                            detail="-38% in this scenario",
                            impact_value="-₹1,20,000", impact_label="Value at risk"),
        ],
        recommendation=InsightRecommendation(
            summary="Trim equity allocation by 10pp.",
            rationale="Historical recovery took 14 months.",
            confidence_pct=72,
        ),
        impact=InsightImpact(before_value="₹6,57,000", after_value="₹7,80,000",
                              delta_label="Save ₹1,23,000 drawdown", delta_tone="healthy"),
        actions=[
            InsightAction(label="Run custom scenario", action_id="custom_stress", style="primary"),
            InsightAction(label="Hedge ideas", action_id="hedge_ideas"),
        ],
        education=InsightEducation(heading="Why this matters",
                                    body="Stress tests don't predict — they educate."),
    )
    payload = card.model_dump()
    restored = InsightCardData.model_validate(json.loads(json.dumps(payload)))
    assert restored == card


# ── 2. Severity mapping ─────────────────────────────────────────


@pytest.mark.parametrize("drop_pct,expected", [
    (-45.0, "critical"),
    (-30.0, "high"),
    (-15.0, "medium"),
    (-5.0,  "info"),
    (0.0,   "healthy"),
    (5.0,   "healthy"),
    (None,  "info"),
])
def test_stress_severity_thresholds(drop_pct, expected):
    """The mapping is documented in the transformer module — these are
    the cliff edges. Adjusting thresholds requires updating this test."""
    assert _stress_severity(drop_pct) == expected


# ── 3. Stress transformer ───────────────────────────────────────


def _sample_stress_data(with_breakdown: bool = True) -> StressTestData:
    breakdown = []
    if with_breakdown:
        breakdown = [
            StressTestBreakdown(fund_name="Axis Bluechip", current_value_rs=300000,
                                  stressed_value_rs=186000, drop_pct=-38.0),
            StressTestBreakdown(fund_name="HDFC Mid-Cap", current_value_rs=200000,
                                  stressed_value_rs=124000, drop_pct=-38.0),
            StressTestBreakdown(fund_name="ICICI Liquid", current_value_rs=100000,
                                  stressed_value_rs=98000,  drop_pct=-2.0),
        ]
    return StressTestData(
        scenario_name="COVID-19 Crash (Feb–Mar 2020)",
        scenario_description="Nifty 50 fell ~38% in 40 days.",
        current_value_rs=600000,
        stressed_value_rs=408000,
        drop_pct=-32.0,
        recovery_years=1.2,
        breakdown=breakdown,
        insight="Your portfolio would fall to ₹4,08,000 under this scenario.",
    )


def test_stress_transformer_full_card_shape():
    card = stress_to_insight_card(_sample_stress_data())

    # Hero — should carry severity + headline + primary value
    assert card.hero.severity == "high"     # -32% → high (-25..-40)
    assert "-32" in card.hero.headline
    assert card.hero.primary_value is not None
    assert "₹" in card.hero.primary_value

    # KPIs — should always include current + drawdown + holdings
    labels = {k.label for k in card.kpis}
    assert "Current value" in labels
    assert "Drawdown" in labels
    assert "Holdings stressed" in labels

    # Findings — top-3 worst holdings, sorted by drop_pct ascending
    assert len(card.findings) == 3
    assert card.findings[0].title == "Axis Bluechip"

    # Recommendation always present (insight or fallback)
    assert card.recommendation is not None
    assert card.recommendation.summary

    # Actions: at least one primary CTA candidate
    primary = [a for a in card.actions if a.style == "primary"]
    assert len(primary) >= 1

    # Education block always present so users learn from the response
    assert card.education is not None


def test_stress_transformer_empty_breakdown_still_valid():
    """New user with no holdings shouldn't crash the transformer."""
    card = stress_to_insight_card(_sample_stress_data(with_breakdown=False))
    assert card.hero is not None
    assert card.findings == []                      # nothing to flag
    # Holdings KPI present but value is "0"
    holdings_kpi = next((k for k in card.kpis if k.label == "Holdings stressed"), None)
    assert holdings_kpi is not None
    assert holdings_kpi.value == "0"


# ── 4. Envelope wrapping ────────────────────────────────────────


def test_insight_card_envelope_wraps_cleanly():
    """The card slots into a WidgetEnvelope with kind='insight_card'.
    This is the shape the frontend WidgetRenderer dispatches on."""
    card = stress_to_insight_card(_sample_stress_data())
    env = WidgetEnvelope(
        kind="insight_card",
        title="COVID-19 Crash",
        freshness=FreshnessChip(state="cached", source=["portfolio_holdings"]),
        agent=AgentInfo(id="market_strategist", label="Market Strategist", version="v1"),
        data=card.model_dump(),
        primary_cta={"label": "Run custom scenario", "action": "custom_stress"},
        suggestions=["Compare 2008 GFC"],
    )
    payload = env.model_dump()
    assert payload["kind"] == "insight_card"
    assert payload["data"]["hero"]["severity"] == "high"
    # Re-parse from JSON to guarantee no field is lost on wire
    re = WidgetEnvelope.model_validate(json.loads(json.dumps(payload)))
    assert re.kind == "insight_card"


# ── 5. Per-tool transformer smoke tests ─────────────────────────
#
# Each test feeds a representative payload through the transformer and
# checks the user-visible card shape: hero present, severity makes
# sense, at least one KPI, at least one action, and JSON round-trips
# cleanly. These guard against regressions when each tool's native
# data schema evolves.


def test_fund_card_transformer():
    fc = FundCardData(
        scheme_name="Parag Parikh Flexi Cap Direct",
        category="Flexi Cap",
        plan_type="Direct",
        nav=78.42,
        aum_cr=84300,
        verdict="Buy",
        verdict_score=78,
        why=["Top quartile 5Y return", "Low expense ratio (0.69%)"],
        watch_outs=[],
        returns={"1Y": 28.2, "3Y": 19.4, "5Y": 22.1},
        expense_ratio=0.69,
        nidp_composite_rank=3,
        nidp_total_in_category=42,
    )
    card = fund_card_to_insight_card(fc)
    assert card.hero.severity == "healthy"
    assert card.hero.headline == "Parag Parikh Flexi Cap Direct"
    assert any(k.label == "1Y return" for k in card.kpis)
    assert any(k.label == "Peer rank" for k in card.kpis)
    assert any(a.style == "primary" for a in card.actions)
    assert card.recommendation is not None


def test_market_brief_transformer_severity_on_drop():
    mb = MarketBriefData(
        indices=[
            MarketBriefIndex(name="Nifty 50",  value=22500, change_pct=-2.4),
            MarketBriefIndex(name="Bank Nifty", value=48200, change_pct=-3.1),
        ],
        fii_dii={"fii_cr": -3200, "dii_cr": 2100, "net_cr": -1100},
        summary_bullets=["FII heavy selling: ₹3,200 Cr outflow", "DII absorbing supply"],
    )
    card = market_brief_to_insight_card(mb)
    assert card.hero.severity == "high"
    assert "Nifty" in card.hero.headline
    # Two indices + FII + DII = 4 KPIs
    assert len(card.kpis) == 4


def test_compare_transformer_picks_leader():
    rows = [
        CompareRow(metric="1Y return %", values=[24, 18, 21], best_index=0, worst_index=1),
        CompareRow(metric="Expense ratio %", values=[0.6, 0.9, 1.1],
                    best_index=0, worst_index=2, higher_is_better=False),
        CompareRow(metric="3Y CAGR",    values=[19, 17, 22], best_index=2),
    ]
    ct = CompareTableData(
        funds=["Parag Parikh Flexi", "Axis Bluechip", "Quant Flexi"],
        rows=rows,
        verdict="Parag Parikh leads on cost and 1Y return.",
    )
    card = compare_to_insight_card(ct)
    assert "Parag Parikh" in card.hero.headline   # leads 2/3 metrics
    assert card.recommendation.summary.startswith("Parag Parikh")


def test_sip_plan_transformer():
    sp = SipPlanData(
        monthly_budget=20000,
        allocations=[
            SipPlanAllocation(scheme_name="Parag Parikh Flexi", monthly_amount=10000, rationale="50%"),
            SipPlanAllocation(scheme_name="Nifty Next 50",     monthly_amount=6000,  rationale="30%"),
            SipPlanAllocation(scheme_name="Short-term Debt",   monthly_amount=4000,  rationale="20%"),
        ],
        why_these=["Aligned to Moderate risk", "Blends index and active funds"],
        counter_points=["STCG applies if redeemed in 12 months"],
    )
    card = sip_plan_to_insight_card(sp)
    assert "20,000" in card.hero.headline
    assert len(card.kpis) == 3
    assert card.recommendation is not None


def test_rebalance_transformer_flags_actions():
    rb = RebalancePlanData(
        current_value_rs=500000,
        actions=[
            RebalanceAction(action="SELL", fund_name="Mid-Cap A", amount_rs=30000,
                             reason="Equity is 78% vs target 65%"),
            RebalanceAction(action="BUY",  fund_name="Short-term Debt", amount_rs=30000),
            RebalanceAction(action="HOLD", fund_name="All other holdings"),
        ],
        summary="Trim equity by 13% and add debt.",
    )
    card = rebalance_to_insight_card(rb)
    assert card.hero.severity == "medium"
    titles = [f.title for f in card.findings]
    # HOLD must be filtered out of findings
    assert all("HOLD" not in t for t in titles)
    assert any("SELL" in t for t in titles)


def test_tax_harvest_transformer_severity_scales_with_usage():
    th = TaxHarvestData(
        fy="FY 2025-26",
        ltcg_used_rs=90000, ltcg_limit_rs=100000, ltcg_remaining_rs=10000,
        candidates=[
            TaxHarvestCandidate(fund_name="ICICI Pru Bluechip", gain_rs=9500,
                                 gain_type="LTCG", days_held=420, eligible=True),
        ],
        total_harvestable_rs=9500,
    )
    card = tax_harvest_to_insight_card(th)
    assert card.hero.severity == "high"          # 90% used → high severity
    # KPIs include limit/used/remaining/candidates (4)
    assert len(card.kpis) == 4
    assert card.education is not None             # tax cards always educate


def test_sector_rotation_transformer():
    sr = SectorRotationData(
        horizon="1M",
        sectors=[
            SectorPoint(name="Banking",  quadrant="Leading",   rs_score=62, month_change_pct=3.2),
            SectorPoint(name="Auto",     quadrant="Leading",   rs_score=58, month_change_pct=4.1),
            SectorPoint(name="IT",       quadrant="Lagging",   rs_score=41, month_change_pct=-3.5),
            SectorPoint(name="Pharma",   quadrant="Improving", rs_score=50),
        ],
    )
    card = sector_rotation_to_insight_card(sr)
    # 4 KPIs — one per quadrant
    assert len(card.kpis) == 4
    quad_labels = {k.label for k in card.kpis}
    assert {"Leading", "Lagging", "Improving", "Weakening"} == quad_labels
    # Findings populated from leading quadrant
    assert any("Banking" in f.title or "Auto" in f.title for f in card.findings)


def test_overlap_transformer_severity_thresholds():
    ov = OverlapRevealData(
        funds=["Axis Bluechip", "Mirae Largecap"],
        overlap_pct=72.0,
        top_common_stocks=[
            OverlapStock(stock_name="HDFC Bank", funds=["Axis Bluechip", "Mirae Largecap"], avg_weight_pct=7.4),
            OverlapStock(stock_name="ICICI Bank", funds=["Axis Bluechip", "Mirae Largecap"], avg_weight_pct=6.1),
        ],
        verdict="High overlap (72%) — these funds largely hold the same stocks.",
    )
    card = overlap_to_insight_card(ov)
    assert card.hero.severity == "high"
    assert "72" in card.hero.headline
    assert card.education is not None


@pytest.mark.parametrize("pct,expected", [
    (60.0, "high"),
    (35.0, "medium"),
    (15.0, "healthy"),
    (None, "info"),
])
def test_overlap_severity_thresholds(pct, expected):
    ov = OverlapRevealData(funds=["A", "B"], overlap_pct=pct)
    assert overlap_to_insight_card(ov).hero.severity == expected


def test_every_transformer_card_jsons_round_trips():
    """Each transformer's output must survive a JSON round-trip so chat
    wire transit can't quietly drop a section. This is the umbrella
    contract guard."""
    samples = [
        fund_card_to_insight_card(FundCardData(scheme_name="X", verdict="Hold", verdict_score=50)),
        market_brief_to_insight_card(MarketBriefData(indices=[MarketBriefIndex(name="Nifty 50", value=20000, change_pct=0.5)])),
        compare_to_insight_card(CompareTableData(funds=["A", "B"], rows=[CompareRow(metric="1Y", values=[10, 12], best_index=1)])),
        sip_plan_to_insight_card(SipPlanData(monthly_budget=5000, allocations=[SipPlanAllocation(scheme_name="F", monthly_amount=5000, rationale="100%")])),
        rebalance_to_insight_card(RebalancePlanData(current_value_rs=100000, actions=[], summary="OK")),
        tax_harvest_to_insight_card(TaxHarvestData(fy="FY 2025-26", ltcg_used_rs=0, ltcg_limit_rs=100000, ltcg_remaining_rs=100000)),
        sector_rotation_to_insight_card(SectorRotationData(horizon="1M", sectors=[SectorPoint(name="X", quadrant="Leading")])),
        overlap_to_insight_card(OverlapRevealData(funds=["A", "B"], overlap_pct=10.0)),
    ]
    for card in samples:
        payload = card.model_dump()
        InsightCardData.model_validate(json.loads(json.dumps(payload)))
