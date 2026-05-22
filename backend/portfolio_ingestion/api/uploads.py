"""Signed-URL upload flow (T3.1 / T3.2).

POST /api/cas/uploads/init
    Returns a GCS signed PUT URL + upload_id (== the new job's UUID).

POST /api/cas/uploads/complete
    Verifies the object landed in GCS, calls CASParser to parse the PDF,
    then runs the same archive → flatten → activate pipeline as sdk-callback.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status

from ..clients import casparser as casparser_client
from ..db.pool import get_pool
from ..db.repositories import jobs as jobs_repo
from ..schemas.parsed_data import ParsedData, SdkMetadata
from ..schemas.portfolio import SdkCallbackResponse
from ..schemas.snapshot import ActivationRequest
from ..schemas.upload import UploadCompleteRequest, UploadInitRequest, UploadInitResponse
from ..services import audit as audit_svc
from ..services import parsed_data_archive
from ..services.checksum import pan_hash as pan_hash_fn
from ..services.gcs_signed_url import build_object_key, generate_upload_url, verify_object_exists
from ..services.portfolio_builder import build_holdings
from ..services.portfolio_view import assemble
from ..services.snapshot_engine import _activate_on_conn
from ..services.user_resolver import PanMismatchError, resolve as resolve_user

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cas", tags=["uploads"])


@router.post(
    "/uploads/init",
    response_model=UploadInitResponse,
    status_code=status.HTTP_200_OK,
)
async def uploads_init(
    body: UploadInitRequest,
    x_user_external_id: Annotated[str, Header(alias="X-User-External-Id")],
    x_user_pan: Annotated[str, Header(alias="X-User-Pan")],
) -> UploadInitResponse:
    """Mint a signed GCS PUT URL; create a job in pending_upload state.

    The caller should:
      1. PUT the PDF bytes directly to ``upload_url``.
      2. POST ``{upload_id, checksum}`` to ``/uploads/complete``.

    ``X-User-Pan`` is the investor's raw PAN (10 chars). In a JWT-based
    production setup this comes from the verified token instead.
    """
    try:
        pan_hash = pan_hash_fn(x_user_pan)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    upload_id = uuid.uuid4()
    object_key = build_object_key(x_user_external_id, str(upload_id), body.filename)

    signed = await generate_upload_url(object_key)

    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            user_id = await resolve_user(
                conn, external_id=x_user_external_id, pan_hash=pan_hash,
                pan=x_user_pan,
            )
        except PanMismatchError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e

        job_id = await jobs_repo.insert_pending_upload(
            conn,
            user_id=user_id,
            pan_hash=pan_hash,
            source_type=body.source_type,
            pdf_gcs_key=object_key,
        )
        await audit_svc.job_status(
            conn,
            job_id=job_id, pan_hash=pan_hash,
            old_status=None, new_status="pending_upload",
            source_type=body.source_type, method="upload",
        )

    log.info(
        "upload init",
        extra={
            "eventType": "UPLOAD_INIT",
            "job_id": str(job_id),
            "object_key": object_key,
            "stub": signed.stub,
        },
    )

    return UploadInitResponse(
        upload_id=job_id,
        upload_url=signed.url,
        object_key=signed.object_key,
        expires_at=signed.expires_at,
        stub=signed.stub,
    )


@router.post(
    "/uploads/complete",
    response_model=SdkCallbackResponse,
    status_code=status.HTTP_200_OK,
)
async def uploads_complete(
    body: UploadCompleteRequest,
    x_user_external_id: Annotated[str, Header(alias="X-User-External-Id")],
    x_user_pan: Annotated[str, Header(alias="X-User-Pan")],
) -> SdkCallbackResponse:
    """Verify the upload landed, parse via CASParser, activate snapshot."""
    try:
        pan_hash = pan_hash_fn(x_user_pan)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    pool = await get_pool()

    # ── Load the pending_upload job ───────────────────────────────────────
    async with pool.acquire() as conn:
        job = await jobs_repo.get(conn, body.upload_id)

    if job is None:
        raise HTTPException(status_code=404, detail="upload_id not found")
    if job.pan_hash != pan_hash:
        raise HTTPException(status_code=403, detail="upload_id does not belong to this user")
    if job.status not in ("pending_upload", "received"):
        raise HTTPException(
            status_code=409,
            detail=f"job already in status '{job.status}'; cannot complete again",
        )

    # ── Verify GCS object exists ──────────────────────────────────────────
    if job.pdf_gcs_key:
        exists = await verify_object_exists(job.pdf_gcs_key)
        if not exists:
            raise HTTPException(
                status_code=422,
                detail="PDF has not been uploaded yet; PUT to upload_url first",
            )

    # ── Mark received + update checksum if supplied ───────────────────────
    async with pool.acquire() as conn:
        await jobs_repo.mark(conn, body.upload_id, status="received",
                             pdf_status="downloaded")
        await audit_svc.job_status(
            conn,
            job_id=body.upload_id, pan_hash=pan_hash,
            old_status="pending_upload", new_status="received",
            source_type=job.source_type, method=job.method,
        )

    # ── Call CASParser to parse the PDF server-side ───────────────────────
    parsed_data = await _parse_pdf(job.pdf_gcs_key or "", job.source_type)

    # ── Derive statement dates from parsed data (or use safe defaults) ────
    statement_to = dt.date.today()
    statement_from = statement_to.replace(day=1)
    generated_at = dt.datetime.now(dt.timezone.utc)

    holdings = build_holdings(
        parsed_data,
        pan_hash=pan_hash,
        source_type=job.source_type,
        statement_to=statement_to.isoformat(),
        ingestion_job_id=body.upload_id,
        raw_data_ref=None,
        sdk_method=job.method,
    )

    raw_data_ref = await parsed_data_archive.archive(
        ingestion_job_id=body.upload_id,
        pan_hash=pan_hash,
        source_type=job.source_type,
        sdk_metadata={"method": job.method, "source": "gcs_upload"},
        parsed_data=parsed_data,
    )

    # ── Activate snapshot ─────────────────────────────────────────────────
    async with pool.acquire() as conn:
        await jobs_repo.mark(conn, body.upload_id, status="parsing",
                             raw_data_ref=raw_data_ref)
        await audit_svc.job_status(
            conn,
            job_id=body.upload_id, pan_hash=pan_hash,
            old_status="received", new_status="parsing",
            source_type=job.source_type, method=job.method,
        )

        activation_req = ActivationRequest(
            job_id=body.upload_id,
            user_id=job.user_id,
            pan_hash=pan_hash,
            source_type=job.source_type,
            method=job.method,
            statement_from=statement_from,
            statement_to=statement_to,
            generated_at=generated_at,
            total_value=parsed_data.total_value,
            holdings=holdings,
        )
        try:
            decision = await _activate_on_conn(conn, activation_req)
            await jobs_repo.mark(conn, body.upload_id, status="activated")
            await audit_svc.job_status(
                conn,
                job_id=body.upload_id, pan_hash=pan_hash,
                old_status="parsing", new_status="activated",
                source_type=job.source_type, method=job.method,
            )
        except Exception as e:
            await jobs_repo.mark(conn, body.upload_id, status="failed",
                                 failure_reason=str(e)[:1024])
            await audit_svc.job_status(
                conn,
                job_id=body.upload_id, pan_hash=pan_hash,
                old_status="parsing", new_status="failed",
                source_type=job.source_type, method=job.method,
                failure_reason=str(e)[:1024],
            )
            log.exception("upload complete: activation failed",
                          extra={"eventType": "UPLOAD_ACTIVATION_FAILED",
                                 "job_id": str(body.upload_id)})
            raise HTTPException(status_code=500, detail="snapshot activation failed") from e

    portfolio = assemble(holdings if decision.is_active else [])
    return SdkCallbackResponse(
        job_id=body.upload_id,
        snapshot_id=decision.snapshot_id,
        is_new=True,
        is_active=decision.is_active,
        status="activated" if decision.is_active else "stored_inactive",
        raw_pdf_available=True,
        portfolio=portfolio,
    )


async def _parse_pdf(gcs_key: str, source_type: str) -> ParsedData:
    """Call CASParser to parse the uploaded PDF; stub when no API key."""
    token = await casparser_client.mint()

    if token.stub:
        log.info(
            "casparser parse (stub — returning empty ParsedData)",
            extra={"eventType": "CASPARSER_PARSE_STUB", "gcs_key": gcs_key},
        )
        return ParsedData(
            meta={"source": "stub"},
            investor={},
            demat_accounts=[],
            mutual_funds=[],
        )

    # Real call: POST /v1/parse with the GCS public-read URL (or signed URL)
    import httpx
    from ..clients.casparser import CasparserUpstreamError
    from ..config import get_settings
    settings = get_settings()
    base = settings.casparser_base_url.rstrip("/")
    gcs_url = f"https://storage.googleapis.com/{os.environ.get('PI_GCS_BUCKET','')}/{gcs_key}"

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{base}/v1/parse",
            json={"file_url": gcs_url, "access_token": token.access_token},
            headers={"x-api-key": settings.casparser_api_key or "", "accept": "application/json"},
        )
    if resp.status_code >= 400:
        raise CasparserUpstreamError(f"CASParser parse returned {resp.status_code}")

    body = resp.json()
    raw = body.get("data") or body
    return ParsedData.model_validate(raw)


