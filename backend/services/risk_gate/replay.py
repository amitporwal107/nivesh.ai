"""Replay and lineage for a recorded risk decision (PRD P0.3, first part). Read only: nothing here writes.

replay(row)          runs gate.decide() again on the snapshot stored with the decision, under the code and policy
                     running now, and compares the outcome, the reason codes and the checks with what was recorded.
                     It also re-hashes the stored request and snapshot, so a row edited after the fact cannot report
                     a match. A row recorded before snapshots existed (or written by the older control stream) is
                     `replayable: false` with the reason, not an error.
lineage(db, row)     the PRD's ten steps from market data to audit record, each `recorded`, `not_recorded`,
                     `not_reached` or `not_applicable`, with what was recorded and the backlog item for what was not.
                     Only what the row or a linked record proves is marked recorded.

What replay proves, stated because the word invites more: the same code and policy, given the same inputs the gate
read, reach the same decision. The inputs are the request plus the gate's own reads (controls, live grant, exchange
lot and expiry reference, open-structure count). There is no market price snapshot yet, so a replay says nothing
about the prices the trade was entered at.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from services import desk_trading as desk
from services import risk_controls as rc
from services.oms import orders as oms

from . import gate, policy
from .contract import RiskRequest, inputs_hash

REPLAY_VERSION = "decision-replay-v1"
JOURNAL = "trade_journal"
MAX_LINKED = 20
AGENT_PATHS = ("ai_trader_signal", "ai_trader_confirm")

LINEAGE_STEPS = (
    ("market_snapshot", "Market snapshot"),
    ("instrument_master", "Instrument master"),
    ("regime", "Regime"),
    ("agent_proposal", "Agent proposal"),
    ("schema_check", "Schema check"),
    ("pricing_margin", "Pricing & margin"),
    ("risk_decision", "Risk decision"),
    ("certification", "Certification"),
    ("oms", "OMS"),
    ("audit_record", "Audit record"),
)


async def load(db, decision_id: str, user_id: str, is_admin: bool) -> Optional[Dict[str, Any]]:
    """The decision row, or None when it does not exist or belongs to someone else (an admin may read any)."""
    query: Dict[str, Any] = {"_id": decision_id}
    if not is_admin:
        query["user_id"] = user_id
    return await db[rc.DECISIONS].find_one(query)


def _word(outcome: Any) -> Optional[str]:
    """The stream stores allowed / blocked; the gate's contract says allow / block."""
    return {"allowed": "allow", "allow": "allow", "blocked": "block", "block": "block"}.get(outcome)


def _codes(reasons: Any) -> List[str]:
    return [str(r.get("code")) for r in reasons or [] if isinstance(r, dict)]


def _checks(checks: Any) -> List[Dict[str, Any]]:
    return [{"check": c.get("check"), "status": c.get("status")} for c in checks or [] if isinstance(c, dict)]


def _not_replayable(row: Dict[str, Any], reason: str) -> Dict[str, Any]:
    return {"decision_id": row.get("_id"), "replayable": False, "reason": reason, "replay_version": REPLAY_VERSION,
            "writes": "none"}


def replay(row: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = row.get("snapshot")
    if row.get("source") == "risk_service":
        return _replay_service(row)
    if row.get("source") != "risk_gate":
        return _not_replayable(row, "This decision came from the kill-switch stream, not the F&O risk gate; "
                                    "only gate decisions store the inputs a replay needs.")
    if not isinstance(snapshot, dict):
        return _not_replayable(row, "This decision was recorded before decision snapshots were stored, so the "
                                    "inputs the gate read are not available to replay it on.")
    if row.get("snapshot_version") != gate.SNAPSHOT_VERSION:
        return _not_replayable(row, f"The snapshot is version {row.get('snapshot_version')!r}; this code reads "
                                    f"{gate.SNAPSHOT_VERSION}.")
    try:
        req = RiskRequest(**(snapshot.get("request") or {}))
    except (TypeError, ValidationError):
        return _not_replayable(row, "The stored request no longer fits the gate's request contract.")
    try:
        run, capital = gate.decide(req, snapshot)
    except Exception as e:  # noqa: BLE001 — a replay that cannot run is reported, never a 500
        return _not_replayable(row, f"The replay could not run on the stored snapshot ({type(e).__name__}).")

    snapshot_ok = gate.snapshot_hash(snapshot) == row.get("snapshot_hash")
    inputs_ok = inputs_hash(req) == row.get("inputs_hash")
    outcome_then, outcome_now = _word(row.get("outcome")), "block" if run.reasons else "allow"
    reasons_then, reasons_now = _codes(row.get("reasons")), [r.code for r in run.reasons]
    checks_then, checks_now = _checks(row.get("checks")), _checks([c.model_dump() for c in run.checks])

    differences: List[str] = []
    if not snapshot_ok:
        differences.append("The stored snapshot does not hash to the recorded snapshot hash.")
    if not inputs_ok:
        differences.append("The stored request does not hash to the recorded inputs hash.")
    if outcome_then != outcome_now:
        differences.append(f"Outcome was {outcome_then or 'not recorded'}, replays as {outcome_now}.")
    if reasons_then != reasons_now:
        differences.append("The reason codes differ.")
    if checks_then != checks_now:
        differences.append("The check results differ.")
    policy_then = row.get("policy_version")
    if policy_then != policy.POLICY_VERSION:
        differences.append(f"The policy was {policy_then}, it is {policy.POLICY_VERSION} now.")

    return {
        "decision_id": row.get("_id"),
        "replayable": True,
        "match": snapshot_ok and inputs_ok and outcome_then == outcome_now and reasons_then == reasons_now
                 and checks_then == checks_now,
        "outcome_then": outcome_then, "outcome_now": outcome_now,
        "reasons_then": reasons_then, "reasons_now": reasons_now,
        "checks_then": checks_then, "checks_now": checks_now,
        "capital_at_risk_then": (row.get("detail") or {}).get("capital_at_risk_rs"), "capital_at_risk_now": capital,
        "inputs_hash_match": inputs_ok, "snapshot_hash_match": snapshot_ok,
        "policy_version_then": policy_then, "policy_version_now": policy.POLICY_VERSION,
        "snapshot_version": row.get("snapshot_version"),
        "differences": differences,
        "replayed_on": "the request and the gate's own reads as stored; no market price snapshot exists (P0.3)",
        "replay_version": REPLAY_VERSION,
        "writes": "none",
    }


def _replay_service(row: Dict[str, Any]) -> Dict[str, Any]:
    """A universal risk service decision (services/risk_gate/service.py): decide() again on the stored snapshot."""
    from . import service

    snapshot = row.get("snapshot")
    if not isinstance(snapshot, dict):
        return _not_replayable(row, "This row records a reservation refused after the decision; the decision it "
                                    "supersedes carries the snapshot." if row.get("supersedes") else
                                    "This decision has no stored snapshot.")
    if row.get("snapshot_version") != service.SNAPSHOT_VERSION:
        return _not_replayable(row, f"The snapshot is version {row.get('snapshot_version')!r}; this code reads "
                                    f"{service.SNAPSHOT_VERSION}.")
    try:
        req = service.EntryRequest(**(snapshot.get("request") or {}))
        body = service.decide(req, snapshot)
    except (TypeError, ValidationError):
        return _not_replayable(row, "The stored request no longer fits the service's request contract.")
    except Exception as e:  # noqa: BLE001 — a replay that cannot run is reported, never a 500
        return _not_replayable(row, f"The replay could not run on the stored snapshot ({type(e).__name__}).")
    snapshot_ok = service.snapshot_hash(snapshot) == row.get("snapshot_hash")
    inputs_ok = service.inputs_hash(req) == row.get("inputs_hash")
    outcome_then = {"allowed": "allow", "reduced": "reduce", "blocked": "block"}.get(row.get("outcome"))
    reasons_then, reasons_now = _codes(row.get("reasons")), [r["code"] for r in body["reasons"]]
    checks_then, checks_now = _checks(row.get("checks")), _checks(body["checks"])
    qty_then = (row.get("approved_qty"), row.get("approved_lots"))
    qty_now = (body.get("approved_qty"), body.get("approved_lots"))
    differences: List[str] = []
    for ok, text in ((snapshot_ok, "The stored snapshot does not hash to the recorded snapshot hash."),
                     (inputs_ok, "The stored request does not hash to the recorded inputs hash."),
                     (outcome_then == body["outcome"], f"Outcome was {outcome_then}, replays as {body['outcome']}."),
                     (reasons_then == reasons_now, "The reason codes differ."),
                     (checks_then == checks_now, "The check results differ."),
                     (qty_then == qty_now, "The approved size differs."),
                     (row.get("policy_version") == service.POLICY_VERSION,
                      f"The policy was {row.get('policy_version')}, it is {service.POLICY_VERSION} now.")):
        if not ok:
            differences.append(text)
    return {"decision_id": row.get("_id"), "replayable": True, "match": not differences,
            "outcome_then": outcome_then, "outcome_now": body["outcome"], "reasons_then": reasons_then,
            "reasons_now": reasons_now, "checks_then": checks_then, "checks_now": checks_now,
            "approved_then": qty_then, "approved_now": qty_now, "inputs_hash_match": inputs_ok,
            "snapshot_hash_match": snapshot_ok, "policy_version_then": row.get("policy_version"),
            "policy_version_now": service.POLICY_VERSION, "snapshot_version": row.get("snapshot_version"),
            "differences": differences,
            "replayed_on": "the request and every server-resolved input as stored (the book, the last close, the "
                           "sector, the market state, the exchange reference); the bars themselves are not stored",
            "replay_version": REPLAY_VERSION, "writes": "none"}


# ── lineage ──────────────────────────────────────────────────────────────────
def _step(step_id: str, status: str, detail: str, ref: Any = None, backlog: Optional[str] = None) -> Dict[str, Any]:
    return {"step": step_id, "label": dict(LINEAGE_STEPS)[step_id], "status": status, "ref": ref, "detail": detail,
            "backlog": backlog}


def _by_check(row: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {c.get("check"): c for c in row.get("checks") or [] if isinstance(c, dict)}


async def _linked(db, decision_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """Records that carry this decision's id: OMS orders, and the paper positions written on its authority (a journal
    trade carries it on the trade, or on the entry fill it judged)."""
    lookups = (
        ("oms_orders", oms.ORDERS, ("risk_decision_id",), ("state", "client_order_id")),
        ("desk_paper_trades", desk.TRADES, ("risk_decision_id",), ("status", "symbol")),
        ("trade_journal", JOURNAL, ("risk_decision_id", "fills.risk_decision_id"), ("status", "nse_symbol")),
    )
    found: Dict[str, List[Dict[str, Any]]] = {}
    for name, collection, keys, fields in lookups:
        rows: Dict[str, Dict[str, Any]] = {}
        for key in keys:
            docs = await db[collection].find({key: decision_id}, {f: 1 for f in fields}).to_list(MAX_LINKED)
            for d in docs:
                rows.setdefault(str(d.get("_id")), {"id": str(d.get("_id")), **{f: d.get(f) for f in fields}})
        found[name] = list(rows.values())[:MAX_LINKED]
    return found


async def lineage(db, row: Dict[str, Any]) -> Dict[str, Any]:
    decision_id = str(row.get("_id"))
    snapshot = row.get("snapshot") if isinstance(row.get("snapshot"), dict) else None
    gate_row = row.get("source") == "risk_gate"
    checks = _by_check(row)
    blocked = _word(row.get("outcome")) == "block" or row.get("outcome") == "denied"
    linked = await _linked(db, decision_id)
    detail = row.get("detail") or {}
    steps: List[Dict[str, Any]] = []

    steps.append(_step("market_snapshot", "not_recorded", "No market price snapshot is stored with a decision; the "
                       "legs carry the entry prices the request sent.", backlog="P0.3"))

    refs = (snapshot or {}).get("references") or {}
    if refs:
        sources = sorted({f"{v.get('source') or 'unverified'} as of {v.get('as_of') or '—'}"
                          for v in refs.values() if isinstance(v, dict)})
        steps.append(_step("instrument_master", "recorded", "The exchange lot size and listed expiries the gate checked, "
                           f"stored in the decision snapshot: {'; '.join(sources)}. Not a versioned instrument master.",
                           ref=sorted(refs), backlog="P0.3"))
    elif snapshot is not None and detail.get("instrument") == "cash":
        steps.append(_step("instrument_master", "not_applicable", "A cash request has no contract to look up."))
    else:
        steps.append(_step("instrument_master", "not_recorded", "No contract reference is stored with this decision.",
                           backlog="P0.3"))

    steps.append(_step("regime", "not_recorded", "The gate does not read the regime, and none is stored with a "
                       "decision.", backlog="P0.3"))

    if row.get("path") in AGENT_PATHS:
        steps.append(_step("agent_proposal", "not_recorded", "The AI-trader signal this decision judged is not linked "
                           "to it by id.", backlog="P0.3"))
    elif gate_row:
        steps.append(_step("agent_proposal", "not_applicable", "A person entered this trade; no agent proposed it."))
    else:
        steps.append(_step("agent_proposal", "not_recorded", "No proposal is linked to this decision.", backlog="P0.3"))

    structure = checks.get("structure")
    if structure:
        steps.append(_step("schema_check", "recorded", f"The gate's structure check: {structure.get('status')}"
                           f"{' — ' + structure['detail'] if structure.get('detail') else ''}.", ref="checks.structure"))
    else:
        steps.append(_step("schema_check", "not_recorded", "No structure check is recorded on this row.",
                           backlog="P0.3"))

    caps = checks.get("caps")
    capital = detail.get("capital_at_risk_rs")
    if caps:
        figure = "not worked out" if capital is None else f"Rs {capital:,.2f}"
        steps.append(_step("pricing_margin", "recorded", f"Capital at risk {figure} (maximum loss at expiry at the "
                           f"entry prices, before costs); caps check {caps.get('status')}. Exchange margin is not "
                           "computed.", ref="checks.caps", backlog="P1.1"))
    else:
        steps.append(_step("pricing_margin", "not_recorded", "No pricing or caps result is recorded on this row.",
                           backlog="P0.3"))

    steps.append(_step("risk_decision", "recorded", f"{row.get('outcome') or 'outcome not recorded'} under "
                       f"{row.get('policy_version') or 'an unrecorded policy'}"
                       f"{'; ' + str(len(row.get('reasons') or [])) + ' reason(s)' if row.get('reasons') else ''}.",
                       ref=decision_id))

    steps.append(_step("certification", "not_recorded", "No certification record exists to match against.",
                       backlog="P3.1"))

    orders = linked["oms_orders"]
    if orders:
        steps.append(_step("oms", "recorded", f"{len(orders)} OMS order(s) carry this decision id.",
                           ref=[o["id"] for o in orders], backlog="P3.2"))
    elif blocked:
        steps.append(_step("oms", "not_reached", "The decision blocked the write, so no order may follow it."))
    else:
        steps.append(_step("oms", "not_recorded", "No OMS order carries this decision id; paper positions are written "
                           "to their own stores (listed below), and there is no broker order.", backlog="P3.2"))

    written = linked["desk_paper_trades"] + linked["trade_journal"]
    hashed = f" Snapshot hash {row['snapshot_hash'][:12]}…" if row.get("snapshot_hash") else ""
    steps.append(_step("audit_record", "recorded", "The decision's own row in risk_decisions; the code only inserts "
                       f"it, nothing in the database enforces append-only.{hashed} "
                       f"{len(written)} paper record(s) carry this decision id.", ref=f"risk_decisions/{decision_id}"))

    return {
        "decision_id": decision_id,
        "steps": steps,
        "recorded": sum(1 for s in steps if s["status"] == "recorded"),
        "replayable": gate_row and snapshot is not None and row.get("snapshot_version") == gate.SNAPSHOT_VERSION,
        "linked": linked,
        "lineage_version": REPLAY_VERSION,
    }
