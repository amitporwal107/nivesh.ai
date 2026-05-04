"""Decision-Engine Action Generator — Step 5 of the architecture.

Given a `DeviationResult` and a sector/category cap analysis, emits
concrete SELL/BUY/TRIM actions in the same shape `action_plan_manager`
already persists. Two rule families:

  • Rule 6 — Asset-class drift (equity/debt/gold over- or under-weight
    vs target by more than the hard threshold).
  • Rule 7 — Sector cap (any sector >30% of equity exposure).
  • Rule 8 — Market-cap cap (any fund-category bucket >40% of MF AUM,
    e.g. small-cap heavy).

Rule 6 actions:
  • OVERWEIGHT bucket → TRIM the largest holdings in that bucket
    (₹ amount = (current_pct - target_pct) × portfolio_value).
  • UNDERWEIGHT bucket → ADD a placeholder fund in that bucket.

Each emitted action has the same field set as the action_plan_manager
rules (type, asset_name, amount, reason_codes, reason_text) so it
slots cleanly into the existing plan-board UI.

This module is INTENTIONALLY decoupled from action_plan_manager.py —
that file is large and rules 2 / 4 / 5 there are already battle-tested.
The new rules live here so they can be invoked / tested independently
and surfaced via the chat RAG without touching the dashboard plan flow.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Caps tuned against the architecture doc. Tweakable later via
# rules_config.system_config if business wants UI control.
_SECTOR_CAP_PCT = 30.0       # any sector >30% of equity → trim
_CATEGORY_CAP_PCT = 40.0     # any fund-category >40% of MF AUM → trim
_MIN_ACTION_RS = 5_000       # don't emit micro-actions below ₹5k
_MAX_TRIMS_PER_BUCKET = 2    # at most N trim suggestions per asset bucket
                             # (otherwise 5 SGBs in gold burn the action cap)


@dataclass
class ProposedAction:
    type: str                       # "TRIM" | "EXIT" | "ADD"
    asset_name: str                 # holding/fund name (or generic for ADDs)
    amount_rs: float                # ₹ amount to move
    reason_codes: List[str] = field(default_factory=list)
    reason_text: str = ""
    bucket: Optional[str] = None    # "equity" | "debt" | "gold" | sector | category
    rule: Optional[str] = None      # "Rule 6" | "Rule 7" | "Rule 8"
    priority: str = "medium"        # "high" | "medium" | "low" — set by rule
    score: float = 5.0              # for cap-tiebreak vs legacy actions

    def to_dict(self) -> Dict[str, Any]:
        # Drop-in compatible with both:
        #   • orchestrator's plan formatter (reads `action_type`)
        #   • action_plan_manager's pipeline (reads `type`, `priority`,
        #     `status`, `action_id`, `amount`, optionally `score`).
        # Emitting all fields lets the same dict survive both consumers.
        from uuid import uuid4
        return {
            "action_id": f"act_{uuid4().hex[:12]}",
            "type": self.type,
            "action_type": self.type,
            "asset_name": self.asset_name,
            "amount": round(self.amount_rs, 0),
            "amount_rs": round(self.amount_rs, 0),
            "reason_codes": self.reason_codes,
            "reason_text": self.reason_text,
            "priority": self.priority,
            "status": "PENDING",
            "score": self.score,
            "tax_impact": None,     # drift moves don't have computed tax
            "bucket": self.bucket,
            "rule": self.rule,
            "source": "decision_engine",  # marker for telemetry
        }


# ── Rule 6: asset-class drift → TRIM / ADD ─────────────────────────────
async def _rule6_asset_class_drift(user_id: str) -> List[ProposedAction]:
    from services.deviation_engine import compute_deviation, _bucket_for_holding
    from deps import db

    dev = await compute_deviation(user_id)
    if not dev.rows:
        return []
    total_value = float(dev.extras.get("total_value_rs") or 0)
    if total_value <= 0:
        return []

    holdings = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(500)
    # Pre-compute current value + bucket per holding so we can pick
    # what to trim from overweight buckets.
    enriched: List[Dict[str, Any]] = []
    for h in holdings:
        qty = float(h.get("quantity") or 0)
        cp = float(h.get("current_price") or 0)
        v = qty * cp
        if v <= 0:
            continue
        enriched.append({
            "name": h.get("name") or "Unknown",
            "type": (h.get("asset_type") or "").lower(),
            "value": v,
            "bucket": _bucket_for_holding(h),
        })

    actions: List[ProposedAction] = []
    for row in dev.rows:
        if row.trigger != "hard":
            continue
        bucket = row.asset.lower()
        delta_rs = abs(row.deviation_pp) / 100.0 * total_value
        if delta_rs < _MIN_ACTION_RS:
            continue

        # Severity-driven priority + score: a 17pp-off bucket is more
        # urgent than a barely-over-10pp one and should outrank legacy
        # advisory actions in the cap sort.
        severity = abs(row.deviation_pp)
        if severity >= 15:
            prio, score = "high", 8.5
        elif severity >= 10:
            prio, score = "medium", 6.5
        else:
            prio, score = "low", 4.5

        if row.direction == "overweight":
            in_bucket = sorted(
                [h for h in enriched if h["bucket"] == bucket],
                key=lambda x: x["value"], reverse=True,
            )
            # Cap to top-N largest so we don't emit 5 SGB rows when one
            # "trim gold" idea is enough. Larger holdings absorb most of
            # the cut anyway.
            in_bucket = in_bucket[:_MAX_TRIMS_PER_BUCKET]
            remaining = delta_rs
            n = len(in_bucket)
            for h in in_bucket:
                if remaining <= _MIN_ACTION_RS:
                    break
                # Distribute the cut across the top-N holdings —
                # ~delta/n each, capped at 50% of the holding's value.
                fair_share = remaining / max(1, n)
                cut = min(h["value"] * 0.5, fair_share, remaining)
                if cut < _MIN_ACTION_RS:
                    continue
                actions.append(ProposedAction(
                    type="TRIM",
                    asset_name=h["name"],
                    amount_rs=cut,
                    reason_codes=["ASSET_CLASS_DRIFT", f"{bucket.upper()}_OVERWEIGHT"],
                    reason_text=(
                        f"{bucket.title()} is {row.deviation_pp:+.1f}pp above target "
                        f"({row.current_pct:.0f}% vs {row.target_pct:.0f}%); trim to free ₹{cut:,.0f}."
                    ),
                    bucket=bucket,
                    rule="Rule 6",
                    priority=prio,
                    score=score,
                ))
                remaining -= cut
                n -= 1
        elif row.direction == "underweight":
            placeholder = {
                "equity": "Diversified large/flexi-cap fund",
                "debt": "Investment-grade corporate bond fund",
                "gold": "Sovereign Gold Bond / Gold ETF",
            }.get(bucket, f"{bucket} allocation top-up")
            actions.append(ProposedAction(
                type="ADD",
                asset_name=placeholder,
                amount_rs=delta_rs,
                reason_codes=["ASSET_CLASS_DRIFT", f"{bucket.upper()}_UNDERWEIGHT"],
                reason_text=(
                    f"{bucket.title()} is {row.deviation_pp:+.1f}pp below target "
                    f"({row.current_pct:.0f}% vs {row.target_pct:.0f}%); top up by ₹{delta_rs:,.0f}."
                ),
                bucket=bucket,
                rule="Rule 6",
                priority=prio,
                score=score,
            ))
    return actions


# ── Rule 7: sector cap (>30% of equity exposure) ───────────────────────
async def _rule7_sector_cap(user_id: str) -> List[ProposedAction]:
    try:
        from services import portfolio_intelligence as _pi
        m = await _pi.compute_portfolio_intelligence(user_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("rule7 sector data unavailable: %s", e)
        return []
    sector_exp = (m or {}).get("sector_exposure") or []
    if not sector_exp:
        return []

    # Total sector AUM (sum of look-through sector ₹) so we can size
    # the trim action proportionally to the over-cap excess.
    total_rs = sum(float(s.get("rs") or 0) for s in sector_exp)
    if total_rs <= 0:
        return []

    actions: List[ProposedAction] = []
    for s in sector_exp:
        pct = float(s.get("pct") or 0)
        if pct <= _SECTOR_CAP_PCT:
            continue
        excess_pp = pct - _SECTOR_CAP_PCT
        excess_rs = excess_pp / 100.0 * total_rs
        if excess_rs < _MIN_ACTION_RS:
            continue
        prio = "high" if excess_pp >= 5 else "medium"
        actions.append(ProposedAction(
            type="TRIM",
            asset_name=f"Funds with high {s.get('sector')} exposure",
            amount_rs=excess_rs,
            reason_codes=["SECTOR_CAP_BREACH", f"SECTOR_{(s.get('sector') or '').upper()}"],
            reason_text=(
                f"{s.get('sector')} exposure is {pct:.1f}% (cap {_SECTOR_CAP_PCT:.0f}%); "
                f"trim ₹{excess_rs:,.0f} to bring it under the cap."
            ),
            bucket=s.get("sector"),
            rule="Rule 7",
            priority=prio,
            score=7.0 if prio == "high" else 5.5,
        ))
    return actions


# ── Rule 8: market-cap / category concentration (>40% in one bucket) ───
async def _rule8_category_cap(user_id: str) -> List[ProposedAction]:
    from deps import db
    holdings = await db.holdings.find(
        {"user_id": user_id}, {"_id": 0, "name": 1, "asset_type": 1,
                                "quantity": 1, "current_price": 1, "sector": 1},
    ).to_list(500)
    if not holdings:
        return []
    by_cat: Dict[str, float] = {}
    grand = 0.0
    for h in holdings:
        if (h.get("asset_type") or "").lower() not in ("mutual_fund", "mf", "etf"):
            continue
        v = float(h.get("quantity") or 0) * float(h.get("current_price") or 0)
        if v <= 0:
            continue
        cat = (h.get("sector") or "Uncategorised").strip()
        by_cat[cat] = by_cat.get(cat, 0.0) + v
        grand += v
    if grand <= 0:
        return []
    actions: List[ProposedAction] = []
    for cat, val in by_cat.items():
        pct = val / grand * 100
        if pct <= _CATEGORY_CAP_PCT:
            continue
        excess_pp = pct - _CATEGORY_CAP_PCT
        excess_rs = excess_pp / 100.0 * grand
        if excess_rs < _MIN_ACTION_RS:
            continue
        prio = "medium" if excess_pp >= 10 else "low"
        actions.append(ProposedAction(
            type="TRIM",
            asset_name=f"{cat} category funds (consolidate)",
            amount_rs=excess_rs,
            reason_codes=["CATEGORY_CAP_BREACH", f"CATEGORY_{cat.upper()}"],
            reason_text=(
                f"{cat} is {pct:.1f}% of MF AUM (cap {_CATEGORY_CAP_PCT:.0f}%); "
                f"trim ₹{excess_rs:,.0f} or rotate into under-allocated categories."
            ),
            bucket=cat,
            rule="Rule 8",
            priority=prio,
            score=5.5 if prio == "medium" else 4.0,
        ))
    return actions


# ── Public API: full sweep ─────────────────────────────────────────────
async def generate_actions(user_id: str) -> List[ProposedAction]:
    """Run all three rules in parallel and return a deduplicated,
    priority-ordered list. Asset-class drift (Rule 6) is the
    foundational rule; sector / category caps refine it."""
    import asyncio
    r6, r7, r8 = await asyncio.gather(
        _rule6_asset_class_drift(user_id),
        _rule7_sector_cap(user_id),
        _rule8_category_cap(user_id),
        return_exceptions=True,
    )
    out: List[ProposedAction] = []
    for batch in (r6, r7, r8):
        if isinstance(batch, list):
            out.extend(batch)
    # Sort: ADDs last, TRIMs first; within each, larger amounts first.
    type_rank = {"EXIT": 0, "TRIM": 1, "ADD": 2}
    out.sort(key=lambda a: (type_rank.get(a.type, 3), -a.amount_rs))
    return out
