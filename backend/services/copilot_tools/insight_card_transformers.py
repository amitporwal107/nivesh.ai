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

from typing import List, Optional

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
