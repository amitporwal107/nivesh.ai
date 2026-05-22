"""POST /api/cas/sdk-callback — the SDK-driven happy-path entry point.

Wires T1.4 (job upsert) → T1.5 (archive + flatten) → T1.3 (activate TX) →
:mod:`portfolio_view` (response assembly).

Auth in staging is a thin ``X-User-External-Id`` header; real JWT lands in
a later iteration. The header is required so we never accept anonymous
ingest in production-shaped code paths.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status

from ..db.pool import get_pool
from ..db.repositories import jobs as jobs_repo
from ..schemas.parsed_data import SdkCallbackPayload
from ..schemas.portfolio import SdkCallbackResponse
from ..schemas.snapshot import ActivationRequest
from ..services import parsed_data_archive
from ..services.checksum import pan_hash as pan_hash_fn
from ..services.portfolio_builder import build_holdings
from ..services.portfolio_view import assemble
from ..services.snapshot_engine import _activate_on_conn
from ..services.user_resolver import PanMismatchError, resolve as resolve_user

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cas", tags=["sdk-callback"])


@router.post(
    "/sdk-callback",
    response_model=SdkCallbackResponse,
    status_code=status.HTTP_200_OK,
)
async def sdk_callback(
    payload: SdkCallbackPayload,
    x_user_external_id: Annotated[str, Header(alias="X-User-External-Id")],
) -> SdkCallbackResponse:
    # ── Required derivations ──────────────────────────────────────────────
    investor_pan = (payload.data.investor or {}).get("pan")
    if not investor_pan:
        raise HTTPException(
            status_code=422,
            detail="data.investor.pan is required",
        )
    try:
        pan_hash = pan_hash_fn(investor_pan)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    statement_to = payload.statement_to or dt.date.today()
    statement_from = payload.statement_from or statement_to.replace(day=1)
    generated_at = payload.generated_at or dt.datetime.now(dt.timezone.utc)

    pool = await get_pool()

    # ── Resolve user (create if missing) + job upsert ─────────────────────
    async with pool.acquire() as conn:
        try:
            user_id = await resolve_user(
                conn, external_id=x_user_external_id, pan_hash=pan_hash,
                pan=investor_pan,
            )
        except PanMismatchError as e:
            log.warning(
                "PAN mismatch on SDK callback",
                extra={"eventType": "AUTH_PAN_MISMATCH",
                       "external_id": x_user_external_id},
            )
            raise HTTPException(status_code=403, detail=str(e)) from e

        job_id, is_new = await jobs_repo.upsert(
            conn,
            user_id=user_id,
            pan_hash=pan_hash,
            source_type=payload.source_type,
            method=payload.metadata.method,
            checksum=payload.checksum,
            status="received",
        )

        # If this is a duplicate request, short-circuit: load the snapshot &
        # holdings already attached to this job and return them.
        if not is_new:
            return await _existing_response(conn, job_id, payload)

    # ── New job: archive raw payload then flatten ─────────────────────────
    raw_data_ref = await parsed_data_archive.archive(
        ingestion_job_id=job_id,
        pan_hash=pan_hash,
        source_type=payload.source_type,
        sdk_metadata=payload.metadata.model_dump(),
        parsed_data=payload.data,
    )

    holdings = build_holdings(
        payload.data,
        pan_hash=pan_hash,
        source_type=payload.source_type,
        statement_to=statement_to.isoformat(),
        ingestion_job_id=job_id,
        raw_data_ref=raw_data_ref,
        sdk_method=payload.metadata.method,
    )

    # ── Activate snapshot in one TX ───────────────────────────────────────
    async with pool.acquire() as conn:
        # Mark parsing first so anyone watching the jobs table sees progress
        await jobs_repo.mark(conn, job_id, status="parsing",
                             raw_data_ref=raw_data_ref)

        activation_req = ActivationRequest(
            job_id=job_id,
            user_id=user_id,
            pan_hash=pan_hash,
            source_type=payload.source_type,
            method=payload.metadata.method,
            statement_from=statement_from,
            statement_to=statement_to,
            generated_at=generated_at,
            total_value=payload.data.total_value,
            holdings=holdings,
        )
        try:
            decision = await _activate_on_conn(conn, activation_req)
            await jobs_repo.mark(conn, job_id, status="activated")
        except Exception as e:
            await jobs_repo.mark(conn, job_id, status="failed",
                                 failure_reason=str(e)[:1024])
            log.exception("snapshot activation failed",
                          extra={"eventType": "SNAPSHOT_ACTIVATION_FAILED",
                                 "job_id": str(job_id)})
            raise HTTPException(status_code=500,
                                detail="snapshot activation failed") from e

    portfolio = assemble(holdings if decision.is_active else [])

    return SdkCallbackResponse(
        job_id=job_id,
        snapshot_id=decision.snapshot_id,
        is_new=True,
        is_active=decision.is_active,
        status="activated" if decision.is_active else "stored_inactive",
        portfolio=portfolio,
    )


async def _existing_response(
    conn, job_id, payload: SdkCallbackPayload,
) -> SdkCallbackResponse:
    """Build a 200 response for an idempotent duplicate POST."""
    snap_row = await conn.fetchrow(
        """
        SELECT id, is_active FROM portfolio_ingestion.snapshots
         WHERE ingestion_job_id = $1
         ORDER BY created_at DESC LIMIT 1
        """,
        job_id,
    )
    if snap_row is None:
        # Job exists but no snapshot yet (race window). Return a minimal
        # response so the client can retry.
        log.warning("duplicate job with no snapshot yet",
                    extra={"eventType": "DUPLICATE_NO_SNAPSHOT",
                           "job_id": str(job_id)})
        raise HTTPException(status_code=409,
                            detail="job already received; processing")

    # Re-derive the portfolio from holdings currently attached to this snap
    rows = await conn.fetch(
        """
        SELECT asset_class, name, value
          FROM portfolio_ingestion.holdings
         WHERE snapshot_id = $1
        """,
        snap_row["id"],
    )
    # Minimal HoldingRow-shaped objects for assemble()
    from decimal import Decimal
    from ..schemas.snapshot import HoldingRow
    cheap_holdings = [
        HoldingRow(
            asset_class=r["asset_class"],
            isin=None, amfi_code=None, folio=None, scheme_code=None,
            amc=None, name=r["name"],
            quantity=Decimal("1"), value=r["value"],
            source_trace={},
        )
        for r in rows
    ]
    return SdkCallbackResponse(
        job_id=job_id,
        snapshot_id=snap_row["id"],
        is_new=False,
        is_active=snap_row["is_active"],
        status="activated" if snap_row["is_active"] else "stored_inactive",
        portfolio=assemble(cheap_holdings),
    )
