"""The F&O risk policy the gate enforces.

THESE ARE CONSERVATIVE DEFAULTS FOR THE FIRST RELEASE, not limits calibrated to any account, broker margin or
user's risk profile. They exist so every check has a number to enforce. Changing one is a policy change: bump
POLICY_VERSION so a stored decision can be read against the limits it was judged by.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Tuple

from services.strategy_limits import MAX_STRATEGY_LEGS

POLICY_VERSION = "fno-risk-v1"
BASIS = "Conservative defaults for the first release; not calibrated to any account, broker margin or risk profile."


@dataclass(frozen=True)
class Limits:
    #: the shared product limit (services/strategy_limits); a stricter policy may lower it, never raise it
    max_legs: int = MAX_STRATEGY_LEGS
    max_lots_per_leg: int = 10
    max_open_structures: int = 10
    #: per trade: the maximum loss at expiry for a structure, the capital deployed for cash
    max_capital_at_risk_rs: float = 200_000.0
    #: blocks naked short calls and puts, futures-only structures and any unhedged futures exposure
    require_defined_risk: bool = True
    #: shadow is not built; live is refused while services/execution_modes.LIVE_EXECUTION_AVAILABLE is False
    allowed_modes: Tuple[str, ...] = ("paper", "assisted")


LIMITS = Limits()


def limits() -> Dict[str, Any]:
    out = asdict(LIMITS)
    out["allowed_modes"] = list(LIMITS.allowed_modes)
    out["basis"] = BASIS
    return out
