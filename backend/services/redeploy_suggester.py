"""Redeployment suggester — Phase C of the optimisation engine.

Given freed capital from a Keep/Exit decision and the user's current
allocation, returns a list of asset-class buckets where the capital
should be redeployed.

# Logic

1. Compute current allocation by asset class:
     equity, debt, gold, international, others
2. Compare against a baseline-diversified portfolio (currently a fixed
   moderate-risk template — Phase D wires it to the user's goals/risk
   profile).
3. For each under-allocated bucket, suggest ₹ to add proportional to
   the gap.
4. Hard cap each suggestion at the freed capital.

# Baseline allocation (moderate risk)

  equity: 55%, debt: 20%, gold: 10%, international: 10%, other: 5%

When all buckets are at or above baseline (rare), we return an empty
plan with a "no redeployment needed" note.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Bucket detection by asset_type + name heuristic
BUCKET_KEYS = ("equity", "debt", "gold", "international", "other")

BASELINE_PCT = {
    "equity":        0.55,
    "debt":          0.20,
    "gold":          0.10,
    "international": 0.10,
    "other":         0.05,
}

BUCKET_PITCH = {
    "debt":          "Stability anchor — Short-Duration Debt or Liquid funds",
    "gold":          "Inflation hedge — Gold ETF or Sovereign Gold Bond",
    "international": "Geographic diversification — US Equity or Global ETF",
    "equity":        "Domestic growth — Index or Mid-Cap fund",
    "other":         "Alternative — REIT / InvIT for yield",
}

BUCKET_INSTRUMENTS = {
    "debt":          ["HDFC Short Term Debt Fund - Direct Growth", "ICICI Pru Liquid Direct Growth"],
    "gold":          ["Nippon India Gold ETF", "SBI Gold ETF", "Sovereign Gold Bond"],
    "international": ["Motilal Oswal Nasdaq 100 ETF", "ICICI Pru US Bluechip Equity Direct"],
    "equity":        ["UTI Nifty 50 Index Fund - Direct Growth", "Parag Parikh Flexi Cap Direct"],
    "other":         ["Mindspace Business Parks REIT"],
}


def _classify_bucket(holding: Dict[str, Any]) -> str:
    """Map a holding into one of the BUCKET_KEYS."""
    at = (holding.get("asset_type") or "").lower()
    name = (holding.get("name") or "").lower()
    sector = (holding.get("sector") or "").lower()

    if at in ("gold",) or "gold" in name or "gold" in sector or "sgb" in name:
        return "gold"
    if at in ("bond", "debt") or "debt" in name or "liquid" in name or "money market" in name:
        return "debt"
    if "international" in name or "us " in name or "nasdaq" in name or "global" in name or "world" in name:
        return "international"
    if at in ("equity", "mutual_fund", "etf"):
        return "equity"
    return "other"


def current_allocation(holdings: List[Dict[str, Any]]) -> Dict[str, float]:
    """₹-share of each bucket in the portfolio."""
    totals: Dict[str, float] = {k: 0.0 for k in BUCKET_KEYS}
    grand = 0.0
    for h in holdings:
        val = float(h.get("quantity") or 0) * float(h.get("current_price") or 0)
        if val <= 0:
            continue
        totals[_classify_bucket(h)] += val
        grand += val
    if grand <= 0:
        return totals
    return {k: v / grand for k, v in totals.items()}


def suggest_redeployment(
    capital_rs: float,
    holdings: List[Dict[str, Any]],
    baseline: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Suggest where to redeploy `capital_rs` to close allocation gaps.

    Returns dict with:
      - allocations: [{bucket, pct, rs, instruments, pitch}]
      - current_pct, target_pct (the baseline used)
      - rationale: list of strings
    """
    if capital_rs <= 0:
        return {"allocations": [], "rationale": ["No capital to redeploy."]}

    base = baseline or BASELINE_PCT
    cur = current_allocation(holdings)
    # Subtract the freed capital from the equity bucket (we assume the
    # exit fund came from there) so the user's "current_pct" reflects
    # the post-exit world, not the current world.
    grand_pre_exit = sum(
        (h.get("quantity") or 0) * (h.get("current_price") or 0) for h in holdings
    ) or 1.0
    grand_post_exit = max(1.0, grand_pre_exit - capital_rs)
    # Reweight: keep totals, but subtract the freed cash from equity
    cur_rs = {k: v * grand_pre_exit for k, v in cur.items()}
    cur_rs["equity"] = max(0.0, cur_rs["equity"] - capital_rs)
    cur_post = {k: cur_rs[k] / grand_post_exit for k in cur_rs}

    # Compute gaps (target - current_post) for each bucket — only keep positive gaps
    gaps: List[tuple] = []
    for k in BUCKET_KEYS:
        gap = base.get(k, 0.0) - cur_post.get(k, 0.0)
        if gap > 0.005:  # >0.5% under-allocated
            gaps.append((k, gap))

    if not gaps:
        return {
            "allocations": [],
            "current_pct": {k: round(v * 100, 1) for k, v in cur_post.items()},
            "target_pct": {k: round(v * 100, 1) for k, v in base.items()},
            "rationale": ["Already diversified across target asset classes — keep the freed capital in your existing best fund."],
        }

    # Allocate proportional to gap, capped at capital_rs
    total_gap = sum(g for _, g in gaps)
    allocations: List[Dict[str, Any]] = []
    for bucket, gap in gaps:
        pct_of_capital = gap / total_gap
        amount = capital_rs * pct_of_capital
        allocations.append({
            "bucket": bucket,
            "label": bucket.replace("_", " ").title(),
            "pct": round(pct_of_capital * 100, 1),
            "rs": round(amount, 2),
            "instruments": BUCKET_INSTRUMENTS.get(bucket, []),
            "pitch": BUCKET_PITCH.get(bucket, "Diversification"),
        })

    rationale = [
        f"Freed capital: ₹{capital_rs:,.0f}.",
        f"Closing gaps in {', '.join(a['label'] for a in allocations)} per moderate-risk baseline.",
    ]

    return {
        "allocations": allocations,
        "current_pct": {k: round(v * 100, 1) for k, v in cur_post.items()},
        "target_pct": {k: round(v * 100, 1) for k, v in base.items()},
        "capital_rs": capital_rs,
        "rationale": rationale,
    }
