"""The shared F&O pre-trade risk gate (gate.py), its request/decision contract (contract.py), the policy it enforces
(policy.py), the exchange reference it checks legs against (reference.py) and the route-side helpers (wiring.py).
Routes call these through this package, e.g. `risk_gate.enabled_for(db, user)` and `risk_gate.enforce(db, req)`."""
from .contract import RiskDecision, RiskRequest
from .gate import DecisionUnrecorded, check, usage
from .policy import POLICY_VERSION
from .wiring import (FLAG, blocked_detail, cash_request, correlation_id, enabled_for, enforce, stamp,
                     structure_request)

__all__ = ["RiskDecision", "RiskRequest", "DecisionUnrecorded", "check", "usage", "POLICY_VERSION", "FLAG",
           "blocked_detail", "cash_request", "correlation_id", "enabled_for", "enforce", "stamp", "structure_request"]
