"""Snapshots of broker holdings syncs (`broker_sync_snapshots`).

`db.holdings` only ever holds the latest read of a broker account: each sync
replaces that account's rows. This collection is the history. Every
successful holdings sync of a native account (`hub_reads.sync_account`)
leaves one immutable document here — which broker and which login it was
read from, what started it, the rows as they were stored, and what the
duplicate check found.

A snapshot never holds a session token or the broker's client id in the
clear: the login is identified by `broker_account_id` and the masked
`broker_user_masked` only.

At most `MAX_PER_ACCOUNT` snapshots are kept per account; the oldest are
pruned after each write. Indexes are created at startup in `server.py`.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# What started the sync: the connect callback, the user, or the daily job.
TRIGGERS = ("connect", "manual", "daily")
MAX_PER_ACCOUNT = 90

# A stored holdings row as kept in a snapshot. Ids and timestamps of the live
# row are left out: the row they belong to is replaced by the next sync.
_HOLDING_FIELDS = (
    "name", "ticker", "isin", "asset_type", "quantity",
    "buy_price", "current_price", "sector", "source_id",
)
# A snapshot as listed — everything but the holdings and the owner's id.
_SUMMARY_FIELDS = (
    "snapshot_id", "synced_at", "trigger", "count",
    "total_value_rs", "total_invested_rs", "priced", "duplicates",
)


def build(
    account_doc: Dict[str, Any], rows: List[Dict[str, Any]], *,
    trigger: str, duplicates: Dict[str, Optional[int]], synced_at: str, broker_display: str,
) -> Dict[str, Any]:
    """The snapshot document for one sync. `rows` are the holdings rows as
    stored; only named fields are copied from them and from the account row,
    so nothing secret can ride along."""
    if trigger not in TRIGGERS:
        raise ValueError(f"Unknown sync trigger {trigger!r}")
    holdings = [{k: r[k] for k in _HOLDING_FIELDS if k in r} for r in rows]
    priced = [h for h in holdings if (h.get("current_price") or 0) > 0]
    return {
        "snapshot_id": f"bsnap_{uuid.uuid4().hex[:12]}",
        "user_id": account_doc["user_id"],
        "broker_account_id": account_doc["account_id"],
        "broker": account_doc.get("broker"),
        "broker_display": broker_display,
        "broker_user_masked": account_doc.get("broker_user_masked"),
        "trigger": trigger,
        "synced_at": synced_at,
        "count": len(holdings),
        # A row the broker gave no price for adds nothing to the value; it
        # is not valued at cost. `priced` says how many rows the value covers.
        "total_value_rs": round(float(sum(h["quantity"] * h["current_price"] for h in priced)), 2),
        "total_invested_rs": round(
            float(sum((h.get("quantity") or 0) * (h.get("buy_price") or 0) for h in holdings)), 2,
        ),
        "priced": len(priced),
        "holdings": holdings,
        "duplicates": dict(duplicates),
    }


async def record(
    db, account_doc: Dict[str, Any], rows: List[Dict[str, Any]], *,
    trigger: str, duplicates: Dict[str, Optional[int]], synced_at: str, broker_display: str,
) -> str:
    """Write the snapshot of one sync and return its `snapshot_id`. Raises
    when the write fails — the caller decides that this must not fail the
    sync. A failed prune is logged here: the snapshot itself is written."""
    snapshot = build(
        account_doc, rows, trigger=trigger, duplicates=duplicates,
        synced_at=synced_at, broker_display=broker_display,
    )
    await db.broker_sync_snapshots.insert_one(dict(snapshot))  # copy: Mongo adds `_id` to what it is given
    try:
        await prune(db, snapshot["user_id"], snapshot["broker_account_id"])
    except Exception:  # noqa: BLE001
        logger.exception(
            "broker sync snapshots: prune failed account=%s", snapshot["broker_account_id"],
        )
    return snapshot["snapshot_id"]


async def prune(db, user_id: str, account_id: str, keep: int = MAX_PER_ACCOUNT) -> int:
    """Delete all but the newest `keep` snapshots of one account. Returns how
    many were removed."""
    cursor = db.broker_sync_snapshots.find(
        {"user_id": user_id, "broker_account_id": account_id},
        {"_id": 0, "snapshot_id": 1},
    ).sort("synced_at", -1).skip(keep)
    stale = [d["snapshot_id"] for d in await cursor.to_list(length=None)]
    if not stale:
        return 0
    res = await db.broker_sync_snapshots.delete_many({"snapshot_id": {"$in": stale}})
    return res.deleted_count


async def list_for_account(
    db, user_id: str, account_id: str, limit: int = 30,
) -> List[Dict[str, Any]]:
    """One account's snapshots, newest first, without the holdings rows."""
    cursor = db.broker_sync_snapshots.find(
        {"user_id": user_id, "broker_account_id": account_id},
        {"_id": 0, **{field: 1 for field in _SUMMARY_FIELDS}},
    ).sort("synced_at", -1).limit(limit)
    return await cursor.to_list(length=limit)


async def get_for_owner(db, user_id: str, snapshot_id: str) -> Optional[Dict[str, Any]]:
    """The full snapshot, holdings included — only for the user it belongs to."""
    return await db.broker_sync_snapshots.find_one(
        {"snapshot_id": snapshot_id, "user_id": user_id}, {"_id": 0, "user_id": 0},
    )


async def delete_for_account(db, user_id: str, account_id: str) -> int:
    """Remove every snapshot of one account (the account was disconnected)."""
    res = await db.broker_sync_snapshots.delete_many(
        {"user_id": user_id, "broker_account_id": account_id},
    )
    return res.deleted_count


async def delete_for_user(db, user_id: str) -> int:
    """Remove every snapshot a user owns (account erasure)."""
    res = await db.broker_sync_snapshots.delete_many({"user_id": user_id})
    return res.deleted_count
