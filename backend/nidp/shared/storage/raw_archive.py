"""Raw-file archive — persist source bytes verbatim before parsing.

PRD §14: idempotent ingestion, replayable substrate. The archive lets
us replay ingestion from disk/S3 when parsers change, without
re-fetching from upstream sources. The DB table indexes the stored
files by (ingester, target_date, sha256).

Storage location is pluggable: LocalDiskBackend by default,
S3Backend in prod. See nidp/shared/storage_backend.py.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import date
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from nidp.shared.storage.pg import get_pool
from nidp.shared.storage_backend import get_backend

logger = logging.getLogger(__name__)


def _basename_for(url: str, sha: str) -> str:
    path = urlsplit(url).path
    suffix = Path(path).suffix or ".bin"
    return f"{sha[:12]}{suffix}"


def _key_for(ingester: str, target_date: Optional[date], url: str, sha: str) -> str:
    yyyy = (target_date or date.today()).strftime("%Y")
    mm = (target_date or date.today()).strftime("%m")
    return f"{ingester}/{yyyy}/{mm}/{_basename_for(url, sha)}"


async def store(
    *,
    ingester: str,
    target_date: Optional[date],
    source_url: str,
    body: bytes,
    http_status: int,
    content_type: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> tuple[uuid.UUID, str]:
    """Write `body` via the active StorageBackend and index it.
    Returns (archive_id, storage_uri).

    De-dup: if the same (ingester, sha256) already exists, returns
    the existing row's id and uri without re-writing.
    """
    sha = hashlib.sha256(body).hexdigest()
    key = _key_for(ingester, target_date, source_url, sha)
    backend = get_backend()

    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            """
            SELECT archive_id, file_path FROM nidp.raw_archive_files
             WHERE ingester = $1 AND file_sha256 = $2
             LIMIT 1
            """,
            ingester, sha,
        )
        if existing:
            return existing["archive_id"], existing["file_path"]

        storage_uri = backend.put(key, body, content_type=content_type)

        archive_id = uuid.uuid4()
        await conn.execute(
            """
            INSERT INTO nidp.raw_archive_files
                (archive_id, ingester, target_date, source_url, file_path,
                 file_bytes, file_sha256, content_type, http_status, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb)
            """,
            archive_id, ingester, target_date, source_url, storage_uri,
            len(body), sha, content_type, http_status,
            _json_dumps(metadata or {}),
        )
    logger.info(
        "archived %s/%s (%d bytes, sha=%s…, backend=%s)",
        ingester, key, len(body), sha[:8], backend.scheme,
    )
    return archive_id, storage_uri


def _json_dumps(d: dict) -> str:
    import json
    return json.dumps(d, default=str)
