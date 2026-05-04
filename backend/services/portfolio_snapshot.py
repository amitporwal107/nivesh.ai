"""Portfolio Snapshot Engine — immutable daily portfolio state.

A snapshot captures:
  - Total value + invested + return
  - Asset allocation %
  - Per-asset-class counts + values
  - Top-10 holdings by value
  - V3 Portfolio Health scores (overall + components + grade)
  - Source / trigger metadata (eod_cron | cas_upload | manual)

One snapshot per (user_id, YYYY-MM-DD). Writing the same date twice
upserts — the LATER trigger wins (e.g. a post-CAS snapshot overwrites
the morning's EOD snapshot on the same day, which is the desired
behaviour because it reflects the most recent portfolio state).

Used by:
  - /api/portfolio/snapshots  (list available dates)
  - /api/portfolio/snapshot   (fetch one snapshot)
  - /api/portfolio/compare    (diff two snapshots)
  - APScheduler daily cron 23:30 IST
  - helpers.parsing.save_holdings  (post-CAS trigger)
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone, date
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from deps import db

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")


def _today_ist_str() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


def _asset_bucket(asset_type: Optional[str]) -> str:
    """Map the heterogeneous asset_type values in holdings to the 4
    canonical buckets we track allocation against."""
    t = (asset_type or "").lower()
    if t in ("equity", "stock"):
        return "equity"
    if t in ("mutual_fund", "etf"):
        # MF allocation is split further downstream via V3 category,
        # but at the snapshot level MFs count as "mf" — the health
        # engine already carries the fine-grained equity/debt split.
        return "mf"
    if t in ("gold", "sgb", "silver"):
        return "gold"
    return "other"


async def build_snapshot_payload(user_id: str, trigger: str = "eod_cron") -> Dict[str, Any]:
    """Compute (but don't persist) a snapshot for a user. Pure read —
    useful for unit tests, /snapshot/preview admin endpoint, and the
    real insert path."""
    from services import portfolio_health as _ph

    # 1. All holdings
    holdings: List[Dict[str, Any]] = await db.holdings.find(
        {"user_id": user_id}, {"_id": 0},
    ).to_list(2000)

    total_value = 0.0
    total_invested = 0.0
    by_bucket: Dict[str, Dict[str, float]] = {}
    # Track per-asset-class counts + values for the holdings_summary
    by_asset_type: Dict[str, Dict[str, float]] = {}

    for h in holdings:
        qty = float(h.get("quantity") or 0)
        cmp_ = float(h.get("current_price") or h.get("buy_price") or 0)
        bp = float(h.get("buy_price") or 0)
        value = qty * cmp_
        invested = qty * bp
        total_value += value
        total_invested += invested
        bucket = _asset_bucket(h.get("asset_type"))
        b = by_bucket.setdefault(bucket, {"value": 0.0, "count": 0})
        b["value"] += value
        b["count"] += 1
        at = (h.get("asset_type") or "unknown").lower()
        a = by_asset_type.setdefault(at, {"value": 0.0, "count": 0})
        a["value"] += value
        a["count"] += 1

    # 2. Allocation percentages (of total_value)
    allocation: Dict[str, float] = {}
    if total_value > 0:
        for bucket, d in by_bucket.items():
            allocation[bucket] = round(d["value"] / total_value * 100, 2)

    # 3. Top 10 holdings
    holdings_with_val = [
        {
            "name": h.get("name") or h.get("asset_name") or h.get("scheme_name") or "Unknown",
            "asset_type": (h.get("asset_type") or "").lower(),
            "value": float(h.get("quantity") or 0) * float(h.get("current_price") or h.get("buy_price") or 0),
            "weight_pct": 0.0,
        }
        for h in holdings
    ]
    for row in holdings_with_val:
        if total_value > 0:
            row["weight_pct"] = round(row["value"] / total_value * 100, 2)
    top_holdings = sorted(holdings_with_val, key=lambda r: r["value"], reverse=True)[:10]

    # 4. V3 Portfolio Health — reuse live service (cheap via existing caches)
    scores: Dict[str, Any] = {}
    grade = None
    health_overall: Optional[float] = None
    try:
        hr = await _ph.build_portfolio_health(user_id)
        if hr and hr.health_score is not None:
            health_overall = float(hr.health_score)
            grade = hr.grade
            scores = {
                "health": round(health_overall, 2),
                **{
                    c.name: round(float(c.score), 2)
                    for c in (hr.components or {}).values()
                },
            }
    except Exception:  # noqa: BLE001
        logger.warning("snapshot: health compute failed for %s", user_id, exc_info=True)

    return_pct = (
        round((total_value - total_invested) / total_invested * 100, 2)
        if total_invested > 0 else None
    )

    return {
        "user_id": user_id,
        "snapshot_date": _today_ist_str(),
        "trigger": trigger,
        "total_value": round(total_value, 2),
        "total_invested": round(total_invested, 2),
        "return_pct": return_pct,
        "allocation": allocation,
        "holdings_summary": [
            {"asset_type": k, "count": int(v["count"]), "value": round(v["value"], 2)}
            for k, v in sorted(by_asset_type.items())
        ],
        "holdings_count": len(holdings),
        "top_holdings": top_holdings,
        "scores": scores,
        "health_score": round(health_overall, 2) if health_overall is not None else None,
        "grade": grade,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


async def persist_snapshot(user_id: str, trigger: str = "eod_cron") -> Dict[str, Any]:
    """Compute + upsert snapshot for (user_id, today). Same date
    overwrites (later trigger wins). Returns the stored payload."""
    payload = await build_snapshot_payload(user_id, trigger=trigger)
    if payload["total_value"] == 0 and payload["holdings_count"] == 0:
        logger.debug("snapshot: skipping empty portfolio for %s", user_id)
        return payload
    await db.portfolio_snapshots.update_one(
        {"user_id": user_id, "snapshot_date": payload["snapshot_date"]},
        {"$set": payload},
        upsert=True,
    )
    return payload


async def list_snapshot_dates(user_id: str, limit: int = 365) -> List[str]:
    """Return available snapshot dates for a user, newest first."""
    cursor = db.portfolio_snapshots.find(
        {"user_id": user_id}, {"_id": 0, "snapshot_date": 1},
    ).sort("snapshot_date", -1).limit(limit)
    return [doc["snapshot_date"] async for doc in cursor]


async def get_snapshot(user_id: str, snapshot_date: str) -> Optional[Dict[str, Any]]:
    return await db.portfolio_snapshots.find_one(
        {"user_id": user_id, "snapshot_date": snapshot_date},
        {"_id": 0},
    )


async def get_latest_snapshot(user_id: str) -> Optional[Dict[str, Any]]:
    return await db.portfolio_snapshots.find_one(
        {"user_id": user_id}, {"_id": 0},
        sort=[("snapshot_date", -1)],
    )


async def get_snapshot_on_or_before(user_id: str, snapshot_date: str) -> Optional[Dict[str, Any]]:
    """Fetch the snapshot for the given date, or the closest earlier
    one. Useful for timeline scrubbing on days where no snapshot
    was taken (weekends, holidays)."""
    return await db.portfolio_snapshots.find_one(
        {"user_id": user_id, "snapshot_date": {"$lte": snapshot_date}},
        {"_id": 0},
        sort=[("snapshot_date", -1)],
    )


async def build_trend_series(
    user_id: str, days: int = 30,
) -> List[Dict[str, Any]]:
    """Light-weight time series for sparklines — one row per snapshot
    day, newest last, only the fields sparklines need.

    Filters by `days` only if the date window catches at least 2 snapshots.
    Otherwise (e.g. monthly CAS snapshots viewed with `days=30`) falls back
    to the last 30 snapshots regardless of date so the sparkline still
    shows a meaningful series. The frontend's "30d" label is now a soft
    indicator — what matters is the trend, not the literal window.
    """
    from datetime import timedelta
    cutoff = (datetime.now(IST).date() - timedelta(days=days)).strftime("%Y-%m-%d")
    proj = {
        "_id": 0, "snapshot_date": 1, "total_value": 1, "health_score": 1,
        "allocation": 1, "return_pct": 1, "scores": 1,
    }
    cursor = db.portfolio_snapshots.find(
        {"user_id": user_id, "snapshot_date": {"$gte": cutoff}},
        proj,
    ).sort("snapshot_date", 1)
    series = [doc async for doc in cursor]
    if len(series) >= 2:
        return series
    # Fallback: last 30 snapshots regardless of date window.
    cursor = db.portfolio_snapshots.find(
        {"user_id": user_id}, proj,
    ).sort("snapshot_date", -1).limit(30)
    series = [doc async for doc in cursor]
    series.reverse()  # newest last for sparklines
    return series


async def backfill_snapshot_health(user_id: str, *, only_missing: bool = True) -> Dict[str, Any]:
    """Compute and persist Portfolio Health for every historical snapshot
    of `user_id` so the Time Machine deltas (and the trend sparkline)
    have something to plot. Old snapshots only ever got health computed
    when they were active — historical scores stay null forever
    otherwise.

    Strategy:
      1. Read current `cas_view_state.current_snapshot_date` so we can
         restore the live holdings table afterwards (the user's "current"
         view is unchanged when this returns).
      2. For each snapshot (oldest first):
           a. Skip if `health_score` already set and `only_missing=True`.
           b. Mount its stored `holdings` into `db.holdings` for the user.
           c. Run `build_portfolio_health(user_id)` against those holdings.
           d. Persist `health_score / grade / scores` on the snapshot doc
              and warm both Redis and `health_full` for the snapshot.
      3. Re-mount the original active snapshot's holdings + state.

    Best-effort. Errors on a single snapshot are logged and don't
    abort the loop. Returns a summary dict for the caller.
    """
    from services import portfolio_health as _ph
    user_doc = await db.users.find_one(
        {"user_id": user_id}, {"_id": 0, "cas_view_state": 1},
    )
    cas_state = (user_doc or {}).get("cas_view_state") or {}
    original_active = cas_state.get("current_snapshot_date")

    snaps: List[Dict[str, Any]] = await db.portfolio_snapshots.find(
        {"user_id": user_id},
        {"_id": 0, "snapshot_date": 1, "holdings": 1, "health_score": 1},
    ).sort("snapshot_date", 1).to_list(500)

    processed = skipped = failed = 0
    for snap in snaps:
        snap_date = snap.get("snapshot_date")
        if not snap_date:
            continue
        if only_missing and snap.get("health_score") is not None:
            skipped += 1
            continue
        snap_holdings = snap.get("holdings") or []
        if not snap_holdings:
            skipped += 1
            continue
        try:
            # Mount this snapshot's holdings as the user's live holdings.
            # Insert-then-delete (instead of delete-then-insert) so concurrent
            # readers — and the daily eod_cron snapshot job — never observe
            # an empty `db.holdings`. We tag the new rows with
            # `_backfill_user`, drop everything else for this user, then
            # strip the marker.
            stamped = [
                {**{k: v for k, v in h.items() if k != "_id"},
                 "user_id": user_id, "_backfill_user": user_id}
                for h in snap_holdings
            ]
            if stamped:
                await db.holdings.insert_many(stamped)
            await db.holdings.delete_many({
                "user_id": user_id, "_backfill_user": {"$ne": user_id},
            })
            await db.holdings.update_many(
                {"user_id": user_id, "_backfill_user": user_id},
                {"$unset": {"_backfill_user": ""}},
            )
            await db.users.update_one(
                {"user_id": user_id},
                {"$set": {
                    "cas_view_state.current_snapshot_date": snap_date,
                    "cas_view_state.last_updated": _now_iso(),
                }},
                upsert=True,
            )
            hr = await _ph.build_portfolio_health(user_id, force_refresh_stocks=True)
            if hr and hr.health_score is not None:
                scores = {
                    "health": round(float(hr.health_score), 2),
                    **{c.name: round(float(c.score), 2) for c in (hr.components or {}).values()},
                }
                await db.portfolio_snapshots.update_one(
                    {"user_id": user_id, "snapshot_date": snap_date},
                    {"$set": {
                        "scores": scores,
                        "health_score": round(float(hr.health_score), 2),
                        "grade": hr.grade,
                        "summary": hr.summary,
                    }},
                )
                await _ph.cache_health_for_snapshot(user_id, snap_date, hr)
                processed += 1
            else:
                failed += 1
        except Exception:  # noqa: BLE001
            logger.warning(
                "backfill_snapshot_health: %s/%s failed",
                user_id, snap_date, exc_info=True,
            )
            failed += 1

    # ── Restore the original active snapshot ─────────────────────────
    if original_active:
        original_snap = await db.portfolio_snapshots.find_one(
            {"user_id": user_id, "snapshot_date": original_active},
            {"_id": 0, "holdings": 1},
        )
        if original_snap and original_snap.get("holdings"):
            # Same insert-then-delete swap as the per-iteration code above.
            stamped = [
                {**{k: v for k, v in h.items() if k != "_id"},
                 "user_id": user_id, "_backfill_user": user_id}
                for h in original_snap["holdings"]
            ]
            if stamped:
                await db.holdings.insert_many(stamped)
            await db.holdings.delete_many({
                "user_id": user_id, "_backfill_user": {"$ne": user_id},
            })
            await db.holdings.update_many(
                {"user_id": user_id, "_backfill_user": user_id},
                {"$unset": {"_backfill_user": ""}},
            )
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {
                "cas_view_state.current_snapshot_date": original_active,
                "cas_view_state.last_updated": _now_iso(),
            }},
            upsert=True,
        )

    return {
        "user_id": user_id,
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "restored_to": original_active,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def diff_snapshots(new_snap: Dict[str, Any], old_snap: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute a UI-ready diff between two snapshots. `old_snap=None`
    means "first snapshot" — we emit deltas as null."""
    out: Dict[str, Any] = {
        "from_date": (old_snap or {}).get("snapshot_date"),
        "to_date": (new_snap or {}).get("snapshot_date"),
    }
    if not new_snap:
        return out

    def _delta(a, b):
        if a is None or b is None:
            return None
        return round(a - b, 2)

    def _pct_change(a, b):
        if a is None or b is None or b == 0:
            return None
        return round((a - b) / b * 100, 2)

    old_val = (old_snap or {}).get("total_value")
    new_val = new_snap.get("total_value")
    out["value_delta"] = _delta(new_val, old_val)
    out["value_pct_change"] = _pct_change(new_val, old_val)

    old_health = (old_snap or {}).get("health_score")
    new_health = new_snap.get("health_score")
    out["health_delta"] = _delta(new_health, old_health)

    # Allocation delta per bucket (only keys present in either side)
    old_alloc = (old_snap or {}).get("allocation") or {}
    new_alloc = new_snap.get("allocation") or {}
    alloc_delta = {}
    for k in set(list(old_alloc.keys()) + list(new_alloc.keys())):
        alloc_delta[k] = round((new_alloc.get(k) or 0) - (old_alloc.get(k) or 0), 2)
    out["allocation_delta_pp"] = alloc_delta

    # Holdings-level added / removed (by name — cheap + good enough for UI)
    old_names = {(h.get("name") or "").strip(): h for h in (old_snap or {}).get("top_holdings") or []}
    new_names = {(h.get("name") or "").strip(): h for h in new_snap.get("top_holdings") or []}
    added = [h for n, h in new_names.items() if n and n not in old_names]
    removed = [h for n, h in old_names.items() if n and n not in new_names]
    out["holdings_added"] = added[:10]
    out["holdings_removed"] = removed[:10]

    return out


async def ensure_indexes() -> None:
    """One-time index creation. Safe to call on every boot."""
    await db.portfolio_snapshots.create_index(
        [("user_id", 1), ("snapshot_date", -1)], unique=True, name="user_date_uniq",
    )
    await db.portfolio_snapshots.create_index(
        [("snapshot_date", -1)], name="date_desc",
    )


async def run_eod_snapshot_job() -> Dict[str, Any]:
    """Daily EOD cron — snapshots every user with holdings. Runs
    23:30 IST (after the V3 rescore at 22:45). Returns summary stats."""
    cursor = db.holdings.aggregate([
        {"$group": {"_id": "$user_id", "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 0}}},
    ])
    user_ids = [doc["_id"] async for doc in cursor if doc.get("_id")]
    ok = 0
    failed = 0
    for uid in user_ids:
        try:
            await persist_snapshot(uid, trigger="eod_cron")
            ok += 1
        except Exception:  # noqa: BLE001
            logger.exception("eod snapshot failed for %s", uid)
            failed += 1
    logger.info("EOD snapshot job: %d ok, %d failed, %d users", ok, failed, len(user_ids))
    return {"ok": ok, "failed": failed, "total": len(user_ids), "date": _today_ist_str()}
