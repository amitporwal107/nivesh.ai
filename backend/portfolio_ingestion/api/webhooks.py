"""POST /webhooks/casparser/inbound-email (T3.3).

CASParser fires this when an investor forwards their CAS email to their
CASParser inbox address. The webhook body contains the investor's
``external_id`` (set when the SDK was initialised) and a URL to download
the attached PDF.

Enabled only when ``PI_WEBHOOK_ENABLED=true``.  Disabled by default so that
a misconfigured secret can never accidentally accept unauthenticated traffic.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, status

from ..clients import casparser as casparser_client
from ..config import get_settings
from ..db.pool import get_pool
from ..db.repositories import jobs as jobs_repo
from ..schemas.parsed_data import ParsedData
from ..schemas.portfolio import SdkCallbackResponse
from ..schemas.snapshot import ActivationRequest
from ..services import audit as audit_svc
from ..services import parsed_data_archive
from ..services.checksum import pan_hash as pan_hash_fn
from ..services.portfolio_builder import build_holdings
from ..services.portfolio_view import assemble
from ..services.snapshot_engine import _activate_on_conn
from ..services.user_resolver import PanMismatchError, resolve as resolve_user
from ..services.webhook_verify import WebhookSignatureError, verify_signature

log = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/casparser", tags=["webhooks"])


@router.post(
    "/inbound-email",
    status_code=status.HTTP_200_OK,
)
async def inbound_email(
    request: Request,
    x_casparser_signature: Annotated[str | None, Header(alias="X-Casparser-Signature")] = None,
) -> dict:
    """Receive a CASParser inbound-email event, parse PDF, activate snapshot.

    Body shape (CASParser webhook payload):
    ```json
    {
      "external_id": "<user external id>",
      "pan":         "<10-char PAN>",
      "source_type": "MF_CAMS",
      "pdf_url":     "https://...",
      "filename":    "CAS_2026_01.pdf"
    }
    ```
    """
    settings = get_settings()
    if not settings.webhook_enabled:
        raise HTTPException(status_code=404, detail="webhook endpoint not enabled")

    # Read raw body for HMAC verification BEFORE parsing JSON.
    raw_body = await request.body()

    if settings.webhook_secret:
        try:
            verify_signature(raw_body, x_casparser_signature, settings.webhook_secret)
        except WebhookSignatureError as e:
            log.warning(
                "webhook signature invalid",
                extra={"eventType": "WEBHOOK_SIG_FAIL", "reason": str(e)},
            )
            raise HTTPException(status_code=401, detail=str(e)) from e
    else:
        log.warning(
            "PI_WEBHOOK_SECRET not set — skipping signature verification (staging only)",
            extra={"eventType": "WEBHOOK_SIG_SKIP"},
        )

    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(status_code=422, detail="invalid JSON body") from e

    external_id = payload.get("external_id")
    pan = payload.get("pan")
    source_type = payload.get("source_type", "MF_CAMS")
    pdf_url = payload.get("pdf_url")

    if not external_id or not pan:
        raise HTTPException(status_code=422, detail="external_id and pan are required")

    try:
        pan_hash = pan_hash_fn(pan)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    # ── Parse PDF via CASParser ───────────────────────────────────────────
    parsed_data = await _parse_from_url(pdf_url, source_type)

    statement_to = dt.date.today()
    statement_from = statement_to.replace(day=1)
    generated_at = dt.datetime.now(dt.timezone.utc)

    pool = await get_pool()

    # ── Resolve user + upsert job ─────────────────────────────────────────
    async with pool.acquire() as conn:
        try:
            user_id = await resolve_user(
                conn, external_id=external_id, pan_hash=pan_hash, pan=pan,
            )
        except PanMismatchError as e:
            log.warning(
                "PAN mismatch on webhook",
                extra={"eventType": "WEBHOOK_PAN_MISMATCH", "external_id": external_id},
            )
            raise HTTPException(status_code=403, detail=str(e)) from e

        job_id, is_new = await jobs_repo.upsert(
            conn,
            user_id=user_id,
            pan_hash=pan_hash,
            source_type=source_type,
            method="inbox",
            checksum=None,
            pdf_status="downloaded",
            status="received",
        )
        if is_new:
            await audit_svc.job_status(
                conn,
                job_id=job_id, pan_hash=pan_hash,
                old_status=None, new_status="received",
                source_type=source_type, method="inbox",
            )

    holdings = build_holdings(
        parsed_data,
        pan_hash=pan_hash,
        source_type=source_type,
        statement_to=statement_to.isoformat(),
        ingestion_job_id=job_id,
        raw_data_ref=None,
        sdk_method="inbox",
    )

    raw_data_ref = await parsed_data_archive.archive(
        ingestion_job_id=job_id,
        pan_hash=pan_hash,
        source_type=source_type,
        sdk_metadata={"method": "inbox", "pdf_url": pdf_url or ""},
        parsed_data=parsed_data,
    )

    # ── Activate snapshot ─────────────────────────────────────────────────
    async with pool.acquire() as conn:
        await jobs_repo.mark(conn, job_id, status="parsing", raw_data_ref=raw_data_ref)
        await audit_svc.job_status(
            conn,
            job_id=job_id, pan_hash=pan_hash,
            old_status="received", new_status="parsing",
            source_type=source_type, method="inbox",
        )

        activation_req = ActivationRequest(
            job_id=job_id,
            user_id=user_id,
            pan_hash=pan_hash,
            source_type=source_type,
            method="inbox",
            statement_from=statement_from,
            statement_to=statement_to,
            generated_at=generated_at,
            total_value=parsed_data.total_value,
            holdings=holdings,
        )
        try:
            decision = await _activate_on_conn(conn, activation_req)
            await jobs_repo.mark(conn, job_id, status="activated")
            await audit_svc.job_status(
                conn,
                job_id=job_id, pan_hash=pan_hash,
                old_status="parsing", new_status="activated",
                source_type=source_type, method="inbox",
            )
        except Exception as e:
            await jobs_repo.mark(conn, job_id, status="failed",
                                 failure_reason=str(e)[:1024])
            await audit_svc.job_status(
                conn,
                job_id=job_id, pan_hash=pan_hash,
                old_status="parsing", new_status="failed",
                source_type=source_type, method="inbox",
                failure_reason=str(e)[:1024],
            )
            log.exception("webhook activation failed",
                          extra={"eventType": "WEBHOOK_ACTIVATION_FAILED",
                                 "job_id": str(job_id)})
            raise HTTPException(status_code=500, detail="snapshot activation failed") from e

    log.info(
        "webhook inbound-email processed",
        extra={
            "eventType": "WEBHOOK_PROCESSED",
            "job_id": str(job_id),
            "is_active": decision.is_active,
            "reason": decision.reason,
        },
    )

    return {
        "job_id": str(job_id),
        "snapshot_id": str(decision.snapshot_id),
        "is_active": decision.is_active,
        "status": "activated" if decision.is_active else "stored_inactive",
    }


async def _parse_from_url(pdf_url: str | None, source_type: str) -> ParsedData:
    """Mint a token, call CASParser parse. Stub when no API key."""
    token = await casparser_client.mint()

    if token.stub or not pdf_url:
        log.info(
            "casparser parse (stub)",
            extra={"eventType": "CASPARSER_PARSE_STUB", "pdf_url": pdf_url},
        )
        return ParsedData(meta={"source": "stub"}, investor={},
                          demat_accounts=[], mutual_funds=[])

    import httpx
    from ..clients.casparser import CasparserUpstreamError
    settings = get_settings()
    base = settings.casparser_base_url.rstrip("/")

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{base}/v1/parse",
            json={"file_url": pdf_url, "access_token": token.access_token},
            headers={"x-api-key": settings.casparser_api_key or ""},
        )
    if resp.status_code >= 400:
        raise CasparserUpstreamError(f"CASParser parse returned {resp.status_code}")

    body = resp.json()
    return ParsedData.model_validate(body.get("data") or body)
