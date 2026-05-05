"""Parsed-rows archive — persist normalized JSONL after parse+validate.

Counterpart to raw_archive.py:
    raw_archive    → original source bytes, byte-identical to upstream
    parsed_archive → normalized rows AFTER parse+validate, gzipped JSONL

Why both?
    - Raw lets us re-parse old data when parsers improve.
    - Parsed lets us skip parsing entirely when only the storage
      schema or downstream model changes — replay reads JSONL and
      re-runs persist.

Storage layout (under storage backend root):
    parsed/<ingester>/<YYYY>/<MM>/<sha12>.jsonl.gz
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import logging
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from nidp.shared.storage.pg import get_pool
from nidp.shared.storage_backend import get_backend

logger = logging.getLogger(__name__)


def _serialize(rows: list[dict]) -> bytes:
    """Encode rows as gzipped UTF-8 JSONL. Stable key order so the
    sha256 is deterministic across runs that produce identical data."""
    def _default(o: Any) -> Any:
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        if isinstance(o, uuid.UUID):
            return str(o)
        return str(o)

    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        for r in rows:
            gz.write(json.dumps(r, default=_default, sort_keys=True).encode("utf-8"))
            gz.write(b"\n")
    return buf.getvalue()


def _key_for(ingester: str, snapshot_date: date, sha: str) -> str:
    return (
        f"parsed/{ingester}/{snapshot_date.strftime('%Y')}/"
        f"{snapshot_date.strftime('%m')}/{sha[:12]}.jsonl.gz"
    )


async def store_parsed(
    *,
    ingester: str,
    snapshot_date: date,
    target_date: Optional[date],
    job_run_id: uuid.UUID,
    rows: list[dict],
    raw_archive_id: Optional[uuid.UUID] = None,
    schema_name: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> tuple[uuid.UUID, str, str]:
    """Write parsed rows as gzipped JSONL to the storage backend and
    index in nidp.parsed_archive_files.

    Returns (parsed_id, storage_uri, file_sha256).
    """
    body = _serialize(rows)
    sha = hashlib.sha256(body).hexdigest()
    key = _key_for(ingester, snapshot_date, sha)
    backend = get_backend()
    storage_uri = backend.put(key, body, content_type="application/gzip")

    parsed_id = uuid.uuid4()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO nidp.parsed_archive_files
                (parsed_id, ingester, target_date, snapshot_date, job_run_id,
                 raw_archive_id, file_path, file_bytes, file_sha256,
                 row_count, format, schema_name, metadata)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'jsonl.gz',$11,$12::jsonb)
            ON CONFLICT (job_run_id, file_sha256) DO NOTHING
            """,
            parsed_id, ingester, target_date, snapshot_date, job_run_id,
            raw_archive_id, storage_uri, len(body), sha,
            len(rows), schema_name,
            json.dumps(metadata or {}, default=str),
        )
    logger.info(
        "parsed_archive %s/%s rows=%d bytes=%d sha=%s…",
        ingester, key, len(rows), len(body), sha[:8],
    )
    return parsed_id, storage_uri, sha


async def upsert_feed_snapshot(
    *,
    ingester: str,
    snapshot_date: date,
    target_date: Optional[date],
    job_run_id: uuid.UUID,
    rows: list[dict],
    raw_archive_id: Optional[uuid.UUID] = None,
    parsed_archive_id: Optional[uuid.UUID] = None,
) -> None:
    """Upsert one row in nidp.feed_snapshot for (ingester, snapshot_date).

    rows_payload stores the parsed rows themselves so a model rebuild
    can replay any past day with a single SELECT — no object-store
    round-trip needed.
    """
    def _default(o: Any) -> Any:
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        if isinstance(o, uuid.UUID):
            return str(o)
        return str(o)

    payload_json = json.dumps(rows, default=_default, sort_keys=True)
    payload_sha = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO nidp.feed_snapshot
                (ingester, snapshot_date, target_date, job_run_id,
                 raw_archive_id, parsed_archive_id, row_count,
                 rows_payload, payload_sha256, captured_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9, NOW())
            ON CONFLICT (ingester, snapshot_date) DO UPDATE SET
                target_date       = EXCLUDED.target_date,
                job_run_id        = EXCLUDED.job_run_id,
                raw_archive_id    = EXCLUDED.raw_archive_id,
                parsed_archive_id = EXCLUDED.parsed_archive_id,
                row_count         = EXCLUDED.row_count,
                rows_payload      = EXCLUDED.rows_payload,
                payload_sha256    = EXCLUDED.payload_sha256,
                captured_at       = NOW()
            """,
            ingester, snapshot_date, target_date, job_run_id,
            raw_archive_id, parsed_archive_id, len(rows),
            payload_json, payload_sha,
        )
    logger.info(
        "feed_snapshot upsert ingester=%s snapshot_date=%s rows=%d sha=%s…",
        ingester, snapshot_date, len(rows), payload_sha[:8],
    )
