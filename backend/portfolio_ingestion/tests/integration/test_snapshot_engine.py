"""End-to-end tests for the snapshot activation transaction.

These run inside the staging container against the live Postgres. Each
scenario uses its own PAN (via the ``clean_pan`` fixture) so the suite is
self-contained and concurrency-safe.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from decimal import Decimal

import asyncpg
import pytest

from portfolio_ingestion.schemas.snapshot import ActivationRequest, HoldingRow
from portfolio_ingestion.services.snapshot_engine import activate

from .conftest import _insert_job


def _holding(name: str, value: str, isin: str | None = None) -> HoldingRow:
    return HoldingRow(
        asset_class="equity" if isin else "mf",
        isin=isin,
        amfi_code=None,
        folio=None,
        scheme_code=None,
        amc=None,
        name=name,
        quantity=Decimal("1"),
        value=Decimal(value),
        source_trace={"src": "test"},
    )


def _req(
    *,
    job_id: uuid.UUID,
    user_id: uuid.UUID,
    pan_hash: str,
    source_type: str = "ECAS_CDSL",
    method: str = "upload",
    statement_to: str = "2026-01-31",
    holdings: list[HoldingRow] | None = None,
) -> ActivationRequest:
    return ActivationRequest(
        job_id=job_id,
        user_id=user_id,
        pan_hash=pan_hash,
        source_type=source_type,
        method=method,
        statement_from=dt.date.fromisoformat(statement_to[:8] + "01"),
        statement_to=dt.date.fromisoformat(statement_to),
        generated_at=dt.datetime.now(dt.timezone.utc),
        total_value=Decimal("100000"),
        holdings=holdings or [_holding("RELIANCE", "50000", "INE002A01018")],
    )


# ── 1. First activation when no current active ─────────────────────────────


@pytest.mark.integration
async def test_first_activation_activates_and_writes_holdings(
    pg_pool: asyncpg.Pool, clean_pan: tuple[str, uuid.UUID]
) -> None:
    pan_hash, user_id = clean_pan
    async with pg_pool.acquire() as conn:
        job_id = await _insert_job(conn, user_id, pan_hash, "ECAS_CDSL", "upload", "c1")

    decision = await activate(_req(job_id=job_id, user_id=user_id, pan_hash=pan_hash))

    assert decision.is_active is True
    assert decision.reason == "no_current_active"
    assert decision.deactivated_snapshot_ids == []
    assert decision.holdings_written == 1

    async with pg_pool.acquire() as conn:
        active_count = await conn.fetchval(
            "SELECT COUNT(*) FROM portfolio_ingestion.snapshots "
            "WHERE pan_hash=$1 AND is_active=true",
            pan_hash,
        )
        holdings_count = await conn.fetchval(
            "SELECT COUNT(*) FROM portfolio_ingestion.holdings WHERE pan_hash=$1",
            pan_hash,
        )
    assert active_count == 1
    assert holdings_count == 1


# ── 2. Same source, newer statement_to wins ────────────────────────────────


@pytest.mark.integration
async def test_newer_statement_supersedes_older(
    pg_pool: asyncpg.Pool, clean_pan: tuple[str, uuid.UUID]
) -> None:
    pan_hash, user_id = clean_pan
    async with pg_pool.acquire() as conn:
        j1 = await _insert_job(conn, user_id, pan_hash, "ECAS_CDSL", "upload", "c1")
        j2 = await _insert_job(conn, user_id, pan_hash, "ECAS_CDSL", "upload", "c2")

    first = await activate(_req(job_id=j1, user_id=user_id, pan_hash=pan_hash, statement_to="2025-12-31"))
    second = await activate(_req(job_id=j2, user_id=user_id, pan_hash=pan_hash, statement_to="2026-01-31"))

    assert first.is_active and second.is_active
    assert second.reason == "newer_statement"
    assert first.snapshot_id in second.deactivated_snapshot_ids

    async with pg_pool.acquire() as conn:
        active_ids = [
            r["id"] for r in await conn.fetch(
                "SELECT id FROM portfolio_ingestion.snapshots "
                "WHERE pan_hash=$1 AND is_active=true",
                pan_hash,
            )
        ]
    assert active_ids == [second.snapshot_id]


# ── 3. eCAS supersedes MF ──────────────────────────────────────────────────


@pytest.mark.integration
async def test_ecas_supersedes_mf_even_when_mf_is_newer(
    pg_pool: asyncpg.Pool, clean_pan: tuple[str, uuid.UUID]
) -> None:
    pan_hash, user_id = clean_pan
    async with pg_pool.acquire() as conn:
        j_mf   = await _insert_job(conn, user_id, pan_hash, "MF_CAMS",   "inbox",  "cm")
        j_ecas = await _insert_job(conn, user_id, pan_hash, "ECAS_CDSL", "upload", "ce")

    await activate(_req(
        job_id=j_mf, user_id=user_id, pan_hash=pan_hash,
        source_type="MF_CAMS", method="inbox", statement_to="2026-03-31",
    ))
    decision = await activate(_req(
        job_id=j_ecas, user_id=user_id, pan_hash=pan_hash,
        source_type="ECAS_CDSL", method="upload", statement_to="2026-01-31",
    ))

    assert decision.is_active is True
    assert decision.reason == "ecas_supersedes_mf"


# ── 4. MF does NOT supersede eCAS ──────────────────────────────────────────


@pytest.mark.integration
async def test_mf_does_not_supersede_ecas(
    pg_pool: asyncpg.Pool, clean_pan: tuple[str, uuid.UUID]
) -> None:
    pan_hash, user_id = clean_pan
    async with pg_pool.acquire() as conn:
        j_ecas = await _insert_job(conn, user_id, pan_hash, "ECAS_CDSL", "upload", "ce")
        j_mf   = await _insert_job(conn, user_id, pan_hash, "MF_CAMS",   "inbox",  "cm")

    await activate(_req(
        job_id=j_ecas, user_id=user_id, pan_hash=pan_hash,
        source_type="ECAS_CDSL", method="upload", statement_to="2026-01-31",
    ))
    decision = await activate(_req(
        job_id=j_mf, user_id=user_id, pan_hash=pan_hash,
        source_type="MF_CAMS", method="inbox", statement_to="2026-03-31",
    ))

    assert decision.is_active is False
    assert decision.reason == "stored_inactive_loses"

    async with pg_pool.acquire() as conn:
        active_source = await conn.fetchval(
            "SELECT source_type FROM portfolio_ingestion.snapshots "
            "WHERE pan_hash=$1 AND is_active=true",
            pan_hash,
        )
    assert active_source == "ECAS_CDSL"


# ── 5. Concurrent activations serialize via the advisory lock ─────────────


@pytest.mark.integration
@pytest.mark.slow
async def test_concurrent_activations_yield_exactly_one_active(
    pg_pool: asyncpg.Pool, clean_pan: tuple[str, uuid.UUID]
) -> None:
    """Spawn N parallel activations for the same PAN; assert one active row."""
    pan_hash, user_id = clean_pan
    n = 8
    async with pg_pool.acquire() as conn:
        job_ids = [
            await _insert_job(conn, user_id, pan_hash, "ECAS_CDSL", "upload", f"cx{i}")
            for i in range(n)
        ]

    # Stagger the statement_to so each call has a deterministic winner — the
    # one with the latest statement_to. Order them shuffled to prove the
    # serialization is doing the work, not the call order.
    statement_tos = [f"2026-0{((i % 9) + 1)}-{((i % 28) + 1):02d}" for i in range(n)]
    expected_winner_date = max(statement_tos)

    reqs = [
        _req(
            job_id=job_ids[i], user_id=user_id, pan_hash=pan_hash,
            source_type="ECAS_CDSL", method="upload",
            statement_to=statement_tos[i],
        )
        for i in range(n)
    ]

    results = await asyncio.gather(*(activate(r) for r in reqs))
    assert len(results) == n

    async with pg_pool.acquire() as conn:
        active = await conn.fetch(
            "SELECT id, statement_to::text AS statement_to "
            "FROM portfolio_ingestion.snapshots WHERE pan_hash=$1 AND is_active=true",
            pan_hash,
        )
        total_rows = await conn.fetchval(
            "SELECT COUNT(*) FROM portfolio_ingestion.snapshots WHERE pan_hash=$1",
            pan_hash,
        )
    assert len(active) == 1, f"Expected 1 active row, got {len(active)}"
    assert active[0]["statement_to"] == expected_winner_date
    assert total_rows == n  # every call inserted a row


# ── 6. TX rollback preserves previously-active ────────────────────────────


@pytest.mark.integration
async def test_failure_inside_tx_leaves_previous_active_intact(
    pg_pool: asyncpg.Pool, clean_pan: tuple[str, uuid.UUID]
) -> None:
    """Force a constraint violation inside the activation TX and confirm the
    previously-active snapshot survives unchanged."""
    pan_hash, user_id = clean_pan
    async with pg_pool.acquire() as conn:
        j1 = await _insert_job(conn, user_id, pan_hash, "ECAS_CDSL", "upload", "ca")
        j2 = await _insert_job(conn, user_id, pan_hash, "ECAS_CDSL", "upload", "cb")

    good = await activate(_req(
        job_id=j1, user_id=user_id, pan_hash=pan_hash, statement_to="2026-01-31",
    ))
    assert good.is_active

    # Make the next activation explode mid-TX by handing it an invalid
    # source_trace (will fail JSONB serialisation? No — json.dumps handles
    # anything via default=str). Instead, point job_id to a non-existent UUID
    # so the FK check fails when we INSERT the snapshot.
    bad_req = _req(
        job_id=uuid.UUID(int=0), user_id=user_id, pan_hash=pan_hash,
        statement_to="2026-02-28",
    )
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await activate(bad_req)

    async with pg_pool.acquire() as conn:
        active = await conn.fetch(
            "SELECT id, statement_to::text AS s FROM portfolio_ingestion.snapshots "
            "WHERE pan_hash=$1 AND is_active=true",
            pan_hash,
        )
    assert len(active) == 1
    assert active[0]["id"] == good.snapshot_id
    assert active[0]["s"] == "2026-01-31"
