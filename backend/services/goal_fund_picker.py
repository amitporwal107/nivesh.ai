"""Fund picker for Goal-Based Investment Planning.

Given an allocation bucket (equity / debt / hybrid) and optional category
constraints, returns top-ranked funds from the V3 master catalog using the
V3 scores + HAS-style filters (high quality, low overlap, good expense).

Pulls directly from Postgres (mutual_fund_metadata + instrument_master).
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from services import pg_client, v3_weights


# Plain-English labels that map to v3_weights.classify_fund_category()
_BUCKET_MAP = {
    "equity": "equity",
    "debt":   "debt",
    "hybrid": "hybrid",
    "liquid": "liquid",
}


async def pick_funds_for_bucket(
    bucket: str,
    *,
    n: int = 3,
    min_quality: float = 55.0,
    max_expense_ratio: float = 1.5,
    min_aum_cr: float = 500.0,
) -> List[Dict[str, Any]]:
    """Return up to `n` top funds for the bucket, ranked by quality_score DESC.

    Filters:
      - classify_fund_category() matches `bucket`
      - quality_score is populated AND ≥ min_quality
      - expense_ratio (direct) ≤ max_expense_ratio
      - aum_cr ≥ min_aum_cr (liquidity floor)
      - prefers direct plan where available
    """
    bucket = _BUCKET_MAP.get(bucket.lower())
    if not bucket:
        return []

    pool = await pg_client.get_pool()
    if pool is None:
        return []

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT im.instrument_id,
                   im.instrument_name AS scheme_name,
                   im.isin,
                   mfm.category, mfm.sub_category,
                   mfm.expense_ratio::float AS expense_ratio,
                   mfm.aum_cr::float AS aum_cr,
                   mfm.quality_score::float AS quality_score,
                   mfm.health_score::float AS health_score,
                   mfm.add_score_baseline::float AS add_score
            FROM mutual_fund_metadata mfm
            JOIN instrument_master im ON im.instrument_id = mfm.instrument_id
            WHERE mfm.quality_score IS NOT NULL
              AND mfm.quality_score >= $1
              AND COALESCE(mfm.expense_ratio, 99) <= $2
              AND COALESCE(mfm.aum_cr, 0) >= $3
              AND im.is_active = TRUE
            ORDER BY mfm.quality_score DESC NULLS LAST,
                     mfm.health_score DESC NULLS LAST
            LIMIT 100
            """,
            float(min_quality), float(max_expense_ratio), float(min_aum_cr),
        )

    candidates: List[Dict[str, Any]] = []
    for r in rows:
        fd = dict(r)
        cat = v3_weights.classify_fund_category({
            "category": fd.get("category"),
            "sub_category": fd.get("sub_category"),
            "scheme_name": fd.get("scheme_name"),
        })
        if cat != bucket:
            continue
        scheme = fd.get("scheme_name") or ""
        plan_type = "direct" if "direct" in scheme.lower() else "regular"
        candidates.append({
            "instrument_id": str(fd["instrument_id"]),
            "scheme_name": fd["scheme_name"],
            "isin": fd.get("isin"),
            "category": fd.get("category"),
            "sub_category": fd.get("sub_category"),
            "expense_ratio": fd.get("expense_ratio"),
            "aum_cr": fd.get("aum_cr"),
            "quality_score": fd.get("quality_score"),
            "health_score": fd.get("health_score"),
            "add_score": fd.get("add_score"),
            "plan_type": plan_type,
        })
        if len(candidates) >= n * 5:       # pick top pool, trim below
            break

    # Prefer Direct plans when tied on quality
    direct = [c for c in candidates if c.get("plan_type") == "direct"]
    if len(direct) >= n:
        candidates = direct
    return candidates[:n]


async def auto_allocate_funds(
    allocation: Dict[str, float],
    *,
    per_bucket: int = 1,
) -> Dict[str, List[Dict[str, Any]]]:
    """Given an allocation dict {equity, debt, hybrid: pct}, pick `per_bucket`
    fund(s) for each non-zero bucket. Returns:
        {equity: [{instrument_id, scheme_name, weight_pct, ...}], ...}
    Weight is the bucket's pct share (split equally across its funds).
    """
    out: Dict[str, List[Dict[str, Any]]] = {}
    for bucket, pct in allocation.items():
        if not pct or pct <= 0:
            continue
        funds = await pick_funds_for_bucket(bucket, n=per_bucket)
        if not funds:
            out[bucket] = []
            continue
        w = float(pct) / max(1, len(funds))
        for f in funds:
            f["weight_pct"] = round(w, 2)
        out[bucket] = funds
    return out


async def shortlist_for_bucket(
    bucket: str, n: int = 5, *, min_quality: float = 55.0,
) -> List[Dict[str, Any]]:
    """Exposed to the UI so users can see & override auto-picked funds."""
    return await pick_funds_for_bucket(bucket, n=n, min_quality=min_quality)
