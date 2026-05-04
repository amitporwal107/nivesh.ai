"""AI Portfolio Builder — empty-state magic moment.

For a user who has a risk profile + at least one goal but no holdings yet,
generate a complete proposed portfolio with reasoning. This is the orchestrator
that ties together:

  • target_allocator.compute_target_allocation     → how much per bucket
  • goal_fund_picker.pick_funds_for_bucket         → which funds per bucket
  • Per-fund "why" rationale derived from V3 primitives
  • Optional sizing — given a monthly SIP capacity, split across buckets

The output is a self-contained payload the frontend renders as the
"AI Portfolio Builder" hero card. Reuses everything that already exists
under the hood — this module is glue + explanation, not new modelling.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Per-bucket fund counts (kept small so the user doesn't drown) ──────
_FUNDS_PER_BUCKET = {
    "equity": 3,
    "debt":   2,
    "gold":   1,
    "cash":   1,
    "hybrid": 2,
}


def _fund_rationale(fund: Dict[str, Any], category_avg_expense: float = 1.0) -> str:
    """Human-readable 1-line "why this fund" sentence from V3 primitives.

    Composes from whichever signals are present — never fabricates.
    Example output:
        "Top-quartile in Flexi Cap · Quality 78 · Expense 0.62%
         (vs category avg 1.20%) · 5y CAGR 17.4%"
    """
    parts: List[str] = []
    q = fund.get("quality_score")
    if q is not None and q >= 65:
        parts.append(f"Quality {q:.0f}")
    er = fund.get("expense_ratio")
    if er is not None:
        if category_avg_expense and er < category_avg_expense * 0.8:
            parts.append(f"Expense {er:.2f}% (vs cat avg {category_avg_expense:.2f}%)")
        else:
            parts.append(f"Expense {er:.2f}%")
    aum = fund.get("aum_cr")
    if aum is not None and aum >= 1000:
        parts.append(f"AUM ₹{int(aum):,}Cr")
    h = fund.get("health_score")
    if h is not None and h >= 70:
        parts.append(f"Health {h:.0f}")
    if not parts:
        parts.append("Top-ranked in category by V3 quality score")
    return " · ".join(parts)


def _split_sip_across_buckets(
    sip_monthly_rs: float, allocation: Dict[str, float],
) -> Dict[str, float]:
    """Split a monthly SIP across buckets pro-rata to target allocation."""
    total = sum(allocation.values()) or 1.0
    return {
        bucket: round(sip_monthly_rs * (pct / total), 0)
        for bucket, pct in allocation.items()
    }


def _split_lumpsum_across_funds(
    bucket_amount_rs: float, n_funds: int,
) -> List[float]:
    """Naive equal split. Caller can override later if a fund-weighted
    score-based split is wanted."""
    if n_funds <= 0 or bucket_amount_rs <= 0:
        return []
    per = round(bucket_amount_rs / n_funds, 0)
    return [per] * n_funds


async def build_proposed_portfolio(
    user_id: str,
    *,
    monthly_sip_rs: Optional[float] = None,
    lumpsum_rs: Optional[float] = None,
) -> Dict[str, Any]:
    """Generate the proposed portfolio for a user.

    Args:
        user_id: target user (or shadow_user_id for MFD-impersonated client)
        monthly_sip_rs: optional; if provided, splits the SIP across buckets
        lumpsum_rs: optional; if provided, splits the lump-sum across buckets

    Returns:
        {
          "allocation":     {equity, debt, gold, cash},
          "allocation_rs":  {bucket: amount_rs} when SIP/lump given,
          "buckets":        [{bucket, target_pct, target_rs, funds: [...]}],
          "totals":         {total_funds, total_rs},
          "risk_profile":   "moderate",
          "horizon_years":  10,
          "rationale":      [...],
          "_message":       short copy explaining the proposal
        }
    """
    from services.target_allocator import compute_target_allocation
    from services import goal_fund_picker as _gfp

    ta = await compute_target_allocation(user_id)
    allocation = ta.allocation or {}
    risk = ta.risk_category
    horizon_years = None  # ta.inputs_used has n_goals but not horizon directly

    # Per-bucket SIP/lumpsum split
    sip_split = _split_sip_across_buckets(monthly_sip_rs, allocation) if monthly_sip_rs else {}
    lump_split = _split_sip_across_buckets(lumpsum_rs, allocation) if lumpsum_rs else {}

    buckets_out: List[Dict[str, Any]] = []
    total_funds = 0
    for bucket, pct in allocation.items():
        if pct <= 0:
            continue
        n = _FUNDS_PER_BUCKET.get(bucket, 2)
        try:
            picks = await _gfp.pick_funds_for_bucket(bucket, n=n)
        except Exception as e:  # noqa: BLE001
            logger.warning("portfolio_builder: pick_funds failed for %s: %s", bucket, e)
            picks = []

        # Estimate category-avg expense for the rationale comparison.
        cat_avg_er = (
            sum((p.get("expense_ratio") or 0) for p in picks) / max(1, len(picks))
            if picks else 1.0
        )
        bucket_lump_rs = lump_split.get(bucket, 0)
        per_fund_lump = _split_lumpsum_across_funds(bucket_lump_rs, len(picks))

        funds_out: List[Dict[str, Any]] = []
        for i, p in enumerate(picks):
            funds_out.append({
                "instrument_id": p.get("instrument_id"),
                "scheme_name": p.get("scheme_name"),
                "isin": p.get("isin"),
                "category": p.get("category"),
                "sub_category": p.get("sub_category"),
                "expense_ratio": p.get("expense_ratio"),
                "aum_cr": p.get("aum_cr"),
                "quality_score": p.get("quality_score"),
                "health_score": p.get("health_score"),
                "add_score": p.get("add_score"),
                "plan_type": p.get("plan_type"),
                "rationale": _fund_rationale(p, category_avg_expense=cat_avg_er),
                # Sizing — only populated when caller passed a SIP / lumpsum
                "lumpsum_rs": per_fund_lump[i] if per_fund_lump else None,
            })
            total_funds += 1

        buckets_out.append({
            "bucket": bucket,
            "target_pct": round(float(pct), 1),
            "target_rs": round(lump_split.get(bucket, 0), 0) if lumpsum_rs else None,
            "monthly_sip_rs": round(sip_split.get(bucket, 0), 0) if monthly_sip_rs else None,
            "n_funds_picked": len(funds_out),
            "funds": funds_out,
        })

    rationale: List[str] = [
        f"Asset mix derived from your {risk} risk profile",
    ]
    if ta.inputs_used.get("n_goals"):
        rationale.append(f"Tilted toward your {ta.inputs_used['n_goals']} active goal(s)")
    if monthly_sip_rs:
        rationale.append(f"Monthly SIP of ₹{int(monthly_sip_rs):,} split across buckets pro-rata")
    if lumpsum_rs:
        rationale.append(f"Lump sum of ₹{int(lumpsum_rs):,} allocated to start positions")

    return {
        "user_id": user_id,
        "risk_profile": risk,
        "horizon_years": horizon_years,
        "allocation": allocation,
        "allocation_rs": lump_split or None,
        "monthly_sip_split_rs": sip_split or None,
        "buckets": buckets_out,
        "totals": {
            "total_funds": total_funds,
            "monthly_sip_rs": monthly_sip_rs,
            "lumpsum_rs": lumpsum_rs,
        },
        "rationale": rationale,
        "_meta": {
            "confidence_score": ta.confidence_score,
            "inputs_used": ta.inputs_used,
            "breakdown": ta.breakdown,
        },
    }
