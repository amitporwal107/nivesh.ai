"""Switch simulator — Phase D of the optimisation engine.

Given a Keep/Exit plan + redeployment plan, projects the portfolio
forward 10 years and returns a Before/After comparison the UI can
render as a table or stacked bars.

# What this simulates

For each scenario (Before = do nothing, After = follow the plan):
  - Total invested today (same in both — we don't model new SIPs here)
  - 10Y projected value at the blended CAGR of that scenario's mix
  - Net of taxes the user would pay on the switch
  - Number of holdings
  - Weighted expense ratio
  - Diversification score (reuses _build_summary's heuristic)

# CAGR assumptions

Blended CAGR per bucket, FY24-25 reasonable mid-cycle assumptions:
  equity:        13%/yr
  international: 11%/yr  (geo-diversified, slightly lower base)
  debt:           7%/yr
  gold:           9%/yr
  other:         10%/yr  (REITs / alts midpoint)

Net CAGR = bucket weights × bucket CAGR − weighted expense ratio.

These are deliberately conservative; the wealth delta the UI shows is
the **difference** between After and Before, which dampens absolute
assumption error.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .redeploy_suggester import _classify_bucket, current_allocation

# Mid-cycle CAGR assumptions per bucket (decimal, pre-expense)
BUCKET_CAGR = {
    "equity":        0.13,
    "international": 0.11,
    "debt":          0.07,
    "gold":          0.09,
    "other":         0.10,
}

PROJECTION_YEARS = 10
DEFAULT_BLENDED_ER = 0.0120  # 1.20% — typical actively-managed equity blend


def _holding_value(h: Dict[str, Any]) -> float:
    return float(h.get("quantity") or 0) * float(h.get("current_price") or 0)


def _portfolio_value(holdings: List[Dict[str, Any]]) -> float:
    return sum(_holding_value(h) for h in holdings)


def _weighted_expense_ratio(holdings: List[Dict[str, Any]]) -> float:
    """Portfolio-wide expense ratio = Σ (weight × ER per holding)."""
    from .duplicate_optimizer import _expense_ratio  # avoid circular at top
    total = _portfolio_value(holdings)
    if total <= 0:
        return DEFAULT_BLENDED_ER
    er = 0.0
    for h in holdings:
        if h.get("asset_type") not in ("mutual_fund", "etf"):
            continue
        val = _holding_value(h)
        er += (val / total) * _expense_ratio(h)
    return er


def _blended_cagr(allocation_pct: Dict[str, float], expense_ratio: float) -> float:
    """Σ (bucket weight × bucket CAGR) − weighted expense."""
    gross = sum(allocation_pct.get(k, 0.0) * BUCKET_CAGR[k] for k in BUCKET_CAGR)
    return gross - expense_ratio


def _project_value(initial: float, cagr: float, years: int = PROJECTION_YEARS) -> float:
    if initial <= 0:
        return 0.0
    return initial * ((1 + cagr) ** years)


def _portfolio_snapshot(
    holdings: List[Dict[str, Any]],
    label: str,
) -> Dict[str, Any]:
    total = _portfolio_value(holdings)
    er = _weighted_expense_ratio(holdings)
    alloc = current_allocation(holdings)
    cagr = _blended_cagr(alloc, er)
    proj = _project_value(total, cagr)
    return {
        "label": label,
        "total_invested_rs": round(total, 2),
        "mf_count": sum(1 for h in holdings if h.get("asset_type") in ("mutual_fund", "etf")),
        "weighted_expense_ratio_pct": round(er * 100, 2),
        "blended_cagr_pct": round(cagr * 100, 2),
        "projected_10y_value_rs": round(proj, 2),
        "allocation_pct": {k: round(v * 100, 1) for k, v in alloc.items()},
    }


def simulate_switch(
    insight: Dict[str, Any],
    holdings: List[Dict[str, Any]],
    plan: Dict[str, Any],
    redeploy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the Before/After comparison.

    Args:
      insight: the duplicate-pair insight
      holdings: current holdings list
      plan: OptimizationPlan.to_dict() — has `keep`, `exit`, `capital_released_rs`,
            `tax_impact_rs`, `annual_fee_savings_rs`
      redeploy: result of `suggest_redeployment` (optional — when omitted we
                assume the freed capital stays in the keep fund)
    """
    from .duplicate_optimizer import _name_tokens  # token-based matcher
    exit_name = (plan.get("exit") or {}).get("fund_name", "")
    keep_name = (plan.get("keep") or {}).get("fund_name", "")
    exit_tokens = _name_tokens(exit_name)
    keep_tokens = _name_tokens(keep_name)
    capital = float(plan.get("capital_released_rs") or 0)
    tax = float(plan.get("tax_impact_rs") or 0)

    # ── BEFORE: untouched holdings
    before = _portfolio_snapshot(holdings, "Before")

    # ── AFTER: drop the exit fund, add capital to keep fund (or redeploy)
    after_holdings: List[Dict[str, Any]] = []
    exit_dropped = False
    for h in holdings:
        h_tokens = _name_tokens(h.get("name") or "")
        # Drop only the first match — duplicate scheme names will dupe-match otherwise
        if not exit_dropped and exit_tokens and h_tokens and len(exit_tokens & h_tokens) >= max(2, len(exit_tokens) // 2):
            exit_dropped = True
            continue
        after_holdings.append(dict(h))

    if redeploy and redeploy.get("allocations"):
        # Spread freed capital across redeploy allocations as synthetic holdings
        for a in redeploy["allocations"]:
            after_holdings.append({
                "asset_type": "mutual_fund" if a["bucket"] != "gold" else "gold",
                "name": (a.get("instruments") or [a["label"]])[0],
                "sector": a["label"],
                "quantity": 1,
                "current_price": float(a.get("rs", 0)),
                "buy_price": float(a.get("rs", 0)),  # synthetic — no embedded gain
            })
    else:
        # No redeploy — add freed capital (post-tax) into keep fund's price field
        if capital > 0:
            for h in after_holdings:
                h_tokens = _name_tokens(h.get("name") or "")
                if keep_tokens and h_tokens and len(keep_tokens & h_tokens) >= max(2, len(keep_tokens) // 2):
                    qty = float(h.get("quantity") or 1)
                    new_total = _holding_value(h) + (capital - tax)
                    h["current_price"] = new_total / qty
                    break

    after = _portfolio_snapshot(after_holdings, "After")

    wealth_delta = after["projected_10y_value_rs"] - before["projected_10y_value_rs"]

    return {
        "insight_id": insight.get("insight_id", ""),
        "before": before,
        "after": after,
        "delta": {
            "mf_count": after["mf_count"] - before["mf_count"],
            "expense_ratio_pct": round(after["weighted_expense_ratio_pct"] - before["weighted_expense_ratio_pct"], 2),
            "cagr_pct": round(after["blended_cagr_pct"] - before["blended_cagr_pct"], 2),
            "projected_10y_wealth_gain_rs": round(wealth_delta, 2),
        },
        "tax_impact_rs": round(tax, 2),
        "capital_released_rs": round(capital, 2),
        "annual_fee_savings_rs": round(float(plan.get("annual_fee_savings_rs") or 0), 2),
        "assumptions": {
            "projection_years": PROJECTION_YEARS,
            "bucket_cagrs_pct": {k: round(v * 100, 1) for k, v in BUCKET_CAGR.items()},
            "note": "Mid-cycle CAGRs net of weighted expense ratio. Wealth delta cancels common assumption errors.",
        },
    }
