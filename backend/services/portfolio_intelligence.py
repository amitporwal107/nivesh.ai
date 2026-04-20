"""Portfolio Intelligence — real stock-level overlap + concentration analytics.

Consumes:
  * db.holdings           (user's portfolio: MF + Equity with qty/price)
  * Postgres instrument_master + mutual_fund_holdings + metadata

Produces everything the "AI Copilot" & Insights views need:

  compute_portfolio_intelligence(user_id) → dict:
    mf_investments : [{ instrument_id, scheme_name, isin, amount_rs, category, ... }]
    pairwise_overlap : [{ a, b, overlap_pct, shared_stocks, reasons[] }]
    top_stocks    : [{ name, slug, exposure_pct, exposure_rs, via_funds[] }]
    compression_score : float   # 0-100, higher = more efficient
    effective_stocks : int      # Σ(weight²) reciprocal, like HHI-based
    category_inefficiency : [{ category, funds_count, avg_pair_overlap, invested_rs }]
    sector_exposure : [{ sector, pct, rs }]
    redundancy_suggestions : [{ action, remove, overlap_removed_pct, sector_delta_pct, reason }]
    mf_catalog    : {instrument_id: {holdings:[...], metadata:{...}, ratios:{...}}}

All heavy math is vectorless (pure dicts) — no numpy dependency.
"""
from __future__ import annotations
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict

from deps import db
from services import pg_client

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────
def _amount(h: Dict[str, Any]) -> float:
    qty = h.get("quantity") or 0
    px = h.get("current_price") or h.get("buy_price") or 0
    try:
        return float(qty) * float(px)
    except (TypeError, ValueError):
        return 0.0


def _overlap(a: Dict[str, float], b: Dict[str, float]) -> float:
    """Σ min(w_a(s), w_b(s)) across shared stocks (weights as % 0-100)."""
    return sum(min(a[s], b[s]) for s in a.keys() & b.keys())


# ── Main entry point ─────────────────────────────────────────────────────
async def _compute_holistic_allocation(user_id: str) -> Dict[str, Any]:
    """Scan ALL holdings (not just MF) to compute total value + allocation.

    Used to enrich the intelligence response so downstream callers
    (Copilot prompts, Insights widgets, tax engine) can see the full picture
    even when the MF-only overlap/AMC analytics don't apply.
    """
    total = 0.0
    equity = 0.0
    debt = 0.0
    gold = 0.0
    other = 0.0
    async for h in db.holdings.find({"user_id": user_id}, {"_id": 0}):
        val = _amount(h)
        if val <= 0:
            continue
        total += val
        at = (h.get("asset_type") or "").lower()
        name = (h.get("name") or "").lower()
        if at == "gold" or "gold" in name or "sgb" in name or "sovereign gold" in name:
            gold += val
            continue
        is_debt_mf_or_etf = at in ("mutual_fund", "etf") and any(
            k in name for k in [
                "liquid", "gilt", "bond", "corporate bond", "short term",
                "overnight", "banking & psu", "low duration", "ultra short",
                "medium duration", "long duration", "credit risk",
                "floater", "dynamic bond", "debt",
            ]
        )
        if at in ("bond", "debt", "fd", "deposit") or is_debt_mf_or_etf:
            debt += val
            continue
        if at in ("equity", "stock", "mutual_fund", "mutual fund", "etf"):
            equity += val
            continue
        other += val
    if total <= 0:
        return {"total_value": 0, "asset_allocation": None}
    return {
        "total_value": round(total, 2),
        "asset_allocation": {
            "equity_pct": round(equity / total * 100, 1),
            "debt_pct":   round(debt / total * 100, 1),
            "gold_pct":   round(gold / total * 100, 1),
            "other_pct":  round(other / total * 100, 1),
            "equity_rs":  round(equity, 2),
            "debt_rs":    round(debt, 2),
            "gold_rs":    round(gold, 2),
            "other_rs":   round(other, 2),
        },
    }


async def compute_portfolio_intelligence(user_id: str) -> Dict[str, Any]:
    # Holistic allocation + total value (all asset types, not just MF)
    holistic = await _compute_holistic_allocation(user_id)

    # 1. MF investments from Mongo
    mf_holdings = await db.holdings.find(
        {"user_id": user_id, "asset_type": {"$in": ["mutual_fund", "MUTUAL_FUND"]}},
        {"_id": 0},
    ).to_list(500)

    if not mf_holdings:
        resp = _empty_response("No mutual fund holdings found")
        # Still carry holistic totals so Copilot/Insights can use them
        resp["total_value"] = holistic.get("total_value", 0)
        resp["asset_allocation"] = holistic.get("asset_allocation")
        return resp

    # 2. Resolve each MF → Postgres instrument_id + pull holdings + metadata
    pool = await pg_client.get_pool()
    if pool is None:
        resp = _empty_response("Postgres not configured")
        resp["total_value"] = holistic.get("total_value", 0)
        resp["asset_allocation"] = holistic.get("asset_allocation")
        return resp

    mf_investments: List[Dict[str, Any]] = []
    catalog: Dict[str, Dict[str, Any]] = {}     # instrument_id → {...}
    weights_by_id: Dict[str, Dict[str, float]] = {}  # id → {stock_slug_or_name: pct}

    async with pool.acquire() as conn:
        for h in mf_holdings:
            amt = _amount(h)
            if amt <= 0:
                continue
            name = h.get("name") or ""
            ticker = h.get("ticker") or ""
            isin = ticker if len(ticker) == 12 and ticker.isalnum() else None

            # Resolve
            row = None
            if isin:
                row = await conn.fetchrow(
                    "SELECT im.instrument_id, im.instrument_name, im.isin, im.symbol, "
                    "m.category, m.risk_label, m.aum_cr, m.nav, m.expense_ratio "
                    "FROM instrument_master im LEFT JOIN mutual_fund_metadata m "
                    "ON m.instrument_id = im.instrument_id "
                    "WHERE im.isin = $1 AND im.instrument_type = 'MUTUAL_FUND'",
                    isin,
                )
            if row is None and name:
                row = await conn.fetchrow(
                    "SELECT im.instrument_id, im.instrument_name, im.isin, im.symbol, "
                    "m.category, m.risk_label, m.aum_cr, m.nav, m.expense_ratio "
                    "FROM instrument_master im LEFT JOIN mutual_fund_metadata m "
                    "ON m.instrument_id = im.instrument_id "
                    "WHERE im.instrument_type = 'MUTUAL_FUND' "
                    "AND instrument_name ILIKE $1 "
                    "ORDER BY char_length(instrument_name) ASC LIMIT 1",
                    f"%{name.split(',')[0].strip()}%",
                )
            if row is None:
                # No PG match — still record with just name + amount
                mf_investments.append({
                    "instrument_id": None,
                    "scheme_name": name,
                    "amount_rs": amt,
                    "category": None,
                    "resolved": False,
                })
                continue
            mf_id = str(row["instrument_id"])
            # Fetch latest holdings
            latest = await conn.fetchval(
                "SELECT MAX(holding_date) FROM mutual_fund_holdings WHERE instrument_id = $1",
                row["instrument_id"],
            )
            h_rows = []
            if latest:
                h_rows = await conn.fetch(
                    "SELECT holding_name, holding_stock_slug, holding_sector, "
                    "holding_type, weight_percent, rank "
                    "FROM mutual_fund_holdings "
                    "WHERE instrument_id = $1 AND holding_date = $2",
                    row["instrument_id"], latest,
                )
            # Fetch ratios
            r_row = await conn.fetchrow(
                "SELECT alpha, beta, sharpe, sortino, std_dev, ret_1y, ret_3y, ret_5y "
                "FROM mutual_fund_performance_ratios WHERE instrument_id = $1 "
                "ORDER BY ratios_date DESC LIMIT 1",
                row["instrument_id"],
            )
            mf_investments.append({
                "instrument_id": mf_id,
                "scheme_name": row["instrument_name"],
                "isin": row["isin"],
                "scheme_code": row["symbol"],
                "amount_rs": amt,
                "category": row["category"],
                "risk_label": row["risk_label"],
                "aum_cr": float(row["aum_cr"]) if row["aum_cr"] is not None else None,
                "nav": float(row["nav"]) if row["nav"] is not None else None,
                "expense_ratio": float(row["expense_ratio"]) if row["expense_ratio"] is not None else None,
                "resolved": True,
                "holdings_count": len(h_rows),
            })
            catalog[mf_id] = {
                "scheme_name": row["instrument_name"],
                "category": row["category"],
                "holdings": [dict(x) for x in h_rows],
                "ratios": dict(r_row) if r_row else {},
            }
            weights_by_id[mf_id] = {
                (r["holding_stock_slug"] or r["holding_name"] or "").lower():
                float(r["weight_percent"] or 0)
                for r in h_rows if r["weight_percent"] is not None
            }

    # Dedupe: if multiple Mongo holdings resolved to the same instrument_id,
    # sum their amounts (user may have both direct + regular or ISIN variants).
    mf_investments = _dedupe_investments(mf_investments)

    total_rs = sum(m["amount_rs"] for m in mf_investments)
    resolved_ids = [m["instrument_id"] for m in mf_investments if m["resolved"] and m["instrument_id"] in weights_by_id]

    # 3. Pairwise overlap
    pairs = _pairwise_overlap(resolved_ids, weights_by_id, catalog)

    # 4. Top-stock exposure across the WHOLE MF portfolio
    top_stocks = _top_stock_exposure(mf_investments, weights_by_id, catalog, total_rs)

    # 5. Compression / effective stocks
    comp = _compression_score(top_stocks, total_rs)

    # 6. Category inefficiency
    cat_ineff = _category_inefficiency(mf_investments, pairs)

    # 7. Sector exposure
    sector_exp = _sector_exposure(mf_investments, catalog, total_rs)

    # 8. Redundancy suggestions
    redund = _redundancy_suggestions(mf_investments, weights_by_id, pairs, catalog, total_rs)

    # 9. Unique stocks behavior → compression narrative
    narrative = {
        "total_invested_rs": round(total_rs, 2),
        "unique_stocks": len(top_stocks),
        "effective_stocks": comp["effective_stocks"],
        "compression_score": comp["score"],
        "behaves_like_rs": round(total_rs * comp["score"] / 100, 2),
    }

    return {
        "mf_investments": mf_investments,
        "pairwise_overlap": pairs,
        "top_stocks": top_stocks,
        "compression": comp,
        "narrative": narrative,
        "category_inefficiency": cat_ineff,
        "sector_exposure": sector_exp,
        "redundancy_suggestions": redund,
        "catalog": catalog,
        # Holistic allocation across all asset types (MF + equity + ETF + debt + gold)
        "total_value": holistic.get("total_value", 0),
        "asset_allocation": holistic.get("asset_allocation"),
    }


# ── Sub-computations ─────────────────────────────────────────────────────
def _pairwise_overlap(
    ids: List[str], weights: Dict[str, Dict[str, float]], catalog: Dict[str, Any],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            ov = _overlap(weights[a], weights[b])
            shared_keys = set(weights[a]) & set(weights[b])
            shared = sorted(
                [{"key": s,
                  "w_a": round(weights[a][s], 2),
                  "w_b": round(weights[b][s], 2),
                  "shared_w": round(min(weights[a][s], weights[b][s]), 2)}
                 for s in shared_keys],
                key=lambda x: x["shared_w"], reverse=True,
            )[:10]
            reasons: List[str] = []
            if catalog[a].get("category") and catalog[a]["category"] == catalog[b].get("category"):
                reasons.append(f"Same category: {catalog[a]['category']}")
            if ov >= 60:
                reasons.append("Very high stock-level overlap")
            elif ov >= 35:
                reasons.append("Moderate overlap")
            out.append({
                "a": a, "b": b,
                "a_name": catalog[a]["scheme_name"],
                "b_name": catalog[b]["scheme_name"],
                "overlap_pct": round(ov, 2),
                "shared_count": len(shared_keys),
                "top_shared": shared,
                "reasons": reasons,
            })
    out.sort(key=lambda x: x["overlap_pct"], reverse=True)
    return out


def _top_stock_exposure(
    investments: List[Dict[str, Any]], weights: Dict[str, Dict[str, float]],
    catalog: Dict[str, Any], total_rs: float,
) -> List[Dict[str, Any]]:
    """Aggregate every underlying stock's weighted exposure across MFs + hold rupees."""
    agg: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"exposure_rs": 0.0, "via_funds": [], "sector": None, "name": None}
    )
    for inv in investments:
        if not inv.get("resolved"):
            continue
        mf_id = inv["instrument_id"]
        cat = catalog.get(mf_id, {})
        amt = inv["amount_rs"]
        for h in cat.get("holdings", []):
            key = (h["holding_stock_slug"] or h["holding_name"] or "").lower()
            if not key:
                continue
            w = float(h["weight_percent"] or 0) / 100
            contrib_rs = amt * w
            bucket = agg[key]
            bucket["exposure_rs"] += contrib_rs
            bucket["name"] = bucket["name"] or h["holding_name"]
            bucket["slug"] = h["holding_stock_slug"]
            bucket["sector"] = bucket["sector"] or h["holding_sector"]
            bucket["via_funds"].append({
                "mf_id": mf_id,
                "scheme_name": cat["scheme_name"],
                "weight_in_fund": round(w * 100, 2),
                "rs": round(contrib_rs, 2),
            })
    rows = []
    for key, v in agg.items():
        pct = (v["exposure_rs"] / total_rs * 100) if total_rs > 0 else 0
        rows.append({
            "key": key,
            "name": v["name"],
            "slug": v.get("slug"),
            "sector": v["sector"],
            "exposure_rs": round(v["exposure_rs"], 2),
            "exposure_pct": round(pct, 2),
            "via_funds": sorted(v["via_funds"], key=lambda x: x["rs"], reverse=True),
            "fund_count": len(v["via_funds"]),
        })
    rows.sort(key=lambda x: x["exposure_pct"], reverse=True)
    return rows[:50]


def _compression_score(top_stocks: List[Dict[str, Any]], total_rs: float) -> Dict[str, Any]:
    """Compression: effective # of stocks via 1 / Σ(w²) (reciprocal HHI).
    Score = min(effective_stocks * 100 / max_effective_stocks, 100)
    max_effective_stocks caps at 80 (diversified enough for Indian equities).
    """
    weights = [s["exposure_pct"] / 100 for s in top_stocks if s["exposure_pct"] > 0]
    tot_w = sum(weights)
    if tot_w == 0:
        return {"score": 0, "effective_stocks": 0, "top_10_exposure_pct": 0, "top_20_exposure_pct": 0}
    # Normalise to sum=1 for clean HHI
    norm = [w / tot_w for w in weights]
    hhi = sum(w * w for w in norm)
    eff = round(1 / hhi, 1) if hhi > 0 else 0
    target = 80.0
    score = round(min(eff / target * 100, 100), 1)
    top10 = round(sum(s["exposure_pct"] for s in top_stocks[:10]), 2)
    top20 = round(sum(s["exposure_pct"] for s in top_stocks[:20]), 2)
    return {
        "score": score,
        "effective_stocks": eff,
        "unique_stocks": len(top_stocks),
        "top_10_exposure_pct": top10,
        "top_20_exposure_pct": top20,
    }


def _category_inefficiency(
    investments: List[Dict[str, Any]], pairs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    by_cat: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for inv in investments:
        if inv.get("category"):
            by_cat[inv["category"]].append(inv)
    out = []
    for cat, invs in by_cat.items():
        if len(invs) < 2:
            continue
        ids = {i["instrument_id"] for i in invs if i.get("instrument_id")}
        pair_ovs = [p["overlap_pct"] for p in pairs
                    if p["a"] in ids and p["b"] in ids]
        if not pair_ovs:
            continue
        avg_ov = sum(pair_ovs) / len(pair_ovs)
        max_ov = max(pair_ovs)
        invested = sum(i["amount_rs"] for i in invs)
        out.append({
            "category": cat,
            "funds_count": len(invs),
            "avg_pair_overlap": round(avg_ov, 2),
            "max_pair_overlap": round(max_ov, 2),
            "invested_rs": round(invested, 2),
            "inefficient": avg_ov >= 50,
        })
    out.sort(key=lambda x: (x["inefficient"], x["avg_pair_overlap"]), reverse=True)
    return out


def _sector_exposure(
    investments: List[Dict[str, Any]], catalog: Dict[str, Any], total_rs: float,
) -> List[Dict[str, Any]]:
    agg: Dict[str, float] = defaultdict(float)
    for inv in investments:
        if not inv.get("resolved"):
            continue
        cat = catalog.get(inv["instrument_id"], {})
        amt = inv["amount_rs"]
        for h in cat.get("holdings", []):
            sec = h.get("holding_sector") or "Unclassified"
            w = float(h["weight_percent"] or 0) / 100
            agg[sec] += amt * w
    rows = [{"sector": s, "rs": round(v, 2),
             "pct": round(v / total_rs * 100, 2) if total_rs > 0 else 0}
            for s, v in agg.items()]
    rows.sort(key=lambda x: x["pct"], reverse=True)
    return rows


def _redundancy_suggestions(
    investments: List[Dict[str, Any]], weights: Dict[str, Dict[str, float]],
    pairs: List[Dict[str, Any]], catalog: Dict[str, Any], total_rs: float,
) -> List[Dict[str, Any]]:
    """For each fund, compute the portfolio overlap delta if removed."""
    def portfolio_overlap(ids: List[str]) -> float:
        # Portfolio overlap = weighted mean of pairwise min-weight overlaps
        if len(ids) < 2:
            return 0
        total = 0.0
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                total += _overlap(weights[ids[i]], weights[ids[j]])
        n_pairs = len(ids) * (len(ids) - 1) / 2
        return total / n_pairs if n_pairs > 0 else 0

    resolved = [m for m in investments if m.get("resolved") and m["instrument_id"] in weights]
    if len(resolved) < 3:
        return []
    ids = [m["instrument_id"] for m in resolved]
    base = portfolio_overlap(ids)
    out = []
    for m in resolved:
        kept = [x for x in ids if x != m["instrument_id"]]
        new_ov = portfolio_overlap(kept)
        delta = base - new_ov
        # Compute sector-drift (L1 distance of before/after sector exposure)
        before_sec = _sector_from_ids(ids, investments, catalog)
        after_sec = _sector_from_ids(kept, investments, catalog)
        drift = _sector_l1_drift(before_sec, after_sec)
        out.append({
            "remove_id": m["instrument_id"],
            "remove_name": m["scheme_name"],
            "remove_amount_rs": m["amount_rs"],
            "portfolio_overlap_before": round(base, 2),
            "portfolio_overlap_after": round(new_ov, 2),
            "overlap_reduced_pp": round(delta, 2),
            "sector_l1_drift_pct": round(drift, 2),
            "score": round(delta - drift * 0.3, 2),   # prefer big overlap cut + low sector drift
        })
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:5]


def _sector_from_ids(
    ids: List[str], investments: List[Dict[str, Any]], catalog: Dict[str, Any]
) -> Dict[str, float]:
    invested = {i["instrument_id"]: i["amount_rs"] for i in investments
                if i.get("instrument_id") in ids}
    total = sum(invested.values()) or 1.0
    agg: Dict[str, float] = defaultdict(float)
    for mf_id, amt in invested.items():
        cat = catalog.get(mf_id, {})
        for h in cat.get("holdings", []):
            sec = h.get("holding_sector") or "Unclassified"
            w = float(h["weight_percent"] or 0) / 100
            agg[sec] += amt * w
    return {s: v / total * 100 for s, v in agg.items()}


def _sector_l1_drift(before: Dict[str, float], after: Dict[str, float]) -> float:
    keys = set(before) | set(after)
    return sum(abs(before.get(k, 0) - after.get(k, 0)) for k in keys) / 2


def _dedupe_investments(invs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fold rows sharing the same instrument_id (or scheme_name if unresolved).

    Collapses 'regular' + 'direct' plan variants into a single entry by summing
    amount_rs. Keeps the first resolved row's metadata.
    """
    by_key: Dict[str, Dict[str, Any]] = {}
    for m in invs:
        key = m.get("instrument_id") or f"name::{(m.get('scheme_name') or '').lower().strip()}"
        if key in by_key:
            by_key[key]["amount_rs"] += m["amount_rs"]
        else:
            by_key[key] = {**m}
    return list(by_key.values())


def _empty_response(reason: str) -> Dict[str, Any]:
    return {
        "empty": True,
        "reason": reason,
        "mf_investments": [], "pairwise_overlap": [], "top_stocks": [],
        "compression": {"score": 0, "effective_stocks": 0,
                        "top_10_exposure_pct": 0, "top_20_exposure_pct": 0},
        "narrative": {"total_invested_rs": 0},
        "category_inefficiency": [], "sector_exposure": [],
        "redundancy_suggestions": [], "catalog": {},
    }
