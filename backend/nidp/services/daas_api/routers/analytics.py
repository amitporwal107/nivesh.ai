"""DuckDB analytics router — serves historical WARM-tier data from MinIO Parquet.

Endpoints:
    GET /v1/analytics/features/{symbol}     historical stock features (> 180 days)
    GET /v1/analytics/financials/{symbol}   historical NSE financials (> 5 years)
    GET /v1/analytics/features/export       AI/backtesting bulk export URL

For data within the hot window (< 180 days for features, < 5 years for financials),
callers should use the standard /v1/features/* and /v1/financials/* endpoints which
query TimescaleDB directly.

DuckDB reads Parquet directly from MinIO via the httpfs/s3 extension.
Connection is a module-level singleton (DuckDB is in-process, not a server).
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import envelope, normalise_symbol, page_params, parse_date

log = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"], dependencies=[Depends(require_api_key)])

_duck_lock = threading.Lock()
_duck_conn = None


def _get_duck():
    """Return a module-level DuckDB connection, configured for MinIO S3."""
    global _duck_conn
    if _duck_conn is not None:
        return _duck_conn
    with _duck_lock:
        if _duck_conn is not None:
            return _duck_conn
        try:
            import duckdb  # type: ignore[import-not-found]
        except ImportError as e:
            raise RuntimeError("DuckDB analytics requires duckdb. pip install duckdb") from e

        conn = duckdb.connect(database=":memory:")
        conn.execute("INSTALL httpfs; LOAD httpfs;")

        endpoint = os.environ.get("NIDP_MINIO_ENDPOINT", "http://nidp-minio:9000")
        # Strip protocol for DuckDB s3_endpoint setting
        s3_endpoint = endpoint.replace("http://", "").replace("https://", "")
        use_ssl = endpoint.startswith("https://")

        conn.execute(f"""
            SET s3_endpoint = '{s3_endpoint}';
            SET s3_access_key_id = '{os.environ.get("NIDP_MINIO_ACCESS_KEY", "nidp-dev")}';
            SET s3_secret_access_key = '{os.environ.get("NIDP_MINIO_SECRET_KEY", "nidp-dev-secret")}';
            SET s3_use_ssl = {str(use_ssl).lower()};
            SET s3_url_style = 'path';
        """)
        _duck_conn = conn
        log.info("DuckDB analytics: connected, MinIO endpoint=%s", s3_endpoint)
        return conn


def _parquet_glob(dataset: str) -> str:
    bucket = os.environ.get("NIDP_S3_BUCKET", "nidp-raw")
    return f"s3://{bucket}/parquet/{dataset}/**/*.parquet"


@router.get("/features/{symbol}", summary="Historical stock features from Parquet (WARM tier)")
async def historical_features(
    symbol: str = Path(...),
    start: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    """Query stock_features_daily Parquet files on MinIO.

    Use this endpoint for date ranges older than ~180 days.
    For recent data use GET /v1/features/stocks/{symbol} (TimescaleDB).
    """
    sym = normalise_symbol(symbol)
    d_start = parse_date(start, field="start")
    d_end = parse_date(end, field="end")

    try:
        conn = _get_duck()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    glob = _parquet_glob("stock_features_daily")
    where_clauses = ["symbol = ?"]
    params: list = [sym]
    if d_start:
        where_clauses.append("as_of_date >= ?")
        params.append(str(d_start))
    if d_end:
        where_clauses.append("as_of_date <= ?")
        params.append(str(d_end))

    where = " AND ".join(where_clauses)
    sql = f"""
        SELECT symbol, as_of_date::varchar AS as_of_date,
               close, sma20, sma50, sma100, sma200,
               rsi14, macd, macd_signal, macd_hist,
               return_5d_pct, return_20d_pct, return_60d_pct,
               volatility_20d, beta_nifty_60d,
               volume, avg_volume_20d
        FROM read_parquet('{glob}', hive_partitioning=true)
        WHERE {where}
        ORDER BY as_of_date DESC
        LIMIT {page['limit']} OFFSET {page['offset']}
    """
    try:
        rows = conn.execute(sql, params).fetchall()
        cols = [d[0] for d in conn.description]
        result = [dict(zip(cols, r)) for r in rows]
    except Exception as e:
        log.warning("DuckDB query failed: %s", e)
        raise HTTPException(status_code=503, detail=f"Parquet query failed: {e}")

    return envelope(result, **page, extra={"symbol": sym, "source": "parquet"})


@router.get("/financials/{symbol}", summary="Historical NSE financials from Parquet (WARM tier)")
async def historical_financials(
    symbol: str = Path(...),
    start: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    """Query nse_financials_quarterly Parquet files on MinIO.

    Use this endpoint for data older than ~5 years.
    For recent data use GET /v1/financials/{symbol} (TimescaleDB).
    """
    sym = normalise_symbol(symbol)
    d_start = parse_date(start, field="start")
    d_end = parse_date(end, field="end")

    try:
        conn = _get_duck()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    glob = _parquet_glob("nse_financials_quarterly")
    where_clauses = ["symbol = ?"]
    params: list = [sym]
    if d_start:
        where_clauses.append("period_end >= ?")
        params.append(str(d_start))
    if d_end:
        where_clauses.append("period_end <= ?")
        params.append(str(d_end))

    where = " AND ".join(where_clauses)
    sql = f"""
        SELECT symbol, period_end::varchar AS period_end, period_type,
               revenue, expenses, profit_after_tax, eps,
               roe, debt_to_equity, profit_margin,
               revenue_growth_yoy, pat_growth_yoy
        FROM read_parquet('{glob}', hive_partitioning=true)
        WHERE {where}
        ORDER BY period_end DESC
        LIMIT {page['limit']} OFFSET {page['offset']}
    """
    try:
        rows = conn.execute(sql, params).fetchall()
        cols = [d[0] for d in conn.description]
        result = [dict(zip(cols, r)) for r in rows]
    except Exception as e:
        log.warning("DuckDB financials query failed: %s", e)
        raise HTTPException(status_code=503, detail=f"Parquet query failed: {e}")

    return envelope(result, **page, extra={"symbol": sym, "source": "parquet"})
