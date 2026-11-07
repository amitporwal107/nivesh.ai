"""Which desk events are support issues, and the fixed message for each. Pure: no network, no database."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

MAX_LEN = 1500
_IST = timezone(timedelta(hours=5, minutes=30))
_FIELD_CAP = 4000
# Only these payload fields reach a message: nothing else (emails, tenant data, raw payloads) is copied.
_SHOWN = ("status", "session_date", "control", "reason", "error", "to")


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


RANK = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}


@dataclass(frozen=True)
class Alert:
    key: str
    severity: Severity
    check: str
    result: str
    since: datetime
    account: str
    simulation: Optional[str]
    detail: str
    next_action: str
    seq: int
    resolves: Optional[str] = None      # key of the alert this one clears


def _key(check: str, account: str, sim: Optional[str], result: str) -> str:
    return f"{check}|{account}|{sim or '-'}|{result}"


def _detail(p: dict) -> str:
    parts = []
    for f in _SHOWN:
        v = p.get(f)
        if v not in (None, ""):
            parts.append(f"{f}: {str(v)[:_FIELD_CAP]}")
    return "; ".join(parts)


def classify(event: dict[str, Any]) -> Optional[Alert]:
    """The alert for a desk event, or None when the event is ordinary traffic (or malformed)."""
    try:
        typ = event["event_type"]
        p = event.get("payload") or {}
        since = event["occurred_at"]
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        account = event.get("account_id") or "desk"
        sim = event.get("simulation_id")
        seq = int(event.get("seq") or 0)
        detail = _detail(p)

        def mk(sev, check, result, next_action, resolves=None):
            return Alert(_key(check, account, sim, result), sev, check, result, since, account, sim, detail,
                         next_action, seq, resolves)

        if typ == "PREMARKET_BLOCKED":
            return mk(Severity.CRITICAL, "premarket", "BLOCKED",
                      "New risk is held back for the session. Check the data feeds, then re-run the pre-market check.")
        if typ == "PREMARKET_READY" and p.get("status") == "DEGRADED":
            return mk(Severity.WARNING, "premarket", "DEGRADED",
                      "The desk continues with the segments still allowed. Check the missing data feed.")
        if typ == "WORKFLOW_FAILED":
            return mk(Severity.CRITICAL, "workflow", "FAILED", "Open the workflow in the desk and read its error.")
        if typ == "MARKET_DATA_STALE":
            return mk(Severity.WARNING, "market_data", "STALE", "No stale data is used. Check the market data feed.")
        if typ == "AGENT_UNHEALTHY":
            return mk(Severity.WARNING, "agent", "UNHEALTHY", "Check the agent's last task in the desk.")
        if typ == "DESK_CONTROL_ACTIVATED":
            c = str(p.get("control") or "control")
            return mk(Severity.CRITICAL, f"desk_control:{c}", "ACTIVE",
                      "A desk control is on. It stays on until someone lifts it in the desk.")
        if typ == "DESK_CONTROL_LIFTED":
            c = str(p.get("control") or "control")
            return mk(Severity.INFO, f"desk_control:{c}", "RESOLVED", "No action needed.",
                      resolves=_key(f"desk_control:{c}", account, sim, "ACTIVE"))
    except Exception:       # a malformed event is not an alert; it must never stop the others
        return None
    return None


def _when(t: datetime) -> str:
    u = t.astimezone(timezone.utc)
    i = t.astimezone(_IST)
    return f"{i:%Y-%m-%d %H:%M} IST / {u:%H:%M} UTC"


def render(a: Alert, *, repeated: int = 0) -> str:
    head = "RESOLVED" if a.resolves else a.severity.value
    scope = f"SIMULATION {a.simulation}" if a.simulation else f"account {a.account}"
    lines = [f"[{head}] {a.check} — {a.result} ({scope})", f"Since: {_when(a.since)}"]
    if a.detail:
        lines.append(f"Detail: {a.detail}")
    if repeated:
        lines.append(f"Repeated {repeated} time{'s' if repeated != 1 else ''} since the last post.")
    lines.append(f"Next action: {a.next_action}")
    text = "\n".join(lines)
    if len(text) > MAX_LEN:
        text = text[:MAX_LEN - len(" [truncated]")] + " [truncated]"
    return text
