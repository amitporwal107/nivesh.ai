"""Mutual Fund data endpoints — AMCs, schemes, NAV, holdings, events, disclosure, circulars."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import (
    envelope,
    page_params,
    parse_date,
    row_to_dict,
)


router = APIRouter(prefix="/mf", tags=["mutual_funds"], dependencies=[Depends(require_api_key)])


# ── AMC master ─────────────────────────────────────────────────────────────

@router.get("/amcs", summary="AMC master list with scheme counts")
async def list_amcs() -> Dict[str, Any]:
    """All mutual fund AMCs tracked in the warehouse, ordered by AUM descending."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                a.amc_id,
                a.amc_name,
                a.registrar,
                a.in_top_n,
                a.aum_inr_crore,
                a.website,
                COUNT(s.scheme_code) FILTER (WHERE s.status = 'active') AS active_schemes,
                COUNT(s.scheme_code)                                     AS total_schemes
            FROM nidp.mf_amc_master a
            LEFT JOIN nidp.mf_scheme_master s USING (amc_id)
            WHERE a.enabled = TRUE
            GROUP BY a.amc_id
            ORDER BY a.aum_inr_crore DESC NULLS LAST
            """
        )
    return envelope([row_to_dict(r) for r in rows], limit=len(rows), offset=0)


# ── Scheme master ──────────────────────────────────────────────────────────

@router.get("/schemes", summary="Search and filter scheme master")
async def search_schemes(
    q: Optional[str] = Query(None, description="Scheme name substring search (case-insensitive)"),
    amc_id: Optional[str] = Query(None, description="Filter by AMC slug, e.g. 'sbi', 'hdfc'"),
    category: Optional[str] = Query(None, description="Partial match on scheme_category, e.g. 'Large Cap'"),
    scheme_type: Optional[str] = Query(None, description="Open Ended / Close Ended / Interval"),
    isin: Optional[str] = Query(None, description="Match on ISIN growth or IDCW"),
    status: Optional[str] = Query("active", description="active | closed | merged | suspended"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    """Paginated scheme search. At least one filter recommended for large result sets."""
    conditions = ["1=1"]
    params: List[Any] = []

    if q:
        params.append(q)
        conditions.append(f"s.scheme_name ILIKE '%' || ${len(params)} || '%'")
    if amc_id:
        params.append(amc_id)
        conditions.append(f"s.amc_id = ${len(params)}")
    if category:
        params.append(category)
        conditions.append(f"s.scheme_category ILIKE '%' || ${len(params)} || '%'")
    if scheme_type:
        params.append(scheme_type)
        conditions.append(f"s.scheme_type ILIKE '%' || ${len(params)} || '%'")
    if isin:
        params.append(isin)
        params.append(isin)
        conditions.append(f"(s.isin_growth = ${len(params)-1} OR s.isin_idcw = ${len(params)})")
    if status:
        params.append(status)
        conditions.append(f"s.status = ${len(params)}")

    where = " AND ".join(conditions)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                s.scheme_code,
                s.scheme_name,
                s.amc_id,
                a.amc_name,
                s.isin_growth,
                s.isin_idcw,
                s.scheme_type,
                s.scheme_category,
                s.benchmark_id,
                s.status,
                s.latest_nav,
                s.latest_nav_date,
                s.launch_date
            FROM nidp.mf_scheme_master s
            LEFT JOIN nidp.mf_amc_master a USING (amc_id)
            WHERE {where}
            ORDER BY s.scheme_name
            LIMIT ${len(params)+1} OFFSET ${len(params)+2}
            """,
            *params, page["limit"], page["offset"],
        )
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM nidp.mf_scheme_master s WHERE {where}",
            *params,
        )
    return envelope([row_to_dict(r) for r in rows], total=total, **page)


@router.get("/schemes/{scheme_code}", summary="Single scheme detail with latest disclosure")
async def get_scheme(scheme_code: str) -> Dict[str, Any]:
    """Full scheme metadata joined with latest TER, risk-o-meter, and fund managers."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                s.scheme_code,
                s.scheme_name,
                s.amc_id,
                a.amc_name,
                a.registrar,
                a.website       AS amc_website,
                s.isin_growth,
                s.isin_idcw,
                s.scheme_type,
                s.scheme_category,
                s.status,
                s.latest_nav,
                s.latest_nav_date,
                s.launch_date,
                b.benchmark_id,
                b.name          AS benchmark_name,
                b.index_code    AS benchmark_index_code,
                b.provider      AS benchmark_provider,
                d.ter_pct,
                d.ter_pct_direct,
                d.risk_o_meter,
                d.primary_manager,
                d.secondary_manager,
                d.aum_inr_crore AS disclosed_aum_inr_crore,
                d.snapshot_date AS disclosure_date
            FROM nidp.mf_scheme_master s
            LEFT JOIN nidp.mf_amc_master      a USING (amc_id)
            LEFT JOIN nidp.mf_benchmark_master b ON b.benchmark_id = s.benchmark_id
            LEFT JOIN LATERAL (
                SELECT *
                FROM nidp.mf_scheme_disclosure_snapshot
                WHERE scheme_code = s.scheme_code
                ORDER BY snapshot_date DESC
                LIMIT 1
            ) d ON TRUE
            WHERE s.scheme_code = $1
            """,
            scheme_code,
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"scheme {scheme_code!r} not found")
    return {"data": row_to_dict(row)}


# ── NAV time series ────────────────────────────────────────────────────────

@router.get("/nav/latest", summary="Latest NAV for up to 100 schemes")
async def nav_latest(
    scheme_codes: str = Query(..., description="Comma-separated scheme codes, max 100"),
) -> Dict[str, Any]:
    """Batch latest-NAV lookup. Cheaper than calling /nav/{scheme_code} per scheme."""
    codes = [c.strip() for c in scheme_codes.split(",") if c.strip()][:100]
    if not codes:
        raise HTTPException(status_code=400, detail="provide at least one scheme_code")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (scheme_code)
                scheme_code, nav_date, nav, repurchase_nav, sale_nav, source
            FROM nidp.mf_nav_daily
            WHERE scheme_code = ANY($1)
            ORDER BY scheme_code, nav_date DESC
            """,
            codes,
        )
    return envelope([row_to_dict(r) for r in rows], limit=len(codes), offset=0)


@router.get("/nav/{scheme_code}", summary="NAV time series for a scheme")
async def nav_series(
    scheme_code: str,
    start: Optional[str] = Query(None, description="YYYY-MM-DD (default: 365 days ago)"),
    end: Optional[str]   = Query(None, description="YYYY-MM-DD (default: today)"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    """Daily NAV series, newest-first. Use pagination for multi-year history."""
    d_start = parse_date(start, field="start")
    d_end   = parse_date(end,   field="end")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (nav_date)
                nav_date, nav, repurchase_nav, sale_nav, source
            FROM nidp.mf_nav_daily
            WHERE scheme_code = $1
              AND ($2::date IS NULL OR nav_date >= $2)
              AND ($3::date IS NULL OR nav_date <= $3)
            ORDER BY nav_date DESC
            LIMIT $4 OFFSET $5
            """,
            scheme_code, d_start, d_end, page["limit"], page["offset"],
        )
        total = await conn.fetchval(
            """
            SELECT COUNT(DISTINCT nav_date) FROM nidp.mf_nav_daily
            WHERE scheme_code = $1
              AND ($2::date IS NULL OR nav_date >= $2)
              AND ($3::date IS NULL OR nav_date <= $3)
            """,
            scheme_code, d_start, d_end,
        )
    if not rows and page["offset"] == 0:
        raise HTTPException(status_code=404, detail=f"no NAV data for {scheme_code!r}")
    return envelope([row_to_dict(r) for r in rows], total=total, **page,
                    extra={"scheme_code": scheme_code})


# ── Monthly holdings ───────────────────────────────────────────────────────

@router.get("/holdings/{scheme_code}", summary="Monthly portfolio holdings for a scheme")
async def scheme_holdings(
    scheme_code: str,
    as_of_month: Optional[str] = Query(None, description="YYYY-MM-DD (first day of month); default: latest available"),
    instrument_type: Optional[str] = Query(None, description="EQUITY | DEBT | CASH | DERIVATIVE | REIT"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    """Per-security portfolio holdings. Sorted by weight descending."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if not as_of_month:
            latest = await conn.fetchval(
                "SELECT MAX(as_of_month) FROM nidp.mf_holdings_monthly WHERE scheme_code = $1",
                scheme_code,
            )
            if not latest:
                raise HTTPException(status_code=404, detail=f"no holdings for {scheme_code!r}")
            as_of_month = latest.isoformat()

        conditions = ["scheme_code = $1", "as_of_month = $2::date"]
        params: List[Any] = [scheme_code, as_of_month]
        if instrument_type:
            params.append(instrument_type.upper())
            conditions.append(f"instrument_type = ${len(params)}")

        rows = await conn.fetch(
            f"""
            SELECT
                security_name,
                security_isin,
                instrument_type,
                sector,
                rating,
                quantity,
                market_value_inr,
                weight_pct
            FROM nidp.mf_holdings_monthly
            WHERE {" AND ".join(conditions)}
            ORDER BY weight_pct DESC NULLS LAST
            LIMIT ${len(params)+1} OFFSET ${len(params)+2}
            """,
            *params, page["limit"], page["offset"],
        )
        where_clause = " AND ".join(conditions)
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM nidp.mf_holdings_monthly WHERE {where_clause}",
            *params,
        )
    return envelope([row_to_dict(r) for r in rows], total=total, **page,
                    extra={"scheme_code": scheme_code, "as_of_month": as_of_month})


@router.get("/holdings/overlap", summary="Equity holding overlap between two schemes")
async def holdings_overlap(
    scheme_a: str = Query(...),
    scheme_b: str = Query(...),
    as_of_month: Optional[str] = Query(None, description="YYYY-MM-DD; default: latest available for each"),
) -> Dict[str, Any]:
    """Intersection of equity holdings by ISIN. Returns overlap_pct = sum of min(w_a, w_b)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if as_of_month:
            month_a = month_b = as_of_month
        else:
            row = await conn.fetchrow(
                """
                SELECT
                    MAX(as_of_month) FILTER (WHERE scheme_code = $1) AS m_a,
                    MAX(as_of_month) FILTER (WHERE scheme_code = $2) AS m_b
                FROM nidp.mf_holdings_monthly
                WHERE scheme_code = ANY($3)
                """,
                scheme_a, scheme_b, [scheme_a, scheme_b],
            )
            if not row["m_a"] or not row["m_b"]:
                raise HTTPException(status_code=404, detail="holdings not available for one or both schemes")
            month_a = row["m_a"].isoformat()
            month_b = row["m_b"].isoformat()

        rows = await conn.fetch(
            """
            SELECT
                a.security_isin,
                a.security_name,
                a.sector,
                a.weight_pct         AS weight_a,
                b.weight_pct         AS weight_b,
                LEAST(a.weight_pct, b.weight_pct) AS overlap_weight
            FROM nidp.mf_holdings_monthly a
            JOIN nidp.mf_holdings_monthly b ON a.security_isin = b.security_isin
            WHERE a.scheme_code    = $1
              AND a.as_of_month    = $2::date
              AND b.scheme_code    = $3
              AND b.as_of_month    = $4::date
              AND a.security_isin  IS NOT NULL
              AND a.instrument_type = 'EQUITY'
            ORDER BY overlap_weight DESC NULLS LAST
            """,
            scheme_a, month_a, scheme_b, month_b,
        )

    data = [row_to_dict(r) for r in rows]
    overlap_pct = round(sum(r.get("overlap_weight") or 0 for r in data), 4)
    return {
        "data": data,
        "count": len(data),
        "scheme_a": scheme_a,
        "scheme_b": scheme_b,
        "as_of_month_a": month_a,
        "as_of_month_b": month_b,
        "overlap_pct": overlap_pct,
    }


# ── Scheme events ──────────────────────────────────────────────────────────

@router.get("/schemes/{scheme_code}/events", summary="Lifecycle events: TER changes, manager changes, risk shifts, mergers")
async def scheme_events(
    scheme_code: str,
    event_types: Optional[str] = Query(
        None,
        description="Comma-separated: ter_change, manager_change, risk_change, merger, rename, launch, closure",
    ),
    start: Optional[str] = Query(None, description="YYYY-MM-DD"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    """All detected lifecycle events for a scheme, newest-first."""
    d_start = parse_date(start, field="start")
    types = [t.strip() for t in event_types.split(",")] if event_types else None

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                event_id::text,
                event_type,
                event_date,
                old_value,
                new_value,
                source,
                source_ref,
                detected_at
            FROM nidp.mf_scheme_events
            WHERE scheme_code = $1
              AND ($2::text[]  IS NULL OR event_type = ANY($2))
              AND ($3::date    IS NULL OR event_date >= $3)
            ORDER BY event_date DESC
            LIMIT $4 OFFSET $5
            """,
            scheme_code, types, d_start, page["limit"], page["offset"],
        )
        total = await conn.fetchval(
            """
            SELECT COUNT(*) FROM nidp.mf_scheme_events
            WHERE scheme_code = $1
              AND ($2::text[] IS NULL OR event_type = ANY($2))
              AND ($3::date   IS NULL OR event_date >= $3)
            """,
            scheme_code, types, d_start,
        )
    return envelope([row_to_dict(r) for r in rows], total=total, **page,
                    extra={"scheme_code": scheme_code})


# ── Disclosure snapshot ────────────────────────────────────────────────────

@router.get("/schemes/{scheme_code}/disclosure", summary="TER, risk-o-meter, and fund manager history")
async def scheme_disclosure(
    scheme_code: str,
    history: int = Query(4, ge=1, le=52, description="Number of past snapshots (default: 4 ≈ one quarter)"),
) -> Dict[str, Any]:
    """Weekly SID snapshots: expense ratio, risk category, and named fund managers."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                snapshot_date,
                ter_pct,
                ter_pct_direct,
                risk_o_meter,
                primary_manager,
                secondary_manager,
                aum_inr_crore
            FROM nidp.mf_scheme_disclosure_snapshot
            WHERE scheme_code = $1
            ORDER BY snapshot_date DESC
            LIMIT $2
            """,
            scheme_code, history,
        )
    if not rows:
        raise HTTPException(status_code=404, detail=f"no disclosure data for {scheme_code!r}")
    data = [row_to_dict(r) for r in rows]
    return {
        "scheme_code": scheme_code,
        "latest": data[0],
        "history": data,
        "count": len(data),
    }


# ── AMFI circulars ─────────────────────────────────────────────────────────

@router.get("/circulars", summary="AMFI notices, circulars, and addenda")
async def list_circulars(
    kind: Optional[str] = Query(None, description="notice | circular | addendum"),
    start: Optional[str] = Query(None, description="YYYY-MM-DD"),
    q: Optional[str] = Query(None, description="Title keyword search"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    """AMFI-published lifecycle documents. Source for scheme mergers, renames, regulatory changes."""
    d_start = parse_date(start, field="start")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                circular_id,
                published_at,
                title,
                url,
                kind,
                body_text
            FROM nidp.mf_amfi_circulars
            WHERE ($1::text IS NULL OR kind = $1)
              AND ($2::date IS NULL OR published_at >= $2)
              AND ($3::text IS NULL OR title ILIKE '%' || $3 || '%')
            ORDER BY published_at DESC NULLS LAST
            LIMIT $4 OFFSET $5
            """,
            kind, d_start, q, page["limit"], page["offset"],
        )
        total = await conn.fetchval(
            """
            SELECT COUNT(*) FROM nidp.mf_amfi_circulars
            WHERE ($1::text IS NULL OR kind = $1)
              AND ($2::date IS NULL OR published_at >= $2)
              AND ($3::text IS NULL OR title ILIKE '%' || $3 || '%')
            """,
            kind, d_start, q,
        )
    return envelope([row_to_dict(r) for r in rows], total=total, **page)
