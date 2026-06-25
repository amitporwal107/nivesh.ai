"""Load persona context for a user from MongoDB so it can be passed into CopilotState.

Called by the chat route before invoking the LangGraph copilot graph. Keeps the
DB lookup at the call site (not inside the graph) so the graph stays pure and
checkpointer state stays cheap.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


_DEFAULT_PERSONA = "retail_investor"


async def load_persona_context(db, user_id: str) -> Dict[str, Any]:
    """Return persona / risk_profile / age_band / journey_type for a user.

    Reads from the `user_profiles` MongoDB collection which is the source of
    truth maintained by `services.persona_engine`. Falls back to retail_investor
    when no profile exists so the LangGraph state always has a sensible default.
    """
    ctx: Dict[str, Any] = {
        "persona": _DEFAULT_PERSONA,
        "risk_profile": None,
        "age_band": None,
        "journey_type": None,
    }

    if not user_id:
        return ctx

    try:
        profile = await db.user_profiles.find_one({"user_id": user_id}, {"_id": 0})
    except Exception as exc:  # noqa: BLE001
        logger.warning("persona_loader: profile lookup failed for %s: %s", user_id, exc)
        return ctx

    if not profile:
        return ctx

    persona_block = profile.get("persona") or {}
    if isinstance(persona_block, dict):
        ctx["persona"] = persona_block.get("persona") or _DEFAULT_PERSONA
    elif isinstance(persona_block, str):
        ctx["persona"] = persona_block

    # `user_profiles.risk_profile` is the structured object
    # {category, score, capacity_score, persona, ...} (see services.risk_profile_chat),
    # but CopilotState.risk_profile is a plain band string. Coerce to the category
    # label; tolerate the legacy string shape and anything else → None.
    rp = profile.get("risk_profile") or profile.get("risk_category")
    if isinstance(rp, dict):
        rp = rp.get("category")
    ctx["risk_profile"] = rp if isinstance(rp, str) else None
    ctx["age_band"] = profile.get("age_band")
    ctx["journey_type"] = profile.get("journey_type")

    return ctx


def derive_age_band(age: Optional[int]) -> Optional[str]:
    """Bucket a numeric age into a band string used for prompt framing."""
    if age is None:
        return None
    if age < 30:
        return "20s"
    if age < 40:
        return "30s"
    if age < 50:
        return "40s"
    if age < 60:
        return "50s"
    return "60s+"
