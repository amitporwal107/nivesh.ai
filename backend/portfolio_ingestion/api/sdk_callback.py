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
from ..services import audit as audit_svc
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

    # Statement period — prefer the SDK's top-level fields, then look inside
    # ParsedData.meta/summary for the CASParser SDK's standard shape. Falling
    # back to "today" is a last resort and breaks source priority, so we try
    # hard to find the real date.
    statement_from, statement_to, generated_at = _resolve_statement_dates(payload)

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

        is_cdsl_fetch = payload.metadata.method == "cdsl_fetch"
        job_id, is_new = await jobs_repo.upsert(
            conn,
            user_id=user_id,
            pan_hash=pan_hash,
            source_type=payload.source_type,
            method=payload.metadata.method,
            checksum=payload.checksum,
            status="received",
            pdf_status="unavailable" if is_cdsl_fetch else None,
        )

        if is_new:
            await audit_svc.job_status(
                conn,
                job_id=job_id, pan_hash=pan_hash,
                old_status=None, new_status="received",
                source_type=payload.source_type, method=payload.metadata.method,
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
        await audit_svc.job_status(
            conn,
            job_id=job_id, pan_hash=pan_hash,
            old_status="received", new_status="parsing",
            source_type=payload.source_type, method=payload.metadata.method,
        )

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
            await audit_svc.job_status(
                conn,
                job_id=job_id, pan_hash=pan_hash,
                old_status="parsing", new_status="activated",
                source_type=payload.source_type, method=payload.metadata.method,
            )
        except Exception as e:
            await jobs_repo.mark(conn, job_id, status="failed",
                                 failure_reason=str(e)[:1024])
            await audit_svc.job_status(
                conn,
                job_id=job_id, pan_hash=pan_hash,
                old_status="parsing", new_status="failed",
                source_type=payload.source_type, method=payload.metadata.method,
                failure_reason=str(e)[:1024],
            )
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
        raw_pdf_available=payload.metadata.raw_pdf_available,
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
        raw_pdf_available=payload.metadata.raw_pdf_available,
        portfolio=assemble(cheap_holdings),
    )


# ── Statement-date resolution ────────────────────────────────────────────
# The CASParser SDK does not consistently echo the statement period at the
# top level of its callback. Real-world payloads put the dates in any of:
#   data.meta.statement_period.{from,to}
#   data.summary.statement_period.{from,to}
#   data.statement_period.{from,to}
#   data.meta.{from_date,to_date}
#   data.meta.{period_from,period_to}
# We accept all of them, parse robustly, and fall back to a today/month-default
# only if absolutely nothing was found.

_DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d %b %Y", "%d-%B-%Y")


def _parse_date_loose(value: object) -> "dt.date | None":
    if value is None or value == "":
        return None
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.datetime):
        return value.date()
    s = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # ISO-8601 with timezone
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _resolve_statement_dates(payload) -> tuple["dt.date", "dt.date", "dt.datetime"]:
    """Pick the best statement_from / statement_to / generated_at we can find."""
    meta = (payload.data.meta or {}) if hasattr(payload.data, "meta") else {}
    summary = (payload.data.summary or {}) if hasattr(payload.data, "summary") else {}
    # Top-level on ParsedData itself (some SDK versions hoist these up).
    root = {}
    try:
        root = payload.data.model_dump(exclude_none=True)
    except Exception:
        pass

    def _from_any(*paths: tuple) -> dt.date | None:
        for src, keys in paths:
            cur = src
            for k in keys:
                if not isinstance(cur, dict):
                    cur = None
                    break
                cur = cur.get(k)
            d = _parse_date_loose(cur)
            if d is not None:
                return d
        return None

    statement_to = payload.statement_to or _from_any(
        (meta, ("statement_period", "to")),
        (summary, ("statement_period", "to")),
        (root, ("statement_period", "to")),
        (meta, ("to_date",)),
        (meta, ("period_to",)),
        (meta, ("statement_to",)),
    ) or dt.date.today()

    statement_from = payload.statement_from or _from_any(
        (meta, ("statement_period", "from")),
        (summary, ("statement_period", "from")),
        (root, ("statement_period", "from")),
        (meta, ("from_date",)),
        (meta, ("period_from",)),
        (meta, ("statement_from",)),
    ) or statement_to.replace(day=1)

    # generated_at: SDK's parse time, not statement boundary.
    gen_raw = (
        payload.generated_at
        or meta.get("generated_at")
        or meta.get("parsed_at")
        or meta.get("timestamp")
    )
    if isinstance(gen_raw, dt.datetime):
        generated_at = gen_raw
    elif isinstance(gen_raw, str):
        try:
            generated_at = dt.datetime.fromisoformat(gen_raw.replace("Z", "+00:00"))
        except ValueError:
            generated_at = dt.datetime.now(dt.timezone.utc)
    else:
        generated_at = dt.datetime.now(dt.timezone.utc)

    return statement_from, statement_to, generated_at
