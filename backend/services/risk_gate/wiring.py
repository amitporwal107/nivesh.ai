"""The route side of the risk gate: is it on for this user, the correlation id, building a request, and turning a
decision into the HTTP answer.

The gate is rolled out behind the KNOWN_FEATURES flag `fno_risk_gate` (off by default). It is judged on the signed-in
person, the same rule as feature_gate.require_feature: an advisor acting for a client is gated by the advisor's
flag. If the persisted flags cannot be re-read, this worker's copy decides (the feature_gate.fresh_user_feature_map
rule): the flag is a rollout switch, not a control, and with it off the route still runs the fail-closed kill-switch
check it always ran (risk_controls.assert_allowed).
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Request

import feature_flags as ff
import feature_gate
from services import risk_controls as rc

from . import gate
from .contract import RiskDecision, RiskRequest

logger = logging.getLogger(__name__)

FLAG = "fno_risk_gate"
_CORRELATION = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


async def enabled_for(db, user: Dict[str, Any]) -> bool:
    try:
        await feature_gate.refresh_if_stale(db)
    except Exception as e:  # noqa: BLE001 — keep this worker's copy; the kill switch stays fail-closed either way
        logger.warning("risk_gate: feature flags not refreshed (%s); using this worker's copy", type(e).__name__)
    email = user.get("email")
    owner = user.get("_session_user_id")
    if owner and owner != user.get("user_id"):
        try:
            doc = await db.users.find_one({"user_id": owner}, {"_id": 0, "email": 1})
        except Exception as e:  # noqa: BLE001 — no email: an allowlist cannot match; "everyone" still applies
            logger.warning("risk_gate: session owner unreadable for the %s flag (%s)", FLAG, type(e).__name__)
            doc = None
        email = (doc or {}).get("email")
    return ff.is_enabled(FLAG, email)


def correlation_id(request: Request) -> str:
    """The request's X-Correlation-ID (core/correlation.py), or a fresh one when there is none or it is not a plain
    token (it is stored on decisions and trades, so an arbitrary header value is not)."""
    cid = getattr(getattr(request, "state", None), "correlation_id", None)
    return cid if isinstance(cid, str) and _CORRELATION.match(cid) else uuid.uuid4().hex


def cash_request(user: Dict[str, Any], cid: str, *, path: str, mode: str, action: str, symbol: Any,
                 quantity: Optional[float], capital_at_risk_rs: Optional[float]) -> RiskRequest:
    return RiskRequest(correlation_id=cid, user_id=str(user.get("user_id") or ""), actor_id=rc.session_actor(user),
                       mode=mode, path=path, action=action, instrument="cash", symbol=symbol, quantity=quantity,
                       capital_at_risk_rs=capital_at_risk_rs)


def structure_request(user: Dict[str, Any], cid: str, *, path: str, mode: str, action: str, underlying: Any,
                      legs: List[Dict[str, Any]]) -> RiskRequest:
    return RiskRequest(correlation_id=cid, user_id=str(user.get("user_id") or ""), actor_id=rc.session_actor(user),
                       mode=mode, path=path, action=action, instrument="structure", symbol=underlying,
                       legs=[dict(leg) for leg in legs])


def blocked_detail(decision: RiskDecision) -> Dict[str, Any]:
    return {"code": "risk_blocked", "reasons": [r.model_dump() for r in decision.reasons],
            "decision_id": decision.decision_id, "correlation_id": decision.correlation_id}


async def enforce(db, req: RiskRequest) -> RiskDecision:
    """The decision when it allows; otherwise 409 risk_blocked, or 503 risk_decision_unrecorded when the decision
    could not be written. Either way the caller writes nothing."""
    try:
        decision = await gate.check(db, req)
    except gate.DecisionUnrecorded:
        raise HTTPException(status_code=503, detail={
            "code": "risk_decision_unrecorded", "correlation_id": req.correlation_id,
            "message": "The risk decision could not be recorded, so nothing was written. Try again."})
    if decision.outcome == "block":
        raise HTTPException(status_code=409, detail=blocked_detail(decision))
    return decision


def stamp(doc: Dict[str, Any], decision: RiskDecision) -> Dict[str, Any]:
    """Put the decision's ids on the document about to be written."""
    doc["correlation_id"] = decision.correlation_id
    doc["risk_decision_id"] = decision.decision_id
    return doc
