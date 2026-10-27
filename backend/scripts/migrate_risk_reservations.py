"""Reserve risk for the positions opened BEFORE Phase 1 (study §6 Phase 1, A Q10 migration risk 1).

Positions opened before the universal risk service exist carry no risk reservation on their paper account
(services/paper_account.reserve_entry). Until they do, the service counts them against the budgets from their stored
levels on every decision (services/risk_book.py "legacy"), so nothing is unsafe; this script moves them onto the account's
counters so the ATOMIC reservation sees them too, and so `reservation_invariants` describes the whole book.

    python -m scripts.migrate_risk_reservations                      DRY RUN (the default): reads only, prints the plan
    python -m scripts.migrate_risk_reservations --apply --run-id R --snapshot PATH
                                                                     writes, after a snapshot (needs the owner's go-ahead)
    python -m scripts.migrate_risk_reservations --rollback R --snapshot PATH
                                                                     undoes run R exactly

WHAT A RESERVATION FOR AN EXISTING POSITION HOLDS
    risk_rs       its estimated risk from its stored levels (services/risk_book.legacy_estimate: shares =
                  qty x (entry - stop) + desk-cost-v2 costs + 1% gap stress; a structure from its legs; a journal trade
                  from its held shares and stop, or its whole invested amount when it has no stop)
    exposure_rs   its market exposure (notional; a structure's desk_strategy_trades.exposure_rs)
    sector        NSE industry (services/risk_gate/inputs.sector_map); unknown is kept unknown (counted conservatively)
    funding_rs    0: the funds are NOT touched. A trade's paper_reserved_rs stays as it is; a trade that never reserved
                  funds (staging's first ICICIBANK) is the Phase 0 reconciliation's business (services/paper_reconcile.py)
    positions 1, held symbol for a share / journal position; reservation id "migr-<trade id>"; migration_run_id = R
Existing positions are GRANDFATHERED: the reservation is written without a budget filter (they are already open), and a
book over a cap simply refuses new entries until it falls back under it. The dry run says which caps are exceeded.

APPLY (not run by the author; the owner approves staging writes, study §9.2):
    1. snapshot: every affected paper_accounts document and each trade's risk fields, written to PATH (must not exist)
    2. per position, ONE conditional update on its account ({reservations.id: {$ne: rid}}: $inc the counters, $push the
       entry) — re-running it changes nothing — then the trade's risk_reservation_id set where it is unset
    3. validation: reservation_invariants(account) == [] for every account, and every open position reserved
ROLLBACK: per entry of run R, ONE conditional update ({reservations.id: rid}: $inc the negatives, $pull the entry) and
the trade's risk_reservation_id unset where it equals rid; then the same validation.

Read-only by construction in the dry run: it calls find / find_one only (tests/test_risk_migration.py checks it with a
database that raises on any write). User ids are printed hashed.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

MIGRATION_VERSION = "risk-reservation-migration-v1"


def hash_user(user_id: Any) -> str:
    return hashlib.sha256(str(user_id).encode()).hexdigest()[:8]


async def plan(db, *, sectors: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """The migration plan, from reads only."""
    from services import desk_strategy_trades as strat
    from services import desk_trading as desk
    from services import paper_account as acct
    from services import risk_book
    from services import risk_profile
    from services.ai_trader.risk_governor import DEFAULT_LIMITS

    accounts = {a["user_id"]: a async for a in db[acct.ACCOUNTS].find({}, {"_id": 0})}
    trades = [d async for d in db[desk.TRADES].find({"status": "open"})]
    journal = [d async for d in db[risk_book.JOURNAL].find({"status": "OPEN"})]
    reserved_ids = {(uid, e.get("trade_id")) for uid, a in accounts.items() for e in (a.get("reservations") or [])}
    rows: List[Dict[str, Any]] = []
    for d in trades + journal:
        store = risk_book.JOURNAL if d in journal else desk.TRADES
        uid = d["user_id"]
        if (uid, d["_id"]) in reserved_ids or d.get("risk_reservation_id"):
            rows.append({"trade_id": d["_id"], "user": hash_user(uid), "status": "already_reserved"})
            continue
        if store == desk.TRADES:
            est = risk_book.legacy_estimate(d)
            kind = "structure" if d.get("kind") == strat.KIND else "cash"
            symbol = d.get("underlying") if kind == "structure" else d.get("symbol")
            qty, entry, stop = d.get("quantity"), d.get("entry_price"), d.get("stop_price") or d.get("stop_underlying")
        else:
            jp = risk_book.journal_position(d)
            est = risk_book.legacy_journal_estimate(d, jp)
            kind, symbol = "journal", d.get("nse_symbol")
            qty, entry, stop = jp["held_qty"], round(jp["avg_buy"], 2), d.get("stop_loss")
        sector = (sectors or {}).get(str(symbol or "").upper())
        rows.append({
            "trade_id": d["_id"], "user": hash_user(uid), "user_id": uid, "store": store, "kind": kind, "symbol": symbol,
            "qty": qty, "entry": entry, "stop": stop, "opened_at": d.get("opened_at"),
            "paper_reserved_rs": d.get("paper_reserved_rs"), "risk_rs": est.get("risk_rs"),
            "exposure_rs": est.get("exposure_rs"), "sector": sector,
            "status": "to_reserve" if est.get("risk_rs") is not None else "risk_unknown",
            "reservation_id": f"migr-{d['_id']}",
        })
    # What each account would hold afterwards, against the owner's default caps (equity = cash here: the dry run does
    # not mark positions, so this is the cash basis, said so).
    by_user: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        if r["status"] != "to_reserve":
            continue
        u = by_user.setdefault(r["user_id"], {"risk_rs": 0.0, "exposure_rs": 0.0, "positions": 0, "sector_rs": {}})
        u["risk_rs"] += r["risk_rs"]
        u["exposure_rs"] += r["exposure_rs"] or 0.0
        u["positions"] += 1
        key = r["sector"] or "unknown"
        u["sector_rs"][key] = u["sector_rs"].get(key, 0.0) + (r["exposure_rs"] or 0.0)
    limits = risk_profile.NAMED[risk_profile.OWNER_DEFAULT]
    checks = []
    for uid, u in by_user.items():
        a = accounts.get(uid) or {}
        cash = float(a.get("cash_rs", acct.DEFAULT_CAPITAL))
        prior = {"risk_rs": float(a.get("open_risk_rs") or 0.0), "exposure_rs": float(a.get("exposure_rs") or 0.0),
                 "positions": int(a.get("open_positions") or 0)}
        after = {k: round(prior[k] + u[k], 2) for k in ("risk_rs", "exposure_rs", "positions")}
        over = []
        if after["risk_rs"] > cash * limits["max_open_risk_pct"] / 100:
            over.append(f"open risk {after['risk_rs']:,.2f} > {limits['max_open_risk_pct']}% of cash")
        if after["exposure_rs"] > cash * DEFAULT_LIMITS.max_net_exposure_pct / 100:
            over.append("net exposure over the governor's 80%")
        if after["positions"] > DEFAULT_LIMITS.max_open_positions:
            over.append(f"{after['positions']} positions > {DEFAULT_LIMITS.max_open_positions}")
        for sec, rs in u["sector_rs"].items():
            if rs > cash * limits["max_sector_pct"] / 100:
                over.append(f"sector {sec} {rs:,.2f} > {limits['max_sector_pct']}% of cash")
        checks.append({"user": hash_user(uid), "account_exists": bool(a), "cash_rs": round(cash, 2),
                       "counters_before": prior, "counters_after": after,
                       "sector_rs_after": {k: round(v, 2) for k, v in u["sector_rs"].items()},
                       "existing_invariants": acct.reservation_invariants(a) if a else [],
                       "over_owner_default_caps": over,
                       "unfunded_trades": [r["trade_id"] for r in rows if r.get("user_id") == uid and r["status"] == "to_reserve"
                                           and r["store"] == desk.TRADES and not r.get("paper_reserved_rs")]})
    counts = {"accounts": len(accounts), "open_desk_trades": len(trades), "open_journal_trades": len(journal),
              "already_reserved": sum(r["status"] == "already_reserved" for r in rows),
              "to_reserve": sum(r["status"] == "to_reserve" for r in rows),
              "risk_unknown": sum(r["status"] == "risk_unknown" for r in rows),
              "accounts_affected": len(by_user)}
    return {"version": MIGRATION_VERSION, "counts": counts, "rows": rows, "accounts": checks}


async def apply(db, the_plan: Dict[str, Any], run_id: str, snapshot_path: str) -> Dict[str, Any]:
    """Write the plan (see the module docstring). Not run in the author's session."""
    from services import paper_account as acct

    todo = [r for r in the_plan["rows"] if r["status"] == "to_reserve"]
    users = sorted({r["user_id"] for r in todo})
    if os.path.exists(snapshot_path):
        raise SystemExit(f"refusing to overwrite the snapshot {snapshot_path}")
    snap = {"run_id": run_id, "at": datetime.now(timezone.utc).isoformat(), "version": MIGRATION_VERSION,
            "accounts": [a async for a in db[acct.ACCOUNTS].find({"user_id": {"$in": users}}, {"_id": 0})],
            "trades": [{"trade_id": r["trade_id"], "store": r["store"]} for r in todo]}
    with open(snapshot_path, "x") as fh:
        json.dump(snap, fh, default=str)
    moved = 0
    for r in todo:
        entry = {"id": r["reservation_id"], "trade_id": r["trade_id"], "store": r["store"], "path": "migration",
                 "kind": r["kind"], "symbol": str(r["symbol"] or "").upper(), "sector": r["sector"],
                 "sector_key": acct.field_key(r["sector"]) if r["sector"] else None,
                 "held_key": acct.field_key(r["symbol"]) if r["kind"] in ("cash", "journal") else None,
                 "risk_rs": round(float(r["risk_rs"]), 2), "exposure_rs": round(float(r["exposure_rs"] or 0.0), 2),
                 "funding_rs": 0.0, "positions": 1, "at": datetime.now(timezone.utc).isoformat(),
                 "version": acct.RESERVATION_VERSION, "migration_run_id": run_id}
        await acct.ensure(db, r["user_id"])
        res = await db[acct.ACCOUNTS].update_one(
            {"user_id": r["user_id"], "reservations.id": {"$ne": entry["id"]}},
            {"$inc": acct._entries_inc([entry], sign=1), "$push": {"reservations": entry}})
        moved += int(bool(res.matched_count))
        await db[r["store"]].update_one({"_id": r["trade_id"], "risk_reservation_id": {"$exists": False}},
                                        {"$set": {"risk_reservation_id": entry["id"], "risk_migration_run_id": run_id}})
    return {"reserved": moved, "validation": await validate(db, users)}


async def rollback(db, run_id: str) -> Dict[str, Any]:
    from services import paper_account as acct

    undone = 0
    users = []
    async for a in db[acct.ACCOUNTS].find({"reservations.migration_run_id": run_id}):
        users.append(a["user_id"])
        for e in [e for e in a.get("reservations") or [] if e.get("migration_run_id") == run_id]:
            res = await db[acct.ACCOUNTS].update_one(
                {"user_id": a["user_id"], "reservations.id": e["id"]},
                {"$inc": acct._entries_inc([e], sign=-1), "$pull": {"reservations": {"id": e["id"]}}})
            undone += int(bool(res.matched_count))
            await db[e["store"]].update_one({"_id": e["trade_id"], "risk_reservation_id": e["id"]},
                                            {"$unset": {"risk_reservation_id": "", "risk_migration_run_id": ""}})
    return {"undone": undone, "validation": await validate(db, users)}


async def validate(db, users: List[str]) -> Dict[str, Any]:
    from services import paper_account as acct
    out = {}
    for uid in users:
        a = await db[acct.ACCOUNTS].find_one({"user_id": uid})
        out[hash_user(uid)] = acct.reservation_invariants(a)
    return out


async def _sectors() -> Dict[str, str]:
    from services.risk_gate import inputs
    try:
        cache = await inputs._sector_map()
        return {k: v["sector"] for k, v in (cache.get("map") or {}).items()}
    except Exception as e:  # noqa: BLE001 — the plan then says "unknown", never guesses
        print(f"sector lists unreadable ({type(e).__name__}); sectors left unknown")
        return {}


def _print(the_plan: Dict[str, Any]) -> None:
    print(f"{MIGRATION_VERSION} DRY RUN — read only, nothing written")
    print("counts:", json.dumps(the_plan["counts"]))
    for r in the_plan["rows"]:
        if r["status"] == "already_reserved":
            print(f"  {r['user']} {r['trade_id'][:8]} already reserved")
            continue
        print(f"  {r['user']} {r['trade_id'][:8]} {r['store']:<17} {r['kind']:<9} {str(r['symbol']):<10} qty={r['qty']} "
              f"entry={r['entry']} stop={r['stop']} risk_rs={r['risk_rs']} exposure_rs={r['exposure_rs']} "
              f"sector={r['sector']} paper_reserved_rs={r['paper_reserved_rs']} -> {r['status']} ({r['reservation_id']})")
    for a in the_plan["accounts"]:
        print("account", json.dumps(a, default=str))
    print("snapshot (on --apply): the affected paper_accounts documents in full + each trade's id and store, to --snapshot")
    print("apply: per position one conditional update {user_id, reservations.id $ne migr-<trade>}: $inc counters, $push "
          "entry; then trade.risk_reservation_id set where unset. Re-running changes nothing.")
    print("validate: reservation_invariants(account) == [] for every affected account; every open position reserved")
    print("rollback: --rollback <run id>: per entry of that run, $inc the negatives and $pull it; unset the trade's id")


async def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--apply", action="store_true")
    p.add_argument("--rollback")
    p.add_argument("--run-id")
    p.add_argument("--snapshot")
    args = p.parse_args(argv)
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    if args.rollback:
        print(json.dumps(await rollback(db, args.rollback), default=str))
        return 0
    the_plan = await plan(db, sectors=await _sectors())
    if not args.apply:
        _print(the_plan)
        return 0
    if not args.run_id or not args.snapshot:
        print("--apply needs --run-id and --snapshot")
        return 2
    print(json.dumps(await apply(db, the_plan, args.run_id, args.snapshot), default=str))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
