"""Parquet exporter — exports WARM-tier tables to MinIO as partitioned Parquet files.

Exports:
    nidp.stock_features_daily       → parquet/stock_features_daily/year=YYYY/month=MM/
    nidp.nse_financials_quarterly   → parquet/nse_financials_quarterly/year=YYYY/quarter=Q/

Designed to run daily after price feed. Exports yesterday's partition (or a
specified date range). Idempotent: skips partitions already present in MinIO.

This is the WARM layer — once exported, TimescaleDB retention policies can
drop old chunks and queries route to DuckDB → MinIO Parquet instead.
"""
from __future__ import annotations

import io
import logging
import os
from datetime import date, timedelta
from typing import Optional

log = logging.getLogger(__name__)


async def run(target_date: Optional[date] = None) -> dict:
    """Export yesterday's data (or target_date) to Parquet on MinIO."""
    export_date = target_date or (date.today() - timedelta(days=1))

    log.info("Parquet export starting for date=%s", export_date)

    try:
        import pyarrow as pa          # type: ignore[import-not-found]
        import pyarrow.parquet as pq  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError("parquet_exporter requires pyarrow. pip install pyarrow") from e

    s3 = _get_minio_client()
    bucket = os.environ.get("NIDP_S3_BUCKET", "nidp-raw")
    _ensure_bucket(s3, bucket)

    results: dict[str, int] = {}

    results["stock_features_daily"] = await _export_stock_features(
        s3, bucket, pa, pq, export_date
    )
    results["nse_financials_quarterly"] = await _export_nse_financials(
        s3, bucket, pa, pq, export_date
    )

    total_rows = sum(results.values())
    log.info("Parquet export complete: %s total_rows=%d", results, total_rows)
    return {"exported": results, "date": str(export_date), "total_rows": total_rows}


async def _export_stock_features(s3, bucket, pa, pq, export_date: date) -> int:
    from nidp.shared.storage.pg import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT symbol, as_of_date,
                   close, sma20, sma50, sma100, sma200,
                   sma50_slope, dist_200dma_pct, dist_52w_high_pct, dist_52w_low_pct,
                   rsi14, macd, macd_signal, macd_hist,
                   return_5d_pct, return_20d_pct, return_60d_pct,
                   volatility_20d, beta_nifty_60d, volume, avg_volume_20d,
                   source, source_run_id, ingested_at
            FROM nidp.stock_features_daily
            WHERE as_of_date = $1
            ORDER BY symbol
        """, export_date)

    if not rows:
        log.info("stock_features_daily: no rows for %s, skipping", export_date)
        return 0

    key = (
        f"parquet/stock_features_daily/"
        f"year={export_date.year}/month={export_date.month:02d}/"
        f"{export_date.isoformat()}.parquet"
    )

    if _object_exists(s3, bucket, key):
        log.info("stock_features_daily: %s already in MinIO, skipping", key)
        return len(rows)

    table = pa.Table.from_pylist([dict(r) for r in rows])
    _upload_parquet(s3, bucket, key, table, pq)
    log.info("stock_features_daily: exported %d rows → minio://%s/%s", len(rows), bucket, key)
    return len(rows)


async def _export_nse_financials(s3, bucket, pa, pq, export_date: date) -> int:
    """Export nse_financials_quarterly rows whose ingested_at falls on export_date."""
    from nidp.shared.storage.pg import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT symbol, period_end, period_type,
                   revenue, expenses, profit_after_tax, eps,
                   roe, debt_to_equity, profit_margin,
                   revenue_growth_yoy, pat_growth_yoy,
                   source, source_run_id, ingested_at
            FROM nidp.nse_financials_quarterly
            WHERE ingested_at::date = $1
            ORDER BY symbol, period_end
        """, export_date)

    if not rows:
        log.info("nse_financials_quarterly: no new rows for ingested_at=%s", export_date)
        return 0

    # Partition by year/quarter of period_end
    quarter = (export_date.month - 1) // 3 + 1
    key = (
        f"parquet/nse_financials_quarterly/"
        f"year={export_date.year}/quarter=Q{quarter}/"
        f"ingested_{export_date.isoformat()}.parquet"
    )

    if _object_exists(s3, bucket, key):
        log.info("nse_financials_quarterly: %s already in MinIO, skipping", key)
        return len(rows)

    table = pa.Table.from_pylist([dict(r) for r in rows])
    _upload_parquet(s3, bucket, key, table, pq)
    log.info("nse_financials_quarterly: exported %d rows → minio://%s/%s", len(rows), bucket, key)
    return len(rows)


def _get_minio_client():
    try:
        import boto3  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError("parquet_exporter requires boto3. pip install boto3") from e

    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("NIDP_MINIO_ENDPOINT", "http://nidp-minio:9000"),
        aws_access_key_id=os.environ.get("NIDP_MINIO_ACCESS_KEY", "nidp-dev"),
        aws_secret_access_key=os.environ.get("NIDP_MINIO_SECRET_KEY", "nidp-dev-secret"),
    )


def _ensure_bucket(s3, bucket: str) -> None:
    try:
        s3.head_bucket(Bucket=bucket)
    except Exception:
        s3.create_bucket(Bucket=bucket)
        log.info("Created MinIO bucket: %s", bucket)


def _object_exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def _upload_parquet(s3, bucket: str, key: str, table, pq) -> None:
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    buf.seek(0)
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=buf.getvalue(),
        ContentType="application/octet-stream",
    )
