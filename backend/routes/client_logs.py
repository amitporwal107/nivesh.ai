"""Client-side log ingestion → Google Cloud Logging.

The mobile (Android) app POSTs batches of log lines here; we forward them to
Cloud Logging under logName 'nivesh-android-client' so they're visible in the
GCP Logs Explorer without pulling files off the device.

Auth: a shared-secret header (X-Client-Log-Key) matched against the
CLIENT_LOG_KEY secret (DB-first via helpers.secrets, env fallback). If the
secret is unset the endpoint is disabled (503) — fail safe, no open ingest.

The app never holds GCP credentials; this server-side route does the write
using the VM's service account (needs roles/logging.logWriter).
"""
from __future__ import annotations
from fastapi import APIRouter, Request, Header
from fastapi.responses import JSONResponse
from typing import Optional
import logging

from helpers import secrets as _secrets

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

LOG_NAME = "nivesh-android-client"
MAX_ENTRIES = 200          # cap entries forwarded per request
MAX_MSG_LEN = 8000         # cap a single message length

_SEVERITY = {
    "debug": "DEBUG", "info": "INFO", "log": "INFO",
    "warn": "WARNING", "warning": "WARNING",
    "error": "ERROR", "fatal": "CRITICAL",
}

# Lazily-initialised google-cloud-logging logger (None if the lib/credentials
# are unavailable — we then fall back to structured stdout).
_cloud_logger = None
_cloud_init_done = False


def _get_cloud_logger():
    global _cloud_logger, _cloud_init_done
    if _cloud_init_done:
        return _cloud_logger
    _cloud_init_done = True
    try:
        import google.cloud.logging as gcl  # type: ignore
        client = gcl.Client()              # project inferred from SA / metadata
        _cloud_logger = client.logger(LOG_NAME)
        logger.info("client-logs: Cloud Logging initialised (logName=%s)", LOG_NAME)
    except Exception as e:  # noqa: BLE001 — degrade gracefully to stdout
        logger.warning("client-logs: Cloud Logging unavailable (%s); using stdout", type(e).__name__)
        _cloud_logger = None
    return _cloud_logger


@router.post("/client-logs")
async def ingest_client_logs(
    request: Request,
    x_client_log_key: Optional[str] = Header(default=None),
):
    expected = _secrets.get("CLIENT_LOG_KEY")
    if not expected:
        return JSONResponse({"error": "client logging disabled"}, status_code=503)
    if not x_client_log_key or x_client_log_key != expected:
        return JSONResponse({"error": "forbidden"}, status_code=403)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    entries = body.get("entries")
    if not isinstance(entries, list):
        return JSONResponse({"error": "entries must be a list"}, status_code=400)

    meta = body.get("meta") or {}
    base = {
        "client": "android",
        "platform": str(meta.get("platform", ""))[:64],
        "appVersion": str(meta.get("appVersion", ""))[:32],
        "deviceId": str(meta.get("deviceId", ""))[:80],
        "ip": request.client.host if request.client else "",
    }

    clogger = _get_cloud_logger()
    written = 0
    for e in entries[:MAX_ENTRIES]:
        if not isinstance(e, dict):
            continue
        sev = _SEVERITY.get(str(e.get("level", "info")).lower(), "INFO")
        payload = {
            **base,
            "ts": str(e.get("ts", ""))[:40],
            "message": str(e.get("message", ""))[:MAX_MSG_LEN],
        }
        if clogger is not None:
            try:
                clogger.log_struct(payload, severity=sev)
            except Exception:  # noqa: BLE001
                logger.warning("client-logs: forward failed for one entry")
        else:
            logger.info("client-log [%s] %s", sev, payload)
        written += 1

    return JSONResponse({"written": written}, status_code=200)
