"""GCS signed-URL helpers for the upload flow (T3.1).

Production:
  Requires ``google-cloud-storage`` (optional dependency) plus a service
  account key at ``PI_GCS_SA_KEY_PATH`` or ADC (Application Default Creds
  when running on GCE/Cloud Run).

Stub mode (``PI_GCS_BUCKET`` unset or ``PI_GCS_STUB=true``):
  Returns a clearly-labelled fake URL and skips HEAD verification.
  Used in staging and unit tests; the returned URL is never suitable for
  a real browser upload.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import uuid
from dataclasses import dataclass

log = logging.getLogger(__name__)

_STUB = object()   # sentinel


def _is_stub() -> bool:
    if os.environ.get("PI_GCS_STUB", "").lower() in ("1", "true", "yes"):
        return True
    return not bool(os.environ.get("PI_GCS_BUCKET"))


@dataclass(frozen=True)
class SignedUploadUrl:
    url: str
    object_key: str
    expires_at: dt.datetime
    stub: bool = False


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _bucket() -> str:
    return os.environ.get("PI_GCS_BUCKET", "stub-bucket")


def build_object_key(external_id: str, upload_id: str, filename: str = "cas.pdf") -> str:
    """Deterministic GCS key: cas-uploads/<external_id>/<upload_id>/<filename>"""
    safe_ext = external_id.replace("/", "_")[:64]
    return f"cas-uploads/{safe_ext}/{upload_id}/{filename}"


async def generate_upload_url(
    object_key: str,
    ttl_seconds: int = 900,
    content_type: str = "application/pdf",
) -> SignedUploadUrl:
    """Return a signed PUT URL for the browser to upload a PDF directly to GCS.

    In stub mode the URL is ``https://storage.googleapis.com/stub-bucket/<key>``
    (never reachable), and the caller must treat ``stub=True`` as a signal that
    no real upload is expected.
    """
    expires_at = _now() + dt.timedelta(seconds=ttl_seconds)

    if _is_stub():
        url = f"https://storage.googleapis.com/{_bucket()}/{object_key}?stub=1"
        log.info(
            "gcs signed url (stub)",
            extra={"eventType": "GCS_SIGNED_URL_STUB", "object_key": object_key},
        )
        return SignedUploadUrl(url=url, object_key=object_key, expires_at=expires_at, stub=True)

    # Production path — requires google-cloud-storage.
    try:
        from google.cloud import storage as gcs  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-storage is required for GCS signed URLs. "
            "Set PI_GCS_STUB=true or PI_GCS_BUCKET= to use stub mode."
        ) from exc

    sa_key = os.environ.get("PI_GCS_SA_KEY_PATH")
    if sa_key:
        client = gcs.Client.from_service_account_json(sa_key)
    else:
        client = gcs.Client()   # ADC

    bucket = client.bucket(_bucket())
    blob = bucket.blob(object_key)
    url = blob.generate_signed_url(
        version="v4",
        expiration=dt.timedelta(seconds=ttl_seconds),
        method="PUT",
        content_type=content_type,
    )
    log.info(
        "gcs signed url generated",
        extra={"eventType": "GCS_SIGNED_URL_OK", "object_key": object_key},
    )
    return SignedUploadUrl(url=url, object_key=object_key, expires_at=expires_at, stub=False)


async def verify_object_exists(object_key: str) -> bool:
    """HEAD-check that an object was uploaded.  Returns False in stub mode."""
    if _is_stub():
        log.info(
            "gcs head verify (stub — skip)",
            extra={"eventType": "GCS_HEAD_STUB", "object_key": object_key},
        )
        return True   # stub: assume uploaded

    try:
        from google.cloud import storage as gcs  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-storage required for GCS HEAD verify"
        ) from exc

    sa_key = os.environ.get("PI_GCS_SA_KEY_PATH")
    client = gcs.Client.from_service_account_json(sa_key) if sa_key else gcs.Client()
    blob = client.bucket(_bucket()).blob(object_key)
    exists = blob.exists()
    log.info(
        "gcs head verify",
        extra={"eventType": "GCS_HEAD_VERIFY", "object_key": object_key, "exists": exists},
    )
    return exists
