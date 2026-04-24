"""Candidate-fund hydrator for the V3 Switch Decision Engine.

Queries the Mongo PG-mirror collections `pg_mirror_mutual_fund_metadata`
and `pg_mirror_mutual_fund_performance_ratios` to build a list of
`CandidateFund` objects for a given peer-group (sub-category) that can
be passed into `switch_decision_engine.decide()`.

Filters (per PRD §3):
  * Same `sub_category` as the current fund (peer-group)
  * AUM ≥ ₹500 Cr
  * Track record ≥ 3 years (fund_age_years)
  * Direct plan preferred (expense_ratio_direct used)

All scale conversions (% → decimal, 0-10 consistency → 0-100) happen here
so the engine stays in a single unit system.

A 5-minute in-process cache keyed by (sub_category, plan_preference)
avoids hitting Mongo per-holding when an insights call iterates over
many funds in the same category.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Tuple

from services.switch_decision_engine import CandidateFund

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 300  # 5 minutes
_cache: Dict[Tuple[str, str], Tuple[float, List[CandidateFund]]] = {}

MIN_AUM_CR = 500.0
MIN_TRACK_RECORD_YEARS = 3.0


# ── Safe coercion helpers ────────────────────────────────────────────────
def _to_float(v, default: Optional[float] = None) -> Optional[float]:
    if v is None:
        return default
    try:
        f = float(v)
        # Treat NaN / Infinity as missing
        if f != f or f in (float("inf"), float("-inf")):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _pct_to_decimal(v, default: Optional[float] = None) -> Optional[float]:
    """Convert a percentage-unit number (e.g., 14.19) to decimal (0.1419)."""
    f = _to_float(v)
    if f is None:
        return default
    return f / 100.0


def _best_return(p: dict) -> Optional[float]:
    """Pick the longest-horizon return available, as decimal fraction."""
    for key in ("ret_5y", "ret_3y", "ret_1y"):
        r = _pct_to_decimal(p.get(key))
        if r is not None:
            return r
    return None


def _consistency_on_100(v) -> float:
    """DB stores `consistency_score` on 0-10. Engine uses 0-100. Scale up."""
    f = _to_float(v)
    if f is None:
        return 0.0
    # Defensive: if someone already stored on 0-100 (>10), pass through.
    if f > 10.0:
        return min(100.0, f)
    return f * 10.0


def _drawdown_decimal(v) -> float:
    """max_drawdown_pct stored as percentage magnitude (20.83 for 20.83%).
    Engine expects positive decimal fraction (lower is better)."""
    f = _to_float(v)
    if f is None:
        return 0.0
    # Stored as absolute magnitude already; a few rows store negative sign.
    return abs(f) / 100.0


def _derive_name(meta: dict, instrument_name_by_iid: Dict[str, str]) -> str:
    """Prefer the canonical instrument_name; fall back to a titleised slug."""
    iid = meta.get("instrument_id")
    if iid and iid in instrument_name_by_iid:
        return instrument_name_by_iid[iid]
    slug = meta.get("groww_slug") or ""
    if slug:
        # tt_bandhan-liquid-fund-M_IDFAH → "Bandhan Liquid Fund"
        core = slug.split("_")[1] if slug.startswith("tt_") else slug
        core = core.replace("-direct", "").replace("-regular", "").replace("-growth", "")
        return " ".join(w.capitalize() for w in core.replace("-", " ").split() if w)
    return "Unknown fund"


# ── Public API ───────────────────────────────────────────────────────────
async def fetch_candidates_for_category(
    db,
    sub_category: str,
    *,
    prefer_direct: bool = True,
    exclude_instrument_id: Optional[str] = None,
) -> List[CandidateFund]:
    """Hydrate a list of CandidateFund peers for the given sub_category.

    Args:
        db: Motor AsyncIOMotorDatabase.
        sub_category: peer group (e.g., "Flexi Cap", "Small Cap").
        prefer_direct: when True, uses `expense_ratio_direct`; else `_regular`.
        exclude_instrument_id: omit this fund from the result (the current
            holding itself should not match as its own alternative).

    Returns:
        Filtered list of CandidateFund objects. May be empty if no peers
        meet the AUM / track-record gates.
    """
    if not sub_category:
        return []

    cache_key = (sub_category, "direct" if prefer_direct else "regular")
    now = time.time()
    cached = _cache.get(cache_key)
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        base = cached[1]
    else:
        base = await _query_and_build(db, sub_category, prefer_direct)
        _cache[cache_key] = (now, base)

    if exclude_instrument_id:
        return [c for c in base if getattr(c, "_instrument_id", None) != exclude_instrument_id]
    return list(base)


async def fetch_current_fund_context(
    db,
    instrument_id: Optional[str] = None,
    scheme_name: Optional[str] = None,
) -> Optional[dict]:
    """Look up the current holding's metadata+ratios to supply
    `expense_current`, `current_return_5y`, `current_drawdown`,
    `current_consistency`, `current_category`, `expense_direct` to the
    decision engine.

    Returns a dict with decimal-unit values, or None if not found.
    """
    meta = None
    if instrument_id:
        meta = await db.pg_mirror_mutual_fund_metadata.find_one(
            {"instrument_id": instrument_id}
        )
    if meta is None and scheme_name:
        # Loose name match — mirrors have `groww_slug`, not name. Walk
        # instrument_master for the instrument_id, then the metadata.
        im = await db.pg_mirror_instrument_master.find_one(
            {"instrument_name": {"$regex": f"^{scheme_name}$", "$options": "i"}}
        )
        if im:
            meta = await db.pg_mirror_mutual_fund_metadata.find_one(
                {"instrument_id": im.get("instrument_id")}
            )
    if meta is None:
        return None

    perf = await db.pg_mirror_mutual_fund_performance_ratios.find_one(
        {"instrument_id": meta.get("instrument_id")}
    ) or {}

    exp_reg = _pct_to_decimal(meta.get("expense_ratio_regular")) or _pct_to_decimal(meta.get("expense_ratio"))
    exp_dir = _pct_to_decimal(meta.get("expense_ratio_direct"))

    return {
        "instrument_id": meta.get("instrument_id"),
        "sub_category": meta.get("sub_category"),
        "category": meta.get("category"),
        "expense_current": exp_reg,
        "expense_direct": exp_dir,
        "current_return_5y": _best_return(perf),
        "current_drawdown": _drawdown_decimal(meta.get("max_drawdown_pct")),
        "current_consistency": _consistency_on_100(meta.get("consistency_score")),
        "fund_age_years": _to_float(meta.get("fund_age_years")),
    }


# ── Internals ────────────────────────────────────────────────────────────
async def _query_and_build(
    db, sub_category: str, prefer_direct: bool
) -> List[CandidateFund]:
    """Run the Mongo queries and assemble CandidateFund objects.

    Filters inline so we never return sub-standard peers.
    """
    # 1. Metadata rows for this sub-category. Project away `_id`.
    query = {"sub_category": sub_category}
    metas = await db.pg_mirror_mutual_fund_metadata.find(
        query, {"_id": 0}
    ).to_list(length=500)

    if not metas:
        return []

    # 2. Performance ratios batch-fetched for every instrument_id.
    iids = [m.get("instrument_id") for m in metas if m.get("instrument_id")]
    perf_rows = await db.pg_mirror_mutual_fund_performance_ratios.find(
        {"instrument_id": {"$in": iids}}, {"_id": 0}
    ).to_list(length=len(iids) + 1)
    perf_by_iid = {p.get("instrument_id"): p for p in perf_rows}

    # 3. Instrument names for human-readable labels.
    im_rows = await db.pg_mirror_instrument_master.find(
        {"instrument_id": {"$in": iids}}, {"_id": 0, "instrument_id": 1, "instrument_name": 1}
    ).to_list(length=len(iids) + 1)
    name_by_iid = {r["instrument_id"]: r.get("instrument_name") or "" for r in im_rows}

    out: List[CandidateFund] = []
    for m in metas:
        iid = m.get("instrument_id")
        aum = _to_float(m.get("aum_cr")) or 0.0
        age = _to_float(m.get("fund_age_years")) or 0.0

        if aum < MIN_AUM_CR:
            continue
        if age < MIN_TRACK_RECORD_YEARS:
            continue

        exp_key = "expense_ratio_direct" if prefer_direct else "expense_ratio_regular"
        exp_dec = _pct_to_decimal(m.get(exp_key)) or _pct_to_decimal(m.get("expense_ratio"))
        if exp_dec is None:
            continue  # no usable cost data

        perf = perf_by_iid.get(iid, {})
        ret_dec = _best_return(perf)
        if ret_dec is None:
            continue  # need at least one return horizon

        cf = CandidateFund(
            name=_derive_name(m, name_by_iid),
            category=sub_category,
            expense=exp_dec,
            return_5y=ret_dec,
            drawdown=_drawdown_decimal(m.get("max_drawdown_pct")),
            consistency=_consistency_on_100(m.get("consistency_score")),
            aum_cr=aum,
            track_record_years=age,
        )
        # Annotate instrument_id for dedup in the public API.
        setattr(cf, "_instrument_id", iid)
        out.append(cf)

    # Sort by a quick proxy (return_5y desc) so the engine picks fast even
    # when its own scorer ties; the engine re-scores anyway.
    out.sort(key=lambda c: c.return_5y, reverse=True)
    return out


def _invalidate_cache() -> None:
    """Test hook — flushes the module-level cache."""
    _cache.clear()
