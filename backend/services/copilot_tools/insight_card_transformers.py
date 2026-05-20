"""insight_card transformers — convert per-tool widget payloads into the
unified InsightCardData shape (Doc 06 §6.8 — "every response, same chrome").

Why this lives as its own module: each tool owns its native data
schema (StressTestData, CompareTableData, …). The mobile insight-card
layout has a fixed information architecture (hero → kpis → findings →
recommendation → impact → actions → education). The transformer is the
ONLY place that maps native fields onto card sections, so the layout
stays consistent across tools and the mapping rules are testable.

Each transformer returns a fully-populated InsightCardData. Sections
that the source data can't supply are simply left empty (e.g. no
`impact` for stress test because the action there is "review", not
"execute a trade"). Per the project rule "no UI fallback states", we
don't emit `data_state: "unavailable"` placeholders — missing sections
just don't render.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from models_copilot_widgets import (
    InsightCardData,
    InsightHero,
    InsightKpi,
    InsightFinding,
    InsightRecommendation,
    InsightImpact,
    InsightAction,
    InsightEducation,
    InsightSeverity,
    StressTestData,
    FundCardData,
    MarketBriefData,
    CompareTableData,
    SipPlanData,
    RebalancePlanData,
    TaxHarvestData,
    SectorRotationData,
    OverlapRevealData,
)


def _fmt_rs(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"₹{round(value):,}"


def _stress_severity(drop_pct: Optional[float]) -> InsightSeverity:
    """Map projected drawdown to a severity tag.

    Why these thresholds: -10% is typical of correction-grade equity
    moves; -25% lines up with the 'bear market' definition; -40%+ is
    GFC/COVID-scale. These feed the hero card colour tint.
    """
    if drop_pct is None:
        return "info"
    d = abs(drop_pct)
    if d >= 40:
        return "critical"
    if d >= 25:
        return "high"
    if d >= 10:
        return "medium"
    if drop_pct >= 0:
        return "healthy"
    return "info"


def stress_to_insight_card(stress: StressTestData) -> InsightCardData:
    """Map a StressTestData payload to the unified InsightCardData."""
    drop_pct = stress.drop_pct
    severity = _stress_severity(drop_pct)
    drop_label = f"{drop_pct:+.1f}%" if drop_pct is not None else "—"

    hero = InsightHero(
        severity=severity,
        eyebrow=stress.scenario_name,
        headline=f"Projected impact: {drop_label}",
        primary_value=_fmt_rs(stress.stressed_value_rs),
        primary_label="Stressed portfolio value",
        subtitle=stress.scenario_description,
        trend="down" if (drop_pct or 0) < 0 else "flat",
    )

    kpis: List[InsightKpi] = []
    if stress.current_value_rs is not None:
        kpis.append(InsightKpi(label="Current value", value=_fmt_rs(stress.current_value_rs)))
    if drop_pct is not None:
        kpis.append(InsightKpi(
            label="Drawdown",
            value=drop_label,
            tone=severity,
            trend="down" if drop_pct < 0 else "up",
        ))
    if stress.recovery_years is not None:
        yrs = stress.recovery_years
        kpis.append(InsightKpi(
            label="Recovery",
            value=f"~{yrs:.1f} yr" if yrs % 1 else f"~{int(yrs)} yr",
            sublabel="historical avg",
        ))
    kpis.append(InsightKpi(label="Holdings stressed", value=str(len(stress.breakdown))))

    # Top-3 worst-affected funds become the priority findings
    findings: List[InsightFinding] = []
    worst = sorted(stress.breakdown, key=lambda b: (b.drop_pct or 0))[:3]
    for b in worst:
        if b.drop_pct is None:
            continue
        findings.append(InsightFinding(
            priority="high" if b.drop_pct <= -30 else "medium",
            title=b.fund_name,
            detail=f"{b.drop_pct:+.1f}% in this scenario",
            impact_value=_fmt_rs((b.stressed_value_rs or 0) - (b.current_value_rs or 0)),
            impact_label="Value at risk",
        ))

    recommendation = InsightRecommendation(
        summary=stress.insight or "Review the breakdown to see which holdings drive the drawdown.",
        rationale=(
            "Stress tests apply historical shock magnitudes uniformly to each "
            "holding by asset class. Real outcomes vary by fund manager skill, "
            "sector tilt, and rebalancing speed."
        ),
        confidence_pct=72,
    )

    actions: List[InsightAction] = [
        InsightAction(label="Run custom scenario", action_id="custom_stress", style="primary"),
        InsightAction(label="Compare 2008 GFC", action_id="compare_gfc_2008", style="secondary"),
        InsightAction(label="Show hedge ideas", action_id="hedge_ideas", style="secondary"),
    ]

    education = InsightEducation(
        heading="Why this matters",
        body=(
            "Stress tests don't predict the future — they show how today's "
            "portfolio would have fared in a past crash. Use them to gauge "
            "whether your drawdown tolerance matches your allocation, not "
            "to time markets."
        ),
    )

    return InsightCardData(
        hero=hero,
        kpis=kpis,
        findings=findings,
        recommendation=recommendation,
        impact=None,           # stress test is informational; no exec preview
        actions=actions,
        education=education,
    )


# ── Fund Card ──────────────────────────────────────────────────────

_VERDICT_SEVERITY: dict = {
    "Strong Buy": "healthy",
    "Buy":        "healthy",
    "Hold":       "info",
    "Sell":       "high",
}


def fund_card_to_insight_card(fc: FundCardData) -> InsightCardData:
    """Map a FundCardData payload to InsightCardData.

    Hero carries the verdict + score; KPIs surface the headline returns,
    rank, and expense ratio so they're visible above the fold.
    """
    severity: InsightSeverity = _VERDICT_SEVERITY.get(fc.verdict or "Hold", "info")  # type: ignore[assignment]
    hero = InsightHero(
        severity=severity,
        eyebrow=fc.category,
        headline=fc.scheme_name,
        primary_value=(f"{fc.verdict_score}/100" if fc.verdict_score is not None else None),
        primary_label=fc.verdict or "Quality score",
        subtitle=(f"Direct plan · NAV ₹{fc.nav:.2f}" if fc.nav else None) if fc.plan_type == "Direct"
                 else (f"{fc.plan_type} plan · NAV ₹{fc.nav:.2f}" if fc.nav and fc.plan_type else None),
        trend="up" if severity == "healthy" else ("down" if severity == "high" else "flat"),
    )

    kpis: List[InsightKpi] = []
    if fc.returns.get("1Y") is not None:
        kpis.append(InsightKpi(label="1Y return", value=f"{fc.returns['1Y']:+.1f}%"))
    if fc.returns.get("3Y") is not None:
        kpis.append(InsightKpi(label="3Y CAGR", value=f"{fc.returns['3Y']:+.1f}%"))
    if fc.expense_ratio is not None:
        ter_tone: InsightSeverity = "healthy" if fc.expense_ratio <= 0.8 else "info"
        kpis.append(InsightKpi(label="Expense ratio", value=f"{fc.expense_ratio:.2f}%", tone=ter_tone))
    if fc.nidp_composite_rank and fc.nidp_total_in_category:
        kpis.append(InsightKpi(
            label="Peer rank",
            value=f"#{fc.nidp_composite_rank}",
            sublabel=f"of {fc.nidp_total_in_category}",
        ))
    if fc.aum_cr is not None:
        kpis.append(InsightKpi(label="AUM", value=f"₹{fc.aum_cr:,.0f} Cr"))

    findings: List[InsightFinding] = []
    for flag in fc.nidp_red_flags[:3]:
        findings.append(InsightFinding(priority="high", title=flag,
                                        detail="NIDP lifecycle event flagged"))
    for w in fc.watch_outs[:3 - len(findings)]:
        findings.append(InsightFinding(priority="medium", title=w))

    recommendation = None
    if fc.why:
        recommendation = InsightRecommendation(
            summary=fc.why[0],
            rationale="\n".join(fc.why[1:]) if len(fc.why) > 1 else None,
            confidence_pct=fc.verdict_score,
        )

    actions = [
        InsightAction(label="Compare with mine",      action_id="compare_with_mine",  style="primary"),
        InsightAction(label="Show portfolio overlap", action_id="show_overlap",       style="secondary"),
        InsightAction(label="Cheaper alternatives",   action_id="cheaper_alternatives", style="secondary"),
    ]

    return InsightCardData(
        hero=hero,
        kpis=kpis,
        findings=findings,
        recommendation=recommendation,
        actions=actions,
    )


# ── Market Brief ──────────────────────────────────────────────────

def market_brief_to_insight_card(mb: MarketBriefData) -> InsightCardData:
    """Map a MarketBriefData payload to InsightCardData."""
    # Severity: derive from Nifty's day-change.
    nifty = next((i for i in mb.indices if "Nifty 50" in i.name), None)
    chg = nifty.change_pct if nifty else 0.0
    if chg <= -2:   severity: InsightSeverity = "high"
    elif chg <= -0.5: severity = "medium"
    elif chg >= 1.5:  severity = "healthy"
    else:            severity = "info"

    hero = InsightHero(
        severity=severity,
        eyebrow="Markets · Today",
        headline=(f"Nifty 50 {chg:+.2f}%" if nifty else "Markets at a glance"),
        primary_value=(f"{nifty.value:,.2f}" if nifty else None),
        primary_label=("Nifty 50 close" if nifty else None),
        subtitle=(mb.summary_bullets[0] if mb.summary_bullets else None),
        trend="up" if chg > 0 else ("down" if chg < 0 else "flat"),
    )

    kpis: List[InsightKpi] = []
    for idx in mb.indices[:4]:
        kpis.append(InsightKpi(
            label=idx.name,
            value=f"{idx.value:,.0f}",
            sublabel=f"{idx.change_pct:+.2f}%",
            trend="up" if idx.change_pct > 0 else ("down" if idx.change_pct < 0 else "flat"),
            tone="healthy" if idx.change_pct > 0 else ("high" if idx.change_pct < -1 else "info"),
        ))
    if mb.fii_dii:
        kpis.append(InsightKpi(
            label="FII net flow",
            value=f"₹{mb.fii_dii.get('fii_cr', 0):,.0f} Cr",
            tone="high" if mb.fii_dii.get("fii_cr", 0) < -1000 else "info",
        ))
        kpis.append(InsightKpi(
            label="DII net flow",
            value=f"₹{mb.fii_dii.get('dii_cr', 0):,.0f} Cr",
            tone="healthy" if mb.fii_dii.get("dii_cr", 0) > 1000 else "info",
        ))

    findings: List[InsightFinding] = []
    for bullet in mb.summary_bullets[1:4]:
        findings.append(InsightFinding(priority="medium", title=bullet))

    recommendation = None
    if mb.summary_bullets:
        recommendation = InsightRecommendation(
            summary=mb.summary_bullets[0],
            rationale=None,
        )

    actions = [
        InsightAction(label="Impact on my portfolio", action_id="portfolio_impact", style="primary"),
        InsightAction(label="Which sectors to trim?", action_id="sector_trim",     style="secondary"),
        InsightAction(label="Set Nifty alert",        action_id="set_nifty_alert", style="secondary"),
    ]

    return InsightCardData(
        hero=hero,
        kpis=kpis,
        findings=findings,
        recommendation=recommendation,
        actions=actions,
    )


# ── Compare Funds ──────────────────────────────────────────────────

def compare_to_insight_card(ct: CompareTableData) -> InsightCardData:
    """Map a CompareTableData payload to InsightCardData.

    Hero shows the leader (verdict line). KPIs surface the best/worst
    counts. Findings list each metric with the leader marker.
    """
    n = len(ct.funds)
    # Tally how many metrics each fund leads
    leads = [0] * n
    for r in ct.rows:
        if r.best_index is not None and 0 <= r.best_index < n:
            leads[r.best_index] += 1
    top_idx = max(range(n), key=lambda i: leads[i]) if leads else 0
    leader = ct.funds[top_idx] if ct.funds else "—"

    severity: InsightSeverity = "info"
    hero = InsightHero(
        severity=severity,
        eyebrow=f"{n} funds compared",
        headline=f"Leader: {leader}",
        primary_value=f"{leads[top_idx]}/{len(ct.rows)}",
        primary_label="metrics led",
        subtitle=ct.verdict,
    )

    kpis: List[InsightKpi] = []
    for i, fund in enumerate(ct.funds[:4]):
        kpis.append(InsightKpi(
            label=fund,
            value=str(leads[i]),
            sublabel="metrics led",
            tone="healthy" if i == top_idx else "info",
        ))

    findings: List[InsightFinding] = []
    for r in ct.rows[:5]:
        if r.best_index is None or not ct.funds:
            continue
        winner = ct.funds[r.best_index] if 0 <= r.best_index < n else "—"
        v = r.values[r.best_index] if 0 <= r.best_index < len(r.values) else None
        val_str: Optional[str]
        if isinstance(v, (int, float)):
            val_str = f"{v:.2f}"
        elif v is not None:
            val_str = str(v)
        else:
            val_str = None
        findings.append(InsightFinding(
            priority="medium",
            title=r.metric,
            detail=f"{winner} leads",
            impact_value=val_str,
        ))

    recommendation = (
        InsightRecommendation(summary=ct.verdict) if ct.verdict else None
    )

    actions = [
        InsightAction(label="Switch to leader",        action_id="switch_to_leader",   style="primary"),
        InsightAction(label="Show overlap",            action_id="show_overlap",       style="secondary"),
        InsightAction(label="Cheaper alternatives",    action_id="cheaper_alternatives", style="secondary"),
    ]

    return InsightCardData(
        hero=hero,
        kpis=kpis,
        findings=findings,
        recommendation=recommendation,
        actions=actions,
    )


# ── SIP Plan ───────────────────────────────────────────────────────

def sip_plan_to_insight_card(sp: SipPlanData) -> InsightCardData:
    """Map a SipPlanData payload to InsightCardData.

    Hero shows the monthly commitment; KPIs break down the allocations;
    findings list the why/counter-points.
    """
    total = sum(a.monthly_amount for a in sp.allocations) or sp.monthly_budget
    hero = InsightHero(
        severity="healthy",
        eyebrow="SIP plan",
        headline=f"₹{int(sp.monthly_budget):,}/month",
        primary_value=f"{len(sp.allocations)}",
        primary_label="bucket allocation",
        subtitle=(sp.why_these[0] if sp.why_these else None),
        trend="up",
    )

    kpis: List[InsightKpi] = []
    for a in sp.allocations[:4]:
        pct = (a.monthly_amount / total * 100) if total else 0
        kpis.append(InsightKpi(
            label=a.scheme_name,
            value=f"₹{int(a.monthly_amount):,}",
            sublabel=f"{pct:.0f}% of plan",
        ))

    findings: List[InsightFinding] = []
    for cp in sp.counter_points[:3]:
        findings.append(InsightFinding(priority="medium", title=cp))

    recommendation = None
    if sp.why_these:
        recommendation = InsightRecommendation(
            summary=sp.why_these[0],
            rationale="\n".join(sp.why_these[1:]) if len(sp.why_these) > 1 else None,
        )

    actions = [
        InsightAction(label="Set up SIP",       action_id="setup_sip",    style="primary"),
        InsightAction(label="Step up 10%/yr",   action_id="step_up_10",   style="secondary"),
        InsightAction(label="Show tax impact",  action_id="sip_tax_impact", style="secondary"),
    ]

    return InsightCardData(
        hero=hero,
        kpis=kpis,
        findings=findings,
        recommendation=recommendation,
        actions=actions,
    )


# ── Rebalance Plan ─────────────────────────────────────────────────

def rebalance_to_insight_card(rb: RebalancePlanData) -> InsightCardData:
    """Map a RebalancePlanData payload to InsightCardData.

    Hero shows the net rebalance amount; findings are individual
    BUY/SELL/SWITCH/HOLD actions, ranked by amount.
    """
    n = len(rb.actions)
    needs_action = any(a.action != "HOLD" for a in rb.actions)
    severity: InsightSeverity = "medium" if needs_action else "healthy"
    net_amount = sum(abs(a.amount_rs or 0) for a in rb.actions) or rb.net_rebalance_rs

    hero = InsightHero(
        severity=severity,
        eyebrow="Rebalance plan",
        headline=(rb.summary or "Portfolio rebalance review"),
        primary_value=(f"₹{net_amount:,.0f}" if net_amount else None),
        primary_label="net rebalance",
        trend="flat",
    )

    kpis: List[InsightKpi] = []
    if rb.current_value_rs is not None:
        kpis.append(InsightKpi(label="Portfolio value", value=f"₹{rb.current_value_rs:,.0f}"))
    kpis.append(InsightKpi(label="Actions", value=str(n)))
    if rb.estimated_tax_rs is not None:
        kpis.append(InsightKpi(label="Est. tax", value=f"₹{rb.estimated_tax_rs:,.0f}", tone="high"))

    findings: List[InsightFinding] = []
    sorted_actions = sorted(
        rb.actions,
        key=lambda a: -(abs(a.amount_rs or 0)),
    )
    for a in sorted_actions[:4]:
        if a.action == "HOLD":
            continue
        impact_value = (f"₹{a.amount_rs:,.0f}" if a.amount_rs is not None else None)
        findings.append(InsightFinding(
            priority="high" if a.action in ("SELL", "SWITCH") else "medium",
            title=f"{a.action} · {a.fund_name}",
            detail=a.reason,
            impact_value=impact_value,
        ))

    recommendation = None
    if rb.summary:
        recommendation = InsightRecommendation(summary=rb.summary)

    actions = [
        InsightAction(label="Execute plan",      action_id="execute_rebalance",  style="primary"),
        InsightAction(label="Simulate tax",      action_id="rebalance_tax_sim",  style="secondary"),
        InsightAction(label="Equity only",       action_id="rebalance_equity_only", style="secondary"),
    ]

    return InsightCardData(
        hero=hero,
        kpis=kpis,
        findings=findings,
        recommendation=recommendation,
        actions=actions,
    )


# ── Tax Harvest ────────────────────────────────────────────────────

def tax_harvest_to_insight_card(th: TaxHarvestData) -> InsightCardData:
    """Map a TaxHarvestData payload to InsightCardData."""
    pct_used = (th.ltcg_used_rs / th.ltcg_limit_rs * 100) if th.ltcg_limit_rs else 0
    severity: InsightSeverity = "high" if pct_used >= 80 else ("medium" if pct_used >= 40 else "healthy")

    hero = InsightHero(
        severity=severity,
        eyebrow=th.fy,
        headline=(f"Harvest opportunity: ₹{th.total_harvestable_rs:,.0f}"
                  if th.total_harvestable_rs else "No harvest candidates yet"),
        primary_value=f"₹{th.ltcg_remaining_rs:,.0f}",
        primary_label="LTCG room remaining",
        subtitle=(f"{len(th.candidates)} eligible holding(s)" if th.candidates else None),
        trend="flat",
    )

    kpis: List[InsightKpi] = [
        InsightKpi(label="LTCG limit",     value=f"₹{th.ltcg_limit_rs:,.0f}"),
        InsightKpi(label="Used this FY",   value=f"₹{th.ltcg_used_rs:,.0f}", tone=severity),
        InsightKpi(label="Remaining",      value=f"₹{th.ltcg_remaining_rs:,.0f}", tone="healthy"),
        InsightKpi(label="Candidates",     value=str(len(th.candidates))),
    ]

    findings: List[InsightFinding] = []
    for c in th.candidates[:4]:
        findings.append(InsightFinding(
            priority="medium" if c.eligible else "low",
            title=c.fund_name,
            detail=(f"{c.gain_type} ₹{c.gain_rs:,.0f}"
                    + (f" · {c.days_held}d held" if c.days_held else "")),
            impact_value=(f"₹{c.gain_rs:,.0f}"),
            impact_label="Gain",
        ))

    recommendation = None
    if th.warning:
        recommendation = InsightRecommendation(
            summary="Stagger harvests to maximise the ₹1L LTCG exemption.",
            rationale=th.warning,
        )

    actions = [
        InsightAction(label="Simulate harvest",   action_id="simulate_harvest",   style="primary"),
        InsightAction(label="Plan switch",        action_id="plan_switch",        style="secondary"),
        InsightAction(label="STCG separately",    action_id="show_stcg",          style="secondary"),
    ]

    education = InsightEducation(
        heading="Why this matters",
        body=(
            "Long-term capital gains on equity over ₹1L per financial year "
            "are taxed at 10%. Harvesting eligible gains up to the exemption "
            "limit each year resets the cost basis tax-free."
        ),
    )

    return InsightCardData(
        hero=hero,
        kpis=kpis,
        findings=findings,
        recommendation=recommendation,
        actions=actions,
        education=education,
    )


# ── Sector Rotation ────────────────────────────────────────────────

def sector_rotation_to_insight_card(sr: SectorRotationData) -> InsightCardData:
    """Map a SectorRotationData payload to InsightCardData."""
    by_q: dict = {}
    for s in sr.sectors:
        by_q.setdefault(s.quadrant, []).append(s)

    leading  = by_q.get("Leading", [])
    weakening = by_q.get("Weakening", [])
    lagging  = by_q.get("Lagging", [])
    improving = by_q.get("Improving", [])

    severity: InsightSeverity = "info"
    hero = InsightHero(
        severity=severity,
        eyebrow=f"Sector rotation · {sr.horizon}",
        headline=(f"{len(leading)} sector(s) leading"
                  if leading else "Sector rotation snapshot"),
        primary_value=str(len(sr.sectors)),
        primary_label="sectors tracked",
        subtitle=(f"{len(weakening)} weakening · {len(lagging)} lagging · {len(improving)} improving"),
    )

    kpis: List[InsightKpi] = [
        InsightKpi(label="Leading",   value=str(len(leading)),   tone="healthy"),
        InsightKpi(label="Improving", value=str(len(improving)), tone="info"),
        InsightKpi(label="Weakening", value=str(len(weakening)), tone="medium"),
        InsightKpi(label="Lagging",   value=str(len(lagging)),   tone="high"),
    ]

    findings: List[InsightFinding] = []
    for s in sorted(leading, key=lambda x: -(x.month_change_pct or 0))[:3]:
        findings.append(InsightFinding(
            priority="medium",
            title=s.name,
            detail=f"{s.quadrant} · RS {s.rs_score:.0f}" if s.rs_score is not None else s.quadrant,
            impact_value=(f"{s.month_change_pct:+.1f}%" if s.month_change_pct is not None else None),
            impact_label="1M change",
        ))

    recommendation = InsightRecommendation(
        summary=(f"{len(leading)} sector(s) show leadership over the last {sr.horizon}; "
                 f"{len(lagging)} are lagging."),
        rationale=(
            "Sector rotation tells you which slices of the market are working. "
            "Use it to tilt new contributions, not to fully rotate established holdings."
        ),
    )

    actions = [
        InsightAction(label="Trim weak sectors",  action_id="sector_trim_advice", style="primary"),
        InsightAction(label="My sector exposure", action_id="my_sector_exposure", style="secondary"),
        InsightAction(label="3M view",            action_id="sector_3m",          style="secondary"),
    ]

    return InsightCardData(
        hero=hero,
        kpis=kpis,
        findings=findings,
        recommendation=recommendation,
        actions=actions,
    )


# ── Overlap Reveal ─────────────────────────────────────────────────

def overlap_to_insight_card(ov: OverlapRevealData) -> InsightCardData:
    """Map an OverlapRevealData payload to InsightCardData.

    Hero shows the headline overlap %; findings list the most-shared
    stocks. Severity tracks the same threshold used for the verdict.
    """
    pct = ov.overlap_pct
    if pct is None:
        severity: InsightSeverity = "info"
    elif pct >= 50:
        severity = "high"
    elif pct >= 25:
        severity = "medium"
    else:
        severity = "healthy"

    hero = InsightHero(
        severity=severity,
        eyebrow=f"{len(ov.funds)} funds compared",
        headline=(f"{pct:.0f}% overlap" if pct is not None else "Overlap analysis"),
        primary_value=(f"{pct:.0f}%" if pct is not None else None),
        primary_label="shared holdings",
        subtitle=ov.verdict,
    )

    kpis: List[InsightKpi] = [
        InsightKpi(label="Funds analysed", value=str(len(ov.funds))),
        InsightKpi(label="Shared stocks",  value=str(len(ov.top_common_stocks))),
    ]
    if pct is not None:
        kpis.append(InsightKpi(label="Overlap", value=f"{pct:.0f}%", tone=severity))

    findings: List[InsightFinding] = []
    for s in ov.top_common_stocks[:4]:
        findings.append(InsightFinding(
            priority="high" if pct and pct > 50 else "medium",
            title=s.stock_name,
            detail=f"Held by {len(s.funds)} fund(s)",
            impact_value=(f"{s.avg_weight_pct:.1f}%" if s.avg_weight_pct is not None else None),
            impact_label="Avg weight",
        ))

    recommendation = None
    if ov.verdict:
        recommendation = InsightRecommendation(
            summary=ov.verdict,
            rationale=(
                "High overlap means you're paying two expense ratios for the "
                "same underlying exposure. Consolidating into one fund saves "
                "fees without changing risk."
            ),
        )

    actions = [
        InsightAction(label="Consolidate funds",  action_id="consolidate",        style="primary"),
        InsightAction(label="Cheaper alternatives", action_id="cheaper_alternatives", style="secondary"),
        InsightAction(label="Show full overlap",  action_id="show_full_overlap",  style="secondary"),
    ]

    education = InsightEducation(
        heading="Why this matters",
        body=(
            "Two funds with 50%+ stock overlap behave almost identically. "
            "Holding both adds cost and complexity without adding "
            "diversification."
        ),
    )

    return InsightCardData(
        hero=hero,
        kpis=kpis,
        findings=findings,
        recommendation=recommendation,
        actions=actions,
        education=education,
    )


# ────────────────────────────────────────────────────────────────────
# Retrieval-based transformers (chat-only intents that don't have a
# dedicated widget endpoint). Each takes the Retrieval object the
# orchestrator already produces for the intent and maps the rows /
# extras onto the unified card sections.
#
# Why a single dispatcher: every chat intent that wants a card needs
# the same wrapper (severity, hero, KPIs, findings, recommendation,
# actions, education). Keeping it in one function means the chat path
# can wire any new intent with one line — `if intent.name == "X":
# card = _retrieval_card(intent, retrieval)` — rather than 50 lines
# of boilerplate per intent.
# ────────────────────────────────────────────────────────────────────


def _retrieval_unavailable_card(intent_name: str, summary: str) -> InsightCardData:
    """When a retriever fails (`ok=False`), still return a well-formed
    info card so the chat bubble doesn't surface a blank renderer.

    The hero carries the reason verbatim from the retriever — keeps the
    user honest about what's missing without inventing data.
    """
    return InsightCardData(
        hero=InsightHero(
            severity="info",
            eyebrow=intent_name.replace("_", " ").title(),
            headline=summary or "No data to show yet.",
            primary_value=None,
            primary_label=None,
            subtitle=None,
        ),
    )


def _intent_default_actions(intent_name: str) -> List[InsightAction]:
    """Sensible default action chips per intent — keeps the user in a
    conversational loop instead of dead-ending after each card."""
    return {
        "concentration": [
            InsightAction(label="How do I diversify?",   action_id="diversify",       style="primary"),
            InsightAction(label="Show full breakdown",   action_id="show_full",       style="secondary"),
        ],
        "goals": [
            InsightAction(label="Adjust monthly SIP",    action_id="adjust_sip",      style="primary"),
            InsightAction(label="Show goal projection",  action_id="goal_projection", style="secondary"),
        ],
        "health": [
            InsightAction(label="Improve my score",      action_id="improve_health",  style="primary"),
            InsightAction(label="Show component detail", action_id="health_detail",   style="secondary"),
        ],
        "invest_fresh": [
            InsightAction(label="Set up SIP into bucket", action_id="setup_sip",      style="primary"),
            InsightAction(label="Show fund picks",        action_id="fund_picks",     style="secondary"),
        ],
        "ranking": [
            InsightAction(label="Show full leaderboard",  action_id="show_full",       style="primary"),
            InsightAction(label="Explain ranking",        action_id="explain_ranking", style="secondary"),
        ],
        "mf_analysis": [
            InsightAction(label="Show compare table",    action_id="show_compare",    style="primary"),
            InsightAction(label="Find cheaper options",  action_id="cheaper_options", style="secondary"),
        ],
    }.get(intent_name, [])


def _concentration_to_card(intent_name: str, grouping: Optional[str],
                             retrieval) -> InsightCardData:
    """Concentration breakdown (sector / AMC / category / company /
    asset_class). Severity tracks the top-bucket share — anything > 30%
    is medium, > 40% is high."""
    rows = retrieval.rows
    grouping_label = (grouping or "amc").replace("_", " ").title()

    # Top bucket — the visible "you're heavy in X" line.
    top = rows[0] if rows else None
    top_pct = float(top.get("value", 0)) if top else 0
    if top_pct >= 40:   severity: InsightSeverity = "high"
    elif top_pct >= 30: severity = "medium"
    elif top_pct >= 20: severity = "info"
    else:               severity = "healthy"

    hero = InsightHero(
        severity=severity,
        eyebrow=f"Concentration · {grouping_label}",
        headline=(f"Top {grouping_label.lower()}: {top.get('label')} ({top_pct:.0f}%)"
                  if top else "Concentration breakdown"),
        primary_value=(f"{top_pct:.0f}%" if top else None),
        primary_label=(f"share of {grouping_label.lower()}" if top else None),
        subtitle=retrieval.summary,
    )

    kpis: List[InsightKpi] = []
    for r in rows[:4]:
        kpis.append(InsightKpi(
            label=r.get("label", "")[:30],
            value=f"{float(r.get('value', 0)):.0f}%",
            sublabel=(f"₹{float(r.get('amount_rs', 0)):,.0f}"
                      if r.get("amount_rs") else None),
            tone=("high" if float(r.get("value", 0)) >= 30 else None),
        ))

    findings: List[InsightFinding] = []
    for r in rows[:5]:
        v = float(r.get("value", 0))
        if v < 10:
            continue
        findings.append(InsightFinding(
            priority="high" if v >= 30 else ("medium" if v >= 20 else "low"),
            title=str(r.get("label", "Bucket")),
            detail=f"{v:.1f}% of portfolio",
            impact_value=(f"₹{float(r.get('amount_rs', 0)):,.0f}"
                          if r.get("amount_rs") else None),
            impact_label="Value",
        ))

    recommendation: Optional[InsightRecommendation] = None
    if top and top_pct >= 30:
        recommendation = InsightRecommendation(
            summary=(f"{top.get('label')} accounts for {top_pct:.0f}% of your "
                     f"{grouping_label.lower()} exposure — that's concentration risk."),
            rationale=(
                f"A single {grouping_label.lower()} above 30% means any shock to "
                f"that bucket disproportionately affects the portfolio. Diversifying "
                f"reduces single-point-of-failure risk."
            ),
        )

    return InsightCardData(
        hero=hero, kpis=kpis, findings=findings,
        recommendation=recommendation,
        actions=_intent_default_actions("concentration"),
    )


def _goals_to_card(retrieval) -> InsightCardData:
    """Goal progress overview. Severity = the lowest on_track_pct across
    high-priority goals (the most-behind goal sets the tone)."""
    rows = retrieval.rows
    if not rows:
        return _retrieval_unavailable_card("goals", retrieval.summary)

    high_priority = [r for r in rows if (r.get("priority") or "").lower() == "high"]
    track_pool = high_priority or rows
    min_track = min(float(r.get("on_track_pct", 100)) for r in track_pool)

    if min_track < 50:    severity: InsightSeverity = "high"
    elif min_track < 75:  severity = "medium"
    elif min_track < 95:  severity = "info"
    else:                 severity = "healthy"

    hero = InsightHero(
        severity=severity,
        eyebrow=f"{len(rows)} active goal(s)",
        headline=(f"Most-behind goal: {min_track:.0f}% on track"
                  if min_track < 100 else "All goals on track"),
        primary_value=f"{min_track:.0f}%",
        primary_label="on track (weakest)",
    )

    kpis: List[InsightKpi] = []
    for r in rows[:4]:
        on_track = float(r.get("on_track_pct", 0))
        kpis.append(InsightKpi(
            label=str(r.get("name", "Goal"))[:24],
            value=f"{on_track:.0f}%",
            sublabel=f"₹{float(r.get('target_rs', 0)) / 1e5:.1f}L target",
            tone=("high" if on_track < 50
                   else "medium" if on_track < 75
                   else "healthy" if on_track >= 95 else "info"),
        ))

    findings: List[InsightFinding] = []
    behind = sorted([r for r in rows if float(r.get("on_track_pct", 100)) < 90],
                     key=lambda r: float(r.get("on_track_pct", 100)))[:3]
    for r in behind:
        on_track = float(r.get("on_track_pct", 0))
        findings.append(InsightFinding(
            priority="high" if on_track < 50 else "medium",
            title=str(r.get("name", "Goal")),
            detail=(f"{r.get('horizon_years', 0)} yr horizon · "
                    f"current ₹{float(r.get('corpus_rs', 0)) / 1e5:.1f}L"),
            impact_value=f"₹{float(r.get('plan_sip_rs', 0)):,.0f}/mo",
            impact_label="Plan SIP",
        ))

    recommendation = InsightRecommendation(
        summary=(f"Your {behind[0].get('name')} goal is "
                 f"{float(behind[0].get('on_track_pct', 0)):.0f}% on track. "
                 f"Step up the SIP or extend the horizon to close the gap."
                 if behind
                 else "All goals are tracking ≥ 90% — no urgent SIP changes needed."),
        rationale=(
            "On-track % combines current corpus + planned SIP + assumed CAGR "
            "against the target amount and horizon. Anything below 75% needs "
            "either a higher SIP, a longer horizon, or both."
        ),
    )

    return InsightCardData(
        hero=hero, kpis=kpis, findings=findings,
        recommendation=recommendation,
        actions=_intent_default_actions("goals"),
    )


def _health_to_card(retrieval) -> InsightCardData:
    """Portfolio health scorecard. Severity tracks the grade letter."""
    extras = retrieval.extras
    score = float(extras.get("health_score", 0))
    grade = extras.get("grade", "—")
    top_drivers = extras.get("top_drivers") or []

    if score < 50:    severity: InsightSeverity = "high"
    elif score < 70:  severity = "medium"
    elif score < 85:  severity = "info"
    else:             severity = "healthy"

    hero = InsightHero(
        severity=severity,
        eyebrow="Portfolio Health",
        headline=f"Grade {grade} · {score:.0f}/100",
        primary_value=f"{score:.0f}",
        primary_label="overall score",
        subtitle=(extras.get("summary_text") or "")[:140] or None,
    )

    # KPIs from individual components.
    kpis: List[InsightKpi] = []
    for c in retrieval.rows[:4]:
        c_score = float(c.get("score", 0))
        kpis.append(InsightKpi(
            label=str(c.get("component", "Component"))[:24],
            value=f"{c_score:.0f}/100",
            sublabel=("low confidence" if c.get("low_confidence") else None),
            tone=("high" if c_score < 50 else "medium" if c_score < 75 else "healthy"),
        ))

    findings: List[InsightFinding] = []
    for d in top_drivers[:3]:
        findings.append(InsightFinding(
            priority="medium",
            title=str(d.get("label", "Driver")),
            detail=str(d.get("detail", ""))[:180],
        ))

    recommendation = InsightRecommendation(
        summary=(extras.get("summary_text") or "Health score is computed across "
                  "diversification, risk, cost and goal alignment.")[:200],
        rationale=(
            "Each component is scored 0–100 and weighted by impact on outcomes. "
            "The lowest-scoring component is usually the highest-leverage place "
            "to act first."
        ),
    )

    return InsightCardData(
        hero=hero, kpis=kpis, findings=findings,
        recommendation=recommendation,
        actions=_intent_default_actions("health"),
    )


def _invest_fresh_to_card(intent_extras: Dict[str, Any], retrieval) -> InsightCardData:
    """Allocation-gap recommendation for fresh capital."""
    rows = retrieval.rows
    if not rows:
        # Portfolio is balanced — celebratory healthy card.
        return InsightCardData(
            hero=InsightHero(
                severity="healthy",
                eyebrow="Fresh capital",
                headline="Portfolio already balanced",
                primary_value=None,
                subtitle=retrieval.summary,
            ),
            recommendation=InsightRecommendation(
                summary="No bucket is underweight enough to recommend fresh capital — split new contributions across existing allocations.",
            ),
        )

    headline_bucket = rows[0]
    amount_rs = intent_extras.get("amount_rs")
    dev_pp = abs(float(headline_bucket.get("deviation_pp", 0)))
    if dev_pp >= 15:   severity: InsightSeverity = "high"
    elif dev_pp >= 8:  severity = "medium"
    else:              severity = "info"

    hero = InsightHero(
        severity=severity,
        eyebrow="Deploy fresh capital",
        headline=f"{headline_bucket.get('bucket', '').title()} is most underweight",
        primary_value=(f"₹{amount_rs:,.0f}" if amount_rs else None),
        primary_label=("fresh capital" if amount_rs else None),
        subtitle=retrieval.summary,
    )

    kpis: List[InsightKpi] = []
    for r in rows[:4]:
        cur = float(r.get("current_pct", 0))
        tgt = float(r.get("target_pct", 0))
        gap = float(r.get("deviation_pp", 0))
        kpis.append(InsightKpi(
            label=str(r.get("bucket", "")).title(),
            value=f"{cur:.0f}% → {tgt:.0f}%",
            sublabel=f"{gap:+.1f}pp gap",
            tone="high" if abs(gap) >= 10 else "medium",
        ))

    findings: List[InsightFinding] = []
    for r in rows[:4]:
        share = float(r.get("share_of_fresh_pct", 0))
        sugg = r.get("suggested_amount_rs")
        findings.append(InsightFinding(
            priority="high" if abs(float(r.get("deviation_pp", 0))) >= 10 else "medium",
            title=str(r.get("fund_class", r.get("bucket", "Bucket"))),
            detail=f"{share:.0f}% of fresh capital",
            impact_value=(f"₹{sugg:,.0f}" if sugg else None),
            impact_label="Suggested",
        ))

    recommendation = InsightRecommendation(
        summary=(
            f"Direct {float(headline_bucket.get('share_of_fresh_pct', 0)):.0f}% of new money to "
            f"{headline_bucket.get('bucket', '').title()} first — it's "
            f"{abs(float(headline_bucket.get('deviation_pp', 0))):.1f}pp below target."
        ),
        rationale=(
            "Fresh capital is the cheapest way to rebalance — no tax cost, no "
            "transaction friction. Tilting new contributions toward the most "
            "underweight bucket closes the gap without triggering capital gains."
        ),
    )

    return InsightCardData(
        hero=hero, kpis=kpis, findings=findings,
        recommendation=recommendation,
        actions=_intent_default_actions("invest_fresh"),
    )


def _ranking_to_card(retrieval, metric: str) -> InsightCardData:
    """Top-N holdings ranked by a metric (profit/return/loss/value)."""
    rows = retrieval.rows
    if not rows:
        return _retrieval_unavailable_card("ranking", retrieval.summary)

    is_loss = metric == "loss"
    top = rows[0]
    severity: InsightSeverity = "high" if is_loss else "healthy"

    hero = InsightHero(
        severity=severity,
        eyebrow=f"Top {len(rows)} by {metric}",
        headline=str(top.get("name", "Top holding")),
        primary_value=(
            f"{float(top.get('return_pct', 0)):+.1f}%" if metric == "return"
            else f"₹{float(top.get('profit_rs', 0)):+,.0f}"
        ),
        primary_label=metric,
        trend=("down" if is_loss else "up"),
    )

    kpis: List[InsightKpi] = []
    for r in rows[:4]:
        kpis.append(InsightKpi(
            label=str(r.get("name", ""))[:24],
            value=(f"{float(r.get('return_pct', 0)):+.1f}%" if metric == "return"
                   else f"₹{float(r.get('profit_rs', 0)):+,.0f}"),
            sublabel=f"₹{float(r.get('current_value_rs', 0)):,.0f}",
            tone="high" if is_loss else "healthy",
        ))

    findings: List[InsightFinding] = []
    for r in rows[:5]:
        findings.append(InsightFinding(
            priority="high" if is_loss else "medium",
            title=str(r.get("name", "Holding")),
            detail=(f"{r.get('asset_type', '')} · {r.get('sector', '')}"),
            impact_value=(f"{float(r.get('return_pct', 0)):+.1f}%"),
            impact_label="Return",
        ))

    return InsightCardData(
        hero=hero, kpis=kpis, findings=findings,
        recommendation=InsightRecommendation(summary=retrieval.summary),
        actions=_intent_default_actions("ranking"),
    )


def _mf_analysis_to_card(retrieval) -> InsightCardData:
    """MF leaderboard / analysis. Reuses ranking shape since the
    retrieval rows are top-funds-by-metric."""
    return _ranking_to_card(retrieval, "return")


def retrieval_to_insight_card(intent_name: str,
                                intent_extras: Dict[str, Any],
                                retrieval) -> Optional[InsightCardData]:
    """Single entry point — dispatch a Retrieval to the right card maker.

    Returns None when:
      - the intent isn't card-able, OR
      - the retrieval failed (chat falls back to prose-only)."""
    if not retrieval.ok:
        return None
    if intent_name == "concentration":
        return _concentration_to_card(intent_name,
                                       intent_extras.get("grouping"),
                                       retrieval)
    if intent_name == "goals":
        return _goals_to_card(retrieval)
    if intent_name == "health":
        return _health_to_card(retrieval)
    if intent_name == "invest_fresh":
        return _invest_fresh_to_card(intent_extras, retrieval)
    if intent_name == "ranking":
        return _ranking_to_card(retrieval, intent_extras.get("metric") or "profit")
    if intent_name == "mf_analysis":
        return _mf_analysis_to_card(retrieval)
    return None


# ────────────────────────────────────────────────────────────────────
# Widget-endpoint transformers for risk_suitability + portfolio_var.
# These have HTTP endpoints whose data shape is service-specific, so
# they get dedicated transformers (mirrors the stress/overlap pattern).
# ────────────────────────────────────────────────────────────────────


def risk_suitability_to_insight_card(data: Dict[str, Any]) -> InsightCardData:
    """Map the /widgets/risk_suitability payload to InsightCardData."""
    rating = (data.get("risk_rating") or "MEDIUM").upper()
    score = data.get("risk_score") or 0
    misalign = data.get("misalignment") or []
    profile = data.get("user_profile_category") or "—"

    if rating in ("VERY HIGH",):  severity: InsightSeverity = "critical"
    elif rating == "HIGH":         severity = "high"
    elif rating == "MEDIUM":       severity = "medium"
    else:                          severity = "healthy"

    hero = InsightHero(
        severity=severity,
        eyebrow="Risk Suitability",
        headline=f"Portfolio risk: {rating}",
        primary_value=f"{score}/10",
        primary_label="risk score",
        subtitle=f"User profile: {profile}",
    )

    kpis: List[InsightKpi] = [
        InsightKpi(label="Risk rating",    value=rating,           tone=severity),
        InsightKpi(label="User profile",   value=profile),
        InsightKpi(label="Misalignments",  value=str(len(misalign)),
                   tone="high" if misalign else "healthy"),
    ]

    findings: List[InsightFinding] = []
    for m in misalign[:4]:
        if isinstance(m, dict):
            findings.append(InsightFinding(
                priority="high",
                title=str(m.get("label") or m.get("metric") or "Misalignment"),
                detail=str(m.get("message") or m.get("detail") or ""),
            ))
        else:
            findings.append(InsightFinding(priority="high", title=str(m)))

    recommendation = InsightRecommendation(
        summary=(f"Portfolio risk is {rating} vs your {profile} profile — "
                 f"{len(misalign)} misalignment(s) flagged."
                 if misalign else
                 f"Portfolio risk ({rating}) aligns with your {profile} profile."),
        rationale=(
            "Risk suitability checks equity %, small/mid-cap exposure, and "
            "weighted portfolio beta against your stored risk profile. "
            "Misalignments mean a single bad quarter hits harder than your "
            "stated tolerance."
        ),
    )

    return InsightCardData(
        hero=hero, kpis=kpis, findings=findings,
        recommendation=recommendation,
        actions=[
            InsightAction(label="How do I reduce risk?",   action_id="reduce_risk",   style="primary"),
            InsightAction(label="Rebalance to profile",    action_id="rebalance_to_profile", style="secondary"),
            InsightAction(label="Show VaR breakdown",       action_id="show_var",      style="secondary"),
        ],
    )


# ────────────────────────────────────────────────────────────────────
# NIDP (LangGraph) widget_data → insight_card adapter.
#
# The LangGraph engine emits its own AgentResponse with
# `widget_type` + `widget_data` (loose dict) instead of one of our
# native Pydantic models. To paint the unified card in chat without
# refactoring the NIDP toolchain, this adapter normalises the loose
# dict into the matching native model and runs the existing
# per-tool transformer. Tools we don't recognise get None back so
# the caller can fall back to the legacy widget path.
# ────────────────────────────────────────────────────────────────────


def nidp_widget_to_insight_card(widget_type: str,
                                  widget_data: Dict[str, Any]) -> Optional[InsightCardData]:
    """Shape-translate an NIDP `widget_data` dict into our native
    model and run it through the matching insight_card transformer.

    Returns None when the tool isn't supported or the data is too
    sparse to build a meaningful card."""
    wt = (widget_type or "").lower()
    wd = widget_data or {}

    try:
        if wt == "stress_test":
            # Common NIDP fields: stressed_value, drop_pct, loss_rs,
            # rows[*].name + scenario_name on the outer envelope.
            current = wd.get("current_value") or wd.get("current_value_rs") or wd.get("portfolio_value_before")
            stressed = wd.get("stressed_value") or wd.get("stressed_value_rs") or wd.get("portfolio_value_after")
            drop = wd.get("drop_pct")
            # If only loss is reported, derive current from stressed + loss.
            loss = wd.get("loss_rs") or wd.get("loss")
            if current is None and stressed is not None and loss is not None:
                current = float(stressed) + float(loss)
            if drop is None and current and stressed:
                try:
                    drop = (float(stressed) - float(current)) / float(current) * 100
                except Exception:
                    drop = None
            scenario_name = wd.get("scenario_name") or wd.get("scenario") or "Portfolio Stress Test"
            description = wd.get("scenario_description") or wd.get("description")
            recovery = wd.get("recovery_years") or wd.get("historical_recovery_years")
            rows = wd.get("rows") or wd.get("breakdown") or []

            breakdown = []
            for r in rows[:10]:
                name = r.get("fund_name") or r.get("name") or "Holding"
                breakdown.append(StressTestBreakdown(  # type: ignore[name-defined]
                    fund_name=name,
                    current_value_rs=r.get("current_value") or r.get("current_value_rs"),
                    stressed_value_rs=r.get("stressed_value") or r.get("stressed_value_rs"),
                    drop_pct=float(r.get("drop_pct") or 0),
                ))

            data = StressTestData(
                scenario_name=str(scenario_name),
                scenario_description=description,
                current_value_rs=float(current) if current is not None else None,
                stressed_value_rs=float(stressed) if stressed is not None else None,
                drop_pct=round(float(drop), 2) if drop is not None else None,
                recovery_years=float(recovery) if recovery is not None else None,
                breakdown=breakdown,
                insight=wd.get("insight"),
            )
            return stress_to_insight_card(data)

        if wt == "tax_harvest":
            data = TaxHarvestData(
                fy=wd.get("fy", "FY 2025-26"),
                ltcg_used_rs=float(wd.get("ltcg_used_rs", 0)),
                ltcg_limit_rs=float(wd.get("ltcg_limit_rs", 100_000)),
                ltcg_remaining_rs=float(wd.get("ltcg_remaining_rs", 100_000)),
                candidates=[],   # NIDP rows are dicts; skip parsing details
                total_harvestable_rs=wd.get("total_harvestable_rs"),
                warning=wd.get("warning"),
            )
            return tax_harvest_to_insight_card(data)

        if wt == "rebalance_plan":
            actions = []
            for r in (wd.get("rows") or wd.get("actions") or [])[:8]:
                actions.append(RebalanceAction(  # type: ignore[name-defined]
                    action=(r.get("action") or "HOLD").upper(),
                    fund_name=r.get("fund_name") or r.get("name") or "Holding",
                    current_pct=r.get("current_pct"),
                    target_pct=r.get("target_pct"),
                    amount_rs=r.get("amount_rs"),
                    reason=r.get("reason"),
                ))
            data = RebalancePlanData(
                current_value_rs=wd.get("current_value_rs") or wd.get("portfolio_value"),
                actions=actions,
                summary=wd.get("summary") or "Rebalance plan",
            )
            return rebalance_to_insight_card(data)

        if wt == "overlap_reveal":
            data = OverlapRevealData(
                funds=wd.get("funds") or [],
                overlap_pct=wd.get("overlap_pct"),
                top_common_stocks=[],
                verdict=wd.get("verdict"),
            )
            return overlap_to_insight_card(data)

        if wt == "sip_plan":
            data = SipPlanData(
                monthly_budget=float(wd.get("monthly_budget", 0)),
                allocations=[],   # NIDP shape divergence — leave empty
                why_these=wd.get("why_these") or [],
                counter_points=wd.get("counter_points") or [],
            )
            return sip_plan_to_insight_card(data)

        if wt == "fund_comparison":
            data = CompareTableData(
                funds=wd.get("funds") or [],
                rows=[],
                verdict=wd.get("verdict"),
            )
            return compare_to_insight_card(data)

        return None
    except Exception:
        return None


def portfolio_var_to_insight_card(data: Dict[str, Any]) -> InsightCardData:
    """Map the /widgets/portfolio_var payload to InsightCardData.

    Var fields vary by service implementation — we pull the common ones
    (`var_1d_rs`, `var_10d_rs`, `var_1d_pct`, `confidence`, `total_value_rs`).
    Missing fields just don't render in their section."""
    var_1d_rs = data.get("var_1d_rs") or data.get("var_1d")
    var_10d_rs = data.get("var_10d_rs") or data.get("var_10d")
    var_1d_pct = data.get("var_1d_pct") or data.get("var_pct_1d")
    confidence = data.get("confidence") or 0.95
    total_value = data.get("total_value_rs") or data.get("portfolio_value_rs")

    # Severity from 1-day VaR % of portfolio.
    pct = float(var_1d_pct or 0)
    if pct >= 3:   severity: InsightSeverity = "high"
    elif pct >= 2: severity = "medium"
    elif pct >= 1: severity = "info"
    else:          severity = "healthy"

    hero = InsightHero(
        severity=severity,
        eyebrow=f"Value at Risk · {int(confidence*100)}% confidence",
        headline=(f"1-day VaR: ₹{float(var_1d_rs):,.0f}"
                  if var_1d_rs is not None else "Portfolio Value at Risk"),
        primary_value=(f"{pct:.2f}%" if var_1d_pct is not None else None),
        primary_label="of portfolio (1-day)",
    )

    kpis: List[InsightKpi] = []
    if total_value is not None:
        kpis.append(InsightKpi(label="Portfolio value", value=f"₹{float(total_value):,.0f}"))
    if var_1d_rs is not None:
        kpis.append(InsightKpi(label="1-day VaR",  value=f"₹{float(var_1d_rs):,.0f}", tone=severity))
    if var_10d_rs is not None:
        kpis.append(InsightKpi(label="10-day VaR", value=f"₹{float(var_10d_rs):,.0f}",
                                 tone="high" if pct >= 2 else "medium"))
    kpis.append(InsightKpi(label="Confidence", value=f"{int(confidence*100)}%"))

    recommendation = InsightRecommendation(
        summary=(f"With {int(confidence*100)}% confidence, your portfolio "
                 f"shouldn't lose more than ₹{float(var_1d_rs):,.0f} in a single day."
                 if var_1d_rs is not None else
                 "Value at Risk quantifies the worst-case single-day loss at a given confidence level."),
        rationale=(
            "VaR is parametric — it assumes returns are approximately normal "
            "and uses weighted daily volatility. Tail events (crashes) routinely "
            "exceed VaR, so treat it as a baseline, not a ceiling."
        ),
    )

    return InsightCardData(
        hero=hero, kpis=kpis,
        recommendation=recommendation,
        actions=[
            InsightAction(label="How to reduce VaR",       action_id="reduce_var",    style="primary"),
            InsightAction(label="10-day breakdown",        action_id="var_10d_detail", style="secondary"),
            InsightAction(label="Show stress scenario",    action_id="stress_test",   style="secondary"),
        ],
        education=InsightEducation(
            heading="What VaR means",
            body=(
                "VaR is a statistical lower bound — 'in 95% of days, losses won't "
                "exceed this'. The 5% tail can be much worse. Use VaR + stress "
                "tests together to understand both routine and extreme downside."
            ),
        ),
    )
