"""Mutual Fund DaaS (Data-as-a-Service) API.

Read-only endpoints surfacing the NIDP mutual-fund data lake directly to
authenticated users. All data is sourced from nidp.mf_* tables.

Endpoints
---------
  GET /api/data/mf/amcs                          — AMC master list
  GET /api/data/mf/schemes                       — scheme search/filter
  GET /api/data/mf/schemes/{scheme_code}         — single scheme detail
  GET /api/data/mf/nav/{scheme_code}             — NAV time series
  GET /api/data/mf/nav/latest                    — latest NAV for ≤100 schemes
  GET /api/data/mf/holdings/{scheme_code}        — monthly holdings
  GET /api/data/mf/holdings/overlap              — portfolio overlap between two schemes
  GET /api/data/mf/schemes/{scheme_code}/events  — TER / manager / risk events
  GET /api/data/mf/schemes/{scheme_code}/disclosure — latest TER, risk-o-meter, managers
  GET /api/data/mf/circulars                     — AMFI notices & circulars

Throttling: process-local TTL cache (60 s default) shared across users.
Auth: any authenticated user.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from deps import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/data/mf", tags=["mf_daas"])

# ── TTL cache ──────────────────────────────────────────────────────────────
_cache: dict[str, tuple[float, Any]] = {}
_locks: dict[str, asyncio.Lock] = {}
_TTL = 60   # seconds


def _cache_get(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry and entry[0] > time.monotonic():
        return entry[1]
    return None


def _cache_set(key: str, value: Any, ttl: int = _TTL) -> None:
    _cache[key] = (time.monotonic() + ttl, value)


def _get_lock(key: str) -> asyncio.Lock:
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


def _serialise(rows) -> list[dict]:
    """Convert asyncpg Records to JSON-safe dicts."""
    out = []
    for r in rows:
        d = dict(r)
        for k, v in d.items():
            if isinstance(v, (date, datetime)):
                d[k] = v.isoformat()
            elif isinstance(v, Decimal):
                d[k] = float(v)
        out.append(d)
    return out


async def _pool():
    from services import pg_client
    pool = await pg_client.get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return pool


# ── AMC master ─────────────────────────────────────────────────────────────

@router.get("/amcs")
async def list_amcs(request: Request):
    """All AMCs with scheme counts and AUM."""
    await get_current_user(request)
    key = "amcs:all"
    async with _get_lock(key):
        if (hit := _cache_get(key)) is not None:
            return hit
        pool = await _pool()
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
        result = {"amcs": _serialise(rows), "total": len(rows)}
        _cache_set(key, result, ttl=300)
        return result


# ── Scheme search ──────────────────────────────────────────────────────────

@router.get("/schemes")
async def search_schemes(
    request: Request,
    q: Optional[str] = Query(None, description="Name search (substring, case-insensitive)"),
    amc_id: Optional[str] = Query(None),
    category: Optional[str] = Query(None, description="Partial match on scheme_category"),
    scheme_type: Optional[str] = Query(None, description="Open Ended / Close Ended / Interval"),
    isin: Optional[str] = Query(None, description="ISIN growth or IDCW"),
    status: str = Query("active"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Search/filter the scheme master. Supports pagination."""
    await get_current_user(request)

    key = f"schemes:{q}:{amc_id}:{category}:{scheme_type}:{isin}:{status}:{limit}:{offset}"
    async with _get_lock(key):
        if (hit := _cache_get(key)) is not None:
            return hit

        conditions = ["1=1"]
        params: list[Any] = []

        def add(cond: str, val: Any):
            params.append(val)
            conditions.append(cond.replace("?", f"${len(params)}"))

        if q:
            add("s.scheme_name ILIKE '%' || ? || '%'", q)
        if amc_id:
            add("s.amc_id = ?", amc_id)
        if category:
            add("s.scheme_category ILIKE '%' || ? || '%'", category)
        if scheme_type:
            add("s.scheme_type ILIKE '%' || ? || '%'", scheme_type)
        if isin:
            add("(s.isin_growth = ? OR s.isin_idcw = ?)", isin)
            # asyncpg needs separate params for each placeholder
            params[-1] = isin  # duplicate: already added once
            # rebuild for two placeholders
            conditions.pop()
            params.pop()
            params.append(isin)
            params.append(isin)
            conditions.append(f"(s.isin_growth = ${len(params)-1} OR s.isin_idcw = ${len(params)})")
        if status:
            add("s.status = ?", status)

        where = " AND ".join(conditions)

        pool = await _pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT
                    s.scheme_code,
                    s.scheme_name,
                    s.amc_id,
                    s.amc_name_raw,
                    s.isin_growth,
                    s.isin_idcw,
                    s.scheme_type,
                    s.scheme_category,
                    s.benchmark_id,
                    s.status,
                    s.latest_nav,
                    s.latest_nav_date,
                    s.launch_date,
                    a.amc_name,
                    a.registrar
                FROM nidp.mf_scheme_master s
                LEFT JOIN nidp.mf_amc_master a USING (amc_id)
                WHERE {where}
                ORDER BY s.scheme_name
                LIMIT ${len(params)+1} OFFSET ${len(params)+2}
                """,
                *params, limit, offset,
            )
            total_row = await conn.fetchrow(
                f"SELECT COUNT(*) AS n FROM nidp.mf_scheme_master s WHERE {where}",
                *params,
            )

        result = {
            "schemes": _serialise(rows),
            "total": total_row["n"],
            "limit": limit,
            "offset": offset,
        }
        _cache_set(key, result)
        return result


@router.get("/schemes/{scheme_code}")
async def get_scheme(request: Request, scheme_code: str):
    """Full detail for a single scheme including latest disclosure snapshot."""
    await get_current_user(request)
    key = f"scheme:{scheme_code}"
    async with _get_lock(key):
        if (hit := _cache_get(key)) is not None:
            return hit
        pool = await _pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    s.*,
                    a.amc_name,
                    a.registrar,
                    a.website       AS amc_website,
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
            raise HTTPException(status_code=404, detail=f"Scheme {scheme_code!r} not found")
        result = _serialise([row])[0]
        _cache_set(key, result)
        return result


# ── NAV time series ────────────────────────────────────────────────────────

@router.get("/nav/latest")
async def nav_latest(
    request: Request,
    scheme_codes: str = Query(..., description="Comma-separated scheme codes, max 100"),
):
    """Latest NAV for up to 100 schemes in one call."""
    await get_current_user(request)
    codes = [c.strip() for c in scheme_codes.split(",") if c.strip()][:100]
    if not codes:
        raise HTTPException(status_code=400, detail="Provide at least one scheme_code")
    key = f"nav:latest:{','.join(sorted(codes))}"
    async with _get_lock(key):
        if (hit := _cache_get(key)) is not None:
            return hit
        pool = await _pool()
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
        result = {"nav": _serialise(rows)}
        _cache_set(key, result)
        return result


@router.get("/nav/{scheme_code}")
async def nav_series(
    request: Request,
    scheme_code: str,
    from_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    to_date: Optional[str] = Query(None, description="YYYY-MM-DD (default: today)"),
    limit: int = Query(365, ge=1, le=3650),
):
    """NAV time series for a scheme. Defaults to last 365 days."""
    await get_current_user(request)
    to_dt   = to_date   or date.today().isoformat()
    from_dt = from_date or ""
    key = f"nav:{scheme_code}:{from_dt}:{to_dt}:{limit}"
    async with _get_lock(key):
        if (hit := _cache_get(key)) is not None:
            return hit
        pool = await _pool()
        async with pool.acquire() as conn:
            if from_dt:
                rows = await conn.fetch(
                    """
                    SELECT DISTINCT ON (nav_date)
                        nav_date, nav, repurchase_nav, sale_nav, source
                    FROM nidp.mf_nav_daily
                    WHERE scheme_code = $1
                      AND nav_date BETWEEN $2::date AND $3::date
                    ORDER BY nav_date DESC
                    LIMIT $4
                    """,
                    scheme_code, from_dt, to_dt, limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT DISTINCT ON (nav_date)
                        nav_date, nav, repurchase_nav, sale_nav, source
                    FROM nidp.mf_nav_daily
                    WHERE scheme_code = $1
                      AND nav_date <= $2::date
                    ORDER BY nav_date DESC
                    LIMIT $3
                    """,
                    scheme_code, to_dt, limit,
                )
        if not rows:
            raise HTTPException(status_code=404, detail=f"No NAV data for {scheme_code!r}")
        # Return chronological order for charting
        data = list(reversed(_serialise(rows)))
        result = {"scheme_code": scheme_code, "count": len(data), "nav": data}
        _cache_set(key, result)
        return result


# ── Monthly holdings ───────────────────────────────────────────────────────

@router.get("/holdings/{scheme_code}")
async def scheme_holdings(
    request: Request,
    scheme_code: str,
    as_of_month: Optional[str] = Query(None, description="YYYY-MM-DD (first day of month); default: latest"),
    instrument_type: Optional[str] = Query(None, description="EQUITY | DEBT | CASH | DERIVATIVE | REIT"),
):
    """Monthly portfolio holdings for a scheme."""
    await get_current_user(request)
    key = f"holdings:{scheme_code}:{as_of_month}:{instrument_type}"
    async with _get_lock(key):
        if (hit := _cache_get(key)) is not None:
            return hit
        pool = await _pool()
        async with pool.acquire() as conn:
            # Resolve latest month if not specified
            if not as_of_month:
                latest = await conn.fetchval(
                    "SELECT MAX(as_of_month) FROM nidp.mf_holdings_monthly WHERE scheme_code = $1",
                    scheme_code,
                )
                if not latest:
                    raise HTTPException(status_code=404, detail=f"No holdings for {scheme_code!r}")
                as_of_month = latest.isoformat()

            conditions = ["scheme_code = $1", "as_of_month = $2::date"]
            params: list[Any] = [scheme_code, as_of_month]
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
                """,
                *params,
            )
        result = {
            "scheme_code": scheme_code,
            "as_of_month": as_of_month,
            "count": len(rows),
            "holdings": _serialise(rows),
        }
        _cache_set(key, result, ttl=3600)   # holdings change monthly
        return result


@router.get("/holdings/overlap")
async def holdings_overlap(
    request: Request,
    scheme_a: str = Query(...),
    scheme_b: str = Query(...),
    as_of_month: Optional[str] = Query(None),
):
    """Portfolio overlap between two schemes (by ISIN weight intersection)."""
    await get_current_user(request)
    key = f"overlap:{min(scheme_a,scheme_b)}:{max(scheme_a,scheme_b)}:{as_of_month}"
    async with _get_lock(key):
        if (hit := _cache_get(key)) is not None:
            return hit
        pool = await _pool()
        async with pool.acquire() as conn:
            # Resolve month for both schemes
            if not as_of_month:
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
                month_a = row["m_a"]
                month_b = row["m_b"]
            else:
                month_a = month_b = as_of_month

            if not month_a or not month_b:
                raise HTTPException(status_code=404, detail="Holdings data not available for one or both schemes")

            rows = await conn.fetch(
                """
                SELECT
                    a.security_isin,
                    a.security_name,
                    a.sector,
                    a.weight_pct    AS weight_a,
                    b.weight_pct    AS weight_b,
                    LEAST(a.weight_pct, b.weight_pct) AS overlap_weight
                FROM nidp.mf_holdings_monthly a
                JOIN nidp.mf_holdings_monthly b
                  ON a.security_isin = b.security_isin
                WHERE a.scheme_code  = $1
                  AND a.as_of_month  = $2::date
                  AND b.scheme_code  = $3
                  AND b.as_of_month  = $4::date
                  AND a.security_isin IS NOT NULL
                  AND a.instrument_type = 'EQUITY'
                ORDER BY overlap_weight DESC NULLS LAST
                """,
                scheme_a, month_a, scheme_b, month_b,
            )

        data = _serialise(rows)
        total_overlap = sum(r["overlap_weight"] or 0 for r in data)
        result = {
            "scheme_a": scheme_a,
            "scheme_b": scheme_b,
            "as_of_month_a": month_a.isoformat() if hasattr(month_a, "isoformat") else month_a,
            "as_of_month_b": month_b.isoformat() if hasattr(month_b, "isoformat") else month_b,
            "overlap_pct": round(total_overlap, 4),
            "common_stocks": len(data),
            "holdings": data,
        }
        _cache_set(key, result, ttl=3600)
        return result


# ── Scheme events ──────────────────────────────────────────────────────────

@router.get("/schemes/{scheme_code}/events")
async def scheme_events(
    request: Request,
    scheme_code: str,
    event_types: Optional[str] = Query(None, description="Comma-separated: ter_change,manager_change,risk_change,merger,rename,launch,closure"),
    from_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    limit: int = Query(50, ge=1, le=200),
):
    """Lifecycle events for a scheme: TER changes, manager changes, risk shifts, mergers."""
    await get_current_user(request)
    key = f"scheme_events:{scheme_code}:{event_types}:{from_date}:{limit}"
    async with _get_lock(key):
        if (hit := _cache_get(key)) is not None:
            return hit
        pool = await _pool()
        async with pool.acquire() as conn:
            conditions = ["scheme_code = $1"]
            params: list[Any] = [scheme_code]
            if event_types:
                types = [t.strip() for t in event_types.split(",") if t.strip()]
                params.append(types)
                conditions.append(f"event_type = ANY(${len(params)})")
            if from_date:
                params.append(from_date)
                conditions.append(f"event_date >= ${len(params)}::date")

            rows = await conn.fetch(
                f"""
                SELECT
                    event_id,
                    event_type,
                    event_date,
                    old_value,
                    new_value,
                    source,
                    source_ref,
                    detected_at
                FROM nidp.mf_scheme_events
                WHERE {" AND ".join(conditions)}
                ORDER BY event_date DESC
                LIMIT ${len(params)+1}
                """,
                *params, limit,
            )
        result = {
            "scheme_code": scheme_code,
            "count": len(rows),
            "events": _serialise(rows),
        }
        _cache_set(key, result)
        return result


# ── Disclosure snapshot (TER, risk-o-meter, managers) ─────────────────────

@router.get("/schemes/{scheme_code}/disclosure")
async def scheme_disclosure(
    request: Request,
    scheme_code: str,
    history: int = Query(4, ge=1, le=52, description="Number of past snapshots to return"),
):
    """Latest TER, risk-o-meter, and fund manager for a scheme (plus history)."""
    await get_current_user(request)
    key = f"disclosure:{scheme_code}:{history}"
    async with _get_lock(key):
        if (hit := _cache_get(key)) is not None:
            return hit
        pool = await _pool()
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
            raise HTTPException(status_code=404, detail=f"No disclosure data for {scheme_code!r}")
        data = _serialise(rows)
        result = {
            "scheme_code": scheme_code,
            "latest": data[0],
            "history": data,
        }
        _cache_set(key, result)
        return result


# ── AMFI circulars ─────────────────────────────────────────────────────────

@router.get("/circulars")
async def list_circulars(
    request: Request,
    kind: Optional[str] = Query(None, description="notice | circular | addendum"),
    from_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    q: Optional[str] = Query(None, description="Title search"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """AMFI notices, circulars, and addenda."""
    await get_current_user(request)
    key = f"circulars:{kind}:{from_date}:{q}:{limit}:{offset}"
    async with _get_lock(key):
        if (hit := _cache_get(key)) is not None:
            return hit
        pool = await _pool()
        async with pool.acquire() as conn:
            conditions = ["1=1"]
            params: list[Any] = []

            if kind:
                params.append(kind)
                conditions.append(f"kind = ${len(params)}")
            if from_date:
                params.append(from_date)
                conditions.append(f"published_at >= ${len(params)}::date")
            if q:
                params.append(q)
                conditions.append(f"title ILIKE '%' || ${len(params)} || '%'")

            where = " AND ".join(conditions)
            rows = await conn.fetch(
                f"""
                SELECT
                    circular_id,
                    published_at,
                    title,
                    url,
                    kind,
                    body_text
                FROM nidp.mf_amfi_circulars
                WHERE {where}
                ORDER BY published_at DESC NULLS LAST
                LIMIT ${len(params)+1} OFFSET ${len(params)+2}
                """,
                *params, limit, offset,
            )
            total = await conn.fetchval(
                f"SELECT COUNT(*) FROM nidp.mf_amfi_circulars WHERE {where}",
                *params,
            )
        result = {
            "circulars": _serialise(rows),
            "total": total,
            "limit": limit,
            "offset": offset,
        }
        _cache_set(key, result)
        return result
