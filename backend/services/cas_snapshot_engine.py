"""CAS Snapshot Engine — store one *immutable* snapshot per CAS PDF
upload, keyed by `statement_period_end`. The snapshot carries the full
holdings list, transactions, and detected SIPs — everything needed to
"rewind" the Client 360 to that month-end.

Key behaviours:
  - Default Client 360 view = the LATEST snapshot (we mirror its
    holdings into `db.holdings` so existing pages keep working).
  - When the MFD clicks an older snapshot, we replace `db.holdings`
    with that snapshot's holdings. The `current_snapshot_date` field
    on the user (in `users.cas_view_state`) tracks which snapshot is
    currently mounted.
  - All historical snapshots stay in `portfolio_snapshots` indefinitely,
    so performance graphs, SIP bars, and date-range transaction
    queries can read them without touching the live holdings table.

Schema additions (vs. the existing v1 snapshot):
  holdings              : List[dict]   # full holdings array (40+ rows)
  transactions          : List[dict]   # extracted from CAS folios
  sips_detected         : List[dict]   # cas_transactions.detect_sip_patterns
  cas_file_id           : str          # link to client_cas_invites.processed_files.file_id
  cas_filename          : str
  source                : "cas_upload" | "manual" | "eod_cron"
  statement_period_start: str (ISO)
  statement_period_end  : str (ISO)    # = snapshot_date when CAS-derived
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, date
from typing import Any, Dict, List, Optional

from deps import db
from services import portfolio_snapshot as _v1_snap
from services.cas_period_detector import detect_statement_period

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _allocation_from_holdings(holdings: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_bucket: Dict[str, Dict[str, float]] = {}
    by_asset_type: Dict[str, Dict[str, float]] = {}
    total_value = 0.0
    total_invested = 0.0
    for h in holdings:
        qty = float(h.get("quantity") or 0)
        cmp_ = float(h.get("current_price") or h.get("buy_price") or 0)
        bp = float(h.get("buy_price") or 0)
        value = qty * cmp_
        invested = qty * bp
        total_value += value
        total_invested += invested
        bucket = _bucket(h.get("asset_type"))
        b = by_bucket.setdefault(bucket, {"value": 0.0, "count": 0})
        b["value"] += value
        b["count"] += 1
        at = (h.get("asset_type") or "unknown").lower()
        a = by_asset_type.setdefault(at, {"value": 0.0, "count": 0})
        a["value"] += value
        a["count"] += 1
    allocation: Dict[str, float] = {}
    if total_value > 0:
        for bucket, d in by_bucket.items():
            allocation[bucket] = round(d["value"] / total_value * 100, 2)
    holdings_summary = [
        {"asset_type": k, "count": int(v["count"]), "value": round(v["value"], 2)}
        for k, v in sorted(by_asset_type.items())
    ]
    holdings_with_val = [
        {
            "name": h.get("name") or h.get("scheme_name") or "Unknown",
            "asset_type": (h.get("asset_type") or "").lower(),
            "value": float(h.get("quantity") or 0) * float(h.get("current_price") or h.get("buy_price") or 0),
            "weight_pct": (
                round(float(h.get("quantity") or 0) * float(h.get("current_price") or h.get("buy_price") or 0) / total_value * 100, 2)
                if total_value > 0 else 0.0
            ),
        }
        for h in holdings
    ]
    top_holdings = sorted(holdings_with_val, key=lambda r: r["value"], reverse=True)[:10]
    return {
        "total_value": round(total_value, 2),
        "total_invested": round(total_invested, 2),
        "return_pct": (
            round((total_value - total_invested) / total_invested * 100, 2)
            if total_invested > 0 else None
        ),
        "allocation": allocation,
        "holdings_summary": holdings_summary,
        "top_holdings": top_holdings,
    }


def _bucket(asset_type: Optional[str]) -> str:
    t = (asset_type or "").lower()
    if t in ("equity", "stock"):
        return "equity"
    if t in ("mutual_fund", "etf"):
        return "mf"
    if t in ("gold", "sgb", "silver"):
        return "gold"
    return "other"


async def get_latest_snapshot_date(user_id: str) -> Optional[str]:
    doc = await db.portfolio_snapshots.find_one(
        {"user_id": user_id}, {"_id": 0, "snapshot_date": 1},
        sort=[("snapshot_date", -1)],
    )
    return doc.get("snapshot_date") if doc else None


async def write_holdings_table(user_id: str, holdings: List[Dict[str, Any]],
                                source: str = "snapshot_load") -> int:
    """Replace the live `holdings` table for `user_id` with the given
    list. This is what makes a snapshot the "current" view in Client 360.
    """
    await db.holdings.delete_many({"user_id": user_id})
    inserted = 0
    for h in holdings:
        doc = {
            "holding_id": h.get("holding_id") or f"hold_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "portfolio_id": h.get("portfolio_id", ""),
            "name": h.get("name", "Unknown"),
            "ticker": h.get("ticker", ""),
            "asset_type": (h.get("asset_type") or "equity"),
            "quantity": float(h.get("quantity") or 0),
            "buy_price": float(h.get("buy_price") or 0),
            "current_price": float(h.get("current_price") or 0),
            "sector": h.get("sector", "Other"),
            "buy_date": h.get("buy_date"),
            "source": source,
            "uploaded_at": _now_iso(),
            "created_at": _now_iso(),
        }
        await db.holdings.insert_one(doc)
        inserted += 1
    # Bust caches so Client 360 shows fresh data
    await db.fund_performance_cache.delete_many({"user_id": user_id})
    await db.mfd_profile_signal_cache.delete_many({"user_id": user_id})
    return inserted


async def create_cas_snapshot(
    *,
    user_id: str,
    holdings: List[Dict[str, Any]],
    transactions: List[Dict[str, Any]],
    sips_detected: List[Dict[str, Any]],
    period_start: Optional[str],
    period_end: Optional[str],
    cas_file_id: str,
    cas_filename: str,
) -> Dict[str, Any]:
    """Persist a CAS-derived snapshot. Auto-detects whether this is the
    LATEST snapshot for the user; if yes, mirrors holdings into the
    live `holdings` table so Client 360 shows it by default.

    Returns the snapshot document (with `is_latest` flag set).
    """
    if not period_end:
        # Fallback: today (better than nothing — MFD can re-edit later)
        period_end = _today_iso()
    snapshot_date = period_end

    # Compute allocation/health from the snapshot holdings (NOT from
    # the live holdings table — they may belong to an older snapshot).
    aggs = _allocation_from_holdings(holdings)

    snap: Dict[str, Any] = {
        "snapshot_id": uuid.uuid4().hex[:16],
        "user_id": user_id,
        "snapshot_date": snapshot_date,
        "trigger": "cas_upload",
        "source": "cas_upload",
        "cas_file_id": cas_file_id,
        "cas_filename": cas_filename,
        "statement_period_start": period_start,
        "statement_period_end": period_end,
        "holdings": holdings,
        "transactions": transactions or [],
        "sips_detected": sips_detected or [],
        "holdings_count": len(holdings),
        "transactions_count": len(transactions or []),
        "sips_count": len(sips_detected or []),
        "created_at": _now_iso(),
        **aggs,
    }

    # Determine if this is the latest snapshot
    latest_date = await get_latest_snapshot_date(user_id)
    is_latest = latest_date is None or snapshot_date >= latest_date

    # Upsert (if user re-uploads same month's CAS, replace it)
    await db.portfolio_snapshots.update_one(
        {"user_id": user_id, "snapshot_date": snapshot_date},
        {"$set": snap},
        upsert=True,
    )

    # If this snapshot is now the latest → mirror to the live holdings table
    if is_latest:
        await write_holdings_table(user_id, holdings, source="cas")
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {
                "cas_view_state.current_snapshot_date": snapshot_date,
                "cas_view_state.is_default_latest": True,
                "cas_view_state.last_updated": _now_iso(),
            }},
            upsert=True,
        )
        # Compute v3 health for the freshly mounted snapshot. We update
        # the snapshot doc with the score so the timeline can plot it
        # without re-running the engine.
        try:
            from services import portfolio_health as _ph
            hr = await _ph.build_portfolio_health(user_id)
            if hr and hr.health_score is not None:
                scores = {
                    "health": round(float(hr.health_score), 2),
                    **{c.name: round(float(c.score), 2) for c in (hr.components or {}).values()},
                }
                await db.portfolio_snapshots.update_one(
                    {"user_id": user_id, "snapshot_date": snapshot_date},
                    {"$set": {
                        "scores": scores,
                        "health_score": round(float(hr.health_score), 2),
                        "grade": hr.grade,
                    }},
                )
                snap["scores"] = scores
                snap["health_score"] = round(float(hr.health_score), 2)
                snap["grade"] = hr.grade
        except Exception:  # noqa: BLE001
            logger.warning("cas_snapshot: health compute failed for %s", user_id, exc_info=True)

    snap["is_latest"] = is_latest
    return snap


async def load_snapshot_into_holdings(user_id: str, snapshot_date: str) -> Dict[str, Any]:
    """MFD clicks an older snapshot tile → replace live holdings with
    that snapshot's holdings. Preserves all historical snapshots.
    Returns the loaded snapshot."""
    snap = await db.portfolio_snapshots.find_one(
        {"user_id": user_id, "snapshot_date": snapshot_date}, {"_id": 0},
    )
    if not snap:
        raise ValueError(f"No snapshot for {snapshot_date}")
    holdings = snap.get("holdings") or []
    await write_holdings_table(user_id, holdings, source="cas")
    latest_date = await get_latest_snapshot_date(user_id)
    is_latest = snapshot_date == latest_date
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {
            "cas_view_state.current_snapshot_date": snapshot_date,
            "cas_view_state.is_default_latest": is_latest,
            "cas_view_state.last_updated": _now_iso(),
        }},
        upsert=True,
    )
    return snap


async def get_view_state(user_id: str) -> Dict[str, Any]:
    """Returns {current_snapshot_date, is_default_latest} so the UI
    knows which timeline tile to highlight."""
    u = await db.users.find_one({"user_id": user_id}, {"_id": 0, "cas_view_state": 1})
    return (u or {}).get("cas_view_state") or {}


async def list_snapshots(user_id: str, limit: int = 60) -> List[Dict[str, Any]]:
    """Lightweight list — no `holdings` payload — for snapshot-picker UI."""
    cursor = db.portfolio_snapshots.find(
        {"user_id": user_id},
        {
            "_id": 0,
            "snapshot_id": 1,
            "snapshot_date": 1,
            "trigger": 1,
            "source": 1,
            "cas_file_id": 1,
            "cas_filename": 1,
            "statement_period_start": 1,
            "statement_period_end": 1,
            "total_value": 1,
            "total_invested": 1,
            "return_pct": 1,
            "health_score": 1,
            "grade": 1,
            "holdings_count": 1,
            "transactions_count": 1,
            "sips_count": 1,
            "allocation": 1,
            "created_at": 1,
        },
    ).sort("snapshot_date", -1).limit(limit)
    return [d async for d in cursor]


async def get_snapshot(user_id: str, snapshot_date: str, *, include_holdings: bool = True) -> Optional[Dict[str, Any]]:
    proj = {"_id": 0}
    if not include_holdings:
        proj.update({"holdings": 0, "transactions": 0, "sips_detected": 0})
    return await db.portfolio_snapshots.find_one(
        {"user_id": user_id, "snapshot_date": snapshot_date}, proj,
    )


# ── Date-range queries for graphs/tables ─────────────────────────────
async def performance_series(user_id: str, from_date: Optional[str] = None,
                              to_date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns a chronological list of {snapshot_date, total_value,
    total_invested, return_pct, health_score, allocation} — feeds the
    line chart + sparklines."""
    query: Dict[str, Any] = {"user_id": user_id}
    if from_date or to_date:
        date_q: Dict[str, str] = {}
        if from_date:
            date_q["$gte"] = from_date
        if to_date:
            date_q["$lte"] = to_date
        query["snapshot_date"] = date_q
    cursor = db.portfolio_snapshots.find(
        query,
        {
            "_id": 0,
            "snapshot_date": 1,
            "total_value": 1,
            "total_invested": 1,
            "return_pct": 1,
            "health_score": 1,
            "grade": 1,
            "allocation": 1,
            "scores": 1,
        },
    ).sort("snapshot_date", 1)
    return [d async for d in cursor]


def _holding_key(h: Dict[str, Any]) -> str:
    """Stable unique key for matching a holding across two snapshots."""
    return h.get("isin") or h.get("ticker") or (h.get("name") or "").strip()


async def _snapshot_holding_delta(user_id: str, snap_before: str, snap_after: str) -> Dict[str, Any]:
    """Compare holdings between two snapshot dates.
    Returns:
      sip_inflow   – holdings whose units increased (new SIPs / top-ups)
      redemptions  – holdings whose units decreased (switches / redemptions)
      new_entries  – holdings present in after but not in before
      exits        – holdings present in before but not in after
      gross_sip    – sum of estimated SIP amounts (unit_gain × nav)
    """
    docs = await db.portfolio_snapshots.find(
        {"user_id": user_id, "snapshot_date": {"$in": [snap_before, snap_after]}},
        {"_id": 0, "snapshot_date": 1, "holdings": 1},
    ).to_list(2)
    by_date = {d["snapshot_date"]: {_holding_key(h): h for h in (d.get("holdings") or [])} for d in docs}

    before = by_date.get(snap_before, {})
    after  = by_date.get(snap_after, {})

    sip_inflow, redemptions, new_entries, exits = [], [], [], []

    for key, h_b in after.items():
        qty_b = float(h_b.get("quantity") or 0)
        nav_b = float(h_b.get("current_price") or h_b.get("buy_price") or 0)
        name  = h_b.get("name") or h_b.get("scheme_name") or key
        amc   = h_b.get("amc") or h_b.get("asset_type") or "—"
        if key not in before:
            est = round(qty_b * nav_b, 2)
            new_entries.append({"name": name, "amc": amc, "isin": key, "units": qty_b, "estimated_amount": est})
        else:
            qty_a = float(before[key].get("quantity") or 0)
            delta = qty_b - qty_a
            if delta > 0.0001:
                est = round(delta * nav_b, 2)
                sip_inflow.append({"name": name, "amc": amc, "isin": key, "units_added": round(delta, 4), "estimated_amount": est})
            elif delta < -0.0001:
                est = round(abs(delta) * nav_b, 2)
                redemptions.append({"name": name, "amc": amc, "isin": key, "units_removed": round(abs(delta), 4), "estimated_amount": est})

    for key, h_a in before.items():
        if key not in after:
            qty_a = float(h_a.get("quantity") or 0)
            nav_a = float(h_a.get("current_price") or h_a.get("buy_price") or 0)
            name  = h_a.get("name") or h_a.get("scheme_name") or key
            amc   = h_a.get("amc") or h_a.get("asset_type") or "—"
            est   = round(qty_a * nav_a, 2)
            exits.append({"name": name, "amc": amc, "isin": key, "units": qty_a, "estimated_amount": est})

    gross_sip = sum(x["estimated_amount"] for x in sip_inflow) + \
                sum(x["estimated_amount"] for x in new_entries)

    sip_inflow.sort(key=lambda x: x["estimated_amount"], reverse=True)
    redemptions.sort(key=lambda x: x["estimated_amount"], reverse=True)
    new_entries.sort(key=lambda x: x["estimated_amount"], reverse=True)

    return {
        "sip_inflow": sip_inflow,
        "new_entries": new_entries,
        "redemptions": redemptions,
        "exits": exits,
        "gross_sip": round(gross_sip, 2),
    }


async def sip_monthly_summary(user_id: str, from_date: Optional[str] = None,
                               to_date: Optional[str] = None) -> Dict[str, Any]:
    """Aggregate SIP-flagged purchases by YYYY-MM.

    Primary source: `cas_transactions` collection (populated when casparser
    library extracts structured transaction data from digital CAS PDFs).
    Fallback: derive investment amounts from month-over-month snapshot
    total_invested changes (works even for OCR-parsed CAS PDFs).
    """
    match: Dict[str, Any] = {
        "user_id": user_id,
        "type": {"$in": ["SIP_PURCHASE", "PURCHASE"]},
    }
    if from_date or to_date:
        d_q: Dict[str, str] = {}
        if from_date:
            d_q["$gte"] = from_date
        if to_date:
            d_q["$lte"] = to_date
        match["date"] = d_q

    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": {"$substr": ["$date", 0, 7]},
            "total": {"$sum": "$amount"},
            "count": {"$sum": 1},
        }},
        {"$sort": {"_id": 1}},
    ]
    months = []
    total_all = 0.0
    async for d in db.cas_transactions.aggregate(pipeline):
        m = d["_id"]
        amt = round(float(d.get("total") or 0), 2)
        months.append({"month": m, "total": amt, "count": int(d.get("count") or 0)})
        total_all += amt

    # ── Fallback: holding unit-delta SIP inflow ─────────────────────────
    # For OCR-parsed CAS PDFs, estimate monthly SIP inflows from the change
    # in holdings units between consecutive snapshots.
    # Holdings that GAINED units → new SIP / top-up → estimate cost = units_gained × NAV.
    # First snapshot in the range has no "previous" → shown as 0 (baseline).
    if not months:
        # Fetch ALL snapshots in range (and the one just before, for first delta)
        snap_q: Dict[str, Any] = {"user_id": user_id}
        date_filter: Dict[str, str] = {}
        if from_date:
            date_filter["$gte"] = from_date[:10]
        if to_date:
            date_filter["$lte"] = to_date[:10]
        if date_filter:
            snap_q["snapshot_date"] = date_filter

        snaps = await db.portfolio_snapshots.find(
            snap_q,
            {"_id": 0, "snapshot_date": 1, "total_invested": 1},
        ).sort("snapshot_date", 1).to_list(100)

        # Also fetch the snapshot immediately before the range for the first delta
        if snaps and from_date:
            prev_snap = await db.portfolio_snapshots.find_one(
                {"user_id": user_id, "snapshot_date": {"$lt": from_date[:10]}},
                {"_id": 0, "snapshot_date": 1},
                sort=[("snapshot_date", -1)],
            )
            if prev_snap:
                snaps = [prev_snap] + snaps

        total_sip = 0.0
        for i in range(1, len(snaps)):
            delta = await _snapshot_holding_delta(
                user_id, snaps[i - 1]["snapshot_date"], snaps[i]["snapshot_date"]
            )
            gross = delta["gross_sip"]
            m = snaps[i]["snapshot_date"][:7]
            months.append({
                "month": m,
                "total": gross,
                "count": len(delta["sip_inflow"]) + len(delta["new_entries"]),
                "source": "unit_delta",
                # Store snapshot pair so breakdown can reuse the comparison
                "snap_before": snaps[i - 1]["snapshot_date"],
                "snap_after": snaps[i]["snapshot_date"],
            })
            total_sip += gross

        total_all = total_sip

    return {"months": months, "total_invested": round(total_all, 2)}


async def sip_breakdown_for_month(user_id: str, month: str) -> Dict[str, Any]:
    """For a given YYYY-MM, return per-fund and per-AMC breakdown of
    SIP/Purchase amounts. Drill-down view for the bar chart.

    Primary: `cas_transactions` (structured CAS PDFs).
    Fallback: snapshot holding-delta comparison for the two snapshots
    bracketing the requested month.
    """
    if not (len(month) == 7 and month[4] == "-"):
        raise ValueError(f"month must be YYYY-MM, got {month!r}")

    start = f"{month}-01"
    end   = f"{month}-31"
    match = {
        "user_id": user_id,
        "type": {"$in": ["SIP_PURCHASE", "PURCHASE"]},
        "date": {"$gte": start, "$lte": end},
    }

    by_fund_pipe = [
        {"$match": match},
        {"$group": {
            "_id": {"scheme": "$scheme_name", "amc": "$amc", "isin": "$isin"},
            "total": {"$sum": "$amount"},
            "count": {"$sum": 1},
            "units": {"$sum": "$units"},
        }},
        {"$sort": {"total": -1}},
    ]
    funds = []
    async for d in db.cas_transactions.aggregate(by_fund_pipe):
        funds.append({
            "scheme_name": d["_id"]["scheme"],
            "amc": d["_id"]["amc"],
            "isin": d["_id"]["isin"],
            "total": round(float(d.get("total") or 0), 2),
            "count": int(d.get("count") or 0),
            "units": round(float(d.get("units") or 0), 4),
        })

    by_amc_pipe = [
        {"$match": match},
        {"$group": {
            "_id": "$amc",
            "total": {"$sum": "$amount"},
            "count": {"$sum": 1},
        }},
        {"$sort": {"total": -1}},
    ]
    amcs = []
    async for d in db.cas_transactions.aggregate(by_amc_pipe):
        amcs.append({
            "amc": d["_id"] or "Unknown",
            "total": round(float(d.get("total") or 0), 2),
            "count": int(d.get("count") or 0),
        })

    total = sum(f["total"] for f in funds)

    # ── Fallback: snapshot holding-delta breakdown ─────────────────────
    if not funds:
        # Find the snapshot for this month and the one just before it
        snap_after = await db.portfolio_snapshots.find_one(
            {"user_id": user_id, "snapshot_date": {"$gte": start, "$lte": end}},
            {"_id": 0, "snapshot_date": 1},
        )
        if not snap_after:
            # Try the closest snapshot on or after the month
            snap_after = await db.portfolio_snapshots.find_one(
                {"user_id": user_id, "snapshot_date": {"$gte": start}},
                {"_id": 0, "snapshot_date": 1},
                sort=[("snapshot_date", 1)],
            )
        if snap_after:
            snap_before = await db.portfolio_snapshots.find_one(
                {"user_id": user_id, "snapshot_date": {"$lt": snap_after["snapshot_date"]}},
                {"_id": 0, "snapshot_date": 1},
                sort=[("snapshot_date", -1)],
            )
            if snap_before:
                delta = await _snapshot_holding_delta(
                    user_id, snap_before["snapshot_date"], snap_after["snapshot_date"]
                )
                # SIP inflow = holdings with increased units + new entries
                for item in delta["sip_inflow"] + delta["new_entries"]:
                    funds.append({
                        "scheme_name": item["name"],
                        "amc": item.get("amc") or "—",
                        "isin": item.get("isin") or "—",
                        "total": item["estimated_amount"],
                        "count": 1,
                        "units": item.get("units_added") or item.get("units") or 0,
                        "source": "unit_delta",
                    })
                # Build per-AMC rollup
                amc_map: Dict[str, float] = {}
                for f in funds:
                    a = f["amc"] or "Unknown"
                    amc_map[a] = amc_map.get(a, 0.0) + f["total"]
                amcs = [{"amc": a, "total": round(v, 2), "count": 1}
                        for a, v in sorted(amc_map.items(), key=lambda x: -x[1])]
                total = delta["gross_sip"]

                # Also expose redemptions so UI can show full picture
                return {
                    "month": month,
                    "total": round(total, 2),
                    "funds": funds,
                    "amcs": amcs,
                    "redemptions": delta["redemptions"],
                    "exits": delta["exits"],
                    "snap_before": snap_before["snapshot_date"],
                    "snap_after": snap_after["snapshot_date"],
                    "source": "unit_delta",
                }

    return {
        "month": month,
        "total": round(total, 2),
        "funds": funds,
        "amcs": amcs,
    }


async def top_transactions(user_id: str, from_date: Optional[str] = None,
                           to_date: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
    """Top N transactions by absolute amount.

    Primary source: `cas_transactions` (structured, digital CAS PDFs).
    Fallback: top holdings by current value from the latest snapshot
    (useful when only OCR-parsed data is available).
    """
    match: Dict[str, Any] = {"user_id": user_id}
    if from_date or to_date:
        d_q: Dict[str, str] = {}
        if from_date:
            d_q["$gte"] = from_date
        if to_date:
            d_q["$lte"] = to_date
        match["date"] = d_q
    cursor = db.cas_transactions.find(
        match,
        {"_id": 0, "date": 1, "scheme_name": 1, "amc": 1, "type": 1,
         "amount": 1, "units": 1, "nav": 1, "folio": 1, "isin": 1},
    ).sort("amount", -1).limit(limit)
    txns = [d async for d in cursor]

    # ── Fallback: top holdings by value across all snapshots in range ─────
    if not txns:
        snap_q: Dict[str, Any] = {"user_id": user_id}
        date_filter: Dict[str, str] = {}
        if from_date:
            date_filter["$gte"] = from_date[:10]
        if to_date:
            date_filter["$lte"] = to_date[:10]
        if date_filter:
            snap_q["snapshot_date"] = date_filter

        # Fetch all snapshots in range, then pick the one with the most data
        snap = await db.portfolio_snapshots.find_one(
            snap_q,
            {"_id": 0, "snapshot_date": 1},
            sort=[("snapshot_date", -1)],  # most recent in range
        )
        if snap:
            full_snap = await db.portfolio_snapshots.find_one(
                {"user_id": user_id, "snapshot_date": snap["snapshot_date"]},
                {"_id": 0, "snapshot_date": 1, "holdings": 1},
            )
            holdings = (full_snap or {}).get("holdings") or []
            holdings_sorted = sorted(
                holdings,
                key=lambda h: float(h.get("quantity") or 0) * float(h.get("current_price") or h.get("buy_price") or 0),
                reverse=True,
            )[:limit]
            for h in holdings_sorted:
                qty = float(h.get("quantity") or 0)
                cp = float(h.get("current_price") or h.get("buy_price") or 0)
                txns.append({
                    "date": snap["snapshot_date"],
                    "scheme_name": h.get("name") or h.get("scheme_name"),
                    "amc": h.get("amc") or h.get("asset_type") or "—",
                    "type": "HOLDING",
                    "amount": round(qty * cp, 2),
                    "units": qty,
                    "nav": cp,
                    "folio": h.get("folio") or "—",
                    "isin": h.get("isin") or h.get("ticker") or "—",
                    "source": "snapshot_holdings",
                })
    return txns


async def ensure_indexes() -> None:
    # Snapshot indexes already covered by services.portfolio_snapshot.ensure_indexes
    await db.cas_transactions.create_index(
        [("user_id", 1), ("date", -1)], name="user_date_desc",
    )
    await db.cas_transactions.create_index(
        [("user_id", 1), ("type", 1), ("date", 1)], name="user_type_date",
    )
