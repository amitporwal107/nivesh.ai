"""The one evidence record every AI-Trader skill returns (PRD F1; requirement §3 "Shared evidence model")."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

STATUS_OK = "OK"
STATUS_UNAVAILABLE = "UNAVAILABLE"

SKILLS = ("market_intelligence", "technical", "fundamental", "fno", "strategy", "risk", "execution")
IMPACTS = ("supports", "opposes", "neutral", "veto_candidate")
STATUSES = (STATUS_OK, STATUS_UNAVAILABLE)

# Confidence of evidence that no calibration has measured yet. 0.5 says "no information", and `calibrated` is False so
# nothing downstream mistakes it for a measured probability (PRD §4 F6: calibration decides when that changes).
UNCALIBRATED_CONFIDENCE = 0.5


class EvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class Evidence:
    skill: str
    symbol: Optional[str]            # None for market-wide evidence
    as_of: str                       # ISO date the evidence is point-in-time to
    horizon: str                     # e.g. "market", "daily", "weekly", "monthly", "5d"
    observation: str                 # what was measured, in plain words
    interpretation: str              # what it means for a trade decision
    confidence: float                # 0..1
    decision_impact: str             # one of IMPACTS
    status: str = STATUS_OK
    reason_code: Optional[str] = None
    calibrated: bool = False
    contradictions: List[str] = field(default_factory=list)
    conditions: List[str] = field(default_factory=list)   # what would invalidate this view
    sources: List[Dict[str, Any]] = field(default_factory=list)   # [{name, timestamp}]
    data: Dict[str, Any] = field(default_factory=dict)   # raw numbers behind the observation

    def __post_init__(self) -> None:
        if self.skill not in SKILLS:
            raise EvidenceError(f"unknown skill {self.skill!r}")
        if self.decision_impact not in IMPACTS:
            raise EvidenceError(f"unknown decision_impact {self.decision_impact!r}")
        if self.status not in STATUSES:
            raise EvidenceError(f"unknown status {self.status!r}")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            raise EvidenceError("confidence must be a number")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise EvidenceError(f"confidence {self.confidence!r} outside [0, 1]")
        if self.status == STATUS_UNAVAILABLE and not self.reason_code:
            raise EvidenceError("UNAVAILABLE evidence needs a reason_code")
        if self.status == STATUS_OK and self.reason_code:
            raise EvidenceError("OK evidence must not carry a reason_code")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def unavailable(skill: str, symbol: Optional[str], as_of: str, horizon: str, what: str, reason: str,
                sources: Optional[List[Dict[str, Any]]] = None) -> Evidence:
    """Evidence for something that could not be measured. No value, confidence 0, no impact on a decision."""
    return Evidence(
        skill=skill, symbol=symbol, as_of=as_of, horizon=horizon,
        observation=f"{what}: unavailable ({reason})",
        interpretation="Not measured; this view must not be used for or against a trade.",
        confidence=0.0, decision_impact="neutral", status=STATUS_UNAVAILABLE, reason_code=reason,
        sources=sources or [],
    )
