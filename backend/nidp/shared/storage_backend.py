"""Pluggable raw-storage backend.

The raw-archive layer keeps original source bytes for replay.
Three implementations:
    LocalDiskBackend  — writes to NIDP_RAW_DIR (default for dev/CI)
    S3Backend         — writes to s3://NIDP_S3_BUCKET/<key>
    MinIOBackend      — writes to minio://NIDP_S3_BUCKET/<key> via local MinIO
                        (S3-compatible; uses NIDP_MINIO_ENDPOINT for endpoint_url)

Selection by env: NIDP_STORAGE_BACKEND ∈ {"local", "s3", "minio"}.
boto3 is imported lazily so dev environments without it still work.

Interface (sync — fits the small object sizes; ingesters batch writes
via raw_archive.store()):

    backend.put(key: str, body: bytes, *, content_type: Optional[str]) -> str
        Returns a canonical "uri" — local file path or s3://… URI.

    backend.get(key: str) -> bytes
        Reads back for replay.

    backend.exists(key: str) -> bool
"""
from __future__ import annotations

import abc
import logging
import os
from pathlib import Path
from typing import Optional

from nidp.shared.config import NIDP_RAW_DIR

logger = logging.getLogger(__name__)


class StorageBackend(abc.ABC):
    @abc.abstractmethod
    def put(self, key: str, body: bytes, *, content_type: Optional[str] = None) -> str: ...

    @abc.abstractmethod
    def get(self, key: str) -> bytes: ...

    @abc.abstractmethod
    def exists(self, key: str) -> bool: ...

    @property
    @abc.abstractmethod
    def scheme(self) -> str: ...


class LocalDiskBackend(StorageBackend):
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = root or NIDP_RAW_DIR
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def scheme(self) -> str:
        return "file"

    def put(self, key: str, body: bytes, *, content_type: Optional[str] = None) -> str:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(body)
        return str(path)

    def get(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    def exists(self, key: str) -> bool:
        return (self.root / key).exists()


class S3Backend(StorageBackend):
    def __init__(self, bucket: Optional[str] = None, prefix: Optional[str] = None) -> None:
        self.bucket = bucket or os.environ.get("NIDP_S3_BUCKET")
        if not self.bucket:
            raise RuntimeError("NIDP_S3_BUCKET not set for S3 storage backend")
        self.prefix = (prefix or os.environ.get("NIDP_S3_PREFIX") or "raw/").rstrip("/") + "/"
        try:
            import boto3  # type: ignore[import-not-found]
        except ImportError as e:                                  # pragma: no cover
            raise RuntimeError(
                "S3 backend requires boto3. pip install boto3."
            ) from e
        self._s3 = boto3.client("s3")

    @property
    def scheme(self) -> str:
        return "s3"

    def _full_key(self, key: str) -> str:
        return f"{self.prefix}{key}"

    def put(self, key: str, body: bytes, *, content_type: Optional[str] = None) -> str:
        full = self._full_key(key)
        kwargs = {"Bucket": self.bucket, "Key": full, "Body": body}
        if content_type:
            kwargs["ContentType"] = content_type
        self._s3.put_object(**kwargs)
        return f"s3://{self.bucket}/{full}"

    def get(self, key: str) -> bytes:
        full = self._full_key(key)
        obj = self._s3.get_object(Bucket=self.bucket, Key=full)
        return obj["Body"].read()

    def exists(self, key: str) -> bool:
        full = self._full_key(key)
        try:
            self._s3.head_object(Bucket=self.bucket, Key=full)
            return True
        except Exception:                                          # noqa: BLE001
            return False


class MinIOBackend(StorageBackend):
    """MinIO backend — S3-compatible, runs on-VM at nidp-minio:9000.

    Required env vars:
        NIDP_S3_BUCKET        — bucket name (e.g. "nidp-raw")
        NIDP_MINIO_ENDPOINT   — MinIO URL (default: http://nidp-minio:9000)
        NIDP_MINIO_ACCESS_KEY — access key (default: minioadmin)
        NIDP_MINIO_SECRET_KEY — secret key (default: minioadmin)
    """

    def __init__(self, bucket: Optional[str] = None, prefix: Optional[str] = None) -> None:
        self.bucket = bucket or os.environ.get("NIDP_S3_BUCKET", "nidp-raw")
        self.prefix = (prefix or os.environ.get("NIDP_S3_PREFIX") or "raw/").rstrip("/") + "/"
        endpoint = os.environ.get("NIDP_MINIO_ENDPOINT", "http://nidp-minio:9000")
        access_key = os.environ.get("NIDP_MINIO_ACCESS_KEY", "minioadmin")
        secret_key = os.environ.get("NIDP_MINIO_SECRET_KEY", "minioadmin")
        try:
            import boto3  # type: ignore[import-not-found]
        except ImportError as e:                                  # pragma: no cover
            raise RuntimeError("MinIO backend requires boto3. pip install boto3.") from e
        self._s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            self._s3.head_bucket(Bucket=self.bucket)
        except Exception:                                          # noqa: BLE001
            self._s3.create_bucket(Bucket=self.bucket)
            logger.info("MinIO: created bucket %s", self.bucket)

    @property
    def scheme(self) -> str:
        return "minio"

    def _full_key(self, key: str) -> str:
        return f"{self.prefix}{key}"

    def put(self, key: str, body: bytes, *, content_type: Optional[str] = None) -> str:
        full = self._full_key(key)
        kwargs: dict = {"Bucket": self.bucket, "Key": full, "Body": body}
        if content_type:
            kwargs["ContentType"] = content_type
        self._s3.put_object(**kwargs)
        return f"minio://{self.bucket}/{full}"

    def get(self, key: str) -> bytes:
        full = self._full_key(key)
        obj = self._s3.get_object(Bucket=self.bucket, Key=full)
        return obj["Body"].read()

    def exists(self, key: str) -> bool:
        full = self._full_key(key)
        try:
            self._s3.head_object(Bucket=self.bucket, Key=full)
            return True
        except Exception:                                          # noqa: BLE001
            return False


class GCSBackend(StorageBackend):
    """Google Cloud Storage backend. Uses Application Default
    Credentials (Cloud Run automatically provides these via the
    runtime service account). Bucket name is read from
    NIDP_S3_BUCKET (kept for env-var compat with the S3 backend)."""

    def __init__(self, bucket: Optional[str] = None, prefix: Optional[str] = None) -> None:
        self.bucket_name = bucket or os.environ.get("NIDP_S3_BUCKET")
        if not self.bucket_name:
            raise RuntimeError("NIDP_S3_BUCKET not set for GCS storage backend")
        self.prefix = (prefix or os.environ.get("NIDP_S3_PREFIX") or "raw/").rstrip("/") + "/"
        try:
            from google.cloud import storage                        # type: ignore[import-not-found]
        except ImportError as e:                                    # pragma: no cover
            raise RuntimeError(
                "GCS backend requires google-cloud-storage. "
                "pip install google-cloud-storage."
            ) from e
        self._client = storage.Client()
        self._bucket = self._client.bucket(self.bucket_name)

    @property
    def scheme(self) -> str:
        return "gs"

    def _full_key(self, key: str) -> str:
        return f"{self.prefix}{key}"

    def put(self, key: str, body: bytes, *, content_type: Optional[str] = None) -> str:
        full = self._full_key(key)
        blob = self._bucket.blob(full)
        if content_type:
            blob.content_type = content_type
        blob.upload_from_string(body, content_type=content_type)
        return f"gs://{self.bucket_name}/{full}"

    def get(self, key: str) -> bytes:
        full = self._full_key(key)
        return self._bucket.blob(full).download_as_bytes()

    def exists(self, key: str) -> bool:
        return self._bucket.blob(self._full_key(key)).exists()


_singleton: Optional[StorageBackend] = None


def get_backend() -> StorageBackend:
    global _singleton
    if _singleton is not None:
        return _singleton
    choice = (os.environ.get("NIDP_STORAGE_BACKEND") or "local").lower()
    if choice == "s3":
        _singleton = S3Backend()
        logger.info("Storage backend: S3 (bucket=%s)", _singleton.bucket)
    elif choice == "gcs":
        _singleton = GCSBackend()
        logger.info("Storage backend: GCS (bucket=%s)", _singleton.bucket_name)
    elif choice == "minio":
        _singleton = MinIOBackend()
        logger.info("Storage backend: MinIO (bucket=%s)", _singleton.bucket)
    else:
        _singleton = LocalDiskBackend()
        logger.info("Storage backend: local (root=%s)", _singleton.root)
    return _singleton


def reset_backend() -> None:
    """Test hook — drop singleton so the next get_backend() re-reads env."""
    global _singleton
    _singleton = None
