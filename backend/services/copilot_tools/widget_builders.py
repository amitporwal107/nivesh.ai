"""Widget data builders — single source of truth for the per-tool
payload-construction logic. Both the HTTP endpoints in
`routes/copilot_widgets.py` and the chat orchestrator
(`services/copilot_rag/orchestrator.py`) call these builders, so the
behaviour seen by chat and by direct widget requests is identical.

Each builder takes a `user_id` (and any tool-specific args) and returns
the populated native Pydantic data model. Wrapping into the
`WidgetEnvelope` is the caller's responsibility (the endpoint adds
freshness/agent/CTA; the orchestrator does the same thing with the
extra step of routing the data through an `insight_card_transformer`).

This module is deliberately free of FastAPI imports so it can be
called from background tasks, tests, or scheduled jobs without setting
up a request scope.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from deps import db
from models_copilot_widgets import (
    StressTestData, StressTestBreakdown,
    OverlapRevealData, OverlapStock,
    TaxHarvestData, TaxHarvestCandidate,
    RebalancePlanData, RebalanceAction,
)


# ── Stress Test ────────────────────────────────────────────────────

_STRESS_SCENARIOS = {
    "covid_2020": {
        "name": "COVID-19 Crash (Feb–Mar 2020)",
        "description": "Nifty 50 fell ~38% in 40 days. Debt remained largely stable.",
        "equity_drop": -38.0, "debt_drop": -2.0, "recovery_years": 1.2,
    },
    "gfc_2008": {
        "name": "Global Financial Crisis (2008)",
        "description": "Nifty 50 fell ~60% peak-to-trough over 14 months.",
        "equity_drop": -60.0, "debt_drop": -5.0, "recovery_years": 4.0,
    },
    "rate_shock": {
        "name": "Rate Shock (+200 bps)",
        "description": "Simulates a sudden 200 bps rate hike. Debt NAVs fall ~4–8%.",
        "equity_drop": -12.0, "debt_drop": -7.0, "recovery_years": 1.5,
    },
}


async def _load_holdings(user_id: str) -> list:
    """Pull the user's holdings from either of the two collections in
    use across the codebase. Single point so callers don't repeat the
    fallback."""
    rows: list = []
    async for h in db.holdings.find({"user_id": user_id}, {"_id": 0}):
        rows.append(h)
    if not rows:
        async for h in db.portfolio_holdings.find({"user_id": user_id}, {"_id": 0}):
            rows.append(h)
    return rows


async def build_stress_test_data(
    user_id: str,
    scenario: str = "covid_2020",
    custom_drop_pct: Optional[float] = None,
) -> Tuple[StressTestData, dict]:
    """Return (StressTestData, scenario_meta). Mirrors the logic from
    `routes/copilot_widgets.stress_test` line-for-line so the chat path
    and HTTP path produce identical outputs for the same inputs."""
    raw = await _load_holdings(user_id)

    scen_key = scenario if scenario in _STRESS_SCENARIOS else "covid_2020"
    scen = dict(_STRESS_SCENARIOS[scen_key])
    if scenario == "custom" and custom_drop_pct is not None:
        drop = float(custom_drop_pct)
        scen = {
            "name": f"Custom scenario ({drop:+.0f}%)",
            "description": f"User-defined uniform {drop:+.0f}% shock applied to all holdings.",
            "equity_drop": drop, "debt_drop": drop * 0.1,
            "recovery_years": abs(drop) / 15,
        }

    current_value = sum(float(h.get("current_value") or h.get("value") or 0) for h in raw)

    breakdown: List[StressTestBreakdown] = []
    stressed_total = 0.0
    for h in raw:
        name = h.get("fund_name") or h.get("scheme_name") or "Fund"
        curr = float(h.get("current_value") or h.get("value") or 0)
        asset = (h.get("asset_class") or "equity").lower()
        drop_pct = scen["equity_drop"] if asset == "equity" else scen["debt_drop"]
        stressed = curr * (1 + drop_pct / 100)
        stressed_total += stressed
        breakdown.append(StressTestBreakdown(
            fund_name=name, current_value_rs=curr,
            stressed_value_rs=round(stressed, 2), drop_pct=drop_pct,
        ))

    overall_drop = ((stressed_total - current_value) / current_value * 100) if current_value else 0
    insight = (
        f"Your portfolio would fall to ₹{stressed_total:,.0f} "
        f"({overall_drop:+.1f}%) under this scenario. "
        f"Historical recovery took ~{scen['recovery_years']} year(s)."
    ) if current_value else "Add holdings to run a stress test."

    data = StressTestData(
        scenario_name=scen["name"],
        scenario_description=scen.get("description"),
        current_value_rs=current_value or None,
        stressed_value_rs=round(stressed_total, 2) if current_value else None,
        drop_pct=round(overall_drop, 2) if current_value else None,
        recovery_years=scen.get("recovery_years"),
        breakdown=breakdown[:10],
        insight=insight,
    )
    return data, scen


# ── Overlap ────────────────────────────────────────────────────────

async def build_overlap_data(
    user_id: str,
    scheme_codes: Optional[List[str]] = None,
) -> OverlapRevealData:
    """Compute stock-level overlap across funds, identical to
    `routes/copilot_widgets.overlap_reveal`."""
    codes: List[str] = list(scheme_codes or [])
    if not codes:
        async for h in db.holdings.find({"user_id": user_id}, {"_id": 0}):
            c = h.get("scheme_code") or h.get("isin")
            if c:
                codes.append(c)
        if not codes:
            async for h in db.portfolio_holdings.find({"user_id": user_id}, {"_id": 0}):
                c = h.get("scheme_code") or h.get("isin")
                if c:
                    codes.append(c)
    codes = list(dict.fromkeys(codes))[:4]

    fund_stocks: dict = {}
    fund_names: dict = {}
    for code in codes:
        doc = await db.mf_master.find_one(
            {"$or": [{"scheme_code": code}, {"isin": code}]}, {"_id": 0}
        )
        if not doc:
            continue
        fund_names[code] = doc.get("scheme_name") or code
        stocks_raw = doc.get("top_holdings") or []
        fund_stocks[code] = {
            (s.get("stock_name") or s.get("name") or "").strip()
            for s in stocks_raw if s.get("stock_name") or s.get("name")
        }

    all_funds = list(fund_stocks.keys())
    names = [fund_names.get(c, c) for c in all_funds]
    common_stocks: List[OverlapStock] = []
    overlap_pct: Optional[float] = None
    matrix: Optional[List[List[float]]] = None

    if len(all_funds) == 2:
        s0, s1 = fund_stocks[all_funds[0]], fund_stocks[all_funds[1]]
        denom = len(s0 | s1)
        overlap_pct = round(len(s0 & s1) / denom * 100, 1) if denom else 0.0
        for stk in sorted(s0 & s1):
            if stk:
                common_stocks.append(OverlapStock(
                    stock_name=stk,
                    funds=[fund_names.get(c, c) for c in all_funds if stk in fund_stocks[c]],
                ))
    elif len(all_funds) > 2:
        matrix = []
        for ci in all_funds:
            row = []
            for cj in all_funds:
                si, sj = fund_stocks[ci], fund_stocks[cj]
                denom = len(si | sj)
                row.append(round(len(si & sj) / denom * 100, 1) if denom else 0.0)
            matrix.append(row)
        all_common = set.intersection(*fund_stocks.values()) if fund_stocks else set()
        for stk in sorted(all_common):
            if stk:
                common_stocks.append(OverlapStock(stock_name=stk, funds=names))

    verdict: Optional[str] = None
    if overlap_pct is not None:
        if overlap_pct > 50:
            verdict = f"High overlap ({overlap_pct}%) — these funds largely hold the same stocks."
        elif overlap_pct > 25:
            verdict = f"Moderate overlap ({overlap_pct}%) — some diversification benefit."
        else:
            verdict = f"Low overlap ({overlap_pct}%) — good diversification between these funds."
    elif not all_funds:
        verdict = "No fund data found. Try specifying scheme codes or add holdings."

    return OverlapRevealData(
        funds=names or codes,
        overlap_pct=overlap_pct,
        overlap_matrix=matrix,
        top_common_stocks=common_stocks[:8],
        verdict=verdict,
    )


# ── Tax Harvest ────────────────────────────────────────────────────

async def build_tax_harvest_data(user_id: str) -> TaxHarvestData:
    """Build the LTCG harvest candidate list. Mirrors
    `routes/copilot_widgets.tax_harvest`."""
    raw = await _load_holdings(user_id)

    cg_doc = await db.capital_gains_summary.find_one({"user_id": user_id}) or {}
    ltcg_used = float(cg_doc.get("ltcg_booked_rs") or 0)
    ltcg_limit = 100_000.0
    ltcg_remaining = max(0.0, ltcg_limit - ltcg_used)

    candidates: List[TaxHarvestCandidate] = []
    total_harvestable = 0.0
    for h in raw:
        gain = float(h.get("unrealised_gain") or h.get("gain") or 0)
        days = int(h.get("days_held") or h.get("holding_days") or 0)
        cost = float(h.get("invested_value") or h.get("cost_basis") or 0)
        curr = float(h.get("current_value") or h.get("value") or 0)
        name = h.get("fund_name") or h.get("scheme_name") or "Unknown Fund"
        if gain <= 0 or days < 365:
            continue
        eligible = gain <= ltcg_remaining
        total_harvestable += gain if eligible else 0
        candidates.append(TaxHarvestCandidate(
            fund_name=name, current_value_rs=curr or None,
            cost_basis_rs=cost or None, gain_rs=gain, gain_type="LTCG",
            days_held=days or None, eligible=eligible, wash_sale_risk=False,
        ))
    candidates.sort(key=lambda c: c.gain_rs)

    return TaxHarvestData(
        fy="FY 2025-26",
        ltcg_used_rs=ltcg_used, ltcg_limit_rs=ltcg_limit,
        ltcg_remaining_rs=ltcg_remaining,
        candidates=candidates[:8],
        total_harvestable_rs=total_harvestable or None,
        warning="Repurchasing within 30 days may trigger wash-sale rules in some jurisdictions." if candidates else None,
    )


# ── Rebalance ──────────────────────────────────────────────────────

async def build_rebalance_data(user_id: str) -> RebalancePlanData:
    """Build rebalance actions toward the user's risk-profile-derived target allocation.

    Target comes from compute_target_allocation() — the single canonical source.
    Previously hardcoded to 65/35 for all users regardless of risk profile.
    """
    from services.target_allocator import compute_target_allocation
    raw = await _load_holdings(user_id)
    current_value = sum(float(h.get("current_value") or h.get("value") or 0) for h in raw)

    # Resolve user's personalised target from the allocation_bands service
    ta = await compute_target_allocation(user_id)
    target_equity = ta.allocation.get("equity", 55.0)
    target_debt   = ta.allocation.get("debt",   35.0)
    risk_label    = ta.risk_category.capitalize()

    actions: List[RebalanceAction] = []
    if raw and current_value > 0:
        equity_val = sum(
            float(h.get("current_value") or 0)
            for h in raw
            if (h.get("asset_class") or "equity").lower() == "equity"
        )
        debt_val = current_value - equity_val
        equity_pct = round(equity_val / current_value * 100, 1)
        debt_pct = round(debt_val / current_value * 100, 1)

        if equity_pct > target_equity + 5:
            excess = (equity_pct - target_equity) / 100 * current_value
            delta = round(equity_pct - target_equity, 1)
            actions.append(RebalanceAction(
                action="SELL", fund_name="Highest-drift equity fund",
                current_pct=equity_pct, target_pct=target_equity,
                amount_rs=round(excess, -2),
                reason=f"Equity at {equity_pct}% — {delta}pp above your {risk_label} band target of {target_equity}%",
            ))
            actions.append(RebalanceAction(
                action="BUY", fund_name="Short-term Debt Fund",
                current_pct=debt_pct, target_pct=target_debt,
                amount_rs=round(excess, -2),
                reason=f"Debt at {debt_pct}% — redirect equity proceeds to restore your {risk_label} debt target",
            ))
        elif equity_pct < target_equity - 5:
            deficit = (target_equity - equity_pct) / 100 * current_value
            delta = round(target_equity - equity_pct, 1)
            actions.append(RebalanceAction(
                action="BUY", fund_name="Flexi-Cap Fund",
                current_pct=equity_pct, target_pct=target_equity,
                amount_rs=round(deficit, -2),
                reason=f"Equity at {equity_pct}% — {delta}pp below your {risk_label} band target of {target_equity}%",
            ))
        else:
            actions.append(RebalanceAction(
                action="HOLD", fund_name="All holdings",
                current_pct=equity_pct, target_pct=target_equity,
                reason=f"Equity at {equity_pct}% — within ±5pp of your {risk_label} band target. No rebalance needed.",
            ))

        for h in raw[:3]:
            plan = (h.get("plan_type") or "").lower()
            name = h.get("fund_name") or h.get("scheme_name") or "Fund"
            if plan == "regular":
                actions.append(RebalanceAction(
                    action="SWITCH", fund_name=name,
                    reason="Switch Regular → Direct to save ~0.8%/yr expense",
                ))

    summary = (
        f"Portfolio value ₹{current_value:,.0f}. "
        + (f"{len(actions)} action(s) suggested." if actions else "No rebalance needed.")
    )
    return RebalancePlanData(
        current_value_rs=current_value or None,
        actions=actions,
        summary=summary,
    )
