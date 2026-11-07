"""Whether a user's NEW paper entries are blocked right now (WF §19.3, PRD §18 rules 12–14).

Read from two places and the stricter answer wins:
  1. services/risk_controls — the kill switch and the trading halt. Unreadable counts as BLOCKED (risk_controls' own
     rule: an unreadable kill switch must never read as off).
  2. slice B's `services.spt.risk.kill_switch_state(db, user_id=...)`, when that module and function exist. It is where
     the account-level states (daily-loss block, drawdown halt, the WF §19.3 kill-switch states) live. Its answer blocks
     when any of `entries_blocked`, `blocking`, `kill_switch`, `halted` is true or `state` is TRIGGERED / RESTRICTED /
     RESET_PENDING. When it raises, entries are blocked (fail closed) and the error is logged.

What a block does (monitor.py, orders.py): pending ENTRY orders are cancelled and their reservations released, a new
ENTRY order is REJECTED, no ENTRY fill happens. Exits and risk-reducing modifications are NOT blocked: blocking new risk
and unwinding existing risk are different decisions.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from services import risk_controls as rc

logger = logging.getLogger(__name__)

B_BLOCKING_STATES = ("TRIGGERED", "RESTRICTED", "RESET_PENDING")


def _b_reader():
    try:
        from services.spt import risk as spt_risk          # slice B; absent until it is merged
    except ImportError:
        return None
    return getattr(spt_risk, "kill_switch_state", None)


async def entry_block(db, user_id: str) -> Optional[Dict[str, Any]]:
    """None when new entries are allowed; else {code, reason, source}."""
    try:
        state = await rc.read(db, user_id)
    except Exception as e:  # noqa: BLE001 — fail closed
        logger.warning("spt paper: risk controls unreadable for a user (%s); entries blocked", type(e).__name__)
        return {"code": "controls_unreadable", "reason": "the kill switch could not be read", "source": "risk_controls"}
    if state.get("kill_switch"):
        return {"code": "kill_switch_on", "reason": state.get("reason"), "source": "risk_controls"}
    if state.get("halted"):
        return {"code": "trading_halted", "reason": state.get("reason"), "source": "risk_controls"}
    reader = _b_reader()
    if reader is None:
        return None
    try:
        b = await reader(db, user_id=user_id) or {}
    except Exception as e:  # noqa: BLE001 — fail closed: B's account state is unknown
        logger.warning("spt paper: account risk state unreadable (%s); entries blocked", type(e).__name__)
        return {"code": "account_state_unreadable", "reason": type(e).__name__, "source": "spt_risk"}
    if not isinstance(b, dict):
        return {"code": "account_state_unreadable", "reason": "unexpected answer", "source": "spt_risk"}
    if any(bool(b.get(k)) for k in ("entries_blocked", "blocking", "kill_switch", "halted")) \
            or str(b.get("state") or "").upper() in B_BLOCKING_STATES:
        return {"code": str(b.get("code") or "account_restricted"), "reason": b.get("reason"), "source": "spt_risk"}
    return None
