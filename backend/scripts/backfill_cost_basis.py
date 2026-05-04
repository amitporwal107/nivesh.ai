"""One-off backfill: walk a user's stored CAS snapshots and recompute
cost basis for direct equities / SGBs / demat MFs that were polluted by
the old "market_price as buy_price" fallback.

Usage:
  python -m backend.scripts.backfill_cost_basis <user_id>
  python -m backend.scripts.backfill_cost_basis --email priyankamantri@gmail.com
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

# Make the backend package importable when run as a top-level script.
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from deps import db  # noqa: E402
from services.cost_basis_from_snapshots import derive_cost_basis_for_holdings  # noqa: E402


async def _resolve_user_id(arg_user: str | None, arg_email: str | None) -> str:
    if arg_user:
        return arg_user
    if not arg_email:
        raise SystemExit("must pass either user_id or --email")
    user = await db.users.find_one(
        {"email": arg_email.strip().lower()}, {"_id": 0, "user_id": 1}
    )
    if not user:
        # Try a regex fallback for case-insensitive mismatches.
        import re
        user = await db.users.find_one(
            {"email": re.compile(f"^{re.escape(arg_email)}$", re.IGNORECASE)},
            {"_id": 0, "user_id": 1},
        )
    if not user:
        raise SystemExit(f"no user found for email {arg_email}")
    return user["user_id"]


async def backfill(user_id: str) -> None:
    print(f"=== backfilling cost basis for {user_id} ===")
    snaps = await db.cas_parsed_responses.count_documents({"user_id": user_id})
    holdings_count = await db.holdings.count_documents({"user_id": user_id})
    print(f"  cas snapshots: {snaps}, current holdings: {holdings_count}")
    if snaps == 0 or holdings_count == 0:
        print("  nothing to do")
        return

    holdings = [h async for h in db.holdings.find({"user_id": user_id}, {"_id": 0})]

    # Tag MF folio rows so the derivation skips them. Heuristic: a MF
    # holding with a folio_number was parsed from the folio table; one
    # without was parsed from the demat MF table.
    for h in holdings:
        if (h.get("asset_type") or "").lower() in ("mutual_fund", "mf"):
            if h.get("folio_number"):
                h.setdefault("parsed_by", "claude_folio")
            else:
                h.setdefault("parsed_by", "claude_demat")

    patched = await derive_cost_basis_for_holdings(user_id, holdings)
    unknown = sum(1 for h in holdings if h.get("cost_basis_source") == "unknown")
    print(f"  patched {patched} holdings · marked {unknown} as cost-basis-unknown")

    # Write back to db.holdings
    bulk = 0
    for h in holdings:
        if h.get("cost_basis_source") not in ("snapshot_delta", "unknown", "fully_sold"):
            continue
        update = {
            "buy_price": float(h.get("buy_price") or 0),
            "cost_basis_source": h["cost_basis_source"],
        }
        await db.holdings.update_one(
            {"user_id": user_id, "holding_id": h["holding_id"]},
            {"$set": update},
        )
        bulk += 1
    print(f"  wrote {bulk} updates to db.holdings")

    # Sample some holdings before/after for verification
    print("  sample updated holdings:")
    sample_isins = ["INE524A01029", "INE066P01011", "INE002A01018", "INE079A01024"]
    for isin in sample_isins:
        h = await db.holdings.find_one(
            {"user_id": user_id, "ticker": isin},
            {"_id": 0, "name": 1, "quantity": 1, "buy_price": 1,
             "current_price": 1, "cost_basis_source": 1},
        )
        if h:
            qty = float(h.get("quantity") or 0)
            bp = float(h.get("buy_price") or 0)
            cp = float(h.get("current_price") or 0)
            ret = ((cp - bp) / bp * 100) if bp > 0 else None
            ret_s = f"{ret:+.1f}%" if ret is not None else "—"
            print(
                f"    {h['name'][:32]:<32} | qty {qty:g} | bp ₹{bp:g} | "
                f"cp ₹{cp:g} | P&L {ret_s} | src={h.get('cost_basis_source')}"
            )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("user_id", nargs="?", default=None)
    ap.add_argument("--email", default=None)
    args = ap.parse_args()

    async def _run():
        uid = await _resolve_user_id(args.user_id, args.email)
        await backfill(uid)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
