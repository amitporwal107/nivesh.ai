#!/usr/bin/env python3
"""One-off migration: copy existing local raw archives → MinIO, update DB pointers.

Usage (run on nidp-stack-vm as the nidp user):
    NIDP_POSTGRES_URL=postgresql://postgres:postgres@localhost:5433/nidp \
    NIDP_MINIO_ENDPOINT=http://nidp-minio:9000 \
    NIDP_MINIO_ACCESS_KEY=nidp-dev \
    NIDP_MINIO_SECRET_KEY=nidp-dev-secret \
    NIDP_S3_BUCKET=nidp-raw \
    python3 migrate_raw_archives_to_minio.py [--dry-run] [--batch 100]

What it does:
    1. Reads all rows in nidp.raw_archive_files where file_path starts with '/'
       (i.e. local disk paths, not already minio:// or s3://)
    2. Uploads each file to MinIO preserving the relative key structure
    3. Updates file_path in the DB to minio://nidp-raw/<key>
    4. Logs progress and skips files already on MinIO

Safe to re-run: idempotent (skips rows already migrated, skips MinIO uploads
if the object already exists).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)


def build_minio_client():
    try:
        import boto3  # type: ignore[import-not-found]
    except ImportError:
        log.error("boto3 not installed. pip install boto3")
        sys.exit(1)

    endpoint = os.environ.get("NIDP_MINIO_ENDPOINT", "http://nidp-minio:9000")
    access_key = os.environ.get("NIDP_MINIO_ACCESS_KEY", "nidp-dev")
    secret_key = os.environ.get("NIDP_MINIO_SECRET_KEY", "nidp-dev-secret")
    bucket = os.environ.get("NIDP_S3_BUCKET", "nidp-raw")

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )

    # Ensure bucket exists
    try:
        client.head_bucket(Bucket=bucket)
        log.info("MinIO bucket '%s' exists", bucket)
    except Exception:
        client.create_bucket(Bucket=bucket)
        log.info("Created MinIO bucket '%s'", bucket)

    return client, bucket


def run(dry_run: bool, batch_size: int) -> None:
    pg_url = os.environ.get("NIDP_POSTGRES_URL")
    if not pg_url:
        log.error("NIDP_POSTGRES_URL not set")
        sys.exit(1)

    s3, bucket = build_minio_client()
    conn = psycopg2.connect(pg_url)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Count work
    cur.execute("""
        SELECT count(*) AS n FROM nidp.raw_archive_files
        WHERE NOT (
            starts_with(file_path, 'minio://')
            OR starts_with(file_path, 's3://')
            OR starts_with(file_path, 'gs://')
        )
    """)
    total = cur.fetchone()["n"]
    log.info("Found %d local raw archive rows to migrate", total)

    # Pre-fetch ALL pending rows into memory to avoid OFFSET-drift pagination bug
    # (migrated rows get removed from the WHERE result set mid-pagination).
    cur.execute("""
        SELECT archive_id, file_path, ingester
        FROM nidp.raw_archive_files
        WHERE NOT (
            starts_with(file_path, 'minio://')
            OR starts_with(file_path, 's3://')
            OR starts_with(file_path, 'gs://')
        )
        ORDER BY archive_id
    """)
    all_rows = cur.fetchall()
    log.info("Fetched %d rows to process", len(all_rows))

    migrated = skipped_missing = skipped_already = errors = 0

    for i in range(0, len(all_rows), batch_size):
        batch = all_rows[i: i + batch_size]
        for row in batch:
            local_path = Path(row["file_path"])
            if not local_path.exists():
                log.warning("Missing local file, skipping: %s", local_path)
                skipped_missing += 1
                continue

            # Derive the MinIO key from the local path
            # Local path: /opt/nidp/repo/backend/data/nidp_raw/<ingester>/YYYY/MM/<hash>.bin
            # Key: raw/<ingester>/YYYY/MM/<hash>.bin  (matches LocalDiskBackend structure)
            try:
                # Find the nidp_raw segment and use everything after it as the key
                parts = local_path.parts
                raw_idx = next(i for i, p in enumerate(parts) if p == "nidp_raw")
                relative_key = "/".join(parts[raw_idx + 1:])
                minio_key = f"raw/{relative_key}"
            except StopIteration:
                # fallback: use ingester + filename
                minio_key = f"raw/{row['ingester']}/{local_path.name}"

            minio_uri = f"minio://{bucket}/{minio_key}"

            # Check if already uploaded
            try:
                s3.head_object(Bucket=bucket, Key=minio_key)
                skipped_already += 1
            except Exception:
                # Upload
                if not dry_run:
                    try:
                        s3.upload_file(str(local_path), bucket, minio_key)
                    except Exception as e:
                        log.error("Upload failed for %s: %s", local_path, e)
                        errors += 1
                        continue
                log.debug("Uploaded %s → %s", local_path, minio_uri)

            # Update DB pointer
            if not dry_run:
                with conn:
                    with conn.cursor() as uc:
                        uc.execute(
                            "UPDATE nidp.raw_archive_files SET file_path = %s WHERE archive_id = %s",
                            (minio_uri, row["archive_id"]),
                        )
            migrated += 1

        log.info(
            "Progress: migrated=%d skipped_missing=%d skipped_already=%d errors=%d / %d total",
            migrated, skipped_missing, skipped_already, errors, total,
        )

    conn.close()
    log.info(
        "Migration complete. migrated=%d skipped_missing=%d skipped_already=%d errors=%d",
        migrated, skipped_missing, skipped_already, errors,
    )

    if not dry_run and errors == 0:
        log.info(
            "All files migrated successfully.\n"
            "Next step: set NIDP_STORAGE_BACKEND=minio in /opt/nidp/nidp.env"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate raw archives from local disk to MinIO")
    parser.add_argument("--dry-run", action="store_true", help="Scan only, no uploads or DB updates")
    parser.add_argument("--batch", type=int, default=100, help="DB batch size (default: 100)")
    args = parser.parse_args()

    if args.dry_run:
        log.info("DRY RUN — no changes will be made")

    run(dry_run=args.dry_run, batch_size=args.batch)
