"""Post-snapshot-activation action writers for v4.

Per docs/api-changes.md Decision 6: on snapshot activation, emit plan
actions for tax harvesting (source_domain="tax") and goal shortfalls
(source_domain="goals") so the Plan Board and dashboards have pre-populated
recommendations without the user having to navigate each dashboard first.

Called by: routes/cas_snapshots.py after a snapshot is marked active.
"""
from __future__ import annotations

import logging
from uuid import uuid4

logger = logging.getLogger(__name__)

_LTCG_LIMIT = 125_000.0  # ₹1.25L per Jul-2024 amendment


async def write_tax_actions(db, user_id: str) -> int:
    """Write LTCG tax-harvesting plan actions for qualifying holdings.

    A holding qualifies when unrealised_gain > 0 AND days_held >= 365.
    Idempotent: skips if any TAX_HARVEST action already exists in the active plan.
    Returns count of actions written (0 if skipped or none qualify).
    """
    plan = await db.action_plans.find_one({"user_id": user_id, "status": "active"})
    if not plan:
        return 0

    existing = plan.get("actions", [])
    if any(a.get("reason_codes") and "TAX_HARVEST" in a["reason_codes"] for a in existing):
        return 0  # idempotent — already have tax actions

    # Try primary holdings collection, fall back to portfolio_holdings
    holdings = await db.holdings.find(
        {"user_id": user_id}, {"_id": 0}
    ).to_list(2000)

    if not holdings:
        holdings = await db.portfolio_holdings.find(
            {"user_id": user_id}, {"_id": 0}
        ).to_list(2000)

    qualifying = [
        h for h in holdings
        if (h.get("unrealised_gain") or 0) > 0 and (h.get("days_held") or 0) >= 365
    ]

    if not qualifying:
        return 0

    new_actions = []
    for h in qualifying:
        gain = float(h.get("unrealised_gain", 0))
        tax_saved = max(0.0, min(gain, _LTCG_LIMIT) * 0.10)
        action = {
            "action_id": f"tax_{uuid4().hex[:8]}",
            "type": "HARVEST",
            "verb": "HARVEST",
            "status": "PENDING",
            "priority": 1,
            "priority_label": "Critical",
            "asset_type": h.get("asset_type", "FUND").upper(),
            "asset_name": h.get("fund_name") or h.get("name") or "Unknown",
            "instrument_id": h.get("instrument_id") or h.get("isin"),
            "amount": gain,
            "reason_text": (
                f"LTCG harvestable: \u20b9{gain:.0f} \u2014 within \u20b91.25L FY limit."
            ),
            "reason_codes": ["TAX_HARVEST"],
            "source_domain": "tax",
            "exclusive": False,
            "effort": "LOW",
            "trade_off": "Re-entry at market price within 30 days.",
            "impact": {"label": "Tax saved", "value": f"\u20b9{tax_saved:.0f}"},
            "expected_impact": {
                "tax_saved_inr": round(tax_saved),
                "health_delta": 1,
            },
            "confidence": "HIGH",
            "scores": None,
            "switch_target": None,
        }
        new_actions.append(action)

    if not new_actions:
        return 0

    await db.action_plans.update_one(
        {"user_id": user_id, "status": "active"},
        {"$push": {"actions": {"$each": new_actions}}},
    )
    logger.info("write_tax_actions: wrote %d TAX_HARVEST actions for %s", len(new_actions), user_id)
    return len(new_actions)


async def write_goals_actions(db, user_id: str) -> int:
    """Write RAISE_SIP plan actions for under-funded goals.

    A goal qualifies when funding_pct < 80.
    Idempotent: skips per-goal if a GOAL_AT_RISK action for that goal name already exists.
    Returns count of actions written.
    """
    plan = await db.action_plans.find_one({"user_id": user_id, "status": "active"})
    if not plan:
        return 0

    existing = plan.get("actions", [])
    existing_goal_names = {
        a.get("asset_name")
        for a in existing
        if a.get("reason_codes") and "GOAL_AT_RISK" in a["reason_codes"]
    }

    goals = await db.goals.find({"user_id": user_id}, {"_id": 0}).to_list(100)
    if not goals:
        return 0

    new_actions = []
    for goal in goals:
        funding_pct = float(goal.get("funding_pct") or goal.get("progress_pct") or 0)
        if funding_pct >= 80:
            continue
        goal_name = goal.get("name") or goal.get("goal_name") or "Goal"
        if goal_name in existing_goal_names:
            continue  # idempotent per goal

        priority = 1 if funding_pct < 50 else 2
        priority_label = "Closes the gap" if funding_pct < 50 else "Closes most"

        action = {
            "action_id": f"goal_{uuid4().hex[:8]}",
            "type": "RAISE_SIP",
            "verb": "RAISE_SIP",
            "status": "PENDING",
            "priority": priority,
            "priority_label": priority_label,
            "asset_type": "FUND",
            "asset_name": goal_name,
            "instrument_id": None,
            "amount": 0,
            "reason_text": (
                f"{goal_name} funded at {funding_pct:.0f}% \u2014 raise SIP to close gap."
            ),
            "reason_codes": ["GOAL_AT_RISK"],
            "source_domain": "goals",
            "exclusive": True,  # PRD §7.4 — Goals actions are mutually exclusive
            "effort": "MEDIUM",
            "trade_off": "Higher SIP commitment reduces liquidity.",
            "impact": {
                "label": "Funding",
                "value": f"{funding_pct:.0f}% \u2192 100%",
            },
            "expected_impact": {
                "funding_pp": round(100 - funding_pct, 1),
                "health_delta": 2,
            },
            "confidence": "MEDIUM",
            "scores": None,
            "switch_target": None,
        }
        new_actions.append(action)

    if not new_actions:
        return 0

    await db.action_plans.update_one(
        {"user_id": user_id, "status": "active"},
        {"$push": {"actions": {"$each": new_actions}}},
    )
    logger.info("write_goals_actions: wrote %d GOAL_AT_RISK actions for %s", len(new_actions), user_id)
    return len(new_actions)
