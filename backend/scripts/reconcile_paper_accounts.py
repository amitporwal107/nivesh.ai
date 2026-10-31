#!/usr/bin/env python3
"""reconcile_paper_accounts.py — compare every paper account with its ledger and its trades, and correct it with
ADDITIVE compensating entries (services/paper_reconcile.py). Nothing is ever deleted or overwritten.

Usage (inside the backend container):
    python -m scripts.reconcile_paper_accounts                      # = --dry-run: the report, reads only
    python -m scripts.reconcile_paper_accounts --dry-run --json     # the plan as JSON (user ids hashed)
    python -m scripts.reconcile_paper_accounts --dry-run --decide <trade-id-prefix>:<issue>=<option>   # preview a decision
    python -m scripts.reconcile_paper_accounts --check              # invariants only (the daily check)
    python -m scripts.reconcile_paper_accounts --apply --run-id <id> --snapshot <label> [--decide ...]
    python -m scripts.reconcile_paper_accounts --revert <run-id> --snapshot <label> [--run-id <id>]

--apply writes only the entries the dry run lists as "proposed", plus the option of each --decide. Each entry has an
idempotency key per (issue, trade): a second --apply writes nothing. --revert adds the opposite entry for each entry
the run wrote. --snapshot names the pre-change snapshot (it is recorded on every entry); take it first.

Exit codes: 0 done / nothing wrong · 1 failed · 2 --check found a mismatch · 3 --apply refused (a --decide did not match)
Reads Mongo through the backend's own settings; prints no setting, token or user id (users appear as 8-char hashes).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

log = logging.getLogger("reconcile_paper_accounts")

_RUN_ID = re.compile(r"^[A-Za-z0-9._:-]{3,64}$")
_DECIDE = re.compile(r"^([0-9a-fA-F-]{8,36}):([a-z_]+)=([a-z_]+)$")


def _money(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:,.2f}"


def _signed(x: float) -> str:
    return f"{'+' if x > 0 else '−' if x < 0 else '±'}{abs(x):,.2f}"


def scrub(obj: Any) -> Any:
    """Drop raw user ids from anything printed (the hashed `user` stays)."""
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items() if k != "user_id"}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    if isinstance(obj, set):
        return sorted(obj)
    return obj


async def strategy_evidence(trade: Dict[str, Any]) -> List[str]:
    """For a structure closed with no P&L: each leg's marks around the close, from the data platform (reads only)."""
    from services import desk_strategy_trades as strat
    from services import desk_trading as svc

    lines: List[str] = []
    try:
        closed_day = svc.ist_date(trade["closed_at"])
        start = svc.ist_date(trade["opened_at"]) - timedelta(days=7)
        for i, leg in enumerate(trade.get("legs") or []):
            rows = await strat.fetch_contract_rows(trade.get("underlying") or trade["symbol"], leg, start)
            by_day = sorted(rows, key=lambda r: str(r.get("as_of_date")))
            before = [r for r in by_day if str(r.get("as_of_date"))[:10] <= closed_day.isoformat()]
            after = [r for r in by_day if str(r.get("as_of_date"))[:10] > closed_day.isoformat()]
            name = f"leg {i + 1} {leg.get('side')} {leg.get('strike')} {leg.get('option_type') or leg.get('kind')} {leg.get('expiry')}"
            last = before[-1] if before else None
            nxt = after[0] if after else None
            lines.append(
                f"{name}: entry {leg.get('entry_price')}; last bhavcopy row on or before the close date "
                f"({closed_day.isoformat()} IST): " + (f"{last.get('as_of_date')} close {last.get('close_price')} "
                                                      f"settle {last.get('settle_price')}" if last else "none")
                + "; first row after it: " + (f"{nxt.get('as_of_date')} close {nxt.get('close_price')} settle "
                                              f"{nxt.get('settle_price')} (after the close: look-ahead, not offered)"
                                              if nxt else "none"))
    except Exception as exc:  # noqa: BLE001 — evidence is extra; say it could not be read and carry on
        lines.append(f"marks could not be read from the data platform: {type(exc).__name__}: {str(exc)[:120]}")
    return lines


def print_plan(plan: Dict[str, Any], evidence: Dict[str, List[str]], *, mode: str) -> None:
    from services import paper_reconcile as rec

    c = plan["counts"]
    print(f"Paper-account reconciliation — {mode}   plan {plan['plan_version']}")
    print(f"Read: {c['trades']} trades, {c['ledger_rows']} ledger rows, {c['accounts']} accounts. "
          f"Issues: {c['issues']} {c['by_resolution']}. Entries to write: {c['entries']}.")
    for s in plan["accounts"]:
        print(f"\nAccount u={s['user']}")
        for label, inv in (("now", s["before"]), ("after the entries", s["after_proposed"])):
            if not inv.get("account"):
                print(f"  {label}: NO ACCOUNT ({inv['open_trades']} open trades)")
                continue
            print(f"  {label}: cash {_money(inv['cash_rs'])}  blocked {_money(inv['blocked_rs'])}  "
                  f"available {_money(inv['available_rs'])}  (start {_money(inv['starting_capital_rs'])})")
            print(f"    I1 cash − start {_money(inv['I1_cash_minus_start'])} = ledger cash {_money(inv['I1_ledger_cash'])}"
                  f"  {'OK' if inv['I1_ok'] else 'MISMATCH'}")
            print(f"    I2 blocked {_money(inv['blocked_rs'])} = ledger blocked {_money(inv['I2_ledger_blocked'])}"
                  f"  {'OK' if inv['I2_ok'] else 'MISMATCH'}")
            print(f"    I3 blocked {_money(inv['blocked_rs'])} = Σ open reservations {_money(inv['I3_open_reserved'])}"
                  f"  {'OK' if inv['I3_ok'] else 'MISMATCH'}")
            print(f"    I4 open trades without a reservation: {len(inv['I4_unreserved_open_trades'])}"
                  f"  {'OK' if inv['I4_ok'] else 'MISMATCH ' + ', '.join(inv['I4_unreserved_open_trades'])}")
    order = {"proposed": 0, "decided": 1, rec.DECISION: 2, rec.REVIEW: 3, rec.RESOLVED: 4}
    print("\nIssues")
    for i in sorted(plan["issues"], key=lambda x: (order.get(x["resolution"], 9), x["code"], str(x["trade_id"]))):
        ev = i["evidence"]
        print(f"\n  [{i['resolution']}] {i['code']}  {i['symbol'] or ''}  trade {i['trade_id']}  "
              f"({i['status'] or '—'}, u={i['user']})")
        if ev.get("why"):
            print(f"    why: {ev['why']}")
        facts = {k: v for k, v in ev.items() if k not in ("why", "trades") and v not in (None, [], "")}
        if facts:
            print("    evidence: " + "; ".join(f"{k}={v}" for k, v in facts.items()))
        for t in ev.get("trades") or []:
            print(f"      - {t['trade_id']}  {t['status']}  opened {t['opened_at']}  net {t['net_pnl_rs']}  "
                  f"reserved {t['paper_reserved_rs']}")
        for line in evidence.get(i["issue_id"], []):
            print(f"    marks: {line}")
        for e in i["entries"]:
            stamp = (f"; stamps {e['stamp']['field']} {e['stamp']['before']} → {e['stamp']['after']} on the trade"
                     if e.get("stamp") else "")
            print(f"    entry {e['key']}: cash {_signed(e['cash_delta_rs'])}  blocked {_signed(e['blocked_delta_rs'])}"
                  f"  reason {e['reason_code']}{stamp}")
        for o in i["options"]:
            print(f"    option {o['option']}: cash {_signed(o['cash_delta_rs'])} — {o['text']}")
        if i["resolution"] == rec.DECISION and i["options"]:
            print(f"    decide with: --decide {str(i['trade_id'])[:8]}:{i['code']}="
                  f"<{'|'.join(o['option'] for o in i['options'])}>")
    for err in plan["decision_errors"]:
        print(f"\nDECISION NOT APPLIED: {err}")


async def main_async(args: argparse.Namespace) -> int:
    from deps import db
    from services import paper_reconcile as rec

    decisions: Dict[str, str] = {}
    for spec in args.decide or []:
        m = _DECIDE.match(spec)
        if not m:
            log.error("--decide %r: expected <trade-id-prefix (8+ hex)>:<issue code>=<option>", spec)
            return 3
        decisions[f"{m.group(1).lower()}:{m.group(2)}"] = m.group(3)

    if args.revert:
        report = await rec.revert(db, args.revert, args.run_id or f"revert-{args.revert}", snapshot=args.snapshot)
        print(json.dumps(scrub(report), indent=1, default=str))
        after = rec.check(await rec.load(db))
        print(json.dumps(scrub(after), indent=1, default=str))
        return 0

    data = await rec.load(db)
    if args.check:
        rows = rec.check(data)
        print(json.dumps(scrub(rows), indent=1, default=str))
        return 0 if all(r["ok"] for r in rows) else 2

    plan = rec.build_plan(data["accounts"], data["ledger"], data["trades"], decisions)
    evidence: Dict[str, List[str]] = {}
    if not args.no_evidence:
        by_id = {t["_id"]: t for t in data["trades"]}
        for i in plan["issues"]:
            t = by_id.get(i["trade_id"])
            if i["code"] == rec.PNL_MISSING and t and t.get("kind") == "strategy":
                evidence[i["issue_id"]] = await strategy_evidence(t)

    if not args.apply:
        if args.json:
            print(json.dumps(scrub({**plan, "marks": evidence}), indent=1, default=str))
        else:
            print_plan(plan, evidence, mode="DRY RUN (reads only; nothing written)")
        return 0

    if plan["decision_errors"]:
        print_plan(plan, evidence, mode="APPLY REFUSED")
        return 3
    print_plan(plan, evidence, mode=f"APPLY run {args.run_id}")
    report = await rec.apply(db, plan, args.run_id, snapshot=args.snapshot)
    print("\nWritten:")
    print(json.dumps(scrub(report), indent=1, default=str))
    after = rec.check(await rec.load(db))
    print("\nInvariants after:")
    print(json.dumps(scrub(after), indent=1, default=str))
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    p = argparse.ArgumentParser(description="Reconcile paper accounts with their ledger and trades (additive entries only)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Report only (the default)")
    mode.add_argument("--check", action="store_true", help="Invariants only; exit 2 on a mismatch")
    mode.add_argument("--apply", action="store_true", help="Write the proposed entries (needs --run-id and --snapshot)")
    mode.add_argument("--revert", metavar="RUN_ID", help="Add reversing entries for everything RUN_ID wrote")
    p.add_argument("--run-id", help="Id stamped on every entry this run writes")
    p.add_argument("--snapshot", help="Label of the pre-change snapshot (recorded on every entry)")
    p.add_argument("--decide", action="append", metavar="TRADE:ISSUE=OPTION",
                   help="Resolve a needs_owner_decision issue with one of its options (repeatable)")
    p.add_argument("--json", action="store_true", help="Dry run: print the plan as JSON")
    p.add_argument("--no-evidence", action="store_true", help="Do not read F&O marks from the data platform")
    args = p.parse_args()
    if args.apply and not (args.run_id and _RUN_ID.match(args.run_id)):
        p.error("--apply needs --run-id (3-64 of A-Z a-z 0-9 . _ : -)")
    if args.run_id and not _RUN_ID.match(args.run_id):
        p.error("--run-id: 3-64 of A-Z a-z 0-9 . _ : -")
    if (args.apply or args.revert) and not args.snapshot:
        p.error("--apply / --revert need --snapshot <label>: take the snapshot first (see the approval pack)")
    try:
        return asyncio.run(main_async(args))
    except Exception as exc:  # noqa: BLE001 — the database failed; cron / the operator needs a non-zero exit
        log.exception("reconciliation failed: %r", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
