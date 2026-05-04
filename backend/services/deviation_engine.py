"""Deviation Engine — Step 4 of the Nivesh Decision Engine.

Compares CURRENT asset-class allocation (from holdings, derived via
the same look-through logic the chat already uses) against the
TARGET allocation (from `target_allocator`). Produces a per-bucket
deviation matrix + a list of trigger flags.

Output drives the "Asset Allocation Reset" rule in the action plan
manager — buckets where |deviation| > threshold need rebalancing.

Cash is computed but flagged separately: cash isn't tracked as a
holding type yet, so its "current" is derived from a snapshot block
on user_financial_snapshots.current_corpus_rs minus invested. v1
just reports cash deviation as informational, not actionable.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Bucket thresholds. Anything over hard_pp triggers an action; soft_pp
# is "watch" status.
_HARD_PP = 10.0
_SOFT_PP = 5.0


@dataclass
class DeviationRow:
    asset: str
    current_pct: float
    target_pct: float
    deviation_pp: float
    direction: str           # "overweight" | "underweight" | "balanced"
    trigger: str             # "hard" | "soft" | "ok"
    note: Optional[str] = None


@dataclass
class DeviationResult:
    rows: List[DeviationRow]
    target_confidence: float
    risk_category: str
    needs_rebalance: bool
    summary: str
    extras: Dict[str, Any] = field(default_factory=dict)


_TYPE_TO_BUCKET = {
    # raw asset_type from holdings → target-allocator bucket
    "equity": "equity",
    "mutual_fund": "equity",   # default; overridden below for debt MFs
    "mf": "equity",
    "etf": "equity",
    "gold": "gold",
    "debt": "debt",
    "bond": "debt",
}


def _bucket_for_holding(h: Dict[str, Any]) -> str:
    """Map a holding doc to one of {equity, debt, gold, cash}.

    MFs and ETFs default to equity, but debt-flavoured names route to
    debt — best-effort substring match because we don't always have a
    SEBI category tag on the holdings doc."""
    at = (h.get("asset_type") or "").lower()
    base = _TYPE_TO_BUCKET.get(at, "equity")
    if at in ("mutual_fund", "mf", "etf"):
        n = (h.get("name") or "").lower()
        debt_markers = (
            "liquid", "debt", "bond", "gilt", "corporate",
            "short term", "ultra short", "money market", "low duration",
            "savings", "overnight",
        )
        if any(m in n for m in debt_markers):
            return "debt"
    return base


async def compute_deviation(user_id: str) -> DeviationResult:
    """Top-level entry. Pulls target + current allocation, builds the
    deviation matrix, marks hard/soft triggers."""
    from services.target_allocator import compute_target_allocation
    from deps import db

    target = await compute_target_allocation(user_id)

    # Current allocation — value-weighted bucket over all holdings.
    holdings = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(500)
    if not holdings:
        return DeviationResult(
            rows=[], target_confidence=target.confidence_score,
            risk_category=target.risk_category, needs_rebalance=False,
            summary="no holdings — cannot compute deviation",
            extras={"target": target.allocation},
        )

    bucket_value: Dict[str, float] = {"equity": 0.0, "debt": 0.0, "gold": 0.0, "cash": 0.0}
    grand = 0.0
    for h in holdings:
        qty = float(h.get("quantity") or 0)
        cp = float(h.get("current_price") or 0)
        v = qty * cp
        if v <= 0:
            continue
        b = _bucket_for_holding(h)
        bucket_value[b] += v
        grand += v
    if grand <= 0:
        return DeviationResult(
            rows=[], target_confidence=target.confidence_score,
            risk_category=target.risk_category, needs_rebalance=False,
            summary="portfolio value is zero",
            extras={"target": target.allocation},
        )

    current = {k: round(v / grand * 100, 2) for k, v in bucket_value.items()}

    rows: List[DeviationRow] = []
    needs_rebalance = False
    for asset in ("equity", "debt", "gold", "cash"):
        cur = float(current.get(asset, 0))
        tgt = float(target.allocation.get(asset, 0))
        dev = round(cur - tgt, 2)
        absdev = abs(dev)

        if absdev <= _SOFT_PP:
            trigger = "ok"
        elif absdev <= _HARD_PP:
            trigger = "soft"
        else:
            trigger = "hard"

        if dev > _SOFT_PP:
            direction = "overweight"
        elif dev < -_SOFT_PP:
            direction = "underweight"
        else:
            direction = "balanced"

        # Cash caveat — current is always 0 because cash isn't tracked.
        note = None
        if asset == "cash" and cur == 0 and tgt > 0:
            note = "cash isn't tracked as a holding type — current=0 is a known gap"
            trigger = "ok"  # don't trigger an action on cash for v1
            direction = "untracked"

        if trigger == "hard":
            needs_rebalance = True

        rows.append(DeviationRow(
            asset=asset, current_pct=cur, target_pct=tgt,
            deviation_pp=dev, direction=direction, trigger=trigger, note=note,
        ))

    most_off = max(rows, key=lambda r: abs(r.deviation_pp)) if rows else None
    summary_bits = [f"target conf {target.confidence_score:.0f}/100"]
    if most_off and most_off.trigger != "ok":
        summary_bits.append(
            f"{most_off.asset} {most_off.direction} {most_off.deviation_pp:+.1f}pp"
        )
    summary = " · ".join(summary_bits)

    return DeviationResult(
        rows=rows,
        target_confidence=target.confidence_score,
        risk_category=target.risk_category,
        needs_rebalance=needs_rebalance,
        summary=summary,
        extras={
            "target": target.allocation,
            "current": current,
            "total_value_rs": round(grand, 0),
            "target_breakdown": target.breakdown,
            "thresholds_pp": {"soft": _SOFT_PP, "hard": _HARD_PP},
        },
    )
