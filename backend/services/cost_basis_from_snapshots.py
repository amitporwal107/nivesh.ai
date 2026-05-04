"""Derive cost basis for direct equities / SGBs / demat MFs by walking
all of a user's CAS snapshots and accounting share-count changes at the
period-end market price.

NSDL/CDSL CAS statements only print *current* market price + balance per
holding; they don't carry a cost-basis column for direct equities. With
multiple monthly statements stored we can reconstruct an approximate
weighted-average buy price:

    for each (ISIN) in chronological order:
        delta = qty_this_period - qty_prev_period
        if delta > 0:  # purchase → contribute at this period's close
            total_cost   += delta * market_price
            total_shares += delta
        elif delta < 0:  # sale → reduce position at running avg cost
            avg = total_cost / total_shares
            total_cost   += delta * avg          # delta is negative
            total_shares += delta

    buy_price = total_cost / final_qty   if final_qty > 0 else 0

Pledged shares are *still owned* (just collateralised), so we treat
`num_shares + pledged_shares` as the period quantity for equities.

Mutual-fund-folio rows have a real avg cost from the CAS already (the
CAMS/KFin folio table prints `total_cost_inr`), so they're skipped here.

This is an approximation, not a tax-grade cost basis. Limitations:
  • If the user held the stock before the earliest stored CAS, the
    initial position is priced at the FIRST snapshot's market price
    (best we can do without older history).
  • Bonus issues / splits between snapshots show up as a delta and
    pollute the average. Without corporate-action data we can't tell
    them apart from real purchases.
  • Pledge/unpledge round-trips that the parser misreads as quantity
    swings will distort the average.

When the algorithm has no signal (single snapshot, qty unchanged across
all snapshots, or holding only appeared in the latest CAS), we set
buy_price = 0 to flag "cost basis unknown" — the UI then renders "—"
for P&L instead of a fake number.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from deps import db

logger = logging.getLogger(__name__)


_PLACEHOLDER_ASSET_TYPES = {"equity", "etf", "gold", "preference"}


def _qty_for(row: Dict[str, Any], asset_type: str) -> float:
    """Return total holding quantity for a CAS-parsed row.

    `pledged_shares` is intentionally NOT added — the demat-section parser
    sometimes misreads adjacent columns into that field, producing wild
    swings (e.g. 0 → 222 → 0). Including it polluted the running average
    badly. num_shares alone is the stable signal across snapshots.
    """
    if asset_type in ("equity", "etf", "preference"):
        return float(row.get("num_shares") or 0)
    if asset_type == "gold":
        return float(row.get("num_units") or 0)
    if asset_type in ("mutual_fund", "mf"):
        return float(row.get("num_units") or 0)
    return float(row.get("num_shares") or row.get("num_units") or 0)


# SGB unit prices live in the ~₹2,500–₹20,000 range. Above this ceiling the
# parser has misplaced the *total* value into market_price_per_unit_inr — the
# row is unusable as a cost-basis signal and we drop it.
_SGB_UNIT_PRICE_CEILING = 50_000.0


def _price_for(row: Dict[str, Any], asset_type: str) -> float:
    """Return the per-unit price from a parsed CAS row, with a fallback to
    `value_inr / qty` when the printed price column is missing or bogus."""
    if asset_type in ("equity", "etf", "preference"):
        price = float(row.get("market_price_inr") or 0)
        value = float(row.get("value_inr") or 0)
        qty = float(row.get("num_shares") or 0)
        if price <= 0 and qty > 0 and value > 0:
            return value / qty
        return price
    if asset_type == "gold":
        price = float(row.get("market_price_per_unit_inr") or 0)
        value = float(row.get("value_inr") or 0)
        qty = float(row.get("num_units") or 0)
        # Some snapshots stuff the holding's TOTAL value into the per-unit
        # price column when the parser fails (then leave value_inr=0). The
        # number is then 5-50× the real per-gram price. Drop these rows so
        # they don't poison the running average — the remaining snapshots
        # carry plausible per-unit prices.
        if price > _SGB_UNIT_PRICE_CEILING and value <= 0:
            if qty > 0:
                # Reinterpret: `price` was actually the total value.
                return price / qty
            return 0.0
        if price <= 0 and qty > 0 and value > 0:
            return value / qty
        return price
    if asset_type in ("mutual_fund", "mf"):
        nav = float(row.get("nav_inr") or 0)
        value = float(row.get("value_inr") or 0)
        qty = float(row.get("num_units") or 0)
        if nav <= 0 and qty > 0 and value > 0:
            return value / qty
        return nav
    return 0.0


def _merge_into_index(
    out: Dict[str, Dict[str, Any]],
    isin: str,
    asset_type: str,
    row: Dict[str, Any],
) -> None:
    """Insert/merge a parsed CAS row into the per-ISIN index. The Claude
    parser occasionally emits *duplicate* rows for the same ISIN within a
    single statement (a real one and a zero-shares ghost); without this
    guard the dict assignment lets the ghost overwrite the real row."""
    qty = _qty_for(row, asset_type)
    if isin not in out:
        out[isin] = {"asset_type": asset_type, "row": row}
        return
    # Prefer the row with the larger reported quantity. If they tie, keep
    # the one with a non-zero price (the real row vs the all-zeros ghost).
    cur = out[isin]
    cur_qty = _qty_for(cur["row"], cur["asset_type"])
    if qty > cur_qty:
        out[isin] = {"asset_type": asset_type, "row": row}
    elif qty == cur_qty:
        cur_price = _price_for(cur["row"], cur["asset_type"])
        new_price = _price_for(row, asset_type)
        if new_price > 0 and cur_price <= 0:
            out[isin] = {"asset_type": asset_type, "row": row}


def _index_snapshot_rows(raw_payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Flatten one CAS payload's holdings into {isin: {asset_type, row}}."""
    out: Dict[str, Dict[str, Any]] = {}
    h = raw_payload.get("holdings") or {}
    for row in h.get("equities") or []:
        isin = (row.get("isin") or "").strip().upper()
        if isin:
            _merge_into_index(out, isin, "equity", row)
    for row in h.get("preference_shares") or []:
        isin = (row.get("isin") or "").strip().upper()
        if isin:
            _merge_into_index(out, isin, "preference", row)
    for row in h.get("sovereign_gold_bonds") or []:
        isin = (row.get("isin") or "").strip().upper()
        if isin:
            _merge_into_index(out, isin, "gold", row)
    for row in h.get("mutual_funds_demat") or []:
        isin = (row.get("isin") or "").strip().upper()
        if isin:
            _merge_into_index(out, isin, "mutual_fund", row)
    # MF folios already carry their own avg cost — skip on purpose.
    return out


def _derive_running_avg(
    isin: str,
    snapshots: List[Dict[str, Any]],
) -> Optional[float]:
    """Walk per-period rows for one ISIN and return the running avg cost.
    `snapshots` is a list of {asset_type, row} ordered by period_end ASC."""
    total_cost = 0.0
    total_shares = 0.0
    prev_qty = 0.0
    saw_any_delta = False

    for entry in snapshots:
        at = entry["asset_type"]
        row = entry["row"]
        qty = _qty_for(row, at)
        price = _price_for(row, at)

        # Skip rows where neither qty nor price look usable — these are
        # parser stubs that would otherwise read as a sale-then-rebuy.
        if qty <= 0 and price <= 0:
            continue

        delta = qty - prev_qty

        if delta > 1e-6 and price > 0:
            total_cost += delta * price
            total_shares += delta
            saw_any_delta = True
        elif delta < -1e-6 and total_shares > 0:
            avg = total_cost / total_shares
            total_cost += delta * avg          # delta < 0 reduces cost
            total_shares += delta
            saw_any_delta = True

        prev_qty = qty

    final_qty = prev_qty
    if not saw_any_delta or final_qty <= 0 or total_shares <= 1e-6:
        return None
    avg_cost = total_cost / final_qty
    if avg_cost <= 0:
        return None
    return round(avg_cost, 4)


async def derive_cost_basis_for_holdings(
    user_id: str,
    holdings: List[Dict[str, Any]],
) -> int:
    """Backfill `buy_price` on `holdings` (in-place) using the user's
    historical CAS snapshots. Only touches direct-equity / SGB / demat-MF
    rows whose stored buy_price is a placeholder (== current_price, the
    pre-fix CAS-rebuild fallback). MF folios are left alone — their CAS-
    reported avg cost is authoritative.

    Returns the number of holdings whose buy_price was updated.
    """
    if not holdings:
        return 0

    cursor = db.cas_parsed_responses.find(
        {"user_id": user_id},
        {"_id": 0, "period_end": 1, "raw_payload": 1},
    ).sort("period_end", 1)

    history: List[Dict[str, Dict[str, Any]]] = []
    period_ends: List[str] = []
    async for snap in cursor:
        pe = snap.get("period_end") or ""
        if not pe:
            continue
        idx = _index_snapshot_rows(snap.get("raw_payload") or {})
        history.append(idx)
        period_ends.append(pe)

    if len(history) == 0:
        return 0

    patched = 0
    unknown = 0
    for h in holdings:
        at = (h.get("asset_type") or "").lower()
        # MF folios already carry CAS-reported avg cost — skip.
        if h.get("parsed_by") == "claude_folio":
            continue
        if at not in _PLACEHOLDER_ASSET_TYPES and at not in ("mutual_fund", "mf"):
            continue
        # demat MF rows use parsed_by="claude_demat"; folios use claude_folio.
        # Only enrich demat MFs (no CAS cost basis), not folios.
        if at in ("mutual_fund", "mf") and h.get("parsed_by") != "claude_demat":
            continue

        isin = (h.get("ticker") or "").strip().upper()
        if not isin:
            continue

        per_holding_history: List[Dict[str, Any]] = []
        for snap_idx in history:
            entry = snap_idx.get(isin)
            if entry:
                per_holding_history.append(entry)

        if not per_holding_history:
            continue

        derived = _derive_running_avg(isin, per_holding_history)
        if derived is None:
            # Either fully sold (final_qty == 0 in CAS) or no signal in
            # history. Either way the placeholder buy_price (= last CAS
            # market price) is misleading. Flip to 0 so the UI hides P&L.
            qty = float(h.get("quantity") or 0)
            if qty <= 0:
                h["buy_price"] = 0.0
                h["cost_basis_source"] = "fully_sold"
                unknown += 1
            else:
                # Live qty but no usable history (single snapshot, never
                # changed) — can't reconstruct cost basis from CAS alone.
                h["buy_price"] = 0.0
                h["cost_basis_source"] = "unknown"
                unknown += 1
            continue

        h["buy_price"] = derived
        h["cost_basis_source"] = "snapshot_delta"
        patched += 1

    if patched or unknown:
        logger.info(
            "cost-basis enrichment for %s: patched %d, marked unknown %d "
            "(of %d holdings, %d snapshots)",
            user_id, patched, unknown, len(holdings), len(history),
        )
    return patched
