"""Portfolio direct push — bypasses GCS.

Builds the same record shapes as portfolio_gcs_export.py but instead of
writing JSONL to GCS it pushes them directly to the NIDP Query API
(POST /portfolio/ingest-holdings, /ingest-transactions and /ingest-goals).

``sync_portfolio_to_nidp`` is the single entry point every trigger uses (CAS
import, post-upload enrichment, the nightly job, the admin endpoints).

The NIDP Query API writes straight to portfolio.user_holdings_snapshot
and portfolio.user_transactions in NIDP TimescaleDB — no GCS billing,
no IAM, no storage.Client import required.

Usage (replaces the export_* calls in cas_snapshot_engine._export_then_sync):
    from services.portfolio_direct_push import push_portfolio_direct, push_transactions_direct
    await push_portfolio_direct(db, target_date=snapshot_date)
    await push_transactions_direct(db, target_date=snapshot_date)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


_ASSET_CLASS: dict[str, str] = {
    "equity":      "EQUITY",
    "mutual_fund": "MF",
    "etf":         "ETF",
    "gold":        "GOLD",
    "debt":        "DEBT",
    "cash":        "CASH",
    "sgb":         "GOLD",
}

_TXN_TYPE_MAP: dict[str, str] = {
    "PURCHASE":         "PURCHASE",
    "SIP_PURCHASE":     "SIP_PURCHASE",
    "BUY":              "PURCHASE",
    "REDEMPTION":       "REDEMPTION",
    "SELL":             "REDEMPTION",
    "SWITCH_IN":        "SWITCH_IN",
    "SWITCH_OUT":       "SWITCH_OUT",
    "DIVIDEND":         "DIVIDEND",
    "DIVIDEND_PAYOUT":  "DIVIDEND",
    "DIVIDEND_REINVEST": "DIVIDEND",
    "BONUS":            "BONUS",
}


def _to_asset_class(asset_type: str) -> str:
    return _ASSET_CLASS.get((asset_type or "").lower(), "OTHER")


def _normalise_txn_type(raw: Optional[str]) -> str:
    return _TXN_TYPE_MAP.get((raw or "").upper().strip(), "OTHER")


def _merge_same_instrument(raw_holdings: list[dict]) -> list[dict]:
    """One position per instrument.

    The same fund is often held in several folios, and the same stock in more
    than one demat account, so `holdings` has several rows per ISIN. NIDP keys
    a snapshot row on (user, date, isin, symbol, scheme code, source); sending
    the rows as they are made each one overwrite the last, and the portfolio
    arrived short (93 rows and about two thirds of the value for a 117-row
    statement). Quantities and values are summed; the buy price is the
    quantity-weighted average of the rows that have one.
    """
    merged: dict[tuple, dict] = {}
    for h in raw_holdings:
        qty = float(h.get("quantity") or 0)
        price = float(h.get("current_price") or 0)
        buy = float(h.get("buy_price") or 0)
        asset_type = (h.get("asset_type") or "").lower()
        isin = h.get("isin") or h.get("ticker")
        symbol = h.get("nse_symbol") if asset_type == "equity" else None
        key = (isin or "", symbol or "")
        pos = merged.get(key)
        if pos is None:
            pos = merged[key] = {
                "asset_class": _to_asset_class(asset_type), "symbol": symbol, "isin": isin,
                "instrument_name": h.get("name"), "quantity": 0.0, "market_value_inr": 0.0,
                "_cost": 0.0, "_cost_qty": 0.0,
            }
        pos["quantity"] += qty
        pos["market_value_inr"] += qty * price
        if buy > 0 and qty > 0:
            pos["_cost"] += qty * buy
            pos["_cost_qty"] += qty
    out = []
    for pos in merged.values():
        cost, cost_qty = pos.pop("_cost"), pos.pop("_cost_qty")
        pos["avg_buy_price"] = (cost / cost_qty) if cost_qty > 0 else None
        out.append(pos)
    return out


async def push_portfolio_direct(
    db,
    target_date: Optional[date] = None,
) -> dict[str, Any]:
    """Build holdings records from MongoDB and push directly to NIDP Postgres.

    Returns a summary dict identical in shape to export_portfolio_to_gcs
    so callers can swap it in with no other changes.
    """
    from services import nidp_query_client as _nqc

    if not _nqc.is_configured():
        logger.info("portfolio_direct_push: NIDP_QUERY_API_URL not configured — skipping")
        return {"exported": 0, "skipped": 0, "via": "skipped"}

    export_date = target_date or date.today()
    date_str = export_date.isoformat()

    # Build user map
    user_map: dict[str, dict] = {}
    async for u in db.users.find({}, {"user_id": 1, "email": 1, "name": 1, "_id": 0}):
        if u.get("user_id") and u.get("email"):
            user_map[u["user_id"]] = {"email": u["email"], "name": u.get("name", "")}

    if not user_map:
        logger.info("portfolio_direct_push: no users found")
        return {"exported": 0, "skipped": 0, "date": date_str, "via": "direct"}

    holdings_by_user: dict[str, list] = {}
    async for h in db.holdings.find({}):
        uid = h.get("user_id")
        if uid:
            holdings_by_user.setdefault(uid, []).append(h)

    records: list[dict] = []
    exported = skipped = 0

    for user_id, user_info in user_map.items():
        raw_holdings = holdings_by_user.get(user_id, [])
        if not raw_holdings:
            skipped += 1
            continue

        positions = _merge_same_instrument(raw_holdings)
        total_value = sum(p["market_value_inr"] for p in positions)

        for p in positions:
            records.append({
                "external_user_id": user_info["email"],
                "client_id":        user_id,
                "display_name":     user_info["name"],
                "snapshot_date":    date_str,
                "asset_class":      p["asset_class"],
                "symbol":           p["symbol"],
                "isin":             p["isin"],
                "amfi_scheme_code": None,
                "instrument_name":  p["instrument_name"],
                "quantity":         p["quantity"],
                "avg_buy_price":    p["avg_buy_price"],
                "market_value_inr": p["market_value_inr"],
                "weight_pct":       round(p["market_value_inr"] / total_value * 100, 6) if total_value > 0 else 0.0,
                "source_system":    "nivesh_cas",
            })
        exported += 1
        logger.info("portfolio_direct_push: queued %s — %d holdings as %d positions",
                    user_info["email"], len(raw_holdings), len(positions))

    if not records:
        return {"exported": 0, "skipped": skipped, "date": date_str, "via": "direct"}

    result = await _nqc.push_holdings(records, date_str)
    logger.info("portfolio_direct_push: holdings push result: %s", result)
    return {
        "exported": exported,
        "skipped": skipped,
        "date": date_str,
        "via": "direct",
        "upserted": result.get("upserted", 0),
        "sync_run_id": result.get("sync_run_id"),
    }


async def push_transactions_direct(
    db,
    target_date: Optional[date] = None,
) -> dict[str, Any]:
    """Build transaction records from MongoDB and push directly to NIDP Postgres."""
    from services import nidp_query_client as _nqc

    if not _nqc.is_configured():
        logger.info("portfolio_direct_push: NIDP_QUERY_API_URL not configured — skipping")
        return {"exported": 0, "via": "skipped"}

    export_date = target_date or date.today()
    date_str = export_date.isoformat()

    user_map: dict[str, dict] = {}
    async for u in db.users.find({}, {"user_id": 1, "email": 1, "name": 1, "_id": 0}):
        if u.get("user_id") and u.get("email"):
            user_map[u["user_id"]] = {"email": u["email"], "name": u.get("name", "")}

    if not user_map:
        return {"exported": 0, "users": 0, "date": date_str, "via": "direct"}

    records: list[dict] = []

    for user_id, user_info in user_map.items():
        async for t in db.cas_transactions.find(
            {"user_id": user_id},
            {
                "_id": 0,
                "folio": 1, "folio_number": 1, "isin": 1,
                "amfi_scheme_code": 1, "symbol": 1, "name": 1, "scheme_name": 1,
                "asset_type": 1, "date": 1, "type": 1,
                "units": 1, "amount": 1, "nav": 1, "price": 1,
                "cas_file_id": 1,
            },
        ):
            txn_date = t.get("date")
            if not txn_date:
                continue
            units = t.get("units")
            amount = t.get("amount")
            nav = t.get("nav") or t.get("price")
            if nav in (None, 0) and units and amount:
                try:
                    nav = float(amount) / float(units)
                except (TypeError, ZeroDivisionError):
                    nav = None

            asset_type = (t.get("asset_type") or "").lower()
            records.append({
                "external_user_id": user_info["email"],
                "client_id":        user_id,
                "txn_date":         str(txn_date)[:10],
                "txn_type":         _normalise_txn_type(t.get("type")),
                "folio":            t.get("folio") or t.get("folio_number"),
                "isin":             t.get("isin"),
                "amfi_scheme_code": t.get("amfi_scheme_code"),
                "symbol":           t.get("symbol"),
                "instrument_name":  t.get("name") or t.get("scheme_name"),
                "asset_class":      _to_asset_class(asset_type) if asset_type else "MF",
                "units":            float(units) if units is not None else None,
                "amount_inr":       float(amount) if amount is not None else None,
                "nav_or_price":     float(nav) if nav is not None else None,
                "cas_file_id":      t.get("cas_file_id"),
                "source_system":    "nivesh_cas",
            })

    if not records:
        logger.info("portfolio_direct_push: no transactions to push")
        return {"exported": 0, "users": 0, "date": date_str, "via": "direct"}

    result = await _nqc.push_transactions(records, date_str)
    logger.info("portfolio_direct_push: transactions push result: %s", result)
    return {
        "exported": len(records),
        "date": date_str,
        "via": "direct",
        "upserted": result.get("upserted", 0),
    }


async def push_goals_direct(
    db,
    target_date: Optional[date] = None,
) -> dict[str, Any]:
    """Build goal records (PG `user_goals`) and push directly to NIDP Postgres."""
    import json

    from services import nidp_query_client as _nqc
    from services.portfolio_gcs_export import build_goal_records

    if not _nqc.is_configured():
        logger.info("portfolio_direct_push: NIDP_QUERY_API_URL not configured — skipping")
        return {"exported": 0, "via": "skipped"}

    date_str = (target_date or date.today()).isoformat()
    built = await build_goal_records(db)
    if built.get("skipped_reason"):
        return {"exported": 0, "users": 0, "date": date_str, "via": "direct",
                "skipped_reason": built["skipped_reason"]}
    if not built["records"]:
        logger.info("portfolio_direct_push: no goals to push")
        return {"exported": 0, "users": 0, "date": date_str, "via": "direct",
                "skipped_no_email": built["skipped_no_email"]}

    # Same serialisation the JSONL export applies (UUIDs, Decimals, datetimes → str).
    records = json.loads(json.dumps(built["records"], default=str))
    result = await _nqc.push_goals(records, date_str)
    logger.info("portfolio_direct_push: goals push result: %s", result)
    return {
        "exported": len(records),
        "users": len(built["users"]),
        "date": date_str,
        "via": "direct",
        "upserted": result.get("upserted", 0),
        "skipped_no_email": built["skipped_no_email"],
    }


_PUSHERS = {
    "holdings":     push_portfolio_direct,
    "transactions": push_transactions_direct,
    "goals":        push_goals_direct,
}


async def sync_portfolio_to_nidp(
    db,
    target_date: Optional[date] = None,
    include: tuple[str, ...] = ("holdings", "transactions", "goals"),
) -> dict[str, Any]:
    """Send user portfolio data to NIDP — the one entry point for every trigger.

    With the NIDP Query API configured the data is pushed over HTTP. A failure
    of one kind is logged and reported under its key (``{"error": ...}``) and
    does not stop the others; nothing falls back to another transport, so a
    failed push is visible instead of being masked.

    Where the Query API is NOT configured, the legacy GCS export is used (an
    environment that still relies on the bucket landing zone and the
    portfolio_*_sync cron jobs).
    """
    from services import nidp_query_client as _nqc

    if not _nqc.is_configured():
        from services import portfolio_gcs_export as _gcs
        exporters = {
            "holdings":     _gcs.export_portfolio_to_gcs,
            "transactions": _gcs.export_cas_transactions_to_gcs,
            "goals":        _gcs.export_user_goals_to_gcs,
        }
        out: dict[str, Any] = {"via": "gcs"}
        for kind in include:
            try:
                out[kind] = await exporters[kind](db, target_date=target_date)
            except Exception as exc:  # noqa: BLE001
                logger.warning("portfolio sync (gcs) %s failed: %s", kind, exc)
                out[kind] = {"error": str(exc)[:300]}
        return out

    out = {"via": "direct"}
    for kind in include:
        try:
            out[kind] = await _PUSHERS[kind](db, target_date=target_date)
        except Exception as exc:  # noqa: BLE001
            logger.warning("portfolio sync (direct) %s failed: %s", kind, exc)
            out[kind] = {"error": str(exc)[:300]}
    return out
