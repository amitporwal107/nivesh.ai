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
from services import pg_client, portfolio_snapshot as _v1_snap
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
    """Latest snapshot date that carries a full holdings array.

    The eod_cron job persists lightweight trend snapshots (total_value +
    top_holdings only — no full `holdings` field). Those are valuable for
    the trend sparkline but should NOT be eligible to be "the active
    portfolio view", because mounting them into the live holdings table
    yields zero rows. Filter them out so callers (Time Machine, snapshot
    activation, is_default_latest checks) only see snapshots they can
    actually mount.
    """
    doc = await db.portfolio_snapshots.find_one(
        {"user_id": user_id,
         "holdings": {"$exists": True, "$not": {"$size": 0}}},
        {"_id": 0, "snapshot_date": 1},
        sort=[("snapshot_date", -1)],
    )
    return doc.get("snapshot_date") if doc else None


async def _resolve_full_scheme_name(name: str, ticker: str, asset_type: str) -> str:
    """Repair a CAS-parsed fund name using the AMFI master (keyed by ISIN).

    The Claude/CAS extractor sometimes truncates scheme names ("HDFC Balanced",
    "NIPPON INDIA", "SUNDARAM"). When we have an ISIN (`ticker` for MF rows
    holds the ISIN), we look it up in AMFI's authoritative NAV feed and
    swap in the canonical scheme name — but only if it looks better than
    what's stored, so we don't replace good names with worse ones.
    """
    name = (name or "").strip()
    ticker = (ticker or "").strip().upper()
    at = (asset_type or "").lower()
    if at not in ("mutual_fund", "mutual fund", "etf"):
        return name
    if not ticker.startswith("INF"):  # AMFI MF ISINs all start with INF
        return name
    try:
        from services import amfi_nav
        entry = await amfi_nav.lookup_nav(isin=ticker)
    except Exception:  # noqa: BLE001
        return name
    if not entry:
        return name
    canonical = (entry.get("scheme_name") or "").strip()
    if not canonical:
        return name
    # Use AMFI's name if our stored one is materially shorter or generic.
    if len(canonical) > len(name) + 4:
        return canonical
    return name


async def write_holdings_table(user_id: str, holdings: List[Dict[str, Any]],
                                source: str = "snapshot_load") -> int:
    """Replace the live `holdings` table for `user_id` with the given
    list. This is what makes a snapshot the "current" view in Client 360.
    """
    await db.holdings.delete_many({"user_id": user_id})
    inserted = 0
    for h in holdings:
        resolved_name = await _resolve_full_scheme_name(
            h.get("name", "Unknown"), h.get("ticker", ""), h.get("asset_type") or "",
        )
        doc = {
            "holding_id": h.get("holding_id") or f"hold_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "portfolio_id": h.get("portfolio_id", ""),
            "name": resolved_name,
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


async def backfill_holding_names_from_amfi(user_id: Optional[str] = None) -> Dict[str, Any]:
    """One-shot: walk `db.holdings` (and stored snapshot.holdings arrays),
    look up each MF/ETF row's ISIN in AMFI, and replace truncated stored
    names with the canonical AMFI scheme name. Idempotent — names that
    already look full enough are left alone."""
    from services import amfi_nav
    await amfi_nav.fetch_nav_data()  # ensure cached
    q: Dict[str, Any] = {"asset_type": {"$in": ["mutual_fund", "etf"]}}
    if user_id:
        q["user_id"] = user_id
    total = 0
    updated = 0
    async for h in db.holdings.find(q, {"_id": 1, "name": 1, "ticker": 1, "asset_type": 1}):
        total += 1
        new_name = await _resolve_full_scheme_name(
            h.get("name") or "", h.get("ticker") or "", h.get("asset_type") or "",
        )
        if new_name and new_name != (h.get("name") or ""):
            await db.holdings.update_one({"_id": h["_id"]}, {"$set": {"name": new_name}})
            updated += 1
    # Snapshots embed their own holdings array — fix those too so a future
    # snapshot activation doesn't reintroduce the truncated names.
    sq: Dict[str, Any] = {}
    if user_id:
        sq["user_id"] = user_id
    snap_updated = 0
    async for snap in db.portfolio_snapshots.find(sq, {"_id": 1, "holdings": 1}):
        holdings = snap.get("holdings") or []
        changed = False
        for h in holdings:
            if (h.get("asset_type") or "").lower() not in ("mutual_fund", "etf"):
                continue
            new_name = await _resolve_full_scheme_name(
                h.get("name") or "", h.get("ticker") or "", h.get("asset_type") or "",
            )
            if new_name and new_name != (h.get("name") or ""):
                h["name"] = new_name
                changed = True
        if changed:
            await db.portfolio_snapshots.update_one(
                {"_id": snap["_id"]}, {"$set": {"holdings": holdings}},
            )
            snap_updated += 1
    return {
        "scanned_holdings": total,
        "renamed_holdings": updated,
        "snapshots_renamed": snap_updated,
    }


async def _enrich_buy_dates(
    user_id: str,
    holdings: List[Dict[str, Any]],
    txns_just_received: List[Dict[str, Any]],
) -> int:
    """Backfill `buy_date` on holdings using:
      1. The transactions array passed into this snapshot, AND
      2. The user's existing `cas_transactions` collection (covers
         purchases from prior CAS uploads — the current CAS only carries
         that month's transactions, but a fund SIP'd for years has its
         original buy date in an earlier statement).

    For each holding we use the earliest purchase txn matching
    (isin, folio_number) — falling back to ISIN-only when folio is empty
    (demat MFs / equities). Returns the number of holdings patched.
    """
    pairs: Dict[tuple, str] = {}
    by_isin: Dict[str, str] = {}

    def _ingest(t: Dict[str, Any]) -> None:
        if not isinstance(t, dict):
            return
        ttype = (t.get("type") or t.get("transaction_type") or "").upper()
        desc = (t.get("description") or t.get("raw_description") or "").upper()
        if any(k in f"{ttype} {desc}" for k in ("REDEMPTION", "SELL", "SWITCH OUT", "SWITCH-OUT", "REVERSAL", "PLEDGE", "STT", "STAMP")):
            return
        is_buy = (
            ttype in ("PURCHASE", "SIP_PURCHASE", "BUY")
            or any(k in f"{ttype} {desc}" for k in ("PURCHASE", "SIP", "BUY", "ALLOTMENT"))
        )
        if not is_buy:
            try:
                if float(t.get("units") or 0) > 0 and float(t.get("amount") or t.get("amount_inr") or 0) > 0:
                    is_buy = True
            except (TypeError, ValueError):
                pass
        if not is_buy:
            return
        d = (t.get("date") or "")[:10]
        if not d:
            return
        isin = (t.get("isin") or "").strip().upper()
        folio = (t.get("folio") or t.get("folio_number") or "").strip()
        if isin and folio:
            key = (isin, folio)
            if key not in pairs or d < pairs[key]:
                pairs[key] = d
        if isin:
            if isin not in by_isin or d < by_isin[isin]:
                by_isin[isin] = d

    for t in txns_just_received or []:
        _ingest(t)
    cursor = db.cas_transactions.find(
        {"user_id": user_id, "type": {"$in": ["PURCHASE", "SIP_PURCHASE", "BUY"]}},
        {"_id": 0, "isin": 1, "folio": 1, "folio_number": 1, "date": 1, "type": 1, "units": 1, "amount": 1},
    )
    async for t in cursor:
        _ingest(t)

    patched = 0
    for h in holdings:
        if h.get("buy_date"):
            continue
        isin = (h.get("ticker") or "").strip().upper()
        folio = (h.get("folio_number") or h.get("folio") or "").strip()
        bd = pairs.get((isin, folio)) if folio else None
        bd = bd or by_isin.get(isin)
        if bd:
            h["buy_date"] = bd
            patched += 1
    if patched:
        logger.info("buy_date enrichment: patched %d/%d holdings for %s", patched, len(holdings), user_id)
    return patched


async def _resolve_instrument_id(conn, holding: Dict[str, Any]) -> Optional[str]:
    """Map a snapshot holding to an `instrument_master.instrument_id` (UUID)
    by ISIN first, then symbol/ticker. Returns None when no match — the
    caller skips the holding rather than failing the whole snapshot."""
    isin = (holding.get("isin") or "").strip()
    if isin:
        row = await conn.fetchrow(
            "SELECT instrument_id::text FROM instrument_master WHERE isin = $1 LIMIT 1",
            isin,
        )
        if row:
            return row["instrument_id"]
    sym = (holding.get("ticker") or holding.get("symbol") or "").strip()
    if sym:
        row = await conn.fetchrow(
            "SELECT instrument_id::text FROM instrument_master WHERE symbol = $1 LIMIT 1",
            sym,
        )
        if row:
            return row["instrument_id"]
    return None


async def _persist_pg_snapshot(
    *,
    user_id: str,
    email: Optional[str],
    display_name: Optional[str],
    snapshot_date: str,
    holdings: List[Dict[str, Any]],
    aggs: Dict[str, Any],
) -> None:
    """Mirror a CAS snapshot into the relational `portfolio_snapshot_master`
    + `portfolio_snapshot_holdings` tables (migration 012). Best-effort —
    PG outages must not break the Mongo write path."""
    pool = await pg_client.get_pool()
    if pool is None:
        logger.debug("pg snapshot: pool unavailable, skipping")
        return
    total_value = aggs.get("total_value")
    total_invested = aggs.get("total_invested")
    try:
        snap_date = date.fromisoformat((snapshot_date or "")[:10])
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Keep email → user_id mapping fresh so the NIDP portfolio sync
                # agent can join on email as the canonical external_user_id.
                if email:
                    await conn.execute(
                        """
                        INSERT INTO client_user_map (client_id, email, display_name, updated_at)
                        VALUES ($1, $2, $3, NOW())
                        ON CONFLICT (client_id) DO UPDATE SET
                            email        = EXCLUDED.email,
                            display_name = EXCLUDED.display_name,
                            updated_at   = NOW()
                        """,
                        user_id, email, display_name,
                    )

                row = await conn.fetchrow(
                    """
                    INSERT INTO portfolio_snapshot_master
                        (client_id, snapshot_date, total_value, total_invested)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (client_id, snapshot_date) DO UPDATE SET
                        total_value   = EXCLUDED.total_value,
                        total_invested = EXCLUDED.total_invested,
                        updated_at    = NOW()
                    RETURNING id
                    """,
                    user_id, snap_date, total_value, total_invested,
                )
                snapshot_id = row["id"]
                # Replace holdings for this snapshot — re-uploads are common.
                await conn.execute(
                    "DELETE FROM portfolio_snapshot_holdings WHERE snapshot_id = $1",
                    snapshot_id,
                )
                tv = float(total_value or 0)
                for h in holdings:
                    iid = await _resolve_instrument_id(conn, h)
                    if not iid:
                        continue
                    qty = float(h.get("quantity") or 0)
                    cmp_ = float(h.get("current_price") or h.get("buy_price") or 0)
                    value = qty * cmp_
                    weight = round(value / tv * 100, 2) if tv > 0 else 0.0
                    await conn.execute(
                        """
                        INSERT INTO portfolio_snapshot_holdings
                            (snapshot_id, instrument_id, units, current_value, weight_pct)
                        VALUES ($1, $2::uuid, $3, $4, $5)
                        ON CONFLICT (snapshot_id, instrument_id) DO UPDATE SET
                            units = EXCLUDED.units,
                            current_value = EXCLUDED.current_value,
                            weight_pct = EXCLUDED.weight_pct
                        """,
                        snapshot_id, iid, qty, round(value, 2), weight,
                    )
    except Exception:  # noqa: BLE001
        logger.warning("pg snapshot persist failed for %s/%s", user_id, snapshot_date, exc_info=True)


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

    # Backfill buy_date from this CAS's txns plus any older cas_transactions
    # so the tax-snapshot view can split STCG vs LTCG.
    await _enrich_buy_dates(user_id, holdings, transactions or [])

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

    # Mirror into the relational portfolio_snapshot tables (migration 012).
    # Pull email + display_name from Mongo so client_user_map stays in sync
    # for the NIDP portfolio sync agent.
    _user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0, "email": 1, "name": 1})
    await _persist_pg_snapshot(
        user_id=user_id,
        email=(_user_doc or {}).get("email"),
        display_name=(_user_doc or {}).get("name"),
        snapshot_date=snapshot_date,
        holdings=holdings,
        aggs=aggs,
    )

    # Export fresh holdings to GCS then trigger NIDP sync — fire-and-forget.
    # NIDP reads from GCS (no cross-VM PG bridge needed).
    import asyncio as _asyncio

    async def _export_then_sync() -> None:
        try:
            from services.pg_client import get_pool as _get_pg_pool
            from services.portfolio_gcs_export import export_portfolio_to_gcs
            pool = await _get_pg_pool()
            if pool:
                result = await export_portfolio_to_gcs(pool, target_date=snapshot_date)
                logger.info("portfolio GCS export after CAS import: %s", result)
        except Exception as _exc:  # noqa: BLE001
            logger.warning("portfolio GCS export failed (non-blocking): %s", _exc)
            return  # don't attempt NIDP sync if export failed
        try:
            from services import nidp_query_client as _nqc
            if _nqc.is_configured():
                await _nqc.execute_feed("portfolio_holdings_sync", target_date=snapshot_date)
        except Exception as _exc:  # noqa: BLE001
            logger.debug("NIDP portfolio sync trigger skipped: %s", _exc)

    _asyncio.ensure_future(_export_then_sync())

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
        # without re-running the engine, AND stash the full HealthResult
        # in Redis under (user_id, snapshot_date) so subsequent activates
        # of this same snapshot are instant.
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
                # cache_health_for_snapshot writes to BOTH Redis and Mongo
                # (snap.health_full) so the next read short-circuits the
                # Groww/V3/intelligence pipeline entirely.
                await _ph.cache_health_for_snapshot(user_id, snapshot_date, hr)
        except Exception:  # noqa: BLE001
            logger.warning("cas_snapshot: health compute failed for %s", user_id, exc_info=True)
    else:
        # Non-latest CAS upload (advisor importing an older statement).
        # Without this, the new snapshot is born with health_score=None
        # and the Time Machine deltas / sparkline will never see it. Run
        # the backfill helper restricted to missing rows — it temp-mounts
        # the snapshot's holdings, computes, and restores the live state.
        try:
            from services import portfolio_snapshot as _ps
            await _ps.backfill_snapshot_health(user_id, only_missing=True)
        except Exception:  # noqa: BLE001
            logger.warning(
                "cas_snapshot: non-latest health backfill failed for %s/%s",
                user_id, snapshot_date, exc_info=True,
            )

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
    """Aggregate SIP-flagged purchases by YYYY-MM directly from the
    `cas_transactions` collection.

    No more unit-delta estimation: we only count REAL transactions
    extracted from the structured CAS payload. If a CAS PDF was parsed
    via OCR/AI (no structured txns), the months array will be empty —
    the UI is responsible for showing an "upload a digital CAS PDF"
    nudge.
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
    raw: List[Dict[str, Any]] = []
    total_all = 0.0
    async for d in db.cas_transactions.aggregate(pipeline):
        m = d["_id"]
        amt = round(float(d.get("total") or 0), 2)
        raw.append({
            "month": m,
            "total": amt,
            "count": int(d.get("count") or 0),
            "source": "cas_transactions",
            "gap": False,
        })
        total_all += amt

    # Fill gap months between first and last so the SIP chart shows
    # missed contributions explicitly (essential for advisor follow-up).
    months: List[Dict[str, Any]] = []
    gap_count = 0
    longest_gap = 0
    if raw:
        by_month = {r["month"]: r for r in raw}
        first_y, first_m = (int(x) for x in raw[0]["month"].split("-"))
        last_y, last_m = (int(x) for x in raw[-1]["month"].split("-"))
        y, m = first_y, first_m
        run = 0
        while (y < last_y) or (y == last_y and m <= last_m):
            key = f"{y:04d}-{m:02d}"
            row = by_month.get(key)
            if row:
                months.append(row)
                run = 0
            else:
                months.append({
                    "month": key,
                    "total": 0.0,
                    "count": 0,
                    "source": "gap",
                    "gap": True,
                })
                gap_count += 1
                run += 1
                longest_gap = max(longest_gap, run)
            m += 1
            if m > 12:
                m = 1
                y += 1

    return {
        "months": months,
        "total_invested": round(total_all, 2),
        "gap_months": gap_count,
        "longest_gap_months": longest_gap,
    }


async def actual_monthly_sip_rate(
    user_id: str, *, lookback_months: int = 6,
) -> Dict[str, Any]:
    """Average monthly SIP / purchase amount over the last `lookback_months`
    *as observed in CAS data*, including gap months as zeroes.

    Used by the goal-rollup to surface a realistic on-track % rather
    than the optimistic one based on the planned mandate.
    Returns dict with avg, total, months_observed, gap_months_in_window.
    """
    summary = await sip_monthly_summary(user_id)
    months = summary.get("months") or []
    if not months:
        return {"avg_monthly_rs": 0.0, "total_in_window_rs": 0.0,
                "months_observed": 0, "gap_months": 0}
    window = months[-lookback_months:]
    total = sum(float(m.get("total") or 0) for m in window)
    gap_in_window = sum(1 for m in window if m.get("gap"))
    return {
        "avg_monthly_rs": round(total / max(1, len(window)), 2),
        "total_in_window_rs": round(total, 2),
        "months_observed": len(window),
        "gap_months": gap_in_window,
    }


async def sip_breakdown_for_month(user_id: str, month: str) -> Dict[str, Any]:
    """For a given YYYY-MM, return per-fund and per-AMC breakdown of
    SIP/Purchase amounts from `cas_transactions`. Drill-down view for
    the bar chart. Also returns redemptions in the same window so the
    UI can show inflow + outflow side-by-side.
    """
    if not (len(month) == 7 and month[4] == "-"):
        raise ValueError(f"month must be YYYY-MM, got {month!r}")

    start = f"{month}-01"
    end   = f"{month}-31"
    base_match = {
        "user_id": user_id,
        "date": {"$gte": start, "$lte": end},
    }
    purchase_match = {**base_match, "type": {"$in": ["SIP_PURCHASE", "PURCHASE"]}}
    redemption_match = {**base_match, "type": {"$in": ["REDEMPTION", "SWITCH_OUT"]}}

    by_fund_pipe = [
        {"$match": purchase_match},
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
        {"$match": purchase_match},
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

    # Redemptions in the same window
    redemptions = []
    async for d in db.cas_transactions.find(
        redemption_match,
        {"_id": 0, "date": 1, "scheme_name": 1, "amc": 1, "amount": 1, "units": 1, "type": 1, "isin": 1, "folio": 1},
    ).sort("amount", -1):
        redemptions.append({
            "name":  d.get("scheme_name"),
            "amc":   d.get("amc") or "—",
            "isin":  d.get("isin"),
            "estimated_amount": round(abs(float(d.get("amount") or 0)), 2),
            "units": round(abs(float(d.get("units") or 0)), 4),
            "date":  d.get("date"),
        })

    total = sum(f["total"] for f in funds)

    return {
        "month": month,
        "total": round(total, 2),
        "funds": funds,
        "amcs": amcs,
        "redemptions": redemptions,
        "exits": [],
        "source": "cas_transactions",
    }


async def top_transactions(user_id: str, from_date: Optional[str] = None,
                           to_date: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
    """Top N actual CAS transactions by absolute amount in the date range.

    Reads ONLY from the structured `cas_transactions` collection — no
    holdings fallback. Empty list when no CAS PDF in the range was
    parsed via the structured path (API or casparser library).
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
    return [d async for d in cursor]


async def ensure_indexes() -> None:
    # Snapshot indexes already covered by services.portfolio_snapshot.ensure_indexes
    await db.cas_transactions.create_index(
        [("user_id", 1), ("date", -1)], name="user_date_desc",
    )
    await db.cas_transactions.create_index(
        [("user_id", 1), ("type", 1), ("date", 1)], name="user_type_date",
    )
    # Parsed CAS JSON cache — one row per file_id
    await db.cas_parsed_responses.create_index("file_id", unique=True)


async def backfill_transactions_from_snapshots(user_id: str) -> Dict[str, Any]:
    """Extract `transactions` arrays embedded in existing
    `portfolio_snapshots` and insert them into `cas_transactions` so
    aggregations work without re-parsing the original PDFs.

    Idempotent — same key as `persist_transactions_and_sips` so re-runs
    don't create dupes.
    """
    snaps = await db.portfolio_snapshots.find(
        {"user_id": user_id, "transactions_count": {"$gt": 0}},
        {"_id": 0, "snapshot_date": 1, "transactions": 1, "cas_file_id": 1},
    ).to_list(500)

    now_iso = _now_iso()
    inserted = updated = 0
    for snap in snaps:
        for t in snap.get("transactions") or []:
            if not isinstance(t, dict) or not t.get("date"):
                continue
            key = {
                "user_id": user_id,
                "folio":   t.get("folio", ""),
                "isin":    t.get("isin", ""),
                "date":    t.get("date"),
                "amount":  t.get("amount", 0),
                "units":   t.get("units", 0),
            }
            update = {
                "$set": {
                    **t,
                    "user_id": user_id,
                    "source": "BACKFILL_SNAPSHOT",
                    "last_seen_at": now_iso,
                    "snapshot_date": snap.get("snapshot_date"),
                    "cas_file_id": snap.get("cas_file_id"),
                },
                "$setOnInsert": {"created_at": now_iso},
            }
            r = await db.cas_transactions.update_one(key, update, upsert=True)
            if r.upserted_id is not None:
                inserted += 1
            elif r.modified_count:
                updated += 1
    return {
        "snapshots_scanned": len(snaps),
        "transactions_inserted": inserted,
        "transactions_updated": updated,
    }
