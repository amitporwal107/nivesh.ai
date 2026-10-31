"""The live readiness gate of PRD §21: the twelve conditions live F&O orders need, each read from what exists today.

Every condition is `pass` or `fail` with the evidence it was judged on and the backlog item that closes it. In this
build none can pass: there is no order adapter, no certification and no freshness check before a decision, so
`enforceable` is 0. The rows still read live state where it exists (the gate flag, the live feed, the live grant, the
kill switch, the stored decisions), from the same sources as GET /api/risk/status and GET /api/live/status, so the
screen shows the current values rather than fixed text. A read that fails is `fail` with "could not be read": an
unknown is never a pass.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from services import execution_modes as modes
from services import risk_controls as rc

from . import gate, policy

READINESS_VERSION = "live-readiness-v1"
UNREADABLE = "could not be read"


async def _try(read: Callable[[], Awaitable[Any]]) -> tuple:
    try:
        return True, await read()
    except Exception:  # noqa: BLE001 — reported on the row as unreadable, never as a pass
        return False, None


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _row(cid: str, label: str, evidence: str, backlog: str, status: str = "fail") -> Dict[str, Any]:
    return {"id": cid, "label": label, "status": status, "evidence": evidence, "backlog": backlog}


def _feed_text(ok: bool, st: Optional[Dict[str, Any]]) -> str:
    if not ok:
        return f"Live feed status {UNREADABLE}"
    if not st:
        return "The live feed has not reported a status"
    universe = st.get("universe") or {}
    sets = ", ".join(f"{k} {v}" for k, v in sorted(universe.items())) if isinstance(universe, dict) else ""
    return (f"Live feed {st.get('state') or 'state not reported'}, session {st.get('session') or 'not reported'}, "
            f"data at {st.get('data_at') or 'none'}{'; instruments: ' + sets if sets else ''}")


async def live_readiness(db, user_id: str, *, gate_enabled: Callable[[], Awaitable[bool]],
                         feed_status: Callable[[], Awaitable[Optional[Dict[str, Any]]]],
                         now: Optional[datetime] = None) -> Dict[str, Any]:
    gate_ok, gate_on = await _try(gate_enabled)
    feed_ok, feed = await _try(feed_status)
    auth_ok, auth = await _try(lambda: modes.read_live_authorization(db, user_id))
    ctl_ok, ctl = await _try(lambda: rc.read(db, user_id))
    ev_ok, counts = await _try(lambda: _decision_counts(db, user_id))
    live = modes.LIVE_EXECUTION_AVAILABLE

    gate_text = UNREADABLE if not gate_ok else ("on for your account" if gate_on else "off for your account")
    if not auth_ok:
        auth_text = f"live authorization {UNREADABLE}"
    elif (auth or {}).get("granted"):
        auth_text = "an admin has granted you live authorization"
    else:
        auth_text = "no live authorization is granted"
    if not ctl_ok or not isinstance(ctl, dict):
        kill_text = f"Kill switch {UNREADABLE}"
    else:
        kill_text = (f"Kill switch {'ON' if ctl.get('kill_switch') else 'off'}, trading halt "
                     f"{'ON' if ctl.get('halted') else 'off'}")
    if not ev_ok:
        ev_text = f"Your stored decisions {UNREADABLE}"
    else:
        ev_text = (f"{counts['gate']} of your gate decisions are stored with a correlation id; {counts['snapshot']} "
                   f"carry the decision snapshot (the gate's reads) and can be replayed")
    adapter = ("the build reports live execution available, but no certified order adapter exists" if live
               else "live execution is not available in this build; the broker adapters are read-only")

    conditions: List[Dict[str, Any]] = [
        _row("agent_certified", "Agent version certified", "No agent certification service exists", "P3.1"),
        _row("template_certified", "Strategy template certified", "No strategy certification records exist", "P3.1"),
        _row("universe_certified", "Contract in certified universe", "No certified universe scope exists", "P3.1"),
        _row("adapter_certified", "Broker, account and adapter certified", _cap(adapter), "P3.2"),
        _row("risk_policy_matches", "Risk policy matches certification",
             f"The {policy.POLICY_VERSION} gate is {gate_text}; there is no certification to match it against", "P3.1"),
        _row("market_data_fresh", "Market data fresh and complete",
             f"{_feed_text(feed_ok, feed)}. Stock options are not on the feed, and no freshness check runs before a "
             "decision", "P0.1"),
        _row("pricing_margin", "Pricing, payoff, Greeks, margin pass",
             "Payoff and capital at risk are computed; Greeks are end-of-day Black-76; exchange margin needs the "
             "platform's daily Kite login and is not checked before a decision", "P1.1"),
        _row("portfolio_risk", "Portfolio risk checks pass",
             f"The gate caps legs ({policy.LIMITS.max_legs}), lots per leg ({policy.LIMITS.max_lots_per_leg}), open "
             f"structures ({policy.LIMITS.max_open_structures}) and capital at risk per trade "
             f"(Rs {policy.LIMITS.max_capital_at_risk_rs:,.0f}); no portfolio Greeks or stress tests", "P1.2"),
        _row("user_authorization", "User authorisation present",
             f"{_cap(auth_text)}; there is no per-order confirmation flow", "P3.2"),
        _row("oms_reconciliation", "OMS and reconciliation healthy",
             "The OMS state machine and an idempotent paper order store exist; no broker adapter and no "
             "reconciliation", "P3.2"),
        _row("kill_switch", "Kill switch inactive and available",
             f"{kill_text}. It blocks new paper positions; it cannot cancel orders or flatten positions", "P0.4"),
        _row("evidence_persisted", "Evidence persisted",
             f"{ev_text}. No market price snapshot is stored with a decision", "P0.3"),
    ]
    return {
        "conditions": conditions,
        "count": len(conditions),
        "enforceable": sum(1 for c in conditions if c["status"] == "pass"),
        "live_execution_available": live,
        "policy_version": policy.POLICY_VERSION,
        "read_at": (now or datetime.now(timezone.utc)).isoformat(),
        "readiness_version": READINESS_VERSION,
    }


async def _decision_counts(db, user_id: str) -> Dict[str, int]:
    gate_rows = {"user_id": user_id, "source": "risk_gate"}
    return {"gate": await db[rc.DECISIONS].count_documents(gate_rows),
            "snapshot": await db[rc.DECISIONS].count_documents({**gate_rows, "snapshot_version": gate.SNAPSHOT_VERSION})}
