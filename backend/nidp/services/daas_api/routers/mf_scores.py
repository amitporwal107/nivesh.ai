"""V3 MF persisted-score endpoints (Quality + Health).

Reads from nidp.v3_mf_scores_daily / nidp.v_v3_mf_scores_latest (migration 065),
which is populated nightly by services.v3_scores_engine.

Scope: Quality + Health only. Exit/Add are portfolio-aware and stay on-the-fly
downstream when a user's portfolio is in context.

Every response includes coverage_pct — the fraction of the intended weight
backed by non-NULL primitives. Callers MUST gate ranking comparisons on this
(see project_scoring_ux_defer_until_v3.md).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query

from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import envelope, page_params, row_to_dict
from nidp.shared.storage.pg import get_pool

router = APIRouter(
    prefix="/mf/scores",
    tags=["mf-scores"],
    dependencies=[Depends(require_api_key)],
)

_SCORE_COLS = """
    as_of_date, isin, scheme_code, scheme_name,
    fund_category, sub_category,
    quality_score, quality_components, quality_missing,
    quality_eff_weights, quality_coverage_pct,
    health_score, health_components, health_missing,
    health_eff_weights, health_coverage_pct,
    engine_version, computed_at
"""


@router.get(
    "/{isin}",
    summary="Latest V3 Quality + Health score for one MF scheme (by ISIN)",
)
async def mf_score_latest(
    isin: str = Path(..., min_length=10, max_length=20),
) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {_SCORE_COLS} FROM nidp.v_v3_mf_scores_latest WHERE isin = $1",
            isin.upper(),
        )
    if row is None:
        raise HTTPException(404, f"no persisted V3 score for ISIN {isin.upper()!r}")
    return {"data": row_to_dict(row)}


@router.get(
    "/{isin}/history",
    summary="V3 Quality + Health score history (last N days) for one MF scheme",
)
async def mf_score_history(
    isin: str = Path(..., min_length=10, max_length=20),
    days: int = Query(30, ge=1, le=365, description="Look-back window in days"),
) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT {_SCORE_COLS}
              FROM nidp.v3_mf_scores_daily
             WHERE isin = $1
               AND as_of_date > CURRENT_DATE - $2::int
             ORDER BY as_of_date DESC
            """,
            isin.upper(), days,
        )
    return {
        "isin": isin.upper(),
        "days": days,
        "count": len(rows),
        "history": [row_to_dict(r) for r in rows],
    }


@router.post(
    "/bulk",
    summary="Bulk latest V3 MF scores by ISIN",
)
async def mf_scores_bulk(
    body: Dict[str, Any] = Body(..., example={"isins": ["INF179K01608", "INF179K01VL5"]}),
) -> Dict[str, Any]:
    """Returns the latest persisted score per requested ISIN, keyed by ISIN.

    Missing ISINs are simply absent from the response — callers should degrade
    gracefully when a fund has no persisted score (e.g., new scheme that the
    nightly engine hasn't covered yet).
    """
    raw = body.get("isins") or []
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="isins must be a list")
    isins = [s.strip().upper() for s in raw if isinstance(s, str) and s.strip()]
    if not isins:
        return {"data": {}, "count": 0, "requested": len(raw)}

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT {_SCORE_COLS}
              FROM nidp.v_v3_mf_scores_latest
             WHERE isin = ANY($1::text[])
            """,
            isins,
        )

    data = {r["isin"]: row_to_dict(r) for r in rows}
    return {"data": data, "count": len(data), "requested": len(raw)}


@router.get(
    "/",
    summary="Filtered + sorted V3 MF scores screener (latest snapshot)",
)
async def mf_scores_screener(
    fund_category:        Optional[str]   = Query(None, description="equity | debt | hybrid"),
    sub_category:         Optional[str]   = Query(None, description="ILIKE %X% on sub_category"),
    min_quality:          Optional[float] = Query(None, ge=0, le=100),
    min_health:           Optional[float] = Query(None, ge=0, le=100),
    min_quality_coverage: Optional[float] = Query(80.0, ge=0, le=100,
        description="Minimum quality_coverage_pct (defaults to 80 — ranking-honest)"),
    sort_by:              str             = Query("quality_score",
        description="quality_score | health_score | quality_coverage_pct | health_coverage_pct"),
    sort_desc:            bool            = Query(True),
    page:                 Dict[str, int]  = Depends(page_params),
) -> Dict[str, Any]:
    _ALLOWED_SORT = {
        "quality_score", "health_score",
        "quality_coverage_pct", "health_coverage_pct",
    }
    if sort_by not in _ALLOWED_SORT:
        raise HTTPException(400, f"sort_by must be one of {sorted(_ALLOWED_SORT)}")
    direction = "DESC" if sort_desc else "ASC"

    conds: List[str] = ["TRUE"]
    args: List[Any] = []
    i = 1
    if fund_category:
        conds.append(f"fund_category = ${i}"); args.append(fund_category.lower()); i += 1
    if sub_category:
        conds.append(f"sub_category ILIKE ${i}"); args.append(f"%{sub_category}%"); i += 1
    if min_quality is not None:
        conds.append(f"quality_score >= ${i}"); args.append(min_quality); i += 1
    if min_health is not None:
        conds.append(f"health_score >= ${i}");  args.append(min_health);  i += 1
    if min_quality_coverage is not None:
        conds.append(f"quality_coverage_pct >= ${i}"); args.append(min_quality_coverage); i += 1

    where = " AND ".join(conds)
    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM nidp.v_v3_mf_scores_latest WHERE {where}",
            *args,
        )
        rows = await conn.fetch(
            f"""
            SELECT {_SCORE_COLS}
              FROM nidp.v_v3_mf_scores_latest
             WHERE {where}
             ORDER BY {sort_by} {direction} NULLS LAST
             LIMIT ${i} OFFSET ${i+1}
            """,
            *args, page["limit"], page["offset"],
        )
    return envelope(
        [row_to_dict(r) for r in rows],
        total=total, **page,
        extra={
            "filters": {
                "fund_category":        fund_category,
                "sub_category":         sub_category,
                "min_quality":          min_quality,
                "min_health":           min_health,
                "min_quality_coverage": min_quality_coverage,
            },
            "sort_by":  sort_by,
            "sort_desc": sort_desc,
        },
    )
