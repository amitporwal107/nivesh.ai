"""Paper-account reconciliation: where trades, reservations and the cash ledger disagree, and the ADDITIVE entries
that correct the account.

WHY THIS EXISTS
The paper account (services/paper_account.py) arrived after the first paper trades. Trades opened before it reserved
nothing, trades closed before it never reached cash, and a structure closed before any session had marked it closed
with P&L `None`, which the close passes to the account as "no change". Nothing compared the three records, so the
account could overstate free capital (an open position holding no reservation) and nobody would see it.

THE INVARIANTS (per account; `check` computes them, and the dry run shows them before and after the proposal)
    I1  cash − starting capital  =  Σ release.net_pnl_rs + Σ adjust.cash_delta_rs
    I2  blocked                  =  Σ reserve.amount_rs − Σ release.amount_rs + Σ adjust.blocked_delta_rs
    I3  blocked                  =  Σ paper_reserved_rs over the account's open trades
    I4  every open trade holds a reservation
I1 and I2 say the account equals its ledger: cash cannot be created or destroyed without a row. I3 and I4 say the
ledger equals the positions.

WHAT A CORRECTION IS
An `adjust` ledger row (paper_account.adjust), never an edit or a delete: `_id` = idempotency key
`reconcile:<issue>:<trade_id>`, `reason_code`, the original `trade_id`, `actor: "reconcile"`, `run_id`, the deltas.
A reservation also stamps `paper_reserved_rs` on the open trade (only while it is still open and unreserved), with a
`reconciliation[]` history entry, so the trade's own close releases it. A revert adds the opposite row
(`revert:<key>`) and never removes the original.

WHAT IS NOT INVENTED
Where the right amount cannot be derived from stored data, the issue is `needs_owner_decision` and lists options,
each with its exact entry; no option is applied unless chosen. Duplicates are listed for review; nothing is deleted.
Nothing here places an order or imports a broker.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from services import desk_strategy_trades as strat
from services import paper_account as acct
from services.desk_trading import TRADES

ACTOR = "reconcile"
PLAN_VERSION = "paper-reconcile-v1"
TOL = 0.01                     # rupees: float noise below this is not a discrepancy

# Issue codes.
OPEN_UNRESERVED = "open_trade_unreserved"
PNL_NOT_IN_CASH = "closed_pnl_not_in_cash"
PNL_MISSING = "closed_pnl_missing"
ORPHAN_RESERVATION = "reservation_without_open_trade"
RESERVATION_MISMATCH = "reservation_ledger_mismatch"
PNL_POSTED_MISMATCH = "pnl_posted_mismatch"
FILL_MISMATCH = "pnl_not_from_fill"
DUPLICATES = "duplicate_trades"
ACCOUNT_CASH = "account_cash_mismatch"
ACCOUNT_BLOCKED = "account_blocked_mismatch"
ACCOUNT_MISSING = "account_missing"
REVERT = "revert"

# Resolutions.
PROPOSED, DECISION, REVIEW, RESOLVED = "proposed", "needs_owner_decision", "review_only", "resolved"

NO_POSITION_EXITS = ("cancelled", "entry_not_reached")

TRADE_FIELDS = ("_id", "user_id", "kind", "status", "symbol", "underlying", "family", "quantity", "entry_price",
                "stop_price", "target_price", "opened_at", "closed_at", "paper_reserved_rs", "exit_reason", "exit_price",
                "exit_session", "exit_note", "realized_pnl_rs", "costs_rs", "net_pnl_rs", "sim_entry_price",
                "entry_status", "legs", "cost_model", "observations", "held_sessions", "checked_through",
                "reconciliation", "flags")
ACCOUNT_FIELDS = ("user_id", "cash_rs", "blocked_rs", "starting_capital_rs", "created_at", "adjustment_keys")
LEDGER_FIELDS = ("_id", "user_id", "at", "action", "amount_rs", "net_pnl_rs", "trade_id", "symbol", "cash_delta_rs",
                 "blocked_delta_rs", "reason_code", "run_id", "actor", "reverts", "stamp", "idempotency_key")


def hash_user(user_id: Any) -> str:
    """What the output shows instead of a user id."""
    return hashlib.sha256(str(user_id).encode()).hexdigest()[:8]


def _r(x: Optional[float]) -> Optional[float]:
    return None if x is None else round(float(x), 2)


def _inr(x: float) -> str:
    return f"{'−' if x < 0 else ''}₹{abs(x):,.2f}"


def _projection(fields: Iterable[str]) -> Dict[str, int]:
    return {f: 1 for f in fields}


async def load(db) -> Dict[str, List[Dict[str, Any]]]:
    """Every paper account, ledger row and desk paper trade, through allow-list projections. Reads only."""
    accounts = await db[acct.ACCOUNTS].find({}, _projection(ACCOUNT_FIELDS)).to_list(None)
    ledger = await db[acct.LEDGER].find({}, _projection(LEDGER_FIELDS)).to_list(None)
    trades = await db[TRADES].find({}, _projection(TRADE_FIELDS)).to_list(None)
    return {"accounts": accounts, "ledger": ledger, "trades": trades}


# ── the ledger, per trade and per account ────────────────────────────────────
def _num(x: Any) -> float:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else 0.0


def ledger_by_trade(rows: List[Dict[str, Any]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for row in rows:
        k = (row.get("user_id"), row.get("trade_id"))
        a = out.setdefault(k, {"reserved": 0.0, "released": 0.0, "pnl_posted": 0.0, "pnl_rows": 0, "release_rows": 0,
                               "adjust_cash": 0.0, "adjust_blocked": 0.0, "keys": set()})
        action = row.get("action")
        if action == "reserve":
            a["reserved"] += _num(row.get("amount_rs"))
        elif action == "release":
            a["released"] += _num(row.get("amount_rs"))
            a["release_rows"] += 1
            if row.get("net_pnl_rs") is not None:
                a["pnl_posted"] += _num(row.get("net_pnl_rs"))
                a["pnl_rows"] += 1
        elif action == acct.ADJUST:
            a["adjust_cash"] += _num(row.get("cash_delta_rs"))
            a["adjust_blocked"] += _num(row.get("blocked_delta_rs"))
            a["keys"].add(str(row.get("_id")))
    return out


def active_keys(rows: List[Dict[str, Any]]) -> Tuple[set, set]:
    """(keys of adjust rows that are in force, keys that were reverted)."""
    applied = {str(r.get("_id")) for r in rows if r.get("action") == acct.ADJUST and not r.get("reverts")}
    reverted = {str(r.get("reverts")) for r in rows if r.get("action") == acct.ADJUST and r.get("reverts")}
    return applied - reverted, reverted


def next_key(code: str, trade_id: str, applied: set, reverted: set) -> Tuple[Optional[str], str]:
    """(the key in force for (issue, trade), or None; the key a new entry would use). A key that was reverted is not
    reused: the next generation is `<base>#2`, `#3`, ..."""
    base = f"reconcile:{code}:{trade_id}"
    n, key = 1, base
    while True:
        if key in applied:
            return key, key
        if key not in reverted:
            return None, key
        n += 1
        key = f"{base}#{n}"


def invariants(account: Optional[Dict[str, Any]], rows: List[Dict[str, Any]], trades: List[Dict[str, Any]],
               extra: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """I1–I4 for one user's account (`extra`: entries not yet written, to project the state after them)."""
    cash_ledger = blocked_ledger = 0.0
    for row in rows:
        a = row.get("action")
        if a == "reserve":
            blocked_ledger += _num(row.get("amount_rs"))
        elif a == "release":
            blocked_ledger -= _num(row.get("amount_rs"))
            cash_ledger += _num(row.get("net_pnl_rs"))
        elif a == acct.ADJUST:
            cash_ledger += _num(row.get("cash_delta_rs"))
            blocked_ledger += _num(row.get("blocked_delta_rs"))
    open_trades = [t for t in trades if t.get("status") == "open"]
    stamped = {e["trade_id"]: e["blocked_delta_rs"] for e in (extra or []) if e.get("stamp")}
    open_reserved = sum(_num(t.get("paper_reserved_rs")) or _num(stamped.get(t["_id"])) for t in open_trades)
    unreserved = [t["_id"] for t in open_trades if not t.get("paper_reserved_rs") and t["_id"] not in stamped]
    if account is None:
        return {"account": False, "open_trades": len(open_trades), "unreserved_open_trades": unreserved, "ok": False}
    cash = _num(account.get("cash_rs")) + sum(_num(e["cash_delta_rs"]) for e in extra or [])
    blocked = _num(account.get("blocked_rs")) + sum(_num(e["blocked_delta_rs"]) for e in extra or [])
    cash_ledger += sum(_num(e["cash_delta_rs"]) for e in extra or [])
    blocked_ledger += sum(_num(e["blocked_delta_rs"]) for e in extra or [])
    start = _num(account.get("starting_capital_rs", acct.DEFAULT_CAPITAL))
    out = {
        "account": True,
        "starting_capital_rs": _r(start), "cash_rs": _r(cash), "blocked_rs": _r(blocked), "available_rs": _r(cash - blocked),
        "I1_cash_minus_start": _r(cash - start), "I1_ledger_cash": _r(cash_ledger),
        "I1_ok": abs((cash - start) - cash_ledger) <= TOL,
        "I2_ledger_blocked": _r(blocked_ledger), "I2_ok": abs(blocked - blocked_ledger) <= TOL,
        "I3_open_reserved": _r(open_reserved), "I3_ok": abs(blocked - open_reserved) <= TOL,
        "I4_unreserved_open_trades": unreserved, "I4_ok": not unreserved,
        "open_trades": len(open_trades),
    }
    out["ok"] = out["I1_ok"] and out["I2_ok"] and out["I3_ok"] and out["I4_ok"]
    return out


# ── the plan ─────────────────────────────────────────────────────────────────
def _entry(user_id: str, trade: Optional[Dict[str, Any]], trade_id: str, key: str, reason: str, *, cash: float = 0.0,
           blocked: float = 0.0, stamp: Optional[Dict[str, Any]] = None, note: str) -> Dict[str, Any]:
    return {"key": key, "user_id": user_id, "trade_id": trade_id, "symbol": (trade or {}).get("symbol"),
            "reason_code": reason, "cash_delta_rs": _r(cash) or 0.0, "blocked_delta_rs": _r(blocked) or 0.0,
            "stamp": stamp, "note": note}


def _ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _dup_signature(t: Dict[str, Any]) -> Tuple:
    if t.get("kind") == strat.KIND:
        legs = tuple((l.get("kind"), l.get("side"), l.get("lots"), l.get("lot_size"), l.get("entry_price"),
                      l.get("expiry"), l.get("strike"), l.get("option_type")) for l in t.get("legs") or [])
        return (t.get("user_id"), "strategy", t.get("underlying") or t.get("symbol"), t.get("family"), legs)
    return (t.get("user_id"), "cash", t.get("symbol"), t.get("quantity"), t.get("entry_price"), t.get("stop_price"),
            t.get("target_price"))


def why_pnl_is_none(t: Dict[str, Any]) -> str:
    opened, closed = _ts(t.get("opened_at")), _ts(t.get("closed_at"))
    held = t.get("held_sessions")
    span = f"{int((closed - opened).total_seconds())} s after it was opened" if opened and closed else "at an unknown time"
    if (held in (0, None)) and t.get("checked_through") is None:
        return (f"It was closed {span}, before any end-of-day session after its opening date had marked it: the desk "
                "marks a structure only on sessions strictly after the IST date it was opened, so no leg had an exit "
                "mark, the gross P&L and the costs were left None, and the close released the reservation with no P&L.")
    return ("At least one leg had no exit mark when it was closed (see the trade's flags), so the gross P&L and the "
            "costs were left None and the close released the reservation with no P&L.")


def build_plan(accounts: List[Dict[str, Any]], ledger: List[Dict[str, Any]], trades: List[Dict[str, Any]],
               decisions: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Every discrepancy with its evidence and resolution, and the entries to write. Pure: reads its arguments only.

    `decisions` maps "<trade_id>:<issue code>" (or a unique prefix of the trade id) to an option id; a chosen option's
    entries join the plan's entries."""
    decisions = dict(decisions or {})
    by_user_account = {a["user_id"]: a for a in accounts}
    agg = ledger_by_trade(ledger)
    applied, reverted = active_keys(ledger)
    issues: List[Dict[str, Any]] = []

    def add(code: str, t: Optional[Dict[str, Any]], user_id: str, trade_id: Optional[str], resolution: str,
            evidence: Dict[str, Any], entries: Optional[List[Dict[str, Any]]] = None,
            options: Optional[List[Dict[str, Any]]] = None, key: Optional[str] = None) -> None:
        issues.append({"issue_id": f"{trade_id}:{code}" if trade_id else f"{hash_user(user_id)}:{code}", "code": code,
                       "user": hash_user(user_id), "user_id": user_id, "trade_id": trade_id,
                       "symbol": (t or {}).get("symbol"), "status": (t or {}).get("status"),
                       "resolution": resolution, "evidence": evidence, "entries": entries or [], "options": options or [],
                       "key": key})

    def keyed(code: str, trade_id: str) -> Tuple[Optional[str], str]:
        return next_key(code, trade_id, applied, reverted)

    by_id = {t["_id"]: t for t in trades}
    for t in sorted(trades, key=lambda d: str(d.get("opened_at") or "")):
        uid, tid = t["user_id"], t["_id"]
        a = agg.get((uid, tid), {"reserved": 0.0, "released": 0.0, "pnl_posted": 0.0, "pnl_rows": 0, "release_rows": 0,
                                 "adjust_cash": 0.0, "adjust_blocked": 0.0, "keys": set()})
        net_reserved = a["reserved"] - a["released"] + a["adjust_blocked"]
        account = by_user_account.get(uid)
        base_ev = {"opened_at": t.get("opened_at"), "closed_at": t.get("closed_at"), "kind": t.get("kind") or "cash",
                   "paper_reserved_rs": t.get("paper_reserved_rs"), "ledger_net_reserved_rs": _r(net_reserved),
                   "account_created_at": (account or {}).get("created_at")}

        if t.get("status") == "open":
            if not t.get("paper_reserved_rs"):
                if net_reserved > TOL:
                    add(RESERVATION_MISMATCH, t, uid, tid, DECISION, {**base_ev, "why": (
                        "The ledger holds a reservation for this trade but the trade records none; which is right cannot "
                        "be told from the stored data.")}, options=[])
                    continue
                if account is None:
                    continue                                    # reported once per user below (account_missing)
                exposure = strat.exposure_rs(t) if t.get("kind") == strat.KIND else None
                amount = acct.reservation_for(t, exposure)
                in_force, key = keyed(OPEN_UNRESERVED, tid)
                if amount is None:
                    add(OPEN_UNRESERVED, t, uid, tid, DECISION, {**base_ev, "why": "The trade cannot be priced "
                        "(a quantity, price or leg field is missing), so its reservation cannot be derived."})
                    continue
                basis = ("quantity × entry price" if t.get("kind") != strat.KIND
                         else "capital at risk (desk_strategy_trades.exposure_rs)")
                ev = {**base_ev, "reservation_rs": amount, "basis": basis, "why": (
                    "Open position holding no reservation: opened before the paper account existed"
                    if account and _ts(t.get("opened_at")) and _ts(account.get("created_at"))
                    and _ts(t.get("opened_at")) < _ts(account.get("created_at"))
                    else "Open position holding no reservation")}
                note = f"Reserve {basis} for an open position that holds no reservation ({amount:,.2f})."
                add(OPEN_UNRESERVED, t, uid, tid, PROPOSED, ev, entries=[_entry(
                    uid, t, tid, key, OPEN_UNRESERVED, blocked=amount, note=note,
                    stamp={"field": "paper_reserved_rs", "before": t.get("paper_reserved_rs"), "after": amount})], key=key)
            elif abs(net_reserved - _num(t.get("paper_reserved_rs"))) > TOL:
                add(RESERVATION_MISMATCH, t, uid, tid, DECISION, {**base_ev, "why": (
                    "The trade's reservation and the ledger's net reservation for it differ; which is right cannot be told "
                    "from the stored data.")})
            continue

        # closed
        if net_reserved > TOL:
            in_force, key = keyed(ORPHAN_RESERVATION, tid)
            add(ORPHAN_RESERVATION, t, uid, tid, PROPOSED, {**base_ev, "why": (
                "The trade is closed but the ledger still holds part of its reservation (reserved minus released).")},
                entries=[_entry(uid, t, tid, key, ORPHAN_RESERVATION, blocked=-net_reserved,
                                note=f"Release {net_reserved:,.2f} still reserved for a closed trade.")], key=key)
        elif net_reserved < -TOL:
            add(RESERVATION_MISMATCH, t, uid, tid, DECISION, {**base_ev, "why": (
                "The ledger released more for this trade than it reserved.")})

        if t.get("exit_reason") in NO_POSITION_EXITS:
            continue
        posted = a["pnl_posted"] + a["adjust_cash"]
        net = t.get("net_pnl_rs")
        if t.get("kind") != strat.KIND and t.get("exit_price") is not None and t.get("realized_pnl_rs") is not None:
            fill = t.get("sim_entry_price") if t.get("sim_entry_price") is not None else t.get("entry_price")
            expected = (float(t["exit_price"]) - float(fill)) * int(t["quantity"])
            if abs(expected - float(t["realized_pnl_rs"])) > TOL:
                add(FILL_MISMATCH, t, uid, tid, REVIEW, {**base_ev, "realized_pnl_rs": t.get("realized_pnl_rs"),
                    "from_fill_rs": _r(expected), "sim_entry_price": t.get("sim_entry_price"),
                    "why": "Gross P&L was not computed from the simulated fill (study item 0.2); not corrected here."})

        if net is None:
            in_force, key = keyed(PNL_MISSING, tid)
            if in_force:
                add(PNL_MISSING, t, uid, tid, RESOLVED, {**base_ev, "resolved_by": in_force})
                continue
            if account is None:
                continue
            options = [{"option": "void", "cash_delta_rs": 0.0, "text": (
                "Record that this trade has no cash effect (opened and closed with no session in between); a "
                "zero-amount entry documents the decision.")}]
            if t.get("kind") == strat.KIND and t.get("legs"):
                costs = strat.strategy_costs(t, [leg.get("entry_price") for leg in t["legs"]])
                if costs is not None:
                    source = t["legs"][0].get("price_source") or "the entry prices"
                    options.insert(0, {"option": "costs_at_entry_marks", "cash_delta_rs": -_r(costs), "text": (
                        f"Gross P&L ₹0.00 at the only marks on record when it closed (each leg's entry mark: {source}), "
                        f"minus the round-trip costs of the trade's own cost model, ₹{costs:,.2f}. This is what a cash "
                        f"trade closed at its entry price is charged.")})
            ev = {**base_ev, "observations": t.get("observations"), "held_sessions": t.get("held_sessions"),
                  "checked_through": t.get("checked_through"), "exit_note": t.get("exit_note"),
                  "flags": [f.get("code") for f in t.get("flags") or [] if isinstance(f, dict)], "why": why_pnl_is_none(t)}
            add(PNL_MISSING, t, uid, tid, DECISION, ev, options=[
                {**o, "entries": [_entry(uid, t, tid, key, PNL_MISSING, cash=o["cash_delta_rs"],
                                         note=f"Owner decision '{o['option']}': {o['text']}")]} for o in options], key=key)
            continue

        if abs(posted - float(net)) <= TOL:
            continue
        in_force, key = keyed(PNL_NOT_IN_CASH, tid)
        if in_force:
            add(PNL_NOT_IN_CASH, t, uid, tid, RESOLVED, {**base_ev, "resolved_by": in_force})
            continue
        if account is None:
            continue
        if abs(posted) <= TOL and a["pnl_rows"] == 0 and not (a["keys"] & applied):   # nothing in force for it
            closed, created = _ts(t.get("closed_at")), _ts(account.get("created_at"))
            before_account = bool(closed and created and closed < created)
            ev = {**base_ev, "net_pnl_rs": _r(net), "posted_rs": _r(posted), "closed_before_account": before_account,
                  "why": ("Closed before the paper account existed, so its close never reached cash. Trades opened before "
                          "the account but closed after it (HAL) did reach cash, so including or excluding it is a "
                          "policy choice." if before_account else
                          "Closed after the account existed, but no release with its P&L is in the ledger.")}
            opts = [{"option": "post_pnl", "cash_delta_rs": _r(net), "text": f"Post its net P&L ({_inr(net)}) to cash."},
                    {"option": "exclude", "cash_delta_rs": 0.0, "text": (
                        "Keep it out of the account (the account covers trades closed after it was created); a "
                        "zero-amount entry documents the decision.")}]
            options = [{**o, "entries": [_entry(uid, t, tid, key, PNL_NOT_IN_CASH, cash=o["cash_delta_rs"],
                                                note=f"Owner decision '{o['option']}': {o['text']}")]} for o in opts]
            inv = invariants(account, [r for r in ledger if r.get("user_id") == uid],
                             [x for x in trades if x["user_id"] == uid])
            if not before_account and inv["I1_ok"]:
                add(PNL_NOT_IN_CASH, t, uid, tid, PROPOSED, ev, entries=options[0]["entries"], key=key)
            else:
                add(PNL_NOT_IN_CASH, t, uid, tid, DECISION, ev, options=options, key=key)
        else:
            add(PNL_POSTED_MISMATCH, t, uid, tid, DECISION, {**base_ev, "net_pnl_rs": _r(net), "posted_rs": _r(posted),
                "why": "The P&L in cash for this trade differs from the trade's net P&L."},
                options=[{"option": "post_difference", "cash_delta_rs": _r(float(net) - posted), "text": (
                    "Post the difference so cash carries the trade's recorded net P&L."), "entries": [_entry(
                        uid, t, tid, keyed(PNL_POSTED_MISMATCH, tid)[1], PNL_POSTED_MISMATCH, cash=float(net) - posted,
                        note="Owner decision 'post_difference'.")]}])

    # Ledger rows for trades that are not stored.
    for (uid, tid), a in sorted(agg.items(), key=lambda kv: str(kv[0])):
        if tid in by_id or tid is None:
            continue
        net_reserved = a["reserved"] - a["released"] + a["adjust_blocked"]
        if net_reserved > TOL and uid in by_user_account:
            in_force, key = keyed(ORPHAN_RESERVATION, tid)
            add(ORPHAN_RESERVATION, None, uid, tid, PROPOSED, {"why": "The ledger reserved capital for a trade that is "
                "not stored (its insert failed and nothing released it).", "ledger_net_reserved_rs": _r(net_reserved)},
                entries=[_entry(uid, None, tid, key, ORPHAN_RESERVATION, blocked=-net_reserved,
                                note=f"Release {net_reserved:,.2f} reserved for a trade that does not exist.")], key=key)

    # Duplicates: review only.
    groups: Dict[Tuple, List[Dict[str, Any]]] = {}
    for t in trades:
        groups.setdefault(_dup_signature(t), []).append(t)
    for sig, members in groups.items():
        if len(members) < 2:
            continue
        members = sorted(members, key=lambda d: str(d.get("opened_at") or ""))
        first = members[0]
        issues.append({"issue_id": f"{first['_id']}:{DUPLICATES}", "code": DUPLICATES, "user": hash_user(first["user_id"]),
                       "user_id": first["user_id"], "trade_id": first["_id"], "symbol": first.get("symbol"),
                       "status": None, "resolution": REVIEW, "entries": [], "options": [], "key": None,
                       "evidence": {"count": len(members), "why": "Identical instrument, size and levels: the desk accepted "
                                    "the same trade more than once (study item 0.5). Listed for review; nothing is deleted.",
                                    "trades": [{"trade_id": m["_id"], "status": m.get("status"), "opened_at": m.get("opened_at"),
                                                "net_pnl_rs": m.get("net_pnl_rs"), "paper_reserved_rs": m.get("paper_reserved_rs")}
                                               for m in members]}})

    # Decisions → entries.
    unknown: List[str] = []
    for spec, option in decisions.items():
        prefix, _, code = spec.partition(":")
        matches = [i for i in issues if i["resolution"] == DECISION and i["code"] == code
                   and str(i["trade_id"]).startswith(prefix) and len(prefix) >= 8]
        if len(matches) != 1:
            unknown.append(f"{spec}: {'no' if not matches else 'more than one'} open decision matches")
            continue
        [issue] = matches
        picked = [o for o in issue["options"] if o["option"] == option]
        if not picked:
            unknown.append(f"{spec}: no option '{option}' (options: {', '.join(o['option'] for o in issue['options'])})")
            continue
        issue["resolution"] = "decided"
        issue["decision"] = option
        issue["entries"] = picked[0]["entries"]
    entries = [e for i in issues if i["resolution"] in (PROPOSED, "decided") for e in i["entries"]]

    # Per account: the invariants now and after the entries, and what the account-level check cannot explain.
    users = sorted({t["user_id"] for t in trades} | set(by_user_account) | {r.get("user_id") for r in ledger if r.get("user_id")})
    summaries = []
    for uid in users:
        rows = [r for r in ledger if r.get("user_id") == uid]
        mine = [t for t in trades if t["user_id"] == uid]
        account = by_user_account.get(uid)
        before = invariants(account, rows, mine)
        after = invariants(account, rows, mine, [e for e in entries if e["user_id"] == uid])
        if account is None:
            if mine:
                add(ACCOUNT_MISSING, None, uid, None, DECISION, {"trades": len(mine), "why": (
                    "This user has paper trades but no paper account; a reconciliation never creates one.")})
        else:
            if not before["I1_ok"]:
                add(ACCOUNT_CASH, None, uid, None, DECISION, {"cash_minus_start_rs": before["I1_cash_minus_start"],
                    "ledger_cash_rs": before["I1_ledger_cash"], "why": "Cash differs from the sum of its ledger; the "
                    "missing movement cannot be identified from the stored data, so no amount is proposed."})
            if not before["I2_ok"]:
                add(ACCOUNT_BLOCKED, None, uid, None, DECISION, {"blocked_rs": before["blocked_rs"],
                    "ledger_blocked_rs": before["I2_ledger_blocked"], "why": "Blocked differs from the sum of its "
                    "ledger; no amount is proposed."})
        summaries.append({"user": hash_user(uid), "user_id": uid, "before": before, "after_proposed": after})

    return {"plan_version": PLAN_VERSION, "accounts": summaries, "issues": issues, "entries": entries,
            "decision_errors": unknown,
            "counts": {"trades": len(trades), "ledger_rows": len(ledger), "accounts": len(accounts),
                       "issues": len(issues), "entries": len(entries),
                       "by_resolution": _count(i["resolution"] for i in issues), "by_code": _count(i["code"] for i in issues)}}


def _count(values: Iterable[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out


# ── writes ───────────────────────────────────────────────────────────────────
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def apply(db, plan: Dict[str, Any], run_id: str, *, snapshot: Optional[str] = None) -> Dict[str, Any]:
    """Write the plan's entries. Each is applied at most once (its key); a re-run writes nothing new. `snapshot` names
    the pre-change snapshot and is recorded on every entry."""
    report = {"run_id": run_id, "moved": [], "already_applied": [], "skipped": []}
    for e in plan["entries"]:
        uid, tid, key = e["user_id"], e["trade_id"], e["key"]
        if e.get("stamp"):
            field, before, after = e["stamp"]["field"], e["stamp"]["before"], e["stamp"]["after"]
            history = {"key": key, "run_id": run_id, "actor": ACTOR, "reason_code": e["reason_code"], "field": field,
                       "before": before, "after": after, "at": _now_iso()}
            res = await db[TRADES].update_one(
                {"_id": tid, "user_id": uid, "status": "open", field: before},
                {"$set": {field: after}, "$push": {"reconciliation": history}})
            if not res.matched_count:
                doc = await db[TRADES].find_one({"_id": tid, "user_id": uid})
                if not any(h.get("key") == key for h in (doc or {}).get("reconciliation") or []):
                    report["skipped"].append({"key": key, "why": "the trade is no longer open and unreserved"})
                    continue
        row = {"reason_code": e["reason_code"], "trade_id": tid, "symbol": e.get("symbol"), "actor": ACTOR,
               "run_id": run_id, "note": e.get("note"), "plan_version": PLAN_VERSION, "stamp": e.get("stamp"),
               "snapshot": snapshot}
        moved = await acct.adjust(db, uid, key=key, cash_delta=e["cash_delta_rs"], blocked_delta=e["blocked_delta_rs"],
                                  row=row)
        report["moved" if moved else "already_applied"].append(key)
    return report


async def revert(db, run_id: str, revert_run_id: str, *, snapshot: Optional[str] = None) -> Dict[str, Any]:
    """Add the opposite of every entry `run_id` wrote. Never deletes. A reservation whose trade has closed since is
    skipped: the close released it, so reversing it as well would release it twice."""
    rows = await db[acct.LEDGER].find({"action": acct.ADJUST, "run_id": run_id, "actor": ACTOR},
                                      _projection(LEDGER_FIELDS)).to_list(None)
    report = {"run_id": revert_run_id, "reverts": run_id, "moved": [], "already_applied": [], "skipped": []}
    for row in sorted(rows, key=lambda r: str(r.get("_id"))):
        if row.get("reverts"):
            continue
        key, uid, tid = str(row["_id"]), row["user_id"], row.get("trade_id")
        rkey = f"revert:{key}"
        stamp = row.get("stamp")
        if stamp:
            history = {"key": rkey, "run_id": revert_run_id, "actor": ACTOR, "reason_code": REVERT,
                       "field": stamp["field"], "before": stamp["after"], "after": stamp["before"], "at": _now_iso()}
            res = await db[TRADES].update_one(
                {"_id": tid, "user_id": uid, "status": "open", stamp["field"]: stamp["after"]},
                {"$set": {stamp["field"]: stamp["before"]}, "$push": {"reconciliation": history}})
            if not res.matched_count:
                doc = await db[TRADES].find_one({"_id": tid, "user_id": uid})
                if not any(h.get("key") == rkey for h in (doc or {}).get("reconciliation") or []):
                    report["skipped"].append({"key": key, "why": "the trade has closed (or changed) since; its close "
                                              "released the reservation, so it is not reversed again"})
                    continue
        moved = await acct.adjust(db, uid, key=rkey, cash_delta=-_num(row.get("cash_delta_rs")),
                                  blocked_delta=-_num(row.get("blocked_delta_rs")),
                                  row={"reason_code": REVERT, "reverts": key, "trade_id": tid, "symbol": row.get("symbol"),
                                       "actor": ACTOR, "run_id": revert_run_id, "plan_version": PLAN_VERSION,
                                       "snapshot": snapshot, "note": f"Reverses {key} (run {run_id})."})
        report["moved" if moved else "already_applied"].append(rkey)
    return report


# ── the user's own corrections (GET /api/desk/paper-account/corrections) ─────
#: What the corrections list reads of a ledger row: an allow-list. Never user_id, snapshot, stamp or policy_version.
CORRECTION_FIELDS = ("_id", "action", "at", "reason_code", "trade_id", "symbol", "note", "cash_delta_rs",
                     "blocked_delta_rs", "reverts", "run_id", "actor")
MAX_CORRECTIONS = 1000
REASON_LABELS = {
    OPEN_UNRESERVED: "An open position held no reservation",
    PNL_NOT_IN_CASH: "A closed trade's P&L had not reached cash",
    PNL_MISSING: "A closed trade had no P&L on record",
    ORPHAN_RESERVATION: "Capital was reserved for a trade that was never stored",
    RESERVATION_MISMATCH: "The ledger's reservation did not match the trade",
    PNL_POSTED_MISMATCH: "The P&L in cash differed from the trade's net P&L",
    REVERT: "Reverses an earlier correction",
}
_DECISION_RE = re.compile(r"^Owner decision '([a-z_]+)'")


def decision_of(note: Any) -> Optional[str]:
    """The owner's option named in a correction's note ("Owner decision 'exclude': ..."), or None: an entry the dry
    run proposed (a reservation, a release) or a revert carries no decision."""
    m = _DECISION_RE.match(note) if isinstance(note, str) else None
    return m.group(1) if m else None


async def corrections(db, user_id: str) -> Dict[str, Any]:
    """The user's correction rows (ledger action `adjust`), newest first, each with the decision it records and
    whether it is still in force. One read, filtered to this user, with the allow-list projection. Writes nothing."""
    rows = await db[acct.LEDGER].find({"user_id": user_id, "action": acct.ADJUST}, _projection(CORRECTION_FIELDS)) \
        .sort("at", -1).to_list(MAX_CORRECTIONS + 1)
    truncated = len(rows) > MAX_CORRECTIONS
    rows = rows[:MAX_CORRECTIONS]
    applied, _reverted = active_keys(rows)
    reverted_by = {str(r["reverts"]): str(r.get("_id")) for r in rows if r.get("reverts")}
    out = []
    for r in rows:
        key = str(r.get("_id"))
        is_revert = bool(r.get("reverts"))
        decision = decision_of(r.get("note"))
        out.append({
            "id": key, "at": r.get("at"), "reason_code": r.get("reason_code"),
            "reason": REASON_LABELS.get(r.get("reason_code")), "decision": decision,
            "kind": "revert" if is_revert else ("owner_decision" if decision else "proposed"),
            "trade_id": r.get("trade_id"), "symbol": r.get("symbol"),
            "cash_delta_rs": r.get("cash_delta_rs"), "blocked_delta_rs": r.get("blocked_delta_rs"),
            "note": r.get("note"), "reverts": r.get("reverts"), "reverted_by": reverted_by.get(key),
            "in_force": is_revert or key in applied, "run_id": r.get("run_id"), "actor": r.get("actor"),
        })
    live = [c for c in out if c["in_force"] and c["kind"] != "revert"]
    return {"corrections": out, "count": len(out), "truncated": truncated,
            "counts": {"in_force": len(live), "excluded": sum(1 for c in live if c["decision"] == "exclude"),
                       "voided": sum(1 for c in live if c["decision"] == "void"),
                       "reverted": sum(1 for c in out if c["reverted_by"]),
                       "by_reason_code": _count(str(c["reason_code"]) for c in out)},
            "append_only": True, "plan_version": PLAN_VERSION,
            "note": ("Corrections are added to the ledger, never edited or deleted. A revert adds the opposite entry; "
                     "the original stays and is marked not in force.")}


def check(data: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """I1–I4 for every account (the daily check). Pure."""
    out = []
    for account in data["accounts"]:
        uid = account["user_id"]
        inv = invariants(account, [r for r in data["ledger"] if r.get("user_id") == uid],
                         [t for t in data["trades"] if t["user_id"] == uid])
        out.append({"user": hash_user(uid), **inv})
    return out
