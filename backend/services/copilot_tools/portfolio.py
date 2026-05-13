"""Portfolio analytics tools for the Nivesh Copilot.

Wraps existing service functions for use by the RAG orchestrator and
future LangGraph agents:

  get_portfolio_xirr      — per-holding XIRR + portfolio weighted return
  get_portfolio_summary   — allocation, overlap, sector exposure
  get_portfolio_overlap   — pairwise fund overlap from portfolio_intelligence
  get_rebalance_plan      — equity/debt drift + actions
  get_tax_harvest_candidates — unrealised-loss positions for harvesting
  run_stress_test         — historical crash scenario simulation
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Stress scenarios (mirrors routes/copilot_widgets.py) ─────────────────
_STRESS_SCENARIOS: Dict[str, Dict[str, Any]] = {
    "covid_2020": {
        "name": "COVID-19 Crash (Feb–Mar 2020)",
        "equity_drop": -38.0,
        "debt_drop": -2.0,
        "recovery_years": 1.2,
    },
    "gfc_2008": {
        "name": "Global Financial Crisis (2008)",
        "equity_drop": -60.0,
        "debt_drop": -5.0,
        "recovery_years": 4.0,
    },
    "rate_shock": {
        "name": "Rate Shock (+200 bps)",
        "equity_drop": -12.0,
        "debt_drop": -7.0,
        "recovery_years": 1.5,
    },
}


@dataclass
class PortfolioResult:
    ok: bool
    summary: str
    data: Dict[str, Any] = field(default_factory=dict)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


# ── Holdings loader ───────────────────────────────────────────────────────

async def _load_holdings(user_id: str) -> List[Dict[str, Any]]:
    from deps import db
    raw: List[Dict[str, Any]] = []
    async for h in db.holdings.find({"user_id": user_id}, {"_id": 0}):
        raw.append(h)
    if not raw:
        async for h in db.portfolio_holdings.find({"user_id": user_id}, {"_id": 0}):
            raw.append(h)
    return raw


# ── XIRR ────────────────────────────────────────────────────────────────

async def get_portfolio_xirr(user_id: str) -> PortfolioResult:
    """Compute per-holding XIRR and portfolio-level weighted average.

    Used for: "What is my portfolio XIRR?", "How are my investments performing?"
    """
    from services.portfolio_enrichment import _holding_xirr

    holdings = await _load_holdings(user_id)
    if not holdings:
        return PortfolioResult(ok=False, summary="No holdings found", error="no_holdings")

    rows: List[Dict[str, Any]] = []
    total_invested = 0.0
    total_current = 0.0
    weighted_xirr_sum = 0.0
    weighted_xirr_weight = 0.0

    for h in holdings:
        qty = float(h.get("quantity") or 0)
        bp = float(h.get("buy_price") or h.get("avg_cost") or 0)
        cp = float(h.get("current_price") or 0)
        name = h.get("name") or h.get("scheme_name") or h.get("fund_name") or "Unknown"
        buy_date = h.get("buy_date") or h.get("purchase_date")

        if qty <= 0 or cp <= 0:
            continue

        invested = qty * bp
        current = qty * cp
        gain = current - invested
        ret_pct = (gain / invested * 100.0) if invested > 0 else 0.0

        xirr_pct = _holding_xirr(buy_date, bp, cp, qty)

        total_invested += invested
        total_current += current
        if xirr_pct is not None and invested > 0:
            weighted_xirr_sum += xirr_pct * invested
            weighted_xirr_weight += invested

        rows.append({
            "name": name,
            "asset_type": h.get("asset_type", "equity"),
            "invested_rs": round(invested, 0),
            "current_rs": round(current, 0),
            "gain_rs": round(gain, 0),
            "return_pct": round(ret_pct, 2),
            "xirr_pct": round(xirr_pct, 2) if xirr_pct is not None else None,
        })

    if not rows:
        return PortfolioResult(ok=False, summary="No priced holdings found", error="no_data")

    portfolio_gain = total_current - total_invested
    portfolio_return_pct = (portfolio_gain / total_invested * 100.0) if total_invested > 0 else 0.0
    portfolio_xirr = (weighted_xirr_sum / weighted_xirr_weight) if weighted_xirr_weight > 0 else None

    xirr_str = f" (XIRR {portfolio_xirr:+.1f}%)" if portfolio_xirr is not None else ""
    summary = (
        f"Portfolio: invested ₹{total_invested:,.0f} → current ₹{total_current:,.0f} "
        f"= {portfolio_return_pct:+.1f}% absolute return{xirr_str} "
        f"across {len(rows)} positions"
    )

    return PortfolioResult(
        ok=True,
        summary=summary,
        data={
            "total_invested_rs": round(total_invested, 0),
            "total_current_rs": round(total_current, 0),
            "total_gain_rs": round(portfolio_gain, 0),
            "portfolio_return_pct": round(portfolio_return_pct, 2),
            "portfolio_xirr_pct": round(portfolio_xirr, 2) if portfolio_xirr is not None else None,
            "position_count": len(rows),
        },
        rows=sorted(rows, key=lambda r: r.get("xirr_pct") or -999, reverse=True),
    )


# ── Portfolio summary (allocation + overlap) ──────────────────────────────

async def get_portfolio_summary(user_id: str) -> PortfolioResult:
    """High-level portfolio snapshot: allocation, overlap, sector.

    Used for: "Summarise my portfolio", "How concentrated am I?"
    """
    try:
        from services import portfolio_intelligence as PI
        intel = await PI.compute_portfolio_intelligence(user_id)
    except Exception as exc:
        logger.warning("portfolio_summary pi_failed user=%s error=%s", user_id, exc)
        return PortfolioResult(ok=False, summary="Portfolio intelligence unavailable", error=str(exc))

    alloc = intel.get("holistic_allocation") or {}
    top_stocks = (intel.get("top_stocks") or [])[:5]
    pairs = (intel.get("pairwise_overlap") or [])
    high_overlap = [p for p in pairs if p.get("overlap_pct", 0) >= 40]
    sectors = (intel.get("sector_exposure") or [])[:5]

    equity_pct = alloc.get("equity_pct", 0)
    debt_pct = alloc.get("debt_pct", 0)
    total_rs = alloc.get("total_value", 0)

    summary_parts = [f"Total ₹{total_rs:,.0f}" if total_rs else "Portfolio"]
    if equity_pct:
        summary_parts.append(f"equity {equity_pct:.0f}%")
    if debt_pct:
        summary_parts.append(f"debt {debt_pct:.0f}%")
    if high_overlap:
        summary_parts.append(f"{len(high_overlap)} high-overlap fund pair(s)")

    rows = []
    for s in top_stocks:
        rows.append({
            "type": "stock_exposure",
            "label": s.get("name") or s.get("slug", ""),
            "value": s.get("exposure_pct", 0),
            "amount_rs": s.get("exposure_rs", 0),
        })
    for sec in sectors:
        rows.append({
            "type": "sector",
            "label": sec.get("sector", "Unknown"),
            "value": sec.get("pct", 0),
            "amount_rs": sec.get("rs", 0),
        })

    return PortfolioResult(
        ok=True,
        summary=" · ".join(summary_parts),
        data={
            "total_value_rs": total_rs,
            "equity_pct": equity_pct,
            "debt_pct": debt_pct,
            "high_overlap_pairs": len(high_overlap),
            "effective_stocks": intel.get("effective_stocks"),
            "compression_score": intel.get("compression_score"),
        },
        rows=rows,
    )


# ── Portfolio overlap ─────────────────────────────────────────────────────

async def get_portfolio_overlap(user_id: str) -> PortfolioResult:
    """Pairwise MF overlap for user's fund holdings.

    Used for: "Which of my funds overlap?", "Show redundancy in my portfolio"
    """
    try:
        from services import portfolio_intelligence as PI
        intel = await PI.compute_portfolio_intelligence(user_id)
    except Exception as exc:
        return PortfolioResult(ok=False, summary="Could not compute overlap", error=str(exc))

    pairs = intel.get("pairwise_overlap") or []
    if not pairs:
        return PortfolioResult(ok=True, summary="No pairwise overlap data — MF holdings may lack portfolio disclosures", rows=[])

    rows = [
        {
            "fund_a": p.get("a") or p.get("fund_a", ""),
            "fund_b": p.get("b") or p.get("fund_b", ""),
            "overlap_pct": round(float(p.get("overlap_pct") or 0), 1),
            "shared_count": p.get("shared_stocks") or len(p.get("shared", [])),
            "top_shared": (p.get("reasons") or [])[:3],
        }
        for p in pairs
    ]
    rows.sort(key=lambda r: r["overlap_pct"], reverse=True)

    high = [r for r in rows if r["overlap_pct"] >= 40]
    summary = (
        f"{len(rows)} fund pair(s) analysed; "
        f"{len(high)} pair(s) with ≥40% overlap"
        + (f" — top: {rows[0]['fund_a']} ↔ {rows[0]['fund_b']} {rows[0]['overlap_pct']:.0f}%" if rows else "")
    )
    return PortfolioResult(ok=True, summary=summary, rows=rows)


# ── Rebalance plan ────────────────────────────────────────────────────────

async def get_rebalance_plan(user_id: str) -> PortfolioResult:
    """Compute equity/debt rebalance actions from current holdings.

    Used for: "Should I rebalance?", "How should I rebalance my portfolio?"
    """
    holdings = await _load_holdings(user_id)
    if not holdings:
        return PortfolioResult(ok=False, summary="No holdings found", error="no_holdings")

    current_value = sum(
        float(h.get("current_value") or h.get("value") or
              float(h.get("current_price") or 0) * float(h.get("quantity") or 0))
        for h in holdings
    )
    if current_value <= 0:
        return PortfolioResult(ok=False, summary="Cannot compute — holdings have no current value", error="no_value")

    equity_val = sum(
        float(h.get("current_value") or float(h.get("current_price") or 0) * float(h.get("quantity") or 0))
        for h in holdings
        if (h.get("asset_class") or h.get("asset_type") or "equity").lower() in ("equity", "stock")
    )
    debt_val = current_value - equity_val
    equity_pct = round(equity_val / current_value * 100, 1)
    debt_pct = round(debt_val / current_value * 100, 1)

    target_equity = 65.0
    target_debt = 35.0
    actions: List[Dict[str, Any]] = []

    if equity_pct > target_equity + 5:
        excess = (equity_pct - target_equity) / 100 * current_value
        actions.append({
            "action": "SELL",
            "asset": "equity",
            "amount_rs": round(excess, -2),
            "current_pct": equity_pct,
            "target_pct": target_equity,
            "reason": f"Equity {equity_pct:.0f}% > target {target_equity:.0f}% — trim excess",
        })
        actions.append({
            "action": "BUY",
            "asset": "debt",
            "amount_rs": round(excess, -2),
            "current_pct": debt_pct,
            "target_pct": target_debt,
            "reason": "Redirect proceeds to short-term debt fund",
        })
    elif equity_pct < target_equity - 5:
        deficit = (target_equity - equity_pct) / 100 * current_value
        actions.append({
            "action": "BUY",
            "asset": "equity",
            "amount_rs": round(deficit, -2),
            "current_pct": equity_pct,
            "target_pct": target_equity,
            "reason": f"Equity {equity_pct:.0f}% < target {target_equity:.0f}% — add to flexi-cap fund",
        })
    else:
        actions.append({
            "action": "HOLD",
            "asset": "all",
            "amount_rs": 0,
            "current_pct": equity_pct,
            "target_pct": target_equity,
            "reason": f"Equity {equity_pct:.0f}% is within ±5pp of target — no rebalance needed",
        })

    # Flag regular-plan MFs for direct-plan switch
    for h in holdings:
        if (h.get("plan_type") or "").lower() == "regular":
            name = h.get("fund_name") or h.get("scheme_name") or h.get("name", "Fund")
            actions.append({
                "action": "SWITCH",
                "asset": name,
                "amount_rs": None,
                "reason": "Switch to Direct plan to save ~0.8% p.a. in expenses",
            })

    summary = (
        f"Portfolio ₹{current_value:,.0f}: equity {equity_pct:.0f}% / debt {debt_pct:.0f}% "
        f"vs target {target_equity:.0f}/{target_debt:.0f}. "
        f"{len(actions)} action(s) suggested."
    )
    return PortfolioResult(
        ok=True,
        summary=summary,
        data={
            "current_value_rs": current_value,
            "equity_pct": equity_pct,
            "debt_pct": debt_pct,
            "target_equity_pct": target_equity,
            "target_debt_pct": target_debt,
        },
        rows=actions,
    )


# ── Tax harvest (FY 2025-26 engine) ──────────────────────────────────────

async def get_tax_harvest_candidates(
    user_id: str,
    *,
    slab_rate: float = 0.30,
) -> PortfolioResult:
    """Per-holding tax estimate using the FY 2025-26 capital gains engine.

    Uses `capital_gains_engine.quick_tax_estimate()` which correctly applies:
    - ₹1,25,000 LTCG exemption (shared across equity + REIT)
    - Grandfathering (pre-31-Jan-2018 cost basis)
    - 20% STCG / 12.5% LTCG rates + 4% cess
    - SGB-RBI full exemption
    - Debt MF acquired post-Apr-2023 → slab rate

    Returns rows sorted: losses first (harvest immediately), then LTCG
    with high tax liability (review urgently), then STCG.

    Used for: "Which positions should I sell for tax savings?",
              "Help me harvest tax losses", "Show my capital gains exposure"
    """
    from services.capital_gains_engine import quick_tax_estimate

    holdings = await _load_holdings(user_id)
    if not holdings:
        return PortfolioResult(ok=False, summary="No holdings found", error="no_holdings")

    rows: List[Dict[str, Any]] = []
    ltcg_used = 0.0          # track ₹1,25,000 exemption consumed as we iterate
    total_tax_if_sold = 0.0
    total_harvestable_loss = 0.0

    for h in holdings:
        est = quick_tax_estimate(h, ltcg_used=ltcg_used, slab_rate=slab_rate)
        if not est.get("ok"):
            continue

        capital_gain = est["capital_gain"]
        tax_if_sold = est["tax_liability"]
        is_lt = est["is_long_term"]
        regime = est.get("tax_regime", "")

        # Update LTCG exemption tracker for subsequent holdings
        if is_lt and capital_gain > 0 and "equity" in regime:
            ltcg_used += capital_gain

        gain_type = (
            "EXEMPT" if regime == "sgb_rbi_exempt" else
            "LTCG"   if is_lt else
            "STCG"
        )
        harvest_saving = abs(tax_if_sold) if capital_gain < 0 else 0.0

        name = h.get("fund_name") or h.get("scheme_name") or h.get("name", "Unknown")
        rows.append({
            "name":             name,
            "asset_category":   est.get("asset_category", ""),
            "gain_type":        gain_type,
            "capital_gain":     round(capital_gain, 0),
            "tax_if_sold":      round(tax_if_sold, 0),
            "tax_saved_if_harvested": round(harvest_saving, 0),
            "holding_days":     est.get("holding_days", 0),
            "is_long_term":     is_lt,
            "is_grandfathered": est.get("is_grandfathered", False),
            "tax_rate":         est.get("tax_rate", 0),
            "tax_regime":       regime,
            "note":             est.get("note", ""),
        })

        if capital_gain < 0:
            total_harvestable_loss += abs(capital_gain)
        if capital_gain > 0:
            total_tax_if_sold += tax_if_sold

    if not rows:
        return PortfolioResult(
            ok=True,
            summary="Insufficient holding data for tax estimate",
            rows=[],
        )

    # Sort: losses first, then by descending tax liability
    rows.sort(key=lambda r: (0 if r["capital_gain"] < 0 else 1, -abs(r["tax_if_sold"])))

    loss_count = sum(1 for r in rows if r["capital_gain"] < 0)
    gain_count = len(rows) - loss_count
    summary = (
        f"{loss_count} loss position(s) to harvest (saving up to ₹{total_harvestable_loss * slab_rate:,.0f} tax); "
        f"{gain_count} gain position(s) with ₹{total_tax_if_sold:,.0f} total tax if exited today"
    )
    return PortfolioResult(
        ok=True,
        summary=summary,
        data={
            "total_harvestable_loss_rs": round(total_harvestable_loss, 0),
            "total_tax_if_sold_rs": round(total_tax_if_sold, 0),
            "ltcg_exemption_used_rs": round(ltcg_used, 0),
            "ltcg_exemption_remaining_rs": max(0, 125_000 - round(ltcg_used, 0)),
            "candidate_count": len(rows),
            "slab_rate_used": slab_rate,
        },
        rows=rows,
    )


async def get_full_tax_report(
    user_id: str,
    *,
    slab_rate: float = 0.30,
    total_income_rs: float = 0.0,
) -> PortfolioResult:
    """Full FY 2025-26 capital gains report using compute_capital_gains().

    Unlike get_tax_harvest_candidates() (per-holding estimates), this runs the
    complete 10-step pipeline — cross-holding loss set-off, correct ₹1,25,000
    shared exemption, surcharge, cess — giving the actual net tax payable if
    the entire portfolio were exited today.

    Used for: "What is my total capital gains tax this year?",
              "Show me my full tax liability", "Tax report for my portfolio"
    """
    from services.capital_gains_engine import (
        classify_asset, compute_capital_gains, Transaction,
    )
    from datetime import date as _date

    holdings = await _load_holdings(user_id)
    if not holdings:
        return PortfolioResult(ok=False, summary="No holdings found", error="no_holdings")

    transactions: List[Any] = []
    skipped = 0

    for h in holdings:
        try:
            bp  = float(h.get("buy_price") or 0)
            cp  = float(h.get("current_price") or 0)
            qty = float(h.get("quantity") or 0)
            bd_raw = h.get("buy_date") or h.get("purchase_date")

            if bp <= 0 or cp <= 0 or qty <= 0 or not bd_raw:
                skipped += 1
                continue

            from datetime import datetime as _dt
            if isinstance(bd_raw, str):
                bd = _dt.fromisoformat(bd_raw.replace("Z", "+00:00")).date()
            elif isinstance(bd_raw, _dt):
                bd = bd_raw.date()
            else:
                bd = bd_raw

            atype    = h.get("asset_type") or ""
            name     = h.get("fund_name") or h.get("scheme_name") or h.get("name") or ""
            eq_alloc = h.get("equity_allocation_pct")
            fmv      = h.get("fmv_31jan2018")

            category = classify_asset(atype, name, equity_allocation_pct=eq_alloc, acquisition_date=bd)
            transactions.append(Transaction(
                asset_category=category,
                quantity=qty,
                buy_price=bp,
                sell_price=cp,
                buy_date=bd,
                sell_date=_date.today(),
                fmv_31jan2018=float(fmv) if fmv is not None else None,
                name=name,
                holding_id=str(h.get("holding_id") or h.get("id") or ""),
            ))
        except Exception as exc:
            logger.debug("skip holding in full tax report: %s", exc)
            skipped += 1

    if not transactions:
        return PortfolioResult(
            ok=True,
            summary="No valid holdings to compute tax report",
            rows=[],
            data={"skipped": skipped},
        )

    result = compute_capital_gains(
        transactions,
        slab_rate=slab_rate,
        total_income_rs=total_income_rs,
    )
    d = result.to_dict()

    # Per-holding rows from gain_records
    rows = []
    for gr in result.gain_records:
        t = gr.transaction
        rows.append({
            "name":             t.name or "Unknown",
            "asset_category":   t.asset_category.value,
            "gain_type":        "LTCG" if gr.is_long_term else "STCG",
            "capital_gain":     round(gr.gross_gain, 0),
            "holding_days":     gr.holding_days,
            "is_long_term":     gr.is_long_term,
            "is_grandfathered": gr.is_grandfathered,
            "is_exempt":        gr.is_exempt,
            "tax_category":     gr.tax_category,
            "cost_basis":       round(gr.cost_basis, 2),
            "note":             gr.note,
        })

    rows.sort(key=lambda r: -abs(r["capital_gain"]))

    summary = (
        f"Total tax payable if portfolio exited today: ₹{d['net_tax_payable']:,.0f} "
        f"(LTCG ₹{d['ltcg_equity_tax']:,.0f} + STCG ₹{d['stcg_tax']:,.0f} + slab ₹{d['slab_tax']:,.0f}); "
        f"LTCG exemption applied ₹{d['equity_ltcg_exemption']:,.0f}"
    )
    if skipped:
        summary += f"; {skipped} holding(s) skipped (missing price/date data)"

    return PortfolioResult(
        ok=True,
        summary=summary,
        data=d,
        rows=rows,
    )


# ── Stress test ───────────────────────────────────────────────────────────

async def run_stress_test(user_id: str, scenario: str = "covid_2020") -> PortfolioResult:
    """Simulate portfolio value under a historical crash scenario.

    Used for: "What if market crashes?", "Run a stress test", "COVID scenario",
              "How much would I lose in a 2008-style crash?"

    Args:
        scenario: "covid_2020" | "gfc_2008" | "rate_shock"
    """
    holdings = await _load_holdings(user_id)
    if not holdings:
        return PortfolioResult(ok=False, summary="No holdings found", error="no_holdings")

    scen = _STRESS_SCENARIOS.get(scenario, _STRESS_SCENARIOS["covid_2020"])

    current_value = 0.0
    stressed_value = 0.0
    rows: List[Dict[str, Any]] = []

    for h in holdings:
        name = h.get("fund_name") or h.get("scheme_name") or h.get("name", "Fund")
        curr = float(
            h.get("current_value") or h.get("value") or
            float(h.get("current_price") or 0) * float(h.get("quantity") or 0)
        )
        asset = (h.get("asset_class") or h.get("asset_type") or "equity").lower()
        drop_pct = scen["equity_drop"] if asset in ("equity", "stock", "mutual_fund", "etf") else scen["debt_drop"]
        stressed = curr * (1 + drop_pct / 100)

        current_value += curr
        stressed_value += stressed
        rows.append({
            "name": name,
            "asset_type": asset,
            "current_rs": round(curr, 0),
            "stressed_rs": round(stressed, 0),
            "loss_rs": round(stressed - curr, 0),
            "drop_pct": drop_pct,
        })

    if current_value <= 0:
        return PortfolioResult(ok=False, summary="Holdings have no current value", error="no_value")

    total_loss = stressed_value - current_value
    total_drop_pct = total_loss / current_value * 100

    rows.sort(key=lambda r: r["loss_rs"])  # worst loss first

    summary = (
        f"Scenario: {scen['name']} — "
        f"portfolio would fall from ₹{current_value:,.0f} to ₹{stressed_value:,.0f} "
        f"({total_drop_pct:+.1f}%, loss ₹{total_loss:,.0f}). "
        f"Historical recovery: ~{scen['recovery_years']:.1f} years."
    )
    return PortfolioResult(
        ok=True,
        summary=summary,
        data={
            "scenario": scen["name"],
            "current_value_rs": round(current_value, 0),
            "stressed_value_rs": round(stressed_value, 0),
            "total_loss_rs": round(total_loss, 0),
            "total_drop_pct": round(total_drop_pct, 2),
            "recovery_years": scen["recovery_years"],
        },
        rows=rows,
    )
