"""GET /api/portfolio/composition

Composition Explorer endpoint for the v5 Performance Dashboard.

Returns portfolio breakdown segmented by one of four dimensions:
  asset_class  — Equity / Debt / Hybrid / Gold / International / MF
  sector       — sector name from holdings
  fund         — individual fund / holding name
  group        — conglomerate parent (HDFC Group, Tata Group, etc.)

Each segment carries weight_pct, current_value, invested, pnl_pct,
and an optional xirr_pct. Concentration breach flags are included
so the frontend can render warning chips without a second call.

GET /api/portfolio/composition/scope — what the totals are made of (PRD §8.3, the trading desk's Portfolio card):
the accounts and sources the stored holdings came from (each with its value, invested value, instrument types,
rows without a price or a cost, last update, and for a broker account its lines for reconciliation), the instrument
types and asset allocation over all of them, and the instruments held in more than one source.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Request

from deps import db, get_current_user
from services.portfolio_concentration import _group_for  # reuse existing group logic

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/portfolio", tags=["portfolio-composition"])

# Concentration thresholds (matches portfolio_remediation._CAP)
_THRESHOLDS: dict[str, float] = {
    "asset_class": 80.0,   # not usually breached; included for completeness
    "sector": 35.0,
    "fund": 10.0,
    "group": 15.0,
}

_VALID_DIMENSIONS = {"asset_class", "sector", "fund", "group"}
_VALID_METRICS = {"weight", "invested", "current"}


def _asset_class_for(asset_type: str, category: str) -> str:
    at = (asset_type or "").lower()
    cat = (category or "").lower()
    if at in {"equity", "stock"}:
        return "Equity"
    if at == "gold" or at == "sgb":
        return "Gold"
    if at == "debt":
        return "Debt"
    if at == "cash":
        return "Cash"
    # MF/ETF — refine by category
    if any(k in cat for k in {"liquid", "debt", "bond", "gilt", "corporate",
                               "short term", "low duration", "overnight", "money market"}):
        return "Debt"
    if any(k in cat for k in {"hybrid", "balanced", "multi asset", "arbitrage"}):
        return "Hybrid"
    if "gold" in cat or "commodity" in cat:
        return "Gold"
    if any(k in cat for k in {"international", "global", "overseas", "us equity", "nasdaq"}):
        return "International"
    return "Equity"


@router.get("/composition")
async def get_composition(
    request: Request,
    dimension: str = "asset_class",
    metric: str = "weight",
    period: Optional[str] = None,   # reserved for future period-scoped XIRR
) -> dict[str, Any]:
    """Portfolio composition breakdown for the Composition Explorer.

    Query params:
      dimension: asset_class | sector | fund | group  (default: asset_class)
      metric:    weight | invested | current           (default: weight)
      period:    1M|3M|6M|1Y|3Y|inception              (reserved; echoed back)
    """
    if dimension not in _VALID_DIMENSIONS:
        from fastapi import HTTPException
        raise HTTPException(status_code=422,
                            detail=f"dimension must be one of {sorted(_VALID_DIMENSIONS)}")
    if metric not in _VALID_METRICS:
        from fastapi import HTTPException
        raise HTTPException(status_code=422,
                            detail=f"metric must be one of {sorted(_VALID_METRICS)}")

    user = await get_current_user(request)
    user_id = user["user_id"]

    holdings: list[dict] = await db.holdings.find(
        {"user_id": user_id},
        {"_id": 0, "name": 1, "ticker": 1, "asset_type": 1, "sector": 1,
         "category": 1, "amc_name": 1, "quantity": 1, "buy_price": 1,
         "current_price": 1, "amfi_matched": 1},
    ).to_list(2000)

    if not holdings:
        return _empty_response(dimension, metric, period)

    # Compute per-holding values
    total_current = 0.0
    total_invested = 0.0
    rows: list[dict] = []
    for h in holdings:
        qty = float(h.get("quantity") or 0)
        bp = float(h.get("buy_price") or 0)
        cp = float(h.get("current_price") or 0)
        current = qty * cp
        invested = qty * bp if bp > 0 else 0.0
        total_current += current
        if bp > 0:
            total_invested += invested

        at = (h.get("asset_type") or "").lower()
        cat = h.get("category") or ""
        name = h.get("name") or "Unknown"

        rows.append({
            "name": name,
            "asset_class": _asset_class_for(at, cat),
            "sector": h.get("sector") or "Other",
            "group": _group_for(name) or "Other",
            "amc": h.get("amc_name") or "Other",
            "current": current,
            "invested": invested,
            "amfi_matched": bool(h.get("amfi_matched", False)),
        })

    if total_current == 0:
        return _empty_response(dimension, metric, period)

    # Bucket by dimension
    buckets: dict[str, dict[str, float]] = defaultdict(lambda: {"current": 0.0, "invested": 0.0})
    for r in rows:
        key = _dimension_key(r, dimension)
        buckets[key]["current"] += r["current"]
        buckets[key]["invested"] += r["invested"]

    # Build segments
    threshold = _THRESHOLDS.get(dimension, 35.0)
    segments = []
    for seg_name, vals in buckets.items():
        weight_pct = vals["current"] / total_current * 100 if total_current > 0 else 0.0
        inv = vals["invested"]
        pnl_pct = ((vals["current"] - inv) / inv * 100) if inv > 0 else None

        # Metric basis value (what the chart sizes/proportions use)
        if metric == "weight":
            metric_value = round(weight_pct, 2)
        elif metric == "invested":
            metric_value = round(inv, 2)
        else:  # current
            metric_value = round(vals["current"], 2)

        segments.append({
            "name": seg_name,
            "weight_pct": round(weight_pct, 2),
            "current_value": round(vals["current"], 2),
            "invested": round(inv, 2) if inv > 0 else None,
            "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
            "metric_value": metric_value,
            "breach": weight_pct >= threshold,
            "breach_threshold": threshold,
        })

    # Sort by current value descending
    segments.sort(key=lambda s: s["current_value"], reverse=True)

    # Concentration breach summary
    breaches = [
        {"segment": s["name"], "weight_pct": s["weight_pct"], "threshold": threshold}
        for s in segments if s["breach"]
    ]

    return {
        "dimension": dimension,
        "metric": metric,
        "period": period,
        "segments": segments,
        "totals": {
            "current_value": round(total_current, 2),
            "invested": round(total_invested, 2) if total_invested > 0 else None,
        },
        "concentration_breaches": breaches,
        "threshold": threshold,
    }


def _dimension_key(row: dict, dimension: str) -> str:
    if dimension == "asset_class":
        return row["asset_class"]
    if dimension == "sector":
        return row["sector"] or "Other"
    if dimension == "fund":
        return row["name"]
    if dimension == "group":
        return row["group"] or "Other"
    return "Other"


def _empty_response(dimension: str, metric: str, period: Optional[str]) -> dict:
    return {
        "dimension": dimension,
        "metric": metric,
        "period": period,
        "segments": [],
        "totals": {"current_value": 0.0, "invested": None},
        "concentration_breaches": [],
        "threshold": _THRESHOLDS.get(dimension, 35.0),
    }


# ── GET /api/portfolio/composition/scope ─────────────────────────────────
# What every total on the trading desk's Portfolio card is made of (PRD §8.3): which accounts and sources, which
# instrument types, how fresh each source is, and what the reconciliation rule left in two places.

SCOPE_RULE = ("Broker wins (helpers.holdings_reconcile): a broker account or a broker's own file replaces a "
              "statement's copy of the same ISIN. Holdings at two different brokers, or a plain sheet beside a "
              "statement, both count; such overlaps are listed here, never merged.")


def _broker_name(slug: Optional[str]) -> str:
    if not slug:
        return "Broker"
    try:
        from services.brokers import registry
        return registry.get(slug).DISPLAY
    except Exception:  # noqa: BLE001 — an unknown or unregistered slug is still named
        return slug.replace("_", " ").title()


def _segment_of(h: dict, accounts: dict) -> tuple[str, str, str, Optional[str], Optional[str]]:
    """(key, kind, name, broker, account_id) of the source a stored holding came from."""
    acct = h.get("broker_account_id")
    broker = h.get("broker")
    if acct:
        doc = accounts.get(acct) or {}
        broker = broker or doc.get("broker")
        display = _broker_name(broker)
        label = (doc.get("label") or "").strip()
        name = display if not label or label.lower() == display.lower() else f"{display} · {label}"
        return f"account:{acct}", "broker_account", name, broker, acct
    if h.get("source") == "broker_export":
        return f"file:{broker}", "broker_file", f"{_broker_name(broker)} file", broker, None
    if h.get("source") in ("cas", "snapshot_load"):
        return "statement", "statement", "CAS statement", None, None
    return "manual", "manual", "Added by hand or from a plain sheet", None, None


def _stamp(h: dict) -> Optional[str]:
    stamps = [str(h[k]) for k in ("price_updated_at", "uploaded_at", "created_at") if h.get(k)]
    return max(stamps) if stamps else None


@router.get("/composition/scope")
async def get_scope(request: Request) -> dict[str, Any]:
    """Accounts / sources, instrument types, asset allocation, freshness and reconciliation of the stored holdings —
    the same rows /api/portfolio/holdings-enriched values (value = quantity × current price)."""
    from helpers import holdings_reconcile

    user = await get_current_user(request)
    uid = user["user_id"]
    holdings: list[dict] = await db.holdings.find(
        {"user_id": uid},
        {"_id": 0, "name": 1, "ticker": 1, "isin": 1, "asset_type": 1, "category": 1, "quantity": 1, "buy_price": 1,
         "current_price": 1, "source": 1, "broker": 1, "broker_account_id": 1, "uploaded_at": 1, "created_at": 1,
         "price_updated_at": 1},
    ).to_list(2000)
    account_docs: list[dict] = await db.broker_accounts.find(
        {"user_id": uid}, {"_id": 0, "account_id": 1, "broker": 1, "label": 1, "native": 1, "last_sync_at": 1},
    ).to_list(50)
    accounts = {a["account_id"]: a for a in account_docs if a.get("account_id")}

    segments: dict[str, dict] = {}
    types: dict[str, int] = defaultdict(int)
    classes: dict[str, float] = defaultdict(float)
    by_isin: dict[str, dict] = {}
    total_value = total_invested = 0.0
    unpriced = no_cost = 0
    stamps: list[str] = []
    for h in holdings:
        key, kind, name, broker, acct = _segment_of(h, accounts)
        seg = segments.setdefault(key, {
            "key": key, "kind": kind, "name": name, "broker": broker, "account_id": acct, "holdings": 0,
            "value_rs": 0.0, "invested_rs": 0.0, "instrument_types": defaultdict(int), "unpriced": 0, "no_cost": 0,
            "last_updated": None,
            "last_sync_at": (accounts.get(acct) or {}).get("last_sync_at") if acct else None,
            "lines": [] if acct else None,
        })
        qty = float(h.get("quantity") or 0)
        bp = float(h.get("buy_price") or 0)
        cp = float(h.get("current_price") or 0)
        value = qty * cp
        at = (h.get("asset_type") or "other").lower()
        seg["holdings"] += 1
        seg["value_rs"] += value
        if bp > 0:
            seg["invested_rs"] += qty * bp
            total_invested += qty * bp
        else:
            seg["no_cost"] += 1
            no_cost += 1
        if cp <= 0:
            seg["unpriced"] += 1
            unpriced += 1
        seg["instrument_types"][at] += 1
        types[at] += 1
        classes[_asset_class_for(at, h.get("category") or "")] += value
        total_value += value
        stamp = _stamp(h)
        if stamp:
            stamps.append(stamp)
            seg["last_updated"] = max(seg["last_updated"] or stamp, stamp)
        isin = holdings_reconcile.resolve_isin(h)
        if acct is not None:
            seg["lines"].append({"isin": isin or None, "symbol": (h.get("ticker") or "").upper() or None, "quantity": qty})
        if isin:
            entry = by_isin.setdefault(isin, {"isin": isin, "name": h.get("name"), "sources": set(), "rows": 0})
            entry["sources"].add(name)
            entry["rows"] += 1

    out_segments = []
    for seg in sorted(segments.values(), key=lambda s: -s["value_rs"]):
        out_segments.append({
            **seg,
            "value_rs": round(seg["value_rs"], 2),
            "invested_rs": round(seg["invested_rs"], 2) if seg["holdings"] > seg["no_cost"] else None,
            "weight_pct": round(seg["value_rs"] / total_value * 100, 2) if total_value > 0 else None,
            "instrument_types": dict(seg["instrument_types"]),
        })
    duplicates = [{**d, "sources": sorted(d["sources"])} for d in by_isin.values() if len(d["sources"]) > 1]
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "source": "Stored holdings (db.holdings), valued at quantity × current price as /api/portfolio/holdings-enriched",
        "accounts": out_segments,
        "instrument_types": dict(types),
        "asset_allocation": sorted(
            [{"asset_class": k, "value_rs": round(v, 2), "weight_pct": round(v / total_value * 100, 2) if total_value > 0 else None}
             for k, v in classes.items()], key=lambda a: -a["value_rs"]),
        "totals": {
            "holdings": len(holdings),
            "value_rs": round(total_value, 2) if holdings else None,
            "invested_rs": round(total_invested, 2) if holdings and len(holdings) > no_cost else None,
            "unpriced_rows": unpriced,
            "no_cost_rows": no_cost,
        },
        "last_updated": max(stamps) if stamps else None,
        "oldest_updated": min(stamps) if stamps else None,
        "reconciliation": {"rule": SCOPE_RULE, "duplicates": duplicates},
    }
