"""What goes into the risk gate and what comes out of it.

A RiskRequest describes one position-creating write before it happens. The model is deliberately permissive: a
missing or malformed value is not a validation error raised at the caller, it is a reason the gate BLOCKS with a
specific code, recorded like every other decision. So the fields are loosely typed and the gate does the checking.

    correlation_id   the request's X-Correlation-ID (services/risk_gate/wiring.correlation_id)
    user_id          whose book the position lands in (the client, when an advisor acts for one)
    actor_id         who is acting (the signed-in person)
    mode             one of services/execution_modes.MODES
    path             which write this is (PATHS)
    action           "open" a new position or "add" to one (a journal entry fill)
    instrument       "cash" (one share position) or "structure" (futures / options legs)
    symbol           the share for cash, the underlying for a structure
    legs             structure legs as the desk stores them: {kind future|option|cash, side buy|sell, lots, lot_size,
                     entry_price, expiry "YYYY-MM-DD", strike, option_type call|put}
    quantity         shares, for cash (optional: a journal entry is a capital plan with no quantity yet)
    capital_at_risk_rs  required for cash; for a structure the gate works out the maximum loss at expiry from the legs
                     and uses the larger of the two when a caller also sends one
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

PATHS = ("desk_paper_trade", "journal_create", "journal_fill", "ai_trader_signal", "ai_trader_confirm")
ACTIONS = ("open", "add")
INSTRUMENTS = ("cash", "structure")


class RiskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correlation_id: str
    user_id: str
    actor_id: str
    mode: str
    path: str
    action: str
    instrument: str
    symbol: Optional[str] = None
    legs: List[Dict[str, Any]] = Field(default_factory=list)
    quantity: Optional[float] = None
    capital_at_risk_rs: Optional[float] = None


class Reason(BaseModel):
    code: str
    message: str
    check: str


class Check(BaseModel):
    check: str
    status: Literal["pass", "fail", "skipped"]
    detail: Optional[str] = None


class RiskDecision(BaseModel):
    decision_id: str
    outcome: Literal["allow", "block"]
    reasons: List[Reason]
    checks: List[Check]
    policy_version: str
    inputs_hash: str
    at: str
    correlation_id: str


def inputs_hash(req: RiskRequest) -> str:
    """SHA-256 over every input except the correlation id: the same request judged twice hashes the same, and any
    changed input hashes differently, so a stored decision can be matched to exactly what it judged."""
    core = req.model_dump(exclude={"correlation_id"})
    return hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
